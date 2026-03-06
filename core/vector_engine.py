"""
Lumina Studio - Native Vector Engine (v2 - Chroma-aligned)

SVG to 3D mesh conversion using vector geometry operations.
Aligned with ChromaPrint3D's processing philosophy:

Pipeline:
    SVG → Parse Paths → Occlusion Clip → Match Colors → Run-Length Extrude
        → Silhouette Backing → (optional Double-sided) → Assemble Scene

Key changes from v1:
    - Per-shape reverse-order occlusion clipping (no "small feature" exemptions)
    - Per-unique-color recipe caching via LUT KDTree
    - Run-length layer extrusion (consecutive same-channel layers merged)
    - No micro Z-offset between overlapping colors on the same material
    - Output objects sorted by material ID for stable slicer ordering
"""

import os
import numpy as np
import time
import trimesh
from svgelements import SVG, Path, Shape
from shapely.geometry import Polygon, MultiPolygon
from shapely import affinity
from shapely.ops import unary_union
from shapely.strtree import STRtree

from config import PrinterConfig, ColorSystem

# Lazy import to avoid circular dependency at module load time
_LuminaImageProcessor = None
_VECTOR_PARSE_CLIP_CACHE = {}
_VECTOR_PARSE_CLIP_CACHE_MAX = 3


def _get_image_processor_class():
    global _LuminaImageProcessor
    if _LuminaImageProcessor is None:
        from core.image_processing import LuminaImageProcessor
        _LuminaImageProcessor = LuminaImageProcessor
    return _LuminaImageProcessor


class VectorProcessor:
    """
    Native vector processing engine for SVG files.

    Converts SVG directly to 3D meshes without rasterization,
    preserving vector precision.  Uses ChromaPrint3D-style
    occlusion clipping and run-length layer extrusion.

    Attributes:
        color_mode: Color system mode string forwarded to ColorSystem.
        img_processor: LuminaImageProcessor instance for LUT / KDTree access.
        sampling_precision: Curve approximation precision in mm.
    """

    def __init__(self, lut_path: str, color_mode: str):
        self.color_mode = color_mode
        print(f"[VECTOR] Initializing Native Vector Engine ({color_mode})...")

        ImageProcessor = _get_image_processor_class()
        self.img_processor = ImageProcessor(lut_path, color_mode)
        self.sampling_precision = 0.05  # mm
        self.last_stage_timings = {}

        print(f"[VECTOR] Initialized with {len(self.img_processor.ref_stacks)} LUT colors")

    # ── Public entry point ───────────────────────────────────────────────

    def svg_to_mesh(
        self,
        svg_path: str,
        target_width_mm: float,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        color_replacements: dict = None,
        progress_fn=None,
    ) -> trimesh.Scene:
        """Convert an SVG file to a trimesh Scene ready for 3MF export.

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            thickness_mm:     Backing (spacer) thickness in mm.
            structure_mode:   "Single-sided" or "Double-sided".
            color_replacements: Optional ``{hex: hex}`` replacement map.

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot, sorted
            by material ID.  Geometry names match slot names from the active
            ``ColorSystem`` configuration.
        """
        print(f"[VECTOR] Processing: {svg_path}")
        print(f"[VECTOR] Structure mode: {structure_mode}")
        stage_timings = {}
        t_total_start = time.perf_counter()

        # === Stage 1+2: Parse & Occlusion clip (with cache) ===
        cache_key = None
        cached_entry = None
        try:
            svg_abs = os.path.abspath(svg_path)
            svg_mtime = os.path.getmtime(svg_abs)
            cache_key = (
                svg_abs,
                round(float(target_width_mm), 4),
                round(float(self.sampling_precision), 4),
                svg_mtime,
            )
            cached_entry = _VECTOR_PARSE_CLIP_CACHE.get(cache_key)
        except Exception:
            cache_key = None

        if cached_entry is not None:
            shape_data = cached_entry["shape_data"]
            clipped_shapes = cached_entry["clipped_shapes"]
            silhouette = cached_entry["silhouette"]
            scale_factor = cached_entry["scale_factor"]
            bbox = cached_entry["bbox"]
            stage_timings["parse_s"] = 0.0
            stage_timings["occlusion_s"] = 0.0
            print(f"[VECTOR] Parse/clip cache hit: {os.path.basename(svg_path)}")
            print(f"[VECTOR] Parsed {len(shape_data)} shapes. Scale: {scale_factor:.4f}")
            print(f"[VECTOR] After occlusion clip: {len(clipped_shapes)} non-overlapping shapes")
        else:
            t0 = time.perf_counter()
            shape_data, scale_factor, bbox = self._parse_svg(svg_path, target_width_mm)
            if not shape_data:
                raise ValueError("No valid filled shapes found in SVG.")
            stage_timings["parse_s"] = time.perf_counter() - t0
            print(f"[VECTOR] Parsed {len(shape_data)} shapes. Scale: {scale_factor:.4f}")

            t0 = time.perf_counter()
            clipped_shapes, silhouette = self._clip_occlusion(shape_data, return_silhouette=True)
            stage_timings["occlusion_s"] = time.perf_counter() - t0
            print(f"[VECTOR] After occlusion clip: {len(clipped_shapes)} non-overlapping shapes")

            if cache_key is not None:
                _VECTOR_PARSE_CLIP_CACHE[cache_key] = {
                    "shape_data": shape_data,
                    "clipped_shapes": clipped_shapes,
                    "silhouette": silhouette,
                    "scale_factor": scale_factor,
                    "bbox": bbox,
                }
                while len(_VECTOR_PARSE_CLIP_CACHE) > _VECTOR_PARSE_CLIP_CACHE_MAX:
                    _VECTOR_PARSE_CLIP_CACHE.pop(next(iter(_VECTOR_PARSE_CLIP_CACHE)))

        # === Stage 3: Resolve color system config ===
        is_six_color = len(self.img_processor.lut_rgb) == 1296
        if is_six_color:
            print("[VECTOR] Auto-detected 6-Color LUT. Forcing 6-Color mode.")
            color_conf = ColorSystem.SIX_COLOR
            self.color_mode = "6-Color"
        else:
            color_conf = ColorSystem.get(self.color_mode)

        slot_names = color_conf["slots"]
        preview_colors = color_conf["preview"]
        num_channels = len(slot_names)
        num_layers = color_conf.get('layer_count', PrinterConfig.COLOR_LAYERS)

        # === Stage 4: Match fill colors to LUT recipes ===
        replacement_manager = None
        if color_replacements:
            try:
                from core.color_replacement import ColorReplacementManager
                replacement_manager = ColorReplacementManager.from_dict(color_replacements)
            except Exception as e:
                print(f"[VECTOR] Warning: Failed to load color replacements: {e}")

        t0 = time.perf_counter()
        matched_shapes = self._match_colors(clipped_shapes, replacement_manager, num_channels, num_layers=num_layers)
        stage_timings["color_match_s"] = time.perf_counter() - t0
        print(f"[VECTOR] Matched {len(matched_shapes)} shapes to LUT recipes")

        # === Stage 5: Run-length extrude per channel ===
        layer_h = PrinterConfig.LAYER_HEIGHT
        extrude_cache = {}
        is_5color = "5-Color Extended" in self.color_mode
        backing_layer_count = max(1, int(round(thickness_mm / layer_h)))
        backing_height = backing_layer_count * layer_h

        t0 = time.perf_counter()
        if is_5color:
            # Face-up: reversed optical layers stacked above the backing
            meshes_by_slot = self._run_length_extrude(
                matched_shapes, num_layers, layer_h, num_channels,
                slot_names, scale_factor, extrude_cache=extrude_cache,
                face_up=True, optical_z_base=backing_height,
            )
            print(f"[VECTOR] 5-Color face-up: {num_layers} optical layers above {backing_height:.2f}mm backing")
        else:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes, num_layers, layer_h, num_channels,
                slot_names, scale_factor, extrude_cache=extrude_cache,
            )
        stage_timings["extrude_bottom_s"] = time.perf_counter() - t0

        # === Stage 6: Backing layer from silhouette ===
        t0 = time.perf_counter()
        if silhouette is None and clipped_shapes:
            # Defensive fallback if union accumulation failed in occlusion stage.
            all_geoms = [
                s["geometry"]
                for s in clipped_shapes
                if s["geometry"] is not None and not s["geometry"].is_empty
            ]
            silhouette = unary_union(all_geoms) if all_geoms else None

        if is_5color:
            backing_z_start = 0  # face-up: backing at print-bed level
        else:
            backing_z_start = num_layers * layer_h

        if thickness_mm > 0 and silhouette is not None and not silhouette.is_empty:
            print(f"[VECTOR] Generating backing: {backing_layer_count} layers ({thickness_mm}mm)")
            backing_meshes = []
            backing_height = backing_layer_count * layer_h
            backing_meshes.extend(
                self._extrude_geometry(silhouette, height=backing_height,
                                       z_offset=backing_z_start, scale=scale_factor,
                                       extrude_cache=extrude_cache)
            )
            if backing_meshes:
                backing_name = "Board"
                if backing_name not in meshes_by_slot:
                    meshes_by_slot[backing_name] = {"meshes": [], "mat_id": 0}
                meshes_by_slot[backing_name]["meshes"].extend(backing_meshes)
        stage_timings["backing_s"] = time.perf_counter() - t0

        # === Stage 7: Double-sided structure ===
        t0 = time.perf_counter()
        is_double_sided = "双面" in structure_mode or "Double" in structure_mode
        if is_double_sided:
            print("[VECTOR] Adding mirrored color layers (double-sided mode)...")
            top_z_start = backing_z_start + backing_layer_count * layer_h
            self._add_double_sided_layers(
                matched_shapes, num_layers, layer_h, num_channels,
                slot_names, scale_factor, top_z_start, meshes_by_slot,
                extrude_cache=extrude_cache,
            )
        stage_timings["extrude_top_s"] = time.perf_counter() - t0

        # === Stage 8: Assemble scene (sorted by material ID) ===
        t0 = time.perf_counter()
        scene = trimesh.Scene()
        svg_height_mm = bbox[3] * scale_factor

        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])

        for name, data in sorted_items:
            mesh_list = data["meshes"]
            mat_id = data["mat_id"]
            if not mesh_list:
                continue

            print(f"[VECTOR] Merging {len(mesh_list)} parts for {name}...")
            combined = (
                trimesh.util.concatenate(mesh_list) if len(mesh_list) > 1 else mesh_list[0]
            )
            self._fix_coordinates(combined, svg_height_mm)

            color_val = preview_colors.get(mat_id, [255, 255, 255, 255])
            combined.visual.face_colors = color_val
            combined.metadata["name"] = name
            scene.add_geometry(combined, geom_name=name)

        stage_timings["assemble_s"] = time.perf_counter() - t0
        stage_timings["total_s"] = time.perf_counter() - t_total_start
        stage_timings["extrude_cache_entries"] = len(extrude_cache)
        self.last_stage_timings = stage_timings

        print(
            "[VECTOR] Stage timings (s): "
            f"parse={stage_timings['parse_s']:.3f}, "
            f"clip={stage_timings['occlusion_s']:.3f}, "
            f"match={stage_timings['color_match_s']:.3f}, "
            f"extrude_bottom={stage_timings['extrude_bottom_s']:.3f}, "
            f"backing={stage_timings['backing_s']:.3f}, "
            f"extrude_top={stage_timings['extrude_top_s']:.3f}, "
            f"assemble={stage_timings['assemble_s']:.3f}, "
            f"total={stage_timings['total_s']:.3f}"
        )
        print(f"[VECTOR] Extrude cache entries: {stage_timings['extrude_cache_entries']}")
        print(f"[VECTOR] Scene complete: {len(scene.geometry)} objects")
        return scene

    # ── Stage 2: Occlusion clipping (Chroma-style) ───────────────────────

    @staticmethod
    def _clip_occlusion(shape_data, return_silhouette=False):
        """Clip shapes so no two overlap in XY.

        Iterates in reverse draw order (topmost first).  Each shape is
        subtracted from the accumulated union so that lower shapes only
        retain geometry not already covered by higher shapes.

        This mirrors ``ChromaPrint3D::detail::ClipOcclusion``.
        """
        n = len(shape_data)
        if n == 0:
            return ([], None) if return_silhouette else []

        valid = []
        for i, item in enumerate(shape_data):
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue
            valid.append((i, geom))

        if not valid:
            return ([], None) if return_silhouette else []

        orders = [v[0] for v in valid]
        geoms = [v[1] for v in valid]
        tree = STRtree(geoms)
        geom_id_to_idx = {id(g): idx for idx, g in enumerate(geoms)}
        result = []

        for i in range(n - 1, -1, -1):
            item = shape_data[i]
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue

            occluders = []
            try:
                candidate_refs = tree.query(geom)
            except Exception:
                candidate_refs = []

            for ref in candidate_refs:
                if isinstance(ref, (int, np.integer)):
                    idx = int(ref)
                else:
                    idx = geom_id_to_idx.get(id(ref), -1)
                if idx < 0:
                    continue
                if orders[idx] <= i:
                    continue
                cand = geoms[idx]
                try:
                    if cand.intersects(geom):
                        occluders.append(cand)
                except Exception:
                    continue

            if not occluders:
                clipped = geom
            else:
                try:
                    clipped = geom.difference(occluders[0] if len(occluders) == 1 else unary_union(occluders))
                except Exception:
                    clipped = geom

            if clipped is not None and not clipped.is_empty:
                if not clipped.is_valid:
                    clipped = clipped.buffer(0)
                if not clipped.is_empty:
                    result.append({
                        "geometry": clipped,
                        "color": item["color"],
                        "draw_order": i,
                    })

        result.reverse()
        if return_silhouette:
            try:
                silhouette = unary_union(geoms)
            except Exception:
                silhouette = None
            return result, silhouette
        return result

    # ── Stage 4: Color matching with per-color cache ─────────────────────

    def _match_colors(self, clipped_shapes, replacement_manager, num_channels, num_layers=None):
        """Match each shape's fill colour to a LUT recipe.

        Identical fill colours share a single KDTree lookup via a cache,
        mirroring ``ChromaPrint3D::VectorRecipeMap::Match`` behaviour.

        Returns a list of dicts: ``{geometry, recipe, color}``.
        """
        if num_layers is None:
            num_layers = PrinterConfig.COLOR_LAYERS
        recipe_log_mode = os.getenv("LUMINA_VECTOR_RECIPE_LOG", "summary").strip().lower()
        color_cache = {}
        matched = []
        sample_logs = []

        for item in clipped_shapes:
            rgb = item["color"]

            if rgb in color_cache:
                recipe = color_cache[rgb]
            else:
                query_lab = self.img_processor._rgb_to_lab(np.array([rgb], dtype=np.uint8))
                _, index = self.img_processor.kdtree.query(query_lab)
                lut_idx = index[0]

                if replacement_manager is not None:
                    matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[lut_idx])
                    replacement = replacement_manager.get_replacement(matched_rgb)
                    if replacement is not None:
                        rep_lab = self.img_processor._rgb_to_lab(
                            np.array([replacement], dtype=np.uint8)
                        )
                        _, rep_index = self.img_processor.kdtree.query(rep_lab)
                        lut_idx = rep_index[0]

                stack = self.img_processor.ref_stacks[lut_idx]
                recipe = [
                    min(int(stack[z]), num_channels - 1)
                    for z in range(min(num_layers, len(stack)))
                ]
                color_cache[rgb] = recipe

                hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                if recipe_log_mode == "full":
                    print(f"  {hex_c} -> recipe {recipe}")
                elif recipe_log_mode == "summary" and len(sample_logs) < 8:
                    sample_logs.append(f"{hex_c} -> {recipe}")

            matched.append({
                "geometry": item["geometry"],
                "recipe": recipe,
                "color": rgb,
            })

        if recipe_log_mode == "summary":
            print(f"[VECTOR] Recipe cache summary: unique_colors={len(color_cache)}, shapes={len(clipped_shapes)}")
            if sample_logs:
                print(f"[VECTOR] Recipe samples: {'; '.join(sample_logs)}")

        return matched

    # ── Stage 5: Run-length extrusion ────────────────────────────────────

    @staticmethod
    def _build_channel_runs(recipe, layers_to_use, num_channels):
        """Build contiguous layer runs grouped by channel.

        Returns:
            dict[channel_id] -> list of (start_layer, end_layer)
        """
        runs_by_channel = {}
        if layers_to_use <= 0:
            return runs_by_channel

        run_start = 0
        run_channel = int(recipe[0])
        for z in range(1, layers_to_use + 1):
            current_channel = int(recipe[z]) if z < layers_to_use else None
            if current_channel != run_channel:
                if 0 <= run_channel < num_channels:
                    runs_by_channel.setdefault(run_channel, []).append((run_start, z - 1))
                run_start = z
                run_channel = current_channel

        return runs_by_channel

    @staticmethod
    def _run_length_extrude(matched_shapes, num_layers, layer_h,
                            num_channels, slot_names, scale_factor,
                            extrude_cache=None, face_up=False, optical_z_base=0.0):
        """Extrude each shape per channel, merging consecutive same-channel
        layers into single volumes (run-length encoding).

        When *face_up* is True the layer order is reversed so that
        recipe[N-1] sits at the lowest Z (just above *optical_z_base*)
        and recipe[0] at the highest Z — matching ``_build_voxel_matrix_faceup``
        semantics used by the raster path for 5-Color Extended.
        """
        meshes_by_slot = {}

        for item in matched_shapes:
            geom = item["geometry"]
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                continue

            layers_to_use = min(num_layers, len(recipe))

            runs_by_channel = VectorProcessor._build_channel_runs(
                recipe, layers_to_use, num_channels
            )
            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    continue

                slot_name = slot_names[ch]
                if slot_name not in meshes_by_slot:
                    meshes_by_slot[slot_name] = {"meshes": [], "mat_id": ch}

                for run_start, run_end in runs:
                    if face_up:
                        inv_start = (num_layers - 1) - run_end
                        inv_end = (num_layers - 1) - run_start
                        z_bot = optical_z_base + inv_start * layer_h
                        height = (inv_end - inv_start + 1) * layer_h
                    else:
                        z_bot = run_start * layer_h
                        height = (run_end - run_start + 1) * layer_h
                    new_meshes = VectorProcessor._extrude_geometry(
                        geom, height=height, z_offset=z_bot, scale=scale_factor,
                        extrude_cache=extrude_cache,
                    )
                    meshes_by_slot[slot_name]["meshes"].extend(new_meshes)

        return meshes_by_slot

    # ── Stage 7: Double-sided helper ─────────────────────────────────────

    @staticmethod
    def _add_double_sided_layers(matched_shapes, num_layers, layer_h,
                                  num_channels, slot_names, scale_factor,
                                  top_z_start, meshes_by_slot, extrude_cache=None):
        """Mirror colour layers above the backing for double-sided mode.

        Layer Z order is inverted so the viewing surface faces upward on
        the top side.
        """
        for item in matched_shapes:
            geom = item["geometry"]
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                continue

            layers_to_use = min(num_layers, len(recipe))

            runs_by_channel = VectorProcessor._build_channel_runs(
                recipe, layers_to_use, num_channels
            )
            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    continue

                slot_name = slot_names[ch]
                if slot_name not in meshes_by_slot:
                    meshes_by_slot[slot_name] = {"meshes": [], "mat_id": ch}

                for run_start, run_end in runs:
                    inv_start = (num_layers - 1) - run_end
                    inv_end = (num_layers - 1) - run_start

                    z_bot = top_z_start + inv_start * layer_h
                    height = (inv_end - inv_start + 1) * layer_h
                    new_meshes = VectorProcessor._extrude_geometry(
                        geom, height=height, z_offset=z_bot, scale=scale_factor,
                        extrude_cache=extrude_cache,
                    )
                    meshes_by_slot[slot_name]["meshes"].extend(new_meshes)

    # ── SVG parsing ──────────────────────────────────────────────────────

    def _parse_svg(self, svg_path: str, target_width_mm: float):
        """Parse SVG and return shapes in draw order with normalised coords.

        Returns:
            ``(shape_list, scale_factor, bbox_tuple)``
            where each shape item is ``{'poly': Polygon, 'color': (r,g,b)}``.
        """
        try:
            svg = SVG.parse(svg_path)
        except Exception as e:
            raise ValueError(f"Failed to parse SVG: {e}")

        def _sample_path_to_polygon(path_obj):
            path_len = path_obj.length()
            if path_len == 0:
                return None

            # Adaptive sampling: coarser for larger precision settings.
            sample_step_svg = max(0.5, min(4.0, self.sampling_precision * 20.0))
            num_points = max(10, min(int(path_len / sample_step_svg), 1200))
            t_vals = np.linspace(0, 1, num_points)
            pts = [path_obj.point(t) for t in t_vals]

            if len(pts) < 3:
                return None

            poly = Polygon([(p.x, p.y) for p in pts])
            if not poly.is_valid:
                poly = poly.buffer(0)

            if poly.is_valid and not poly.is_empty:
                return poly
            return None

        raw_shapes = []
        print("[VECTOR] Parsing SVG geometry...")

        for element in svg.elements():
            if not isinstance(element, (Path, Shape)):
                continue
            if element.fill is None or element.fill.value is None:
                continue

            rgb = (element.fill.red, element.fill.green, element.fill.blue)

            if isinstance(element, Shape) and not isinstance(element, Path):
                try:
                    element = Path(element)
                except Exception:
                    continue

            sampled_any = False
            try:
                subpaths = list(element.as_subpaths())
            except Exception:
                subpaths = []

            # Parse subpaths independently to avoid "bridging" disjoint contours
            # into one invalidly large polygon.
            for subpath in subpaths:
                try:
                    sub_path = subpath if isinstance(subpath, Path) else Path(subpath)
                    poly = _sample_path_to_polygon(sub_path)
                except Exception:
                    continue
                if poly is None:
                    continue
                raw_shapes.append({"poly": poly, "color": rgb})
                sampled_any = True

            if sampled_any:
                continue

            # Fallback for compatibility if subpath splitting is unavailable
            # or yields no valid polygon.
            try:
                poly = _sample_path_to_polygon(element)
                if poly is not None:
                    raw_shapes.append({"poly": poly, "color": rgb})
            except Exception:
                continue

        if not raw_shapes:
            raise ValueError("No valid shapes found in SVG")

        # Global bounding box
        min_xs, min_ys, max_xs, max_ys = [], [], [], []
        for item in raw_shapes:
            bx0, by0, bx1, by1 = item["poly"].bounds
            min_xs.append(bx0)
            min_ys.append(by0)
            max_xs.append(bx1)
            max_ys.append(by1)

        gx0, gy0 = min(min_xs), min(min_ys)
        real_w = max(max_xs) - gx0
        real_h = max(max_ys) - gy0

        print(f"[VECTOR] Global bounds: x={gx0:.1f}, y={gy0:.1f}, w={real_w:.1f}, h={real_h:.1f}")
        if real_w == 0:
            raise ValueError("Invalid geometry width (0)")

        scale_factor = target_width_mm / real_w
        simplify_tol_svg = max(0.0, (self.sampling_precision / max(scale_factor, 1e-9)) * 0.5)
        min_area_svg = max(0.0, (self.sampling_precision ** 2) / max(scale_factor ** 2, 1e-12) * 0.25)

        final_shapes = []
        for item in raw_shapes:
            shifted = affinity.translate(item["poly"], xoff=-gx0, yoff=-gy0)
            if simplify_tol_svg > 0.0:
                try:
                    shifted = shifted.simplify(simplify_tol_svg, preserve_topology=True)
                except Exception:
                    pass

            if not shifted.is_valid:
                shifted = shifted.buffer(0)

            if shifted.is_empty or shifted.area <= min_area_svg:
                continue
            final_shapes.append({"poly": shifted, "color": item["color"]})

        return final_shapes, scale_factor, (gx0, gy0, real_w, real_h)

    # ── Geometry helpers ─────────────────────────────────────────────────

    @staticmethod
    def _extrude_geometry(geometry, height, z_offset, scale, extrude_cache=None):
        """Extrude 2D Shapely geometry to 3D trimesh objects."""
        meshes = []
        if geometry is None or geometry.is_empty:
            return meshes

        polys = geometry.geoms if hasattr(geometry, "geoms") else [geometry]

        for poly in polys:
            if poly.is_empty:
                continue
            if not hasattr(poly, "exterior"):
                continue
            try:
                cache_key = None
                cached_base = None
                if extrude_cache is not None:
                    # Key excludes height: cache unit-height (h=1) base mesh,
                    # then scale Z per call. Avoids re-triangulating the same
                    # polygon when it appears in multiple layers at different heights.
                    cache_key = (poly.wkb, round(float(scale), 8))
                    cached_base = extrude_cache.get(cache_key)

                if cached_base is None:
                    m_base = trimesh.creation.extrude_polygon(poly, height=1.0)
                    m_base.apply_scale([scale, scale, 1.0])
                    if extrude_cache is not None and cache_key is not None:
                        extrude_cache[cache_key] = m_base.copy()
                else:
                    m_base = cached_base

                m = m_base.copy()
                m.apply_scale([1.0, 1.0, float(height)])
                m.apply_translation([0, 0, z_offset])
                meshes.append(m)
            except Exception as e:
                print(f"[VECTOR] Warning: Failed to extrude polygon: {e}")
                continue

        return meshes

    @staticmethod
    def _fix_coordinates(mesh, svg_height_mm):
        """Flip Y-axis from SVG (Y-down) to printer (Y-up) coordinate system."""
        transform = np.eye(4)
        transform[1, 1] = -1
        mesh.apply_transform(transform)
        mesh.apply_translation([0, svg_height_mm, 0])

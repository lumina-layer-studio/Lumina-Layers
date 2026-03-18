# -*- coding: utf-8 -*-
"""Step 8: 附加 Mesh（backing / wire / free color / loop / coating / outline）"""

from __future__ import annotations

from core.pipeline import PipelineContext, PipelineStep
from config import PrinterConfig
from core.geometry_utils import create_keychain_loop


class AddonMeshStep(PipelineStep):
    """生成附加 mesh：backing、cloisonné wire、free color、loop、coating、outline。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.outline_mesh import generate_outline_mesh
        from core.processing.backing_mesh import generate_backing_mesh
        from core.processing.wire_mesh import generate_wire_mesh
        from core.processing.free_color_mesh import extract_free_color_meshes
        from core.processing.coating_mesh import generate_coating_mesh

        p = ctx.params
        scene = ctx['scene']
        mesher = ctx['mesher']
        transform = ctx['transform']
        full_matrix = ctx['full_matrix']
        target_h = ctx['target_h']
        target_w = ctx['target_w']
        mask_solid = ctx['mask_solid']
        matched_rgb = ctx['matched_rgb']
        pixel_scale = ctx['pixel_scale']
        preview_colors = ctx['preview_colors']
        valid_slot_names = ctx['valid_slot_names']
        backing_metadata = ctx['backing_metadata']
        total_layers = ctx['total_layers']
        separate_backing = ctx['separate_backing']

        enable_cloisonne = p.get('enable_cloisonne', False)
        enable_coating = p.get('enable_coating', False)
        coating_height_mm = p.get('coating_height_mm', 0.08)
        enable_outline = p.get('enable_outline', False)
        outline_width = p.get('outline_width', 2.0)
        free_color_set = p.get('free_color_set')

        # --- Separate Backing ---
        if separate_backing:
            backing_mesh = generate_backing_mesh(
                mesher=mesher, full_matrix=full_matrix,
                target_h=target_h, transform=transform,
                preview_colors=preview_colors,
            )
            if backing_mesh is not None:
                scene.add_geometry(backing_mesh, node_name="Backing", geom_name="Backing")
                valid_slot_names.append("Backing")
        else:
            print(f"[CONVERTER] Backing merged with first layer (original behavior)")

        # --- Cloisonné Wire ---
        if enable_cloisonne and backing_metadata.get('is_cloisonne'):
            wire_mesh = generate_wire_mesh(
                mesher=mesher, full_matrix=full_matrix,
                target_h=target_h, transform=transform,
            )
            if wire_mesh is not None:
                scene.add_geometry(wire_mesh, node_name="Wire", geom_name="Wire")
                valid_slot_names.append("Wire")

        # --- Free Color ---
        if free_color_set:
            fc_results = extract_free_color_meshes(
                free_color_set=free_color_set,
                matched_rgb=matched_rgb, mask_solid=mask_solid,
                full_matrix=full_matrix, target_h=target_h,
                mesher=mesher, transform=transform,
            )
            for fc in fc_results:
                scene.add_geometry(fc.mesh, node_name=fc.name, geom_name=fc.name)
                valid_slot_names.append(fc.name)

        # --- Keychain Loop ---
        loop_info = ctx.get('loop_info')
        add_loop = p.get('add_loop', False)
        loop_added = False

        if add_loop and loop_info is not None:
            try:
                loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT
                loop_mesh = create_keychain_loop(
                    width_mm=loop_info['width_mm'],
                    length_mm=loop_info['length_mm'],
                    hole_dia_mm=loop_info['hole_dia_mm'],
                    thickness_mm=loop_thickness,
                    attach_x_mm=loop_info['attach_x_mm'],
                    attach_y_mm=loop_info['attach_y_mm'],
                )
                if loop_mesh is not None:
                    loop_mesh.visual.face_colors = preview_colors[loop_info['color_id']]
                    loop_mesh.metadata['name'] = "Keychain_Loop"
                    scene.add_geometry(loop_mesh, node_name="Keychain_Loop", geom_name="Keychain_Loop")
                    valid_slot_names.append("Keychain_Loop")
                    loop_added = True
                    print(f"[CONVERTER] Loop added successfully")
            except Exception as e:
                print(f"[CONVERTER] Loop creation failed: {e}")

        ctx['loop_added'] = loop_added

        # --- Coating ---
        if enable_coating:
            coating_mesh = generate_coating_mesh(
                mask_solid=mask_solid, target_h=target_h, target_w=target_w,
                pixel_scale=pixel_scale, coating_height_mm=coating_height_mm,
                mesher=mesher, enable_outline=enable_outline,
                outline_width=outline_width,
            )
            if coating_mesh is not None:
                scene.add_geometry(coating_mesh, node_name="Coating", geom_name="Coating")
                valid_slot_names.append("Coating")

        # --- Outline ---
        outline_added = False
        if enable_outline:
            try:
                outline_thickness_mm = total_layers * PrinterConfig.LAYER_HEIGHT
                outline_z_offset = 0.0
                if enable_coating:
                    c_layers = max(1, int(round(coating_height_mm / PrinterConfig.LAYER_HEIGHT)))
                    coating_mm = c_layers * PrinterConfig.LAYER_HEIGHT
                    outline_thickness_mm += coating_mm
                    outline_z_offset = -coating_mm
                    print(f"[CONVERTER] 🔲 Outline extended to cover coating: total_thickness={outline_thickness_mm}mm")

                print(f"[CONVERTER] 🔲 Generating outline: width={outline_width}mm, "
                      f"thickness={outline_thickness_mm}mm (z_offset={outline_z_offset}mm)")

                outline_mesh = generate_outline_mesh(
                    mask_solid=mask_solid, pixel_scale=pixel_scale,
                    outline_width_mm=outline_width,
                    outline_thickness_mm=outline_thickness_mm,
                    target_h=target_h,
                )
                if outline_mesh is not None:
                    if outline_z_offset != 0.0:
                        outline_mesh.vertices[:, 2] += outline_z_offset
                    outline_mesh.visual.face_colors = preview_colors[0]
                    outline_name = "Outline"
                    outline_mesh.metadata['name'] = outline_name
                    scene.add_geometry(outline_mesh, node_name=outline_name, geom_name=outline_name)
                    valid_slot_names.append(outline_name)
                    outline_added = True
                    print(f"[CONVERTER] ✅ Outline added as standalone object")
                else:
                    print(f"[CONVERTER] Warning: Outline mesh is empty, skipping")
            except Exception as e:
                print(f"[CONVERTER] Outline generation failed: {e}")
                import traceback; traceback.print_exc()

        ctx['outline_added'] = outline_added
        ctx['valid_slot_names'] = valid_slot_names

        return ctx

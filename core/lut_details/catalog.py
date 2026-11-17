"""Catalog indexing for LUT details.
LUT 详情目录索引。
"""

from __future__ import annotations

from dataclasses import dataclass
import glob
from pathlib import Path
import re
import time
from typing import Any

from core.filament_display import filament_display
from core.lut_board_preview import lut_board_preview
from core.lut_details.aliases import AliasResolver, normalize_lookup_token
from core.lut_details.parser import LutParser, ParsedLut


_ALLOWED_EXTENSIONS = (".json", ".msgpack", ".npz", ".npy")
_EXT_PRIORITY = {".npy": 0, ".npz": 1, ".json": 2, ".msgpack": 3}
_MODE_FOLDER_TOKENS = {
    "bw",
    "2色",
    "4色",
    "5色",
    "6色",
    "8色",
    "4-color",
    "5-color",
    "6-color",
    "8-color",
}


@dataclass(frozen=True)
class LutCatalogItemSummary:
    """Indexed summary for one LUT details entry.
    单个 LUT 详情条目的索引摘要。
    """

    name: str
    path: str
    color_mode: str
    source_kind: str
    compatibility_key: str
    manufacturer: str
    material_type: str
    manufacturer_source: str
    material_source: str
    search_tokens: tuple[str, ...]
    revision: str = ""
    display: dict[str, Any] | None = None


@dataclass(frozen=True)
class LutCatalogGroupSummary:
    """Grouped LUT details catalog bucket.
    分组后的 LUT 详情目录桶。
    """

    manufacturer: str
    items: tuple[LutCatalogItemSummary, ...]


@dataclass(frozen=True)
class LutDetailsCatalog:
    """Grouped LUT details catalog result.
    分组后的 LUT 详情目录结果。
    """

    groups: tuple[LutCatalogGroupSummary, ...]


@dataclass(frozen=True)
class ResolvedLutIdentity:
    """Resolved manufacturer/material identity for one LUT.
    单个 LUT 的厂商/材质解析结果。
    """

    manufacturer: str
    manufacturer_source: str
    manufacturer_raw: str
    material_type: str
    material_source: str
    material_raw: str


class LutCatalogIndexer:
    """Index LUT files into a manufacturer-grouped details catalog.
    将 LUT 文件索引为按厂商分组的详情目录。

    Args:
        preset_dir: Root preset directory. (预设根目录)
        alias_resolver: Alias resolver. (别名解析器)
        parser: LUT parser. (LUT 解析器)
        additional_roots: Named external writable roots. 命名的外部可写目录。
    """

    CATALOG_SIGNATURE_TTL_SECONDS = 5.0

    def __init__(
        self,
        *,
        preset_dir: Path,
        alias_resolver: AliasResolver,
        parser: LutParser,
        additional_roots: tuple[tuple[str, Path], ...] = (),
    ) -> None:
        self._preset_dir = Path(preset_dir).resolve()
        self._scan_roots = self._normalize_scan_roots(additional_roots)
        self._alias_resolver = alias_resolver
        self._parser = parser
        self._candidate_cache: dict[str, tuple[Path, ...]] | None = None
        self._resolved_path_cache: dict[str, Path] = {}
        self._resolved_path_signature_cache: dict[str, tuple[int, int]] = {}
        self._catalog_cache_checked_at: float | None = None
        self._catalog_cache_value: LutDetailsCatalog | None = None

    def build_catalog(self) -> LutDetailsCatalog:
        """Build the manufacturer-grouped details catalog.
        构建按厂商分组的详情目录。

        Returns:
            LutDetailsCatalog: Indexed catalog. (索引后的目录)
        """

        now = time.monotonic()
        if (
            self._catalog_cache_value is not None
            and self._catalog_cache_checked_at is not None
            and now - self._catalog_cache_checked_at <= self.CATALOG_SIGNATURE_TTL_SECONDS
        ):
            return self._catalog_cache_value

        candidates_by_name = self._discover_file_candidates(refresh=True)
        revision = str(time.monotonic_ns())
        grouped: dict[str, list[LutCatalogItemSummary]] = {}
        resolved_paths: dict[str, Path] = {}
        resolved_signatures: dict[str, tuple[int, int]] = {}
        parse_failure_count = 0
        for name, candidates in candidates_by_name.items():
            parsed: ParsedLut | None = None
            resolved_path: Path | None = None
            for path in candidates:
                try:
                    parsed = self._parser.parse(name=name, path=path)
                    resolved_path = path
                    break
                except Exception:
                    parse_failure_count += 1
                    continue
            if parsed is None or resolved_path is None:
                continue
            resolved_paths[name] = resolved_path
            resolved_signatures[name] = self._path_signature(resolved_path)
            identity = self.resolve_identity(resolved_path, parsed)
            tokens = self._build_item_search_tokens(parsed, identity)
            item = LutCatalogItemSummary(
                name=name,
                path=str(resolved_path),
                color_mode=parsed.color_mode,
                source_kind=parsed.source_kind,
                compatibility_key=parsed.compatibility_key,
                manufacturer=identity.manufacturer,
                material_type=identity.material_type,
                manufacturer_source=identity.manufacturer_source,
                material_source=identity.material_source,
                search_tokens=tuple(tokens),
                revision=revision,
                display={
                    **filament_display(parsed.raw_metadata), **filament_display(parsed.raw_metadata.get("display")),
                    **lut_board_preview(parsed.rgb, parsed.color_mode, parsed.raw_metadata),
                } or None,
            )
            grouped.setdefault(identity.manufacturer, []).append(item)

        groups = tuple(
            LutCatalogGroupSummary(
                manufacturer=manufacturer,
                items=tuple(sorted(items, key=lambda item: (item.material_type.casefold(), item.name.casefold()))),
            )
            for manufacturer, items in sorted(grouped.items(), key=lambda entry: entry[0].casefold())
        )
        if not groups and parse_failure_count > 0:
            raise RuntimeError("All discovered LUT detail files failed to parse")
        self._resolved_path_cache = resolved_paths
        self._resolved_path_signature_cache = resolved_signatures
        catalog = LutDetailsCatalog(groups=groups)
        self._catalog_cache_checked_at = now
        self._catalog_cache_value = catalog
        return catalog

    def find_path_by_name(self, name: str) -> Path | None:
        """Resolve one catalog display name to a file path.
        将单个目录显示名解析为文件路径。
        """

        cached_path = self._resolved_path_cache.get(name)
        if cached_path is not None:
            if cached_path.is_file() and self._resolved_path_signature_cache.get(name) == self._path_signature(cached_path):
                return cached_path
            self._resolved_path_cache.pop(name, None)
            self._resolved_path_signature_cache.pop(name, None)
            self._candidate_cache = None
            self._clear_catalog_cache()
        candidates = self._discover_file_candidates().get(name, ())
        had_existing_candidate = False
        for candidate in candidates:
            if not candidate.is_file():
                continue
            had_existing_candidate = True
            try:
                self._parser.parse(name=name, path=candidate)
                self._resolved_path_cache[name] = candidate
                self._resolved_path_signature_cache[name] = self._path_signature(candidate)
                return candidate
            except Exception:
                continue
        if had_existing_candidate:
            raise RuntimeError(f"LUT detail source exists but failed to parse: {name}")
        return None

    def resolve_identity(self, path: Path, parsed: ParsedLut) -> ResolvedLutIdentity:
        """Resolve canonical manufacturer/material with precedence rules.
        按优先级解析标准厂商/材质。
        """

        folder_vendor, folder_material = self._infer_from_folder(path)
        file_vendor, file_material = self._infer_from_filename(path)

        manufacturer_raw, manufacturer_source = self._first_non_empty(
            (parsed.metadata.manufacturer, "metadata"),
            (folder_vendor, "folder"),
            (file_vendor, "filename"),
            ("Unlabeled", "fallback"),
        )
        material_raw, material_source = self._first_non_empty(
            (parsed.metadata.type, "metadata"),
            (folder_material, "folder"),
            (file_material, "filename"),
            ("", "fallback"),
        )
        manufacturer = self._alias_resolver.canonicalize_manufacturer(manufacturer_raw) or "Unlabeled"
        material_type = self._alias_resolver.canonicalize_material(material_raw)
        return ResolvedLutIdentity(
            manufacturer=manufacturer,
            manufacturer_source=manufacturer_source,
            manufacturer_raw=manufacturer_raw,
            material_type=material_type,
            material_source=material_source,
            material_raw=material_raw,
        )

    def _clear_catalog_cache(self) -> None:
        self._catalog_cache_checked_at = None
        self._catalog_cache_value = None

    def _discover_file_candidates(self, *, refresh: bool = False) -> dict[str, tuple[Path, ...]]:
        if self._candidate_cache is not None and not refresh:
            return self._candidate_cache
        discovered: dict[str, list[Path]] = {}
        seen_paths: set[Path] = set()
        for _label, root in self._scan_roots:
            for ext in _ALLOWED_EXTENSIONS:
                for file_path in glob.glob(
                    str(root / "**" / f"*{ext}"),
                    recursive=True,
                ):
                    resolved = Path(file_path).resolve()
                    if not resolved.is_file() or resolved in seen_paths:
                        continue
                    virtual_parts = self._virtual_relative_parts(resolved)
                    if not virtual_parts or virtual_parts[0] == "_sync":
                        continue
                    seen_paths.add(resolved)
                    name = self._display_name_for_path(resolved)
                    discovered.setdefault(name, []).append(resolved)

        candidates = {
            name: tuple(
                sorted(
                    paths,
                    key=lambda path: _EXT_PRIORITY[path.suffix.lower()],
                    reverse=True,
                ),
            )
            for name, paths in discovered.items()
        }
        self._candidate_cache = dict(sorted(candidates.items(), key=lambda entry: entry[0].casefold()))
        return self._candidate_cache

    def _path_signature(self, path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except OSError:
            return (-1, -1)
        return (stat.st_mtime_ns, stat.st_size)

    def _display_name_for_path(self, path: Path) -> str:
        rel_parts = self._virtual_relative_parts(path)
        stem = path.stem
        if len(rel_parts) >= 2:
            return " - ".join([*rel_parts[:-1], stem])
        return stem

    def _infer_from_folder(self, path: Path) -> tuple[str, str]:
        rel_parts = self._identity_relative_parts(path)
        if len(rel_parts) < 2 or rel_parts[0] == "Custom":
            return "", ""
        vendor = str(rel_parts[0])
        material = ""
        if len(rel_parts) >= 3:
            second = str(rel_parts[1]).strip()
            if second.casefold() not in _MODE_FOLDER_TOKENS:
                material = second
        return vendor, material

    def _identity_relative_parts(self, path: Path) -> tuple[str, ...]:
        parts = self._virtual_relative_parts(path)
        # Cloud and revision directories describe storage, not manufacturers.
        if parts and parts[0] == "Cloud":
            parts = parts[1:]
        if parts and parts[0] == "_revisions":
            return (path.name,)
        return parts

    def _infer_from_filename(self, path: Path) -> tuple[str, str]:
        parts = path.stem.split("&")
        if len(parts) >= 2:
            vendor = parts[0].strip()
            for raw_material in (part.strip() for part in parts[1:] if part.strip()):
                canonical_material = self._alias_resolver.canonicalize_material(raw_material)
                if canonical_material != raw_material:
                    return vendor, canonical_material
                inferred_material = self._infer_material_from_stem(raw_material)
                if inferred_material:
                    return vendor, inferred_material
            return vendor, ""
        material = self._infer_material_from_stem(path.stem)
        underscore_parts = [part.strip() for part in Path(path).stem.split("_") if part.strip()]
        if len(underscore_parts) >= 2 and material:
            rel_parts = self._identity_relative_parts(path)
            if (
                len(rel_parts) >= 2
                and rel_parts[0] != "Custom"
                and underscore_parts[0].casefold() == str(rel_parts[0]).strip().casefold()
            ):
                return underscore_parts[0], material
        return "", material

    def _infer_material_from_stem(self, stem: str) -> str:
        tokens: list[str] = []
        whole_stem = normalize_lookup_token(stem)
        if whole_stem:
            tokens.append(whole_stem)
        tokens.extend(
            normalize_lookup_token(part)
            for part in re.split(r"[\s\-_&]+", stem)
            if normalize_lookup_token(part)
        )
        for canonical, aliases in self._alias_resolver.materials.items():
            candidates = [normalize_lookup_token(canonical), *(normalize_lookup_token(alias) for alias in aliases)]
            for candidate in candidates:
                if any(self._matches_material_candidate(token, candidate) for token in tokens):
                    return canonical
        return ""

    def _normalize_scan_roots(
        self,
        additional_roots: tuple[tuple[str, Path], ...],
    ) -> tuple[tuple[str, Path], ...]:
        roots: list[tuple[str, Path]] = [("Preset", self._preset_dir)]
        seen = {self._preset_dir}
        for raw_label, raw_root in additional_roots:
            label = str(raw_label).strip()
            root = Path(raw_root).resolve()
            if not label or root in seen:
                continue
            try:
                root.relative_to(self._preset_dir)
            except ValueError:
                pass
            else:
                continue
            roots.append((label, root))
            seen.add(root)
        return tuple(roots)

    def _virtual_relative_parts(self, path: Path) -> tuple[str, ...]:
        resolved = path.resolve()
        for label, root in self._scan_roots:
            try:
                relative = resolved.relative_to(root)
            except ValueError:
                continue
            if label == "Preset":
                return relative.parts
            return (label, *relative.parts)
        return ()

    @staticmethod
    def _matches_material_candidate(token: str, candidate: str) -> bool:
        if token == candidate:
            return True
        if token.startswith(candidate):
            remainder = token[len(candidate):]
            return bool(remainder) and not (remainder[0].isascii() and remainder[0].isalpha())
        return False

    def _build_item_search_tokens(self, parsed: ParsedLut, identity: ResolvedLutIdentity) -> list[str]:
        manufacturer_tokens = self._alias_resolver.build_search_tokens(
            canonical=identity.manufacturer,
            raw_values=[identity.manufacturer_raw],
            aliases=self._alias_resolver.aliases_for_manufacturer(identity.manufacturer),
        )
        material_tokens = self._alias_resolver.build_search_tokens(
            canonical=identity.material_type,
            raw_values=[identity.material_raw],
            aliases=self._alias_resolver.aliases_for_material(identity.material_type),
        )
        name_tokens = self._alias_resolver.build_search_tokens(
            canonical=parsed.name,
            raw_values=[parsed.path.name, parsed.path.stem],
        )
        seen: set[str] = set()
        ordered: list[str] = []
        for token in [*manufacturer_tokens, *material_tokens, *name_tokens]:
            if token and token not in seen:
                seen.add(token)
                ordered.append(token)
        return ordered

    @staticmethod
    def _first_non_empty(*candidates: tuple[str, str]) -> tuple[str, str]:
        for value, source in candidates:
            if str(value).strip():
                return str(value).strip(), source
        return "", "fallback"

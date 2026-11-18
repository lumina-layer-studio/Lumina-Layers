"""Small public identity and color previews shared by archives and catalogs."""

import re
from typing import Any
from urllib.parse import urlsplit

from core.lut_board_preview import published_lut_board


def _preview_rgb(value: object, *, bgr: bool = False) -> list[int] | None:
    if isinstance(value, dict):
        for key in ("hex_color", "hex", "rgb", "bgr"):
            if key in value:
                value = value[key]
                bgr = key == "bgr"
                break
    if isinstance(value, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
        raw = value.removeprefix("#")
        return [int(raw[i:i + 2], 16) for i in (0, 2, 4)]
    if isinstance(value, list) and len(value) == 3 and all(type(c) is int and 0 <= c <= 255 for c in value):
        return list(reversed(value)) if bgr else list(value)
    return None


def preview_step_indices(count: int, limit: int = 18) -> list[int]:
    """Choose actual ordered samples, keeping both endpoints."""
    if count <= limit:
        return list(range(count))
    return [round(index * (count - 1) / (limit - 1)) for index in range(limit)]


def filament_preview(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = published_lut_board(value.get("lut_board_preview"))
    swatches = value.get("preview_swatches")
    if isinstance(swatches, dict):
        black, white = swatches.get("black"), swatches.get("white")
        if isinstance(black, list) and isinstance(white, list) and len(white) == len(black) >= 2:
            sample = preview_step_indices(len(black))
            black_rgb = [_preview_rgb(black[index]) for index in sample]
            white_rgb = [_preview_rgb(white[index]) for index in sample]
            source = swatches.get("source")
            if source in ("measured", "model") and None not in black_rgb and None not in white_rgb:
                result["preview_swatches"] = {"source": source, "black": black_rgb, "white": white_rgb}
                depth = swatches.get("board_thickness_mm")
                if type(depth) in (int, float) and 0 < depth <= 34:
                    result["preview_swatches"]["board_thickness_mm"] = depth
    palette = value.get("palette_rgb")
    bgr = False
    if not isinstance(palette, list):
        palette = value.get("palette_bgr")
        bgr = isinstance(palette, list)
    if not isinstance(palette, list):
        palette = value.get("palette", value.get("channels"))
        order = value.get("ordered_channels")
        if isinstance(order, list):
            palette = [
                palette.get(slot, slot) if isinstance(slot, str) and isinstance(palette, dict) else slot
                for slot in order
            ]
        elif isinstance(palette, dict):
            palette = list(palette.values())
    if isinstance(palette, list) and palette:
        colors = [_preview_rgb(palette[i], bgr=bgr) for i in preview_step_indices(len(palette), 16)]
        if None not in colors:
            result["palette_rgb"] = colors
    return result


def catalog_thumbnail_metadata(item: dict[str, Any]) -> dict[str, Any]:
    """Project fields already in a public catalog entry. Never open its package."""
    row = dict(item)
    projected = filament_preview(item)
    preview_fields = ("preview_swatches", "palette_rgb", "lut_board_preview")
    for key in preview_fields:
        row.pop(key, None)
    for key in ("card_metadata", "compatibility", "display"):
        block = row.get(key)
        if not isinstance(block, dict):
            continue
        projected.update(filament_preview(block))
        if any(field in block for field in preview_fields):
            row[key] = {field: data for field, data in block.items() if field not in preview_fields}
    if projected:
        display = row.get("display")
        row["display"] = {**(display if isinstance(display, dict) else {}), **projected}
    return row


def _purchase_links(value: object) -> list[dict[str, str]]:
    """Keep public link fields only; credentials and non-web schemes never leave the archive."""
    result: list[dict[str, str]] = []
    if not isinstance(value, list):
        return result
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            continue
        url = row["url"].strip()
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        result.append({
            key: row[key].strip() for key in ("url", "label", "market") if isinstance(row.get(key), str)
        })
        if len(result) == 8:
            break
    return result


def filament_display(value: object) -> dict[str, Any]:
    """Project catalog display metadata without copying archive paths or calibration payloads."""
    if not isinstance(value, dict):
        return {}
    keys = (
        "brand", "manufacturer", "vendor", "material_name", "name", "display_name", "lut_name", "title",
        "material_type", "color_name", "market_names", "localized_names", "aliases",
        "sku", "color_code", "fila_color_code", "brand_identity",
        "series", "description", "contributor_name", "author", "license", "original_name",
        "purchase_links", "product_url", "purchase_url",
    )
    result = {**{key: value[key] for key in keys if key in value}, **filament_preview(value)}
    if "attribution" in value:
        from core.resource_attribution import normalize_attribution
        try:
            result["attribution"] = normalize_attribution(value["attribution"])
        except ValueError:
            pass  # Older malformed metadata cannot break local browsing.
    if "purchase_links" in result:
        result["purchase_links"] = _purchase_links(result["purchase_links"])
    filaments = value.get("filaments")
    if isinstance(filaments, list) and 0 < len(filaments) <= 16:
        slot_keys = (*keys, "slot", "material_id", "revision_id", "color_hex", "rgb")
        result["filaments"] = [
            {key: _purchase_links(row[key]) if key == "purchase_links" else row[key]
             for key in slot_keys if key in row}
            for row in filaments if isinstance(row, dict)
        ]
    return result

"""Prepare bundled logo presentation variants; keep the attributed originals intact.

Run with the project's Python environment. This is an asset maintenance command,
not a frontend build or runtime step.
"""

from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt


ASSETS = Path(__file__).resolve().parents[1] / "frontend/src/assets/filament-brands"
# Backgrounds are inspected source mattes, not inferred from an arbitrary upload.
MATTES = {
    "alchemakes": (255, 255, 255), "antinsky": (255, 255, 255),
    "anycubic": (238, 243, 250), "biqu": (255, 255, 255),
    "cailab": (255, 255, 255), "ching-leung": (255, 255, 255),
    "inslogic": (0, 0, 0), "jayo": (255, 255, 255),
    "karvax": (255, 255, 255), "kynix": (255, 255, 255),
    "rebirth3d": (0, 0, 0), "snapmaker": (0, 0, 0), "xyd": (255, 255, 255),
}
MONOCHROME = {"aliz", "antinsky", "biqu", "inslogic", "jayo", "kynix", "snapmaker"}
WHITE_WORDMARKS = {"inslogic", "snapmaker"}
# Low-value blue/green inks need a lighter version on dark surfaces. Their hue
# and colored-vs-neutral regions stay intact; this is not whole-image inversion.
DARK_COLOR_WORDMARKS = {"anycubic", "bing3d", "elegoo", "esun", "xyd"}
SHARED_THEME = {"ching-leung", "kexcelled", "sunlu"}
LIGHT_INK = np.array((38, 49, 63), dtype=float)
DARK_INK = np.array((226, 232, 240), dtype=float)


def remove_matte(rgba: np.ndarray, background: tuple[int, int, int]) -> np.ndarray:
    """Unmatte edge pixels using their nearest solid foreground, avoiding halos."""
    rgb = rgba[..., :3].astype(float)
    matte = np.array(background, dtype=float)
    difference = np.max(np.abs(rgb - matte), axis=2)
    solid = difference >= 96
    nearest = distance_transform_edt(~solid, return_distances=False, return_indices=True)
    foreground = rgb[tuple(nearest)]
    direction = foreground - matte
    amount = np.clip(
        np.sum((rgb - matte) * direction, axis=2)
        / np.maximum(np.sum(direction * direction, axis=2), 1),
        0, 1,
    )
    amount[difference <= 12] = 0
    amount[solid] = 1
    rgb = np.clip(matte + (rgb - matte) / np.maximum(amount[..., None], 0.001), 0, 255)
    return np.dstack((rgb, rgba[..., 3] * amount)).round().astype(np.uint8)


def variants(source: Path) -> tuple[Image.Image, Image.Image]:
    rgba = np.array(Image.open(source).convert("RGBA"))
    if source.stem in MATTES:
        rgba = remove_matte(rgba, MATTES[source.stem])
    light, dark = rgba.copy(), rgba.copy()
    rgb = rgba[..., :3].astype(float)
    if source.stem in MONOCHROME:
        if source.stem in WHITE_WORDMARKS:
            light[..., :3] = LIGHT_INK
        dark[..., :3] = DARK_INK
    elif source.stem != "kexcelled":
        # Keep colored artwork. Neutral lettering gets a legible theme variant.
        neutral = (rgb.max(axis=2) - rgb.min(axis=2)) <= 38
        light[neutral & (rgb.mean(axis=2) > 150), :3] = LIGHT_INK
        dark[neutral & (rgb.mean(axis=2) < 160), :3] = DARK_INK
        if source.stem in DARK_COLOR_WORDMARKS:
            colored = ~neutral
            # Blend toward white only until the dark ink reaches a readable
            # lightness. Already-bright cyan/yellow artwork is left alone.
            luminance = rgb @ np.array((0.2126, 0.7152, 0.0722))
            lift = np.clip((145 - luminance) / np.maximum(255 - luminance, 1), 0, 1)
            dark[colored, :3] = np.round((rgb + (255 - rgb) * lift[..., None])[colored])
    alpha = Image.fromarray(rgba[..., 3]).point(lambda value: 255 if value > 16 else 0)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError(f"No logo foreground in {source.name}")
    padding = max(2, round(max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.04))
    bounds = (
        max(0, bounds[0] - padding), max(0, bounds[1] - padding),
        min(rgba.shape[1], bounds[2] + padding), min(rgba.shape[0], bounds[3] + padding),
    )
    return Image.fromarray(light).crop(bounds), Image.fromarray(dark).crop(bounds)


def main() -> None:
    destination = ASSETS / "theme"
    destination.mkdir(exist_ok=True)
    for source in sorted(ASSETS.iterdir()):
        if source.suffix not in {".png", ".jpg"}:
            continue
        light, dark = variants(source)
        light.save(destination / f"{source.stem}.png", optimize=True)
        if source.stem not in SHARED_THEME:
            dark.save(destination / f"{source.stem}-dark.png", optimize=True)
    # This SVG's neutral wordmark is separate from its colored symbol.
    creality = (ASSETS / "creality.svg").read_text(encoding="utf-8")
    (destination / "creality-dark.svg").write_text(
        creality.replace("fill:#323e48", "fill:#e2e8f0"), encoding="utf-8",
    )


if __name__ == "__main__":
    main()

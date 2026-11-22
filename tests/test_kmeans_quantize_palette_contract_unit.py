"""Regression tests for the K-Means quantizer's palette contract.
K-Means 量化器调色板契约回归测试。

The quantizer must ALWAYS satisfy ``unique RGB count <= n_colors``. A
previous implementation ran ``cv2.medianBlur`` after quantization, which
computes the median independently per channel and therefore synthesised
new RGB triples at neighbourhood boundaries — violating the contract by
10-100x on real-world images. That blur has been removed entirely; this
test locks the contract in so it cannot quietly regress again.

量化器必须始终满足 ``unique RGB 数 <= n_colors``。老实现会在量化之后跑
``cv2.medianBlur``，逐通道取中值会在邻域边界上凭空造出新的 RGB 三元组，
把契约违反 10-100 倍；该步骤已整块删除。本回归测试把契约钉死，防止
日后再次悄悄引入破坏契约的后处理。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors


def _synthetic_noisy_image(n_centers: int, h: int, w: int, seed: int) -> np.ndarray:
    """Build an (H, W, 3) uint8 image whose ground-truth palette has
    exactly ``n_centers`` distinct RGB values arranged randomly.
    生成 (H, W, 3) uint8 合成图，真实调色板恰有 ``n_centers`` 个随机 RGB 值。
    """
    rng = np.random.default_rng(seed)
    centers = rng.integers(0, 256, size=(n_centers, 3), dtype=np.uint8)
    labels = rng.integers(0, n_centers, size=(h, w))
    return centers[labels]


@pytest.mark.parametrize(
    ("n_centers", "n_colors", "seed"),
    [
        (16, 8, 1),
        (16, 16, 2),
        (32, 16, 3),
        (64, 32, 4),
        # High-K unlocked case: mirrors the frontend "unlock quantize colors"
        # flow where users can pick K up to 8192. The palette contract must
        # still hold. (前端解锁模式可选 K 到 8192，契约仍需成立。)
        (256, 256, 5),
    ],
)
def test_quantize_colors_respects_palette_contract(
    n_centers: int, n_colors: int, seed: int
) -> None:
    """量化输出的 unique RGB 数必须 <= n_colors。"""
    img = _synthetic_noisy_image(n_centers=n_centers, h=120, w=120, seed=seed)
    out = quantize_colors(img, n_colors=n_colors, seed=42)
    unique_count = np.unique(out.reshape(-1, 3), axis=0).shape[0]
    assert unique_count <= n_colors, (
        f"palette contract violated: n_colors={n_colors} but "
        f"got {unique_count} unique RGB values"
    )


def test_deprecated_skip_post_blur_kwarg_is_accepted_and_noop() -> None:
    """``skip_post_blur`` is a deprecated no-op kept for backward compat.
    保留的已废弃关键字参数不应影响输出。
    """
    img = _synthetic_noisy_image(n_centers=16, h=64, w=64, seed=6)
    out_default = quantize_colors(img, n_colors=16, seed=42)
    out_legacy_kwarg = quantize_colors(
        img, n_colors=16, seed=42, skip_post_blur=True
    )
    # The cache is keyed without ``skip_post_blur`` so both calls should
    # return byte-identical output; the kwarg is purely cosmetic now.
    # cache key 与 skip_post_blur 无关，两次调用应输出完全相同。
    assert np.array_equal(out_default, out_legacy_kwarg)


def test_large_low_color_image_keeps_exact_rgb_without_full_size_unique_sort(monkeypatch):
    image = np.zeros((640, 641, 3), dtype=np.uint8)
    image[-2:, :, :] = (12, 45, 78)
    unique = np.unique
    sorted_sizes = []

    def measure(values, *args, **kwargs):
        sorted_sizes.append(values.size)
        return unique(values, *args, **kwargs)

    with monkeypatch.context() as patching:
        patching.setattr(np, "unique", measure)
        result = quantize_colors(image, n_colors=2)

    assert max(sorted_sizes, default=0) <= 256 * 1024
    np.testing.assert_array_equal(result, image)
    assert not np.shares_memory(result, image)


def test_masked_quantization_ignores_and_preserves_unselected_pixels() -> None:
    """Masked-out air must neither train K-Means nor leak through its cache."""
    mask = np.zeros((6, 6), dtype=bool)
    mask[5, 3:6] = True
    visible = np.array(
        [[255, 0, 0], [0, 255, 0], [0, 0, 255]],
        dtype=np.uint8,
    )

    white_air = np.full((6, 6, 3), 255, dtype=np.uint8)
    white_air[mask] = visible
    white_result = quantize_colors(white_air, n_colors=2, seed=42, mask=mask)

    black_air = np.zeros((6, 6, 3), dtype=np.uint8)
    black_air[mask] = visible
    black_result = quantize_colors(black_air, n_colors=2, seed=42, mask=mask)

    assert np.unique(white_result[mask], axis=0).shape[0] == 2
    np.testing.assert_array_equal(white_result[mask], black_result[mask])
    np.testing.assert_array_equal(white_result[~mask], white_air[~mask])
    np.testing.assert_array_equal(black_result[~mask], black_air[~mask])


def test_masked_quantization_large_input_samples_only_selected_pixels(
    monkeypatch,
) -> None:
    """The large-image path must stay mask-aware without a spatial resize."""
    from core.pipeline.processing_ops import kmeans_quantizer

    monkeypatch.setattr(kmeans_quantizer, "KMEANS_PIXEL_THRESHOLD", 8)
    rng = np.random.default_rng(77)
    image = np.full((5, 5, 3), 17, dtype=np.uint8)
    mask = np.zeros((5, 5), dtype=bool)
    mask[:4, :4] = True
    image[mask] = rng.integers(0, 256, size=(16, 3), dtype=np.uint8)

    result = kmeans_quantizer.quantize_colors(
        image,
        n_colors=4,
        seed=42,
        mask=mask,
    )

    assert result.shape == image.shape
    assert np.unique(result[mask], axis=0).shape[0] <= 4
    np.testing.assert_array_equal(result[~mask], image[~mask])


def test_masked_large_quantization_does_not_alias_periodic_colors(
    monkeypatch,
) -> None:
    """Large masked sampling must not lock onto one phase of a pattern."""
    from core.pipeline.processing_ops import kmeans_quantizer

    monkeypatch.setattr(kmeans_quantizer, "KMEANS_PIXEL_THRESHOLD", 8)
    image = np.zeros((1, 17, 3), dtype=np.uint8)
    image[0, :16:2] = [255, 0, 0]
    image[0, 1:16:2] = [0, 255, 0]
    image[0, 16] = [19, 23, 29]
    mask = np.zeros((1, 17), dtype=bool)
    mask[0, :16] = True

    kmeans_quantizer._kmeans_cache.clear()
    result = kmeans_quantizer.quantize_colors(
        image,
        n_colors=1,
        seed=42,
        mask=mask,
    )
    kmeans_quantizer._kmeans_cache.clear()
    recomputed = kmeans_quantizer.quantize_colors(
        image,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    np.testing.assert_array_equal(
        np.unique(result[mask], axis=0),
        [[127, 127, 0]],
    )
    np.testing.assert_array_equal(recomputed, result)
    np.testing.assert_array_equal(result[~mask], image[~mask])


def test_all_true_mask_reuses_unmasked_large_image_behavior_and_cache(
    monkeypatch,
) -> None:
    """An all-selected mask is exactly equivalent to omitting the mask."""
    from core.pipeline.processing_ops import kmeans_quantizer

    monkeypatch.setattr(kmeans_quantizer, "KMEANS_PIXEL_THRESHOLD", 8)
    image = np.empty((4, 4, 3), dtype=np.uint8)
    image.reshape(-1, 3)[0::2] = [255, 0, 0]
    image.reshape(-1, 3)[1::2] = [0, 255, 0]
    mask = np.ones((4, 4), dtype=bool)

    kmeans_quantizer._kmeans_cache.clear()
    unmasked = kmeans_quantizer.quantize_colors(image, n_colors=1, seed=42)
    masked = kmeans_quantizer.quantize_colors(
        image,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    np.testing.assert_array_equal(masked, unmasked)
    assert len(kmeans_quantizer._kmeans_cache) == 1


@pytest.mark.parametrize("use_all_true_mask", [False, True])
def test_full_image_cache_hashes_every_rgb_pixel(
    use_all_true_mask: bool,
) -> None:
    """Sample-equal full images must not share a quantized cache result."""
    from core.pipeline.processing_ops import kmeans_quantizer

    blue = np.full((100, 100, 3), [0, 0, 255], dtype=np.uint8)
    green = np.full((100, 100, 3), [0, 255, 0], dtype=np.uint8)
    blue[::3, ::3] = [255, 0, 0]
    green[::3, ::3] = [255, 0, 0]
    np.testing.assert_array_equal(blue[::3, ::3], green[::3, ::3])
    assert not np.array_equal(blue, green)

    mask = np.ones((100, 100), dtype=bool) if use_all_true_mask else None
    kmeans_quantizer._kmeans_cache.clear()
    first_result = kmeans_quantizer.quantize_colors(
        blue,
        n_colors=1,
        seed=42,
        mask=mask,
    )
    cached_second = kmeans_quantizer.quantize_colors(
        green,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    kmeans_quantizer._kmeans_cache.clear()
    fresh_second = kmeans_quantizer.quantize_colors(
        green,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    assert not np.array_equal(first_result, fresh_second)
    np.testing.assert_array_equal(cached_second, fresh_second)


def test_partial_mask_large_quantization_cache_keeps_current_air(
    monkeypatch,
) -> None:
    """Partial-mask cache hits reuse visible results but not stale air RGB."""
    from core.pipeline.processing_ops import kmeans_quantizer

    monkeypatch.setattr(kmeans_quantizer, "KMEANS_PIXEL_THRESHOLD", 8)
    mask = np.zeros((5, 5), dtype=bool)
    mask[:4, :4] = True

    first = np.full((5, 5, 3), 255, dtype=np.uint8)
    first_visible = np.empty((16, 3), dtype=np.uint8)
    first_visible[0::2] = [255, 0, 0]
    first_visible[1::2] = [0, 255, 0]
    first[mask] = first_visible

    second = np.zeros((5, 5, 3), dtype=np.uint8)
    second[mask] = first_visible

    kmeans_quantizer._kmeans_cache.clear()
    first_result = kmeans_quantizer.quantize_colors(
        first,
        n_colors=1,
        seed=42,
        mask=mask,
    )
    second_result = kmeans_quantizer.quantize_colors(
        second,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    np.testing.assert_array_equal(
        np.unique(first_result[mask], axis=0),
        [[127, 127, 0]],
    )
    np.testing.assert_array_equal(second_result[mask], first_result[mask])
    np.testing.assert_array_equal(first_result[~mask], first[~mask])
    np.testing.assert_array_equal(second_result[~mask], second[~mask])
    assert len(kmeans_quantizer._kmeans_cache) == 1


def test_masked_quantization_cache_hashes_every_selected_pixel() -> None:
    """Unsampled selected RGB changes must not reuse another image's result."""
    from core.pipeline.processing_ops import kmeans_quantizer

    mask = np.ones((100, 101), dtype=bool)
    mask[:, -1] = False
    first_visible = np.empty((10_000, 3), dtype=np.uint8)
    first_visible[0::2] = [255, 0, 0]
    first_visible[1::2] = [0, 0, 255]
    second_visible = first_visible.copy()
    # The historical partial-mask key sampled selected_rgb[::2], so changing
    # only odd visible positions must still invalidate the cache entry.
    second_visible[1::2] = [0, 255, 0]

    first = np.zeros((100, 101, 3), dtype=np.uint8)
    first[mask] = first_visible
    second = np.zeros((100, 101, 3), dtype=np.uint8)
    second[mask] = second_visible

    np.testing.assert_array_equal(first_visible[::2], second_visible[::2])
    assert not np.array_equal(first_visible, second_visible)

    kmeans_quantizer._kmeans_cache.clear()
    kmeans_quantizer.quantize_colors(first, n_colors=1, seed=42, mask=mask)
    cached_second = kmeans_quantizer.quantize_colors(
        second,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    kmeans_quantizer._kmeans_cache.clear()
    recomputed_second = kmeans_quantizer.quantize_colors(
        second,
        n_colors=1,
        seed=42,
        mask=mask,
    )

    np.testing.assert_array_equal(cached_second, recomputed_second)

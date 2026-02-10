"""
ΔE2000 Color Matcher Module

This module implements a NumPy-vectorized CIEDE2000 color difference matcher
for mapping unique colors to LUT entries using perceptual color distance.

Reference: Sharma, G., Wu, W., & Dalal, E. N. (2004).
"The CIEDE2000 Color-Difference Formula: Implementation Notes,
Supplementary Test Data, and Mathematical Observations."

Functions:
- rgb_to_lab: Convert sRGB colors to CIELAB color space
- delta_e_2000: Compute CIEDE2000 color difference (vectorized)
- match_colors_deltae2000: Match unique colors to LUT using ΔE2000
"""

import numpy as np
from typing import Tuple


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """
    Convert sRGB colors to CIELAB color space (vectorized).

    Uses standard sRGB to XYZ conversion with D65 white point,
    then XYZ to LAB conversion.

    Args:
        rgb: RGB color array, shape (N, 3), values in [0, 255] or [0, 1]

    Returns:
        LAB color array, shape (N, 3)
        - L*: Lightness [0, 100]
        - a*: Green-red axis [-128, 127]
        - b*: Blue-yellow axis [-128, 127]

    Reference:
        - sRGB to XYZ: IEC 61966-2-1:1999
        - XYZ to LAB: CIE 15:2004
    """
    # Handle uint8 input
    if rgb.dtype == np.uint8:
        rgb = rgb.astype(np.float64) / 255.0
    else:
        rgb = rgb.astype(np.float64)

    # Apply inverse gamma correction (sRGB to linear RGB)
    # Using piecewise function for sRGB companding
    mask = rgb <= 0.04045
    rgb_linear = np.empty_like(rgb)
    rgb_linear[mask] = rgb[mask] / 12.92
    rgb_linear[~mask] = ((rgb[~mask] + 0.055) / 1.055) ** 2.4

    # Linear RGB to XYZ (D65 illuminant)
    # sRGB transformation matrix
    M = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float64,
    )

    # Reshape for matrix multiplication: (N, 3) @ (3, 3).T
    xyz = rgb_linear @ M.T

    # Scale by reference white (D65)
    xyz_ref_white = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
    xyz_normalized = xyz / xyz_ref_white

    # XYZ to LAB conversion
    # f(t) = t^(1/3) for t > (6/29)^3, else f(t) = (1/3)(29/6)^2 * t + 4/29
    delta = 6.0 / 29.0
    delta_cubed = delta**3

    # Apply f function
    f_xyz = np.empty_like(xyz_normalized)
    mask_large = xyz_normalized > delta_cubed
    mask_small = ~mask_large

    f_xyz[mask_large] = xyz_normalized[mask_large] ** (1.0 / 3.0)
    f_xyz[mask_small] = (1.0 / 3.0) * (29.0 / 6.0) ** 2 * xyz_normalized[
        mask_small
    ] + 4.0 / 29.0

    # Calculate LAB
    L = 116.0 * f_xyz[:, 1] - 16.0  # L*
    a = 500.0 * (f_xyz[:, 0] - f_xyz[:, 1])  # a*
    b = 200.0 * (f_xyz[:, 1] - f_xyz[:, 2])  # b*

    return np.stack([L, a, b], axis=1)


def delta_e_2000(
    lab1: np.ndarray,
    lab2: np.ndarray,
    kL: float = 1.0,
    kC: float = 1.0,
    kH: float = 1.0,
) -> np.ndarray:
    """
    Compute CIEDE2000 color difference (vectorized).

    Args:
        lab1: LAB color array, shape (N, 3)
        lab2: LAB color array, shape (M, 3)
        kL: Lightness weighting factor (default: 1.0)
        kC: Chroma weighting factor (default: 1.0)
        kH: Hue weighting factor (default: 1.0)

    Returns:
        Delta E array, shape (N, M)
        ΔE values between each pair of colors

    Note:
        This function broadcasts to compute pair-wise differences.
        For N unique colors and M LUT entries, returns (N, M) matrix.
    """
    # Reshape for broadcasting
    # lab1: (N, 3) -> (N, 1, 3)
    # lab2: (M, 3) -> (1, M, 3)
    lab1_broadcast = lab1[:, np.newaxis, :]
    lab2_broadcast = lab2[np.newaxis, :, :]

    # Extract components
    L1, a1, b1 = lab1_broadcast[..., 0], lab1_broadcast[..., 1], lab1_broadcast[..., 2]
    L2, a2, b2 = lab2_broadcast[..., 0], lab2_broadcast[..., 1], lab2_broadcast[..., 2]

    # Calculate mean L and chroma
    L_mean = (L1 + L2) / 2.0

    # Calculate chroma (C = sqrt(a^2 + b^2))
    C1 = np.sqrt(a1**2 + b1**2)
    C2 = np.sqrt(a2**2 + b2**2)

    # Mean chroma
    C_mean = (C1 + C2) / 2.0

    # Calculate G factor (compensates for chroma-dependent hue rotation)
    # G = 0.5 * (1 - sqrt(C_mean^7 / (C_mean^7 + 25^7)))
    C_mean7 = C_mean**7
    G = 0.5 * (1.0 - np.sqrt(C_mean7 / (C_mean7 + 25.0**7)))

    # Calculate adjusted a' (a prime)
    a1p = a1 * (1.0 + G)
    a2p = a2 * (1.0 + G)

    # Calculate adjusted chroma C'
    C1p = np.sqrt(a1p**2 + b1**2)
    C2p = np.sqrt(a2p**2 + b2**2)

    # Calculate hue angle h' (in radians)
    # Handle arctan2 to get angle in [-π, π]
    h1p = np.arctan2(b1, a1p)
    h2p = np.arctan2(b2, a2p)

    # Calculate mean hue angle
    # Handle absolute difference > π case
    h_abs_diff = np.abs(h1p - h2p)
    h_mean = (h1p + h2p) / 2.0

    # Adjust mean hue for wrap-around
    mask_wrap = h_abs_diff > np.pi
    h_mean = np.where(mask_wrap, h_mean + np.pi, h_mean)
    h_mean = np.where(h_mean < 0, h_mean + 2 * np.pi, h_mean)

    # Calculate ΔL', ΔC', ΔH'
    dL = L2 - L1
    dC = C2p - C1p

    # Calculate hue difference dH'
    # Need to handle the case where hue difference wraps around ±π
    dh = h2p - h1p
    dh = np.where(dh <= -np.pi, dh + 2 * np.pi, dh)
    dh = np.where(dh > np.pi, dh - 2 * np.pi, dh)

    # dH' = 2 * sqrt(C1' * C2') * sin(dh' / 2)
    dH = 2.0 * np.sqrt(np.maximum(C1p * C2p, 0)) * np.sin(dh / 2.0)

    # Calculate weighting functions SL, SC, SH
    # SL = 1 + (0.015 * L_mean^2) / sqrt(20 + L_mean^2)
    SL = 1.0 + (0.015 * L_mean**2) / np.sqrt(20.0 + L_mean**2)

    # SC = 1 + 0.045 * C_mean
    SC = 1.0 + 0.045 * C_mean

    # SH = 1 + 0.015 * C_mean * T
    # T = 1 - 0.17 * cos(h_mean - 30°) + 0.24 * cos(2*h_mean)
    #      + 0.32 * cos(3*h_mean + 6°) - 0.20 * cos(4*h_mean - 63°)
    # Convert degrees to radians for trig functions
    h_mean_deg = np.degrees(h_mean)

    T = (
        1.0
        - 0.17 * np.cos(np.radians(h_mean_deg - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_mean_deg))
        + 0.32 * np.cos(np.radians(3.0 * h_mean_deg + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_mean_deg - 63.0))
    )

    SH = 1.0 + 0.015 * C_mean * T

    # Calculate rotation factor RT
    # RT = -2 * sqrt(C_mean^7 / (C_mean^7 + 25^7)) * sin(60° * exp(-((h_mean - 275°)/25)^2))
    delta_theta = 60.0 * np.exp(-(((h_mean_deg - 275.0) / 25.0) ** 2))
    RT = -2.0 * np.sqrt(C_mean7 / (C_mean7 + 25.0**7)) * np.sin(np.radians(delta_theta))

    # Calculate CIEDE2000
    # dE = sqrt((dL/(kL*SL))^2 + (dC/(kC*SC))^2 + (dH/(kH*SH))^2
    #           + RT * (dC/(kC*SC)) * (dH/(kH*SH)))
    dL_term = dL / (kL * SL)
    dC_term = dC / (kC * SC)
    dH_term = dH / (kH * SH)

    dE_squared = dL_term**2 + dC_term**2 + dH_term**2 + RT * dC_term * dH_term

    # Ensure non-negative before sqrt
    dE = np.sqrt(np.maximum(dE_squared, 0))

    # If input was 1D, squeeze the output
    if len(lab1.shape) == 1 and len(lab2.shape) == 1:
        return dE.item()

    # If lab1 is 1D, return 1D array (M,)
    if len(lab1.shape) == 1:
        return dE[0]

    # If lab2 is 1D, return 1D array (N,)
    if len(lab2.shape) == 1:
        return dE[:, 0]

    # Otherwise return (N, M) matrix
    return dE


def match_colors_deltae2000(
    unique_colors: np.ndarray, lut_rgb: np.ndarray, top_k: int = None
) -> np.ndarray:
    """
    Match unique colors to LUT entries using CIEDE2000 color difference.

    This function performs vectorized color matching by:
    1. Converting all colors to CIELAB space
    2. Computing pair-wise ΔE2000 values
    3. Finding minimum ΔE for each unique color
    4. Applying tie-break rule (smallest index when ΔE values are equal)

    Args:
        unique_colors: RGB colors to match, shape (N, 3), dtype uint8 or float
        lut_rgb: LUT RGB colors, shape (M, 3), dtype uint8 or float
        top_k: If specified, only search top-k closest candidates by RGB distance
               as an optimization. Set to None for full search (default).

    Returns:
        Indices array, shape (N,), dtype int64
        Each index maps a unique color to its best LUT entry.

    Notes:
        - Tie-breaking: When multiple LUT entries have identical or very
          similar ΔE values (difference < 1e-6), the smallest index is chosen.
        - This ensures deterministic, reproducible results.
        - For top_k optimization: RGB Euclidean distance is used for candidate
          filtering, then ΔE2000 is computed only for those candidates.

    Examples:
        >>> unique_colors = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
        >>> lut_rgb = np.array([[250, 0, 0], [0, 250, 0], [128, 128, 128]], dtype=np.uint8)
        >>> indices = match_colors_deltae2000(unique_colors, lut_rgb)
        >>> print(indices)  # [0, 1]
    """
    print(
        f"[DeltaE2000] Matching {unique_colors.shape[0]} colors to {lut_rgb.shape[0]} LUT entries..."
    )

    # Validate inputs
    if unique_colors.shape[1] != 3 or lut_rgb.shape[1] != 3:
        raise ValueError("Input arrays must have shape (N, 3) for RGB colors")

    if unique_colors.shape[0] == 0:
        return np.array([], dtype=np.int64)

    if lut_rgb.shape[0] == 0:
        raise ValueError("LUT cannot be empty")

    # Step 1: Convert RGB to LAB for perceptual color difference calculation
    print("[DeltaE2000] Converting colors to CIELAB space...")
    unique_lab = rgb_to_lab(unique_colors)  # (N, 3)
    lut_lab = rgb_to_lab(lut_rgb)  # (M, 3)

    # Step 2: Optionally filter candidates using RGB distance (top_k optimization)
    lut_indices_to_check = np.arange(lut_rgb.shape[0], dtype=np.int64)

    if top_k is not None and top_k < lut_rgb.shape[0]:
        print(f"[DeltaE2000] Using top-{top_k} candidate filtering...")
        # Normalize RGB to [0, 1] for distance calculation
        unique_rgb_norm = unique_colors.astype(np.float64) / 255.0
        lut_rgb_norm = lut_rgb.astype(np.float64) / 255.0

        # Compute RGB distances using broadcasting
        # (N, 1, 3) - (1, M, 3) -> (N, M, 3)
        diff = unique_rgb_norm[:, np.newaxis, :] - lut_rgb_norm[np.newaxis, :, :]
        rgb_distances = np.sqrt(np.sum(diff**2, axis=2))  # (N, M)

        # For each unique color, find top-k closest LUT entries
        # Use argsort and take first k indices
        # Note: We need to select unique top-k indices across all query colors
        # to avoid recomputing LAB conversion multiple times
        k = min(top_k, lut_rgb.shape[0])
        top_k_indices = np.argpartition(rgb_distances, k - 1, axis=1)[:, :k]
        lut_indices_to_check = np.unique(top_k_indices.flatten())
        print(
            f"[DeltaE2000] Filtered to {lut_indices_to_check.shape[0]} candidates from {lut_rgb.shape[0]}"
        )

        # Use only filtered LUT entries
        lut_lab_filtered = lut_lab[lut_indices_to_check]
    else:
        lut_lab_filtered = lut_lab

    # Step 3: Compute pair-wise ΔE2000
    print(
        f"[DeltaE2000] Computing ΔE2000 for {unique_lab.shape[0]} x {lut_lab_filtered.shape[0]} pairs..."
    )
    delta_e_matrix = delta_e_2000(unique_lab, lut_lab_filtered)  # (N, M_filtered)

    # Step 4: Find best match with tie-breaking
    # Use lexsort to implement tie-break:
    # Primary key: ΔE value (ascending)
    # Secondary key: LUT index (ascending)
    # This ensures smallest index wins when ΔE values are equal

    print("[DeltaE2000] Finding best matches with tie-breaking...")
    # Get indices that would sort each row by ΔE value
    sorted_indices = np.argsort(delta_e_matrix, axis=1)  # (N, M_filtered)

    # Get minimum ΔE value and its position
    min_indices = sorted_indices[:, 0]  # (N,) - index into filtered LUT
    min_delta_e = delta_e_matrix[np.arange(delta_e_matrix.shape[0]), min_indices]

    # Map back to original LUT indices
    lut_indices = lut_indices_to_check[min_indices]

    # Apply tie-breaking for near-equal ΔE values
    # Check if there are multiple candidates with ΔE difference < 1e-6
    tolerance = 1e-6

    # For each unique color, find all candidates within tolerance
    for i in range(unique_colors.shape[0]):
        mask = delta_e_matrix[i] < (min_delta_e[i] + tolerance)
        candidates = np.where(mask)[0]

        if len(candidates) > 1:
            # Multiple candidates within tolerance - choose smallest original index
            original_indices = lut_indices_to_check[candidates]
            best_idx = np.argmin(original_indices)
            lut_indices[i] = original_indices[best_idx]

    print(
        f"[DeltaE2000] Matching complete. Min ΔE: {min_delta_e.min():.4f}, Max ΔE: {min_delta_e.max():.4f}"
    )

    return lut_indices


def compute_delta_e_stats(
    source_colors: np.ndarray, matched_colors: np.ndarray
) -> dict:
    """
    Compute statistics about ΔE2000 values for matched colors.

    Args:
        source_colors: Original colors, shape (N, 3)
        matched_colors: Matched LUT colors, shape (N, 3)

    Returns:
        Dictionary with statistics:
        - mean: Mean ΔE value
        - median: Median ΔE value
        - std: Standard deviation of ΔE values
        - min: Minimum ΔE value
        - max: Maximum ΔE value
        - p95: 95th percentile ΔE value
    """
    source_lab = rgb_to_lab(source_colors)
    matched_lab = rgb_to_lab(matched_colors)

    delta_e = delta_e_2000(source_lab, matched_lab)

    return {
        "mean": float(np.mean(delta_e)),
        "median": float(np.median(delta_e)),
        "std": float(np.std(delta_e)),
        "min": float(np.min(delta_e)),
        "max": float(np.max(delta_e)),
        "p95": float(np.percentile(delta_e, 95)),
    }

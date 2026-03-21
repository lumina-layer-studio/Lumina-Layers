"""
Merge Remap Verification Script

Verifies that material ID remapping produces correct 8-Color space stacks
for all color modes (BW, 4-Color RYBW/CMYW, 6-Color CMYWGK/RYBWGK, 8-Color).

Uses actual LUT files from the preset folder to validate end-to-end correctness.
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.lut_merger import (
    LUTMerger, _remap_stacks, _detect_4color_subtype, _detect_6color_subtype,
    _REMAP_TO_8COLOR
)
from config import ColorSystem

# 8-Color slot names for readable output
SLOT_8COLOR = {0: "White", 1: "Cyan", 2: "Magenta", 3: "Yellow",
               4: "Black", 5: "Red", 6: "DeepBlue", 7: "Green"}

# 6-Color CMYWGK slot names
SLOT_6COLOR_CMYWGK = {0: "White", 1: "Cyan", 2: "Magenta", 3: "Green", 4: "Yellow", 5: "Black"}

# 6-Color RYBWGK slot names
SLOT_6COLOR_RYBWGK = {0: "White", 1: "Red", 2: "Blue", 3: "Green", 4: "Yellow", 5: "Black"}

# 4-Color RYBW slot names
SLOT_4COLOR_RYBW = {0: "White", 1: "Red", 2: "Yellow", 3: "Blue"}

# 4-Color CMYW slot names
SLOT_4COLOR_CMYW = {0: "White", 1: "Cyan", 2: "Magenta", 3: "Yellow"}

# BW slot names
SLOT_BW = {0: "White", 1: "Black"}


def verify_remap_table(remap_key, src_slots, expected_mapping):
    """Verify a remap table maps source colors to correct 8-Color slots."""
    remap = _REMAP_TO_8COLOR[remap_key]
    print(f"\n{'='*60}")
    print(f"Verifying: {remap_key}")
    print(f"{'='*60}")

    errors = 0
    for src_id, dst_id in remap.items():
        src_name = src_slots.get(src_id, f"?{src_id}")
        dst_name = SLOT_8COLOR.get(dst_id, f"?{dst_id}")
        expected_dst = expected_mapping.get(src_id)

        status = "✅" if dst_id == expected_dst else "❌"
        if dst_id != expected_dst:
            errors += 1
            expected_name = SLOT_8COLOR.get(expected_dst, f"?{expected_dst}")
            print(f"  {status} slot {src_id}({src_name}) → {dst_id}({dst_name})  EXPECTED → {expected_dst}({expected_name})")
        else:
            print(f"  {status} slot {src_id}({src_name}) → {dst_id}({dst_name})")

    if errors == 0:
        print(f"  ✅ All {len(remap)} mappings correct")
    else:
        print(f"  ❌ {errors} mapping errors!")
    return errors == 0


def verify_subtype_detection():
    """Verify filename-based subtype detection."""
    print(f"\n{'='*60}")
    print("Verifying subtype detection")
    print(f"{'='*60}")

    errors = 0

    # 4-Color tests
    tests_4c = [
        ("Bambulab_basic_rybw.npy", "4-Color-RYBW"),
        ("some_CMYW_lut.npy", "4-Color-CMYW"),
        ("通用LUT[有色差]RYBW General.npy", "4-Color-RYBW"),
        ("unknown_4color.npy", "4-Color-RYBW"),  # default
    ]
    for fname, expected in tests_4c:
        result = _detect_4color_subtype(fname)
        status = "✅" if result == expected else "❌"
        if result != expected:
            errors += 1
        print(f"  {status} 4-Color: {fname} → {result} (expected {expected})")

    # 6-Color tests
    tests_6c = [
        ("Bambulab_basic_cmywgk.npy", "6-Color-CMYWGK"),
        ("Aliz&PLA&6色红色模式&红-黄-蓝-白-绿-黑&20260211.npy", "6-Color-CMYWGK"),  # no RYBW keyword
        ("some_6color_RYBW_mode.npy", "6-Color-RYBWGK"),
        ("Aliz_PETG_6color_rybwgk.npy", "6-Color-RYBWGK"),
        ("unknown_6color.npy", "6-Color-CMYWGK"),  # default
    ]
    for fname, expected in tests_6c:
        result = _detect_6color_subtype(fname)
        status = "✅" if result == expected else "❌"
        if result != expected:
            errors += 1
        print(f"  {status} 6-Color: {fname} → {result} (expected {expected})")

    if errors == 0:
        print(f"  ✅ All detection tests passed")
    else:
        print(f"  ❌ {errors} detection errors!")
    return errors == 0


def verify_remap_with_real_stacks():
    """Verify remap produces valid 8-Color material IDs using synthetic stacks."""
    print(f"\n{'='*60}")
    print("Verifying remap with synthetic stacks")
    print(f"{'='*60}")

    errors = 0

    # Test: 6-Color CMYWGK pure-color stacks
    # Stack of all Cyan (slot 1) should become all Cyan (8-Color slot 1)
    cmywgk_cyan = np.array([[1, 1, 1, 1, 1]])
    result = _remap_stacks(cmywgk_cyan, "6-Color", "/fake/path_cmywgk.npy")
    expected = np.array([[1, 1, 1, 1, 1]])  # Cyan→Cyan(1)
    if np.array_equal(result, expected):
        print(f"  ✅ 6C-CMYWGK: Cyan(1) → Cyan(1)")
    else:
        print(f"  ❌ 6C-CMYWGK: Cyan(1) → {result[0]} (expected {expected[0]})")
        errors += 1

    # Stack of all Green (slot 3) should become all Green (8-Color slot 7)
    cmywgk_green = np.array([[3, 3, 3, 3, 3]])
    result = _remap_stacks(cmywgk_green, "6-Color", "/fake/path_cmywgk.npy")
    expected = np.array([[7, 7, 7, 7, 7]])  # Green→Green(7)
    if np.array_equal(result, expected):
        print(f"  ✅ 6C-CMYWGK: Green(3) → Green(7)")
    else:
        print(f"  ❌ 6C-CMYWGK: Green(3) → {result[0]} (expected {expected[0]})")
        errors += 1

    # Test: 6-Color RYBWGK pure-color stacks
    # Stack of all Red (slot 1) should become all Red (8-Color slot 5)
    rybwgk_red = np.array([[1, 1, 1, 1, 1]])
    result = _remap_stacks(rybwgk_red, "6-Color", "/fake/path_RYBW_mode.npy")
    expected = np.array([[5, 5, 5, 5, 5]])  # Red→Red(5)
    if np.array_equal(result, expected):
        print(f"  ✅ 6C-RYBWGK: Red(1) → Red(5)")
    else:
        print(f"  ❌ 6C-RYBWGK: Red(1) → {result[0]} (expected {expected[0]})")
        errors += 1

    # Stack of all Blue (slot 2) should become all DeepBlue (8-Color slot 6)
    rybwgk_blue = np.array([[2, 2, 2, 2, 2]])
    result = _remap_stacks(rybwgk_blue, "6-Color", "/fake/path_RYBW_mode.npy")
    expected = np.array([[6, 6, 6, 6, 6]])  # Blue→DeepBlue(6)
    if np.array_equal(result, expected):
        print(f"  ✅ 6C-RYBWGK: Blue(2) → DeepBlue(6)")
    else:
        print(f"  ❌ 6C-RYBWGK: Blue(2) → {result[0]} (expected {expected[0]})")
        errors += 1

    # Mixed stack: [White, Red, Yellow, Green, Black] in RYBWGK
    rybwgk_mixed = np.array([[0, 1, 4, 3, 5]])
    result = _remap_stacks(rybwgk_mixed, "6-Color", "/fake/RYBW_test.npy")
    expected = np.array([[0, 5, 3, 7, 4]])  # White→0, Red→5, Yellow→3, Green→7, Black→4
    if np.array_equal(result, expected):
        print(f"  ✅ 6C-RYBWGK mixed: [0,1,4,3,5] → [0,5,3,7,4]")
    else:
        print(f"  ❌ 6C-RYBWGK mixed: [0,1,4,3,5] → {result[0]} (expected {expected[0]})")
        errors += 1

    # Test: 8-Color should pass through unchanged
    eight_color = np.array([[0, 1, 5, 6, 7]])
    result = _remap_stacks(eight_color, "8-Color")
    if np.array_equal(result, eight_color):
        print(f"  ✅ 8-Color: passthrough unchanged")
    else:
        print(f"  ❌ 8-Color: modified! {result[0]}")
        errors += 1

    # Test: All remapped IDs must be in 0-7 range
    for mode_key, remap in _REMAP_TO_8COLOR.items():
        for src, dst in remap.items():
            if dst < 0 or dst > 7:
                print(f"  ❌ {mode_key}: dst {dst} out of range 0-7")
                errors += 1

    if errors == 0:
        print(f"  ✅ All synthetic stack tests passed")
    else:
        print(f"  ❌ {errors} errors!")
    return errors == 0


def verify_real_lut_files():
    """Verify remap with actual LUT files from preset folder."""
    print(f"\n{'='*60}")
    print("Verifying with real LUT files")
    print(f"{'='*60}")

    preset_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "lut-npy预设", "Custom")

    lut_files = {
        "Bambulab&PLA&8色&红-品红-青-蓝-黄-白-绿-黑.npy": ("8-Color", 2738),
        "Bambulab&PLA&CMYW&青-品红-黄-绿-白-黑.npy": ("6-Color", 1296),
        "Bambulab&PLA&BW&白-黑.npy": ("BW", None),
        "Bambulab&PLA&RYBW&红-黄-蓝-白.npy": ("4-Color", 1024),
    }

    errors = 0
    all_entries = []

    for fname, (expected_mode, expected_count) in lut_files.items():
        fpath = os.path.join(preset_dir, fname)
        if not os.path.exists(fpath):
            print(f"  ⚠️  Skipping {fname} (not found)")
            continue

        mode, count = LUTMerger.detect_color_mode(fpath)
        print(f"\n  📁 {fname}: detected {mode} ({count} colors)")

        if mode != expected_mode:
            print(f"  ❌ Expected mode {expected_mode}, got {mode}")
            errors += 1
            continue

        if expected_count and count != expected_count:
            print(f"  ⚠️  Expected {expected_count} colors, got {count}")

        # Load with stacks (this triggers remap)
        rgb, stacks = LUTMerger.load_lut_with_stacks(fpath, mode)
        print(f"  Loaded: {rgb.shape[0]} colors, stacks shape {stacks.shape}")

        # Verify all material IDs are in 0-7 range (8-Color space)
        unique_ids = np.unique(stacks)
        max_id = np.max(stacks)
        min_id = np.min(stacks)

        if min_id < 0 or max_id > 7:
            print(f"  ❌ Material IDs out of range: [{min_id}, {max_id}]")
            errors += 1
        else:
            print(f"  ✅ Material IDs in range: {unique_ids}")

        all_entries.append((rgb, stacks, mode))

    # If we have enough entries, do a test merge
    if len(all_entries) >= 2:
        print(f"\n  🔀 Test merge with {len(all_entries)} LUTs...")
        merged_rgb, merged_stacks, stats = LUTMerger.merge_luts(all_entries, dedup_threshold=0)

        print(f"  Merged: {stats['total_before']} → {stats['total_after']} colors")
        print(f"  Exact dupes: {stats['exact_dupes']}")

        # Verify merged stacks are all in 0-7
        merged_unique = np.unique(merged_stacks)
        merged_max = np.max(merged_stacks)
        if merged_max > 7 or np.min(merged_stacks) < 0:
            print(f"  ❌ Merged material IDs out of range: {merged_unique}")
            errors += 1
        else:
            print(f"  ✅ Merged material IDs valid: {merged_unique}")

    if errors == 0:
        print(f"\n  ✅ All real LUT file tests passed")
    else:
        print(f"\n  ❌ {errors} errors!")
    return errors == 0


def verify_merged_npz():
    """Verify existing merged .npz file has correct material IDs."""
    print(f"\n{'='*60}")
    print("Verifying existing merged .npz")
    print(f"{'='*60}")

    preset_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "lut-npy预设", "Custom")

    errors = 0
    for fname in os.listdir(preset_dir):
        if not fname.endswith('.npz'):
            continue

        fpath = os.path.join(preset_dir, fname)
        data = np.load(fpath)
        rgb = data['rgb']
        stacks = data['stacks']

        unique_ids = np.unique(stacks)
        max_id = np.max(stacks)

        print(f"\n  📁 {fname}")
        print(f"  Colors: {rgb.shape[0]}, Stacks: {stacks.shape}")
        print(f"  Material IDs: {unique_ids}")

        if max_id > 7 or np.min(stacks) < 0:
            print(f"  ❌ Material IDs out of range!")
            errors += 1
        else:
            print(f"  ✅ All material IDs in valid 8-Color range (0-7)")

    return errors == 0



def verify_image_conversion():
    """Verify that merged LUT produces correct stacks when processing an image."""
    print(f"\n{'='*60}")
    print("Verifying image conversion with merged LUT")
    print(f"{'='*60}")

    test_image = "new_test.png"
    if not os.path.exists(test_image):
        print(f"  ⚠️  Skipping: {test_image} not found")
        return True

    # Find merged .npz
    preset_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "lut-npy预设", "Custom")
    npz_files = [f for f in os.listdir(preset_dir) if f.endswith('.npz')]
    if not npz_files:
        print(f"  ⚠️  No .npz files found, skipping")
        return True

    npz_path = os.path.join(preset_dir, npz_files[0])
    print(f"  Using LUT: {npz_files[0]}")
    print(f"  Using image: {test_image}")

    errors = 0

    try:
        from core.image_processing import LuminaImageProcessor
        from config import ModelingMode

        processor = LuminaImageProcessor(npz_path, "Merged")
        result = processor.process_image(
            image_path=test_image,
            target_width_mm=80,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            quantize_colors=32,
            auto_bg=True,
            bg_tol=30,
            blur_kernel=0,
            smooth_sigma=10
        )

        material_matrix = result['material_matrix']
        mask_solid = result['mask_solid']

        # Check material IDs in the output
        solid_materials = material_matrix[mask_solid]
        unique_ids = np.unique(solid_materials)
        max_id = np.max(solid_materials) if len(solid_materials) > 0 else -1

        print(f"  Image processed: {result['dimensions']}")
        print(f"  Solid pixels: {np.sum(mask_solid)}")
        print(f"  Material IDs used: {unique_ids}")

        if max_id > 7:
            print(f"  ❌ Material ID {max_id} exceeds 8-Color range!")
            errors += 1
        elif max_id < 0 and len(solid_materials) > 0:
            print(f"  ❌ Negative material ID found!")
            errors += 1
        else:
            print(f"  ✅ All material IDs in valid 8-Color range (0-7)")

        # Verify ref_stacks are in 0-7 range
        ref_max = np.max(processor.ref_stacks)
        ref_min = np.min(processor.ref_stacks)
        print(f"  ref_stacks range: [{ref_min}, {ref_max}]")
        if ref_max > 7 or ref_min < 0:
            print(f"  ❌ ref_stacks out of range!")
            errors += 1
        else:
            print(f"  ✅ ref_stacks in valid range")

        # Show a few sample color→stack mappings
        print(f"\n  Sample color→stack mappings (first 10 unique colors):")
        matched_rgb = result['matched_rgb']
        seen = set()
        count = 0
        for y in range(matched_rgb.shape[0]):
            if count >= 10:
                break
            for x in range(matched_rgb.shape[1]):
                if count >= 10:
                    break
                if not mask_solid[y, x]:
                    continue
                rgb_key = tuple(matched_rgb[y, x])
                if rgb_key in seen:
                    continue
                seen.add(rgb_key)
                stack = material_matrix[y, x]
                slot_names = [SLOT_8COLOR.get(s, f"?{s}") for s in stack]
                print(f"    RGB{rgb_key} → stack{list(stack)} ({'/'.join(slot_names)})")
                count += 1

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        errors += 1

    return errors == 0


if __name__ == "__main__":
    print("=" * 60)
    print("  MERGE REMAP VERIFICATION")
    print("=" * 60)

    results = []

    # 1. Verify remap tables
    results.append(("BW remap", verify_remap_table(
        "BW", SLOT_BW, {0: 0, 1: 4})))
    results.append(("4C-RYBW remap", verify_remap_table(
        "4-Color-RYBW", SLOT_4COLOR_RYBW, {0: 0, 1: 5, 2: 3, 3: 6})))
    results.append(("4C-CMYW remap", verify_remap_table(
        "4-Color-CMYW", SLOT_4COLOR_CMYW, {0: 0, 1: 1, 2: 2, 3: 3})))
    results.append(("6C-CMYWGK remap", verify_remap_table(
        "6-Color-CMYWGK", SLOT_6COLOR_CMYWGK, {0: 0, 1: 1, 2: 2, 3: 7, 4: 3, 5: 4})))
    results.append(("6C-RYBWGK remap", verify_remap_table(
        "6-Color-RYBWGK", SLOT_6COLOR_RYBWGK, {0: 0, 1: 5, 2: 6, 3: 7, 4: 3, 5: 4})))

    # 2. Verify subtype detection
    results.append(("Subtype detection", verify_subtype_detection()))

    # 3. Verify with synthetic stacks
    results.append(("Synthetic stacks", verify_remap_with_real_stacks()))

    # 4. Verify with real LUT files
    results.append(("Real LUT files", verify_real_lut_files()))

    # 5. Verify existing merged .npz
    results.append(("Merged .npz", verify_merged_npz()))

    # 6. Verify image conversion
    results.append(("Image conversion", verify_image_conversion()))

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}")
        if not passed:
            all_pass = False

    print(f"\n{'='*60}")
    if all_pass:
        print("  ✅ ALL VERIFICATIONS PASSED")
    else:
        print("  ❌ SOME VERIFICATIONS FAILED")
    print(f"{'='*60}")

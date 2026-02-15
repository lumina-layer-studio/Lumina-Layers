"""
Lumina Studio - LUT Preset Manager
LUT preset management module
"""

import os
import shutil
import glob
from pathlib import Path

from utils.i18n_help import make_status_tag


class LUTManager:
    """LUT preset manager"""

    # LUT preset folder path
    LUT_PRESET_DIR = "lut-npy预设"

    @classmethod
    def get_all_lut_files(cls):
        """
        Scan and return all available LUT files

        Returns:
            dict: {display_name: file_path}
        """
        lut_files = {}

        if not os.path.exists(cls.LUT_PRESET_DIR):
            print(
                f"[LUT_MANAGER] Warning: LUT preset directory not found: {cls.LUT_PRESET_DIR}"
            )
            return lut_files

        # Recursively search for all .npy files
        pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.npy")
        npy_files = glob.glob(pattern, recursive=True)

        for file_path in npy_files:
            # Generate friendly display name
            rel_path = os.path.relpath(file_path, cls.LUT_PRESET_DIR)

            # Extract brand/folder name
            parts = Path(rel_path).parts
            if len(parts) > 1:
                # Has subfolder, format: Brand - Filename
                brand = parts[0]
                filename = Path(parts[-1]).stem  # Remove .npy extension
                display_name = f"{brand} - {filename}"
            else:
                # Root directory file, use filename directly
                display_name = Path(rel_path).stem

            lut_files[display_name] = file_path

        # Sort by name
        lut_files = dict(sorted(lut_files.items()))

        print(f"[LUT_MANAGER] Found {len(lut_files)} LUT presets")
        return lut_files

    @classmethod
    def get_lut_choices(cls):
        """
        Get LUT choice list (for Dropdown)

        Returns:
            list: Display name list
        """
        lut_files = cls.get_all_lut_files()
        return list(lut_files.keys())

    @classmethod
    def get_lut_path(cls, display_name):
        """
        Get LUT file path by display name

        Args:
            display_name: Display name

        Returns:
            str: File path, returns None if not found
        """
        lut_files = cls.get_all_lut_files()
        return lut_files.get(display_name)

    @classmethod
    def save_uploaded_lut(cls, uploaded_file, custom_name=None):
        """
        Save user-uploaded LUT file to preset folder

        Args:
            uploaded_file: Gradio uploaded file object
            custom_name: Custom filename (optional)

        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        if uploaded_file is None:
            return False, make_status_tag("lut_err_no_file"), cls.get_lut_choices()

        try:
            # Ensure preset folder exists
            custom_dir = os.path.join(cls.LUT_PRESET_DIR, "Custom")
            os.makedirs(custom_dir, exist_ok=True)

            # Get original filename
            original_name = Path(uploaded_file.name).stem

            # Use custom name or original name
            if custom_name and custom_name.strip():
                final_name = custom_name.strip()
            else:
                final_name = original_name

            # Ensure filename is safe
            final_name = "".join(
                c for c in final_name if c.isalnum() or c in (" ", "-", "_", "中", "文")
            )
            final_name = final_name.strip()

            if not final_name:
                final_name = "custom_lut"

            # Build target path
            dest_path = os.path.join(custom_dir, f"{final_name}.npy")

            # If file exists, add numeric suffix
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{final_name}_{counter}.npy")
                counter += 1

            # Copy file
            shutil.copy2(uploaded_file.name, dest_path)

            display_name = f"Custom - {Path(dest_path).stem}"

            print(f"[LUT_MANAGER] Saved uploaded LUT: {dest_path}")

            return (
                True,
                make_status_tag("lut_saved", name=display_name),
                cls.get_lut_choices(),
            )

        except Exception as e:
            print(f"[LUT_MANAGER] Error saving LUT: {e}")
            return (
                False,
                make_status_tag("lut_err_save_failed", error=str(e)),
                cls.get_lut_choices(),
            )

    @classmethod
    def delete_lut(cls, display_name):
        """
        Delete specified LUT preset

        Args:
            display_name: Display name

        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        file_path = cls.get_lut_path(display_name)

        if not file_path:
            return False, make_status_tag("lut_err_not_found"), cls.get_lut_choices()

        # Only allow deleting files in Custom folder
        if "Custom" not in file_path:
            return False, make_status_tag("lut_err_custom_only"), cls.get_lut_choices()

        try:
            os.remove(file_path)
            print(f"[LUT_MANAGER] Deleted LUT: {file_path}")
            return (
                True,
                make_status_tag("lut_deleted", name=display_name),
                cls.get_lut_choices(),
            )
        except Exception as e:
            print(f"[LUT_MANAGER] Error deleting LUT: {e}")
            return (
                False,
                make_status_tag("lut_err_delete_failed", error=str(e)),
                cls.get_lut_choices(),
            )

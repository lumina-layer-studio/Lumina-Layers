"""
Lumina Studio - Helper Functions
Helper functions module
"""

import zipfile
import re
from typing import List


def safe_fix_3mf_names(
    filepath: str, slot_names: List[str], create_assembly: bool = True
):
    """
    Fix object names in 3MF file and optionally create an assembly.
    Maps objects to slot_names in the order they appear in the file.

    Args:
        filepath: 3MF file path
        slot_names: Object name list
        create_assembly: Whether to create assembly
    """
    try:
        # Read original 3MF
        with zipfile.ZipFile(filepath, "r") as zf_in:
            files_data = {}
            for name in zf_in.namelist():
                files_data[name] = zf_in.read(name)

        # Find the 3D model file
        model_file = None
        for name in files_data:
            if name.endswith(".model") and "3D/" in name:
                model_file = name
                break

        if model_file and model_file in files_data:
            content = files_data[model_file].decode("utf-8")

            # Find all <object> tags with their IDs (in order of appearance)
            object_pattern = re.compile(r"<object\s+([^>]*)>", re.IGNORECASE)

            # Track which objects we've seen
            obj_info = []  # List of (start_pos, end_pos, full_tag, id)

            for match in object_pattern.finditer(content):
                attrs = match.group(1)
                id_match = re.search(r'\bid="(\d+)"', attrs)
                if id_match:
                    obj_id = id_match.group(1)
                    obj_info.append(
                        (match.start(), match.end(), match.group(0), obj_id)
                    )

            # Collect object IDs for assembly
            object_ids = [info[3] for info in obj_info]
            print(f"[DEBUG] Found {len(object_ids)} objects in 3MF: {object_ids}")

            # Process in reverse order to preserve positions (for name fixing)
            for idx, (start, end, old_tag, obj_id) in enumerate(reversed(obj_info)):
                real_idx = len(obj_info) - 1 - idx

                # [FIX] Use modulo to cycle through slot_names if there are more objects
                # This ensures all objects get a color name, even if there are multiple layers
                color_name = slot_names[real_idx % len(slot_names)]

                # Remove existing name attribute and add new one
                new_tag = re.sub(r'\s+name="[^"]*"', "", old_tag)
                new_tag = new_tag[:-1] + f' name="{color_name}">'

                content = content[:start] + new_tag + content[end:]

            # Create assembly if requested
            # Note: For vector mode with many objects, we skip assembly creation
            # to keep the 3MF structure simple and compatible with all slicers
            if create_assembly and len(object_ids) > 1:
                # Find the maximum object ID
                max_id = max(int(oid) for oid in object_ids)
                assembly_id = max_id + 1

                # Create assembly object XML
                components_xml = "\n".join(
                    [f'      <component objectid="{oid}" />' for oid in object_ids]
                )
                assembly_xml = f'''
  <object id="{assembly_id}" type="model" name="Lumina_Model">
    <components>
{components_xml}
    </components>
  </object>
'''

                # Insert assembly before </resources>
                resources_end = content.find("</resources>")
                if resources_end != -1:
                    content = (
                        content[:resources_end] + assembly_xml + content[resources_end:]
                    )
                    print(
                        f"[DEBUG] Created assembly with id={assembly_id}, containing {len(object_ids)} components"
                    )

                # Modify <build> section to only reference the assembly
                # Find and replace the build section
                build_pattern = re.compile(r"<build>.*?</build>", re.DOTALL)
                build_match = build_pattern.search(content)
                if build_match:
                    new_build = (
                        f'<build>\n    <item objectid="{assembly_id}" />\n  </build>'
                    )
                    content = (
                        content[: build_match.start()]
                        + new_build
                        + content[build_match.end() :]
                    )
                    print(f"[DEBUG] Updated build section to reference assembly")

            files_data[model_file] = content.encode("utf-8")

        # Write back
        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for name, data in files_data.items():
                zf_out.writestr(name, data)

        print(f"[DEBUG] 3MF file updated successfully: {filepath}")

    except Exception as e:
        print(f"Warning: Could not fix 3MF names: {e}")

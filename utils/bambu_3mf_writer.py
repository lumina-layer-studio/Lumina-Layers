"""
Lumina Studio - BambuStudio 3MF Writer
Enhanced 3MF export with BambuStudio-compatible metadata and configurations
"""

import os
import io
import sys
import zipfile
import xml.etree.ElementTree as ET
import json
import copy
from datetime import datetime
from typing import List, Dict, Optional
import trimesh
import numpy as np

_CONFIG_TEMPLATE_CACHE = None


class BambuStudio3MFWriter:
    """
    Enhanced 3MF writer with BambuStudio-compatible metadata.
    
    Features:
    - Embeds print settings (layer height, temperatures, speeds)
    - Adds color information to objects
    - Includes preview thumbnails
    - Compatible with BambuStudio/OrcaSlicer
    """
    
    # Default print settings (optimized for color layering)
    DEFAULT_SETTINGS = {
        'layer_height': '0.08',
        'initial_layer_height': '0.08',
        'wall_loops': '1',
        'top_shell_layers': '0',
        'bottom_shell_layers': '0',
        'sparse_infill_density': '100%',
        'sparse_infill_pattern': 'zig-zag',
        'nozzle_temperature': ['220', '220', '220', '220'],
        'bed_temperature': ['60', '60', '60', '60'],
        'filament_type': ['PLA', 'PLA', 'PLA', 'PLA'],
        'print_speed': '100',
        'travel_speed': '150',
        'enable_support': '0',
        'brim_width': '5',
        'brim_type': 'auto_brim',
    }
    
    def __init__(self, output_path: str, settings: Optional[Dict] = None, color_mode: str = '4-Color'):
        """
        Initialize 3MF writer.
        
        Args:
            output_path: Output .3mf file path
            settings: Optional custom print settings (overrides defaults)
            color_mode: Color mode ('4-Color', '6-Color', '8-Color', 'BW')
        """
        self.output_path = output_path
        self.settings = {**self.DEFAULT_SETTINGS, **(settings or {})}
        self.objects = []  # List of (mesh, name, color_rgb) tuples
        self.object_id_counter = 1
        self.color_mode = color_mode
        
    def add_mesh(self, mesh: trimesh.Trimesh, name: str, color_rgb: tuple):
        """
        Add a mesh object to the scene.
        
        Args:
            mesh: Trimesh object
            name: Object name (e.g., "White", "Cyan", "Magenta")
            color_rgb: RGB color tuple (0-255)
        """
        if mesh is None:
            raise ValueError(f"[BAMBU_3MF] Cannot add mesh '{name}': mesh is None")

        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        v_count = len(vertices) if vertices is not None else 0
        f_count = len(faces) if faces is not None else 0
        if v_count == 0 or f_count == 0:
            raise ValueError(
                f"[BAMBU_3MF] Cannot add mesh '{name}': empty geometry (v={v_count}, f={f_count})"
            )

        self.objects.append((mesh, name, color_rgb))
        
    def export(self):
        """
        Export all meshes to a BambuStudio-compatible 3MF file.
        
        Returns:
            str: Path to the exported 3MF file
        """
        if len(self.objects) == 0:
            raise ValueError("[BAMBU_3MF] Refusing to export 3MF: no mesh objects were added")

        print(f"[BAMBU_3MF] Exporting {len(self.objects)} objects to {self.output_path}")
        
        # Create a temporary directory for 3MF contents
        import tempfile
        import shutil
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Create directory structure
            os.makedirs(os.path.join(tmpdir, '3D', 'Objects'), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, '3D', '_rels'), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, 'Metadata'), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, '_rels'), exist_ok=True)
            
            # 2. Write [Content_Types].xml
            self._write_content_types(tmpdir)
            
            # 3. Write _rels/.rels
            self._write_root_rels(tmpdir)
            
            # 4. Write 3D/3dmodel.model (main assembly file)
            self._write_main_model(tmpdir)
            
            # 5. Write 3D/_rels/3dmodel.model.rels
            self._write_model_rels(tmpdir)
            
            # 6. Write Metadata files
            self._write_metadata_files(tmpdir)
            
            # 7. Package everything into a ZIP file
            self._create_zip(tmpdir, include_object_model=True)
        
        print(f"[BAMBU_3MF] [OK] Export complete: {self.output_path}")
        return self.output_path
    
    def _write_content_types(self, tmpdir: str):
        """Write [Content_Types].xml"""
        content = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Default Extension="jpeg" ContentType="image/jpeg"/>
  <Default Extension="config" ContentType="text/xml"/>
  <Default Extension="json" ContentType="application/json"/>
</Types>'''
        
        with open(os.path.join(tmpdir, '[Content_Types].xml'), 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _write_root_rels(self, tmpdir: str):
        """Write _rels/.rels with thumbnail relationships"""
        content = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>'''
        
        with open(os.path.join(tmpdir, '_rels', '.rels'), 'w', encoding='utf-8') as f:
            f.write(content)
    
    def _write_main_model(self, tmpdir: str):
        """Write 3D/3dmodel.model - matching LD format exactly (no UUIDs)"""
        assembly_id = len(self.objects) + 1
        
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<model unit="millimeter" xml:lang="en-US" requiredextensions="p" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">',
            f' <metadata name="Application">BambuStudio-02.04.00.70</metadata>',
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
            f' <metadata name="CreationDate">{datetime.now().strftime("%Y-%m-%d")}</metadata>',
            ' <resources>',
            f'  <object id="{assembly_id}" type="model">',
            '   <components>',
        ]
        
        # Add components - NO UUIDs, NO transforms (matching LD exactly)
        for idx in range(1, len(self.objects) + 1):
            xml_lines.append(
                f'    <component objectid="{idx}" p:path="/3D/Objects/object_1.model"/>'
            )
        
        xml_lines.extend([
            '   </components>',
            '  </object>',
            ' </resources>',
            ' <build>',
            f'  <item objectid="{assembly_id}"/>',
            ' </build>',
            '</model>',
        ])
        
        xml_content = '\n'.join(xml_lines)
        
        with open(os.path.join(tmpdir, '3D', '3dmodel.model'), 'w', encoding='utf-8') as f:
            f.write(xml_content)
    
    def _write_model_rels(self, tmpdir: str):
        """Write 3D/_rels/3dmodel.model.rels"""
        rels_content = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>'''
        
        with open(os.path.join(tmpdir, '3D', '_rels', '3dmodel.model.rels'), 'w', encoding='utf-8') as f:
            f.write(rels_content)
    
    def _write_object_files(self, tmpdir: str):
        """Write object_1.model - matching LD format (no UUIDs), streaming I/O for large meshes."""
        output_path = os.path.join(tmpdir, '3D', 'Objects', 'object_1.model')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" unit="millimeter" xml:lang="en-US" requiredextensions="p">\n')
            f.write(' <resources>\n')

            for idx, (mesh, name, color_rgb) in enumerate(self.objects, start=1):
                f.write(f'  <object id="{idx}" type="model">\n')
                f.write('   <mesh>\n')
                f.write('    <vertices>\n')
                self._write_vertices_stream(f, mesh.vertices)
                f.write('    </vertices>\n')
                f.write('    <triangles>\n')
                self._write_triangles_stream(f, mesh.faces)

                f.write('    </triangles>\n')
                f.write('   </mesh>\n')
                f.write('  </object>\n')

            f.write(' </resources>\n')
            f.write(' <build/>\n')
            f.write('</model>\n')

    @staticmethod
    def _write_vertices_stream(stream, vertices):
        if len(vertices) == 0:
            return
        verts = np.asarray(vertices, dtype=np.float64)
        x = np.char.mod('%.4f', verts[:, 0])
        y = np.char.mod('%.4f', verts[:, 1])
        z = np.char.mod('%.4f', verts[:, 2])
        chunk = 200000
        total = len(verts)
        for i in range(0, total, chunk):
            j = min(i + chunk, total)
            lines = '     <vertex x="' + x[i:j] + '" y="' + y[i:j] + '" z="' + z[i:j] + '"/>\n'
            stream.writelines(lines.tolist())

    @staticmethod
    def _write_triangles_stream(stream, faces):
        if len(faces) == 0:
            return
        f = np.asarray(faces, dtype=np.int64)
        v1 = np.char.mod('%d', f[:, 0])
        v2 = np.char.mod('%d', f[:, 1])
        v3 = np.char.mod('%d', f[:, 2])
        chunk = 200000
        total = len(f)
        for i in range(0, total, chunk):
            j = min(i + chunk, total)
            lines = '     <triangle v1="' + v1[i:j] + '" v2="' + v2[i:j] + '" v3="' + v3[i:j] + '"/>\n'
            stream.writelines(lines.tolist())

    @staticmethod
    def _write_vertices_bytes(raw, vertices):
        """Write vertices as ASCII bytes directly to a binary stream (no TextIOWrapper).
        Uses %.2f (0.01 mm precision) — safe since printer resolution is 0.1 mm.
        Batches chunks into one encode() call to minimise Python overhead."""
        if len(vertices) == 0:
            return
        verts = np.asarray(vertices, dtype=np.float64)
        x = np.char.mod('%.2f', verts[:, 0])
        y = np.char.mod('%.2f', verts[:, 1])
        z = np.char.mod('%.2f', verts[:, 2])
        chunk = 100_000
        total = len(verts)
        for i in range(0, total, chunk):
            j = min(i + chunk, total)
            lines = '     <vertex x="' + x[i:j] + '" y="' + y[i:j] + '" z="' + z[i:j] + '"/>\n'
            raw.write(''.join(lines.tolist()).encode('ascii'))

    @staticmethod
    def _write_triangles_bytes(raw, faces):
        """Write triangles as ASCII bytes directly to a binary stream."""
        if len(faces) == 0:
            return
        f = np.asarray(faces, dtype=np.int64)
        v1 = np.char.mod('%d', f[:, 0])
        v2 = np.char.mod('%d', f[:, 1])
        v3 = np.char.mod('%d', f[:, 2])
        chunk = 100_000
        total = len(f)
        for i in range(0, total, chunk):
            j = min(i + chunk, total)
            lines = '     <triangle v1="' + v1[i:j] + '" v2="' + v2[i:j] + '" v3="' + v3[i:j] + '"/>\n'
            raw.write(''.join(lines.tolist()).encode('ascii'))

    @staticmethod
    def _format_vertices(vertices):
        if len(vertices) == 0:
            return []
        verts = np.asarray(vertices, dtype=np.float64)
        x = np.char.mod('%.6f', verts[:, 0])
        y = np.char.mod('%.6f', verts[:, 1])
        z = np.char.mod('%.6f', verts[:, 2])
        lines = (
            '     <vertex x="'
            + x
            + '" y="'
            + y
            + '" z="'
            + z
            + '"/>'
        )
        return lines.tolist()

    @staticmethod
    def _format_triangles(faces):
        if len(faces) == 0:
            return []
        f = np.asarray(faces, dtype=np.int64)
        v1 = np.char.mod('%d', f[:, 0])
        v2 = np.char.mod('%d', f[:, 1])
        v3 = np.char.mod('%d', f[:, 2])
        lines = (
            '     <triangle v1="'
            + v1
            + '" v2="'
            + v2
            + '" v3="'
            + v3
            + '"/>'
        )
        return lines.tolist()

    def _write_single_object(self, tmpdir: str, obj_id: int, mesh: trimesh.Trimesh, name: str, color_rgb: tuple):
        """Write a single object .model file - matching BambuStudio format exactly"""
        
        # Build XML manually for exact control
        xml_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">',
            ' <resources>',
            f'  <object id="{obj_id}" p:UUID="{self._generate_uuid()}" type="model">',
            '   <mesh>',
            '    <vertices>',
        ]
        
        # Add vertices with color
        r, g, b = color_rgb
        for vertex in mesh.vertices:
            xml_lines.append(
                f'     <vertex x="{vertex[0]:.6f}" y="{vertex[1]:.6f}" z="{vertex[2]:.6f}" '
                f'r="{r}" g="{g}" b="{b}"/>'
            )
        
        xml_lines.append('    </vertices>')
        xml_lines.append('    <triangles>')
        
        # Add triangles
        for face in mesh.faces:
            xml_lines.append(
                f'     <triangle v1="{face[0]}" v2="{face[1]}" v3="{face[2]}"/>'
            )
        
        xml_lines.extend([
            '    </triangles>',
            '   </mesh>',
            '  </object>',
            ' </resources>',
            f' <build p:UUID="{self._generate_uuid()}">',
            f'  <item objectid="{obj_id}" p:UUID="{self._generate_uuid()}"/>',
            ' </build>',
            '</model>',
        ])
        
        xml_content = '\n'.join(xml_lines)
        
        output_path = os.path.join(tmpdir, '3D', 'Objects', f'object_{obj_id}.model')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
    
    def _write_metadata_files(self, tmpdir: str):
        """Write metadata configuration files"""
        # 1. model_settings.config
        self._write_model_settings(tmpdir)
        
        # 2. project_settings.config (print settings)
        self._write_project_settings(tmpdir)
        
        # 3. slice_info.config
        self._write_slice_info(tmpdir)
        
        # 4. filament_sequence.json
        self._write_filament_sequence(tmpdir)
        
        # 5. cut_information.xml
        self._write_cut_information(tmpdir)
    
    def _write_model_settings(self, tmpdir: str):
        """Write model_settings.config with minimal metadata - let BambuStudio auto-center"""
        config = ET.Element('config')
        
        # Add assembly object metadata
        assembly_id = len(self.objects) + 1
        obj_elem = ET.SubElement(config, 'object', attrib={'id': str(assembly_id)})
        
        # Add a separate part for EACH object with MINIMAL metadata
        # No matrix/position info - let BambuStudio auto-center the model
        for idx, (mesh, name, color_rgb) in enumerate(self.objects, start=1):
            part = ET.SubElement(obj_elem, 'part', attrib={'id': str(idx), 'subtype': 'normal_part'})
            
            # Part name
            ET.SubElement(part, 'metadata', attrib={'key': 'name', 'value': name})
            
            # CRITICAL: Extruder assignment (this is what matters for color mapping)
            ET.SubElement(part, 'metadata', attrib={'key': 'extruder', 'value': str(idx)})
        
        # Add plate info with filament mapping
        plate = ET.SubElement(config, 'plate')
        ET.SubElement(plate, 'metadata', attrib={'key': 'plater_id', 'value': '1'})
        ET.SubElement(plate, 'metadata', attrib={'key': 'plater_name', 'value': ''})
        ET.SubElement(plate, 'metadata', attrib={'key': 'locked', 'value': 'false'})
        ET.SubElement(plate, 'metadata', attrib={'key': 'filament_map_mode', 'value': 'Auto For Flush'})
        
        # Model instance (minimal - no position info)
        model_instance = ET.SubElement(plate, 'model_instance')
        ET.SubElement(model_instance, 'metadata', attrib={'key': 'object_id', 'value': str(assembly_id)})
        ET.SubElement(model_instance, 'metadata', attrib={'key': 'instance_id', 'value': '0'})
        ET.SubElement(model_instance, 'metadata', attrib={'key': 'identify_id', 'value': '1'})
        
        # NO assemble section - let BambuStudio auto-center
        
        # Write to file
        tree = ET.ElementTree(config)
        ET.indent(tree, space='  ')
        
        with open(os.path.join(tmpdir, 'Metadata', 'model_settings.config'), 'wb') as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            tree.write(f, encoding='utf-8', xml_declaration=False)
    
    def _get_base_config_template(self):
        """
        Get complete BambuStudio configuration template with all 538+ keys.
        
        Returns:
            dict: Complete configuration template
        """
        # Load the reference configuration template
        # In frozen mode (PyInstaller), use sys._MEIPASS as base directory
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            template_path = os.path.join(sys._MEIPASS, 'bambu_config_template.json')
        else:
            template_path = os.path.join(os.path.dirname(__file__), '..', 'bambu_config_template.json')
        
        global _CONFIG_TEMPLATE_CACHE
        if os.path.exists(template_path):
            if _CONFIG_TEMPLATE_CACHE is None:
                with open(template_path, 'r', encoding='utf-8') as f:
                    _CONFIG_TEMPLATE_CACHE = json.load(f)
            return copy.deepcopy(_CONFIG_TEMPLATE_CACHE)
        else:
            # Fallback: return minimal config if template not found
            print("[WARNING] bambu_config_template.json not found, using minimal config")
            return self._get_minimal_config_template()
    
    def _get_minimal_config_template(self):
        """Fallback minimal configuration template."""
        return {
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
            'nozzle_temperature': ['220'] * 8,
            'nozzle_temperature_initial_layer': ['220'] * 8,
        }
    
    def _build_filament_arrays(self, num_colors: int, color_conf: dict):
        """
        Build filament-related arrays with length matching num_colors.
        
        Args:
            num_colors: Number of colors in the mode (2, 4, 6, or 8)
            color_conf: ColorSystem configuration dict
        
        Returns:
            dict: Filament arrays with correct lengths
        """
        arrays = {}
        
        # CRITICAL: Build color arrays from ACTUAL meshes added, not from color_conf
        # This ensures colors match the actual objects in the model
        arrays['filament_colour'] = []
        for mesh, name, color_rgb in self.objects:
            # Convert RGB to hex
            hex_color = f"#{color_rgb[0]:02X}{color_rgb[1]:02X}{color_rgb[2]:02X}"
            arrays['filament_colour'].append(hex_color)
        
        # ALL filament arrays MUST have length = num_colors (not 8!)
        arrays['filament_settings_id'] = ['Bambu PLA Basic @BBL H2D'] * num_colors
        arrays['filament_type'] = ['PLA'] * num_colors
        arrays['filament_vendor'] = ['Bambu Lab'] * num_colors
        arrays['filament_ids'] = ['GFA00'] * num_colors
        arrays['filament_cost'] = ['24.99'] * num_colors
        arrays['filament_density'] = ['1.26'] * num_colors
        arrays['filament_diameter'] = ['1.75'] * num_colors
        arrays['filament_colour_type'] = ['1'] * num_colors
        arrays['filament_map'] = ['1'] * num_colors
        
        # Temperature arrays
        arrays['nozzle_temperature'] = ['220'] * num_colors
        arrays['nozzle_temperature_initial_layer'] = ['220'] * num_colors
        arrays['nozzle_temperature_range_low'] = ['190'] * num_colors
        arrays['nozzle_temperature_range_high'] = ['240'] * num_colors
        arrays['bed_temperature'] = ['60'] * num_colors
        arrays['bed_temperature_initial_layer'] = ['60'] * num_colors
        
        # Other filament properties
        arrays['filament_flow_ratio'] = ['1'] * num_colors
        arrays['filament_max_volumetric_speed'] = ['15'] * num_colors
        arrays['filament_minimal_purge_on_wipe_tower'] = ['15'] * num_colors
        arrays['filament_soluble'] = ['0'] * num_colors
        arrays['filament_is_support'] = ['0'] * num_colors
        
        return arrays
    
    def _write_project_settings(self, tmpdir: str):
        """Write project_settings.config with complete configuration."""
        from config import ColorSystem
        
        # Get color configuration
        color_conf = ColorSystem.get(self.color_mode)
        num_colors = len(self.objects)  # Use actual number of objects
        
        # Load complete base configuration template (538+ keys)
        settings = self._get_base_config_template()
        
        # Build filament arrays with correct length
        filament_arrays = self._build_filament_arrays(num_colors, color_conf)
        
        # CRITICAL: Update ALL array fields in settings to match num_colors
        # Go through all keys in settings and resize arrays
        for key, value in settings.items():
            if isinstance(value, list) and len(value) > 0:
                # Check if this is a filament-related array (starts with 'filament_' or contains temperature/fan settings)
                if (key.startswith('filament_') or 
                    key in ['nozzle_temperature', 'nozzle_temperature_initial_layer', 
                           'nozzle_temperature_range_low', 'nozzle_temperature_range_high',
                           'bed_temperature', 'bed_temperature_initial_layer',
                           'activate_air_filtration', 'additional_cooling_fan_speed',
                           'chamber_temperatures', 'close_fan_the_first_x_layers',
                           'complete_print_exhaust_fan_speed', 'cool_plate_temp',
                           'cool_plate_temp_initial_layer', 'during_print_exhaust_fan_speed',
                           'eng_plate_temp', 'eng_plate_temp_initial_layer',
                           'fan_cooling_layer_time', 'fan_max_speed', 'fan_min_speed',
                           'hot_plate_temp', 'hot_plate_temp_initial_layer',
                           'textured_plate_temp', 'textured_plate_temp_initial_layer']):
                    # Resize array to num_colors
                    if len(value) != num_colors:
                        # Take first element as template
                        template_value = value[0] if value else '0'
                        settings[key] = [template_value] * num_colors
        
        # Apply filament arrays (this will override the resized arrays with correct values)
        settings.update(filament_arrays)
        
        # CRITICAL: Set these keys for multi-material support
        settings['single_extruder_multi_material'] = '1'
        settings['enable_prime_tower'] = '1'
        
        # Apply user-provided settings overrides (if any)
        if self.settings:
            for key in ['layer_height', 'initial_layer_height', 'wall_loops',
                       'top_shell_layers', 'bottom_shell_layers', 
                       'sparse_infill_density', 'sparse_infill_pattern',
                       'print_speed', 'travel_speed', 'enable_support',
                       'brim_width', 'brim_type']:
                if key in self.settings:
                    settings[key] = self.settings[key]
        
        # Write complete configuration to file
        with open(os.path.join(tmpdir, 'Metadata', 'project_settings.config'), 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    
    def _write_slice_info(self, tmpdir: str):
        """Write slice_info.config"""
        config = ET.Element('config')
        
        header = ET.SubElement(config, 'header')
        ET.SubElement(header, 'header_item', attrib={'key': 'X-BBL-Client-Type', 'value': 'slicer'})
        ET.SubElement(header, 'header_item', attrib={'key': 'X-BBL-Client-Version', 'value': 'Lumina-1.6.7'})
        
        tree = ET.ElementTree(config)
        ET.indent(tree, space='  ')
        
        with open(os.path.join(tmpdir, 'Metadata', 'slice_info.config'), 'wb') as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            tree.write(f, encoding='utf-8', xml_declaration=False)
    
    def _write_filament_sequence(self, tmpdir: str):
        """Write filament_sequence.json"""
        import json
        
        data = {'plate_1': {'sequence': []}}
        
        with open(os.path.join(tmpdir, 'Metadata', 'filament_sequence.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    
    def _write_cut_information(self, tmpdir: str):
        """Write cut_information.xml"""
        config = ET.Element('objects')
        
        # Add object with cut_id (matching standard format)
        obj = ET.SubElement(config, 'object', attrib={'id': '1'})
        ET.SubElement(obj, 'cut_id', attrib={
            'id': '0',
            'check_sum': '1',
            'connectors_cnt': '0'
        })
        
        tree = ET.ElementTree(config)
        ET.indent(tree, space=' ')
        
        with open(os.path.join(tmpdir, 'Metadata', 'cut_information.xml'), 'wb') as f:
            f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
            tree.write(f, encoding='utf-8', xml_declaration=False)
    
    def _write_object_file_to_zip(self, zf: zipfile.ZipFile):
        """Stream mesh data directly into ZIP with DEFLATE compression and ZIP64 support.
        将 mesh 数据以流式方式直接写入 ZIP，启用 DEFLATE 压缩和 ZIP64 大文件支持。
        """
        # Use ZipInfo to enable DEFLATE compression for the streamed entry.
        # zf.open('name', 'w') alone defaults to ZIP_STORED (no compression),
        # which causes "file size too large" errors on large models (>2 GiB).
        zi = zipfile.ZipInfo('3D/Objects/object_1.model')
        zi.compress_type = zipfile.ZIP_DEFLATED
        with zf.open(zi, 'w', force_zip64=True) as raw:
            raw.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            raw.write(b'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" unit="millimeter" xml:lang="en-US" requiredextensions="p">\n')
            raw.write(b' <resources>\n')

            for idx, (mesh, name, color_rgb) in enumerate(self.objects, start=1):
                raw.write(f'  <object id="{idx}" type="model">\n'.encode())
                raw.write(b'   <mesh>\n    <vertices>\n')
                self._write_vertices_bytes(raw, mesh.vertices)
                raw.write(b'    </vertices>\n    <triangles>\n')
                self._write_triangles_bytes(raw, mesh.faces)
                raw.write(b'    </triangles>\n   </mesh>\n  </object>\n')

            raw.write(b' </resources>\n <build/>\n</model>\n')

    def _create_zip(self, tmpdir: str, include_object_model: bool = False):
        """Package all files into a ZIP archive (.3mf)"""
        with zipfile.ZipFile(self.output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmpdir):
                for file in files:
                    if include_object_model and file == 'object_1.model':
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmpdir)
                    with open(file_path, 'rb') as f:
                        zf.writestr(arcname, f.read())
            if include_object_model:
                self._write_object_file_to_zip(zf)
    
    @staticmethod
    def _generate_uuid() -> str:
        """Generate a UUID for 3MF objects"""
        import uuid
        return str(uuid.uuid4())


def export_scene_with_bambu_metadata(scene: trimesh.Scene, output_path: str,
                                     slot_names: List[str], preview_colors: Dict,
                                     settings: Optional[Dict] = None, color_mode: str = '4-Color'):
    """
    Export a Trimesh scene to BambuStudio-compatible 3MF with metadata.
    
    Args:
        scene: Trimesh Scene object containing all meshes
        output_path: Output .3mf file path
        slot_names: List of ACTUALLY USED material names (e.g., ['White', 'Cyan', 'Magenta', 'Yellow'])
        preview_colors: Dict mapping material IDs to RGBA colors (full color system)
        settings: Optional custom print settings
        color_mode: Color mode ('4-Color', '6-Color', '8-Color', 'BW')
    
    Returns:
        str: Path to the exported 3MF file
    """
    if scene is None:
        raise ValueError("[BAMBU_3MF] Scene is None")
    if not slot_names:
        raise ValueError("[BAMBU_3MF] slot_names is empty - no exportable objects")

    # CRITICAL: Use actual number of colors, not the LUT color mode
    # This ensures filament list matches actual model parts
    num_used_colors = len(slot_names)
    
    # Map actual usage to color mode
    if num_used_colors <= 2:
        actual_color_mode = 'BW'
    elif num_used_colors <= 4:
        actual_color_mode = '4-Color'
    elif num_used_colors <= 6:
        actual_color_mode = '6-Color'
    else:
        actual_color_mode = '8-Color'
    
    print(f"[BAMBU_3MF] LUT color_mode: {color_mode}, Actual colors used: {num_used_colors} → 3MF mode: {actual_color_mode}")
    
    writer = BambuStudio3MFWriter(output_path, settings, actual_color_mode)
    
    # Build a mapping from slot_name to preview_color
    # We need to find the original material ID for each slot_name
    from config import ColorSystem
    full_color_conf = ColorSystem.get(color_mode)
    full_slot_names = full_color_conf['slots']
    
    # Create name-to-color mapping from original material IDs
    name_to_color = {}
    for slot_name in slot_names:
        # Find this slot_name in the full color system
        for mat_id, full_name in enumerate(full_slot_names):
            if slot_name == full_name or slot_name in full_name or full_name in slot_name:
                if mat_id in preview_colors:
                    name_to_color[slot_name] = tuple(preview_colors[mat_id][:3])
                    break
        
        # Fallback: "Board" is the SVG backing plate (always white); other
        # unrecognised names fall back to gray.
        if slot_name not in name_to_color:
            if slot_name == "Board" and 0 in preview_colors:
                name_to_color[slot_name] = tuple(preview_colors[0][:3])
            else:
                name_to_color[slot_name] = (200, 200, 200)
    
    print(f"[BAMBU_3MF] Color mapping: {list(name_to_color.keys())}")
    
    # Add each mesh from the scene IN THE ORDER OF slot_names.
    # Use strict exact-name matching to avoid accidental substring collisions.
    unmatched = []
    for slot_name in slot_names:
        mesh = scene.geometry.get(slot_name)
        if mesh is None:
            unmatched.append(slot_name)
            continue

        color_rgb = name_to_color.get(slot_name, (200, 200, 200))
        writer.add_mesh(mesh, slot_name, color_rgb)
        print(f"[BAMBU_3MF] Added mesh '{slot_name}' with color {color_rgb}")

    if unmatched:
        raise ValueError(
            "[BAMBU_3MF] Missing geometries for slot names: " + ", ".join(unmatched)
        )
    
    return writer.export()


def inject_bambu_metadata(filepath: str, settings: Optional[Dict],
                          slot_names: List[str], preview_colors: Dict,
                          color_mode: str = '4-Color'):
    """
    Inject BambuStudio metadata into an existing 3MF file (exported by trimesh).

    Opens the 3MF ZIP, adds Metadata/ files (print settings, filament config,
    model settings, etc.), and re-saves. The original geometry is untouched.
    """
    import json as _json
    from config import ColorSystem

    # Create a temporary writer to reuse metadata generation logic
    writer = BambuStudio3MFWriter(filepath, settings, color_mode)

    # Build a dummy objects list so filament arrays have correct length
    color_conf = ColorSystem.get(color_mode)
    full_slot_names = color_conf.get('slots', [])
    for slot_name in slot_names:
        color_rgb = (200, 200, 200)
        for mat_id, full_name in enumerate(full_slot_names):
            if slot_name == full_name or slot_name in full_name or full_name in slot_name:
                if mat_id in preview_colors:
                    color_rgb = tuple(preview_colors[mat_id][:3])
                    break
        writer.objects.append((None, slot_name, color_rgb))

    # Generate metadata content in a temp dir, then inject into the 3MF ZIP
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, 'Metadata'), exist_ok=True)
        writer._write_metadata_files(tmpdir)

        # Read existing 3MF contents
        existing_files = {}
        with zipfile.ZipFile(filepath, 'r') as zf:
            for name in zf.namelist():
                existing_files[name] = zf.read(name)

        # Add metadata files
        for root, _dirs, files in os.walk(os.path.join(tmpdir, 'Metadata')):
            for fname in files:
                full_path = os.path.join(root, fname)
                arcname = 'Metadata/' + fname
                with open(full_path, 'rb') as f:
                    existing_files[arcname] = f.read()

        # Re-write ZIP with original geometry + new metadata
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, data in existing_files.items():
                zf.writestr(name, data)

    print(f"[BAMBU_3MF] Injected BambuStudio metadata into {filepath}")

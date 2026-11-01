"""Real writer-produced puzzle sources through the shared Fat Cat merge path.

Replaces hand-built legacy template fixtures: geometry, material identity,
unknown user fields, range XML, and final package descriptors all come from
actual supported source exports.
"""
from __future__ import annotations

import json
import io
from PIL import Image
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import pytest
import trimesh

from core.puzzle_3mf import PuzzlePiece3MFSource, assemble_puzzle_3mf
from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import (
    build_builtin_project_settings_request, compose_builtin_project_settings,
    read_source_metadata, select_metadata_target,
)
from utils.merged_bambu_3mf_writer import MaterialSlot

TARGETS = [('BambuStudio', 'bambu-h2d'), ('OrcaSlicer', 'bambu-h2d'),
           ('SnapmakerOrca', 'snapmaker-u1')]
PALETTE = ['Color', 'Unused', 'Backing']
COLORS = [(255, 0, 0), (0, 0, 0), (255, 255, 255)]


def _write_piece(path: Path, *, slicer: str, printer: str, density: int,
                 modifier: bool, user_source: bool = True) -> None:
    target = select_metadata_target(slicer=slicer, printer_id=printer,
        nozzle_size='0.4', device_profile_id=None, build_plate_id=None)
    materials = [{'name': name, 'colour': '#%02X%02X%02X' % color, 'material_type': 'PLA'}
                 for name, color in zip(PALETTE, COLORS)]
    project = json.loads(compose_builtin_project_settings(
        build_builtin_project_settings_request({}, materials, target=target))['project_settings_json'])
    project['nozzle_temperature'] = ['217', '226', '235']
    project['filament_flow_ratio'] = ['0.97', '1.03', '1.01']
    project['vendor_opaque_process'] = {'custom': ['retain', 17]}
    project['vendor_opaque_array'] = ['a', 'b', 'c']
    project['precise_outer_wall'] = '1'
    writer = BambuStudio3MFWriter(output_path=str(path), settings={'layer_height': .08, 'initial_layer_print_height': .08},
        printer_id=printer, slicer=slicer, nozzle_size='0.4',
        base_height_mm=4.8, color_height_mm=0.4, face_orientation='down',
        backing_infill_density_percent=density,
        enable_base_layer_height_modifier=modifier)
    if user_source:
        writer._custom_template = project
    writer._set_project_palette(PALETTE, dict(zip(PALETTE, COLORS)))
    color = trimesh.creation.box(extents=(16, 16, .4))
    color.apply_translation((8, 8, .2))
    backing = trimesh.creation.box(extents=(16, 16, 4.8))
    backing.apply_translation((8, 8, 2.8))
    writer.add_mesh(color, PALETTE[0], COLORS[0])
    writer.add_mesh(backing, PALETTE[2], COLORS[2])
    writer.export()


def _overview():
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), (230, 180, 90)).save(buffer, format='PNG')
    return buffer.getvalue()


def _project(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('Metadata/project_settings.config'))


def _ranges(path):
    with zipfile.ZipFile(path) as archive:
        if 'Metadata/layer_config_ranges.xml' not in archive.namelist():
            return None
        return ET.fromstring(archive.read('Metadata/layer_config_ranges.xml'))


@pytest.mark.parametrize('slicer,printer', TARGETS)
@pytest.mark.parametrize('modifier', [False, True])
@pytest.mark.parametrize('density', [20, 100])
def test_real_puzzle_preserves_user_process_slots_and_local_height_ranges(
    tmp_path, slicer, printer, modifier, density,
):
    """XY assembly cannot discard Z ranges or reconstruct materials from names."""
    sources = [tmp_path/'A1.3mf', tmp_path/'A2.3mf']
    for path in sources:
        _write_piece(path, slicer=slicer, printer=printer, density=density, modifier=modifier)
    output = tmp_path/'puzzle.3mf'
    target = select_metadata_target(slicer=slicer, printer_id=printer,
        nozzle_size='0.4', device_profile_id=None, build_plate_id=None)
    assemble_puzzle_3mf(
        piece_sources=[PuzzlePiece3MFSource('A1', str(sources[0]), 0, 0),
         PuzzlePiece3MFSource('A2', str(sources[1]), 20, 0)],
        piece_slots=[tuple(MaterialSlot(**slot)
            for slot in read_source_metadata(path, target=target)['slots'])
            for path in sources],
        output_path=str(output), preview_colors=dict(zip(PALETTE, COLORS)),
        slot_names=PALETTE, printer_id=printer, nozzle_size='0.4',
        slot_index_by_name=None, device_profile_id=None, build_plate_id=None,
        metadata_target=target,
        overview_png_bytes=_overview(),
    )
    first, final = _project(sources[0]), _project(output)
    for key in ['nozzle_temperature', 'filament_flow_ratio', 'vendor_opaque_process',
                'vendor_opaque_array', 'precise_outer_wall', 'sparse_infill_density']:
        assert final[key] == first[key], key
    assert final['sparse_infill_density'] == f'{density}%'
    assert len(final['filament_settings_id']) == 3
    assert final['filament_colour'] == ['#FF0000', '#000000', '#FFFFFF']
    before, after = _ranges(sources[0]), _ranges(output)
    if before is None:
        assert after is None
    else:
        assert after is not None
        source_ranges = [ET.tostring(r) for r in before.find('object').findall('range')]
        objects = after.findall('object')
        assert len(objects) == 2
        assert len({o.get('id') for o in objects}) == 2
        for obj in objects:
            assert [ET.tostring(r) for r in obj.findall('range')] == source_ranges
        if density < 100:
            assert any(o.text == '100%' for o in after.findall('.//option[@opt_key="sparse_infill_density"]'))
        assert any(float(option.text) > .08 + 1e-6
                   for option in after.findall('.//option[@opt_key="layer_height"]')) is modifier
    with zipfile.ZipFile(output) as archive:
        root = ET.fromstring(archive.read('Metadata/model_settings.config'))
        parts = root.findall('.//part')
        assert len(parts) == 4
        # Each backing uses original palette slot 2 => native extruder 3.
        extruders = [m.get('value') for m in root.findall('.//part/metadata[@key="extruder"]')]
        assert extruders.count('3') == 2
        assert extruders.count('1') == 2
        assert 'Metadata/plate_1.png' in archive.namelist()
        model = ET.fromstring(archive.read('3D/3dmodel.model'))
        items = model.findall('.//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}item')
        assert len(items) == 2
        assert len({i.get('objectid') for i in items}) == 2
        translations = [list(map(float, i.get('transform').split()))[-3:] for i in items]
        assert translations[1][0] - translations[0][0] == pytest.approx(20)
        assert all(t[2] == 0 for t in translations)


@pytest.mark.parametrize('slicer,printer', TARGETS)
def test_real_puzzle_can_disable_final_tower_planning(tmp_path, slicer, printer):
    source, output = tmp_path/'piece.3mf', tmp_path/'puzzle.3mf'
    _write_piece(source, slicer=slicer, printer=printer, density=20, modifier=True)
    target = select_metadata_target(slicer=slicer, printer_id=printer,
        nozzle_size='0.4', device_profile_id=None, build_plate_id=None)
    assemble_puzzle_3mf(piece_sources=[PuzzlePiece3MFSource('A1', str(source), 0, 0)],
        piece_slots=[tuple(MaterialSlot(**slot)
            for slot in read_source_metadata(source, target=target)['slots'])],
        output_path=str(output), preview_colors=dict(zip(PALETTE, COLORS)),
        slot_names=PALETTE, printer_id=printer, nozzle_size='0.4',
        slot_index_by_name=None, device_profile_id=None, build_plate_id=None,
        overview_png_bytes=None, metadata_target=target,
        enable_wipe_tower_auto_placement=False)
    with zipfile.ZipFile(output) as archive:
        placement = json.loads(archive.read('Metadata/lumina_wipe_tower_placement.json'))
    assert placement['enabled'] is False
    assert _project(output)['enable_prime_tower'] == '1'
    assert _ranges(output) is not None

_NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}

def _metadata_value(element, key):
    return next((row.get("value") for row in element.findall("metadata") if row.get("key") == key), None)

@pytest.mark.parametrize("material_index", [1, 2, 3])
@pytest.mark.parametrize("numbered_names", [False, True])
@pytest.mark.parametrize("slicer,printer_id", [
    ("BambuStudio", "bambu-h2d"),
    ("OrcaSlicer", "bambu-h2d"),
    ("SnapmakerOrca", "snapmaker-u1"),
])
def test_single_material_piece_object_uses_its_global_extruder(
    tmp_path: Path, material_index: int, numbered_names: bool, slicer: str, printer_id: str,
) -> None:
    """Slicers must retain the material when collapsing a one-volume object."""

    slot_names = ["赛纳PLA蓝色", "纵维立方PLA红色", "赛纳PLA黄色", "Bambu PLA Basic 玉石白"]
    if numbered_names:
        # A merged palette can retain slot numbers from its original LUTs.
        slot_names = [f"Slot {4 - index} ({name})" for index, name in enumerate(slot_names)]
    palette = [(47, 49, 129), (182, 61, 68), (248, 224, 65), (255, 254, 252)]
    material_name = slot_names[material_index]
    piece_path = tmp_path / "single-material-piece.3mf"
    output_path = tmp_path / "puzzle.3mf"
    writer = BambuStudio3MFWriter(
        str(piece_path), printer_id=printer_id, slicer=slicer,
        enable_base_layer_height_modifier=False,
        enable_wipe_tower_auto_placement=False,
    )
    writer.add_mesh(trimesh.creation.box(extents=(10, 10, 2)), material_name, palette[material_index])
    writer.export()

    target = select_metadata_target(slicer=slicer, printer_id=printer_id,
        nozzle_size='0.4', device_profile_id=None, build_plate_id=None)
    assemble_puzzle_3mf(
        piece_sources=[PuzzlePiece3MFSource(
            label="C11", threemf_path=str(piece_path), offset_x_mm=10, offset_y_mm=10,
        )],
        output_path=str(output_path),
        piece_slots=[tuple(MaterialSlot(**slot)
            for slot in read_source_metadata(piece_path, target=target)['slots'])],
        preview_colors={index: (*rgb, 255) for index, rgb in enumerate(palette)},
        slot_names=slot_names, printer_id=printer_id, nozzle_size='0.4',
        slot_index_by_name=None, device_profile_id=None, build_plate_id=None,
        overview_png_bytes=None, metadata_target=target,
        enable_wipe_tower_auto_placement=False,
    )
    with zipfile.ZipFile(output_path) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        meshes = ET.fromstring(archive.read("3D/Objects/object_1.model"))
    assert project["filament_colour"] == ["#%02X%02X%02X" % rgb for rgb in palette]
    obj = settings.find("object")
    assert obj is not None
    parts = obj.findall("part")
    assert len(parts) == 1
    expected_extruder = str(material_index + 1)
    assert _metadata_value(parts[0], "name") == material_name
    assert _metadata_value(parts[0], "extruder") == expected_extruder
    assert _metadata_value(obj, "extruder") == expected_extruder
    mesh = meshes.find("m:resources/m:object", _NS)
    assert mesh is not None and mesh.get("pindex") == str(material_index)

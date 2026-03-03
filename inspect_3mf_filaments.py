"""
检查 3MF 文件中的耗材配置顺序
"""
import sys
import zipfile
import json
import xml.etree.ElementTree as ET

def inspect_3mf_filaments(file_path):
    """检查 3MF 文件中的耗材配置"""
    
    print(f"检查 3MF 文件: {file_path}")
    print("=" * 80)
    
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # 1. 检查 project_settings.config (JSON 格式)
            if 'Metadata/project_settings.config' in zf.namelist():
                print("\n✅ 找到 project_settings.config")
                
                with zf.open('Metadata/project_settings.config') as f:
                    settings = json.load(f)
                
                # 检查耗材相关配置
                print("\n" + "=" * 80)
                print("耗材配置 (Filament Configuration)")
                print("=" * 80)
                
                # filament_colour - 耗材颜色
                if 'filament_colour' in settings:
                    colours = settings['filament_colour']
                    print(f"\n1. filament_colour (耗材颜色) - {len(colours)} 个:")
                    for i, colour in enumerate(colours):
                        print(f"   Slot {i+1}: {colour}")
                
                # filament_type - 耗材类型
                if 'filament_type' in settings:
                    types = settings['filament_type']
                    print(f"\n2. filament_type (耗材类型) - {len(types)} 个:")
                    for i, ftype in enumerate(types):
                        print(f"   Slot {i+1}: {ftype}")
                
                # filament_settings_id - 耗材配置 ID
                if 'filament_settings_id' in settings:
                    ids = settings['filament_settings_id']
                    print(f"\n3. filament_settings_id (耗材配置) - {len(ids)} 个:")
                    for i, fid in enumerate(ids):
                        print(f"   Slot {i+1}: {fid}")
                
                # 检查是否有其他耗材相关的数组字段
                print(f"\n4. 其他耗材相关字段:")
                filament_keys = [k for k in settings.keys() if k.startswith('filament_')]
                for key in sorted(filament_keys):
                    if key not in ['filament_colour', 'filament_type', 'filament_settings_id']:
                        value = settings[key]
                        if isinstance(value, list):
                            print(f"   {key}: {len(value)} 个元素")
                        else:
                            print(f"   {key}: {value}")
            
            # 2. 检查 model_settings.config (XML 格式)
            if 'Metadata/model_settings.config' in zf.namelist():
                print("\n" + "=" * 80)
                print("模型设置 (Model Settings)")
                print("=" * 80)
                
                with zf.open('Metadata/model_settings.config') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                
                # 查找所有 part 元素
                parts = root.findall('.//part')
                print(f"\n找到 {len(parts)} 个模型部件:")
                
                for part in parts:
                    part_id = part.get('id')
                    part_name = None
                    extruder = None
                    
                    # 查找 metadata
                    for meta in part.findall('metadata'):
                        key = meta.get('key')
                        value = meta.get('value')
                        
                        if key == 'name':
                            part_name = value
                        elif key == 'extruder':
                            extruder = value
                    
                    print(f"\n  Part ID {part_id}:")
                    print(f"    名称: {part_name}")
                    print(f"    挤出机: {extruder}")
            
            # 3. 检查 3D/Objects/object_1.model
            if '3D/Objects/object_1.model' in zf.namelist():
                print("\n" + "=" * 80)
                print("对象模型 (Object Model)")
                print("=" * 80)
                
                with zf.open('3D/Objects/object_1.model') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                
                # 查找所有 object 元素
                objects = root.findall('.//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}object')
                print(f"\n找到 {len(objects)} 个对象:")
                
                for obj in objects:
                    obj_id = obj.get('id')
                    obj_type = obj.get('type')
                    print(f"\n  Object ID {obj_id} (type={obj_type})")
                    
                    # 检查是否有 mesh
                    mesh = obj.find('.//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}mesh')
                    if mesh is not None:
                        vertices = mesh.find('.//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}vertices')
                        triangles = mesh.find('.//{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}triangles')
                        
                        if vertices is not None:
                            vertex_count = len(vertices)
                            print(f"    顶点数: {vertex_count}")
                        
                        if triangles is not None:
                            triangle_count = len(triangles)
                            print(f"    三角形数: {triangle_count}")
            
            print("\n" + "=" * 80)
            
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        inspect_3mf_filaments(file_path)
    else:
        print("用法: python inspect_3mf_filaments.py <3mf文件路径>")

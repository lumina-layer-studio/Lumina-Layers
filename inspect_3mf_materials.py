"""
检查 3MF 文件中的材料名称
"""

import zipfile
import xml.etree.ElementTree as ET
import sys

def inspect_3mf(file_path):
    """检查 3MF 文件中的材料定义"""
    print(f"检查 3MF 文件: {file_path}")
    print("=" * 80)
    
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # 读取 3D/3dmodel.model
            with zf.open('3D/3dmodel.model') as f:
                content = f.read().decode('utf-8')
                
                # 解析 XML
                root = ET.fromstring(content)
                
                # 查找命名空间
                namespaces = {
                    'model': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02',
                    'p': 'http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
                }
                
                # 查找 basematerials
                basematerials = root.find('.//model:basematerials', namespaces)
                
                if basematerials is not None:
                    print("\n材料定义 (basematerials):")
                    for i, base in enumerate(basematerials.findall('model:base', namespaces)):
                        name = base.get('name', 'Unknown')
                        display_color = base.get('displaycolor', 'Unknown')
                        print(f"  Material {i}: {name} (Color: {display_color})")
                else:
                    print("\n❌ 未找到 basematerials")
                
                # 查找 colorgroup (BambuStudio 格式)
                colorgroup = root.find('.//p:colorgroup', namespaces)
                
                if colorgroup is not None:
                    print("\n颜色组 (colorgroup - BambuStudio):")
                    for i, color in enumerate(colorgroup.findall('p:color', namespaces)):
                        name = color.get('name', 'Unknown')
                        color_val = color.text
                        print(f"  Color {i}: {name} = {color_val}")
                else:
                    print("\n未找到 colorgroup (可能不是 BambuStudio 格式)")
                
                # 查找 object 和 pid 引用
                print("\n对象材料引用:")
                objects = root.findall('.//model:object', namespaces)
                for obj in objects[:5]:  # 只显示前5个
                    obj_id = obj.get('id', 'Unknown')
                    obj_name = obj.get('name', 'Unknown')
                    
                    # 查找 mesh 中的 triangle
                    mesh = obj.find('model:mesh', namespaces)
                    if mesh is not None:
                        triangles = mesh.find('model:triangles', namespaces)
                        if triangles is not None:
                            # 查找第一个 triangle 的 pid
                            triangle = triangles.find('model:triangle', namespaces)
                            if triangle is not None:
                                pid = triangle.get('pid', 'None')
                                print(f"  Object {obj_id} ({obj_name}): pid={pid}")
                
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        # 使用最新的 3MF 文件
        import os
        import glob
        
        pattern = "output/*_Lumina_HiFi_8C_*.3mf"
        files = glob.glob(pattern)
        
        if files:
            # 按修改时间排序，取最新的
            files.sort(key=os.path.getmtime, reverse=True)
            file_path = files[0]
            print(f"自动选择最新的 3MF 文件: {file_path}\n")
        else:
            print("❌ 未找到 3MF 文件")
            print(f"请指定文件路径: python inspect_3mf_materials.py <file.3mf>")
            sys.exit(1)
    
    inspect_3mf(file_path)

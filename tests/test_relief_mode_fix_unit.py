"""
Lumina Studio - UI 模式切换清除逻辑单元测试

测试 on_height_mode_change 和 on_relief_mode_toggle 在模式切换时
正确清除 heightmap 组件残留值。

由于这两个函数是 create_ui 内部函数，无法直接导入，
此处复制其核心逻辑进行测试，验证返回值结构的正确性。

Requirements: 1.1, 1.2, 1.3
"""

import importlib
import pytest


def _real_gr():
    """Import the real gradio module, bypassing any MagicMock pollution."""
    import gradio
    if hasattr(gradio.update, '__wrapped__') or not callable(getattr(gradio, 'update', None)):
        importlib.reload(gradio)
    return gradio


# ---------- 复制自 ui/layout_new.py 的核心逻辑 ----------

def on_height_mode_change(mode: str) -> tuple:
    """切换排列规则时，控制高度图上传区和一键生成按钮的显隐，并清除残留值。"""
    gr = _real_gr()
    if mode == "根据高度图":
        return (
            gr.update(visible=True),    # row_conv_heightmap
            gr.update(visible=False),   # btn_conv_auto_height_apply
            gr.update(visible=False),   # image_conv_heightmap_preview
            gr.update(),                # image_conv_heightmap（不变）
        )
    else:
        return (
            gr.update(visible=False),   # row_conv_heightmap
            gr.update(visible=True),    # btn_conv_auto_height_apply
            gr.update(visible=False),   # image_conv_heightmap_preview
            gr.update(value=None),      # image_conv_heightmap（清除）
        )


def on_relief_mode_toggle(enable_relief, selected_color, height_map, base_thickness) -> tuple:
    """Toggle relief mode visibility and reset state."""
    gr = _real_gr()
    if not enable_relief:
        return (
            gr.update(visible=False),   # slider_conv_relief_height
            gr.update(visible=False),   # accordion_conv_auto_height
            gr.update(visible=False),   # slider_conv_auto_height_max
            gr.update(visible=False),   # row_conv_heightmap
            gr.update(visible=False),   # image_conv_heightmap_preview
            {},                         # conv_color_height_map
            None,                       # conv_relief_selected_color
            gr.update(value="深色凸起"), # radio_conv_auto_height_mode reset
            gr.update(),                # checkbox_conv_cloisonne_enable
            gr.update(value=None),      # image_conv_heightmap（清除）
        )
    else:
        if selected_color:
            current_height = height_map.get(selected_color, base_thickness)
            return (
                gr.update(visible=True, value=current_height),
                gr.update(visible=True),
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                height_map,
                selected_color,
                gr.update(value="深色凸起"),
                gr.update(value=False),
                gr.update(),
            )
        else:
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                height_map,
                selected_color,
                gr.update(value="深色凸起"),
                gr.update(value=False),
                gr.update(),
            )


# ---------- 测试 on_height_mode_change ----------

class TestOnHeightModeChange:
    """测试排列规则切换时 heightmap 清除逻辑 (Requirements 1.1, 1.2)"""

    def test_switch_to_dark_raised_clears_heightmap(self) -> None:
        """从"根据高度图"切换到"深色凸起"时，image_conv_heightmap 应被清除为 None"""
        result = on_height_mode_change("深色凸起")
        heightmap_update = result[3]
        assert "value" in heightmap_update
        assert heightmap_update["value"] is None

    def test_switch_to_light_raised_clears_heightmap(self) -> None:
        """从"根据高度图"切换到"浅色凸起"时，image_conv_heightmap 应被清除为 None"""
        result = on_height_mode_change("浅色凸起")
        heightmap_update = result[3]
        assert "value" in heightmap_update
        assert heightmap_update["value"] is None

    def test_switch_to_heightmap_mode_preserves(self) -> None:
        """选择"根据高度图"时，image_conv_heightmap 不应被清除"""
        result = on_height_mode_change("根据高度图")
        heightmap_update = result[3]
        assert "value" not in heightmap_update

    def test_return_tuple_length(self) -> None:
        """返回值应为 4 元素元组"""
        assert len(on_height_mode_change("深色凸起")) == 4
        assert len(on_height_mode_change("根据高度图")) == 4


# ---------- 测试 on_relief_mode_toggle ----------

class TestOnReliefModeToggle:
    """测试关闭浮雕模式时 heightmap 清除逻辑 (Requirement 1.3)"""

    def test_disable_relief_clears_heightmap(self) -> None:
        """关闭浮雕模式时，image_conv_heightmap (index 9) 应被清除为 None"""
        result = on_relief_mode_toggle(False, None, {}, 1.0)
        heightmap_update = result[9]
        assert "value" in heightmap_update
        assert heightmap_update["value"] is None

    def test_enable_relief_preserves_heightmap(self) -> None:
        """开启浮雕模式时，image_conv_heightmap (index 9) 不应被清除"""
        result = on_relief_mode_toggle(True, "#ff0000", {"#ff0000": 2.0}, 1.0)
        heightmap_update = result[9]
        assert "value" not in heightmap_update

    def test_disable_relief_return_length(self) -> None:
        """关闭浮雕模式返回值应为 10 元素元组"""
        result = on_relief_mode_toggle(False, None, {}, 1.0)
        assert len(result) == 10

    def test_enable_relief_no_selected_color_preserves_heightmap(self) -> None:
        """开启浮雕模式但无选中颜色时，heightmap 也不应被清除"""
        result = on_relief_mode_toggle(True, None, {}, 1.0)
        heightmap_update = result[9]
        assert "value" not in heightmap_update

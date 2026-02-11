"""UI-level i18n extensions for layout-specific text keys."""

from core.i18n import I18n as _CoreI18n

I18n = _CoreI18n

_LAYOUT_TEXTS = {
    "conv_advanced": {"zh": "🛠️ 高级设置", "en": "🛠️ Advanced Settings"},
    "conv_stop": {"zh": "🛑 停止生成", "en": "🛑 Stop Generation"},
    "conv_batch_mode": {"zh": "📦 批量模式", "en": "📦 Batch Mode"},
    "conv_batch_mode_info": {
        "zh": "一次生成多个模型 (参数共享)",
        "en": "Generate multiple models (Shared Settings)",
    },
    "conv_batch_input": {
        "zh": "📤 批量上传图片",
        "en": "📤 Batch Upload Images",
    },
    "conv_lut_status": {
        "zh": "💡 拖放.npy文件自动添加",
        "en": "💡 Drop .npy file to load",
    },
}


def register_layout_texts() -> None:
    """Register layout-only i18n keys once on UI import path."""
    if hasattr(I18n, "TEXTS"):
        I18n.TEXTS.update(_LAYOUT_TEXTS)


register_layout_texts()

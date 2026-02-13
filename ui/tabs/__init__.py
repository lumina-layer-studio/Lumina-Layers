"""
Lumina Studio - UI Tabs Package
Split tab components for better maintainability
"""

from .converter_tab import create_converter_tab_content
from .calibration_tab import create_calibration_tab_content
from .extractor_tab import create_extractor_tab_content
from .about_tab import create_about_tab_content

__all__ = [
    "create_converter_tab_content",
    "create_calibration_tab_content",
    "create_extractor_tab_content",
    "create_about_tab_content",
]

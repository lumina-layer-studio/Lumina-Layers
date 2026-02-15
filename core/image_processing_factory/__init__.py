"""
Lumina Studio - Processing Strategies Module

This module implements the Strategy Pattern for image processing,
separating concerns between color modes and processing modes.

Architecture:
- ColorModeStrategy: Handles LUT loading and color data preparation
- ProcessingModeStrategy: Handles image processing logic
- ProcessorFactory: Assembles the correct strategies based on parameters
- Helper Classes: Common utilities (ImageLoader, LUTManager, ColorMatcher)

This design eliminates the complex if-else branching in the original
LuminaImageProcessor class.
"""

from .color_modes import (
    ColorModeStrategy,
    TwoColorStrategy,
    FourColorStrategy,
    SixColorStrategy,
    EightColorStrategy,
)

from .processing_modes import (
    ProcessingModeStrategy,
    HighFidelityStrategy,
    PixelStrategy,
    VectorStrategy,
)

from .helpers import ImageLoader, LUTManager, ColorMatcher

from .factory import ProcessorFactory

__all__ = [
    # Color Mode Strategies
    "ColorModeStrategy",
    "TwoColorStrategy",
    "FourColorStrategy",
    "SixColorStrategy",
    "EightColorStrategy",
    # Processing Mode Strategies
    "ProcessingModeStrategy",
    "HighFidelityStrategy",
    "PixelStrategy",
    "VectorStrategy",
    # Helper Classes
    "ImageLoader",
    "LUTManager",
    "ColorMatcher",
    # Factory
    "ProcessorFactory",
]

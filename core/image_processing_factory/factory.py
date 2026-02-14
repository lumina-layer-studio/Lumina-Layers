"""
Processor Factory

Factory class for assembling image processors with appropriate strategies.

This factory creates the correct combination of color mode strategy
and processing mode strategy based on parameters.
"""

from typing import Tuple
import numpy as np
from scipy.spatial import KDTree

from config import ColorMode, ModelingMode

from .color_modes import (
    ColorModeStrategy,
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


class ProcessorFactory:
    """
    Factory for creating image processing strategy combinations.

    This class eliminates complex if-else branching by encapsulating
    the logic for selecting appropriate strategies.
    """

    @staticmethod
    def create_color_strategy(color_mode: ColorMode) -> ColorModeStrategy:
        """
        Create color mode strategy based on color_mode string.

        Args:
            color_mode: Color mode identifier (e.g., "CMYW", "RYBW", "6-Color", "8-Color")

        Returns:
            Appropriate ColorModeStrategy instance

        Raises:
            ValueError: If color_mode is not recognized
        """
        mode_enum = color_mode
        if mode_enum == ColorMode.EIGHT_COLOR_MAX:
            return EightColorStrategy(mode_enum)
        elif mode_enum == ColorMode.SIX_COLOR:
            return SixColorStrategy(mode_enum)
        else:
            # Default to 4-color for CMYW and RYBW
            return FourColorStrategy(mode_enum)

    @staticmethod
    def create_processing_strategy(
        modeling_mode: ModelingMode,
    ) -> ProcessingModeStrategy:
        """
        Create processing mode strategy based on modeling_mode enum.

        Args:
            modeling_mode: ModelingMode enum value

        Returns:
            Appropriate ProcessingModeStrategy instance

        Raises:
            ValueError: If modeling_mode is not recognized
        """
        if modeling_mode == ModelingMode.VECTOR:
            return VectorStrategy()
        elif modeling_mode == ModelingMode.PIXEL:
            return PixelStrategy()
        elif modeling_mode == ModelingMode.HIGH_FIDELITY:
            return HighFidelityStrategy()
        else:
            raise ValueError(f"Unknown modeling mode: {modeling_mode}")

    @staticmethod
    def create_processor(
        color_mode: ColorMode, modeling_mode: ModelingMode
    ) -> Tuple[ColorModeStrategy, ProcessingModeStrategy]:
        """
        Create both strategies for a complete processing pipeline.

        Args:
            color_mode: Color mode identifier
            modeling_mode: ModelingMode enum value

        Returns:
            Tuple of (color_strategy, processing_strategy)
        """
        color_strategy = ProcessorFactory.create_color_strategy(color_mode)
        processing_strategy = ProcessorFactory.create_processing_strategy(modeling_mode)

        print(f"[ProcessorFactory] Created:")
        print(f"  - Color Strategy: {color_strategy.get_mode_name()}")
        print(f"  - Processing Strategy: {processing_strategy.get_mode_name()}")

        return color_strategy, processing_strategy

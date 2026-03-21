"""
Lumina Studio - Image Preprocessor

Handles image cropping and format conversion before main processing.
Independent module that doesn't modify existing image_processing.py.
"""

import os
import tempfile
from dataclasses import dataclass
from typing import Tuple, Optional

import cv2
import numpy as np
from PIL import Image

# HEIC/HEIF support (optional dependency)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HAS_HEIF = True
except ImportError:
    HAS_HEIF = False
    print("⚠️ [HEIC] pillow-heif not installed. HEIC/HEIF support disabled.")


@dataclass
class CropRegion:
    """Crop region data model"""
    x: int = 0
    y: int = 0
    width: int = 100
    height: int = 100

    def to_tuple(self) -> Tuple[int, int, int, int]:
        """Convert to (x, y, w, h) tuple"""
        return (self.x, self.y, self.width, self.height)

    def clamp(self, img_width: int, img_height: int) -> 'CropRegion':
        """Clamp crop region to image boundaries"""
        x = max(0, min(self.x, img_width - 1))
        y = max(0, min(self.y, img_height - 1))
        w = max(1, min(self.width, img_width - x))
        h = max(1, min(self.height, img_height - y))
        return CropRegion(x, y, w, h)


@dataclass
class ImageInfo:
    """Image information data model"""
    original_path: str
    processed_path: str
    width: int
    height: int
    original_format: str
    was_converted: bool


class ImagePreprocessor:
    """
    Image preprocessor - handles cropping and format conversion.
    
    This is a standalone module that processes images before they
    enter the main conversion pipeline.
    """

    # Supported formats
    SUPPORTED_FORMATS = {'JPEG', 'JPG', 'PNG', 'GIF', 'BMP', 'WEBP', 'HEIF', 'HEIC'}
    
    @staticmethod
    def detect_format(image_path: str) -> str:
        """
        Detect image format.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Format string (e.g., 'JPEG', 'PNG')
            
        Raises:
            ValueError: If file cannot be read or format unsupported
        """
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Image file not found: {image_path}")
        
        try:
            with Image.open(image_path) as img:
                fmt = img.format
                if fmt is None:
                    # Try to detect from extension
                    ext = os.path.splitext(image_path)[1].upper().lstrip('.')
                    if ext in ('JPG', 'JPEG'):
                        return 'JPEG'
                    elif ext == 'PNG':
                        return 'PNG'
                    elif ext in ('HEIC', 'HEIF'):
                        return 'HEIF'
                    raise ValueError(f"Cannot detect image format: {image_path}")
                return fmt.upper()
        except Exception as e:
            # Check if it's a HEIC file that can't be opened due to missing pillow-heif
            ext = os.path.splitext(image_path)[1].upper().lstrip('.')
            if ext in ('HEIC', 'HEIF') and not HAS_HEIF:
                raise ValueError(
                    "HEIC/HEIF format detected but pillow-heif is not installed. "
                    "Please install it: pip install pillow-heif"
                )
            raise ValueError(f"Cannot read image file: {e}")

    @staticmethod
    def get_image_dimensions(image_path: str) -> Tuple[int, int]:
        """
        Get image dimensions.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Tuple of (width, height)
            
        Raises:
            ValueError: If file cannot be read
        """
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Image file not found: {image_path}")
        
        try:
            with Image.open(image_path) as img:
                return img.size  # (width, height)
        except Exception as e:
            raise ValueError(f"Cannot read image dimensions: {e}")

    @staticmethod
    def convert_to_png(image_path: str, output_path: Optional[str] = None) -> str:
        """
        Convert image to PNG format.
        
        Args:
            image_path: Path to source image
            output_path: Optional output path. If None, creates temp file.
            
        Returns:
            Path to PNG file
            
        Raises:
            ValueError: If conversion fails
        """
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Image file not found: {image_path}")
        
        try:
            with Image.open(image_path) as img:
                # Check if already PNG
                if img.format == 'PNG':
                    return image_path
                
                # Convert to RGBA to preserve transparency
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    img = img.convert('RGBA')
                else:
                    img = img.convert('RGB')
                
                # Generate output path if not provided
                if output_path is None:
                    fd, output_path = tempfile.mkstemp(suffix='.png')
                    os.close(fd)
                
                # Save as PNG
                img.save(output_path, 'PNG')
                return output_path
                
        except Exception as e:
            raise ValueError(f"Cannot convert image to PNG: {e}")

    @staticmethod
    def crop_image(image_path: str, x: int, y: int, 
                   width: int, height: int,
                   output_path: Optional[str] = None) -> str:
        """
        Crop image to specified region.
        
        Args:
            image_path: Path to source image
            x: X offset (left)
            y: Y offset (top)
            width: Crop width
            height: Crop height
            output_path: Optional output path. If None, creates temp file.
            
        Returns:
            Path to cropped image (PNG format)
            
        Raises:
            ValueError: If crop fails
        """
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Image file not found: {image_path}")
        
        try:
            with Image.open(image_path) as img:
                img_w, img_h = img.size
                
                # Validate and clamp crop region
                region = CropRegion(x, y, width, height)
                region = region.clamp(img_w, img_h)
                
                # Calculate crop box (left, upper, right, lower)
                box = (
                    region.x,
                    region.y,
                    region.x + region.width,
                    region.y + region.height
                )
                
                # Crop image
                cropped = img.crop(box)
                
                # Convert to RGBA if needed
                if cropped.mode in ('RGBA', 'LA') or (cropped.mode == 'P' and 'transparency' in img.info):
                    cropped = cropped.convert('RGBA')
                else:
                    cropped = cropped.convert('RGB')
                
                # Generate output path if not provided
                if output_path is None:
                    fd, output_path = tempfile.mkstemp(suffix='.png')
                    os.close(fd)
                
                # Save as PNG
                cropped.save(output_path, 'PNG')
                return output_path
                
        except Exception as e:
            raise ValueError(f"Cannot crop image: {e}")

    @staticmethod
    def validate_crop_region(img_width: int, img_height: int,
                            x: int, y: int,
                            crop_w: int, crop_h: int) -> Tuple[int, int, int, int]:
        """
        Validate and correct crop region to fit within image boundaries.
        
        Args:
            img_width: Image width
            img_height: Image height
            x: Requested X offset
            y: Requested Y offset
            crop_w: Requested crop width
            crop_h: Requested crop height
            
        Returns:
            Tuple of valid (x, y, width, height)
        """
        region = CropRegion(x, y, crop_w, crop_h)
        clamped = region.clamp(img_width, img_height)
        return clamped.to_tuple()

    @classmethod
    def process_upload(cls, image_path: str) -> ImageInfo:
        """
        Process uploaded image: detect format, convert if needed.
        
        Args:
            image_path: Path to uploaded image
            
        Returns:
            ImageInfo with processing results
            
        Raises:
            ValueError: If processing fails
        """
        # Detect format
        fmt = cls.detect_format(image_path)
        
        # Get dimensions
        width, height = cls.get_image_dimensions(image_path)
        
        # Convert to PNG if JPEG or HEIC/HEIF
        was_converted = False
        if fmt in ('JPEG', 'JPG', 'HEIF', 'HEIC'):
            processed_path = cls.convert_to_png(image_path)
            was_converted = True
        else:
            processed_path = image_path
        
        return ImageInfo(
            original_path=image_path,
            processed_path=processed_path,
            width=width,
            height=height,
            original_format=fmt,
            was_converted=was_converted
        )


    @staticmethod
    def analyze_recommended_colors(image_path: str, target_width_mm: float = 60.0) -> dict:
        """
        分析图片，推荐最佳量化颜色数。
        
        委托给 ColorAnalyzer 模块处理。
        
        Args:
            image_path: 图片路径
            target_width_mm: 目标打印宽度（毫米），默认 60mm
            
        Returns:
            dict: {
                'recommended': 推荐颜色数,
                'max_safe': 最大安全颜色数（超过会有噪点）,
                'unique_colors': 独特颜色数,
                'complexity_score': 复杂度评分 (0-100)
            }
        """
        from core.color_analyzer import analyze_recommended_colors as _analyze
        return _analyze(image_path, target_width_mm)

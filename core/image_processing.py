"""
Lumina Studio - Image Processing Core

Handles image loading, preprocessing, color quantization and matching.
"""

import os
import sys
import numpy as np
import cv2
from PIL import Image
from scipy.spatial import KDTree

from config import PrinterConfig, ModelingMode

# SVG support (optional dependency)
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    HAS_SVG = True
except ImportError:
    HAS_SVG = False
    print("⚠️ [SVG] svglib/reportlab not installed. SVG support disabled.")


class LuminaImageProcessor:
    """
    Image processor class.
    
    Handles LUT loading, image processing, and color matching.
    """
    
    def __init__(self, lut_path, color_mode):
        """
        Initialize image processor.
        
        Args:
            lut_path: LUT file path (.npy)
            color_mode: Color mode string (CMYW/RYBW/6-Color)
        """
        self.color_mode = color_mode
        self.lut_rgb = None
        self.ref_stacks = None
        self.kdtree = None
        self.enable_cleanup = True  # 默认开启孤立像素清理
        
        self._load_lut(lut_path)
    
    def _load_svg(self, svg_path, target_width_mm):
        """
        [Final Fix] Safe Padding + Dual-Pass Transparency Detection.
        
        Method: Render twice (White BG / Black BG).
        - If pixel changes color -> It's background (Transparent) -> Remove it.
        - If pixel stays same -> It's content (Opaque) -> Keep it 100% intact.
        
        This guarantees NO internal image damage.
        """
        if not HAS_SVG:
            raise ImportError("Please install 'svglib' and 'reportlab'.")
        
        print(f"[SVG] Rasterizing: {svg_path}")
        
        # 1. 读取 SVG
        drawing = svg2rlg(svg_path)
        
        # --- 步骤 A: 撑大画布 (确保内容不被切断) ---
        x1, y1, x2, y2 = drawing.getBounds()
        raw_w = x2 - x1
        raw_h = y2 - y1
        
        # 添加 20% 安全边距
        padding_x = raw_w * 0.2
        padding_y = raw_h * 0.2
        
        drawing.translate(-x1 + padding_x, -y1 + padding_y)
        drawing.width = raw_w + (padding_x * 2)
        drawing.height = raw_h + (padding_y * 2)
        
        # 2. 缩放
        pixels_per_mm = 20.0
        target_width_px = int(target_width_mm * pixels_per_mm)
        
        if raw_w > 0:
            scale_factor = target_width_px / raw_w
        else:
            scale_factor = 1.0
        
        drawing.scale(scale_factor, scale_factor)
        drawing.width = int(drawing.width * scale_factor)
        drawing.height = int(drawing.height * scale_factor)
        
        # ================== 【终极方案】双重渲染差分法 ==================
        try:
            # Pass 1: 白底渲染 (0xFFFFFF)
            # 强制不使用透明通道，完全模拟打印在白纸上的效果
            pil_white = renderPM.drawToPIL(drawing, bg=0xFFFFFF, configPIL={'transparent': False})
            arr_white = np.array(pil_white.convert('RGB'))  # 丢弃 Alpha，只看颜色
            
            # Pass 2: 黑底渲染 (0x000000)
            # 强制不使用透明通道，完全模拟打印在黑纸上的效果
            pil_black = renderPM.drawToPIL(drawing, bg=0x000000, configPIL={'transparent': False})
            arr_black = np.array(pil_black.convert('RGB'))
            
            # 计算差异 (Difference)
            # diff = |白底图 - 黑底图|
            # 如果像素是实心的，它挡住了背景，所以在白底和黑底上颜色一样 -> diff 为 0
            # 如果像素是透明的，它透出了背景，所以在白底是白，黑底是黑 -> diff 很大
            diff = np.abs(arr_white.astype(int) - arr_black.astype(int))
            diff_sum = np.sum(diff, axis=2)
            
            # 生成完美的 Alpha 掩膜
            # 只要差异小于 10，我们就认为它是实心内容 (容错处理抗锯齿边缘)
            # 这样绝对不会误伤图像内部的任何颜色
            alpha_mask = np.where(diff_sum < 10, 255, 0).astype(np.uint8)
            
            # 合成最终图像
            # 我们取白底图的颜色 (因为它是实心的，取黑底图也一样)，然后把算出来的 alpha 贴上去
            r, g, b = cv2.split(arr_white)
            img_final = cv2.merge([r, g, b, alpha_mask])
            
            # 执行安全裁切
            coords = cv2.findNonZero(alpha_mask)
            
            if coords is not None:
                x, y, w_rect, h_rect = cv2.boundingRect(coords)
                
                if w_rect > 0 and h_rect > 0:
                    print(f"[SVG] Dual-Pass Crop: {w_rect}x{h_rect} (Safe & Clean)")
                    
                    # 留 2 像素边缘
                    pad = 2
                    y_start = max(0, y - pad)
                    y_end = min(img_final.shape[0], y + h_rect + pad)
                    x_start = max(0, x - pad)
                    x_end = min(img_final.shape[1], x + w_rect + pad)
                    
                    img_final = img_final[y_start:y_end, x_start:x_end]
                else:
                    print("[SVG] Warning: Content too small.")
            else:
                print("[SVG] Warning: Image appears fully transparent.")
            
            print(f"[SVG] Final resolution: {img_final.shape[1]}x{img_final.shape[0]} px")
            return img_final
            
        except Exception as e:
            print(f"[SVG] Dual-Pass failed: {e}")
            import traceback
            traceback.print_exc()
            
            # 最后的保底：如果双重渲染失败，回退到普通渲染
            pil_img = renderPM.drawToPIL(drawing, bg=None, configPIL={'transparent': True})
            return np.array(pil_img.convert('RGBA'))
    
    def _load_lut(self, lut_path):
        """
        Load and validate LUT file (Supports 2-Color, 4-Color, 6-Color, and 8-Color).
        
        Automatically detects LUT type based on size:
        - 32 colors: 2-Color BW (Black & White)
        - 1024 colors: 4-Color Standard (CMYW/RYBW)
        - 1296 colors: 6-Color Smart 1296
        - 2738 colors: 8-Color Max
        """
        try:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
            total_colors = measured_colors.shape[0]
        except Exception as e:
            raise ValueError(f"❌ LUT file corrupted: {e}")
        
        valid_rgb = []
        valid_stacks = []
        
        print(f"[IMAGE_PROCESSOR] Loading LUT with {total_colors} points...")
        
        # Branch 0: 2-Color BW (32)
        if self.color_mode == "BW (Black & White)" or self.color_mode == "BW" or total_colors == 32:
            print("[IMAGE_PROCESSOR] Detected 2-Color BW mode")
            
            # Generate all 32 combinations (2^5 = 32)
            for i in range(32):
                if i >= total_colors:
                    break
                
                # Rebuild 2-base stacking (0..31)
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 2)
                    temp //= 2
                stack = digits[::-1]  # [顶...底] format
                
                valid_rgb.append(measured_colors[i])
                valid_stacks.append(stack)
            
            self.lut_rgb = np.array(valid_rgb)
            self.ref_stacks = np.array(valid_stacks)
            
            print(f"✅ LUT loaded: {len(self.lut_rgb)} colors (2-Color BW mode)")
        
        # Branch 1: 8-Color Max (2738)
        elif "8-Color" in self.color_mode or total_colors == 2738:
            print("[IMAGE_PROCESSOR] Detected 8-Color Max mode")
            
            # Load pre-generated 8-color stacks
            import sys
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                stacks_path = os.path.join(sys._MEIPASS, 'assets', 'smart_8color_stacks.npy')
            else:
                # Running as script
                stacks_path = 'assets/smart_8color_stacks.npy'
            
            smart_stacks = np.load(stacks_path).tolist()
            
            # Reverse stacking order for Face-Down printing
            smart_stacks = [tuple(reversed(s)) for s in smart_stacks]
            print("[IMAGE_PROCESSOR] Stacks reversed for Face-Down printing compatibility.")
            
            if len(smart_stacks) != total_colors:
                print(f"⚠️ Warning: Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})")
                min_len = min(len(smart_stacks), total_colors)
                smart_stacks = smart_stacks[:min_len]
                measured_colors = measured_colors[:min_len]
            
            self.lut_rgb = measured_colors
            self.ref_stacks = np.array(smart_stacks)
            
            print(f"✅ LUT loaded: {len(self.lut_rgb)} colors (8-Color mode)")
        
        # Branch 2: 6-Color Smart 1296
        elif "6-Color" in self.color_mode or total_colors == 1296:
            print("[IMAGE_PROCESSOR] Detected 6-Color Smart 1296 mode")
            
            from core.calibration import get_top_1296_colors
            
            smart_stacks = get_top_1296_colors()
            smart_stacks = [tuple(reversed(s)) for s in smart_stacks]
            print("[IMAGE_PROCESSOR] Stacks reversed for Face-Down printing compatibility.")
            
            if len(smart_stacks) != total_colors:
                print(f"⚠️ Warning: Stacks count ({len(smart_stacks)}) != LUT count ({total_colors})")
                min_len = min(len(smart_stacks), total_colors)
                smart_stacks = smart_stacks[:min_len]
                measured_colors = measured_colors[:min_len]
            
            self.lut_rgb = measured_colors
            self.ref_stacks = np.array(smart_stacks)
            
            print(f"✅ LUT loaded: {len(self.lut_rgb)} colors (6-Color mode)")
        
        # Branch 3: 4-Color Standard (1024)
        else:
            print("[IMAGE_PROCESSOR] Detected 4-Color Standard mode")
            
            # Keep original outlier filtering logic (Blue Check)
            base_blue = np.array([30, 100, 200])
            dropped = 0
            
            for i in range(1024):
                if i >= total_colors:
                    break
                
                # Rebuild 4-base stacking (0..1023)
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 4)
                    temp //= 4
                stack = digits[::-1]
                
                real_rgb = measured_colors[i]
                
                # Filter outliers: close to blue but doesn't contain blue
                dist = np.linalg.norm(real_rgb - base_blue)
                if dist < 60 and 3 not in stack:  # 3 is Blue in RYBW/CMYW
                    dropped += 1
                    continue
                
                valid_rgb.append(real_rgb)
                valid_stacks.append(stack)
            
            self.lut_rgb = np.array(valid_rgb)
            self.ref_stacks = np.array(valid_stacks)
            
            print(f"✅ LUT loaded: {len(self.lut_rgb)} colors (filtered {dropped} outliers)")
        
        # Build KD-Tree
        self.kdtree = KDTree(self.lut_rgb)
    
    def process_image(self, image_path, target_width_mm, modeling_mode,
                     quantize_colors, auto_bg, bg_tol,
                     blur_kernel=0, smooth_sigma=10):
        """
        Main image processing method
        
        Args:
            image_path: Image file path
            target_width_mm: Target width (millimeters)
            modeling_mode: Modeling mode ("high-fidelity", "pixel")
            quantize_colors: K-Means quantization color count
            auto_bg: Whether to auto-remove background
            bg_tol: Background tolerance
            blur_kernel: Median filter kernel size (0=disabled, recommended 0-5)
            smooth_sigma: Bilateral filter sigma value (recommended 5-20)
        
        Returns:
            dict: Dictionary containing processing results
                - matched_rgb: (H, W, 3) Matched RGB array
                - material_matrix: (H, W, Layers) Material index matrix
                - mask_solid: (H, W) Solid mask
                - dimensions: (width, height) Pixel dimensions
                - pixel_scale: mm/pixel ratio
                - mode_info: Mode information dictionary
                - debug_data: Debug data (high-fidelity mode only)
        """
        print(f"[IMAGE_PROCESSOR] Mode: {modeling_mode.get_display_name()}")
        print(f"[IMAGE_PROCESSOR] Filter settings: blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}")
        
        # ========== Image Loading Logic Branch ==========
        is_svg = image_path.lower().endswith('.svg')
        
        if is_svg:
            print("[IMAGE_PROCESSOR] SVG detected - Engaging Ultra-High-Fidelity Vector Mode")
            img_arr = self._load_svg(image_path, target_width_mm)
            # SVG reset to PIL object to reuse subsequent logic (e.g., get dimensions)
            img = Image.fromarray(img_arr)
            
            # [CRITICAL] SVG is also a type of High-Fidelity, but it doesn't need denoising
            # Force override filter parameters, because vector graphics have no noise, no need to blur
            # 
            # [SUPER-SAMPLING STRATEGY]
            # We render at 20 px/mm (2x standard), which physically eliminates jaggies
            # through super-sampling. This is superior to blur-based anti-aliasing
            # because it preserves sharp edges while making curves smooth.
            blur_kernel = 0
            smooth_sigma = 0
            print("[IMAGE_PROCESSOR] SVG Mode: Filters disabled (Vector source is clean)")
            print("[IMAGE_PROCESSOR] Super-sampling at 20 px/mm eliminates jagged edges naturally")
            
            # Recalculate target_w/h (based on rendered dimensions)
            target_w, target_h = img.size
            pixel_to_mm_scale = 0.05  # 20 px/mm (1/20) - Ultra-High-Fidelity
        else:
            # [Original Logic] Bitmap loading
            # Load image
            img = Image.open(image_path).convert('RGBA')
            
            # DEBUG: Check original image properties
            print(f"[IMAGE_PROCESSOR] Original image: {image_path}")
            print(f"[IMAGE_PROCESSOR] Image mode: {Image.open(image_path).mode}")
            print(f"[IMAGE_PROCESSOR] Image size: {Image.open(image_path).size}")
            
            # Check if image has transparency
            original_img = Image.open(image_path)
            has_alpha = original_img.mode in ('RGBA', 'LA') or (original_img.mode == 'P' and 'transparency' in original_img.info)
            print(f"[IMAGE_PROCESSOR] Has alpha channel: {has_alpha}")
            
            if has_alpha:
                # Check alpha channel statistics
                if original_img.mode != 'RGBA':
                    original_img = original_img.convert('RGBA')
                alpha_data = np.array(original_img)[:, :, 3]
                print(f"[IMAGE_PROCESSOR] Alpha stats: min={alpha_data.min()}, max={alpha_data.max()}, mean={alpha_data.mean():.1f}")
                print(f"[IMAGE_PROCESSOR] Transparent pixels (alpha<10): {np.sum(alpha_data < 10)}")
            
            # Calculate target resolution
            if modeling_mode == ModelingMode.HIGH_FIDELITY:
                # High-precision mode: 10 pixels/mm
                PIXELS_PER_MM = 10
                target_w = int(target_width_mm * PIXELS_PER_MM)
                pixel_to_mm_scale = 1.0 / PIXELS_PER_MM  # 0.1 mm per pixel
                print(f"[IMAGE_PROCESSOR] High-res mode: {PIXELS_PER_MM} px/mm")
            else:
                # Pixel mode: Based on nozzle width
                target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
                pixel_to_mm_scale = PrinterConfig.NOZZLE_WIDTH
                print(f"[IMAGE_PROCESSOR] Pixel mode: {1.0/pixel_to_mm_scale:.2f} px/mm")
            
            target_h = int(target_w * img.height / img.width)
            print(f"[IMAGE_PROCESSOR] Target: {target_w}×{target_h}px ({target_w*pixel_to_mm_scale:.1f}×{target_h*pixel_to_mm_scale:.1f}mm)")
        
        # ========== End of Image Loading Logic Branch ==========
        
        # ========== CRITICAL FIX: Use NEAREST for both modes ==========
        # REASON: LANCZOS anti-aliasing creates light transition pixels at edges.
        # These light pixels map to stacks with WHITE bases (Layer 1),
        # causing the mesh to "float" above the build plate.
        # 
        # SOLUTION: Use NEAREST to preserve hard edges and ensure dark pixels
        # map to solid dark stacks from Layer 1 upwards.
        print(f"[IMAGE_PROCESSOR] Using NEAREST interpolation (no anti-aliasing)")
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        
        img_arr = np.array(img)
        rgb_arr = img_arr[:, :, :3]
        alpha_arr = img_arr[:, :, 3]
        
        # CRITICAL FIX: Identify transparent pixels BEFORE color processing
        # This prevents transparent areas from being matched to LUT colors
        mask_transparent_initial = alpha_arr < 10
        print(f"[IMAGE_PROCESSOR] Found {np.sum(mask_transparent_initial)} transparent pixels (alpha<10)")
        
        # Color processing and matching
        debug_data = None
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            matched_rgb, material_matrix, bg_reference, debug_data = self._process_high_fidelity_mode(
                rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
            )
        else:
            matched_rgb, material_matrix, bg_reference = self._process_pixel_mode(
                rgb_arr, target_h, target_w
            )
        
        # >>> 孤立像素清理（可选后处理）<<<
        if modeling_mode == ModelingMode.HIGH_FIDELITY and self.enable_cleanup:
            try:
                from core.isolated_pixel_cleanup import cleanup_isolated_pixels
                matched_rgb, material_matrix = cleanup_isolated_pixels(
                    material_matrix, matched_rgb, self.lut_rgb, self.ref_stacks
                )
            except ImportError:
                print("[IMAGE_PROCESSOR] ⚠️ isolated_pixel_cleanup module not found, skipping")
        
        # Background removal - combine alpha transparency with optional auto-bg
        mask_transparent = mask_transparent_initial.copy()
        if auto_bg:
            bg_color = bg_reference[0, 0]
            diff = np.sum(np.abs(bg_reference - bg_color), axis=-1)
            mask_transparent = np.logical_or(mask_transparent, diff < bg_tol)
        
        # Apply transparency mask to material matrix
        material_matrix[mask_transparent] = -1
        mask_solid = ~mask_transparent
        
        result = {
            'matched_rgb': matched_rgb,
            'material_matrix': material_matrix,
            'mask_solid': mask_solid,
            'dimensions': (target_w, target_h),
            'pixel_scale': pixel_to_mm_scale,
            'mode_info': {
                'mode': modeling_mode
            }
        }
        
        # Add debug data (high-fidelity mode only)
        if debug_data is not None:
            result['debug_data'] = debug_data
        
        return result

    
    def _process_high_fidelity_mode(self, rgb_arr, target_h, target_w, quantize_colors,
                                    blur_kernel, smooth_sigma):
        """
        High-fidelity mode image processing
        Includes configurable filtering, K-Means quantization and color matching
        
        优化：
        1. K-Means++ 初始化（OpenCV 默认支持）
        2. 预缩放：在小图上做 K-Means，然后映射回原图
        
        Args:
            rgb_arr: Input RGB array
            target_h: Target height
            target_w: Target width
            quantize_colors: K-Means color count
            blur_kernel: Median filter kernel size (0=disabled)
            smooth_sigma: Bilateral filter sigma value
        
        Returns:
            tuple: (matched_rgb, material_matrix, quantized_image, debug_data)
        """
        import time
        total_start = time.time()
        
        print(f"[IMAGE_PROCESSOR] Starting edge-preserving processing...")
        
        # Step 1: Bilateral filter (edge-preserving smoothing)
        t0 = time.time()
        if smooth_sigma > 0:
            print(f"[IMAGE_PROCESSOR] Applying bilateral filter (sigma={smooth_sigma})...")
            rgb_processed = cv2.bilateralFilter(
                rgb_arr.astype(np.uint8), 
                d=9,
                sigmaColor=smooth_sigma, 
                sigmaSpace=smooth_sigma
            )
        else:
            print(f"[IMAGE_PROCESSOR] Bilateral filter disabled (sigma=0)")
            rgb_processed = rgb_arr.astype(np.uint8)
        print(f"[IMAGE_PROCESSOR] ⏱️ Bilateral filter: {time.time() - t0:.2f}s")
        
        # Step 2: Optional median filter (remove salt-and-pepper noise)
        t0 = time.time()
        if blur_kernel > 0:
            kernel_size = blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1
            print(f"[IMAGE_PROCESSOR] Applying median blur (kernel={kernel_size})...")
            rgb_processed = cv2.medianBlur(rgb_processed, kernel_size)
        else:
            print(f"[IMAGE_PROCESSOR] Median blur disabled (kernel=0)")
        print(f"[IMAGE_PROCESSOR] ⏱️ Median blur: {time.time() - t0:.2f}s")
        
        # Step 3: Skip sharpening to prevent noise amplification
        # Sharpening creates high-contrast noise in flat color areas
        print(f"[IMAGE_PROCESSOR] Skipping sharpening to reduce noise...")
        rgb_sharpened = rgb_processed
        
        # Step 4: K-Means quantization with pre-scaling optimization
        h, w = rgb_sharpened.shape[:2]
        total_pixels = h * w
        
        # 方案 3：预缩放优化
        # 如果像素数超过 50 万，先缩小做 K-Means，再映射回原图
        KMEANS_PIXEL_THRESHOLD = 500_000
        
        t0 = time.time()
        if total_pixels > KMEANS_PIXEL_THRESHOLD:
            # 计算缩放比例，目标 50 万像素
            scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
            small_h = int(h / scale_factor)
            small_w = int(w / scale_factor)
            
            print(f"[IMAGE_PROCESSOR] 🚀 Pre-scaling optimization: {w}×{h} → {small_w}×{small_h} ({total_pixels:,} → {small_w*small_h:,} pixels)")
            
            # 缩小图片
            rgb_small = cv2.resize(rgb_sharpened, (small_w, small_h), interpolation=cv2.INTER_AREA)
            
            # 在小图上做 K-Means（使用 K-Means++ 初始化）
            pixels_small = rgb_small.reshape(-1, 3).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
            flags = cv2.KMEANS_PP_CENTERS  # K-Means++ 初始化
            
            t_kmeans = time.time()
            print(f"[IMAGE_PROCESSOR] K-Means++ on downscaled image ({quantize_colors} colors)...")
            _, _, centers = cv2.kmeans(
                pixels_small, quantize_colors, None, criteria, 5, flags
            )
            print(f"[IMAGE_PROCESSOR] ⏱️ K-Means: {time.time() - t_kmeans:.2f}s")
            
            # 用得到的 centers 直接映射原图（不再迭代，只做最近邻查找）
            t_map = time.time()
            print(f"[IMAGE_PROCESSOR] Mapping centers to full image...")
            centers = centers.astype(np.float32)
            pixels_full = rgb_sharpened.reshape(-1, 3).astype(np.float32)
            
            # 批量计算每个像素到所有 centers 的距离，找最近的
            # 使用 KDTree 加速
            from scipy.spatial import KDTree
            centers_tree = KDTree(centers)
            _, labels = centers_tree.query(pixels_full)
            print(f"[IMAGE_PROCESSOR] ⏱️ KDTree query: {time.time() - t_map:.2f}s")
            
            centers = centers.astype(np.uint8)
            quantized_pixels = centers[labels]
            quantized_image = quantized_pixels.reshape(h, w, 3)
            
            print(f"[IMAGE_PROCESSOR] ✅ Pre-scaling optimization complete!")
        else:
            # 小图直接做 K-Means
            print(f"[IMAGE_PROCESSOR] K-Means++ quantization to {quantize_colors} colors...")
            pixels = rgb_sharpened.reshape(-1, 3).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
            flags = cv2.KMEANS_PP_CENTERS
            
            _, labels, centers = cv2.kmeans(
                pixels, quantize_colors, None, criteria, 10, flags
            )
            
            centers = centers.astype(np.uint8)
            quantized_pixels = centers[labels.flatten()]
            quantized_image = quantized_pixels.reshape(h, w, 3)
        print(f"[IMAGE_PROCESSOR] ⏱️ Total quantization: {time.time() - t0:.2f}s")
        
        # [CRITICAL FIX] Post-Quantization Cleanup
        # Removes isolated "salt-and-pepper" noise pixels that survive quantization
        t0 = time.time()
        print(f"[IMAGE_PROCESSOR] Applying post-quantization cleanup (Denoising)...")
        quantized_image = cv2.medianBlur(quantized_image, 3)  # Kernel size 3 is optimal for detail preservation
        print(f"[IMAGE_PROCESSOR] ⏱️ Post-quantization cleanup: {time.time() - t0:.2f}s")
        
        print(f"[IMAGE_PROCESSOR] Quantization complete!")
        
        # Find unique colors
        t0 = time.time()
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        print(f"[IMAGE_PROCESSOR] Found {len(unique_colors)} unique colors")
        print(f"[IMAGE_PROCESSOR] ⏱️ Find unique colors: {time.time() - t0:.2f}s")
        
        # Match to LUT
        t0 = time.time()
        print(f"[IMAGE_PROCESSOR] Matching colors to LUT...")
        _, unique_indices = self.kdtree.query(unique_colors.astype(float))
        print(f"[IMAGE_PROCESSOR] ⏱️ LUT matching: {time.time() - t0:.2f}s")
        
        # 🚀 优化：构建颜色编码查找表
        # 把 RGB 编码成单个整数：R*65536 + G*256 + B
        # 这样可以用 NumPy 向量化操作一次性完成映射
        t0 = time.time()
        print(f"[IMAGE_PROCESSOR] Building color lookup table...")
        
        # 为每个 unique_color 计算编码
        unique_codes = (unique_colors[:, 0].astype(np.int32) * 65536 + 
                        unique_colors[:, 1].astype(np.int32) * 256 + 
                        unique_colors[:, 2].astype(np.int32))
        
        # 构建编码 → 索引的映射数组（用于 np.searchsorted）
        sort_idx = np.argsort(unique_codes)
        sorted_codes = unique_codes[sort_idx]
        sorted_lut_indices = unique_indices[sort_idx]
        
        # 计算所有像素的颜色编码
        print(f"[IMAGE_PROCESSOR] Mapping to full image (optimized)...")
        flat_quantized = quantized_image.reshape(-1, 3)
        pixel_codes = (flat_quantized[:, 0].astype(np.int32) * 65536 + 
                       flat_quantized[:, 1].astype(np.int32) * 256 + 
                       flat_quantized[:, 2].astype(np.int32))
        
        # 使用 searchsorted 找到每个像素对应的 unique_color 索引
        insert_positions = np.searchsorted(sorted_codes, pixel_codes)
        # 获取对应的 LUT 索引
        lut_indices_for_pixels = sorted_lut_indices[insert_positions]
        
        # 一次性映射所有像素
        matched_rgb = self.lut_rgb[lut_indices_for_pixels].reshape(target_h, target_w, 3)
        material_matrix = self.ref_stacks[lut_indices_for_pixels].reshape(
            target_h, target_w, PrinterConfig.COLOR_LAYERS
        )
        print(f"[IMAGE_PROCESSOR] ⏱️ Color mapping (optimized): {time.time() - t0:.2f}s")
        
        print(f"[IMAGE_PROCESSOR] ✅ Total processing time: {time.time() - total_start:.2f}s")
        
        # Prepare debug data
        debug_data = {
            'quantized_image': quantized_image.copy(),
            'num_colors': len(unique_colors),
            'bilateral_filtered': rgb_processed.copy(),
            'sharpened': rgb_sharpened.copy(),
            'filter_settings': {
                'blur_kernel': blur_kernel,
                'smooth_sigma': smooth_sigma
            }
        }
        
        return matched_rgb, material_matrix, quantized_image, debug_data
    
    def _process_pixel_mode(self, rgb_arr, target_h, target_w):
        """
        Pixel art mode image processing
        Direct pixel-level color matching, no smoothing
        """
        print(f"[IMAGE_PROCESSOR] Direct pixel-level matching (Pixel Art mode)...")
        
        flat_rgb = rgb_arr.reshape(-1, 3)
        _, indices = self.kdtree.query(flat_rgb)
        
        matched_rgb = self.lut_rgb[indices].reshape(target_h, target_w, 3)
        material_matrix = self.ref_stacks[indices].reshape(
            target_h, target_w, PrinterConfig.COLOR_LAYERS
        )
        
        print(f"[IMAGE_PROCESSOR] Direct matching complete!")
        
        return matched_rgb, material_matrix, rgb_arr

    def _extract_wireframe_mask(self, rgb_arr, target_w, pixel_scale, wire_width_mm=0.6):
        """
        Extract cloisonné wireframe mask using edge detection + dilation.

        The mask marks pixels that should become raised "gold wire" in the
        final 3D model.  The dilation kernel is sized so that the wire is
        physically printable (≥ nozzle width).

        Args:
            rgb_arr:        (H, W, 3) uint8 – colour-matched or quantised image.
            target_w:       int – image width in pixels (used only for logging).
            pixel_scale:    float – mm per pixel.
            wire_width_mm:  float – desired physical wire width in mm (default 0.6).

        Returns:
            mask_wireframe: (H, W) bool ndarray – True where wire should be.
        """
        import time
        t0 = time.time()

        # 1. Greyscale + light blur to suppress quantisation noise
        gray = cv2.cvtColor(rgb_arr.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        # 2. Adaptive Canny thresholds (Otsu-based)
        otsu_thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        low = max(10, int(otsu_thresh * 0.4))
        high = max(30, int(otsu_thresh * 0.8))
        edges = cv2.Canny(gray, low, high)

        # 3. Dilate to physical wire width
        wire_px = max(1, int(round(wire_width_mm / pixel_scale)))
        if wire_px % 2 == 0:
            wire_px += 1  # kernel must be odd
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (wire_px, wire_px))
        dilated = cv2.dilate(edges, kernel, iterations=1)

        mask_wireframe = dilated > 0

        dt = time.time() - t0
        print(f"[CLOISONNE] Wireframe extracted: Canny({low},{high}), "
              f"dilate {wire_px}px ({wire_width_mm}mm), "
              f"{np.sum(mask_wireframe)} wire pixels, {dt:.2f}s")

        return mask_wireframe

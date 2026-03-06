# Lumina Studio

Physics-Based Multi-Material FDM Color System

[📖 中文文档 / Chinese Version](README_CN.md)

---

## Project Status

**Current Version**: v1.6.0  
**License**: GNU GPL v3.0 (with Commercial Use & "Street Vendor" Support)  
**Nature**: Non-profit independent implementation, open-source community project

---
Inspiration and Technical Statements

### Acknowledgements to Pioneers

This project owes its existence to the open sharing of the following technologies:

- **HueForge** - The first tool to introduce optical color mixing to the FDM community, demonstrating that layering transparent materials can achieve rich colors through light transmission.

- **AutoForge** - An automated color matching workflow, making multi-material color printing easy to use.

- **CMYK Printing Theory** - A layer-by-layer transmission adaptation of the classic subtractive color model in 3D printing.

### Technical Differentiation and Positioning

Traditional tools rely on theoretical calculations (such as TD1/TD0 transmission distance values), but these parameters are highly susceptible to failure due to various objective factors.

 **Lumina Studio employs an exhaustive search approach:**

1. Print a 1024-color physical calibration board (4 colors x 5 layers, full permutation)

2. Scan the board by photograph and extract the actual RGB data

3. Create a "LUT" (Learning Unknown Test Table)

4. Use a nearest neighbor algorithm for matching (similar to the matching in Bambulab's keychain generator).

### Prior Art Declaration

The core principle of FDM multilayer overlay was publicly disclosed by software such as HueForge between 2022 and 2023, and is considered **prior art**.

The HueForge authors have also clearly stated that this technology has entered the public domain, and in most countries and regions, if the patent office carefully examines it, a principle patent would certainly be rejected.

The pioneers have chosen to remain open to help the community develop; therefore, this technology is generally **not patentable**.

Lumina Studio will continue to maintain its open-source, collaborative, and non-profit positioning, and we welcome everyone's supervision.
Lumina Studio will continue to operate on an open-source, collaborative, and non-profit basis, and we welcome your feedback.

- This project is an open-source, non-profit project. There will be no bundled sales, and no features will be made into paid features.
- If you or your company wish to support the project's continued development, please contact us. Sponsored products will only be used for software development, testing, and optimization.
- Sponsorship represents support for the project only and does not constitute any commercial binding.
- We reject any sponsorship collaborations that could influence technical decisions or open-source licenses.

Lumina Studio did not refer to any patent applications because such patents usually only contain specifications and the technical code is not disclosed in the short term. Blindly referring to these patents would affect its own development process.

**Special thanks to the HueForge team for their support and understanding of open source!**  **
---

## Open Ecosystem

### About .npy Calibration Files

All calibration presets (`.npy` files) are **completely free and open**, adhering to the following principles:

- **No Vendor Lock-in:** We have never, currently, and will never force users to use specific consumable brands, nor will we require manufacturers to produce specific "compatible consumables" that meet our requirements. This violates the spirit of open source.

- **Community Collaboration:** We welcome all users, organizations, and consumable manufacturers to submit PRs and synchronize calibration presets. Your printer data can help others.

- No other testing tools are needed; all you need is a 3D printer and a mobile phone.

**Open Data = Democratization of Technology**

---

## License

### Core License: GNU GPL v3.0

- ✅ **Open & Free**: You are free to run, study, modify, and distribute this software.
- 🔄 **Copyleft**: If you modify and distribute this software, you must release the source code under GPL v3.0.
- ❌ **No Proprietary Derivatives**: Selling closed-source versions of this software or its derivatives is strictly prohibited.

### Commercial Use & "Street Vendor" Support Statement

**To individual creators, street vendors, and small businesses**:

GPL permits and encourages commercial use. We specifically support you to earn a living through your craft. You do **NOT** need to ask for additional permission to:
- Use this software to generate models
- Sell physical prints (keychains, reliefs, etc.)
- Sell at night markets, fairs, or personal online shops

**Go set up your stall and make a living! This is your right.**

---

Lumina Studio v1.5.4 integrates three major modules into a unified interface:

### 📐 Module 1: Calibration Generator

Generates precision calibration boards to physically test filament mixing.

- **Multiple Color Systems**: 
  - **4-Color (CMYW/RYBW)**: 1024 colors (4 base filaments × 5 layers)
  - **6-Color**: 1296 colors (6 base filaments × 3 layers) - Extended color gamut
  - **8-Color**: 2738 colors (8 base filaments × 2 pages) - Professional wide gamut
  - **BW Mode**: 32 grayscale levels for monochrome prints
- **Smart Calibration Workflow**:
  - 4-Color: Single board, full permutation
  - 6-Color: Single board with extended palette
  - 8-Color: Two-page system with merge function
- **Face-Down Optimization**: Viewing surface prints directly on the build plate for a smooth finish
- **Solid Backing**: Automatically generates opaque backing to ensure color consistency and structural rigidity
- **Anti-Overlap Geometry**: Applies 0.02mm micro-shrinkage to voxels to prevent slicer line-width conflicts

### 🎨 Module 2: Color Extractor

Digitizes the physical reality of your printer.

- **Computer Vision**: Perspective warp + lens distortion correction for automatic grid alignment
- **Multi-Mode Support**: 
  - 4-Color (CMYW/RYBW): Standard calibration
  - 6-Color: Extended palette extraction
  - 8-Color: Two-page extraction with manual correction support
  - BW Mode: Grayscale calibration
- **Mode-Aware Alignment**: Corner markers follow the correct color sequence based on your selected mode
- **Digital Twin**: Extracts RGB values from the print and generates a .npy LUT file
- **Human-in-the-Loop**: Interactive probe tools allow manual verification/correction of specific color block readings
- **8-Color Workflow**: Extract Page 1 → Manual corrections → Extract Page 2 → Merge into single LUT

### 💎 Module 3: Image Converter

Converts images into printable 3D models using calibrated data.

- **KD-Tree Color Matching**: Maps image pixels to actual printable colors found in your LUT
- **Live 3D Preview**: Interactive WebGL preview with true matched colors—rotate, zoom, and inspect before printing
- **Keychain Loop Generator**: Automatically adds functional hanging loops with:
  - Smart color detection (matches nearby model colors)
  - Customizable dimensions (width, length, hole diameter)
  - Rectangle base + semicircle top + hollow hole geometry
  - 2D preview shows loop placement
- **Structure Options**: Double-sided (keychain) or Single-sided (relief) modes
- **Smart Background Removal**: Automatic transparency detection with adjustable tolerance
- **Correct 3MF Naming**: Objects are named by color (e.g., "Cyan", "Magenta") instead of "geometry_0" for easy slicer identification

---

## What's New in v1.6.0 🚀

### 🎨 Cloisonné Mode (掐丝珐琅)

- **Metal Wire Frame Generation** - Automatically extracts color boundaries to generate metal wire frames
- **Independent Wire Export** - Wire exported as separate object, assignable to metallic material in slicer
- **Adjustable Parameters** - Wire width (0.2-1.2mm) and height (0.04-1.0mm) fully customizable
- **Single-Sided Mode** - Enforces viewing surface facing up for optimal visual effect

### 🆓 Free Color Mode

- **Break LUT Limitations** - Use any RGB color beyond LUT constraints
- **Custom Color Sets** - Define your own color palette, each color exports as independent 3MF object
- **Full Creative Freedom** - Perfect for artistic projects requiring specific brand colors

### 🪟 Transparent Coating Layer

- **Protective Coating** - Add transparent protective layer at model bottom
- **Adjustable Height** - Coating thickness (0.04-0.12mm) fully customizable
- **Independent Export** - Coating exports as separate object for transparent material assignment
- **Outline Compatibility** - When both coating and outline enabled, coating properly extends to cover outline base layer

### 🔲 Outline Border

- **Model Framing** - Add customizable border around model
- **Adjustable Width** - Outline width (0.5-5.0mm) fully customizable
- **Smart Integration** - Automatically extends downward to cover coating layers when both features enabled

### 🎴 Card Palette Layout

- **Physical Calibration Layout** - Display LUT colors in spatial arrangement matching physical calibration board
- **8-Color Split View** - 8-color LUTs automatically split into A/B groups displayed side-by-side
- **Toggle Modes** - Switch between block/card layout in advanced settings

### 🔍 Color Search & Filter

- **Color Picker Search** - "Find by color" - pick any color and auto-match closest physical color in LUT
- **Text Search** - Support Hex (#FF0000) and RGB (255,0,0) input with auto-locate and highlight
- **Hue Filtering** - Filter by color family: Red/Orange/Yellow/Green/Cyan/Blue/Purple/Neutral
- **Smart Navigation** - Matched color blocks auto-scroll to center with breathing light animation

### 🏔️ 2.5D Relief Mode

- **Height-Based Modeling** - Assign independent Z-axis heights to different colors
- **Optical Layering Preserved** - Top 5 layers maintain optical color mixing, bottom filled with backing material
- **Auto Height Generator** - Automatically assign heights based on color brightness (Min-Max normalization)
- **Heightmap Support** - Upload grayscale heightmap (PNG/JPG/BMP) to drive per-pixel relief height
- **Smart Validation** - Auto-warning for aspect ratio deviation >20% and low contrast
- **Performance Optimized** - Vectorized voxel matrix filling for large images

### 🧹 Isolated Pixel Cleanup

- **Automatic Noise Reduction** - Intelligently detect and merge isolated color pixels
- **Print Quality** - Reduces printing artifacts from fragmented regions
- **Auto-Enabled** - Automatically active in High-Fidelity mode

### 🔄 Connected Region Color Replacement

- **Local Color Replacement** - Replace colors by 4-connected regions based on quantized colors
- **Dual-List Palette** - Refactored palette into user replacement / auto-matched dual-list interaction
- **Stable Behavior** - Display original matched colors while maintaining stable replacement behavior
- **Click to Replace** - Click on 2D preview to select connected region and replace its color

### 🎨 CIELAB Perceptual Color Matching

- **Perceptual Uniformity** - Color matching switched from RGB Euclidean distance to CIELAB perceptual uniform space
- **Better Visual Results** - Matches colors based on human perception rather than mathematical distance
- **Comprehensive Coverage** - Applied to all color matching operations: LUT loading, high-fidelity mode, pixel mode, and color replacement

### 🔀 Automatic Color Merging

- **Low-Usage Color Consolidation** - Automatically merge colors with usage below threshold
- **CIELAB Delta-E Distance** - Uses perceptual color difference for intelligent merging
- **UI Controls** - Adjustable threshold, max distance, with preview/apply/revert options
- **Dramatic Reduction** - Test case: 390 colors → 62 colors (84% reduction)

### 🔌 Slicer Integration

- **One-Click Launch** - Auto-detect installed slicers: Bambu Studio / OrcaSlicer / ElegooSlicer
- **Direct Workflow** - Generate model and open directly in slicer without manual drag-and-drop
- **Persistent Selection** - Dropdown to switch slicers, remembers last choice

### 🖱️ Preview Interaction Improvements

- **Gradio 6.0 Compatible** - Fixed preview click coordinate transformation for latest Gradio
- **3D Preview Redesign** - Fullscreen 3D preview with improved controls
- **Crop Presets** - Added aspect ratio presets (1:1, 4:3, 3:2, 16:9, etc.)
- **Smart Workflow** - Generate 3MF button auto-generates preview if missing
- **Persistent Settings** - Remembers color mode and modeling mode selections
- **Crop Toggle Memory** - Crop interface toggle state persists to user_settings.json

### 🏗️ Complete BambuStudio 3MF Export

- **Multi-Material Support** - Full support for BambuStudio's multi-material 3MF format
- **Proper Object Naming** - Objects named by color (e.g., "Cyan", "Magenta") for easy slicer identification
- **Metadata Integration** - Complete metadata for optimal slicer compatibility

### 🐛 Critical Bug Fixes

- **8-Color Stacking Order** - Fixed incorrect stacking order causing wrong color mixing in 8-color mode
- **Data Consistency** - Ensured 8-color ref_stacks format matches 4-color/6-color [top...bottom]
- **Viewing Surface** - Fixed viewing surface (Z=0) and back surface inversion
- **RYBW Detection** - Fixed RYBW mode incorrectly detected as BW mode
- **Color Replacement** - Fixed color replacement now correctly updates material_matrix stacking data
- **Outline Mesh** - Fixed outline mesh missing on image boundary edges
- **Calibration Import** - Fixed missing import for safe_fix_3mf_names in BW calibration generation

### 🧪 Testing & Quality

- **Comprehensive Test Suite** - 78+ tests covering all major features
- **Property-Based Testing** - 24 heightmap tests (16 unit + 8 property)
- **Code Quality** - Replaced all bare exception catches with `except Exception:`

---

## What's New in v1.5.7 🚀

### Recent Bug Fixes

- 🐛 **Fixed Calibration Import Error** - Resolved `NameError` when generating BW calibration boards by adding missing import for `safe_fix_3mf_names`
- 🔧 **Fixed Coating/Outline Compatibility** - Transparent coating now properly extends to cover outline base layer when both features are enabled simultaneously

### 6-Color and 8-Color Mode Support

- 🎨 **6-Color Extended Mode** - 1296 colors (6 base filaments × 3 layers) for wider color gamut
- 🌈 **8-Color Professional Mode** - 2738 colors (8 base filaments × 2 pages) for maximum color range
- � **Two-Page Workflow** - 8-color mode uses two calibration boards that merge into a single LUT
- 🔧 **Manual Color Correction** - Click any color cell to manually adjust RGB values before merging
- 🎯 **Smart Corner Detection** - Automatic corner marker colors based on selected mode
- ⚫ **BW Grayscale Mode** - 32-level grayscale calibration for monochrome prints

### LUT Merging with Stacking Preservation

- 🎨 **Merged LUT Support** - Combine multiple LUTs (8-color + 6-color + 4-color + BW) to expand color gamut
- � **Stacking Information Preservation** - Merged LUTs now preserve original stacking data from calibration prints
- 🔄 **NPZ Format** - Merged LUTs saved as `.npz` files containing both colors and stacking arrays
- 🎯 **Intelligent Reconstruction** - Automatic stacking reconstruction for all LUT types (BW/4-color/6-color/8-color)
- 🖼️ **Color Replacement Support** - Merged LUTs fully compatible with color replacement feature
- 📤 **Upload Support** - All file upload components now accept both `.npy` and `.npz` formats

### Technical Improvements

- ✅ **Multi-Object 3MF Export** - Merged LUTs now correctly export separate objects for each material
- 🔍 **Format Auto-Detection** - System automatically detects and loads `.npy` or `.npz` format
- 🏷️ **Visual Indicators** - Merged LUTs display `[Merged]` tag in dropdown for easy identification
- 🐛 **Bug Fixes** - Fixed 8-color manual correction persistence issue

---

## What's New in v1.5.4 🚀

### Vector Mode Improvements

- 🐛 **Boolean Operation Optimization** - Improved color overlap handling logic in vector mode
- 🎯 **SVG Order Preservation** - Maintains original SVG drawing order for correct layering
- ✨ **Micro Z-Offset Technology** - Adds 0.001mm micro-offset for different colors on same material to maintain detail independence
- 🛡️ **Small Feature Protection** - Enhanced protection mechanism for small geometric features

### Version Update

- ✅ **Version Bump** - Updated to v1.5.4 for consistency

---

## What's New in v1.5.0 🚀

### Code Standardization

- ✅ **English-only Comments** - All code comments translated to English for better international collaboration
- ✅ **Documentation Standards** - Unified Google-style docstrings across codebase
- ✅ **Code Cleanup** - Removed redundant comments, kept essential algorithm explanations

---

## What's New in v1.4.1 🚀

### Modeling Mode Consolidation

**High-Fidelity Mode Replaces Vector & Woodblock Modes**:

The three modeling modes (Vector/Woodblock/Voxel) have been streamlined into **two unified modes**:

| Mode | Description | Use Case |
|------|-------------|----------|
| 🎨 **High-Fidelity Mode** | Unified RLE-based mesh generation with K-Means quantization | Logos, photos, portraits, illustrations |
| 🧱 **Pixel Art Mode** | Legacy voxel mesher with blocky aesthetic | Pixel art, 8-bit style graphics |

**Why the change?**
- Vector and Woodblock modes shared 90% of the same code
- High-Fidelity mode combines the best of both: smooth curves + detail preservation
- Simpler UI with fewer confusing options
- Consistent 10 px/mm resolution for all high-quality outputs

### Language Switching

- **🌐 Dynamic Language Toggle**: Click the language button in the top-right corner to switch between Chinese and English
- **Full UI Translation**: All interface elements update instantly without page reload
- **Persistent Settings**: Language preference is maintained during the session

### Other Improvements

- **Code Optimization**: Improved code structure and maintainability
- **Documentation Updates**: Enhanced inline documentation and comments
- **Stability Improvements**: Minor bug fixes and performance tweaks

---

### Previous Updates (v1.4)

### Three Modeling Modes

Lumina Studio v1.4 introduces **three distinct geometry generation engines** to cover everything from pixel art to photo-realistic details:

| Mode | Use Case | Technical Features | Precision |
|------|----------|-------------------|-----------|
| 🎨 **Vector Mode** | Logos, illustrations, cartoons | Smooth curves, OpenCV contour extraction | 10 px/mm (0.1mm/pixel) |
| 🖼️ **Woodblock Mode** ⭐ | Photos, portraits, complex textures | SLIC superpixels + detail preservation | 10 px/mm  |
| 🧱 **Voxel Mode** | Pixel art, 8-bit style | Blocky geometry, nostalgic aesthetic | 2.4 px/mm (nozzle width) |

### Color Quantization Engine 

**"Cluster First, Match Second"**:

Traditional methods match 1 million pixels to LUT individually. v1.4 instead:
1. **K-Means Clustering**: Quantize image to K dominant colors (8-256, default 64)
2. **Match Only K Colors**: 1000× speed improvement
3. **Spatial Denoising**: Bilateral + median filtering eliminates fragmented regions

**User-Adjustable Parameters**:
- **Vector Color Detail** slider: 8 colors (minimalist) to 256 colors (photographic)

### Other Improvements

| Feature | Description |
|---------|-------------|
| 📏 Resolution Decoupling | Vector/Woodblock: 10 px/mm, Voxel: 2.4 px/mm |
| 🎮 Smart 3D Preview Downsampling | Large models auto-simplify preview (3MF retains full quality) |
| 🚫 Browser Crash Protection | Detects model complexity, disables preview for 2M+ pixels |

**Previous Updates (v1.2-1.3)**:

| Feature | Description |
|---------|-------------|
| 🔧 Fixed 3MF Naming | Slicer now shows correct color names (White, Cyan, Magenta...) |
| 🎨 Dual Color Modes | Full support for both CMYW and RYBW color systems |
| 🎮 Live 3D Preview | Interactive preview with actual LUT-matched colors |
| 🌐 Bilingual UI | Chinese/English labels throughout the interface |
| 📏 Optimized Gap | Default gap changed to 0.82mm for standard line widths |
| 📦 Unified App | All three tools merged into single application |

---

## Development Roadmap

### Phase 1: The Foundation ✅ COMPLETE

**Target**: Pixel Art & Photographic Graphics

- ✅ Fixed CMYW/RYBW mixing
- ✅ Two modeling modes (High-Fidelity/Pixel Art)
- ✅ High-Fidelity mode with RLE mesh generation
- ✅ Ultra-high precision (10 px/mm, 0.1mm/pixel)
- ✅ K-Means color quantization architecture
- ✅ Solid Backing generation
- ✅ Closed-loop calibration system
- ✅ Live 3D preview with true colors
- ✅ Keychain loop generator
- ✅ Dynamic language switching (Chinese/English)

### Phase 2: Manga Mode (Monochrome) 🚧 IN PROGRESS

**Target**: Manga panels, Ink drawings, High-contrast illustrations

- Logic: Black & White layering using thickness-based grayscale (Lithophane logic)
- Tech: Simulating screen tones (Ben-Day dots)

### Phase 3: Dynamic Palette Engine

**Target**: Adaptive color systems

- Logic: Dynamic Palette Support (4/6/8 colors auto-selection)
- Tech:
  - Intelligent color clustering algorithms
  - Adaptive dithering algorithms
  - Perceptual color difference optimization

### Phase 4: Extended Color Modes ✅ COMPLETE

**Target**: Professional multi-material printing

- ✅ 6-color extended mode (1296 colors)
- ✅ 8-color professional mode (2738 colors)
- ✅ BW grayscale mode (32 levels)
- 🚧 Perler bead mode (in progress)

---

## Installation

### Clone the repository

```bash
git clone https://github.com/MOVIBALE/Lumina-Layers.git
cd Lumina-Layers
```

### Option 1: Docker (Recommended)

Using Docker is the easiest way to run Lumina Studio without worrying about system-level dependencies (like `cairo` or `pkg-config`).

1. **Build the image**:
   ```bash
   docker build -t lumina-layers .
   ```

2. **Run the container**:
   ```bash
   docker run -p 7860:7860 lumina-layers
   ```

3. Open your browser to `http://localhost:7860`.

### Option 2: Local Installation

**Core dependencies** (required):
```bash
pip install -r requirements.txt
```

---

## Usage Guide

### Quick Start

```bash
python main.py
```

This launches the web interface with all three modules in tabs.

---

### Step 1: Generate Calibration Board

1. Open the **📐 Calibration** tab
2. Select your color mode:
   - **4-Color RYBW** (Red/Yellow/Blue/White) - Traditional primaries, 1024 colors
   - **4-Color CMYW** (Cyan/Magenta/Yellow/White) - Print colors, wider gamut, 1024 colors
   - **6-Color** - Extended palette with 1296 colors (requires 6-filament printer)
   - **8-Color** - Professional mode with 2738 colors (two-page workflow)
   - **BW** - Grayscale mode with 32 levels
3. Adjust block size (default: 5mm) and gap (default: 0.82mm)
4. Click **Generate** and download the `.3mf` file(s)
   - 4-Color/6-Color/BW: Single file
   - 8-Color: Two files (Page 1 and Page 2)

**Print Settings**:

- Layer height: 0.08mm (color layers), backing can use 0.2mm
- Filament slots must match your selected mode

| Mode | Total Colors | Filament Slots |
|------|--------------|----------------|
| 4-Color RYBW | 1024 | White, Red, Yellow, Blue |
| 4-Color CMYW | 1024 | White, Cyan, Magenta, Yellow |
| 6-Color | 1296 | White, Cyan, Magenta, Yellow, Lime, Black |
| 8-Color | 2738 | White, Cyan, Magenta, Yellow, Lime, Black (+ 2 more) |
| BW | 32 | Black, White |

---

### Step 2: Extract Colors

1. Print the calibration board and photograph it (face-up, even lighting)
2. Open the **🎨 Color Extractor** tab
3. Select the same color mode as your calibration board
4. Upload your photo
5. Click the four corner blocks in order (colors vary by mode):

| Mode | ⬜ White Top-Left | Top-Right | Bottom-Right | Bottom-Left |
|------|------------------|-----------|--------------|-------------|
| 4-Color RYBW | ⬜ White | Red | Blue | Yellow |
| 4-Color CMYW | ⬜ White | Cyan | Magenta | Yellow |
| 6-Color | ⬜ White | Cyan | Magenta | Yellow |
| 8-Color | ⬜ White | Yellow | Black | Cyan |
| BW | ⬜ White | Black | Black | Black |

6. Adjust correction sliders if needed (white balance OFF by default, vignette, distortion)
7. Click **Extract** 
8. **For 8-Color Mode Only**:
   - After extracting Page 1, you can click any color cell to manually correct it
   - Extract Page 2 with the same process
   - Click **Merge 8-Color Pages** to combine into final LUT
9. Download the `.npy` LUT file

---

### Step 3: Convert Image

1. Open the **💎 Image Converter** tab
2. Upload your `.npy` LUT file
3. Upload your image
4. Select the same color mode as your LUT
5. **Choose Modeling Mode**:
   - **High-Fidelity (Smooth)** - Recommended for logos, photos, portraits, illustrations
   - **Pixel Art (Blocky)** - Recommended for pixel art and 8-bit style graphics
6. Adjust **Color Detail** slider (8-256 colors, default 64):
   - 8-32 colors: Minimalist style, fast generation
   - 64-128 colors: Balanced detail & speed (recommended)
   - 128-256 colors: Photographic detail, slower generation
7. Click **👁️ Generate Preview** to see the result
8. (Optional) Add Keychain Loop:
   - Click on the 2D preview where you want the loop attached
   - Enable "启用挂孔" checkbox
   - Adjust loop width, length, and hole diameter
   - The loop color is automatically detected from nearby pixels
9. Choose structure type:
   - **Double-sided** - For keychains (image on both sides)
   - **Single-sided** - For relief/lithophane style
10. Click **🚀 Generate 3MF**
11. Preview in the interactive 3D viewer
12. Download the `.3mf` file

---

## Technical Stack

| Component | Technology |
|-----------|------------|
| Core Logic | Python (NumPy for voxel manipulation) |
| Geometry Engine | Trimesh (Mesh generation & Export) |
| UI Framework | Gradio 4.0+ |
| Vision Stack | OpenCV (Perspective & Color Extraction) |
| Color Matching | SciPy KDTree |
| 3D Preview | Gradio Model3D (GLB format) |

---

## How It Works

### Why Calibration Matters

Theoretical TD values assume:
- Perfectly consistent filament dye concentration
- Identical nozzle temperatures across all materials
- Uniform layer adhesion

In reality, these vary significantly between:
- Different filament brands/batches
- Printer models and nozzle designs
- Environmental humidity and temperature

The LUT-based approach solves this by measuring actual printed colors and matching them via nearest-neighbor search in RGB space.

---

## License

This project is licensed under the **GNU GPL v3.0** Open Source License.

- ✅ **Open & Free**: You are free to run, study, modify, and distribute this software.
- 🔄 **Copyleft**: If you modify and distribute this software, you must release the source code under GPL v3.0.
- ❌ **No Proprietary Derivatives**: Selling closed-source versions of this software or its derivatives is strictly prohibited.

**Commercial Use & "Street Vendor" Support Statement**: GPL permits and encourages commercial use. We specifically support individual creators, street vendors, and small businesses to earn a living through their craft. You may freely use this software to generate models and sell physical prints without additional permission.

---

## Acknowledgments

Special thanks to:

- **HueForge** - For pioneering optical color mixing in FDM printing
- **AutoForge** - For democratizing multi-color workflows
- **The 3D printing community** - For continuous innovation

---

## Contributors

<a href="https://github.com/MOVIBALE/Lumina-Layers/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MOVIBALE/Lumina-Layers" />
</a>

Made with ❤️ by all our contributors!

⭐ Star this repo if you find it useful!

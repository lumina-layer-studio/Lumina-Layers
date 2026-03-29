<p align="center">
  <img src="logo.png" width="128" alt="Lumina Studio Logo">
</p>

<h1 align="center">Lumina Studio</h1>

<p align="center">
  Physics-Based Multi-Material FDM Color System
</p>

<p align="center">
  <a href="https://github.com/MOVIBALE/Lumina-Layers/stargazers">
    <img src="https://img.shields.io/github/stars/MOVIBALE/Lumina-Layers?style=social" alt="Stars">
  </a>
  &nbsp;
  <a href="https://github.com/MOVIBALE/Lumina-Layers/releases/latest">
    <img src="https://img.shields.io/github/v/release/MOVIBALE/Lumina-Layers?label=Latest%20Release" alt="Release">
  </a>
  &nbsp;
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-GPL%20v3.0-blue.svg" alt="License">
  </a>
</p>

<p align="center">
  <a href="README_CN.md">📖 中文文档 / Chinese Version</a>
</p>

---

<h2 align="center">Official Links & Community</h2>

<p align="center"><b>GitHub Repository:</b></p>
<p align="center">
  <a href="https://github.com/MOVIBALE/Lumina-Layers">
    <img src="https://img.shields.io/badge/GitHub-Lumina--Layers-181717?style=for-the-badge&logo=github" alt="GitHub">
  </a>
</p>

<p align="center"><b>Follow us on Bilibili:</b></p>
<p align="center">
  <a href="https://b23.tv/CCxxiKC">
    <img src="https://img.shields.io/badge/Bilibili-Lumina%20Studio-00A1D6?style=for-the-badge&logo=bilibili&logoColor=white" alt="Bilibili">
  </a>
</p>

<p align="center"><b>Join our QQ Group:</b></p>
<p align="center">
  <a href="https://qm.qq.com/q/vocxOMTnj2">
    <img src="https://img.shields.io/badge/QQ%20Group-1065401448-EB1923?style=for-the-badge&logo=tencentqq&logoColor=white" alt="QQ Group">
  </a>
</p>

---

## Project Status

**Current Version**: v1.6.7  
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

## Changelog

For detailed version history, see [CHANGELOG.md](CHANGELOG.md) / [CHANGELOG_CN.md](CHANGELOG_CN.md).

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

### Phase 2: Manga Mode (Monochrome) ✅ COMPLETE

**Target**: Manga panels, Ink drawings, High-contrast illustrations

- ✅ Black & White layering using thickness-based grayscale (Lithophane logic)
- ✅ Simulating screen tones (Ben-Day dots)

### Phase 3: Dynamic Palette Engine ✅ COMPLETE

**Target**: Adaptive color systems

- ✅ Dynamic Palette Support (4/6/8 colors auto-selection)
- ✅ Intelligent color clustering algorithms
- ✅ Adaptive dithering algorithms
- ✅ Perceptual color difference optimization

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
- **[ChromaStack](https://github.com/borealis-zhe/ChromaStack)** - A multi-color layer stacking model generator for FDM printers, using light transmission algorithms to achieve photo-level color effects
- **[LD_ColorLayering](https://github.com/Luban-Daddy/LD_ColorLayering)** - An H5 web application for converting images to multi-color 3D models (3MF), supporting multiple color modes and layer stacking
- **[ChromaPrint3D](https://github.com/Neroued/ChromaPrint3D)** - Converts images to multi-color 3MF models with Bambu Studio preset auto-injection and filament slot matching
- **The 3D printing community** - For continuous innovation

---

## Contributors

<a href="https://github.com/MOVIBALE/Lumina-Layers/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MOVIBALE/Lumina-Layers" />
</a>

Made with ❤️ by all our contributors!

⭐ Star this repo if you find it useful!

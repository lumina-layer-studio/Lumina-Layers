<p align="center">
  <img src="logo.png" width="128" alt="Lumina Studio Logo">
</p>

<h1 align="center">Lumina Studio</h1>

<p align="center">
  A Multi-Material FDM Color System Based on Physical Calibration
</p>

<p align="center">
  <a href="https://github.com/MOVIBALE/Lumina-Layers/stargazers">
    <img src="https://img.shields.io/github/stars/MOVIBALE/Lumina-Layers?style=social" alt="Stars">
  </a>
  &nbsp;
  <a href="https://github.com/MOVIBALE/Lumina-Layers/releases/latest">
    <img src="https://img.shields.io/github/v/release/MOVIBALE/Lumina-Layers?label=Latest%20Version&amp;include_prereleases" alt="Release">
  </a>
  &nbsp;
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-GPL%20v3.0-blue.svg" alt="License">
  </a>
</p>

<p align="center">
  <a href="README_CN.md">📖 Chinese Version / 中文文档</a>
</p>

---

<h2 align="center">Official Links & Community</h2>

<p align="center">
  <b>GitHub :</b>
  <a href="https://github.com/MOVIBALE/Lumina-Layers">
    <img src="https://img.shields.io/badge/GitHub-Lumina--Layers-181717?style=for-the-badge&logo=github" alt="GitHub">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>Join Discord :</b>
  <a href="https://discord.gg/57whRe3C8G">
    <img src="https://img.shields.io/badge/Discord-Lumina%20Studio-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

<p align="center">
  <b> YouTube:</b>
  <a href="https://www.youtube.com/channel/UCyP2Euw9whk1j-MT8d652Kw">
    <img src="https://img.shields.io/badge/YouTube-Lumina%20Studio-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="YouTube">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>Patreon:</b>
  <a href="https://www.patreon.com/Lumina_studio">
    <img src="https://img.shields.io/badge/Patreon-Lumina%20Studio-FF424D?style=for-the-badge&logo=patreon&logoColor=white" alt="Patreon">
  </a>
</p>

<p align="center">
  <b>Bilibili:</b>
  <a href="https://b23.tv/CCxxiKC">
    <img src="https://img.shields.io/badge/Bilibili-Lumina%20Studio-00A1D6?style=for-the-badge&logo=bilibili&logoColor=white" alt="Bilibili">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>QQ Group:</b>
  <a href="https://qm.qq.com/q/vocxOMTnj2">
    <img src="https://img.shields.io/badge/QQ%20Group-1065401448-EB1923?style=for-the-badge&logo=tencentqq&logoColor=white" alt="QQ Group">
  </a>
</p>

## Project Status

**Current Version**: v1.6.7  
**License**: GNU GPL v3.0  
**Nature**: Non-profit Open Source Community Project

---
## Project Background
To simplify the steep learning curve of software such as HueForge/FlatForge and the requirement for specific filaments, Lumina uses brute-force and simplified brute-force methods based on physical calibration to obtain actual printed colors. The current mode does not involve any color theory calculations (color calculation based on color/TD values may be introduced in advanced features of version 2.0 in the future). The current approach is: Print - Capture - Extract Color - Map Stacking Formula Based on Extracted Color - Print (this is a color matching function, inspired by the default color matching in Autoforge and CMYK Lithophane).

## Features
**Color Modes**

2/4/5/6/8 Colors

**Generation Modes**

High-fidelity mode / Pixel mode / SVG mode

**Other Features**

Custom color card and color calibration functions

Adjust the number of generated colors

Image cutout / background removal

Independent backplate

Outline

Add transparent layer

Cloisonné enamel mode

Replace colors in the image after generating preview

**Advanced Features**

Color Formula Search

Merge color card function

## Open Ecosystem

### About .npy Calibration Files

All calibration presets (.npy files) are **completely free and open**, following these principles:

- **Vendor Lock-in Rejection**: We **will never** force users to use specific filament brands, or require manufacturers to produce specific "compatible filaments" — past, present, or future. This violates the spirit of open source.
  
- **Community Collaboration**: All users, organizations, and filament manufacturers are welcome to submit PRs to synchronize calibration presets. Your printer data can help others.
- No additional testing tools required — only a 3D printer and a phone/camera.

**Open Data = Community Co-creation**

---

## Installation

### Clone Repository

```bash
git clone https://github.com/MOVIBALE/Lumina-Layers.git
cd Lumina-Layers
```

### Option 1：Docker 

Using Docker is the easiest way to run Lumina Studio without worrying about system-level dependencies (such as cairo or pkg-config).
1. **Build the lumina image**：
   ```bash
   docker build -t lumina-layers .
   ```

2. **Run Container**：
   ```bash
   docker run -d -p 7860:7860 lumina-layers
   ```

3. Open in your browser `http://localhost:7860`。

### Option 2：Local Installation

**Basic Dependencies**：
```bash
pip install -r requirements.txt
```

---

## User Guide

### Quick Start

```bash
python main.py
```
This will launch the web interface containing all three modules in a browser tab.

---

## Tech Stack

| Component | Technology |
|------|------|
| Core Logic | Python (NumPy for voxel operations) |
| Geometry Engine | Trimesh (mesh generation and export) |
| UI Framework | Gradio 4.0+ |
| Vision Stack | OpenCV (perspective and color extraction) |
| Color Matching | SciPy KDTree |
| 3D Preview | Gradio Model3D (GLB format) |

---


## License

This project is licensed under the **GNU GPL v3.0** open-source license.

- ✅ **Open Source & Freedom**: You are free to run, study, modify and distribute this software.
- 🔄 **Strong Copyleft**: If you modify and distribute this software, you must publish your source code under the GPL v3.0 license.
- ❌ **No Closed-Source**: It is strictly prohibited to package and sell this software or its derivatives as closed-source products.

**Commercial Use & "Small Creator" Support Statement**: This project supports and encourages individual creators, small vendors and micro-enterprises to earn income through labor. You may freely use this software to generate models and sell physical printed products without additional authorization.

---

## Technical Origin & Statement

### Technical Inspiration

This project is inspired by the following works:

- **HueForge** – The first project to commercialize FDM multi-layer stacking color mixing technology.
- **AutoForge** – Automated color matching built on Hueforge.
- **CMYK Backlit Lithophane** – Multi-layer stacked backlit lithophane effects in 3D printing based on transmission and subtractive color principles.

### Technical Differences & Positioning

Traditional tools rely on theoretical calculations (such as TD1/TD0 transmission distance values), but these parameters often fail due to various objective variations.

**Lumina Studio 1.X uses a brute-force approach**:
1. Print physical calibration charts with 1024+ colors (full permutation for 2 colors × 5 layers, 4 colors × 5 layers; simplified brute-force for 6 colors × 5 layers, 8 colors × 5 layers)
2. Scan via photography and extract real RGB data
3. Build a "Lookup Table (LUT) of actual results"
4. Match using nearest-neighbor algorithm (similar to Bambu Lab's keychain generator matching)

### Prior Art Statement

The core principle of FDM multi-layer color mixing was publicly disclosed by software such as HueForge between 2022 and 2023, and constitutes **prior art**.

The author of Hueforge has also clarified that such technical principles have entered the public domain. In most countries and regions, patents on these principles would almost certainly be rejected if rigorously examined by patent offices.

These authors chose openness to support community development, so this technology is generally **not patentable**.

Lumina Studio will remain open-source, collaborative, and non-profit. Public oversight is welcome.

- This is an open-source non-profit project with no bundled sales, and no features will be locked behind paywalls.
- If you or your company wish to support the project’s continued development, please contact us. Sponsored products will only be used for software development, testing and optimization.
- Sponsorship represents support for the project and does not constitute any commercial binding.
- Sponsorship arrangements that would influence technical decisions or open-source licenses are rejected.

Lumina Studio has not referenced any pending patent content, as most such patents only include specifications and do not disclose code in the short term; blind reference would hinder independent development.

**Special thanks to HueForge for their support and understanding of open source!**

---
## Acknowledgments
Special Thanks to:

- **[Hueforge](https://shop.thehueforge.com/)**
- **[AutoForge](https://github.com/AutoForgeAI/autoforge)**
- **[ChromaStack](https://github.com/borealis-zhe/ChromaStack)** 
- **[LD_ColorLayering](https://github.com/Luban-Daddy/LD_ColorLayering)** 
- **[ChromaPrint3D](https://github.com/Neroued/ChromaPrint3D)** 

---

## Contributors
<a href="https://github.com/MOVIBALE/Lumina-Layers/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MOVIBALE/Lumina-Layers" />
</a>

Made with care by all contributors!
---
⭐ Star this repo if you find it useful!

# LUT 色卡文件命名规范 / LUT File Naming Convention

> 本规范用于统一 `.npy` 色卡预设文件的命名格式。
> 规范命名可确保软件在**合并色卡**时精确识别每个 LUT 的颜色模式和色彩配方。
>
> This convention standardizes `.npy` LUT preset file naming.
> Proper naming ensures the software can accurately identify each LUT's
> color mode and color recipe during **LUT merging**.

---

## 命名格式 / Naming Format

```
{品牌}&{耗材类型}&{色彩关键字}&{颜色描述}-{日期}.npy
{Brand}&{Material}&{ColorKeyword}&{ColorDescription}-{Date}.npy
```

### 字段说明 / Field Description

| 字段 / Field | 说明 / Description | 示例 / Example |
|---|---|---|
| 品牌 Brand | 耗材品牌名 / Filament brand | `Bambulab`, `Aliz`, `Jayo` |
| 耗材类型 Material | 耗材材质 / Material type | `PLA`, `PETG`, `PLA+` |
| **色彩关键字 ColorKeyword** | **⚠️ 关键字段，见下表** | `RYBW`, `CMYW`, `BW` |
| 颜色描述 ColorDescription | 实际颜色名称（可选）/ Actual color names (optional) | `红-蓝-黄-白` |
| 日期 Date | 校准日期（可选）/ Calibration date (optional) | `20260227` |

---

## ⚠️ 色彩关键字（核心） / Color Keywords (Critical)

**文件名中必须包含以下关键字之一，软件通过关键字识别颜色配方：**

**The filename MUST contain one of the following keywords. The software uses these keywords to identify the color recipe:**

### 黑白 2 色 / BW 2-Color

| 关键字 Keyword | 颜色 Colors | 8色槽位映射 8-Color Slot Mapping |
|---|---|---|
| `BW` | 白+黑 / White+Black | 0→White(0), 1→Black(4) |

### 4 色模式 / 4-Color Mode

| 关键字 Keyword | 颜色 Colors | 8色槽位映射 8-Color Slot Mapping |
|---|---|---|
| `RYBW` | 红-黄-蓝-白 / Red-Yellow-Blue-White | 0→White(0), 1→Red(5), 2→Yellow(3), 3→DeepBlue(6) |
| `CMYW` | 青-品红-黄-白 / Cyan-Magenta-Yellow-White | 0→White(0), 1→Cyan(1), 2→Magenta(2), 3→Yellow(3) |

### 6 色模式 / 6-Color Mode

| 关键字 Keyword | 颜色 Colors | 8色槽位映射 8-Color Slot Mapping |
|---|---|---|
| `CMYW` (默认) | 白-青-品红-绿-黄-黑 | 0→White(0), 1→Cyan(1), 2→Magenta(2), 3→Green(7), 4→Yellow(3), 5→Black(4) |
| `RYBW` | 白-红-蓝-绿-黄-黑 | 0→White(0), 1→Red(5), 2→DeepBlue(6), 3→Green(7), 4→Yellow(3), 5→Black(4) |

> 6色文件名中包含 `RYBW` → 识别为 RYBWGK 配方
> 6色文件名中包含 `CMYW` 或不含关键字 → 识别为 CMYWGK 配方（默认）
>
> 6-Color filename containing `RYBW` → detected as RYBWGK recipe
> 6-Color filename containing `CMYW` or no keyword → detected as CMYWGK recipe (default)

### 8 色模式 / 8-Color Mode

8 色无需关键字区分，所有 8 色 LUT 使用统一槽位：

8-Color does not need a keyword distinction. All 8-Color LUTs use the unified slot mapping:

| 槽位 Slot | 颜色 Color |
|---|---|
| 0 | White 白 |
| 1 | Cyan 青 |
| 2 | Magenta 品红 |
| 3 | Yellow 黄 |
| 4 | Black 黑 |
| 5 | Red 红 |
| 6 | DeepBlue 克莱因蓝 |
| 7 | Green 绿 |

---

## 正确命名示例 / Correct Naming Examples

### 4 色 / 4-Color
```
✅ Bambulab&PLA&RYBW&红-蓝-黄-白.npy
✅ Bambulab&PLA&CMYW&青-品红-黄-白.npy
✅ Aliz&PETG&RYBW&红-蓝-黄-白-20260207.npy
✅ Aliz&PETG&CMYW&品红-青-黄-白-20260207.npy
```

### 6 色 / 6-Color
```
✅ Aliz&PETG&CMYW&品红-青-黄-绿-白-黑-20260207.npy
✅ Aliz&PETG&RYBW&红-蓝-黄-绿-白-黑-20260207.npy
✅ Bambulab&PLA&CMYW&青-品红-黄-绿-白-黑.npy
```

### 8 色 / 8-Color
```
✅ Aliz&PETG&8色&大红-品红-青-克莱因蓝-黄-白-柠檬绿-黑.npy
✅ Bambulab&PLA&8色&红-品红-青-蓝-黄-白-绿-黑.npy
```

### 黑白 / BW
```
✅ Bambulab&PLA&BW&白-黑.npy
✅ Bambulab_basic_BW.npy
```

---

## ❌ 错误命名示例 / Incorrect Naming Examples

```
❌ Aliz&PETG&六色&红-蓝-黄-绿-白-黑-20260207.npy
   → 缺少 RYBW/CMYW 关键字，软件无法区分6色配方
   → Missing RYBW/CMYW keyword, software cannot distinguish 6-Color recipe

❌ 6色大红色-克莱因蓝-黄色-柠檬绿-黑色-白色.npy
   → 缺少关键字，将被默认识别为 CMYWGK（可能不正确）
   → Missing keyword, will default to CMYWGK (may be incorrect)

❌ my_custom_lut.npy
   → 无任何标识，4色默认RYBW，6色默认CMYWGK
   → No identifier, 4-Color defaults to RYBW, 6-Color defaults to CMYWGK
```

---

## 识别逻辑说明 / Detection Logic

软件通过以下两步识别色卡配方：

The software identifies the color recipe in two steps:

1. **色数检测 / Color Count Detection**：根据 `.npy` 文件中的颜色数量自动判断模式
   - 32 颜色 → BW
   - 1024 颜色 → 4-Color
   - 1296 颜色 → 6-Color
   - 2738 颜色 → 8-Color

2. **子类型检测 / Subtype Detection**：对于 4 色和 6 色，扫描文件名中的关键字
   - 文件名包含 `RYBW`（不区分大小写）→ RYBW 系列
   - 文件名包含 `CMYW`（不区分大小写）→ CMYW 系列
   - 都不包含 → 4色默认 RYBW，6色默认 CMYWGK

---

## 文件夹结构建议 / Recommended Folder Structure

```
lut-npy预设/
├── {品牌 Brand}/
│   ├── {耗材 Material}/
│   │   ├── 4色/
│   │   │   ├── {Brand}&{Material}&RYBW&{colors}.npy
│   │   │   └── {Brand}&{Material}&CMYW&{colors}.npy
│   │   ├── 6色/
│   │   │   ├── {Brand}&{Material}&CMYW&{colors}.npy
│   │   │   └── {Brand}&{Material}&RYBW&{colors}.npy
│   │   └── 8色/
│   │       └── {Brand}&{Material}&8色&{colors}.npy
│   └── 使用须知README.txt
└── Custom/
    ├── *.npy (个人自定义LUT)
    └── *.npz (合并后的LUT)
```

---

## 合并色卡说明 / Merged LUT Notes

合并后的 `.npz` 文件由软件自动命名，格式为：

Merged `.npz` files are automatically named by the software:

```
Merged_{模式1}+{模式2}+..._{日期}_{时间}.npz
```

例如 / Example: `Merged_8-Color+6-Color+BW+4-Color_20260227_222117.npz`

合并后的 LUT 统一使用 8 色槽位空间，无需额外关键字。

Merged LUTs use the unified 8-Color slot space and do not need additional keywords.

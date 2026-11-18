# 固定回归输入

这些小样本来自迁出前的 `Lumina-Layers` `1308c06fc`，仅供自动化回归测试，不进入软件可选 LUT 列表或发行资源包。文件内容保持原样，完整生产数据由 `Lumina-materials` 维护。

| 文件 | 原路径 | 验证用途 |
| --- | --- | --- |
| `必趣&PLAGO&6色RYBWGK.npy` | `BIQU/必趣&PLAGO&6色RYBWGK.npy` | 通道顺序、palette 元数据 |
| `Bambulab&PLA&RYBW&红-黄-蓝-白.npy` | `Custom/Bambulab&PLA&RYBW&红-黄-蓝-白.npy` | SVG 转换与空图错误 |
| `bambulab_pla_basic_rybw.npy` | `bambulab/bambulab_pla_basic_rybw.npy` | 深灰匹配时保持中性色 |
| `赛纳&8色PLA-红-黄-蓝-品红-青-白-绿-黑.npy` | `赛纳/赛纳&8色PLA-红-黄-蓝-品红-青-白-绿-黑.npy` | 模型表面 8 色材料身份 |
| `快造&4色PLA&RYBW.npy` | `snapmaker/快造&4色PLA&RYBW.npy` | 模型表面栅格转换 |

既有冻结基线仍使用 `../frozen_assets` 的原始样本；本次迁移不更新历史性能基线或结果阈值。

同目录的 `精亮`、`赛纳`、`Aliz`、`Custom`、`彩多屋` 子目录保留既有性能/复现脚本实际使用的原始输入（合计不足1MiB），文件名、字节和模式不变。它们只用于这些脚本，不进入发行包或运行时资源扫描。

<p align="center">
  <img src="logo.png" width="128" alt="Lumina Studio Logo">
</p>

<h1 align="center">Lumina Studio</h1>

<p align="center">
  基于物理校准的多材料FDM色彩系统
</p>

<p align="center">
  <a href="https://github.com/MOVIBALE/Lumina-Layers/stargazers">
    <img src="https://img.shields.io/github/stars/MOVIBALE/Lumina-Layers?style=social" alt="Stars">
  </a>
  &nbsp;
  <a href="https://github.com/MOVIBALE/Lumina-Layers/releases/latest">
    <img src="https://img.shields.io/github/v/release/MOVIBALE/Lumina-Layers?label=最新版本&amp;include_prereleases" alt="Release">
  </a>
  &nbsp;
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/协议-GPL%20v3.0-blue.svg" alt="License">
  </a>
</p>

<p align="center">
  <a href="README.md">📖 English Version / 英文文档</a>
</p>

---

<h2 align="center">官方链接与社区</h2>

<p align="center">
  <b>GitHub 仓库：</b>
  <a href="https://github.com/MOVIBALE/Lumina-Layers">
    <img src="https://img.shields.io/badge/GitHub-Lumina--Layers-181717?style=for-the-badge&logo=github" alt="GitHub">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>加入 Discord 社区：</b>
  <a href="https://discord.gg/57whRe3C8G">
    <img src="https://img.shields.io/badge/Discord-Lumina%20Studio-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

<p align="center">
  <b>官方网站：</b>
  <a href="https://www.luminastudio.com.cn/">
    <img src="https://img.shields.io/badge/Website-Lumina%20Studio-2EAADC?style=for-the-badge" alt="Website">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>项目 Wiki：</b>
  <a href="https://wiki.luminastudio.com.cn/">
    <img src="https://img.shields.io/badge/Wiki-项目文档-4C8EDA?style=for-the-badge" alt="Wiki">
  </a>
</p>

<p align="center">
  <b>赞助与支持：</b>
  <a href="https://www.luminastudio.com.cn/sponsors">
    <img src="https://img.shields.io/badge/Sponsors-赞助商与支持名单-8A63D2?style=for-the-badge" alt="Sponsors">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>爱发电：</b>
  <a href="https://www.ifdian.net/a/MMMINNN?utm_source=copylink&utm_medium=link">
    <img src="https://img.shields.io/badge/爱发电-支持 Lumina-946CE6?style=for-the-badge" alt="Aifadian">
  </a>
</p>

<p align="center">
  <b>订阅 YouTube 频道：</b>
  <a href="https://www.youtube.com/channel/UCyP2Euw9whk1j-MT8d652Kw">
    <img src="https://img.shields.io/badge/YouTube-Lumina%20Studio-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="YouTube">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>在 Patreon 支持我们：</b>
  <a href="https://www.patreon.com/Lumina_studio">
    <img src="https://img.shields.io/badge/Patreon-Lumina%20Studio-FF424D?style=for-the-badge&logo=patreon&logoColor=white" alt="Patreon">
  </a>
</p>

<p align="center">
  <b>关注我们的 Bilibili：</b>
  <a href="https://b23.tv/CCxxiKC">
    <img src="https://img.shields.io/badge/Bilibili-Lumina%20Studio-00A1D6?style=for-the-badge&logo=bilibili&logoColor=white" alt="Bilibili">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <b>加入 QQ 交流群：</b>
  <a href="https://qm.qq.com/q/vocxOMTnj2">
    <img src="https://img.shields.io/badge/QQ%20群-1065401448-EB1923?style=for-the-badge&logo=tencentqq&logoColor=white" alt="QQ Group">
  </a>
</p>

---

## 项目状态

**当前版本**: v1.6.9

**协议**: GNU GPL v3.0

**性质**: 非营利性开源社区项目

**官方网站**: https://www.luminastudio.com.cn/

**项目 Wiki**: https://wiki.luminastudio.com.cn/

**赞助商与支持名单**: https://www.luminastudio.com.cn/sponsors

**国内赞助入口**: https://www.ifdian.net/a/MMMINNN?utm_source=copylink&utm_medium=link

---
## 项目背景
Lumina为了简化用户使用hueforge/flatforge等其他软件学习门槛过高或需要使用指定要求的耗材的问题，基于物理校准使用了穷举法和简化穷举法来获得实际打印颜色，目前的模式并未带来任何颜色理论计算（未来可能会在2.0的高级功能中推出基于颜色/td值等的颜色计算玩法），目前采取的方法是打印-拍摄-提取颜色-根据提取的颜色映射堆叠配方-打印（这像是一种颜色匹配功能，就像是你在autoforge和CMYK Lithophane那样会默认给你匹配一些颜色的功能一样，所以受此启发）

## Lumina Studio 2.0

Lumina 1.x 已经证明了基于实物校准和 LUT 的多色 FDM 打印路线是可行的。Lumina Studio 2.0 是 1.x 之后的新一代版本，界面、流程和内部架构都会重做，目标是把这条路线做成更稳定、更易用、更完整的日常工具。

2.0 会围绕下面这些方向升级：

**一、从图片到彩色模型，一步到位**

- 上传图片即可生成可打印的彩色模型，图片预处理、配色、预览、生成模型的链路尽量整合在同一套流程里。
- 直接输出多色 3MF 文件，爱乐酷、Snapmaker、拓竹、创想三维等主流多色打印机和切片软件会作为适配目标。

**二、配色更精准，调色更高效**

- 新一代处理路径会继续提高颜色还原效果，减少颜色层次过度丢失。
- 内置多个主流品牌的精校 LUT，开箱即可用，也欢迎继续提交社区预设。
- 可以对比原始图像和生成结果，更容易发现哪里颜色不满意。
- 调色响应更快，换色后的效果能更快看到。
- 色块单选、多选、撤销等颜色工具会更完整。
- 渐变过渡、浮雕厚度等细节会尽量做成可控参数。

**三、文创周边结构，一站搞定**

- 钥匙扣挂孔支持自定义尺寸和位置。
- 冰箱贴磁铁孔、白色外轮廓、透明镀层会更自然地集成进主流程。

**四、支持 SVG 矢量图输入**

- 2.0 会继续完善 SVG 输入和矢量化导出。Logo、二次元、剪影风格等作品可以得到更干净的边缘效果。

**五、适配你的打印机与切片软件**

- 内置多款打印机热床配置，自动约束模型尺寸，减少生成超出打印范围的文件。
- 在设置中指定打印机型号和切片软件后，后续系统会尽量自动适配默认切片参数。
- 大画幅自动拼接功能会继续完善，热床尺寸不够时也能切分打印超大尺寸作品。

**六、日常使用体验**

- 中英文可以随时切换，后续会基于国际化框架扩展更多语言。
- 生成前可以在浏览器里旋转检查 3D 预览，尽量做到所见即所得。
- 输出目录与缓存支持一键清理，临时文件会自动过期回收。

### 常见问题

**Q1：Lumina 2.0 和 1.x 是什么关系？**

2.0 是 1.x 的新一代版本。叠层混色的核心原理相同，但界面、功能、架构都会重做。可以理解为：1.x 证明了技术上可行，2.0 目标是做成真正成熟的版本。

**Q2：众筹后还会继续开源吗？**

会。Lumina 2.0 的稳定版会继续开源，供大家研究学习。这次众筹的意义是把 2.0 从雏形孵化成稳定、易用、可长期维护升级的软件。

**Q3：支持者会有“独占功能”吗？**

不会做付费专属功能。支持者会根据档位获得更方便运行的稳定版或开发版打包；发布后，其他用户仍然可以通过 GitHub 手动部署稳定版运行。开发版主要用于开发验证，功能经过一段时间评估、确认可靠后，会更新到稳定版中。

**Q4：个人创作者、小店主或小微企业可以商用吗？**

可以。Lumina 支持个人创作者、小店主通过 Lumina 生成的模型制作成品并获取收益。

## 功能
**颜色模式 Color Modes**

2/4/5/6/8色

**生成模式 Generation Modes**

高保真模式/像素模式/svg模式

High-fidelity mode / Pixel mode / SVG mode

**其他功能 Other Features**

自定义色卡和校准颜色功能 Custom color card and color calibration functions

调节生成颜色的数量 Adjust the number of generated colors.

抠图功能 image cutout / background removal

背板独立 Independent backplate

描边 Outline

添加透明层 Add transparent layer

掐丝珐琅模式 wiry enamel(cloisonné enamel)

生成预览后替换图中颜色 Replace colors in the image

**高级功能 Advanced Features**

颜色配方查询功能 Color Formula Search

合并色卡功能 Merge color card function


## 生态开放

### 关于 .npy 校准文件

所有校准预设（`.npy`文件）**完全免费开放**，遵循以下原则：

- **拒绝供应商锁定**：过去、现在、未来，我们**永远不会**强迫用户使用特定耗材品牌，也不会要求制造商生产符合要求的特定的"兼容耗材"。这违背开源精神。
  
- **社区共建**：欢迎所有用户、组织、耗材厂商提交PR，同步校准预设。你的打印机数据可以帮助他人。
- 无需任何其他测试工具，只需要你有3D打印机和手机/相机。

**数据开放 = 社区共创**

---

## 赞助与支持

Lumina Studio 是非营利性开源社区项目。赞助只代表对项目开发、测试和社区维护的支持，不影响技术路线、开源协议，也不构成任何耗材或设备绑定。

- 国内赞助入口（爱发电）：https://www.ifdian.net/a/MMMINNN?utm_source=copylink&utm_medium=link
- 官方赞助商与支持名单：https://www.luminastudio.com.cn/sponsors
- 项目 Wiki：https://wiki.luminastudio.com.cn/
- 官方网站：https://www.luminastudio.com.cn/

### 爱发电档位说明

- **18 元：一杯奶茶支持开发**
  - 2.0 正式版本的打包，可一键运行，无需开发环境部署。
  - 2.0 发布后一个月内的更新和修复版本打包。

- **35 元：基础 Coding Plan**
  - 包含 18 元档全部权益。
  - 支持单台电脑使用可自动更新后续 2.x 版本的稳定版。

- **68 元：我想参加内测**
  - 包含 35 元档全部权益。
  - 可参与后续 2.x 版本内测。

- **1999 元：企业 / 品牌支持**
  - 包含以上全部权益。
  - 品牌鸣谢（官网 + 软件内）。
  - 使用场景专项交流。
  - 支持 10 台电脑设备使用可自动更新后续 2.x 版本的稳定版。

风险提示：爱发电是对开源项目和创作者的支持，不是商品交易保证；支持行为不代表项目提供付费专属功能，也不影响项目继续开源。

### 已适配 / 参与支持的耗材品牌

赞助商页面会持续更新。当前公开列出的耗材适配与支持品牌包括：

爱丽兹 / Aliz、爱乐酷 / Elegoo、必应 / Bing3D、必趣 / BIQU、彩多屋 / CAILAB、快造 / Snapmaker、Inslogic、精亮 / CHING LEUNG、KYNIX、魔创、瑞贝思 / REBIRTH3D、赛纳 / Sailner、拓竹 / Bambu Lab、XYD 小明耗材、蚁在云端 / Antinsky、纵维立方 / Anycubic。

### 产品支持

当前公开列出的产品支持品牌包括：

必趣 / BIQU、大凡光学 / dfoptix、菲托斯 / Phaetus、快造 / Snapmaker、蚁在云端 / Antinsky、纵维立方 / Anycubic。

### 特别感谢

特别感谢爱丽兹、爱乐酷、奥罗玛斯、精亮科技、吉林大学机械与航空航天工程学院 / 吉林大学智能制造创新创业实践示范基地、快造科技、无境新材等对项目的支持。

---




## 安装

### 克隆仓库

```bash
git clone https://github.com/MOVIBALE/Lumina-Layers.git
cd Lumina-Layers
```

### 选项 1：Docker (推荐)

使用 Docker 是运行 Lumina Studio 最简单的方法，无需担心系统级依赖项（如 `cairo` 或 `pkg-config`）。

1. **构建镜像**：
   ```bash
   docker build -t lumina-layers .
   ```

2. **运行容器**：
   ```bash
   docker run -d -p 7860:7860 lumina-layers
   ```

3. 在浏览器中打开 `http://localhost:7860`。

### 选项 2：本地安装

**基础依赖**（必需）：
```bash
pip install -r requirements.txt
```

---

## 使用指南

### 快速启动

```bash
python main.py
```

这将在标签页中启动包含所有三个模块的Web界面。

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 核心逻辑 | Python（NumPy用于体素操作） |
| 几何引擎 | Trimesh（网格生成与导出） |
| UI框架 | Gradio 4.0+ |
| 视觉栈 | OpenCV（透视与颜色提取） |
| 色彩匹配 | SciPy KDTree |
| 3D预览 | Gradio Model3D（GLB格式） |

---


## 许可协议

本项目采用 **GNU GPL v3.0** 开源协议。

- ✅ **开源与自由**：你可以自由地运行、研究、修改和分发本软件。
- 🔄 **强传染性 (Copyleft)**：如果你修改了本软件并分发，你必须在 GPL v3.0 协议下公开你的源代码。
- ❌ **禁止闭源**：严禁将本软件或其衍生作品闭源打包销售。

**商业使用与"小摊主"支持声明**：本项目支持并鼓励个人创作者、小摊主及小微企业通过劳动获取收益。你可以自由地使用本软件生成模型并销售物理打印成品，无需额外授权。

---
## 技术来源与技术声明

### 技术来源

本项目受以下项目启发：

- **HueForge** - 首个将FDM多层堆叠混色技术做成商业软件的项目。
- **AutoForge** - 基于Hueforge制作的自动化色彩匹配。
- **CMYK背光浮雕画** - 基于透射原理和减色原理在3D打印中得到多层堆叠背光浮雕的效果。

### 技术区别与定位

传统工具依赖理论计算（如TD1/TD0透射距离值），但这些参数极易因各种客观原因差异而失效。

**Lumina Studio 1.X 采用"穷举法"路线**：
1. 打印1024及更多色物理校准板（2色x5层的全排列），（4色×5层的全排列）,(6色x5层的简化穷举)，（8色x5层的简化穷举）
2. 拍照扫描，提取真实RGB数据
3. 建立"实际结果查找表"（LUT）
4. 用最近邻算法匹配（类似于Bambulab的钥匙扣生成器的匹配）


### 现有技术（Prior Art）声明

FDM多层叠色的核心原理已于2022-2023年间由HueForge等软件公开披露，属于**现有技术**（Prior Art）。
Hueforge作者也明确，此类技术原理已经进入公共领域，在绝大部分国家和地区，如果专利局认真审核，原理性专利一定会被驳回。
这些作者选择保持开放以帮助社区发展，因此该技术通常**不具备专利性**。

Lumina Studio一直将以开源，互助，非盈利性的定位保持下去，欢迎各位监督。
- 本项目为开源非盈利项目，不会进行任何捆绑销售，并且不会将任何功能做成付费功能。
- 如果你或你的企业希望支持项目持续发展，欢迎联系。赞助的产品等将仅用于软件的开发和测试优化。
- 赞助仅代表对项目的支持，赞助行为不构成任何商业绑定。
- 拒绝任何影响技术决策或开源协议的赞助合作。
Lumina Stuido并未参考任何申请的专利内容，因为该类专利大部分情况下只有说明书，并且短期内不会公开技术代码，盲目参考这些专利，会影响自身开发的思路。
**特别感谢HueForge对开源的支持和理解！**

---
## 致谢

特别感谢：

- **[Hueforge](https://shop.thehueforge.com/)**
- **[AutoForge](https://github.com/AutoForgeAI/autoforge)**
- **[ChromaStack](https://github.com/borealis-zhe/ChromaStack)** 
- **[LD_ColorLayering](https://github.com/Luban-Daddy/LD_ColorLayering)** 
- **[ChromaPrint3D](https://github.com/Neroued/ChromaPrint3D)** 

---

## 贡献者

<a href="https://github.com/MOVIBALE/Lumina-Layers/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MOVIBALE/Lumina-Layers" />
</a>

由所有贡献者精心制作！

---
⭐ 如果觉得有用，请给个Star！

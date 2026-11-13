export interface LocalizedText {
  zh: string;
  en: string;
}

export interface AnnouncementSection {
  category: LocalizedText;
  items: LocalizedText[];
}

export interface AnnouncementEntry {
  version: string;
  title: LocalizedText;
  sections: AnnouncementSection[];
}

export const ANNOUNCEMENTS: ReadonlyArray<AnnouncementEntry> = [
  {
    version: "2026-11-11",
    title: { zh: "Lumina Layers — 11 月更新速览", en: "Lumina Layers — November updates" },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "创意工坊支持在本机运行带 Python 处理功能的模块，可按需准备依赖、查看任务进度，并把结果送到图像转换。切换页面不会中断任务。",
            en: "Creative Workshop can run modules with local Python processing. Prepare dependencies when needed, follow task progress and send results to Image Conversion. Switching pages keeps tasks running.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "大图预览使用更轻的显示图，模型尺寸、打印精度和编辑用的原图保持不变。拖动挂孔时位置同步更稳定，松手或取消后可正常调整视角。",
            en: "Large images use a lighter display preview without changing model dimensions, print detail or the image used for editing. Keychain-loop positions stay in sync while dragging, and view controls resume after releasing or cancelling.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "批量生成后若合并失败，仍可逐件下载已完成的模型；关闭对应预览后，下载在保留期内仍可使用。",
            en: "If a batch cannot be merged, completed models remain available as individual downloads. They stay available for their retention period even after closing the source preview.",
          },
          {
            zh: "使用自定义 3MF 模板时，会在生成模型前提示耗材槽位不足，并说明需要多少槽位。",
            en: "Custom 3MF templates are checked for enough filament slots before model generation, with a message showing how many are needed.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-11-07",
    title: { zh: "Lumina Layers — 11 月更新速览", en: "Lumina Layers — November updates" },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "新增 Bambu H3C，可在设置中选择 0.2 或 0.4 mm 喷嘴。更新了 Bambu、QIDI、Anycubic、Flash、Snapmaker 和 Prusa 的切片配置及 Prusa 机型图片。Prusa 使用 3.0.0-alpha13 预览版。",
            en: "Added Bambu H3C with 0.2 and 0.4 mm nozzles in Settings. Updated Bambu, QIDI, Anycubic, Flash, Snapmaker and Prusa slicer profiles and Prusa printer images. Prusa uses the 3.0.0-alpha13 preview.",
          },
          {
            zh: "使用 Bambu Studio 和 X2D 时，可在「耗材配置」中指定外置料盘上安装的耗材。导出的 3MF 会保留对应的喷嘴分配。",
            en: "For the X2D in Bambu Studio, choose the filament loaded on the external spool under Filament settings. The exported 3MF keeps that nozzle assignment.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "重排、减少或合并耗材槽位时，完整保留各耗材的原生温度等设置和已有工艺参数，支持混合使用不同参数数量的原生耗材预设。",
            en: "Reordering, reducing or merging material slots preserves native temperatures and existing process settings, including native material presets with different numbers of parameters.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-10-28",
    title: { zh: "Lumina Layers — 10 月更新速览", en: "Lumina Layers — October updates" },
    sections: [
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "单独导出底板时，保留所选耗材的颜色、温度和流量等设置，避免在切片软件中套用到其他耗材。",
            en: "Exporting a separate backing preserves the selected material’s color, temperature and flow settings, so the slicer does not apply another material’s settings.",
          },
          {
            zh: "合并与批量排版保留模型原有的高度位置，并按所选打印机的实际打印区域摆放；无法安全合并的模型会给出提示。",
            en: "Merging and batch layout preserve each model’s vertical position and use the selected printer’s actual print area. Models that cannot be merged safely now show an explanation.",
          },
          {
            zh: "大画幅生成只有部分分块成功时，仍可下载已生成的文件，并明确提示缺失的分块；提示会随对应下载结果一起保留或清除。",
            en: "If only some large-format tiles finish generating, you can still download the completed files and see which tiles are missing. The warning stays with its download result and clears when that result is removed.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-10-26",
    title: { zh: "Lumina Layers — 10 月更新速览", en: "Lumina Layers — October updates" },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "常用转换设置可以保存为命名预设，下次一键套用；高级设置、外轮廓和透明镀层可自行选择是否一起保存，未选的部分不会被预设覆盖。",
            en: "Save your usual conversion settings as named presets and apply them next time. Choose whether to include advanced settings, outlines and transparent coating; anything left out keeps its current settings.",
          },
          {
            zh: "尺寸预设按图片长边保存，横图和竖图都能沿用同一尺寸；重新打开软件后，也会恢复上次保存的颜色来源、耗材、尺寸和单面／双面等转换设置。",
            en: "Size presets follow the image’s long edge, so the same size works for landscape and portrait images. Reopening the app also restores saved conversion choices such as the color source, materials, size and single- or double-sided printing.",
          },
          {
            zh: "桌面版可在设置中调整并保存界面缩放，切换显示器时会适配屏幕大小；macOS 新增系统菜单，可使用常见的文件、编辑和窗口操作。",
            en: "The desktop app lets you adjust and save interface scale in Settings, adapting to the screen size when you switch displays. macOS also gains a native menu for familiar file, editing and window actions.",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "核心设置按导入、颜色设置、尺寸和底板、单面／双面打印、建模模式重新分组；耗材、层高、层数和底板耗材集中排列，常用参数更容易找到。",
            en: "Core settings are grouped into import, color, size and backing, single- or double-sided printing, and modeling mode. Material, layer height, layer count and backing material controls now sit together for easier access.",
          },
          {
            zh: "没有保存过偏好时，颜色来源默认选择“耗材档案”；已有选择会继续保留。“传统 LUT”统一称为“经典 LUT”（实拍色卡的颜色对照表），新手导览也按耗材档案、经典 LUT 的顺序介绍。",
            en: "Material Archive is now the default color source when no preference has been saved; existing choices are retained. Traditional LUT is renamed Classic LUT (the color lookup table from photographed charts), and the beginner tour covers Material Archive first, then Classic LUT.",
          },
          {
            zh: "经典 LUT 改用可搜索的选择窗口，可以跨品牌挑选，并在确认后统一应用；刷新入口也收进窗口，主面板只显示选择摘要。",
            en: "Classic LUT selection now has a searchable dialog where you can choose across brands and apply your selection together. Refresh is inside the dialog, while the main panel shows a compact summary.",
          },
          {
            zh: "裁切和旋转操作集中到同一个窗口，可向左或向右旋转 90°；SVG（矢量图）在这里可调整方向，保留原始矢量内容。",
            en: "Cropping and rotation now share one dialog, with 90° turns to the left or right. SVG vector images can be reoriented here while retaining their original vector content.",
          },
          {
            zh: "输出区精简为下载 3MF（多色打印文件）或打开切片软件，省去单独的生成入口；预览满意后选择所需操作，软件会自动生成文件。",
            en: "The output area is simplified to downloading a 3MF multicolor print file or opening it in your slicer, without a separate Generate control. Once the preview looks right, choose either action and the app generates the file as needed.",
          },
          {
            zh: "本次隐藏了掐丝珐琅设置入口，已有设置数据仍保留。",
            en: "The cloisonné settings entry is hidden in this update; existing settings data is retained.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "本地与云端的耗材库、LUT 库统一了浏览布局：列表展示摘要，选中条目后查看详细信息，便于查找和比较；云端条目可直接安装或更新。",
            en: "Local and cloud material and LUT libraries now share a browsing layout: the list shows summaries, and selecting an item reveals its details for easier browsing and comparison. Cloud items can be installed or updated directly.",
          },
          {
            zh: "云端耗材库的“本地历史版本”改为独立窗口，按本地安装时间列出可恢复的版本，选中后即可恢复；也可从单个耗材详情查看它的历史。",
            en: "Local Version History in the cloud material library now opens in its own dialog. Browse restorable versions by local installation time and restore the one you select, or open the history for a single material from its details.",
          },
          {
            zh: "LUT 分析页重新整理了信息和颜色分布图，查看色彩范围与详细数据更方便。",
            en: "The LUT analysis page reorganizes its information and color distribution charts, making the color range and detailed data easier to inspect.",
          },
          {
            zh: "梯度色卡页面分开说明黑白底卡的打印要求和配置包的保存步骤；桌面版可在浏览器中打开在线模型，使用前请确认模型层高与配置包一致。",
            en: "The gradient-card page now separates the black/white card printing instructions from the steps for saving the configuration package. The desktop app opens online models in your browser; check that the model and configuration package use the same layer height.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "设置页简化了分组和留白，左侧分类在滚动时保持可见，宽屏内容居中显示；通用设置可选择语言，模板下拉菜单中可直接导入切片模板。",
            en: "Settings has simpler grouping and spacing, with the left-hand categories staying visible while you scroll and centered content on wide screens. Choose the language in General and import slicer templates directly from the template dropdown.",
          },
          {
            zh: "桌面标题栏与主导航合并，统一了按钮、开关、关闭控件、字体和滚动条样式；颜色调整工作区也沿用相同的界面风格。",
            en: "The desktop title bar and main navigation are combined. Buttons, switches, close controls, typography and scrollbars now use a consistent style, including in the color-adjustment workspace.",
          },
          {
            zh: "深浅色切换、新手导览、问题反馈和连接状态集中在右上角菜单中，连接异常时会有红点提醒。",
            en: "Theme switching, the beginner tour, bug reports and connection status are grouped in the top-right menu, with a red dot to alert you to connection problems.",
          },
          {
            zh: "统一了二维、三维预览和裁切窗口的滚轮缩放与触控板操作，并改善页面切换、侧栏和弹窗滚动时的体验。",
            en: "Mouse-wheel zoom and trackpad controls are more consistent across 2D and 3D previews and the crop dialog, with smoother page transitions and more reliable scrolling in sidebars and dialogs.",
          },
          {
            zh: "调整了三维预览的打印平台标识与取景中心，平台顶面、侧面和底面的显示更清晰。",
            en: "The 3D preview has updated build-plate markings and framing, with a clearer distinction between the plate’s top, sides and underside.",
          },
          {
            zh: "按钮处理任务时会保持原有大小，并在中央显示等待指示；云端库的成功提示停留约 5 秒后平滑收起，错误提示会保留，方便查看和处理。",
            en: "Busy buttons keep their size and show a centered loading indicator. Success messages in cloud libraries fade and collapse after about five seconds, while errors stay visible so you can act on them.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "补齐 JFIF 图片在文件选择和预览中的支持；五色配方画布中的文字也会跟随软件语言切换。",
            en: "JFIF images are now supported throughout file selection and preview, and text on the five-color recipe canvas follows the app’s language setting.",
          },
          {
            zh: "减少云端耗材同步时对其他操作的阻塞，安装或更新耗材期间软件更容易保持响应。",
            en: "Cloud material sync is less likely to hold up other operations, helping the app stay responsive while materials are installed or updated.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-10-21",
    title: {
      zh: "Lumina Layers — 10 月更新速览",
      en: "Lumina Layers — October updates",
    },
    sections: [{
      category: { zh: "校准 & 材料", en: "Calibration & Materials" },
      items: [{
        zh: "修正了高层数耗材配色计算遗漏大量配方的问题；之前计算过的旧数据会在下次使用时自动重新计算，原有项目和耗材档案不受影响。",
        en: "Fixed missing recipe choices in higher-layer material colour calculations. Older calculated data is rebuilt automatically when next needed, without changing your projects or material profiles.",
      }],
    }],
  },
  {
    version: "2026-10-15",
    title: {
      zh: "Lumina Layers — 10 月更新速览",
      en: "Lumina Layers — October updates",
    },
    sections: [{
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "生成打印文件前，会检查耗材预设和打印板是否兼容。遇到多个匹配预设或打印板不兼容时，可直接选择耗材、切换打印板并继续生成；分享卡也会保存耗材选择。",
        en: "Filament presets and build plates are checked before generating print files. If several presets match or the plate is incompatible, choose a filament or switch plates and continue. Share cards also retain your filament choices.",
      }, {
        zh: "首次启动时会等待本机服务准备好，再自动进入工作区，无需手动刷新。耗材预设之间的共同设置冲突也会在生成前明确提示。",
        en: "The first start now waits for the local service before opening the workspace automatically, without a manual refresh. Conflicting shared filament settings are also explained before generation.",
      }, {
        zh: "保存 JSON 项目或 PNG 分享卡时，会带上局部换色、区域配方和选区。重新导入后可以继续编辑；旧文件没有保存的区域信息仍会明确提示。",
        en: "JSON projects and PNG share cards now retain local color edits, regional recipes and selections for continued editing after import. Older files still explain when region data was not saved.",
      }, {
        zh: "启用涂层后，需要明确选择使用哪种耗材，可沿用当前配色耗材或另选耗材档案；混用不同材料类型时会提示，生成前也会检查原生预设和打印板。",
        en: "Coating now requires an explicit material choice from the current palette or a separate material archive. Mixed material types are explained, and native presets and plates are checked before generation.",
      }, {
        zh: "单面模型的分离底板可选择独立工程输出，下载的压缩包保留模型和底板原尺寸，并分别安排打印位置。自动摆放未找到安全位置时，仍会生成文件并持续提示手动检查；请分别打开每个工程，确认切片通过后再打印。",
        en: "Single-sided models can export a separated backing as its own project. The ZIP keeps the original model and backing sizes and lays out each independently. If automatic placement cannot verify a safe layout, the files remain available with a manual-check warning. Open each project and confirm slicing succeeds before printing.",
      }],
    }],
  },
  {
    version: "2026-10-12",
    title: {
      zh: "Lumina Layers — 10 月更新速览",
      en: "Lumina Layers — October updates",
    },
    sections: [{
      category: { zh: "预览 & 交互", en: "Preview & Interaction" },
      items: [{
        zh: "优化颜色调整中的选区描边，选中数千个区域后，二维预览的缩放和拖拽更流畅，保留黑白虚线和选区闪烁。",
        en: "Zooming and panning the 2D preview is smoother with thousands of regions selected in color adjustment, while keeping the black-and-white dashed outlines and selection blink.",
      }],
    }],
  },
  {
    version: "2026-10-10",
    title: {
      zh: "Lumina Layers — 10 月更新速览",
      en: "Lumina Layers — October updates",
    },
    sections: [{
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "提交问题反馈时，现在会附上完整错误记录、原图、SVG、模型等源文件和相关设置，方便直接复现问题。",
        en: "Bug reports now include complete error records, original images, SVG and model source files, and related settings so the problem can be reproduced directly.",
      }],
    }],
  },
  {
    version: "2026-10-08",
    title: {
      zh: "Lumina Layers — 10 月更新速览",
      en: "Lumina Layers — October updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "「高级功能」现更名为「创意中心」，「模型覆面」现更名为「模型贴图」。模型贴图现位于独立面板，默认显示；即使隐藏面板，也能拖放导入模型和图片。",
            en: "The Advanced tab is now called the Creative Center, and Model Surface Overlay is now Model Texture. Model Texture now has its own panel, shown by default; models and images can still be dragged in when the panel is hidden.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-10-07",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "新功能", en: "New" },
      items: [{
        zh: "现在可选择 Prusa 机型，并导出供 PrusaSlicer 3.0.0-alpha12 打开的单件、批量及拼图工程；多色模型需要 MMU 或足够的打印头，材料数量超过设备容量会明确提示。",
        en: "Select a Prusa printer and export single, batch or puzzle projects for PrusaSlicer 3.0.0-alpha12. Multicolor models require an MMU or enough print heads; exports report when the palette exceeds the printer's capacity.",
      }, {
        zh: "设置中可以导入、选择和删除切片软件保存的单盘 3MF 项目模板。图像、矢量、材料档案、大幅分块和模型覆面导出可沿用模板工艺；批量、拼图、校准和色块生成仍使用内置配置。",
        en: "Settings now lets you import, select and delete single-plate 3MF project templates. Image, vector, material-archive, large-format and model-surface exports can reuse template tuning; batch, puzzle, calibration and swatch generation use built-in settings.",
      }],
    }, {
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "补齐 Prusa 机型的官方缩略图，设置中的设备卡片现在会显示对应打印机图片。",
        en: "Prusa device cards in Settings now show the matching official printer thumbnails.",
      }, {
        zh: "生成的 3MF 更新了对 Anycubic Slicer Next 2.0.0.3、Flash Studio 1.7.18 和 Snapmaker Orca 2.4.0 的配置适配；同时修复首层高度设置冲突导致导出失败的问题。",
        en: "Updated 3MF settings for Anycubic Slicer Next 2.0.0.3, Flash Studio 1.7.18 and Snapmaker Orca 2.4.0, and fixed export failures caused by conflicting first-layer height defaults.",
      }],
    }],
  },
  {
    version: "2026-10-06",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "移除 Docker 部署和自动更新支持，请使用桌面客户端或本地安装；用于公网测试的访问放行开关也已移除。",
        en: "Docker deployment and automatic updates have been removed. Use the desktop app or a local installation; the access bypass for public testing has also been removed.",
      }],
    }],
  },
  {
    version: "2026-10-04",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "创意工坊从 GitHub 安装模块时，现在能识别仓库更名或转移后的地址，修复了官方拼豆工作台因仓库转移而无法安装的问题。",
        en: "Creative Workshop now recognizes renamed or transferred GitHub repositories when installing modules, fixing installation of the official Fuse Bead Studio after its repository moved.",
      }],
    }],
  },
  {
    version: "2026-10-03",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "平面拼图可以使用所选的底板填充率和底板层高设置，观赏面附近仍保持实心；合并拼图时也会保留各块的材料槽、温度和流量设置。",
        en: "Flat puzzles now keep your backing infill and layer height choices while staying solid near the viewing surface. Combining pieces also preserves their material slots, temperatures, and flow settings.",
      }, {
        zh: "浮雕、掐丝或磁铁孔槽生成失败时会提示错误，不再把缺少这些结构的平面模型当作成功结果；之前已生成的下载文件仍可使用。",
        en: "Generation now reports failures when building relief, wirework or magnet cavities, instead of returning a flat model with those features missing. Previously generated downloads remain available.",
      }, {
        zh: "修改分享配方中的合法参数后可以直接导入，旧分享卡仍可打开；新分享卡需要使用更新后的 Lumina 打开。同名 LUT 无法明确匹配时会提示重新选择。",
        en: "Recipes can now be imported after editing valid settings, and older share cards still open. New cards require an updated Lumina. Ambiguous LUT names prompt you to choose a source again.",
      }, {
        zh: "更换耗材或重新拟合后，计算结果会按实际材料参数重新匹配。旧缓存文件会保留，但首次使用可能需要重新计算。",
        en: "After changing or refitting materials, cached results are matched against the actual material settings. Older cache files are kept, though the first use may require a rebuild.",
      }],
    }],
  },
  {
    version: "2026-10-01",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "预览 & 交互", en: "Preview & Interaction" },
      items: [{
        zh: "模型覆面选好平面后，视图会从正面显示，图案方向与旁边的二维预览一致；切换页面再回来，也会保留已经调整好的模型角度。",
        en: "After choosing a model surface, the view now faces it directly with the artwork oriented like the 2D preview. Your model angle is also kept when you leave the page and return.",
      }],
    }, {
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "修复部分带有细小孔洞的复杂图案在模型覆面生成时提示开槽失败的问题。",
        en: "Fixed pocket-cutting errors when generating some complex surface artwork with tiny holes.",
      }, {
        zh: "模型覆面使用材料档案生成时，底模会使用所选的底色材料，与图案共用对应材料槽，不再额外添加默认 PLA。",
        en: "When generating a model surface from material archives, the base now uses your selected backing material and shares its slot with the artwork, without adding a default PLA material.",
      }],
    }],
  },
  {
    version: "2026-09-30",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "校准 & 材料", en: "Calibration & Materials" },
      items: [{
        zh: "云端耗材库改成按页浏览，不用再一次次点“加载更多”；可以直接跳到任意一页。",
        en: "The cloud material library now has page-by-page browsing instead of repeated “Load more” clicks, and you can jump straight to any page.",
      }, {
        zh: "云端耗材卡片会显示发布频道（官方、社区等）和拟合误差（色差越小越准），并按优秀、良好、偏高分级。",
        en: "Cloud material cards now show where each material was published (official, community, and so on) and its fit error, graded as excellent, good, or high.",
      }, {
        zh: "按“可更新”“已安装”筛选时的数量更准确；耗材更新后保留的旧版本收进了可折叠的“本地版本记录”，需要时再展开回滚。",
        en: "The “Updates” and “Installed” filters now show accurate counts, and older versions kept after an update live in a collapsible “Local revision history” you can open when you need to roll back.",
      }],
    }, {
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "问题反馈现在点一次“发送”就会上传到官方问题收集服务，不用再配置邮箱，也不用再确认转发；对话框会显示上传进度，失败时可以一键重试。",
        en: "Bug reports now go straight to the official collection service with one click on Send. No mail setup or extra forwarding step is needed; the dialog shows upload progress and offers a one-click retry if it fails.",
      }, {
        zh: "反馈会带上和以前邮件一样完整的诊断资料，包括转换原图、生成的 3MF、所用 LUT 和材料档案（单个文件最大 40 MiB），开发者更容易复现问题。",
        en: "Reports carry the same full diagnostics as before, including the source image, generated 3MF, LUT, and material archive in use (up to 40 MiB per file), so problems are easier to reproduce.",
      }],
    }],
  },
  {
    version: "2026-09-28",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "新功能", en: "New" },
      items: [{
        zh: "大画幅模式下，3D 预览会用橙色线画出作品会被切成哪几块，并在每块上标出编号（如 R1C2 表示第 1 行第 2 列），编号与压缩包里的 3MF 文件名一致。不想看时可以在大画幅设置里关掉。",
        en: "In large format mode, the 3D preview now draws orange lines showing how your artwork will be split, and labels each piece (for example R1C2 means row 1, column 2) to match the 3MF file names in the ZIP. You can hide the lines in the large format settings.",
      }, {
        zh: "新增新手引导：第一次打开软件时会询问是否开始，用约 1 分钟走一遍从图片到 3MF（多色打印文件）的基本流程，讲清三种颜色来源的区别，并教你用鼠标旋转、平移、缩放 3D 预览。随时可以一键跳过，也可以点右上角的书本图标重新查看。",
        en: "Added a beginner tour. On first launch it offers a one-minute walk-through from picture to 3MF (the multi-color print file), explains the three color sources, and shows how to rotate, pan and zoom the 3D preview with the mouse. Skip it with one click, or replay it any time from the book icon at the top right.",
      }],
    }, {
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "修复部分复杂 SVG 能正常预览，却在生成 3MF 时报错的问题。",
        en: "Fixed 3MF generation errors for some complex SVG files that previewed successfully.",
      }],
    }],
  },
  {
    version: "2026-09-26",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "新功能", en: "New" },
      items: [{
        zh: "检测到切片软件时，下拉菜单里的“下载 3MF”变为“生成并下载 3MF”：还没生成过也能直接点，会先生成再下载。",
        en: "When a slicer is detected, the dropdown's “Download 3MF” is now “Generate & Download 3MF”: it works even before you generate, creating the file first and then downloading it.",
      }, {
        zh: "桌面版设置里可以选择生成文件的默认保存位置，保存对话框会默认打开这个文件夹，仍可临时改选其他位置。",
        en: "In the desktop app you can now pick a default save folder in Settings. Save dialogs open there by default, and you can still choose another place each time.",
      }],
    }, {
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "修复换色、撤销后点击生成偶尔提示“画面内容已变化，请刷新后重试”而无法生成的问题，现在会自动同步后继续生成。",
        en: "Fixed an occasional “content changed, please refresh” error when generating after replacing colors or undoing. Generation now syncs automatically and continues.",
      }, {
        zh: "拼图模式生成 3MF 时会同时处理多块拼图，减少块数较多时的等待时间。",
        en: "Puzzle 3MF generation now processes several pieces at once, reducing waits for larger puzzles.",
      }, {
        zh: "批量转换现在可以同时处理多张图片，结果和排盘仍按上传顺序排列。",
        en: "Batch conversion now processes several images at once while keeping results and plate placement in upload order.",
      }, {
        zh: "修复单色拼图块导入切片软件后误用第一种耗材的问题，白色拼图块不再因此变成蓝色。",
        en: "Fixed single-color puzzle pieces using the first filament when opened in a slicer, which could turn white pieces blue.",
      }],
    }],
  },
  {
    version: "2026-09-24",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [{
      category: { zh: "稳定性", en: "Stability" },
      items: [{
        zh: "修复 16 位高度图上传后出现杂纹、浮雕高度错乱的问题，原图的明暗和高低顺序保持一致。",
        en: "Fixed noise and incorrect relief heights when uploading 16-bit heightmaps, preserving the image's brightness and height order.",
      }, {
        zh: "颜色状态文字被浏览器工具改写后，点击“全不选”不再因此白屏，可以继续选色。",
        en: "Clearing the color selection no longer blanks the page after browser tools replace the selection status text. You can keep editing colors.",
      }],
    }],
  },
  {
    version: "2026-09-23",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [{
          zh: "修复了部分 Windows 电脑打开软件后一直白屏的问题，无需更改系统设置或删除原有资料。",
          en: "Fixed a startup white screen on some Windows PCs, without changing system settings or deleting existing data.",
        }],
      },
    ],
  },
  {
    version: "2026-09-14",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [{
          zh: "使用像素画模式转换透明图片时，合并预览和导出的 3MF 现在都会保留透明区域，不再自动补上一整块矩形底板。",
          en: "Pixel Art mode now preserves transparent areas in both the combined preview and exported 3MF, instead of adding a full rectangular backing.",
        }],
      },
    ],
  },
  {
    version: "2026-09-13",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "新增 SVG 小洞补偿，默认关闭。可按成品尺寸填补画面中的小孔和封闭细缝并沿用邻近颜色，预览和生成保持一致；原文件不变，补偿设置可随项目保存。",
            en: "Added SVG hole compensation, off by default. Fill small holes and enclosed thin gaps at the finished size using nearby colours, with matching preview and generation. Your original file stays unchanged, and the settings are saved with the project.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [{
          zh: "批量生成多个 SVG 或图片时，透明镀层现在会按所选厚度添加到每个模型中。",
          en: "When generating multiple SVGs or images together, transparent coating is now added to each model at the selected thickness.",
        }, {
          zh: "修复透明镀层与描边同时开启时出现白色碎点的问题，镀层完整覆盖描边范围。",
          en: "Fixed white specks when coating and outline are enabled together; coating covers the full outline footprint.",
        }],
      },
    ],
  },
  {
    version: "2026-09-03",
    title: {
      zh: "Lumina Layers — 9 月更新速览",
      en: "Lumina Layers — September updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "设置里新增“擦料塔自动摆放”开关，默认开启；关闭后，生成的 3MF 会保留切片软件模板里的擦料塔参数，方便你手动安排位置和尺寸。",
            en: "Settings now include an Automatic wipe-tower placement switch, enabled by default. Turn it off to keep the slicer template's tower position and size for manual layout.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "修复“擦料塔自动摆放”开启后仍沿用模板位置和尺寸的问题；现在普通尺寸作品也会按当前打印机自动调整模型与擦料塔布局。",
            en: "Fixed Automatic wipe-tower placement sometimes keeping the template position and size. Regular-sized projects now get a layout planned for the selected printer too.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-08-31",
    title: {
      zh: "Lumina Layers — 8 月更新速览",
      en: "Lumina Layers — August updates",
    },
    sections: [
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "8 月 31 日：常见的纯色 SVG 现在能更快完成颜色区域分析；遇到复杂描边、透明或特效时会自动沿用兼容处理，成品结构和材料顺序保持不变。",
            en: "August 31: Common flat-colour SVG files now complete colour-region analysis faster. Artwork with complex strokes, transparency, or effects automatically uses the compatibility path, preserving the finished structure and material order.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-08-30",
    title: {
      zh: "Lumina Layers — 8 月更新速览",
      en: "Lumina Layers — August updates",
    },
    sections: [
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "SVG 矢量作品现在默认使用平滑 SVG 轻量预览；修改尺寸和常用创意效果时，画面会直接跟着更新。需要兼容旧显示方式时，可在设置里关闭这个选项。",
            en: "SVG artwork now uses a smooth lightweight SVG preview by default, with size and common creative changes reflected directly in the viewer. You can switch back to the previous display style in Settings when needed.",
          },
          {
            zh: "点击生成后，画面会继续使用轻量预览，不会先加载体积很大的打印模型；下载的 3MF 仍按当前设置精确生成。",
            en: "After you select Generate, the viewer keeps using the lightweight model instead of loading the much larger print model, while the downloaded 3MF is still generated precisely from your current settings.",
          },
          {
            zh: "模型覆面现在会显示改色后的实际画面，不再退回原始颜色；SVG 轮廓也会保持平滑。",
            en: "The model-surface preview now shows the genuinely recoloured artwork instead of reverting to its original colours, while SVG edges stay smooth.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-08-23",
    title: {
      zh: "Lumina Layers — 8 月更新速览",
      en: "Lumina Layers — August updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "8 月 23 日：新增 QIDI Studio 支持，可直接为 Q2、Q2C、X-Max 4 和 X-Plus 5 生成适配的多色 3MF。喷嘴选项按软件内的机型清单提供且最大为 0.4 毫米；导出文件保留 Lumina 工艺参数。",
            en: "August 23: Added QIDI Studio support for multicolour 3MF exports targeting the Q2, Q2C, X-Max 4, and X-Plus 5. Nozzle choices follow QIDI Studio's machine list and are capped at 0.4 mm, while Lumina process settings remain intact.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-08-14",
    title: {
      zh: "Lumina Layers — 8 月更新",
      en: "Lumina Layers — August Update",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "现在可以把原图、输出参数、全图改色和自定义配方历史一起保存为 Lumina 项目文件，之后恢复项目继续比较不同设置或耗材；局部区域改色仍会明确提示仅保留在当前会话。",
            en: "You can now save the source artwork, output settings, whole-image colour changes, and custom recipe history as a Lumina project, then restore it to compare other settings or filaments. Spatial colour edits still show a clear current-session-only notice.",
          },
          {
            zh: "设置里现在可以直接选择切片软件原生打印板；Lumina 会按切片软件与打印机型号分别记忆，并把选择写进生成的 3MF。",
            en: "You can now choose a slicer's native build plate in Settings. Lumina remembers it for each slicer and printer model, then writes the choice into generated 3MF files.",
          },
          {
            zh: "底板厚度现在最高可设为 10 mm，并可单独调节深层底板填充率；靠近观赏面的区域仍会自动保持实心。",
            en: "Backing thickness can now be set up to 10 mm, with a separate infill control for deeper backing while the viewing-surface zone automatically stays solid.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-08-13",
    title: {
      zh: "Lumina Layers — 8 月更新",
      en: "Lumina Layers — August Update",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "设置里新增“导出 3MF 时沿用上传文件名”开关，默认关闭；开启后，普通单件作品会把“海报.png”下载为“海报.3mf”，批量、拼图和大画幅仍使用原有名称。",
            en: "Settings now include an optional “Use uploaded filename for 3MF exports” switch. It is off by default; when enabled, a normal single-item “poster.png” downloads as “poster.3mf”, while batch, puzzle, and large-format exports keep their existing names.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-08-08",
    title: {
      zh: "Lumina Layers — 材料配方颜色一致性",
      en: "Lumina Layers — Consistent material recipe colours",
    },
    sections: [
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "相同的耗材叠层现在会在转换预览、自定义配方、可实现颜色推荐和材料库配方查询里显示一致的模拟颜色；动态 5–8 层模式也会按实际八层范围寻找配方。",
            en: "The same filament stack now shows one consistent simulated colour in conversion previews, custom recipes, achievable-colour suggestions, and Material Library recipe queries. Dynamic 5–8 layer mode also searches the full printable eight-layer range.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-30",
    title: {
      zh: "Lumina Layers — 创意工坊与拼豆工作台",
      en: "Lumina Layers — Creative Workshop and Fuse Bead Studio",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "7 月 30 日：主导航“图像转矢量”右侧新增“创意工坊”。首个官方工具“拼豆工作台”随软件预装，也可单独启用、停用、卸载或从离线预装内容恢复；它能读取清晰拼豆图纸或截图，帮助校正网格和不确定色块，实时预览不同压合程度下豆间缝隙与四豆交汇凹点的变化，并把完成的图像交回 Lumina 原有的叠色打印流程。",
            en: "July 30: Creative Workshop now sits to the right of Vectorizer in the main navigation. Its first official tool, Fuse Bead Studio, is preinstalled and can be enabled, disabled, uninstalled, or restored offline. It reads a clear bead pattern or screenshot, helps correct the grid and uncertain colours, previews how bead gaps and four-bead junctions change with ironing pressure, and sends the finished image back to Lumina’s existing layered-colour printing flow.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-22",
    title: {
      zh: "Lumina Layers — 6 月下旬至 7 月更新速览",
      en: "Lumina Layers — Late June to July updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "7 月 22 日：Flash Studio Desktop 适配现按软件正式清单支持 Flashforge AD5X、Creator 5 / 5 Pro、Guider 3 Ultra、Guider4 / 4 Pro；喷嘴选项按机型提供且最大为 0.4 毫米，Guider 3 Ultra 支持 0.4 毫米，其余五台支持 0.25、0.4 毫米。导出的 3MF 使用 Flash Studio 实际的 2.3.2 项目格式，同时保留 Lumina 工艺参数。",
            en: "July 22: Flash Studio Desktop support now follows its official machine list for the Flashforge AD5X, Creator 5 / 5 Pro, Guider 3 Ultra, and Guider4 / 4 Pro. Nozzles are machine-specific and capped at 0.4 mm: Guider 3 Ultra supports 0.4 mm, while the other five models support 0.25 and 0.4 mm. Exported 3MF files use Flash Studio's observed 2.3.2 project format while retaining Lumina process settings.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-19",
    title: {
      zh: "Lumina Layers — 6 月下旬至 7 月更新速览",
      en: "Lumina Layers — Late June to July updates",
    },
    sections: [
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "7 月 19 日：耗材档案的 3D 预览现在会按配方叠色显示最终模拟颜色，同时保留真实层数和厚度；画面不会再被最上层耗材色遮住或异常偏亮，浮雕预览也能看出高度差。",
            en: "July 19: Material-profile 3D previews now show the final simulated recipe colours while keeping the real layer count and thickness. The top filament no longer hides the blended result or makes it look unusually bright, and relief height differences are visible again.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-18",
    title: {
      zh: "Lumina Layers — 6 月下旬至 7 月更新速览",
      en: "Lumina Layers — Late June to July updates",
    },
    sections: [
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "7 月 18 日：生成 3MF 时，底板层高现在会自动对齐实际底板厚度；双面作品、浮雕和不适合加速的厚度会安全跳过，避免顶部叠色少层或成品变薄。",
            en: "July 18: Base-layer heights now align with the actual backing thickness when generating a 3MF. Double-sided prints, reliefs, and thicknesses that cannot be sped up safely are skipped, preventing missing top colour layers or a thinner result.",
          },
          {
            zh: "7 月 18 日：大画幅作品只调整选中区域的颜色时，下载文件现在会和分层预览保持一致；画面中其他相同颜色的区域不会再一起变色。",
            en: "July 18: Large-format downloads now match the layer preview after recolouring a selected area, without changing other areas that happen to use the same colour.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-15",
    title: {
      zh: "Lumina Layers — 6 月下旬至 7 月更新速览",
      en: "Lumina Layers — Late June to July updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "7 月 15 日：SVG 在矢量模式下现在也能使用颜色深浅或高度图生成浮雕；生成时只调整背板高度，原有叠色层数、顺序和厚度保持不变。",
            en: "July 15: SVG artwork in Vector mode can now create reliefs from colour depth or a heightmap; generation changes only the backing height while keeping the existing colour-layer count, order, and thickness.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-12",
    title: {
      zh: "Lumina Layers — 6 月下旬至 7 月更新速览",
      en: "Lumina Layers — Late June to July updates",
    },
    sections: [
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "7 月 12 日：耗材库里的无境新材已更名为 Karvax；之前选过这家耗材的配方和底板耗材会自动继续对应到新名称。",
            en: "July 12: Wujing materials in the library are now called Karvax, and previously saved material and backing selections will automatically carry over to the new name.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-07-09",
    title: {
      zh: "Lumina Layers — 6 月下旬至 7 月更新速览",
      en: "Lumina Layers — Late June to July updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "6 月 30 日：云端 LUT 库上线，可以直接从云端浏览、安装和刷新 LUT；传统 LUT 也支持同组多选，做颜色匹配时不用再手动合并成一个文件。",
            en: "June 30: The cloud LUT library is now available for browsing, installing, and refreshing LUTs, and traditional LUTs can be selected together in compatible groups without first merging them into one file.",
          },
          {
            zh: "6 月 30 日：LUT 详情、云端安装状态和官方/社区角标做了统一，装过的云端 LUT 更容易看出来源和当前状态。",
            en: "June 30: LUT details, cloud install state, and official/community badges are now aligned, so installed cloud LUTs are easier to identify and trust.",
          },
          {
            zh: "7 月 9 日：云端耗材库和云端 LUT 库的连接说明补齐了，团队测试时能更快确认当前线上数量、连接地址和维护流程。",
            en: "July 9: The cloud material and LUT connection guide is now complete, making it easier for the team to check current totals, connection settings, and maintenance steps.",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "6 月 27 日：刷新预览后，已经做过的区域改色会继续带到新的预览和生成里，不会突然回到旧颜色。",
            en: "June 27: Region recolours now carry through preview refreshes and final generation instead of unexpectedly falling back to the old colours.",
          },
          {
            zh: "6 月 27 日：全选区域后再套用自定义配方时，生成的 3MF 会继续使用选中的区域，不会出现部分区域没有被替换的问题。",
            en: "June 27: When applying a custom recipe after selecting all regions, the exported 3MF now keeps the intended regions instead of leaving part of the artwork unchanged.",
          },
          {
            zh: "7 月 8 日：更换耗材渐变或目标材料后，旧的替换选择会被清掉，避免确认窗口里混入上一轮残留颜色。",
            en: "July 8: Changing a material gradient or target material now clears stale replacement choices, so the confirmation step no longer mixes in colours from the previous attempt.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "6 月 27 日：传统 LUT 处理灰色和黑色时更稳，灰色作品不容易被匹配成偏脏或偏彩的结果。",
            en: "June 27: Legacy LUT matching is steadier for grey and black inputs, reducing muddy or overly colourful results on grey artwork.",
          },
          {
            zh: "6 月 30 日：老 NPY LUT 的 CMYW、蓝色通道和多色槽位识别更准确，旧 LUT 参与多选时更不容易选错颜色顺序。",
            en: "June 30: Older NPY LUT files now recognise CMYW, blue-channel, and multi-colour slots more accurately, so multi-select is less likely to use the wrong colour order.",
          },
          {
            zh: "7 月 7 日：云端 LUT 安装后会刷新详情和列表；提交问题反馈时，多选 LUT 里缺失的项目也会被逐项写清楚，方便复现。",
            en: "July 7: Cloud LUT installs now refresh the details and list, and bug reports describe each selected LUT separately, including any missing item, so issues are easier to reproduce.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "6 月 27 日：SVG 矢量预览和建模速度提升，复杂图形等待时间更短。",
            en: "June 27: SVG vector previews and model preparation are faster for complex artwork.",
          },
          {
            zh: "6 月 27 日：高度图浮雕现在能正常显示 3D 几何，不会只看到空白或缺少浮雕形状。",
            en: "June 27: Heightmap relief previews now show the actual 3D geometry instead of appearing blank or missing the relief shape.",
          },
          {
            zh: "6 月 29 日：复杂预览的容量保护改为按需开启，默认情况下不会再因为过于保守的保护规则提前拦住可处理的作品。",
            en: "June 29: Preview size protection is now opt-in, so Lumina no longer blocks artwork too early because of overly cautious default limits.",
          },
          {
            zh: "7 月 7 日：像素模式会保留原画布尺寸，3D 预览和底板大小不再因为像素图尺寸信息丢失而偏小或偏大。",
            en: "July 7: Pixel mode now preserves the source canvas size, keeping the 3D preview and backing from shrinking or growing because size details were lost.",
          },
          {
            zh: "7 月 8 日：耗材档案预览会保留像素调色板，像素风作品不再因为预览材料信息变化而冒出细碎杂色。",
            en: "July 8: Material-profile previews now preserve pixel palettes, reducing tiny speckles when preview material details change.",
          },
          {
            zh: "7 月 8 日：大画幅 SVG 的预览大小估算更贴近实际，能处理的大图不会再被误判成超出限制。",
            en: "July 8: Large-format SVG size checks now better match real preview cost, so processable large artwork is not rejected as oversized.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "6 月 27 日：半透明 5 色 SVG 的叠色更可靠，透明或半透明区域不容易在生成时盖错层。",
            en: "June 27: Translucent 5-colour SVG stacking is more reliable, so transparent and semi-transparent areas are less likely to land on the wrong layer.",
          },
          {
            zh: "6 月 27 日：耗材档案导出 3MF 时会按实际需要整理耗材槽，不再多占空槽或把不该打印的槽写进去。",
            en: "June 27: Material-profile 3MF exports now keep only the filament slots they actually need, avoiding extra empty or unused slots.",
          },
          {
            zh: "6 月 28 日：H2C 等扩展材料模板导出矢量 3MF 时，会保留更长的材料配置，不容易再提示矢量内容过长。",
            en: "June 28: H2C and other extended material templates now keep their longer material setup in vector 3MF exports, reducing false 'too long' failures.",
          },
          {
            zh: "6 月 30 日：颜色非常接近的 SVG 填充会保持一致分组，预览和生成时不容易把同一种颜色拆成不同结果。",
            en: "June 30: Very similar SVG fill colours are grouped more consistently, so preview and generation are less likely to split one intended colour into different results.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "6 月 27 日：下载 3MF 后，来源会话会保留到下载真正完成，切换或关闭页面时更不容易丢最终文件。",
            en: "June 27: After a 3MF is generated, the finished file stays available long enough for the download, reducing lost files after switching or closing views.",
          },
          {
            zh: "6 月 27 日：问题反馈窗口点到背景时不会直接丢掉已经写好的内容，草稿更安全。",
            en: "June 27: Clicking outside the bug report window no longer discards the text you already typed, making drafts safer.",
          },
          {
            zh: "6 月 29 日：Snapmaker U1 和 OrcaSlicer 导出的 3MF 会保留更多机器与耗材信息，切片软件识别更稳定。",
            en: "June 29: Snapmaker U1 and OrcaSlicer 3MF exports now keep more machine and filament details, making slicer recognition more stable.",
          },
          {
            zh: "6 月 29 日：灰色作品会走更严格的来源保护，减少特殊输入导致颜色处理不一致的情况。",
            en: "June 29: Grey artwork now uses stricter safeguards, reducing cases where unusual inputs could lead to inconsistent colour handling.",
          },
          {
            zh: "6 月 30 日：配方、裁剪和冲突提示继续换成更容易理解的说法，尽量不再把内部路径或技术细节直接展示给用户。",
            en: "June 30: Recipe, crop, and conflict messages now use clearer wording and avoid exposing internal paths or technical details to users.",
          },
          {
            zh: "7 月 8 日：Snapmaker U1 的 OrcaSlicer 信息再次补齐，缺少部分机型信息时也会用可靠的默认值兜底。",
            en: "July 8: Snapmaker U1 exports for OrcaSlicer now fill in reliable defaults when some machine details are missing.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-06-23",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "设置里新增按切片软件、机型和喷嘴选择的机器卡片；导出的 3MF 会尽量保留 Bambu Studio、OrcaSlicer、ElegooSlicer、Anycubic Slicer Next 等软件认识的机器信息。",
            en: "Settings now include slicer, machine, and nozzle cards, so exported 3MF files can keep machine details recognised by Bambu Studio, OrcaSlicer, ElegooSlicer, Anycubic Slicer Next, and related slicers.",
          },
          {
            zh: "拼图模式补齐了预览和导出流程：现在可以在转换区查看拼图叠线，逐块生成后合并成一个 3MF，配方导入导出也会一起保留拼图设置。",
            en: "Puzzle mode now has a fuller preview and export flow: you can see the puzzle overlay in the converter, generate pieces into one 3MF, and keep puzzle settings when importing or exporting recipes.",
          },
          {
            zh: "3D 预览区域新增耗时统计，想排查一张图为什么慢时，可以直接看到预览和生成各花了多久。",
            en: "The 3D preview area now shows timing details, so it is easier to see where preview or 3MF generation time is being spent.",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "大耗材组合做颜色建议时，现在会优先复用已经准备好的候选结果；之前一些 10 层、十几种耗材的组合会直接提示组合太多，现在能继续给出建议。",
            en: "Colour suggestions for large material sets can now reuse prepared candidates first, so some 10-layer, many-material jobs that used to stop as 'too many combinations' can return suggestions instead.",
          },
          {
            zh: "单图模式下重新选图片时，现在明确分成「更换当前图片」和「添加更多图片」；想换图时不会再误变成批量追加。",
            en: "Single-image upload now separates 'replace current image' from 'add more images', so replacing an image no longer accidentally turns into a batch append.",
          },
          {
            zh: "透明图做渐变分组或区域高亮时，透明背景会继续保持透明，不会再被整片蓝色高亮铺满。",
            en: "When highlighting gradient groups or regions in transparent artwork, transparent areas now stay transparent instead of turning into a solid blue background.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "ColorChecker 校色弹窗关闭后不会再偶发自动弹回；如果「执行校色」暂时不可用，界面也会说明还缺哪一步。",
            en: "The ColorChecker calibration dialog no longer reopens right after you close it, and the Calibrate button now explains what is still missing when it cannot run yet.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "耗材选择弹窗和耗材库里的品牌分组默认收起，长列表打开时更清爽；选择弹窗里也新增了「清空选择」。",
            en: "Brand groups in the material picker and material library now start collapsed for long lists, and the picker includes a new clear-selection action.",
          },
          {
            zh: "新增 8 个 KYNIX PETG 耗材档案，可以直接在材料库里选择中国红、白色、黑色等常用颜色。",
            en: "Added eight KYNIX PETG material profiles, including common colours such as Chinese Red, white, and black, ready to select from the material library.",
          },
          {
            zh: "5 色扩展校准板的两张页面现在使用一致的物理外框，自定义色块尺寸后不会再一张大一张小。",
            en: "Both pages of the 5-Color Extended calibration board now use the same physical frame, so custom patch sizes no longer make one page visibly smaller than the other.",
          },
          {
            zh: "5 色扩展配方会保留第 6 层黑色，不会在查询、匹配或生成配方色块时被截掉。",
            en: "5-Color Extended recipes now keep the sixth black layer during lookup, matching, and recipe swatch generation instead of trimming it away.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "高级设置里新增 3D 高精度颜色预览；开启后，低占比颜色更不容易在 3D 预览里被合并掉。",
            en: "Advanced settings now include high-precision 3D colour preview, which helps small colour regions stay visible instead of being merged away in the 3D view.",
          },
          {
            zh: "像素模式的高颜色数预览会保留更多色块和边界，3D 预览看起来会更接近原来的像素图。",
            en: "Pixel-mode previews with high colour counts now keep more colour blocks and boundaries, making the 3D preview closer to the source pixel artwork.",
          },
          {
            zh: "只有 viewBox、没有写死宽高的 SVG 上传后也会正常显示预览，不会再出现 0 尺寸空白框。",
            en: "SVG files that rely on viewBox sizing now show a proper upload preview instead of collapsing into an empty 0-size frame.",
          },
          {
            zh: "高度图浮雕在刷新预览后会自动把高度图带到新的生成流程里，不会因为预览刷新而丢失高度图。",
            en: "Heightmap relief generation now carries the selected heightmap through preview refreshes, so final generation no longer loses it after a new preview is made.",
          },
          {
            zh: "耗材档案浮雕超过 5 层时，现在会按实际层数生成分层预览和 3MF，不会只保留前 5 层。",
            en: "Material-archive relief above five layers now uses the actual layer count for layer previews and 3MF output instead of keeping only the first five layers.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式的外轮廓在预览和导出的 3MF 里都会跟主体对齐，不会再出现边框错位或看起来没有包住边缘的问题。",
            en: "SVG vector outlines now line up with the artwork in both preview and exported 3MF files, instead of appearing offset or missing around the edge.",
          },
          {
            zh: "SVG 矢量模式开启挂件环后，导出的 3MF 现在会真正带上挂件环，同时不会多占一个打印耗材槽。",
            en: "SVG vector exports now include the requested keychain loop in the 3MF without adding an extra filament slot.",
          },
          {
            zh: "大尺寸 SVG 搭配很多耗材和多层配方时，预览不会再过早误报太大；能实际处理的作品会继续正常预览。",
            en: "Large SVG previews with many selected materials and layers are no longer rejected too early as oversized when Lumina can actually process them.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "生成 3MF 已经成功时，即使可选的 3D 预览文件保存失败，也会优先保留最终下载链接，不会把可打印文件一起丢掉。",
            en: "When a 3MF has already been generated, Lumina now keeps the final download even if the optional 3D preview file cannot be saved.",
          },
          {
            zh: "批量、校准、耗材色块和分享卡等下载更稳了；预览附件失败时，软件会尽量保留已经生成好的最终文件。",
            en: "Downloads for batch jobs, calibration, material swatches, and share cards are more resilient, with finished files preserved when optional preview attachments fail.",
          },
          {
            zh: "很多报错提示改成了更容易看懂的中英文说明，不再把本机路径或内部细节直接显示给用户。",
            en: "Many error messages now use clearer Chinese and English text, and avoid showing local file paths or internal details to users.",
          },
          {
            zh: "提交 Bug 反馈时，会更完整地收集原图、生成文件、LUT、耗材档案和最近操作记录，方便后续复现问题。",
            en: "Bug reports now collect the original artwork, generated files, LUT, material profiles, and recent actions more reliably, making issues easier to reproduce later.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-06-02",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "当一张图里的颜色能匹配到多个同样接近的材料组合时，现在会稳定选择同一个结果；重复预览或生成不再出现细微飘动。",
            en: "When an artwork colour is equally close to multiple material mixes, Lumina now picks the same result every time, so repeated previews and 3MF exports no longer drift slightly.",
          },
          {
            zh: "在耗材档案里替换区域颜色时，如果作品层数比默认配方更多，新增层现在也会一起更新，不会留下旧颜色或导致生成失败。",
            en: "When replacing a region colour in the material archive workflow, extra layers beyond the default recipe are now updated too, instead of keeping old colours or failing during generation.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "提取器里只按行做手动修正时，现在也能正常继续处理，不会因为没有选中单个色块而中断。",
            en: "Manual fixes in the Extractor now keep working when you correct a whole row without selecting one individual patch.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 预览里做过区域改色或自定义配方后，即使生成时调整了 SVG 精细度，导出的 3MF 也会保留这些修改。",
            en: "SVG region recolours and custom recipes now carry into the exported 3MF even when you generate with a different SVG detail setting.",
          },
          {
            zh: "线稿类作品在缺少临时预览数据时也能继续提取线框，不会在生成中途停止。",
            en: "Line-art style generation can now continue extracting outlines even when temporary preview data is unavailable.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "很慢的预览或生成任务现在会在超时后自动回收，不会一直占住后台处理能力拖慢后续操作。",
            en: "Very slow preview or 3MF generation jobs are now cleaned up after timing out, so later actions are not left waiting behind them.",
          },
          {
            zh: "打开分层预览时，如果作品暂时没有可用的颜色信息，之前可能直接报错；现在会用灰色兜底继续显示，不会打断预览。",
            en: "Layer previews could fail when an artwork temporarily had no usable colour information. They now fall back to grey and keep the preview open.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-29",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式现在也能勾选「启用描边」了，设置的描边宽度会写进导出的 3MF；大画幅模式仍按既有规则不支持描边。",
            en: "SVG vector mode now lets you turn on outlines. The chosen outline width is written into exported 3MF files; large-format generation still follows the existing no-outline rule.",
          },
          {
            zh: "单面 SVG 生成后的 3D 预览现在会朝向正面，不再先看到白色底板；导出的 3MF 仍保持原来的打印方向。",
            en: "After generating a single-sided SVG, the 3D preview now opens on the front artwork instead of the white backing, while exported 3MF files keep their print orientation.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "用 SVG 梯度图生成 3MF 时，文件封面缩略图现在会像位图一样显示原图外观，不会再变成分层颜色预览。",
            en: "For 3MF files generated from SVG gradients, the cover thumbnail now shows the original artwork like bitmap inputs do, instead of a material-layer colour preview.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-28",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "ColorChecker 色卡校色现在直接在提取器和梯度卡页面里完成，不再跳到独立工具，确认后会自动衔接到提取或梯度卡拟合。",
            en: "ColorChecker calibration now runs inside the Extractor and Gradient Card pages instead of opening a separate tool, and feeds straight into extraction or gradient-card fitting once you confirm it.",
          },
          {
            zh: "ColorChecker 校色支持导入自定义参考表（xlsx）：可以用自己量出来的色卡数据替换默认基准，列表会保存在浏览器里下次直接选用。",
            en: "ColorChecker calibration now imports custom reference tables (xlsx). Your own measured patches can replace the default reference, and the list is remembered locally for next time.",
          },
          {
            zh: "导出的分享卡 PNG 底部新增官网二维码和「可直接导入 Lumina 2.0 重新生成」字样，方便发给别人时对方能直接扫码入门或重做。",
            en: "Exported share-card PNGs now include a wiki QR code and a caption telling viewers they can import the image back into Lumina 2.0 to recreate the result.",
          },
          {
            zh: "新增「必趣 PLA」六种颜色（白、红、绿、蓝、黄、黑）的梯度卡材料档案，可以直接在材料库里选用。",
            en: "Added BIQU PLA gradient-card profiles for six colours (white, red, green, blue, yellow, black), available directly from the material library.",
          },
          {
            zh: "颜色工作站对 10 色 5 层以内的调色板改为精确穷举匹配，并且会让相近颜色之间保持原图的明暗顺序，过渡不会被打乱。",
            en: "The Color Workstation now does an exhaustive match for palettes up to 10 colours and 5 layers, and keeps neighbouring colours in their original light-to-dark order so gradients stay smooth.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式的第一次预览现在就能看到完整底板，不会出现「预览没底板、生成后才有」的情况。",
            en: "The first SVG vector preview now shows the full backing plate, so you no longer see \"no backing in preview, backing appears after generation.\"",
          },
          {
            zh: "在矢量化页面把 SVG 发到转换器时，不再弹出裁剪窗口，直接进入颜色匹配流程。",
            en: "Sending an SVG from the Vectoriser to the Converter no longer pops up the crop dialog; the artwork goes straight to colour matching.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "矢量生成完成后，3D 预览继续显示像素级的混色效果，不再切换成只有几个纯色块的版本。",
            en: "After vector generation, the 3D preview keeps the pixel-level colour-mixed view instead of switching to a flat per-material block view.",
          },
          {
            zh: "用 SVG 生成的 3MF 在 Windows 资源管理器和切片软件里的封面缩略图终于会显示真实图案，不再是一张白图。",
            en: "3MFs generated from SVGs now show the real artwork in the cover thumbnail used by Windows Explorer and slicer project lists, instead of a blank white image.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "用耗材档案做大画幅生成时偶尔报错的问题修好了；同时 bug 反馈里收集的最终产物会按真正的下载文件分类，不会再把大画幅 ZIP 误标。",
            en: "Fixed an occasional failure when running large-format generation under the material archive workflow. Bug-report attachments now classify the final artifact by the real download, so large-format ZIPs are no longer mislabeled.",
          },
          {
            zh: "macOS 上检测已安装的切片软件时，碰到某个应用包内信息文件损坏不会再让整次检测失败，会跳过坏的应用继续找其他切片软件。",
            en: "On macOS, scanning for installed slicers no longer aborts when one app bundle has a corrupted info file; the broken bundle is skipped and the rest of the scan continues.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-21",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 里由线条围出的白色留白不再在颜色识别时显示成黑色。",
            en: "White spaces enclosed by SVG linework no longer show up as black during colour matching.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "在耗材档案下用 SVG 图打开“自定义配方”加层后，新增的几层有时会被填成耗材列表里的第一种颜色，即使你列表里第一种不是白色。修好了：现在新增层会用真正的白色/底色耗材，导出的 3MF 跟分层预览一致。",
            en: "Under the material archive workflow with SVG inputs, adding extra layers in the Custom Recipe dialog could fill the new layers with the first material in your list instead of the white/backing one. This is now fixed — the exported 3MF matches the layer-by-layer preview.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-20",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "批量生成现在会把成功的模型打包成一个 3MF 下载，不用再解压后一件件导入切片软件。",
            en: "Batch generation now downloads successful models as one 3MF, so you no longer need to unzip and import each model into the slicer one by one.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "批量生成完成后，3D 预览会直接在热床上显示多个模型，并在数量太多时只预览能稳定显示的前几件。",
            en: "After batch generation, the 3D preview now shows multiple models on the bed and limits the preview to the first models that can be displayed smoothly when a batch is very large.",
          },
          {
            zh: "透明区域会用棋盘格显示，预览和分层图里更容易分清透明和黑色。",
            en: "Transparent areas now use a checkerboard background, making it easier to tell transparency from black in previews and layer images.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 里的透明背景不再被当成黑色实体，矢量模式打开透明图时不会整片发黑。",
            en: "Transparent SVG backgrounds are no longer treated as solid black, so vector previews no longer turn the whole artwork black.",
          },
          {
            zh: "SVG 渐变图不分离底板时，底板层高修改器现在也能正常生效。",
            en: "The base-plate layer-height modifier now also works for SVG gradient artwork when the base plate is not exported separately.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "批量生成的合并 3MF 打开后会保留工艺参数，不再出现切片软件里看不到参数的情况。",
            en: "Merged batch 3MF files now keep their process settings when opened in slicers instead of appearing with no parameters.",
          },
          {
            zh: "批量生成合并成一个 3MF 时，底板层高修改器会一起保留。",
            en: "Batch generation now preserves the base-plate layer-height modifier inside the merged 3MF.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-19",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "耗材档案搭配 SVG 时，深色和受限材料组合不再容易被吸到错误的大面积颜色上。",
            en: "SVGs in material-library mode are less likely to pull dark or limited-palette colours into the wrong large-area match.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-17",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "导出的 3MF 现在会带上封面缩略图，在切片软件和文件管理器里更容易认出是哪张图。",
            en: "Exported 3MF files now include cover thumbnails, making models easier to recognise in slicers and file managers.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "彩多屋梯度卡材料数据已更新，红色和青色档案会按新的校准结果使用。",
            en: "Caiduowu gradient-card material data has been refreshed, with red and cyan archives using the latest calibration results.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-15",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "配方查询会按观赏面优先显示和生成验证色块，预览里看到的层顺序和导出的色块样板更一致。",
            en: "Recipe lookup now follows the visible face first, so the preview order and exported swatch boards line up more naturally.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "梯度卡提取里的校色卡识别现在能稳定触发，不再偶发点了以后没有反应。",
            en: "Calibration-card detection in gradient-card extraction now triggers reliably instead of occasionally doing nothing after you click it.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "材料验证色块的层顺序会跟界面里的观赏面设置对齐，实物对色时更不容易看反。",
            en: "Material validation swatches now follow the visible-face setting from the UI, making real-world colour checks harder to read backwards.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-14",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "高保真模式处理 SVG 时，现在可以在设置里调整清晰度；默认值保持不变，想要更细或更快时可以自己调。",
            en: "High-Fidelity SVG conversion now has a detail setting. The default stays the same, and you can tune it for cleaner detail or faster runs.",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式会保留每种耗材自己的纯色配方，查询本色时不再容易被相近颜色挤掉。",
            en: "Material-library matching now keeps each material's own pure-colour recipe, so native filament colours are less likely to be crowded out by nearby matches.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "macOS 桌面版现在能更顺地启动和退出，Dock 里也会显示 Lumina 的彩色图标。",
            en: "The macOS desktop app now starts and quits more cleanly, and the Dock shows the coloured Lumina icon.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-10",
    title: {
      zh: "Lumina Layers — 近期更新速览",
      en: "Lumina Layers — Latest updates",
    },
    sections: [
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "Bug 反馈会自动带上最近的前端日志、接口失败和材料底板选择，开发者更容易复现问题。",
            en: "Bug reports now include recent frontend logs, API failures, and the selected backing material, making issues easier to reproduce.",
          },
          {
            zh: "反馈问题时现在会自动带上你当时用的原图、生成的 3MF、所选耗材档案，开发者更容易在本地复现你遇到的情况。",
            en: "Bug reports now automatically include the original image you used, the generated 3MF, and the selected material archives, so the developer can reproduce the problem locally more easily.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-05",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "全选颜色后现在也能打开自定义配方，不用再一个区域一个区域点；应用后只会改你选中的颜色区域。",
            en: "Custom recipes now open correctly after selecting a whole colour, so you no longer need to click regions one by one; applying the recipe only changes the colour areas you selected.",
          },
          {
            zh: "耗材档案高保真模式下，手动改过的 10 层配方会按真实槽位应用，默认白色层也不会再变成其它材料色。",
            en: "In high-fidelity material-library mode, edited 10-layer recipes now apply to the real material slots, and untouched white layers no longer turn into another material colour.",
          },
          {
            zh: "配方查询新增「配方队列」和验证色块生成：可以把多组材料配方先收进队列，一次导出 3MF 色块样板和图例，方便实物对色。",
            en: "Recipe lookup now has a recipe queue and validation-swatch export: collect multiple material recipes first, then generate one 3MF swatch board with a legend for real-world colour checks.",
          },
          {
            zh: "耗材选择器会按品牌分组并标出未分组材料；基础设置里也能指定底板耗材，背板和底色不再只能默认跟第一个耗材槽。",
            en: "Material pickers now group entries by brand and label unassigned materials; Basic Settings can also choose the backing material, so backing and base colours no longer have to follow the first material slot.",
          },
          {
            zh: "材料提取结果旁边现在直接显示合并、覆盖和取消操作，不用再滚回页面顶部处理保存确认。",
            en: "Material extraction results now show merge, override, and cancel actions right beside the results, so you no longer need to scroll back to the top to finish saving.",
          },
          {
            zh: "主动切到提取页面时会清理旧的确认状态，重新校验材料时仍会保留当前上下文，操作不再串台。",
            en: "Opening the extraction page now clears stale confirmation state, while material re-verification still keeps the current context, preventing actions from bleeding between workflows.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "6 色 RYBWGK / CMYWGK 的提取和保存更稳定，颜色模式不会再被错误显示成另一套 6 色或 4 色模式。",
            en: "6-Colour RYBWGK / CMYWGK extraction and saving are more stable, so a LUT is no longer displayed as the wrong 6-Colour or 4-Colour mode.",
          },
          {
            zh: "修复一组 6 色耗材通道顺序不一致导致的颜色错位，选择这类 LUT 时预览和生成会按实际通道顺序来。",
            en: "Fixed colour shifts from a 6-Colour filament set whose channel order differed from the standard order; previews and generation now follow the LUT's actual channel order.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "导出到 Bambu Studio / OrcaSlicer 时，PETG 槽位会保留 PETG 材料和温度配置，不再每次打开都退回 PLA。",
            en: "Exports to Bambu Studio / OrcaSlicer now keep PETG material and temperature settings for PETG slots instead of falling back to PLA every time.",
          },
          {
            zh: "材料档案、单阶段标定卡和挂件环会一起传递真实材料名，辅助零件不再偷偷变回默认 PLA。",
            en: "Material-library exports, single-stage calibration cards, and keychain loops now carry the real material names together, so auxiliary parts no longer silently fall back to default PLA.",
          },
          {
            zh: "校准板色块尺寸支持 5.5mm 这类小数输入，仍会保留原来的 3–10mm 安全范围。",
            en: "Calibration block size now accepts fractional values such as 5.5mm while keeping the existing safe 3–10mm range.",
          },
          {
            zh: "6 色传统 LUT 和 6 色校准板会复用预计算 Smart1296 配方，生成更快，也不再每次现场跑选色。",
            en: "6-Colour traditional LUTs and 6-Colour calibration boards now reuse a precomputed Smart1296 recipe set, making generation faster without running colour selection every time.",
          },
          {
            zh: "挂件环的几何面片更干净，切片软件预览不再容易出现未知面或闪烁，但仍保持正常切片。",
            en: "Keychain loop geometry is cleaner, so slicer previews are less likely to show unknown faces or flicker while slicing remains normal.",
          },
          {
            zh: "导出的 Bambu / Orca 项目不再把切料回抽相关的耗材覆盖项写死，避免模板里的长回抽和切料回抽距离影响实际切片参数。",
            en: "Bambu / Orca exports no longer hard-code filament cut-retraction overrides, preventing template long-retraction and cut-distance values from unexpectedly changing slicer settings.",
          },
          {
            zh: "耗材档案生成的白色底板和描边会继续使用当前底板材料；只有你显式指定独立背板颜色时才会切到另一种材料。",
            en: "Material-library white backing and outlines now keep using the selected backing material; they switch to another material only when a separate backing colour is explicitly chosen.",
          },
        ],
      },
      {
        category: { zh: "预览、切片器 & 交互", en: "Preview, Slicers & Interaction" },
        items: [
          {
            zh: "透明 PNG 和不规则图形的 3D 外轮廓更贴近实际图案，耗材档案预览不再把背板或其它颜色混进轮廓里。",
            en: "3D outlines for transparent PNGs and irregular shapes now follow the actual artwork more closely, and material-library previews no longer mix backing or other colours into the outline.",
          },
          {
            zh: "冰箱贴模式的槽位外轮廓会跟随当前厚度和主体形状，磁铁孔不会再污染轮廓预览。",
            en: "Fridge-magnet slot outlines now follow the current thickness and main shape, and magnet holes no longer pollute the outline preview.",
          },
          {
            zh: "图像转矢量页面改成更宽的左右布局，上传、基础设置、高级参数和结果区域不再挤成一列。",
            en: "The Image-to-Vector page now uses a wider split layout, so upload, basic settings, advanced parameters, and results no longer crowd into one column.",
          },
          {
            zh: "切片成功后切换打印机时会清理旧预览模型，重新导入前不再继续显示上一台设备的过期预览。",
            en: "After slicing, switching printers now clears stale preview models instead of keeping an outdated preview from the previous device.",
          },
          {
            zh: "选择或取消耗材时，耗材列表不再自动折叠变小，靠近列表底部的项目也能稳定点选。",
            en: "When selecting or unselecting materials, the material list no longer collapses unexpectedly, so items near the bottom stay easy to click.",
          },
          {
            zh: "梯度卡里的链接点击区域收窄到实际文字附近，不再横向占满整块结果区域。",
            en: "Gradient-card links now keep their clickable area close to the text instead of stretching across the whole result row.",
          },
          {
            zh: "macOS 设置页现在能自动扫描常见 Applications 目录和 Spotlight 里的 `.app` 切片软件，也支持手动指定 `.app` 路径。",
            en: "On macOS, Settings can now scan common Applications folders and Spotlight for slicer `.app` bundles, and custom `.app` paths can be validated manually.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式开启涂层后，生成的 3MF 会真正带上完整涂层，不再只在参数里显示已开启。",
            en: "When coating is enabled in SVG vector mode, the generated 3MF now actually includes the full coating instead of only showing the option as enabled.",
          },
          {
            zh: "矢量预览后的分享卡会保留来源、色层、材料和模型参数，导出再导入不再丢关键设置。",
            en: "Share cards exported after vector previews now preserve source, layer, material, and model settings, so importing them no longer loses key options.",
          },
          {
            zh: "SVG + 梯度卡和小矢量图形的材料匹配更干净，边缘和小色块不再容易冒出杂色。",
            en: "SVG + gradient-card and small vector artwork now get cleaner material matching, reducing stray colours around edges and tiny shapes.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "Custom 开头的个人 LUT 会正确生成颜色层和分层预览，不再只导出一个底层。",
            en: "Personal LUTs under Custom now generate colour layers and layer previews correctly instead of exporting only a base layer.",
          },
          {
            zh: "生成完成后切换 LUT 再下载，浏览器不再下载失败的 JSON 错误文件，3MF / ZIP 下载会在会话切换后继续可用一段时间。",
            en: "After generating and switching LUTs, the browser no longer downloads failed JSON error files; 3MF / ZIP downloads remain available for a while even after the session changes.",
          },
          {
            zh: "矢量预览后的分享卡导出在普通 HTTP 环境下也更可靠，不再因为浏览器加密接口限制直接失败。",
            en: "Share-card export after vector previews is more reliable on regular HTTP pages and no longer fails outright because of browser crypto restrictions.",
          },
          {
            zh: "批量转换会按当前设置正确传递参数，减少批量生成时出现设置错位的情况。",
            en: "Batch conversion now forwards the current settings in the correct order, reducing parameter mix-ups during batch generation.",
          },
          {
            zh: "反馈问题支持附带截图，并会带上当前来源、LUT、材料和打印参数，开发者更容易复现你遇到的情况。",
            en: "Bug reports can now include a screenshot and carry the current source, LUT, material, and print settings, making it easier for the developer to reproduce what you saw.",
          },
          {
            zh: "反馈弹窗的复制按钮增加兜底方案，即使浏览器剪贴板权限不稳定，也能手动复制问题信息。",
            en: "The bug-report copy button now has a fallback path, so you can still copy the report details manually when browser clipboard permissions are unreliable.",
          },
          {
            zh: "前后端回归测试重新稳定：缺少外部参考资产的环境会明确跳过对应测试，frozen raster 基线也已同步当前转换输出。",
            en: "Frontend and backend regression suites are stable again: environments without external reference assets now skip those tests explicitly, and frozen raster baselines match the current converter output.",
          },
          {
            zh: "App 启动、健康状态和设置初始化相关测试补齐了后台 hook / API mock，Vitest 不再因为未 mock 的副作用挂住。",
            en: "App startup, health-status, and settings-bootstrap tests now mock their background hooks and APIs, so Vitest no longer hangs on unmocked side effects.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-05-03",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "全选颜色后现在也能打开自定义配方，不用再一个区域一个区域点；应用后只会改你选中的颜色区域。",
            en: "Custom recipes now open correctly after selecting a whole colour, so you no longer need to click regions one by one; applying the recipe only changes the colour areas you selected.",
          },
          {
            zh: "耗材档案高保真模式下，手动改过的 10 层配方会按真实槽位应用，默认白色层也不会再变成其它材料色。",
            en: "In high-fidelity material-library mode, edited 10-layer recipes now apply to the real material slots, and untouched white layers no longer turn into another material colour.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "6 色 RYBWGK / CMYWGK 的提取和保存更稳定，颜色模式不会再被错误显示成另一套 6 色或 4 色模式。",
            en: "6-Colour RYBWGK / CMYWGK extraction and saving are more stable, so a LUT is no longer displayed as the wrong 6-Colour or 4-Colour mode.",
          },
          {
            zh: "修复一组 6 色耗材通道顺序不一致导致的颜色错位，选择这类 LUT 时预览和生成会按实际通道顺序来。",
            en: "Fixed colour shifts from a 6-Colour filament set whose channel order differed from the standard order; previews and generation now follow the LUT's actual channel order.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "导出到 Bambu Studio / OrcaSlicer 时，PETG 槽位会保留 PETG 材料和温度配置，不再每次打开都退回 PLA。",
            en: "Exports to Bambu Studio / OrcaSlicer now keep PETG material and temperature settings for PETG slots instead of falling back to PLA every time.",
          },
          {
            zh: "材料档案、单阶段标定卡和挂件环会一起传递真实材料名，辅助零件不再偷偷变回默认 PLA。",
            en: "Material-library exports, single-stage calibration cards, and keychain loops now carry the real material names together, so auxiliary parts no longer silently fall back to default PLA.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "透明 PNG 和不规则图形的 3D 外轮廓更贴近实际图案，耗材档案预览不再把背板或其它颜色混进轮廓里。",
            en: "3D outlines for transparent PNGs and irregular shapes now follow the actual artwork more closely, and material-library previews no longer mix backing or other colours into the outline.",
          },
          {
            zh: "冰箱贴模式的槽位外轮廓会跟随当前厚度和主体形状，磁铁孔不会再污染轮廓预览。",
            en: "Fridge-magnet slot outlines now follow the current thickness and main shape, and magnet holes no longer pollute the outline preview.",
          },
          {
            zh: "图像转矢量页面改成更宽的左右布局，上传、基础设置、高级参数和结果区域不再挤成一列。",
            en: "The Image-to-Vector page now uses a wider split layout, so upload, basic settings, advanced parameters, and results no longer crowd into one column.",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 矢量模式开启涂层后，生成的 3MF 会真正带上完整涂层，不再只在参数里显示已开启。",
            en: "When coating is enabled in SVG vector mode, the generated 3MF now actually includes the full coating instead of only showing the option as enabled.",
          },
          {
            zh: "矢量预览后的分享卡会保留来源、色层、材料和模型参数，导出再导入不再丢关键设置。",
            en: "Share cards exported after vector previews now preserve source, layer, material, and model settings, so importing them no longer loses key options.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "Custom 开头的个人 LUT 会正确生成颜色层和分层预览，不再只导出一个底层。",
            en: "Personal LUTs under Custom now generate colour layers and layer previews correctly instead of exporting only a base layer.",
          },
          {
            zh: "生成完成后切换 LUT 再下载，浏览器不再下载失败的 JSON 错误文件，3MF / ZIP 下载会在会话切换后继续可用一段时间。",
            en: "After generating and switching LUTs, the browser no longer downloads failed JSON error files; 3MF / ZIP downloads remain available for a while even after the session changes.",
          },
          {
            zh: "反馈问题支持附带截图，并会带上当前来源、LUT、材料和打印参数，开发者更容易复现你遇到的情况。",
            en: "Bug reports can now include a screenshot and carry the current source, LUT, material, and print settings, making it easier for the developer to reproduce what you saw.",
          },
          {
            zh: "反馈弹窗的复制按钮增加兜底方案，即使浏览器剪贴板权限不稳定，也能手动复制问题信息。",
            en: "The bug-report copy button now has a fallback path, so you can still copy the report details manually when browser clipboard permissions are unreliable.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-30",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "应用右上角新增「反馈问题」入口：遇到问题写一句描述就能直接提交给开发者，不用再先截图发微信再讲半天环境。",
            en: "A new 「Report a bug」 entry sits in the top-right corner: type a one-liner and submit it straight to the developer — no more screenshot-first-then-explain workflow.",
          },
          {
            zh: "反馈会自动带上你当前的工作流（converter / single stage 等）、color mode、LUT 名字、session ID 和浏览器信息，不用自己回忆环境；同一个工单号也会出现在邮件主题里，开发者一眼对得上。",
            en: "Each report auto-collects your active workstream (converter / single stage), color mode, LUT name, session id, and browser info — no need to recall the environment yourself; the same ticket id is in the email subject so the developer can match it instantly.",
          },
          {
            zh: "提交成功后弹窗会留住工单号方便你复制，关闭按钮在你手上——不会再 1 秒自动消失来不及抄。",
            en: "The success view keeps the ticket id on screen so you have time to copy it — closing is up to you, no more 1-second auto-dismiss.",
          },
          {
            zh: "即使本地没配邮件服务，反馈也会落盘到 feedback/ 目录兜底，开发者可以直接拷走那份 JSON；网络断了也丢不了反馈。",
            en: "Even when SMTP isn't configured locally, reports still land in the feedback/ directory as a JSON dump that the developer can pull directly — flaky networks no longer lose reports.",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "转换器主面板拆分为「核心」「颜色」「高级」三个子标签页，常用功能和高级选项不再挤在同一屏；底部颜色工作站入口也改到顶部二级标签，找起来更直觉。",
            en: "The converter panel is now split into Core / Colour / Advanced sub-tabs so everyday controls and power-user options no longer share a single scroll; the Color Workstation entry moves from the bottom drawer up to a top-level secondary tab for easier access.",
          },
          {
            zh: "3D 查看器右下角诊断弹窗精简：FPS 旁加了红/黄/绿状态点，新增帧耗时一行，去掉了几行只有开发者才关心的指标。",
            en: "The 3D viewer diagnostics popover is now leaner: FPS gets a green/yellow/red dot, a new frame-time row is added, and several developer-only metrics are removed.",
          },
          {
            zh: "颜色工作站 2D 叠层打开时不再上下滑入，改为淡入淡出，过渡更快也不会闪一下布局。",
            en: "The Color Workstation 2D overlay now fades in instead of sliding, making the transition faster and eliminating a brief layout flash.",
          },
          {
            zh: "所有滑块和复选框旁边的帮助提示统一为可见的小问号图标，鼠标悬停弹出说明，不再需要猜哪个控件有隐藏提示。",
            en: "Help hints on all sliders and checkboxes are now shown as a visible question-mark chip that reveals a description on hover, so you no longer have to guess which controls have hidden tooltips.",
          },
          {
            zh: "面板展开/收起动画全面优化：面板高度变化与同级组件位置避让完全同步，不再出现面板展开了但旁边还在挪的割裂感。",
            en: "Widget expand/collapse animations fully optimised: panel height and sibling position shifts now animate in sync, eliminating the visible disconnect where the panel finished expanding but siblings were still sliding.",
          },
          {
            zh: "面板背景毛玻璃效果移除，改用 80% 不透明度背景：之前的 backdrop-blur 在 92% 不透明度下模糊几乎看不见但 GPU 每帧都要采样卷积，去掉后以接近零开销提供同等半透明视觉。",
            en: "Panel backdrop-blur removed in favour of a fixed 80% opacity background: the previous blur was barely visible at 92% opacity but cost a per-frame GPU sample-and-convolve; removing it gives the same translucent look at near-zero cost.",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "「再次验证」现在做合并样本重拟合，而不是对参数取算术平均：Beer-Lambert 在 k 上是非线性的，平均参数统计上不成立；改成把每次拍摄的样本拼起来重新拟合后，多次校准 = 真正更精确才成立。",
            en: "Re-verification now refits Beer-Lambert on the concatenated samples instead of arithmetically averaging (E, k): the model is non-linear in k, so parameter averaging is statistically meaningless. With combined-sample refitting, more captures actually yield a more accurate fit.",
          },
          {
            zh: "「图像来源」标签现在区分原图和 ColorChecker 校正/还原图：校正图可以减少相机色差，但会和原图样本分开合并；真正需要处理的是采样区出现高光或阴影裁切，软件会用「零厚度白底采样接近纯白」等警告提示。",
            en: "The Image Source tag now separates raw captures from ColorChecker-corrected/restored images. Corrected images can reduce camera colour bias, but they are merged separately from raw samples; the real issue to handle is highlight or shadow clipping in the sampled area, surfaced through warnings such as \"zero-thickness white near pure white\".",
          },
          {
            zh: "多 run 聚合自动剔除偏置 run：白底过亮、底板平、单 run ΔE>3 等结构性偏置会被排除在联合重拟合之外；3 个以上历史 run 还会做交叉验证，剔除「自我一致但和别人不一致」的捕获；新 run 始终保留以便审计。",
            en: "Multi-run aggregation now bias-filters: structurally biased runs (overbright white substrate, flat substrate, single-run ΔE>3, …) are excluded from the joint refit; with 3+ historicals a cross-validation pass also drops self-consistent-but-pairwise-inconsistent captures; the freshest run is always kept for audit.",
          },
          {
            zh: "拟合零厚度白底接近纯白（C0_white 均值 > 0.95）现在会单独发警告，识别「ΔE 看着低但 (E, k) 已偏离物理真值」的隐形失效。",
            en: "Stage A now emits a dedicated warning when the zero-thickness white-substrate sample sits above 0.95 in linear RGB, exposing the silent failure mode where ΔE still looks fine but (E, k) has drifted off the true physical attenuation.",
          },
          {
            zh: "校准板默认底板厚度从 1.6 mm 改为 1.2 mm，更贴近常见打印设置；所有颜色模式（包括 6 色）现在都能调底板厚度滑块，不再有模式限制。",
            en: "Default calibration board backing thickness changed from 1.6 mm to 1.2 mm to match common print settings; the slider is now available in every colour mode (including 6-Colour) with no mode restriction.",
          },
        ],
      },
      {
        category: { zh: "提取器（校色卡）", en: "Extractor (Calibration Card)" },
        items: [
          {
            zh: "SVG + 梯度卡模式不再走 K-Means 量化预算，改为用频次直方图取覆盖 99% 可见像素的真实填充色板，再 KDTree 把剩余像素吸附到最近填充色：以前 256 量化预算会给抗锯齿过渡带开簇产生「不沿走线」的杂色配方，现在 SVG 真实有几个填充色就只生成几条配方。",
            en: "SVG + gradient-card material-archive mode no longer feeds the rasterized image to K-Means with a 256-cluster budget. Instead it picks the smallest top-K colors covering 99% of visible pixels as the real fill palette and KDTree-snaps every visible pixel to its nearest fill. The old path spent clusters on anti-aliased edge blends and produced 'noise pixels off the strokes'; now the SVG yields exactly its true fill count of recipes.",
          },
          {
            zh: "耗材档案 + SVG + 矢量现在与 LUT 矢量共用同一条原生矢量管线（解析 → 遮挡裁剪 → 网格挤出 → 抗锯齿预览光栅化），只在颜色匹配那一步用 Beer-Lambert 求解器替代 LUT KDTree：之前耗材档案会先把 SVG 光栅化再做像素吸附 + 逐像素材料映射，2D 预览出来的是硬边像素图、走线边缘还会有 1px 邻色杂点；现在矢量预览的边缘抗锯齿和填充色边界都和 LUT 矢量保持一致，配方仍然由耗材求解器逐唯一色输出。",
            en: "Material archive + SVG + vector now shares the same native vector pipeline as LUT vector mode (parse → occlusion clip → mesh extrude → anti-aliased preview rasterisation); only the per-fill colour matching step is swapped — the LUT KDTree is replaced by the Beer-Lambert solver. The old path rasterised the SVG first, snapped pixels to a fill palette, then ran a per-pixel material mapping, which produced hard-edged pixel previews and the occasional 1-pixel off-colour speck along strokes; the new path keeps anti-aliased fill edges identical to LUT vector mode while still routing recipes through the material solver per unique colour.",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "修复矢量模式下颜色工作站做区域替换或多选区域替换后，生成的 3MF 模型不反映替换的问题；现在 2D 预览改了什么，最终模型就改了什么。",
            en: "Fixed vector mode losing region or multi-region colour edits made in the Color Workstation; what you see in the 2D preview now matches the generated 3MF.",
          },
          {
            zh: "SVG 矢量生成现在纳入和光栅流程同一套日志治理检查，预览到生成之间的问题更容易在发布前被发现。",
            en: "SVG vector generation is now covered by the same log-governance checks as raster, making preview-to-generate issues easier to catch before release.",
          },
          {
            zh: "修复校准板生成完成后日志记录引用已删除字段导致的报错，之前在默认 4 色模式下生成校准板会返回 500。",
            en: "Fixed a logging error that referenced a removed field after calibration board generation, which previously turned a successful 4-Colour generation into a 500 response.",
          },
          {
            zh: "5 色扩展 Page 2 的分层预览现在包含全部 6 个色层，之前漏掉了最后一层。",
            en: "The layer preview for 5-Colour Extended Page 2 now includes all 6 colour layers instead of silently dropping the last one.",
          },
          {
            zh: "Widget 面板不再拦截 3D 场景的旋转拖拽，拖到面板区域时模型照常转动；LUT 详情标签页切换时也不再黑屏闪烁。",
            en: "Widget panels no longer block 3D orbit controls — dragging into a panel area keeps the model rotating as expected; switching LUT detail tabs no longer causes a brief black flash either.",
          },
          {
            zh: "修复在梯度卡提取子标签之间切换时，上一次「再次验证」的状态可能污染下一次新校准的问题。",
            en: "Fixed verification state from a previous re-verification leaking into a fresh calibration when switching between gradient-card extract sub-tabs.",
          },
          {
            zh: "五色 LUT 基础颜色端点改用规范的 combinations 接口；旧版 flat-list JSON LUT（根为列表）不再因 schema 不匹配返回 500。",
            en: "The five-color base-colors endpoint now reads through the canonical combinations accessor; legacy flat-list JSON LUTs (list-rooted) no longer 500 due to a schema mismatch in the source extractor.",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-26",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "顶部材料管理新增 「LUT 详情」 入口：可以浏览所有可用 LUT、查看调色板和每种颜色的用量覆盖，还能在 2D/3D 视图里看色相覆盖图和 Lab 点云，心里有数再去选 LUT",
            en: "A new 「LUT details」 entry in the top Material-Management menu lets you browse every available LUT, inspect its palette and per-colour coverage, and view hue-coverage charts plus a Lab point cloud in 2D/3D — so you can pick a LUT with a clear idea of what it actually covers",
          },
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
          {
            zh: "设置里加了「渐变自动换色」开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → 「Auto replace gradient banding」 toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式下，预览完成后会自动检测原图里平滑渐变被切成多种耗材色的情况，在颜色面板里列成一组一组，点一下就能把整组色块一次选中送去换色",
            en: "In material-archive mode, a successful preview automatically detects smooth source gradients that got quantised into several material colours and lists them as gradient groups; one click multi-selects the whole group for batch replacement",
          },
          {
            zh: "每组还能展开看到里面的独立区域（脸、嘴巴、手等），按区域单独选颜色，而不是只能整组一起换",
            en: "Expand a group to see its spatial regions (face, mouth, hand, etc.) and select a single region's colours instead of the whole group",
          },
          {
            zh: "每个大分组和小分组右边都加了一个「去海带纹」按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "在不同分组之间快速切换时，预览上不会再因为旧请求晚到而显示到旧的高亮色，始终跟当前选中保持一致",
            en: "Rapid switching between gradient groups no longer leaves a stale highlight on the preview: out-of-order responses are dropped so the canvas always matches the current selection",
          },
          {
            zh: "从整组切到组内某个区域时，整组按钮会正确地变灰、只有被点击的区域保持选中态；不会再出现整组和区域同时显示选中的情况",
            en: "Clicking a region inside a group correctly dims the parent group button so only the region you just picked stays highlighted, instead of both lighting up at once",
          },
          {
            zh: "点击小分组时，右边预览只会高亮这个小分组所在的那一块区域，不再把整组覆盖的同色像素全部点亮",
            en: "Clicking a sub-region now highlights only that region in the preview, instead of lighting up every matching pixel across the whole group",
          },
          {
            zh: "选中某个小分组后再从 LUT 里挑颜色换色，现在只会改这一块区域的像素；共享相同颜色的其它区域不会再被一起覆盖",
            en: "Picking a LUT colour while a sub-region is selected now repaints only that region's pixels; other regions that happen to share the same colour stay untouched",
          },
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
          {
            zh: "梯度卡方向控制改成大白话：原来那个看不懂的「白底/黑底方向覆盖」下拉，现在变成「纯白/纯黑色块位置」——直接选色块在照片的哪个角（左上/右上/右下/左下），不用再猜「沿主对角线转置」是什么意思了。",
            en: "Gradient-card orientation control speaks plain language now: the cryptic 「White/Black Orientation Override」 dropdown has been replaced by 「Pure White/Black Block Position」, where you simply pick which screen corner holds the bare-board patch (top-left, top-right, bottom-right, or bottom-left).",
          },
          {
            zh: "梯度卡图片栏的「旋转 90°」按钮拆成「顺时针 90°」和「逆时针 90°」两个，点哪个图就直接转哪个方向，不用再连点 3 下凑出顺时针。",
            en: "The single 「Rotate 90°」 button on each gradient-card image card is now split into 「Rotate 90° CW」 and 「Rotate 90° CCW」, so you can rotate either direction in one click instead of triple-tapping the counter-clockwise button.",
          },
          {
            zh: "梯度卡四角点选会明确提示按 1.左上 → 2.右上 → 3.右下 → 4.左下 顺时针顺序点，配合「色块位置」选项能稳定推导采样方向。",
            en: "Gradient-card corner picking now clearly prompts you to click the four corners in 1.top-left → 2.top-right → 3.bottom-right → 4.bottom-left clockwise order, which combines with the new 「block position」 selector to determine sampling orientation reliably.",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
          {
            zh: "梯度卡生成界面重新排版并去除了中英夹杂：现在清晰分为「生成设置」与「使用须知」，在线模型链接和两张卡（白底/黑底）的打印说明一目了然，不用再到处找教程了。",
            en: "The Gradient Generator panel has been redesigned with clean, plain-language sections: 「Generation Settings」 and 「Instructions & Online Models」 are clearly separated, and the requirement to print two cards (white base and black base) is prominently explained so you no longer have to hunt for tutorials.",
          },
        ],
      },
      {
        category: {
          zh: "预览 & 交互",
          en: "Preview & Interaction",
        },
        items: [
          {
            zh: "分层遮罩查看窗新增跟随鼠标的放大镜，检查细边和层间对齐时不用再来回缩放",
            en: "The layer-mask viewer now has a follow-cursor magnifier, making fine-edge and layer-alignment checks easier without constant zooming",
          },
          {
            zh: "颜色工作站放大后会继续用精准点选光标，不再用小手挡住小色块；需要移动画面时仍可右键拖动",
            en: "The Color Workstation now keeps a precise picking cursor after zooming instead of covering tiny swatches with a hand cursor, while right-button panning still works when you need to move the view",
          },
          {
            zh: "3D 预览模型变得小很多、加载快很多，远程打开也能更快看到模型，真正导出的 3MF 和打印精度不受影响",
            en: "3D preview models are much smaller and load far faster, especially over remote sessions, while exported 3MF files and print accuracy stay unchanged",
          },
          {
            zh: "滑块拖动时不会再自己多跳半格，数值会乖乖停在你拖到的位置",
            en: "Sliders no longer bump themselves by half a step while dragging, so values stay where you actually placed them",
          },
          {
            zh: "导出的 3MF 会带一个切片器能正常读取的预览图，占位图不再卡住 Anycubic Slicer Next",
            en: "Exported 3MF files now include a preview image that slicers can read correctly, so placeholder thumbnails no longer hang Anycubic Slicer Next",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "SVG 导出 3MF 时会真正带上自定义配方和额外添加的颜色层，不会只在界面上看着改了、导出后又丢掉",
            en: "SVG-to-3MF export now carries custom recipes and extra colour layers through to the file instead of only showing them in the UI",
          },
          {
            zh: "带插画风细线的 SVG 不会再被悄悄加粗，复杂边缘处理失败时也会自动走兜底，不会整次生成断掉",
            en: "Illustrated SVGs with fine strokes are no longer silently widened, and complex edge-processing failures now fall back safely instead of breaking the whole generation",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "反推 LUT 会坚持使用自己带的调色板，就算设置里还残留着旧颜色模式，也不会拿错颜色去匹配",
            en: "Inferred LUTs now keep using their own palettes even if settings still contain an older colour mode, avoiding mismatched colour picks",
          },
          {
            zh: "生成 3D 时，加载按钮不会再被浏览器翻译或插件改乱后把操作栏弄崩，模型生成完成后能继续正常显示",
            en: "During 3D generation, loading buttons no longer let browser translation or extensions break the action panel, so the finished model can keep showing normally",
          },
          {
            zh: "下载或复制 3MF 链接后再回来重新生成，不会再因为临时文件被清掉而报 409",
            en: "After downloading or copying a 3MF link, generating again no longer fails with 409 because required temp files were cleaned too aggressively",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-24",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "顶部材料管理新增 「LUT 详情」 入口：可以浏览所有可用 LUT、查看调色板和每种颜色的用量覆盖，还能在 2D/3D 视图里看色相覆盖图和 Lab 点云，心里有数再去选 LUT",
            en: "A new 「LUT details」 entry in the top Material-Management menu lets you browse every available LUT, inspect its palette and per-colour coverage, and view hue-coverage charts plus a Lab point cloud in 2D/3D — so you can pick a LUT with a clear idea of what it actually covers",
          },
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
          {
            zh: "设置里加了「渐变自动换色」开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → 「Auto replace gradient banding」 toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式下，预览完成后会自动检测原图里平滑渐变被切成多种耗材色的情况，在颜色面板里列成一组一组，点一下就能把整组色块一次选中送去换色",
            en: "In material-archive mode, a successful preview automatically detects smooth source gradients that got quantised into several material colours and lists them as gradient groups; one click multi-selects the whole group for batch replacement",
          },
          {
            zh: "每组还能展开看到里面的独立区域（脸、嘴巴、手等），按区域单独选颜色，而不是只能整组一起换",
            en: "Expand a group to see its spatial regions (face, mouth, hand, etc.) and select a single region's colours instead of the whole group",
          },
          {
            zh: "每个大分组和小分组右边都加了一个「去海带纹」按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "在不同分组之间快速切换时，预览上不会再因为旧请求晚到而显示到旧的高亮色，始终跟当前选中保持一致",
            en: "Rapid switching between gradient groups no longer leaves a stale highlight on the preview: out-of-order responses are dropped so the canvas always matches the current selection",
          },
          {
            zh: "从整组切到组内某个区域时，整组按钮会正确地变灰、只有被点击的区域保持选中态；不会再出现整组和区域同时显示选中的情况",
            en: "Clicking a region inside a group correctly dims the parent group button so only the region you just picked stays highlighted, instead of both lighting up at once",
          },
          {
            zh: "点击小分组时，右边预览只会高亮这个小分组所在的那一块区域，不再把整组覆盖的同色像素全部点亮",
            en: "Clicking a sub-region now highlights only that region in the preview, instead of lighting up every matching pixel across the whole group",
          },
          {
            zh: "选中某个小分组后再从 LUT 里挑颜色换色，现在只会改这一块区域的像素；共享相同颜色的其它区域不会再被一起覆盖",
            en: "Picking a LUT colour while a sub-region is selected now repaints only that region's pixels; other regions that happen to share the same colour stay untouched",
          },
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
          {
            zh: "设置里新增 「穷举数量」 开关：默认关闭，走低档（64³，构建快、内存小）；开启后可以选中（128³）或高（256³），穷举缓存会更细、颜色更准，代价是构建时间、内存占用、每次生成查找都会成倍变长。穷举缓存弹窗里会直接显示当前用哪一档，不同档的缓存分开存放、互不覆盖",
            en: 'New Settings → "Exhaustive density" switch: off by default and uses the low tier (64³) — fast to build, low memory; flip it on to pick medium (128³) or high (256³) for tighter colour accuracy at the cost of proportionally longer builds, more memory, and slower per-conversion lookups. The exhaustive-cache dialog shows the active tier, and caches at different tiers are stored separately so switching never overwrites an existing build',
          },
          {
            zh: "耗材库的「编辑信息」弹窗里新增显示颜色编辑：可直接用颜色选择器挑色，或输入 #RRGGBB 色号，保存后列表、选色面板和预览上的耗材色块都会跟着更新；再做一次复测会用新的测量值覆盖回去",
            en: "The Material Library → Edit Details dialog now lets you override the display colour: pick a colour with the native picker or type a #RRGGBB code, and after saving the library, picker and preview swatches all follow suit; running a new verification will overwrite it with the freshly measured colour again",
          },
        ],
      },
      {
        category: {
          zh: "预览 & 交互",
          en: "Preview & Interaction",
        },
        items: [
          {
            zh: "分层遮罩查看窗新增放大镜：鼠标悬停画布时会跟随出现一个高倍放大窗口，对齐细小边缘和逐层检查方便多了，窗口内部仍用 Canvas 绘制，不占显存",
            en: "The layer-mask viewer gains a follow-cursor magnifier: hover over the canvas and a zoomed-in lens tracks the pointer, making it easier to align fine edges and double-check layers without extra GPU cost",
          },
          {
            zh: "3D 预览加载大幅提速：以前上百 MB 的预览模型在远程使用时要等很久才出现，现在真实多色图通常只有几 MB，一打开画面就能看到 3D 模型；实际导出的 3MF 和打印精度完全不受影响",
            en: "The 3D preview loads dramatically faster: what used to be a 100+ MB model that kept remote users waiting is now typically just a few MB on real multi-colour images, so the 3D scene appears almost immediately; the actual exported 3MF and its print precision are completely unchanged",
          },
          {
            zh: '厚度等滑条修掉了"一松手就自动加 0.08"的问题：之前每次拖动停下来，值都会被悄悄往上多挪半格；右边数字框里手动输入 1.5 / 3.5 也不会再被改成 0.08 的整数倍（如 1.52）',
            en: "Sliders like Thickness no longer add an extra 0.08 every time you let go: previously each drag release was silently bumped up by half a step, and typing precise values like 1.5 or 3.5 into the number box on the right got rewritten to the nearest step multiple (such as 1.52)",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "含描边的 SVG 生成更贴合线稿：默认忽略纯描边轮廓与同色描边扩边，避免黑边与线条变粗",
            en: "SVGs with strokes now match the drawing more closely: stroke-only outlines and same-colour stroke padding are ignored by default, removing dark edges and thickened lines",
          },
          {
            zh: "插画类 SVG 预览回到干净矢量效果：细描边的粗细和源文件保持一致，不再被整体加粗；尖角也不会外突出锯齿毛刺",
            en: "Illustrated SVGs now preview as clean vectors: thin stroke widths follow the source file instead of being globally thickened, and sharp corners no longer produce outward spikes or fuzzy jaggies",
          },
          {
            zh: "2D 预览形状边缘过渡更平滑，告别像素化阶梯锯齿",
            en: "2D preview shape boundaries are noticeably smoother, replacing the stair-stepped pixel jaggies with anti-aliased edges",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "与参考实现对齐 backing silhouette 的 close / hole / slit 过滤阈值，并为色块层补充空洞过滤，减少白色气泡",
            en: "Align backing silhouette close / hole / slit thresholds and add color-layer hole filtering with the reference implementation to reduce white bubble artifacts",
          },
          {
            zh: "SVG 矢量图 + 传统 LUT 模式下，自定义配方里改过的颜色和加过的层，现在会真实写进导出的 3MF；之前只能在 2D 预览里看到效果，实际 3MF 会悄悄退回 LUT 默认配色，加的层也像没加过一样",
            en: "For SVG vector inputs with a traditional LUT, recipe edits and extra layers made in the custom recipe dialog now actually land in the exported 3MF; previously the 2D preview reflected them but the 3MF silently fell back to the LUT's default match, as if the custom recipe and added layers had never been applied",
          },
          {
            zh: "反推 LUT 导出的 3MF 不再跟上一次选过的传统 LUT 串色：之前如果上次选的是 CMYW，反推 LUT 的蓝 / 红 / 绿 / 黑会被错刷成青 / 品红 / 黄，黑甚至变成白；栅格（高保真）和 SVG 矢量建模两种路径现在都直接用反推 LUT 自己的调色板，耗材槽名和颜色不再因为上次的颜色模式而翻车",
            en: "3MF files exported from the Inferred LUT no longer pick up colours from the previously-selected legacy LUT: blue / red / green / black slots used to be silently recoloured as cyan / magenta / yellow (and black could come out white) when CMYW was picked last — both the raster (high-fidelity) and SVG vector modelling paths now honour the Inferred LUT's own palette, so filament slot names and colours are correct regardless of what colour mode was used before",
          },
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
          {
            zh: "导出的 3MF 现在能在 Anycubic 切片软件（纵维立方 Anycubic Slicer Next）里正常打开——之前一拖进去就闪退，原因是自动生成的预览缩略图本身就是损坏的；别的切片软件一直没受影响，是因为它们遇到坏缩略图会静默跳过",
            en: "Exported 3MF files now open normally in Anycubic Slicer Next — they used to crash the moment you dropped one in, because the auto-generated preview thumbnails were themselves corrupt; other slicers were unaffected because they silently skip over broken thumbnails",
          },
          {
            zh: "耗材档案预览：偶尔出现的 「10 层效果反而比 5 层差」 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional 「10 layers look worse than 5 layers」 regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-23",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
          {
            zh: "设置里加了「渐变自动换色」开关：开启后每次预览成功会自动把每一组渐变统一替换成组内代表色，一键去掉海带纹；默认关闭，原有手动换色流程不受影响",
            en: "New Settings → 「Auto replace gradient banding」 toggle: when on, every successful preview auto-collapses each gradient group to its representative colour to erase banding in one shot; off by default so the manual flow stays unchanged",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "耗材档案模式下，预览完成后会自动检测原图里平滑渐变被切成多种耗材色的情况，在颜色面板里列成一组一组，点一下就能把整组色块一次选中送去换色",
            en: "In material-archive mode, a successful preview automatically detects smooth source gradients that got quantised into several material colours and lists them as gradient groups; one click multi-selects the whole group for batch replacement",
          },
          {
            zh: "每组还能展开看到里面的独立区域（脸、嘴巴、手等），按区域单独选颜色，而不是只能整组一起换",
            en: "Expand a group to see its spatial regions (face, mouth, hand, etc.) and select a single region's colours instead of the whole group",
          },
          {
            zh: "每个大分组和小分组右边都加了一个「去海带纹」按钮，不必先选中再回到拾色器，直接一键把这一处渐变压成代表色",
            en: "Every group and region row now has its own Flatten button — no need to first multi-select and pick a target colour, one click collapses that specific gradient to its representative colour",
          },
          {
            zh: "在不同分组之间快速切换时，预览上不会再因为旧请求晚到而显示到旧的高亮色，始终跟当前选中保持一致",
            en: "Rapid switching between gradient groups no longer leaves a stale highlight on the preview: out-of-order responses are dropped so the canvas always matches the current selection",
          },
          {
            zh: "从整组切到组内某个区域时，整组按钮会正确地变灰、只有被点击的区域保持选中态；不会再出现整组和区域同时显示选中的情况",
            en: "Clicking a region inside a group correctly dims the parent group button so only the region you just picked stays highlighted, instead of both lighting up at once",
          },
          {
            zh: "点击小分组时，右边预览只会高亮这个小分组所在的那一块区域，不再把整组覆盖的同色像素全部点亮",
            en: "Clicking a sub-region now highlights only that region in the preview, instead of lighting up every matching pixel across the whole group",
          },
          {
            zh: "选中某个小分组后再从 LUT 里挑颜色换色，现在只会改这一块区域的像素；共享相同颜色的其它区域不会再被一起覆盖",
            en: "Picking a LUT colour while a sub-region is selected now repaints only that region's pixels; other regions that happen to share the same colour stay untouched",
          },
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
        ],
      },
      {
        category: {
          zh: "预览 & 交互",
          en: "Preview & Interaction",
        },
        items: [
          {
            zh: "3D 预览加载大幅提速：以前上百 MB 的预览模型在远程使用时要等很久才出现，现在真实多色图通常只有几 MB，一打开画面就能看到 3D 模型；实际导出的 3MF 和打印精度完全不受影响",
            en: "The 3D preview loads dramatically faster: what used to be a 100+ MB model that kept remote users waiting is now typically just a few MB on real multi-colour images, so the 3D scene appears almost immediately; the actual exported 3MF and its print precision are completely unchanged",
          },
          {
            zh: '厚度等滑条修掉了"一松手就自动加 0.08"的问题：之前每次拖动停下来，值都会被悄悄往上多挪半格；右边数字框里手动输入 1.5 / 3.5 也不会再被改成 0.08 的整数倍（如 1.52）',
            en: "Sliders like Thickness no longer add an extra 0.08 every time you let go: previously each drag release was silently bumped up by half a step, and typing precise values like 1.5 or 3.5 into the number box on the right got rewritten to the nearest step multiple (such as 1.52)",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "SVG 矢量图 + 传统 LUT 模式下，自定义配方里改过的颜色和加过的层，现在会真实写进导出的 3MF；之前只能在 2D 预览里看到效果，实际 3MF 会悄悄退回 LUT 默认配色，加的层也像没加过一样",
            en: "For SVG vector inputs with a traditional LUT, recipe edits and extra layers made in the custom recipe dialog now actually land in the exported 3MF; previously the 2D preview reflected them but the 3MF silently fell back to the LUT's default match, as if the custom recipe and added layers had never been applied",
          },
          {
            zh: "反推 LUT 导出的 3MF 不再跟上一次选过的传统 LUT 串色：之前如果上次选的是 CMYW，反推 LUT 的蓝 / 红 / 绿 / 黑会被错刷成青 / 品红 / 黄，黑甚至变成白；栅格（高保真）和 SVG 矢量建模两种路径现在都直接用反推 LUT 自己的调色板，耗材槽名和颜色不再因为上次的颜色模式而翻车",
            en: "3MF files exported from the Inferred LUT no longer pick up colours from the previously-selected legacy LUT: blue / red / green / black slots used to be silently recoloured as cyan / magenta / yellow (and black could come out white) when CMYW was picked last — both the raster (high-fidelity) and SVG vector modelling paths now honour the Inferred LUT's own palette, so filament slot names and colours are correct regardless of what colour mode was used before",
          },
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
          {
            zh: "导出的 3MF 现在能在 Anycubic 切片软件（纵维立方 Anycubic Slicer Next）里正常打开——之前一拖进去就闪退，原因是自动生成的预览缩略图本身就是损坏的；别的切片软件一直没受影响，是因为它们遇到坏缩略图会静默跳过",
            en: "Exported 3MF files now open normally in Anycubic Slicer Next — they used to crash the moment you dropped one in, because the auto-generated preview thumbnails were themselves corrupt; other slicers were unaffected because they silently skip over broken thumbnails",
          },
          {
            zh: "耗材档案预览：偶尔出现的 「10 层效果反而比 5 层差」 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional 「10 layers look worse than 5 layers」 regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-22",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
          {
            zh: "设置里新增 「穷举数量」 开关：默认关闭，走低档（64³，构建快、内存小）；开启后可以选中（128³）或高（256³），穷举缓存会更细、颜色更准，代价是构建时间、内存占用、每次生成查找都会成倍变长。穷举缓存弹窗里会直接显示当前用哪一档，不同档的缓存分开存放、互不覆盖",
            en: 'New Settings → "Exhaustive density" switch: off by default and uses the low tier (64³) — fast to build, low memory; flip it on to pick medium (128³) or high (256³) for tighter colour accuracy at the cost of proportionally longer builds, more memory, and slower per-conversion lookups. The exhaustive-cache dialog shows the active tier, and caches at different tiers are stored separately so switching never overwrites an existing build',
          },
        ],
      },
      {
        category: {
          zh: "预览 & 交互",
          en: "Preview & Interaction",
        },
        items: [
          {
            zh: "3D 预览加载大幅提速：以前上百 MB 的预览模型在远程使用时要等很久才出现，现在真实多色图通常只有几 MB，一打开画面就能看到 3D 模型；实际导出的 3MF 和打印精度完全不受影响",
            en: "The 3D preview loads dramatically faster: what used to be a 100+ MB model that kept remote users waiting is now typically just a few MB on real multi-colour images, so the 3D scene appears almost immediately; the actual exported 3MF and its print precision are completely unchanged",
          },
          {
            zh: '厚度等滑条修掉了"一松手就自动加 0.08"的问题：之前每次拖动停下来，值都会被悄悄往上多挪半格；右边数字框里手动输入 1.5 / 3.5 也不会再被改成 0.08 的整数倍（如 1.52）',
            en: "Sliders like Thickness no longer add an extra 0.08 every time you let go: previously each drag release was silently bumped up by half a step, and typing precise values like 1.5 or 3.5 into the number box on the right got rewritten to the nearest step multiple (such as 1.52)",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "反推 LUT 导出的 3MF 不再跟上一次选过的传统 LUT 串色：之前如果上次选的是 CMYW，反推 LUT 的蓝 / 红 / 绿 / 黑会被错刷成青 / 品红 / 黄，黑甚至变成白；栅格（高保真）和 SVG 矢量建模两种路径现在都直接用反推 LUT 自己的调色板，耗材槽名和颜色不再因为上次的颜色模式而翻车",
            en: "3MF files exported from the Inferred LUT no longer pick up colours from the previously-selected legacy LUT: blue / red / green / black slots used to be silently recoloured as cyan / magenta / yellow (and black could come out white) when CMYW was picked last — both the raster (high-fidelity) and SVG vector modelling paths now honour the Inferred LUT's own palette, so filament slot names and colours are correct regardless of what colour mode was used before",
          },
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
          {
            zh: "导出的 3MF 现在能在 Anycubic 切片软件（纵维立方 Anycubic Slicer Next）里正常打开——之前一拖进去就闪退，原因是自动生成的预览缩略图本身就是损坏的；别的切片软件一直没受影响，是因为它们遇到坏缩略图会静默跳过",
            en: "Exported 3MF files now open normally in Anycubic Slicer Next — they used to crash the moment you dropped one in, because the auto-generated preview thumbnails were themselves corrupt; other slicers were unaffected because they silently skip over broken thumbnails",
          },
          {
            zh: "耗材档案预览：偶尔出现的 「10 层效果反而比 5 层差」 已修复。更多层数的匹配结果现在严格不劣于少层数 + 白色垫底的方案，预览颜色趋于稳定",
            en: "Material-archive preview: the occasional 「10 layers look worse than 5 layers」 regression is fixed — higher layer counts are now guaranteed to be no worse than any smaller-k solution padded with white, so preview colour stays consistent as you raise the layer count",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-20",
    title: {
      zh: "Lumina Layers — 近三天更新速览",
      en: "Lumina Layers — What's new in the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "自定义配方可以加 LUT 里没有的颜色了：下拉直接选，导出的 3MF 会自动多一个对象带上这种颜色，切片那边不用自己改",
            en: "You can now add colours that aren't in the LUT to a custom recipe: pick them from the dropdown and the exported 3MF carries them as extra objects, so the slicer just works",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "打开自定义配方，下拉里能看到每种材料的真实颜色，不再是一堆灰方块",
            en: "Open the custom recipe dialog and the dropdown swatches show each material's actual colour instead of a row of grey placeholders",
          },
          {
            zh: '用耗材档案做的模型现在也能改自定义配方了，不会再弹 "没有预测引擎" 的提示',
            en: 'Models built from the material library now accept custom recipes too — the old "no predictive runtime" blocker is gone',
          },
          {
            zh: "打开配方时，每层的初始值就是这个色块实际在用的配方，而不是全白；只改一两层不会再把别的层覆盖掉",
            en: "When you open the recipe dialog, every layer starts with the colour it's actually using, not pure white — so tweaking one or two layers doesn't wipe the rest",
          },
          {
            zh: '点应用之后，分层预览会整屏刷新；不再出现 "只有改过的层亮起、其它层灰掉" 的情况',
            en: "Hitting apply now refreshes every layer in the preview, so you don't end up with only the edited layers showing colour and the rest looking greyed-out",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "耗材库里已经存好的条目，现在可以直接改名字和品牌，不用重新扫卡",
            en: "Already-saved entries in the material library can now be renamed (and have their brand changed) in place — no need to re-scan the card",
          },
          {
            zh: "品牌输入改成下拉：之前用过的品牌会自动列出来，想加新品牌也能直接打字",
            en: "Brand input is now a dropdown: it auto-lists brands you've used before, and you can still type a new one on the spot",
          },
          {
            zh: '提取完出的一堆 JSON、拟合摘要、Stage A 下载全收进一个 "详情" 按钮里，主面板干净多了',
            en: 'The JSON dumps, fit summary and Stage A download link now live behind a single "Details" button, keeping the main panel uncluttered',
          },
          {
            zh: "保存成功 / 失败的提示从主面板挪到右上角小浮层，几秒自动消失，不会再把面板挤乱",
            en: "Save success / failure messages moved to a small top-right toast that fades on its own, so they no longer push the rest of the panel around",
          },
        ],
      },
      {
        category: {
          zh: "校准 & 材料",
          en: "Calibration & Materials",
        },
        items: [
          {
            zh: "梯度卡校准的默认层高从 0.04 mm 改成 0.08 mm，跟大家平时打印的层高更接近；以前存好的档案保持原样，不会被动",
            en: "Default gradient-card layer height is now 0.08 mm (was 0.04 mm) to match the layer height most people actually print at; archives you saved earlier keep their original layer height",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "梯度卡提取或保存失败时，会告诉你具体是哪一步出问题（ZIP 格式不对、图片解码不出来、角点选少了、基底方向认不出来、会话过期、找不到目标档案等），不再甩一串英文报错",
            en: "When gradient-card extract / save fails, you now get a clear sentence about what went wrong (bad ZIP, undecodable image, wrong number of corner points, can't tell substrate orientation, expired session, target archive missing, …) instead of a raw English error",
          },
          {
            zh: '提交表单填错字段时，弹窗会直接点名哪个字段有问题；之前偶尔会被 "请求失败 status 422" 这种模糊提示盖住',
            en: 'When form fields are invalid, the dialog now names the offending field directly, instead of sometimes masking it behind a generic "request failed with status 422"',
          },
          {
            zh: '修了一个隐藏 bug：有些字段校验错误本来该返回 422，却被内部处理器弄成 500 显示成 "服务器崩了"，现在已经走正规流程',
            en: "Fixed a hidden bug where some field-validation errors (which should be 422) were turning into 500s that looked like server crashes; they now follow the normal path",
          },
          {
            zh: '耗材档案里的自定义配方应用不再卡在 "LUT/source file missing" 409，整套流程能走通',
            en: 'Applying a custom recipe on a material-archive model no longer gets stuck on "LUT/source file missing" (409) — the whole flow works end to end',
          },
          {
            zh: "扩层时的边界修正：模型外面原本该透明的地方保持透明，不会再多一圈白边；模型里面没改动的像素继续沿用背板材料，不会塌成空层",
            en: "When the layer count is extended: transparent background outside the model stays transparent (no more white ring), and untouched pixels inside the model keep their backing material (no more collapsed empty layers)",
          },
        ],
      },
    ],
  },
  {
    version: "2026-04-19",
    title: {
      zh: "Lumina Layers v2.0.0 — 近三天的大更新",
      en: "Lumina Layers v2.0.0 — Highlights from the past three days",
    },
    sections: [
      {
        category: { zh: "新功能", en: "New" },
        items: [
          {
            zh: "梯度卡收纳盒生成器上线：一键生成用于收纳梯度校准卡的分格打印盒模型，卡片按品牌 / 耗材分格存放不易乱",
            en: "Gradient-card storage box generator: print a slotted box that organises your calibration cards by brand and material",
          },
          {
            zh: "梯度色卡：打印一张梯度卡扫入，自动提取该耗材的色彩物理参数入库，单卷耗材即可独立完成校准",
            en: "Gradient card calibration: print one card, scan it back in, and the physical colour parameters for that single filament are extracted into the library",
          },
          {
            zh: "耗材库支持自定义组合：把已校准的耗材自由拼成多色打印配色方案；档案按品牌 / 耗材两级目录整理，支持批量导入导出 ZIP",
            en: "Material library now supports custom bundles: freely combine calibrated filaments into multi-colour palettes; archives are organised by brand / material and support bulk ZIP import / export",
          },
          {
            zh: "3MF 底板层高修改器（Bambu）：可独立控制底板层高",
            en: "Bambu 3MF base-plate layer-height editor: control the base plate's layer height independently",
          },
          {
            zh: "0.2 mm 喷嘴元数据方案：小喷嘴用户开箱即用",
            en: "0.2 mm nozzle metadata preset: works out of the box for fine-nozzle users",
          },
          {
            zh: "LUT 下拉框新增刷新按钮：切换或放入新的 LUT 后不用重启页面，点一下即可重新加载",
            en: "LUT dropdown gains a refresh button: no page reload needed after swapping in a new LUT",
          },
        ],
      },
      {
        category: { zh: "颜色工作站", en: "Color Workstation" },
        items: [
          {
            zh: "颜色替换后，鼠标悬停「分层颜色」现在会同步更新，不再显示替换前的旧颜色",
            en: "After a colour replacement, the hover inspector's per-layer colours stay in sync instead of showing stale pre-replacement values",
          },
          {
            zh: "调色板顶部工具栏重新分组：历史 / 选择模式 / 自由色 / 配方 / 悬停显示 各自独立卡片，一眼分清",
            en: "Palette toolbar is regrouped into tinted cards — history, selection mode, free colour, recipe, and hover display — so each group is easier to spot",
          },
          {
            zh: "自定义配方编辑器升级：每层带颜色色块，目标色支持直接改 hex / Lab 双向联动；应用过的配方进历史，再点一下就能复用；材料档案模式下还会按目标色推荐相近配方。",
            en: "Custom recipe editor upgrade: each layer now shows a colour swatch, the target colour can be edited via hex or Lab with two-way sync, applied recipes are saved as reusable history snapshots, and Material Archive mode suggests recipes that match the target colour.",
          },
          {
            zh: "耗材档案颜色匹配更稳：增加耗材时，原本匹配良好的参考色不容易再被带偏",
            en: "Material-archive colour matching is steadier: adding new filaments is less likely to throw off reference colours that were already matching well",
          },
        ],
      },
      {
        category: {
          zh: "提取器（校色卡）",
          en: "Extractor (Calibration Card)",
        },
        items: [
          {
            zh: "5 色扩展模式每一页的角点提示修正",
            en: "Fixed per-page corner-label hints for the 5-Color Extended mode",
          },
          {
            zh: "点「清除角点」会顺带重置预览，直接回到拾取状态",
            en: "‘Clear corners’ now also resets the extraction preview so you return to corner picking immediately",
          },
          {
            zh: "RYBWGK 默认槽位名保持正确（不再误显 CMYW）",
            en: "RYBWGK slot names now stay correct instead of occasionally falling back to CMYW",
          },
          {
            zh: "小屏下按钮不再溢出",
            en: "Buttons no longer overflow on narrow screens",
          },
          {
            zh: "新增角点数值微调面板：四个校准角点可直接输入数值精调，不用再对着图像反复点拾",
            en: "New corner fine-tune panel: type exact pixel values for each of the four calibration corners instead of repeatedly clicking on the image",
          },
        ],
      },
      {
        category: { zh: "校准 & 材料", en: "Calibration & Materials" },
        items: [
          {
            zh: "默认材料改为下拉选择，告别输错名",
            en: "Default material switched from free text to a curated dropdown — no more typos",
          },
          {
            zh: "默认色块间距 0.82 → 0.84 mm",
            en: "Default colour-cell gap changed from 0.82 mm to 0.84 mm",
          },
          {
            zh: "材料求解器缓存 + 更紧凑的材料选择器",
            en: "Material solver now caches exhaustive results, and the material picker UI is more compact",
          },
          {
            zh: "校色卡色块提取采样窗口收紧：降低相邻色块串色与边缘反锯齿污染，提取出来的参考色更干净",
            en: "Calibration-card cell sampling window is tighter: less bleed from neighbouring cells and edge anti-aliasing, producing cleaner reference colours",
          },
        ],
      },
      {
        category: { zh: "预览 & 交互", en: "Preview & Interaction" },
        items: [
          {
            zh: "滚轮缩放预览时不再连带滚动整页",
            en: "Wheel-zooming the preview no longer scrolls the whole page",
          },
          {
            zh: "Slider 范围拖动会自动吸附到步进",
            en: "Range sliders now snap to step increments when dragged",
          },
          {
            zh: "LUT 颜色网格提示文字乱码修复",
            en: "Fixed garbled text in the LUT colour-grid hints",
          },
          {
            zh: "2D 预览新增「按住查看原图」：长按按钮或按住键盘 Shift 键即可临时覆盖显示原始图片，松手自动回到生成效果",
            en: "2D preview ‘hold to view original’: press-and-hold the button or hold Shift to temporarily overlay the original upload; release to return to the generated view",
          },
          {
            zh: "2D 预览瘦身：移除打印床画布、网格与标尺，只保留核心画面，更清爽",
            en: "Slimmer 2D preview: bed canvas, grid, and rulers are removed, leaving only the core image",
          },
          {
            zh: "右键拖动平移预览时不再被浏览器菜单打断，和 3D 视图行为一致",
            en: "Right-drag panning no longer triggers the browser context menu — matches the 3D view's behaviour",
          },
          {
            zh: "下拉菜单宽度跟随触发器自适应，选项不多时也不会被错误判定为「下方空间不足」而翻到上方",
            en: "Dropdown menu width now follows its trigger, and short menus no longer flip upward when there is actually enough room below",
          },
          {
            zh: "3D 视图新增「性能」按钮：实时查看 FPS、显存占用、几何体 / 纹理数量和画布尺寸",
            en: "3D viewer gains a Diagnostics button: inspect live FPS, heap usage, geometry / texture counts, and canvas size",
          },
        ],
      },
      {
        category: { zh: "矢量化", en: "Vectorisation" },
        items: [
          {
            zh: "非五色单面 SVG 镜像修复",
            en: "Fixed single-side SVG mirroring for non-five-colour modes",
          },
          {
            zh: "矢量化发送到转换器流程回归覆盖",
            en: "Added regression coverage for the vectorise → converter hand-off flow",
          },
        ],
      },
      {
        category: { zh: "稳定性", en: "Stability" },
        items: [
          {
            zh: "渐变色卡材料句柄超时回收，减少资源泄漏",
            en: "Gradient-card material registry handles now expire on a timeout to reduce resource leaks",
          },
          {
            zh: "会话租约清理",
            en: "Stale session leases are cleaned up more reliably",
          },
          {
            zh: "Windows 11 启动器修复：系统移除 wmic 后进程清理失败的问题，现改用 Get-CimInstance 查询",
            en: "Windows 11 launcher fix: process cleanup now uses Get-CimInstance because wmic was removed from the OS",
          },
          {
            zh: "修复生成穷举缓存后点预览偶发 500：worker 读取预览尺寸的方式已修正",
            en: "Fixed an occasional 500 when previewing after generating the exhaustive cache: the worker's preview-size logging is now correct",
          },
        ],
      },
    ],
  },
];

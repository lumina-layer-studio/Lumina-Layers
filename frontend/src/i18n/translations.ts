/**
 * Lumina Studio - Translation Dictionary
 * Migrated from core/i18n.py TEXTS dictionary
 * Contains all zh/en translation key-value pairs
 */
import splashTranslations from '../../../electron/splash-text.json';
export const translations: Record<string, Record<"zh" | "en", string>> = {
  ...splashTranslations,
  common_close: { zh: "关闭", en: "Close" },
  cloud_library_update: { zh: "更新", en: "Update" },
  cloud_library_results: { zh: "匹配结果", en: "Matching results" },
  cloud_library_loading_index: { zh: "正在加载完整目录，搜索结果尚不完整…", en: "Loading the full catalog; search results are not complete yet…" },
  desktop_menu_about: { zh: "关于 Lumina Studio", en: "About Lumina Studio" },
  desktop_menu_settings: { zh: "设置…", en: "Settings…" },
  desktop_menu_services: { zh: "服务", en: "Services" },
  desktop_menu_hide: { zh: "隐藏 Lumina Studio", en: "Hide Lumina Studio" },
  desktop_menu_hideOthers: { zh: "隐藏其他", en: "Hide Others" },
  desktop_menu_unhide: { zh: "显示全部", en: "Show All" },
  desktop_menu_quit: { zh: "退出 Lumina Studio", en: "Quit Lumina Studio" },
  desktop_menu_file: { zh: "文件", en: "File" },
  desktop_menu_import: { zh: "导入图片 / SVG / 分享卡…", en: "Import image / SVG / share card…" },
  desktop_menu_export: { zh: "保存已生成文件…", en: "Save generated file…" },
  desktop_menu_close: { zh: "关闭窗口", en: "Close Window" },
  desktop_menu_edit: { zh: "编辑", en: "Edit" },
  desktop_menu_undo: { zh: "撤销文本编辑", en: "Undo Text Edit" },
  desktop_menu_redo: { zh: "重做文本编辑", en: "Redo Text Edit" },
  desktop_menu_cut: { zh: "剪切", en: "Cut" },
  desktop_menu_copy: { zh: "复制", en: "Copy" },
  desktop_menu_paste: { zh: "粘贴", en: "Paste" },
  desktop_menu_selectAll: { zh: "全选", en: "Select All" },
  desktop_menu_view: { zh: "显示", en: "View" },
  desktop_menu_zoomIn: { zh: "放大界面", en: "Zoom In" },
  desktop_menu_zoomOut: { zh: "缩小界面", en: "Zoom Out" },
  desktop_menu_resetZoom: { zh: "实际大小（100%）", en: "Actual Size (100%)" },
  desktop_menu_togglefullscreen: { zh: "切换全屏", en: "Toggle Full Screen" },
  desktop_menu_window: { zh: "窗口", en: "Window" },
  desktop_menu_minimize: { zh: "最小化", en: "Minimize" },
  desktop_menu_zoom: { zh: "缩放窗口", en: "Zoom Window" },
  desktop_menu_front: { zh: "前置全部窗口", en: "Bring All to Front" },
  desktop_menu_help: { zh: "帮助", en: "Help" },
  desktop_menu_docs: { zh: "Lumina Studio 使用文档", en: "Lumina Studio Documentation" },
  desktop_menu_report: { zh: "反馈问题…", en: "Report a Problem…" },
  conversion_preset_inline_label: { zh: "预设", en: "Preset" },
  conversion_preset_project: { zh: "当前项目参数", en: "Current project settings" },
  conversion_preset_invalid_name: { zh: "请输入 1–40 个字符的名称", en: "Enter a name with 1–40 characters" },
  conversion_preset_missing: { zh: "此预设已不存在，请重新选择", en: "This preset no longer exists. Please select another." },
  conversion_preset_last: { zh: "上次使用", en: "Last used" },
  conversion_preset_save: { zh: "保存为预设", en: "Save as preset" },
  conversion_preset_modified: { zh: "已修改", en: "Modified" },
  conversion_preset_update: { zh: "更新预设", en: "Update preset" },
  conversion_preset_dirty_hint: { zh: "本次修改不会覆盖原预设", en: "Changes do not overwrite the saved preset" },
  conversion_preset_title: { zh: "保存为参数预设", en: "Save parameter preset" },
  conversion_preset_name: { zh: "预设名称", en: "Preset name" },
  conversion_preset_name_hint: { zh: "例如：日常单面板画", en: "e.g. Everyday single-sided art" },
  conversion_preset_duplicate: { zh: "已有同名预设，请换一个名称", en: "A preset with this name already exists" },
  conversion_preset_long_edge: { zh: "长边", en: "Long edge" },
  conversion_preset_include: { zh: "保存内容", en: "Settings to save" },
  conversion_preset_scope: { zh: "尺寸记录长边；未勾选的设置在应用时保持当前值。", en: "Size records the long edge. Unchecked settings keep their current values when applying the preset." },
  conversion_preset_cancel: { zh: "取消", en: "Cancel" },
  conversion_preset_confirm: { zh: "保存预设", en: "Save preset" },
  conversion_preset_material: { zh: "耗材档案", en: "Material archive" },
  conversion_preset_lut: { zh: "经典 LUT", en: "Classic LUT" },
  conversion_preset_single: { zh: "单面", en: "Single-sided" },
  conversion_preset_double: { zh: "双面", en: "Double-sided" },
  conversion_preset_rename: { zh: "重命名当前预设", en: "Rename current preset" },
  conversion_preset_delete: { zh: "删除当前预设", en: "Delete current preset" },
  conversion_preset_delete_hint: { zh: "删除“{name}”？当前正在使用的参数会保留。", en: "Delete “{name}”? Your current parameters will be kept." },
  conversion_preset_layer_height: { zh: "层高", en: "Layer height" },
  conversion_preset_layers: { zh: "层", en: "layers" },
  conversion_preset_dynamic: { zh: "动态", en: "Dynamic" },
  conversion_preset_fixed: { zh: "固定", en: "Fixed" },
  conversion_preset_coating_on: { zh: "涂层开启", en: "Coating on" },
  conversion_preset_coating_off: { zh: "涂层关闭", en: "Coating off" },
  recipe_export_wait_edits: {
    zh: "编辑或选区仍在提交，请等待完成或同步编辑状态后再保存。",
    en: "An edit or selection is still being committed. Wait for it to finish or synchronize the editor before saving.",
  },
  recipe_editor_restore_unconfirmed: {
    zh: "尚未确认项目局部编辑的恢复结果，原项目数据已保留，请重新预览。",
    en: "The restored project edits could not be confirmed. Your project data is preserved; run preview again.",
  },
  native_material_edit_button: { zh: "耗材配置…", en: "Filament settings…" },
  native_material_edit_title: { zh: "耗材配置", en: "Filament settings" },
  native_material_close: { zh: "关闭", en: "Close" },
  native_material_edit_description: {
    zh: "为每种材料选择切片软件中的耗材预设和兼容打印板。保存后用于下次生成，不会立即生成文件。",
    en: "Choose a slicer filament preset for each material and a compatible build plate. These choices will be saved for the next generation without generating a file now.",
  },
  native_material_edit_cancel: { zh: "取消", en: "Cancel" },
  native_material_edit_save: { zh: "保存选择", en: "Save choices" },
  native_material_load_failed: { zh: "无法读取打印耗材预设，请重试。", en: "Could not load filament presets. Please retry." },
  native_material_rechecking: { zh: "正在检查耗材预设和打印板兼容性…", en: "Checking filament presets and build plate compatibility…" },
  native_material_recheck: { zh: "重新检查", en: "Check again" },
  native_material_recheck_failed: { zh: "未能重新检查耗材与打印板兼容性，草稿已保留，请重试。", en: "Could not recheck filament and build plate compatibility. Your draft is preserved; please retry." },
  native_material_template_managed: {
    zh: "当前导出使用导入的 3MF 模板，耗材预设由该模板管理。",
    en: "The imported 3MF template manages the filament presets for this export.",
  },
  native_material_dialog_title: { zh: "确认打印耗材", en: "Confirm print filaments" },
  native_material_dialog_description: {
    zh: "请为每种材料选择切片软件中的耗材预设和兼容打印板。确认后会继续生成。",
    en: "Choose a slicer filament preset for each material and a compatible build plate. Generation will continue after confirmation.",
  },
  native_material_build_plate: { zh: "兼容打印板", en: "Compatible build plate" },
  native_material_choose_plate: { zh: "选择打印板", en: "Choose a build plate" },
  native_material_profile: { zh: "切片软件耗材预设", en: "Slicer filament preset" },
  native_material_choose_profile: { zh: "请选择耗材预设", en: "Choose a filament preset" },
  native_material_automatic: { zh: "自动匹配：{profile}", en: "Automatic: {profile}" },
  native_material_automatic_option: { zh: "自动匹配", en: "Automatic" },
  native_material_selected: { zh: "已选择：{profile}", en: "Selected: {profile}" },
  native_material_cancel: { zh: "取消生成", en: "Cancel generation" },
  native_material_apply: { zh: "确认并继续生成", en: "Confirm and continue" },
  native_material_no_compatible_plate: {
    zh: "当前耗材预设组合没有共同兼容的打印板。请调整耗材预设或设备后重试。",
    en: "The current filament presets have no compatible build plate in common. Change the presets or machine and try again.",
  },
  native_material_ambiguous: {
    zh: "“{material}”对应多个 {type} 耗材预设，请选择实际使用的耗材。",
    en: "Several {type} presets match “{material}”. Choose the filament you will use.",
  },
  native_material_plate_incompatible: {
    zh: "“{material}”当前选择的耗材预设不支持“{plate}”，请更换预设或打印板。",
    en: "The selected filament preset for “{material}” does not support “{plate}”. Choose another preset or build plate.",
  },
  native_material_unavailable: {
    zh: "当前设备和喷嘴没有可用的 {type} 原生耗材预设（材料：“{material}”）。请调整材料或设备后重试。",
    en: "No native {type} filament preset is available for this machine and nozzle (material: “{material}”). Change the materials or machine and try again.",
  },
  native_material_selection_invalid: {
    zh: "“{material}”之前选择的耗材预设不适用于当前设备或打印板，请重新选择。",
    en: "The previous preset for “{material}” does not support the current machine or build plate. Choose it again.",
  },
  native_material_settings_incompatible: {
    zh: "这组耗材预设的共同设置无法组合。请选择可共同使用的原生预设，或导入切片软件中已配置好的 3MF 模板。",
    en: "These filament presets have incompatible shared settings. Choose compatible native presets or import a 3MF template configured in your slicer.",
  },
  file_save_saved: { zh: "文件已保存", en: "File saved" },
  file_save_download_started: { zh: "已开始下载", en: "Download started" },
  file_save_failed: { zh: "保存失败，请检查文件名、目标目录权限和可用空间后重试。", en: "Save failed. Check the filename, folder permissions and available space, then retry." },
  file_save_too_large: { zh: "文件超过 128 MiB 保存上限，请减小图像后重试。", en: "The file exceeds the 128 MiB save limit. Reduce the image size and retry." },
  // ==================== Application Title and Header ====================
  app_starting: { zh: "正在启动 Lumina", en: "Starting Lumina" },
  app_starting_detail: {
    zh: "正在等待本机服务就绪，首次启动可能需要更久。连接成功后会自动进入，无需刷新；如果一直停留在此处，请检查启动器或终端中的错误。",
    en: "Waiting for the local service. The first start may take longer. Lumina will open automatically when connected; no refresh is needed. If this screen remains, check the launcher or terminal for errors.",
  },
  app_subtitle: {
    zh: "多材料3D打印色彩系统 | v1.6.3",
    en: "Multi-Material 3D Print Color System | v1.6.3",
  },
  app_panel_controls: {
    zh: "面板控件",
    en: "Panel Controls",
  },
  header_menu_label: {
    zh: "更多选项",
    en: "More options",
  },
  credits_title: { zh: "致谢", en: "Credits" },
  credits_close: { zh: "返回关于", en: "Back to About" },
  about_close: { zh: "返回工作区", en: "Back to workspace" },
  about_name: { zh: "Lumina Studio 2", en: "Lumina Studio 2" },
  about_version: { zh: "版本 {version}", en: "Version {version}" },
  about_website: { zh: "官网", en: "Website" },
  about_github: { zh: "GitHub", en: "GitHub" },
  credits_loading: { zh: "正在加载名单…", en: "Loading credits…" },
  credits_load_error: { zh: "暂时无法加载名单", en: "The credits could not be loaded" },
  credits_retry: { zh: "重试", en: "Retry" },
  credits_cached: { zh: "已载入上次保存的名单", en: "Showing the last saved credits" },
  credits_search_placeholder: { zh: "寻找你的名字", en: "Find your name" },
  credits_clear_search: { zh: "清空搜索", en: "Clear search" },
  credits_search_results: { zh: "搜索结果", en: "Search results" },
  credits_search_no_results: { zh: "未找到匹配的姓名", en: "No matching names" },
  credits_sponsor_effects: { zh: "赞助特效", en: "Sponsor effects" },
  credits_motion: { zh: "动态效果", en: "Motion" },
  credits_canvas_label: { zh: "致谢气泡墙", en: "Credits bubble garden" },
  credits_source: { zh: "来自 {{source}}", en: "From {{source}}" },
  credits_found: { zh: "找到了：{{name}}", en: "Found: {{name}}" },
  // Name of the language the toggle switches to, written in that language.
  header_menu_language_target: {
    zh: "English",
    en: "中文",
  },
  header_menu_dark_mode: {
    zh: "深色模式",
    en: "Dark mode",
  },
  header_menu_repro_mode: {
    zh: "复现模式",
    en: "Reproduction mode",
  },
  header_menu_repro_mode_ticket: {
    zh: "复现模式 · {{ticket}}",
    en: "Reproduction mode · {{ticket}}",
  },
  bug_report_button_label: {
    zh: "反馈问题",
    en: "Report a bug",
  },
  bug_report_button_tooltip: {
    zh: "向开发者发送 bug 反馈",
    en: "Send a bug report to the developer",
  },
  error_ticket_prompt_title: { zh: "出现了一个错误", en: "Something went wrong" },
  error_ticket_prompt_body: {
    zh: "是否提交问题工单？工单会附带这条错误信息和最近的操作记录，帮助开发者定位原因。",
    en: "Submit a bug ticket? It includes this error and your recent actions to help developers find the cause.",
  },
  error_ticket_prompt_submit: { zh: "提交工单", en: "Submit ticket" },
  error_ticket_prompt_dismiss: { zh: "暂不", en: "Not now" },
  error_ticket_prompt_suppress: { zh: "本次不再提示", en: "Don't ask again this session" },
  error_ticket_prompt_close: { zh: "关闭提示", en: "Close prompt" },
  error_ticket_preset_intro: {
    zh: "请简单描述出错前你在做什么：",
    en: "Please briefly describe what you were doing before the error:",
  },
  error_ticket_preset_header: { zh: "—— 自动记录的错误信息 ——", en: "--- Auto-captured error ---" },
  error_ticket_preset_kind_label: { zh: "类型", en: "Type" },
  error_ticket_preset_kind_api: { zh: "接口错误", en: "API error" },
  error_ticket_preset_kind_client: { zh: "前端运行错误", en: "Frontend runtime error" },
  error_ticket_preset_path_label: { zh: "接口", en: "Endpoint" },
  error_ticket_preset_request_id_label: { zh: "请求 ID", en: "Request ID" },
  error_ticket_preset_message_label: { zh: "错误信息", en: "Message" },
  error_ticket_preset_time_label: { zh: "时间", en: "Time" },
  bug_report_modal_title: {
    zh: "反馈问题",
    en: "Report a bug",
  },
  bug_report_modal_description_label: {
    zh: "问题描述",
    en: "Describe the problem",
  },
  bug_report_modal_description_placeholder: {
    zh: "请详细描述发生了什么、你期望发生什么、复现步骤……",
    en: "What happened, what did you expect, and how can we reproduce it?",
  },
  bug_report_modal_email_label: {
    zh: "你的邮箱（可选，方便我们回复你）",
    en: "Your email (optional, so we can follow up)",
  },
  bug_report_modal_screenshot_label: {
    zh: "截图（可选）",
    en: "Screenshot (optional)",
  },
  bug_report_modal_screenshot_hint: {
    zh: "支持 PNG、JPG、WebP 或 GIF。",
    en: "PNG, JPG, WebP, or GIF.",
  },
  bug_report_modal_screenshot_attached_label: {
    zh: "已附加截图",
    en: "Attached screenshot",
  },
  bug_report_modal_screenshot_remove: {
    zh: "移除截图",
    en: "Remove screenshot",
  },
  bug_report_modal_context_disclosure: {
    zh: "已自动收集的信息（点击展开）",
    en: "Automatically collected info (click to expand)",
  },
  bug_report_modal_context_summary_heading: {
    zh: "上下文摘要",
    en: "Context summary",
  },
  bug_report_modal_context_summary_none: {
    zh: "当前没有可用的上下文信息。",
    en: "No context information available right now.",
  },
  bug_report_modal_context_active_tab: {
    zh: "标签",
    en: "Tab",
  },
  bug_report_modal_context_color_mode: {
    zh: "颜色模式",
    en: "Color mode",
  },
  bug_report_modal_context_lut: {
    zh: "LUT",
    en: "LUT",
  },
  bug_report_modal_context_recent_actions: {
    zh: "近期操作",
    en: "Recent actions",
  },
  bug_report_modal_context_recent_errors: {
    zh: "近期接口错误",
    en: "Recent API errors",
  },
  api_error_http_400: {
    zh: "请求数据无效，请检查填写的值。",
    en: "Request data is invalid. Please check the entered values.",
  },
  api_error_http_401: {
    zh: "继续操作前需要先完成登录或认证。",
    en: "Authentication is required before this action can continue.",
  },
  api_error_http_402: {
    zh: "此操作需要可用额度或付款状态后才能继续。",
    en: "This action requires an available quota or payment before it can continue.",
  },
  api_error_http_403: {
    zh: "你没有权限执行此操作。",
    en: "You do not have permission to perform this action.",
  },
  api_error_http_404: {
    zh: "请求的资源不存在或已过期。",
    en: "The requested resource was not found or has expired.",
  },
  api_error_http_405: {
    zh: "所选接口不支持此操作。",
    en: "This action is not supported by the selected API endpoint.",
  },
  api_error_http_408: {
    zh: "服务器未能在超时前完成请求。",
    en: "The request timed out before the server could finish.",
  },
  api_error_http_409: {
    zh: "请求与当前服务器状态冲突。",
    en: "The request conflicts with the current server state.",
  },
  api_error_http_413: {
    zh: "上传文件或请求内容过大。",
    en: "The uploaded file or request is too large.",
  },
  api_error_http_415: {
    zh: "服务器不支持此文件类型。",
    en: "This file type is not supported by the server.",
  },
  api_error_http_422: {
    zh: "请求缺少必填数据或包含无效值。",
    en: "The request is missing required data or contains invalid values.",
  },
  api_error_vector_native_requires_svg: {
    zh: "矢量建模模式仅支持 SVG 文件。请上传 SVG，或切换到“高保真”或“像素艺术”模式。",
    en: "Vector Native mode requires an SVG file. Upload an SVG, or switch to High-Fidelity or Pixel Art mode.",
  },
  api_error_source_image_unreadable: {
    zh: "无法读取这张图片。请确认文件未损坏，并重新导出为 PNG、JPEG 或 WebP 后再上传。",
    en: "The image could not be read. Check that the file is not damaged, then re-export it as PNG, JPEG, or WebP and upload it again.",
  },
  api_error_source_image_too_large: {
    zh: "图片像素尺寸过大，无法安全处理。请缩小图片分辨率后重新上传。",
    en: "The image dimensions are too large to process safely. Reduce the image resolution and upload it again.",
  },
  api_error_source_svg_invalid: {
    zh: "无法解析 SVG 文件。请在设计软件中重新导出有效的 SVG 后再上传。",
    en: "The SVG could not be parsed. Re-export a valid SVG from your design application and upload it again.",
  },
  api_error_source_svg_no_renderable_geometry: {
    zh: "SVG 中没有矢量模式可用的可见填充几何。请显示图稿，将描边和文字转换为填充路径，或切换到“高保真”模式。",
    en: "The SVG has no visible filled geometry supported by Vector mode. Make the artwork visible, convert strokes and text to filled paths, or switch to High-Fidelity mode.",
  },
  api_error_model_surface_empty_geometry: {
    zh: "模型文件不包含三角形几何体。请导出非空的 STL 或 OBJ 后重新上传。",
    en: "The model file does not contain triangle geometry. Export a non-empty STL or OBJ and upload it again.",
  },
  api_error_model_surface_invalid_file: {
    zh: "无法读取模型文件。请确认文件是有效的 STL 或 OBJ 后重新上传。",
    en: "The model file could not be read. Check that it is a valid STL or OBJ and upload it again.",
  },
  api_error_model_surface_mesh_not_watertight: {
    zh: "模型不是闭合实体，无法安全开槽。请先修复网格后重新上传。",
    en: "The model is not a closed solid and cannot be cut safely. Repair the mesh and upload it again.",
  },
  api_error_model_surface_mesh_not_volume: {
    zh: "模型实体方向无效。请修复网格法线后重新上传。",
    en: "The model has invalid solid orientation. Repair its normals and upload it again.",
  },
  api_error_model_surface_thickness_unknown: {
    zh: "无法确定所选表面的厚度。请选择其他表面或修复模型。",
    en: "The selected surface thickness could not be determined. Choose another surface or repair the model.",
  },
  api_error_model_surface_insufficient_thickness: {
    zh: "所选表面太薄，无法容纳当前颜色叠层。请减少层数、降低层高，或选择更厚的表面。",
    en: "The selected surface is too thin for the current colour stack. Use fewer layers, a smaller layer height, or a thicker surface.",
  },
  api_error_model_surface_boolean_failed: {
    zh: "模型覆面开槽计算失败。请提交问题反馈，并附上模型和图片。",
    en: "Model-surface pocket calculation failed. Submit a bug report with the model and artwork attached.",
  },
  api_error_http_429: {
    zh: "请求过于频繁，请稍后再试。",
    en: "Too many requests were sent. Please wait and try again.",
  },
  api_error_http_500: {
    zh: "服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。",
    en: "The server hit an internal error. Try again later, or submit feedback if it keeps happening.",
  },
  api_error_http_500_with_request_id: {
    zh: "服务器发生内部错误。请求 ID：{requestId}。",
    en: "The server hit an internal error. Request ID: {requestId}.",
  },
  api_error_http_502: {
    zh: "处理请求时上游依赖失败。",
    en: "An upstream dependency failed while handling this request.",
  },
  api_error_http_503: {
    zh: "服务器暂时不可用，请稍后再试。",
    en: "Server temporarily unavailable. Please try again later.",
  },
  api_error_http_504: {
    zh: "服务器等待依赖服务时超时。",
    en: "The server timed out waiting for a dependency.",
  },
  api_error_http_default: {
    zh: "接口请求失败。请重试；如果问题持续，请提交反馈。",
    en: "The API request failed. Try again, or submit feedback if it keeps happening.",
  },
  api_error_http_client_default: {
    zh: "请求未被服务器接受。请检查当前输入、权限或资源是否仍然可用。",
    en: "The server did not accept the request. Check the current input, permissions, or resource availability.",
  },
  api_error_http_server_default: {
    zh: "服务器处理请求时失败。请稍后重试；如果问题持续，请提交反馈。",
    en: "The server failed while handling the request. Try again later, or submit feedback if it keeps happening.",
  },
  api_error_no_response: {
    zh: "请求没有收到服务器响应。请确认 Lumina 后端已启动、网络连接正常，然后重试。",
    en: "The request did not receive a server response. Make sure the Lumina backend is running, check the network connection, and try again.",
  },
  api_error_with_request_id: {
    zh: "{message}请求 ID：{requestId}。",
    en: "{message} Request ID: {requestId}.",
  },
  bug_report_modal_privacy_note: {
    zh: "发送工单会上传完整诊断信息、错误记录、软件设置和工作流数据，以及已导入的原图、SVG、模型、批量文件、LUT、材料档案、生成文件和截图。数据会按原样保存并提交到 Lumina Studio 官方问题收集服务，用于复现和处理问题。",
    en: "Sending a ticket uploads complete diagnostics, error logs, settings and workflow data, together with imported images, SVGs, models, batch files, LUTs, material archives, generated files and screenshots. The data is saved and sent unchanged to the official Lumina Studio bug collection service to reproduce and resolve the issue.",
  },
  bug_report_modal_submit: {
    zh: "发送",
    en: "Send",
  },
  bug_report_modal_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  bug_report_toast_success: {
    zh: "已收到，谢谢。工单号：{{ticket}}",
    en: "Thanks, we got it. Ticket: {{ticket}}",
  },
  bug_report_toast_error: {
    zh: "提交失败，请稍后再试。",
    en: "Submission failed, please retry.",
  },
  bug_report_fallback_intro: {
    zh: "如果多次失败，请复制下面的反馈内容，通过邮箱或即时通讯发给开发者。",
    en: "If submission keeps failing, copy the report below and send it to the developer by email or chat.",
  },
  bug_report_fallback_copy: {
    zh: "复制反馈内容",
    en: "Copy report",
  },
  bug_report_fallback_copied: {
    zh: "反馈内容已复制",
    en: "Report copied",
  },
  bug_report_fallback_copy_failed: {
    zh: "自动复制失败，请手动选中文本复制。",
    en: "Automatic copy failed. Select the report text and copy it manually.",
  },
  bug_report_fallback_mailto: {
    zh: "用默认邮箱发送",
    en: "Send with default mail app",
  },
  bug_report_fallback_qq_mail: {
    zh: "打开 QQ 邮箱",
    en: "Open QQ Mail",
  },
  global_drop_import_aria: {
    zh: "拖拽导入文件",
    en: "Drag to import file",
  },
  global_drop_import_model: {
    zh: "导入模型",
    en: "Import model",
  },
  global_drop_import_image: {
    zh: "导入图片",
    en: "Import image",
  },
  global_drop_import_mixed: {
    zh: "导入模型和图片",
    en: "Import model and image",
  },
  global_drop_import_files: {
    zh: "导入文件",
    en: "Import files",
  },
  global_drop_import_release: {
    zh: "松开鼠标放入当前流程",
    en: "Release to add to this workflow",
  },
  model_surface_enable: {
    zh: "模型贴图",
    en: "Model texture",
  },
  model_surface_enable_hint: {
    zh: "将当前图片贴到上传模型的选中平面，最终导出保持原模型外形尺寸。",
    en: "Place the current artwork on a selected flat model surface while preserving the source model dimensions.",
  },
  model_surface_switch_on: {
    zh: "启用",
    en: "On",
  },
  model_surface_switch_off: {
    zh: "停用",
    en: "Off",
  },
  model_surface_upload_model: {
    zh: "上传模型",
    en: "Upload model",
  },
  model_surface_replace_model: {
    zh: "更换模型",
    en: "Replace model",
  },
  model_surface_drop_zone_upload: {
    zh: "拖拽 STL/OBJ 模型到此处或点击上传",
    en: "Drop an STL/OBJ model here or click to upload",
  },
  model_surface_drop_zone_replace: {
    zh: "拖拽 STL/OBJ 模型到此处或点击更换",
    en: "Drop an STL/OBJ model here or click to replace",
  },
  model_surface_drop_zone_hint: {
    zh: "支持 STL / OBJ；导入后在 3D 预览里旋转模型并选择贴图平面。",
    en: "Supports STL / OBJ. After import, rotate the model and pick the target face in the 3D preview.",
  },
  model_surface_clear_model: {
    zh: "清除",
    en: "Clear",
  },
  model_surface_model_file: {
    zh: "模型",
    en: "Model",
  },
  model_surface_model_size: {
    zh: "尺寸",
    en: "Size",
  },
  model_surface_status: {
    zh: "状态",
    en: "Status",
  },
  model_surface_status_uploading: {
    zh: "上传中",
    en: "Uploading",
  },
  model_surface_status_selecting: {
    zh: "选面中",
    en: "Selecting",
  },
  model_surface_status_analysis_failed: {
    zh: "模型分析失败",
    en: "Model analysis failed",
  },
  model_surface_status_selected: {
    zh: "已选面",
    en: "Surface selected",
  },
  model_surface_status_select_face: {
    zh: "右侧点选面",
    en: "Pick a face on the right",
  },
  model_surface_selected_size: {
    zh: "选面",
    en: "Surface",
  },
  model_surface_selected_faces: {
    zh: "面片",
    en: "Faces",
  },
  model_surface_fit: {
    zh: "自适应",
    en: "Fit",
  },
  model_surface_fit_hint: {
    zh: "让图片按选中面的边界自适应覆盖，模型尺寸和厚度保持不变。",
    en: "Fit the artwork to the selected surface bounds without changing model size or thickness.",
  },
  model_surface_mode_edge: {
    zh: "铺满",
    en: "Edge",
  },
  model_surface_mode_edge_hint: {
    zh: "让贴图覆盖到选中面的外轮廓和孔洞边缘。",
    en: "Extend the artwork to the selected surface outline and hole edges.",
  },
  model_surface_mode_inset: {
    zh: "内缩",
    en: "Inset",
  },
  model_surface_mode_inset_hint: {
    zh: "按设定距离从选中面的边缘向内退让。",
    en: "Keep the artwork inside the selected surface edges by the specified distance.",
  },
  model_surface_edge_mode: {
    zh: "贴图边界模式",
    en: "Texture edge mode",
  },
  model_surface_scale: {
    zh: "贴图缩放",
    en: "Artwork scale",
  },
  model_surface_offset_x: {
    zh: "水平偏移",
    en: "Offset X",
  },
  model_surface_offset_y: {
    zh: "垂直偏移",
    en: "Offset Y",
  },
  model_surface_rotation: {
    zh: "旋转",
    en: "Rotation",
  },
  model_surface_inset: {
    zh: "内缩距离",
    en: "Inset",
  },
  model_surface_inset_hint: {
    zh: "设置贴图与选中面边缘之间的退让距离，单位为毫米。",
    en: "Set the clearance between the artwork and selected surface edges in millimetres.",
  },
  model_surface_error_select_first: {
    zh: "请先上传模型并在右侧 3D 预览中选择一个平面。",
    en: "Upload a model and select a flat surface in the 3D preview first.",
  },
  model_surface_error_upload_first: {
    zh: "请先上传模型。",
    en: "Upload a model first.",
  },
  model_surface_upload_failed: {
    zh: "模型上传失败",
    en: "Model upload failed",
  },
  model_surface_select_failed: {
    zh: "选面失败",
    en: "Surface selection failed",
  },
  model_surface_viewer_loading: {
    zh: "模型加载中",
    en: "Loading model",
  },
  model_surface_loading_analysis: {
    zh: "模型上传与平面分析中",
    en: "Uploading and analyzing model surfaces",
  },
  model_surface_viewer_load_failed: {
    zh: "模型预览加载失败",
    en: "Model preview failed to load",
  },
  model_surface_tool_select: {
    zh: "选择平面",
    en: "Select surface",
  },
  model_surface_tool_select_hint: {
    zh: "在模型上点选要贴图的平面，默认按平面组选择并过滤小倒角。",
    en: "Pick the model face for artwork, using grouped planes by default and filtering small bevels.",
  },
  model_surface_tool_reselect: {
    zh: "重选面",
    en: "Reselect",
  },
  model_surface_tool_reselect_hint: {
    zh: "重新选择当前模型的贴图平面。",
    en: "Choose a different texture surface on the current model.",
  },
  model_surface_tool_orbit: {
    zh: "旋转模型",
    en: "Rotate model",
  },
  model_surface_tool_orbit_hint: {
    zh: "围绕模型中心旋转，用 X/Y/Z 数值或彩色旋转环调整朝向。",
    en: "Rotate around the model center with X/Y/Z inputs or colored rotation rings.",
  },
  model_surface_tool_move: {
    zh: "移动贴图",
    en: "Move artwork",
  },
  model_surface_tool_move_hint: {
    zh: "在选中平面内拖动贴图位置。",
    en: "Move the artwork across the selected surface.",
  },
  model_surface_tool_rotate: {
    zh: "旋转贴图",
    en: "Rotate artwork",
  },
  model_surface_tool_rotate_hint: {
    zh: "围绕选中平面中心旋转贴图。",
    en: "Rotate the artwork around the selected surface center.",
  },
  model_surface_tool_scale: {
    zh: "缩放贴图",
    en: "Scale artwork",
  },
  model_surface_tool_scale_hint: {
    zh: "缩放贴图覆盖范围，不改变模型厚度和外形尺寸。",
    en: "Scale the artwork coverage without changing model thickness or outer dimensions.",
  },
  model_surface_toolbar_group: {
    zh: "模型贴图工具组",
    en: "Model texture tool groups",
  },
  model_surface_toolbar_title: {
    zh: "贴图工具",
    en: "Texture tools",
  },
  model_surface_toolbar_drag: {
    zh: "拖动贴图工具条",
    en: "Drag texture toolbar",
  },
  model_surface_toolbar_drag_hint: {
    zh: "拖动后会吸附到视口边缘或角落，避免遮挡模型。",
    en: "Drag to snap the toolbar to a viewport edge or corner so it does not cover the model.",
  },
  model_surface_toolbar_collapse: {
    zh: "收起贴图工具条",
    en: "Collapse texture toolbar",
  },
  model_surface_toolbar_collapse_hint: {
    zh: "收起二级工具，只保留一个可拖动入口。",
    en: "Collapse the secondary tools and keep a small draggable entry.",
  },
  model_surface_toolbar_expand: {
    zh: "展开贴图工具条",
    en: "Expand texture toolbar",
  },
  model_surface_toolbar_expand_hint: {
    zh: "展开模型操作、贴图编辑和视图工具。",
    en: "Expand model, artwork, and view tools.",
  },
  model_surface_toolbar_secondary: {
    zh: "模型贴图二级工具栏",
    en: "Model texture secondary toolbar",
  },
  model_surface_toolbar_model: {
    zh: "模型操作",
    en: "Model",
  },
  model_surface_toolbar_artwork: {
    zh: "贴图编辑",
    en: "Artwork",
  },
  model_surface_toolbar_view: {
    zh: "视图",
    en: "View",
  },
  model_surface_view_reverse: {
    zh: "反向查看",
    en: "Reverse view",
  },
  model_surface_view_reverse_hint: {
    zh: "从选中平面的背面正向查看，不加入额外透视倾斜。",
    en: "View the selected surface from the opposite side without extra perspective tilt.",
  },
  model_surface_view_cube: {
    zh: "视图立方体",
    en: "View cube",
  },
  model_surface_view_cube_face_hint: {
    zh: "切换到对应正交视图，只移动相机，不改变模型旋转。",
    en: "Switch to the matching orthographic view. This moves the camera without changing model rotation.",
  },
  model_surface_view_cube_edge_hint: {
    zh: "切换到两面之间的斜向视图，只移动相机。",
    en: "Switch to the angled view between two faces. This only moves the camera.",
  },
  model_surface_view_cube_corner_hint: {
    zh: "切换到等轴测视图，只移动相机。",
    en: "Switch to an isometric view. This only moves the camera.",
  },
  model_surface_axis_gizmo: {
    zh: "坐标轴指示器",
    en: "Axis gizmo",
  },
  model_surface_view_default: {
    zh: "默认视图",
    en: "Default view",
  },
  model_surface_view_default_hint: {
    zh: "回到适合查看模型和热床的默认视角。",
    en: "Return to the default angle for viewing the model and build plate.",
  },
  model_surface_view_top: {
    zh: "顶部视图",
    en: "Top view",
  },
  model_surface_view_bottom: {
    zh: "底部视图",
    en: "Bottom view",
  },
  model_surface_view_front: {
    zh: "前面视图",
    en: "Front view",
  },
  model_surface_view_back: {
    zh: "后面视图",
    en: "Back view",
  },
  model_surface_view_left: {
    zh: "左面视图",
    en: "Left view",
  },
  model_surface_view_right: {
    zh: "右面视图",
    en: "Right view",
  },
  model_surface_view_edge_right_front: {
    zh: "右前视图",
    en: "Right front view",
  },
  model_surface_view_edge_left_front: {
    zh: "左前视图",
    en: "Left front view",
  },
  model_surface_view_edge_right_back: {
    zh: "右后视图",
    en: "Right back view",
  },
  model_surface_view_edge_left_back: {
    zh: "左后视图",
    en: "Left back view",
  },
  model_surface_view_edge_right_top: {
    zh: "右上视图",
    en: "Right top view",
  },
  model_surface_view_edge_right_bottom: {
    zh: "右下视图",
    en: "Right bottom view",
  },
  model_surface_view_edge_left_top: {
    zh: "左上视图",
    en: "Left top view",
  },
  model_surface_view_edge_left_bottom: {
    zh: "左下视图",
    en: "Left bottom view",
  },
  model_surface_view_edge_front_top: {
    zh: "前上视图",
    en: "Front top view",
  },
  model_surface_view_edge_front_bottom: {
    zh: "前下视图",
    en: "Front bottom view",
  },
  model_surface_view_edge_back_top: {
    zh: "后上视图",
    en: "Back top view",
  },
  model_surface_view_edge_back_bottom: {
    zh: "后下视图",
    en: "Back bottom view",
  },
  model_surface_view_corner_right_front_top: {
    zh: "右前上等轴测视图",
    en: "Right front top isometric view",
  },
  model_surface_view_corner_left_front_top: {
    zh: "左前上等轴测视图",
    en: "Left front top isometric view",
  },
  model_surface_view_corner_right_back_top: {
    zh: "右后上等轴测视图",
    en: "Right back top isometric view",
  },
  model_surface_view_corner_left_back_top: {
    zh: "左后上等轴测视图",
    en: "Left back top isometric view",
  },
  model_surface_view_corner_right_front_bottom: {
    zh: "右前下等轴测视图",
    en: "Right front bottom isometric view",
  },
  model_surface_view_corner_left_front_bottom: {
    zh: "左前下等轴测视图",
    en: "Left front bottom isometric view",
  },
  model_surface_view_corner_right_back_bottom: {
    zh: "右后下等轴测视图",
    en: "Right back bottom isometric view",
  },
  model_surface_view_corner_left_back_bottom: {
    zh: "左后下等轴测视图",
    en: "Left back bottom isometric view",
  },
  model_surface_face_top: {
    zh: "顶部",
    en: "Top",
  },
  model_surface_face_bottom: {
    zh: "底部",
    en: "Bottom",
  },
  model_surface_face_front: {
    zh: "前面",
    en: "Front",
  },
  model_surface_face_back: {
    zh: "后面",
    en: "Back",
  },
  model_surface_face_left: {
    zh: "左面",
    en: "Left",
  },
  model_surface_face_right: {
    zh: "右面",
    en: "Right",
  },
  model_surface_fit_view: {
    zh: "适配视图",
    en: "Fit view",
  },
  model_surface_fit_view_hint: {
    zh: "让相机适配当前模型或选中区域。",
    en: "Fit the camera to the current model or selected area.",
  },
  model_surface_display_options: {
    zh: "显示选项",
    en: "Display options",
  },
  model_surface_display_navigator: {
    zh: "3D 导航器",
    en: "3D navigator",
  },
  model_surface_display_navigator_hint: {
    zh: "显示或隐藏左下角视图立方体和导航控件。",
    en: "Show or hide the lower-left view cube and navigation controls.",
  },
  model_surface_display_zoom: {
    zh: "缩放按钮",
    en: "Zoom button",
  },
  model_surface_display_zoom_hint: {
    zh: "显示或隐藏适配视图按钮。",
    en: "Show or hide the fit-view button.",
  },
  model_surface_display_axes: {
    zh: "坐标轴",
    en: "Axes",
  },
  model_surface_display_axes_hint: {
    zh: "显示或隐藏场景坐标轴指示。",
    en: "Show or hide the scene axis indicator.",
  },
  model_surface_display_grid: {
    zh: "网格线",
    en: "Grid",
  },
  model_surface_display_grid_hint: {
    zh: "显示或隐藏热床网格线。",
    en: "Show or hide the build-plate grid.",
  },
  model_surface_display_labels: {
    zh: "标签",
    en: "Labels",
  },
  model_surface_display_labels_hint: {
    zh: "显示或隐藏视图立方体和坐标轴标签。",
    en: "Show or hide view cube and axis labels.",
  },
  model_surface_rotate_axis_x: {
    zh: "X 轴旋转",
    en: "Rotate around X",
  },
  model_surface_rotate_axis_y: {
    zh: "Y 轴旋转",
    en: "Rotate around Y",
  },
  model_surface_rotate_axis_z: {
    zh: "Z 轴旋转",
    en: "Rotate around Z",
  },
  model_surface_rotation_x: {
    zh: "X 角度",
    en: "X angle",
  },
  model_surface_rotation_y: {
    zh: "Y 角度",
    en: "Y angle",
  },
  model_surface_rotation_z: {
    zh: "Z 角度",
    en: "Z angle",
  },
  model_surface_world_coordinates: {
    zh: "世界坐标",
    en: "World coordinates",
  },
  model_surface_rotation_panel_drag: {
    zh: "拖动旋转窗口",
    en: "Drag rotation panel",
  },
  model_surface_rotation_panel_drag_hint: {
    zh: "拖动后会吸附到视口边缘或角落，避开模型和贴图。",
    en: "Drag to snap the rotation panel to a viewport edge or corner, away from the model and artwork.",
  },
  model_surface_rotation_relative: {
    zh: "旋转（相对）",
    en: "Rotate (relative)",
  },
  model_surface_rotation_absolute: {
    zh: "旋转（绝对）",
    en: "Rotate (absolute)",
  },
  model_surface_rotation_relative_input_hint: {
    zh: "输入本次相对增量，适合临时微调当前模型朝向。",
    en: "Enter a relative delta for this edit, useful for fine-tuning the current model orientation.",
  },
  model_surface_rotation_absolute_input_hint: {
    zh: "输入模型绕对应轴的绝对角度，数值会直接更新 3D 模型朝向。",
    en: "Enter the model's absolute angle around the selected axis; the 3D model updates directly.",
  },
  model_surface_rotation_relative_x: {
    zh: "X 相对旋转",
    en: "X relative rotation",
  },
  model_surface_rotation_relative_y: {
    zh: "Y 相对旋转",
    en: "Y relative rotation",
  },
  model_surface_rotation_relative_z: {
    zh: "Z 相对旋转",
    en: "Z relative rotation",
  },
  model_surface_rotation_absolute_x: {
    zh: "X 绝对旋转",
    en: "X absolute rotation",
  },
  model_surface_rotation_absolute_y: {
    zh: "Y 绝对旋转",
    en: "Y absolute rotation",
  },
  model_surface_rotation_absolute_z: {
    zh: "Z 绝对旋转",
    en: "Z absolute rotation",
  },
  model_surface_rotation_angle_readout: {
    zh: "旋转角度读数",
    en: "Rotation angle readout",
  },
  model_surface_rotate_90: {
    zh: "90°",
    en: "90°",
  },
  model_surface_rotation_reset: {
    zh: "重置旋转",
    en: "Reset rotation",
  },
  model_surface_rotation_reset_relative: {
    zh: "回到打开时",
    en: "Reset to open",
  },
  model_surface_rotation_reset_relative_hint: {
    zh: "恢复到打开旋转窗口时的模型角度。",
    en: "Restore the model angle from when this rotation panel was opened.",
  },
  model_surface_rotation_reset_zero: {
    zh: "归零",
    en: "Reset to zero",
  },
  model_surface_rotation_reset_zero_hint: {
    zh: "清除所有模型旋转，让模型回到零度朝向。",
    en: "Clear all model rotation and return the model to zero-degree orientation.",
  },
  model_surface_rotation_done: {
    zh: "完成",
    en: "Done",
  },
  model_surface_rotation_done_hint: {
    zh: "关闭旋转窗口并保留当前模型朝向。",
    en: "Close the rotation panel and keep the current model orientation.",
  },
  model_surface_rotation_quick: {
    zh: "快捷旋转",
    en: "Quick rotate",
  },
  model_surface_rotation_quick_hint: {
    zh: "按 90° 增量快速旋转模型，适合像切片软件一样快速摆正朝向。",
    en: "Rotate the model in 90° increments for slicer-style quick orientation changes.",
  },
  model_surface_rotation_step_90: {
    zh: "+90°",
    en: "+90°",
  },
  model_surface_rotation_step_minus_90: {
    zh: "-90°",
    en: "-90°",
  },
  model_surface_rotation_quick_x_positive: {
    zh: "X 快速旋转 +90°",
    en: "Quick rotate X +90°",
  },
  model_surface_rotation_quick_x_negative: {
    zh: "X 快速旋转 -90°",
    en: "Quick rotate X -90°",
  },
  model_surface_rotation_quick_y_positive: {
    zh: "Y 快速旋转 +90°",
    en: "Quick rotate Y +90°",
  },
  model_surface_rotation_quick_y_negative: {
    zh: "Y 快速旋转 -90°",
    en: "Quick rotate Y -90°",
  },
  model_surface_rotation_quick_z_positive: {
    zh: "Z 快速旋转 +90°",
    en: "Quick rotate Z +90°",
  },
  model_surface_rotation_quick_z_negative: {
    zh: "Z 快速旋转 -90°",
    en: "Quick rotate Z -90°",
  },
  model_surface_artwork_rotation_panel: {
    zh: "贴图旋转",
    en: "Artwork rotation",
  },
  model_surface_artwork_rotation_relative: {
    zh: "贴图相对旋转",
    en: "Artwork relative rotation",
  },
  model_surface_artwork_rotation_angle: {
    zh: "贴图旋转角度",
    en: "Artwork rotation angle",
  },
  model_surface_artwork_rotation_relative_hint: {
    zh: "输入相对变化量，正数顺时针、负数逆时针。",
    en: "Enter a relative delta; positive rotates clockwise and negative counterclockwise.",
  },
  model_surface_artwork_rotation_angle_hint: {
    zh: "输入贴图在所选平面内的绝对旋转角度。",
    en: "Enter the artwork's absolute rotation angle within the selected plane.",
  },
  model_surface_artwork_rotation_quick_hint: {
    zh: "按 90° 增量快速旋转贴图。",
    en: "Rotate the artwork in 90° increments.",
  },
  model_surface_artwork_rotation_minus_90: {
    zh: "贴图逆时针旋转 90°",
    en: "Rotate artwork 90° counterclockwise",
  },
  model_surface_artwork_rotation_plus_90: {
    zh: "贴图顺时针旋转 90°",
    en: "Rotate artwork 90° clockwise",
  },
  model_surface_artwork_rotation_reset_open: {
    zh: "回到打开时",
    en: "Reset to open",
  },
  model_surface_artwork_rotation_reset_open_hint: {
    zh: "恢复到打开贴图旋转工具时的角度。",
    en: "Restore the artwork angle from when the rotation tool was opened.",
  },
  model_surface_artwork_rotation_reset_zero: {
    zh: "贴图旋转归零",
    en: "Reset artwork rotation",
  },
  model_surface_artwork_rotation_reset_zero_hint: {
    zh: "清除贴图旋转，让图片回到零度。",
    en: "Clear artwork rotation and return the image to zero degrees.",
  },
  model_surface_artwork_rotation_done: {
    zh: "完成贴图旋转",
    en: "Finish artwork rotation",
  },
  model_surface_artwork_rotation_done_hint: {
    zh: "关闭旋转辅助并保留当前贴图角度。",
    en: "Close the rotation aids and keep the current artwork angle.",
  },
  model_surface_candidate_select: {
    zh: "选择候选平面",
    en: "Select candidate surface",
  },
  model_surface_candidate_readout: {
    zh: "候选平面读数",
    en: "Candidate surface readout",
  },
  model_surface_candidate_hover: {
    zh: "候选平面",
    en: "Candidate surface",
  },
  model_surface_selection_panel: {
    zh: "选择贴图平面",
    en: "Select texture surface",
  },
  model_surface_selection_mode: {
    zh: "模式",
    en: "Mode",
  },
  model_surface_selection_mode_grouped: {
    zh: "平面组",
    en: "Plane groups",
  },
  model_surface_selection_mode_triangle: {
    zh: "三角面",
    en: "Triangular facet",
  },
  model_surface_selection_mode_grouped_action: {
    zh: "选择平面组模式",
    en: "Select plane group mode",
  },
  model_surface_selection_mode_grouped_hint: {
    zh: "把共面的三角面作为一个平面组选择，适合洞洞板这种平面模型。",
    en: "Select coplanar triangles as one plane group, which fits flat pegboard-style models.",
  },
  model_surface_selection_mode_triangle_action: {
    zh: "选择三角面模式",
    en: "Select triangular facet mode",
  },
  model_surface_selection_mode_triangle_hint: {
    zh: "按单个三角面选择，用于检查细小面片或特殊模型。",
    en: "Select individual triangles for inspecting tiny facets or unusual models.",
  },
  model_surface_selection_candidate_unit: {
    zh: "候选平面",
    en: "candidate surfaces",
  },
  model_surface_selection_bevel_filtered: {
    zh: "已过滤小倒角",
    en: "small bevels filtered",
  },
  model_surface_selected_panel: {
    zh: "已选贴图平面",
    en: "Texture surface selected",
  },
  model_surface_selected_short: {
    zh: "已选",
    en: "Selected",
  },
  model_surface_selected_ready: {
    zh: "贴图可调整",
    en: "Artwork adjustable",
  },
  model_surface_artwork_readout: {
    zh: "贴图位置读数",
    en: "Artwork placement readout",
  },
  model_surface_artwork_readout_offset: {
    zh: "偏移",
    en: "Offset",
  },
  model_surface_artwork_readout_rotation: {
    zh: "旋转",
    en: "Rotation",
  },
  model_surface_artwork_readout_scale: {
    zh: "缩放",
    en: "Scale",
  },
  model_surface_selected_waiting_artwork: {
    zh: "等待图片",
    en: "Waiting for artwork",
  },
  model_surface_selected_tools: {
    zh: "移动 / 旋转 / 缩放",
    en: "Move / rotate / scale",
  },
  model_surface_selected_upload_hint: {
    zh: "上传图片后可调整贴图",
    en: "Upload artwork to adjust placement",
  },
  model_surface_edit_overlay: {
    zh: "继续调整贴图",
    en: "Adjust texture",
  },
  model_surface_adjust_in_viewer: {
    zh: "请在右侧 3D 预览中旋转模型、选择或重选面；选好后再移动、旋转或缩放贴图。",
    en: "Rotate the model and select or reselect a surface in the 3D preview, then move, rotate, or scale the artwork.",
  },
  bug_report_toast_saved_locally: {
    zh: "报告已保存在本机。工单号：{{ticket}}",
    en: "The report was saved on this device. Ticket: {{ticket}}",
  },
  bug_report_upload_pending: {
    zh: "正在上传到官方问题收集服务，可以直接关闭此对话框，上传会在后台继续。",
    en: "Uploading to the official bug collection service. You can close this dialog; the upload continues in the background.",
  },
  bug_report_upload_pending_slow: {
    zh: "上传比平时慢，仍在后台继续。可以关闭对话框，稍后用工单号联系开发者确认。",
    en: "The upload is slower than usual and continues in the background. You can close this dialog and quote the ticket id to the developers later.",
  },
  bug_report_upload_submitted: {
    zh: "已上传到官方问题收集服务，开发者会根据工单号跟进。",
    en: "Uploaded to the official bug collection service. The developers will follow up using the ticket id.",
  },
  bug_report_upload_failed: {
    zh: "上传到官方问题收集服务失败，报告仍保存在本机。可以稍后重试，或用下面的方式手动发送。",
    en: "Uploading to the official bug collection service failed. The report is still saved on this device; retry later or send it manually below.",
  },
  bug_report_upload_disabled: {
    zh: "本机已关闭反馈上传，报告只保存在本机。请用下面的方式手动发送。",
    en: "Report uploads are turned off on this installation, so the report stays on this device. Send it manually below.",
  },
  bug_report_upload_held_back: {
    zh: "以下文件太大或格式不支持，未上传，只保存在本机：{files}",
    en: "These files were too large or unsupported and stay only on this device: {files}",
  },
  bug_report_upload_retry: {
    zh: "重试上传",
    en: "Retry upload",
  },
  bug_report_collection_incomplete: {
    zh: "资料采集不完整：部分源文件或诊断数据未能保存。请检查本机文件和可用磁盘空间，再重新采集提交。",
    en: "Data collection is incomplete: some source files or diagnostics could not be saved. Check the local files and available disk space, then collect and submit again.",
  },
  bug_report_recapture: {
    zh: "重新采集并提交全部资料",
    en: "Collect and submit all data again",
  },
  bug_report_upload_retrying: {
    zh: "正在重试…",
    en: "Retrying…",
  },
  bug_report_upload_retry_failed: {
    zh: "仍然失败，请稍后再试。",
    en: "Still failing. Please try again later.",
  },
  bug_report_success_ticket_label: {
    zh: "工单号",
    en: "Ticket ID",
  },
  bug_report_success_copy: {
    zh: "复制",
    en: "Copy",
  },
  bug_report_success_copied: {
    zh: "已复制",
    en: "Copied",
  },
  bug_report_success_copy_failed: {
    zh: "自动复制失败，请手动选中工单号复制。",
    en: "Automatic copy failed. Select the ticket id and copy it manually.",
  },
  bug_report_success_original_attached: {
    zh: "转换原图已按原始字节随工单保存。",
    en: "The converter source image was saved byte-for-byte with the ticket.",
  },
  bug_report_success_original_session_fallback: {
    zh: "转换原图已从当前转换会话恢复并随工单保存。",
    en: "The converter source image was recovered from the current session and saved with the ticket.",
  },
  bug_report_success_original_not_applicable: {
    zh: "本次没有单独的转换原图；其他已上传源文件会随工单保存。",
    en: "There is no separate converter image; other uploaded source files are saved with the report.",
  },
  bug_report_success_original_too_large: {
    zh: "旧版本客户端因大小限制省略了原图；请更新后重新提交以附带完整源文件。",
    en: "An older client omitted the original image because of its size limit. Update and resubmit to include every source file.",
  },
  bug_report_success_original_failed: {
    zh: "原图保存失败；问题描述和其他诊断信息已提交。",
    en: "The source image could not be saved; the description and other diagnostics were submitted.",
  },
  bug_report_success_dump_path_label: {
    zh: "本地路径",
    en: "Local path",
  },
  bug_report_success_close: {
    zh: "完成",
    en: "Done",
  },
  bug_report_validation_description_required: {
    zh: "请填写问题描述",
    en: "Please describe the problem",
  },
  bug_report_validation_description_truncated: {
    zh: "问题描述已截断到 10000 个字符。",
    en: "The description was truncated to 10,000 characters.",
  },
  bug_report_validation_screenshot_type: {
    zh: "请选择图片文件作为截图。",
    en: "Choose an image file for the screenshot.",
  },
  bug_report_validation_screenshot_size: {
    zh: "截图不能超过 5 MB。",
    en: "Screenshot must be no larger than 5 MB.",
  },
  bug_report_validation_screenshot_read_failed: {
    zh: "读取截图失败，请重试。",
    en: "Could not read the screenshot. Please try again.",
  },
  lang_btn_zh: {
    zh: "🌐 中文",
    en: "🌐 中文",
  },
  lang_btn_en: {
    zh: "🌐 English",
    en: "🌐 English",
  },

  // ==================== Stats Bar ====================
  stats_calibrations: {
    zh: "校准板",
    en: "Calibrations",
  },
  stats_extractions: {
    zh: "颜色提取",
    en: "Extractions",
  },
  stats_conversions: {
    zh: "模型转换",
    en: "Conversions",
  },

  // ==================== Tab Titles ====================
  tab_about: {
    zh: "ℹ️ 关于",
    en: "ℹ️ About",
  },

  // ==================== Converter Tab ====================
  conv_title: {
    zh: "### 第一步：转换图像",
    en: "### Step 1: Convert Image",
  },
  conv_desc: {
    zh: "**两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）\n\n**流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成",
    en: "**Two Modeling Modes**: High-Fidelity (RLE seamless) and Pixel Art (blocky style)\n\n**Workflow**: Upload LUT & Image → Select Mode → Adjust Color Detail → Preview → Generate",
  },
  conv_lut_title: {
    zh: "**校准数据**",
    en: "**Calibration Data**",
  },
  conv_lut_dropdown: {
    zh: "选择预设",
    en: "Select Preset",
  },
  conv_lut_info: {
    zh: "从预设库中选择LUT",
    en: "Select from library",
  },
  conv_image_label: {
    zh: "输入图像",
    en: "Input Image",
  },
  crop_title: {
    zh: "图片裁剪",
    en: "Image Crop",
  },
  crop_original_size: {
    zh: "原图尺寸",
    en: "Original size",
  },
  crop_selection_size: {
    zh: "选区尺寸",
    en: "Selection size",
  },
  crop_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  crop_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  crop_width: {
    zh: "宽度",
    en: "Width",
  },
  crop_height: {
    zh: "高度",
    en: "Height",
  },
  crop_use_original: {
    zh: "使用原图",
    en: "Use original",
  },
  crop_confirm: {
    zh: "确认裁剪",
    en: "Confirm crop",
  },
  conv_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  conv_color_mode_cmyw: {
    zh: "CMYW (青/品红/黄)",
    en: "CMYW (Cyan/Magenta/Yellow)",
  },
  conv_color_mode_rybw: {
    zh: "RYBW (红/黄/蓝)",
    en: "RYBW (Red/Yellow/Blue)",
  },
  conv_structure: {
    zh: "结构",
    en: "Structure",
  },
  conv_structure_double: {
    zh: "双面",
    en: "Double-sided",
  },
  conv_structure_single: {
    zh: "单面",
    en: "Single-sided",
  },
  conv_modeling_mode_info: {
    zh: "高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学 | SVG模式：矢量直接转换",
    en: "High-Fidelity: RLE seamless, watertight | Pixel Art: Classic blocky aesthetic | SVG Mode: Direct vector conversion",
  },
  conv_quantize_info: {
    zh: "颜色数量越多细节越丰富，但生成越慢",
    en: "Higher = More detail, Slower",
  },
  conv_auto_color_btn: {
    zh: "自动计算",
    en: "Auto Detect",
  },
  conv_auto_color_calculating: {
    zh: "⏳ 计算中...",
    en: "⏳ Calculating...",
  },
  conv_width: {
    zh: "宽度 (mm)",
    en: "Width (mm)",
  },
  conv_height: {
    zh: "高度 (mm)",
    en: "Height (mm)",
  },
  conv_thickness: {
    zh: "背板 (mm)",
    en: "Backing (mm)",
  },
  conv_backing_color: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  converter_preview_2d_alt: {
    zh: "2D 预览图",
    en: "2D preview image",
  },
  canvas_preview_load_failed: {
    zh: "预览资源加载失败。请重新生成预览或刷新后再试。",
    en: "Preview resource failed to load. Regenerate the preview or refresh and try again.",
  },
  conv_palette_step1: {
    zh: "### 1. 原图颜色（点击预览图）",
    en: "### 1. Original Color (Click Preview)",
  },
  conv_palette_step2: {
    zh: "### 2. 替换为（点击色块）",
    en: "### 2. Replace With (Click Swatch)",
  },
  conv_palette_selected_label: {
    zh: "当前选中",
    en: "Selected",
  },
  conv_palette_replace_label: {
    zh: "将替换为",
    en: "Replace With",
  },
  conv_palette_lut_loading: {
    zh: "⏳ 正在加载 LUT 颜色...",
    en: "⏳ Loading LUT colors...",
  },
  conv_palette_replacements_placeholder: {
    zh: "生成预览后显示替换列表",
    en: "Generate preview to see replacements",
  },
  conv_palette_replacements_label: {
    zh: "已生效的替换",
    en: "Applied Replacements",
  },
  conv_palette_undo_btn: {
    zh: "↩️ 撤销",
    en: "↩️ Undo",
  },
  conv_palette_user_replacements_title: {
    zh: "用户替换",
    en: "User Replacements",
  },
  conv_palette_auto_pairs_title: {
    zh: "自动配准",
    en: "Auto Pairs",
  },
  conv_palette_delete_selected_btn: {
    zh: "删除选中",
    en: "Delete Selected",
  },
  conv_palette_user_empty: {
    zh: "暂无替换",
    en: "No replacements",
  },
  conv_palette_auto_empty: {
    zh: "暂无自动配准",
    en: "No auto pairs",
  },
  // ==================== Loop / Outline / Cloisonne / Coating ====================
  conv_loop_enable: {
    zh: "启用挂孔",
    en: "Enable Loop",
  },
  conv_loop_width: {
    zh: "宽度(mm)",
    en: "Width(mm)",
  },
  conv_loop_length: {
    zh: "长度(mm)",
    en: "Length(mm)",
  },
  conv_loop_hole: {
    zh: "孔径(mm)",
    en: "Hole(mm)",
  },
  conv_loop_angle: {
    zh: "旋转角度°",
    en: "Rotation°",
  },
  conv_loop_info: {
    zh: "挂孔位置",
    en: "Loop Position",
  },
  conv_outline_section: {
    zh: "##### 外轮廓设置",
    en: "##### Outline Settings",
  },
  conv_outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  conv_outline_width: {
    zh: "外轮廓厚度(mm)",
    en: "Outline Width(mm)",
  },
  conv_cloisonne_section: {
    zh: "##### 掐丝珐琅特效",
    en: "##### Cloisonné Effect",
  },
  conv_cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  conv_cloisonne_wire_width: {
    zh: "丝线宽度(mm)",
    en: "Wire Width(mm)",
  },
  conv_cloisonne_wire_height: {
    zh: "丝线高度(mm)",
    en: "Wire Height(mm)",
  },
  conv_cloisonne_wire_color: {
    zh: "丝线颜色槽位",
    en: "Wire Color Slot",
  },
  conv_free_color_btn: {
    zh: "标记为自由色",
    en: "Mark as Free Color",
  },
  conv_free_color_clear_btn: {
    zh: "清除自由色",
    en: "Clear Free Colors",
  },
  conv_free_color_label: {
    zh: "自由色",
    en: "Free Colors",
  },
  conv_coating_section: {
    zh: "##### 透明镀层",
    en: "##### Transparent Coating",
  },
  conv_coating_enable: {
    zh: "启用透明镀层",
    en: "Enable Transparent Coating",
  },
  conv_coating_height: {
    zh: "透明镀层厚度(mm)",
    en: "Transparent Coating Height(mm)",
  },
  conv_status: {
    zh: "状态",
    en: "Status",
  },
  conv_download_file: {
    zh: "3MF文件",
    en: "3MF File",
  },

  // ==================== Calibration Tab ====================
  cal_title: {
    zh: "生成校准板",
    en: "Generate Calibration Board",
  },
  cal_desc: {
    zh: "生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。",
    en: "Generate a 1024-color calibration board to extract your printer's actual color data.",
  },
  cal_params: {
    zh: "参数",
    en: "Parameters",
  },
  cal_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  cal_block_size: {
    zh: "色块尺寸 (mm)",
    en: "Block Size (mm)",
  },
  cal_gap: {
    zh: "间隙 (mm)",
    en: "Gap (mm)",
  },
  cal_generate_btn: {
    zh: "生成",
    en: "Generate",
  },
  cal_status: {
    zh: "状态",
    en: "Status",
  },
  cal_preview: {
    zh: "预览",
    en: "Preview",
  },
  cal_download: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },

  // ==================== Color Extractor Tab ====================
  ext_title: {
    zh: "提取颜色数据",
    en: "Extract Color Data",
  },
  ext_desc: {
    zh: "拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。",
    en: "Take a photo of your printed calibration board to extract real color data.",
  },
  ext_photo: {
    zh: "校准板照片",
    en: "Calibration Photo",
  },
  ext_rotate_btn: {
    zh: "↺ 旋转",
    en: "↺ Rotate",
  },
  ext_correction_section: {
    zh: "校正参数",
    en: "Correction",
  },
  ext_nudge_section: {
    zh: "角点位置微调",
    en: "Corner Fine-Tune",
  },
  ext_nudge_step_label: {
    zh: "微调步长 (像素)",
    en: "Step (px)",
  },
  ext_nudge_step_hint: {
    zh: "每次点击方向按钮时角点移动的像素数量。值越大移动越快，值越小移动越精细。",
    en: "Number of pixels each directional button press moves the corner. Larger values move faster, smaller values allow finer adjustment.",
  },
  ext_nudge_active_corner_label: {
    zh: "当前调整角点",
    en: "Active Corner",
  },
  ext_nudge_hint_empty: {
    zh: "请先在画布上放置角点",
    en: "Place corners on the canvas first",
  },
  ext_nudge_up: {
    zh: "上移",
    en: "Up",
  },
  ext_nudge_down: {
    zh: "下移",
    en: "Down",
  },
  ext_nudge_left: {
    zh: "左移",
    en: "Left",
  },
  ext_nudge_right: {
    zh: "右移",
    en: "Right",
  },
  ext_nudge_keyboard_hint: {
    zh: "提示：可使用键盘方向键进行微调",
    en: "Tip: arrow keys also nudge the active corner",
  },
  ext_corner_pos_tl: { zh: "左上", en: "Top-Left" },
  ext_corner_pos_tr: { zh: "右上", en: "Top-Right" },
  ext_corner_pos_br: { zh: "右下", en: "Bottom-Right" },
  ext_corner_pos_bl: { zh: "左下", en: "Bottom-Left" },
  ext_color_white: { zh: "白色", en: "White" },
  ext_color_black: { zh: "黑色", en: "Black" },
  ext_color_cyan: { zh: "青色", en: "Cyan" },
  ext_color_magenta: { zh: "品红", en: "Magenta" },
  ext_color_yellow: { zh: "黄色", en: "Yellow" },
  ext_color_red: { zh: "红色", en: "Red" },
  ext_color_blue: { zh: "蓝色", en: "Blue" },
  ext_vignette: {
    zh: "暗角校正",
    en: "Vignette",
  },
  ext_zoom: {
    zh: "缩放",
    en: "Zoom",
  },
  ext_distortion: {
    zh: "畸变",
    en: "Distortion",
  },
  ext_offset_x: {
    zh: "X偏移",
    en: "Offset X",
  },
  ext_offset_y: {
    zh: "Y偏移",
    en: "Offset Y",
  },
  ext_status: {
    zh: "状态",
    en: "Status",
  },
  ext_marked: {
    zh: "标记图",
    en: "Marked",
  },
  ext_click_cell: {
    zh: "点击左侧色块查看...",
    en: "Click cell on left...",
  },
  ext_override: {
    zh: "替换颜色",
    en: "Override Color",
  },
  ext_download_npy: {
    zh: "下载 .npy",
    en: "Download .npy",
  },

  // ==================== 3D Viewer ====================
  viewer_fullscreen: {
    zh: "全屏",
    en: "Fullscreen",
  },
  viewer_exit_fullscreen: {
    zh: "退出全屏",
    en: "Exit Fullscreen",
  },
  viewer_screenshot: {
    zh: "截图",
    en: "Screenshot",
  },
  viewer_diagnostics_toggle: {
    zh: "3D 诊断",
    en: "Diagnostics",
  },
  viewer_diagnostics_title: {
    zh: "3D 诊断",
    en: "3D Diagnostics",
  },
  viewer_diagnostics_source: {
    zh: "来源",
    en: "Source",
  },
  viewer_diagnostics_source_generate: {
    zh: "生成 GLB",
    en: "Generated GLB",
  },
  viewer_diagnostics_source_preview: {
    zh: "预览 GLB",
    en: "Preview GLB",
  },
  viewer_diagnostics_source_idle: {
    zh: "空闲画布",
    en: "Idle Canvas",
  },
  viewer_diagnostics_fps: {
    zh: "FPS",
    en: "FPS",
  },
  viewer_diagnostics_frame_time: {
    zh: "帧时间",
    en: "Frame Time",
  },
  viewer_diagnostics_js_heap: {
    zh: "JS 堆",
    en: "JS Heap",
  },
  viewer_diagnostics_js_heap_unavailable: {
    zh: "不可用",
    en: "Unavailable",
  },
  viewer_diagnostics_geometries: {
    zh: "几何体",
    en: "Geometries",
  },
  viewer_diagnostics_textures: {
    zh: "纹理",
    en: "Textures",
  },
  viewer_diagnostics_programs: {
    zh: "Programs",
    en: "Programs",
  },
  viewer_diagnostics_draw_calls: {
    zh: "调用数",
    en: "Draw Calls",
  },
  viewer_diagnostics_triangles: {
    zh: "三角面",
    en: "Triangles",
  },
  viewer_diagnostics_canvas: {
    zh: "画布",
    en: "Canvas",
  },
  viewer_performance_toggle: {
    zh: "性能统计",
    en: "Performance",
  },
  viewer_performance_title: {
    zh: "性能统计",
    en: "Performance Stats",
  },
  viewer_performance_empty: {
    zh: "暂无性能数据",
    en: "No performance data yet",
  },
  viewer_performance_preview_title: {
    zh: "预览生成",
    en: "Preview Generation",
  },
  viewer_performance_generate_title: {
    zh: "模型生成",
    en: "Model Generation",
  },
  viewer_performance_total: {
    zh: "总耗时",
    en: "Total",
  },
  viewer_performance_upload: {
    zh: "上传处理",
    en: "Upload",
  },
  viewer_performance_worker: {
    zh: "核心计算",
    en: "Worker",
  },
  viewer_performance_pickle_load: {
    zh: "缓存读取",
    en: "Cache Load",
  },
  viewer_performance_segmented_glb: {
    zh: "预览 GLB",
    en: "Preview GLB",
  },
  viewer_performance_palette: {
    zh: "调色板",
    en: "Palette",
  },
  viewer_performance_overhead: {
    zh: "接口开销",
    en: "API Overhead",
  },
  viewer_hover_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_group: {
    zh: "悬停显示",
    en: "Hover Display",
  },
  viewer_hover_toggle_magnifier: {
    zh: "放大镜",
    en: "Magnifier",
  },
  viewer_hover_toggle_layers: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
  viewer_hover_pixel: {
    zh: "像素坐标",
    en: "Pixel",
  },
  viewer_hover_surface_color: {
    zh: "预测颜色",
    en: "Predicted Color",
  },
  viewer_hover_layers_title: {
    zh: "分层颜色",
    en: "Layer Colors",
  },
  viewer_hover_loading_layers: {
    zh: "正在加载分层颜色...",
    en: "Loading layer colors...",
  },
  viewer_hover_no_layer_data: {
    zh: "暂无分层颜色数据",
    en: "No layer color data",
  },
  layer_faces_viewer_suffix: {
    zh: "这层是观赏面",
    en: "viewing face",
  },
  viewer_hover_transparent: {
    zh: "透明",
    en: "Transparent",
  },

  // ==================== Footer ====================
  // ==================== Status Messages ====================
  msg_click_to_place: {
    zh: "点击图片放置挂孔",
    en: "Click to place loop",
  },
  msg_resolution: {
    zh: "分辨率",
    en: "Resolution",
  },
  msg_loop: {
    zh: "挂孔",
    en: "Loop",
  },
  msg_preview_simplified: {
    zh: "ℹ️ 3D预览已简化",
    en: "ℹ️ 3D preview simplified",
  },

  // ==================== Browser Completion Notifications ====================
  "completion_notification.preview.title": {
    zh: "预览已完成",
    en: "Preview complete",
  },
  "completion_notification.preview.body": {
    zh: "预览已准备好，可以查看。",
    en: "Your preview is ready to inspect.",
  },
  "completion_notification.generation.title": {
    zh: "模型生成已完成",
    en: "Model generation complete",
  },
  "completion_notification.generation.body": {
    zh: "模型已准备好，可以下载或发送到切片软件。",
    en: "Your model is ready to download or send to a slicer.",
  },
  "completion_notification.batch.title": {
    zh: "批量生成已完成",
    en: "Batch generation complete",
  },
  "completion_notification.batch.body": {
    zh: "批量生成结果已准备好。",
    en: "Your batch results are ready.",
  },
  "completion_notification.calibration.title": {
    zh: "校准生成已完成",
    en: "Calibration generation complete",
  },
  "completion_notification.calibration.body": {
    zh: "校准文件已准备好。",
    en: "Your calibration files are ready.",
  },

  // ==================== Palette / Replacement ====================
  palette_empty: {
    zh: "暂无颜色，请先生成预览。",
    en: "No colors yet. Generate a preview first.",
  },
  palette_count: {
    zh: "共 {count} 种颜色",
    en: "{count} colors in image",
  },
  palette_hint: {
    zh: "点击色块高亮预览",
    en: "Click swatch to highlight in preview",
  },
  palette_tooltip: {
    zh: "点击高亮: {hex} ({pct}%)",
    en: "Click to highlight: {hex} ({pct}%)",
  },
  palette_replaced_with: {
    zh: "替换为 {hex}",
    en: "Replaced with {hex}",
  },
  palette_click_to_select: {
    zh: "点击调色板选择颜色",
    en: "Click palette to select",
  },
  palette_undone: {
    zh: "↩️ 已撤销",
    en: "↩️ Undone",
  },
  palette_mode_select_all: {
    zh: "同颜色全选",
    en: "Same color",
  },
  palette_mode_multi_select: {
    zh: "点选色块",
    en: "Pick blocks",
  },
  palette_mode_brush: {
    zh: "选区画笔",
    en: "Selection brush",
  },
  palette_selected_blocks: {
    zh: "已选 {count} 个色块",
    en: "{count} blocks selected",
  },
  palette_selected_colors: {
    zh: "涉及 {count} 种颜色",
    en: "{count} colors",
  },
  selection_brush_size: {
    zh: "画笔大小",
    en: "Brush size",
  },
  selection_brush_apply: {
    zh: "执行画笔",
    en: "Apply brush",
  },
  selection_brush_clear: {
    zh: "清除笔迹",
    en: "Clear stroke",
  },
  palette_multi_select_count: {
    zh: "已选 {count} 色",
    en: "{count} selected",
  },
  palette_multi_select_region_count: {
    zh: "已选 {count} 个区域",
    en: "{count} regions selected",
  },
  palette_multi_select_click_remove: {
    zh: "点击取消选择",
    en: "Click to deselect",
  },

  // ==================== Color Merging ====================
  merge_enable_label: {
    zh: "启用自动颜色合并 Enable Auto Color Merging",
    en: "Enable Auto Color Merging",
  },
  merge_enable_info: {
    zh: "自动合并低使用率颜色到相近颜色",
    en: "Automatically merge low-usage colors to similar colors",
  },
  merge_threshold_label: {
    zh: "使用率阈值 Usage Threshold (%)",
    en: "Usage Threshold (%)",
  },
  merge_threshold_info: {
    zh: "低于此百分比的颜色将被合并",
    en: "Colors below this percentage will be merged",
  },
  merge_max_distance_label: {
    zh: "最大颜色距离 Max Color Distance (Delta-E)",
    en: "Max Color Distance (Delta-E)",
  },
  merge_max_distance_info: {
    zh: "只合并距离小于此值的颜色",
    en: "Only merge colors with distance below this value",
  },
  merge_revert_btn: {
    zh: "↩️ 恢复原始 Revert",
    en: "↩️ Revert",
  },
  merge_status_reverted: {
    zh: "↩️ 已恢复到原始颜色",
    en: "↩️ Reverted to original colors",
  },
  // ==================== LUT Grid ====================
  lut_grid_load_hint: {
    zh: "加载 LUT 后显示可用颜色",
    en: "Load LUT to see available colors",
  },
  lut_grid_count: {
    zh: "共 {count} 种可用颜色",
    en: "{count} available colors",
  },
  lut_grid_search_placeholder: {
    zh: "搜索色号 (如 ff0000)",
    en: "Search hex (e.g. ff0000)",
  },
  lut_grid_search_clear: {
    zh: "清除",
    en: "Clear",
  },
  lut_grid_used: {
    zh: "图中已使用 ({count})",
    en: "Used in image ({count})",
  },
  lut_grid_other: {
    zh: "其他可用颜色 ({count})",
    en: "Other colors ({count})",
  },
  lut_grid_tooltip: {
    zh: "点击选择: {hex}",
    en: "Click to select: {hex}",
  },
  lut_grid_picker_hint: {
    zh: "选一个颜色，自动匹配 LUT 中最接近的物理色",
    en: "Pick a color to find the closest match in LUT",
  },
  lut_grid_picker_btn: {
    zh: "匹配最近色",
    en: "Find Nearest",
  },
  lut_grid_hue_all: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_red: {
    zh: "红色系",
    en: "Red",
  },
  lut_grid_hue_orange: {
    zh: "橙色系",
    en: "Orange",
  },
  lut_grid_hue_yellow: {
    zh: "黄色系",
    en: "Yellow",
  },
  lut_grid_hue_green: {
    zh: "绿色系",
    en: "Green",
  },
  lut_grid_hue_cyan: {
    zh: "青色系",
    en: "Cyan",
  },
  lut_grid_hue_blue: {
    zh: "蓝色系",
    en: "Blue",
  },
  lut_grid_hue_purple: {
    zh: "紫色系",
    en: "Purple",
  },
  lut_grid_hue_neutral: {
    zh: "中性色",
    en: "Neutral",
  },
  lut_grid_hue_fav: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_search_hex_placeholder: {
    zh: "输入 Hex 或 RGB 搜索定位 (如 #FF0000 或 255,0,0)",
    en: "Search by Hex or RGB (e.g. #FF0000 or 255,0,0)",
  },

  // ==================== Settings ====================
  // ==================== LUT Merge Tab ====================
  merge_desc: {
    zh: "将不同色彩模式的LUT色卡合并为一个，获得更丰富的色彩。",
    en: "Merge LUT cards from different color modes into one for richer colors.",
  },
  merge_lut_1_label: {
    zh: "选择LUT 1（主色卡）",
    en: "Select LUT 1 (Primary)",
  },
  merge_lut_2_label: {
    zh: "选择LUT 2（合并色卡）",
    en: "Select LUT 2 (Secondary)",
  },
  merge_secondary_modes: {
    zh: "已选副色卡",
    en: "Selected Secondary LUTs",
  },
  merge_secondary_none: {
    zh: "未选择副色卡",
    en: "No secondary LUTs selected",
  },
  merge_mode_label: {
    zh: "检测到的模式",
    en: "Detected Mode",
  },
  merge_mode_unknown: {
    zh: "未选择",
    en: "Not selected",
  },
  merge_dedup_label: {
    zh: "Delta-E 去重阈值",
    en: "Delta-E Dedup Threshold",
  },
  merge_dedup_info: {
    zh: "值越大去除的相近色越多，0=仅精确去重",
    en: "Higher = remove more similar colors, 0 = exact dedup only",
  },
  merge_status_running: {
    zh: "⏳ 合并中...",
    en: "⏳ Merging...",
  },
  // ==================== Widget Titles ====================
  "widget.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "widget.calibration": {
    zh: "校准板",
    en: "Calibration",
  },
  "widget.extractor": {
    zh: "颜色提取",
    en: "Extractor",
  },
  "widget.lutManager": {
    zh: "LUT 合并",
    en: "LUT Merge",
  },
  "widget.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "widget.basicSettings": {
    zh: "图像导入和基础设置",
    en: "Image Import and Basic Settings",
  },
  "widget.modelSurfaceSettings": {
    zh: "模型贴图",
    en: "Model Texture",
  },
  "widget.advancedSettings": {
    zh: "高级设置",
    en: "Advanced Settings",
  },
  "widget.reliefSettings": {
    zh: "浮雕设置",
    en: "Relief Settings",
  },
  "widget.palettePanel": {
    zh: "调色板",
    en: "Palette",
  },
  "widget.lutColorGrid": {
    zh: "LUT 颜色网格",
    en: "LUT Color Grid",
  },
  "widget.outlineSettings": {
    zh: "外轮廓设置",
    en: "Outline Settings",
  },
  "widget.cloisonneSettings": {
    zh: "掐丝珐琅设置",
    en: "Cloisonné Settings",
  },
  "widget.coatingSettings": {
    zh: "透明镀层设置",
    en: "Transparent Coating Settings",
  },
  "widget.keychainLoop": {
    zh: "挂件环设置",
    en: "Keychain Loop",
  },
  "widget.fridgeMagnetSettings": {
    zh: "冰箱贴磁铁槽",
    en: "Fridge Magnet Settings",
  },
  "widget.puzzleSettings": {
    zh: "拼图设置",
    en: "Puzzle Settings",
  },
  "widget.actionBar": {
    zh: "操作栏",
    en: "Actions",
  },
  "widget.colorWorkstation": {
    zh: "颜色工作站",
    en: "Color Workstation",
  },
  "widget.colorWorkstationHint": {
    zh: "点击打开颜色工作站",
    en: "Click to open Color Workstation",
  },

  // ==================== 2D Color Overlay ====================
  fridge_magnet_enable: {
    zh: "启用冰箱贴磁铁槽",
    en: "Enable Fridge Magnet Mode",
  },
  fridge_magnet_mode_hint: {
    zh: "冰箱贴模式会强制切换为单面结构，并禁用拼图、大画幅和挂件环。",
    en: "Fridge magnet mode forces single-sided structure and disables puzzle, large-format, and keychain loop modes.",
  },
  fridge_magnet_mode_active_status: {
    zh: "拼图、大画幅和挂件环已禁用。",
    en: "Puzzle, large-format, and keychain loop modes are disabled.",
  },
  fridge_magnet_loop_disabled_status: {
    zh: "冰箱贴模式下，挂件环不可用。",
    en: "The keychain loop is unavailable in fridge magnet mode.",
  },
  fridge_magnet_summary_structure: {
    zh: "当前结构",
    en: "Structure",
  },
  fridge_magnet_summary_spacer: {
    zh: "当前底板厚度",
    en: "Spacer Thickness",
  },
  fridge_magnet_add: {
    zh: "添加磁铁",
    en: "Add Magnet",
  },
  fridge_magnet_reset_layout: {
    zh: "自动布局",
    en: "Auto Layout",
  },
  fridge_magnet_remove_selected: {
    zh: "删除当前磁铁",
    en: "Remove Selected",
  },
  fridge_magnet_list_title: {
    zh: "磁铁列表",
    en: "Magnet List",
  },
  fridge_magnet_item_label: {
    zh: "磁铁 {index}",
    en: "Magnet {index}",
  },
  fridge_magnet_empty_state: {
    zh: "当前没有磁铁槽，请先添加一个磁铁。",
    en: "No magnet cavities are configured yet. Add a magnet first.",
  },
  fridge_magnet_select_hint: {
    zh: "从上方列表选择一个磁铁以编辑尺寸和位置。",
    en: "Select a magnet above to edit its size and position.",
  },
  fridge_magnet_clear_selection: {
    zh: "清除选中",
    en: "Clear Selection",
  },
  fridge_magnet_shape: {
    zh: "形状",
    en: "Shape",
  },
  fridge_magnet_shape_round: {
    zh: "圆形",
    en: "Round",
  },
  fridge_magnet_shape_rect: {
    zh: "矩形",
    en: "Rectangular",
  },
  fridge_magnet_preset: {
    zh: "官方预设",
    en: "Official Preset",
  },
  fridge_magnet_preset_custom: {
    zh: "自定义",
    en: "Custom",
  },
  fridge_magnet_preset_round_d6x2: {
    zh: "圆形 D6×2 mm",
    en: "Round D6×2 mm",
  },
  fridge_magnet_preset_round_d12x3: {
    zh: "圆形 D12×3 mm",
    en: "Round D12×3 mm",
  },
  fridge_magnet_preset_round_d8x3: {
    zh: "圆形 D8×3 mm",
    en: "Round D8×3 mm",
  },
  fridge_magnet_preset_round_d10x3: {
    zh: "圆形 D10×3 mm",
    en: "Round D10×3 mm",
  },
  fridge_magnet_preset_rect_10x5x1: {
    zh: "矩形 10×5×1 mm",
    en: "Rect 10×5×1 mm",
  },
  fridge_magnet_preset_rect_15x5x2: {
    zh: "矩形 15×5×2 mm",
    en: "Rect 15×5×2 mm",
  },
  fridge_magnet_preset_rect_20x10x2: {
    zh: "矩形 20×10×2 mm",
    en: "Rect 20×10×2 mm",
  },
  fridge_magnet_diameter: {
    zh: "直径",
    en: "Diameter",
  },
  fridge_magnet_width: {
    zh: "宽度",
    en: "Width",
  },
  fridge_magnet_height: {
    zh: "高度",
    en: "Height",
  },
  fridge_magnet_thickness: {
    zh: "厚度",
    en: "Thickness",
  },
  fridge_magnet_center_x: {
    zh: "中心 X",
    en: "Center X",
  },
  fridge_magnet_center_y: {
    zh: "中心 Y",
    en: "Center Y",
  },
  color_2d_overlay_title: {
    zh: "颜色工作站",
    en: "Color Workstation",
  },
  color_2d_overlay_close: {
    zh: "关闭",
    en: "Close",
  },
  color_2d_overlay_close_shortcut: {
    zh: "ESC",
    en: "ESC",
  },
  color_2d_tab_preview: {
    zh: "2D 预览",
    en: "2D Preview",
  },
  color_2d_tab_palette: {
    zh: "调色板",
    en: "Palette",
  },
  color_2d_tab_lut_grid: {
    zh: "LUT 颜色",
    en: "LUT Colors",
  },
  color_2d_no_preview: {
    zh: "暂无预览图，请先完成预览",
    en: "No preview available. Please generate a preview first.",
  },
  color_2d_generating_preview: {
    zh: "正在生成预览…",
    en: "Generating preview…",
  },
  preview_debug_main_2d: {
    zh: "2D 预览",
    en: "2D Preview",
  },
  color_2d_hold_view_original: {
    zh: "按住按钮或按住 Shift 键查看原图",
    en: "Hold this button or hold Shift to view the original image",
  },
  preview_debug_action_2d: {
    zh: "操作栏 2D 小预览",
    en: "ActionBar Mini Preview",
  },
  puzzle_enable: {
    zh: "启用拼图模式",
    en: "Enable Puzzle Mode",
  },
  puzzle_enable_hint: {
    zh: "把作品拆分成可以分别打印、最后再拼合的拼图片。",
    en: "Splits the design into pieces that can be printed separately and assembled afterward.",
  },
  puzzle_batch_disabled_hint: {
    zh: "批量模式下暂不支持拼图模式。",
    en: "Puzzle mode is unavailable while batch mode is active.",
  },
  puzzle_style: {
    zh: "拼图风格",
    en: "Puzzle Style",
  },
  puzzle_style_regular: {
    zh: "规则拼图",
    en: "Regular Puzzle",
  },
  puzzle_style_irregular: {
    zh: "不规则拼图",
    en: "Irregular Puzzle",
  },
  puzzle_sizing_mode: {
    zh: "尺寸控制方式",
    en: "Sizing Mode",
  },
  puzzle_sizing_piece_size: {
    zh: "按块尺寸",
    en: "By Piece Size",
  },
  puzzle_sizing_grid: {
    zh: "按行列",
    en: "By Grid",
  },
  puzzle_sizing_piece_count: {
    zh: "按总片数",
    en: "By Piece Count",
  },
  puzzle_piece_width: {
    zh: "平均块宽",
    en: "Average Piece Width",
  },
  puzzle_piece_height: {
    zh: "平均块高",
    en: "Average Piece Height",
  },
  puzzle_rows: {
    zh: "行数",
    en: "Rows",
  },
  puzzle_cols: {
    zh: "列数",
    en: "Columns",
  },
  puzzle_target_piece_count: {
    zh: "目标片数",
    en: "Target Piece Count",
  },
  puzzle_connector_style: {
    zh: "连接器风格",
    en: "Connector Style",
  },
  puzzle_connector_classic: {
    zh: "经典风格",
    en: "Classic",
  },
  puzzle_connector_easy_cut: {
    zh: "易切割风格",
    en: "Easy Cut",
  },
  puzzle_seed: {
    zh: "随机种子",
    en: "Seed",
  },
  puzzle_randomize_seed: {
    zh: "重新随机",
    en: "Randomize",
  },
  puzzle_labels: {
    zh: "显示编号",
    en: "Show Piece Labels",
  },
  puzzle_engrave_back_labels: {
    zh: "背面刻号",
    en: "Engrave Back Labels",
  },
  puzzle_back_engrave_unavailable_hint: {
    zh: "背面刻号尚未写入导出几何，当前版本暂不可用。",
    en: "Back-label engraving is not embedded into exported geometry yet, so it is disabled for now.",
  },
  puzzle_irregularity_strength: {
    zh: "不规则强度",
    en: "Irregularity Strength",
  },
  puzzle_min_neck_width: {
    zh: "最小脖颈宽度",
    en: "Minimum Neck Width",
  },
  puzzle_summary_grid: {
    zh: "解析网格",
    en: "Resolved Grid",
  },
  puzzle_summary_requested_grid: {
    zh: "目标网格",
    en: "Requested Grid",
  },
  puzzle_summary_requested_piece_count: {
    zh: "目标片数",
    en: "Requested Piece Count",
  },
  puzzle_summary_piece_count: {
    zh: "最终片数",
    en: "Resolved Piece Count",
  },
  puzzle_summary_piece_size: {
    zh: "平均块尺寸",
    en: "Derived Piece Size",
  },
  puzzle_warnings: {
    zh: "几何警告",
    en: "Geometry Warnings",
  },
  puzzle_large_format_disabled_hint: {
    zh: "拼图模式开启时，大画幅模式会被禁用。",
    en: "Large Format is disabled while puzzle mode is enabled.",
  },
  model_surface_large_format_disabled_hint: {
    zh: "模型贴图开启时，大画幅模式会被禁用。",
    en: "Large Format is disabled while model texture is enabled.",
  },
  large_format_model_surface_conflict: {
    zh: "大画幅模式不支持模型贴图：切片只会按平面图片和普通尺寸生成，不包含上传的模型。请关闭大画幅模式或模型贴图后再生成。",
    en: "Large Format does not support model texture: tiles would be cut from the flat image at the ordinary size, without the uploaded model. Turn off Large Format or model texture, then generate again.",
  },
  puzzle_loop_disabled_hint: {
    zh: "拼图模式开启时，挂件环会被禁用。",
    en: "Keychain Loop is disabled while puzzle mode is enabled.",
  },

  // ==================== TAB Navigation Titles ====================
  "tab.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "tab.lutManagement": {
    zh: "LUT管理",
    en: "LUT Management",
  },
  "tab.materialManagement": {
    zh: "耗材管理",
    en: "Material Management",
  },
  "tab.calibration": {
    zh: "生成校准板",
    en: "Calibration Board",
  },
  "tab.extractor": {
    zh: "LUT提取",
    en: "LUT Extractor",
  },
  "tab.gradientCardGenerate": {
    zh: "梯度卡生成",
    en: "Gradient Generator",
  },
  "tab.gradientCardExtract": {
    zh: "梯度卡提取",
    en: "Gradient Extractor",
  },
  "tab.materialLibrary": {
    zh: "耗材库",
    en: "Material Library",
  },
  "tab.materialCloudSync": {
    zh: "云端耗材库",
    en: "Cloud Material Library",
  },
  "tab.materialRecipe": {
    zh: "配方查询",
    en: "Recipe Query",
  },
  "tab.lutManager": {
    zh: "LUT 合并",
    en: "LUT Merge",
  },
  "tab.lutLibrary": {
    zh: "LUT库",
    en: "LUT Library",
  },
  "tab.lutCloudSync": {
    zh: "云端 LUT 库",
    en: "Cloud LUT Library",
  },
  "tab.lutDetails": {
    zh: "LUT 详情",
    en: "LUT Details",
  },
  "tab.lutCompare": {
    zh: "LUT 对比",
    en: "LUT Compare",
  },
  "tab.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "tab.vectorizer": {
    zh: "图像转矢量",
    en: "Vectorizer",
  },
  "tab.workshop": {
    zh: "创意工坊",
    en: "Creative Workshop",
  },
  "tab.settings": {
    zh: "设置",
    en: "Settings",
  },
  "workshop.title": {
    zh: "创意工坊",
    en: "Creative Workshop",
  },
  "workshop.description": {
    zh: "使用 Lumina 官方与受信任模块分析、编辑并准备特殊图像工作流。",
    en: "Use official and trusted Lumina modules to analyze, edit, and prepare specialized image workflows.",
  },
  "workshop.official": {
    zh: "官方",
    en: "Official",
  },
  "workshop.moduleMeta": {
    zh: "{author} · v{version}",
    en: "{author} · v{version}",
  },
  "workshop.open": {
    zh: "打开",
    en: "Open",
  },
  "workshop.continue": {
    zh: "继续",
    en: "Continue",
  },
  "workshop.newProject": {
    zh: "新建项目",
    en: "New project",
  },
  "workshop.back": {
    zh: "返回创意工坊",
    en: "Back to Creative Workshop",
  },
  "workshop.localOnly": {
    zh: "第一版仅加载随 Lumina 发布并列入白名单的模块，项目保存在本机。",
    en: "This first release loads only modules shipped with and whitelisted by Lumina. Projects stay on this device.",
  },
  "workshop.capabilityManaged": {
    zh: "模块权限由 Lumina 宿主管理。",
    en: "Module capabilities are managed by the Lumina host.",
  },
  "workshop.persistenceUnavailable": {
    zh: "浏览器无法使用持久化存储。本次项目仍可编辑，但关闭页面后不会保留。",
    en: "Persistent browser storage is unavailable. You can keep editing this session, but the project will not survive closing the page.",
  },
  "workshop.moduleErrorTitle": {
    zh: "模块暂时无法打开",
    en: "The module could not open",
  },
  "workshop.moduleErrorDescription": {
    zh: "项目数据仍然保留。请返回工坊后重试。",
    en: "Your project data is still preserved. Return to the workshop and try again.",
  },
  "tab.colorEditor": {
    zh: "颜色编辑",
    en: "Color Editor",
  },
  "tab.converterCore": {
    zh: "核心设置",
    en: "Core Settings",
  },
  "tab.converterColor": {
    zh: "颜色调整",
    en: "Color Adjustment",
  },
  palette_mode_color_range: {
    zh: "相近颜色",
    en: "Similar colors",
  },
  selection_color_range_tolerance: {
    zh: "色差容差",
    en: "Tolerance",
  },
  selection_color_range_hint: {
    zh: "点击图中的颜色，会选中所有色差（ΔE00）不超过容差的色块；容差为 0 时只选完全相同的颜色。再点一次同一颜色可取消。",
    en: "Click a color on the image to select every block whose color difference (ΔE00) is within the tolerance; 0 selects only the exact color. Click the same color again to deselect.",
  },
  quick_replace_title: {
    zh: "快速换色与相似配方",
    en: "Quick recolor & similar recipes",
  },
  quick_replace_expand: {
    zh: "展开",
    en: "Expand",
  },
  quick_replace_collapse: {
    zh: "收起",
    en: "Collapse",
  },
  quick_replace_needs_selection: {
    zh: "先在左侧图像上选择区域（同颜色、相近颜色、点选色块或画笔），再在这里换色。",
    en: "Select an area on the image first (same color, similar colors, blocks or brush), then recolor it here.",
  },
  quick_replace_target_heading: {
    zh: "目标颜色 B",
    en: "Target color B",
  },
  quick_replace_eyedropper: {
    zh: "从图中取色",
    en: "Pick from image",
  },
  quick_replace_eyedropper_title: {
    zh: "点一下这个按钮，再点左侧图像上的任意一点，用那一点的颜色作为目标颜色 B（不会改变选区）",
    en: "Click this, then click any point on the image to use its color as target color B (the selection is not changed)",
  },
  quick_replace_eyedropper_active: {
    zh: "请在左侧图像上点击要取色的位置，按 Esc 取消。",
    en: "Click the point on the image whose color you want. Press Esc to cancel.",
  },
  quick_replace_target_hex_placeholder: {
    zh: "#ff8800",
    en: "#ff8800",
  },
  quick_replace_target_hex_invalid: {
    zh: "请输入 6 位十六进制颜色，例如 #ff8800",
    en: "Enter a 6-digit hex color, e.g. #ff8800",
  },
  quick_replace_target_from_image: {
    zh: "从图中已有颜色选取",
    en: "Pick from colors already in the image",
  },
  quick_replace_nearest_printable: {
    zh: "最接近 B 的可打印颜色",
    en: "Nearest printable color to B",
  },
  quick_replace_replace_button: {
    zh: "把选区替换成这个颜色",
    en: "Replace selection with this color",
  },
  quick_replace_recipes_heading: {
    zh: "相似配方",
    en: "Similar recipes",
  },
  quick_replace_reference: {
    zh: "参考色",
    en: "Reference",
  },
  quick_replace_basis_selection: {
    zh: "按选区颜色",
    en: "From selection",
  },
  quick_replace_basis_target: {
    zh: "按目标颜色 B",
    en: "From color B",
  },
  quick_replace_reference_colors: {
    zh: "选区包含多种颜色，点击选择参考色",
    en: "The selection has several colors; click one to use as reference",
  },
  quick_replace_recipes_loading: {
    zh: "正在查找相似配方…",
    en: "Finding similar recipes…",
  },
  quick_replace_recipes_empty: {
    zh: "没有找到可用的配方",
    en: "No printable recipes found",
  },
  quick_replace_recipes_pick_reference: {
    zh: "选择区域或输入目标颜色 B 后，这里会列出颜色最接近的配方。",
    en: "Select an area or enter target color B to list the closest recipes here.",
  },
  quick_replace_recipes_error: {
    zh: "配方推荐加载失败，请重新生成预览后再试。",
    en: "Could not load recipe suggestions. Regenerate the preview and try again.",
  },
  quick_replace_recipe_apply: {
    zh: "替换",
    en: "Apply",
  },
  quick_replace_recipe_apply_title: {
    zh: "把选区替换为 {hex}（{layers}）",
    en: "Replace the selection with {hex} ({layers})",
  },
  quick_replace_recipe_layers_hint: {
    zh: "色块从左到右：观察面 → 底部",
    en: "Chips left to right: viewing face → bottom",
  },
  quick_replace_source_lut: {
    zh: "实测",
    en: "Measured",
  },
  quick_replace_source_lut_title: {
    zh: "来自 LUT 实测色卡，打印结果最可靠",
    en: "From the measured LUT; the most reliable print result",
  },
  quick_replace_source_predictive: {
    zh: "预测",
    en: "Predicted",
  },
  quick_replace_source_predictive_title: {
    zh: "由预测模型估算的颜色，实际打印可能略有差异；应用后需要重新选择区域",
    en: "Estimated by the prediction model; the print may differ slightly. Re-select the area after applying",
  },
  quick_replace_in_image: {
    zh: "图中已有",
    en: "In image",
  },
  quick_replace_in_image_title: {
    zh: "当前图像里已经用到了这个颜色",
    en: "This color is already used in the current image",
  },
  quick_replace_delta_e_value: {
    zh: "色差 ΔE {value}",
    en: "ΔE {value}",
  },
  quick_replace_delta_e_close: {
    zh: "几乎一致",
    en: "Near match",
  },
  quick_replace_delta_e_near: {
    zh: "接近",
    en: "Close",
  },
  quick_replace_delta_e_far: {
    zh: "差异明显",
    en: "Visible difference",
  },
  "tab.converterAdvanced": {
    zh: "创意中心",
    en: "Creative Center",
  },

  // ==================== Settings Panel (Particle Loading) ====================
  "settings.title": {
    zh: "系统设置",
    en: "System Settings",
  },
  "settings.desc": {
    zh: "设置会自动保存在当前设备。",
    en: "Settings are saved automatically on this device.",
  },
  "settings.category_nav_label": {
    zh: "设置分类",
    en: "Settings categories",
  },
  "settings.category_device": {
    zh: "打印与切片",
    en: "Printer & Slicer",
  },
  "settings.category_device_desc": {
    zh: "默认打印机、喷嘴与切片软件",
    en: "Default printer, nozzle, and slicer",
  },
  "settings.category_general": {
    zh: "常规",
    en: "General",
  },
  "settings.language_label": {
    zh: "界面语言 / Language",
    en: "Language / 界面语言",
  },
  "settings.language_zh": {
    zh: "简体中文",
    en: "简体中文",
  },
  "settings.language_en": {
    zh: "English",
    en: "English",
  },
  "settings.interface_scale_label": {
    zh: "界面缩放",
    en: "Interface scale",
  },
  "settings.interface_scale_description": {
    zh: "100% 使用系统默认显示比例，不会因屏幕分辨率额外放大。可按需调整界面大小，或按 Ctrl 加号、减号逐档调整，Ctrl 0 回到 100%（Mac 上用 Command 键）。不影响模型和导出尺寸。",
    en: "100% follows your system display scale without extra enlargement based on screen resolution. Adjust the interface size here or with Ctrl plus/minus; Ctrl+0 returns to 100% (use Command on Mac). Model and export dimensions are unchanged.",
  },
  "settings.interface_scale_failed": {
    zh: "无法读取或更改界面缩放，请重启软件后重试。",
    en: "The interface scale could not be read or changed. Restart the app and try again.",
  },
  "settings.category_general_desc": {
    zh: "通知、导出与界面体验偏好",
    en: "Notifications, exports, and interface preferences",
  },
  "settings.category_conversion": {
    zh: "转换与精度",
    en: "Conversion & Quality",
  },
  "settings.category_conversion_desc": {
    zh: "颜色、SVG 与渐变处理",
    en: "Color, SVG, and gradient handling",
  },
  "settings.category_maintenance": {
    zh: "存储与维护",
    en: "Storage & Maintenance",
  },
  "settings.category_maintenance_desc": {
    zh: "清理临时文件与缓存",
    en: "Clean temporary files and caches",
  },
  "settings.current_device_heading": {
    zh: "当前设备",
    en: "Current Device",
  },
  "settings.current_device_description": {
    zh: "生成 3MF 时默认使用这组切片软件、打印机与喷嘴配置。",
    en: "New 3MF exports use this slicer, printer, and nozzle configuration by default.",
  },
  "settings.change_device": {
    zh: "更改设备",
    en: "Change Device",
  },
  "settings.build_plate": {
    zh: "打印板",
    en: "Build Plate",
  },
  "settings.build_plate_hint": {
    zh: "选择会写入 3MF，并按切片软件与打印机型号分别记忆。",
    en: "The choice is written to 3MF and remembered for each slicer and printer model.",
  },
  "settings.build_plate_fallback": {
    zh: "之前选择的打印板已不可用，已改用该机型的默认打印板。",
    en: "The previous build plate is no longer available, so this printer's default is selected.",
  },
  "settings.machine_dialog_title": {
    zh: "选择打印设备",
    en: "Choose Print Device",
  },
  "settings.machine_dialog_description": {
    zh: "先选择切片软件，再搜索并选择兼容的打印机与喷嘴。",
    en: "Choose a slicer, then search for a compatible printer and nozzle.",
  },
  "settings.machine_dialog_close": {
    zh: "关闭",
    en: "Close",
  },
  "settings.machine_dialog_done": {
    zh: "完成",
    en: "Done",
  },
  "settings.machine_search_label": {
    zh: "搜索打印机",
    en: "Search printers",
  },
  "settings.machine_search_placeholder": {
    zh: "输入品牌或型号",
    en: "Search by brand or model",
  },
  "settings.machine_search_empty": {
    zh: "没有找到兼容的打印机",
    en: "No compatible printers found",
  },
  "settings.machine_search_empty_hint": {
    zh: "请尝试其他关键词，或切换上方的切片软件。",
    en: "Try another search or change the slicer above.",
  },
  "settings.machine_options_loading": {
    zh: "正在加载设备…",
    en: "Loading devices…",
  },
  "settings.machine_thumbnail_fallback": {
    zh: "设备",
    en: "Device",
  },
  "settings.manual_setup_heading": {
    zh: "手动设置切片软件",
    en: "Manual Slicer Setup",
  },
  "settings.manual_setup_description": {
    zh: "仅在自动检测不到本机切片软件时使用。",
    en: "Use this only when the installed slicer cannot be detected automatically.",
  },
  "settings.maintenance": {
    zh: "维护",
    en: "Maintenance",
  },
  "settings.fancy_loading": {
    zh: "粒子特效加载动画",
    en: "Particle Effect Loading",
  },
  "settings.fancy_loading_desc": {
    zh: "启用七彩粒子聚合加载特效，关闭后使用轻量级扫描线动画",
    en: "Enable rainbow particle convergence effect, disable for lightweight scan line animation",
  },
  "settings.witty_loading": {
    zh: "加载趣味消息",
    en: "Loading Witty Messages",
  },
  "settings.witty_loading_desc": {
    zh: "加载过程中显示轻松的提示语。",
    en: "Show lighthearted messages while a task is loading.",
  },
  "settings.header_nav_alignment_heading": {
    zh: "顶部导航对齐",
    en: "Top navigation alignment",
  },
  "settings.header_nav_alignment_description": {
    zh: "选择主导航和子导航的位置。居中：两行导航共用一条中线，空间足够时就是窗口中线；居左：主导航紧跟标题，子导航与主导航第一项左对齐。窗口变窄时会先收起顶部标题文字、只保留标志，给导航腾出空间；标志和右侧按钮之间仍放不下时，主导航才移到下一行。",
    en: "Choose where the main and sub navigation sit. Centered keeps both rows on one shared centre line, which is the middle of the window whenever there is room. Left places the main tabs right after the title and lines the sub tabs up with the first main tab. As the window narrows, the title text is hidden first so only the logo remains; the main tabs move to the next row only when they no longer fit between the logo and the buttons on the right.",
  },
  "settings.header_nav_alignment_label": {
    zh: "对齐方式",
    en: "Alignment",
  },
  "settings.header_nav_alignment_center": {
    zh: "居中",
    en: "Centered",
  },
  "settings.header_nav_alignment_left": {
    zh: "居左",
    en: "Left",
  },
  "settings.preserve_upload_filename_heading": {
    zh: "导出 3MF 时沿用上传文件名",
    en: "Use uploaded filename for 3MF exports",
  },
  "settings.preserve_upload_filename_description": {
    zh: "开启后，普通单件生成会把“海报.png”下载为“海报.3mf”。默认关闭；批量、拼图和大画幅继续使用原有名称。",
    en: "When enabled, a normal single-item export downloads “poster.png” as “poster.3mf”. It is off by default; batch, puzzle, and large-format exports keep their existing names.",
  },
  "settings.generated_file_directory_heading": {
    zh: "生成文件默认保存位置",
    en: "Default save location",
  },
  "settings.generated_file_directory_description": {
    zh: "下载 3MF、导出配方卡等保存对话框会默认打开这个文件夹，仍可在对话框里改选其他位置。",
    en: "Save dialogs for 3MF downloads and recipe exports open in this folder by default; you can still pick another location in the dialog.",
  },
  "settings.generated_file_directory_system_default": {
    zh: "系统默认位置",
    en: "System default",
  },
  "settings.generated_file_directory_choose": {
    zh: "选择文件夹",
    en: "Choose folder",
  },
  "settings.generated_file_directory_reset": {
    zh: "恢复默认",
    en: "Reset",
  },
  "settings.generated_file_directory_pick_failed": {
    zh: "无法打开文件夹选择器，请重试。",
    en: "Could not open the folder picker. Please try again.",
  },
  "settings.cache": {
    zh: "缓存管理",
    en: "Cache Management",
  },
  "settings.clear_cache": {
    zh: "清除缓存",
    en: "Clear Cache",
  },
  "settings.clear_cache_desc": {
    zh: "清除后端临时文件和缓存数据",
    en: "Clear backend temporary files and cached data",
  },
  "settings.cache_summary": {
    zh: "清除转换过程中产生的临时文件和缓存数据，回收存储空间。",
    en: "Remove temporary files and cached data created during conversion to reclaim storage space.",
  },
  "settings.cache_cleared": {
    zh: "缓存已清除",
    en: "Cache cleared",
  },
  "settings.cache_cleared_detail": {
    zh: "已清除 {count} 个临时文件，释放 {size}",
    en: "Cleared {count} temporary files, freed {size}",
  },
  "settings.cache_clear_failed": {
    zh: "清除缓存失败，请稍后重试",
    en: "Failed to clear cache. Please try again.",
  },

  // ==================== Settings Panel (Solver Cache Density) ====================
  "settings.advanced": {
    zh: "高级",
    en: "Advanced",
  },
  "settings.completion_notifications_heading": {
    zh: "完成通知",
    en: "Completion notifications",
  },
  "settings.completion_notifications_description": {
    zh: "预览、模型、批量或校准生成完成时发送系统通知；此设置仅保存在当前浏览器。",
    en: "Send a system notification when preview, model, batch, or calibration generation finishes. This setting is stored only in this browser.",
  },
  "settings.completion_notifications_enable_label": {
    zh: "完成通知",
    en: "Completion notifications",
  },
  "settings.completion_notifications_hint": {
    zh: "开启时浏览器会申请通知权限；允许后，完成提醒会显示在 Windows 通知中心或 macOS 通知中心。",
    en: "Enabling this asks the browser for notification permission. Once allowed, completion alerts appear in Windows Notification Center or macOS Notification Center.",
  },
  "settings.completion_notifications_granted": {
    zh: "浏览器已允许通知。开启后，此设备会收到完成提醒。",
    en: "Browser permission is granted. When enabled, this device will receive completion alerts.",
  },
  "settings.completion_notifications_denied": {
    zh: "浏览器已拒绝通知权限，功能保持关闭。请在浏览器的网站通知设置中允许；macOS 还需确认“系统设置 > 通知”未关闭浏览器通知。",
    en: "The browser denied notification permission, so the feature remains off. Allow it in the browser's website notification settings; on macOS, also check that the browser is enabled under System Settings > Notifications.",
  },
  "settings.completion_notifications_default": {
    zh: "尚未授予浏览器通知权限。开启时浏览器会询问；若关闭或忽略提示，功能会保持关闭。",
    en: "Browser notification permission has not been granted. The browser will ask when you enable it; dismissing the prompt keeps the feature off.",
  },
  "settings.completion_notifications_unsupported": {
    zh: "当前浏览器不支持通知，功能保持关闭。",
    en: "This browser does not support notifications, so the feature remains off.",
  },
  "settings.completion_notifications_request_failed": {
    zh: "请求浏览器通知权限失败，功能保持关闭。请稍后重试。",
    en: "The notification permission request failed, so the feature remains off. Please try again later.",
  },
  "settings.solver_cache_density_heading": {
    zh: "颜色计算精度",
    en: "Color calculation quality",
  },
  "settings.solver_cache_density_description": {
    zh: "允许选择更细的颜色搜索网格；精度越高，颜色匹配越细，查找时间也会略有增加。",
    en: "Use a finer color-search grid for tighter matching, with a small increase in lookup time at higher tiers.",
  },
  "settings.solver_cache_density_enable_label": {
    zh: "颜色计算精度",
    en: "Color calculation quality",
  },
  "settings.solver_cache_density_default_hint": {
    zh: "当前使用标准精度（64³）。",
    en: "Currently using standard quality (64³).",
  },
  "settings.solver_cache_density_select_label": {
    zh: "穷举数量",
    en: "Exhaustive density",
  },
  "settings.solver_cache_density_option_64": {
    zh: "低（64³）",
    en: "Low (64³)",
  },
  "settings.solver_cache_density_option_128": {
    zh: "中（128³）",
    en: "Medium (128³)",
  },
  "settings.solver_cache_density_option_256": {
    zh: "高（256³）",
    en: "High (256³)",
  },
  "settings.solver_cache_density_option_512": {
    zh: "极高（512³）",
    en: "Very high (512³)",
  },
  "settings.solver_cache_density_option_1024": {
    zh: "极致（1024³）",
    en: "Ultra (1024³)",
  },
  "settings.solver_cache_density_option_2048": {
    zh: "极致+（2048³，覆盖全部可达配方）",
    en: "Ultra+ (2048³, captures every reachable recipe)",
  },
  "settings.solver_cache_density_tip": {
    zh: "构建采用稀疏存储，内存只随实际可达配方数增长（与档位无关），极致档也不会爆内存；查找时间会随档位略有增加，但通常仍是毫秒级。改动后旧缓存不会被覆盖，首次点击「构建」时会产生对应分辨率的新缓存文件。",
    en: "Builds use sparse storage, so memory grows with the number of physically reachable recipes (not with the tier) — even the ultra tiers stay lightweight. Per-lookup time grows mildly with tier but typically stays in the millisecond range. Existing caches are not overwritten — the first build at a new resolution produces a separate cache file.",
  },
  "settings.material_delta_e00_tolerance_heading": {
    zh: "动态叠层颜色容差",
    en: "Dynamic-layer color tolerance",
  },
  "settings.material_delta_e00_tolerance_description": {
    zh: "控制动态材料模式可用多少综合色差换取更短的有效配方。",
    en: "Controls how much color difference dynamic material mode may trade for a shorter effective recipe.",
  },
  "settings.material_delta_e00_tolerance_label": {
    zh: "动态叠层 ΔE00 容差",
    en: "Dynamic-layer ΔE00 tolerance",
  },
  "settings.material_delta_e00_tolerance_hint": {
    zh: "程序先求出范围内的精确 CIEDE2000 最佳值，再选择不超过最佳值加此容差的最短配方。允许范围 0.0–5.0，步进 0.1。",
    en: "The solver first finds the exact CIEDE2000 optimum in range, then chooses the shortest recipe no worse than that optimum plus this tolerance. Allowed range: 0.0–5.0 in 0.1 steps.",
  },
  "settings.svg_pixels_per_mm_heading": {
    zh: "SVG 清晰度",
    en: "SVG clarity",
  },
  "settings.svg_pixels_per_mm_description": {
    zh: "仅控制高保真模式下 SVG 转为像素图时的清晰度；矢量模式不受影响。",
    en: "Controls SVG rasterization clarity only in High-Fidelity mode; Vector mode is unaffected.",
  },
  "settings.svg_pixels_per_mm_scope": {
    zh: "仅适用于高保真模式下的 SVG；矢量模式不受影响。",
    en: "Only applies to SVG in High-Fidelity mode; Vector mode is unaffected.",
  },
  "settings.svg_pixels_per_mm_label": {
    zh: "采样密度",
    en: "Sampling density",
  },
  "settings.svg_pixels_per_mm_tip": {
    zh: "仅在“高保真”模式处理 SVG 图片时生效；数值越大边缘越细，处理时间和内存占用也会增加。允许范围 2.0–50.0，步进 0.1。",
    en: "Only affects SVG images processed in High-Fidelity mode. Higher values preserve finer edges but increase processing time and memory use. Allowed range: 2.0–50.0 in 0.1 steps.",
  },
  "settings.svg_pixels_per_mm_reset": {
    zh: "恢复默认",
    en: "Reset default",
  },
  "settings.svg_pixels_per_mm_default_hint": {
    zh: "默认值为 10.0 像素/毫米。",
    en: "The default is 10.0 px/mm.",
  },
  "settings.smooth_vector_preview_heading": {
    zh: "平滑 SVG 轻量预览",
    en: "Smooth lightweight SVG preview",
  },
  "settings.smooth_vector_preview_description": {
    zh: "优先用 SVG 原始轮廓生成平滑、轻量的浏览器 3D 模型；关闭后回退旧版像素分区预览。",
    en: "Prefer smooth, lightweight browser 3D geometry from the original SVG outlines; turn it off to use the legacy pixel-segmented preview.",
  },
  "settings.smooth_vector_preview_hint": {
    zh: "默认开启，仅影响原生矢量模式的浏览器 3D 显示，不改变 3MF、材料或打印质量。可在兼容性排查时临时关闭。",
    en: "On by default. This affects only browser 3D display for native Vector mode; it does not change the 3MF, materials, or print quality. Turn it off temporarily for compatibility troubleshooting.",
  },
  "settings.smooth_vector_preview_help_aria": {
    zh: "关于平滑 SVG 轻量预览",
    en: "About smooth lightweight SVG preview",
  },
  "settings.auto_replace_gradient_heading": {
    zh: "自动清理渐变条纹",
    en: "Clean gradient banding automatically",
  },
  "settings.auto_replace_gradient_description": {
    zh: "预览完成后，将同一渐变中的近似耗材色合并为代表色；仍可在颜色工作站撤销或继续调整。",
    en: "After preview, merge similar material colors in each gradient into one representative color. You can still undo or refine it in the Color Workstation.",
  },
  "settings.auto_replace_gradient_label": {
    zh: "自动清理渐变条纹",
    en: "Clean gradient banding automatically",
  },
  "settings.auto_replace_gradient_default_hint": {
    zh: "默认关闭：预览保留原始渐变，由你在颜色工作站里按需替换。",
    en: "Off by default: previews keep the original banded gradient, you apply the fix manually from the Color Workstation.",
  },
  "settings.auto_replace_gradient_tip": {
    zh: "开启后渐变较多的图片在预览后会略慢一步出现最终效果（需要额外的批量替换）。若关闭，同样的功能仍可在颜色工作站里手动使用。",
    en: "With this on, images rich in gradients show the final banding-free result a beat later (extra batch replacement runs). Turning it off keeps the same capability available as a manual action in the Color Workstation.",
  },

  // ==================== Settings Panel (Slicer Settings) ====================
  "settings.slicer_settings": {
    zh: "切片软件设置",
    en: "Slicer Settings",
  },
  "settings.slicer_software": {
    zh: "切片软件",
    en: "Slicer Software",
  },
  "settings.printer_model": {
    zh: "打印机型号",
    en: "Printer Model",
  },
  "settings.printer_options_load_failed": {
    zh: "打印机列表加载失败：{error}",
    en: "Failed to load printer options: {error}",
  },
  "settings.slicer_options_load_failed": {
    zh: "切片器列表加载失败：{error}",
    en: "Failed to load slicer options: {error}",
  },
  "settings.bed_size": {
    zh: "打印床尺寸",
    en: "Bed Size",
  },
  "settings.nozzle_size": {
    zh: "喷嘴尺寸",
    en: "Nozzle Size",
  },
  "settings.device_profile": {
    zh: "设备配置",
    en: "Device Profile",
  },
  "settings.template_title": {
    zh: "3MF 项目模板",
    en: "3MF project template",
  },
  "settings.template_builtin": {
    zh: "使用内置配置",
    en: "Use built-in settings",
  },
  "settings.template_summary": {
    zh: "导入当前切片软件保存的单盘 3MF 项目，沿用其中的耗材和全局工艺设置。模板须与所选打印机、喷嘴和切片软件匹配；不匹配时会报错。",
    en: "Import a single-plate 3MF saved by the selected slicer to reuse its material and global process settings. The template must match the selected printer, nozzle and slicer; mismatches produce an error.",
  },
  "settings.template_compatibility_note": {
    zh: "模板须匹配当前打印机、喷嘴和切片软件，不匹配时会报错。",
    en: "The template must match the current printer, nozzle, and slicer; mismatches produce an error.",
  },
  "settings.template_hint": {
    zh: "保留模板的速度、加速度、温度、流量、回抽和冷却设置。模型使用模板耗材槽位，槽位数量按生成流程保留或收紧。Lumina 按模型需要覆盖层高、线宽、墙层、顶底壳层和填充率；擦料塔按下方自动摆放选项处理。原模型、局部参数和修改器不导入。",
    en: "Keeps the template's speed, acceleration, temperature, flow, retraction and cooling settings. The model uses template material slots; the workflow retains or compacts the slot table. Lumina overrides layer height, line width, walls, shells and infill as required by the model. Tower handling follows the automatic placement option below. Source geometry, local settings and modifiers are not imported.",
  },
  "settings.template_excluded": {
    zh: "支持图像、矢量、材料档案、大幅分块和模型覆面导出。批量、拼图、校准和色块生成请先选择内置配置。",
    en: "Supports image, vector, material-archive, large-format and model-surface exports. Select built-in settings for batch, puzzle, calibration and swatch generation.",
  },
  "settings.template_active_scope_hint": {
    zh: "当前已选自定义模板；批量、拼图、校准和色块生成需先切回内置配置。",
    en: "A custom template is selected. Switch to built-in settings before batch, puzzle, calibration or swatch generation.",
  },
  "settings.template_missing_option": {
    zh: "所选模板在本机不可用",
    en: "Selected template unavailable on this device",
  },
  "settings.template_missing": {
    zh: "模板仅保存在本机，分享配方不会携带模板文件。请在本机导入原项目并重新选择，或切回内置配置；生成时不会静默替换模板。",
    en: "Templates are stored locally; shared recipes do not contain the template file. Import the source project on this device and select it again, or choose built-in settings. Generation will not silently replace the template.",
  },
  "settings.template_name": {
    zh: "模板名称（可选）",
    en: "Template name (optional)",
  },
  "settings.template_file": {
    zh: "3MF 项目文件",
    en: "3MF project file",
  },
  "settings.template_choose_file": {
    zh: "选择 3MF 文件",
    en: "Choose 3MF file",
  },
  "settings.template_change_file": {
    zh: "重新选择文件",
    en: "Choose another file",
  },
  "settings.template_metadata": {
    zh: "{printer} · {slicer} · {nozzle} mm · {count} 个耗材槽位",
    en: "{printer} · {slicer} · {nozzle} mm · {count} material slots",
  },
  "settings.template_import": {
    zh: "导入模板",
    en: "Import template",
  },
  "settings.template_delete": {
    zh: "删除模板",
    en: "Delete template",
  },
  "settings.template_load_error": {
    zh: "无法加载模板，请重新打开设置重试。",
    en: "Could not load templates. Reopen Settings to retry.",
  },
  "settings.template_file_error": {
    zh: "请选择 .3mf 项目文件。",
    en: "Choose a .3mf project file.",
  },
  "settings.template_import_error": {
    zh: "模板导入失败：",
    en: "Template import failed:",
  },
  "settings.template_delete_error": {
    zh: "模板删除失败，请重试：",
    en: "Could not delete the template. Retry:",
  },
  "settings.base_layer_height_modifier": {
    zh: "底板层高修改器",
    en: "Base-plate layer-height modifier",
  },
  "settings.base_layer_height_modifier_desc": {
    zh: "生成 3MF 时会计入固定首层，并选择能准确落在底板边界、且符合当前机型限制的较粗层高，缩短底板耗时并避免余数导致少层。仅对当前设置中选择的兼容切片软件生效，并使用各自的机器配置；浮雕、双面模型或没有安全可选值时会自动跳过。",
    en: "When generating a 3MF, this accounts for the fixed first layer and selects a compatible coarser height that lands exactly on the backing boundary and fits the selected printer. It applies only to the compatible slicer selected in Settings and uses that slicer's own machine profile; reliefs, double-sided prints, and cases where no safe value exists are skipped.",
  },
  "settings.wipe_tower_auto_placement": {
    zh: "擦料塔自动摆放",
    en: "Automatic wipe-tower placement",
  },
  "settings.wipe_tower_auto_placement_desc": {
    zh: "生成 3MF 时，Lumina 会根据所选打印机的可打印区域自动移动模型，并调整擦料塔的位置和尺寸来避免碰撞。关闭后会保留切片软件模板里的擦料塔参数，需要你在切片软件中自行检查和调整。",
    en: "When generating a 3MF, Lumina uses the selected printer's build area to move the model and adjust the wipe tower's position and size to avoid collisions. Turn this off to keep the slicer template's tower settings and check the layout manually in your slicer.",
  },
  "settings.custom_slicer_path": {
    zh: "手动切片软件路径",
    en: "Manual slicer app path",
  },
  "settings.prusa_preview_help": {
    zh: "Prusa 工程使用 3.0.0-alpha12 预览版格式。多色导出需要 MMU 或足够的打印头；当前内置配置提供原生默认 0.4 mm 喷嘴。",
    en: "Prusa projects use the 3.0.0-alpha12 preview format. Multicolor exports need an MMU or enough print heads. Bundled profiles use the native default 0.4 mm nozzle.",
  },
  "settings.custom_slicer_path_help": {
    zh: "macOS 可粘贴 .app 路径，例如 /Applications/Bambu Studio.app；保存后会优先用于打开 3MF。",
    en: "On macOS, paste a .app path such as /Applications/Bambu Studio.app. Saved paths are preferred when opening 3MF files.",
  },
  "settings.custom_slicer_path_placeholder": {
    zh: "/Applications/Bambu Studio.app",
    en: "/Applications/Bambu Studio.app",
  },
  "settings.custom_slicer_save": {
    zh: "校验并保存",
    en: "Validate & Save",
  },
  "settings.custom_slicer_clear": {
    zh: "清除",
    en: "Clear",
  },
  "settings.nozzle_count": {
    zh: "喷头数量",
    en: "Nozzle Count",
  },
  "settings.dual_head": {
    zh: "双头",
    en: "Dual Head",
  },
  "settings.single_head": {
    zh: "单头",
    en: "Single Head",
  },
  "loading.generating": {
    zh: "模型生成中...",
    en: "Generating model...",
  },

  // ==================== App Header ====================
  app_header_title: {
    zh: "Lumina Studio 2",
    en: "Lumina Studio 2",
  },
  app_checking_backend: {
    zh: "正在检查后端…",
    en: "Checking backend…",
  },
  app_backend_connected: {
    zh: "后端已连接",
    en: "Backend Connected",
  },
  app_backend_unreachable: {
    zh: "后端不可达",
    en: "Backend Unreachable",
  },
  app_reset_layout: {
    zh: "重置布局",
    en: "Reset Layout",
  },
  app_3d_scene_error: {
    zh: "3D 场景加载失败",
    en: "3D scene failed to load",
  },
  viewer_scene_recovery_hint: {
    zh: "可以重试加载 3D 预览，图片和参数会保留。若仍失败，请检查浏览器的图形加速设置。",
    en: "Retry the 3D preview; your image and settings are kept. If it still fails, check your browser's graphics acceleration settings.",
  },
  viewer_retry_scene: {
    zh: "重试 3D 预览",
    en: "Retry 3D preview",
  },
  viewer_lighting_fallback: {
    zh: "环境光照加载失败，已使用基础光照。",
    en: "Environment lighting could not load. Using basic lighting.",
  },
  viewer_retry_lighting: {
    zh: "重试光照",
    en: "Retry lighting",
  },
  app_toggle_language: {
    zh: "切换语言",
    en: "Toggle language",
  },
  app_toggle_theme: {
    zh: "切换主题",
    en: "Toggle theme",
  },
  app_quit_confirm_title: {
    zh: "退出确认",
    en: "Quit Confirmation",
  },
  app_quit_confirm_message: {
    zh: "确定要退出 Lumina Studio 吗？",
    en: "Are you sure you want to quit Lumina Studio?",
  },
  app_quit_quit: {
    zh: "退出",
    en: "Quit",
  },
  app_quit_cancel: {
    zh: "取消",
    en: "Cancel",
  },

  // ==================== LUT Manager Panel ====================
  lut_manager_title: {
    zh: "LUT 合并工具",
    en: "LUT Merge Tool",
  },
  lut_manager_desc: {
    zh: "将多个 LUT 合并为一个，支持 Delta-E 去重。主 LUT 必须为 6-Color 或 8-Color 模式。",
    en: "Merge multiple LUTs into one with Delta-E dedup. Primary LUT must be 6-Color or 8-Color mode.",
  },
  lut_manager_primary_label: {
    zh: "主 LUT",
    en: "Primary LUT",
  },
  lut_manager_primary_placeholder: {
    zh: "选择主 LUT...",
    en: "Select primary LUT...",
  },
  lut_manager_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  lut_manager_primary_mode_invalid: {
    zh: "主 LUT 必须为 6-Color 或 8-Color 模式",
    en: "Primary LUT must be 6-Color or 8-Color mode",
  },
  lut_manager_secondary_label: {
    zh: "副 LUT",
    en: "Secondary LUTs",
  },
  lut_manager_no_secondary: {
    zh: "无可用的副 LUT",
    en: "No secondary LUTs available",
  },
  lut_manager_select_primary_first: {
    zh: "请先选择主 LUT",
    en: "Please select a primary LUT first",
  },
  lut_manager_dedup_label: {
    zh: "去重阈值",
    en: "Dedup Threshold",
  },
  lut_manager_dedup_hint: {
    zh: "0 = 仅精确去重，值越大去除越多相近色",
    en: "0 = exact dedup only, higher = remove more similar colors",
  },
  lut_manager_merge_btn: {
    zh: "合并并保存",
    en: "Merge & Save",
  },
  lut_manager_merge_success: {
    zh: "✓ 合并成功！",
    en: "✓ Merge successful!",
  },
  lut_manager_merge_before: {
    zh: "合并前",
    en: "Before",
  },
  lut_manager_merge_after: {
    zh: "合并后",
    en: "After",
  },
  lut_manager_exact_dupes: {
    zh: "精确去重",
    en: "Exact dupes",
  },
  lut_manager_similar_removed: {
    zh: "相近色去除",
    en: "Similar removed",
  },
  lut_manager_file: {
    zh: "文件",
    en: "File",
  },
  lut_manager_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  lut_manager_mode_summary: {
    zh: "模式 {mode} · 共 {count} 色",
    en: "Mode {mode} · {count} colors",
  },
  lut_manager_selected_count: {
    zh: "已选择 {count} 个副 LUT",
    en: "{count} secondary LUTs selected",
  },

  // ==================== LUT Details Panel ====================
  lut_details_title: {
    zh: "LUT 详情浏览",
    en: "LUT Details Browser",
  },
  lut_details_desc: {
    zh: "查找 LUT，并查看其颜色、材料和分布图。",
    en: "Find LUTs and inspect their colors, materials, and distribution charts.",
  },
  lut_details_query_label: {
    zh: "筛选 LUT",
    en: "Filter LUTs",
  },
  lut_details_query_placeholder: {
    zh: "输入名称、材料或别名",
    en: "Search by name, material, or alias",
  },
  lut_details_manufacturer_label: {
    zh: "制造商",
    en: "Manufacturer",
  },
  lut_details_manufacturer_placeholder: {
    zh: "选择制造商...",
    en: "Select manufacturer...",
  },
  lut_details_lut_label: {
    zh: "LUT 方案",
    en: "LUT",
  },
  lut_details_lut_placeholder: {
    zh: "选择 LUT...",
    en: "Select LUT...",
  },
  lut_details_load_action: {
    zh: "加载 LUT",
    en: "Load LUT",
  },
  lut_details_load_hint: {
    zh: "选择 LUT 后点击加载。",
    en: "Select a LUT, then click load.",
  },
  lut_details_pending_loaded_notice: {
    zh: "当前显示的是已加载 LUT，点击加载后更新。",
    en: "You are viewing the loaded LUT. Click load to update it.",
  },
  lut_details_loading_selected: {
    zh: "正在加载所选 LUT...",
    en: "Loading selected LUT...",
  },
  lut_details_catalog_loading: {
    zh: "正在加载 LUT 目录...",
    en: "Loading LUT catalog...",
  },
  lut_details_close_error: {
    zh: "关闭错误",
    en: "Dismiss error",
  },
  lut_details_no_matches: {
    zh: "没有匹配的 LUT，请调整筛选条件。",
    en: "No LUTs match the current filters.",
  },
  lut_details_summary_title: {
    zh: "摘要",
    en: "Summary",
  },
  lut_details_summary_desc: {
    zh: "当前 LUT 的基本信息。",
    en: "Core information for the current LUT.",
  },
  lut_details_no_detail: {
    zh: "请选择一个 LUT。",
    en: "Select a LUT.",
  },
  lut_details_loading: {
    zh: "加载详情中...",
    en: "Loading details...",
  },
  lut_details_error_load_catalog: {
    zh: "LUT 详情目录加载失败",
    en: "Failed to load LUT details catalog",
  },
  lut_details_error_load_detail: {
    zh: "LUT 详情加载失败",
    en: "Failed to load LUT details",
  },
  lut_error_missing_refresh: {
    zh: "该 LUT 已不存在，请刷新列表后重试。",
    en: "The selected LUT no longer exists. Refresh the list and try again.",
  },
  lut_details_summary_name: {
    zh: "名称",
    en: "Name",
  },
  lut_details_summary_manufacturer: {
    zh: "制造商",
    en: "Manufacturer",
  },
  lut_details_summary_material: {
    zh: "材料",
    en: "Material",
  },
  lut_details_summary_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  lut_details_summary_color_count: {
    zh: "颜色数",
    en: "Color Count",
  },
  lut_details_summary_source_kind: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_details_summary_path: {
    zh: "公开引用",
    en: "Public reference",
  },
  lut_details_metadata_title: {
    zh: "类型化元数据",
    en: "Typed Metadata",
  },
  lut_details_metadata_desc: {
    zh: "结构化参数与打印设置。",
    en: "Structured parameters and print settings.",
  },
  lut_details_metadata_schema: {
    zh: "Schema",
    en: "Schema",
  },
  lut_details_metadata_manufacturer_source: {
    zh: "制造商来源",
    en: "Manufacturer Source",
  },
  lut_details_metadata_material_source: {
    zh: "材料来源",
    en: "Material Source",
  },
  lut_details_metadata_max_color_layers: {
    zh: "最大颜色层数",
    en: "Max Color Layers",
  },
  lut_details_metadata_layer_height: {
    zh: "层高",
    en: "Layer Height",
  },
  lut_details_metadata_line_width: {
    zh: "线宽",
    en: "Line Width",
  },
  lut_details_metadata_base_layers: {
    zh: "底层数",
    en: "Base Layers",
  },
  lut_details_metadata_base_channel: {
    zh: "基础通道",
    en: "Base Channel",
  },
  lut_details_metadata_layer_order: {
    zh: "层顺序",
    en: "Layer Order",
  },
  lut_details_metadata_coverage: {
    zh: "覆盖统计",
    en: "Coverage",
  },
  lut_details_coverage_summary: {
    zh: "{entries} 条记录 / {points} 个点",
    en: "{entries} entries / {points} plotted points",
  },
  lut_details_capabilities_title: {
    zh: "能力",
    en: "Capabilities",
  },
  lut_details_capabilities_desc: {
    zh: "该 LUT 声明的能力。",
    en: "Capabilities declared by this LUT.",
  },
  lut_details_capabilities_empty: {
    zh: "无能力信息",
    en: "No capabilities",
  },
  lut_details_supported_modes_title: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  lut_details_supported_modes_desc: {
    zh: "可用的层数与层高组合。",
    en: "Available layer-count and layer-height combinations.",
  },
  lut_details_supported_modes_empty: {
    zh: "无支持模式",
    en: "No supported modes",
  },
  lut_details_supported_mode_item: {
    zh: "{layers} 层 · {height} mm",
    en: "{layers} layers · {height} mm",
  },
  lut_details_raw_metadata_title: {
    zh: "LUT 原始元数据",
    en: "Raw LUT Metadata",
  },
  lut_details_raw_metadata_desc: {
    zh: "",
    en: "",
  },
  lut_details_no_raw_metadata: {
    zh: "{}",
    en: "{}",
  },
  lut_details_palette_title: {
    zh: "调色板",
    en: "Palette",
  },
  lut_details_palette_desc: {
    zh: "颜色、材料与色值对应关系。",
    en: "Color, material, and color-value mappings.",
  },
  lut_details_palette_count: {
    zh: "{count} 项",
    en: "{count} entries",
  },
  lut_details_palette_color: {
    zh: "颜色",
    en: "Color",
  },
  lut_details_palette_material: {
    zh: "材料",
    en: "Material",
  },
  lut_details_palette_hex: {
    zh: "HEX",
    en: "Hex",
  },
  lut_details_palette_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  lut_details_no_palette: {
    zh: "没有调色板数据。",
    en: "No palette data.",
  },
  lut_details_lab_chart_title: {
    zh: "Lab 图",
    en: "Lab Chart",
  },
  lut_details_lab_chart_desc: {
    zh: "显示颜色在 Lab a*/b* 平面上的分布。X 轴为 a*，负方向偏绿、正方向偏红；Y 轴为 b*，负方向偏蓝、正方向偏黄。亮度维度 L* 在该图中不显示。",
    en: "Shows the color distribution on the Lab a*/b* plane. The X axis is a*, with negative values toward green and positive values toward red; the Y axis is b*, with negative values toward blue and positive values toward yellow. The L* lightness dimension is not shown in this chart.",
  },
  lut_details_lab_chart_3d_desc: {
    zh: "显示颜色在 Lab 三维空间中的分布。X 轴为 a*，负方向偏绿、正方向偏红；Y 轴为 L*，负方向更暗、正方向更亮；Z 轴为 b*，负方向偏蓝、正方向偏黄。",
    en: "Shows the color distribution in the Lab 3D space. The X axis is a*, with negative values toward green and positive values toward red; the Y axis is L*, with negative values darker and positive values lighter; the Z axis is b*, with negative values toward blue and positive values toward yellow.",
  },
  lut_details_lab_view_2d: {
    zh: "2D",
    en: "2D",
  },
  lut_details_lab_view_3d: {
    zh: "3D",
    en: "3D",
  },
  lut_details_lab_chart_x: {
    zh: "a* 轴",
    en: "a* axis",
  },
  lut_details_lab_chart_y: {
    zh: "b* 轴",
    en: "b* axis",
  },
  lut_details_lab_chart_footer: {
    zh: "L 范围: {lRange} | a 范围: {aRange} | b 范围: {bRange}",
    en: "L range: {lRange} | a range: {aRange} | b range: {bRange}",
  },
  lut_details_lab_3d_axis_x: {
    zh: "X = a*（-绿 / +红）",
    en: "X = a* (-green / +red)",
  },
  lut_details_lab_3d_axis_y: {
    zh: "Y = L*（暗 → 亮）",
    en: "Y = L* (dark -> light)",
  },
  lut_details_lab_3d_axis_z: {
    zh: "Z = b*（-蓝 / +黄）",
    en: "Z = b* (-blue / +yellow)",
  },
  lut_details_lab_3d_loading_hull: {
    zh: "正在生成 3D 外壳...",
    en: "Generating the 3D hull...",
  },
  lut_details_lab_3d_error_hull: {
    zh: "3D 外壳生成失败，已仅显示点云。",
    en: "The 3D hull failed to generate. Only the point cloud is shown.",
  },
  lut_details_lab_3d_reference_toggle: {
    zh: "参考切片",
    en: "Reference Slice",
  },
  lut_details_lab_3d_reference_status: {
    zh: "参考切片 · L* {lightness}",
    en: "Reference Slice · L* {lightness}",
  },
  lut_details_lab_3d_reference_slider: {
    zh: "参考切片 L*",
    en: "Reference Slice L*",
  },
  lut_details_rgb_chart_title: {
    zh: "RGB 投影视图",
    en: "RGB Projection Chart",
  },
  lut_details_rgb_chart_desc: {
    zh: "显示颜色在 RGB 空间中的整体分布趋势。由于采用二维等距投影表示，沿 R=G=B 的中性轴，也就是黑到白的第三维度，在该图中不直接显示，因此不适合用于精确读取单独通道值。",
    en: "Shows the overall distribution trend in RGB space. Because this chart uses a 2D isometric projection, the third dimension along the neutral R=G=B axis, from black to white, is not shown directly, so the chart is not suitable for precise single-channel readings.",
  },
  lut_details_rgb_chart_x: {
    zh: "投影 X",
    en: "Projection X",
  },
  lut_details_rgb_chart_y: {
    zh: "投影 Y",
    en: "Projection Y",
  },
  lut_details_rgb_chart_footer: {
    zh: "原始通道范围 R: {rRange} | G: {gRange} | B: {bRange}",
    en: "Raw channel ranges R: {rRange} | G: {gRange} | B: {bRange}",
  },
  lut_details_hue_lightness_chart_title: {
    zh: "色相 × 相对亮度",
    en: "Hue × Relative Lightness",
  },
  lut_details_hue_lightness_chart_desc: {
    zh: "显示各色相上的相对亮度分布，用于观察不同色相对应的亮度覆盖情况。饱和度维度在该图中不显示。",
    en: "Shows the relative lightness distribution across hues, so you can inspect the lightness coverage for each hue. The saturation dimension is not shown in this chart.",
  },
  lut_details_hue_lightness_chart_x: {
    zh: "色相 (°)",
    en: "Hue (°)",
  },
  lut_details_hue_lightness_chart_y: {
    zh: "相对亮度 (%)",
    en: "Relative Lightness (%)",
  },
  lut_details_hue_lightness_chart_footer: {
    zh: "相对亮度范围: {lRange} | 色相范围: {hRange}",
    en: "Relative lightness range: {lRange} | Hue range: {hRange}",
  },
  lut_details_hue_chroma_chart_title: {
    zh: "色相 × 饱和度",
    en: "Hue × Saturation",
  },
  lut_details_hue_chroma_chart_desc: {
    zh: "显示各色相上的相对饱和度分布，用于观察不同色相对应的饱和度覆盖情况。亮度维度在该图中不显示。",
    en: "Shows the relative saturation distribution across hues, so you can inspect the saturation coverage for each hue. The lightness dimension is not shown in this chart.",
  },
  lut_details_hue_chroma_chart_x: {
    zh: "色相 (°)",
    en: "Hue (°)",
  },
  lut_details_hue_chroma_chart_y: {
    zh: "相对饱和度 (%)",
    en: "Relative Saturation (%)",
  },
  lut_details_hue_chroma_chart_footer: {
    zh: "相对饱和度范围: {cRange} | 色相范围: {hRange}",
    en: "Relative saturation range: {cRange} | Hue range: {hRange}",
  },
  lut_details_hue_chart_omitted_neutral: {
    zh: "低饱和、色相未定义的点未显示：{count}",
    en: "Low-saturation points with undefined hue are not shown: {count}",
  },
  lut_details_no_chart_points: {
    zh: "暂无点位数据",
    en: "No point data available",
  },

  lut_compare_title: {
    zh: "LUT 对比工具",
    en: "LUT Compare Tool",
  },
  lut_compare_desc: {
    zh: "按同配方比较两个 LUT 的颜色偏移，适用于耗材、批次和重复校准的一致性分析。",
    en: "Compare two LUTs by shared recipe to measure material, batch, and calibration drift.",
  },
  lut_compare_lut_a_label: {
    zh: "基准 LUT",
    en: "Baseline LUT",
  },
  lut_compare_lut_b_label: {
    zh: "对比 LUT",
    en: "Comparison LUT",
  },
  lut_compare_lut_a_placeholder: {
    zh: "选择基准 LUT...",
    en: "Select baseline LUT...",
  },
  lut_compare_lut_b_placeholder: {
    zh: "选择对比 LUT...",
    en: "Select comparison LUT...",
  },
  lut_compare_compare_btn: {
    zh: "开始对比",
    en: "Compare LUTs",
  },
  lut_compare_result_title: {
    zh: "对比结果",
    en: "Comparison Result",
  },
  lut_compare_summary: {
    zh: "已比较 {lutA} 与 {lutB} 的 {count} 个共享配方。",
    en: "Compared {count} shared recipes between {lutA} and {lutB}.",
  },
  lut_compare_matched: {
    zh: "共享配方",
    en: "Shared Recipes",
  },
  lut_compare_coverage_a: {
    zh: "A 覆盖率",
    en: "A Coverage",
  },
  lut_compare_coverage_b: {
    zh: "B 覆盖率",
    en: "B Coverage",
  },
  lut_compare_mean: {
    zh: "平均 ΔE00",
    en: "Mean ΔE00",
  },
  lut_compare_p95: {
    zh: "P95 ΔE00",
    en: "P95 ΔE00",
  },
  lut_compare_max: {
    zh: "最大 ΔE00",
    en: "Max ΔE00",
  },
  lut_compare_identical: {
    zh: "RGB 完全一致",
    en: "Exact RGB Matches",
  },
  lut_compare_warnings_title: {
    zh: "注意事项",
    en: "Warnings",
  },
  lut_compare_warning_mode_mismatch: {
    zh: "LUT 模式不一致：{modeA} vs {modeB}",
    en: "LUT modes differ: {modeA} vs {modeB}",
  },
  lut_compare_warning_layer_count_mismatch: {
    zh: "配方层数不一致：{countA} vs {countB}",
    en: "Recipe layer counts differ: {countA} vs {countB}",
  },
  lut_compare_warning_layer_height_mismatch: {
    zh: "层高不一致：{values}",
    en: "Layer heights differ: {values}",
  },
  lut_compare_warning_line_width_mismatch: {
    zh: "线宽不一致：{values}",
    en: "Line widths differ: {values}",
  },
  lut_compare_warning_no_shared_recipes: {
    zh: "没有共享配方，统计结果已归零。",
    en: "No shared recipes were found, so comparison metrics were zeroed.",
  },
  lut_compare_warning_row_mismatch: {
    zh: "{label} 的 rgb/stacks 行数不一致：rgb={rgb}，stacks={stacks}；已仅使用前 {used} 行。",
    en: "{label} has mismatched rgb/stacks rows: rgb={rgb}, stacks={stacks}; only the first {used} rows were used.",
  },
  lut_compare_warning_duplicate_recipes: {
    zh: "{label} 存在 {count} 条重复配方记录；每个配方仅保留第一条。",
    en: "{label} contains {count} duplicate recipe rows; only the first row for each recipe was kept.",
  },
  lut_compare_warning_generic: {
    zh: "对比过程中返回了额外警告，请结合结果谨慎解读。",
    en: "Additional warnings were returned during comparison; please interpret the result with care.",
  },
  lut_compare_worst_title: {
    zh: "最大差异配方",
    en: "Largest Recipe Diffs",
  },
  lut_compare_worst_desc: {
    zh: "展示共享配方中差异最大的若干条目，帮助快速定位色偏最明显的配方。",
    en: "Shows the shared recipes with the largest differences so the biggest color shifts are easy to spot.",
  },
  lut_compare_delta: {
    zh: "ΔE00",
    en: "ΔE00",
  },
  lut_compare_no_result: {
    zh: "选择两个 LUT 后即可开始对比。",
    en: "Select two LUTs to start comparing.",
  },
  lut_compare_no_diffs: {
    zh: "当前没有可展示的共享配方差异。",
    en: "There are no shared recipe diffs to display.",
  },

  // ==================== Calibration Panel ====================
  cal_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  cal_color_mode_hint: {
    zh: "选择要生成的校准板颜色模式。",
    en: "Select the color mode for the calibration board.",
  },
  cal_block_size_label: {
    zh: "色块尺寸",
    en: "Block Size",
  },
  cal_block_size_hint: {
    zh: "定义单个色块的边长（毫米）。推荐值: 5.00mm。",
    en: "Define the edge length of a single block (in mm). Recommended: 5.00mm.",
  },
  cal_gap_label: {
    zh: "色块间距",
    en: "Block Gap",
  },
  cal_gap_hint: {
    zh: "定义相邻色块之间的间隙（毫米）。推荐值: 0.84mm。",
    en: "Define the gap between adjacent blocks (in mm). Recommended: 0.84mm.",
  },
  cal_backing_thickness_label: {
    zh: "底板厚度",
    en: "Backing Thickness",
  },
  cal_backing_thickness_hint: {
    zh: "调整底板层的物理厚度（毫米）。每一格对应一层打印层（0.08 mm），推荐值: 1.20 mm。",
    en: "Adjust the backing layer thickness in millimeters. Each tick equals one print layer (0.08 mm); recommended: 1.20 mm.",
  },
  cal_generate_btn_panel: {
    zh: "生成校准板",
    en: "Generate Calibration",
  },
  calibration_generation_failed: {
    zh: "校准板生成失败，请稍后重试。",
    en: "Calibration generation failed. Please try again.",
  },
  cal_download_3mf: {
    zh: "下载校准文件",
    en: "Download Calibration File",
  },
  cal_8color_full_export_label: {
    zh: "导出全部 8 色配方",
    en: "Export Full 8-Color Recipes",
  },
  cal_8color_full_export_hint: {
    zh: "生成多页 ZIP，每页包含 3MF 和对应配方 JSON，不影响现有两页提取流程。",
    en: "Generate a multi-page ZIP with a 3MF and matching recipe JSON for each page without changing the existing two-page extraction flow.",
  },
  cal_8color_full_export_on: {
    zh: "全量",
    en: "Full",
  },
  cal_8color_full_export_off: {
    zh: "精简",
    en: "Compact",
  },
  cal_preview_alt: {
    zh: "校准板预览",
    en: "Calibration preview",
  },

  // ==================== Extractor Panel ====================
  ext_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  ext_color_mode_hint: {
    zh: "选择与您打印的校准板对应的颜色模式。不同的模式会决定提取颜色时使用的色块数量和布局。",
    en: "Select the color mode corresponding to your printed calibration board. This determines the number and layout of color blocks extracted.",
  },
  ext_page_label: {
    zh: "校准板页码",
    en: "Board Page",
  },
  ext_page_hint: {
    zh: "选择当前上传照片对应的校准板页码。部分颜色模式（如 8色 或 5色扩展）由多张校准板组成。",
    en: "Select the page number for the current photo. Some color modes (like 8-Color or 5-Color Extended) span multiple boards.",
  },
  ext_page_number_prefix: {
    zh: "",
    en: "Page ",
  },
  ext_page_number_suffix: {
    zh: "号",
    en: "",
  },
  ext_upload_label: {
    zh: "上传校准板照片",
    en: "Upload Calibration Board Photo",
  },
  ext_offset_x_label: {
    zh: "水平偏移 (offset_x)",
    en: "Horizontal Offset (offset_x)",
  },
  ext_offset_x_hint: {
    zh: "水平方向位移校正。向右偏移为正，向左为负，单位为像素。",
    en: "Horizontal displacement correction. Positive moves right, negative moves left, in pixels.",
  },
  ext_offset_y_label: {
    zh: "垂直偏移 (offset_y)",
    en: "Vertical Offset (offset_y)",
  },
  ext_offset_y_hint: {
    zh: "垂直方向位移校正。向下偏移为正，向上为负，单位为像素。",
    en: "Vertical displacement correction. Positive moves down, negative moves up, in pixels.",
  },
  ext_zoom_label: {
    zh: "缩放 (zoom)",
    en: "Zoom",
  },
  ext_zoom_hint: {
    zh: "对检测到的棋盘格进行缩放校正。1.0 表示原始尺寸，小于 1 则缩小，大于 1 则放大。",
    en: "Scale correction for the detected checkerboard. 1.0 means original size; less than 1 shrinks, greater than 1 enlarges.",
  },
  ext_distortion_label: {
    zh: "畸变校正 (distortion)",
    en: "Distortion Correction",
  },
  ext_distortion_hint: {
    zh: "桶形/枕形畸变校正系数。正值矫正桶形畸变，负值矫正枕形畸变，0 表示不校正。",
    en: "Barrel/pincushion distortion correction coefficient. Positive corrects barrel distortion, negative corrects pincushion, zero disables correction.",
  },
  ext_vignette_label: {
    zh: "暗角校正",
    en: "Vignette Correction",
  },
  ext_vignette_hint: {
    zh: "自动检测并补偿镜头暗角导致的边缘亮度下降，使颜色提取更均匀准确。",
    en: "Automatically detects and compensates for edge brightness falloff caused by lens vignetting for more uniform and accurate color extraction.",
  },
  ext_auto_wb_label: {
    zh: "自动白平衡",
    en: "Auto White Balance",
  },
  ext_auto_wb_hint: {
    zh: "自动校正图像的白平衡，将白色参考块还原为标准白色，使整体色彩更准确。",
    en: "Automatically corrects the image white balance, restoring the white reference patch to standard white for more accurate overall colors.",
  },
  ext_colorchecker_label: {
    zh: "ColorChecker 校色",
    en: "ColorChecker Calibration",
  },
  ext_colorchecker_hint: {
    zh: "启用后将使用图片中的 ColorChecker 色卡计算颜色校正矩阵 (CCM)，先校正图片颜色再进行提取，适用于照片色温偏差较大的场景。",
    en: "When enabled, computes a Color Correction Matrix (CCM) from the ColorChecker card in the image, applying color correction before extraction. Useful when photos have significant color temperature deviation.",
  },
  ext_cc_step1_title: {
    zh: "第 1 步：标记 ColorChecker 色卡",
    en: "Step 1: Mark ColorChecker Card",
  },
  ext_cc_step1_hint: {
    zh: "请在图片上点击 ColorChecker 色卡的 4 个角点",
    en: "Click the 4 corners of the ColorChecker card in the image",
  },
  ext_cc_warp_btn: {
    zh: "生成预览",
    en: "Generate Preview",
  },
  ext_cc_calibrate_btn: {
    zh: "执行校色",
    en: "Calibrate",
  },
  ext_cc_clear_corners_btn: {
    zh: "清除色卡角点",
    en: "Clear Card Corners",
  },
  ext_cc_step_review_title: {
    zh: "检查采样点",
    en: "Review Patch Points",
  },
  ext_cc_step_review_hint: {
    zh: "下方为校色卡透视展开预览，标注了 24 个采样点。如有偏差，先选择编号再在图上点击新的位置来修正；确认无误后点击「执行校色」。",
    en: "Below is the warped ColorChecker preview with 24 sampling points. To adjust, select a patch number then click its correct position on the image. When satisfied, click Calibrate.",
  },
  ext_cc_step2_title: {
    zh: "第 2 步：标记校准板",
    en: "Step 2: Mark Calibration Board",
  },
  ext_cc_step2_hint: {
    zh: "校色完成，请在校正后的图片上点击校准板的 4 个角点，然后提取",
    en: "Calibration done. Click the 4 corners of the calibration board on the corrected image, then extract.",
  },
  ext_cc_dialog_title: {
    zh: "ColorChecker 色卡校色",
    en: "ColorChecker Calibration",
  },
  ext_cc_close_btn: {
    zh: "关闭",
    en: "Close",
  },
  ext_cc_open_dialog_btn: {
    zh: "打开校色工具",
    en: "Open Calibration Tool",
  },
  ext_cc_recalibrate_btn: {
    zh: "重新校色 / 替换",
    en: "Recalibrate / Replace",
  },
  ext_cc_auto_detect_btn: {
    zh: "自动定位色卡",
    en: "Auto Locate Card",
  },
  ext_cc_auto_detect_success: {
    zh: "已自动定位色卡",
    en: "Card auto-located",
  },
  ext_cc_auto_detect_failed: {
    zh: "自动定位失败，请手动点选四角",
    en: "Auto locate failed. Mark the four corners manually.",
  },
  ext_cc_corner_adjust_hint: {
    zh: "按顺序点选四角；点完后可拖动圆点，或先选中角点再在图片上点击新位置。",
    en: "Mark the four corners in order. After that, drag a handle or select a corner and click a new position.",
  },
  ext_cc_corner_label: {
    zh: "色卡角点",
    en: "Card corner",
  },
  ext_cc_patch_orientation_label: {
    zh: "色块方向",
    en: "Patch Order",
  },
  ext_cc_patch_orientation_normal: {
    zh: "正常",
    en: "Normal",
  },
  ext_cc_patch_orientation_rotate_180: {
    zh: "旋转 180°",
    en: "Rotated 180°",
  },
  ext_cc_patch_orientation_flip_horizontal: {
    zh: "水平镜像",
    en: "Mirrored Horizontally",
  },
  ext_cc_patch_orientation_flip_vertical: {
    zh: "垂直镜像",
    en: "Mirrored Vertically",
  },
  ext_cc_missing_image: {
    zh: "请先选择图片",
    en: "Choose an image first",
  },
  ext_cc_status_preparing: {
    zh: "正在生成校色预览",
    en: "Preparing calibration preview",
  },
  ext_cc_upload_progress: {
    zh: "正在上传原图 {percent}%",
    en: "Uploading source image {percent}%",
  },
  ext_cc_upload_progress_label: {
    zh: "原图上传进度",
    en: "Source image upload progress",
  },
  ext_cc_source_prepare_timeout: {
    zh: "校色器原图上传或预览生成超时。图片较大或网络较慢时可能发生，请重试或使用更快网络。",
    en: "Timed out while uploading the source image or preparing its preview. This can happen with large images or slow networks. Please retry or use a faster connection.",
  },
  ext_cc_source_prepare_failed: {
    zh: "原图上传或预览生成失败，请重试。",
    en: "Failed to upload the source image or prepare its preview. Please retry.",
  },
  ext_cc_auto_detect_timeout: {
    zh: "ColorChecker 自动识别超时。请重试，或手动点选四个色卡角点。",
    en: "ColorChecker auto detection timed out. Please retry or mark the four chart corners manually.",
  },
  ext_cc_warp_timeout: {
    zh: "ColorChecker 透视预览生成超时。请重试，或检查角点是否框住完整色卡。",
    en: "ColorChecker warp preview generation timed out. Please retry or check that the corners bound the full chart.",
  },
  ext_cc_calibrate_timeout: {
    zh: "ColorChecker 校色计算超时。请重试；大 RAW/DNG 图片可能需要更长处理时间。",
    en: "ColorChecker calibration timed out. Please retry; large RAW/DNG images can need more processing time.",
  },
  ext_cc_warp_ready: {
    zh: "透视预览已生成，可执行校色",
    en: "Warp preview is ready. You can calibrate now.",
  },
  ext_cc_warp_failed: {
    zh: "透视预览生成失败",
    en: "Failed to generate warp preview",
  },
  ext_cc_calibrate_failed: {
    zh: "校色失败",
    en: "Calibration failed",
  },
  ext_cc_result_ready: {
    zh: "校色完成，请检查结果后确认使用。",
    en: "Calibration is complete. Review the result before accepting it.",
  },
  ext_cc_confirm_preview_failed: {
    zh: "校色预览加载失败，请重试或重新执行校色。",
    en: "Failed to load the calibrated preview. Try again or recalibrate.",
  },
  ext_cc_metric_mean: {
    zh: "平均",
    en: "Mean",
  },
  ext_cc_metric_median: {
    zh: "中位",
    en: "Median",
  },
  ext_cc_metric_p95: {
    zh: "P95",
    en: "P95",
  },
  ext_cc_metric_worst: {
    zh: "最差",
    en: "Worst",
  },
  ext_cc_metric_worst_patch: {
    zh: "最差色块",
    en: "Worst Patch",
  },
  ext_cc_metric_delta_e00: {
    zh: "DeltaE00",
    en: "DeltaE00",
  },
  ext_cc_luminance_curve: {
    zh: "亮度曲线",
    en: "Luminance Curve",
  },
  ext_cc_no_curve: {
    zh: "暂无曲线",
    en: "No curve",
  },
  ext_cc_calibrated_badge: {
    zh: "已校色 ✓",
    en: "Calibrated ✓",
  },
  ext_cc_confirm_title: {
    zh: "校色结果确认",
    en: "Calibration Result",
  },
  ext_cc_confirm_body: {
    zh: "请检查下方校色后的图片。如果颜色看起来正确，点击「确认使用」将此校色结果用于后续提取；否则点击「重新校色」重新标记角点。",
    en: "Review the calibrated image below. If colors look correct, click Accept to use it for extraction; otherwise click Retry to re-mark corners.",
  },
  ext_cc_compare_original: {
    zh: "原图",
    en: "Original",
  },
  ext_cc_compare_calibrated: {
    zh: "校准后",
    en: "Calibrated",
  },
  ext_cc_confirm_accept: {
    zh: "确认使用",
    en: "Accept",
  },
  ext_cc_confirm_reject: {
    zh: "重新校色",
    en: "Retry",
  },
  ext_cc_main_area_hint: {
    zh: "24 色卡校色会在弹窗中进行，完成并确认后再继续选择 LUT 色卡四角。",
    en: "The 24-patch correction runs in a popup. Continue picking LUT corners after you confirm.",
  },
  ext_cc_main_area_hint_upload: {
    zh: "上传校准板照片后会自动弹出校色窗口；也可以稍后点「打开校色工具」手动打开。",
    en: "Uploading the calibration board photo opens the correction popup automatically. You can also reopen it later with Open Calibration Tool.",
  },
  ext_cc_advanced_toggle: {
    zh: "高级选项",
    en: "Advanced Options",
  },
  ext_cc_advanced_hint: {
    zh: "默认使用 3x3 矩阵校色。只有需要对比算法、采样方式或灰阶归一化时再打开。",
    en: "The default uses a 3x3 matrix. Enable this only when comparing algorithms, sampling, or gray-axis normalization.",
  },
  ext_cc_algorithm_label: {
    zh: "校色算法",
    en: "Calibration Algorithm",
  },
  ext_cc_algorithm_matrix_3x3: {
    zh: "3x3 矩阵（默认）",
    en: "3x3 Matrix (Default)",
  },
  ext_cc_algorithm_matrix_3x4: {
    zh: "3x4 仿射矩阵",
    en: "3x4 Affine Matrix",
  },
  ext_cc_algorithm_root_polynomial: {
    zh: "二阶 Root-Polynomial",
    en: "Degree-2 Root-Polynomial",
  },
  ext_cc_algorithm_auto: {
    zh: "自动选择",
    en: "Auto",
  },
  ext_cc_sampling_method_label: {
    zh: "采样方式",
    en: "Sampling Method",
  },
  ext_cc_sampling_mean: {
    zh: "平均值",
    en: "Mean",
  },
  ext_cc_sampling_median: {
    zh: "中位数",
    en: "Median",
  },
  ext_cc_gray_affine_label: {
    zh: "灰阶归一化",
    en: "Gray Normalization",
  },
  ext_cc_gray_affine_auto: {
    zh: "自动",
    en: "Auto",
  },
  ext_cc_gray_affine_enabled: {
    zh: "强制启用",
    en: "Force On",
  },
  ext_cc_gray_affine_fallback: {
    zh: "回退模式",
    en: "Fallback",
  },
  ext_cc_sample_radius_label: {
    zh: "采样半径",
    en: "Sample Radius",
  },
  ext_cc_blur_radius_label: {
    zh: "输出柔化",
    en: "Output Blur",
  },
  ext_cc_reference_label: {
    zh: "当前基准",
    en: "Reference",
  },
  ext_cc_reference_builtin: {
    zh: "内置 24 色卡基准",
    en: "Built-in 24-patch reference",
  },
  ext_cc_reference_meta: {
    zh: "{count} 个色块 · Lab 白点 {whitePoint}",
    en: "{count} patches · Lab white point {whitePoint}",
  },
  ext_cc_reference_select_title: {
    zh: "校色基准",
    en: "Calibration Reference",
  },
  ext_cc_reference_select_hint: {
    zh: "检测评分和校色拟合会使用同一个基准。",
    en: "Detection scoring and calibration fitting use the same reference.",
  },
  ext_cc_reference_select_label: {
    zh: "选择基准",
    en: "Select reference",
  },
  ext_cc_reference_group_server: {
    zh: "服务端预设",
    en: "Server presets",
  },
  ext_cc_reference_group_custom: {
    zh: "自定义基准",
    en: "Custom references",
  },
  ext_cc_reference_upload_btn: {
    zh: "上传 .xlsx",
    en: "Upload .xlsx",
  },
  ext_cc_reference_delete_btn: {
    zh: "删除自定义",
    en: "Delete custom",
  },
  ext_cc_reference_upload_ready: {
    zh: "校色基准已上传并选中",
    en: "Reference uploaded and selected",
  },
  ext_cc_reference_upload_ready_with_warnings: {
    zh: "校色基准已上传并选中，{count} 条提示",
    en: "Reference uploaded and selected with {count} warnings",
  },
  ext_cc_reference_upload_ready_session_only: {
    zh: "校色基准已用于当前会话，但浏览器阻止保存，刷新页面后需要重新上传。",
    en: "Reference is selected for this session, but the browser blocked saving it. Upload it again after refreshing.",
  },
  ext_cc_reference_upload_failed: {
    zh: "校色基准上传失败",
    en: "Reference upload failed",
  },
  ext_cc_reference_load_failed: {
    zh: "校色基准列表加载失败",
    en: "Failed to load references",
  },
  ext_cc_reference_serial: {
    zh: "SN：{serial}",
    en: "SN: {serial}",
  },
  ext_cc_algorithm_meta: {
    zh: "{method} 采样 · 灰阶 {gray}",
    en: "{method} sampling · Gray {gray}",
  },
  ext_cc_unknown_value: {
    zh: "未知",
    en: "Unknown",
  },
  ext_cc_overlay_title: {
    zh: "色卡检查图",
    en: "Patch Check View",
  },
  ext_cc_no_overlay: {
    zh: "暂无检查图",
    en: "No check view",
  },
  ext_cc_warning_title: {
    zh: "校色质量提示",
    en: "Correction Quality Notice",
  },
  ext_cc_warning_fit_metric: {
    zh: "{metric} ΔE00 为 {value}，高于建议值 {threshold}。建议检查色卡角点、采样点和光照。",
    en: "{metric} ΔE00 is {value}, above the suggested {threshold}. Check chart corners, sample points, and lighting.",
  },
  ext_cc_warning_patch_validity: {
    zh: "{total} 个色块中有 {invalid} 个未参与拟合。请检查采样点是否落在色块中心，并适当调小采样半径。",
    en: "{invalid} of {total} patches were excluded from fitting. Check that sample points are centered and reduce the sample radius if needed.",
  },
  ext_cc_warning_gray_l_not_monotonic: {
    zh: "中性灰亮度顺序不稳定。请检查灰阶色块是否被反光、阴影或错误采样影响。",
    en: "Neutral gray brightness is not monotonic. Check for glare, shadow, or misplaced gray samples.",
  },
  ext_cc_warning_gray_a_threshold: {
    zh: "中性灰 a* 偏色偏高。建议检查白平衡、光源和灰阶采样点。",
    en: "Neutral gray a* cast is high. Check white balance, lighting, and gray sample points.",
  },
  ext_cc_warning_gray_b_threshold: {
    zh: "中性灰 b* 偏色偏高。建议检查白平衡、光源和灰阶采样点。",
    en: "Neutral gray b* cast is high. Check white balance, lighting, and gray sample points.",
  },
  ext_cc_warning_gray_reference_delta: {
    zh: "{index}. {label} 灰块的 Δ{axis}* 为 {delta}（校色后 {corrected}，参考 {reference}），高于建议值 {threshold}。建议检查白平衡、光源和该灰阶采样点。",
    en: "Gray patch {index}. {label} has Δ{axis}* {delta} (corrected {corrected}, reference {reference}), above the suggested {threshold}. Check white balance, lighting, and that gray sample point.",
  },
  ext_cc_warning_negative_ratio: {
    zh: "校色后有 {value} 的像素出现负通道裁剪。建议改用默认算法或降低高级校正强度。",
    en: "{value} of corrected pixels have negative-channel clipping. Prefer the default algorithm or reduce advanced correction strength.",
  },
  ext_cc_warning_clipping_ratio: {
    zh: "校色后有 {value} 的线性 RGB 通道样本超过 1.0，导出到当前显示色域时会被裁剪。建议检查曝光，或改用更保守的算法。",
    en: "{value} of corrected linear RGB channel samples exceed 1.0 and will be clipped for the current display gamut. Check exposure or use a more conservative algorithm.",
  },
  ext_cc_delta_status_high_precision: {
    zh: "高精度",
    en: "High precision",
  },
  ext_cc_delta_status_acceptable: {
    zh: "可接受",
    en: "Acceptable",
  },
  ext_cc_delta_status_check: {
    zh: "需检查",
    en: "Check",
  },
  ext_cc_warning_exposure_drift: {
    zh: "该算法对曝光变化较敏感，结果可能随亮度变化而偏色。建议优先使用默认 3x3 矩阵。",
    en: "This algorithm is sensitive to exposure changes. Prefer the default 3x3 matrix unless you are comparing expert settings.",
  },
  ext_cc_warning_affine_bias: {
    zh: "仿射算法的偏置项较大，暗部颜色可能漂移。建议检查黑色块采样或改回 3x3 矩阵。",
    en: "The affine bias is high, so dark colors may drift. Check black-patch sampling or switch back to the 3x3 matrix.",
  },
  ext_cc_warning_generic: {
    zh: "校色结果存在质量风险。请检查角点、采样点、曝光和色卡摆放。",
    en: "The correction result has a quality risk. Check corners, samples, exposure, and chart placement.",
  },
  ext_extract_btn_label: {
    zh: "提取颜色",
    en: "Extract Colors",
  },
  ext_clear_corners: {
    zh: "清除角点",
    en: "Clear Corners",
  },
  ext_merge_5c_title: {
    zh: "5色扩展双页合并",
    en: "5-Color Extended Dual-Page Merge",
  },
  ext_merge_8c_title: {
    zh: "8色双页合并",
    en: "8-Color Dual-Page Merge",
  },
  ext_merge_8c_full_title: {
    zh: "8色完整版合并",
    en: "8-Color Full Merge",
  },
  ext_merge_5c_btn: {
    zh: "合并 5 色 LUT",
    en: "Merge 5-Color LUT",
  },
  ext_merge_8c_btn: {
    zh: "合并 8 色 LUT",
    en: "Merge 8-Color LUT",
  },
  ext_merge_8c_full_btn: {
    zh: "合并 8 色完整版 LUT",
    en: "Merge Full 8-Color LUT",
  },
  ext_pages_extracted_label: {
    zh: "已提取页数",
    en: "Extracted Pages",
  },
  ext_page_extracted: {
    zh: "已提取",
    en: "Extracted",
  },
  ext_page_not_extracted: {
    zh: "未提取",
    en: "Not extracted",
  },
  ext_page_1_label: {
    zh: "第 1 页",
    en: "Page 1",
  },
  ext_page_2_label: {
    zh: "第 2 页",
    en: "Page 2",
  },
  ext_8color_full_export_label: {
    zh: "8色完整版提取",
    en: "Full 8-Color Extraction",
  },
  ext_8color_full_export_hint: {
    zh: "如果你的校准板来自完整版 ZIP，请开启后按 1号-24号逐页提取并在全部完成后合并。",
    en: "Enable this if your calibration boards come from the full 8-color ZIP, then extract pages 1-24 and merge after all pages are complete.",
  },
  ext_8color_full_export_on: {
    zh: "全量",
    en: "Full",
  },
  ext_8color_full_export_off: {
    zh: "精简",
    en: "Compact",
  },
  ext_download_lut: {
    zh: "下载 LUT 文件 (.json)",
    en: "Download LUT File (.json)",
  },
  ext_manual_fix_hint: {
    zh: "点击右侧 LUT 预览图中的色块可手动修正颜色",
    en: "Click a cell in the LUT preview to manually fix its color",
  },
  ext_manual_fix_resolve_failed: {
    zh: "无法识别你点击的 LUT 色块，请重新提取后再试。",
    en: "Could not resolve the selected LUT cell. Re-run extraction and try again.",
  },
  ext_material_type_label: {
    zh: "耗材类型",
    en: "Material Type",
  },
  ext_palette_title: {
    zh: "调色板确认",
    en: "Palette Confirmation",
  },
  ext_palette_metadata_hint: {
    zh: "填写厂商、耗材类型，并为每个颜色记录厂商命名",
    en: "Set manufacturer, material type, and vendor color names for each entry",
  },
  ext_manufacturer_label: {
    zh: "厂商",
    en: "Manufacturer",
  },
  ext_manufacturer_placeholder: {
    zh: "输入或选择厂商",
    en: "Type or select manufacturer",
  },
  ext_manufacturer_loading: {
    zh: "正在加载耗材品牌...",
    en: "Loading material brands...",
  },
  ext_manufacturer_empty: {
    zh: "当前耗材库暂无品牌，可直接手动输入",
    en: "No brands in the current material library; you can type one",
  },
  ext_manufacturer_custom_hint: {
    zh: "可使用当前手动输入的厂商",
    en: "You can use the manually typed manufacturer",
  },
  ext_palette_internal_color_label: {
    zh: "内部通道",
    en: "Internal Slot",
  },
  ext_palette_color_name_label: {
    zh: "厂商颜色名称",
    en: "Vendor Color Name",
  },
  ext_confirm_palette_btn: {
    zh: "确认调色板",
    en: "Confirm Palette",
  },
  ext_palette_confirmed: {
    zh: "✓ 调色板已确认",
    en: "✓ Palette confirmed",
  },

  // ==================== Extractor Canvas ====================
  ext_canvas_warp_view: {
    zh: "定位标记图",
    en: "Corner Markers",
  },
  ext_canvas_lut_preview: {
    zh: "LUT 预览 / 点击色块修正颜色",
    en: "LUT Preview / Click cell to fix color",
  },
  ext_canvas_row: {
    zh: "行",
    en: "Row",
  },
  ext_canvas_col: {
    zh: "列",
    en: "Col",
  },
  ext_canvas_fixing: {
    zh: "修正中...",
    en: "Fixing...",
  },
  ext_canvas_confirm_fix: {
    zh: "确认修正",
    en: "Confirm Fix",
  },
  ext_canvas_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  ext_canvas_upload_hint: {
    zh: "请在左侧面板上传校准板照片",
    en: "Upload a calibration board photo from the left panel",
  },
  ext_canvas_upload_hint_en: {
    zh: "上传校准板照片以开始",
    en: "Upload a calibration board photo to begin",
  },
  ext_canvas_positioning_done: {
    zh: "定位完成",
    en: "Positioning Complete",
  },
  ext_canvas_click_corner: {
    zh: "请点击第 {n} 个角点: {label}",
    en: "Click corner {n}: {label}",
  },

  // ==================== Basic Settings ====================
  basic_crop_image: {
    zh: "裁切与旋转",
    en: "Crop & Rotate",
  },
  basic_crop_after_upload: {
    zh: "上传后裁剪",
    en: "Crop After Upload",
  },
  basic_crop_after_upload_hint: {
    zh: "勾选后，每次上传图片会先弹出裁剪窗口，方便只保留想打印的部分。",
    en: "When checked, a crop dialog opens after each upload so you can keep only the part you want to print.",
  },
  basic_image_rotation_label: {
    zh: "图像旋转",
    en: "Image Rotation",
  },
  basic_image_rotation_apply: {
    zh: "应用旋转",
    en: "Apply Rotation",
  },
  basic_image_rotation_hint: {
    zh: "旋转会直接更新当前图片；后续预览和导出都会使用旋转后的图像。",
    en: "Rotation updates the current image; later previews and exports use the rotated image.",
  },
  basic_image_rotation_failed: {
    zh: "图像旋转失败",
    en: "Failed to rotate image",
  },
  basic_lut_manufacturer_label: {
    zh: "选择LUT",
    en: "Select LUT",
  },
  basic_lut_manufacturer_placeholder: {
    zh: "选择 LUT 数据库…",
    en: "Choose a LUT database…",
  },
  basic_lut_unlabeled_brand: {
    zh: "个人",
    en: "Personal",
  },
  basic_lut_placeholder: {
    zh: "选择 LUT...",
    en: "Select LUT...",
  },
  basic_lut_lut_placeholder: {
    zh: "选择 LUT",
    en: "Select a LUT",
  },
  basic_lut_no_brand_hint: {
    zh: "请先选择 LUT 品牌",
    en: "Pick a LUT brand first",
  },
  basic_lut_selected_count: {
    zh: "已选",
    en: "Selected",
  },
  basic_lut_color_mode_bw: {
    zh: "黑白",
    en: "BW",
  },
  basic_lut_color_mode_4color: {
    zh: "4 色",
    en: "4-Color",
  },
  basic_lut_color_mode_4color_cmyw: {
    zh: "4 色 CMYW",
    en: "4-Color (CMYW)",
  },
  basic_lut_color_mode_4color_rybw: {
    zh: "4 色 RYBW",
    en: "4-Color (RYBW)",
  },
  basic_lut_color_mode_5color_ext: {
    zh: "5 色扩展",
    en: "5-Color Extended",
  },
  basic_lut_color_mode_5color_ext_1444: {
    zh: "5 色扩展 1444",
    en: "5-Color Extended (1444)",
  },
  basic_lut_color_mode_6color: {
    zh: "6 色",
    en: "6-Color",
  },
  basic_lut_color_mode_6color_cmywgk: {
    zh: "6 色 CMYWGK",
    en: "6-Color (CMYWGK 1296)",
  },
  basic_lut_color_mode_6color_rybwgk: {
    zh: "6 色 RYBWGK",
    en: "6-Color (RYBWGK 1296)",
  },
  basic_lut_color_mode_8color: {
    zh: "8 色",
    en: "8-Color",
  },
  basic_lut_color_mode_8color_max: {
    zh: "8 色 Max",
    en: "8-Color Max",
  },
  basic_lut_color_mode_merged: {
    zh: "合并 LUT",
    en: "Merged",
  },
  basic_lut_upload: {
    zh: "上传",
    en: "Upload",
  },
  basic_lut_refresh: {
    zh: "刷新",
    en: "Refresh",
  },
  basic_lut_refresh_tooltip: {
    zh: "重新读取 LUT 目录",
    en: "Reload LUT directory",
  },
  basic_lut_upload_success: {
    zh: "LUT 上传成功",
    en: "LUT uploaded",
  },
  basic_lut_upload_error: {
    zh: "LUT 上传失败",
    en: "LUT upload failed",
  },
  basic_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  basic_source_version_label: {
    zh: "色彩数据来源",
    en: "Color Data Source",
  },
  basic_source_version_hint: {
    zh: "选择配色数据从哪里来：\n• 耗材档案：使用你在「耗材提取」中创建的耗材，自由搭配组合。\n• 经典 LUT：使用实际打印并扫描出的色卡数据，颜色最可靠。",
    en: "Choose where the color data comes from:\n• Material Archive: freely combine materials you created in Material Extraction.\n• Classic LUT: data measured from actually printed color charts — most reliable.",
  },
  basic_source_version_legacy: {
    zh: "经典 LUT",
    en: "Classic LUT",
  },
  basic_source_version_native: {
    zh: "\u53cd\u63a8LUT",
    en: "Inferred LUT",
  },
  basic_source_version_material: {
    zh: "\u8017\u6750\u6863\u6848",
    en: "Material Archive",
  },
  basic_material_select_label: {
    zh: "\u9009\u62e9\u8017\u6750",
    en: "Select Materials",
  },
  basic_material_loading: {
    zh: "\u52a0\u8f7d\u8017\u6750\u5e93\u2026",
    en: "Loading materials\u2026",
  },
  basic_material_empty: {
    zh: "\u65e0\u53ef\u7528\u8017\u6750\uff0c\u8bf7\u5148\u5728\u300c\u8017\u6750\u63d0\u53d6\u300d\u4e2d\u521b\u5efa",
    en: "No materials available. Create one in Material Extraction first.",
  },
  basic_material_selected_count: {
    zh: "\u5df2\u9009\u8017\u6750",
    en: "Selected",
  },
  basic_material_layer_count_label: {
    zh: "\u53e0\u8272\u5c42\u6570",
    en: "Color Layers",
  },
  basic_material_layer_count_hint: {
    zh: "每个颜色由几层耗材叠成。层数越多，能叠出的颜色和过渡越丰富，但打印时间越长。",
    en: "How many material layers are stacked to form each color. More layers give richer colors and smoother transitions but take longer to print.",
  },
  basic_material_dynamic_layer_count_label: {
    zh: "动态调整有效叠层数",
    en: "Dynamic effective layer count",
  },
  basic_material_dynamic_layer_count_hint: {
    zh: "为每种目标颜色在设定范围内选择综合色差最小的有效层数；色差相近时优先使用更短配方。",
    en: "Choose the best effective layer count for each target color within the configured range, preferring shorter recipes when color differences are close.",
  },
  basic_material_min_layer_count_label: {
    zh: "最小有效叠层数",
    en: "Minimum effective layers",
  },
  basic_material_min_layer_count_hint: {
    zh: "每种颜色配方允许使用的最少有效颜色层数。",
    en: "Minimum number of effective color layers allowed for each recipe.",
  },
  basic_material_max_layer_count_label: {
    zh: "最大有效叠层数",
    en: "Maximum effective layers",
  },
  basic_material_max_layer_count_hint: {
    zh: "每种颜色配方允许使用的最多有效颜色层数，也是最终模型的统一打印层数。",
    en: "Maximum number of effective color layers allowed per recipe and the uniform printed layer count of the final model.",
  },
  basic_material_dynamic_range_hint: {
    zh: "动态模式会在设定范围内自动加载并评估候选；单一层数的穷举缓存入口暂不显示。",
    en: "Dynamic mode automatically loads and evaluates candidates across the configured range; the single-layer-count cache control is hidden.",
  },
  basic_material_layer_height_label: {
    zh: "\u5c42\u9ad8",
    en: "Layer Height",
  },
  basic_material_layer_height_hint: {
    zh: "\u6253\u5370\u65f6\u6bcf\u4e00\u5c42\u7684\u539a\u5ea6\uff08\u6beb\u7c73\uff09\u3002\u8fd9\u91cc\u9009\u7684\u6570\u503c\u8981\u548c\u5207\u7247\u8f6f\u4ef6\u91cc\u7684\u5c42\u9ad8\u4e00\u81f4\uff0c\u5426\u5219\u53e0\u51fa\u6765\u7684\u989c\u8272\u4f1a\u4e0d\u51c6\u3002",
    en: "Thickness of each printed layer (mm). Must match the layer height in your slicer, or the blended colors will be off.",
  },
  basic_material_backing_label: {
    zh: "\u5e95\u677f\u8017\u6750",
    en: "Base Plate Material",
  },
  basic_material_backing_hint: {
    zh: "\u57ab\u5728\u753b\u9762\u6700\u5e95\u4e0b\u7684\u8017\u6750\uff0c\u76f8\u5f53\u4e8e\u6574\u5e45\u56fe\u7684\u80cc\u666f\u8272\u3002\u901a\u5e38\u9009\u767d\u8272\uff0c\u989c\u8272\u8fd8\u539f\u6548\u679c\u6700\u597d\u3002",
    en: "The material placed under the whole image, acting as its background color. White usually gives the most accurate colors.",
  },
  basic_material_backing_placeholder: {
    zh: "\u5148\u9009\u62e9\u8017\u6750",
    en: "Select materials first",
  },
  basic_material_picker_open: {
    zh: "\u9009\u62e9\u8017\u6750\u2026",
    en: "Choose materials\u2026",
  },
  basic_material_picker_dialog_title: {
    zh: "\u9009\u62e9\u8017\u6750",
    en: "Choose Materials",
  },
  basic_material_picker_dialog_subtitle: {
    zh: "\u52fe\u9009\u8981\u53c2\u4e0e\u8c03\u8272\u7684\u8017\u6750\uff08\u53ef\u591a\u9009\uff09",
    en: "Pick materials to use for color blending (multi-select)",
  },
  basic_material_picker_done: {
    zh: "\u5b8c\u6210",
    en: "Done",
  },
  basic_material_picker_clear: {
    zh: "\u6e05\u7a7a",
    en: "Clear all",
  },
  basic_material_picker_select_all: {
    zh: "\u5168\u9009",
    en: "Select all",
  },
  basic_material_picker_deselect_all: {
    zh: "\u6e05\u7a7a\u9009\u62e9",
    en: "Deselect all",
  },
  basic_material_picker_remove_selected: {
    zh: "移除 {material}",
    en: "Remove {material}",
  },
  basic_material_picker_selected_label: {
    zh: "已选",
    en: "Selected",
  },
  basic_material_picker_close: {
    zh: "\u5173\u95ed",
    en: "Close",
  },
  basic_material_picker_search_placeholder: {
    zh: "搜索耗材、品牌或作者…",
    en: "Search materials, brands, or authors…",
  },
  basic_material_picker_search_clear: {
    zh: "\u6e05\u9664\u641c\u7d22",
    en: "Clear search",
  },
  basic_material_picker_no_match: {
    zh: "\u6ca1\u6709\u5339\u914d\u7684\u8017\u6750",
    en: "No materials match your search",
  },
  basic_material_picker_tab_favorites: {
    zh: "收藏",
    en: "Favorites",
  },
  basic_material_picker_tab_all: {
    zh: "全部",
    en: "All",
  },
  basic_material_picker_tab_pla: {
    zh: "PLA",
    en: "PLA",
  },
  basic_material_picker_tab_petg: {
    zh: "PETG",
    en: "PETG",
  },
  basic_material_picker_tab_other: {
    zh: "其他",
    en: "Other",
  },
  basic_material_picker_all_brands: {
    zh: "全部品牌",
    en: "All brands",
  },
  basic_material_picker_brand_filter_label: {
    zh: "品牌",
    en: "Brand",
  },
  basic_material_picker_sort_label: {
    zh: "排序",
    en: "Sort",
  },
  basic_material_picker_sort_name: {
    zh: "按名称",
    en: "Name",
  },
  basic_material_picker_sort_recent: {
    zh: "最近使用",
    en: "Recently used",
  },
  basic_material_picker_unknown_type: {
    zh: "未分类",
    en: "Unclassified",
  },
  basic_material_picker_unknown_author: {
    zh: "未知作者",
    en: "Unknown contributor",
  },
  basic_material_picker_profile_count: {
    zh: "{count} 份档案",
    en: "{count} profiles",
  },
  basic_material_picker_verification_count: {
    zh: "验证 {count} 次",
    en: "{count} verifications",
  },
  basic_material_picker_delta_e: {
    zh: "ΔE {value}",
    en: "ΔE {value}",
  },
  basic_material_picker_expand_profiles: {
    zh: "展开 {material} 的档案",
    en: "Expand profiles for {material}",
  },
  basic_material_picker_collapse_profiles: {
    zh: "收起 {material} 的档案",
    en: "Collapse profiles for {material}",
  },
  basic_material_picker_select_material: {
    zh: "选择 {material}",
    en: "Select {material}",
  },
  basic_material_picker_deselect_material: {
    zh: "取消选择 {material}",
    en: "Deselect {material}",
  },
  basic_material_picker_select_profile: {
    zh: "选择 {material}（{author}）档案",
    en: "Select the {material} profile by {author}",
  },
  basic_material_picker_favorite_profile: {
    zh: "收藏 {material}（{author}）",
    en: "Favorite {material} by {author}",
  },
  basic_material_picker_unfavorite_profile: {
    zh: "取消收藏 {material}（{author}）",
    en: "Remove {material} by {author} from favorites",
  },
  basic_material_picker_empty_favorites: {
    zh: "还没有收藏耗材档案",
    en: "No material profiles have been favorited yet",
  },
  basic_material_picker_mixed_status: {
    zh: "当前选择包含 {types}。",
    en: "The current selection contains {types}.",
  },
  basic_material_picker_type_count: {
    zh: "{type} {count} 项",
    en: "{type} {count}",
  },
  basic_material_picker_mixed_confirm_title: {
    zh: "确认混合耗材类型？",
    en: "Confirm mixed material types?",
  },
  basic_material_picker_mixed_confirm_body: {
    zh: "当前选择包含 {types}。请确认喷嘴温度、热床温度和层间粘结符合你的打印方案。",
    en: "The current selection contains {types}. Confirm that nozzle temperature, bed temperature, and inter-layer adhesion fit your print plan.",
  },
  basic_material_picker_mixed_back: {
    zh: "返回调整",
    en: "Go back",
  },
  basic_material_picker_mixed_continue: {
    zh: "仍然使用",
    en: "Use anyway",
  },
  basic_material_picker_load_error: {
    zh: "耗材列表加载失败，请重试。",
    en: "The material library could not be loaded. Try again.",
  },
  basic_material_picker_retry: {
    zh: "重试",
    en: "Retry",
  },
  basic_material_cache_section_title: {
    zh: "穷举缓存",
    en: "Exhaustive Cache",
  },
  basic_material_cache_open_button: {
    zh: "\u7a77\u4e3e\u7f13\u5b58\u2026",
    en: "Exhaustive cache\u2026",
  },
  basic_material_cache_section_description: {
    zh: "为当前耗材组合构建 Lab 网格配方库，后续出图直接查表。",
    en: "Build a Lab-grid recipe library for this palette so future conversions are served from cache.",
  },
  basic_material_cache_active_grid_label: {
    zh: "当前穷举数量：{tier}（{grid}³）。可在设置里切换。",
    en: "Current density: {tier} ({grid}³). Change in Settings.",
  },
  basic_material_cache_status_idle: {
    zh: "请选择至少一种耗材后查看缓存状态。",
    en: "Select at least one material to view cache status.",
  },
  basic_material_cache_status_checking: {
    zh: "正在检查缓存\u2026",
    en: "Checking cache\u2026",
  },
  basic_material_cache_status_ready: {
    zh: "缓存已就绪",
    en: "Cache ready",
  },
  basic_material_cache_status_missing: {
    zh: "缓存未构建",
    en: "Cache not built",
  },
  basic_material_cache_status_error: {
    zh: "缓存状态查询失败",
    en: "Failed to query cache status",
  },
  basic_material_cache_status_error_detail: {
    zh: "缓存状态查询失败，请稍后重试。",
    en: "Failed to query the cache status. Please try again later.",
  },
  basic_material_cache_fallback_hint: {
    zh: "未构建缓存时，参数调整不会自动预览；仍可手动预览，但会使用临时候选求解器，耗时较长，结果可能与持久缓存不同。",
    en: "When no cache is available, parameter changes will not auto-preview. You can still preview manually with the temporary candidate solver; it may take longer and differ from a persisted-cache result.",
  },
  basic_material_cache_build_button: {
    zh: "立即构建缓存",
    en: "Build cache now",
  },
  basic_material_cache_building_label: {
    zh: "正在构建\u2026",
    en: "Building\u2026",
  },
  basic_material_cache_building_hint: {
    zh: "穷举 {combinations} 种组合并落盘，大约需要 {seconds} 秒。",
    en: "Enumerating {combinations} combinations and writing to disk — about {seconds} seconds.",
  },
  basic_material_cache_rebuild_button: {
    zh: "重新构建",
    en: "Rebuild",
  },
  basic_material_cache_delete_button: {
    zh: "删除缓存",
    en: "Delete cache",
  },
  basic_material_cache_charts_show_button: {
    zh: "查看色彩分布图",
    en: "View color charts",
  },
  basic_material_cache_charts_hide_button: {
    zh: "收起色彩分布图",
    en: "Hide color charts",
  },
  basic_material_cache_charts_loading: {
    zh: "正在加载色彩分布图…",
    en: "Loading color charts…",
  },
  basic_material_cache_charts_error: {
    zh: "色彩分布图加载失败：{message}",
    en: "Failed to load color charts: {message}",
  },
  basic_material_cache_charts_failed: {
    zh: "色彩分布图加载失败，请稍后重试。",
    en: "Failed to load the color charts. Please try again later.",
  },
  basic_material_cache_confirm_delete: {
    zh: "确认删除当前组合的缓存？",
    en: "Delete the cache for this combination?",
  },
  basic_material_cache_built_at_label: {
    zh: "构建时间",
    en: "Built at",
  },
  basic_material_cache_size_label: {
    zh: "缓存大小",
    en: "Cache size",
  },
  basic_material_cache_coverage_label: {
    zh: "覆盖格数",
    en: "Cell coverage",
  },
  basic_material_cache_mean_delta_e_label: {
    zh: "平均 ΔE",
    en: "Mean ΔE",
  },
  basic_material_cache_max_delta_e_label: {
    zh: "最大 ΔE",
    en: "Max ΔE",
  },
  basic_material_cache_build_time_label: {
    zh: "构建耗时",
    en: "Build time",
  },
  basic_material_cache_units_seconds: {
    zh: "{seconds} 秒",
    en: "{seconds} s",
  },
  basic_material_cache_units_mb: {
    zh: "{mb} MB",
    en: "{mb} MB",
  },
  basic_material_cache_build_error: {
    zh: "构建失败：{message}",
    en: "Build failed: {message}",
  },
  basic_material_cache_build_failed: {
    zh: "缓存构建失败，请稍后重试。",
    en: "Cache build failed. Please try again later.",
  },
  basic_material_cache_delete_error: {
    zh: "删除失败：{message}",
    en: "Delete failed: {message}",
  },
  basic_material_cache_delete_failed: {
    zh: "缓存删除失败，请稍后重试。",
    en: "Cache delete failed. Please try again later.",
  },
  basic_material_runtime_section_title: {
    zh: "智能配方缓存",
    en: "Smart Recipe Cache",
  },
  basic_material_runtime_section_description: {
    zh: "为大耗材组合预生成覆盖广的配方，加速颜色匹配。",
    en: "Precompute broad recipe coverage for large material palettes to speed color matching.",
  },
  basic_material_runtime_status_idle: {
    zh: "请选择至少一种耗材后查看智能缓存状态。",
    en: "Select at least one material to view smart cache status.",
  },
  basic_material_runtime_status_checking: {
    zh: "正在检查智能缓存…",
    en: "Checking smart cache…",
  },
  basic_material_runtime_status_ready: {
    zh: "智能缓存已就绪",
    en: "Smart cache ready",
  },
  basic_material_runtime_status_missing: {
    zh: "配方缓存未构建",
    en: "Smart recipe cache not built",
  },
  basic_material_runtime_status_error: {
    zh: "智能缓存状态查询失败",
    en: "Failed to query smart cache status",
  },
  basic_material_runtime_status_error_detail: {
    zh: "智能缓存状态查询失败，请稍后重试。",
    en: "Failed to query the smart cache status. Please try again later.",
  },
  basic_material_runtime_budget_label: {
    zh: "缓存规模",
    en: "Cache size",
  },
  basic_material_runtime_budget_option_1048576: {
    zh: "快速 1M",
    en: "Fast 1M",
  },
  basic_material_runtime_budget_option_4194304: {
    zh: "标准 4M",
    en: "Standard 4M",
  },
  basic_material_runtime_budget_option_8388608: {
    zh: "高精度 8M",
    en: "High 8M",
  },
  basic_material_runtime_budget_option_33554432: {
    zh: "推荐 32M",
    en: "Recommended 32M",
  },
  basic_material_runtime_budget_option_67108864: {
    zh: "极高 64M",
    en: "Extreme 64M",
  },
  basic_material_runtime_missing_hint: {
    zh: "未构建时，系统会按需临时生成一份小规模配方缓存。",
    en: "When no smart cache is saved, the system builds a small recipe cache on demand.",
  },
  basic_material_runtime_build_button: {
    zh: "构建智能缓存",
    en: "Build smart cache",
  },
  basic_material_runtime_rebuild_button: {
    zh: "重建智能缓存",
    en: "Rebuild smart cache",
  },
  basic_material_runtime_delete_button: {
    zh: "删除智能缓存",
    en: "Delete smart cache",
  },
  basic_material_runtime_charts_show_button: {
    zh: "查看配方覆盖图",
    en: "View recipe coverage",
  },
  basic_material_runtime_charts_hide_button: {
    zh: "收起配方覆盖图",
    en: "Hide recipe coverage",
  },
  basic_material_runtime_charts_loading: {
    zh: "正在加载配方覆盖图…",
    en: "Loading recipe coverage…",
  },
  basic_material_runtime_charts_error: {
    zh: "配方覆盖图加载失败：{message}",
    en: "Failed to load recipe coverage: {message}",
  },
  basic_material_runtime_charts_failed: {
    zh: "配方覆盖图加载失败，请稍后重试。",
    en: "Failed to load recipe coverage. Please try again later.",
  },
  basic_material_runtime_building_label: {
    zh: "正在构建智能缓存…",
    en: "Building smart cache…",
  },
  basic_material_runtime_building_hint: {
    zh: "正在生成 {budget} 条配方并保存。",
    en: "Generating and saving {budget} recipes.",
  },
  basic_material_runtime_confirm_delete: {
    zh: "确认删除当前组合的智能配方缓存？",
    en: "Delete the smart recipe cache for this combination?",
  },
  basic_material_runtime_candidates_label: {
    zh: "配方数",
    en: "Recipe count",
  },
  basic_material_runtime_inverse_label: {
    zh: "反推精修",
    en: "Inverse refinement",
  },
  basic_material_runtime_enabled: {
    zh: "启用",
    en: "Enabled",
  },
  basic_material_runtime_disabled: {
    zh: "关闭",
    en: "Disabled",
  },
  basic_material_runtime_build_error: {
    zh: "智能缓存构建失败：{message}",
    en: "Smart cache build failed: {message}",
  },
  basic_material_runtime_build_failed: {
    zh: "智能缓存构建失败，请稍后重试。",
    en: "Smart cache build failed. Please try again later.",
  },
  basic_material_runtime_delete_error: {
    zh: "智能缓存删除失败：{message}",
    en: "Smart cache delete failed: {message}",
  },
  basic_material_runtime_delete_failed: {
    zh: "智能缓存删除失败，请稍后重试。",
    en: "Smart cache delete failed. Please try again later.",
  },
  basic_source_kind_label: {
    zh: "颜色源类型",
    en: "Source Kind",
  },
  basic_brand_label: {
    zh: "品牌",
    en: "Brand",
  },
  basic_brand_hint: {
    zh: "选择耗材品牌后，会加载该品牌对应的颜色数据用于配色。",
    en: "Selecting a filament brand loads that brand's color data for color matching.",
  },
  basic_brand_loading: {
    zh: "品牌目录加载中…",
    en: "Loading brands…",
  },
  basic_brand_placeholder: {
    zh: "请选择品牌",
    en: "Select a brand",
  },
  basic_native_brand_placeholder: {
    zh: "请选择品牌",
    en: "Select a brand",
  },
  basic_native_brand_summary_label: {
    zh: "品牌信息",
    en: "Brand Info",
  },
  basic_native_material_label: {
    zh: "材质类型",
    en: "Material Type",
  },
  basic_native_vendor_label: {
    zh: "供应商",
    en: "Vendor",
  },
  basic_native_db_label: {
    zh: "数据库",
    en: "Databases",
  },
  basic_native_db_placeholder: {
    zh: "未选择数据库",
    en: "No databases selected",
  },
  basic_lut_picker_open: {
    zh: "选择 LUT 数据库…",
    en: "Choose LUT databases…",
  },
  basic_lut_picker_change: {
    zh: "更换",
    en: "Change",
  },
  basic_lut_picker_selection_summary: {
    zh: "已选 {count} 个 LUT",
    en: "{count} LUTs selected",
  },
  basic_lut_picker_more_selected: {
    zh: "另 {count} 个",
    en: "+{count} more",
  },
  basic_lut_picker_title: {
    zh: "选择 LUT",
    en: "Choose LUT",
  },
  basic_lut_picker_search_placeholder: {
    zh: "搜索 LUT…",
    en: "Search LUTs…",
  },
  basic_lut_picker_all_groups: {
    zh: "全部色彩模式",
    en: "All color modes",
  },
  basic_lut_picker_no_match: {
    zh: "未找到匹配的 LUT",
    en: "No matching LUTs",
  },
  basic_lut_picker_deselect_all: {
    zh: "清空选择",
    en: "Deselect all",
  },
  basic_lut_picker_confirm: {
    zh: "确认",
    en: "Confirm",
  },
  basic_lut_picker_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  basic_native_db_picker_title: {
    zh: "选择数据库",
    en: "Choose Databases",
  },
  basic_native_db_picker_search_placeholder: {
    zh: "搜索数据库…",
    en: "Search databases…",
  },
  basic_native_db_picker_no_match: {
    zh: "未找到匹配的数据库",
    en: "No matching databases",
  },
  basic_native_mode_label: {
    zh: "动态层模式",
    en: "Layer Mode",
  },
  basic_native_layer_count_label: {
    zh: "层数",
    en: "Layer Count",
  },
  basic_native_layer_count_hint: {
    zh: "叠色使用的打印层数。层数越多能表现的颜色越丰富，但打印时间也越长。可选范围由所选的颜色数据库决定。",
    en: "Number of printed layers used for color blending. More layers allow richer colors but take longer to print. The available range depends on the selected color database.",
  },
  basic_native_mode_placeholder: {
    zh: "请选择支持模式",
    en: "Select a supported mode",
  },
  basic_color_layers_label: {
    zh: "叠色层数",
    en: "Color Layers",
  },
  basic_color_layers_hint: {
    zh: "叠色混合使用的层数。层数越多可表现的颜色越丰富，但打印耗时和耗材消耗也相应增加。",
    en: "Number of layers used for color blending. More layers enable richer colors but increase print time and material consumption.",
  },
  basic_layer_height_label: {
    zh: "叠色层高",
    en: "Layer Height",
  },
  basic_layer_height_hint: {
    zh: "打印时每一层的厚度（毫米）。请选择该色卡（LUT）制作时使用的层高，并在切片软件里设置相同数值，否则颜色会有偏差。",
    en: "Thickness of each printed layer (mm). Choose the layer height the LUT was made with, and use the same value in your slicer — otherwise colors will drift.",
  },
  basic_supported_modes_label: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  basic_model_gate_label: {
    zh: "模型辅助匹配",
    en: "Model-Assisted Matching",
  },
  basic_model_enable: {
    zh: "模型辅助匹配",
    en: "Model-Assisted Matching",
  },
  basic_model_enable_hint: {
    zh: "在数据库配色的基础上，用预测模型补充数据库里没有实测过的颜色组合，通常能让颜色更接近原图。",
    en: "Supplements database color matching with a predictive model that covers combinations not physically measured, usually bringing colors closer to the original image.",
  },
  basic_model_only: {
    zh: "仅模型匹配",
    en: "Model only",
  },
  basic_model_only_hint: {
    zh: "完全用预测模型配色，不使用数据库实测数据。主要用于对比测试模型效果，日常使用建议保持关闭。",
    en: "Uses only the predictive model for color matching, ignoring measured database data. Mainly for testing the model; keep it off for everyday use.",
  },
  basic_model_threshold: {
    zh: "模型阈值",
    en: "Model Threshold",
  },
  basic_model_margin: {
    zh: "模型边距",
    en: "Model Margin",
  },
  basic_model_runtime_defaults_hint: {
    zh: "留空则使用运行时默认值。",
    en: "Leave blank to use runtime defaults.",
  },
  basic_width: {
    zh: "宽度",
    en: "Width",
  },
  basic_width_hint: {
    zh: "打印成品的宽度（毫米）。需在打印机有效打印范围内。",
    en: "Printed output width (in mm). Must be within the printer's effective print area.",
  },
  basic_height: {
    zh: "高度",
    en: "Height",
  },
  basic_height_hint: {
    zh: "打印成品的高度（毫米）。需在打印机有效打印范围内。",
    en: "Printed output height (in mm). Must be within the printer's effective print area.",
  },
  basic_thickness: {
    zh: "底板厚度",
    en: "Base plate thickness",
  },
  basic_thickness_hint: {
    zh: "底板的厚度（毫米）。底板越厚成品越结实，但打印时间和耗材用量也会增加。滑块每格对应一层打印层。",
    en: "Thickness of the base plate (mm). A thicker base is sturdier but takes more time and material to print. Each slider step equals one print layer.",
  },
  basic_backing_infill_density: {
    zh: "底板填充率",
    en: "Base plate infill",
  },
  basic_backing_infill_density_hint: {
    zh: "控制深层背板的填充率，平面拼图也可使用。靠近观赏面的保护区域始终保持 100% 实心；浮雕模式固定为 100%。",
    en: "Controls infill in the deeper backing, including flat puzzles. The protected zone next to the viewing surface always stays 100% solid; relief mode stays at 100%.",
  },
  basic_structure_mode: {
    zh: "单面/双面打印",
    en: "Single/Double-sided Printing",
  },
  basic_structure_mode_hint: {
    zh: "决定成品的正反面结构：\n• 双面：正反两面都呈现画面，适合挂件、灯片等两面都会被看到的场景。\n• 单面：只有正面有画面，背面是平整底板，打印更快、更省耗材。",
    en: "Controls the front/back structure of the print:\n• Double-sided: the image shows on both sides — good for pendants or light panels viewed from either side.\n• Single-sided: image on the front only, flat base plate on the back — faster and uses less material.",
  },
  basic_modeling_mode: {
    zh: "建模模式",
    en: "Modeling Mode",
  },
  basic_group_input: {
    zh: "导入",
    en: "Import",
  },
  basic_group_color_source: {
    zh: "颜色设置",
    en: "Color Settings",
  },
  basic_group_output_size: {
    zh: "输出尺寸",
    en: "Output Size",
  },
  basic_group_build: {
    zh: "结构与质感",
    en: "Structure",
  },
  basic_block_size_and_base_plate: {
    zh: "尺寸和底板",
    en: "Size and base plate",
  },
  basic_block_structure: {
    zh: "结构",
    en: "Structure",
  },
  basic_block_modeling: {
    zh: "建模",
    en: "Modeling",
  },
  basic_backing_infill_disabled_model_surface: {
    zh: "模型覆面开启时由模型本身决定背衬，填充率不可调整。",
    en: "Model surface mode derives the backing from the model, so infill is not adjustable.",
  },
  basic_backing_infill_disabled_relief: {
    zh: "浮雕模式固定使用 100% 实心填充，填充率不可调整。",
    en: "Relief mode always uses 100% solid infill, so this is not adjustable.",
  },
  basic_structure_mode_disabled_model_surface: {
    zh: "模型覆面只生成单面结构，无法切换结构模式。",
    en: "Model surface mode only produces a single-sided structure.",
  },
  basic_structure_mode_disabled_relief: {
    zh: "浮雕模式只支持单面结构，无法切换结构模式。",
    en: "Relief mode only supports a single-sided structure.",
  },
  basic_structure_mode_disabled_fridge_magnet: {
    zh: "冰箱贴模式只生成单面结构，无法切换结构模式。",
    en: "Fridge magnet mode only produces a single-sided structure.",
  },
  basic_structure_mode_five_color_hint: {
    zh: "5 色扩展模式只支持单面结构。",
    en: "5-color extended mode only supports a single-sided structure.",
  },
  basic_modeling_mode_hint: {
    zh: "决定图片如何变成 3D 模型：\n• 高保真（位图）：忠实还原照片细节，适合绝大多数图片（推荐）。\n• 像素艺术：保留方块像素感，适合像素画、马赛克风格。\n• 矢量图：生成平滑的曲线轮廓，适合 Logo、图标等颜色分明的图形。\n• 验证色卡：生成用于校准颜色的标准色卡，仅在测试耗材颜色时使用。",
    en: "Controls how the image becomes a 3D model:\n• High-Fidelity (Bitmap): faithfully reproduces photo detail — recommended for most images.\n• Pixel Art: keeps the blocky pixel look — for pixel art and mosaic styles.\n• Vector Image: smooth curved outlines — for logos, icons, and flat-color artwork.\n• Color Card: generates a calibration color chart — only for testing filament colors.",
  },
  basic_image_format_error: {
    zh: "仅支持 JPG/JFIF/PNG/SVG/WebP/HEIC 格式",
    en: "Only JPG/JFIF/PNG/SVG/WebP/HEIC formats are supported",
  },
  svg_hole_compensation: {
    zh: "SVG 小洞补偿",
    en: "SVG hole compensation",
  },
  svg_hole_compensation_hint: {
    zh: "按成品尺寸填补画面内部的小孔和细缝，并沿用邻近颜色；预览和生成使用同一张补偿后的画面。不会扩大外轮廓，也不会改写原文件。有意保留的小孔也可能被填上，默认关闭。",
    en: "Fill enclosed small holes and thin gaps at the finished size using a nearby colour. Preview and generation use the same compensated artwork. The outer outline and original file stay unchanged. Intentional small details may also be filled; off by default.",
  },
  svg_hole_compensation_unavailable: {
    zh: "仅适用于 SVG 的矢量模式；批量使用时需全部为 SVG。",
    en: "Available for SVG artwork in Vector mode only; every file in a batch must be SVG.",
  },
  svg_hole_max_area: {
    zh: "补孔面积上限 (mm²)",
    en: "Maximum hole area (mm²)",
  },
  svg_hole_max_area_hint: {
    zh: "小于等于此面积的内部孔洞会被填满。数值越大，填补的孔越多；设为 0 关闭按面积补孔。面积或细缝条件满足任一项即可填补。",
    en: "Fill enclosed holes up to this area. Larger values fill more holes; 0 disables the area criterion. A hole is filled if either the area or thin-gap criterion is met.",
  },
  svg_hole_max_width: {
    zh: "细缝宽度上限 (mm)",
    en: "Maximum thin-gap width (mm)",
  },
  svg_hole_max_width_hint: {
    zh: "补上面积较大但整体狭长的封闭细缝。这里按孔洞面积和周长估算宽度，不是孔洞的最宽处；设为 0 关闭细缝筛选。",
    en: "Fill long, enclosed thin gaps even when their area is larger. Width is estimated from the hole's area and perimeter, not its widest point; 0 disables the thin-gap criterion.",
  },
  svg_hole_compensation_invalid: {
    zh: "SVG 小洞补偿参数无效：面积和宽度必须是大于等于 0 的有限数值。",
    en: "Invalid SVG hole compensation settings: area and width must be finite, non-negative numbers.",
  },
  converter_raw_preview_failed: {
    zh: "RAW 图片预览失败：{error}。请先转换为 PNG/JPG 后再试。",
    en: "RAW image preview failed: {error}. Please convert it to PNG or JPG and try again.",
  },
  extractor_raw_preview_failed: {
    zh: "RAW 图片预览失败：{error}。请先转换为 PNG/JPG 后再试。",
    en: "RAW image preview failed: {error}. Please convert it to PNG or JPG and try again.",
  },

  // ==================== Large Format Mode ====================
  slicer_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  slicer_generate_download_zip: {
    zh: "生成并下载 ZIP",
    en: "Generate & Download ZIP",
  },
  basic_large_format: {
    zh: "大画幅模式",
    en: "Large Format Mode",
  },
  basic_large_format_hint: {
    zh: "作品超过打印床尺寸时，自动把模型切成多块，分别打印后再拼接。会生成一个包含多个 3MF 文件的压缩包。",
    en: "When the artwork exceeds the print bed, the model is automatically split into tiles to print separately and assemble afterwards. Produces a ZIP containing multiple 3MF files.",
  },
  large_format_warning_native_unavailable: {
    zh: "此 SVG 暂不支持原生大画幅切片，已改用栅格切片。",
    en: "This SVG is not supported by native large-format tiling, so raster tiling was used.",
  },
  large_format_warning_unsupported_features: {
    zh: "此 SVG 含有原生大画幅暂不支持的特性（{features}），已改用栅格切片。",
    en: "This SVG uses features unsupported by native large-format tiling ({features}), so raster tiling was used.",
  },
  large_format_warning_raster_fallback: {
    zh: "本次大画幅 SVG 已改用栅格切片。",
    en: "Raster tiling was used for this large-format SVG.",
  },
  large_format_warning_native_failure: {
    zh: "原生矢量切片生成失败，已自动改用栅格切片。",
    en: "Native vector tiling failed, so raster tiling was used automatically.",
  },
  large_format_partial_result: {
    zh: "仅部分切片生成成功。下载包缺少以下切片：{tiles}。请重新生成这些部分后再拼装。",
    en: "Only some tiles were generated. The download is missing: {tiles}. Generate these tiles again before assembling the model.",
  },
  wipe_tower_manual_adjustment_title: {
    zh: "打印前请手动检查摆放",
    en: "Check the layout before printing",
  },
  wipe_tower_manual_adjustment_warning: {
    zh: "文件已生成，可以下载。自动摆放未能确认模型、底边（brim）和擦料塔的安全位置；当前估算会预留完整底边，实际切片可能占用更少空间。模型尺寸、原生工艺和擦料塔均已保留。请在切片软件中检查并手动调整，确认切片通过后再打印。ZIP 中的每个工程都需要分别检查。",
    en: "The file is ready to download. Automatic placement could not verify safe positions for the model, brim and wipe tower. The estimate reserves the full brim allowance; actual slicing may use less space. Model dimensions, native process settings and the tower were preserved. Check and adjust the layout in your slicer, and confirm slicing succeeds before printing. Check each project in a ZIP separately.",
  },
  basic_tile_width: {
    zh: "切片宽度",
    en: "Tile Width",
  },
  basic_tile_width_hint: {
    zh: "大画幅模式下每个切片的宽度（毫米）。切片越小，拼接数量越多。",
    en: "Width of each tile in large format mode (in mm). Smaller tiles result in more pieces to assemble.",
  },
  basic_tile_height: {
    zh: "切片高度",
    en: "Tile Height",
  },
  basic_tile_height_hint: {
    zh: "大画幅模式下每个切片的高度（毫米）。切片越小，拼接数量越多。",
    en: "Height of each tile in large format mode (in mm). Smaller tiles result in more pieces to assemble.",
  },
  basic_large_format_show_tiles: {
    zh: "在预览中显示切割轮廓",
    en: "Show Cut Outline in Preview",
  },
  basic_large_format_show_tiles_hint: {
    zh: "在 3D 预览上用橙色线标出每一块的切割位置，并显示编号（如 R1C2 表示第 1 行第 2 列），编号与压缩包内的 3MF 文件名一致。只影响预览显示，不改变生成结果。",
    en: "Draws orange cut lines over the 3D preview and labels each tile (e.g. R1C2 = row 1, column 2). Labels match the 3MF file names in the ZIP. Preview only; generated files are unchanged.",
  },

  // ==================== Structure Mode Options ====================
  "structure_mode.Double-sided": {
    zh: "双面",
    en: "Double-sided",
  },
  "structure_mode.Single-sided": {
    zh: "单面",
    en: "Single-sided",
  },

  // ==================== Modeling Mode Options ====================
  "modeling_mode.high-fidelity": {
    zh: "高保真（位图）",
    en: "High-Fidelity (Bitmap)",
  },
  "modeling_mode.pixel": {
    zh: "像素艺术",
    en: "Pixel Art",
  },
  "modeling_mode.vector": {
    zh: "矢量图",
    en: "Vector Image",
  },
  "modeling_mode.color-card": {
    zh: "验证色卡",
    en: "Color Card",
  },

  // ==================== Advanced Settings ====================
  adv_quantize_colors: {
    zh: "量化颜色数",
    en: "Quantize Colors",
  },
  adv_quantize_colors_hint: {
    zh: "把图片归纳成多少种颜色再进行配色。数值越大，颜色过渡越细腻，但处理越慢；数值越小，色块越明显，处理越快。仅高保真模式有效，矢量模式下此参数不起作用。",
    en: "How many colors the image is reduced to before color matching. Higher values give smoother color transitions but slower processing; lower values give more visible color blocks and faster processing. Only applies in High-Fidelity mode; has no effect in Vector mode.",
  },
  adv_isolated_pixel_cleanup: {
    zh: "孤立像素清理",
    en: "Isolated Pixel Cleanup",
  },
  adv_isolated_pixel_cleanup_hint: {
    zh: "自动清理配色后画面上零星的孤立杂点（和周围颜色都不一样的单个像素），让色块更干净。只会借用周围已有的颜色，不会产生新颜色。",
    en: "Automatically removes stray isolated dots left after color matching (single pixels that differ from all their neighbors), making color areas cleaner. Only reuses nearby existing colors — never introduces new ones.",
  },
  adv_separate_backing: {
    zh: "分离底板",
    en: "Separate Backing",
  },
  adv_separate_backing_hint: {
    zh: "把底板（通常是白色背景）单独作为一个颜色部件输出，方便在切片软件里对底板单独换色或设置参数。",
    en: "Outputs the base plate (usually the white background) as its own color part, so you can recolor or configure it separately in your slicer.",
  },
  adv_hue_protection: {
    zh: "色相保护",
    en: "Hue Protection",
  },
  adv_hue_protection_hint: {
    zh: "配色时优先保证颜色的色调不跑偏（例如红色不会变成偏橙）。适合颜色丰富、对还原准确度要求高的图片。",
    en: "Prioritizes keeping color tones true during matching (e.g. reds won't drift toward orange). Good for colorful images where color accuracy matters.",
  },
  adv_unlock_quantize: {
    zh: "解锁量化颜色数",
    en: "Unlock quantize ceiling",
  },
  adv_unlock_quantize_hint: {
    zh: "解锁后颜色数量上限从 256 提升到 8192。会明显增加内存占用和处理时间，仅在确有需要时使用。",
    en: "Unlocking raises the color count ceiling from 256 to 8192. This noticeably increases memory use and processing time; enable only when truly needed.",
  },
  adv_chroma_gate: {
    zh: "暗色彩度门槛",
    en: "Dark Chroma Gate",
  },
  adv_chroma_gate_hint: {
    zh: "控制「色调保护」对暗部的作用范围：只有鲜艳程度低于此值的暗色区域才会被保护。设为 0 对所有暗色生效；数值越大，只保护越暗的阴影。推荐 15。",
    en: "Controls how far hue protection reaches into dark areas: only dark regions less vivid than this value are protected. 0 protects all dark colors; higher values limit it to very dark shadows. Recommended: 15.",
  },
  adv_precise_color_matching: {
    zh: "高精度颜色匹配（实验性功能）",
    en: "Precise Color Matching (Experimental)",
  },
  adv_precise_color_matching_hint: {
    zh: "配色时只使用打印机真正能打出来的颜色，减少成品和屏幕预览之间的色差。处理会稍慢一些，仅在经典 LUT 模式下有效。",
    en: "Restricts color matching to colors your printer can actually produce, reducing the gap between the print and the on-screen preview. Slightly slower; only effective in Classic LUT mode.",
  },
  adv_hue_protection_disabled_hint: {
    zh: "高精度匹配开启时，色相保护已被接管，无需手动启用。",
    en: "Hue protection is automatically handled when high-precision matching is enabled; no need to enable manually.",
  },
  adv_hue_protection_dynamic_hint: {
    zh: "动态有效叠层模式由精确 CIEDE2000 统一评分，色相保护和暗色彩度修正不会参与计算。",
    en: "Dynamic effective-layer mode is scored entirely by exact CIEDE2000; hue protection and dark-chroma adjustments are not applied.",
  },
  adv_hue_protection_dynamic_status: {
    zh: "动态叠层模式下，色相保护和暗色彩度修正不可用。",
    en: "Hue protection and dark-chroma adjustments are unavailable in dynamic-layer mode.",
  },
  adv_hue_protection_disabled_status: {
    zh: "高精度匹配已接管色相保护，无需手动启用。",
    en: "High-precision matching handles hue protection automatically; no manual setting is needed.",
  },
  adv_auto_dynamic_range: {
    zh: "自动动态范围（实验性功能）",
    en: "Auto Dynamic Range (Experimental)",
  },
  adv_auto_dynamic_range_hint: {
    zh: "自动把图片的明暗范围调整到耗材实际能打出来的范围内，避免高光一片死白、阴影一片死黑，同时尽量保留画面的对比度。",
    en: "Automatically fits the image's brightness range to what your filaments can actually reproduce, preventing blown-out highlights and crushed shadows while preserving as much contrast as possible.",
  },
  adv_high_precision_3d_preview: {
    zh: "3D高精度颜色预览",
    en: "High-precision 3D colour preview",
  },
  adv_high_precision_3d_preview_hint: {
    zh: "让 3D 预览显示更多颜色、更接近成品效果，尤其能避免少量出现的颜色被合并成灰色。代价是生成预览和网页渲染会变慢。不影响最终打印文件。",
    en: "Shows more colors in the 3D preview so it looks closer to the final print, especially preventing rare colors from being merged into gray. Preview generation and rendering get slower. Does not affect the exported print file.",
  },

  // ==================== Relief Settings ====================
  relief_enable: {
    zh: "启用浮雕",
    en: "Enable Relief",
  },
  relief_enable_hint: {
    zh: "根据图片明暗或高度图，让平面作品产生高低起伏。",
    en: "Uses image brightness or a heightmap to add raised and recessed detail to a flat design.",
  },
  relief_vector_unsupported_mode: {
    zh: "原生 SVG 浮雕目前仅支持非五色扩展的单面模式。",
    en: "Native SVG relief currently supports only single-sided, non-5-Color Extended mode.",
  },
  relief_max_height: {
    zh: "最大高度",
    en: "Max Height",
  },
  relief_max_height_hint: {
    zh: "浮雕模型最高点的高度（毫米）。值越大浮雕凸起越高，值越小浮雕越浅。",
    en: "The height of the tallest point of the relief model (in mm). Larger values produce taller relief, smaller values produce shallower relief.",
  },
  relief_auto_height_mode: {
    zh: "自动高度模式",
    en: "Auto Height Mode",
  },
  relief_darker_higher: {
    zh: "深色凸起",
    en: "Darker Higher",
  },
  relief_lighter_higher: {
    zh: "浅色凸起",
    en: "Lighter Higher",
  },
  relief_use_heightmap: {
    zh: "根据高度图",
    en: "Use Heightmap",
  },
  relief_heightmap_label: {
    zh: "高度图",
    en: "Heightmap",
  },
  relief_heightmap_generate_requires_upload: {
    zh: "请先上传高度图并获取高度映射后再生成",
    en: "Upload a heightmap and generate its height mapping before generating the model.",
  },
  relief_file_selected: {
    zh: "已选择",
    en: "Selected",
  },

  // ==================== Outline Settings ====================
  outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  outline_enable_hint: {
    zh: "沿作品外缘生成一圈可以调整宽度的边框。",
    en: "Adds an adjustable border around the outside edge of the design.",
  },
  outline_width: {
    zh: "外轮廓厚度",
    en: "Outline Width",
  },
  outline_width_hint: {
    zh: "外描边线条的宽度（毫米）。值越大轮廓线越粗，值越小轮廓线越细。",
    en: "Width of the outline stroke (in mm). Larger values produce thicker lines, smaller values produce thinner lines.",
  },
  // TODO(vector-outline): canonical key names reserved by the acceptance
  // design decision matrix rows D5 / D6. Copy is intentionally a concise
  // placeholder; refine in a follow-up spec when D5 / D6 detection is wired
  // and we have real product copy. See
  // `progress/svg-vector-outline-acceptance-checkpoint.md` Open Question OQ-2.
  // 仅作占位文案；当 D5/D6 真正命中并需要正式提示时再单独立 spec 完善。
  outline_enable_unsupported_alpha_unavailable: {
    zh: "无法在透明通道不可用的素材上启用外轮廓",
    en: "Outline unavailable when image has no usable alpha channel",
  },
  outline_enable_unsupported_subscription_combo: {
    zh: "当前组合暂不支持外轮廓",
    en: "Outline temporarily unavailable for this configuration",
  },

  // ==================== Cloisonne Settings ====================
  cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  cloisonne_enable_hint: {
    zh: "沿色块边界生成凸起线条，形成类似掐丝珐琅的分隔效果。",
    en: "Raises lines along color boundaries to create a cloisonné-style separated look.",
  },
  cloisonne_wire_width: {
    zh: "金属丝宽度",
    en: "Wire Width",
  },
  cloisonne_wire_width_hint: {
    zh: "掐丝珐琅金属丝的水平宽度（毫米）。值越大金属丝越粗，掐丝效果越明显。",
    en: "Horizontal width of the cloisonné wire (in mm). Larger values produce thicker wires with more pronounced cloisonné effect.",
  },
  cloisonne_wire_height: {
    zh: "金属丝高度",
    en: "Wire Height",
  },
  cloisonne_wire_height_hint: {
    zh: "掐丝珐琅金属丝的垂直高度（毫米）。值越大金属丝凸起越高，立体感越强。",
    en: "Vertical height of the cloisonné wire (in mm). Larger values produce taller wire protrusion with stronger three-dimensional appearance.",
  },
  cloisonne_wip: {
    zh: "此功能正在施工中，部分效果可能不完整",
    en: "This feature is under construction, some effects may be incomplete",
  },

  // ==================== Coating Settings ====================
  adv_backing_output: { zh: "背板输出", en: "Backing output" },
  adv_backing_output_same: { zh: "同一工程", en: "Same project" },
  adv_backing_output_separate: { zh: "独立分盘工程（ZIP）", en: "Independent plate projects (ZIP)" },
  adv_backing_output_hint: { zh: "保留原尺寸，模型和背板各输出一个 3MF。解压后分别打开切片，检查模型、底边（brim）和擦料塔的位置。", en: "Keeps the original size and writes one 3MF each for the model and backing. Unzip and slice each project separately, checking the model, brim and wipe tower positions." },
  adv_backing_output_unavailable: { zh: "独立背板工程用于单面、无浮雕的单模型导出。当前模式请使用同一工程或现有分块输出。", en: "Independent backing projects support a single-sided model without relief. Use the same project or the existing tile workflow for this mode." },
  coating_enable: {
    zh: "启用透明镀层",
    en: "Enable Transparent Coating",
  },
  coating_enable_hint: {
    zh: "在作品表面增加透明耗材保护层。材质跟随模型耗材，混合材质默认使用 PLA。",
    en: "Adds a protective layer for transparent filament. Follows the model material type; mixed types default to PLA.",
  },
  coating_height: {
    zh: "透明镀层高度",
    en: "Transparent Coating Height",
  },
  coating_height_hint: {
    zh: "透明镀层覆盖层的高度（毫米）。值越大镀层凸起越高，表面越光滑。",
    en: "Height of the transparent coating layer (in mm). Larger values produce taller coating protrusion and a smoother surface.",
  },

  // ==================== Keychain Loop Settings ====================
  loop_enable: {
    zh: "添加挂件环",
    en: "Add Keychain Loop",
  },
  loop_enable_hint: {
    zh: "在作品边缘增加一个可调整尺寸和位置的挂环。",
    en: "Adds a loop whose size and position can be adjusted for a keychain or lanyard.",
  },
  loop_width: {
    zh: "环宽度",
    en: "Loop Width",
  },
  loop_width_hint: {
    zh: "挂件环的水平宽度（毫米）。值越大环越宽。",
    en: "Horizontal width of the keychain loop (in mm). Larger values produce a wider loop.",
  },
  loop_length: {
    zh: "环长度",
    en: "Loop Length",
  },
  loop_length_hint: {
    zh: "挂件环的垂直长度（毫米）。值越大环越长。",
    en: "Vertical length of the keychain loop (in mm). Larger values produce a longer loop.",
  },
  loop_hole_diameter: {
    zh: "环孔直径",
    en: "Loop Hole Diameter",
  },
  loop_hole_diameter_hint: {
    zh: "挂件环内孔的直径（毫米）。需确保钥匙扣或挂绳能穿过。",
    en: "Diameter of the inner hole (in mm). Must be large enough for a keychain or lanyard to pass through.",
  },
  loop_angle: {
    zh: "旋转角度",
    en: "Rotation Angle",
  },
  loop_angle_hint: {
    zh: "挂件环相对于模型的旋转角度（度）。0° 为竖直向上，正值顺时针旋转。",
    en: "Rotation angle of the loop relative to the model (in degrees). 0° is vertical upward; positive values rotate clockwise.",
  },
  loop_position_preset: {
    zh: "位置预设",
    en: "Position Preset",
  },
  loop_offset_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  loop_offset_x_hint: {
    zh: "挂件环中心相对于模型中心的水平偏移（毫米）。正值向右，负值向左。",
    en: "Horizontal offset of the loop center from the model center (in mm). Positive moves right, negative moves left.",
  },
  loop_offset_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  loop_offset_y_hint: {
    zh: "挂件环相对当前预设吸附点的垂直偏移（毫米）。顶部居中且未旋转时，向内移动会限制在模型局部轮廓处。",
    en: "Vertical offset from the current preset anchor (in mm). For an unrotated top-center loop, inward movement is clamped at the model's local contour.",
  },
  loop_preset_top_center: {
    zh: "上中",
    en: "Top Center",
  },
  loop_preset_top_left: {
    zh: "左上",
    en: "Top Left",
  },
  loop_preset_top_right: {
    zh: "右上",
    en: "Top Right",
  },
  loop_preset_left_center: {
    zh: "左中",
    en: "Left Center",
  },
  loop_preset_right_center: {
    zh: "右中",
    en: "Right Center",
  },
  loop_preset_bottom_center: {
    zh: "下中",
    en: "Bottom Center",
  },

  // ==================== Action Bar ====================
  action_upload_hint: {
    zh: "请先上传图片并选择 LUT",
    en: "Please upload an image and select a LUT first",
  },
  action_upload_image_hint: {
    zh: "请先上传图片",
    en: "Please upload an image first",
  },
  action_select_lut_hint: {
    zh: "请先选择 LUT",
    en: "Please select a LUT first",
  },
  action_upload_hint_material: {
    zh: "请先上传图片并选择耗材",
    en: "Please upload an image and select materials first",
  },
  action_select_material_hint: {
    zh: "请先选择耗材",
    en: "Please select materials first",
  },
  action_upload_hint_native: {
    zh: "请先上传图片并选择品牌和数据库",
    en: "Please upload an image and select a brand and databases first",
  },
  action_select_native_hint: {
    zh: "请先选择品牌和数据库",
    en: "Please select a brand and databases first",
  },
  action_batch_upload_hint: {
    zh: "请先添加图片并选择 LUT",
    en: "Please add images and select a LUT first",
  },
  action_batch_upload_hint_material: {
    zh: "请先添加图片并选择耗材",
    en: "Please add images and select materials first",
  },
  action_batch_upload_hint_native: {
    zh: "请先添加图片并选择品牌和数据库",
    en: "Please add images and select a brand and databases first",
  },
  action_preview: {
    zh: "预览",
    en: "Preview",
  },
  action_generate: {
    zh: "生成",
    en: "Generate",
  },
  action_sync_editor_commit: {
    zh: "同步编辑提交状态",
    en: "Sync edit commit status",
  },
  action_sync_editor_commit_hint: {
    zh: "上一次编辑的提交结果暂时未知。同步前请不要重复提交或生成。",
    en: "The previous edit has an unknown commit result. Sync it before editing or generating again.",
  },
  action_color_card: {
    zh: "生成色卡",
    en: "Color Card",
  },
  action_color_card_loading: {
    zh: "色卡生成中…",
    en: "Generating Card…",
  },
  action_color_card_title: {
    zh: "验证色卡",
    en: "Validation Color Card",
  },
  action_color_card_desc: {
    zh: "从当前调色板生成可打印的色卡 3MF，用于在打印机上验证颜色准确性。",
    en: "Generate a printable colour swatch 3MF from the current palette to verify colour accuracy on your printer.",
  },
  action_batch_generate: {
    zh: "批量生成",
    en: "Batch Generate",
  },
  action_preview_alt: {
    zh: "预览结果",
    en: "Preview result",
  },
  action_view_layers: {
    zh: "查看分层",
    en: "View Layers",
  },
  action_layers_loading: {
    zh: "加载分层...",
    en: "Loading layers...",
  },
  loading_witty_1: {
    zh: "正在折叠高维空间...",
    en: "Folding higher dimensions...",
  },
  loading_witty_2: {
    zh: "正在为打印床预热赛博能量...",
    en: "Preheating cyber energy for the print bed...",
  },
  loading_witty_3: {
    zh: "正在提炼像素点中的灵魂...",
    en: "Extracting souls from pixels...",
  },
  loading_witty_4: {
    zh: "正在拼接彩色多边形...",
    en: "Splicing colorful polygons...",
  },
  loading_witty_5: {
    zh: "正在向打印机注入魔法...",
    en: "Injecting magic into the printer...",
  },
  loading_witty_6: {
    zh: "正在打磨 3MF 积木块...",
    en: "Polishing 3MF building blocks...",
  },
  loading_witty_7: {
    zh: "正在从异世界召唤材质...",
    en: "Summoning textures from another world...",
  },
  loading_witty_8: {
    zh: "正在计算光子跳跃轨道...",
    en: "Calculating photon jump trajectories...",
  },
  loading_witty_9: {
    zh: "不要走开，马上渲染完毕...",
    en: "Hold on, rendering almost complete...",
  },
  loading_witty_10: {
    zh: "请给您的喷嘴一点准备时间...",
    en: "Please give your nozzle some time to prepare...",
  },
  loading_witty_11: {
    zh: "正在校准多发混合挤出机...",
    en: "Calibrating multi-color mixing extruder...",
  },
  loading_witty_12: {
    zh: "正在清理虚拟构建底板...",
    en: "Cleaning virtual build plate...",
  },
  loading_witty_13: {
    zh: "正在熔化高精度的数字耗材...",
    en: "Melting high-precision digital filament...",
  },
  loading_witty_14: {
    zh: "正在挤出完美的底层裙边...",
    en: "Extruding the perfect base skirt...",
  },
  loading_witty_15: {
    zh: "正在规划 G 代码的最优路径...",
    en: "Planning optimal G-code paths...",
  },
  loading_witty_16: {
    zh: "正在调教步进电机的脾气...",
    en: "Tuning the temper of stepper motors...",
  },
  loading_witty_17: {
    zh: "正在精心填充网格内部...",
    en: "Carefully infilling the mesh interior...",
  },
  loading_witty_18: {
    zh: "预热虚拟喷头至 210°C 中...",
    en: "Preheating virtual nozzle to 210°C...",
  },
  loading_witty_19: {
    zh: "正在生成仿生有机树状支撑...",
    en: "Generating bionic organic tree supports...",
  },
  loading_witty_20: {
    zh: "正在抹平第一层讨厌的大象腿...",
    en: "Smoothing the annoying first layer elephant foot...",
  },
  loading_witty_21: {
    zh: "超级风扇启动，冷却悬垂区域...",
    en: "Superfan activated, cooling overhangs...",
  },
  loading_witty_22: {
    zh: "正在计算桥接的完美抛物线...",
    en: "Calculating the perfect parabola for bridging...",
  },
  loading_witty_23: {
    zh: "正在对层叠颜色进行魔法混合...",
    en: "Magically blending stacked layers of colors...",
  },
  loading_witty_24: {
    zh: "正在宇宙中寻找丢失的 Z 轴原点...",
    en: "Searching the universe for the lost Z-axis origin...",
  },
  loading_witty_25: {
    zh: "正在安抚打滑的挤出机齿轮...",
    en: "Pacifying slipping extruder gears...",
  },
  loading_witty_26: {
    zh: "为模型注入强防翘边附着力...",
    en: "Injecting anti-warping adhesion into the model...",
  },
  loading_witty_27: {
    zh: "正在用微波清理喷嘴上的拉丝...",
    en: "Microwaving stringing residue off the nozzle...",
  },
  loading_witty_28: {
    zh: "正在将您的灵感切片成一层层...",
    en: "Slicing your inspiration layer by layer...",
  },
  loading_witty_29: {
    zh: "为调色盘补充一点赛博朋克墨水...",
    en: "Refilling cyberpunk ink for the palette...",
  },
  loading_witty_30: {
    zh: "正在进行一百万次色彩碰撞测试...",
    en: "Conducting an intense color collision test...",
  },
  loading_witty_31: {
    zh: "正在把二维像素用力吹成三维...",
    en: "Blowing 2D pixels vigorously into 3D...",
  },
  loading_witty_32: {
    zh: "构建坚不可摧的 3D 底层网格中...",
    en: "Building indestructible 3D base grids...",
  },
  loading_witty_33: {
    zh: "熨平顶层，让它像镜面一样反光...",
    en: "Ironing top layers until they shine like mirrors...",
  },
  loading_witty_34: {
    zh: "正在从虚空深渊中召唤支撑材料...",
    en: "Summoning support structures from the void abyss...",
  },
  loading_witty_35: {
    zh: "正在解构庞大的彩色三维点云矩阵...",
    en: "Deconstructing massive colorful 3D matrices...",
  },
  loading_witty_36: {
    zh: "正在为立体模型注入引力波形...",
    en: "Injecting gravitational waveforms into 3D models...",
  },
  loading_witty_37: {
    zh: "调色中...不，是在重新发明颜色...",
    en: "Calibrating colors... no, reinventing colors...",
  },
  loading_witty_38: {
    zh: "正在为您一砖一瓦搭建浮雕世界...",
    en: "Building a relief world for you, brick by brick...",
  },
  loading_witty_39: {
    zh: "正在拿针线缝补模型的破损多边形...",
    en: "Darning the broken polygons of your model...",
  },
  loading_witty_40: {
    zh: "Lumina 工作室正在为您打印一个好心情...",
    en: "Lumina Studio is printing a good mood for you...",
  },
  action_layers_title: {
    zh: "分层预览",
    en: "Layer Preview",
  },
  action_layer_nth: {
    zh: "第",
    en: "Layer ",
  },
  action_layer_unit: {
    zh: "层",
    en: "",
  },
  action_layer_prev: {
    zh: "上一层",
    en: "Prev",
  },
  action_layer_next: {
    zh: "下一层",
    en: "Next",
  },

  // ==================== Bed Size Selector ====================
  bed_size_label: {
    zh: "打印机热床",
    en: "Printer Bed",
  },
  bed_size_hint: {
    zh: "这里显示“设置”中的打印机型号和热床尺寸，与左侧选择的 LUT 品牌相互独立。",
    en: "This shows the printer model and bed size from Settings. It is independent of the selected LUT brand.",
  },
  bed_size_hint_aria: {
    zh: "查看打印机热床说明",
    en: "Show printer bed help",
  },
  bed_size_change: {
    zh: "更改",
    en: "Change",
  },
  bed_size_change_aria: {
    zh: "在设置中更改打印机",
    en: "Change printer in Settings",
  },
  bed_size_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  bed_size_placeholder: {
    zh: "选择热床尺寸...",
    en: "Select bed size...",
  },

  // ==================== Palette Panel ====================
  palette_no_data: {
    zh: "暂无调色板数据，请先完成预览",
    en: "No palette data. Please generate a preview first.",
  },
  palette_quantized: {
    zh: "量化色",
    en: "Quantized",
  },
  palette_matched: {
    zh: "匹配色",
    en: "Matched",
  },
  palette_replaced_label: {
    zh: "替换色",
    en: "Replaced",
  },
  palette_dynamic_actual_layers: {
    zh: "实际层数",
    en: "Actual layers",
  },
  palette_dynamic_saved_layers: {
    zh: "节省层数",
    en: "Layers saved",
  },
  palette_dynamic_selected_delta_e00: {
    zh: "当前 ΔE00",
    en: "Selected ΔE00",
  },
  palette_dynamic_fixed_delta_e00: {
    zh: "固定最大层数 ΔE00",
    en: "Fixed-max ΔE00",
  },
  palette_dynamic_best_delta_e00: {
    zh: "范围最佳 ΔE00",
    en: "Range-best ΔE00",
  },
  palette_dynamic_sacrifice: {
    zh: "容差损失",
    en: "Tolerance loss",
  },
  palette_dynamic_benefit_title: {
    zh: "全图层数收益",
    en: "Whole-image layer benefit",
  },
  palette_dynamic_benefit_scope_automatic: {
    zh: "仅自动求解区域（{count} 像素）",
    en: "Automatic-solver region only ({count} pixels)",
  },
  palette_dynamic_benefit_layer: {
    zh: "{count} 层",
    en: "{count} layers",
  },
  palette_dynamic_benefit_mean: {
    zh: "平均 ΔE00 {value}",
    en: "Mean ΔE00 {value}",
  },
  palette_dynamic_benefit_baseline: {
    zh: "起始层数",
    en: "Starting layer count",
  },
  palette_dynamic_benefit_no_improvement: {
    zh: "无改善",
    en: "No improvement",
  },
  palette_dynamic_benefit_marginal: {
    zh: "边际改善 {value}",
    en: "Marginal gain {value}",
  },
  palette_undo: {
    zh: "撤销",
    en: "Undo",
  },
  palette_clear_remaps: {
    zh: "清空替换",
    en: "Clear Remaps",
  },
  palette_redo: {
    zh: "重做",
    en: "Redo",
  },
  palette_clear_selection: {
    zh: "全不选",
    en: "Select none",
  },
  palette_selection_blink: {
    zh: "选区闪烁",
    en: "Blink selection",
  },
  palette_selection_blink_title: {
    zh: "让当前选区整体呼吸闪烁：浅色区块变暗，深色区块发白；仅前端显示，不重新生成预览",
    en: "Make the selected region pulse: light regions darken, dark regions brighten, without regenerating preview",
  },
  palette_group_history: {
    zh: "历史",
    en: "History",
  },
  palette_group_mode: {
    zh: "选择工具",
    en: "Selection tools",
  },
  palette_group_free: {
    zh: "自由色",
    en: "Free Color",
  },
  palette_group_recipe: {
    zh: "配方",
    en: "Recipe",
  },
  palette_list_label: {
    zh: "调色板颜色列表",
    en: "Palette color list",
  },

  // ==================== LUT Color Grid ====================
  // Shown as an overlay while a replacement / undo-redo is being applied and
  // the backend regenerates the preview. Key name kept for compatibility; the
  // copy is intentionally neutral — it is not about loading LUT data.
  // 替换/撤销重做进行中、后端重新出图时的遮罩文案。key 名保留兼容，文案
  // 故意中性——它并不表示加载 LUT 数据。
  lut_grid_loading: {
    zh: "正在更新预览...",
    en: "Updating preview...",
  },
  lut_grid_select_lut: {
    zh: "请先选择 LUT 以加载可用颜色",
    en: "Select a LUT to load available colors",
  },

  // ==================== Material Color Picker (material-archive mode) ====================
  material_picker_title: {
    zh: "耗材可达色",
    en: "Achievable colors",
  },
  material_picker_hint: {
    zh: "输入或选取目标颜色，系统会根据当前耗材求解出最接近的 20 个可达色。",
    en: "Pick a target color — the solver returns the 20 closest achievable colors for the current materials.",
  },
  material_picker_target_label: {
    zh: "目标颜色",
    en: "Target color",
  },
  material_picker_target_placeholder: {
    zh: "#RRGGBB",
    en: "#RRGGBB",
  },
  material_picker_submit: {
    zh: "生成建议",
    en: "Suggest colors",
  },
  material_picker_loading: {
    zh: "正在为目标色求解可达色...",
    en: "Solving achievable colors for the target...",
  },
  material_picker_empty: {
    zh: "输入目标颜色后生成可达色建议。",
    en: "Enter a target color to get achievable suggestions.",
  },
  material_picker_error: {
    zh: "求解失败：{message}",
    en: "Failed: {message}",
  },
  material_picker_no_material: {
    zh: "请先在「耗材档案」下选择至少一个耗材。",
    en: 'Select at least one material under "Material Archive" first.',
  },
  material_picker_suggestion_tooltip: {
    zh: "{hex} · ΔE={delta} · 配方 {recipe}",
    en: "{hex} · ΔE={delta} · recipe {recipe}",
  },
  material_picker_source_cache: {
    zh: "缓存命中（毫秒级返回）",
    en: "Cache hit (millisecond response)",
  },
  material_picker_source_runtime: {
    zh: "运行时命中（适合大耗材组合）",
    en: "Runtime hit (large-palette solve)",
  },
  material_picker_source_mitm: {
    zh: "MITM 实时求解（构建持久化缓存可显著加速）",
    en: "MITM live solve (build a persisted cache to accelerate)",
  },
  material_picker_result_count: {
    zh: "共 {count} 个可达色建议",
    en: "{count} achievable colors",
  },
  material_picker_delta_e_label: {
    zh: "ΔE{value}",
    en: "ΔE{value}",
  },

  // ==================== Gradient groups panel (banding detection) ====================
  gradient_groups_title: {
    zh: "渐变分组（海带纹）",
    en: "Gradient groups (banding)",
  },
  gradient_groups_hint: {
    zh: "发现 {count} 条平滑渐变被切成多个耗材色。点击「选中整组」可一次性选中组内所有颜色，再配合上方的拾色器换成同一个目标色。",
    en: "Detected {count} smooth gradients split across multiple material colors. Click Select all to multi-select the whole group, then use the picker above to replace them with a single target color.",
  },
  gradient_groups_loading: {
    zh: "正在读取渐变分组...",
    en: "Loading gradient groups...",
  },
  gradient_groups_empty: {
    zh: "未检测到海带纹渐变。",
    en: "No banding gradients detected.",
  },
  gradient_groups_error: {
    zh: "读取失败：{message}",
    en: "Failed: {message}",
  },
  gradient_groups_select_group: {
    zh: "选中整组",
    en: "Select all",
  },
  gradient_groups_select_region: {
    zh: "选中区域",
    en: "Select region",
  },
  gradient_groups_view_highlight: {
    zh: "查看高亮图",
    en: "View highlight",
  },
  gradient_groups_view_highlight_group_title: {
    zh: "第 {index} 组 高亮预览",
    en: "Group #{index} highlight preview",
  },
  gradient_groups_view_highlight_region_title: {
    zh: "第 {group} 组 · 区域 {region} 高亮预览",
    en: "Group #{group} · region #{region} highlight preview",
  },
  gradient_groups_view_highlight_loading: {
    zh: "生成高亮图中…",
    en: "Generating highlight…",
  },
  gradient_groups_view_highlight_error: {
    zh: "生成高亮图失败：{message}",
    en: "Failed to generate highlight: {message}",
  },
  gradient_groups_view_highlight_close: {
    zh: "关闭",
    en: "Close",
  },
  gradient_groups_expand_regions: {
    zh: "展开区域（{count}）",
    en: "Expand regions ({count})",
  },
  gradient_groups_collapse_regions: {
    zh: "收起区域",
    en: "Collapse regions",
  },
  gradient_groups_materials_count: {
    zh: "{count} 种颜色",
    en: "{count} colors",
  },
  gradient_groups_pixels_count: {
    zh: "{count} 像素",
    en: "{count} px",
  },
  gradient_groups_region_label: {
    zh: "区域 {index}",
    en: "Region {index}",
  },
  gradient_groups_auto_banner: {
    zh: "已按设置自动替换为代表色，可在高级设置关闭。",
    en: "Auto-replaced with representative colors (toggle off in Advanced Settings).",
  },
  gradient_groups_apply_now: {
    zh: "一键去除海带纹",
    en: "Flatten all gradients",
  },
  gradient_groups_flatten_group: {
    zh: "去海带纹",
    en: "Flatten",
  },
  gradient_groups_flatten_region: {
    zh: "去海带纹",
    en: "Flatten",
  },
  gradient_groups_merge_flatten: {
    zh: "合并去海带纹 ({count})",
    en: "Merge flatten ({count})",
  },
  gradient_groups_merge_checkbox_label: {
    zh: "勾选区域 {index} 加入合并",
    en: "Select region {index} for merge",
  },
  gradient_groups_requantize: {
    zh: "二次量化 ({count})",
    en: "Re-quantize ({count})",
  },
  // Short label for the per-region requantize button that lives on every
  // region row. Keeps the chip narrow so it does not crowd the existing
  // "Select / Flatten / Highlight" trio.
  // 单 region 行上的"二次量化"按钮文案；尽量短以免挤占同行其它按钮。
  gradient_groups_requantize_region: {
    zh: "二次量化",
    en: "Re-quantize",
  },
  // External batch button shown at the panel header so the user never has
  // to scroll back to find the group their selection belongs to.
  // 外置批量按钮文案（面板顶部）；避免用户为了找到所在分组而滚动列表。
  gradient_groups_batch_requantize: {
    zh: "批量二次量化 ({count})",
    en: "Batch re-quantize ({count})",
  },
  gradient_groups_batch_requantize_empty: {
    zh: "请先勾选至少一个区域",
    en: "Select at least one region first",
  },
  // Shown in the dialog description when the explicit target list spans
  // multiple gradient groups (the batch button can do this).
  // 批量调用跨多 group 时，dialog 描述里用这个字符串替换 {group}。
  gradient_groups_requantize_dialog_multi_group: {
    zh: "多组",
    en: "multiple",
  },
  gradient_groups_requantize_dialog_title: {
    zh: "区域二次量化",
    en: "Region re-quantization",
  },
  gradient_groups_requantize_dialog_description: {
    zh: "为分组 {group} 中勾选的 {count} 个区域分别重新量化，随后用材料求解器重新匹配。保留低频渐变，消除条纹。",
    en: "Re-quantize {count} selected region(s) in group {group} with a dedicated palette each, then re-match via the material solver. Keeps low-frequency gradients while collapsing kelp banding.",
  },
  gradient_groups_requantize_dialog_slider_label: {
    zh: "每个区域的量化色数",
    en: "Per-region quantize colour count",
  },
  gradient_groups_requantize_dialog_hint: {
    zh: "范围 {min}-{max}；值越大保留的色阶越多，越小越接近直接平坦化。",
    en: "Range {min}-{max}; larger keeps more gradient detail, smaller approximates flatten.",
  },
  gradient_groups_requantize_dialog_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  gradient_groups_requantize_dialog_submit: {
    zh: "开始量化",
    en: "Re-quantize",
  },
  gradient_groups_requantize_dialog_submitting: {
    zh: "处理中...",
    en: "Working...",
  },
  lut_grid_total_colors: {
    zh: "共 {total} 色，显示 {visible} 色",
    en: "{total} colors, showing {visible}",
  },
  lut_grid_selected: {
    zh: "已选中",
    en: "Selected",
  },
  lut_grid_search_placeholder_short: {
    zh: "搜索 HEX / RGB 颜色...",
    en: "Search HEX / RGB...",
  },
  lut_grid_hue_all_short: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_fav_short: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_hue_red_short: {
    zh: "红",
    en: "Red",
  },
  lut_grid_hue_orange_short: {
    zh: "橙",
    en: "Orange",
  },
  lut_grid_hue_yellow_short: {
    zh: "黄",
    en: "Yellow",
  },
  lut_grid_hue_green_short: {
    zh: "绿",
    en: "Green",
  },
  lut_grid_hue_cyan_short: {
    zh: "青",
    en: "Cyan",
  },
  lut_grid_hue_blue_short: {
    zh: "蓝",
    en: "Blue",
  },
  lut_grid_hue_purple_short: {
    zh: "紫",
    en: "Purple",
  },
  lut_grid_hue_neutral_short: {
    zh: "中性",
    en: "Neutral",
  },
  lut_grid_recommendations: {
    zh: "推荐替换色",
    en: "Recommended Replacements",
  },
  lut_grid_used_in_image: {
    zh: "图中使用",
    en: "Used in image",
  },
  lut_grid_other_available: {
    zh: "其他可用",
    en: "Other available",
  },
  lut_grid_all_available: {
    zh: "全部可用",
    en: "All available",
  },
  lut_grid_no_match: {
    zh: "无匹配颜色",
    en: "No matching colors",
  },
  lut_grid_color_label: {
    zh: "颜色 {hex}",
    en: "Color {hex}",
  },
  lut_grid_color_fav: {
    zh: "已收藏",
    en: "Favorited",
  },
  lut_grid_dblclick_fav: {
    zh: "双击收藏",
    en: "Double-click to favorite",
  },
  lut_grid_dblclick_unfav: {
    zh: "双击取消收藏",
    en: "Double-click to unfavorite",
  },
  lut_grid_mode_swatch: {
    zh: "色块",
    en: "Swatch",
  },
  lut_grid_mode_card: {
    zh: "色卡",
    en: "Card",
  },
  lut_grid_card_a: {
    zh: "色卡 A",
    en: "Card A",
  },
  lut_grid_card_b: {
    zh: "色卡 B",
    en: "Card B",
  },
  lut_grid_card_label: {
    zh: "色卡 {card}",
    en: "Card {card}",
  },

  // ==================== Replace Confirmation ====================
  replace_confirm_btn: {
    zh: "确认替换",
    en: "Confirm Replace",
  },
  replace_cancel_btn: {
    zh: "取消",
    en: "Cancel",
  },
  replace_preview_label: {
    zh: "替换预览",
    en: "Replace Preview",
  },

  // ==================== Image Upload ====================
  upload_drag_hint: {
    zh: "拖拽图片或点击上传",
    en: "Drag & drop image or click to upload",
  },

  // ==================== Unified Uploader ====================
  upload_unified_hint: {
    zh: "拖拽图片或 Lumina 项目文件",
    en: "Drop images or a Lumina project file",
  },
  upload_unified_multiselect_hint: {
    zh: "（图片支持多选）",
    en: "(images support multi-select)",
  },
  upload_tap_to_change: {
    zh: "点击更换或追加",
    en: "Change or add",
  },
  upload_replace_current: {
    zh: "更换当前图片",
    en: "Replace current image",
  },
  upload_unified_aria: {
    zh: "拖拽图片或 Lumina 项目文件",
    en: "Drop images or a Lumina project file",
  },
  upload_add_more: {
    zh: "添加更多图片",
    en: "Add more images",
  },
  upload_file_count: {
    zh: "已选 {count} 个文件",
    en: "{count} files selected",
  },
  upload_file_list_label: {
    zh: "已选文件列表",
    en: "Selected files list",
  },
  upload_delete_file: {
    zh: "删除 {name}",
    en: "Delete {name}",
  },
  upload_file_list_truncated: {
    zh: "还有 {count} 个文件已加入批量队列，未在这里展开显示。",
    en: "{count} more files are in the batch queue and are not expanded here.",
  },

  // ==================== Zoomable Image ====================
  zoom_reset: {
    zh: "重置缩放",
    en: "Reset Zoom",
  },

  // ==================== Batch Result Summary ====================
  batch_success: {
    zh: "成功",
    en: "Success",
  },
  batch_total: {
    zh: "总计",
    en: "Total",
  },
  batch_failed: {
    zh: "失败",
    en: "Failed",
  },
  batch_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  batch_download_zip_aria: {
    zh: "下载 ZIP 文件",
    en: "Download ZIP file",
  },
  batch_failed_files: {
    zh: "失败文件：",
    en: "Failed files:",
  },
  batch_failed_list_label: {
    zh: "失败文件列表",
    en: "Failed files list",
  },
  "batch.itemError.conversionFailed": {
    zh: "这个文件无法转换。请重新上传该文件，或查看服务端日志了解详情。",
    en: "This file could not be converted. Re-upload it or check the server log for details.",
  },
  // Merged batch 3MF download + plate-overflow warning (batch-mode-merged-3mf).
  // 批量合并 3MF 下载与超出热床范围的警告文案。
  "batch.download.mergedThreemf": {
    zh: "下载批量 3MF",
    en: "Download batch 3MF",
  },
  "batch.warnings.plateOverflow.title": {
    zh: "部分模型超出热床范围",
    en: "Some models extend beyond the print bed",
  },
  "batch.warnings.plateOverflow.body": {
    zh: "部分模型可能超出热床范围，请在切片软件中调整。",
    en: "Some models may extend beyond the print bed; please adjust them in the slicer.",
  },
  "batch.warnings.previewLimited.body": {
    zh: "批量 3MF 已包含全部成功模型；3D 预览会按当前热床尺寸自动显示可容纳的前若干个模型。",
    en: "The batch 3MF includes every successful model; the 3D preview automatically shows the first models that fit on the current print bed.",
  },
  "batch.warnings.wipeTowerManual.title": {
    zh: "打印前必须手动调整擦料塔",
    en: "Manual wipe tower adjustment required",
  },
  "batch.warnings.wipeTowerManual.body": {
    zh: "批量 3MF 已继续生成，但全部模型与擦料塔无法在所选热床上同时安全摆放。Lumina 没有缩小模型，也没有关闭擦料塔；请务必在切片软件中手动调整后再打印。",
    en: "The batch 3MF was generated, but the full model group and wipe tower cannot fit safely on the selected bed. Lumina did not scale the models or disable the tower; adjust them manually in the slicer before printing.",
  },

  // ==================== Slicer Selector ====================
  slicer_open_in: {
    zh: "在 {name} 中打开",
    en: "Open in {name}",
  },
  slicer_generate_open_in: {
    zh: "生成并在 {name} 中打开",
    en: "Generate & open in {name}",
  },
  slicer_download_3mf: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },
  slicer_generate_download: {
    zh: "生成并下载",
    en: "Generate & Download",
  },
  slicer_generate_download_3mf: {
    zh: "生成并下载 3MF",
    en: "Generate & Download 3MF",
  },
  slicer_download_failed: {
    zh: "下载文件暂时无法读取，请重新生成后再试。",
    en: "The download file could not be read. Regenerate it and try again.",
  },
  slicer_detecting: {
    zh: "正在检测切片软件...",
    en: "Detecting slicers...",
  },
  slicer_not_detected: {
    zh: "未检测到切片软件，仍可下载 3MF 文件。",
    en: "No slicer detected. You can still download the 3MF file.",
  },
  slicer_toggle_list: {
    zh: "切换切片软件列表",
    en: "Toggle slicer list",
  },
  slicer_output_hint: {
    zh: "生成后可直接在已检测到的切片软件中打开，也可以下载 3MF；大画幅任务会下载 ZIP。",
    en: "Open the generated model in a detected slicer or download the 3MF; large-format jobs download a ZIP.",
  },
  slicer_preferred_mismatch: {
    zh: "当前导出格式为 {expected}，但操作栏启动目标是 {actual}",
    en: "Current export format targets {expected}, but the action bar is set to {actual}",
  },
  slicer_preferred_missing: {
    zh: "未检测到 {name}，仍可下载 3MF 文件后手动打开。",
    en: "{name} was not detected. You can still download the 3MF file and open it manually.",
  },

  // ==================== Crop Modal ====================
  crop_modal_title: {
    zh: "裁切与旋转",
    en: "Crop & Rotate",
  },
  crop_modal_rotate_left: {
    zh: "向左旋转 90°",
    en: "Rotate left 90°",
  },
  crop_modal_rotate_right: {
    zh: "向右旋转 90°",
    en: "Rotate right 90°",
  },
  crop_modal_svg_rotation_only: {
    zh: "SVG 图片支持旋转，保留原始矢量内容。",
    en: "SVG images support rotation while preserving their vector content.",
  },
  crop_modal_close: {
    zh: "关闭",
    en: "Close",
  },
  crop_modal_original: {
    zh: "原图",
    en: "Original",
  },
  crop_modal_selection: {
    zh: "选区",
    en: "Selection",
  },
  crop_modal_free: {
    zh: "自由",
    en: "Free",
  },
  crop_modal_use_original: {
    zh: "取消",
    en: "Cancel",
  },
  crop_modal_confirm: {
    zh: "应用更改",
    en: "Apply Changes",
  },

  // ==================== Five Color Query Panel ====================
  five_color_lut_label: {
    zh: "LUT 选择",
    en: "LUT Selection",
  },
  five_color_title: {
    zh: "五色配方查询",
    en: "Five-Color Recipe Query",
  },
  five_color_desc: {
    zh: "从基础色中选出配方颜色并查询叠层后的结果色，适合快速验证色片配方。",
    en: "Pick base colors and query the blended result to validate layered color recipes quickly.",
  },
  five_color_palette: {
    zh: "基础色板",
    en: "Base Palette",
  },
  five_color_match_title: {
    zh: "按色值查询",
    en: "Match by color value",
  },
  five_color_match_desc: {
    zh: "输入目标 Hex 色值，从当前色卡中按标准最近邻匹配配方。",
    en: "Enter a target Hex value and match the nearest recipe from the current LUT card.",
  },
  five_color_match_input_label: {
    zh: "目标色值",
    en: "Target Hex",
  },
  five_color_match_input_placeholder: {
    zh: "#RRGGBB",
    en: "#RRGGBB",
  },
  five_color_match_button: {
    zh: "匹配配方",
    en: "Match recipe",
  },
  five_color_match_target: {
    zh: "目标色",
    en: "Target",
  },
  five_color_match_matched: {
    zh: "匹配色",
    en: "Matched",
  },
  five_color_match_rgb_value: {
    zh: "RGB {value}",
    en: "RGB {value}",
  },
  five_color_match_delta: {
    zh: "ΔE",
    en: "Delta E",
  },
  five_color_match_position: {
    zh: "色卡位置",
    en: "Card position",
  },
  five_color_match_card: {
    zh: "色卡 {card}",
    en: "Card {card}",
  },
  five_color_match_row: {
    zh: "第 {row} 行",
    en: "Row {row}",
  },
  five_color_match_col: {
    zh: "第 {col} 列",
    en: "Column {col}",
  },
  five_color_match_recipe: {
    zh: "匹配配方",
    en: "Matched recipe",
  },
  five_color_match_neighborhood: {
    zh: "虚拟小色卡",
    en: "Virtual card",
  },
  five_color_match_empty_cell: {
    zh: "空位",
    en: "Empty cell",
  },
  five_color_match_recipe_unavailable: {
    zh: "已找到最接近的色卡颜色，但该行无法反推出配方。",
    en: "The nearest LUT color was found, but this row cannot be converted into a recipe.",
  },
  five_color_match_recipe_unavailable_title: {
    zh: "无法生成配方",
    en: "Recipe unavailable",
  },
  five_color_error_select_lut_first: {
    zh: "请先选择 LUT",
    en: "Select a LUT first",
  },
  five_color_error_load_base_colors_failed: {
    zh: "基础色板加载失败",
    en: "Base palette loading failed",
  },
  five_color_error_match_failed: {
    zh: "按色值查询失败",
    en: "Color value lookup failed",
  },
  five_color_error_invalid_hex: {
    zh: "请输入 #RRGGBB 格式的色值",
    en: "Enter a color value in #RRGGBB format",
  },
  five_color_error_query_failed: {
    zh: "五色配方查询失败",
    en: "Five-color recipe lookup failed",
  },
  five_color_error_generate_swatch_failed: {
    zh: "色卡生成失败",
    en: "Swatch generation failed",
  },
  five_color_error_download_swatch_failed: {
    zh: "色卡下载失败",
    en: "Swatch download failed",
  },
  five_color_error_generic: {
    zh: "五色操作失败",
    en: "Five-color operation failed",
  },
  five_color_actions: {
    zh: "操作",
    en: "Actions",
  },
  five_color_lut_placeholder: {
    zh: "请选择 LUT",
    en: "Select LUT",
  },
  five_color_clear: {
    zh: "清除",
    en: "Clear",
  },
  five_color_undo: {
    zh: "撤销",
    en: "Undo",
  },
  five_color_add_to_list: {
    zh: "加入配方收藏",
    en: "Add to collection",
  },
  five_color_already_in_list: {
    zh: "已在收藏",
    en: "Already in collection",
  },
  five_color_collection_title: {
    zh: "配方收藏",
    en: "Recipe collection",
  },
  five_color_collection_count: {
    zh: "共 {count} 条",
    en: "{count} item(s)",
  },
  five_color_collection_empty: {
    zh: "尚未收藏任何配方",
    en: "No recipes collected yet",
  },
  five_color_collection_clear: {
    zh: "清空收藏",
    en: "Clear collection",
  },
  five_color_remove_recipe: {
    zh: "移除此配方",
    en: "Remove this recipe",
  },
  five_color_swatch_block_size: {
    zh: "色块尺寸 (mm)",
    en: "Block size (mm)",
  },
  five_color_swatch_gap: {
    zh: "色块间距 (mm)",
    en: "Gap (mm)",
  },
  five_color_swatch_cols: {
    zh: "每行列数",
    en: "Columns per row",
  },
  five_color_swatch_structure: {
    zh: "色卡结构",
    en: "Swatch structure",
  },
  five_color_swatch_single_sided: {
    zh: "单面",
    en: "Single-sided",
  },
  five_color_swatch_double_sided: {
    zh: "双面",
    en: "Double-sided",
  },
  five_color_swatch_legend_alt: {
    zh: "色卡预览图",
    en: "Swatch preview",
  },
  five_color_generate_swatch: {
    zh: "生成色卡",
    en: "Generate swatch",
  },
  five_color_generating_swatch: {
    zh: "生成中...",
    en: "Generating...",
  },
  five_color_download_swatch: {
    zh: "下载色卡",
    en: "Download swatch",
  },
  five_color_reverse: {
    zh: "反序",
    en: "Reverse",
  },
  five_color_query: {
    zh: "查询",
    en: "Query",
  },
  five_color_query_loading: {
    zh: "查询中...",
    en: "Querying...",
  },
  five_color_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  five_color_result_hex: {
    zh: "Hex",
    en: "Hex",
  },
  five_color_result_rgb: {
    zh: "RGB",
    en: "RGB",
  },
  five_color_result_row: {
    zh: "行号",
    en: "Row",
  },
  five_color_result_lut_row_index: {
    zh: "LUT 行索引（0 起）",
    en: "LUT row index (0-based)",
  },
  five_color_result_source: {
    zh: "来源",
    en: "Source",
  },
  five_color_result_color: {
    zh: "结果颜色 {hex}",
    en: "Result color {hex}",
  },
  five_color_result_panel: {
    zh: "查询结果",
    en: "Query Result",
  },
  five_color_not_found: {
    zh: "未找到匹配",
    en: "No match found",
  },
  five_color_not_found_message: {
    zh: "当前颜色顺序没有对应的色卡记录。",
    en: "The current color order does not match a LUT record.",
  },
  five_color_selection_progress: {
    zh: "已选择 {count}/{total} 种颜色，请继续完成配方。",
    en: "{count}/{total} colors selected. Keep building the recipe.",
  },
  five_color_selected: {
    zh: "已选颜色 {n}: {name}",
    en: "Selected color {n}: {name}",
  },
  five_color_viewing_face: {
    zh: "观赏面",
    en: "Viewing Face",
  },
  five_color_bottom_face: {
    zh: "底面",
    en: "Bottom",
  },
  five_color_slot_empty: {
    zh: "颜色槽 {n}: 空",
    en: "Color slot {n}: empty",
  },
  five_color_select_color: {
    zh: "选择颜色 {name} ({hex})",
    en: "Select color {name} ({hex})",
  },
  five_color_no_base_colors: {
    zh: "未加载到基础颜色",
    en: "No base colors loaded",
  },
  five_color_select_lut_first: {
    zh: "请先选择 LUT 以加载基础颜色",
    en: "Select a LUT to load base colors",
  },

  // ==================== Widget Error ====================
  widget_error: {
    zh: "组件出错",
    en: "Widget error",
  },
  widget_retry: {
    zh: "重试",
    en: "Retry",
  },
  widget_expand: {
    zh: "展开",
    en: "Expand",
  },
  widget_collapse: {
    zh: "折叠",
    en: "Collapse",
  },

  // ==================== WikiTooltip ====================
  wiki_tooltip_link: {
    zh: "查看 Wiki 详情 ↗",
    en: "View Wiki Details ↗",
  },
  // ==================== Vectorizer Panel ====================
  "vec.title": {
    zh: "图像转矢量",
    en: "Image Vectorizer",
  },
  "vec.upload_hint": {
    zh: "拖放或点击上传图片进行矢量化",
    en: "Drag & drop or click to upload an image for vectorization",
  },
  "vec.basic_params": {
    zh: "基础参数",
    en: "Basic Parameters",
  },
  "vec.advanced_params": {
    zh: "高级参数",
    en: "Advanced Parameters",
  },
  "vec.output_enhance": {
    zh: "输出增强",
    en: "Output Enhancement",
  },

  // Core params
  "vec.num_colors": {
    zh: "颜色数量",
    en: "Number of Colors",
  },
  "vec.num_colors_auto": {
    zh: "自动",
    en: "Auto",
  },
  "vec.num_colors_manual": {
    zh: "手动",
    en: "Manual",
  },
  "vec.detail_level": {
    zh: "细节等级",
    en: "Detail Level",
  },
  "vec.detail_level_enable": {
    zh: "启用统一细节控制",
    en: "Enable Unified Detail Control",
  },
  "vec.detail_level_on": {
    zh: "启用",
    en: "On",
  },
  "vec.detail_level_off": {
    zh: "禁用",
    en: "Off",
  },
  "vec.smoothness": {
    zh: "平滑度",
    en: "Smoothness",
  },

  // Output enhancement
  "vec.svg_enable_stroke": {
    zh: "启用描边",
    en: "Enable Stroke",
  },
  "vec.svg_stroke_width": {
    zh: "描边宽度",
    en: "Stroke Width",
  },
  "vec.thin_line_max_radius": {
    zh: "薄线检测半径",
    en: "Thin Line Max Radius",
  },
  "vec.enable_coverage_fix": {
    zh: "启用覆盖修复",
    en: "Enable Coverage Fix",
  },
  "vec.min_coverage_ratio": {
    zh: "最小覆盖率",
    en: "Min Coverage Ratio",
  },

  // Advanced - Preprocessing
  "vec.adv_preprocess": {
    zh: "预处理",
    en: "Preprocessing",
  },
  "vec.smoothing_spatial": {
    zh: "空间平滑半径",
    en: "Spatial Smoothing",
  },
  "vec.smoothing_color": {
    zh: "颜色平滑半径",
    en: "Color Smoothing",
  },
  "vec.max_working_pixels": {
    zh: "最大工作像素数",
    en: "Max Working Pixels",
  },

  // Advanced - Segmentation
  "vec.adv_segmentation": {
    zh: "超像素分割",
    en: "Superpixel Segmentation",
  },
  "vec.slic_region_size": {
    zh: "超像素区域大小",
    en: "SLIC Region Size",
  },
  "vec.edge_sensitivity": {
    zh: "边缘敏感度",
    en: "Edge Sensitivity",
  },
  "vec.refine_passes": {
    zh: "边界细化次数",
    en: "Refine Passes",
  },
  "vec.enable_antialias_detect": {
    zh: "启用抗锯齿检测",
    en: "Antialiasing Detection",
  },
  "vec.aa_tolerance": {
    zh: "抗锯齿容差",
    en: "AA Tolerance",
  },

  // Advanced - Curve fitting
  "vec.adv_curve_fitting": {
    zh: "曲线拟合",
    en: "Curve Fitting",
  },
  "vec.curve_fit_error": {
    zh: "曲线拟合误差",
    en: "Curve Fit Error",
  },
  "vec.contour_simplify": {
    zh: "轮廓简化强度",
    en: "Contour Simplification",
  },
  "vec.merge_segment_tolerance": {
    zh: "线段合并容差",
    en: "Merge Segment Tolerance",
  },

  // Advanced - Filtering
  "vec.adv_filtering": {
    zh: "区域过滤",
    en: "Region Filtering",
  },
  "vec.min_region_area": {
    zh: "最小区域面积",
    en: "Min Region Area",
  },
  "vec.max_merge_color_dist": {
    zh: "最大合并色差",
    en: "Max Merge Color Dist",
  },
  "vec.min_contour_area": {
    zh: "最小轮廓面积",
    en: "Min Contour Area",
  },
  "vec.min_hole_area": {
    zh: "最小孔洞面积",
    en: "Min Hole Area",
  },
  "vec.submit": {
    zh: "开始矢量化",
    en: "Start Vectorization",
  },
  "vec.processing": {
    zh: "正在矢量化...",
    en: "Vectorizing...",
  },
  "vec.result_title": {
    zh: "矢量化结果",
    en: "Vectorization Result",
  },
  "vec.original": {
    zh: "原始图片",
    en: "Original",
  },
  "vec.svg_preview": {
    zh: "SVG 预览",
    en: "SVG Preview",
  },
  "vec.shapes": {
    zh: "形状数",
    en: "Shapes",
  },
  "vec.colors": {
    zh: "颜色数",
    en: "Colors",
  },
  "vec.download_svg": {
    zh: "下载 SVG",
    en: "Download SVG",
  },
  "vec.send_to_converter": {
    zh: "发送到图像转换",
    en: "Send to Image Converter",
  },
  "vec.resource_action_failed": {
    zh: "SVG 文件暂时无法读取，请重新生成后再试。",
    en: "The SVG file could not be read. Regenerate it and try again.",
  },
  "vec.error": {
    zh: "矢量化失败",
    en: "Vectorization Failed",
  },
  "vec.no_image": {
    zh: "请先上传图片",
    en: "Please upload an image first",
  },

  // ===== Vectorizer Parameter Hints =====
  "vec.hint_num_colors": {
    zh: "自动模式会检测图像的最优颜色数量。切换到手动模式可指定固定值（2-256）。",
    en: "Auto mode detects the optimal color count. Switch to Manual to specify a fixed value (2-256).",
  },
  "vec.hint_smoothness": {
    zh: "整体轮廓平滑度。0 = 保留所有细节；1 = 最大平滑。控制抽稀精度和平滑迭代。",
    en: "Overall contour smoothness. 0 = preserve all details; 1 = maximum smoothing. Controls decimation precision and smoothing iterations.",
  },
  "vec.hint_detail_level": {
    zh: "统一细节控制。启用后用一个滑块同时调整多个细节参数；禁用时使用各项独立参数。",
    en: "Unified detail control. When enabled, a single slider adjusts multiple detail parameters; when disabled, individual parameters are used.",
  },
  "vec.hint_svg_enable_stroke": {
    zh: "为 SVG 路径添加描边。可以减少色块之间的接缝（白线）。",
    en: "Add stroke to SVG paths. Helps reduce visible seams (white gaps) between color regions.",
  },
  "vec.hint_svg_stroke_width": {
    zh: "描边线条的宽度。增大可更好覆盖接缝，但可能导致细节丢失。",
    en: "Width of the stroke lines. Larger values cover seams better but may blur fine details.",
  },
  "vec.hint_thin_line_max_radius": {
    zh: "薄线检测的最大半径。用于检测并保留图像中的细线结构。",
    en: "Max radius for thin line detection. Used to detect and preserve thin structures in the image.",
  },
  "vec.hint_enable_coverage_fix": {
    zh: "启用后会扩展区域边界以确保完整覆盖画布，消除微小间隙。",
    en: "Expands region boundaries to ensure full canvas coverage, eliminating tiny gaps.",
  },
  "vec.hint_min_coverage_ratio": {
    zh: "画布最小覆盖率阈值。低于此值时会触发覆盖修复。通常保持接近 1.0。",
    en: "Minimum canvas coverage ratio threshold. Coverage fix is triggered below this value. Keep close to 1.0.",
  },
  "vec.hint_smoothing_spatial": {
    zh: "Mean Shift 空间半径。增大可降噪，但可能模糊细小结构。",
    en: "Mean Shift spatial radius. Larger values reduce noise but may blur fine structures.",
  },
  "vec.hint_smoothing_color": {
    zh: "Mean Shift 颜色半径。增大可合并相近颜色，减少颜色碎片。",
    en: "Mean Shift color radius. Larger values merge similar colors, reducing color fragmentation.",
  },
  "vec.hint_max_working_pixels": {
    zh: "内部处理的最大像素数。大图会被缩小到此限制以提升速度。增大可保留更多细节但更慢。",
    en: "Max pixels for internal processing. Large images are downscaled to this limit for speed. Increase to preserve more detail at the cost of speed.",
  },
  "vec.hint_slic_region_size": {
    zh: "超像素初始区域大小。小值产生更多超像素，保留更多细节但更慢。",
    en: "Initial superpixel region size. Smaller values create more superpixels with more detail but slower processing.",
  },
  "vec.hint_edge_sensitivity": {
    zh: "边缘检测敏感度。高值更积极地保留边缘，低值产生更平滑的分割。",
    en: "Edge detection sensitivity. Higher values preserve edges more aggressively; lower values produce smoother segmentation.",
  },
  "vec.hint_refine_passes": {
    zh: "边界细化迭代次数。更多次迭代产生更精确的区域边界，但增加处理时间。",
    en: "Boundary refinement iterations. More passes produce more precise region boundaries at the cost of processing time.",
  },
  "vec.hint_enable_antialias_detect": {
    zh: "检测并处理抗锯齿像素。对带有平滑边缘的图像效果好，但可能影响像素画风格图像。",
    en: "Detect and handle antialiased pixels. Works well for images with smooth edges but may affect pixel art style images.",
  },
  "vec.hint_aa_tolerance": {
    zh: "抗锯齿检测的颜色容差（LAB ΔE）。增大可检测更多抗锯齿像素。",
    en: "Color tolerance for antialiasing detection (LAB ΔE). Increase to detect more antialiased pixels.",
  },
  "vec.hint_curve_fit_error": {
    zh: "贝塞尔曲线拟合的最大误差（像素）。小值更精确但产生更多锚点；大值更平滑但可能丢失细节。",
    en: "Max error for Bezier curve fitting (pixels). Smaller values are more precise with more anchor points; larger values are smoother but may lose detail.",
  },
  "vec.hint_contour_simplify": {
    zh: "轮廓简化强度。增大可减少轮廓点数，使路径更简洁。",
    en: "Contour simplification strength. Increase to reduce contour points for cleaner paths.",
  },
  "vec.hint_merge_segment_tolerance": {
    zh: "共线线段合并容差。增大可合并更多近似共线的线段。",
    en: "Tolerance for merging collinear segments. Increase to merge more nearly-collinear segments.",
  },
  "vec.hint_min_region_area": {
    zh: "面积小于此值的区域会被合并到相邻区域。增大可减少小碎片。",
    en: "Regions smaller than this area are merged into neighbors. Increase to reduce small fragments.",
  },
  "vec.hint_max_merge_color_dist": {
    zh: "区域合并时允许的最大色差（LAB ΔE²）。增大可合并颜色差异更大的相邻区域。",
    en: "Max color distance for region merging (LAB ΔE²). Increase to merge neighbors with larger color differences.",
  },
  "vec.hint_min_contour_area": {
    zh: "面积小于此值的轮廓会被过滤掉。用于去除微小噪点形状。",
    en: "Contours smaller than this area are filtered out. Used to remove tiny noise shapes.",
  },
  "vec.hint_min_hole_area": {
    zh: "面积小于此值的孔洞会被填充。用于去除区域内的微小空洞。",
    en: "Holes smaller than this area are filled in. Used to remove tiny voids inside regions.",
  },

  app_logo_alt: {
    zh: "Lumina Studio 标志",
    en: "Lumina Studio logo",
  },
  common_preview_alt: {
    zh: "预览图片",
    en: "Preview image",
  },
  common_unit_mm: {
    zh: "毫米",
    en: "mm",
  },
  common_pagination_label: {
    zh: "分页",
    en: "Pagination",
  },
  common_pagination_prev: {
    zh: "上一页",
    en: "Previous",
  },
  common_pagination_next: {
    zh: "下一页",
    en: "Next",
  },
  common_pagination_page: {
    zh: "第 {page} 页",
    en: "Page {page}",
  },
  common_pagination_jump: {
    zh: "前往",
    en: "Go to",
  },
  common_pagination_total_pages: {
    zh: "页，共 {count} 页",
    en: "of {count}",
  },
  common_not_available: {
    zh: "不可用",
    en: "N/A",
  },
  common_unit_px: {
    zh: "像素",
    en: "px",
  },
  common_unit_px_per_mm: {
    zh: "像素/毫米",
    en: "px/mm",
  },
  crop_modal_axis_x: {
    zh: "X 轴",
    en: "X",
  },
  crop_modal_axis_y: {
    zh: "Y 轴",
    en: "Y",
  },
  action_zoom_icon: {
    zh: "缩放",
    en: "Zoom",
  },
  action_layer_prev_arrow: {
    zh: "<",
    en: "<",
  },
  action_layer_next_arrow: {
    zh: ">",
    en: ">",
  },
  action_close_overlay: {
    zh: "关闭预览",
    en: "Close preview",
  },
  action_close_icon: {
    zh: "✕",
    en: "✕",
  },
  five_color_combinations_loaded: {
    zh: "已加载 {count} 个有效组合",
    en: "{count} valid combinations loaded",
  },
  five_color_combinations_hint: {
    zh: "灰色选项表示当前选择路径下不可用的组合。",
    en: "Gray items are unavailable for the current selection path.",
  },
  five_color_error_close_icon: {
    zh: "✕",
    en: "✕",
  },
  five_color_not_found_suggestions_title: {
    zh: "建议操作：",
    en: "Suggestions:",
  },
  five_color_not_found_tip_reverse: {
    zh: "尝试使用反转操作来反转颜色顺序。",
    en: "Try the reverse order with the reverse action.",
  },
  five_color_not_found_tip_change: {
    zh: "尝试不同的颜色组合。",
    en: "Try a different color combination.",
  },
  five_color_not_found_tip_gray: {
    zh: "灰色选项表示该位置上的无效组合。",
    en: "Gray options indicate invalid combinations at that position.",
  },

  // ==================== Recipe Share Card ====================
  share_card_footer_caption: {
    zh: "Lumina 2.0 可直接导入本图片生成",
    en: "Import this image directly into Lumina 2.0 to recreate",
  },
  recipe_export_btn: {
    zh: "导出分享卡",
    en: "Export Share Card",
  },
  recipe_export_sidecar_btn: {
    zh: "保存项目",
    en: "Save Project",
  },
  recipe_export_loading: {
    zh: "正在导出...",
    en: "Exporting...",
  },
  recipe_export_success: {
    zh: "分享卡已保存",
    en: "Share card saved",
  },
  recipe_export_error: {
    zh: "导出失败：{error}",
    en: "Export failed: {error}",
  },
  recipe_export_error_no_image: {
    zh: "请先载入图片。",
    en: "Load an image first.",
  },
  recipe_export_error_no_preview: {
    zh: "请先生成预览后再导出。",
    en: "Generate a preview before exporting.",
  },
  recipe_export_error_preview_load: {
    zh: "预览图已失效，请重新生成预览后再导出。",
    en: "The preview image is no longer available. Generate a new preview before exporting.",
  },
  recipe_export_model_surface_unavailable: {
    zh: "模型贴图暂不支持配方导出，因为配方无法包含上传模型和选面。",
    en: "Recipe export is unavailable for model texture because the uploaded model and selected face cannot be included yet.",
  },
  recipe_export_error_unknown: {
    zh: "导出没有完成，请稍后重试。",
    en: "The export did not finish. Please try again.",
  },
  recipe_import_title: {
    zh: "恢复项目",
    en: "Restore Project",
  },
  recipe_import_source_label: {
    zh: "来源",
    en: "Source",
  },
  recipe_import_source_png: {
    zh: "PNG 分享卡",
    en: "PNG Share Card",
  },
  recipe_import_source_json: {
    zh: "Lumina 项目文件",
    en: "Lumina Project File",
  },
  recipe_import_version_label: {
    zh: "应用版本",
    en: "App Version",
  },
  recipe_import_created_label: {
    zh: "创建时间",
    en: "Created",
  },
  recipe_import_lut_label: {
    zh: "LUT",
    en: "LUT",
  },
  recipe_import_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  recipe_import_size_label: {
    zh: "尺寸",
    en: "Size",
  },
  recipe_import_warnings_label: {
    zh: "警告",
    en: "Warnings",
  },
  recipe_import_confirm: {
    zh: "确认恢复",
    en: "Confirm Restore",
  },
  recipe_import_continue_workshop: {
    zh: "导入并继续编辑",
    en: "Import and Continue Editing",
  },
  recipe_import_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  announcement_title: {
    zh: "版本更新",
    en: "What's New",
  },
  announcement_close: {
    zh: "关闭",
    en: "Close",
  },
  announcement_close_label: {
    zh: "稍后再看",
    en: "Later",
  },
  announcement_mark_read: {
    zh: "知道了",
    en: "Got it",
  },
  announcement_version_label: {
    zh: "发布日期",
    en: "Released",
  },
  recipe_import_success: {
    zh: "项目已恢复",
    en: "Project restored",
  },
  recipe_import_error: {
    zh: "导入失败：{error}",
    en: "Import failed: {error}",
  },
  recipe_import_error_unreadable: {
    zh: "无法读取这个分享卡文件，请确认文件未损坏且来自 Lumina。",
    en: "This share card could not be read. Make sure the file is not corrupted and was created by Lumina.",
  },
  recipe_import_not_share_card: {
    zh: "该 PNG 不包含 Lumina 配方数据",
    en: "This PNG does not contain Lumina recipe data",
  },
  recipe_export_with_sidecar: {
    zh: "同时导出 JSON",
    en: "Also export JSON",
  },
  recipe_custom_button: {
    zh: "自定义配方",
    en: "Custom Recipe",
  },
  recipe_custom_disabled_region: {
    zh: "请先在预览图上点选一个颜色区域，再打开自定义配方",
    en: "Click a color region in the preview first, then open Custom Recipe",
  },
  recipe_custom_undo: {
    zh: "撤销编辑",
    en: "Undo edit",
  },
  recipe_custom_applied_toast: {
    zh: "已应用到当前区域。可以继续调整，或换一个区域再打开。",
    en: "Applied to this region. Keep tweaking, or pick another region and reopen.",
  },
  recipe_custom_current_region: {
    zh: "当前区域",
    en: "Current region",
  },
  recipe_custom_region_multiple: {
    zh: "已选 {count} 个区域",
    en: "{count} regions selected",
  },
  recipe_custom_title: {
    zh: "自定义配方编辑器",
    en: "Custom Recipe Editor",
  },
  recipe_custom_close: {
    zh: "关闭",
    en: "Close",
  },
  recipe_custom_layer_count: {
    zh: "{count} 层",
    en: "{count} layers",
  },
  recipe_custom_layer_label: {
    zh: "第 {index} 层",
    en: "Layer {index}",
  },
  recipe_custom_add_layer: {
    zh: "添加层",
    en: "Add Layer",
  },
  recipe_custom_remove_layer: {
    zh: "删除层",
    en: "Remove Layer",
  },
  recipe_custom_drag_handle_label: {
    zh: "按住可以拖拽更换层序",
    en: "Hold and drag to reorder layers",
  },
  recipe_custom_predict: {
    zh: "预测颜色",
    en: "Predict Color",
  },
  recipe_custom_predicting: {
    zh: "正在预测…",
    en: "Predicting…",
  },
  recipe_custom_predict_hint: {
    zh: "点击「预测颜色」查看当前配方的预览颜色。",
    en: "Use Predict Color to preview the current recipe.",
  },
  recipe_custom_preview_color: {
    zh: "预览颜色",
    en: "Preview Color",
  },
  recipe_custom_rgb_label: {
    zh: "RGB",
    en: "RGB",
  },
  recipe_custom_lab_label: {
    zh: "Lab",
    en: "Lab",
  },
  recipe_custom_apply: {
    zh: "应用到选区",
    en: "Apply to Selection",
  },
  recipe_custom_applying: {
    zh: "正在应用…",
    en: "Applying…",
  },
  recipe_custom_region_required: {
    zh: "请先选中至少一个区域，再应用自定义配方。",
    en: "Select at least one region before applying a custom recipe.",
  },
  recipe_custom_region_count: {
    zh: "目标区域：{count}",
    en: "Target Regions: {count}",
  },
  recipe_custom_pattern_placeholder: {
    zh: "输入配方，可以快速应用，例如 WRYBG",
    en: "Enter a recipe to apply quickly, e.g. WRYBG",
  },
  recipe_custom_pattern_hint: {
    zh: "可输入颜色字母快速应用。",
    en: "Enter color letters to apply quickly.",
  },
  recipe_custom_pattern_apply: {
    zh: "快速应用",
    en: "Quick Apply",
  },
  recipe_custom_pattern_invalid: {
    zh: "无法识别的字符：{char}",
    en: "Unrecognized character: {char}",
  },
  recipe_custom_predict_failed: {
    zh: "颜色预测失败",
    en: "Color prediction failed",
  },
  recipe_custom_apply_failed: {
    zh: "应用自定义配方失败",
    en: "Failed to apply custom recipe",
  },
  recipe_custom_layer_upgrade_warning: {
    zh: "新配方 {new} 层比当前预览的 {old} 层多，应用后整张图都会按新层数重新出图。再点一次确认。",
    en: "The new recipe has {new} layers, more than the current {old}-layer preview. Applying will re-render the whole image at the new layer count. Click again to confirm.",
  },
  recipe_custom_layer_upgrade_confirm: {
    zh: "确认升级层数并应用",
    en: "Confirm layer upgrade",
  },
  recipe_custom_predict_no_forward_model: {
    zh: "当前 LUT 没带预测模型，无法算出配方的颜色。",
    en: "This LUT has no forward model, so the recipe color can't be predicted.",
  },
  recipe_custom_target_from_model: {
    zh: "来自模型",
    en: "From Model",
  },
  recipe_custom_history_title: {
    zh: "历史配方",
    en: "Recipe History",
  },
  recipe_custom_history_empty: {
    zh: "应用一次后，这里会留下用过的配方。目前还没有历史记录哦。",
    en: "After you apply a recipe, it will appear here. No history yet.",
  },
  recipe_custom_history_layers: {
    zh: "{count} 层",
    en: "{count} layers",
  },
  recipe_import_lut_missing: {
    zh: "LUT 未找到，请手动选择兼容的 LUT",
    en: "LUT not found, please select a compatible LUT manually",
  },
  recipe_import_predictive_lut_unavailable: {
    zh: "此项目使用当前暂不可用的反推 LUT。请改用经典 LUT 或耗材档案。",
    en: "This project uses an inferred LUT, which is currently unavailable. Use a classic LUT or material archive instead.",
  },
  recipe_import_lut_degraded: {
    zh: "原 LUT 记录未找到，已按名称与颜色模式匹配，请确认选中了预期 LUT。",
    en: "Original LUT record unavailable; matched by name and color mode. Confirm the intended LUT is selected.",
  },
  recipe_import_warning_secondary_lut_missing: {
    zh: "部分多选 LUT 在本机未找到，已从导入选择中移除。",
    en: "Some selected LUTs were not found locally and were removed from the imported selection.",
  },
  recipe_import_warning_fridge_conflict_puzzle: {
    zh: "导入的配方同时启用了冰箱贴模式和拼图模式。为保持状态有效，拼图模式已被禁用。",
    en: "The imported recipe enabled both fridge magnet mode and puzzle mode. Puzzle mode has been disabled to keep the state valid.",
  },
  recipe_import_warning_fridge_conflict_large_format: {
    zh: "导入的配方同时启用了冰箱贴模式和大画幅切片。为保持状态有效，大画幅模式已被禁用。",
    en: "The imported recipe enabled both fridge magnet mode and large-format tiling. Large-format mode has been disabled to keep the state valid.",
  },
  recipe_import_warning_fridge_conflict_loop: {
    zh: "导入的配方同时启用了冰箱贴模式和挂件环。为保持状态有效，挂件环已被禁用。",
    en: "The imported recipe enabled both fridge magnet mode and a keychain loop. The loop has been disabled to keep the state valid.",
  },
  recipe_import_warning_puzzle_conflict_large_format: {
    zh: "导入的配方同时启用了拼图模式和大画幅切片。为保持状态有效，大画幅模式已被禁用。",
    en: "The imported recipe enabled both puzzle mode and large-format tiling. Large-format mode has been disabled to keep the state valid.",
  },
  recipe_import_warning_puzzle_conflict_loop: {
    zh: "导入的配方同时启用了拼图模式和挂件环。为保持状态有效，挂件环已被禁用。",
    en: "The imported recipe enabled both puzzle mode and a keychain loop. The loop has been disabled to keep the state valid.",
  },
  recipe_import_warning_back_labels_unavailable: {
    zh: "导入的配方启用了拼图背面标签。当前版本暂不支持背面标签，已自动关闭。",
    en: "The imported recipe enabled puzzle back labels. Back labels are not available in this version and have been disabled.",
  },
  recipe_import_warning_spatial_edits_not_serialized: {
    zh: "这个旧项目未保存局部改色的空间数据，无法还原缺失的选区；原图和其他参数仍会恢复。",
    en: "This older project did not save the spatial data for local color edits. Missing selections cannot be recovered; the original source and other settings will still be restored.",
  },
  recipe_import_warning_region_recipes_not_restored: {
    zh: "这个旧项目缺少区域配方的实际掩码，不能确定原来的应用范围；已保留配方历史，可重新选区后应用。",
    en: "This older project is missing the actual masks for region recipes, so their original scope cannot be recovered. Recipe history is kept for reuse after selecting a new region.",
  },
  recipe_import_workshop_degraded: {
    zh: "分享卡中的创意工坊编辑数据已损坏或当前不可用；主图和转换参数仍可正常导入。",
    en: "The workshop editing data in this share card is damaged or unavailable. The main image and converter settings can still be imported.",
  },
  workshop_source_banner_title: {
    zh: "创意工坊图像",
    en: "Creative Workshop image",
  },
  workshop_source_banner_module: {
    zh: "来源模块",
    en: "Source module",
  },
  workshop_source_banner_module_value: {
    zh: "{id} · v{version}",
    en: "{id} · v{version}",
  },
  workshop_source_banner_print_library: {
    zh: "当前打印色库",
    en: "Current print library",
  },
  workshop_source_banner_library_unavailable: {
    zh: "尚未选择可用色库",
    en: "No usable library selected",
  },
  workshop_source_banner_library_changed: {
    zh: "打印色库已变化；图纸原色不受影响，将按当前色库重新叠色。",
    en: "The print library changed. Source colors are unchanged and will be remapped with the current library.",
  },
  workshop_source_banner_guidance: {
    zh: "源色色块由创意工坊保留；下方 LUT 或耗材档案只负责叠色打印，不会覆盖源色。",
    en: "Source color blocks stay with the Workshop project. The LUT or material archive below controls layered printing without replacing those source colors.",
  },
  workshop_runtime_preparing: {
    zh: "正在准备模块",
    en: "Preparing module",
  },
  workshop_runtime_loading: {
    zh: "正在加载模块",
    en: "Loading module",
  },
  workshop_runtime_handshaking: {
    zh: "正在建立安全连接",
    en: "Establishing secure connection",
  },
  workshop_runtime_waiting_ready: {
    zh: "正在等待模块就绪",
    en: "Waiting for module readiness",
  },
  workshop_runtime_running: {
    zh: "运行中",
    en: "Running",
  },
  workshop_runtime_desktop_required: {
    zh: "此模块需要 Lumina 桌面版才能运行",
    en: "This module requires the Lumina desktop app",
  },
  workshop_runtime_disabled: {
    zh: "此模块已被禁用",
    en: "This module is disabled",
  },
  workshop_runtime_incompatible: {
    zh: "此模块与当前创意工坊接口不兼容",
    en: "This module is incompatible with the current Workshop API",
  },
  workshop_runtime_handshake_timeout: {
    zh: "模块启动超时",
    en: "Module startup timed out",
  },
  workshop_runtime_snapshot_failed: {
    zh: "更新前项目快照失败，模块未启动",
    en: "The pre-update project snapshot failed, so the module was not started",
  },
  workshop_runtime_activation_failed: {
    zh: "候选版本未能安全激活",
    en: "The candidate version could not be activated safely",
  },
  workshop_runtime_load_failed: {
    zh: "模块加载失败",
    en: "Module failed to load",
  },
  "workshop.manager.eyebrow": {
    zh: "Lumina Studio",
    en: "Lumina Studio",
  },
  "workshop.manager.description": {
    zh: "安装、管理并在隔离环境中运行图像创作模块。",
    en: "Install, manage, and run image-creation modules in an isolated environment.",
  },
  "workshop.manager.navigation": {
    zh: "创意工坊页面",
    en: "Creative Workshop views",
  },
  "workshop.manager.view.installed": {
    zh: "已安装",
    en: "Installed",
  },
  "workshop.manager.view.discover": {
    zh: "发现",
    en: "Discover",
  },
  "workshop.manager.view.developer": {
    zh: "开发者",
    en: "Developer",
  },
  "workshop.manager.source.official": {
    zh: "官方",
    en: "Official",
  },
  "workshop.manager.source.community": {
    zh: "社区",
    en: "Community",
  },
  "workshop.manager.source.unreviewed": {
    zh: "未审核",
    en: "Unreviewed",
  },
  "workshop.manager.enabled": {
    zh: "已启用",
    en: "Enabled",
  },
  "workshop.manager.disabled": {
    zh: "已停用",
    en: "Disabled",
  },
  "workshop.manager.currentVersion": {
    zh: "当前版本 {version}",
    en: "Current version {version}",
  },
  "workshop.manager.candidateVersion": {
    zh: "待激活版本 {version}",
    en: "Candidate version {version}",
  },
  "workshop.manager.activeMeta": {
    zh: "{name} · v{version}",
    en: "{name} · v{version}",
  },
  "workshop.manager.updateAvailable": {
    zh: "可更新至 {version}",
    en: "Update available: {version}",
  },
  "workshop.manager.projectsRetained": {
    zh: "保留了本地工程",
    en: "Local projects retained",
  },
  "workshop.manager.officialUninstalled": {
    zh: "官方模块已卸载",
    en: "Official module is uninstalled",
  },
  "workshop.manager.restoreSeed": {
    zh: "从离线种子恢复",
    en: "Restore from offline seed",
  },
  "workshop.manager.open": {
    zh: "打开",
    en: "Open",
  },
  "workshop.manager.reviewCandidate": {
    zh: "审查权限并打开候选版本",
    en: "Review permissions and open candidate",
  },
  "workshop.manager.blocked": {
    zh: "已被 Registry 阻止",
    en: "Blocked by the Registry",
  },
  "workshop.manager.desktopOnly": {
    zh: "仅桌面版可打开",
    en: "Desktop app required",
  },
  "workshop.manager.details": {
    zh: "详情",
    en: "Details",
  },
  "workshop.manager.update": {
    zh: "更新",
    en: "Update",
  },
  "workshop.manager.rollback": {
    zh: "回退",
    en: "Roll back",
  },
  "workshop.manager.enable": {
    zh: "启用",
    en: "Enable",
  },
  "workshop.manager.disable": {
    zh: "停用",
    en: "Disable",
  },
  "workshop.manager.uninstall": {
    zh: "卸载",
    en: "Uninstall",
  },
  "workshop.manager.install": {
    zh: "安装",
    en: "Install",
  },
  "workshop.manager.installedCurrent": {
    zh: "已安装最新兼容版本",
    en: "Latest compatible version installed",
  },
  "workshop.manager.loading": {
    zh: "正在读取已安装模块…",
    en: "Loading installed modules…",
  },
  "workshop.manager.loadError": {
    zh: "无法读取已安装模块。",
    en: "Installed modules could not be loaded.",
  },
  "workshop.manager.noInstalled": {
    zh: "尚未安装任何创意工坊模块。",
    en: "No Creative Workshop modules are installed.",
  },
  "workshop.manager.catalogLoading": {
    zh: "正在验证创意工坊目录…",
    en: "Verifying the Workshop catalog…",
  },
  "workshop.manager.catalogInvalid": {
    zh: "目录签名验证失败，未显示任何模块。",
    en: "Catalog signature verification failed. No modules are shown.",
  },
  "workshop.manager.retry": {
    zh: "重试",
    en: "Retry",
  },
  "workshop.manager.runtime.desktop-secure": {
    zh: "桌面安全模式：社区模块在独立沙箱中运行，无法访问网络或本机文件路径。",
    en: "Desktop secure mode: community modules run in an isolated sandbox without network or filesystem-path access.",
  },
  "workshop.manager.runtime.browser-restricted": {
    zh: "浏览器限制模式：预装官方模块和签名 Registry 中的官方模块可在受限沙箱运行；社区与未审核模块需要桌面版。",
    en: "Browser restricted mode: bundled official modules and official modules from the signed Registry can run in the restricted sandbox; community and unreviewed modules require the desktop app.",
  },
  "workshop.manager.runtime.unsafe-development": {
    zh: "不安全开发模式：仅本地模块可用合成数据调试，不会获得真实图片、工程或色库。",
    en: "Unsafe development mode: local modules receive synthetic debug data instead of real images, projects, or color libraries.",
  },
  "workshop.manager.operationError": {
    zh: "模块操作失败，现有安装和工程数据未被替换。",
    en: "The module operation failed. Existing installation and project data were not replaced.",
  },
  "workshop.manager.recipeImportSaveError": {
    zh: "无法把分享配方交给模块；转换器内容仍然可用。",
    en: "The shared recipe could not be handed to the module; converter content remains available.",
  },
  "workshop.manager.recipeModuleMissing": {
    zh: "主图和转换参数已恢复。若要继续编辑，请安装 {id} 的 {version} 版本。",
    en: "The image and converter settings were restored. Install {id} version {version} to continue editing.",
  },
  "workshop.manager.recipeModuleDiscover": {
    zh: "前往发现",
    en: "Open Discover",
  },
  "workshop.manager.localTitle": {
    zh: "安装本地模块包",
    en: "Install a local module package",
  },
  "workshop.manager.localDescription": {
    zh: "选择经过验证的 .lumina-workshop 单文件安装包。浏览器中不会向它提供真实数据。",
    en: "Choose a validated single-file .lumina-workshop package. Browser mode does not provide it with real data.",
  },
  "workshop.manager.localPackage": {
    zh: "本地模块包",
    en: "Local module package",
  },
  "workshop.manager.localInvalid": {
    zh: "请选择扩展名为 .lumina-workshop 的安装包。",
    en: "Choose a package with the .lumina-workshop extension.",
  },
  "workshop.manager.githubTitle": {
    zh: "从 GitHub Release 安装",
    en: "Install from a GitHub Release",
  },
  "workshop.manager.githubRepository": {
    zh: "GitHub 仓库",
    en: "GitHub repository",
  },
  "workshop.manager.githubPlaceholder": {
    zh: "https://github.com/所有者/仓库",
    en: "https://github.com/owner/repository",
  },
  "workshop.manager.exactVersion": {
    zh: "精确版本",
    en: "Exact version",
  },
  "workshop.manager.installGithub": {
    zh: "从 GitHub 安装",
    en: "Install from GitHub",
  },
  "workshop.manager.githubInvalid": {
    zh: "请输入规范的 GitHub 仓库地址和精确语义版本。",
    en: "Enter a canonical GitHub repository URL and an exact semantic version.",
  },
  "workshop.manager.permissionTitle": {
    zh: "确认新增权限",
    en: "Confirm added permissions",
  },
  "workshop.manager.permissionInstallTitle": {
    zh: "确认模块权限",
    en: "Confirm module permissions",
  },
  "workshop.manager.permissionDescription": {
    zh: "这个更新请求了当前版本没有的权限。确认前不会安装或激活候选版本。",
    en: "This update requests permissions not used by the current version. The candidate will not be installed or activated before confirmation.",
  },
  "workshop.manager.permissionInstallDescription": {
    zh: "安装包已通过校验并暂存。确认后才会在隔离环境中启动，并在成功就绪后激活。",
    en: "The package has been validated and staged. It runs only after confirmation and activates only after becoming ready in the sandbox.",
  },
  "workshop.manager.newPermissions": {
    zh: "新增权限",
    en: "Added permissions",
  },
  "workshop.manager.requestedPermissions": {
    zh: "请求的权限",
    en: "Requested permissions",
  },
  "workshop.manager.confirmPermissions": {
    zh: "确认权限并更新",
    en: "Confirm permissions and update",
  },
  "workshop.manager.confirmPermissionsAndOpen": {
    zh: "确认权限并打开",
    en: "Confirm permissions and open",
  },
  "workshop.manager.cancel": {
    zh: "取消",
    en: "Cancel",
  },
  "workshop.manager.permission.image.pick": {
    zh: "选择图片",
    en: "Choose images",
  },
  "workshop.manager.permission.project.storage": {
    zh: "读写模块工程",
    en: "Read and write module projects",
  },
  "workshop.manager.permission.color-library.read": {
    zh: "读取当前打印色库",
    en: "Read the current print color library",
  },
  "workshop.manager.permission.handoff.image": {
    zh: "将图像交给转换器",
    en: "Hand images to the converter",
  },
  "workshop.manager.uninstallTitle": {
    zh: "卸载模块",
    en: "Uninstall module",
  },
  "workshop.manager.uninstallDescription": {
    zh: "默认只删除模块代码并保留本地工程。删除工程需要单独确认。",
    en: "By default, only module code is removed and local projects are retained. Deleting projects requires separate confirmation.",
  },
  "workshop.manager.deleteProjects": {
    zh: "同时删除本地工程",
    en: "Also delete local projects",
  },
  "workshop.manager.confirmUninstall": {
    zh: "确认卸载",
    en: "Confirm uninstall",
  },
  "workshop.manager.close": {
    zh: "关闭",
    en: "Close",
  },
  "workshop.manager.detailsError": {
    zh: "无法读取此版本的公开说明。",
    en: "Public details for this version could not be loaded.",
  },
  "workshop.manager.license": {
    zh: "许可证",
    en: "License",
  },
  recipe_import_schema_newer: {
    zh: "配方版本较新，部分参数可能无法恢复",
    en: "Recipe uses a newer schema version — some parameters may not restore",
  },
  recipe_import_asset_corrupt: {
    zh: "素材数据损坏，无法恢复原始文件",
    en: "Asset data is corrupted — unable to restore original file",
  },

  lut_info_schema_label: {
    zh: "Schema",
    en: "Schema",
  },
  lut_info_capabilities_label: {
    zh: "能力",
    en: "Capabilities",
  },
  lut_info_predictive_enabled: {
    zh: "支持预测式匹配",
    en: "Predictive match enabled",
  },
  lut_info_predictive_disabled: {
    zh: "仅传统查表",
    en: "Legacy lookup only",
  },
  lut_info_dynamic_enabled: {
    zh: "支持动态层高",
    en: "Dynamic layer height enabled",
  },
  lut_info_dynamic_disabled: {
    zh: "固定层高",
    en: "Fixed layer height",
  },
  lut_info_dynamic_count_enabled: {
    zh: "支持动态层数",
    en: "Dynamic layer count enabled",
  },
  lut_info_dynamic_count_disabled: {
    zh: "固定层数",
    en: "Fixed layer count",
  },
  lut_info_custom_recipe_enabled: {
    zh: "支持自定义配方",
    en: "Custom recipe enabled",
  },
  lut_info_custom_recipe_disabled: {
    zh: "不支持自定义配方",
    en: "Custom recipe unavailable",
  },
  lut_info_source_kind_label: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_info_supported_modes_label: {
    zh: "支持模式",
    en: "Supported Modes",
  },
  lut_info_capability_legacy_lookup: {
    zh: "传统查表",
    en: "Legacy lookup",
  },
  lut_info_capability_predictive_match: {
    zh: "预测式匹配",
    en: "Predictive match",
  },
  lut_info_capability_predictive_model: {
    zh: "预测模型",
    en: "Predictive model",
  },
  lut_info_capability_dynamic_layer_height: {
    zh: "动态层高",
    en: "Dynamic layer height",
  },
  lut_info_capability_dynamic_layer_count: {
    zh: "动态层数",
    en: "Dynamic layer count",
  },
  lut_info_capability_custom_recipe: {
    zh: "自定义配方",
    en: "Custom recipe",
  },
  lut_info_capability_native_reference: {
    zh: "原生参考源",
    en: "Native reference",
  },
  lut_compare_warning_schema_mismatch: {
    zh: "Schema 版本不一致：{schemaA} vs {schemaB}",
    en: "Schema versions differ: {schemaA} vs {schemaB}",
  },
  lut_compare_warning_predictive_mismatch: {
    zh: "预测式匹配支持不一致：{valueA} vs {valueB}",
    en: "Predictive match support differs: {valueA} vs {valueB}",
  },
  lut_compare_warning_dynamic_mismatch: {
    zh: "动态层高支持不一致：{valueA} vs {valueB}",
    en: "Dynamic layer height support differs: {valueA} vs {valueB}",
  },
  action_lut_match_label: {
    zh: "LUT 匹配",
    en: "LUT Match",
  },
  action_lut_match_legacy: {
    zh: "传统查表",
    en: "Legacy KD-tree",
  },
  action_lut_match_predictive: {
    zh: "预测式运行时",
    en: "Predictive Runtime",
  },
  action_lut_match_mode_key: {
    zh: "模式 {mode}",
    en: "Mode {mode}",
  },
  recipe_editor_button: {
    zh: "自定义配方",
    en: "Custom Recipe",
  },
  recipe_editor_title: {
    zh: "自定义配方编辑器",
    en: "Custom Recipe Editor",
  },
  recipe_editor_layers_label: {
    zh: "按层编辑当前选区的配方，并可直接预测颜色。",
    en: "Edit the per-layer recipe for the current selection and predict its color.",
  },
  recipe_editor_layer_n: {
    zh: "第 {n} 层",
    en: "Layer {n}",
  },
  recipe_editor_add_layer: {
    zh: "添加层",
    en: "Add Layer",
  },
  recipe_editor_remove_layer: {
    zh: "删除层",
    en: "Remove Layer",
  },
  recipe_editor_move_up: {
    zh: "上移",
    en: "Move Up",
  },
  recipe_editor_move_down: {
    zh: "下移",
    en: "Move Down",
  },
  recipe_editor_predict: {
    zh: "预测颜色",
    en: "Predict Color",
  },
  recipe_editor_predict_loading: {
    zh: "预测中...",
    en: "Predicting...",
  },
  recipe_editor_predict_failed: {
    zh: "颜色预测失败",
    en: "Color prediction failed",
  },
  recipe_editor_search: {
    zh: "搜索候选",
    en: "Search Recipes",
  },
  recipe_editor_search_loading: {
    zh: "搜索中...",
    en: "Searching...",
  },
  recipe_editor_search_placeholder: {
    zh: "按层搜索，如 W?BK*",
    en: "Search by layer pattern, e.g. W?BK*",
  },
  recipe_editor_search_results: {
    zh: "候选配方",
    en: "Candidate Recipes",
  },
  recipe_editor_search_failed: {
    zh: "配方搜索失败",
    en: "Recipe search failed",
  },
  recipe_editor_apply: {
    zh: "应用到选区",
    en: "Apply to Selection",
  },
  recipe_editor_apply_failed: {
    zh: "配方应用失败",
    en: "Failed to apply recipe override",
  },
  recipe_editor_clear: {
    zh: "清除覆盖",
    en: "Clear Override",
  },
  recipe_editor_no_region: {
    zh: "请先选择一个区域或选区。",
    en: "Select a region or active selection first.",
  },
  recipe_editor_upgrade_confirm: {
    zh: "当前全局层数为 {old}，应用该配方后会升到 {new} 层。继续吗？",
    en: "The current global layer count is {old}. Applying this recipe will upgrade it to {new}. Continue?",
  },
  cal_workflow_label: {
    zh: "工作流模式",
    en: "Workflow",
  },
  cal_substrate_id_label: {
    zh: "基板 ID",
    en: "Substrate ID",
  },
  cal_substrate_name_label: {
    zh: "基板名称",
    en: "Substrate Name",
  },
  cal_material_default_label: {
    zh: "默认材料",
    en: "Default Material",
  },
  cal_single_stage_layer_height_label: {
    zh: "层高",
    en: "Layer Height",
  },
  cal_generate_single_stage_btn: {
    zh: "生成 梯度色卡",
    en: "Generate Single-Stage Kit",
  },
  cal_download_kit: {
    zh: "下载 Kit ZIP",
    en: "Download Kit ZIP",
  },
  cal_download_manifest: {
    zh: "下载 Manifest",
    en: "Download Manifest",
  },
  cal_single_stage_jobs_title: {
    zh: "Single-Stage 任务",
    en: "Single-Stage Jobs",
  },
  cal_single_stage_jobs_desc: {
    zh: "每个颜色都会生成一个可打印的 3MF 任务",
    en: "One printable 3MF job is generated per color",
  },
  mat_gradient_generate_title: {
    zh: "生成梯度卡",
    en: "Generate Gradient Card",
  },
  mat_gradient_generate_desc: {
    zh: "生成用于打印和提取的梯度卡文件包（包含不同层高的切片配置文件和参数信息）。",
    en: "Generate gradient card print files (including slicer profiles and parameters) used for printing and color extraction.",
  },
  mat_gradient_generate_section_title: {
    zh: "生成设置",
    en: "Generation Settings",
  },
  mat_gradient_generate_section_desc: {
    zh: "选择你的打印层高，生成包含 3MF 打印文件和提取所需的配置包。",
    en: "Select your print layer height and generate the package containing 3MF print files and configuration needed for extraction.",
  },
  mat_gradient_generate_notice_title: {
    zh: "使用须知与线上模型",
    en: "Instructions & Online Models",
  },
  mat_gradient_generate_notice_desc: {
    zh: "打印前请务必阅读此说明，以确保后续操作顺利进行。",
    en: "Please read these instructions before printing to ensure smooth operation later.",
  },
  mat_gradient_generate_notice_dual_print: {
    zh: "每种耗材需要打印两张梯度卡：白底、黑底各一张。",
    en: "Each material requires printing two gradient cards: one with a white base and one with a black base.",
  },
  mat_gradient_generate_notice_config: {
    zh: "请按打印层高生成并保存配置文件包（ZIP），提取梯度卡时需要导入。使用在线模型也需要此配置包。",
    en: "Generate and save the configuration ZIP for your print layer height. Import it when extracting gradient cards, including cards printed from online models.",
  },
  mat_gradient_generate_notice_online_model: {
    zh: "也可从 MakerWorld 下载模型，请确认模型层高与所选层高一致。下载获得的积分将用于 Lumina 社区抽奖。",
    en: "Models are also available on MakerWorld. Check that the model layer height matches your selection. Download points support Lumina community giveaways.",
  },
  mat_gradient_model_open_error: {
    zh: "无法打开模型页面，请重试或复制链接到浏览器中打开。",
    en: "Could not open the model page. Try again or copy the link into your browser.",
  },
  mat_gradient_generate_online_model_link: {
    zh: "梯度卡在线模型",
    en: "Gradient Card Online Model",
  },
  mat_gradient_generate_parametric_box_link: {
    zh: "梯度卡收纳盒在线模型",
    en: "Gradient Card Parametric Storage Box",
  },
  mat_gradient_generate_btn: {
    zh: "生成配置文件包",
    en: "Generate Configuration Package",
  },
  mat_gradient_download_title: {
    zh: "下载结果",
    en: "Download Result",
  },
  mat_gradient_download_desc: {
    zh: "配置包已生成，请下载并妥善保存。在提取色彩时需要上传此 ZIP 文件。",
    en: "Configuration package generated. Please download and save it. You will need to upload this ZIP file during color extraction.",
  },
  mat_gradient_download_btn: {
    zh: "下载配置文件包 (.zip)",
    en: "Download Configuration Package (.zip)",
  },
  mat_gradient_extract_title: {
    zh: "提取梯度卡数据",
    en: "Extract Gradient Card Data",
  },
  mat_gradient_extract_desc: {
    zh: "首先导入下载好的梯度卡ZIP，然后分别上传白底与黑底照片，并框选出色块区域即可完成提取。",
    en: "First import the downloaded gradient card ZIP, then upload the white and black background photos separately, and bound the color blocks area to complete extraction.",
  },
  mat_gradient_colorchecker_hint: {
    zh: "这里的 ColorChecker 只负责先校正白底图或黑底图的颜色；确认使用后，梯度卡提取会明确标记为已校色图片来源。",
    en: "ColorChecker only corrects the white or black image first. After you accept it, gradient extraction explicitly records the image as a calibrated source.",
  },
  mat_gradient_colorchecker_white_btn: {
    zh: "校色白底图",
    en: "Calibrate White Image",
  },
  mat_gradient_colorchecker_black_btn: {
    zh: "校色黑底图",
    en: "Calibrate Black Image",
  },
  mat_gradient_colorchecker_restored_source: {
    zh: "已使用校色后的图片。后续提取会标记为校色来源，避免和原始拍摄图混用。",
    en: "Using the corrected image. Later extraction will keep it separate from original captures.",
  },
  mat_gradient_view_details_btn: {
    zh: "查看详细信息",
    en: "View Details",
  },
  mat_gradient_details_dialog_title: {
    zh: "提取详细信息",
    en: "Extraction Details",
  },
  mat_gradient_details_dialog_desc: {
    zh: "拟合参数和材料摘要的原始数据，可用于排查问题或手动校准。",
    en: "Raw fit parameters and material summary for troubleshooting or manual calibration.",
  },
  mat_gradient_details_close_btn: {
    zh: "关闭",
    en: "Close",
  },
  mat_gradient_select_dataset_btn: {
    zh: "选择数据集 ZIP",
    en: "Choose Dataset ZIP",
  },
  mat_gradient_no_dataset_selected: {
    zh: "尚未选择数据集 ZIP",
    en: "No dataset ZIP selected",
  },
  mat_gradient_invalid_zip_error: {
    zh: "你上传的 ZIP 不是正确的梯度卡 Kit ZIP，请重新选择生成时下载的 Kit ZIP。",
    en: "The uploaded ZIP is not a valid gradient card kit. Please reselect the Kit ZIP downloaded during generation.",
  },
  mat_gradient_extract_inputs_required_error: {
    zh: "请先选择 Kit ZIP，并上传白底图和黑底图。",
    en: "Please choose the Kit ZIP and upload both the white and black images first.",
  },
  mat_gradient_extract_corners_required_error: {
    zh: "请先在白底图和黑底图上各点选四个角。",
    en: "Please mark four corners on both the white and black images first.",
  },
  mat_gradient_extract_colorchecker_pair_required_error: {
    zh: "ColorChecker 校色图需要白底图和黑底图都确认后才能用于梯度卡拟合。",
    en: "Confirm both white and black ColorChecker images before using them for gradient-card fitting.",
  },
  mat_gradient_colorchecker_confirm_error: {
    zh: "ColorChecker 校色图确认失败，请重新执行校色后再试。",
    en: "Failed to confirm the ColorChecker calibrated image. Please recalibrate and try again.",
  },
  mat_gradient_invalid_image_error: {
    zh: "上传的图片无法识别，请重新选择清晰且完整的梯度卡照片。",
    en: "The uploaded image could not be read. Please reselect a clear and complete gradient card photo.",
  },
  mat_gradient_heic_unsupported_error: {
    zh: "当前环境暂不支持 HEIC/HEIF 图片，请先转换为 PNG 或 JPG 后再上传。",
    en: "HEIC/HEIF images are not supported in the current environment. Please convert them to PNG or JPG before uploading.",
  },
  mat_gradient_invalid_corner_error: {
    zh: "四角数据无效，请重新点选四个角后再试。",
    en: "The corner selection is invalid. Please re-mark the four corners and try again.",
  },
  mat_gradient_invalid_orientation_error: {
    zh: "无法可靠判断梯度卡方向，请检查图片方向和四角位置后重试。",
    en: "The gradient card orientation could not be determined reliably. Please check the image orientation and corner positions, then try again.",
  },
  mat_gradient_extract_failed_error: {
    zh: "梯度卡提取失败，请重试。",
    en: "Gradient card extraction failed. Please try again.",
  },
  mat_gradient_rotate_white_failed: {
    zh: "白底梯度卡图片旋转失败，请重试。",
    en: "Failed to rotate the white gradient card image. Please try again.",
  },
  mat_gradient_rotate_black_failed: {
    zh: "黑底梯度卡图片旋转失败，请重试。",
    en: "Failed to rotate the black gradient card image. Please try again.",
  },
  mat_gradient_save_requires_extract_error: {
    zh: "请先完成提取，再保存耗材档案。",
    en: "Please complete extraction before saving the material archive.",
  },
  mat_gradient_save_name_required_error: {
    zh: "请输入耗材名称后再保存。",
    en: "Please enter a material name before saving.",
  },
  mat_gradient_save_session_expired_error: {
    zh: "当前提取结果已失效，请重新提取后再保存。",
    en: "The current extraction result has expired. Please run extraction again before saving.",
  },
  mat_gradient_save_target_missing_error: {
    zh: "目标耗材档案不存在，可能已被删除，请刷新后重试。",
    en: "The target material archive no longer exists. It may have been deleted. Please refresh and try again.",
  },
  mat_gradient_save_target_invalid_error: {
    zh: "目标耗材档案已损坏，无法继续保存，请检查后重试。",
    en: "The target material archive is invalid, so saving cannot continue. Please check it and try again.",
  },
  mat_gradient_save_failed_error: {
    zh: "保存耗材档案失败，请重试。",
    en: "Saving the material archive failed. Please try again.",
  },
  mat_gradient_extract_output_title: {
    zh: "提取输出",
    en: "Extraction Output",
  },
  mat_gradient_fit_output_title: {
    zh: "拟合输出",
    en: "Fit Output",
  },
  mat_gradient_upload_title: {
    zh: "导入生成的梯度卡ZIP",
    en: "Import Generated Gradient Card ZIP",
  },
  mat_gradient_upload_desc: {
    zh: "导入您在梯度卡生成工具中下载的zip。",
    en: "Import the ZIP you downloaded from the gradient card generation tool.",
  },
  mat_gradient_white_image_label: {
    zh: "白底梯度卡图片",
    en: "White Gradient Card Image",
  },
  mat_gradient_black_image_label: {
    zh: "黑底梯度卡图片",
    en: "Black Gradient Card Image",
  },
  mat_gradient_no_image_selected: {
    zh: "尚未选择图片",
    en: "No image selected",
  },
  mat_gradient_select_image_btn: {
    zh: "选择图片",
    en: "Choose Image",
  },
  mat_gradient_rotate_cw_btn: {
    zh: "顺时针 90°",
    en: "Rotate 90° CW",
  },
  mat_gradient_rotate_ccw_btn: {
    zh: "逆时针 90°",
    en: "Rotate 90° CCW",
  },
  mat_gradient_clear_points_btn: {
    zh: "清除角点",
    en: "Clear Corners",
  },
  mat_gradient_corner_hint_prefix: {
    zh: "已标记角点",
    en: "Corners Marked",
  },
  mat_gradient_corner_complete: {
    zh: "四角已完成，可开始提取。",
    en: "All four corners are set and ready for extraction.",
  },
  mat_gradient_white_canvas_title: {
    zh: "白底梯度卡",
    en: "White Gradient Card",
  },
  mat_gradient_black_canvas_title: {
    zh: "黑底梯度卡",
    en: "Black Gradient Card",
  },
  mat_gradient_empty_white_canvas: {
    zh: "上传白底梯度卡图片后，在这里点选四角。",
    en: "Upload the white gradient card image to mark its four corners here.",
  },
  mat_gradient_empty_black_canvas: {
    zh: "上传黑底梯度卡图片后，在这里点选四角。",
    en: "Upload the black gradient card image to mark its four corners here.",
  },
  mat_gradient_compute_btn: {
    zh: "提取耗材",
    en: "Extract Material",
  },
  mat_gradient_material_name_label: {
    zh: "耗材名称",
    en: "Material Name",
  },
  mat_gradient_material_name_placeholder: {
    zh: "输入要保存的耗材名称",
    en: "Enter the material name to save",
  },
  mat_gradient_brand_label: {
    zh: "品牌（可选）",
    en: "Brand (optional)",
  },
  mat_gradient_brand_placeholder: {
    zh: "例如：瑞贝思、拓竹",
    en: "e.g. Ribes, Bambu Lab",
  },
  mat_gradient_brand_hint: {
    zh: "填写后，该耗材将保存至 materials/<品牌>/<耗材名>/",
    en: "If set, the material is saved under materials/<brand>/<name>/",
  },
  mat_gradient_brand_loading: {
    zh: "正在加载已有品牌...",
    en: "Loading saved brands...",
  },
  mat_gradient_brand_empty: {
    zh: "暂无已有品牌，可直接输入新品牌",
    en: "No saved brands yet. You can type a new brand directly.",
  },
  mat_gradient_brand_create_option: {
    zh: "新增品牌：{brand}",
    en: "Create brand: {brand}",
  },
  mat_gradient_save_material_btn: {
    zh: "保存耗材档案",
    en: "Save Material Archive",
  },
  mat_gradient_warp_preview_title: {
    zh: "透视校正预览",
    en: "Perspective Warp Preview",
  },
  mat_gradient_sample_boxes_hint: {
    zh: "方框表示实际取色区域。",
    en: "Boxes indicate the actual sampled regions.",
  },
  mat_gradient_estimated_color_title: {
    zh: "计算出的耗材颜色",
    en: "Estimated Material Color",
  },
  mat_gradient_rgb_label: {
    zh: "RGB",
    en: "RGB",
  },
  mat_gradient_hex_label: {
    zh: "HEX",
    en: "HEX",
  },
  mat_gradient_mean_delta_e_label: {
    zh: "平均 ΔE",
    en: "Mean ΔE",
  },
  mat_gradient_max_delta_e_label: {
    zh: "最大 ΔE",
    en: "Max ΔE",
  },
  mat_gradient_rmse_linear_label: {
    zh: "线性 RMSE",
    en: "Linear RMSE",
  },
  mat_gradient_channel_rmse_label: {
    zh: "通道 RMSE",
    en: "Channel RMSE",
  },
  mat_gradient_channel_rmse_value: {
    zh: "红 {r} / 绿 {g} / 蓝 {b}",
    en: "R {r} / G {g} / B {b}",
  },
  mat_gradient_orientation_title: {
    zh: "方向检测",
    en: "Orientation Detection",
  },
  mat_gradient_orientation_reliable: {
    zh: "可靠",
    en: "Reliable",
  },
  mat_gradient_orientation_unreliable: {
    zh: "置信度低",
    en: "Low Confidence",
  },
  mat_gradient_white_orientation_label: {
    zh: "白底方向",
    en: "White Orientation",
  },
  mat_gradient_black_orientation_label: {
    zh: "黑底方向",
    en: "Black Orientation",
  },
  mat_gradient_delta_e_gap_label: {
    zh: "ΔE 差距",
    en: "ΔE Gap",
  },
  mat_gradient_anchor_section_title: {
    zh: "色块位置（决定读取顺序）",
    en: "Pure Block Position (Drives Sampling Order)",
  },
  mat_gradient_anchor_section_desc: {
    zh: "请告诉系统照片上「露出底板的纯色块」位于哪个角。先按 1.左上 → 2.右上 → 3.右下 → 4.左下 顺序点选 4 个角，再选这里。若不确定可保留「自动检测」。",
    en: "Tell the system which screen corner holds the pure substrate block (the only patch where the bare board shows through). Pick the four corners in 1.top-left → 2.top-right → 3.bottom-right → 4.bottom-left order first, then choose here. Leave on \"Auto detect\" if unsure.",
  },
  mat_gradient_white_anchor_label: {
    zh: "纯白色块位置",
    en: "Pure White Block Position",
  },
  mat_gradient_black_anchor_label: {
    zh: "纯黑色块位置",
    en: "Pure Black Block Position",
  },
  mat_gradient_anchor_option_auto: {
    zh: "自动检测（推荐）",
    en: "Auto detect (recommended)",
  },
  mat_gradient_anchor_option_tl: {
    zh: "左上角",
    en: "Top-left",
  },
  mat_gradient_anchor_option_tr: {
    zh: "右上角",
    en: "Top-right",
  },
  mat_gradient_anchor_option_br: {
    zh: "右下角",
    en: "Bottom-right",
  },
  mat_gradient_anchor_option_bl: {
    zh: "左下角",
    en: "Bottom-left",
  },
  mat_gradient_corner_pick_order_hint: {
    zh: "请按 1.左上 → 2.右上 → 3.右下 → 4.左下 顺序点选 4 个角。",
    en: "Click the four corners in 1.top-left → 2.top-right → 3.bottom-right → 4.bottom-left order.",
  },
  mat_gradient_image_source_section_title: {
    zh: "图像来源",
    en: "Image Source",
  },
  mat_gradient_image_source_section_desc: {
    zh: "请确认上传的两张梯度卡图是「相机/扫描仪原图」还是「ColorChecker 校正/还原图」。色卡校正可减少相机色差，通常有利于拟合；请保持白底图、黑底图使用同一相机、曝光、白平衡和校色设置，并关注采样区域是否出现高光/阴影裁切。若出现「零厚度白底采样接近纯白」等警告，请按该警告处理。",
    en: "Tell the system whether the two uploaded gradient-card images are direct camera/scanner captures (raw) or ColorChecker-corrected/restored renders. ColorChecker correction can reduce camera color bias and can help the fit; keep the white/black images on the same camera, exposure, white balance, and calibration settings, and watch for highlight/shadow clipping in the sampled area. If warnings such as \"zero-thickness white near pure white\" appear, treat those warnings as the deciding signal.",
  },
  mat_gradient_image_source_option_raw: {
    zh: "原图（相机/扫描仪直出，推荐）",
    en: "Raw photo (camera/scanner direct, recommended)",
  },
  mat_gradient_image_source_option_restored: {
    zh: "ColorChecker 校正/还原图",
    en: "ColorChecker-corrected / restored image",
  },
  mat_gradient_image_source_restored_warning: {
    zh: "已选择「ColorChecker 校正/还原图」。该来源会与原图记录分开合并；请确认两张图使用同一校色设置，且 Stage A 采样区域没有裁切。若出现「零厚度白底采样接近纯白」等警告，请重新拍摄或调整曝光/校色设置后再提取。",
    en: "ColorChecker-corrected/restored source selected. This source is kept separate from raw captures during merging; make sure both images use the same calibration settings and the sampled Stage A area is not clipped. If warnings such as \"zero-thickness white near pure white\" appear, re-capture or adjust exposure/calibration before extracting again.",
  },
  mat_gradient_image_source_mismatch_error: {
    zh: "本次上传的图像来源与该耗材已有的验证记录不一致，无法合并。请使用相同来源（同为原图或同为校正/还原图）重新拍摄，或在保存时改用「覆盖」模式以丢弃原有验证记录。",
    en: "The image source of this capture does not match the existing verification runs for this material, so they cannot be merged. Re-capture using the same source (raw or corrected/restored) or use override mode when saving to discard previous verification runs.",
  },
  // ----- Aggregation diagnostics ("merge diagnostics" section) -----
  // Surfaced in the saved-material card after a successful save so the
  // user can see which historical runs participated in the joint refit
  // and why others were dropped.
  mat_gradient_aggregation_section_title: {
    zh: "合并诊断",
    en: "Merge Diagnostics",
  },
  mat_gradient_aggregation_method_label: {
    zh: "聚合方式",
    en: "Aggregation Method",
  },
  mat_gradient_aggregation_method_refit_combined_samples: {
    zh: "合并样本重拟合",
    en: "Refit on combined samples",
  },
  mat_gradient_aggregation_method_mean: {
    zh: "参数均值兜底",
    en: "Parameter-mean fallback",
  },
  mat_gradient_aggregation_selection_strategy_label: {
    zh: "选择策略",
    en: "Selection Strategy",
  },
  mat_gradient_aggregation_strategy_bias_filter_v1: {
    zh: "偏置硬过滤",
    en: "Bias filter",
  },
  "mat_gradient_aggregation_strategy_bias_filter_v1+cross_val": {
    zh: "偏置过滤 + 交叉验证",
    en: "Bias filter + cross-val",
  },
  mat_gradient_aggregation_runs_used: {
    zh: "{{used}} / {{total}} 次校准参与本次重拟合",
    en: "{{used}} of {{total}} verification runs participated in this refit",
  },
  mat_gradient_aggregation_run_label: {
    zh: "第 {{index}} 次校准",
    en: "Run #{{index}}",
  },
  mat_gradient_aggregation_run_fresh_badge: {
    zh: "本次新增",
    en: "Fresh",
  },
  mat_gradient_aggregation_run_excluded_badge: {
    zh: "已排除",
    en: "Excluded",
  },
  mat_gradient_aggregation_run_included_badge: {
    zh: "已采纳",
    en: "Included",
  },
  mat_gradient_aggregation_no_excluded: {
    zh: "本次合并未排除任何历史校准。",
    en: "No historical runs were excluded by the bias filter for this merge.",
  },
  // Bias-flag labels (stable codes from backend → localised strings)
  mat_gradient_bias_flag_c0_white_avg_gt_0_95: {
    zh: "白底零厚度像素接近纯白（C0_white > 0.95，可能裁切/过亮归一化）",
    en: "Zero-thickness white near pure white (C0_white > 0.95, possible clipping or overbright normalization)",
  },
  mat_gradient_bias_flag_image_source_restored: {
    zh: "图像来源标记为「ColorChecker 校正/还原图」",
    en: "Image source tagged as ColorChecker-corrected/restored",
  },
  mat_gradient_bias_flag_white_substrate_flat: {
    zh: "白底信号过弱（朝向不可分辨）",
    en: "White substrate signal too flat",
  },
  mat_gradient_bias_flag_black_substrate_flat: {
    zh: "黑底信号过弱（朝向不可分辨）",
    en: "Black substrate signal too flat",
  },
  mat_gradient_bias_flag_orientation_unreliable: {
    zh: "朝向打分不可靠（提示性，不参与硬过滤）",
    en: "Orientation ranking unreliable (advisory, not used for hard filter)",
  },
  mat_gradient_bias_flag_c0_white_avg_lt_0_60: {
    zh: "白底零厚度像素过暗（C0_white < 0.60，曝光不足或角点选错）",
    en: "Zero-thickness white too dark (C0_white < 0.60, underexposed or wrong anchor)",
  },
  mat_gradient_bias_flag_mean_de_gt_3: {
    zh: "本次拟合平均 ΔE > 3（拟合本身已不可信，禁止其样本进入联合重拟）",
    en: "Run's own mean ΔE > 3 (fit already unreliable; samples blocked from joint refit)",
  },
  mat_gradient_bias_flag_c0_session_outlier: {
    zh: "白底读数与同期校准的其他材料中位数偏差过大（疑似白底取样位置错误或光照不一致，建议重拍）",
    en: "White-substrate reading deviates from the session median across other materials (likely wrong patch sample or inconsistent lighting; please re-shoot)",
  },
  mat_gradient_aggregation_excluded_reason_bias_filter: {
    zh: "偏置硬过滤",
    en: "Bias filter",
  },
  mat_gradient_aggregation_excluded_reason_cross_val: {
    zh: "交叉验证排序",
    en: "Cross-val ranking",
  },
  mat_gradient_aggregation_excluded_reason_c0_white_pairwise_mismatch: {
    zh: "白底亮度与新捕获相差过大（>1.5×，光照环境不一致）",
    en: "White-substrate brightness differs from fresh capture by more than 1.5x (inconsistent lighting)",
  },
  mat_gradient_aggregation_excluded_reason_c0_session_outlier: {
    zh: "白底跨材料一致性（与同 session 其他材料的中位数偏差超阈值）",
    en: "Cross-material session white_C0 outlier (deviates from same-session median beyond threshold)",
  },
  mat_gradient_white_signal_label: {
    zh: "白底信号",
    en: "White Signal",
  },
  mat_gradient_black_signal_label: {
    zh: "黑底信号",
    en: "Black Signal",
  },
  mat_gradient_signal_flat_badge: {
    zh: "信号过弱",
    en: "Low Signal",
  },
  mat_gradient_manual_override_badge: {
    zh: "手动指定",
    en: "Manual",
  },
  mat_gradient_signal_flat_hint: {
    zh: "此基底梯度极弱（采样格颜色几乎一致），自动方向检测可能不可靠。建议在上方手动选择「色块位置」对应的角。",
    en: "This substrate's gradient is very weak (sample cells are nearly identical). Auto orientation detection may be unreliable — pick the matching anchor in the \"Pure Block Position\" selector above.",
  },
  mat_gradient_saved_material_title: {
    zh: "底层参数文件（可选导出）",
    en: "Low-Level Parameter Files (Optional Export)",
  },
  mat_gradient_saved_material_desc: {
    zh: "提取结果已自动保存至软件本地，普通用户无需下载。这些底层文件仅供跨设备备份或高级调试使用。",
    en: "Extraction results are automatically saved locally; normal users do not need to download them. These low-level files are only for cross-device backup or advanced debugging.",
  },
  mat_gradient_download_material_btn: {
    zh: "导出基础耗材信息 (material.json)",
    en: "Export Basic Material Info (material.json)",
  },
  mat_gradient_library_title: {
    zh: "耗材库",
    en: "Material Library",
  },
  mat_gradient_library_desc: {
    zh: "浏览已保存的 Stage A 耗材档案，并支持多选导出 ZIP 或批量导入 ZIP。",
    en: "Browse saved Stage A material archives, export selected ZIP bundles, or import ZIP bundles in bulk.",
  },
  mat_gradient_library_select_all_btn: {
    zh: "全选耗材",
    en: "Select All",
  },
  mat_gradient_library_clear_selection_btn: {
    zh: "清空选择",
    en: "Clear Selection",
  },
  mat_gradient_library_import_btn: {
    zh: "导入耗材 ZIP",
    en: "Import Material ZIP",
  },
  mat_gradient_library_export_btn: {
    zh: "导出所选耗材",
    en: "Export Selected",
  },
  mat_gradient_library_import_hint: {
    zh: "可一次选择多个 ZIP；导出文件也可再次批量导入。",
    en: "You can choose multiple ZIP files at once, and exported bundles can be imported again in bulk.",
  },
  lut_library_title: {
    zh: "LUT库",
    en: "LUT Library",
  },
  lut_library_total_label: {
    zh: "本地 LUT",
    en: "Local LUTs",
  },
  lut_library_cloud_label: {
    zh: "云端安装",
    en: "Cloud Installed",
  },
  lut_library_custom_label: {
    zh: "自定义",
    en: "Custom",
  },
  lut_library_mode_count_label: {
    zh: "颜色模式",
    en: "Color Modes",
  },
  lut_library_refresh_btn: {
    zh: "刷新本地库",
    en: "Refresh Library",
  },
  lut_library_upload_btn: {
    zh: "导入 LUT 文件",
    en: "Import LUT File",
  },
  lut_library_search_placeholder: {
    zh: "搜索名称、品牌、类型、颜色模式…",
    en: "Search names, brands, types, color modes…",
  },
  lut_library_loading: {
    zh: "正在加载本地 LUT...",
    en: "Loading local LUTs...",
  },
  lut_library_empty: {
    zh: "没有匹配的本地 LUT。",
    en: "No matching local LUTs.",
  },
  lut_library_load_failed: {
    zh: "读取本地 LUT 库失败",
    en: "Failed to load local LUT library",
  },
  lut_library_upload_success: {
    zh: "LUT 已导入本地库。",
    en: "LUT imported into the local library.",
  },
  lut_library_upload_failed: {
    zh: "LUT 导入失败",
    en: "LUT import failed",
  },
  lut_library_group_count: {
    zh: "{count} 个 LUT",
    en: "{count} LUTs",
  },
  lut_library_origin_cloud: {
    zh: "云端",
    en: "Cloud",
  },
  lut_library_origin_custom: {
    zh: "自定义",
    en: "Custom",
  },
  lut_library_origin_preset: {
    zh: "预设",
    en: "Preset",
  },
  lut_library_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  lut_library_source_kind_label: {
    zh: "来源类型",
    en: "Source Kind",
  },
  lut_library_path_label: {
    zh: "路径",
    en: "Path",
  },
  lut_library_details_btn: {
    zh: "查看详情",
    en: "View Details",
  },
  lut_library_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  lut_sync_title: {
    zh: "云端 LUT 库",
    en: "Cloud LUT Library",
  },
  lut_sync_catalog_count_label: {
    zh: "云端条目",
    en: "Cloud Items",
  },
  lut_sync_catalog_loaded_inline: {
    zh: "已加载 {loaded} / {total} 个云端 LUT",
    en: "Loaded {loaded} / {total} cloud LUTs",
  },
  lut_sync_installed_count_label: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_config_label: {
    zh: "远端配置",
    en: "Remote",
  },
  lut_sync_configured: {
    zh: "已配置",
    en: "Configured",
  },
  lut_sync_not_configured: {
    zh: "未配置",
    en: "Not configured",
  },
  lut_sync_refresh_btn: {
    zh: "刷新云端目录",
    en: "Refresh Catalog",
  },
  lut_sync_load_more_btn: {
    zh: "加载更多",
    en: "Load More",
  },
  lut_sync_status_failed: {
    zh: "读取云端 LUT 库失败",
    en: "Failed to load cloud LUT library",
  },
  lut_sync_catalog_not_configured: {
    zh: "尚未配置云端 LUT 库。本地 LUT 仍可离线使用；配置 LUMINA_LUT_REGISTRY_URL 后会显示云端 LUT。",
    en: "Cloud LUT registry is not configured. Local LUTs remain available offline; configure LUMINA_LUT_REGISTRY_URL to show cloud LUTs.",
  },
  lut_sync_catalog_refresh_success: {
    zh: "云端 LUT 目录已刷新。",
    en: "Cloud LUT catalog refreshed.",
  },
  lut_sync_search_placeholder: {
    zh: "搜索名称、厂商、路径或 ID",
    en: "Search name, maker, path, or ID",
  },
  lut_sync_install_btn: {
    zh: "下载到本地",
    en: "Download",
  },
  lut_sync_installed_btn: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_local_available_btn: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_install_success: {
    zh: "LUT 已下载并安装到本地。",
    en: "LUT downloaded and installed locally.",
  },
  lut_sync_install_failed: {
    zh: "LUT 下载失败",
    en: "LUT download failed",
  },
  lut_sync_catalog_empty: {
    zh: "没有匹配的云端 LUT。",
    en: "No matching cloud LUTs.",
  },
  lut_sync_loading: {
    zh: "正在加载云端 LUT...",
    en: "Loading cloud LUTs...",
  },
  lut_sync_package_size_label: {
    zh: "体积",
    en: "Size",
  },
  lut_sync_content_fingerprint_label: {
    zh: "内容指纹",
    en: "Fingerprint",
  },
  lut_sync_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  lut_sync_catalog_state_label: {
    zh: "状态",
    en: "Status",
  },
  lut_sync_catalog_state_not_installed: {
    zh: "未下载",
    en: "Not Downloaded",
  },
  lut_sync_catalog_state_installed: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_catalog_state_local_available: {
    zh: "已安装",
    en: "Installed",
  },
  lut_sync_local_path_label: {
    zh: "本地路径",
    en: "Local Path",
  },
  lut_sync_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  mat_sync_title: {
    zh: "云端耗材库",
    en: "Cloud Material Library",
  },
  mat_sync_catalog_count_label: {
    zh: "云端条目",
    en: "Cloud Items",
  },
  mat_sync_index_state_label: {
    zh: "索引状态",
    en: "Index",
  },
  mat_sync_installed_count_label: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_update_count_label: {
    zh: "可更新",
    en: "Updates",
  },
  mat_sync_last_sync_label: {
    zh: "上次同步",
    en: "Last Sync",
  },
  mat_sync_last_sync_inline: {
    zh: "本地索引更新时间：{time}",
    en: "Local index updated: {time}",
  },
  mat_sync_state_missing: {
    zh: "未建立",
    en: "Missing",
  },
  mat_sync_state_ready: {
    zh: "正常",
    en: "Ready",
  },
  mat_sync_state_invalid: {
    zh: "异常",
    en: "Invalid",
  },
  mat_sync_state_unknown: {
    zh: "未知",
    en: "Unknown",
  },
  mat_sync_refresh_btn: {
    zh: "刷新云端目录",
    en: "Refresh Catalog",
  },
  mat_sync_status_failed: {
    zh: "读取云端耗材库失败",
    en: "Failed to load cloud material library",
  },
  mat_sync_catalog_not_configured: {
    zh: "尚未配置云端耗材库。本地耗材库仍可离线使用；配置 LUMINA_MATERIAL_REGISTRY_URL 后会显示云端耗材。",
    en: "Cloud material registry is not configured. The local material library remains available offline; configure LUMINA_MATERIAL_REGISTRY_URL to show cloud materials.",
  },
  mat_sync_catalog_refresh_success: {
    zh: "云端耗材目录已刷新。",
    en: "Cloud material catalog refreshed.",
  },
  mat_sync_refresh_success: {
    zh: "云端耗材同步完成。",
    en: "Cloud material sync completed.",
  },
  mat_sync_refresh_failed: {
    zh: "云端耗材同步失败",
    en: "Cloud material sync failed",
  },
  mat_sync_official_badge: {
    zh: "官方",
    en: "Official",
  },
  mat_sync_search_placeholder: {
    zh: "搜索品牌、名称、目录或 ID",
    en: "Search brand, name, directory, or ID",
  },
  mat_sync_filter_group_label: {
    zh: "云端耗材筛选",
    en: "Cloud material filters",
  },
  mat_sync_filter_all: {
    zh: "全部",
    en: "All",
  },
  mat_sync_filter_official: {
    zh: "官方",
    en: "Official",
  },
  mat_sync_filter_not_installed: {
    zh: "未安装",
    en: "Not Installed",
  },
  mat_sync_filter_updates: {
    zh: "可更新",
    en: "Updates",
  },
  mat_sync_filter_installed: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_install_btn: {
    zh: "下载到本地",
    en: "Download",
  },
  mat_sync_update_btn: {
    zh: "更新到 {revisionId}",
    en: "Update to {revisionId}",
  },
  mat_sync_installed_btn: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_local_available_btn: {
    zh: "本地已有版本",
    en: "Local revision available",
  },
  mat_sync_official_password_required_btn: {
    zh: "需要官方密码",
    en: "Official password required",
  },
  mat_sync_install_success: {
    zh: "耗材已下载并安装到本地。",
    en: "Material downloaded and installed locally.",
  },
  mat_sync_install_failed: {
    zh: "耗材下载失败",
    en: "Material download failed",
  },
  mat_sync_catalog_state_label: {
    zh: "状态",
    en: "Status",
  },
  mat_sync_catalog_state_not_installed: {
    zh: "未安装",
    en: "Not installed",
  },
  mat_sync_catalog_state_installed: {
    zh: "已安装",
    en: "Installed",
  },
  mat_sync_catalog_state_update_available: {
    zh: "有新版本",
    en: "Update available",
  },
  mat_sync_catalog_state_local_available: {
    zh: "本地已有版本",
    en: "Local revision available",
  },
  mat_sync_catalog_state_local_missing: {
    zh: "本地文件缺失",
    en: "Local files missing",
  },
  mat_sync_history_hint: { zh: "按本地安装时间查看版本，选择要恢复的版本。", en: "Versions are listed by local installation date. Select a version to restore." },
  mat_sync_history_unknown_date: { zh: "日期未知", en: "Date unknown" },
  mat_sync_history_current: { zh: "当前使用", en: "Current" },
  mat_sync_history_previous: { zh: "历史版本", en: "Previous version" },
  mat_sync_history_empty: { zh: "暂无可恢复的本地历史版本", en: "No local history available to restore" },
  mat_sync_history_close: { zh: "关闭", en: "Close" },
  mat_sync_history_restore: { zh: "恢复所选版本", en: "Restore selected version" },
  mat_sync_local_section_title: {
    zh: "本地历史版本",
    en: "Local Version History",
  },
  mat_sync_local_section_hint: {
    zh: "更新耗材后会保留旧版本；如果新版本效果不理想，可以一键回滚。",
    en: "Older revisions are kept after an update, so you can roll back if the new one does not work well.",
  },
  mat_sync_local_section_expand: {
    zh: "展开",
    en: "Show",
  },
  mat_sync_local_section_collapse: {
    zh: "收起",
    en: "Hide",
  },
  mat_sync_local_current_revision: {
    zh: "当前版本 {revision} · 更新于 {time}",
    en: "Current {revision} · updated {time}",
  },
  mat_sync_channel_label: {
    zh: "发布频道",
    en: "Channel",
  },
  mat_sync_channel_official: {
    zh: "官方频道",
    en: "Official",
  },
  mat_sync_channel_community: {
    zh: "社区频道",
    en: "Community",
  },
  mat_sync_channel_team: {
    zh: "团队频道",
    en: "Team",
  },
  mat_sync_fit_error_label: {
    zh: "拟合误差",
    en: "Fit Error",
  },
  mat_sync_fit_error_hint: {
    zh: "平均色差 ΔE，数值越低越准确：不超过 {excellent} 为优秀，不超过 {high} 为良好，超过 {high} 为偏高。",
    en: "Mean color difference (ΔE); lower is more accurate: up to {excellent} is excellent, up to {high} is good, above {high} is high.",
  },
  mat_sync_fit_error_value: {
    zh: "ΔE {value}",
    en: "ΔE {value}",
  },
  mat_sync_fit_error_grade_excellent: {
    zh: "优秀",
    en: "Excellent",
  },
  mat_sync_fit_error_grade_good: {
    zh: "良好",
    en: "Good",
  },
  mat_sync_fit_error_grade_high: {
    zh: "偏高",
    en: "High",
  },
  mat_sync_fit_error_missing: {
    zh: "未提供",
    en: "Not provided",
  },
  mat_sync_fit_error_verifications: {
    zh: "{count} 次验证",
    en: "{count} verifications",
  },
  mat_sync_page_range_inline: {
    zh: "第 {from}–{to} 条，共 {total} 条",
    en: "{from}–{to} of {total}",
  },
  mat_sync_full_catalog_failed: {
    zh: "按安装状态筛选需要读取完整云端目录，但这次读取失败了。",
    en: "Filtering by install status needs the full cloud catalog, but it could not be loaded.",
  },
  mat_sync_full_catalog_retry_btn: {
    zh: "重试",
    en: "Retry",
  },
  mat_sync_dismiss_btn: {
    zh: "关闭提示",
    en: "Dismiss",
  },
  mat_sync_catalog_empty: {
    zh: "没有匹配的云端耗材。",
    en: "No matching cloud materials.",
  },
  mat_sync_admin_section_title: {
    zh: "贡献者 / 管理员入口",
    en: "Contributor / Admin",
  },
  mat_sync_upload_title: {
    zh: "测试服务器上传与审批",
    en: "Test Server Upload & Approval",
  },
  mat_sync_upload_empty: {
    zh: "上传耗材包后，可用官方密码批准为 official 耗材。",
    en: "After uploading a material package, approve it as official with the official password.",
  },
  mat_sync_upload_btn: {
    zh: "上传耗材包",
    en: "Upload Package",
  },
  mat_sync_upload_success: {
    zh: "耗材包已上传到待审核队列。",
    en: "Material package uploaded to the review queue.",
  },
  mat_sync_upload_failed: {
    zh: "耗材包上传失败",
    en: "Material package upload failed",
  },
  mat_sync_approve_official_btn: {
    zh: "批准为官方耗材",
    en: "Approve as Official",
  },
  mat_sync_approve_success: {
    zh: "耗材包已批准为官方耗材。",
    en: "Material package approved as official.",
  },
  mat_sync_approve_failed: {
    zh: "官方耗材审批失败",
    en: "Official approval failed",
  },
  mat_sync_approve_existing_title: {
    zh: "审批已有云端耗材",
    en: "Approve Existing Cloud Materials",
  },
  mat_sync_approve_existing_empty: {
    zh: "在上方云端耗材卡片勾选非 official 耗材后，可在这里批准为官方耗材。",
    en: "Select non-official cloud material cards above, then approve them as official here.",
  },
  mat_sync_approve_selected_summary: {
    zh: "已选择 {count} 个云端耗材，审批后会进入 official 频道。",
    en: "{count} cloud materials selected. Approval will publish them to the official channel.",
  },
  mat_sync_approve_selected_btn: {
    zh: "批准选中云端耗材为官方",
    en: "Approve Selected Cloud Materials",
  },
  mat_sync_approve_selected_success: {
    zh: "已将 {count} 个云端耗材批准为官方耗材。",
    en: "Approved {count} cloud materials as official.",
  },
  mat_sync_approve_package_path_invalid: {
    zh: "无法解析所选云端耗材的包路径。",
    en: "Could not resolve the selected cloud material package path.",
  },
  mat_sync_official_password_placeholder: {
    zh: "官方审批密码",
    en: "Official approval password",
  },
  mat_sync_package_path_label: {
    zh: "包路径",
    en: "Package Path",
  },
  mat_sync_package_size_label: {
    zh: "体积",
    en: "Size",
  },
  mat_sync_material_id_label: {
    zh: "耗材 ID",
    en: "Material ID",
  },
  mat_sync_revision_label: {
    zh: "版本",
    en: "Revision",
  },
  mat_sync_content_fingerprint_label: {
    zh: "内容指纹",
    en: "Fingerprint",
  },
  mat_sync_select_catalog_item_label: {
    zh: "选择云端耗材「{materialName}」",
    en: 'Select cloud material "{materialName}"',
  },
  mat_sync_rollback_btn: {
    zh: "回滚到 {revisionId}",
    en: "Rollback to {revisionId}",
  },
  mat_sync_rollback_success: {
    zh: "耗材版本已回滚。",
    en: "Material revision rolled back.",
  },
  mat_sync_rollback_failed: {
    zh: "耗材版本回滚失败",
    en: "Material rollback failed",
  },
  mat_gradient_library_selection_summary: {
    zh: "已选择 {selected} / {total} 个耗材",
    en: "Selected {selected} / {total} materials",
  },
  mat_gradient_library_select_item_label: {
    zh: "选择耗材「{materialName}」",
    en: 'Select material "{materialName}"',
  },
  mat_gradient_library_refresh_btn: {
    zh: "刷新耗材库",
    en: "Refresh Library",
  },
  mat_gradient_library_loading: {
    zh: "正在加载耗材库...",
    en: "Loading material library...",
  },
  mat_gradient_library_load_failed: {
    zh: "加载耗材库失败",
    en: "Failed to load material library",
  },
  mat_gradient_library_empty: {
    zh: "还没有已保存的耗材档案。先在「梯度卡提取」里保存一个耗材。",
    en: "No saved material archives yet. Save one from Gradient Card Extract first.",
  },
  mat_gradient_library_updated_at_label: {
    zh: "最近更新",
    en: "Last Updated",
  },
  mat_gradient_library_created_at_label: {
    zh: "创建时间",
    en: "Created",
  },
  mat_gradient_library_verification_count_label: {
    zh: "验证次数",
    en: "Verification Runs",
  },
  mat_gradient_library_usage_count_label: {
    zh: "使用次数",
    en: "Usage Count",
  },
  mat_gradient_library_usage_last_used: {
    zh: "最近使用：{when}",
    en: "Last used: {when}",
  },
  mat_gradient_library_directory_label: {
    zh: "目录名",
    en: "Directory",
  },
  mat_gradient_library_brand_label: {
    zh: "品牌",
    en: "Brand",
  },
  mat_gradient_library_brand_unassigned: {
    zh: "未分组",
    en: "Unassigned",
  },
  basic_material_picker_brand_unassigned: {
    zh: "未分组",
    en: "Unassigned",
  },
  mat_gradient_library_fit_error_label: {
    zh: "拟合误差",
    en: "Fit Error",
  },
  mat_gradient_library_layer_height_label: {
    zh: "采集层高",
    en: "Calibration Layer Height",
  },
  mat_gradient_library_details: {
    zh: "详细信息",
    en: "Details",
  },
  mat_gradient_library_type_missing: { zh: "类型未填写", en: "Type not specified" },
  mat_gradient_library_calibration: { zh: "标定信息", en: "Calibration" },
  mat_gradient_library_usage: { zh: "使用记录", en: "Usage" },
  mat_gradient_library_files: { zh: "文件信息", en: "File information" },
  mat_gradient_library_browse_summary: { zh: "耗材库 · {count} 个耗材", en: "Material library · {count} materials" },
  mat_gradient_library_selection_start: { zh: "选择耗材", en: "Select materials" },
  mat_gradient_library_collapse_all: { zh: "全部收起", en: "Collapse all" },
  mat_gradient_library_expand_all: { zh: "全部展开", en: "Expand all" },
  library_pin_hint: { zh: "每次进入仓库时自动展开", en: "Expand automatically whenever you open the library" },
  lut_library_inventory_summary: { zh: "{count}个 LUT · {brands}个品牌", en: "{count} LUTs · {brands} brands" },
  lut_library_analyze_btn: { zh: "查看完整 LUT 分析", en: "Open full LUT analysis" },
  mat_gradient_library_search: { zh: "搜索耗材名称、品牌、类型…", en: "Search materials, brands, types…" },
  mat_gradient_library_inventory_summary: { zh: "{count}种耗材 · {brands}个品牌", en: "{count} materials · {brands} brands" },
  mat_gradient_library_search_empty: { zh: "没有找到匹配的耗材，试试其他关键词。", en: "No matching materials. Try another search." },
  mat_gradient_library_reorder_hint: { zh: "拖拽调整品牌顺序，也可用上下方向键调整", en: "Drag to reorder brands, or use the up and down arrow keys" },
  mat_gradient_library_brand_count: { zh: "{count}种", en: "{count} types" },
  mat_gradient_library_pin_brand: { zh: "固定展开 {brand}", en: "Pin {brand} open" },
  mat_gradient_library_unpin_brand: { zh: "取消固定 {brand}", en: "Unpin {brand}" },
  mat_gradient_library_pin_hint: { zh: "每次进入耗材库时自动展开", en: "Expand automatically whenever you open the library" },
  mat_gradient_library_unpin_hint: { zh: "取消默认展开", en: "Stop expanding by default" },
  mat_gradient_library_selection_done: { zh: "完成选择", en: "Done selecting" },
  mat_gradient_library_edit_btn: {
    zh: "编辑信息",
    en: "Edit Details",
  },
  mat_gradient_library_edit_title: {
    zh: "编辑耗材信息",
    en: "Edit Material Details",
  },
  mat_gradient_library_edit_desc: {
    zh: "你正在编辑目录 {directoryName} 的显示名称、品牌与颜色。",
    en: "You are editing the display name, brand and color for directory {directoryName}.",
  },
  mat_gradient_library_edit_color_label: {
    zh: "显示颜色",
    en: "Display Color",
  },
  mat_gradient_library_edit_color_hex_placeholder: {
    zh: "#RRGGBB 色号",
    en: "#RRGGBB hex",
  },
  mat_gradient_library_edit_color_invalid_hex: {
    zh: "色号必须是 #RGB 或 #RRGGBB 格式",
    en: "Color must be #RGB or #RRGGBB format",
  },
  mat_gradient_library_edit_color_hint: {
    zh: "可使用颜色选择器或直接输入色号；修改后会替换测量得到的显示颜色。",
    en: "Use the picker or enter a hex code; this overrides the measured display color.",
  },
  mat_gradient_library_edit_cancel_btn: {
    zh: "取消",
    en: "Cancel",
  },
  mat_gradient_library_edit_save_btn: {
    zh: "保存修改",
    en: "Save Changes",
  },
  mat_gradient_library_edit_success: {
    zh: "耗材信息已更新。",
    en: "Material details updated.",
  },
  mat_gradient_library_edit_failed: {
    zh: "更新耗材信息失败",
    en: "Failed to update material details",
  },
  mat_gradient_library_reverify_btn: {
    zh: "再次验证",
    en: "Re-Verify",
  },
  mat_gradient_library_cloud_upload_btn: {
    zh: "上传到云端",
    en: "Upload to Cloud",
  },
  mat_gradient_library_cloud_upload_password_prompt: {
    zh: "请输入官方审批密码，用于上传这个耗材到云端待审核队列。",
    en: "Enter the official approval password to upload this material to the cloud review queue.",
  },
  mat_gradient_library_cloud_upload_success: {
    zh: "耗材已提交到云端待审核队列。",
    en: "Material uploaded to the cloud review queue.",
  },
  mat_gradient_library_cloud_upload_failed: {
    zh: "上传到云端失败",
    en: "Failed to upload material to cloud",
  },
  mat_gradient_library_delete_btn: {
    zh: "删除耗材",
    en: "Delete Material",
  },
  mat_gradient_library_duplicate_badge: {
    zh: "同名 {count} 份",
    en: "{count} copies",
  },
  mat_gradient_library_card_meta: {
    zh: "目录：{directoryName} · 创建：{createdAt} · 最近更新：{updatedAt}",
    en: "Directory: {directoryName} · Created: {createdAt} · Last updated: {updatedAt}",
  },
  mat_gradient_library_delete_confirm: {
    zh: "确认删除这份耗材「{materialName}」？\n目录：{directoryName}\n最近更新：{updatedAt}\n此操作只删除当前服务器上的这份本地耗材档案，且不可撤销。",
    en: 'Delete this material copy "{materialName}"?\nDirectory: {directoryName}\nLast updated: {updatedAt}\nThis only deletes this local material archive on the current server and cannot be undone.',
  },
  mat_gradient_library_delete_success: {
    zh: "耗材已删除。",
    en: "Material deleted.",
  },
  mat_gradient_library_delete_failed: {
    zh: "删除耗材失败",
    en: "Failed to delete material",
  },
  mat_gradient_library_export_requires_selection: {
    zh: "请先至少选择一个耗材再导出。",
    en: "Select at least one material before exporting.",
  },
  mat_gradient_library_export_success: {
    zh: "已导出所选耗材。",
    en: "Selected materials exported.",
  },
  mat_gradient_library_export_failed: {
    zh: "导出耗材失败",
    en: "Failed to export materials",
  },
  mat_gradient_library_import_success: {
    zh: "耗材导入完成。",
    en: "Materials imported.",
  },
  mat_gradient_library_import_failed: {
    zh: "导入耗材失败",
    en: "Failed to import materials",
  },
  mat_gradient_library_show_history_btn: {
    zh: "展开验证历史",
    en: "Show Verification History",
  },
  mat_gradient_library_hide_history_btn: {
    zh: "收起验证历史",
    en: "Hide Verification History",
  },
  mat_gradient_library_history_title: {
    zh: "验证历史",
    en: "Verification History",
  },
  mat_gradient_library_history_close_btn: {
    zh: "关闭",
    en: "Close",
  },
  mat_gradient_library_history_empty: {
    zh: "当前还没有可展示的验证历史摘要。",
    en: "No verification history summary is available yet.",
  },
  mat_gradient_library_history_run_label: {
    zh: "第 {index} 次验证",
    en: "Run {index}",
  },
  mat_gradient_library_history_time_label: {
    zh: "验证时间",
    en: "Verified At",
  },
  mat_gradient_library_history_color_label: {
    zh: "估算颜色",
    en: "Estimated Color",
  },
  mat_gradient_library_history_rmse_label: {
    zh: "线性 RMSE",
    en: "Linear RMSE",
  },
  mat_gradient_library_history_e_label: {
    zh: "E 参数",
    en: "E Parameters",
  },
  mat_gradient_library_history_k_label: {
    zh: "k 参数",
    en: "k Parameters",
  },
  mat_gradient_library_history_white_c0_label: {
    zh: "白底 C0",
    en: "White C0",
  },
  mat_gradient_library_history_black_c0_label: {
    zh: "黑底 C0",
    en: "Black C0",
  },
  mat_gradient_library_history_orientation_label: {
    zh: "识别方向",
    en: "Detected Orientation",
  },
  mat_gradient_library_history_orientation_value: {
    zh: "白底 {white} / 黑底 {black}",
    en: "White {white} / Black {black}",
  },
  mat_gradient_verification_mode_title: {
    zh: "当前正在进行耗材复验",
    en: "Material Re-Verification Active",
  },
  mat_gradient_verification_mode_desc: {
    zh: "目标耗材：{materialName}。当前已累计 {count} 次验证；本次保存后会继续聚合参数。",
    en: "Target material: {materialName}. There are already {count} verification runs; saving this run will further aggregate the parameters.",
  },
  mat_gradient_verification_name_label: {
    zh: "复验目标耗材",
    en: "Verification Target Material",
  },
  mat_gradient_verification_name_desc: {
    zh: "当前为已有耗材做复验。已累计 {count} 次验证，本次结果会并入同一档案。",
    en: "You are re-verifying an existing material. There are already {count} runs and this result will be merged into the same archive.",
  },
  mat_gradient_save_verification_btn: {
    zh: "保存验证结果",
    en: "Save Verification Result",
  },
  mat_gradient_save_merge_btn: {
    zh: "合并结果",
    en: "Merge Result",
  },
  mat_gradient_save_override_btn: {
    zh: "覆盖结果",
    en: "Override",
  },
  mat_gradient_material_saved_success: {
    zh: "耗材保存成功",
    en: "Material saved successfully",
  },
  mat_gradient_verification_saved_success: {
    zh: "耗材校验保存成功（已聚合 {count} 次校验结果）",
    en: "Verification saved successfully ({count} runs aggregated)",
  },
  mat_gradient_cancel_verification_btn: {
    zh: "取消复验",
    en: "Cancel Re-Verification",
  },
  ext_workflow_label: {
    zh: "工作流模式",
    en: "Workflow",
  },
  ext_single_stage_upload_title: {
    zh: "Single-Stage 数据集上传",
    en: "Single-Stage Dataset Upload",
  },
  ext_single_stage_upload_desc: {
    zh: "上传按 {substrate}/{color}/ 结构打包的 ZIP 数据集",
    en: "Upload a ZIP dataset organized as {substrate}/{color}/",
  },
  ext_single_stage_zip_label: {
    zh: "数据集 ZIP",
    en: "Dataset ZIP",
  },
  ext_single_stage_extract_btn: {
    zh: "提取 1_single_stage.json",
    en: "Extract 1_single_stage.json",
  },
  ext_single_stage_download_json: {
    zh: "下载 1_single_stage.json",
    en: "Download 1_single_stage.json",
  },
  ext_single_stage_fit_btn: {
    zh: "继续拟合 Stage A",
    en: "Fit Stage A",
  },
  ext_single_stage_download_stage_a: {
    zh: "导出预测模型参数 (stage_A_parameters.json)",
    en: "Export Predictive Model Parameters (stage_A_parameters.json)",
  },
  ext_single_stage_summary_title: {
    zh: "数据集摘要",
    en: "Dataset Summary",
  },
  ext_single_stage_fit_summary_title: {
    zh: "Stage A 拟合摘要",
    en: "Stage A Fit Summary",
  },
  ext_single_stage_warnings_title: {
    zh: "提取警告",
    en: "Extraction Warnings",
  },
  cal_workflow_legacy: {
    zh: "经典 LUT",
    en: "Classic LUT",
  },
  cal_workflow_single_stage: {
    zh: "梯度卡",
    en: "Gradient Card",
  },
  ext_workflow_legacy: {
    zh: "经典 LUT",
    en: "Classic LUT",
  },
  ext_workflow_single_stage: {
    zh: "梯度卡",
    en: "Gradient Card",
  },
  material_recipe_title: {
    zh: "耗材配方查询",
    en: "Material Recipe Query",
  },
  material_recipe_desc: {
    zh: "从耗材库中按观赏面朝基底的顺序选择多层耗材，使用 Beer-Lambert 正向模型直接预测叠层颜色，不依赖任何 LUT。层数不受 5 层限制。",
    en: "Pick materials from the library from the viewing face toward the substrate; the Beer-Lambert forward model predicts the stacked color directly, without any LUT. Layer count is not capped at 5.",
  },
  material_recipe_layers_heading: {
    zh: "配方层（观赏面 → 基底）",
    en: "Recipe layers (viewing face → substrate)",
  },
  material_recipe_layers_empty: {
    zh: "尚未添加任何层。点击下方耗材以追加到靠近基底的一侧。",
    en: "No layers yet. Click a material below to append it toward the substrate side.",
  },
  material_recipe_visible_face: {
    zh: "观赏面",
    en: "Viewing face",
  },
  material_recipe_substrate_side: {
    zh: "基底侧",
    en: "Substrate side",
  },
  material_recipe_layers_count: {
    zh: "已选 {count} 层",
    en: "{count} layer(s)",
  },
  material_recipe_layer_label: {
    zh: "第 {index} 层",
    en: "Layer {index}",
  },
  material_recipe_remove_layer: {
    zh: "移除该层",
    en: "Remove this layer",
  },
  material_recipe_clear: {
    zh: "清空",
    en: "Clear",
  },
  material_recipe_undo: {
    zh: "撤销最后一层",
    en: "Undo last layer",
  },
  material_recipe_reverse: {
    zh: "反序",
    en: "Reverse",
  },
  material_recipe_search_placeholder: {
    zh: "搜索耗材名 / 品牌 / 目录名",
    en: "Search material name / brand / directory",
  },
  material_recipe_search_empty: {
    zh: "未找到匹配的耗材",
    en: "No materials match the search",
  },
  material_recipe_search_clear: {
    zh: "清除搜索",
    en: "Clear search",
  },
  material_recipe_query: {
    zh: "计算混色",
    en: "Compute color",
  },
  material_recipe_query_loading: {
    zh: "计算中...",
    en: "Computing...",
  },
  material_recipe_substrate_label: {
    zh: "基底",
    en: "Substrate",
  },
  material_recipe_substrate_white: {
    zh: "白色基底",
    en: "White",
  },
  material_recipe_substrate_black: {
    zh: "黑色基底",
    en: "Black",
  },
  material_recipe_layer_height_label: {
    zh: "层厚 (mm)",
    en: "Layer height (mm)",
  },
  material_recipe_palette_heading: {
    zh: "耗材库",
    en: "Material library",
  },
  material_recipe_palette_empty: {
    zh: "耗材库为空，请先在「耗材库」或「梯度卡提取」页面建立耗材。",
    en: "Material library is empty. Use the Material Library or Gradient Extractor first to create materials.",
  },
  material_recipe_palette_loading: {
    zh: "加载耗材库...",
    en: "Loading material library...",
  },
  material_recipe_palette_load_failed: {
    zh: "加载耗材库失败",
    en: "Failed to load material library",
  },
  material_recipe_result_heading: {
    zh: "预测颜色",
    en: "Predicted color",
  },
  material_recipe_result_pending: {
    zh: "添加至少一层并点击「计算混色」即可查看预测结果。",
    en: "Add at least one layer then click \"Compute color\" to see the prediction.",
  },
  material_recipe_query_failed: {
    zh: "配方计算失败",
    en: "Recipe computation failed",
  },
  material_recipe_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  material_recipe_result_rgb_value: {
    zh: "RGB {value}",
    en: "RGB {value}",
  },
  material_recipe_result_meta: {
    zh: "{count} 层 · {height} mm · {substrate}",
    en: "{count} layer(s) · {height} mm · {substrate}",
  },
  material_recipe_add_to_collection: {
    zh: "添加到队列",
    en: "Add to queue",
  },
  material_recipe_already_in_collection: {
    zh: "已在队列中",
    en: "Already in queue",
  },
  material_recipe_collection_title: {
    zh: "配方队列",
    en: "Recipe queue",
  },
  material_recipe_collection_count: {
    zh: "{count} 个配方",
    en: "{count} recipe(s)",
  },
  material_recipe_collection_empty: {
    zh: "队列为空。计算配方颜色后可添加到队列。",
    en: "Queue is empty. Compute a recipe color then add it to the queue.",
  },
  material_recipe_collection_clear: {
    zh: "清空队列",
    en: "Clear queue",
  },
  material_recipe_remove_from_collection: {
    zh: "移除",
    en: "Remove",
  },
  material_recipe_swatch_block_size: {
    zh: "色块尺寸",
    en: "Block size",
  },
  material_recipe_swatch_gap: {
    zh: "间距",
    en: "Gap",
  },
  material_recipe_swatch_cols: {
    zh: "列数",
    en: "Columns",
  },
  material_recipe_swatch_structure: {
    zh: "结构模式",
    en: "Structure mode",
  },
  material_recipe_swatch_single_sided: {
    zh: "单面",
    en: "Single-sided",
  },
  material_recipe_swatch_double_sided: {
    zh: "双面",
    en: "Double-sided",
  },
  material_recipe_generate_swatch: {
    zh: "生成验证色块",
    en: "Generate swatch",
  },
  material_recipe_generating_swatch: {
    zh: "生成中...",
    en: "Generating...",
  },
  material_recipe_download_swatch: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },
  material_recipe_generate_swatch_failed: {
    zh: "色块生成失败",
    en: "Swatch generation failed",
  },
  material_recipe_download_swatch_failed: {
    zh: "色块下载失败",
    en: "Swatch download failed",
  },
  material_recipe_swatch_legend_alt: {
    zh: "色块图例",
    en: "Swatch legend",
  },
  // ==================== Beginner Tutorial ====================
  tutorial_welcome_title: {
    zh: "欢迎使用 Lumina Studio",
    en: "Welcome to Lumina Studio",
  },
  tutorial_welcome_body: {
    zh: "Lumina Studio 可以把一张普通图片转换成多色 3D 打印文件（3MF）：用几种耗材一层层叠着打印，叠出丰富的颜色。\n\n这份新手引导按第一次打印的顺序，带你一步步设置好打印机、耗材和参数，大约需要 3 分钟。",
    en: "Lumina Studio turns an ordinary picture into a multi-color 3D print file (3MF) by stacking a few materials layer by layer to mix rich colors.\n\nThis tour follows the order of a first print and walks you through setting up your printer, materials and settings. It takes about 3 minutes.",
  },
  tutorial_welcome_note: {
    zh: "每一步都可以直接在高亮区域里完成设置，也可以只看说明、点「下一步」继续。之后可以随时打开右上角的菜单（三条横线图标），选择“新手引导”重新查看。",
    en: "You can set things up right in the highlighted area at each step, or just read and click Next. You can reopen the tour any time from the menu in the top-right corner (the three-line icon).",
  },
  tutorial_welcome_start: {
    zh: "开始引导",
    en: "Start tour",
  },
  tutorial_welcome_skip: {
    zh: "跳过",
    en: "Skip",
  },
  tutorial_welcome_close: {
    zh: "关闭并跳过引导",
    en: "Close and skip the tour",
  },
  tutorial_launcher_label: {
    zh: "新手引导",
    en: "Beginner tour",
  },
  tutorial_launcher_tooltip: {
    zh: "重新查看新手引导",
    en: "Replay the beginner tour",
  },
  tutorial_progress_label: {
    zh: "新手引导",
    en: "Beginner tour",
  },
  tutorial_skip: {
    zh: "跳过引导",
    en: "Skip tour",
  },
  tutorial_back: {
    zh: "上一步",
    en: "Back",
  },
  tutorial_next: {
    zh: "下一步",
    en: "Next",
  },
  tutorial_done: {
    zh: "完成",
    en: "Done",
  },
  tutorial_flow_label: {
    zh: "操作步骤",
    en: "Steps",
  },
  tutorial_need_label: {
    zh: "需要准备：",
    en: "What you need: ",
  },
  tutorial_fit_label: {
    zh: "适合：",
    en: "Best for: ",
  },
  tutorial_step_upload_title: {
    zh: "导入图片或 SVG",
    en: "Import a picture or SVG",
  },
  tutorial_step_upload_body: {
    zh: "点击这里选择图片，或者直接把文件拖进来。支持 JPG、PNG 等常见图片，也可以导入 SVG 矢量图。\n上传后还可以裁剪、旋转图片。",
    en: "Click here to choose a picture, or drag a file in. Common formats such as JPG and PNG work, and you can also import SVG vector images.\nAfter uploading you can crop and rotate the picture.",
  },
  tutorial_step_source_title: {
    zh: "颜色设置：选「耗材档案」",
    en: "Color settings: choose Material Archive",
  },
  tutorial_step_source_body: {
    zh: "在这里选「耗材档案」：颜色和过渡通常比经典 LUT 更好，耗材也能自由搭配，不需要整套同品牌。经典 LUT 适合已经有现成 LUT 的用户。",
    en: "Choose Material Archive here: colors and transitions are usually better than with a Classic LUT, and you can mix materials freely instead of needing a full set from one brand. Classic LUT is for people who already have a LUT.",
  },
  tutorial_step_device_title: {
    zh: "先选好打印机和打印板",
    en: "First, choose your printer and build plate",
  },
  tutorial_step_device_body: {
    zh: "点「更改设备」选择切片软件（如 Orca Slicer、Bambu Studio）、打印机型号和喷嘴，再在下面选好打印板。\n只需设置一次，之后会自动记住；以后在「图像转换」页点「打印机热床」旁的「更改」也能回到这里。",
    en: "Click Change Device to choose your slicer (such as Orca Slicer or Bambu Studio), printer model and nozzle, then pick the build plate below.\nYou only need to do this once; it is remembered. Later, Change next to Printer Bed on the Converter page brings you back here.",
  },
  tutorial_step_materials_title: {
    zh: "选耗材：点开选择框",
    en: "Choose materials: open the picker",
  },
  tutorial_step_materials_body: {
    zh: "点「选择耗材…」打开耗材选择框。",
    en: "Click Choose materials… to open the material picker.",
  },
  tutorial_interactive_hint: {
    zh: "可以直接在高亮区域里设置。",
    en: "You can set this up right in the highlighted area.",
  },
  tutorial_interactive_auto_hint: {
    zh: "可以直接在高亮区域里操作，完成后会自动进入下一步。",
    en: "You can do this right in the highlighted area; the tour moves on when you are done.",
  },
  tutorial_step_picker_palette_title: {
    zh: "推荐配色，找到你手上的耗材",
    en: "Recommended colors: find your filaments",
  },
  tutorial_step_picker_palette_body: {
    zh: "按下面的推荐准备耗材，再在搜索框输入品牌或颜色（比如「拓竹 白」）找到你手上的那卷，也可以在左侧按品牌筛选。透明耗材不在这里选，后面在「透明镀层」里打开。",
    en: "Use the recommendations below, then type a brand or color in the search box (such as \"Bambu white\") to find the filament you have, or filter by brand on the left. Clear filament is not picked here; you turn it on later under Transparent Coating.",
  },
  tutorial_palette_eight_title: {
    zh: "8 色：效果最好",
    en: "8 colors: best results",
  },
  tutorial_palette_clear_title: {
    zh: "7+1：7 色 + 透明首层",
    en: "7+1: 7 colors + a clear first layer",
  },
  tutorial_palette_clear_note: {
    zh: "0.08 mm 的首层很薄，热床稍有不平就容易打不好。很多用户（尤其是拓竹打印机）会用一卷透明耗材打首层，把误差填平。",
    en: "A 0.08 mm first layer is very thin, so a slightly uneven bed easily ruins it. Many people (especially with Bambu Lab printers) print the first layer in clear filament to even out the bed.",
  },
  tutorial_palette_four_title: {
    zh: "4 色",
    en: "4 colors",
  },
  tutorial_palette_four_note: {
    zh: "需要把 0.08 mm 首层调好；调不好的话，可以加一台 AMS 扩到 8 个槽位，改用 7+1。",
    en: "Needs a well-tuned 0.08 mm first layer. If you cannot get it reliable, add another AMS for 8 slots and use 7+1.",
  },
  tutorial_color_white: {
    zh: "白",
    en: "White",
  },
  tutorial_color_yellow: {
    zh: "黄",
    en: "Yellow",
  },
  tutorial_color_red: {
    zh: "红",
    en: "Red",
  },
  tutorial_color_blue: {
    zh: "蓝",
    en: "Blue",
  },
  tutorial_color_black: {
    zh: "黑",
    en: "Black",
  },
  tutorial_color_magenta: {
    zh: "品红",
    en: "Magenta",
  },
  tutorial_color_cyan: {
    zh: "青",
    en: "Cyan",
  },
  tutorial_color_green: {
    zh: "绿",
    en: "Green",
  },
  tutorial_color_clear: {
    zh: "透明",
    en: "Clear",
  },
  tutorial_step_coating_title: {
    zh: "透明首层：打开「透明镀层」",
    en: "Clear first layer: turn on Transparent Coating",
  },
  tutorial_step_coating_body: {
    zh: "用 7+1 方案时，在这里勾选「启用透明镀层」。画面朝下打印时，这层透明耗材就是贴着热床的首层，可以填平热床的误差。在切片软件里确认它用的是透明耗材。\n不用透明首层的话，保持关闭即可。",
    en: "If you use 7+1, tick Enable Transparent Coating here. When the picture is printed face down, this clear layer is the first layer on the bed and evens out bed unevenness. In your slicer, check that it uses the clear filament.\nIf you do not use a clear first layer, leave it off.",
  },
  tutorial_size_small: {
    zh: "小尺寸",
    en: "Small",
  },
  tutorial_size_large: {
    zh: "大尺寸",
    en: "Large",
  },
  tutorial_size_caption: {
    zh: "同一张图，打得越大，细节越清楚",
    en: "The same picture: printed larger, the details are clearer",
  },
  tutorial_step_picker_cards_title: {
    zh: "勾选耗材并收藏",
    en: "Select materials and favorite them",
  },
  tutorial_step_picker_cards_body: {
    zh: "点卡片选中耗材，可以多选。选中的耗材会按顺序显示在列表上方，点 × 可以移除。同一款耗材有多份档案时，优先选 ΔE 低、验证次数多的那份。\n点卡片上的星标，把常用耗材收藏起来。",
    en: "Click a card to select a material; you can select several. Selected materials are listed in order above the list, and × removes one. When one material has several profiles, prefer the one with a lower ΔE and more verifications.\nClick the star on a card to favorite the materials you use often.",
  },
  tutorial_step_picker_favorites_title: {
    zh: "下次在「收藏」里找",
    en: "Find them under Favorites next time",
  },
  tutorial_step_picker_favorites_body: {
    zh: "收藏过的耗材都在「收藏」页，下次打开不用再搜索。PLA、PETG 等标签页可以按材料类型筛选。",
    en: "Everything you favorite appears on the Favorites tab, so next time you do not need to search. The PLA, PETG and other tabs filter by material type.",
  },
  tutorial_step_picker_done_title: {
    zh: "确认数量，点「完成」",
    en: "Check the count and click Done",
  },
  tutorial_step_picker_done_body: {
    zh: "底部会显示已选耗材的数量，确认无误后点「完成」。",
    en: "The bottom bar shows how many materials are selected. When it looks right, click Done.",
  },
  tutorial_step_materials_summary_title: {
    zh: "已选耗材显示在这里",
    en: "Your selected materials appear here",
  },
  tutorial_step_materials_summary_body: {
    zh: "选好的耗材会带色块显示在这里，一眼就能核对颜色。需要调整时再点一下，重新打开选择框。",
    en: "Your selected materials are listed here with color swatches, so you can check them at a glance. Click again to reopen the picker and make changes.",
  },
  tutorial_step_backing_title: {
    zh: "底板耗材选白色",
    en: "Use white as the base plate material",
  },
  tutorial_step_backing_body: {
    zh: "「底板耗材」垫在画面最底下，相当于整幅图的背景色。通常选白色，颜色还原最好。",
    en: "The Base Plate Material sits underneath the whole picture and acts as its background color. White usually gives the most accurate colors.",
  },
  tutorial_step_materials_missing_title: {
    zh: "找不到同款耗材？",
    en: "Can't find your filament?",
  },
  tutorial_step_materials_missing_body: {
    zh: "到「耗材管理 → 云端耗材库」下载。如果云端耗材库不可用（例如从 GitHub 源码自行部署、没有配置云端地址），就用「梯度卡生成」打印梯度卡，再在「梯度卡提取」里为自己的耗材建档。",
    en: "Download it from Material Management → Cloud Material Library. If the cloud library isn't available (for example a self-hosted build from the GitHub source with no registry configured), print a gradient card with Gradient Generator and create a profile for your filament in Gradient Extractor.",
  },
  tutorial_step_layer_height_title: {
    zh: "层高保持 0.08 mm",
    en: "Keep the layer height at 0.08 mm",
  },
  tutorial_step_layer_height_body: {
    zh: "软件内置的耗材档案都是按 0.08 mm 层高校准的，保持默认最准确。改用其他层高，需要用那个层高重新打印梯度卡、校准耗材，否则颜色会有偏差。\n切片软件里的层高也要保持一致。",
    en: "The built-in material profiles are calibrated at 0.08 mm, so the default is the most accurate. To use another layer height, print new gradient cards at that height and recalibrate your materials, or the colors will be off.\nKeep the same layer height in your slicer.",
  },
  tutorial_step_layer_count_title: {
    zh: "叠色层数：7–8 层就够",
    en: "Color layers: 7–8 is plenty",
  },
  tutorial_step_layer_count_body: {
    zh: "每个颜色由几层耗材叠成。理论上层数越多，能叠出的颜色和过渡越丰富，但打印时间也越长。通常 7–8 层就足够了。",
    en: "Each color is built from a stack of material layers. More layers can produce more colors and smoother transitions, but take longer to print. 7–8 layers is usually enough.",
  },
  tutorial_step_size_title: {
    zh: "设置尺寸",
    en: "Set the size",
  },
  tutorial_step_size_body: {
    zh: "在这里设置宽度和高度（毫米），需要在打印机的打印范围内。\n叠色画由一格格色块拼成：同一张图打得越大，每处细节分到的色块越多，画面越清晰。空间允许就尽量打大一些。底板厚度第一次保持默认即可。",
    en: "Set the width and height (mm) here, within your printer's build area.\nA color-stacked picture is made of small printed cells: the larger you print the same picture, the more cells each detail gets and the clearer it looks. Print as large as you can. Leave the base thickness at its default for your first print.",
  },
  tutorial_step_preview_title: {
    zh: "预览效果",
    en: "Preview",
  },
  tutorial_step_preview_body: {
    zh: "放好图片、选好颜色来源后，点击「预览」。转换结果会显示在屏幕中间的 3D 预览区，用来检查颜色和细节。\n不满意可以回去调整设置，再预览一次。",
    en: "Once the picture and color source are set, click Preview. The result appears in the 3D preview in the middle of the screen, so you can check colors and details.\nIf something looks off, adjust the settings and preview again.",
  },
  tutorial_step_view3d_title: {
    zh: "3D 预览：用鼠标查看",
    en: "3D preview: mouse controls",
  },
  tutorial_step_view3d_body: {
    zh: "中间这块区域是 3D 预览，预览后模型会显示在打印热床上。用下面的鼠标操作从各个角度检查效果，现在就可以在高亮区域里试一试。",
    en: "This middle area is the 3D preview. After you preview, the model appears on the print bed. Use these mouse controls to inspect it from any angle, and feel free to try them in the highlighted area now.",
  },
  tutorial_controls_label: {
    zh: "鼠标操作",
    en: "Mouse controls",
  },
  tutorial_control_left_drag: {
    zh: "左键拖动",
    en: "Left-drag",
  },
  tutorial_control_rotate: {
    zh: "旋转视角",
    en: "Rotate the view",
  },
  tutorial_control_right_drag: {
    zh: "右键（或中键）拖动",
    en: "Right- or middle-drag",
  },
  tutorial_control_pan: {
    zh: "平移视图",
    en: "Pan the view",
  },
  tutorial_control_wheel: {
    zh: "滚动鼠标滚轮",
    en: "Scroll the wheel",
  },
  tutorial_control_zoom: {
    zh: "放大 / 缩小",
    en: "Zoom in / out",
  },
  tutorial_control_space_drag: {
    zh: "按住空格 + 左键拖动",
    en: "Hold Space + left-drag",
  },
  tutorial_control_space_pan: {
    zh: "也可以平移，适合触控板",
    en: "Also pans, handy on a trackpad",
  },
  tutorial_step_output_title: {
    zh: "生成并在切片软件中打开",
    en: "Generate and open in your slicer",
  },
  tutorial_step_output_body: {
    zh: "预览满意后，点击「生成并在 … 中打开」，模型会直接在切片软件（如 Orca Slicer）里打开；网页版或没有检测到切片软件时，点击「生成并下载 3MF」，再手动用切片软件打开。\n在切片软件里确认每个耗材槽位对应的颜色正确，就可以开始打印了。",
    en: "When the preview looks right, click Generate & open in … to open the model straight in your slicer (such as Orca Slicer). In the web version, or if no slicer is detected, click Generate & Download 3MF and open the file in your slicer yourself.\nIn the slicer, check that each filament slot has the right color, then print.",
  },
  tutorial_step_help_title: {
    zh: "遇到问题时",
    en: "When you need help",
  },
  tutorial_step_help_body: {
    zh: "设置项旁边的问号图标可以查看说明和在线文档；右上角这个菜单里的“反馈问题”可以把问题发给开发者。\n想再看一遍这份引导，随时打开这个菜单选择“新手引导”。祝打印顺利！",
    en: "The question-mark icons next to settings show explanations and link to the online docs, and Report a bug in this menu at the top right sends problems to the developers.\nTo see this tour again, open this menu and choose Beginner tour any time. Happy printing!",
  },
};

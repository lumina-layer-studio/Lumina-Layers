# 本地 LUT 目录

生产 LUT、色卡和配套照片已迁到 [Lumina-materials](https://github.com/lumina-layer-studio/Lumina-materials)。软件中的空库引导提供公开库查找、导入与自己校准；没有用于占位的空 LUT。

打包版包含固定版本离线资源。源码用户可运行 `python scripts/prepare_public_resources.py` 准备相同的材料与 LUT 入门包，也可直接从界面按需安装。完整说明见 [公开资源与离线使用](../docs/public-resources.md)。

运行时仍可在此保存用户 LUT；`Custom`、`Cloud` 和同步状态不纳入 Git。已存在的个人文件保持原样，不要用清空目录代替软件内的资源管理。

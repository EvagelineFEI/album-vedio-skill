# 素材与参考说明

## Long Cang 字体

文件：`assets/fonts/LongCang-Regular.ttf`。

Copyright 2018 The Long Cang Project Authors (https://github.com/googlefonts/longcang)。字体按 SIL Open Font License 1.1 提供，完整许可见 [assets/fonts/OFL.txt](assets/fonts/OFL.txt)。本仓库保留原始字体及许可；没有打包青峰体字体或系统字体。

## 通用相机与材质

`assets/instant-camera.png`、`assets/paper-fibers.png`、`assets/linen-weave.png` 是本项目使用内置图像生成工具创建的通用素材。实际提示词记录在 [references/generated-materials.json](references/generated-materials.json)。

## 设计参考

- [travel-memory-sticker-card](https://github.com/carolinaaafy/travel-memory-sticker-card)：从照片中选取重要元素的创作参考。
- [color-diary](https://github.com/carolinaaafy/color-diary)：从原照片选择颜色与背景气质的参考。
- [Flipin](https://flipin.pages.dev/)：电子书、自由拼贴与内页节奏的参考。

本仓库的工作流与合成脚本独立编写，不包含上述参考项目的原始代码、提示词文件或模板资产。参考项目仍适用其各自许可，本仓库不为其转授任何权利。

## 运行时依赖

Pillow、NumPy、imageio-ffmpeg 和 FFmpeg 分别适用各自的许可。本仓库不打包 FFmpeg 或 Python 运行时二进制。用户提供的照片、文案、录音、配乐和字体由用户在自己的项目中准备与管理。

# album-vedio-skill

把旅行、日常、家庭或宠物照片，剪成一本会翻页的精装影像手账。

**美学封面 → 相机吐出最多五张真实照片 → 叠放成书 → 连续翻页 → 合书 → 照片回到相机 → 可选片尾词。**

这是一个可安装的 Codex skill，包含创作流程、图像素材提示词、可配置合成脚本、相机与纸张/织物材质。它不依赖本仓库作者的聊天记录。

## 在 Codex 中使用

本机安装后，在下一条消息或新的 Codex 对话中输入：

```text
使用 $album-vedio-skill，把这些照片做成翻书电子相册。
```

也可以补充偏好：

```text
使用 $album-vedio-skill。标题用“秋日散步”，我会提供文案。
连续同前缀的照片放在同一页，保留 GIF 动态，封面用哑光纸和自然光影。
```

开始真正剪辑前，skill 会先询问尚未明确的选择：

1. 是否指定相册标题，也可授权代拟或选择不加标题。
2. 是否提供文案。有稿先校对，再结合图片与页组分段；无稿才根据照片另写简短生活配文。
3. 是否指定片尾词，也可授权代拟或选择不加文字。明确不要片尾时跳过这项。

当前制作已经回答过的信息直接复用。只修改 skill 或咨询方法时，不触发制作问询，也不自动生成样片。

## 安装

在另一个 Codex 环境中，可以直接发送：

```text
请安装这个 skill：https://github.com/EvagelineFEI/album-vedio-skill
```

也可手动安装到用户技能目录：

```bash
git clone https://github.com/EvagelineFEI/album-vedio-skill.git ~/.codex/skills/album-vedio-skill
```

若使用了自定义 `CODEX_HOME`，安装到该目录的 `skills/album-vedio-skill`。不要把仓库根目录里的文件逐个散放到 `skills/` 下，需保留整个 skill 文件夹。

手动 Git 安装的更新方式：

```bash
git -C ~/.codex/skills/album-vedio-skill pull --ff-only
```

安装后的下一条消息即可使用；其他电脑需分别安装。同一台电脑的其他 Codex 对话可以调用同一份用户级 skill。

## 能做什么

| 能力 | 处理方式 |
| --- | --- |
| 标题与文案 | 先询问；保留原稿、校对稿、修改记录与逐页分段；不擅改专名和事实 |
| 同前缀合页 | 仅合并连续的语义前缀图片，保留顺序；支持两张及多张照片放在左页 |
| 动态图片 | 保留 GIF、APNG、动态 WebP 的真实多帧；支持有独立 MOV/MP4 动态段的实况照片 |
| 封面 | 装帧材质、嵌图、氛围背景、字体四个轴独立组合，保留至少 40% 呼吸空间的设计规范 |
| 片头 | 先展示封面，再相机吐片；片头最多五张，不限制电子书的总图片数 |
| 自由内页 | 文字可在上方、侧边、中央等位置，可覆盖每个图层的坐标、尺寸和倾斜角 |
| 人物与动物 | 优先考虑鲜明着装、独特姿态，与建筑、植物、小物混合选取，不做成全人物贴纸集 |
| 立体效果 | 素材体积光影、接触阴影、轻摆和 2.5D 倾斜；翻页有弯曲投影、正反面与遮挡 |
| 声音 | 原创简易程序伴奏或已有音乐；快门、出片、翻页音效；已有口播时压低配乐 |
| 单页修改 | 自动检测变化，仅重做受影响页面及相邻翻页；复用其他视频片段，连续音轨独立缓存 |
| 多文件夹 | 一个总工程统一故事、书册和页码；各部分单独渲染，最终补齐交界翻页 |
| 片尾 | 最后一页合书、照片逐张返回相机；可指定、代拟或不加片尾词，全片仅一次 |

## 多文件夹合成一本书

图片可以留在多个文件夹中。先整体规划照片顺序和文案，再让总工程引用各文件夹的子工程；各部分共用书册、配色、字体、配乐及全局页码。内容也会检查衔接，避免每一部分都重复开场或提前告别。

```text
使用 $album-vedio-skill，按“01 抵达 → 02 散步 → 03 傍晚”的顺序制作。
先统一规划内容，再分部分渲染，最后合成一本连续翻页的书，只保留一个片头和片尾。
片尾词用“把今天，慢慢收藏”。
```

```bash
.venv/bin/python scripts/render_book.py /project/master.json --part arrival --output /project/part-01.mp4
.venv/bin/python scripts/render_book.py /project/master.json --part walk --output /project/part-02.mp4
.venv/bin/python scripts/render_book.py /project/master.json --output /project/complete.mp4
```

最后一步复用已生成的页面和内部转场，补上跨部分的翻页，输出连续音轨。首部分含唯一片头，末部分含唯一片尾。完整示例见 [多文件夹总工程](examples/collection/master.example.json)；规则见 [分部分合成与片尾](references/collections-and-outro.md)。

此方式需要保留子工程、原素材和共同缓存；只有几个已经独立完成的 MP4 时，无法自动还原书页和原来的翻页关系。

## 只修改某一页

可以直接说：

```text
使用 $album-vedio-skill，修改原相册的第 2 页：文字移到左上角，树叶放大一点。
其余页面沿用原设计，复用已经生成的视频片段。
```

从这一版开始，默认导出会保存片头、开书、各页、翻页和结尾的独立片段。后续修改自动核对内容与素材；例如只改第 2 页排版，通常只生成第 2 页及 1→2、2→3 的翻页，其余视频直接拼接。只换口播且时长不变时，可以复用全部画面。

保留 `project.json`、素材和其旁边的 `.album-cache/`。第一次使用新功能时，需要完整导出一次建立缓存；已有的旧 MP4 本身没有这些缓存。配置文件换名时用 `--cache-dir` 指回原目录，输出 MP4 换名不影响缓存命中。

```bash
# 查看将重做和复用的片段，不生成视频
.venv/bin/python scripts/render_book.py /path/to/project.json --cache-plan
# 修改原配置后导出新版本，自动复用
.venv/bin/python scripts/render_book.py /path/to/project.json --output /path/to/album-v2.mp4
# 必要时强制刷新某页及相邻翻页
.venv/bin/python scripts/render_book.py /path/to/project.json --rebuild-pages 2 --output /path/to/album-v3.mp4
```

`.render.json` 会记录实际重做和复用的片段、帧数及音轨是否复用。更换全局主题、字体、画幅，或更换同时出现在封面/吐片中的照片，可能影响更多片段；渲染器不会强行使用旧画面。详细规则见 [局部修改说明](references/incremental-editing.md)。

## 封面与文字策略

每次正式制作前会先说明本次视觉配方，并记录在项目中，避免总用一套模板：

- **A：装帧与比例**：正方布面、美术馆哑光白、露脊线装、暗调压印。
- **B：封面嵌图**：拍立得、微缩窗口、非对称出血、撕边和纸胶带。
- **C：背景**：虹彩泡泡、暮色云层、斑驳自然光、水面、胶片渐变。
- **D：封面排字**：等宽打字机、微缩衬线、瑞士网格。

同一次制作中的封面、回书与开本保持一致。日期、坐标、天气、期号只使用实际已知的信息。

有文案时，以校对后的原稿为文字主线，按图片和页组分段；没有文案时，才写“路过一扇窗，刚好接住阳光”这类基于画面的小观察。内页默认细长、松散的手写风格，封面字体独立服从本次视觉配方。

## 脚本依赖与运行

需要 **Python 3.10+**、Pillow、NumPy，以及支持 `libx264`、AAC、`loudnorm` 的 FFmpeg。`imageio-ffmpeg` 可提供编码器；也可使用系统 FFmpeg。

以下为 macOS/Linux 示例：

```bash
cd album-vedio-skill
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

先准备真实照片、透明抠图和已完成的文字，再将 [示例配置](examples/project.example.json) 复制到个人工程，替换文件路径：

```bash
.venv/bin/python scripts/album_inputs.py "街角_01.jpg" "街角_02.gif" "河边_01.jpg" --output input-plan.json
.venv/bin/python scripts/render_book.py /path/to/project.json --plan-only
.venv/bin/python scripts/render_book.py /path/to/project.json --frame 4 --frame-file /path/to/preview.png
.venv/bin/python scripts/render_book.py /path/to/project.json --output /path/to/album.mp4
```

Windows 使用虚拟环境的 `Scripts/python.exe`。`FFMPEG_BINARY` 可显式指定编码器路径。

**示例只含配置，不附带旅行照片、个人素材或样片。** 相机和材质是随 skill 提供的通用素材。示例中的封面配方只是填写方式，不代表每次必须沿用同一组合。

### 输出

- `album.mp4`：H.264/AAC 成片。
- `album.cover.jpg`：封面预览。
- `album.timeline.json`：实际时间表、配方、取色、图片分组与动态信息。
- `album.audio.wav`：合成音轨。
- `album.render.json`：本次重做/复用记录。
- `.album-cache/<配置名>/`：可复用的视频片段和连续音轨，不需要上传到 GitHub。

完整字段说明见 [references/rendering.md](references/rendering.md)。

## 动图与同前缀的细节

- `街角_01.jpg`、`街角_02.gif` 连续出现时可合页；中间夹入其他事件后，不跨页重排合并。
- 拷贝或改名后用 `original_name` 保留原附件名；可用显式 `group` 覆盖自动前缀。IMG、DSC 等通用相机命名不作为事件名误合整批照片。
- 同组多图保持比例和主体完整；过密时先调整开本或询问是否拆页，不静默丢图。
- 动图默认按原速度循环，`playback=source` 尊重源循环信息，`once` 只播一次。封面和吐片采用动图时也保留真实换帧。
- 实况照片的静态文件与动态段放在同一来源项的 `file`、`motion_file` 中；缺少动态段时不能把静态首帧声称为保留了动态。

## 模型与脚本分别负责什么

Codex 负责看图、提问、校对、语义分组与分段、艺术方向，以及调用实际可用的图像工具制作透明元素。

脚本负责排版、材质、时间线、多帧播放、翻页、混音和 MP4 输出。仅安装 Python 依赖不会自动获得图像生成、精确分割、中文纠错或语音合成服务；也可直接提供已准备好的透明素材与口播音频。

默认的“3D”是 2.5D 图层效果；观看物体背面的真实旋转需要另备网格或多视角素材。内置手写动画为逐字显现，不是逐笔书写。内置 Long Cang 为近似手写备选，不是青峰体同款字体。封面字体系会寻找可用系统字体，实际替代情况写入时间表；用户也可通过 `cover_fonts` 指定已有字体文件。

## 目录

```text
album-vedio-skill/
├── SKILL.md                  Codex 工作流与判断规则
├── agents/openai.yaml        名称、简介与默认调用提示
├── scripts/                  合成、分段缓存、媒体读取、输入分组、封面与版面模块
├── assets/                   通用相机、纸张/织物材质与字体许可
├── examples/project.example.json
├── references/               输入、封面、抠图、美术与配置说明
├── tests/                    基础功能与临时片段的增量合成检查
└── requirements.txt
```

## 验证

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q scripts
```

测试使用临时简单图像检查连续分组、动态图时序、多图左页、封面配方及无标题流程；临时片段测试核对单页修改、延长页面、替换口播、缓存恢复、跨部分翻页、片头片尾各一次，以及拼接后的逐帧一致性。临时文件自动清理，不使用或上传个人照片和样片；无 FFmpeg 时会跳过合成测试。

## 素材与参考

字体许可和素材来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本仓库只打包独立编写的工作流与脚本、通用生成素材、带许可的字体及配置示例；参考项目的原始代码、模板与个人照片不包含在仓库中。

仓库暂未声明代码和文字的整体开放源代码许可证；第三方字体继续适用其随附许可。

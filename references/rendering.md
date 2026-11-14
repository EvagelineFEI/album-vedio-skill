# 材质、片头与自由版面合成

合成器消费已准备好的照片、透明元素和成稿文字。识图、人物/动物选择、抠图与文案提炼由前面的制作步骤完成；脚本不自动生成这些内容。

## 依赖与运行

Python 3.10+、Pillow、NumPy、FFmpeg（libx264、AAC、loudnorm）。可通过 `imageio-ffmpeg` 提供编码器。

```bash
python3 -m venv work/video-env
work/video-env/bin/python -m pip install Pillow numpy imageio-ffmpeg
work/video-env/bin/python "SKILL_DIR/scripts/render_book.py" work/project.json --plan-only
work/video-env/bin/python "SKILL_DIR/scripts/render_book.py" work/project.json --frame 4 --frame-file work/preview.png
work/video-env/bin/python "SKILL_DIR/scripts/render_book.py" work/project.json --output outputs/memory-book.mp4
```

`SKILL_DIR` 换成实际 skill 目录。`FFMPEG_BINARY` 可指定编码器路径。不要为了内置图像编辑工具要求用户提供 API key；合成器没有图像 API 调用。

六个脚本 render_book.py、book_design.py、book_intro.py、book_cover.py、album_inputs.py、album_media.py 应放在同一目录。内置相机、纸纤维、封皮织物与手写字体在 `assets/` 中。使用原始脚本时自动找到内置材质；导出独立工程时一并复制素材，或在配置中显式指明位置。

## project.json

所有资产路径相对于 JSON。文件名换成真实资产，文字已经是成稿，不由合成器自动润色。

```json
{
  "size": [1920, 1080],
  "fps": 30,
  "title": "Autumn Notes",
  "subtitle": "街角的秋天",
  "cover_recipe": {"A": "A3", "B": "B2", "C": "C3", "D": "D2", "seed": 137},
  "cover_photo_index": 1,
  "intake": {
    "title": {"mode": "user", "value": "Autumn Notes"},
    "copy": {
      "mode": "provided",
      "original": "阳光落在街角，树梢开始变黄，慢慢走过这个秋天。",
      "corrected": "阳光落在街角，树梢开始变黄，慢慢走过这个秋天。",
      "edits": []
    }
  },
  "caption_policy": "provided-script",
  "intro": {
    "mode": "cover-camera-book",
    "hero_hold": 2.2,
    "hero_transition": 0.65,
    "photo_gap": 0.8,
    "photo_travel": 1.2,
    "merge_duration": 1.15,
    "title_delay": 0.25,
    "title_reveal": 0.9,
    "title_hold": 0.7
  },
  "opening": 1.8,
  "page_turn": 1.5,
  "final_hold": 1.2,
  "motion": 0.8,
  "theme": {"auto": true},
  "materials": {"paper_strength": 0.9, "cover_strength": 0.9},
  "typography": {"width_scale": 0.87, "tracking": 0.045, "line_height": 1.48},
  "music": {"mode": "synth", "mood": "calm", "bpm": 76, "source": "原创程序器乐伴奏"},
  "sfx": true,
  "scenes": [
    {
      "group_key": "街角",
      "photos": [
        {"file": "assets/photo-01.jpg", "original_name": "街角_01.jpg"},
        {"file": "assets/photo-02.gif", "original_name": "街角_02.gif", "playback": "loop"}
      ],
      "photo_layout": "auto",
      "layout": "caption-top",
      "elements": [
        {"file": "assets/person-red-coat.png", "name": "红外套人物", "kind": "person", "treatment": "original-cutout"},
        {"file": "assets/window.png", "name": "拱窗", "kind": "architecture", "treatment": "paper-3d-look"},
        {"file": "assets/bag.png", "name": "随身包", "kind": "object", "treatment": "original-cutout"}
      ],
      "caption": "阳光落在街角，树梢开始变黄。",
      "caption_source": "reviewed-script",
      "narration": "阳光落在街角，树梢开始变黄。"
    },
    {
      "photo": "assets/photo-03.jpg",
      "layout": "caption-left",
      "elements": [
        {"file": "assets/cat.png", "name": "猫", "kind": "animal"},
        {"file": "assets/leaf.png", "name": "树叶", "kind": "plant"}
      ],
      "caption": "慢慢走过这个秋天。",
      "caption_source": "reviewed-script",
      "narration": "慢慢走过这个秋天。"
    }
  ]
}
```

示例人物、动物等只是字段示意，不能据此向没有这些物体的原图添加它们。

## 封面配方与片头时间

封面美术规范见 [cover-art-direction.md](cover-art-direction.md)。新项目显式设置 `cover_recipe`，A/B/C/D 可指定 ID 或 `auto`，并保存 `seed`。四轴分别选择，不是固定四套打包模板。制作前由 agent 宣布并写入本次配方；重渲染同一工程不重新抽取。新制作应结合主题和已用配方避免重复，而不是每次都照抄示例 A3/B2/C3/D2。

- A1 为 1:1、A2 为 3:4、A3 为 4:5，A4 根据本次种子取 1:1 或 3:4。比例决定同一本电子书的开本，封面与回书保持一致。
- `cover_photo_index` 为封面嵌图的零基索引，指向逐页展开后的原始图片列表，不是页组编号；同页两张图会占两个索引。封面 B1/B2/B3/B4 控制相纸、窗口、出血或胶带关系。
- `backdrop.asset` 可使用实际生成的背景图；没有时按 C 轴生成程序氛围背景。`backdrop.gobo` 可为 `leaves` 或 `blinds`；C2 的 `silhouette_asset` 仅在实际已有剪影素材时使用。
- `cover_fonts` 可提供 `mono`、`serif`、`sans` 的字体路径。未提供时寻找系统对应字体，缺少时使用内置字体作近似替代，实际字体及替代情况记录在时间表中。不要把系统字体文件未经许可打包进工程。
- `cover_metadata` 可记录真实的 `date`、`year`、`issue`、`weather`、`coordinates`；只显示确有输入的字段。脚本没有默认日期、天气、坐标和假期号。
- `intro.mode=cover-camera-book`：新开场，先展示完整封面，再过渡到相机吐片，照片收拢后回到同一封面，再开书。
- `hero_hold` 为第一张完整封面的展示时间，`hero_transition` 为到相机的过渡时间。
- `intro.mode=camera-stack`：保留 v2 的相机直接开场；`cover`：只开书。未写 `intro` 的旧配置仍走 cover，未写 `cover_recipe` 的旧配置保留 v2 封面与开本。
- `intro.camera_asset` 可替换透明相机 PNG，需检查下前方出片口对齐。
- `intro.photo_count` 最多 **5**，且不能超过实际照片数；默认从全书有序选取最多五张代表照片。电子书内页本身不受这五张片头限制。
- `intro.photo_indices` 可直接指定 1–5 个不重复、有效的零基照片索引。打印的仍是这些真实照片，不能为凑数量造图。
- `opening` 只表示完整片头之后的开书时长，不是整个片头时长。音效、页面起点与口播随前段偏移。
- 有标题时回书阶段先成书、后重新显现书名。最初完整封面可以带书名，打印中的照片不能加上书名。用户选择 intake.title.mode=none 时不加标题/副标题，跳过回书标题动画，不强制代拟书名。

`--plan-only` 返回封面展示、相机开始、出片、成书与回书标题时刻，以及完整配方和每幕起点。使用实际时间表选择关键帧，不依赖旧项目秒数。


## 自动取色与材质

`theme={"auto":true}` 从本项目照片提取候选主色、阴影与点缀，并结合书名/原稿中的主题词选择强调色。可以覆盖 `accent`、`cover`、`paper`、`ink`、`cover_ink`、`foil`。最终取色与实际值记录在时间表的 `resolved_theme`。

明确背景渐变：

```json
"theme": {
  "accent": "#b6a15c",
  "background_gradient": {
    "colors": ["#d8cda3", "#ccd9de", "#b4b2a4"],
    "angle": 128
  }
}
```

颜色需按本次照片选择，不把此示例当固定配色。旧字段 `theme.background` 仍可用，会从该色产生明暗渐变。文字与纸面明暗对比低于 4.5:1 时拒绝显式低对比配置。

`materials.paper_texture`、`materials.cover_texture` 可指定本地纹理；默认使用内置纸纤维与细亚麻。`paper_strength`、`cover_strength` 取值 0–2；0 关闭纹理。纹理按纸面坐标固定，没有逐帧噪声闪烁。

每幕 `theme` 可覆盖 `paper`、`ink`、`background_gradient` 等；跨页时背景会交叉过渡。封皮保持全书主题的一致性。

## 可变化的版式与自由覆盖

`layout` 可为 `auto`、`caption-top`、`caption-left`、`caption-right`、`caption-center`、`diagonal-notes`、`caption-bottom`。自动版式结合页码与文字长度形成变化；具体创作可按主体轮廓指定家族。

更精确时用 `composition` 覆盖文字区与每个元素的图层框。坐标归一化到右页：`[x, y, width, height]`，原点为右页左上角。元素顺序对应 `elements`，同时决定入场顺序。框只作为排版边界，不会被画成图片的矩形背景。

```json
"composition": {
  "text": {
    "box": [0.50, 0.08, 0.40, 0.28],
    "rotation": -1,
    "align": "left",
    "style": {"font_scale": 0.067}
  },
  "elements": [
    {"box": [0.08, 0.14, 0.35, 0.63], "rotation": -2},
    {"box": [0.53, 0.46, 0.35, 0.42], "rotation": 2}
  ],
  "decorations": [
    {"kind": "wash", "box": [0.48, 0.06, 0.44, 0.32], "opacity": 0.08, "rotation": -2}
  ]
}
```

自定义框必须留在页内、不能压住文字阅读区。确实要抠图层间叠压时设置 `allow_element_overlap=true`，仍不能遮住文字。`decorations` 的 wash 是轻色纸/色块，其他装饰请使用准备好的真实 PNG，不把文字或图像模型输出的假字当装饰。

每幕 `photo_rotation` 可为 ±4 度以内，默认轻微交替倾斜；原照片等比 contain、不拉伸。

## 字体、口播与配乐

- `font`：用户提供的字体路径；默认 Long Cang。截图只能指导风格，不能当字体加载。没有青峰体字体文件时明确是近似手写风格。
- `typography.width_scale`：0.70–1.10，默认 0.87；`tracking` 是相对字号的额外字距；`line_height` 是行高倍数。`preserve_breaks=true` 优先让作者指定的配文断行完整保留，必要时缩小字号；生活诗意配文默认开启。正文可以缩小到适合位置，但过小会报错，要求改排版或拆句。
- 每幕 voiceover 为已有口播音频路径。narration 记录本幕文案或口播稿，不自动生成声音；caption 在有稿时来自校对稿对应片段，无稿时才按图另写。
- 每幕 `duration`：翻页前时长，不含相机片头、开书、翻页。若不足以让文字和口播完成，合成器拒绝截断。
- `music.mode=synth`：原创简易程序伴奏，情绪可选 calm / nostalgic / playful / urban / dreamy。
- `music.mode=file` 搭配 `music.file`：使用实际音乐；填写 `source`。短于全片时交叉淡化循环。
- `music.mode=none` 关闭配乐；`sfx=false` 关闭快门、出片、翻页与触感声。口播不会被关闭。
- 快门在每次出片时刻响起；出片带轻机械声；人声播放时压低音乐。

## 输出与核验

输出 MP4（H.264/AAC）、`.cover.jpg`（新模式为美学封面预览，旧模式为第一幕预览）、`.timeline.json`（含封面配方、字体、取色与逐页构图）和 `.audio.wav`。重新制作使用新文件名，或明确指定 `--overwrite`。

检查完整片头的照片、叠放与书名先后；至少检查两种不同右页排版；检查纹理在翻动中稳定、文字准确且无缺字，源照片无变形。人物/动物素材的生成质量由资产步骤检查，合成成功并不代表身份或肢体已经正确。元素仍是透明二维素材与 2.5D 动作，内置脚本不会重建物体背面。


## 输入问询、校对稿与分段

制作前执行 [input-workflow.md](input-workflow.md)。这两个选择由用户回答，不能以默认配置代替询问：是否指定标题，是否提供文案。当前制作中已有明确答案则直接复用。只修改 skill 时不发起这些制作问题。

`intake.title` 的 mode 为 user / assistant / none；user 或 assistant 的实际选定标题放在 value，none 不加书名。intake.copy 保存 mode=provided / image-led、original、corrected、edits。中文校对与语义分段由 agent 完成，脚本不自动纠错。

有文案用 caption_policy=provided-script、caption_source=reviewed-script。把校对稿按图片和页组语义分段，允许页面片段与同幕 narration 相同；不能因旧版“避免重复”规则而丢开用户原稿。用户明确授权短化或另写题记时再记录其授权用途。

没有文案才使用 observational-poetry / image-inspired。该模式仍拦截与本幕 narration 完全相同的题记；它只防逐字重复，不能替代内容判断。用户明确指定页面成稿用 caption_verbatim=true，不擅自润色。

## 连续同前缀分组与多图左页

在改名拷贝与生成素材之前读取原附件名。可先输出分组计划：

```bash
python3 "SKILL_DIR/scripts/album_inputs.py" "街角_01.jpg" "街角_02.gif" "河边_01.jpg" --output work/input-plan.json
```

这只是分组计划，不会校对文字、生成素材或渲染样片。agent 根据计划补齐文案、元素和艺术配方后形成 project.json。

同一连续组放在一个 scenes 项的 photos 列表；不要既写 photo 又写 photos。单图旧工程继续用 photo。文件重命名时保留 original_name，显式 group 字段可覆盖自动前缀。输入顺序保持不变，不跨过中间文件合并非连续组。

photo_layout 可为 auto / stack / side-by-side / grid。auto 依据组内横竖比例选择合适的组合；右页仍是该组的元素与文字。照片太密会报错，要求扩大开本或先询问是否拆组，不静默删图或拆页。

精确左页构图可用 photo_boxes 覆盖，每图一个 `[x,y,width,height]` 归一化边界，照片在框内等比完整展示。需要保留留白、避免主体遮挡，不能把一组第一张代替整组。

```json
"photos": [
  {"file": "assets/a.jpg", "original_name": "街角_01.jpg"},
  {"file": "assets/b.gif", "original_name": "街角_02.gif", "playback": "loop"}
],
"photo_boxes": [[0.09, 0.08, 0.82, 0.39], [0.09, 0.54, 0.82, 0.39]]
```

## 保留真实多帧动态

GIF、APNG、动态 WebP 使用 MediaSource 多帧合成；页面照片、相机吐片、封面嵌图及真实多帧透明元素均可读取随时间变化的源帧。Pillow 提供合成后的透明/处置帧，按原帧时长取样，不用首帧 JPEG 或抖动效果冒充原动态。封面预览仍是单张图片，但不会把预览回写成视频素材。

每个来源可设 playback=loop / source / once，默认原速度循环覆盖停留；source 尊重原循环信息，once 只播一次。offset 是非负起始偏移。动图画布尺寸保持一致，不能每帧裁框居中造成内容跳动。

Live Photo 或动态图的独立视频段可写 motion_file，例如：

```json
{"file": "assets/live-photo.jpeg", "motion_file": "assets/live-photo.mov", "playback": "loop"}
```

配对 MOV/MP4 等用 FFmpeg 解码并保留帧时间；相册内仍是一张来源，不把视频文件另算成第二张照片。嵌入式 Motion Photo 需先提取动态段。无配对文件或解码能力时明确提示，不静默静态化。视频动态默认只取画面，原声混音需按用户声音要求另行配置。

时间表会保存每页原始来源、组名、排版框、是否多帧、帧时长与播放策略，方便检查动图确实被保留。片头最多五张的限制作用于展开后的真实来源数，而不是页组数。

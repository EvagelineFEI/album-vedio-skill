# 多文件夹、分部分合成与合书片尾

用一个总工程管理一本书，而不是把几部独立成片直接接在一起。图片可以保留在不同文件夹；页面使用全局顺序，片头和片尾只在整片的两端出现。

## 先策划完整故事

先确认文件夹顺序，查看全部图片和完整文案。文件夹名与文件名可帮助整理，但不能自动当成真实拍摄时间。没有确定的先后关系且影响故事时，再询问必要的顺序信息。

将已校对的完整原稿按实际画面与全局页组分配，再划分部分。每个部分可在 `narrative` 中记录 summary、entry、exit；总工程记录叙事提纲。上一部分的 exit 和下一部分的 entry 应衔接，例如从街角继续走到河边，不在每部分重复“刚到这里”，不提前告别后又重新开始。需要承接句时放到下一页的 caption/narration 中，并按用户的原稿或改写授权处理。

这些语义判断由 agent 看图、校对和编辑完成。脚本负责保留顺序与记录，不会自动理解图片或判断文案是否连贯，也不会凭空生成连接经历。

## 规划多个文件夹的来源

```bash
python3 SKILL_DIR/scripts/album_collection.py /photos/01-arrival /photos/02-walk --output /project/input-plan.json
```

文件夹按给定顺序、内部按文件名自然排序。结果是待审核的输入分组计划，不会生成抠图、文案或视频。支持 `--recursive` 读取子目录；默认只读取指定目录内支持的图片文件，隐藏文件不计入。实况照片应由 agent 补齐配对动态来源。

连续同语义前缀可跨文件夹合成一组，`cross_folder_groups` 标出这种情况。整组放在一个子工程的同一页，素材路径可以引用另一个文件夹。总工程发现相邻部分把同前缀组拆开时会提示改组。只有用户明确授权拆组后，才设置总工程 `allow_boundary_group_split=true`。

## 总工程与子工程

示例总工程见 [../examples/collection/master.example.json](../examples/collection/master.example.json)。照片、透明元素、字幕、动态来源和已有口播放在各子工程的 scenes 中，路径相对于各自的 chapter.json；总工程会统一解析。

```json
{
  "parts": [
    {"id": "arrival", "project": "01-arrival/chapter.json"},
    {"id": "walk", "project": "02-walk/chapter.json"}
  ]
}
```

这是 parts 字段示意，其余设置使用完整示例。子工程只含 `scenes`、可选的 `narrative` 和 `metadata`。标题、字体、开本、配色、材质、配乐、原稿、片头片尾均放在总工程，避免各文件夹使用不同的书或声音。每页仍可有主题或构图覆盖，但需服从全书设计。

旧独立工程迁移时，先将选定的共同设置放到总工程，再把各工程的 scenes 按正确顺序放进子工程，检查素材路径、相邻同前缀分组和文案衔接。不要直接将旧 MP4 当作可编辑子工程。

## 分部分渲染，最后连贯合成

```bash
python3 SKILL_DIR/scripts/render_book.py /project/master.json --part arrival --output /project/part-01.mp4
python3 SKILL_DIR/scripts/render_book.py /project/master.json --part walk --output /project/part-02.mp4
python3 SKILL_DIR/scripts/render_book.py /project/master.json --cache-plan
python3 SKILL_DIR/scripts/render_book.py /project/master.json --output /project/complete.mp4
```

`--part` 可用 id 或部分序号，页号与动态时钟仍按总工程计算。首部分含唯一片头与开书，末部分含唯一结尾停留与片尾；中间部分不额外开书、合书或告别。部分预览不包含与其他部分交界的翻页。最终不带 `--part` 输出时，渲染器补齐交界翻页并复用已有页面和内部转场，最终视频各有一次片头、片尾。

最后合成使用缓存中的视频片段，而非再次压缩各个 MP4。配乐与口播始终按总时间线统一混音，部分预览取对应音轨区间；完整成片使用连续音轨，避免多个 AAC 片段首尾相接的断音、重复淡出或节拍重启。分批能减少每次逐帧渲染的范围，仍需读取全局计划并检查素材。

只有独立 MP4、没有原配置/素材/缓存时，可以普通拼接，但无法保证补出的翻页与原场景完全一致；不得声称能恢复原来的可编辑书页。

## 合书、照片回到相机与片尾词

新制作在总工程设置：

```json
{
  "intake": {"ending": {"mode": "user", "value": "把今天，慢慢收藏。"}},
  "outro": {"mode": "book-camera"}
}
```

制作前询问是否指定片尾词；user 使用已校对原句，assistant 表示已授权代拟并在 value 保存实际成稿，none 表示不加文字。无字片尾仍有合书和回收照片动画。仅修改 skill 时不问这些制作问题，旧工程未配置 outro 时继续保留原有结尾。

物理顺序：最后一页停留 → 合上同一本书 → 封面收拢成代表相片堆 → 相片逐张返回相机出片口 → 片尾词显现与阅读停留 → 淡出。相机默认沿用片头素材，返回照片默认与片头选取一致，最多五张真实照片；可用 outro.photo_indices 或 photo_count 调整。它们代表全书，不为数量复制或造图。GIF 等内部运动保持正向，只有飞回相机的路径反向。

outro 可覆盖 `close_duration`（0.5–5 秒）、`photo_gap`、`photo_travel`、`merge_duration`、`text_reveal`、`text_hold`、`fade_out`（0–3 秒）和 `camera_asset`。文字过长或停留不足会要求调整，不静默截断。时间表记录合书完成、照片回收完成、片尾词开始/完成和声音事件；`final_hold` 仍表示最后一页进入片尾前的停留。无需片尾时显式设 `outro.mode=none`。

片尾独立缓存；仅改片尾词且时长不变时，只重做片尾，页面、翻页、片头和连续音轨可以复用。

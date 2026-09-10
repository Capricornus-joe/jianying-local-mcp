# 工具参考

0.3.0 提供 **22 个 stdio MCP 工具**。本页与 `jianying_local_mcp/server.py` 的接口对应；完整参数校验由源码和 MCP 工具 schema 提供。

## 通用约定

- 时间单位是秒；`duration` 指时间线时长，视频/音频消耗的源时长为 `duration × speed`。
- `name` 是已存在的 MCP 管理工程；`new_name` 必须是一个尚不存在的新工程名。修订保留源工程。
- 写入工具默认 `dry_run=true`：校验输入，不创建工程或输出媒体。正式执行使用 `false`，内部仍会校验。
- 下表标为 **C** 的 11 个工具还接受 `include_plan=false`。默认只返回状态、摘要、输出位置等必要信息；显式传 `true` 返回完整计划。底层 Python `ProjectStore` 的完整返回行为未改变。
- 预检计划尚未保存。需要预检全文时，对同一调用传 `include_plan=true`，不要尝试读取一个尚不存在的新工程。
- 所有媒体路径必须指向受支持的本地文件。参数中的路径示例需要替换成实际绝对路径。

## 全部工具

| # | 工具 | 主要参数与行为 |
|---:|---|---|
| 1 | `check_environment` | 无参数。报告应用、草稿目录、版本和功能限制；不会认证新工程兼容性。 |
| 2 | `inspect_media` | `path`。读取时长、尺寸、音轨等本地元数据。 |
| 3 | `read_native_draft` | `path`。只读检查明文原生草稿目录或文件；非明文返回 unsupported。 |
| 4 | `list_managed_projects` | 无参数。列出当前配置工作区中的管理工程。 |
| 5 | `read_managed_project` | `name, view="summary", offset=0, limit=50, track=null`。摘要、clip 分页或显式全文，见下节。 |
| 6 | `batch_edit` **C** | `name, new_name, steps, dry_run=true`。1–100 个有序步骤在内存组合，最后只保存一个新修订。 |
| 7 | `create_draft` **C** | `plan, dry_run=true`。校验或生成自包含管理工程；不登记剪映首页。 |
| 8 | `edit_draft` **C** | `name, new_name, operations, dry_run=true`。追加、移除、更新、拆分；不自动消除空隙。 |
| 9 | `add_srt` **C** | `name, new_name, content, track="字幕", offset=0, font_size=48, color="#FFFFFF", dry_run=true`。从 SRT 文本添加原生字幕。 |
| 10 | `publish_draft` | `name, draft_root, dry_run=true`。向已有剪映草稿库登记一个新工程并备份首页索引；要求应用完全退出。 |
| 11 | `list_motion_presets` | 无参数。列出九种本地线性运动配方及透明度兼容性提示。 |
| 12 | `set_clip_features` **C** | `name, new_name, clip_ids, features, dry_run=true`。设置变换、裁切、文字样式、关键帧、蒙版等。 |
| 13 | `apply_motion_preset` **C** | `name, new_name, clip_ids, preset, strength=0.15, dry_run=true`。生成片段相对时间的线性关键帧。 |
| 14 | `reorder_track` **C** | `name, new_name, track, clip_ids, start=0, dry_run=true`。按给定顺序将一条轨道的全部片段无间隙排列。 |
| 15 | `ripple_delete` **C** | `name, new_name, start, end, dry_run=true`。删除所有轨道上的区间，剪裁相交片段并关闭空隙。 |
| 16 | `style_subtitles` **C** | `name, new_name, style, track=null, clip_ids=null, dry_run=true`。批量调整字幕 `font_size/color/x/y`。 |
| 17 | `export_srt` | `name, track=null`。返回字幕文本与时间，不写文件；不携带原生样式。 |
| 18 | `montage_create` **C** | `name, paths, clip_duration=null, image_duration=3, track="主画面", width=1920, height=1080, fps=30, dry_run=true`。顺序拼接视频/图片；不接受纯音频输入。 |
| 19 | `process_media` | `path, output_dir, operations, dry_run=true`。生成经过固定本地处理的新媒体，保留源文件。 |
| 20 | `extract_frame` | `path, time, output_dir, dry_run=true`。在指定源时间提取新 PNG；作为图片片段时自行设置停留时长。 |
| 21 | `list_native_resources` | `kind="all", query="", cache_root=null`。查询已审阅资源目录和本地缓存，不下载资源。 |
| 22 | `apply_native_resource` **C** | `name, new_name, clip_ids, resource_kind, resource_name, duration=0.5, dry_run=true`。使用唯一匹配的有效缓存资源生成新修订。 |

## 默认摘要与分页读取

```json
{"name":"demo-v1","view":"clips","offset":0,"limit":50,"track":"字幕"}
```

`view` 只能为 `summary`、`clips`、`full`。默认 `summary` 返回画布、帧率、时长、片段数和轨道名称等摘要。`clips` 先按精确轨道名称过滤，再按原计划顺序分页：

- `offset` 为非负整数，`limit` 为 1–200 的整数。
- 返回 `total`、`returned`、`next_offset`；末页或超出范围时 `next_offset=null`。
- 每个片段仅包含存在的 `id/kind/track/start/duration/text/display_name/source_start/speed/volume`；路径、样式和关键帧需查看全文。
- 不截断字幕正文。分页限制的是片段数量，不是响应字节上限。

```json
{"name":"demo-v1","view":"full"}
```

`full` 直接返回完整管理计划，保留全部字段与文本。`summary/full` 不接受非默认 `offset/limit` 或 `track`，避免把过滤结果误认作全文。升级旧客户端时，将依赖完整写入返回的调用加上 `include_plan=true`；原先直接读取全部 clip 的调用改用 `view="full"` 或分页。

## 创建计划与基础编辑

最小文字工程不需要媒体文件：

```json
{
  "plan": {
    "name": "demo-v1",
    "width": 1920,
    "height": 1080,
    "fps": 25,
    "clips": [
      {"id":"caption1","kind":"text","track":"字幕","start":0,"duration":3,"text":"示例字幕"}
    ]
  },
  "dry_run": false
}
```

`plan` 的画布默认 1920×1080，帧率默认 30。片段 `kind` 为 `video/audio/image/text`，需要 `duration`，可指定稳定 ASCII `id`、`track` 和 `start`。视频/音频/图片需要本地 `path`；视频和音频可设 `source_start=0`、`speed=1`、`volume=1`。文字需要 `text`，可设 `font_size=48`、`color="#FFFFFF"`、`x=0`、`y=-0.75`。字号到原生单位的换算仍需实际画面校准。

媒体片段可用 `display_name` 命名，长度 1–120 字符，不接受空白名称或控制字符；文字片段以 `text` 正文显示。同源不同名称/裁切可使用独立材质记录，单个工程内同一路径的媒体文件只复制一次。

同轨重叠被拒绝；叠加画面使用独立轨道。计划最多 2000 个片段，时间线不超过 24 小时，单个片段不少于 1 毫秒；正式自包含打包的不同媒体总量最多 10 GiB。

`edit_draft.operations` 接受 1–2000 项：

```json
[
  {"op":"append","clip":{"id":"caption2","kind":"text","track":"字幕","start":3,"duration":2,"text":"下一句"}},
  {"op":"update","id":"caption1","changes":{"text":"修改后的字幕","duration":2.5}},
  {"op":"split","id":"caption2","at":4},
  {"op":"remove","id":"caption1"}
]
```

`at` 为时间线绝对秒数。更新支持时间、源入点、速度、音量、文字、字号、颜色、位置、轨道、显示名和高级属性；不通过 update 更换媒体 `path` 或 `kind`。拆分会处理线性关键帧的切点值，但带原生动画、转场或非零音频淡入淡出的片段会被拒绝，需先移除相关效果。重排和波纹删除也会拒绝无法可靠重算的效果，宜先确定剪裁/顺序再添加动画。

SRT 导入将正文保留为字面文字，不解释 HTML 样式。导出仅保留文本与时间；空白正文行等无法忠实往返的内容会报错。不同文本轨合并导出时可以保留重叠字幕，但导入同一轨道仍受同轨不可重叠的计划校验约束。

## 批处理：一次保存多个步骤

```json
{
  "name":"demo-v1",
  "new_name":"demo-v2",
  "steps":[
    {"action":"edit","operations":[{"op":"update","id":"caption1","changes":{"text":"更新字幕"}}]},
    {"action":"style_subtitles","track":"字幕","style":{"font_size":42,"color":"#FFFFFF"}},
    {"action":"features","clip_ids":["caption1"],"features":{"text_style":{"bold":true}}}
  ],
  "dry_run":false
}
```

步骤按顺序执行，后一步看到前一步的结果。每步仍执行原工具的校验；任何一步失败都会报告步骤序号，并在创建最终工程前终止。成功执行只新增一份修订和一套媒体；预检不保存修订。`steps` 长度为 1–100，不接受未知 action 或额外字段。

| action | 必需字段 | 可选字段与默认值 |
|---|---|---|
| `edit` | `operations` | 无 |
| `features` | `clip_ids, features` | 无 |
| `motion` | `clip_ids, preset` | `strength=0.15` |
| `subtitles` | `content`（SRT 文本） | `track="字幕", offset=0, font_size=48, color="#FFFFFF"` |
| `style_subtitles` | `style` | `track=null, clip_ids=null` |
| `reorder` | `track, clip_ids` | `start=0` |
| `ripple_delete` | `start, end` | 无 |

步骤内部不接收 `name/new_name/dry_run/include_plan`，这些由外层调用统一管理。发布、导出、媒体预处理、资源下载不属于批处理步骤。

额外返回包括 `batch_steps`、`committed_revisions` 和 `review_scope`。后者包含受影响时间、片段类型、音频可能受影响和视觉轨道顺序变化等提示；片段 ID 和时间区间列表各最多 50 项，并带截断标记。它不是自动验收报告，也没有执行视频渲染或 QA。

## 高级属性、运动与缓存资源

`set_clip_features.features` 的主要分组：

| 分组 | 字段 |
|---|---|
| `transform` | `x, y, scale_x, scale_y, rotation, opacity, flip_horizontal, flip_vertical` |
| `crop` | `left, top, right, bottom`；源图归一化边界，范围 0–1，必须形成正面积矩形 |
| `text_style` | `bold, italic, underline, alignment, stroke_color, stroke_width, background_color, background_opacity, background_radius, shadow_color, shadow_opacity, shadow_diffuse, shadow_distance, shadow_angle, letter_spacing, line_spacing` |
| `keyframes` | `x/y/scale_x/scale_y/rotation/opacity` 各自的 `[{"time":0,"value":1}]` 数组；time 相对当前片段，线性插值 |
| `audio_fade` | `in, out` 秒；两段淡变不能相互重叠 |
| `mask` | `shape` 为 `circle/rectangle/linear`；可设 `x, y, width, height, rotation, feather, invert, round_corner` |
| `animations` | `[{"type":"in|out|group","duration":0.5,"resource":{...}}]` |
| `transition_out` | `duration` 和 `resource`；作用于本片段到同轨相邻片段的转场 |

`transform/text_style/keyframes` 按组内字段合并，其余组替换；在 `set_clip_features` 中将整个组设为 `null` 可移除该组。音频片段不接受视觉属性或视觉关键帧。支持的动画预设是 `zoom_in/zoom_out/pan_left/pan_right/slide_up/slide_down/fade_in/fade_out/pulse`，不是任意贝塞尔曲线。

`list_native_resources.kind` 为 `all/animation/video_animation/text_animation/transition`。`apply_native_resource.resource_kind` 只允许 `video_animation/text_animation/transition`，`resource_name` 取查询结果中的确切名称。仅使用已审阅目录中唯一匹配、有效的本机缓存资源；不下载效果，不根据缓存存在推定账号权益。具体应用渲染范围见[兼容性](compatibility.md)。

## 本地预处理

`process_media.operations` 接受 `brightness[-1,1]`、`contrast[0,3]`、`saturation[0,3]`、`gamma[0.1,10]`，以及布尔值 `reverse/extract_audio/normalize_audio/denoise_audio`。无效组合会报错；不接受任意 FFmpeg 滤镜字符串。倒放视频输入最多 600 秒。

这些操作生成新 H.264/AAC MP4、48 kHz PCM WAV 或 PNG，源文件保持不变。输出结果包含处理记录及复用建议；`extract_frame` 得到的图片片段仍需指定停留时长。预处理效果已写入文件，不是原生可编辑的调色/降噪参数。预检中的候选输出路径不保证与正式执行的新文件名相同。

多步确定修改优先使用 `batch_edit`，读取优先使用摘要和 clip 页。性能数据与计量边界见[性能说明](performance.md)。

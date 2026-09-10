# 让 AI 交出真正能改的剪映工程

**Jianying Local MCP｜把剪辑计划落到时间线，把继续创作的空间留给你。**

我希望 AI 做完剪辑后，交出的工程依然能继续调整：改一句字幕、换一个镜头、移动画面、细调节奏。这就是我做这个项目的出发点。

先看一个实际完成的案例：**《入戏·川剧初体验》**。

[![《入戏·川剧初体验》——点击观看案例预览](docs/assets/showcase-poster.jpg)](docs/assets/showcase-preview.mp4)

**[▶ 观看案例预览](docs/assets/showcase-preview.mp4) · [查看重建过程与工程边界](docs/case-study.md)**

| 成片 | 时间线 |
| --- | --- |
| 59.52 秒 · 1080p · 25 fps | 23 个场景 · 6 条主时间线轨道 |
| 从原始素材重建画面与节奏 | 28 句普通字幕，拆成 36 个可编辑文本片段 |
| 书法等视觉文字使用独立 PNG | 运动与裁剪保留为原生参数 |

这个案例把原素材、普通字幕、书法图层和运动逐项放回剪映时间线，并经过实际导出核对。**精修用到了包外专项适配，不能把它理解成当前通用 MCP 一键生成的结果；最终效果也不是逐像素相等。** 公开案例展示作品与实现过程，不附带原始素材或私人路径。细节见 [案例说明](docs/case-study.md)。

## 项目能做什么

`jianying-local-mcp` 提供 **22 个工具**，把本地视频、图片、音频和文字组织成可继续编辑的 Mac 剪映草稿。可编辑字幕、关键帧和部分原生效果都能通过 MCP 调用。服务通过本地 **stdio** 运行，不需要 HTTP 服务或剪映云端 API；本服务处理素材时不上传文件。时间线生成器为独立实现，不依赖第三方剪映草稿库运行。

当前版本 **0.3.0**。重点是减少重复工作：**批量编辑只生成一个新版本，默认返回简要结果，复用未变化素材的探测缓存。**

这是非官方项目，与剪映、CapCut 或字节跳动没有隶属或背书关系。**Mac 草稿兼容性仍属实验性；本项目不提供可靠的原生自动导出，不解密草稿，也不改写任意已有工程。** 生成后请在已安装版本的剪映中核对画面并导出。

[快速开始](#快速开始) · [批量编辑](#五步编辑一次保存) · [22 个工具](#22-个工具) · [能力边界](#能力边界) · [文档](#文档导航) · [English](README.en.md)

## 快速开始

### 1. 安装

准备 **macOS、Python 3.11 或更新版本**。原生预览和导出还需要本机安装剪映。项目使用 MCP Python SDK **v1.x**，依赖范围为 `mcp>=1.28,<2`；安装脚本会按项目声明安装，不需要手动安装最新版 `mcp`。

从源码安装：

```sh
git clone https://github.com/mjz925804554-jpg/jianying-local-mcp.git
cd jianying-local-mcp
bash setup.sh
bash run.sh doctor
```

`setup.sh` 在仓库内创建 `.venv` 并安装项目及测试依赖。若默认 `python3` 版本太旧，可指定已有的 Python：

```sh
JIANYING_SETUP_PYTHON=python3.11 bash setup.sh
```

这是本地源码安装方式，不要求本项目已发布到 PyPI。FFmpeg 默认由 `imageio-ffmpeg` 提供，也可通过环境变量指定已有程序。

### 2. 连接 MCP 客户端

将以下配置加入支持通用 `mcpServers` 格式的客户端，并把路径替换为实际**绝对路径**。不同客户端的配置文件位置或结构可能不同。

```json
{
  "mcpServers": {
    "jianying-local": {
      "command": "/absolute/path/to/jianying-local-mcp/.venv/bin/python",
      "args": ["-m", "jianying_local_mcp", "serve"],
      "env": {
        "JIANYING_MCP_WORKSPACE": "/absolute/path/to/jianying-local-mcp/projects"
      }
    }
  }
}
```

重新加载客户端后，调用 `check_environment` 检查应用和草稿位置。`bash run.sh` 也可直接启动服务，但它会等待 stdio 客户端连接，没有网页界面；通常由客户端启动即可。

| 环境变量 | 用途 |
| --- | --- |
| `JIANYING_MCP_WORKSPACE` | MCP 管理项目的目录；`run.sh` 默认使用仓库内 `projects/` |
| `JIANYING_SETUP_PYTHON` | 安装时使用的 Python，默认 `python3` |
| `JIANYING_MCP_PYTHON` | 启动时使用的 Python，默认 `.venv/bin/python` |
| `JIANYING_FFMPEG` | 可选：本地 FFmpeg 可执行文件的绝对路径 |

### 3. 创建第一个草稿

这个六秒小例仅含两段原生文字，不需要下载示例视频。调用 **`create_draft`**，参数如下：

```json
{
  "plan": {
    "name": "hello-mcp-v1",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "clips": [
      {
        "id": "caption1",
        "kind": "text",
        "track": "字幕",
        "text": "你好，剪映 MCP",
        "start": 0,
        "duration": 3,
        "font_size": 48,
        "color": "#FFFFFF"
      },
      {
        "id": "caption2",
        "kind": "text",
        "track": "字幕",
        "text": "这是一条可以继续编辑的字幕",
        "start": 3,
        "duration": 3,
        "font_size": 48,
        "color": "#FFFFFF"
      }
    ]
  },
  "dry_run": false
}
```

`dry_run=false` 会实际创建新草稿；希望仅校验时改为 `true`，需要查看完整计划时再加 `include_plan=true`。实际写入也会校验，无需为每个确定操作重复调用预检和写入。同名项目不会被覆盖，重复执行示例时请换一个名称。

结果中的 `project_dir` 指向管理目录。新项目包含 `draft_info.json`、`draft_meta_info.json`、`jianying_mcp_project.json` 和 `Resources/`。生成草稿包与登记到剪映首页是两步不同操作。

### 4. 登记到剪映并打开

**完全退出剪映**，使用 `check_environment` 或剪映设置确认实际草稿根目录。调用 **`publish_draft`**：

```json
{
  "name": "hello-mcp-v1",
  "draft_root": "/absolute/path/to/com.lveditor.draft",
  "dry_run": false
}
```

`draft_root` 必须是已有且含可识别 `root_meta_info.json` 的草稿目录。工具复制为一个新的原生工程，备份首页索引并登记；执行期间保持剪映退出。随后手动打开剪映，在首页进入草稿，检查字幕并导出。

`publish_draft` 不会上传到互联网，也不会启动剪映或导出 MP4。若先试下一节批处理，可以只登记最终版本。

## 五步编辑，一次保存

对已有的 `hello-mcp-v1` 调用 **`batch_edit`**。下面依次改文字、加粗、统一字号、加描边、添加渐显关键帧，最终只创建 `hello-mcp-v2`：

```json
{
  "name": "hello-mcp-v1",
  "new_name": "hello-mcp-v2",
  "steps": [
    {
      "action": "edit",
      "operations": [
        {"op": "update", "id": "caption1", "changes": {"text": "五步编辑，一次保存"}}
      ]
    },
    {
      "action": "features",
      "clip_ids": ["caption1"],
      "features": {"text_style": {"bold": true}}
    },
    {
      "action": "style_subtitles",
      "track": "字幕",
      "style": {"font_size": 42, "color": "#FFFFFF"}
    },
    {
      "action": "features",
      "clip_ids": ["caption1"],
      "features": {"text_style": {"stroke_color": "#000000", "stroke_width": 2}}
    },
    {
      "action": "motion",
      "clip_ids": ["caption1"],
      "preset": "fade_in",
      "strength": 0.2
    }
  ],
  "dry_run": false
}
```

批处理支持 **1–100 个有序步骤**：`edit`、`features`、`motion`、`subtitles`、`style_subtitles`、`reorder`、`ripple_delete`。沿用对应工具的编辑规则，校验失败时停止，不留下中间工程或中间媒体副本。原项目保留；最终新版本仍是自包含草稿，会复制它引用的媒体。批处理不包含发布、媒体预处理或导出。

渐显等透明度关键帧存在应用版本差异，需检查实际导出。时间单位统一为秒：`start` 是时间线位置，`source_start` 是素材入点，`duration` 是时间线时长，消耗源素材时长为 `duration × speed`。同轨片段不能重叠；叠加画面或文字使用不同轨道。剪裁、排序通常应先于动画和转场。

### 减少返回数据与重复探测

- 返回剪辑计划的写入工具默认只给摘要；需要全量数据时传 `include_plan=true`。
- `read_managed_project` 默认 `view="summary"`。取得片段 ID 可用 `{"name":"hello-mcp-v2","view":"clips","offset":0,"limit":50,"track":"字幕"}`；每页最多 200 段。完整计划用 `view="full"`。
- 媒体探测缓存限于同一服务进程，最多 2,048 项、保留五分钟，并检查媒体文件与 FFmpeg 身份变化。相同素材的并发探测会合并；它缓存的是元数据，不是整段解码画面。
- 批处理的 `review_scope` 给出受影响片段、时间范围和音频检查提示，**不是原生画面通过证明**。

本机历史 stdio 小样中，同一组五步编辑由 **5 次调用、5 个新版本降为 1 次调用、1 个新版本**。该结果说明减少了重复保存，不代表整片剪辑、渲染或模型账单按相同比例下降。基准范围、数据与复现方法见 [性能说明](docs/performance.md)。

## 22 个工具

| 工具 | 用途 |
| --- | --- |
| `check_environment` | 检查应用、草稿位置和能力边界 |
| `inspect_media` | 读取本地素材类型、时长、尺寸和音轨信息 |
| `read_native_draft` | 只读检查明文原生草稿 |
| `list_managed_projects` | 列出本 MCP 管理的项目 |
| `read_managed_project` | 摘要、按轨道分页或显式全量读取 |
| `create_draft` | 新建视频、图片、音频和文字草稿 |
| `edit_draft` | 在新版本中追加、删除、拆分和调整片段 |
| `batch_edit` | 组合多步编辑，最终保存一个新版本 |
| `add_srt` | 将 SRT 导入为可编辑字幕 |
| `publish_draft` | 新建原生工程并登记到剪映首页 |
| `list_motion_presets` | 列出九种线性运动预设 |
| `set_clip_features` | 设置几何、裁剪、关键帧、文字样式、蒙版等 |
| `apply_motion_preset` | 批量应用推近、平移、渐显等关键帧预设 |
| `reorder_track` | 连续排列指定轨道的全部片段 |
| `ripple_delete` | 删除所有轨道的指定区间并收拢后续内容 |
| `style_subtitles` | 按轨道或 ID 批量设置字号、颜色和位置 |
| `export_srt` | 返回 SRT 文本 |
| `montage_create` | 按文件顺序组装视频或图片 |
| `process_media` | 生成经过基础调色、倒放或音频处理的新素材 |
| `extract_frame` | 提取 PNG，用于封面或停帧画面 |
| `list_native_resources` | 查询小型已审阅资源目录及本机缓存 |
| `apply_native_resource` | 应用唯一匹配且有效的本机动画或转场缓存 |

## 能力边界

| 范围 | 当前行为 |
| --- | --- |
| 目标平台 | Mac 剪映草稿；其他系统或 CapCut 版本未作通用兼容承诺 |
| 可以编辑的工程 | 仅本 MCP 的管理计划；修改创建新版本，不覆盖源项目 |
| 已有原生工程 | 支持明文只读检查；不解密，不直接改写任意原生草稿 |
| GUI 修改回流 | 在剪映内修改发布版后，不会自动同步回 MCP 管理计划 |
| 自动导出 | 未实现可靠的 Mac 原生自动导出；需在剪映内预览和导出 |
| 原生资源 | 依赖本机有效缓存；不下载效果包，不保证其他机器或会员资源可用 |
| 原生编辑与预处理 | 文字、几何等写入草稿；`process_media` 的处理结果烘焙在新文件中，不能在剪映里逐项关闭 |
| 高级剪辑 | 不提供曲线变速、自动配音、语音识别、智能抠图或实时控制时间线 |

直接创建仍拒绝含旋转元数据的视频。工作流若不能安全保留关键帧、动画、转场或音频淡入淡出的时间关系，会明确拒绝；基本拆分可保留线性关键帧。部分蒙版和资源组合仍需逐项验证，详见 [兼容性说明](docs/compatibility.md)。

原生兼容性取决于剪映版本和具体参数。新工程始终返回 `native_app_verified=false`：结构校验通过不能自动证明这个工程已经在剪映中正确显示或导出。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [工具参考](docs/tools.md) | 22 个工具、参数与示例 |
| [兼容性说明](docs/compatibility.md) | 平台、版本、能力状态和已知限制 |
| [性能说明](docs/performance.md) | batch、简要响应、缓存和局部性能基准 |
| [原生草稿结构](docs/native-schema.md) | 管理计划、原生文件和资源组织 |
| [排错指南](docs/troubleshooting.md) | 安装、连接、草稿与资源常见问题 |
| [川剧案例](docs/case-study.md) | 作品、原始素材重建方法与专项适配边界 |
| [第三方说明](THIRD_PARTY_NOTICES.md) | 结构参考、依赖与许可证说明 |

## 测试与验证

安装后运行：

```sh
.venv/bin/python -m pytest -q
```

**本机历史记录：v0.3.0 完整程序回归通过 375 项测试、60 个子测试**，另完成真实 stdio 调用与局部基准。这个数字不是当前 GitHub CI 状态，也不是所有 Mac 剪映版本的兼容保证；本次公开说明不宣称新增功能已完成新一轮原生导出验收。历史原生应用证据与程序测试分开记录。

## 贡献与许可

欢迎提交 [Issue](https://github.com/mjz925804554-jpg/jianying-local-mcp/issues) 或 [Pull Request](https://github.com/mjz925804554-jpg/jianying-local-mcp/pulls)。兼容问题请提供 macOS、Python、剪映版本、最小合成复现步骤、工具参数和脱敏错误输出。修改编辑逻辑时，请补充能验证时间范围、源素材保留及失败不落盘的针对性测试；原生结果请区分“结构校验”“应用预览”和“实际导出”。

请勿在公开 Issue 或测试夹具中附带私人素材、账户信息、机器标识或个人绝对路径。使用合成素材和脱敏最小工程即可。

项目代码采用 [MIT 许可证](LICENSE)；第三方版权及依赖说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。案例媒体的权利说明见 [案例页面](docs/case-study.md)，代码许可证不自动授予第三方素材权利。

文档组织参考了 [MCP Python SDK v1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) 的安装、最小示例与文档导航，以及 [capcut-cli](https://github.com/renezander030/capcut-cli) 对可编辑草稿、快速开始和版本边界的说明方式。它们的功能与兼容结论不等同于本项目的支持范围。

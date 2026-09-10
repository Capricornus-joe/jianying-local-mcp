# 快速开始

[返回首页](../README.md) · [工具参考](tools.md)


### 1. 安装

准备 **macOS、Python 3.11 或更新版本**。原生预览和导出还需要本机安装剪映。项目使用 MCP Python SDK **v1.x**，依赖范围为 `mcp>=1.28,<2`；安装脚本会按项目声明安装，不需要手动安装最新版 `mcp`。

从源码安装：

```sh
git clone https://github.com/Capricornus-joe/jianying-local-mcp.git
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

## 批量编辑

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

### 返回数据与素材缓存

- 返回剪辑计划的写入工具默认只给摘要；需要全量数据时传 `include_plan=true`。
- `read_managed_project` 默认 `view="summary"`。取得片段 ID 可用 `{"name":"hello-mcp-v2","view":"clips","offset":0,"limit":50,"track":"字幕"}`；每页最多 200 段。完整计划用 `view="full"`。
- 媒体探测缓存限于同一服务进程，最多 2,048 项、保留五分钟，并检查媒体文件与 FFmpeg 身份变化。相同素材的并发探测会合并；它缓存的是元数据，不是整段解码画面。
- 批处理的 `review_scope` 给出受影响片段、时间范围和音频检查提示，**不是原生画面通过证明**。

本机历史 stdio 小样中，同一组五步编辑由 **5 次调用、5 个新版本降为 1 次调用、1 个新版本**。该结果说明减少了重复保存，不代表整片剪辑、渲染或模型账单按相同比例下降。基准范围、数据与复现方法见 [性能说明](performance.md)。


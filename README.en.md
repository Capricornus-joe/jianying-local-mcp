# Jianying Local MCP

**Give AI edits a timeline you can keep working on.**

[中文完整文档](README.md)

[![Sichuan Opera showcase — watch the preview](docs/assets/showcase-poster.jpg)](docs/assets/showcase-preview.mp4)

**Showcase:《入戏·川剧初体验》** — 59.52 seconds, 1080p, 25 fps; 23 scenes, six main timeline tracks, and 28 subtitle lines split into 36 editable text segments. Rebuilt from original media, with separate PNGs for calligraphy and native motion/crop parameters. This case used additional project-specific adapters outside the package: it is **not a one-click result of the generic MCP**, nor a pixel-identical reconstruction. Original footage is not included. [Watch the preview](docs/assets/showcase-preview.mp4) · [Read the case study](docs/case-study.md).

Version **0.3.0** exposes **22 tools** over local **stdio** for video, images, audio, editable subtitles, keyframes and selected native effects. The draft generator is independently implemented. It does not require a third-party Jianying draft library at runtime or upload media while processing it.

This is an unofficial, experimental Mac draft adapter, with no affiliation to Jianying, CapCut or ByteDance. **Reliable native auto-export, encrypted drafts and arbitrary existing-project editing are not supported.** Open and verify generated drafts in your installed Jianying version, then export there.

## Install

Requirements: **macOS and Python 3.11+**; Jianying for native preview/export. Dependencies pin the MCP Python SDK to **`mcp>=1.28,<2`**.

```sh
git clone https://github.com/mjz925804554-jpg/jianying-local-mcp.git
cd jianying-local-mcp
bash setup.sh
bash run.sh doctor
```

This installs from source into a local `.venv`; it does not assume a PyPI release. To select Python explicitly, use `JIANYING_SETUP_PYTHON=python3.11 bash setup.sh`.

## Connect a client

For clients using the `mcpServers` format, replace both paths with actual absolute paths:

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

Reload the client, call `check_environment`, then follow the [text-only first draft and five-step batch example](README.md#快速开始). The client normally starts the stdio process; there is no web interface.

## What v0.3.0 changes

- `batch_edit` applies 1–100 ordered steps in memory and creates one final revision, without intermediate project/media copies. It retains the source revision.
- Plan-returning write tools return compact summaries by default. Use `include_plan=true` for the full plan.
- `read_managed_project` defaults to a summary; `view="clips"` supports track filtering and pagination, and `view="full"` returns the complete plan.
- A bounded, five-minute in-process cache reuses unchanged media metadata and merges concurrent probes. It does not cache full decoded video.

The historical local stdio benchmark reduced five editing calls/revisions to one. This is a local editing benchmark, **not an end-to-end rendering speedup or a token-billing claim**. See [measurements and scope](docs/performance.md).

## Boundaries

Edits apply only to this MCP's managed plans and always use a new revision name. New revisions still copy referenced media into a self-contained package. Publishing creates a new native project and registers it on Jianying's home page; fully quit Jianying first. Publishing neither uploads nor renders the project. Native GUI edits do not sync back to managed plans.

Native effects require valid local caches; this server does not download effect packs. Media preprocessing creates new baked files. Unsupported effect/timing combinations fail explicitly. `review_scope` is a review hint, and `native_app_verified=false` remains the default for every newly generated draft.

## Documentation and tests

- [Complete Chinese README and all 22 tools](README.md)
- [Tool reference](docs/tools.md)
- [Compatibility and limitations](docs/compatibility.md)
- [Native draft structure](docs/native-schema.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Case study](docs/case-study.md)

```sh
.venv/bin/python -m pytest -q
```

Historical local v0.3.0 verification recorded **375 passing tests and 60 subtests**, plus real stdio checks. This is not a claim about current GitHub CI or all installed Jianying versions.

## Contributing and license

Use [Issues](https://github.com/mjz925804554-jpg/jianying-local-mcp/issues) and [Pull Requests](https://github.com/mjz925804554-jpg/jianying-local-mcp/pulls). Include version information, a minimal synthetic reproduction and sanitized logs. Keep private media, account details, device identifiers and personal paths out of public fixtures.

The code is [MIT-licensed](LICENSE); third-party copyrights and dependency notices remain in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). See the [case study](docs/case-study.md) for media rights; the code license does not grant rights to third-party footage. Documentation structure draws on the [MCP Python SDK v1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x) and [capcut-cli](https://github.com/renezander030/capcut-cli); their compatibility claims do not transfer to this project.

# AI video editing with Jianying

**Jianying Local MCP** is a local stdio server for video editing with Jianying on Mac. An AI client plans edits and calls its 22 tools; the MCP writes local drafts for preview and export in Jianying. [中文](README.md)

## Demo

[![《入戏·川剧初体验》](docs/assets/showcase-poster.jpg)](docs/assets/showcase-preview.mp4)

**《入戏·川剧初体验》**: 59.52 seconds, 1080p, 25 fps; 23 scenes and six main tracks. The linked preview is 720p. In my view, its finish is comparable to work produced after about a year of regular editing practice.

The demo's easing, compound scenes and visual calibration use project-specific adapters outside the package; the [case study](docs/case-study.md) documents these additions and the remaining differences from the reference.

## Features

### Native keyframes

Control position, scale, rotation and opacity with native keyframes. Nine linear motion presets cover common movements and fades; custom keyframe values are also supported.

![Native keyframes and transform controls](docs/assets/jianying-animation.png)

### Subtitle editing

Create native text clips or import SRT. Edit individual lines, apply size, colour and position across a track, and export text and timing to SRT. The demo contains 28 lines in 36 text clips. Calligraphy titles are separate PNGs, without editable letters.

![Native subtitle text and style controls](docs/assets/jianying-subtitles.png)

### Multitrack editing

Organize footage, images, text and audio on named tracks. Append, split and reorder clips, or ripple-delete a section. Each saved revision preserves the previous version.

![Scene layers in the Jianying timeline](docs/assets/jianying-layers.png)

### Batch editing

`batch_edit` validates 1–100 operations in memory, then saves one revision. Five edits require no intermediate projects or media copies. Version 0.3.0 adds compact responses and caches unchanged media metadata. See [performance measurements](docs/performance.md).

## Get started

Requirements: macOS, Python 3.11+, and Jianying.

```sh
git clone https://github.com/Capricornus-joe/jianying-local-mcp.git
cd jianying-local-mcp
bash setup.sh
bash run.sh doctor
```

See [Quick start](docs/quickstart.md) for client configuration and a first draft.

## Limitations

The Mac draft adapter is experimental and edits only its own managed plans. Changes made in Jianying do not sync back. Encrypted drafts, arbitrary existing-project editing and reliable native auto-export are unsupported. Generated drafts require review and manual export in Jianying. See [compatibility](docs/compatibility.md).

## Docs & Contributing

[Tools](docs/tools.md) · [Draft structure](docs/native-schema.md) · [Troubleshooting](docs/troubleshooting.md) · [Contributing](CONTRIBUTING.md)

Bug reports should include versions, synthetic media and sanitized logs.

## License

[MIT](LICENSE). [Third-party notices](THIRD_PARTY_NOTICES.md) and [case media rights](docs/case-study.md) apply separately. Independent project; no affiliation with Jianying, CapCut or ByteDance.

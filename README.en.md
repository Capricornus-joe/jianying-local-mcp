# AI video editing with Jianying

**Jianying Local MCP** lets an AI client automate video edits using your local media on Mac. The AI plans the edit and calls tools; the MCP creates or updates a local Jianying draft. You review and export the result in Jianying. [中文](README.md)

[![《入戏·川剧初体验》 — watch the film](docs/assets/showcase-poster.jpg)](docs/assets/showcase-preview.mp4)

[▶ Watch the film (720p preview; 1080p master)](docs/assets/showcase-preview.mp4) · [How it was made](docs/case-study.md) · [Quick start](docs/quickstart.md)

I built this while making **《入戏·川剧初体验》**, a short film about a first encounter with Sichuan opera. It brings theatre, face-changing, fire-breathing and a costume fitting into 59.52 seconds at 1080p, 25 fps. To my eye, it has the finish I'd expect after a year of serious editing practice. The result is a Jianying project I can open to change a line, replace a shot or adjust the movement.

## Animation

Let a photo slide into place, slowly push in, or fade away. The movement is written as native keyframes, so you can change its timing and values in Jianying. The MCP provides nine linear motion presets and accepts custom keyframes for position, scale, rotation and opacity.

For this film, a separate script sampled smoothstep easing at 25 fps and wrote those values into native keyframes, alongside crop and transform settings. That is how the layered photos ease into place.

![Photo animation and native keyframe controls in Jianying](docs/assets/jianying-animation.png)

## Editable subtitles

Import an SRT file or create text clips directly. Correct one sentence, change its timing, or apply a font size, colour and position across a subtitle track. You can export the text and timing back to SRT.

The film has **28 subtitle lines in 36 native text clips**. The calligraphy titles are separate PNG layers: you can move, resize or replace them, but their individual letters are not editable text.

![A subtitle selected with its text and style controls visible](docs/assets/jianying-subtitles.png)

## Organized timeline

Keep footage, titles, decorations and sound on named tracks. Add a shot, split a clip, reorder a sequence, or remove a section and close the gap. Each saved revision keeps the previous one available.

In the showcase, a project-specific adapter groups the photo, paper border, shadow and lettering layers into **23 scene compound clips within a six-track main timeline**. Open a scene to adjust its individual layers. The MCP itself supports layered tracks; scene grouping is part of the case adapter.

![The showcase timeline with its separate scene layers](docs/assets/jianying-layers.png)

## Batch edits

Change the text, make it bold, adjust the size, add an outline and give it a fade-in—all in one `batch_edit` call. Each step is checked in memory; once all five pass, the tool saves one new revision. The source revision stays in place, with no intermediate media copies to clean up.

Version **0.3.0** also returns compact results by default and reuses metadata for unchanged media. These changes cut repeated calls, probing and disk writes. The [performance notes](docs/performance.md) explain what was measured.

## Get started

You need **macOS and Python 3.11+**, with Jianying installed to preview and export drafts.

```sh
git clone https://github.com/Capricornus-joe/jianying-local-mcp.git
cd jianying-local-mcp
bash setup.sh
bash run.sh doctor
```

Follow the [quick start](docs/quickstart.md) to connect your MCP client and make a small text-only draft before adding your own footage. The server runs locally over stdio and exposes **22 tools**.

## Current scope

This is an experimental Mac draft adapter. It edits its own managed plans; it does not read encrypted drafts, rewrite arbitrary existing projects, or reliably automate native export. Open each generated draft in your installed Jianying version, check it and export there. The showcase also used scripts outside the package for scene grouping and visual calibration, so it is not a one-click result of the general MCP or a pixel-identical reconstruction. Original footage is not included. See [compatibility](docs/compatibility.md) and the [case study](docs/case-study.md) for details.

## Docs and contributions

[Tools](docs/tools.md) · [Compatibility](docs/compatibility.md) · [Performance](docs/performance.md) · [Draft structure](docs/native-schema.md) · [Troubleshooting](docs/troubleshooting.md)

Have a clip you want to make, or a Jianying version to test? Open an [issue](https://github.com/Capricornus-joe/jianying-local-mcp/issues) or see [Contributing](CONTRIBUTING.md). Please use synthetic media for reproductions and remove private paths and account details from logs.

The code is [MIT-licensed](LICENSE). [Third-party notices](THIRD_PARTY_NOTICES.md) and [case media rights](docs/case-study.md) still apply. This is an independent project, unaffiliated with Jianying, CapCut or ByteDance.

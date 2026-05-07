# Install And Sync

This repository depends on the StreamVox runtime dependency stack and expects the private/local `streamvox` SDK wheel to remain installed in `.venv`.

## Recommended Local Setup

Create or activate the project environment:

```bash
source .venv/bin/activate
```

Install or update declared dependencies without removing the already installed private StreamVox SDK:

```bash
uv sync --inexact
```

If the private StreamVox SDK wheel is not installed yet, install the matching wheel after dependency sync:

```bash
uv pip install /path/to/streamvox-*.whl
```

Then verify imports:

```bash
.venv/bin/python -c "import streamvox, streamvox_agent_voice; print(streamvox.__file__); print(streamvox_agent_voice.__file__)"
```

## Why `--inexact`

`uv sync` in exact mode may remove packages that are installed in `.venv` but not represented as public dependencies in this repository. Use `uv sync --inexact` when you need to preserve a locally installed private StreamVox wheel.

## Server Smoke Test

Use `null` output on servers without an audio device:

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
streamvox-say --event progress "我正在读取文件"
streamvox-runtime status
streamvox-runtime stop
```

Use `wav` output when you need a file artifact:

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output wav --output-dir streamvox_outputs
streamvox-say --event done --wait "处理完成"
ls streamvox_outputs
streamvox-runtime stop
```

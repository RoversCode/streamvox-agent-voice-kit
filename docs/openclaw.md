# OpenClaw Adapter

OpenClaw only needs to learn one thing for the MVP:

When progress, result, error, or reminder text should be spoken, call `streamvox-say`.

Examples:

```bash
streamvox-say --event progress "我正在读取文件"
streamvox-say --event done "处理完成"
streamvox-say --event error "执行失败，需要检查日志"
streamvox-say --interrupt "等等，我发现了新的问题"
```

`error` is still FIFO unless you explicitly use `--interrupt` or `--interrupt-current`.

The skill does not load models, synthesize wav files, or manage audio devices. The local `streamvox-runtime` process owns those responsibilities.

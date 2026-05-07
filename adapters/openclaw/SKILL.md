# StreamVox Agent Voice Skill

Use this skill when you need to speak progress updates, errors, final results, or urgent reminders through the local StreamVox Runtime.

## Rule

Call `streamvox-say` when speech helps the user understand what is happening.

## Commands

```bash
streamvox-say --event progress "我正在读取文件"
streamvox-say --event done "处理完成"
streamvox-say --event error "执行失败，需要检查日志"
streamvox-say --interrupt "等等，我发现了新的问题"
streamvox-say --stop
```

`event` 只是语义标签。`error` 不会自动打断。只有 `--interrupt`、`--interrupt-current` 或 `--stop` 是控制行为。

## Boundaries

- Do not load StreamVox models.
- Do not synthesize wav files directly.
- Do not manage speakers or audio devices.
- Do not use this for every tiny internal step; speak only useful progress, failures, and final outcomes.

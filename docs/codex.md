# Codex Adapter

The MVP integration path for Codex is shell-based:

```bash
streamvox-say --event started "我开始处理这个任务"
streamvox-say --event progress "我正在运行测试"
streamvox-say --event done "任务完成"
streamvox-say --event error "测试失败，需要查看日志"
```

Future Codex hook integrations can map lifecycle events to this same CLI. The Voice Kit does not parse Codex internals in V0.1/V0.2.

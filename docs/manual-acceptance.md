# Manual Runtime Acceptance Record

Use this template when running the real StreamVox model, because automated tests use fake TTS and do not load large model assets.

## Environment

- Date:
- Machine:
- OS:
- Python:
- StreamVox SDK wheel:
- Model:
- Device:
- Output sink: `speaker` / `null` / `wav`
- Output dir, if `wav`:
- Has audio device: yes / no

## Commands

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
streamvox-say --event started "我开始处理任务"
streamvox-say --event progress --action replace_pending "我正在读取文件"
streamvox-say --event done --wait "处理完成"
streamvox-runtime status
streamvox-runtime stop
```

## Observations

- Runtime loaded model once: yes / no
- `streamvox-say` returned quickly with `wait=false`: yes / no
- FIFO worked for normal events: yes / no
- `--interrupt` stopped current output and cleared pending events: yes / no
- `--stop` stopped output without shutting down Runtime: yes / no
- `streamvox-runtime stop` shut down process: yes / no
- First audible chunk latency, if measured:
- Notes:

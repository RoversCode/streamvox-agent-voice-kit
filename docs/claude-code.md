# Claude Code SDK Adapter

The Voice Kit is the speech output layer for a Claude Code SDK based shell. The SDK remains responsible for thinking, tool use, permissions, and working directory selection.

Example:

```python
from streamvox_agent_voice import VoiceClient

voice = VoiceClient()

await voice.say("我正在交给 Claude Code 处理", event="started")
await voice.say("我正在整理中间结果", event="progress")
await voice.done("处理完成")
```

Keep the boundary clear:

- Claude Code SDK decides what to do.
- Jarvis Voice Shell decides when to call the SDK.
- StreamVox Runtime decides how to speak.

# Qwen3 TTS Clone

这份文档只讨论一件事：在“私人智能助手”场景下，Agent 应该怎样理解 `qwen3-tts-clone-0.6b-gguf` 和 `qwen3-tts-clone-1.7b-gguf`。

## 先说结论

对 Agent Voice 来说，Qwen3 不是第一优先模型。

优先级应该是：

1. 先判断当前机器的显存和内存是否满足模型要求。
2. 再判断当前机器的推理效率是否足够做实时语音生成。
3. 如果满足，优先选更有副语言控制和更强拟人表达能力的：
   - `s2-pro-4b-gguf`
   - `voxcpm2-gguf`
4. 只有在上面两者不适合，或者硬件不够时，再退到 Qwen3：
   - `qwen3-tts-clone-1.7b-gguf`
   - `qwen3-tts-clone-0.6b-gguf`

Qwen3 的价值是稳、轻、简单，不是情感和拟人性最强。

## 0.6B 和 1.7B 的真实区别

在 Agent Voice 里，这两个模型的核心调用思路没有本质区别。

唯一值得 Agent 关心的差别就是：

- `qwen3-tts-clone-1.7b-gguf`
  - 参数量更大，效果通常更好一些
- `qwen3-tts-clone-0.6b-gguf`
  - 参数量更小，更省资源，更容易跑实时

所以如果硬件能扛住，优先 `1.7B`；如果硬件紧张，再退到 `0.6B`。

## Agent 真正需要关注的参数

只需要关注：

- `language`
- `stream`
- `icl`

不需要关注：

- `max_length`
- `min_length`

这些内部已经有合适默认值，Agent 不必参与。

## 参数使用建议

### `language`

这是 Qwen3 最值得 Agent 关注的参数。

建议：

- 目标文本语言明确时，显式传 `language`
- 不要在正式生成里默认依赖 `auto`

示例：

```bash
streamvox-say --role-name assistant_voice --streamvox-json '{"language":"Chinese"}' "今天下午三点我会提醒你开会。"
```

### `stream`

一般开 `stream=True` 就够用了。

对于私人智能助手，实时反馈通常比整段离线生成更重要。

### `icl`

`icl=True` 时，音色相似度会尽量最大化。

但在 Agent Voice 场景里，一般 `stream=True` 就已经足够，`icl` 不需要被 Agent 频繁拿来调。

## 文本写法建议

- 直接写干净、自然、口语化的目标语言正文
- 不要堆复杂风格提示
- 如果只是日常助手对话，短句和中短句通常最稳
- Qwen3 的优势不是“演”，而是“稳稳地说出来”

## 什么时候退回 Qwen3

以下情况可以优先考虑 Qwen3：

- 机器跑不动 `s2-pro` 或 `voxcpm2`
- 需要更稳的实时响应
- 任务重心是“清晰、稳定、低延迟”，而不是强情感表达

## 已知约束

- 当前 Runtime 只公开单参考角色工作流
- `control_text` 不是 Qwen3 工作流的一部分
- 它不是当前项目里拟人化最强的模型路线

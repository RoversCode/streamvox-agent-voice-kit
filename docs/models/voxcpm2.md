# VoxCPM2

这份文档从“私人智能助手”场景出发解释 `voxcpm2-gguf`。

## 先说结论

如果硬件满足，`voxcpm2-gguf` 也是 Agent Voice 的第一优先梯队。

原因是它同时具备：

- 更强的副语言能力
- 更适合做轻量风格控制
- 更适合在参考音色基础上追求更拟人的表达

它和 `s2-pro-4b-gguf` 一样，应该先于 Qwen3 被考虑。

## Agent 先判断什么

和其他模型一样，先判断两件事：

1. 显存和内存是否满足
2. 推理效率是否足够支撑实时语音生成

满足以后，再在 `s2-pro-4b-gguf` 和 `voxcpm2-gguf` 之间选择。

## Agent 真正需要关注的参数

只需要关注：

- `mode`

不需要把下面这些当成 Agent 的主控制面：

- `max_length`
- `min_length`

它们在这里都不是重点。

## 四种模式该怎么选

### `mode=ref`

这是私人智能助手里最常用的模式。

特点：

- 有 `control_text` 能力
- 可以在参考音色基础上做轻量风格控制
- 更适合日常助手播报

如果你选择 `mode=ref`，Agent 需要知道：

- `control_text` 要尽量简单
- 写太复杂，前后音色更容易漂
- 推理时应该固定 `seed`，尽量不要让内部随机，避免同一角色声音飘动

### `mode=continuation`

没有 `control_text` 能力，但仍然有副语言能力。

适合：

- 不追求最高音色相似度
- 更看重沿当前上下文自然地接着说下去

### `mode=ref_continuation`

同样没有 `control_text` 能力，但有副语言能力。

适合：

- 追求最高音色相似度
- 同时又要延续已有上下文

如果目标是“相似度尽量最高”，优先 `ref_continuation`；否则优先 `continuation`。

### `mode=text`

在 Agent Voice 里几乎不用。

这个项目主路径是私人智能助手，不是纯文本重新设计一个声音人格。

## `mode=ref` 下怎样用 `control_text`

### 原则一：尽量简单

不要写成长篇人物设定。

更推荐：

```text
四川话
```

```text
Cantonese
```

```text
更温柔一点
```

不推荐：

```text
三十岁左右、低沉、有故事感、略带沙哑、情绪轻松但不夸张、像老朋友聊天一样自然并带一点点懒散感
```

描述一复杂，前后音色更容易发生变化。

### 原则二：方言尽量让正文自己说方言

如果要方言效果更自然，正文最好直接写成方言常见说法，而不是只写一个方言名。

例如：

- 粤语
  - `伙计，唔该一个A餐，冻奶茶少甜！`
- 四川话
  - `幺儿，哈戳戳得你屋头来噶！`
- 东北话
  - `你搁这整啥玩意儿呢？`
- 河南话
  - `恁这是弄啥嘞？晌午吃啥饭？`

如果不会写方言，先用文本助手把普通话改写成更地道的版本，再送给 TTS。

## 副语言标签怎么用

对私人智能助手来说，副语言标签很有价值，因为它们能明显减少“机械播报感”。

推荐优先使用英文方括号标签：

- 笑与叹息：
  - `[laughing]`
  - `[sigh]`
- 停顿与思考：
  - `[Uhm]`
  - `[Shh]`
- 疑问语气：
  - `[Question-ah]`
  - `[Question-ei]`
  - `[Question-en]`
  - `[Question-oh]`
- 情绪：
  - `[Surprise-wa]`
  - `[Surprise-yo]`
  - `[Dissatisfaction-hnn]`

使用建议：

- 尽量只用推荐标签
- 数量一定要少
- 一句话里不要叠太多标签
- `[laughing]` 这类常见全小写形式通常更稳

## Agent 最该关注的其实不是参数，而是推理文本

对 `continuation` 和 `ref_continuation` 来说，没有 `control_text`，所以 Agent 的重点会进一步转移到：

- 这句话本身怎么写最像真人
- 要不要加副语言标签
- 加什么标签最合适
- 是不是应该追求更高相似度

简化成一句话：

- 追求最高音色相似度：
  - `ref_continuation`
- 更偏自然续说，不强求最高相似度：
  - `continuation`

## 推荐示例

### `mode=ref`

```json
{
  "mode": "ref",
  "control_text": "四川话",
  "seed": 42
}
```

```bash
streamvox-say --role-name assistant_voice --streamvox-json-file ./voxcpm2-ref.json "你先别急，我把最关键的点慢慢跟你讲。[Uhm] 这次确实有个地方需要你注意。"
```

### `mode=continuation`

```json
{
  "mode": "continuation",
  "seed": 42
}
```

### `mode=ref_continuation`

```json
{
  "mode": "ref_continuation",
  "seed": 42
}
```

## 已知约束

- `ref` / `continuation` / `ref_continuation` 必须命中持久化 `role_name`
- `ref` 才有 `control_text` 能力
- `continuation` 和 `ref_continuation` 没有 `control_text`，但仍然有副语言能力
- `text` 在 Agent Voice 主场景里几乎不用

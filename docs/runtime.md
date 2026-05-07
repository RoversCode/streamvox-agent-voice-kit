# Runtime

`streamvox-runtime` is the long-running local process that owns StreamVox model loading, event queueing, synthesis, and playback.

## Start

Desktop or machine with a local speaker:

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output speaker
```

Server or CLI-only machine without an audio device:

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output null
```

Save each request as a wav file:

```bash
streamvox-runtime start --model voxcpm2-gguf --device auto --output wav --output-dir streamvox_outputs
```

Useful options:

- `--model`: StreamVox model name or local bundle path.
- `--device`: `auto`, `cpu`, `gpu`, or `gpu:<index>`.
- `--license-key`: online StreamVox license key.
- `--license-path`: offline license path.
- `--verify-model-sha256`: enable bundle integrity verification.
- `--control-text`: default VoxCPM2 voice design text. This is only a lightweight text hint, not a persisted StreamVox prompt/role asset.
- `--default-role-name`: validate and preload a cached role as the Runtime default voice role.
- `--output` / `--audio-backend`: `speaker` for local speaker playback, `null` for server-side protocol verification, `wav` for saving requests as files. `sounddevice` is accepted as a compatibility alias for `speaker`.
- `--output-dir`: directory used by file output sinks such as `wav`.

## Voice Role Status

The underlying StreamVox SDK commonly uses a two-step flow:

1. Build or persist prompt assets with `TTSEngine.make_prompt(...)`.
2. Synthesize with `TTSEngine.stream(..., role_name=...)`.

The current Agent Voice Runtime now exposes the core persisted-role workflow:

- Register a role through `TTSEngine.make_prompt(...)`.
- List cached roles for the current model.
- Delete cached roles for the current model.
- Set or clear the Runtime default role.
- Override the default role per event through event metadata.

Current implementation notes:

- Runtime now exposes both JSON registration and multipart file upload for persisted roles.
- If `prompt_text` is omitted during role registration, Runtime automatically transcribes the single reference audio with the built-in SenseVoice ONNX helper.
- Single-reference role assets are capped at 30 seconds across `audio_path`, upload, and `audio_data` inputs.
- Agent Voice Runtime intentionally keeps the public role workflow single-reference-only even when the underlying SDK supports multi-reference prompt assets.
- The validated model-specific parameter set now also includes `stream`, `icl`, `max_length`, `min_length`, and `remove_meaningless_chars`.

## Role Management

List cached roles in the current model scope:

```bash
streamvox-runtime roles list
```

Register a persisted role from one reference audio file:

```bash
streamvox-runtime roles register assistant_voice \
  --audio-file reference.wav \
  --set-default
```

Register a persisted role from one Runtime-local reference audio path:

```bash
streamvox-runtime roles register assistant_voice \
  --audio-path reference.wav \
  --prompt-text "这是参考音频对应的转写文本。" \
  --set-default
```

Register a persisted role from in-memory audio samples:

```bash
streamvox-runtime roles register memory_voice \
  --audio-data-file samples.json \
  --sample-rate 24000
```

Switch or clear the Runtime default role:

```bash
streamvox-runtime roles set-default assistant_voice
streamvox-runtime roles clear-default
```

Delete cached roles:

```bash
streamvox-runtime roles delete assistant_voice
```

Current role-management constraints:

- Cached roles are scoped by model because StreamVox itself isolates prompt caches per model.
- Runtime role registration currently requires `persist=True`.
- Runtime intentionally exposes only persisted roles and `role_name`; transient prompt objects are out of scope.
- Runtime intentionally keeps its public role-registration contract single-reference-only.
- In-memory audio registration currently accepts only a single one-dimensional sample array plus `sample_rate`.
- Reference audio is limited to 30 seconds for upload, path-based registration, and in-memory audio registration.
- Missing `prompt_text` triggers an internal one-shot ASR pass during role registration.
- Internal ASR weights default to `~/.cache/streamvox-agent-voice-kit/sensevoice_onnx`. Override the directory with `STREAMVOX_ASR_MODEL_DIR` and the provider with `STREAMVOX_ASR_PROVIDER`.
- If `--default-role-name` points to a missing cached role, Runtime startup fails early.

Per-model prompt notes:

- `qwen3-tts-clone-0.6b-gguf` and `qwen3-tts-clone-1.7b-gguf` are single-reference role workflows today. They accept one file reference or one in-memory audio array, and synthesis commonly benefits from an explicit `language` value. Runtime also validates `stream`, `icl`, `max_length`, `min_length`, and `remove_meaningless_chars`.
- `s2-pro-4b-gguf` supports multi-reference prompt assets in the underlying SDK, but Agent Voice Runtime currently exposes only a single-reference persisted-role workflow. Runtime validates `temperature`, `top_p`, `top_k`, `speaker`, `max_length`, `min_length`, and `remove_meaningless_chars`.
- `voxcpm2-gguf` currently uses a single-reference role workflow in Runtime role registration. Its `control_text` behavior is model-specific and is only auto-applied in `text` / `ref` modes, not in continuation modes. `ref`, `continuation`, and `ref_continuation` require a persisted `role_name`.

Per-event override examples:

```bash
streamvox-say --role-name assistant_voice "Use a one-off role override"
streamvox-say --streamvox-json '{"language":"zh"}' "Pass model-specific synthesis options"
```

Validation notes:

- Runtime now validates the currently documented model-specific keys before enqueueing a request.
- The current validated set includes `language`, `stream`, `icl`, `max_length`, `min_length`, `remove_meaningless_chars`, `mode`, `control_text`, `temperature`, `top_p`, `top_k`, and `speaker`.
- Unsupported keys for a known model are rejected early with `400`, and an explicit event-level `role_name` must already exist in the current model cache.
- For VoxCPM2, `ref`, `continuation`, and `ref_continuation` are also rejected early when no persisted `role_name` is available in the current session.
- Unknown extra SDK kwargs that are not yet modeled in the registry are still passed through as-is.

## Status

```bash
streamvox-runtime status
```

This calls `GET /status` and returns model, device, sample rate, initialization state, and queue status.

To inspect the current model capability snapshot:

```bash
streamvox-runtime capabilities
```

To inspect built-in model profiles before startup:

```bash
streamvox-runtime models list
streamvox-runtime models inspect voxcpm2-gguf
streamvox-runtime models recommend
streamvox-runtime doctor --model voxcpm2-gguf
```

The HTTP Runtime also exposes:

- `GET /capabilities`
- `GET /roles`
- `POST /roles`
- `POST /roles/upload`
- `POST /roles/delete`
- `POST /session/default-role`

## Stop Runtime Process

```bash
streamvox-runtime stop
```

This calls `POST /shutdown`. It is different from `streamvox-say --stop`, which only stops current playback.

## Output Sink

The Runtime streams TTS chunks into an output sink. The sink does not have to be a local speaker.

- `speaker`: consumes StreamVox `numpy.float32` chunks and writes them to the default system output device through `sounddevice`.
- `null`: consumes chunks without playing audio. Use this on servers without a desktop audio device.
- `wav`: consumes chunks and writes one wav file per request to `--output-dir`.

Interrupt and stop are chunk-boundary cancellations. If `TTSEngine.stream(...)` is already computing the current chunk, the Runtime stops at the next yielded chunk boundary rather than forcibly killing model internals.

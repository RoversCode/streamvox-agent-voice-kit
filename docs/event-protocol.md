# Event Protocol

The runtime accepts one JSON object per speech event.

```json
{
  "event": "progress",
  "text": "我正在读取文件",
  "priority": "normal",
  "action": "enqueue",
  "interrupt": false,
  "wait": false,
  "metadata": {}
}
```

## Fields

- `event`: one of `started`, `progress`, `done`, `error`, `interrupt`, `stop`.
- `text`: text to speak. It can be empty only when `event` is `stop`.
- `priority`: one of `low`, `normal`, `high`.
- `action`: queue control action. Supported values are `enqueue`, `interrupt`, `stop`, `replace_pending`, and `clear_pending_then_enqueue`.
- `interrupt`: when true, request the runtime to stop current output and clear the whole pending queue before speaking this event.
- `wait`: when true, the HTTP request waits until the event finishes, stops, or fails.
- `metadata`: optional object for model hints such as `language`, `mode`, `control_text`, `track_performance`, and future prompt-role fields such as `role_name` or `prompt_ref`.

## Semantics

- `event` is a semantic label for logs, humans, and future UI. It does not imply queue control.
- Normal events, including `progress`, `done`, and `error`, are played FIFO.
- `error` does not automatically interrupt. Set `interrupt=true` when interruption is intended.
- `action=interrupt` stops the current output, stops consuming the current `TTSEngine.stream(...)` at the next chunk boundary, clears the pending queue, and inserts the current event at the front.
- `interrupt=true` is kept as a compatibility shortcut for `action=interrupt`.
- `action=replace_pending` does not interrupt current output; it replaces pending events with the same `event` value.
- `action=clear_pending_then_enqueue` does not interrupt current output; it clears all pending events and enqueues the current event.
- `action=stop` stops current output, clears pending events, and does not speak new text.
- `/stop` stops current output, stops consuming the current stream at the next chunk boundary, and clears the pending queue without shutting down the runtime.
- `/shutdown` stops playback, releases StreamVox, and exits the runtime process.

## Current Metadata Support

The current Runtime actively uses only a small subset of metadata:

- `mode`
- `control_text`
- `language`
- `track_performance`

Fields such as `role_name` or `prompt_ref` are part of the planned protocol direction, because the underlying StreamVox SDK supports prompt creation plus `role_name`-based synthesis, but the Agent Voice Runtime has not exposed a full prompt-role lifecycle yet.

## Responses

Accepted without waiting:

```json
{
  "status": "accepted",
  "event_id": "..."
}
```

Completed with `wait=true`:

```json
{
  "status": "completed",
  "event_id": "...",
  "detail": ""
}
```

Possible final statuses are `completed`, `stopped`, `skipped`, and `failed`.

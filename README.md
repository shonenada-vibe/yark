# yark

macOS voice-to-text input. Hold a hotkey, speak, and yark types the transcript into the focused app.

First version talks to [Volcengine bidirectional streaming ASR](https://docs.volcengine.com/docs/6561/2630027) (`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`, Seed-ASR 2.0).

## What it does

1. Captures 16 kHz / 16-bit / mono PCM from the microphone.
2. Streams 200 ms packets over WebSocket to Volcengine (gzip + SAUC binary protocol).
3. Commits each definite utterance as it arrives and inserts it at the caret.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
yark init-config
```

Put your Volcengine API key in `~/.config/yark/config.toml`:

```toml
[volcengine]
api_key = "your-api-key"
resource_id = "volc.seedasr.sauc.duration"
endpoint = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
```

Create the key in [API Key 管理](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default). Enable **豆包流式语音识别模型 2.0**. `resource_id` should match the product you opened (`volc.seedasr.sauc.duration` for the hourly plan).

Legacy console auth still works: set `app_key` + `access_key` instead of `api_key`.

macOS permissions (both are required for typing):

- **Microphone** — System Settings → Privacy & Security → Microphone → enable your terminal / Python.
- **Accessibility** — same pane → Accessibility. Needed for the global hotkey and for inserting text.

```bash
yark doctor
yark listen
```

`yark listen` puts a mic icon in the macOS menu bar. Hold **Right Option** (default) to dictate, release to stop. Click the icon → **Settings…** to change the shortcut (dropdown or press a key). Quit from the menu, or Ctrl+C.

## Commands

```bash
yark listen                 # menu bar + hold-to-talk
yark listen --print         # same, but print instead of typing
yark listen --hotkey f8
yark once --print           # record until Enter
yark doctor
yark init-config
```

The menu bar extra shows Ready vs Listening. **Settings…** (or ⌘,) opens a panel to pick or record the hold-to-talk key; the choice is written to `config.toml`.

Environment overrides: `YARK_VOLC_API_KEY`, `YARK_VOLC_RESOURCE_ID`, `YARK_VOLC_ENDPOINT`, `YARK_HOTKEY`, `YARK_INJECT`.

## Inject modes

| `input.inject` | Behavior |
| --- | --- |
| `unicode` (default) | Unicode key events, live, Chinese-safe |
| `paste` | Clipboard + Cmd+V per committed phrase |
| `print` | stdout only |

## Protocol notes

Endpoint, headers, and framing follow the official SAUC demo for doc 2630027:

- Headers: `X-Api-Key` (or `X-Api-App-Key` + `X-Api-Access-Key`), `X-Api-Resource-Id`, `X-Api-Request-Id`
- First packet: gzip JSON full client request (`model_name=bigmodel`, PCM 16 kHz)
- Following packets: gzip PCM audio-only requests, 200 ms each
- Last packet: negative sequence
- Results: `result.utterances[].definite` marks a sentence that will not change

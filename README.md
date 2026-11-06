# yark

Voice-to-text input for macOS and Windows (via WSL). Hold a hotkey, speak, and yark types the transcript into the focused app.

First version talks to [Volcengine bidirectional streaming ASR](https://docs.volcengine.com/docs/6561/2630027) (`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`, Seed-ASR 2.0).

## What it does

1. Captures 16 kHz / 16-bit / mono PCM from the microphone.
2. Streams 200 ms packets over WebSocket to Volcengine (gzip + SAUC binary protocol).
3. Optionally refines and/or translates the transcript via an OpenAI-compatible Chat Completions API.
4. Inserts the result at the caret.

## Setup

```bash
uv sync --extra dev
uv run yark init-config
```

`uv sync` installs `yark` into `.venv`, not onto your PATH. Use `uv run yark …`, or `source .venv/bin/activate` and then `yark`. `just listen` / `just wsl` already wrap `uv run`.

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
uv run yark doctor
uv run yark listen
```

`yark listen` puts a mic icon in the macOS menu bar. Three hold-to-talk shortcuts (Settings → Shortcut):

1. **Transcript** — type STT as-is  
2. **Translate** — STT, then translate  
3. **Translate + Refine** — STT, translate, then refine  

Click the icon → **Settings…** → **Record** next to each level. Quit from the menu, or Ctrl+C.

## Windows (WSL)

Run yark **inside WSL**. A PowerShell helper on the Windows side watches the hotkeys and pastes into the focused Windows app.

```bash
uv run yark wsl
# or, from WSL / native Windows:
uv run yark listen
```

Same `~/.config/yark/config.toml` as macOS. Key names map as:

| config | Windows |
| --- | --- |
| `option` / `right_option` | Alt / Right Alt |
| `command` | Win |
| `control` | Ctrl |

Default typing is clipboard + Ctrl+V (Chinese-safe). `unicode` is treated as paste. Microphone uses WSL PulseAudio/WSLg when available; otherwise the Windows default recording device (`audio.device = "windows"` forces that). Allow microphone access for desktop apps in Windows Settings.

```bash
uv run yark wsl --doctor
uv run yark wsl --hotkey f8
```

## Commands

```bash
uv run yark listen                 # macOS menu bar, or WSL/Windows hold-to-talk
uv run yark listen --print         # same, but print instead of typing
uv run yark listen --hotkey f8
uv run yark wsl                    # Windows hold-to-talk from WSL
uv run yark wsl --doctor
uv run yark once --print           # record until Enter
uv run yark doctor
uv run yark doctor --test-mic       # briefly test capture locally; audio is discarded
uv run yark init-config
```

If microphone capture fails, run `uv run yark doctor --test-mic` from the same
terminal or app that launches yark. This tests your configured device without
contacting the speech service or requiring an API key. PortAudio's `-9986`
(`Internal PortAudio error`) alone does not identify a permission problem.
Check the launching app's Microphone permission on macOS and the input device
shown by doctor. To select another input, set `device = "device name"` (or its
listed index as a string) in the `[audio]` section of your config. Restart yark
after changing audio devices or permissions.

The menu bar extra shows Ready vs Listening. **Settings…** (or ⌘,) has three tabs:

- **Shortcut** — record three hold-to-talk chords (transcript / translate / translate+refine)
- **Refine** — enable, API key, prompt (clean up ASR text before typing)
- **Translate** — enable, API key, prompt (run after refine)

Shared **Base URL**, **Model**, and fallback **API key** sit above the tabs. Any OpenAI-compatible `/v1/chat/completions` endpoint works. When either feature is on, yark waits until you release the hotkey, then post-processes the full transcript and types once.

Environment overrides: `YARK_VOLC_API_KEY`, `YARK_VOLC_RESOURCE_ID`, `YARK_VOLC_ENDPOINT`, `YARK_HOTKEY`, `YARK_INJECT`, `YARK_LLM_API_KEY`, `YARK_LLM_BASE_URL`, `YARK_LLM_MODEL`.

HTTP(S) proxy: set `HTTPS_PROXY` (or `https_proxy` / `ALL_PROXY` / `HTTP_PROXY`). `NO_PROXY` / `no_proxy` bypasses listed hosts. Used for Volcengine WebSocket STT and the OpenAI-compatible LLM calls.

LLM requests send a browser-like `User-Agent` so hosts behind Cloudflare (for example Groq) do not return error 1010. Override with `YARK_LLM_USER_AGENT` if needed.

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

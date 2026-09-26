# I Learning Bilibili Emoji Bot · ILBB

[中文](README.md) ｜ **English**

> **Current version: v0.1.0-beta** ｜ Release branch: `beta` ｜ Beta stage: features and interfaces may still change.

A **self-hosted** QQ sticker generator bot plus a web workbench. Hook it up to NapCat (OneBot V11) and your group chats can generate memes with a single message — while the web UI gives you a pairing-card generator, quote-image composer, asset browser, API debugger and a plugin system.

No third-party cloud service required. Everything runs on your own machine.

---

## Table of Contents

- [Features](#features)
- [Pages](#pages)
- [Quick Start](#quick-start)
- [Command Cheatsheet](#command-cheatsheet)
- [Configuration & Integration](#configuration--integration)
- [Plugin System](#plugin-system)
- [Three Deployment Targets](#three-deployment-targets)
- [Project Layout](#project-layout)
- [Documentation Index](#documentation-index)
- [FAQ](#faq)
- [Credits & License](#credits--license)

---

## Features

| Module | Description |
| --- | --- |
| Meme generation `/meme` | 282 memes, 3,400+ asset files. Send a command plus text (optionally with an image, an `@mention` or a QQ number) and get a sticker back. Supports per-meme preset arguments |
| Pairing card `/pair` | QQ-style pairing cards with three templates (classic / dark / paper); custom title, background and button labels |
| Quote image `/quote` | Landscape 16:9: rounded square avatar in the left half, frosted-glass bubble in the right half (animated stickers supported), random anime background with a grey mask, and a signature at the bottom right; JPG for static content, GIF when animated, fonts switchable |
| Image menu `/help` | Every command rendered as a clean, phone-friendly image |
| Web workbench | Pairing-card generator, meme preview and debugging, command dry-run preview, web chat session (try commands without QQ) |
| Integration panel | Start/stop the OneBot V11 reverse-WS server, edit its config, watch a live event stream with raw JSON, and use a debug panel for 30+ OneBot APIs |
| Plugin system | One folder = one plugin, manifest-driven config, hot reload, optional bundled web page |
| Setup wizard `/setup` | Environment check, online asset bootstrap and basic config in five steps — no manual file editing |
| OpenAI-compatible layer `/v1` | Exposes `/v1/images/generations`, `/v1/images/edits`, `/v1/cards`, etc., callable by any OpenAI client |

---

## Pages

After startup, open `http://127.0.0.1:5000`:

| Page | Path | Purpose |
| --- | --- | --- |
| Workbench | `/` | Main pairing-card generator |
| Status | `/status` | Runtime status, cache and API call statistics |
| Setup wizard | `/setup` | First-run guide (env check / asset download / config) |
| Admin | `/admin` | Back-office panels (integration, plugins, command center) |

On first launch a random admin password is generated and **printed to the terminal**. You can pre-set it via `INIT_ADMIN_PASSWORD` in `.env`.

---

## Quick Start

### 1. Prerequisites

- **Python 3.10 – 3.13 (64-bit), 3.13 recommended** — the version and architecture are fixed on purpose: `skia-python`, `Pillow` and friends only ship prebuilt wheels, and a mismatch fails outright. **3.14 and newer are not supported yet** (the meme engine pins `Pillow ^10.0.0`, and 10.x has no 3.14 wheel).
- Windows: install from [python.org](https://www.python.org/downloads/) or the Microsoft Store, ticking `Add to PATH`.
- Linux: use your distro packages or `uv` (see [Linux deployment](docs/en/deploy-linux.md)).

### 2. Get the code

```bash
git clone -b beta https://github.com/<your-user>/<your-repo>.git
cd <your-repo>
```

> Releases live on the **`beta`** branch; the repository **does not include the meme assets** (~254 MB). The setup wizard downloads them on first run.

### 3. Create a virtual environment and install dependencies

Windows:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -U pip
& .venv\Scripts\python.exe -m pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

Linux / macOS:

```bash
python3.13 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

### 4. Configure

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Every option has a default, so you can **skip this and configure everything in the browser** later.

### 5. Run

**You must start from the project root** (`cache`, `temp` and `font` are resolved relatively):

```powershell
# Windows
& .venv\Scripts\python.exe app.py
```

```bash
# Linux
./.venv/bin/python app.py
```

Once the admin password appears in the logs, open `http://127.0.0.1:5000/setup` and walk through the wizard:

1. **Environment check** — verifies all 7 dependencies
2. **Meme assets** — one-click online download (skippable)
3. **Basic config** — bot name, command prefix, ports
4. **Finish** — go to the workbench

Then follow [Platform Integration](docs/en/platform-integration.md) to connect NapCat and let the bot loose in QQ.

---

## Command Cheatsheet

The default prefix is `/` (change it via `BOT_PREFIX`). Full reference: **[Command Manual](docs/en/commands.md)**.

| Command | Description |
| --- | --- |
| `/help`, `/菜单`, `/menu`, `/?` | Returns the **image** command menu |
| `/meme` | Usage guide for the meme generator |
| `/meme [keyword] [text1] [text2] …` | Generate a meme directly; attach an image, `@` someone or write a QQ number as source material |
| `/meme list [page/keyword]` | Browse assets with pagination; a keyword searches, e.g. `/meme list 摸头` |
| `/meme help [ID]` | Per-meme illustrated tutorial (template, presets, examples) |
| `/pair [QQ/@] [title]` | Generate a pairing card; accepts `template=` `bg=` `btn=` |
| `/quote [@/QQ] text…` | Compose a quote image |
| `<plugin trigger>` | Declared by `plugins/<plugin>/plugin.json` |

**Three ways to supply an image**: (1) send the command together with the image; (2) reply to an image message and then send the command; (3) `@` a member or write a QQ number so the bot fetches that avatar.

---

## Configuration & Integration

Two equivalent paths — **either one works**:

1. **Web UI** — the `/setup` wizard and the admin panels write back to files automatically.
2. **`.env`** — copy `.env.example`, edit, restart.

Priority: **system environment variables > `.env` > built-in defaults**.

### Key options

| Variable | Default | Description |
| --- | --- | --- |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `5000` | Workbench bind address and port. Use `127.0.0.1` for local-only |
| `INIT_ADMIN_PASSWORD` | empty | Initial admin password, used only on first run; empty = random and printed |
| `SECRET_KEY` | empty | Session key. Empty = regenerated each start (re-login after restart) |
| `WS_HOST` / `WS_PORT` / `WS_PATH` | `0.0.0.0` / `6700` / `/onebot/v11/ws` | OneBot V11 reverse-WS listener (NapCat connects here) |
| `WS_ACCESS_TOKEN` | empty | Connection token; empty disables verification |
| `WS_AUTO_START` | `false` | Start the WS server together with the main service |
| `WS_CONFIG_PRIORITY` | `file` | `file` = panel values override `.env`; `env` = `.env` wins and the panel cannot save |
| `BOT_ENABLED` | `true` | Master switch for commands |
| `BOT_NAME` / `BOT_PREFIX` | `我在哔哩学习` / `/` | Bot display name and command prefix |
| `BOT_GROUP_NEED_AT` | `false` | Whether group commands require an `@` mention |
| `BOT_ALLOW_PRIVATE` | `true` | Allow commands in private chats |
| `BOT_COOLDOWN_SEC` | `3` | Minimum seconds between two commands from the same user |
| `BOT_MAX_IMAGE_MB` | `8` | Max size of a single reply image |
| `PLUGIN_ENABLED` / `PLUGIN_HOT_RELOAD` | `true` / `true` | Plugin master switch / hot reload |
| `PLUGIN_WEB_PORT_BASE` | `7000` | Starting port for plugin-bundled web pages |
| `CACHE_EXPIRE_DAYS` | `30` | Days to keep generated-image cache |

The exhaustive list (quote layout, cache, background API, etc.) lives in **[Configuration Reference](docs/en/configuration.md)** and in `.env.example`, which is fully commented.

### Connecting NapCat (OneBot V11)

ILBB itself is a **WebSocket server**; NapCat connects to it as a **reverse WebSocket**:

1. In ILBB: confirm the WS server is running (or set `WS_AUTO_START=true` in `.env`).
2. In NapCat: add a new "Network Config → Reverse WebSocket" entry pointing at
   `ws://<machine-running-ILBB>:6700/onebot/v11/ws`, with a token matching `WS_ACCESS_TOKEN`.
3. Once connected, the ILBB **live event stream** starts showing messages, notices, requests and meta events.

Step-by-step instructions, protocol fields, the API debugger and the OpenAI-compatible layer are documented in **[Platform Integration](docs/en/platform-integration.md)**.

---

## Plugin System

**One folder = one plugin.** Copy `plugins/example/` to `plugins/my_plugin/` and edit it. Hot reload is on by default (3-second polling), so changes apply without a restart.

```
plugins/
└── my_plugin/
    ├── plugin.json     # Manifest: id / name / config fields / command declarations
    ├── main.py         # Entry point: setup(ctx) registers commands and handlers
    └── web/            # Optional: the plugin's own web page
        └── index.html
```

Inside `main.py` the `ctx` object exposes the full feature set: send/receive messages, list friends/groups/members, read and write plugin config, call any OneBot API, and serve its own web port.

```python
def setup(ctx):
    @ctx.on_command(["ping"], desc="Test")
    def _ping(args, ctx, p):
        return ([], ["pong"])

    @ctx.on_event
    def _on_msg(ev, client):
        ctx.log("event: %s" % ev.get("post_type"))
```

Config fields support 8 types (`text` / `textarea` / `int` / `bool` / `enum` / `friend` / `group` / `group_member`), rendered as a form in the admin panel and applied live.

Full API reference, manifest field table, web-page integration and two copyable examples are in the **[Plugin Development Guide](docs/en/plugin-dev.md)**.

---

## Three Deployment Targets

| Platform | Document | Notes |
| --- | --- | --- |
| **Windows** | [deploy-windows.md](docs/en/deploy-windows.md) | Python 3.10 – 3.13 (64-bit); copy `icudtl.dat` into the Python install dir; open ports 5000 / 6700 in the firewall |
| **Linux** | [deploy-linux.md](docs/en/deploy-linux.md) | Python 3.10 – 3.13; mind `libfontconfig1` / `libgl1` and friends; keep the path free of spaces and non-ASCII |
| **Android** | [deploy-android.md](docs/en/deploy-android.md) | Run under Termux with Python 3.10 – 3.13; **not thoroughly validated — test at your own risk** |

Chinese versions: [Windows](docs/zh/deploy-windows.md) ｜ [Linux](docs/zh/deploy-linux.md) ｜ [Android](docs/zh/deploy-android.md)

> Recommended order: get `/setup` working locally and download the assets first, then migrate to Linux, a server or a phone.

---

## Project Layout

```
.
├── app.py                 # Main Flask app (WebUI + routes); runnable via python app.py
├── _serve.py              # Production-style entry point (reads WEB_HOST / WEB_PORT / WEB_THREADED)
├── .env.example           # Commented config template; copy to .env
├── LICENSE                # MIT
├── core/                  # Core logic
│   ├── config.py          # Config loading (.env → constants)
│   ├── ws_server.py       # OneBot V11 reverse-WS server + API debug metadata
│   ├── bot_commands.py    # Command routing and event handling
│   ├── bot_render.py      # Help / menu / list image rendering
│   ├── meme_service.py    # Meme composition service
│   ├── meme_assets.py     # Asset manifest and online bootstrap
│   ├── plugin_manager.py  # Plugin loading / hot reload / config
│   ├── openai_api.py      # OpenAI-compatible layer (/v1)
│   ├── admin.py           # Login and admin password
│   ├── api_key_store.py   # API key storage and validation
│   └── usage.py           # API call statistics
├── plugins/               # Plugins (one folder each)
│   └── example/           # Official example plugin (with its own web page)
├── templates/             # Page templates
├── static/                # Frontend assets (css / js / bg)
├── font/                  # Fonts used by pairing cards
├── vendor/                # Meme engine source + fonts + asset manifest (assets excluded)
├── cache/  temp/          # Runtime cache and temp files (not committed)
└── docs/                  # Bilingual documentation
    ├── zh/                # Chinese docs
    └── en/                # English docs
```

---

## Documentation Index

| Topic | Chinese | English |
| --- | --- | --- |
| Overview | [docs/zh/index.md](docs/zh/index.md) | [docs/en/index.md](docs/en/index.md) |
| Deploy · Windows | [docs/zh/deploy-windows.md](docs/zh/deploy-windows.md) | [docs/en/deploy-windows.md](docs/en/deploy-windows.md) |
| Deploy · Linux | [docs/zh/deploy-linux.md](docs/zh/deploy-linux.md) | [docs/en/deploy-linux.md](docs/en/deploy-linux.md) |
| Deploy · Android | [docs/zh/deploy-android.md](docs/zh/deploy-android.md) | [docs/en/deploy-android.md](docs/en/deploy-android.md) |
| Commands | [docs/zh/commands.md](docs/zh/commands.md) | [docs/en/commands.md](docs/en/commands.md) |
| Plugin development | [docs/zh/plugin-dev.md](docs/zh/plugin-dev.md) | [docs/en/plugin-dev.md](docs/en/plugin-dev.md) |
| Platform integration | [docs/zh/platform-integration.md](docs/zh/platform-integration.md) | [docs/en/platform-integration.md](docs/en/platform-integration.md) |
| Configuration | [docs/zh/configuration.md](docs/zh/configuration.md) | [docs/en/configuration.md](docs/en/configuration.md) |

---

## FAQ

**Is Python 3.13 mandatory?**
The version requirement is fixed at **Python 3.10 – 3.13 (64-bit), 3.13 recommended**. `skia-python~=144.0` ships prebuilt wheels; a mismatched Python version or 32/64-bit architecture simply fails to install. Step 1 of the setup wizard checks the interpreter alongside the dependencies and flags anything that does not qualify.

**Can I use Python 3.14?**
No. `skia-python` itself does publish a 3.14 wheel, but the meme engine vendored here pins `Pillow ^10.0.0`, and Pillow 10.x predates 3.14 with no prebuilt wheel for it, so pip fails with `Could not find a version that satisfies the requirement Pillow<11,>=10`. Installing 64-bit 3.13 is the only painless option.

**"Assets incomplete" or `/meme` says the meme is missing?**
Meme assets (~254 MB) are intentionally excluded from the repo. Open `http://127.0.0.1:5000/setup` and use the "Meme assets" step to download them.

**Startup complains about missing `cache` / `temp` / `font`?**
Start the app from the **project root** — those paths are relative.

**The bot doesn't reply.**
Check in order: WS server running → NapCat reverse-WS connected (the event stream scrolls) → `BOT_ENABLED=true` → correct prefix (default `/`) → private chat not disabled by `BOT_ALLOW_PRIVATE=false` → not hitting `BOT_COOLDOWN_SEC`.

**I forgot the admin password.**
Remove the password hash from `api_keys.json` and restart — a new one is generated and printed. Deleting the whole file also works.

---

## Credits & License

- The meme composition engine comes from [MeetWq/meme-generator](https://github.com/MeetWq/meme-generator) (MIT) and is bundled at `vendor/meme-generator-main`.
- Asset copyrights belong to their respective authors. This project only provides technical integration; please do not use it commercially.

Released under the **[MIT License](LICENSE)**.

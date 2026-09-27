# I Learning Bilibili Emoji Bot · ILBB

[中文](README.md) ｜ **English**

> **Current version: v0.2.0-beta** ｜ Release branch: `beta` ｜ Beta stage: features and interfaces may still change.

A **self-hosted** QQ sticker generator bot plus a web workbench. Hook it up to NapCat (OneBot V11) and your group chats can generate memes with a single message — while the web UI gives you a pairing-card generator, quote-image composer, asset browser, API debugger and a plugin system.

No third-party cloud service required. Everything runs on your own machine.

---

## Table of Contents

- [Features](#features)
- [Pages](#pages)
- [Deployment](#deployment)
- [Command Cheatsheet](#command-cheatsheet)
- [Configuration & Integration](#configuration--integration)
- [Plugin System](#plugin-system)
- [Project Layout](#project-layout)
- [Documentation](#documentation)
- [FAQ](#faq)
- [License & Attribution](#license--attribution)

---

## Features

| Module | Description |
| --- | --- |
| Meme generation `/meme` | 282 memes, 3,400+ asset files. Send a command plus text (optionally with an image, an `@mention` or a QQ number) and get a sticker back. Supports per-meme preset arguments |
| Pairing card `/pair` | QQ-style pairing cards with three templates (classic / dark / paper); custom title, background and button labels |
| Quote image `/quote` | Landscape 16:9: a random anime background with a grey mask (35% opacity by default), one fully blurred tray in the centre holding a circular avatar on the left and text or a sticker on the right, and a signature at the bottom right; JPG for static content, GIF when animated, fonts switchable |
| Image menu `/help` | Every command rendered as a clean, phone-friendly image |
| Web workbench | Pairing-card generator, meme preview and debugging, command dry-run preview, web chat session (try commands without QQ) |
| Integration panel | Start/stop the OneBot V11 reverse-WS server, edit its config, watch a live event stream with raw JSON, and use a debug panel for 30+ OneBot APIs |
| Plugin system | One folder = one plugin, manifest-driven config, hot reload, optional bundled web page |
| Setup wizard `/setup` | Environment check, online asset bootstrap, basic config and setting your admin password in four steps — no manual file editing |
| OpenAI-compatible layer `/v1` | Exposes `/v1/images/generations`, `/v1/images/edits`, `/v1/cards`, etc., callable by any OpenAI client |

---

## Pages

After startup, open `http://127.0.0.1:5000`:

| Page | Path | Purpose |
| --- | --- | --- |
| Workbench | `/` | Main pairing-card generator |
| Status | `/status` | Runtime status, cache and API call statistics |
| Setup wizard | `/setup` | Wizard (env check / asset download / config / set admin password) |
| Admin | `/admin` | Back-office panels (integration, plugins, command center) |

On first launch `/` sends you to the setup wizard, whose last step asks you to set your own admin password. Until then the terminal prints a temporary password on every startup (randomly generated, or taken from `INIT_ADMIN_PASSWORD` in `.env`); it stops working once you set your own.

---

## Deployment

The project is self-hosted and needs no third-party cloud service. Environment requirements, dependency installation, configuration, startup, auto-start on boot and troubleshooting are split by platform and live in [Choose a deployment](docs/en/deploy.md) — pick the route that matches your machine and follow it.

Three things are worth knowing up front. Python must be **3.10 – 3.13 (64-bit), 3.13 recommended**; `skia-python`, `Pillow` and friends only ship prebuilt wheels, so a version or architecture mismatch fails outright, and 3.14 does not work either (see [FAQ](#faq) below for why). Dependencies are managed by [uv](https://docs.astral.sh/uv/): once uv is installed, create the environment with `uv venv --python 3.13` and install with `uv pip install -r requirements.txt` — no need to touch pip again. The repository **does not include the meme assets** (~254 MB); the setup wizard downloads them on first run.

**You must start the service from the project root** — `cache`, `temp` and `font` are resolved relatively. After startup, open `http://127.0.0.1:5000/setup` and let the wizard handle the environment check, asset download and basic config in one pass. Then follow [Platform Integration](docs/en/platform-integration.md) to connect NapCat and let the bot loose in QQ.

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
| `INIT_ADMIN_PASSWORD` | empty | Temporary password used until you set your own admin password; empty = generated at startup and printed |
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

## Documentation

Docs come in two language sets, entered from [docs/en/index.md](docs/en/index.md) and [docs/zh/index.md](docs/zh/index.md). Only the category entries are listed below; open them for the full list.

| Category | Entry |
| --- | --- |
| Deployment | [Choose a deployment](docs/en/deploy.md) — Windows / Linux / Android |
| Usage | [Commands](docs/en/commands.md) ｜ [Configuration](docs/en/configuration.md) ｜ [Platform integration](docs/en/platform-integration.md) |
| Development | [Plugin Development Guide](docs/en/plugin-dev.md) |

Chinese docs: [选择部署方式](docs/zh/deploy.md) ｜ [指令手册](docs/zh/commands.md) ｜ [配置参考](docs/zh/configuration.md) ｜ [平台对接](docs/zh/platform-integration.md) ｜ [插件开发指南](docs/zh/plugin-dev.md)

---

## FAQ

**Is Python 3.13 mandatory?**
The version requirement is fixed at **Python 3.10 – 3.13 (64-bit), 3.13 recommended**. Packages such as `skia-python` and `Pillow` ship as prebuilt wheels; a mismatched Python version or 32/64-bit architecture simply fails to install. Step 1 of the setup wizard checks the interpreter alongside the dependencies and flags anything that does not qualify.

**Can I use Python 3.14?**
No. `skia-python` itself does publish a 3.14 wheel, but the meme engine vendored here pins `Pillow ^10.0.0`, and Pillow 10.x predates 3.14 with no prebuilt wheel for it, so pip fails with `Could not find a version that satisfies the requirement Pillow<11,>=10`. Installing 64-bit 3.13 is the only painless option.

**Startup fails with `ModuleNotFoundError: No module named 'toml'` (or `loguru`, `httpx`)?**
The meme engine's dependencies are missing. The engine ships as source at `vendor/meme-generator-main/` and is not installed through pip, so pip cannot resolve the dependencies it declares, and installing package by package easily leaves a few out. Run `uv pip install -r requirements.txt` from the project root to fill them all in at once. The `Pillow` pin to 10.x in that list follows the same logic: it is the range the engine locks, and 11 or 12 imports fine but breaks when you actually generate a meme.

**"Assets incomplete" or `/meme` says the meme is missing?**
Meme assets (~254 MB) are intentionally excluded from the repo. Open `http://127.0.0.1:5000/setup` and use the "Meme assets" step to download them.

**Startup complains about missing `cache` / `temp` / `font`?**
Start the app from the **project root** — those paths are relative.

**The bot doesn't reply.**
Check in order: WS server running → NapCat reverse-WS connected (the event stream scrolls) → `BOT_ENABLED=true` → correct prefix (default `/`) → private chat not disabled by `BOT_ALLOW_PRIVATE=false` → not hitting `BOT_COOLDOWN_SEC`.

**I forgot the admin password.**
Every startup prints the password currently in effect: until you set your own, the temporary one is printed in plain text. To reset completely, remove `admin_hash` from `api_keys.json` and restart — a new one is generated and printed. Or just open `/setup` and set a new one.

---

## License & Attribution

Released under the **[MIT License](LICENSE)**. Beyond its own code, the repository bundles or integrates the following external projects:

| Project | Role in ILBB | Link |
| --- | --- | --- |
| meme-generator | The meme rendering engine, bundled at `vendor/meme-generator-main` (0.1.14); the fonts and asset manifest used for rendering live here too | [MemeCrafters/meme-generator](https://github.com/MemeCrafters/meme-generator) (MIT; originally by MeetWq, [old repo](https://github.com/MeetWq/meme-generator)) |
| NapCat | The protocol side: logs in to QQ and connects back to ILBB over a reverse WebSocket | [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ) ｜ [docs](https://napneko.github.io/) |
| OneBot V11 | The message protocol between ILBB and the protocol side | [botuniverse/onebot](https://github.com/botuniverse/onebot) |
| uv | Creates the virtual environment and installs dependencies (used in place of pip throughout the deployment docs) | [astral-sh/uv](https://github.com/astral-sh/uv) |

Other external resources in play:

- The meme assets (~254 MB) are not committed. The setup wizard pulls them on first run from mirrors of the meme-generator repository (jsDelivr, raw.githubusercontent and similar), with the candidate URLs listed in `core/meme_assets.py`. Those assets originate from [nonebot-plugin-petpet](https://github.com/noneplugin/nonebot-plugin-petpet) and [nonebot-plugin-memes](https://github.com/noneplugin/nonebot-plugin-memes).
- Quote images and the login page / workbench background call a third-party random image API by default, `BG_API_URL` (`https://api.yppp.net/api.php`). Point it elsewhere in `.env`, or serve your own cached images instead.
- The plugin store points at a companion plugin source server by default, `PLUGIN_STORE_URL` (`https://store.miao.os.kg/`). It supplies the plugin list and repository URLs; the actual code is still cloned from GitHub. Point it at your own instance, or turn the store off with `PLUGIN_STORE_ENABLED=false`.
- The three fonts under `font/`, plus the fonts shipped with the engine, are used only to render pairing cards and quote images. Copyright belongs to their respective authors, so check the licence before any commercial use.
- Python dependencies are listed in `requirements.txt` (Flask, Pillow, skia-python, pil-utils, FastAPI and more), each under its own licence. Asset copyrights belong to their respective authors; this project only provides technical integration, so please do not use it commercially.

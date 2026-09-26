# Configuration Reference

**English** ｜ [中文](../zh/configuration.md)

All ILBB configuration is driven by **environment variables**, layered by precedence from three sources:

```
System environment variables   >   .env file   >   built-in code defaults
```

That is to say: **deleting a line = using the default value**, and you do not need to write them all out. Restart the service for changes to take effect.

`.env` is ignored by `.gitignore`, so **do not commit a `.env` containing secrets**. The project ships with `.env.example` as a template:

```bash
# Windows
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

> After the first startup you can also change configuration on the **setup page `/setup`** and the **settings page**, which writes back to `.env` automatically.

---

## 1. WebUI / Flask

| Variable | Default | Description |
| --- | --- | --- |
| `WEB_HOST` | `0.0.0.0` | Listen address. `0.0.0.0` = allows LAN access, `127.0.0.1` = local machine only |
| `WEB_PORT` | `5000` | WebUI port. Access from other devices requires opening it in the firewall |
| `WEB_DEBUG` | `false` | Flask debug mode; keep it `false` for daily use |
| `WEB_THREADED` | `true` | Handle requests with multiple threads, so slow requests do not block login |
| `WEB_MAX_UPLOAD_MB` | `64` | Maximum request body size per request (MB); avatars/uploads go through base64 |
| `SECRET_KEY` | empty | Session encryption key. **Empty** = randomly generated on every startup, so you must log in again after a restart (more secure); **a fixed value** = you stay logged in after a restart |
| `INIT_ADMIN_PASSWORD` | empty | Initial admin password that takes effect **only on the first run**. Empty = randomly generate 8 characters and print them to the startup log |

> `INIT_ADMIN_PASSWORD` is only meaningful while `api_keys.json` does not yet have an admin password. To change the password afterwards, use "Settings → Change admin password" in the WebUI; changing this variable no longer has any effect.

---

## 2. WS server (OneBot V11 / NapCat)

| Variable | Default | Description |
| --- | --- | --- |
| `WS_HOST` | `0.0.0.0` | Reverse WebSocket listen address |
| `WS_PORT` | `6700` | Listen port. In NapCat fill in `ws://<this machine's IP>:6700/onebot/v11/ws` |
| `WS_PATH` | `/onebot/v11/ws` | Connection path; must start with `/` |
| `WS_ACCESS_TOKEN` | empty | Access token; empty means no verification |
| `WS_AUTO_START` | `false` | Whether to start the WS server automatically together with the main service |
| `WS_CONFIG_PRIORITY` | `file` | Configuration precedence, see the explanation below |
| `WS_EVENT_LIMIT` | `300` | Number of entries in the live event log ring buffer |
| `WS_RAW_LIMIT` | `4000` | Truncation length (characters) of a single raw JSON shown on the web page |
| `WS_MAX_FRAME_MB` | `16` | Maximum size of a single message frame (MB); leave headroom for merged forwards / long messages |

**`WS_CONFIG_PRIORITY` is a common trap**:

- `file` (default) —— the `ws_config.json` saved from the WebUI panel **overrides** the values in `.env`, and the panel can modify and save.
- `env` —— forces `.env` to have the final say, ignores `ws_config.json`, and clicking "Save config" in the panel is rejected.

If you change configuration in the panel but it does not take effect, check this item first.

> **Be sure to get the direction right**: ILBB is the **server** (listening on 6700) and NapCat connects to it as the **client**. See [Message Platform Integration](platform-integration.md) for details.

---

## 3. Bot commands

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_ENABLED` | `true` | Master switch for commands. `false` = the bot does not respond to any command |
| `BOT_NAME` | `我在哔哩学习` | Bot nickname, shown in the help image title and copy |
| `BOT_PREFIX` | `/` | Command prefix; can be changed to `#` etc. |
| `BOT_GROUP_NEED_AT` | `false` | Whether group chats must @ the bot to get a response |
| `BOT_ALLOW_PRIVATE` | `true` | Whether commands are allowed in private chat |
| `BOT_MEME_LIST_PAGE` | `12` | Entries per page for the `/meme list` asset list; beyond that it is sent as multiple images |
| `BOT_MAX_IMAGE_MB` | `8` | Maximum size of a single reply image (MB); oversized ones are compressed or dropped |
| `BOT_COOLDOWN_SEC` | `3` | Minimum interval between two commands from the same user (seconds); `0` = no limit |
| `BOT_FOOTER` | `我在哔哩学习 Emoji Bot · ILBB` | Signature text on the help image; leave empty to hide it |

> The prefix takes at most 3 characters (truncated in code). After changing it to `#`, commands become `#help`, `#meme 摸`.

---

## 4. Quote image (`/quote`)

| Variable | Default | Description |
| --- | --- | --- |
| `QUOTE_ENABLED` | `true` | Switch for the `/quote` command |
| `QUOTE_WIDTH` | `1280` | Landscape canvas width (pixels); keep it at 16:9 with the height |
| `QUOTE_HEIGHT` | `720` | Landscape canvas height (pixels) |
| `QUOTE_MASK_ALPHA` | `0.35` | Opacity of the grey mask over the background; `0.35` = 35% grey (the background stays recognisable). The glass panel, avatar and text are all drawn above the mask |
| `QUOTE_JPG_QUALITY` | `92` | JPG output quality for static images (60–100) |
| `QUOTE_AVATAR` | `236` | Width of the standalone rounded avatar on the left (pixels); its height is about 1.32× the width |
| `QUOTE_TRAY_BLUR` | `30` | Gaussian blur radius of the glass panel (the frosted core — higher is blurrier) |
| `QUOTE_TRAY_GLASS` | `0.58` | Strength of the warm white glass layered on top of the blur (0.2–0.96; higher is whiter and less transparent) |
| `QUOTE_TEXT_MAX` | `56` | Upper limit of the auto font size for text inside the panel (pixels) |
| `QUOTE_TEXT_MIN` | `22` | Lower limit of the auto font size for text inside the panel |
| `QUOTE_MAX_BODY` | `500` | Maximum height of the panel content area; beyond it the font shrinks, and at the bottom line it is truncated with an ellipsis |
| `QUOTE_NAME_SIZE` | `40` | Font size of the signature "—— username" at the bottom right (the font follows the global `FONT_FAMILY`) |
| `QUOTE_NAME` | `无名氏` | Placeholder name used when no nickname can be obtained |
| `QUOTE_NAME_MAX` | `16` | Maximum number of characters shown in the signature name |
| `QUOTE_GIF_MAX_FRAMES` | `60` | When the panel content is an animated emoji the output is a GIF; frames beyond this count are sampled evenly |
| `QUOTE_GIF_MIN_MS` | `40` | Minimum duration of a single GIF frame (milliseconds) |

---

## 5. Plugin system

| Variable | Default | Description |
| --- | --- | --- |
| `PLUGIN_ENABLED` | `true` | Master switch for plugins. `false` = no plugin is loaded |
| `PLUGIN_DIR` | `plugins` | Plugin root directory; every subfolder is one plugin |
| `PLUGIN_CONFIG_PATH` | `plugins_config.json` | File where plugin configuration changed in the Web is stored |
| `PLUGIN_HOT_RELOAD` | `true` | Hot reload: changing plugin files / adding or removing directories takes effect automatically |
| `PLUGIN_POLL_SEC` | `3` | Hot reload polling interval (seconds), minimum 2 |
| `PLUGIN_WEB_SCHEME` | `http` | Protocol of the Web bundled with a plugin |
| `PLUGIN_WEB_PORT_BASE` | `7000` | Starting value for automatic plugin Web port allocation |
| `PLUGIN_WEB_TIMEOUT` | `4` | Timeout (seconds) for probing whether the plugin Web is ready |
| `PLUGIN_MAX_IMAGE_MB` | `8` | Upper limit of reply images for one command of a single plugin (MB) |

See the [Plugin Development Guide](plugin-dev.md) for details.

---

## 6. Directories and data files

| Variable | Default | Description |
| --- | --- | --- |
| `TEMP_DIR` | `temp` | Temporary file directory |
| `CACHE_DIR` | `cache` | Generated image cache directory |
| `FONT_DIR` | `font` | Font directory |
| `FONT_FAMILY` | `system` | Global font; `system` = the built-in CJK font, or a font name placed in `font/` |
| `BG_DIR` | `static/bg` | Background image storage directory, served by the backend at `/bg/<filename>` |
| `BG_CONFIG_PATH` | `bg_config.json` | Persistence file for the background configuration (type / link / blur / mask) |
| `API_KEYS_PATH` | `api_keys.json` | Storage file for the admin password hash + API Keys |
| `OPENAI_V1_DIR` | `cache/v1` | Output directory of the OpenAI-compatible API, also mapped as `/v1/files/<name>` |
| `BG_URL_PREFIX` | `bg` | Public URL prefix of uploaded background images; usually no need to change |

> Relative paths are resolved against the **project root directory**, and absolute paths (such as `E:/data/cache`) also work. Therefore **you must start from the project root directory**.

---

## 7. Cache and canvas

| Variable | Default | Description |
| --- | --- | --- |
| `CACHE_EXPIRE_DAYS` | `30` | Number of days generated image cache is kept |
| `CANVAS_WIDTH` | `600` | Pairing card canvas width (pixels) |
| `CANVAS_HEIGHT` | `800` | Pairing card canvas height (pixels) |

---

## 8. Background image API

| Variable | Default | Description |
| --- | --- | --- |
| `BG_API_URL` | `https://api.yppp.net/api.php` | Random background image API (login page / workbench background) |
| `BG_FETCH_TIMEOUT` | `8` | Background image request timeout (seconds) |

> This is a **third-party API** and its availability is not guaranteed. When no image can be fetched the background falls back to a solid color, which does not affect other features.

---

## 9. First-run setup page

On the first startup, visiting `http://127.0.0.1:5000/setup` takes you to the setup page, which does four things:

| Step | Content |
| --- | --- |
| Environment self-check | Checks 7 dependencies one by one (flask / requests / pillow / websockets / skia-python / numpy / meme engine); a missing one points you to `uv pip install -r requirements.txt` |
| Asset download | Pulls meme assets from the original repository to complete `vendor/.../memes/`, with progress and cancel |
| Basic configuration | Sets the admin password, WebUI port, command prefix, etc., and writes back to `.env` |
| Done | Redirects to the main interface |

**Why the assets must be downloaded**: to keep the repository size down to a few tens of MB, the roughly 282 asset directories (about 254MB) under `vendor/meme-generator-main/meme_generator/memes/` are **not committed** and are completed over the network by this step. ILBB can start without downloading them, but meme generation will fail on a large scale.

---

## 10. Configuration precedence in practice

**Scenario 1: you want to change WS settings in the panel**

Keep `WS_CONFIG_PRIORITY=file` and change them directly in the WebUI panel; after saving, they are written to `ws_config.json` and take effect immediately.

**Scenario 2: you want `.env` to have the final say (e.g. Docker deployment)**

Set `WS_CONFIG_PRIORITY=env`, then fix all WS parameters in the Docker environment variables or in `.env`.

**Scenario 3: you forgot the admin password**

The password hash is stored in `api_keys.json`. After deleting that file (or deleting the admin password field in it) and restarting, the "first run" logic is triggered again: if `INIT_ADMIN_PASSWORD` is empty, an 8-character password is randomly generated and printed to the startup log.

**Scenario 4: you changed `.env` but it does not take effect**

Troubleshoot in order: ① is it written as `KEY = value` (**no spaces allowed**); ② is a system environment variable with the same name overriding it; ③ did you restart the service; ④ for WS-related items, check `WS_CONFIG_PRIORITY`.

---

[Back to docs home](index.md) ｜ [中文](../zh/configuration.md)

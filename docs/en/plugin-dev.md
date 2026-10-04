# Plugin Development Guide

**English** ｜ [中文](../zh/plugin-dev.md)

ILBB's plugin system follows one minimal rule: **one folder = one plugin**. Drop a folder into `plugins/` and it will be recognized; delete the folder and it is uninstalled; change the code and it hot-reloads automatically.

The built-in `plugins/example/` demonstrates every capability; **copying it and renaming it** is the recommended starting point.

---

## 1. Minimal plugin

Directory structure:

```
plugins/
  hello/
    plugin.json      # manifest (required)
    main.py          # entry point (required, must provide setup(ctx))
```

`plugin.json`:

```json
{
  "id": "hello",
  "name": "打招呼",
  "version": "1.0.0",
  "author": "你的名字",
  "desc": "最小示例：收到 /hello 就回一句话。",
  "entry": "main.py",
  "enabled": true
}
```

`main.py`:

```python
# -*- coding: utf-8 -*-

def cmd_hello(args, ctx, p):
    """/hello -- reply with a greeting."""
    who = "、".join(args) if args else "世界"
    return ([], ["你好，%s！" % who])


def setup(ctx):
    ctx.on_command(["hello"], cmd_hello)
    ctx.log("hello 插件已载入")
    return True
```

Put it into `plugins/`, wait one polling cycle (3 seconds by default), and sending `/hello` in a group will get a reply. Whatever `ctx.log()` writes is printed straight to the ILBB console.

---

## 2. plugin.json field reference

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | string | folder name | Unique plugin identifier; only letters / digits / underscores / hyphens are allowed, max 32 characters |
| `name` | string | same as `id` | Display name |
| `version` | string | `0.0.0` | Version number, available as `ctx.version` |
| `author` | string | empty | Author |
| `desc` | string | empty | Description, shown in the Web plugin panel |
| `entry` | string | `main.py` | Entry file; absolute paths or `..` parent directories are **not allowed** |
| `enabled` | bool | `true` | Whether it is enabled by default on first load |
| `web` | bool | `false` | Whether to enable a standalone page (see section 6) |
| `web_title` | string | same as `name` | Title of the standalone page |
| `web_path` | string | `/` | Entry path of the standalone page |
| `web_port` | int | `0` | Standalone page port; `0` means auto-allocate starting from `PLUGIN_WEB_PORT_BASE` (default 7000) |
| `config` | array | empty | Configuration item declarations (see section 5) |
| `help` | object / array / string | empty | Plugin help declaration rendered by `/plugin help` (see section 5.5) |

When `id` is invalid or `entry` cannot be found, the plugin is not loaded, and the "misinstalled plugins" area of the Web plugin panel gives the reason.

---

## 3. Lifecycle

| Function | Required | When it is called |
| --- | --- | --- |
| `setup(ctx)` | **Required** | Called once when the plugin is loaded. Returning `True` / returning nothing is treated as success |
| `teardown()` | Optional | Called on plugin unload, hot disable, or before reloading due to code changes |

Hot reload watches file changes with these extensions: `.py` `.json` `.html` `.js` `.css` `.txt` `.md` `.svg`. That means **changing frontend files also triggers a reload**, so no manual restart is needed.

During a reload the old module is purged (`_purge_modules`), so inside a plugin **do not rely on module-level globals to keep state for long** —— if you need persistence, write to a file or store it with `ctx.set_cfg()`.

---

## 4. Commands and events

### 4.1 Registering commands

```python
def setup(ctx):
    ctx.on_command(["hello", "hi"], cmd_hello)   # an alias list is supported
```

The trigger words of `on_command(triggers, fn)` are **case-insensitive** and do not carry `/`. When triggered, ILBB splits the message by spaces; the first word matches the trigger word, and **the remaining part is passed in as the `args` list**.

It also accepts three **optional** help parameters: `on_command(triggers, fn, desc="one-line description", usage="/usage example", group="group name")`. They only affect what `/plugin help` shows and do not change command behaviour; omitting them is fine (help falls back to listing the registered triggers).

Command function signature:

```python
def fn(args, ctx, p):
    # args -- list[str], the arguments after the command (already split by spaces)
    # ctx  -- the chat context that triggered this command
    # p    -- PluginContext (the context object of this plugin)
    return ([image bytes, ...], ["text", ...])
```

Return value conventions:

| Return | Effect |
| --- | --- |
| `([], ["text"])` | Send text only (in groups the sender is automatically @-mentioned) |
| `([png_bytes], [])` | Send images only; multiple images are allowed |
| `([png_bytes], ["caption"])` | Send image and text together |
| `None` | No reply (used for "silent handling") |
| a plain string | Equivalent to `([], [str])` |

### 4.2 Chat context `ctx` (inside a command)

| Key | Description |
| --- | --- |
| `mtype` | `"group"` or `"private"` |
| `gid` | Group number (empty in private chat) |
| `uid` | Sender's QQ number |
| `av` | Sender avatar URL |
| `message_id` | Message ID |

> Note: this name is easily confused with `PluginContext`. The third argument of a command function is the `PluginContext`.

### 4.3 Listening to events

```python
def on_event(ev, client):
    extra = (ev or {}).get("extra") or {}
    if extra.get("mtype") != "group":
        return
    ...

def setup(ctx):
    ctx.on_event(on_event)
```

`ev` is the event dict parsed by ILBB, and `ev["extra"]` likewise contains `mtype` / `gid` / `uid` / `av`. `client` is the underlying WebSocket connection object, which is generally not needed.

Event callbacks run in a separate thread, so **do not perform long blocking operations**, otherwise event dispatch will be slowed down. Throwing an exception only logs it and does not affect the main service.

---

## 5. Declaring configuration items

Declare them in the `config` array of `plugin.json`; ILBB will automatically generate a form in the Web panel and persist it in `plugins_config.json`.

```json
"config": [
  {
    "key": "greet",
    "label": "打招呼文本",
    "type": "text",
    "default": "你好",
    "placeholder": "请输入",
    "hint": "群里发 /hello 时回复的内容。"
  }
]
```

Supported `type`s:

| Type | Rendered as on the Web | Single-select default | Multi-select default |
| --- | --- | --- | --- |
| `text` | Single-line input box | `""` | — |
| `textarea` | Multi-line input box | `""` | — |
| `int` | Number input box | `0` | — |
| `bool` | Toggle switch | `false` | — |
| `enum` | Dropdown menu (requires `options`) | `""` | — |
| `friend` | **Friend dropdown** | `""` | `[]` |
| `group` | **Group dropdown** | `""` | `[]` |
| `group_member` | **Group member dropdown** | `""` | `[]` |

`friend` / `group` / `group_member` are an ILBB specialty: the options are pulled directly from the friend / group / group member lists of the QQ account NapCat is currently logged in as, so **the plugin side does not need to write a single line of API calls**. Add `"multi": true` to turn it into a multi-select, displayed as tags.

> The options of `group_member` **link to the group already selected by the first `group` / `group_member` in the same plugin**, so the typical pattern is to put "which group to pick" first.

How to write `options` for `enum`:

```json
"options": [
  { "value": "normal", "label": "普通" },
  { "value": "strict", "label": "严格" }
]
```

Other optional fields: `placeholder` (placeholder hint), `hint` (note below the form), `multi` (whether it is multi-select).

### Reading and writing configuration

```python
def cmd_info(args, ctx, p):
    greet = p.cfg("greet", "默认值")     # read a single value
    allv  = p.cfg()                      # read all, returns a dict
    p.set_cfg("greet", "新值")           # write back and persist to disk
    return ([], [greet])
```

`p.cfg(key, default)` returns `default` when the key does not exist.

### Hot-applied configuration

You can optionally implement `on_config(vals, ctx)`; it is called when "Save config" is clicked on the Web, and **the code does not need to be reloaded**:

```python
def on_config(vals, ctx):
    ctx.log("配置已更新：%r" % (vals,))
```

---

## 5.5 Help declaration (`/plugin help`)

ILBB ships two built-in image commands for plugins, shared by all plugins:

```
/plugin                 plugin list (each plugin gets a number, image)
/plugin help <number|id>  usage help for one plugin (image)
```

Help content comes from two sources, in priority order:

1. **the `help` block in `plugin.json`** -- write it once and get full help, recommended;
2. metadata passed at registration time: `ctx.on_command(triggers, fn, desc=..., usage=...)`.

If neither is present, `/plugin help` gracefully falls back to listing the registered trigger words.

The `help` block accepts three forms:

```json
"help": "one-line description"
```

```json
"help": {
  "summary": "What this plugin does",
  "commands": [
    { "usage": "/hello", "desc": "Say hello." },
    { "usage": "/hello <name>", "desc": "Greet a specific person." }
  ],
  "notes": [
    "Send the image together with the command in a group.",
    "Edit settings in the admin plugin panel; they apply without a reload."
  ]
}
```

- `summary` falls back to the manifest `desc`;
- `/trigger` occurrences inside `commands[].usage` are recognised, so declared triggers are not appended twice;
- `notes` is rendered as a "usage notes" group;
- `config` fields appear as a "configurable" group at the end of the help image, together with the standalone page port hint.

See `plugins/example/plugin.json` and `plugins/BiliPlay_ILBB_Toys/plugin.json` for complete examples.

---

## 6. PluginContext full API

The object obtained in `setup(ctx)` provides the following capabilities:

### Basic information

| Member | Description |
| --- | --- |
| `ctx.id` | Plugin id |
| `ctx.name` | Plugin name |
| `ctx.version` | Version number |
| `ctx.folder` | Absolute path of the plugin directory |
| `ctx.web_port` | Port of this plugin's standalone page (`0` if not enabled) |
| `ctx.web_url(host="127.0.0.1")` | Full URL of this plugin's standalone page; returns `""` if not enabled |

### Logging and configuration

| Method | Description |
| --- | --- |
| `ctx.log(msg)` | Output to the ILBB console, with a `[<plugin id>]` prefix |
| `ctx.cfg(key, default)` / `ctx.cfg()` | Read configuration |
| `ctx.set_cfg(key, value)` | Write configuration and persist it to disk |

### Registration

| Method | Description |
| --- | --- |
| `ctx.on_command(triggers, fn)` | Register a command; `triggers` can be a string or a list |
| `ctx.on_event(fn)` | Register an event callback `fn(ev, client)` |

### Sending and receiving messages

| Method | Description |
| --- | --- |
| `ctx.send_group(group_id, message)` | Send a group message; `message` can be a string or an array of message segments |
| `ctx.send_private(user_id, message)` | Send a private message |
| `ctx.send_text(ctx, text)` | **Reply according to the current chat context**; groups automatically get an @ |
| `ctx.send_image(ctx, png_bytes)` | Reply with an image according to the current chat context (converted to base64 internally) |
| `ctx.call_api(action, params, timeout=6.0)` | Call any OneBot API directly, returns the raw response dict |

### Data sources

| Method | Returns |
| --- | --- |
| `ctx.friends()` | `[{"user_id", "nickname", "remark"}, ...]` |
| `ctx.groups()` | `[{"group_id", "group_name", "member_count"}, ...]` |
| `ctx.group_members(gid)` | `[{"user_id", "nickname", "card", "role"}, ...]` |
| `ctx.self_account()` | Information of the currently logged-in account |

When an API call fails, these methods return an empty list; you do not need to guard against empty values or exceptions yourself.

---

## 7. Standalone Web page

To give a plugin its own console, two steps:

1. Write `"web": true` in `plugin.json` (optionally `web_title` / `web_path` / `web_port`).
2. Start an HTTP service in `setup(ctx)` using `ctx.web_port`.

ILBB embeds the plugin page into the main interface; the IP is taken automatically from the browser's current hostname, and the port is allocated according to the manifest.

```python
import os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
_httpd = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):     # don't spam the console with access logs
        pass

    def do_GET(self):
        full = os.path.join(WEB_DIR, "index.html")
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def setup(ctx):
    global _httpd
    if ctx.web_port:
        _httpd = ThreadingHTTPServer(("0.0.0.0", ctx.web_port), Handler)
        _httpd.daemon_threads = True
        threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    return True


def teardown():
    if _httpd:
        _httpd.shutdown()
        _httpd.server_close()
```

Port allocation rule: if `web_port` in the manifest has a valid value (1024–65535) it is used; otherwise the first free port is found starting from `PLUGIN_WEB_PORT_BASE` (default 7000).

---

## 8. Debugging and troubleshooting

**Required switches**: `PLUGIN_ENABLED=true`, `PLUGIN_HOT_RELOAD=true` in `.env`.

**Common debugging flow**:

1. Watch the ILBB console —— plugin log prefixes are `[插件]` and `[<your plugin id>]`.
2. Open the plugin panel in the Web interface —— you can see the plugin list, load status and configuration forms; the "misinstalled plugins" area shows concrete reasons such as `缺少 plugin.json` or `entry 不允许使用绝对路径`.
3. Click "Reload" to force a rescan, without waiting for the poll.
4. Edit code in the command line → save → wait 3 seconds → send a command to test directly.

**High-frequency pitfalls**:

| Symptom | Cause |
| --- | --- |
| Plugin does not appear | The directory has no `plugin.json`, or `plugin.json` is not valid JSON |
| Reports `找不到入口文件` | The name written in `entry` does not match the actual file name |
| Command does not respond | Commands are case-insensitive but have no `/`; make sure the name does not collide with the built-in commands (`help` / `meme` / `pair` / `名言` / `生成名言`) |
| Command throws an error | The exception is caught and an error card is returned; the stack trace is in the console |
| Configuration reads as empty | The `group_member` field depends on the group selected before it; if no group is selected there will be no options |
| Code changes do not take effect | The extension is not in the watch list (only `.py .json .html .js .css .txt .md .svg` are recognized) |
| State is lost | Module-level globals are cleared on reload; to persist, write to a file or use `set_cfg` |

**Security reminder**: plugin code runs inside the main process and has full file and network permissions. **Only install plugins from sources you trust**, and do not download plugin folders from unknown channels.

---

## 9. Copy a starter template

```bash
# Windows (PowerShell)
Copy-Item -Recurse plugins\example plugins\myplugin
```

```bash
# Linux / macOS
cp -r plugins/example plugins/myplugin
```

Then change `id` in `plugins/myplugin/plugin.json` to `myplugin` (matching the folder name exactly makes mistakes least likely), delete the sample parts you do not need in `main.py`, and start writing your own logic.

---

[Back to docs home](index.md) ｜ [中文](../zh/plugin-dev.md)

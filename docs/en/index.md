# ILBB Docs

**English** ｜ [中文](../zh/index.md)

This directory holds the complete documentation for "I Learning Bilibili Emoji Bot (ILBB)". The [README](../../README.md) in the root directory only covers what the project is; deployment and usage details all live here.

---

## Start here

**Deploying for the first time** → Go to [Choose a deployment](deploy.md) and pick the route that matches your machine. All three routes use uv to create the environment and install dependencies, and that page covers the parts they share.

**Already up and running** → Pick what you need from the categories below.

---

## Deployment

| What | Entry | Chinese version |
| --- | --- | --- |
| Choosing among the three routes, shared prerequisites, uv usage | [Choose a deployment](deploy.md) | [中文](../zh/deploy.md) |
| Deploy on Windows | [deploy-windows.md](deploy-windows.md) | [中文](../zh/deploy-windows.md) |
| Deploy on Linux | [deploy-linux.md](deploy-linux.md) | [中文](../zh/deploy-linux.md) |
| Deploy on an Android phone | [deploy-android.md](deploy-android.md) | [中文](../zh/deploy-android.md) |

## Usage

| What | Entry | Chinese version |
| --- | --- | --- |
| How every command works | [commands.md](commands.md) | [中文](../zh/commands.md) |
| What each config option does | [configuration.md](configuration.md) | [中文](../zh/configuration.md) |
| Connecting QQ (NapCat) | [platform-integration.md](platform-integration.md) | [中文](../zh/platform-integration.md) |

## Development

| What | Entry | Chinese version |
| --- | --- | --- |
| Writing your own plugin | [plugin-dev.md](plugin-dev.md) | [中文](../zh/plugin-dev.md) |

---

## Three concepts shared by all platforms

Understanding these three things will make the docs much easier to read.

**1. Configuration has three layers, in descending order of priority**
System environment variables → `.env` file → built-in code defaults. Values changed in the setup wizard and the admin panel are written back to files, with the same effect as editing `.env` by hand.

**2. Startup must be from the project root directory**
Inside the project, `cache`, `temp`, and `font` use relative paths. Starting from a different directory will report that the directory cannot be found.

**3. ILBB is the WebSocket server, NapCat is the client**
It is not ILBB connecting out to NapCat; rather, NapCat connects to ILBB's `6700` port using a "reverse WebSocket". If you get the direction backwards, it will never connect. See [platform-integration.md](platform-integration.md) for details.

---

## Architecture in one sentence

```
QQ client
   │  (NapCat logs in to QQ)
   ▼
NapCat ──reverse WebSocket──▶ core/ws_server.py (port 6700)
                              │
                              ├─▶ core/bot_commands.py  command routing (/meme /pair /quote)
                              │        └─▶ core/meme_service.py  meme composition
                              │        └─▶ core/bot_render.py   help image rendering
                              │        └─▶ plugin_manager     plugin commands
                              │
                              └─▶ app.py (Flask, port 5000) WebUI / REST / OpenAI-compatible layer /v1
```

---

## Running into problems

1. First check the "FAQ" at the end of the corresponding deployment doc.
2. Then check the "FAQ" in the root README.
3. If that still doesn't help, watch the terminal logs at startup — ILBB's logs are in Chinese, and the vast majority of errors will directly tell you what is missing and what to install.

---

[Back to docs home](index.md) ｜ [中文](../zh/index.md)

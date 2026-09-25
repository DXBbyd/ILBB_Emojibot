# ILBB Docs

**English** ｜ [中文](../zh/index.md)

This directory contains the complete documentation for "I Learning Bilibili Emoji Bot (ILBB)". The README only covers "what it is and how to get it running as fast as possible"; the details are all here.

---

## Start here

**New to this project** → Read the [README](../../README.md) in the root directory first, use "Quick Start" to get the service running on your machine, then come back to the docs.

**Already up and running** → Pick what you want to do from the table below.

| I want to... | Read this | English version |
| --- | --- | --- |
| Deploy on Windows | [deploy-windows.md](deploy-windows.md) | [English](../en/deploy-windows.md) |
| Deploy on Linux | [deploy-linux.md](deploy-linux.md) | [English](../en/deploy-linux.md) |
| Deploy on an Android phone | [deploy-android.md](deploy-android.md) | [English](../en/deploy-android.md) |
| Figure out how to use every command | [commands.md](commands.md) | [English](../en/commands.md) |
| Write my own plugin | [plugin-dev.md](plugin-dev.md) | [English](../en/plugin-dev.md) |
| Connect QQ (NapCat) | [platform-integration.md](platform-integration.md) | [English](../en/platform-integration.md) |
| Look up what a given config option does | [configuration.md](configuration.md) | [English](../en/configuration.md) |

---

## How to choose among the three deployment routes

| Scenario | Recommended route | Reason |
| --- | --- | --- |
| Tinkering and debugging on a personal computer | **Windows** | One command to start; finish the setup wizard and it's ready to use |
| Running long-term, for use in a group | **Linux** | Stable and resource-efficient; can be set up with systemd daemon and auto-restart |
| No server, only an old phone | **Android** | It can run under Termux, but it is **not fully verified** — treat it as an experimental option |

> Whichever route you take, it is recommended to first get the `/setup` wizard working and finish downloading the assets on Windows or Linux before considering a migration.

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

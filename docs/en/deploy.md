# Choose a Deployment

[中文](../zh/deploy.md) ｜ **English** ｜ [Docs home](index.md)

Three routes for three kinds of machines. The steps do not overlap, so pick one and follow it through. Each runs from installing uv to auto-start on boot; the code is the same, and the differences come down to system libraries, startup method and permissions.

| Your machine | Take this route | What you will run into |
| --- | --- | --- |
| Windows 10 / 11 (64-bit) | [Windows deployment](deploy-windows.md) | You can skip installing Python entirely and let uv fetch it; copy `icudtl.dat` into the Python install dir; open ports 5000 / 6700 in the firewall |
| Linux server / cloud host | [Linux deployment](deploy-linux.md) | Install `libfontconfig1`, `libgl1` and friends; keep it alive with systemd and put Nginx in front |
| Android phone (Termux) | [Android deployment](deploy-android.md) | It runs, but there is no prebuilt `skia-python` wheel for phones so you compile it yourself; not thoroughly validated, test at your own risk |

If this is your first time with the project, get `/setup` working and the assets downloaded on your own machine first, then move to a server or a phone.

---

## Shared by all three routes

### Python version

**3.10 – 3.13 (64-bit), 3.13 recommended.** The version and architecture are hard requirements: `skia-python`, `Pillow` and similar only publish prebuilt wheels, and a mismatch fails to install outright. **3.14 and newer will not work** — the meme engine pins `Pillow ^10.0.0`, and 10.x predates 3.14 with no matching wheel. With uv you can just let it pull a 3.13 for you instead of wrestling with the system Python.

### Manage dependencies with uv

uv is a standalone executable. Install it one of three ways; after that, every route uses exactly the same commands.

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux / macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

If neither script works for you (or you would rather keep uv inside Python), fall back to pip:

```bash
pip install uv
```

On Linux / macOS the script install puts uv outside your PATH — open a new terminal, or run:

```bash
source $HOME/.local/bin/env
```

Confirm it is there:

```bash
uv --version
```

Creating the environment and installing are just these two lines, identical everywhere:

```bash
uv venv --python 3.13
uv pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

The meme engine under `vendor/meme-generator-main/` needs no separate install; the program puts it on the module search path at startup.

### Configuration and first run

Every `.env` option has a default, so you can leave the file alone and configure things in the browser instead. **Start the service from the project root** — `cache`, `temp` and `font` are resolved relatively — then open `http://127.0.0.1:5000/setup` and let the wizard handle the environment check, asset download and basic config in one pass.

### Ports

5000 is the web workbench, 6700 is the OneBot V11 reverse WS. NapCat has to be able to reach both, so remember to open them in the firewall or security group on a server.

---

## After it is running

A running service is only the first step. Follow [Platform Integration](platform-integration.md) to connect NapCat so the bot can actually work in QQ. For command usage see the [Command Manual](commands.md), for what each option means see [Configuration](configuration.md), and if you want to extend the project see the [Plugin Development Guide](plugin-dev.md).

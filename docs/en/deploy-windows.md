# Deploying ILBB on Windows

**English** ｜ [中文](../zh/deploy-windows.md) ｜ [Docs home](index.md)

Applies to: Windows 10 / 11 (64-bit). The whole process takes about 15 minutes, of which the asset download time depends on your network speed.

---

## 1. Prerequisites

| Item | Requirement | Notes |
| --- | --- | --- |
| Operating system | Windows 10 / 11 64-bit | 32-bit systems cannot install `skia-python` |
| Python | **3.10 – 3.13 (64-bit), 3.13 recommended** | The version is fixed on purpose: `skia-python`, `Pillow` and friends only ship prebuilt wheels, so a version/architecture mismatch fails outright. **3.14 is not supported** (the meme engine pins `Pillow ^10.0.0`, and 10.x has no 3.14 wheel) |
| Disk space | ≥ 2 GB | Project + virtual environment + meme assets are about 600 MB |
| Network | Able to reach the internet | The first startup needs network access to complete the meme assets |
| Ports | 5000, 6700 available | 5000 = workbench, 6700 = OneBot V11 |

---

## 2. Prepare Python 3.13

If the machine has no suitable Python, you can skip this whole step: once uv is installed in section 4, `uv venv --python 3.13` downloads a managed 3.13 build by itself. To install your own copy, read on.

1. Open [python.org/downloads](https://www.python.org/downloads/) and download the **Windows installer (64-bit)** for version 3.13.
2. During installation, **make sure to check `Add python.exe to PATH`**.
3. After installing, open PowerShell to verify:

```powershell
python --version
```

It should output `Python 3.13.x`. If it says the command cannot be found, PATH was not set up; reinstall and check the box, or manually add the Python installation directory to PATH.

> If multiple versions of Python are installed on the machine, remember that this project needs **3.10 – 3.13 (3.13 recommended)** — all later commands are invoked through `.venv\Scripts\python.exe` and do not rely on PATH, so as long as an allowed version was used when creating the venv, it is fine. **Do not use 3.14**: Pillow 10.x, which the meme engine depends on, has no 3.14 wheel.

---

## 3. Get the code

```powershell
git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git
cd ILBB_Emojibot
```

> Current release lives on the **`beta`** branch (v0.1.0-beta). The repository does not include the meme assets (~254 MB); the setup wizard downloads them on first run.

If you don't have git, you can also just click `Code → Download ZIP` on the GitHub page and extract it.

---

## 4. Install uv, create the environment, install dependencies

**In the project root directory** (the level where you can see `app.py`), run:

Install uv first. On Windows the PowerShell one-liner is the smoothest:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Confirm it is on PATH:

```powershell
uv --version
```

> If the script is blocked by the network, fall back to `pip install uv`; that works on any platform.

Then create the virtual environment and install the dependencies:

```powershell
uv venv --python 3.13
uv pip install -r requirements.txt
```

`uv venv --python 3.13` finds a 3.13 interpreter on its own and downloads one if your machine does not have it, so the Python already installed on the system does not matter. Every later command goes through `.venv\Scripts\python.exe`, which likewise does not depend on PATH.

The dependency list is `requirements.txt` at the repository root, and it covers two things: the bot itself needs `flask`, `requests` and `websockets`; the meme engine under `vendor/meme-generator-main/` ships as source and is not installed through pip, but the dozen or so packages it declares cannot be resolved automatically, so the list enumerates them. `Pillow` is pinned to 10.x there — that is the range the engine locks, and 11 or 12 will break meme generation.

> Install dependencies with `uv pip install`, not bare `pip install`. Bare pip very likely lands in your system Python, while uv resolves the `.venv` in the current directory by default and will not wander off. To see what actually went into the environment, use `uv pip list`.

---

## 5. Configuration

```powershell
copy .env.example .env
```

Every item in `.env` has a default value and a Chinese comment, and **you can leave it alone for now** — changing it later in the setup wizard works the same way. If you want to change things here, the ones most commonly touched are:

| Variable | Default | When to change |
| --- | --- | --- |
| `WEB_HOST` | `0.0.0.0` | Change to `127.0.0.1` if you only want local access |
| `WEB_PORT` | `5000` | Change when the port is occupied |
| `INIT_ADMIN_PASSWORD` | empty | Fill it in if you want to set your own initial admin password; otherwise a random one is generated and printed in the terminal |
| `BOT_NAME` | `我在哔哩学习` | Bot nickname, shown in the help image title |
| `BOT_PREFIX` | `/` | Command prefix; changing it to something like `#` also works |

---

## 6. Start and run the setup wizard

In the project root directory, run:

```powershell
& .venv\Scripts\python.exe app.py
```

Seeing logs like the following means success (the admin password only appears the first time):

```
[ILBB] 管理密码：xxxxxxxx
 * Running on http://0.0.0.0:5000
```

Open `http://127.0.0.1:5000` in your browser; it will automatically jump to the `/setup` wizard. Go through the four steps:

1. **Environment self-check** — checks those 7 dependencies one by one, and for anything missing it points you at `uv pip install -r requirements.txt`. Click "Re-check" to check again.
2. **Meme assets** — one-click online download of the asset library (`vendor/.../meme_generator/memes/`). This step is the slowest, and the most likely to get stuck on network issues.
3. **Basic configuration** — bot nickname, command prefix, ports, etc.
4. **Done** — enter the workbench.

> It doesn't matter if the asset step fails; you can skip it and retry later from the settings page. Without assets, `/meme` will report that no meme can be found.

---

## 7. Firewall and LAN access

If you only use it **on this machine**, you can stop reading here.

To let other devices on the same LAN (or NapCat running on another machine) access it, you need to open the ports. Open PowerShell **as administrator**:

```powershell
New-NetFirewallRule -DisplayName "ILBB WebUI 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
New-NetFirewallRule -DisplayName "ILBB OneBot 6700" -Direction Inbound -Protocol TCP -LocalPort 6700 -Action Allow
```

Then use `ipconfig` to find the machine's LAN IP (in the form `192.168.x.x`), and other devices can access it at `http://192.168.x.x:5000`.

> To delete the rules: `Remove-NetFirewallRule -DisplayName "ILBB WebUI 5000"`.

---

## 8. Advanced: auto-start on boot

### Option 1: startup script (simplest)

Create `start.bat` in the project root directory:

```bat
@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe app.py
pause
```

After that, just double-click it to run. Note that `cd /d "%~dp0"` cannot be removed — it must start in the project root directory.

### Option 2: Task Scheduler

1. Open "Task Scheduler" → "Create Task".
2. "General" tab: check "Run whether user is logged on or not", check "Run with highest privileges".
3. "Triggers" tab: New → "At log on" or "At startup".
4. "Actions" tab: for Program/script, enter the **full path** to `.venv\Scripts\python.exe`; for "Start in", enter the **full path** to the project root directory (this one is easy to miss, and if you miss it you'll get errors that `cache` / `temp` cannot be found).
5. For the arguments, enter `app.py`.

---

## FAQ

**Startup reports a `SkIcuLoader / icudtl` warning**
`skia-python` needs an ICU text data file. Copy `.venv\Lib\site-packages\icudtl.dat` to the **Python installation directory** (the same level as `python.exe`). If there is no warning, no need to bother.

**`uv pip install skia-python` reports no matching version**
Three possibilities: ① Python is not in the 3.10 – 3.13 range (3.14 stalls on Pillow 10.x having no wheel); ② the installed Python is 32-bit; ③ uv is too old, update it with `uv self update`. Check them in order; as a last resort, rebuild the environment with `uv venv --python 3.13 --clear` and reinstall.

**The setup wizard keeps showing missing dependencies, but `uv pip list` clearly shows them**
They went into a different Python. Recreate the environment from the project root with `uv venv --python 3.13`, then install again with `uv pip install -r requirements.txt`. If only individual packages are missing — `toml`, `loguru` — that same command fills them in; do not reinstall them one by one by name.

**Startup reports that `cache` / `temp` / `font` cannot be found**
You are not starting from the project root directory. `cd` to the level where you can see `app.py`, then run it.

**The path contains Chinese characters or spaces — will that cause problems?**
It generally runs, but **a somewhat deeper pure-English directory is safer**. If you hit strange import errors, try a different path first.

**Port 5000 is occupied**
Change `WEB_PORT` in `.env` (for example to `5001`), or find the process occupying it: `netstat -ano | findstr :5000`.

**There is a `meme_generator.pth` in `.venv\Lib\site-packages\` pointing to another computer**
Delete it; it doesn't affect running — the program attaches `vendor/meme-generator-main` to the module search path by itself at startup.

**Startup reports `FileNotFoundError: …\meme_generator\memes`**
Meme assets are not committed, so a fresh clone has no `meme_generator\memes` folder — and the engine walks that folder on import, which fails the startup outright and leaves the wizard that downloads those assets unreachable. The app creates the empty folder on boot; on an older checkout, create it yourself and start again:

```powershell
New-Item -ItemType Directory -Force vendor\meme-generator-main\meme_generator\memes
```

**Forgot the admin password**
Delete `api_keys.json` and restart; it will be regenerated and printed to the terminal.

---

## Post-install verification (optional)

One command to verify that the dependencies are complete:

```powershell
& .venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'vendor/meme-generator-main'); import flask, requests, PIL, websockets, numpy, skia, meme_generator; print('deps OK, meme count:', len(meme_generator.get_memes()))"
```

Run this from the project root. The `sys.path.insert` part attaches the vendored engine — only `app.py` does that automatically at startup, so a standalone command has to do it itself. Seeing a number such as `deps OK, meme count: 295` means you are basically good. For a more comprehensive check, just look at step 1 of the setup wizard (it also checks the `cache` / `temp` / `font` / background image directories, the Python version, the engine version, the number of recognizable memes, and the admin password status).

---

## Connect NapCat

A running service is only the first step. In NapCat's (NC) network settings, add a reverse WebSocket entry pointing at `ws://<this machine's LAN IP>:6700/onebot/v11/ws`, set the message format to `array`, and keep the Token aligned with `WS_ACCESS_TOKEN` in `.env` (leave it empty if you never set one).

Find the LAN IP with `ipconfig` (look for an IPv4 address such as `192.168.x.x`), and open port 6700 from an administrator PowerShell:

```powershell
New-NetFirewallRule -DisplayName "ILBB OneBot 6700" -Direction Inbound -Protocol TCP -LocalPort 6700 -Action Allow
```

After saving, go back to the real-time event stream in the ILBB admin panel — a connection count of 1 means it is through. Full steps and troubleshooting are in [Platform Integration](platform-integration.md).

---

[Back to docs home](index.md) ｜ [中文](../zh/deploy-windows.md)

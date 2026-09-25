# Deploying ILBB on Windows

**English** ｜ [中文](../zh/deploy-windows.md) ｜ [Docs home](index.md)

Applies to: Windows 10 / 11 (64-bit). The whole process takes about 15 minutes, of which the asset download time depends on your network speed.

---

## 1. Prerequisites checklist

| Item | Requirement | Notes |
| --- | --- | --- |
| Operating system | Windows 10 / 11 64-bit | 32-bit systems cannot install `skia-python` |
| Python | **3.13 (64-bit)** | Required; `skia-python` is a precompiled package, and it simply will not install if the version does not match |
| Disk space | ≥ 2 GB | Project + virtual environment + meme assets are about 600 MB |
| Network | Able to reach the internet | The first startup needs network access to complete the meme assets |
| Ports | 5000, 6700 available | 5000 = workbench, 6700 = OneBot V11 |

---

## 2. Install Python 3.13

1. Open [python.org/downloads](https://www.python.org/downloads/) and download the **Windows installer (64-bit)** for version 3.13.
2. During installation, **make sure to check `Add python.exe to PATH`**.
3. After installing, open PowerShell to verify:

```powershell
python --version
```

It should output `Python 3.13.x`. If it says the command cannot be found, PATH was not set up; reinstall and check the box, or manually add the Python installation directory to PATH.

> If multiple versions of Python are installed on the machine, remember that this project needs 3.13 — all later commands are invoked through `.venv\Scripts\python.exe` and do not rely on PATH, so as long as 3.13 was used when creating the venv, it is fine.

---

## 3. Get the code

```powershell
git clone -b beta https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

> Current release lives on the **`beta`** branch (v0.1.0-beta). The repository does not include the meme assets (~254 MB); the setup wizard downloads them on first run.

If you don't have git, you can also just click `Code → Download ZIP` on the GitHub page and extract it.

> The repository **does not include meme assets** (about 254 MB); this is intentional. After cloning, the setup wizard completes them over the network.

---

## 4. Create a virtual environment and install dependencies

**In the project root directory** (the level where you can see `app.py`), run:

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -U pip
& .venv\Scripts\python.exe -m pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

What the seven dependencies do:

| Package | Purpose |
| --- | --- |
| `flask` | Web workbench and REST API |
| `requests` | Fetch QQ avatars, random background images |
| `pillow` | Image processing (pair cards, quote images) |
| `websockets` | OneBot V11 reverse WebSocket server |
| `skia-python~=144.0` | Drawing library used by the meme composition engine (**must be 144.x**) |
| `numpy` | Numerical computation dependency of the engine |
| `meme engine` | Already shipped with the code at `vendor/meme-generator-main/`, **no pip install needed**; mounted automatically at startup |

> Be sure to use `& .venv\Scripts\python.exe -m pip ...`. Typing `pip install` directly will very likely install into the system Python, and then the setup wizard will keep reporting "missing dependencies".

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

1. **Environment self-check** — checks those 7 dependencies one by one, and for any that are missing it directly gives the corresponding install command. Click "Re-check" to check again.
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

**`pip install skia-python` reports no matching version**
Three possibilities: ① Python is not 3.13; ② the installed Python is 32-bit; ③ pip is too old. Check them in order, starting with `& .venv\Scripts\python.exe -m pip install -U pip`.

**The setup wizard keeps showing missing dependencies, but they clearly appear in `pip list`**
They were installed into a different Python. You must use `& .venv\Scripts\python.exe -m pip install ...`.

**Startup reports that `cache` / `temp` / `font` cannot be found**
You are not starting from the project root directory. `cd` to the level where you can see `app.py`, then run it.

**The path contains Chinese characters or spaces — will that cause problems?**
It generally runs, but **a somewhat deeper pure-English directory is safer**. If you hit strange import errors, try a different path first.

**Port 5000 is occupied**
Change `WEB_PORT` in `.env` (for example to `5001`), or find the process occupying it: `netstat -ano | findstr :5000`.

**There is a `meme_generator.pth` in `.venv\Lib\site-packages\` pointing to another computer**
Delete it; it doesn't affect running — the program attaches `vendor/meme-generator-main` to the module search path by itself at startup.

**Forgot the admin password**
Delete `api_keys.json` and restart; it will be regenerated and printed to the terminal.

---

## Post-install self-check (optional)

One command to verify that the dependencies are complete:

```powershell
& .venv\Scripts\python.exe -c "import flask,requests,PIL,websockets,numpy,skia; print('base OK'); from meme_generator import get_memes; print('meme OK')"
```

If it outputs the two lines `base OK` / `meme OK`, you are basically good. For a more comprehensive check, just look at step 1 of the setup wizard (it also checks the `cache` / `temp` / `font` / background image directories, the Python version, the engine version, the number of recognizable memes, and the admin password status).

---

[Back to docs home](index.md) ｜ [中文](../zh/deploy-windows.md)

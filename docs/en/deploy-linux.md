# Deploying ILBB on Linux

**English** ｜ [中文](../zh/deploy-linux.md) ｜ [Docs home](index.md)

Applies to: common distributions such as Debian / Ubuntu / CentOS / Arch, on both x86_64 and arm64. The examples below use Ubuntu; for other distributions, just swap out the package management commands.

> **Do not copy `.venv` over directly from Windows** — Windows binary packages cannot be used on Linux, so you must recreate the environment. Copy only the code.

---

## 1. Prerequisites

| Item | Requirement | Notes |
| --- | --- | --- |
| Architecture | x86_64 / arm64 | 32-bit (armv7 / i386) cannot install `skia-python` |
| Python | **3.10 – 3.13, 3.13 recommended** | The version is fixed on purpose: `skia-python`, `Pillow` and friends only ship prebuilt wheels, so a version mismatch fails outright. **3.14 is not supported** (the meme engine pins `Pillow ^10.0.0`, and 10.x has no 3.14 wheel) |
| Disk | ≥ 2 GB | Project + venv + assets |
| System libraries | fontconfig, libGL, libjpeg | Missing them causes missing `.so` errors at runtime |
| Path | **No spaces, no Chinese characters** | `/root/ilbb-bot` is recommended |
| Ports | 5000, 6700 | 5000 = workbench, 6700 = OneBot V11 |

---

## 2. Install system dependencies

```bash
sudo apt-get update
sudo apt-get install -y libfontconfig1 libgl1 libjpeg-dev
```

The project already ships with 3 Chinese fonts (in `font/`), which is enough; if you want to add another set, you can install:

```bash
sudo apt-get install -y fonts-wqy
```

---

## 3. Install uv

Dependencies are managed entirely by [`uv`](https://docs.astral.sh/uv/). You do not have to wrestle with the system Python either: `uv venv --python 3.13` in section 5 fetches a managed 3.13 build on its own.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env       # or reopen the terminal
uv --version
```

> If the script is blocked by the network, fall back to `pip install uv` (on Ubuntu the system pip may first need `sudo apt-get install -y python3-pip`).
>
> You can also compile 3.13 yourself, or use the deadsnakes PPA (Ubuntu): `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.13 python3.13-venv`.
>
> The version requirement is fixed at **3.10 – 3.13**: 3.14 will not install, because the meme engine pins `Pillow ^10.0.0` and Pillow 10.x has no 3.14 wheel.

---

## 4. Get the code

```bash
mkdir -p /root/ilbb-bot && cd /root/ilbb-bot
git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git .
```

`/root` is the home directory reserved for root, with permissions 700, so an ordinary user cannot even enter it. Run the commands above as root: `sudo -i` into a root shell, or log in as root directly if that is how your VPS is set up. Once the project sits at `/root/ilbb-bot`, the code and the `.venv` both belong to root, and the later `uv venv` step, the startup command and the systemd unit are all configured for root as well. The trade-off is that the service runs with the same privileges as the system, which is fine on a single-user machine; on a shared machine, the safer choice is `/opt/ilbb-bot` plus a dedicated run user named in the unit's `User=`.

> When copying only the code, you need to bring along: `app.py`, `_serve.py`, `core/`, `vendor/`, `templates/`, `static/`, `font/`, `plugins/`, `.env.example`. Skip `.venv`, `cache`, `temp`.

---

## 5. Create the environment and install dependencies

```bash
cd /root/ilbb-bot
uv venv --python 3.13
uv pip install -r requirements.txt
```

`uv pip install` resolves the `.venv` in the current directory by default, so running it from the project root will not install anywhere unexpected. To see what went in, use `uv pip list`.

**The meme engine itself does not need to be installed**: the source code in `vendor/meme-generator-main/` is automatically attached to the module search path when the program starts. Its own declared dependencies, however, do have to be present; the ones most easily missed are `toml`, `loguru`, `httpx` and `pil-utils`, and a single missing one stops startup with `ModuleNotFoundError`. `requirements.txt` enumerates all of them, which is why the one command above is enough.

> If you see an editable-install record in `uv pip list` such as `-e /old-path/vendor/meme-generator-main` pointing to an old machine, you can clean it up with `uv pip uninstall meme-generator`; leaving it also does no harm.

---

## 6. Configuration

```bash
cp .env.example .env
```

The two items usually needing changes on Linux:

| Variable | Default | Suggestion |
| --- | --- | --- |
| `WEB_HOST` | `0.0.0.0` | Keep the default if the server provides the service externally; change to `127.0.0.1` if only going through a local reverse proxy |
| `WS_HOST` | `0.0.0.0` | Keep the default if NapCat is on another machine |

All the other items have default values; you can leave them as is and configure them in the setup wizard.

---

## 7. Start and run the setup wizard

```bash
cd /root/ilbb-bot
./.venv/bin/python app.py
```

Open `http://<server-IP>:5000` in your browser; it will enter the `/setup` wizard automatically. Go through the four steps (environment self-check → asset download → basic configuration → done).

> It's fine if the server has no graphical interface; just use your own computer's browser to access the server IP.

---

## 8. Advanced: productionization

### Using gunicorn to handle concurrency

```bash
uv pip install gunicorn
./.venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

`-w 2` is the number of workers; adjust it according to the number of CPU cores (generally `2 × cores + 1`). Note that ILBB has in-memory state internally (current WS connections, event buffers, image cache index), and **multiple workers do not share it**, so starting with `-w 1` or `-w 2` is recommended; do not blindly increase it.

### systemd daemon (recommended)

Create `/etc/systemd/system/ilbb.service`:

```ini
[Unit]
Description=ILBB Emoji Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ilbb-bot
ExecStart=/root/ilbb-bot/.venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` **must** be the project root directory, otherwise it will report that `cache` / `temp` / `font` cannot be found. `User=root` is what pairs with `/root/ilbb-bot`: that directory is mode 700, so a systemd service running as any other user cannot read into it at all. If you move the project elsewhere, remember to change `User=`, `WorkingDirectory` and `ExecStart` together.

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ilbb
sudo systemctl status ilbb
sudo journalctl -u ilbb -f      # view live logs
```

### Nginx reverse proxy (optional)

If you want ILBB to go through 80/443 or have HTTPS:

```nginx
server {
    listen 80;
    server_name ilbb.example.com;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

> Only proxy the WebUI (5000). OneBot's 6700 is WebSocket and is connected directly by NapCat, so it generally does not need to go through Nginx; if you really want to proxy it, extra configuration of the `Upgrade` / `Connection` headers is required.

---

## FAQ

**Startup reports a `SkIcuLoader / icudtl` warning**
After installing `skia-python`, copy `.venv/lib/python3.13/site-packages/icudtl.dat` to Python's base directory. If there is no warning, you can skip this.

**Runtime reports a missing `.so`**
The system is missing a library; install it as prompted:

```bash
sudo apt-get install -y libfontconfig1 libgl1 libjpeg-dev
```

**`uv pip install skia-python` reports no matching version**
Troubleshoot: ① Python is not in the 3.10 – 3.13 range (3.14 stalls on Pillow 10.x having no 3.14 wheel); ② the Python running is 32-bit (`./.venv/bin/python -c "import platform;print(platform.architecture())"` should be `('64bit', ...)`); ③ the architecture is something like armv7 with no wheel available, in which case you have to switch to arm64 or x86_64. As a last resort, rebuild the environment with `uv venv --python 3.13 --clear` and reinstall.

**The setup wizard keeps showing missing dependencies**
The packages did not land in this project's `.venv`. Run `uv pip list` in the project root to check what is actually there, then reinstall with `uv pip install -r requirements.txt`. If only a few packages are missing — `toml`, `loguru` and the like are the usual suspects — that same command fills them in; do not reinstall them one by one by name.

**The path has spaces or Chinese characters, causing import errors**
Move the project to a clean path like `/root/ilbb-bot`.

**systemd fails to start, and the log reports a missing directory**
`WorkingDirectory` was not set to the project root directory.

**The port is occupied**
Use `sudo ss -lntp | grep -E '5000|6700'` to find the process occupying it.

**Forgot the admin password**
Delete `api_keys.json` and restart; it will be regenerated and printed.

---

## Post-install verification (optional)

```bash
./.venv/bin/python -c "import sys; sys.path.insert(0,'vendor/meme-generator-main'); import flask, requests, PIL, websockets, numpy, skia, meme_generator; print('deps OK, meme count:', len(meme_generator.get_memes()))"
```

Run this from the project root. The `sys.path.insert` part attaches the vendored engine — only `app.py` does that automatically at startup, so a standalone command has to do it itself. Seeing a number such as `deps OK, meme count: 295` means it passed. For a more comprehensive check, look at step 1 of the setup wizard.

---

## Connect NapCat

A running service is only the first step. In NapCat's (NC) network settings, add a reverse WebSocket entry pointing at `ws://<this machine's LAN IP>:6700/onebot/v11/ws`, set the message format to `array`, and keep the Token aligned with `WS_ACCESS_TOKEN` in `.env` (leave it empty if you never set one).

Find the LAN IP with `ip -4 addr show` or `hostname -I`, and open port 6700:

```bash
sudo ufw allow 6700/tcp
```

After saving, go back to the real-time event stream in the ILBB admin panel — a connection count of 1 means it is through. Full steps and troubleshooting are in [Platform Integration](platform-integration.md).

---

[Back to docs home](index.md) ｜ [中文](../zh/deploy-linux.md)

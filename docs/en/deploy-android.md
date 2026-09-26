# Deploying ILBB on Android

**English** ｜ [中文](../zh/deploy-android.md) ｜ [Docs Home](index.md)

> **Important notice: the Android route is an experimental approach and the author has not fully verified it.** The steps below are a workable path derived from the Linux dependency chain, but the Android environment is heavily fragmented (CPU architecture, OS version, and Termux version all affect the result). Please test it yourself, and feedback is welcome.

---

## 1. Think It Through First: What You Will Hit on Android

Before you start, get to know four real-world pitfalls:

| Pitfall | Explanation | Workaround |
| --- | --- | --- |
| **`skia-python` has no native Android wheel** | Termux's Python targets Android, and there is no matching prebuilt package on PyPI, so pip tries to build from source and usually fails (it has to compile Skia itself, which is basically impossible to finish on a phone) | Take the **proot-distro with Ubuntu** route so that pip believes it is on a standard Linux |
| **CPU architecture** | You must have **arm64** (aarch64) to get a Linux wheel; 32-bit older machines (armv7 / armeabi) have no wheel, so give up on them directly | Confirm the device is 64-bit; `uname -m` should output `aarch64` |
| **Killed in the background** | Android cleans up background processes, so a long-running service gets killed by the system | Run `termux-wake-lock` inside Termux, and disable battery optimization for Termux in the system settings |
| **NapCat also needs somewhere to run** | ILBB is only a WebSocket server; you still need NapCat to log in to QQ and connect to it | Most people run NapCat on a PC/server and have it connect back to this phone; a phone-only setup requires finding another environment that can run NapCat |

**Conclusion**: if you just want to "see whether it can run at all", take Option A; if your goal is long-term always-on hosting, it is better to use a Linux server directly (see [deploy-linux.md](deploy-linux.md)).

---

## 2. Option A (Recommended): Ubuntu Inside Termux + proot-distro

The idea: Termux only provides a Linux shell, while the real runtime environment is the Ubuntu inside the container, so that the manylinux wheel of `skia-python` can be installed normally.

### 1. Install Termux

Install it from [F-Droid](https://f-droid.org/packages/com.termux/). **Do not use the old version on Google Play** (it has not been updated for a long time and the package sources will fail).

### 2. Basic Preparation

```bash
pkg update && pkg upgrade -y
pkg install -y proot-distro git
termux-wake-lock
```

`termux-wake-lock` is used to stop the system from freezing Termux when it sleeps; use `termux-wake-unlock` to release it.

### 3. Install the Ubuntu Container

```bash
proot-distro install ubuntu
proot-distro login ubuntu
```

From here on, all commands are executed inside this Ubuntu environment (the prompt will change). Use `exit` to leave; next time you come back it is still `proot-distro login ubuntu`.

### 4. Install System Dependencies and uv

```bash
apt-get update
apt-get install -y curl git libfontconfig1 libgl1 libjpeg-dev
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv --version
```

Installing uv is how the environment and the dependencies get built, and it pulls down Python 3.13 along the way, so there is no need to install a Python of your own inside the container. If the script is blocked by the network, run `apt-get install -y python3-pip` first and fall back to `pip install uv`.

### 5. Get the Code, Create the Environment, Install Dependencies

```bash
mkdir -p /root/ilbb-bot && cd /root/ilbb-bot
git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git .

uv venv --python 3.13
uv pip install -r requirements.txt
```

Inside the container you are root and `/root` is the home directory, so there is no `sudo` to type and no permission trouble to hit. `/root/ilbb-bot` is only a folder set aside for the project; another name, or a spot under `/home`, works just as well. The single requirement is that the path contains **no spaces and no Chinese characters**. What you do need to avoid is shared storage such as `/sdcard`: it is an external-storage mount with no execute permission, so `.venv/bin/python` will fail to start. One more thing: `~` resolves to `/root` inside the container but to `/data/data/com.termux/files/home` back in native Termux, so use absolute paths in any startup command you write yourself.

**This step decides success or failure**. If `skia-python` installs successfully, the rest of the road is basically clear; if it gets stuck compiling or reports that the version cannot be found, first confirm that `uname -m` is `aarch64`, then confirm that Python is 64-bit **3.10 – 3.13** (3.13 recommended). **3.14 will not work**: Pillow 10.x, which the meme engine depends on, has no 3.14 wheel.

### 6. Configure and Start

```bash
cp .env.example .env
./.venv/bin/python app.py
```

After starting, open `http://127.0.0.1:5000` in the **phone browser** and go through the `/setup` wizard page (environment self-check → asset download → basic configuration → done).

> The asset download is about 254 MB, so mind your mobile data. You can also download the assets on a PC first and then copy the entire `vendor/meme-generator-main/meme_generator/memes/` directory into the phone.

### 7. Let Other Devices on the LAN Access It

The phone and the machine running NapCat must be on the same LAN. Look up the phone's IP:

```bash
ip -4 addr show | grep inet
```

Then point the reverse WS in NapCat to `ws://<phone-IP>:6700/onebot/v11/ws`.

> To access port 5000 from outside the phone, use `http://<phone-IP>:5000`.

---

## 3. Option B: Termux Native (Very Likely Fails to Install skia)

Without a container, use Termux's own Python directly:

```bash
pkg install -y python git
termux-wake-lock
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git ~/ILBB_Emojibot && cd ~/ILBB_Emojibot
uv venv --python 3.13
uv pip install -r requirements.txt      # in most cases this stalls on skia-python
```

**If `skia-python` fails to install**, that means this route does not work on your machine, so go back to Option A. Some alternative ideas for pure-text scenarios (for example, running only the WebUI without emoji composition) require code changes and are outside the scope of this document.

---

## 4. Performance and Experience Expectations

| Item | Expectation |
| --- | --- |
| First startup | Noticeably slower than a PC (on the order of 1 minute) |
| Single emoji composition | A few seconds to a dozen or so seconds (depends on the device model and the complexity of the emoji) |
| Memory usage | Several hundred MB; low-memory devices may get killed |
| Long-term always-on hosting | Requires `termux-wake-lock` + disabling battery optimization, and stability is still not guaranteed |

If `/meme` often times out, you can lower `BOT_MAX_IMAGE_MB` and raise `BOT_COOLDOWN_SEC` in `.env` to reduce concurrency pressure.

---

## 5. Post-Deployment Confirmation

Run through the following after deployment; all of them should hold:

- [ ] `uname -m` outputs `aarch64`
- [ ] `./.venv/bin/python -c "import platform;print(platform.architecture())"` outputs 64bit
- [ ] `./.venv/bin/python -c "import skia; print('skia OK')"` succeeds
- [ ] `./.venv/bin/python -c "from meme_generator import get_memes; print(len(get_memes()))"` can print the number of assets
- [ ] The phone browser can open `http://127.0.0.1:5000/setup`
- [ ] All four steps of the wizard page pass
- [ ] Another device on the LAN can open `http://<phone-IP>:5000`
- [ ] After NapCat's reverse WS connects, the "live event stream" in the admin panel shows logs scrolling

---

## 6. FAQ

**`pkg update` errors out and the package sources return 404**
You are using the Play Store version of Termux. Uninstall it and reinstall from F-Droid.

**`proot-distro install ubuntu` hangs or times out**
It is a network problem; switch networks and retry; you can also try `pkg install -y wget` first.

**`skia-python` fails halfway through compilation**
It means uv is trying to build from source, usually because the architecture is wrong (not aarch64) or the Python version is outside 3.10 – 3.13.

**The service disconnects after running for a while**
The system has frozen Termux. Run `termux-wake-lock` and set Termux's battery optimization to "not optimized / unrestricted" in the system settings.

**Startup reports that `cache` / `temp` / `font` cannot be found**
You did not start from the project root directory. `cd` to the level where you can see `app.py`.

**The phone cannot open `127.0.0.1:5000`**
Confirm that the service is actually running (the terminal should show `Running on http://0.0.0.0:5000`); do not set `WEB_HOST` to `127.0.0.1` (that way nothing other than the phone itself can reach it, though the phone's own local browser can).

---

If you hit a pitfall on this route, or if you got it working successfully, feedback with the specific device model, Android version, Termux source, and error messages is welcome, as it can save a lot of time for those who come after.

[Back to docs home](index.md) ｜ [中文](../zh/deploy-android.md)

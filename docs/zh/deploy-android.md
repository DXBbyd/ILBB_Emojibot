# 在安卓上部署 ILBB

[English](../en/deploy-android.md) ｜ **中文** ｜ [文档总览](index.md)

> **重要声明：安卓路线属于实验性方案，作者未做完整验证。** 下面的步骤是基于 Linux 依赖关系推导出的可行路径，但安卓环境碎片化严重（CPU 架构、系统版本、Termux 版本都会影响结果）。请自行测试，欢迎反馈。

---

## 一、先想清楚：安卓上跑会遇到什么

在动手之前，先了解四个现实中的坑：

| 坑 | 说明 | 应对 |
| --- | --- | --- |
| **`skia-python` 没有安卓原生 wheel** | Termux 的 Python 是 Android 目标，PyPI 上没有对应的预编译包，pip 会尝试从源码编译，通常失败（要编译 Skia 本体，手机上基本不可能完成） | 走 **proot-distro 装 Ubuntu** 的路线，让 pip 认为自己在一个标准 Linux 上 |
| **CPU 架构** | 必须是 **arm64**（aarch64）才有 Linux 版 wheel；32 位老机器（armv7 / armeabi）没有 wheel，直接放弃 | 确认机型是 64 位；`uname -m` 应输出 `aarch64` |
| **后台被杀** | Android 会清理后台进程，服务跑久了会被系统杀掉 | 在 Termux 里执行 `termux-wake-lock`，并在系统设置里关闭对 Termux 的电池优化 |
| **NapCat 也要有个地方跑** | ILBB 只是 WebSocket 服务端，还得有 NapCat 登录 QQ 并连过来 | 多数人的做法是 NapCat 跑在电脑/服务器上，反向连到这个手机；纯手机方案需要另找能跑 NapCat 的环境 |

**结论**：如果你只是想"试试能不能跑"，走方案 A；如果目的是长期挂机，建议直接用 Linux 服务器（见 [deploy-linux.md](deploy-linux.md)）。

---

## 二、方案 A（推荐）：Termux + proot-distro 里的 Ubuntu

思路：Termux 只提供一个 Linux 壳，真正的运行环境是容器里的 Ubuntu，这样 `skia-python` 的 manylinux wheel 就能正常装上。

### 1. 安装 Termux

从 [F-Droid](https://f-droid.org/packages/com.termux/) 安装。**不要用 Google Play 上的旧版本**（长期未更新，包源会失败）。

### 2. 基础准备

```bash
pkg update && pkg upgrade -y
pkg install -y proot-distro git
termux-wake-lock
```

`termux-wake-lock` 用来阻止系统休眠时冻结 Termux；想解除用 `termux-wake-unlock`。

### 3. 安装 Ubuntu 容器

```bash
proot-distro install ubuntu
proot-distro login ubuntu
```

之后的命令都在这个 Ubuntu 环境里执行（提示符会变）。想退出用 `exit`，下次再进来还是 `proot-distro login ubuntu`。

### 4. 装系统依赖与 uv

```bash
apt-get update
apt-get install -y curl git libfontconfig1 libgl1 libegl1 libjpeg-dev
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv --version
```

装 uv 是为了让它负责建环境和装依赖，顺带把 3.13 的 Python 也拉下来，容器里不用另装。脚本被网络挡住的话，先 `apt-get install -y python3-pip`，再用 `pip install uv` 兜底。

### 5. 取代码、建环境、装依赖

```bash
mkdir -p /root/ilbb-bot && cd /root/ilbb-bot
git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git .

uv venv --python 3.13
uv pip install -r requirements.txt
```

容器里你的身份就是 root，`/root` 是家目录，既不用 `sudo`，也不会碰到权限不足。`/root/ilbb-bot` 只是给项目腾一个独立文件夹，换成别的名字或者放到 `/home` 下面照样能跑，唯一的要求是路径**不含空格和中文**。真正要避开的是 `/sdcard` 这类共享存储：它是 Android 的外部存储挂载，没有执行权限，`.venv/bin/python` 会因为拿不到执行位而起不来。还有一点，`~` 在容器里指向 `/root`，退回到 Termux 原生环境却指向 `/data/data/com.termux/files/home`，所以自己写启动命令时用绝对路径更稳妥。

**这一步是成败关键**。如果 `skia-python` 顺利装完，后面的路基本就通了；如果卡在编译或报找不到版本，先确认 `uname -m` 是 `aarch64`，再确认 Python 是 64 位的 **3.10 – 3.13**（推荐 3.13）。**3.14 不行**：meme 引擎依赖的 Pillow 10.x 没有 3.14 的 wheel。

### 6. 配置并启动

```bash
cp .env.example .env
./.venv/bin/python app.py
```

启动后在**手机浏览器**打开 `http://127.0.0.1:5000`，走 `/setup` 引导页（环境自检 → 素材下载 → 基础配置 → 完成）。

> 素材下载要下约 254 MB，手机流量环境下注意。也可以用电脑先下好素材，再把 `vendor/meme-generator-main/meme_generator/memes/` 整个目录拷进手机。

### 7. 让局域网内其他设备访问

手机和 NapCat 所在机器要在同一局域网。查手机 IP：

```bash
ip -4 addr show | grep inet
```

然后在 NapCat 里把反向 WS 指向 `ws://<手机IP>:6700/onebot/v11/ws`。

> 从手机外部访问 5000 端口，用 `http://<手机IP>:5000`。

---

## 三、方案 B：Termux 原生（大概率装不上 skia）

不套容器，直接在 Termux 里跑，环境和依赖照样交给 uv：

```bash
pkg install -y python git
termux-wake-lock
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git ~/ILBB_Emojibot && cd ~/ILBB_Emojibot
uv venv --python 3.13
uv pip install -r requirements.txt      # 大概率卡在 skia-python
```

**如果 `skia-python` 装失败**，说明这条路在你这台机器上走不通，回头走方案 A。一些纯文本场景下的替代思路（例如只跑 WebUI 而不用表情合成）需要改代码，不在本文档支持范围内。

---

## 四、性能与体验预期

| 项目 | 预期 |
| --- | --- |
| 首次启动 | 明显慢于电脑（1 分钟级） |
| 单张表情合成 | 几秒到十几秒（取决于机型和表情复杂度） |
| 内存占用 | 数百 MB，低内存机型可能被杀 |
| 长时间挂机 | 需要 `termux-wake-lock` + 关闭电池优化，仍不保证稳定 |

如果 `/meme` 经常超时，可以在 `.env` 里把 `BOT_MAX_IMAGE_MB` 调小、`BOT_COOLDOWN_SEC` 调大，降低并发压力。

---

## 五、部署后确认

跑完上面的步骤，下面这些应该都成立：

- [ ] `uname -m` 输出 `aarch64`
- [ ] `./.venv/bin/python -c "import platform;print(platform.architecture())"` 输出 64bit
- [ ] `./.venv/bin/python -c "import skia; print('skia OK')"` 成功
- [ ] `./.venv/bin/python -c "from meme_generator import get_memes; print(len(get_memes()))"` 能打印素材数量
- [ ] 手机浏览器能打开 `http://127.0.0.1:5000/setup`
- [ ] 引导页四步全部通过
- [ ] 局域网内另一台设备能打开 `http://<手机IP>:5000`
- [ ] NapCat 反向 WS 连上后，后台「实时事件流」有日志滚动

---

## 六、常见问题

**`pkg update` 报错、包源 404**
用的是 Play 商店版本的 Termux。卸载后从 F-Droid 重装。

**`proot-distro install ubuntu` 卡住或超时**
网络问题，换网络重试；也可以先 `pkg install -y wget` 再试。

**`skia-python` 编译到一半失败**
说明 uv 在尝试从源码构建，通常是架构不对（非 aarch64）或 Python 版本不在 3.10 – 3.13。

**服务跑一会儿就断**
系统把 Termux 冻结了。执行 `termux-wake-lock`，并在系统设置里把 Termux 的电池优化设为「不优化 / 无限制」。

**启动报找不到 `cache` / `temp` / `font`**
不在项目根目录启动。`cd` 到能看到 `app.py` 的那一层。

**手机访问 `127.0.0.1:5000` 打不开**
确认服务确实在跑（终端里应有 `Running on http://0.0.0.0:5000`）；`WEB_HOST` 别设成 `127.0.0.1`（那样连手机自己以外的都访问不了，手机本机浏览器是可以的）。

---

## 七、连上 NapCat

跑到这里服务已经起来了，还差最后一步：把 NapCat（NC）接上，机器人才会在 QQ 里收消息。手机和 NapCat 所在机器要在同一局域网，然后在 NapCat 的网络配置里新增一项「反向 WebSocket」，URL 填 `ws://<手机IP>:6700/onebot/v11/ws`，消息格式选 `array`。

手机 IP 用 `ip -4 addr show | grep inet` 查。完整步骤和连不上的排查见 [消息平台对接](platform-integration.md)。

如果你在这条路线上踩到了坑，或者成功跑通了，欢迎反馈具体机型、Android 版本、Termux 来源和报错信息，能帮后面的人省很多时间。

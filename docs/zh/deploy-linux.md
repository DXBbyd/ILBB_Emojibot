# 在 Linux 上部署 ILBB

[English](../en/deploy-linux.md) ｜ **中文** ｜ [文档总览](index.md)

适用：Debian / Ubuntu / CentOS / Arch 等常见发行版，x86_64 与 arm64 均可。以下示例以 Ubuntu 为准，其它发行版把包管理命令换掉即可。

> **不要从 Windows 直接拷 `.venv` 过来** —— Windows 的二进制包 Linux 用不了，必须重新建环境。只拷代码。

---

## 一、前置要求

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 架构 | x86_64 / arm64 | 32 位（armv7 / i386）装不了 `skia-python` |
| Python | **3.10 – 3.13，推荐 3.13** | 版本写死：`skia-python`、`Pillow` 等只发预编译 wheel，版本对不上直接装不上。**3.14 暂不支持**（meme 引擎锁了 `Pillow ^10.0.0`，10.x 没有 3.14 的 wheel） |
| 磁盘 | ≥ 2 GB | 项目 + venv + 素材 |
| 系统库 | fontconfig、libGL、libEGL、libjpeg | 缺了运行时会报缺 `.so` |
| 路径 | **无空格、无中文** | 推荐 `/root/ilbb-bot` |
| 端口 | 5000、6700 | 5000 = 工作台，6700 = OneBot V11 |

---

## 二、安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y libfontconfig1 libgl1 libegl1 libjpeg-dev
```

`libegl1` 不能省：`skia-python` 从 138 版起在 Linux 上硬性依赖 `libEGL.so.1`，没有它启动就会报 `ImportError: libEGL.so.1: cannot open shared object file`。无头服务器还建议补上 `libgl1-mesa-dri`，让 OpenGL 能走 mesa 软件渲染兜底。

中文字体项目已自带 3 个（在 `font/`），够用；想再补一套可装：

```bash
sudo apt-get install -y fonts-wqy
```

---

## 三、安装 uv

发行版自带的 Python 通常不是 3.13，而依赖统一交给 [`uv`](https://docs.astral.sh/uv/) 管，所以先把它装上。uv 既是环境与依赖管理器，也能直接下载指定版本的 Python —— 下一节的 `uv venv --python 3.13` 会自己拿一份 3.13，不必折腾系统 Python。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env       # 或重开终端
uv --version
```

脚本被网络挡住的话，用 pip 兜底：`pip install uv`（Ubuntu 上系统 pip 可能要先 `sudo apt-get install -y python3-pip`）。

> 也可以自己编译 3.13，或用 deadsnakes PPA（Ubuntu）：`sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.13 python3.13-venv`。
>
> 版本要求写死为 **3.10 – 3.13**：3.14 装不上 —— meme 引擎锁了 `Pillow ^10.0.0`，而 Pillow 10.x 没有 3.14 的预编译包。

---

## 四、获取代码

```bash
mkdir -p /root/ilbb-bot && cd /root/ilbb-bot
git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git .
```

`/root` 是 root 的专属家目录，权限 700，普通用户连进都进不去，所以这段命令要用 root 身份执行：`sudo -i` 切进去，或者你的 VPS 本来就是 root 登录。项目落在 `/root/ilbb-bot` 之后，代码和 `.venv` 都归 root 所有，后面的 `uv venv`、启动命令、systemd 单元也都按 root 来配。这么做的代价是服务权限和系统一样大，单人自用的机器没什么问题；如果是多人共用的机器，更稳妥的选择是放 `/opt/ilbb-bot`，建一个专用运行用户，再让 systemd 的 `User=` 指向它。

> 只拷代码时，需要带上：`app.py`、`_serve.py`、`core/`、`vendor/`、`templates/`、`static/`、`font/`、`plugins/`、`.env.example`。跳过 `.venv`、`cache`、`temp`。

---

## 五、创建环境并安装依赖

```bash
cd /root/ilbb-bot
uv venv --python 3.13
uv pip install -r requirements.txt
```

`uv pip install` 默认认当前目录下的 `.venv`，在项目根目录执行就不会装错地方；想知道装了些什么，用 `uv pip list` 看。

**meme 引擎本身不用装**：`vendor/meme-generator-main/` 里的源码由程序启动时自动挂到模块搜索路径。但引擎自己声明的依赖得装齐，`toml`、`loguru`、`httpx`、`pil-utils` 这类包漏掉任何一个，启动都会直接报 `ModuleNotFoundError`——`requirements.txt` 已经把它们全部列好，所以上面只要这一条命令。

> 如果 `uv pip list` 里看到 `meme-generator` 指向别的机器上的老路径，可以 `uv pip uninstall meme-generator` 清掉；留着也不影响。

---

## 六、配置

```bash
cp .env.example .env
```

Linux 上通常要动的两项：

| 变量 | 默认 | 建议 |
| --- | --- | --- |
| `WEB_HOST` | `0.0.0.0` | 服务器对外提供服务就保持默认；只走本机反代可改 `127.0.0.1` |
| `WS_HOST` | `0.0.0.0` | NapCat 在别的机器上就保持默认 |

其余项都有默认值，可以先不动，在引导页里配。

---

## 七、启动并跑引导页

```bash
cd /root/ilbb-bot
./.venv/bin/python app.py
```

浏览器打开 `http://<服务器IP>:5000`，会自动进入 `/setup` 引导页，走完四步（环境自检 → 素材下载 → 基础配置 → 完成）。

> 服务器没有图形界面没关系，用你自己电脑的浏览器访问服务器 IP 即可。

---

## 八、进阶：生产化

### 用 gunicorn 扛并发

```bash
uv pip install gunicorn
./.venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

`-w 2` 是 worker 数，按 CPU 核数调整（一般 `2 × 核数 + 1`）。注意 ILBB 内部有内存态（当前 WS 连接、事件缓冲、图片缓存索引），**多 worker 不共享**，所以建议 `-w 1` 或 `-w 2` 起步，不要盲目调大。

### systemd 守护（推荐）

新建 `/etc/systemd/system/ilbb.service`：

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

`WorkingDirectory` **必须**是项目根目录，否则会报找不到 `cache` / `temp` / `font`。`User=root` 是为了配 `/root/ilbb-bot` —— 那个目录权限 700，换个用户身份的 systemd 服务根本读不进去。如果你把项目改放到了别处，记得把 `User=`、`WorkingDirectory`、`ExecStart` 三行一起改。

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ilbb
sudo systemctl status ilbb
sudo journalctl -u ilbb -f      # 看实时日志
```

### Nginx 反向代理（可选）

想让 ILBB 走 80/443 或套 HTTPS：

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

> 只代理 WebUI（5000）。OneBot 的 6700 是 WebSocket，由 NapCat 直连，一般不需要经过 Nginx；真要代理需额外配置 `Upgrade` / `Connection` 头。

---

## 常见问题

**启动报 `SkIcuLoader / icudtl` 警告**
装完 `skia-python` 后，把 `.venv/lib/python3.13/site-packages/icudtl.dat` 复制到 Python 的 base 目录。没有警告时可跳过。

**运行时提示缺某个 `.so`**
系统缺库，按提示补：

```bash
sudo apt-get install -y libfontconfig1 libgl1 libegl1 libjpeg-dev
```

**启动报 `ImportError: libEGL.so.1: cannot open shared object file`**
就是上面那条里漏装 `libegl1`。`skia-python` 从 138 版起在 Linux 上必须有 `libEGL.so`，无头服务器再补一个软件渲染兜底：

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libegl-mesa0 libgl1-mesa-dri
```

**`uv pip install skia-python` 报找不到匹配版本**
排查：① Python 版本不在 3.10 – 3.13（3.14 会卡在 Pillow 10.x 没有 3.14 的 wheel）；② 环境是 32 位的（`./.venv/bin/python -c "import platform;print(platform.architecture())"` 应为 `('64bit', ...)`）；③ 架构是 armv7 之类没有 wheel 的——这种情况得换 arm64 或 x86_64。版本选错就钉死重来：`uv venv --python 3.13 --clear`。

**引导页一直显示缺依赖**
uv 没把包装进项目的 `.venv`。确认是在项目根目录（有 `app.py` 的那层）跑的 `uv pip install -r requirements.txt`，然后 `uv pip list` 复查。如果只是缺了其中几个包（典型的是 `toml`、`loguru` 这类），同样用这一条命令补齐，不要照单包名一个个装。

**路径带空格或中文导致 import 报错**
把项目换到 `/root/ilbb-bot` 这类干净路径。

**systemd 启动失败、日志报找不到目录**
`WorkingDirectory` 没设成项目根目录。

**端口被占用**
`sudo ss -lntp | grep -E '5000|6700'` 找到占用进程。

**忘了管理密码**
删掉 `api_keys.json` 再重启，会重新生成并打印。

---

## 装完验证（可选）

```bash
./.venv/bin/python -c "import sys; sys.path.insert(0,'vendor/meme-generator-main'); import flask, requests, PIL, websockets, numpy, skia, meme_generator; print('deps OK, meme count:', len(meme_generator.get_memes()))"
```

这条要在项目根目录跑，`sys.path.insert` 那一段是把 vendor 里的引擎挂进来——只有 `app.py` 启动时才会自动挂，独立跑一条命令得自己补。打印出 `deps OK, meme count: 295` 一类的数字就算过。更全面的检查看引导页第 1 步。

---

## 连上 NapCat

服务起来只是第一步。在 NapCat（NC）的网络配置里新增一项「反向 WebSocket」，URL 填 `ws://<这台机器内网 IP>:6700/onebot/v11/ws`，消息格式选 `array`，Token 与 `.env` 里的 `WS_ACCESS_TOKEN` 对齐（没设就留空）。

查内网 IP 用 `ip -4 addr show` 或 `hostname -I`，6700 端口放行：

```bash
sudo ufw allow 6700/tcp
```

保存后回到 ILBB 后台的实时事件流，连接数变成 1 就说明通了。完整步骤和连不上的排查见 [消息平台对接](platform-integration.md)。

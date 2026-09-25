# 在 Linux 上部署 ILBB

[English](../en/deploy-linux.md) ｜ **中文** ｜ [文档总览](index.md)

适用：Debian / Ubuntu / CentOS / Arch 等常见发行版，x86_64 与 arm64 均可。以下示例以 Ubuntu 为准，其它发行版把包管理命令换掉即可。

> **不要从 Windows 直接拷 `.venv` 过来** —— Windows 的二进制包 Linux 用不了，必须重新建环境。只拷代码。

---

## 一、前置检查清单

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 架构 | x86_64 / arm64 | 32 位（armv7 / i386）装不了 `skia-python` |
| Python | **3.13** | 版本必须对上，`skia-python` 是预编译包 |
| 磁盘 | ≥ 2 GB | 项目 + venv + 素材 |
| 系统库 | fontconfig、libGL、libjpeg | 缺了运行时会报缺 `.so` |
| 路径 | **无空格、无中文** | 推荐 `/opt/ilbb-bot` |
| 端口 | 5000、6700 | 5000 = 工作台，6700 = OneBot V11 |

---

## 二、安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y libfontconfig1 libgl1 libjpeg-dev
```

中文字体项目已自带 3 个（在 `font/`），够用；想再补一套可装：

```bash
sudo apt-get install -y fonts-wqy
```

---

## 三、安装 Python 3.13

发行版自带的 Python 通常不是 3.13，推荐用 [`uv`](https://docs.astral.sh/uv/) 管理，它能直接下载指定版本的 Python：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env       # 或重开终端
uv --version
```

> 也可以自己编译 3.13，或用 deadsnakes PPA（Ubuntu）：`sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.13 python3.13-venv`。

---

## 四、获取代码

```bash
sudo mkdir -p /opt/ilbb-bot
sudo chown "$USER" /opt/ilbb-bot
git clone -b beta https://github.com/<你的用户名>/<仓库名>.git /opt/ilbb-bot
cd /opt/ilbb-bot
```

> 只拷代码时，需要带上：`app.py`、`_serve.py`、`core/`、`vendor/`、`templates/`、`static/`、`font/`、`plugins/`、`.env.example`。跳过 `.venv`、`cache`、`temp`。

---

## 五、创建环境并安装依赖

```bash
cd /opt/ilbb-bot
uv venv --python 3.13
uv pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

不用 uv 的话，等价的原生写法：

```bash
python3.13 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

**meme 引擎不用装**：`vendor/meme-generator-main/` 里的源码由程序启动时自动挂到模块搜索路径。

> 如果 `pip freeze` 里看到 `-e /老路径/vendor/meme-generator-main` 这种指向旧机器的可编辑安装记录，可以 `pip uninstall meme-generator` 清掉；留着也不影响。

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
cd /opt/ilbb-bot
./.venv/bin/python app.py
```

浏览器打开 `http://<服务器IP>:5000`，会自动进入 `/setup` 引导页，走完四步（环境自检 → 素材下载 → 基础配置 → 完成）。

> 服务器没有图形界面没关系，用你自己电脑的浏览器访问服务器 IP 即可。

---

## 八、进阶：生产化

### 用 gunicorn 扛并发

```bash
./.venv/bin/pip install gunicorn
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
User=ilbb
WorkingDirectory=/opt/ilbb-bot
ExecStart=/opt/ilbb-bot/.venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` **必须**是项目根目录，否则会报找不到 `cache` / `temp` / `font`。

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
sudo apt-get install -y libfontconfig1 libgl1 libjpeg-dev
```

**`pip install skia-python` 报找不到匹配版本**
排查：① Python 不是 3.13；② 是 32 位运行的 Python（`python -c "import platform;print(platform.architecture())"` 应为 `('64bit', ...)`）；③ 架构是 armv7 之类没有 wheel 的——这种情况得换 arm64 或 x86_64。

**引导页一直显示缺依赖**
用的不是项目自己的 Python。确认命令里带 `./.venv/bin/` 前缀。

**路径带空格或中文导致 import 报错**
把项目换到 `/opt/ilbb-bot` 这类干净路径。

**systemd 启动失败、日志报找不到目录**
`WorkingDirectory` 没设成项目根目录。

**端口被占用**
`sudo ss -lntp | grep -E '5000|6700'` 找到占用进程。

**忘了管理密码**
删掉 `api_keys.json` 再重启，会重新生成并打印。

---

## 装完自查（可选）

```bash
./.venv/bin/python -c "import flask,requests,PIL,websockets,numpy,skia; print('base OK'); from meme_generator import get_memes; print('meme OK')"
```

输出两行即通过。更全面的检查看引导页第 1 步。

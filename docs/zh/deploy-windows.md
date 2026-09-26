# 在 Windows 上部署 ILBB

[English](../en/deploy-windows.md) ｜ **中文** ｜ [文档总览](index.md)

适用：Windows 10 / 11（64 位）。全程大约 15 分钟，其中素材下载取决于网速。

---

## 一、前置要求

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 64 位 | 32 位系统装不了 `skia-python` |
| Python | **3.10 – 3.13（64 位），推荐 3.13** | 版本写死：`skia-python`、`Pillow` 等只发预编译 wheel，版本/位数对不上直接装不上。**3.14 暂不支持**（meme 引擎锁了 `Pillow ^10.0.0`，10.x 没有 3.14 的 wheel） |
| 磁盘空间 | ≥ 2 GB | 项目 + 虚拟环境 + meme 素材约 600 MB |
| 网络 | 能访问外网 | 首次启动要联网补全 meme 素材 |
| 端口 | 5000、6700 可用 | 5000 = 工作台，6700 = OneBot V11 |

---

## 二、准备 Python 3.13

本机没有合适的 Python 也可以跳过这一步：第四节装好 uv 之后，`uv venv --python 3.13` 会自动下载一份 3.13 托管版本。想自己装就往下看。

1. 打开 [python.org/downloads](https://www.python.org/downloads/) 下载 **Windows installer (64-bit)** 的 3.13 版本。
2. 安装时**务必勾选 `Add python.exe to PATH`**。
3. 装完打开 PowerShell 验证：

```powershell
python --version
```

应输出 `Python 3.13.x`。如果提示找不到命令，说明 PATH 没配上，重装并勾选，或手动把 Python 安装目录加进 PATH。

> 如果机器上装了多个 Python，记住本项目要用 **3.10 – 3.13（推荐 3.13）** —— 后面所有命令都通过 `.venv\Scripts\python.exe` 调用，不依赖 PATH，所以只要建 venv 时用的是合规版本就行。**别用 3.14**：meme 引擎依赖的 Pillow 10.x 没有 3.14 的 wheel。

---

## 三、获取代码

```powershell
git clone -b beta https://github.com/DXBbyd/ILBB_Emojibot.git
cd ILBB_Emojibot
```

> 当前发布在 `beta` 分支（v0.1.0-beta）。仓库不含 meme 素材（约 254MB），首次启动由引导页联网补全。

没有 git 的话，直接在 GitHub 页面点 `Code → Download ZIP` 解压也行。

---

## 四、装 uv、建环境、装依赖

**在项目根目录**（能看到 `app.py` 的那一层）执行。依赖统一交给 uv 管，第一步把 uv 装上：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

装完**重开一个 PowerShell 窗口**让 PATH 生效，然后确认：

```powershell
uv --version
```

如果这条脚本被组策略或网络挡住，用 pip 兜底：

```powershell
pip install uv
```

接着建虚拟环境、装依赖：

```powershell
uv venv --python 3.13
uv pip install -r requirements.txt
```

`uv venv --python 3.13` 会自己找一份 3.13，本机没有就下载一份，所以不用管系统里装的是哪个 Python。之后所有命令都通过 `.venv\Scripts\python.exe` 调用，同样不依赖 PATH。

依赖清单在仓库根目录的 `requirements.txt`，分两部分：机器人本体需要 `flask`、`requests`、`websockets`；`vendor/meme-generator-main/` 里的 meme 引擎自带源码、不走 pip 安装，但它自己声明的十几个依赖没法自动解析，清单已经把它们列齐了，其中 `Pillow` 钉在 10.x——引擎锁死的就是这个区间，装成 11 或 12 会在生成表情时崩掉。

> 注意装依赖统一用 `uv pip install`，别直接敲 `pip install`。裸 pip 很可能把包装进系统 Python 里，而 uv 默认认当前目录下的 `.venv`，不会跑偏；`.venv` 里到底装了什么，用 `uv pip list` 看。

---

## 五、配置

```powershell
copy .env.example .env
```

`.env` 里每一项都有默认值和中文注释，**可以先不动**——后面在引导页里改也一样。想在这里改的话，最常动的几项：

| 变量 | 默认 | 什么时候改 |
| --- | --- | --- |
| `WEB_HOST` | `0.0.0.0` | 只想本机访问就改成 `127.0.0.1` |
| `WEB_PORT` | `5000` | 端口被占用时改 |
| `INIT_ADMIN_PASSWORD` | 空 | 设置自己的管理密码之前临时使用的密码，留空则启动时随机生成并打印 |
| `BOT_NAME` | `我在哔哩学习` | 机器人昵称，显示在帮助图标题里 |
| `BOT_PREFIX` | `/` | 指令前缀，改成 `#` 之类也行 |

---

## 六、启动并跑引导页

在项目根目录执行：

```powershell
& .venv\Scripts\python.exe app.py
```

看到类似下面的日志就成功了（只要还没自己设过密码，每次启动都会重新打印这枚临时密码）：

```
========================================================
[管理后台] 临时管理密码: xxxxxxxx（本次随机生成，重启后会再次打印）
[管理后台] 打开 http://<本机IP>:5000/setup 设一个你自己的管理密码
[管理后台] 设好后这枚临时密码作废，之后可在 设置→修改密码 中更换
========================================================
 * Running on http://0.0.0.0:5000
```

浏览器打开 `http://127.0.0.1:5000`，会自动跳到 `/setup` 引导页，走完四步：

1. **环境自检** —— 逐项检查那 7 个依赖，缺哪个都会提示跑 `uv pip install -r requirements.txt`。点"重新检测"可复查。
2. **Meme 素材** —— 一键联网下载素材库（`vendor/.../meme_generator/memes/`）。这一步最慢，也最容易被网络问题卡住。
3. **基础配置** —— 机器人昵称、指令前缀、端口等。
4. **完成** —— 在这里设一个属于你自己的管理密码，然后进入工作台。这一步必须填，填完临时密码立即作废。

> 素材这步失败也没关系，可以跳过，之后再从设置页重试。没素材时 `/meme` 会提示找不到表情。

---

## 七、防火墙与局域网访问

只在**本机**用的话，看到这里就够了。

想让同一局域网的其他设备（或 NapCat 跑在别的机器上）访问，需要放行端口。**以管理员身份**打开 PowerShell：

```powershell
New-NetFirewallRule -DisplayName "ILBB WebUI 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
New-NetFirewallRule -DisplayName "ILBB OneBot 6700" -Direction Inbound -Protocol TCP -LocalPort 6700 -Action Allow
```

然后用 `ipconfig` 查到本机内网 IP（形如 `192.168.x.x`），其他设备用 `http://192.168.x.x:5000` 访问。

> 需要删除规则时：`Remove-NetFirewallRule -DisplayName "ILBB WebUI 5000"`。

---

## 八、进阶：开机自启

### 方式一：启动脚本（最简单）

在项目根目录新建 `start.bat`：

```bat
@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe app.py
pause
```

之后双击运行即可。注意 `cd /d "%~dp0"` 不能去掉——必须在项目根目录启动。

### 方式二：任务计划程序

1. 打开「任务计划程序」→「创建任务」。
2. 「常规」页：勾选「不管用户是否登录都要运行」，勾选「使用最高权限运行」。
3. 「触发器」页：新建 →「登录时」或「启动时」。
4. 「操作」页：程序或脚本填 `.venv\Scripts\python.exe` 的**完整路径**；「起始于」填项目根目录的**完整路径**（这一项很容易漏，漏了就会报找不到 `cache` / `temp`）。
5. 参数填 `app.py`。

---

## 常见问题

**启动报 `SkIcuLoader / icudtl` 警告**
`skia-python` 需要一份 ICU 文字数据文件。把 `.venv\Lib\site-packages\icudtl.dat` 复制到 **Python 安装目录**（和 `python.exe` 同级）。没有警告就不用管。

**`uv pip install skia-python` 报找不到匹配版本**
三种可能：① 选择的 Python 不在 3.10 – 3.13（3.14 会卡在 Pillow 10.x 没有 wheel）；② 装的是 32 位 Python；③ uv 太旧，`uv self update` 升一下。都不对就把 Python 版本钉死重来一次：`uv venv --python 3.13 --clear`。

**引导页一直显示缺依赖，但 `uv pip list` 里明明有**
多半是装到别的环境里去了。确认是在项目根目录（有 `app.py` 的那层）执行的 `uv pip install -r requirements.txt`，uv 默认认当前目录的 `.venv`；在别处跑就会落到别的环境。只缺个别包（典型的是 `toml`、`loguru`）也走同一条命令补齐，别照单包名一个个装。

**启动报找不到 `cache` / `temp` / `font`**
不在项目根目录启动。`cd` 到能看到 `app.py` 的那一层再运行。

**路径里有中文或空格，会不会出问题？**
一般能跑，但**深一点的纯英文目录更保险**。如果遇到奇怪的 import 报错，先换个路径试试。

**端口 5000 被占用**
`.env` 里改 `WEB_PORT`（例如 `5001`），或找出占用进程：`netstat -ano | findstr :5000`。

**`.venv\Lib\site-packages\` 里有个 `meme_generator.pth` 指向别的电脑**
删掉它，不影响运行——程序启动时会自己把 `vendor/meme-generator-main` 挂到模块搜索路径上。

**启动报 `FileNotFoundError: …\meme_generator\memes`**
素材本体不入库，克隆下来的仓库里没有 `meme_generator\memes` 这个文件夹，而引擎导入时会去遍历它——起服务当场失败，那个负责下素材的引导页也就进不去。启动时程序会自己补出这个空目录；手上是旧代码还报这个错，就手动建一个再启动：

```powershell
New-Item -ItemType Directory -Force vendor\meme-generator-main\meme_generator\memes
```

**忘了管理密码**
终端每次启动都会打印当前生效的密码。把 `api_keys.json` 里的 `admin_hash` 删掉再重启，会重新生成一枚临时密码并打印；也可以直接打开 `/setup` 设一个新的。

---

## 装完验证（可选）

一条命令验证依赖是否齐全：

```powershell
& .venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'vendor/meme-generator-main'); import flask, requests, PIL, websockets, numpy, skia, meme_generator; print('deps OK, meme count:', len(meme_generator.get_memes()))"
```

这条要在项目根目录跑，`sys.path.insert` 那一段是把 vendor 里的引擎挂进来——只有 `app.py` 启动时才会自动挂，独立跑一条命令得自己补。打印出 `deps OK, meme count: 295` 一类的数字就基本稳了。更全面的检查直接看引导页第 1 步（还会检查 `cache` / `temp` / `font` / 背景图目录、Python 版本、引擎版本、可识别表情数、管理密码状态）。

---

## 连上 NapCat

服务起来只是第一步。在 NapCat（NC）的网络配置里新增一项「反向 WebSocket」，URL 填 `ws://<这台机器内网 IP>:6700/onebot/v11/ws`，消息格式选 `array`，Token 与 `.env` 里的 `WS_ACCESS_TOKEN` 对齐（没设就留空）。

查内网 IP 用 `ipconfig`（找形如 `192.168.x.x` 的 IPv4），6700 端口按管理员 PowerShell 放行：

```powershell
New-NetFirewallRule -DisplayName "ILBB OneBot 6700" -Direction Inbound -Protocol TCP -LocalPort 6700 -Action Allow
```

保存后回到 ILBB 后台的实时事件流，连接数变成 1 就说明通了。完整步骤和连不上的排查见 [消息平台对接](platform-integration.md)。

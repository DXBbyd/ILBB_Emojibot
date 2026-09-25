# 在 Windows 上部署 ILBB

[English](../en/deploy-windows.md) ｜ **中文** ｜ [文档总览](index.md)

适用：Windows 10 / 11（64 位）。全程大约 15 分钟，其中素材下载取决于网速。

---

## 一、前置检查清单

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 64 位 | 32 位系统装不了 `skia-python` |
| Python | **3.13（64 位）** | 必须，`skia-python` 是预编译包，版本对不上直接装不上 |
| 磁盘空间 | ≥ 2 GB | 项目 + 虚拟环境 + meme 素材约 600 MB |
| 网络 | 能访问外网 | 首次启动要联网补全 meme 素材 |
| 端口 | 5000、6700 可用 | 5000 = 工作台，6700 = OneBot V11 |

---

## 二、安装 Python 3.13

1. 打开 [python.org/downloads](https://www.python.org/downloads/) 下载 **Windows installer (64-bit)** 的 3.13 版本。
2. 安装时**务必勾选 `Add python.exe to PATH`**。
3. 装完打开 PowerShell 验证：

```powershell
python --version
```

应输出 `Python 3.13.x`。如果提示找不到命令，说明 PATH 没配上，重装并勾选，或手动把 Python 安装目录加进 PATH。

> 如果机器上装了多个 Python，记住本项目要用 3.13 —— 后面所有命令都通过 `.venv\Scripts\python.exe` 调用，不依赖 PATH，所以只要建 venv 时用的是 3.13 就行。

---

## 三、获取代码

```powershell
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>
```

没有 git 的话，直接在 GitHub 页面点 `Code → Download ZIP` 解压也行。

> 仓库里**不含 meme 素材**（约 254 MB），这是刻意的。克隆后由引导页联网补全。

---

## 四、创建虚拟环境并安装依赖

**在项目根目录**（能看到 `app.py` 的那一层）执行：

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -U pip
& .venv\Scripts\python.exe -m pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

七个依赖的作用：

| 包 | 用途 |
| --- | --- |
| `flask` | Web 工作台与 REST 接口 |
| `requests` | 拉取 QQ 头像、随机背景图 |
| `pillow` | 图片处理（配对卡、名言图） |
| `websockets` | OneBot V11 反向 WebSocket 服务器 |
| `skia-python~=144.0` | 表情合成引擎使用的绘图库（**必须 144.x**） |
| `numpy` | 引擎的数值计算依赖 |
| `meme 引擎` | 已随代码放在 `vendor/meme-generator-main/`，**不需要 pip 安装**，启动时自动挂载 |

> 注意一定要用 `& .venv\Scripts\python.exe -m pip ...`。直接敲 `pip install` 很可能会装到系统 Python 里，然后引导页一直报"缺依赖"。

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
| `INIT_ADMIN_PASSWORD` | 空 | 想自己定初始管理密码就填上，不然随机生成打印在终端 |
| `BOT_NAME` | `我在哔哩学习` | 机器人昵称，显示在帮助图标题里 |
| `BOT_PREFIX` | `/` | 指令前缀，改成 `#` 之类也行 |

---

## 六、启动并跑引导页

在项目根目录执行：

```powershell
& .venv\Scripts\python.exe app.py
```

看到类似下面的日志就成功了（管理密码只在首次出现）：

```
[ILBB] 管理密码：xxxxxxxx
 * Running on http://0.0.0.0:5000
```

浏览器打开 `http://127.0.0.1:5000`，会自动跳到 `/setup` 引导页，走完四步：

1. **环境自检** —— 逐项检查那 7 个依赖，缺哪个会直接给出对应的安装命令。点"重新检测"可复查。
2. **Meme 素材** —— 一键联网下载素材库（`vendor/.../meme_generator/memes/`）。这一步最慢，也最容易被网络问题卡住。
3. **基础配置** —— 机器人昵称、指令前缀、端口等。
4. **完成** —— 进入工作台。

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

**`pip install skia-python` 报找不到匹配版本**
三种可能：① Python 不是 3.13；② 装的是 32 位 Python；③ pip 太旧。依次排查，先 `& .venv\Scripts\python.exe -m pip install -U pip`。

**引导页一直显示缺依赖，但 `pip list` 里明明有**
装到别的 Python 里去了。必须用 `& .venv\Scripts\python.exe -m pip install ...`。

**启动报找不到 `cache` / `temp` / `font`**
不在项目根目录启动。`cd` 到能看到 `app.py` 的那一层再运行。

**路径里有中文或空格，会不会出问题？**
一般能跑，但**深一点的纯英文目录更保险**。如果遇到奇怪的 import 报错，先换个路径试试。

**端口 5000 被占用**
`.env` 里改 `WEB_PORT`（例如 `5001`），或找出占用进程：`netstat -ano | findstr :5000`。

**`.venv\Lib\site-packages\` 里有个 `meme_generator.pth` 指向别的电脑**
删掉它，不影响运行——程序启动时会自己把 `vendor/meme-generator-main` 挂到模块搜索路径上。

**忘了管理密码**
把 `api_keys.json` 删掉再重启，会重新生成并打印到终端。

**`node_modules` / `package.json` 是什么？**
开发期用 puppeteer 截图的小工具留下的，跟运行无关，可以删。

---

## 装完自查（可选）

一条命令验证依赖是否齐全：

```powershell
& .venv\Scripts\python.exe -c "import flask,requests,PIL,websockets,numpy,skia; print('base OK'); from meme_generator import get_memes; print('meme OK')"
```

输出两行 `base OK` / `meme OK` 就基本稳了。更全面的检查直接看引导页第 1 步（还会检查 `cache` / `temp` / `font` / 背景图目录、Python 版本、引擎版本、可识别表情数、管理密码状态）。

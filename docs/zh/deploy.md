# 选择部署方式

[English](../en/deploy.md) ｜ **中文** ｜ [文档总览](index.md)

三条路线对应三种机器，步骤互不通用，挑一条进去照着做就行。三篇都从装 uv 讲到开机自启，跑的是同一套代码，差别只在系统依赖、启动方式和权限。

| 你的机器 | 走这一篇 | 路上会碰到什么 |
| --- | --- | --- |
| Windows 10 / 11（64 位） | [Windows 部署](deploy-windows.md) | Python 可以跳过不装，交给 uv 拉；`icudtl.dat` 得拷进 Python 安装目录；防火墙放行 5000 / 6700 |
| Linux 服务器 / 云主机 | [Linux 部署](deploy-linux.md) | 补 `libfontconfig1`、`libgl1` 等系统库；可以用 systemd 常驻，前面挂 Nginx |
| 安卓手机（Termux） | [Android 部署](deploy-android.md) | 能跑，但 `skia-python` 在手机上没现成轮子，要自己编译；未做充分验证，请自行测试 |

第一次接触这个项目，建议先在本机把 `/setup` 引导页跑通、素材下载完，再考虑搬到服务器或手机上。

---

## 三条路线共用的部分

### Python 版本

**3.10 – 3.13（64 位），推荐 3.13。** 版本和位数是硬要求：`skia-python`、`Pillow` 这类依赖只提供预编译 wheel，对不上就直接装不上。**3.14 及更高不行**，meme 引擎锁了 `Pillow ^10.0.0`，而 10.x 早于 3.14 发布、没有对应 wheel。用 uv 的话可以直接让它拉一份 3.13 下来，省得折腾系统 Python。

### 依赖统一交给 uv

uv 是独立的可执行文件，装法三选一，装完之后三条路线用的命令完全一样。

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Linux / macOS：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

两条脚本都走不通（或想把 uv 统一放进 Python 里管）时，用 pip 兜底：

```bash
pip install uv
```

Linux / macOS 用脚本装完要让它进 PATH，重开一个终端，或者执行：

```bash
source $HOME/.local/bin/env
```

确认装好了：

```bash
uv --version
```

建环境和装依赖就这两条，在所有平台都一样：

```bash
uv venv --python 3.13
uv pip install -r requirements.txt
```

依赖清单在仓库根目录的 `requirements.txt` 里。`vendor/meme-generator-main/` 里的 meme 引擎本身不走 pip 安装，但它依赖的十几个包没法自动解析（vendor 里没有 `pyproject.toml`），所以清单已经把它们一起列好了，照上面这一条命令装就行。

### 配置与首次启动

`.env` 里每一项都有默认值，可以先不动，直接用引导页在浏览器里配。服务**必须在项目根目录启动**（`cache`、`temp`、`font` 走的是相对路径），启动后打开 `http://127.0.0.1:5000/setup`，把环境自检、素材下载、基础配置一次走完。

### 端口

5000 是 Web 工作台，6700 是 OneBot V11 反向 WS。这两个端口要能被 NapCat 访问到，服务器上记得在防火墙或安全组里放行。

---

## 连上 NapCat

服务起得来只是第一步。在 NapCat（NC）的网络配置里新增一项「反向 WebSocket」，URL 填 `ws://<ILBB 机器 IP>:6700/onebot/v11/ws`，消息格式选 `array`，Token 与 `.env` 里的 `WS_ACCESS_TOKEN` 对齐（没设就留空），并在防火墙上放行 6700——这些都做完，机器人才会在 QQ 里收消息。完整步骤和连不上的排查见 [消息平台对接](platform-integration.md)。

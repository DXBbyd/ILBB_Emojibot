# 我在哔哩学习 Emoji Bot · ILBB

**中文** ｜ [English](README.en.md)

一个**自托管**的 QQ 表情包生成机器人 + Web 工作台：接上 NapCat（OneBot V11）就能在群聊/私聊里用一句话合成表情包，同时提供网页端配对卡生成、名言图合成、素材浏览、接口调试与插件系统。

不依赖任何第三方云服务，全部跑在你自己的机器上。

---

## 目录

- [功能一览](#功能一览)
- [效果与界面](#效果与界面)
- [快速开始](#快速开始)
- [指令速查](#指令速查)
- [配置与接入](#配置与接入)
- [插件系统](#插件系统)
- [三种部署方式](#三种部署方式)
- [目录结构](#目录结构)
- [文档索引](#文档索引)
- [常见问题](#常见问题)
- [致谢与许可](#致谢与许可)

---

## 功能一览

| 模块 | 说明 |
| --- | --- |
| 表情合成 `/meme` | 3400+ 款素材。发指令 + 文字（可带图 / @人 / 写 QQ 号）即出表情包，支持按表情预设传参 |
| 配对卡片 `/pair` | 生成 QQ 风格配对卡片，三种模板（classic / dark / paper），标题、背景、按钮文字可自定义 |
| 名言图 `/quote` | 随机网络背景 + 黑色蒙版 + 头像 + 「笑死」气泡 + 右下署名，输出 JPG |
| 图片菜单 `/help` | 全部指令以图片形式返回，排版清晰，手机端也能看清 |
| Web 工作台 | 配对卡生成器、表情预览与调试、指令中心干跑预览、Web 会话（不开 QQ 也能试指令） |
| 对接面板 | OneBot V11 反向 WS 服务器的启停、配置、实时事件流、原始 JSON、30+ 接口调试面板 |
| 插件系统 | `plugins/` 下一个文件夹就是一个插件，清单式配置、热重载、可自带 Web 页面 |
| 引导页 `/setup` | 环境自检、素材联网补全、基础配置，五步跑通，不用手改文件 |
| OpenAI 兼容层 `/v1` | 暴露 `/v1/images/generations`、`/v1/images/edits`、`/v1/cards` 等，可被任意 OpenAI 客户端调用 |

---

## 效果与界面

启动后访问 `http://127.0.0.1:5000`：

| 页面 | 路径 | 用途 |
| --- | --- | --- |
| 工作台 | `/` | 配对卡生成器主界面 |
| 状态页 | `/status` | 运行状态、缓存、接口调用统计 |
| 引导页 | `/setup` | 首次运行的向导（环境自检 / 素材下载 / 配置） |
| 管理页 | `/admin` | 后台面板（对接、插件、指令中心） |

首次启动会生成随机管理密码并**打印在终端**；也可以在 `.env` 里用 `INIT_ADMIN_PASSWORD` 预先指定。

---

## 快速开始

### 1. 准备环境

- **Python 3.13（64 位）** —— 必须，`skia-python` 是预编译包，位数/版本对不上装不上。
- Windows：从 [python.org](https://www.python.org/downloads/) 或 Microsoft Store 安装，安装时勾选 `Add to PATH`。
- Linux：用发行版包管理器或 `uv`（见 [Linux 部署](docs/zh/deploy-linux.md)）。

### 2. 获取代码

```bash
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>
```

> 仓库**不含 meme 素材**（约 254MB），克隆后首次启动由引导页自动联网补全。

### 3. 创建虚拟环境并装依赖

Windows：

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -U pip
& .venv\Scripts\python.exe -m pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

Linux / macOS：

```bash
python3.13 -m venv .venv
./.venv/bin/pip install -U pip
./.venv/bin/pip install flask requests pillow websockets "skia-python~=144.0" numpy
```

### 4. 配置

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

`.env` 里每一项都有默认值，**可以先不改**，直接用引导页在浏览器里配。

### 5. 启动

**必须在项目根目录启动**（`cache`、`temp`、`font` 走的是相对路径）：

```powershell
# Windows
& .venv\Scripts\python.exe app.py
```

```bash
# Linux
./.venv/bin/python app.py
```

看到日志里打印管理密码后，浏览器打开 `http://127.0.0.1:5000/setup` 走一遍引导页：

1. **环境自检** —— 检查 7 项依赖是否齐
2. **Meme 素材** —— 一键联网下载素材库（也可以跳过，之后在设置里补）
3. **基础配置** —— 机器人昵称、指令前缀、端口等
4. **完成** —— 进入工作台

接着按 [消息平台对接](docs/zh/platform-integration.md) 把 NapCat 连上来，机器人就能在 QQ 里干活了。

---

## 指令速查

默认前缀是 `/`（可用 `BOT_PREFIX` 改成 `#` 等）。完整说明见 **[指令手册](docs/zh/commands.md)**。

| 指令 | 说明 |
| --- | --- |
| `/help`、`/菜单`、`/menu`、`/?` | 返回**图片版**指令总览菜单 |
| `/meme` | 表情生成器用法说明 |
| `/meme [关键词] [文本1] [文本2] …` | 直接合成表情；可附图、@ 群友或写 QQ 号当素材 |
| `/meme list [页码/关键词]` | 分页浏览素材；带关键词则搜索，如 `/meme list 摸头` |
| `/meme help [ID]` | 单个表情的图文教程（底图、预设、示例） |
| `/pair [QQ/@] [标题]` | 生成配对卡片，可加 `template=` `bg=` `btn=` |
| `/quote [@/QQ] 文本…` | 合成名言图 |
| `<插件自定触发词>` | 由 `plugins/<插件>/plugin.json` 声明 |

**给图的三种方式**：① 指令和图片一起发；② 引用一条带图消息再发指令；③ `@群友` 或直接写 QQ 号，机器人取头像当素材。

---

## 配置与接入

配置有两条路径，**改任何一边都能生效**：

1. **WebUI** —— 引导页 `/setup` 与后台面板，改完自动写回文件；
2. **`.env`** —— 复制 `.env.example` 修改，重启生效。

优先级：**系统环境变量 > `.env` > 代码内置默认值**。

### 关键配置项

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `5000` | 工作台监听地址与端口。`127.0.0.1` = 仅本机 |
| `INIT_ADMIN_PASSWORD` | 空 | 仅首次运行生效的初始管理密码；留空则随机生成并打印 |
| `SECRET_KEY` | 空 | session 密钥。留空 = 每次启动随机（重启需重新登录） |
| `WS_HOST` / `WS_PORT` / `WS_PATH` | `0.0.0.0` / `6700` / `/onebot/v11/ws` | OneBot V11 反向 WS 监听地址（NapCat 往这里连） |
| `WS_ACCESS_TOKEN` | 空 | 连接校验令牌，留空不校验 |
| `WS_AUTO_START` | `false` | 是否随主服务自动拉起 WS 服务器 |
| `WS_CONFIG_PRIORITY` | `file` | `file` = 面板保存的值覆盖 `.env`；`env` = 以 `.env` 为准，面板禁止保存 |
| `BOT_ENABLED` | `true` | 指令总开关 |
| `BOT_NAME` / `BOT_PREFIX` | `我在哔哩学习` / `/` | 机器人昵称、指令前缀 |
| `BOT_GROUP_NEED_AT` | `false` | 群聊是否必须 @ 机器人才响应 |
| `BOT_ALLOW_PRIVATE` | `true` | 是否允许私聊使用指令 |
| `BOT_COOLDOWN_SEC` | `3` | 同一用户两次指令的最短间隔（秒），防刷屏 |
| `BOT_MAX_IMAGE_MB` | `8` | 单张回图体积上限，超了会压缩或放弃 |
| `PLUGIN_ENABLED` / `PLUGIN_HOT_RELOAD` | `true` / `true` | 插件总开关 / 热重载 |
| `PLUGIN_WEB_PORT_BASE` | `7000` | 插件自带 Web 页面的端口分配起点 |
| `CACHE_EXPIRE_DAYS` | `30` | 生成图片缓存保留天数 |

完整清单（含名言图排版、缓存、背景 API 等）见 **[配置参考](docs/zh/configuration.md)** 与项目里的 `.env.example`（每一项都有中文注释）。

### 对接 NapCat（OneBot V11）

ILBB 自己是 **WebSocket 服务端**，NapCat 以「**反向 WebSocket**」连进来：

1. 在 ILBB：后台面板确认 WS 已启动（或 `.env` 里 `WS_AUTO_START=true`）。
2. 在 NapCat：新增「网络配置 → 反向 WebSocket」，地址填
   `ws://<ILBB 所在机器 IP>:6700/onebot/v11/ws`，Token 与 `WS_ACCESS_TOKEN` 保持一致。
3. 连上后，ILBB 后台的**实时事件流**会开始滚动显示消息、通知、请求与元事件。

详细步骤、协议字段、接口调试与 OpenAI 兼容层说明见 **[消息平台对接](docs/zh/platform-integration.md)**。

---

## 插件系统

**一个文件夹 = 一个插件**。把 `plugins/example/` 整个复制成 `plugins/my_plugin/` 改改就是新插件，支持热重载（默认 3 秒轮询，改完自动生效，不用重启）。

```
plugins/
└── my_plugin/
    ├── plugin.json     # 清单：id / name / 配置字段 / 指令声明
    ├── main.py         # 入口：setup(ctx) 注册指令与事件
    └── web/            # 可选：插件自己的 Web 页面
        └── index.html
```

`main.py` 里拿到 `ctx` 就能用全套能力：收发消息、取好友/群/成员列表、读写插件配置、调用任意 OneBot 接口、开自己的 Web 端口。

```python
def setup(ctx):
    @ctx.on_command(["ping"], desc="测试")
    def _ping(args, ctx, p):
        return ([], ["pong"])

    @ctx.on_event
    def _on_msg(ev, client):
        ctx.log("收到事件：%s" % ev.get("post_type"))
```

插件配置字段支持 8 种类型（`text` / `textarea` / `int` / `bool` / `enum` / `friend` / `group` / `group_member`），在后台面板里直接渲染成表单，改完热生效。

完整 API 参考、清单字段表、Web 页面接入与两个可抄的示例见 **[插件开发指南](docs/zh/plugin-dev.md)**。

---

## 三种部署方式

| 平台 | 文档 | 要点 |
| --- | --- | --- |
| **Windows** | [deploy-windows.md](docs/zh/deploy-windows.md) | Python 3.13 64 位；`icudtl.dat` 需拷到 Python 安装目录；注意防火墙放行 5000 / 6700 端口 |
| **Linux** | [deploy-linux.md](docs/zh/deploy-linux.md) | 推荐 `uv` 建环境；可上 `gunicorn -w 2 -b 0.0.0.0:5000 app:app`；systemd 做服务守护 |
| **Android** | [deploy-android.md](docs/zh/deploy-android.md) | 用 Termux 装 Python 3.13 + 依赖，手机端跑；**未做充分验证，请自行测试** |

英文版：[Windows](docs/en/deploy-windows.md) ｜ [Linux](docs/en/deploy-linux.md) ｜ [Android](docs/en/deploy-android.md)

> 部署顺序建议：先在本机把 `/setup` 引导页跑通、素材下载完，再考虑迁移到 Linux / 服务器 / 手机。

---

## 目录结构

```
.
├── app.py                 # Flask 主程序（WebUI + 路由），可直接 python app.py 启动
├── _serve.py              # 生产式启动入口（读 .env 的 WEB_HOST / WEB_PORT / WEB_THREADED）
├── .env.example           # 配置模板（含中文注释），复制为 .env 使用
├── LICENSE                # MIT
├── 部署说明.md            # 面向本机的部署笔记
├── core/                  # 核心逻辑
│   ├── config.py          # 配置加载（.env → 常量）
│   ├── ws_server.py       # OneBot V11 反向 WS 服务器 + 接口调试元数据
│   ├── bot_commands.py    # 指令路由与事件处理
│   ├── bot_render.py      # 帮助图 / 菜单图 / 列表图渲染
│   ├── meme_service.py    # 表情合成服务
│   ├── meme_assets.py     # 素材清单与联网补全
│   ├── plugin_manager.py  # 插件加载 / 热重载 / 配置
│   ├── openai_api.py      # OpenAI 兼容层（/v1）
│   ├── admin.py           # 登录与管理密码
│   ├── api_key_store.py   # API Key 存储校验
│   └── usage.py           # 接口调用统计
├── plugins/               # 插件目录（一个文件夹 = 一个插件）
│   └── example/           # 官方示例插件（含独立 Web 页面）
├── templates/             # 页面模板
├── static/                # 前端资源（css / js / bg）
├── font/                  # 配对卡使用的字体
├── vendor/                # meme 引擎源码 + 字体 + 素材清单（素材本体不入库）
├── cache/  temp/          # 运行时缓存与临时文件（不入库）
└── docs/                  # 双语文档
    ├── zh/                # 中文文档
    └── en/                # English docs
```

---

## 文档索引

| 主题 | 中文 | English |
| --- | --- | --- |
| 文档总览 | [docs/zh/index.md](docs/zh/index.md) | [docs/en/index.md](docs/en/index.md) |
| 部署 · Windows | [docs/zh/deploy-windows.md](docs/zh/deploy-windows.md) | [docs/en/deploy-windows.md](docs/en/deploy-windows.md) |
| 部署 · Linux | [docs/zh/deploy-linux.md](docs/zh/deploy-linux.md) | [docs/en/deploy-linux.md](docs/en/deploy-linux.md) |
| 部署 · Android | [docs/zh/deploy-android.md](docs/zh/deploy-android.md) | [docs/en/deploy-android.md](docs/en/deploy-android.md) |
| 指令手册 | [docs/zh/commands.md](docs/zh/commands.md) | [docs/en/commands.md](docs/en/commands.md) |
| 插件开发 | [docs/zh/plugin-dev.md](docs/zh/plugin-dev.md) | [docs/en/plugin-dev.md](docs/en/plugin-dev.md) |
| 平台对接 | [docs/zh/platform-integration.md](docs/zh/platform-integration.md) | [docs/en/platform-integration.md](docs/en/platform-integration.md) |
| 配置参考 | [docs/zh/configuration.md](docs/zh/configuration.md) | [docs/en/configuration.md](docs/en/configuration.md) |

---

## 常见问题

**Q：一定要 Python 3.13 吗？**
是。`skia-python~=144.0` 提供的是预编译 wheel，Python 版本或 32/64 位对不上会直接装不上；引导页第一步会体检并告诉你缺什么。

**Q：克隆下来提示素材不全 / `/meme` 报找不到素材？**
仓库故意不含 meme 素材（约 254MB）。打开 `http://127.0.0.1:5000/setup`，在「Meme 素材」一步点下载即可补齐。

**Q：启动报找不到 `cache` / `temp` / `font`？**
必须在**项目根目录**启动，这几个目录走的是相对路径。

**Q：机器人不回消息？**
依次确认：WS 服务器已启动 → NapCat 反向 WS 连上了（后台事件流有滚动的日志）→ `BOT_ENABLED=true` → 前缀对不对（默认 `/`）→ 私聊是否被 `BOT_ALLOW_PRIVATE=false` 关掉 → 是否撞上了 `BOT_COOLDOWN_SEC` 冷却。

**Q：忘记管理密码？**
在 `api_keys.json` 里删掉管理密码哈希后重启，会重新生成并打印到终端（或删掉整个 `api_keys.json`）。

**Q：`node_modules` / `package.json` 是什么？**
开发期用 puppeteer 截图的小工具留下的，跟运行项目无关，删掉不影响使用。

---

## 致谢与许可

- 表情合成引擎来自 [MeetWq/meme-generator](https://github.com/MeetWq/meme-generator)（MIT），本项目以 `vendor/meme-generator-main` 形式内置。
- 素材版权归各自原作者所有；本项目仅做技术集成，请勿用于商业用途。

本项目采用 **[MIT License](LICENSE)** 开源。

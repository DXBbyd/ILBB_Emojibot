# 我在哔哩学习 Emoji Bot · ILBB

**中文** ｜ [English](README.en.md)

> **当前版本：v0.1.0-beta** ｜ 发布分支：`beta` ｜ 处于 Beta 阶段，功能与接口仍可能调整。

一个**自托管**的 QQ 表情包生成机器人 + Web 工作台：接上 NapCat（OneBot V11）就能在群聊/私聊里用一句话合成表情包，同时提供网页端配对卡生成、名言图合成、素材浏览、接口调试与插件系统。

不依赖任何第三方云服务，全部跑在你自己的机器上。

---

## 目录

- [功能一览](#功能一览)
- [效果与界面](#效果与界面)
- [部署](#部署)
- [指令速查](#指令速查)
- [配置与接入](#配置与接入)
- [插件系统](#插件系统)
- [目录结构](#目录结构)
- [文档](#文档)
- [常见问题](#常见问题)
- [许可与来源](#许可与来源)

---

## 功能一览

| 模块 | 说明 |
| --- | --- |
| 表情合成 `/meme` | 282 款表情、3400+ 个素材文件。发指令 + 文字（可带图 / @人 / 写 QQ 号）即出表情包，支持按表情预设传参 |
| 配对卡片 `/pair` | 生成 QQ 风格配对卡片，三种模板（classic / dark / paper），标题、背景、按钮文字可自定义 |
| 名言图 `/quote` | 横屏 16:9 版式：随机二次元背景 + 灰色蒙版（默认不透明度 35%），画面正中一块全模糊托盘，托盘内左圆形头像、右文字或表情包（可放动图），右下署名；静态出 JPG，动图出 GIF，字体可切换 |
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

## 部署

本项目自托管运行，不依赖任何第三方云服务。环境要求、依赖安装、配置、启动、开机自启与故障排查按平台分开，写在 [选择部署方式](docs/zh/deploy.md) 里，照着你的机器选一条路线进去即可。

动手之前有三件事值得先知道。Python 需要 **3.10 – 3.13（64 位），推荐 3.13**，`skia-python`、`Pillow` 这类依赖只发预编译 wheel，版本或位数对不上会直接装不上，3.14 同样不行（原因见下方 [常见问题](#常见问题)）。依赖统一交给 [uv](https://docs.astral.sh/uv/) 管理：装好 uv 之后用 `uv venv --python 3.13` 建虚拟环境，用 `uv pip install` 装依赖，不必再碰 pip。仓库里**不含 meme 素材**（约 254MB），克隆下来首次启动时由引导页联网补全。

服务**必须在项目根目录启动**，`cache`、`temp`、`font` 走的是相对路径。启动后浏览器打开 `http://127.0.0.1:5000/setup`，引导页会把环境自检、素材下载和基础配置一次走完；接着按 [消息平台对接](docs/zh/platform-integration.md) 把 NapCat 连上来，机器人就能在 QQ 里干活了。

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

## 目录结构

```
.
├── app.py                 # Flask 主程序（WebUI + 路由），可直接 python app.py 启动
├── _serve.py              # 生产式启动入口（读 .env 的 WEB_HOST / WEB_PORT / WEB_THREADED）
├── .env.example           # 配置模板（含中文注释），复制为 .env 使用
├── LICENSE                # MIT
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

## 文档

文档分中英两套，入口分别是 [docs/zh/index.md](docs/zh/index.md) 与 [docs/en/index.md](docs/en/index.md)。下面只列分类入口，具体篇目进去看。

| 分类 | 入口 |
| --- | --- |
| 部署 | [选择部署方式](docs/zh/deploy.md) —— Windows / Linux / Android 三条路线 |
| 使用 | [指令手册](docs/zh/commands.md) ｜ [配置参考](docs/zh/configuration.md) ｜ [平台对接](docs/zh/platform-integration.md) |
| 开发 | [插件开发指南](docs/zh/plugin-dev.md) |

英文文档：[Choose a deployment](docs/en/deploy.md) ｜ [Commands](docs/en/commands.md) ｜ [Configuration](docs/en/configuration.md) ｜ [Platform integration](docs/en/platform-integration.md) ｜ [Plugin development](docs/en/plugin-dev.md)

---

## 常见问题

**Q：一定要 Python 3.13 吗？**
版本要求写死为 **3.10 – 3.13（64 位），推荐 3.13**。`skia-python~=144.0` 提供的是预编译 wheel，Python 版本或 32/64 位对不上会直接装不上；引导页第一步会把解释器版本和依赖一起体检，不合格直接标出来。

**Q：能用 Python 3.14 吗？**
不行。`skia-python` 本身有 3.14 的 wheel，但 vendor 里的 meme 引擎锁了 `Pillow ^10.0.0`，而 Pillow 10.x 早于 3.14 发布、没有 3.14 的预编译包，pip 会直接报 `Could not find a version that satisfies the requirement Pillow<11,>=10`。装 64 位 3.13 是唯一省事的选择。

**Q：克隆下来提示素材不全 / `/meme` 报找不到素材？**
仓库故意不含 meme 素材（约 254MB）。打开 `http://127.0.0.1:5000/setup`，在「Meme 素材」一步点下载即可补齐。

**Q：启动报找不到 `cache` / `temp` / `font`？**
必须在**项目根目录**启动，这几个目录走的是相对路径。

**Q：机器人不回消息？**
依次确认：WS 服务器已启动 → NapCat 反向 WS 连上了（后台事件流有滚动的日志）→ `BOT_ENABLED=true` → 前缀对不对（默认 `/`）→ 私聊是否被 `BOT_ALLOW_PRIVATE=false` 关掉 → 是否撞上了 `BOT_COOLDOWN_SEC` 冷却。

**Q：忘记管理密码？**
在 `api_keys.json` 里删掉管理密码哈希后重启，会重新生成并打印到终端（或删掉整个 `api_keys.json`）。

---

## 许可与来源

- 表情合成引擎来自 [MeetWq/meme-generator](https://github.com/MeetWq/meme-generator)（MIT），本项目以 `vendor/meme-generator-main` 形式内置。
- 素材版权归各自原作者所有；本项目仅做技术集成，请勿用于商业用途。

本项目采用 **[MIT License](LICENSE)** 开源。

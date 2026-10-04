# 配置说明

**中文** ｜ [English](../en/configuration.md)

ILBB 的所有配置都通过**环境变量**驱动，三种来源按优先级叠加：

```
系统环境变量   >   .env 文件   >   代码内置默认值
```

也就是说：**删掉某一行 = 使用默认值**，不需要写全。改完重启服务生效。

`.env` 已被 `.gitignore` 忽略，**不要提交含密钥的 `.env`**。项目自带 `.env.example` 作为模板：

```bash
# Windows
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

> 首次启动后也可以在 **引导页 `/setup`** 与 **设置页** 里改配置，会自动写回 `.env`。

---

## 1. WebUI / Flask

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WEB_HOST` | `0.0.0.0` | 监听地址。`0.0.0.0` = 允许局域网访问，`127.0.0.1` = 仅本机 |
| `WEB_PORT` | `5000` | WebUI 端口。从其他设备访问需在防火墙放行 |
| `WEB_DEBUG` | `false` | Flask 调试模式，日用保持 `false` |
| `WEB_THREADED` | `true` | 多线程处理请求，慢请求不阻塞登录 |
| `WEB_MAX_UPLOAD_MB` | `64` | 单次请求体上限（MB），头像/上传图走 base64 |
| `SECRET_KEY` | 空 | session 加密密钥。**留空** = 每次启动随机生成，重启后需重新登录（更安全）；**填固定值** = 重启后保持登录 |
| `INIT_ADMIN_PASSWORD` | 空 | 设置自己的管理密码之前临时使用的密码。留空 = 启动时随机生成 8 位并打印到启动日志 |

> 这枚密码只是临时的：在引导页第 4 步设好自己的密码（或用 WebUI 的「设置 → 修改管理密码」）之后它立即作废，终端也不再打印。在那之前每次启动都会重新打印一遍，漏看一次不用重装。

---

## 2. WS 服务器（OneBot V11 / NapCat）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WS_HOST` | `0.0.0.0` | 反向 WebSocket 监听地址 |
| `WS_PORT` | `6700` | 监听端口。NapCat 里填 `ws://<本机IP>:6700/onebot/v11/ws` |
| `WS_PATH` | `/onebot/v11/ws` | 连接路径，必须以 `/` 开头 |
| `WS_ACCESS_TOKEN` | 空 | 访问令牌，留空表示不校验 |
| `WS_AUTO_START` | `false` | 是否随主服务自动启动 WS 服务器 |
| `WS_CONFIG_PRIORITY` | `file` | 配置优先级，见下方说明 |
| `WS_EVENT_LIMIT` | `300` | 实时事件日志环形缓冲条数 |
| `WS_RAW_LIMIT` | `4000` | 网页展示的单条原始 JSON 截断长度（字符） |
| `WS_MAX_FRAME_MB` | `16` | 单条消息帧上限（MB），合并转发/长消息留余量 |

**`WS_CONFIG_PRIORITY` 是常见坑**：

- `file`（默认）—— WebUI 面板保存的 `ws_config.json` **覆盖** `.env` 里的值，面板可改可存。
- `env` —— 强制以 `.env` 为准，忽略 `ws_config.json`，面板上点「保存配置」会被拒绝。

如果你在面板上改了配置却不生效，先检查这一项。

> **方向一定要搞对**：ILBB 是**服务端**（监听 6700），NapCat 作为**客户端**连过来。详见[消息平台对接](platform-integration.md)。

---

## 3. Bot 指令

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BOT_ENABLED` | `true` | 指令总开关。`false` = 机器人不响应任何指令 |
| `BOT_NAME` | `我在哔哩学习` | 机器人昵称，显示在帮助图标题与文案里 |
| `BOT_PREFIX` | `/` | 指令前缀，可改成 `#` 等 |
| `BOT_GROUP_NEED_AT` | `false` | 群聊里是否必须 @机器人 才响应 |
| `BOT_ALLOW_PRIVATE` | `true` | 是否允许私聊使用指令 |
| `BOT_MEME_LIST_PAGE` | `12` | `/meme list` 素材列表每页条数，超出分多张图发送 |
| `BOT_MAX_IMAGE_MB` | `8` | 单张回图体积上限（MB），过大时压缩或放弃 |
| `BOT_COOLDOWN_SEC` | `3` | 同一用户两次指令的最短间隔（秒），`0` = 不限制 |
| `BOT_FOOTER` | `我在哔哩学习 Emoji Bot · ILBB` | 帮助图落款文字，留空则不显示 |

> 前缀最多取 3 个字符（代码里做了截断）。改成 `#` 后指令就变成 `#help`、`#meme 摸`。

---

## 4. 名言图

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `QUOTE_ENABLED` | `true` | `/名言` 与 `/生成名言` 的总开关 |
| `QUOTE_WIDTH` | `1280` | 横屏画布宽度（像素），建议与高度保持 16:9 |
| `QUOTE_HEIGHT` | `720` | 横屏画布高度（像素） |
| `QUOTE_MASK_ALPHA` | `0.35` | 背景上那层灰色蒙版的不透明度，`0.35` = 压 35% 灰（背景仍可辨认）；玻璃面板 / 头像 / 文字都在蒙版之上 |
| `QUOTE_JPG_QUALITY` | `92` | 静态图（JPG）输出质量（60–100） |
| `QUOTE_AVATAR` | `236` | 左侧独立圆角头像的宽度（像素），高度约为它的 1.32 倍 |
| `QUOTE_TRAY_BLUR` | `30` | 玻璃面板的高斯模糊半径（磨砂核心，越大越糊） |
| `QUOTE_TRAY_GLASS` | `0.58` | 模糊层之上叠加的暖白玻璃浓度（0.2–0.96，越大越白、越不透） |
| `QUOTE_TEXT_MAX` | `56` | 面板内容区文字自动字号上限（像素） |
| `QUOTE_TEXT_MIN` | `22` | 面板内容区文字自动字号下限 |
| `QUOTE_MAX_BODY` | `500` | 面板内容区最大高度，超过则缩字号，到底线就截断加省略号 |
| `QUOTE_NAME_SIZE` | `40` | 右下角署名「—— 用户名」字号（字体跟随全局 `FONT_FAMILY`） |
| `QUOTE_NAME` | `无名氏` | 取不到昵称时的占位名字 |
| `QUOTE_NAME_MAX` | `16` | 署名词最大显示字数 |
| `QUOTE_GIF_MAX_FRAMES` | `60` | 面板内容是动图时输出 GIF，超过此帧数则等间隔抽帧 |
| `QUOTE_GIF_MIN_MS` | `40` | GIF 单帧最短时长（毫秒） |

---

## 5. 插件系统

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PLUGIN_ENABLED` | `true` | 插件总开关。`false` = 不加载任何插件 |
| `PLUGIN_DIR` | `plugins` | 插件根目录，每个子文件夹就是一个插件 |
| `PLUGIN_CONFIG_PATH` | `plugins_config.json` | Web 里修改的插件配置存放文件 |
| `PLUGIN_HOT_RELOAD` | `true` | 热重载：改插件文件 / 增删目录自动生效 |
| `PLUGIN_POLL_SEC` | `3` | 热重载轮询间隔（秒），最小 2 |
| `PLUGIN_WEB_SCHEME` | `http` | 插件自带 Web 的协议 |
| `PLUGIN_WEB_PORT_BASE` | `7000` | 插件 Web 端口自动分配起始值 |
| `PLUGIN_WEB_TIMEOUT` | `4` | 探测插件 Web 是否就绪的超时（秒） |
| `PLUGIN_MAX_IMAGE_MB` | `8` | 单个插件单条指令回图上限（MB） |

详见[插件开发指南](plugin-dev.md)。

---

## 6. 目录与数据文件

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TEMP_DIR` | `temp` | 临时文件目录 |
| `CACHE_DIR` | `cache` | 生成图片缓存目录 |
| `FONT_DIR` | `font` | 字体目录 |
| `FONT_FAMILY` | `system` | 全局字体；`system` = 系统自带中文字体，也可填 `font/` 目录里的字体名 |
| `BG_DIR` | `static/bg` | 背景图存放目录，由后端 `/bg/<文件名>` 提供 |
| `BG_CONFIG_PATH` | `bg_config.json` | 背景配置（类型/链接/模糊/蒙版）持久化文件 |
| `API_KEYS_PATH` | `api_keys.json` | 管理密码哈希 + API Key 存储文件 |
| `OPENAI_V1_DIR` | `cache/v1` | OpenAI 兼容接口出图目录，同时映射为 `/v1/files/<name>` |
| `BG_URL_PREFIX` | `bg` | 上传背景图的对外 URL 前缀，通常不用改 |

> 相对路径按**项目根目录**解析，也可写绝对路径（如 `E:/data/cache`）。所以**启动必须在项目根目录**。

---

## 7. 缓存与画布

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CACHE_EXPIRE_DAYS` | `30` | 生成图片缓存保留天数 |
| `CANVAS_WIDTH` | `600` | 配对卡画布宽度（像素） |
| `CANVAS_HEIGHT` | `800` | 配对卡画布高度（像素） |

---

## 8. 背景图 API

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BG_API_URL` | `https://api.yppp.net/api.php` | 随机背景图接口（登录页/工作台背景） |
| `BG_FETCH_TIMEOUT` | `8` | 背景图请求超时（秒） |

> 这是**第三方接口**，可用性不保证。取不到图时背景会退回纯色，不影响其他功能。

---

## 9. 首次运行引导页

首次启动访问 `http://127.0.0.1:5000/setup` 会进入引导页，它会做四件事：

| 步骤 | 内容 |
| --- | --- |
| 环境自检 | 逐项检查 7 个依赖（flask / requests / pillow / websockets / skia-python / numpy / meme 引擎），缺哪个都会提示跑 `uv pip install -r requirements.txt` |
| 素材下载 | 从原仓库拉取 meme 图片素材补全 `vendor/.../memes/`，带进度与取消 |
| 基础配置 | 机器人昵称、WebUI 端口、指令前缀等，写回 `.env` |
| 设置管理密码 | 设一个属于你自己的管理密码（必填）；此前那枚临时密码立即作废 |

引导没走完时，访问 `/` 会自动把你带回引导页（缺密码时直接落在第 4 步）。

**为什么需要下载素材**：为了把仓库体积控制在几十 MB，`vendor/meme-generator-main/meme_generator/memes/` 下的图片素材（约 2869 个文件、约 254MB）**未入库**，由这一步联网补全。不下载也能启动，但表情生成会大面积失败。

素材是两半拼起来的：图片由这一步下载，而每个表情的定义代码 `memes/<key>/__init__.py` 随仓库分发（约 282 个文件、400 多 KB，见 `.gitignore` 的 vendor 分层）。上游资源清单里只有 png/jpg/gif，所以定义文件缺失时下载补不回来 —— 表情列表会整个空掉，引导页与「状态」页会直接给出提示，按提示确认代码是完整拉取的即可。

---

## 10. 配置优先级实战

**场景一：想在面板上改 WS 设置**

保持 `WS_CONFIG_PRIORITY=file`，直接在 WebUI 面板改，保存后写入 `ws_config.json` 并立即生效。

**场景二：想让 `.env` 说了算（比如 Docker 部署）**

设 `WS_CONFIG_PRIORITY=env`，然后在 Docker 环境变量或 `.env` 里固定所有 WS 参数。

**场景三：忘了管理密码**

密码哈希存在 `api_keys.json` 里。终端每次启动都会打印当前生效的密码；把 `admin_hash` 删掉后重启，会重新生成一枚临时密码并打印，同时 `/` 会把你带回引导页，让你设一个新的。

**场景四：改了 `.env` 但不生效**

按顺序排查：① 是不是写成了 `KEY = value`（**不要有空格**）；② 是否有同名系统环境变量覆盖；③ 是否重启了服务；④ 对 WS 相关的项，检查 `WS_CONFIG_PRIORITY`。

---

[返回文档首页](index.md) ｜ [English](../en/configuration.md)

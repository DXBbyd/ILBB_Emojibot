# 消息平台对接

[English](../en/platform-integration.md) ｜ **中文** ｜ [文档总览](index.md)

ILBB 通过 **OneBot V11** 协议与 QQ 对接，实际落地用的是 **NapCat**。本文讲清楚：谁连谁、怎么连、连上之后能干什么、连不上怎么查。

---

## 一、方向一定要搞对

**ILBB 是 WebSocket 服务端，NapCat 是客户端。**

```
NapCat（登录 QQ）
      │  主动发起「反向 WebSocket」连接
      ▼
ILBB  core/ws_server.py   监听 0.0.0.0:6700/onebot/v11/ws
```

所以配置动作是在 **NapCat 里填 ILBB 的地址**，不是在 ILBB 里填 NapCat 的地址。方向搞反了永远连不上。

| 参数 | 在 ILBB 里（`.env`） | 在 NapCat 里 |
| --- | --- | --- |
| 地址 | `WS_HOST=0.0.0.0`、`WS_PORT=6700` | 填 `ws://<ILBB机器IP>:6700` |
| 路径 | `WS_PATH=/onebot/v11/ws` | 拼在地址后面 |
| 令牌 | `WS_ACCESS_TOKEN=`（留空不校验） | 填相同的 Token |
| 自动启动 | `WS_AUTO_START=false` | — |

---

## 二、对接步骤

### 1. 确认 ILBB 侧的 WS 服务器在跑

两种方式：

- **后台面板** —— 打开 `/admin`，在对接面板里点「启动」；
- **配置文件** —— `.env` 里设 `WS_AUTO_START=true`，随主服务一起启动。

启动后终端会打印：

```
[WS] OneBot V11 WebSocket 服务器已启动 → ws://0.0.0.0:6700/onebot/v11/ws
```

如果配了 `WS_ACCESS_TOKEN`，还会多一行「已启用 access_token 校验」。

### 2. 确认 ILBB 机器的 IP

- Windows：`ipconfig`，找内网 IPv4（形如 `192.168.x.x`）
- Linux：`ip -4 addr show` 或 `hostname -I`

### 3. 在 NapCat 里新增反向 WebSocket

NapCat 的 WebUI / 配置界面里，网络配置新增一项，类型选 **反向 WebSocket（Reverse WebSocket）**：

| 字段 | 填什么 |
| --- | --- |
| URL / 地址 | `ws://192.168.x.x:6700/onebot/v11/ws` |
| Token | 与 `WS_ACCESS_TOKEN` 一致；ILBB 没设就留空 |
| 消息格式 | `array`（数组格式，ILBB 按这个解析） |
| 上报类型 | 建议勾选：消息、消息已发送、通知、请求、元事件 |

保存后 NapCat 会立刻尝试连接。

### 4. 验证连接

回到 ILBB 后台的**实时事件流**：

- **已连上** —— 顶部连接数变成 1，开始滚动显示事件；
- **没反应** —— 见本文最后一节排查。

接着在群里发一条 `/help`，应该能收到图片菜单。

### 5. 防火墙

NapCat 和 ILBB 不在同一台机器上时，ILBB 所在机器必须放行 6700 端口：

```powershell
# Windows（管理员 PowerShell）
New-NetFirewallRule -DisplayName "ILBB OneBot 6700" -Direction Inbound -Protocol TCP -LocalPort 6700 -Action Allow
```

```bash
# Linux（ufw）
sudo ufw allow 6700/tcp
```

---

## 三、协议细节

ILBB 解析的是标准 OneBot V11 上报 JSON，支持这几类 `post_type`：

| `post_type` | 说明 | ILBB 的行为 |
| --- | --- | --- |
| `message` | 收到的消息 | **交给指令系统处理**，命中指令就回复 |
| `message_sent` | 自己发出的消息 | 只展示，不触发指令（避免自问自答） |
| `notice` | 通知（戳一戳、群成员变动等） | 只展示 |
| `request` | 请求（加好友、加群） | 只展示 |
| `meta_event` | 元事件（心跳、生命周期） | 只展示 |

消息里 ILBB 会解析这些**消息段**：

| 段类型 | 用途 |
| --- | --- |
| `text` | 指令正文 |
| `at` | 取被 @ 者的 QQ 号，作为头像素材 |
| `reply` | 取被引用消息的 ID，从中读图片 |
| `image` | 取图片，作为表情素材 |

其余段类型会被忽略。如果整条消息一个 `text` 段都没有，ILBB 会退回用 `raw_message` 兜底。

### 主动调用 OneBot 接口

反方向也能走：ILBB 可以主动向 NapCat 调用任意 OneBot 接口（比如 `send_group_msg` 主动发消息、`get_group_member_list` 拉群成员）。后台的**接口调试面板**内置了 30+ 个接口的参数元数据，会自动渲染成输入框，点一下就发。

按功能分组：

| 分组 | 接口（部分） |
| --- | --- |
| 账号信息 | `get_login_info`、`get_status`、`get_version_info`、`can_send_image`、`can_send_record` |
| 好友与群 | `get_friend_list`、`get_stranger_info`、`get_group_list`、`get_group_info`、`get_group_member_list`、`get_group_member_info`、`get_group_honor_info`、`get_group_msg_history`、`get_friend_msg_history`、`get_group_at_all_remain` |
| 消息发送 | `send_private_msg`、`send_group_msg`、`send_msg`、`delete_msg`、`get_msg`、`get_forward_msg`、`mark_msg_as_read`、`send_like` |
| 群管理 | `set_group_kick`、`set_group_ban`、`set_group_whole_ban`、`set_group_card`、`set_group_name`、`set_group_leave` |

插件里也能调，用 `ctx.call_api(action, params)`，见 [plugin-dev.md](plugin-dev.md)。

---

## 四、后台面板能看什么

打开 `/admin` → 对接面板：

| 功能 | 说明 |
| --- | --- |
| 启停 / 重启 | 不用重启整个程序就能重启 WS 服务 |
| 配置编辑 | 改 host / port / path / token / 自动启动 |
| 实时事件流 | 中文可读的事件摘要，含头像、昵称、群名、消息内容 |
| 原始 JSON | 展开看该事件的完整报文（截断长度由 `WS_RAW_LIMIT` 控制） |
| 接口调试 | 30+ 接口的可视化调用面板，带返回码与关键数据摘要 |
| 连接管理 | 查看当前连接列表，可强制断开某条 |
| 事件缓冲 | 环形缓冲默认保留最近 300 条（`WS_EVENT_LIMIT`），可一键清空 |

### 配置优先级

这是个容易踩的点：

| `WS_CONFIG_PRIORITY` | 行为 |
| --- | --- |
| `file`（默认） | 面板保存的 `ws_config.json` **覆盖** `.env` 的默认值，面板可改可存 |
| `env` | 强制以 `.env` 为准，忽略 `ws_config.json`，面板的「保存配置」会被拒绝 |

如果你改了 `.env` 却发现没生效，多半是被 `ws_config.json` 覆盖了——把这一项设成 `env`，或者直接在面板里改。

---

## 五、REST API 概览

WebUI 自己的接口（`/api/*`，**需要登录**）：

| 分组 | 前缀 | 主要端点 |
| --- | --- | --- |
| 工作台 | `/api/*` | `get_user_info`、`generate_image`、`preview/<key>`、`clear_cache`、`cache_status`、`status` |
| 配对卡 | `/api/*` | `card/meta` |
| 背景 | `/api/background*` | `background`、`background/set`、`background/refresh`、`background/upload`、`background/reset` |
| 表情 | `/api/meme/*` | `list`、`preview/<key>`、`generate` |
| 指令 | `/api/bot/*` | `status`、`memes`、`preview`、`chat`、`chat/stats` |
| 名言图 | `/api/quote/*` | `config`、`generate` |
| 对接 | `/api/ws/*` | `status`、`messages`、`actions`、`config`、`start`、`stop`、`restart`、`send`、`avatar`、`events/clear`、`disconnect` |
| 插件 | `/api/plugins/*` | `list`、`toggle`、`reload`、`config`、`web` |
| 引导页 | `/api/setup/*` | `state`、`env-check`、`check`、`assets/download`、`assets/progress`、`assets/cancel`、`config`、`complete`、`skip` |

后台还有接口调用统计（`/api/status` 里能看到各端点调用次数）。

---

## 六、OpenAI 兼容层 `/v1`

ILBB 对外暴露了一层 **OpenAI 风格**的接口，任何 OpenAI 客户端都能直接调用它出表情包。

**鉴权**：请求头带 `Authorization: Bearer <API Key>`。API Key 在后台设置页生成与管理（可禁用）。

| 端点 | 方法 | 作用 |
| --- | --- | --- |
| `/v1/images/generations` | POST | 按 prompt 生成表情图 |
| `/v1/images/edits` | POST | 带输入图的编辑式生成 |
| `/v1/cards` | POST | 生成配对卡片 |
| `/v1/models` | GET | 列出可用模型 |
| `/v1/files/<name>` | GET | 取回生成的文件 |

典型调用：

```bash
curl -X POST http://127.0.0.1:5000/v1/images/generations \
  -H "Authorization: Bearer <你的API Key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"petpet","prompt":"petpet 头像"}'
```

错误返回也按 OpenAI 格式（`error.type` / `error.param` / `error.code`），缺少或无效 Key 会分别返回 `missing_api_key` / `invalid_api_key`。

> `/v1/*` 与 `/api/*` 走的是**不同**的鉴权：前者用 Bearer API Key，后者用登录 session。

---

## 七、连不上怎么查

按这个顺序排查，基本能定位：

1. **ILBB 的 WS 服务器起来了吗**
   终端有没有那行 `OneBot V11 WebSocket 服务器已启动`；后台对接面板状态是不是「运行中」。

2. **地址能从 NapCat 那台机器访问到吗**
   在 NapCat 所在机器上执行：
   ```bash
   curl -v http://192.168.x.x:6700/onebot/v11/ws
   ```
   连不上就是网络/防火墙问题（见第二步第 5 点）。

3. **Token 对得上吗**
   一边设了 `WS_ACCESS_TOKEN`、另一边留空（或两边不一致）都会被拒。日志里会有相关的鉴权失败提示。

4. **路径写对了吗**
   默认是 `/onebot/v11/ws`，很容易漏掉前面的 `/` 或写错。

5. **消息格式选对了吗**
   NapCat 侧要选 **array**（数组）。如果选成 `string`，ILBB 解析不到 `text` / `at` / `image` 段。

6. **连上了但机器人不回**
   转到指令侧排查：`BOT_ENABLED` 是否为 `true`、前缀对不对（默认 `/`）、群聊是否要求 @（`BOT_GROUP_NEED_AT`）、私聊是否被关（`BOT_ALLOW_PRIVATE`）、是否撞上冷却（`BOT_COOLDOWN_SEC`）。后台的「指令中心」可以用干跑预览单独验证指令逻辑，跟网络问题解耦。

7. **事件流里能看到消息，但回复发不出去**
   看接口调试面板里 `can_send_image` 的返回。另外注意 `BOT_MAX_IMAGE_MB`（默认 8）——GIF 表情过大时会压缩或放弃。

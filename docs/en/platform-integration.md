# Message Platform Integration

**English** ｜ [中文](../zh/platform-integration.md) ｜ [Docs Home](index.md)

ILBB talks to QQ over the **OneBot V11** protocol, and the implementation actually deployed in production is **NapCat**. This document explains clearly: who connects to whom, how to connect, what you can do once connected, and how to troubleshoot when the connection fails.

---

## I. Getting the direction right matters

**ILBB is the WebSocket server; NapCat is the client.**

```
NapCat (logged-in QQ)
      │  Actively initiates a "reverse WebSocket" connection
      ▼
ILBB  core/ws_server.py   listening on 0.0.0.0:6700/onebot/v11/ws
```

So the configuration action is to fill in **ILBB's address inside NapCat**, not to fill in NapCat's address inside ILBB. Get the direction backwards and it will never connect.

| Parameter | In ILBB (`.env`) | In NapCat |
| --- | --- | --- |
| Address | `WS_HOST=0.0.0.0`, `WS_PORT=6700` | Fill in `ws://<ILBB machine IP>:6700` |
| Path | `WS_PATH=/onebot/v11/ws` | Appended after the address |
| Token | `WS_ACCESS_TOKEN=` (leave empty to skip verification) | Fill in the same Token |
| Auto start | `WS_AUTO_START=false` | — |

---

## II. Integration steps

### 1. Confirm that the WS server on the ILBB side is running

Two ways:

- **Admin panel** —— open `/admin` and click "Start" in the integration panel;
- **Config file** —— set `WS_AUTO_START=true` in `.env` so it starts together with the main service.

After starting, the terminal prints:

```
[WS] OneBot V11 WebSocket 服务器已启动 → ws://0.0.0.0:6700/onebot/v11/ws
```

If `WS_ACCESS_TOKEN` is configured, one more line "已启用 access_token 校验" will appear.

### 2. Confirm the IP of the ILBB machine

- Windows: `ipconfig`, find the LAN IPv4 (of the form `192.168.x.x`)
- Linux: `ip -4 addr show` or `hostname -I`

### 3. Add a reverse WebSocket in NapCat

In NapCat's WebUI / configuration interface, add a new network configuration item and choose the type **Reverse WebSocket**:

| Field | What to fill in |
| --- | --- |
| URL / address | `ws://192.168.x.x:6700/onebot/v11/ws` |
| Token | Same as `WS_ACCESS_TOKEN`; leave empty if ILBB has not set one |
| Message format | `array` (array format; ILBB parses it this way) |
| Report types | Recommended to check: message, message sent, notice, request, meta event |

After saving, NapCat will try to connect immediately.

### 4. Verify the connection

Go back to the **live event stream** in the ILBB admin panel:

- **Connected** —— the connection count at the top becomes 1 and events start scrolling;
- **No reaction** —— see the last section of this document for troubleshooting.

Then send a `/help` in the group; you should receive the image menu.

### 5. Firewall

When NapCat and ILBB are not on the same machine, the machine running ILBB must allow port 6700:

```powershell
# Windows (Administrator PowerShell)
New-NetFirewallRule -DisplayName "ILBB OneBot 6700" -Direction Inbound -Protocol TCP -LocalPort 6700 -Action Allow
```

```bash
# Linux (ufw)
sudo ufw allow 6700/tcp
```

---

## III. Protocol details

What ILBB parses is standard OneBot V11 report JSON, and it supports these `post_type` categories:

| `post_type` | Description | ILBB behavior |
| --- | --- | --- |
| `message` | Messages received | **Handed to the command system**; replies when a command matches |
| `message_sent` | Messages sent by itself | Displayed only, does not trigger commands (avoids answering itself) |
| `notice` | Notices (pokes, group member changes, etc.) | Displayed only |
| `request` | Requests (friend requests, group join requests) | Displayed only |
| `meta_event` | Meta events (heartbeat, lifecycle) | Displayed only |

Inside a message, ILBB parses these **message segments**:

| Segment type | Purpose |
| --- | --- |
| `text` | Command body |
| `at` | Takes the QQ number of the @-mentioned user, to be used as avatar material |
| `reply` | Takes the ID of the quoted message and reads images from it |
| `image` | Takes the image, to be used as meme material |

Other segment types are ignored. If an entire message contains no `text` segment at all, ILBB falls back to `raw_message`.

### Calling OneBot APIs proactively

The reverse direction also works: ILBB can proactively call any OneBot API on NapCat (for example `send_group_msg` to send a message proactively, or `get_group_member_list` to pull group members). The **API debugger panel** in the admin panel ships with parameter metadata for 30+ APIs, automatically rendered into input boxes — one click sends the call.

Grouped by function:

| Group | APIs (partial) |
| --- | --- |
| Account info | `get_login_info`, `get_status`, `get_version_info`, `can_send_image`, `can_send_record` |
| Friends and groups | `get_friend_list`, `get_stranger_info`, `get_group_list`, `get_group_info`, `get_group_member_list`, `get_group_member_info`, `get_group_honor_info`, `get_group_msg_history`, `get_friend_msg_history`, `get_group_at_all_remain` |
| Sending messages | `send_private_msg`, `send_group_msg`, `send_msg`, `delete_msg`, `get_msg`, `get_forward_msg`, `mark_msg_as_read`, `send_like` |
| Group management | `set_group_kick`, `set_group_ban`, `set_group_whole_ban`, `set_group_card`, `set_group_name`, `set_group_leave` |

Plugins can call them too, using `ctx.call_api(action, params)`, see [plugin-dev.md](plugin-dev.md).

---

## IV. What the admin panel shows

Open `/admin` → integration panel:

| Feature | Description |
| --- | --- |
| Start / stop / restart | Restart the WS service without restarting the whole program |
| Config editing | Change host / port / path / token / auto start |
| Live event stream | Human-readable event summaries in Chinese, including avatar, nickname, group name and message content |
| Raw JSON | Expand to see the full payload of that event (the truncation length is controlled by `WS_RAW_LIMIT`) |
| API debugging | A visual call panel for 30+ APIs, with return codes and key data summaries |
| Connection management | View the current connection list and forcibly disconnect one of them |
| Event buffer | The ring buffer keeps the latest 300 entries by default (`WS_EVENT_LIMIT`), and can be cleared with one click |

### Configuration precedence

This is an easy trap to fall into:

| `WS_CONFIG_PRIORITY` | Behavior |
| --- | --- |
| `file` (default) | The `ws_config.json` saved from the panel **overrides** the defaults in `.env`, and the panel can modify and save |
| `env` | Forces `.env` to have the final say, ignores `ws_config.json`, and the panel's "Save config" will be rejected |

If you changed `.env` but found it did not take effect, it is most likely overridden by `ws_config.json` —— set this item to `env`, or simply change it in the panel.

---

## V. REST API overview

WebUI's own endpoints (`/api/*`, **login required**):

| Group | Prefix | Main endpoints |
| --- | --- | --- |
| Workbench | `/api/*` | `get_user_info`, `generate_image`, `preview/<key>`, `clear_cache`, `cache_status`, `status` |
| Pairing card | `/api/*` | `card/meta` |
| Background | `/api/background*` | `background`, `background/set`, `background/refresh`, `background/upload`, `background/reset` |
| Memes | `/api/meme/*` | `list`, `preview/<key>`, `generate` |
| Commands | `/api/bot/*` | `status`, `memes`, `preview`, `chat`, `chat/stats` |
| Quote image | `/api/quote/*` | `config`, `generate` |
| Integration | `/api/ws/*` | `status`, `messages`, `actions`, `config`, `start`, `stop`, `restart`, `send`, `avatar`, `events/clear`, `disconnect` |
| Plugins | `/api/plugins/*` | `list`, `toggle`, `reload`, `config`, `web` |
| Setup page | `/api/setup/*` | `state`, `env-check`, `check`, `assets/download`, `assets/progress`, `assets/cancel`, `config`, `complete`, `skip` |

The admin backend also keeps API call statistics (the call count of each endpoint is visible in `/api/status`).

---

## VI. OpenAI-compatible layer `/v1`

ILBB exposes an **OpenAI-style** API layer, so any OpenAI client can call it directly to generate memes.

**Authentication**: send the header `Authorization: Bearer <your API Key>`. API Keys are generated and managed on the settings page in the admin panel (and can be disabled).

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/v1/images/generations` | POST | Generate a meme image from a prompt |
| `/v1/images/edits` | POST | Edit-style generation with an input image |
| `/v1/cards` | POST | Generate a pairing card |
| `/v1/models` | GET | List available models |
| `/v1/files/<name>` | GET | Retrieve a generated file |

A typical call:

```bash
curl -X POST http://127.0.0.1:5000/v1/images/generations \
  -H "Authorization: Bearer <your API Key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"petpet","prompt":"petpet 头像"}'
```

Error responses also follow the OpenAI format (`error.type` / `error.param` / `error.code`); a missing or invalid key returns `missing_api_key` / `invalid_api_key` respectively.

> `/v1/*` and `/api/*` use **different** authentication: the former uses a Bearer API Key, the latter uses a login session.

---

## VII. Troubleshooting a failed connection

Check in this order and you can basically pinpoint the problem:

1. **Is ILBB's WS server up**
   Does the terminal show the line `OneBot V11 WebSocket 服务器已启动`; is the status in the admin integration panel "Running".

2. **Is the address reachable from the machine running NapCat**
   On the machine where NapCat runs, execute:
   ```bash
   curl -v http://192.168.x.x:6700/onebot/v11/ws
   ```
   If it cannot connect, it is a network / firewall problem (see point 5 of step 2).

3. **Does the Token match**
   If one side sets `WS_ACCESS_TOKEN` and the other leaves it empty (or the two sides differ), the connection will be rejected. Related authentication failure messages will appear in the log.

4. **Is the path written correctly**
   The default is `/onebot/v11/ws`; it is very easy to drop the leading `/` or mistype it.

5. **Is the message format selected correctly**
   On the NapCat side you must choose **array**. If `string` is selected, ILBB cannot parse the `text` / `at` / `image` segments.

6. **Connected but the bot does not reply**
   Switch to troubleshooting on the command side: whether `BOT_ENABLED` is `true`, whether the prefix is right (default `/`), whether group chats require an @ (`BOT_GROUP_NEED_AT`), whether private chat is disabled (`BOT_ALLOW_PRIVATE`), and whether the cooldown is hit (`BOT_COOLDOWN_SEC`). The "Command Center" in the admin panel can use a dry-run preview to verify command logic on its own, decoupled from network problems.

7. **Messages are visible in the event stream, but replies cannot be sent out**
   Look at the return value of `can_send_image` in the API debugger panel. Also note `BOT_MAX_IMAGE_MB` (default 8) —— oversized GIF memes will be compressed or dropped.

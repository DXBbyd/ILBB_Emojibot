# 插件开发指南

**中文** ｜ [English](../en/plugin-dev.md)

ILBB 的插件系统遵循一条极简规则：**一个文件夹 = 一个插件**。把文件夹丢进 `plugins/` 就会被识别，删掉文件夹就等于卸载，改代码会自动热重载。

内置的 `plugins/example/` 演示了全部能力，**推荐直接复制它改个名**作为起点。

---

## 1. 最小插件

目录结构：

```
plugins/
  hello/
    plugin.json      # 清单（必需）
    main.py          # 入口（必需，须提供 setup(ctx)）
```

`plugin.json`：

```json
{
  "id": "hello",
  "name": "打招呼",
  "version": "1.0.0",
  "author": "你的名字",
  "desc": "最小示例：收到 /hello 就回一句话。",
  "entry": "main.py",
  "enabled": true
}
```

`main.py`：

```python
# -*- coding: utf-8 -*-

def cmd_hello(args, ctx, p):
    """/hello —— 回一句问候。"""
    who = "、".join(args) if args else "世界"
    return ([], ["你好，%s！" % who])


def setup(ctx):
    ctx.on_command(["hello"], cmd_hello)
    ctx.log("hello 插件已载入")
    return True
```

放进 `plugins/`，等一个轮询周期（默认 3 秒），群里发 `/hello` 就能收到回复。`ctx.log()` 的内容会直接打到 ILBB 主控台。

---

## 2. plugin.json 字段说明

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 文件夹名 | 插件唯一标识，只允许字母 / 数字 / 下划线 / 连字符，最长 32 字符 |
| `name` | string | 同 `id` | 显示名 |
| `version` | string | `0.0.0` | 版本号，`ctx.version` 可取 |
| `author` | string | 空 | 作者 |
| `desc` | string | 空 | 描述，显示在 Web 插件面板 |
| `entry` | string | `main.py` | 入口文件，**不允许**绝对路径或 `..` 上级目录 |
| `enabled` | bool | `true` | 首次载入时是否默认启用 |
| `web` | bool | `false` | 是否开启独立页面（见第 6 节） |
| `web_title` | string | 同 `name` | 独立页面的标题 |
| `web_path` | string | `/` | 独立页面的入口路径 |
| `web_port` | int | `0` | 独立页面端口；`0` 表示从 `PLUGIN_WEB_PORT_BASE`（默认 7000）起自动分配 |
| `config` | array | 空 | 配置项声明（见第 5 节） |

`id` 非法或 `entry` 找不到时，插件不会载入，Web 插件面板的「装错了的插件」区域会给出原因。

---

## 3. 生命周期

| 函数 | 是否必需 | 何时调用 |
| --- | --- | --- |
| `setup(ctx)` | **必需** | 插件载入时调用一次。返回 `True` / 无返回值视为成功 |
| `teardown()` | 可选 | 插件卸载、热禁用、代码变更重载前调用 |

热重载会监控这些后缀的文件变更：`.py` `.json` `.html` `.js` `.css` `.txt` `.md` `.svg`。也就是说**改前端文件也会触发重载**，不用手动重启。

重载时旧模块会被清理（`_purge_modules`），所以插件内部**不要依赖模块级全局变量长期保存状态**——需要持久化请写文件或存到 `ctx.set_cfg()`。

---

## 4. 指令与事件

### 4.1 注册指令

```python
def setup(ctx):
    ctx.on_command(["hello", "hi"], cmd_hello)   # 支持别名列表
```

`on_command(triggers, fn)` 的触发词**不区分大小写**，也不带 `/`。触发时 ILBB 会把消息按空格切开，第一个词匹配触发词，**其余部分作为 `args` 列表**传入。

指令函数签名：

```python
def fn(args, ctx, p):
    # args —— list[str]，指令后面的参数（已按空格切分）
    # ctx  —— 触发这条指令的聊天上下文
    # p    —— PluginContext（本插件的上下文对象）
    return ([图片bytes, ...], ["文本", ...])
```

返回值约定：

| 返回 | 效果 |
| --- | --- |
| `([], ["文本"])` | 只发文本（群里会自动 @ 发送者） |
| `([png_bytes], [])` | 只发图片，可放多张 |
| `([png_bytes], ["说明"])` | 图文一起发 |
| `None` | 不回复（用来做「静默处理」） |
| 纯字符串 | 等价于 `([], [str])` |

### 4.2 聊天上下文 `ctx`（指令内）

| 键 | 说明 |
| --- | --- |
| `mtype` | `"group"` 或 `"private"` |
| `gid` | 群号（私聊时为空） |
| `uid` | 发送者 QQ 号 |
| `av` | 发送者头像 URL |
| `message_id` | 消息 ID |

> 注意：这个名字容易和 `PluginContext` 混淆。指令函数里的第三个参数才是 `PluginContext`。

### 4.3 监听事件

```python
def on_event(ev, client):
    extra = (ev or {}).get("extra") or {}
    if extra.get("mtype") != "group":
        return
    ...

def setup(ctx):
    ctx.on_event(on_event)
```

`ev` 是 ILBB 解析后的事件字典，`ev["extra"]` 里同样是 `mtype` / `gid` / `uid` / `av`。`client` 是底层 WebSocket 连接对象，一般用不到。

事件回调在独立线程里执行，**不要做长时间阻塞操作**，否则会拖慢事件分发。抛异常只会打日志，不会影响主服务。

---

## 5. 配置项声明

在 `plugin.json` 的 `config` 数组里声明，ILBB 会自动在 Web 面板生成表单，并在 `plugins_config.json` 里持久化。

```json
"config": [
  {
    "key": "greet",
    "label": "打招呼文本",
    "type": "text",
    "default": "你好",
    "placeholder": "请输入",
    "hint": "群里发 /hello 时回复的内容。"
  }
]
```

支持的 `type`：

| 类型 | Web 上渲染成 | 单选默认值 | 多选默认值 |
| --- | --- | --- | --- |
| `text` | 单行输入框 | `""` | — |
| `textarea` | 多行输入框 | `""` | — |
| `int` | 数字输入框 | `0` | — |
| `bool` | 开关 | `false` | — |
| `enum` | 下拉菜单（需配 `options`） | `""` | — |
| `friend` | **好友下拉栏** | `""` | `[]` |
| `group` | **群聊下拉栏** | `""` | `[]` |
| `group_member` | **群成员下拉栏** | `""` | `[]` |

`friend` / `group` / `group_member` 是 ILBB 的特色：选项直接从 NapCat 当前登录 QQ 的好友 / 群 / 群成员列表拉取，**插件侧不用写一行接口调用**。加上 `"multi": true` 就变多选，以标签形式展示。

> `group_member` 的选项**跟随同一插件里第一个 `group` / `group_member` 已选中的群**联动，所以典型写法是把「选哪个群」放在前面。

`enum` 的 `options` 写法：

```json
"options": [
  { "value": "normal", "label": "普通" },
  { "value": "strict", "label": "严格" }
]
```

其他可选字段：`placeholder`（占位提示）、`hint`（表单下方说明）、`multi`（是否多选）。

### 读取与写入配置

```python
def cmd_info(args, ctx, p):
    greet = p.cfg("greet", "默认值")     # 读单个
    allv  = p.cfg()                      # 读全部，返回 dict
    p.set_cfg("greet", "新值")           # 写回并落盘
    return ([], [greet])
```

`p.cfg(key, default)` 在 key 不存在时返回 `default`。

### 配置热生效

可选实现 `on_config(vals, ctx)`，Web 上点「保存配置」时会调用它，**不需要重载代码**：

```python
def on_config(vals, ctx):
    ctx.log("配置已更新：%r" % (vals,))
```

---

## 6. PluginContext 全量 API

`setup(ctx)` 拿到的对象提供以下能力：

### 基础信息

| 成员 | 说明 |
| --- | --- |
| `ctx.id` | 插件 id |
| `ctx.name` | 插件名 |
| `ctx.version` | 版本号 |
| `ctx.folder` | 插件目录绝对路径 |
| `ctx.web_port` | 本插件独立页面的端口（未开启为 `0`） |
| `ctx.web_url(host="127.0.0.1")` | 本插件独立页面的完整 URL，未开启返回 `""` |

### 日志与配置

| 方法 | 说明 |
| --- | --- |
| `ctx.log(msg)` | 输出到 ILBB 主控台，带 `[插件id]` 前缀 |
| `ctx.cfg(key, default)` / `ctx.cfg()` | 读配置 |
| `ctx.set_cfg(key, value)` | 写配置并落盘 |

### 注册

| 方法 | 说明 |
| --- | --- |
| `ctx.on_command(triggers, fn)` | 注册指令，`triggers` 可为字符串或列表 |
| `ctx.on_event(fn)` | 注册事件回调 `fn(ev, client)` |

### 收发消息

| 方法 | 说明 |
| --- | --- |
| `ctx.send_group(group_id, message)` | 发群消息，`message` 可以是字符串或消息段数组 |
| `ctx.send_private(user_id, message)` | 发私聊消息 |
| `ctx.send_text(ctx, text)` | **按当前聊天上下文回复**，群里自动带 @ |
| `ctx.send_image(ctx, png_bytes)` | 按当前聊天上下文回图（内部转 base64） |
| `ctx.call_api(action, params, timeout=6.0)` | 直调任意 OneBot 接口，返回原始响应字典 |

### 数据源

| 方法 | 返回 |
| --- | --- |
| `ctx.friends()` | `[{"user_id", "nickname", "remark"}, ...]` |
| `ctx.groups()` | `[{"group_id", "group_name", "member_count"}, ...]` |
| `ctx.group_members(gid)` | `[{"user_id", "nickname", "card", "role"}, ...]` |
| `ctx.self_account()` | 当前登录账号信息 |

接口调用失败时这些方法返回空列表，不需要自己判空异常。

---

## 7. 独立 Web 页面

想让插件有自己的控制台，两步：

1. `plugin.json` 里写 `"web": true`（可选 `web_title` / `web_path` / `web_port`）。
2. `setup(ctx)` 里用 `ctx.web_port` 起一个 HTTP 服务。

ILBB 会把插件页面嵌在主界面里显示，IP 自动取浏览器当前主机名，端口按 manifest 分配。

```python
import os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
_httpd = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):     # 别往主控台刷访问日志
        pass

    def do_GET(self):
        full = os.path.join(WEB_DIR, "index.html")
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def setup(ctx):
    global _httpd
    if ctx.web_port:
        _httpd = ThreadingHTTPServer(("0.0.0.0", ctx.web_port), Handler)
        _httpd.daemon_threads = True
        threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    return True


def teardown():
    if _httpd:
        _httpd.shutdown()
        _httpd.server_close()
```

端口分配规则：manifest 里 `web_port` 填了有效值（1024–65535）就用它，否则从 `PLUGIN_WEB_PORT_BASE`（默认 7000）起找第一个空闲端口。

---

## 8. 调试与排错

**必备开关**：`.env` 里 `PLUGIN_ENABLED=true`、`PLUGIN_HOT_RELOAD=true`。

**常用调试流程**：

1. 看 ILBB 主控台 —— 插件日志前缀是 `[插件]` 和 `[你的插件id]`。
2. 打开 Web 界面的插件面板 —— 能看到插件列表、载入状态、配置表单，「装错了的插件」区域会显示 `缺少 plugin.json`、`entry 不允许使用绝对路径` 之类的具体原因。
3. 点「重载」强制重新扫描，不用等轮询。
4. 命令行里改代码 → 保存 → 等 3 秒 → 直接发指令测试。

**高频坑**：

| 现象 | 原因 |
| --- | --- |
| 插件不出现 | 目录没有 `plugin.json`，或 `plugin.json` 不是合法 JSON |
| 提示 `找不到入口文件` | `entry` 写的名字和实际文件名不一致 |
| 指令没反应 | 指令不区分大小写但没有 `/`；确认没和内置指令（`help` / `meme` / `pair` / `quote`）重名 |
| 指令报错 | 异常会被捕获并回一张错误卡片，具体堆栈在主控台 |
| 配置读出来是空的 | `group_member` 字段依赖前面选中的群；群里没选就不会有选项 |
| 改了代码没生效 | 后缀不在监控列表内（只认 `.py .json .html .js .css .txt .md .svg`） |
| 状态丢失 | 模块级全局变量会在重载时被清空，需要持久化请写文件或 `set_cfg` |

**安全提醒**：插件代码在主进程内运行，拥有完整的文件与网络权限。**只安装你信任来源的插件**，不要从不明渠道下载插件文件夹。

---

## 9. 复制起步模板

```bash
# Windows（PowerShell）
Copy-Item -Recurse plugins\example plugins\myplugin
```

```bash
# Linux / macOS
cp -r plugins/example plugins/myplugin
```

然后把 `plugins/myplugin/plugin.json` 里的 `id` 改成 `myplugin`（必须与文件夹名一致才最不容易出错），删掉 `main.py` 里不需要的示例，开始写自己的逻辑。

---

[返回文档首页](index.md) ｜ [English](../en/plugin-dev.md)

# -*- coding: utf-8 -*-
"""ILBB 示例插件 —— 插件系统全部能力的演示。

复制整个 example 文件夹改名，就是一个新插件的起点。

约定
----
* 文件夹里必须有 ``plugin.json``（清单）与 ``main.py``（入口，含 ``setup(ctx)``）。
* ``setup(ctx)`` 在插件被载入时调用一次；``teardown()`` 在卸载 / 热禁用时调用。
* 指令处理函数签名::

      def fn(args, ctx, p):
          # args —— 指令后面按空格切开的参数列表
          # ctx  —— 触发这条指令的聊天上下文（mtype / gid / uid / av / message_id ...）
          # p    —— PluginContext
          return ([图片bytes, ...], ["文本", ...])   # 或者 None 表示不回复

* 事件处理函数签名：``def fn(ev, client)``，ev["extra"] 里有 mtype / gid / uid / av。
* ``on_config(vals, ctx)`` 可选：Web 上保存配置后热生效，不用重载代码。
"""

from __future__ import annotations

import json
import os
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")

_ctx = None                      # 本插件自己的 PluginContext
_hits = 0                        # 统计到的群消息条数
_recent = []                     # 最近几条消息摘要（给独立页面看）
_lock = threading.Lock()
_httpd = None
_thread = None

MODE_LABEL = {"normal": "普通", "strict": "严格", "quiet": "静默"}
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain; charset=utf-8",
}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _as_list(v):
    """配置里的 friend/group/group_member 单选是字符串、多选是列表，这里统一成列表。"""
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    s = str(v or "").strip()
    return [s] if s else []


def _silent(p):
    return bool(p.cfg("silent", False)) or str(p.cfg("mode", "") or "") == "quiet"


def _remember(text):
    with _lock:
        _recent.insert(0, text)
        del _recent[8:]


# ---------------------------------------------------------------------------
# 指令
# ---------------------------------------------------------------------------
def cmd_example(args, ctx, p):
    """/example —— 打个招呼，并汇报自己配置与运行状态。"""
    if _silent(p):
        p.log("安静模式：收到 /example，不发言")
        return None
    lines = [str(p.cfg("greet", "你好，我是示例插件 👋")), ""]
    intro = str(p.cfg("intro", "") or "").strip()
    if intro:
        lines.append(intro)
        lines.append("")
    with _lock:
        hits = _hits
    lines.append("模式：%s｜已统计 %d 条群消息" % (
        MODE_LABEL.get(str(p.cfg("mode", "normal")), p.cfg("mode", "normal")), hits))
    if str(p.cfg("mode", "")) == "strict":
        lines.append("（严格模式：请勿滥用指令。）")
    return ([], ["\n".join(lines)])


def cmd_echo(args, ctx, p):
    """/echodemo a b c —— 把参数原样回显，演示 args 怎么拿。"""
    if not args:
        return ([], ["用法：/echodemo 要回显的内容"])
    return ([], ["参数 %d 个：%s" % (len(args), " / ".join(args))])


def cmd_info(args, ctx, p):
    """/exampleinfo —— 把 Web 上配置的值读出来，验证 friend / group / group_member 落到插件里的样子。"""
    owner = _as_list(p.cfg("owner"))
    admins = _as_list(p.cfg("admins"))
    groups = _as_list(p.cfg("watch_groups"))
    members = []
    for uid in _as_list(p.cfg("watch_user")) + _as_list(p.cfg("watch_users")):
        if uid not in members:
            members.append(uid)
    rows = [
        "插件：%s v%s" % (p.name, p.version),
        "插件目录：%s" % os.path.basename(p.folder),
        "每次最多处理：%s 条" % p.cfg("limit", 5),
        "安静模式：%s" % ("开" if p.cfg("silent", False) else "关"),
        "通知好友：%s" % ("、".join(owner) if owner else "（未选）"),
        "管理员：%s" % ("、".join(admins) if admins else "（未选）"),
        "统计群：%s" % ("、".join(groups) if groups else "全部群"),
        "重点成员：%s" % ("、".join(members) if members else "（未选）"),
    ]
    return ([], ["\n".join(rows)])


# ---------------------------------------------------------------------------
# 事件
# ---------------------------------------------------------------------------
def on_event(ev, client):
    """监听群消息：统计条数，并记录重点成员。"""
    global _hits
    extra = (ev or {}).get("extra") or {}
    if extra.get("mtype") != "group":
        return
    if _ctx is None:
        return
    gid = str(extra.get("gid") or "")
    if _as_list(_ctx.cfg("watch_groups")) and gid not in _as_list(_ctx.cfg("watch_groups")):
        return
    uid = str(extra.get("uid") or "")
    with _lock:
        _hits += 1
        hits = _hits
    _remember("#%d 群 %s · 用户 %s" % (hits, gid, uid))
    focus = _as_list(_ctx.cfg("watch_user")) + _as_list(_ctx.cfg("watch_users"))
    if uid and uid in focus:
        _ctx.log("重点成员 %s 在群 %s 发言了" % (uid, gid))


# ---------------------------------------------------------------------------
# 配置热生效（Web 上点「保存配置」时调用，不需要重载代码）
# ---------------------------------------------------------------------------
def on_config(vals, ctx):
    ctx.log("配置已更新：%s" % json.dumps(vals, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 独立 Web 页面：插件自己的 HTTP 服务，端口由 ILBB 分配后经 ctx.web_port 告知
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "ILBBExample/1.0"

    def log_message(self, *a):        # 不要往 ILBB 主控台刷访问日志
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = (self.path or "/").split("?", 1)[0].split("#", 1)[0]
        if path == "/api/stats":
            with _lock:
                payload = {
                    "ok": True,
                    "id": _ctx.id if _ctx else "example",
                    "name": _ctx.name if _ctx else "示例插件",
                    "version": _ctx.version if _ctx else "0.0.0",
                    "hits": _hits,
                    "recent": list(_recent),
                    "config": _ctx.cfg() if _ctx else {},
                }
            self._send(200, json.dumps(payload, ensure_ascii=False), MIME[".json"])
            return

        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, rel.replace("/", os.sep)))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self._send(404, "<h1 style='font:600 18px sans-serif;padding:40px'>404 页面不存在</h1>")
            return
        ctype = MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        try:
            with open(full, "rb") as fh:
                self._send(200, fh.read(), ctype)
        except Exception:
            self._send(500, "读取文件失败")


def _start_web(port):
    global _httpd, _thread
    _stop_web()
    if not port or not os.path.isdir(WEB_DIR):
        return False
    try:
        _httpd = ThreadingHTTPServer(("0.0.0.0", int(port)), _Handler)
    except Exception:
        traceback.print_exc()
        _httpd = None
        return False
    _httpd.daemon_threads = True
    _thread = threading.Thread(target=_httpd.serve_forever,
                               name="ilbb_plugin_example_web", daemon=True)
    _thread.start()
    return True


def _stop_web():
    global _httpd, _thread
    if _httpd is not None:
        try:
            _httpd.shutdown()
            _httpd.server_close()
        except Exception:
            pass
        _httpd = None
    _thread = None


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
def setup(ctx):
    global _ctx
    _ctx = ctx
    ctx.on_command(["example"], cmd_example)
    ctx.on_command(["echodemo"], cmd_echo)
    ctx.on_command(["exampleinfo", "demohelp"], cmd_info)
    ctx.on_event(on_event)
    ok = _start_web(ctx.web_port)
    ctx.log("已载入 v%s｜指令 /example · /echodemo · /exampleinfo｜独立页面 %s" % (
        ctx.version, ctx.web_url() if ok else "未开启"))
    return True


def teardown():
    _stop_web()
    if _ctx is not None:
        _ctx.log("已卸载，独立页面已关闭")

# -*- coding: utf-8 -*-
"""OneBot V11 / NapCat WebSocket 服务器

设计目标
--------
1. 项目自身作为 WS 服务器，等待 NapCat 以「反向 WebSocket」方式连接进来
   （NapCat 里填写：ws://<本机IP>:<WS_PORT><WS_PATH>，默认 ws://<本机IP>:6700/onebot/v11/ws）。
2. 协议层使用成熟的 websockets 库（同步 API websockets.sync.server），
   不再手写握手 / 帧解析，稳定性更好。
3. 解析 OneBot V11 上报的 JSON（message / message_sent / notice / request /
   meta_event），格式化成中文可读信息并打印到终端。
4. 维护运行状态、连接列表、收发统计与最近事件环形缓冲，供 WebUI 查询。
5. 提供 call_api()，可主动向 NapCat 调用 OneBot 接口（WebUI 接口测试用）。

对外 API（供 app.py 调用）
-------------------------
    get_config() / set_config(d)
    is_running() / start() / stop() / restart()
    status(include_events, event_limit)      -> dict
    call_api(action, params, timeout)        -> 主动调用 OneBot 接口并等待回包
    actions()                                -> OneBot 接口参数元数据（接口调试面板）
    clear_events() / disconnect(client_id)
    add_event_handler(fn)                    -> 注册事件钩子（自动回复等业务扩展）

依赖：websockets（pip install websockets，引导页第一步会自动体检）
"""

import json
import os
import threading
import time
import traceback
from urllib.parse import urlsplit, parse_qs

import config

# ----------------------------------------------------------------------------
# 依赖检查（缺失时给出可读提示，而不是直接崩）
# ----------------------------------------------------------------------------
try:
    from websockets.sync.server import serve as _ws_serve
    from websockets.exceptions import ConnectionClosed
    from websockets.http11 import Response
    from websockets.datastructures import Headers
    HAS_WEBSOCKETS = True
    _WS_IMPORT_ERROR = ""
except Exception as _e:                                  # pragma: no cover
    HAS_WEBSOCKETS = False
    _WS_IMPORT_ERROR = str(_e)

# ----------------------------------------------------------------------------
# 配置持久化
# ----------------------------------------------------------------------------
# 全部默认值来自 .env（config.WS_*），代码里不再硬编码。
# WS_CONFIG_PRIORITY=file（默认）：面板保存的 ws_config.json 覆盖 .env 默认值；
# WS_CONFIG_PRIORITY=env        ：强制以 .env 为准，忽略 ws_config.json，面板禁止保存。
CONFIG_PATH = config.WS_CONFIG_PATH
EVENT_LIMIT = config.WS_EVENT_LIMIT      # 事件环形缓冲上限
RAW_LIMIT = config.WS_RAW_LIMIT          # 网页展示的原始 JSON 截断长度
MAX_FRAME = config.WS_MAX_FRAME_MB * 1024 * 1024   # 单条消息上限

DEFAULT_CONFIG = dict(config.WS_DEFAULT_CONFIG)
ENV_LOCKED = config.WS_ENV_LOCKED
ENV_LOCK_MSG = ("当前配置由 .env 接管（WS_CONFIG_PRIORITY=env），"
                "面板保存已禁用；如需修改请编辑项目根目录的 .env 后重启")

_config_lock = threading.RLock()


def _normalize_config(d):
    c = dict(DEFAULT_CONFIG)
    if isinstance(d, dict):
        c.update({k: v for k, v in d.items() if k in DEFAULT_CONFIG})
    _dp = int(DEFAULT_CONFIG["port"])
    try:
        c["port"] = int(c.get("port") or _dp)
    except (TypeError, ValueError):
        c["port"] = _dp
    if not (1 <= c["port"] <= 65535):
        c["port"] = _dp
    c["host"] = str(c.get("host") or DEFAULT_CONFIG["host"]).strip() or DEFAULT_CONFIG["host"]
    p = str(c.get("path") or "").strip()
    if p and not p.startswith("/"):
        p = "/" + p
    c["path"] = p or DEFAULT_CONFIG["path"]
    c["access_token"] = str(c.get("access_token") or "")
    c["auto_start"] = bool(c.get("auto_start"))
    return c


def get_config():
    """当前生效配置。

    WS_CONFIG_PRIORITY=env 时直接返回 .env 提供的默认值，不读 ws_config.json。
    """
    if ENV_LOCKED:
        return _normalize_config({})
    with _config_lock:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = {}
        return _normalize_config(raw)


def set_config(d):
    """保存配置。监听地址/端口/路径的改动需 restart() 才生效（app.py 会自动重启）。"""
    if ENV_LOCKED:
        return {"ok": False, "error": ENV_LOCK_MSG, "env_locked": True}
    with _config_lock:
        cur = get_config()
        if isinstance(d, dict):
            cur.update({k: v for k, v in d.items() if k in DEFAULT_CONFIG})
        cur = _normalize_config(cur)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cur, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"ok": False, "error": "配置写入失败: %s" % e}
        return {"ok": True, "config": cur}


# ----------------------------------------------------------------------------
# 终端彩色输出（Windows 下开启 VT 序列）
# ----------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"


_COLOR_OK = os.environ.get("NO_COLOR") is None


def _enable_vt():
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        handle = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(handle, ctypes.byref(mode)):
            k.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


_enable_vt()


def _c(txt, color):
    if not _COLOR_OK:
        return txt
    return color + txt + C.RESET


def _ts():
    return time.strftime("%H:%M:%S")


def _log(tag, msg, color=C.CYAN):
    """统一终端日志格式：[HH:MM:SS] 【标签】 内容"""
    try:
        print("%s %s %s" % (_c("[%s]" % _ts(), C.GREY), _c("【%s】" % tag, color), msg), flush=True)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 事件环形缓冲 + 全局计数
# ----------------------------------------------------------------------------
_ev_lock = threading.RLock()
_events = []
_ev_seq = [0]
_counters = {"recv": 0, "sent": 0, "bytes_in": 0, "bytes_out": 0,
             "conn": 0, "event": 0}

# 名称缓存：QQ 号 → 昵称、群号 → 群名。
# 事件里通常只带 QQ 号 / 群号，昵称与群名靠事件字段 + 接口回包逐步补全，
# 这样前端日志卡片才能显示「谁 · 在哪个群」，而不是一串数字。
_names_lock = threading.RLock()
_user_names = {}
_group_names = {}
_name_busy = {"group": False, "user": False}
_name_try_at = {"group": 0.0, "user": 0.0}

# 机器人最近发出的消息（接口调试发送 / message_sent 事件），供 message_id 参数下拉选择
RECENT_MSG_LIMIT = 60
_recent_msgs = []


def _as_int(v):
    """纯数字字符串转 int，否则原样返回（OneBot 参数常用）。"""
    s = str(v or "").strip()
    return int(s) if s.isdigit() else s


def _remember_user(uid, name):
    uid = str(uid or "").strip()
    name = str(name or "").strip()
    if uid and name:
        with _names_lock:
            _user_names[uid] = name


def _remember_group(gid, name):
    gid = str(gid or "").strip()
    name = str(name or "").strip()
    if gid and name:
        with _names_lock:
            _group_names[gid] = name


def _user_name(uid):
    with _names_lock:
        return _user_names.get(str(uid or ""), "")


def _group_name(gid):
    with _names_lock:
        return _group_names.get(str(gid or ""), "")


def _absorb_names(action, ret):
    """接口回包顺手补全昵称 / 群名缓存。"""
    data = (ret or {}).get("data") if isinstance(ret, dict) else None
    if isinstance(data, list):
        if action == "get_friend_list":
            for f in data:
                if isinstance(f, dict):
                    _remember_user(f.get("user_id"), f.get("remark") or f.get("nickname"))
        elif action == "get_group_list":
            for g in data:
                if isinstance(g, dict):
                    _remember_group(g.get("group_id"), g.get("group_name"))
        elif action == "get_group_member_list":
            for m in data:
                if isinstance(m, dict):
                    _remember_user(m.get("user_id"), m.get("card") or m.get("nickname"))
    elif isinstance(data, dict):
        if action == "get_stranger_info":
            _remember_user(data.get("user_id"), data.get("nickname"))
        elif action == "get_group_info":
            _remember_group(data.get("group_id"), data.get("group_name"))
        elif action == "get_group_member_info":
            _remember_user(data.get("user_id"), data.get("card") or data.get("nickname"))


def _remember_sent(message_id, target_type, target_id, target_name, content, source="事件"):
    """记录一条机器人发出的消息（供「接口调试」按下拉选择 message_id）。"""
    mid = str(message_id or "").strip()
    if not mid:
        return
    text = str(content or "").strip()
    if len(text) > 160:
        text = text[:160] + "…"
    with _names_lock:
        for m in _recent_msgs:
            if m["message_id"] == mid:
                return
        _recent_msgs.insert(0, {
            "message_id": mid,
            "target_type": target_type or "",
            "target_id": str(target_id or "").strip(),
            "target_name": str(target_name or "").strip(),
            "content": text,
            "source": source,
            "ts": time.time(),
            "time": _ts(),
        })
        del _recent_msgs[RECENT_MSG_LIMIT:]


def recent_messages(limit=RECENT_MSG_LIMIT):
    """机器人最近发出的消息（新的在前），供 /api/ws/messages 返回给前端下拉。"""
    try:
        n = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        n = RECENT_MSG_LIMIT
    with _names_lock:
        out = []
        for m in _recent_msgs[:n]:
            it = dict(m)
            if not it.get("target_name"):
                it["target_name"] = (_group_name(it.get("target_id"))
                                     if it.get("target_type") == "group"
                                     else _user_name(it.get("target_id")))
            out.append(it)
        return out


def self_account():
    """当前已连接客户端的登录账号 {self_id, nickname}（多个客户端时取第一个有值的）。"""
    sid, nick = "", ""
    with _state["lock"]:
        for b in _state["clients"].values():
            if not sid and b.self_id:
                sid = str(b.self_id)
            if not nick and b.nickname:
                nick = str(b.nickname)
    return {"self_id": sid, "nickname": nick}


def chat_messages(target_type="group", target_id="", limit=80):
    """按会话筛出最近的消息事件（时间正序），供 WebUI 渲染会话消息流。

    只取 kind == "message" 的事件；group 按群号过滤，private 取「对方发来的
    + 机器人自己发的」。self 标记用于前端区分左右气泡。
    """
    try:
        n = max(1, min(int(limit), 300))
    except (TypeError, ValueError):
        n = 80
    tt = "group" if str(target_type) == "group" else "private"
    tid = str(target_id or "").strip()
    me = self_account()
    self_ids = {me["self_id"]} if me["self_id"] else set()

    with _ev_lock:
        events = list(_events)

    out = []
    for e in events:
        if e.get("kind") != "message":
            continue
        ex = e.get("extra") or {}
        mtype = str(ex.get("mtype") or "")
        uid = str(ex.get("uid") or "")
        gid = str(ex.get("gid") or "")
        post = str(ex.get("post") or "")
        is_self = (post == "message_sent") or bool(uid and uid in self_ids)
        if tt == "group":
            if mtype != "group" or gid != tid:
                continue
        else:
            if mtype == "group":
                continue
            if not is_self and tid and uid != tid:
                continue
        mid = str(ex.get("message_id") or "")
        out.append({
            "key": "%s|%s" % (tt, mid or ("%s-%s" % (uid, e.get("id")))),
            "message_id": mid,
            "uid": uid,
            "uname": _user_name(uid) or str(ex.get("uname") or uid),
            "gid": gid,
            "gname": str(ex.get("gname") or (_group_name(gid) if gid else "")),
            "content": str(ex.get("content") or ""),
            "mtype": mtype,
            "post": post,
            "self": bool(is_self),
            "ts": float(e.get("ts") or 0),
            "time": str(e.get("t") or ""),
            "av": "group" if gid else "user",
        })
    if n:
        out = out[-n:]
    return out


def _ensure_names(uid="", gid=""):
    """事件里只带号码时，后台补拉一次昵称 / 群名（带节流，避免频繁请求）。

    必须在独立线程里调用 call_api：事件回调跑在收包线程上，
    若在收包线程内等待回包会死等直到超时。
    """
    now = time.time()
    jobs = []
    with _names_lock:
        if gid and not _group_name(gid) and not _name_busy["group"] and now - _name_try_at["group"] > 30:
            _name_busy["group"] = True
            _name_try_at["group"] = now
            jobs.append(("get_group_info", {"group_id": _as_int(gid)}))
        if uid and not _user_name(uid) and not _name_busy["user"] and now - _name_try_at["user"] > 30:
            _name_busy["user"] = True
            _name_try_at["user"] = now
            jobs.append(("get_stranger_info", {"user_id": _as_int(uid)}))
    if not jobs:
        return

    def _run():
        try:
            for act, p in jobs:
                call_api(act, p, timeout=8.0)
        except Exception:
            pass
        finally:
            with _names_lock:
                _name_busy["group"] = False
                _name_busy["user"] = False

    threading.Thread(target=_run, name="ws-names", daemon=True).start()


def _warm_names():
    """连接建立后一次性拉取群列表 / 好友列表，批量补齐群名与昵称。"""
    try:
        call_api("get_group_list", {}, timeout=12.0)
        call_api("get_friend_list", {}, timeout=12.0)
    except Exception:
        pass


def _push_event(kind, tag, text, raw="", extra=None):
    with _ev_lock:
        _ev_seq[0] += 1
        _events.append({
            "id": _ev_seq[0],
            "t": _ts(),
            "ts": time.time(),
            "kind": kind,
            "tag": tag,
            "text": text,
            "raw": (raw or "")[:RAW_LIMIT],
            "extra": extra or {},
        })
        if len(_events) > EVENT_LIMIT:
            del _events[:len(_events) - EVENT_LIMIT]


def clear_events():
    with _ev_lock:
        del _events[:]


# ----------------------------------------------------------------------------
# OneBot V11 事件解析
# ----------------------------------------------------------------------------
def _render_segments(message):
    """把 OneBot 消息段数组渲染成可读文本"""
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if not isinstance(message, list):
        return str(message)
    out = []
    for seg in message:
        if not isinstance(seg, dict):
            out.append(str(seg))
            continue
        typ = seg.get("type")
        data = seg.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if typ == "text":
            out.append(str(data.get("text", "")))
        elif typ == "at":
            qq = str(data.get("qq", ""))
            out.append("[全体]" if qq == "all" else "@" + qq)
        elif typ == "image":
            out.append("[图片]")
        elif typ == "face":
            out.append("[表情 %s]" % data.get("id", ""))
        elif typ == "mface":
            out.append("[商城表情]")
        elif typ == "reply":
            out.append("[回复 #%s]" % data.get("id", ""))
        elif typ == "record":
            out.append("[语音]")
        elif typ == "video":
            out.append("[视频]")
        elif typ == "file":
            out.append("[文件 %s]" % (data.get("name") or data.get("file") or ""))
        elif typ == "json":
            out.append("[卡片消息]")
        elif typ == "xml":
            out.append("[XML 消息]")
        elif typ == "forward":
            out.append("[合并转发]")
        elif typ == "node":
            out.append("[转发节点]")
        elif typ == "poke":
            out.append("[戳一戳]")
        elif typ == "dice":
            out.append("[骰子]")
        elif typ == "rps":
            out.append("[猜拳]")
        elif typ == "music":
            out.append("[音乐]")
        elif typ:
            out.append("[%s]" % typ)
    return "".join(out)


def _sender_name(sender):
    sender = sender or {}
    return sender.get("card") or sender.get("nickname") or str(sender.get("user_id", "?"))


# ----------------------------------------------------------------------------
# 日志文字化工具：把 JSON 结构转成用户能看懂的中文短语（终端不再打印原始 JSON）
# ----------------------------------------------------------------------------
def _bool_text(v, yes, no, unknown="未知"):
    if v is True:
        return yes
    if v is False:
        return no
    return unknown


def _brief_value(v, depth=0):
    """把任意值压成一行短文本"""
    try:
        if isinstance(v, dict):
            if not v:
                return "空"
            if depth >= 1:
                return "共 %d 项" % len(v)
            items = []
            for k, val in list(v.items())[:6]:
                items.append("%s=%s" % (k, _brief_value(val, depth + 1)))
            if len(v) > 6:
                items.append("…另有 %d 项" % (len(v) - 6))
            return " ".join(items)
        if isinstance(v, (list, tuple)):
            if not v:
                return "空"
            if depth >= 1:
                return "共 %d 项" % len(v)
            items = [_brief_value(x, depth + 1) for x in list(v)[:4]]
            if len(v) > 4:
                items.append("…另有 %d 项" % (len(v) - 4))
            return " ".join(items)
        if v is None:
            return "-"
        if isinstance(v, bool):
            return "是" if v else "否"
        s = str(v)
    except Exception:
        return "?"
    if len(s) > 80:
        s = s[:80] + "…"
    return s


def _status_text(st):
    """心跳 status 字典 → 中文短语，例如「在线 · 收发正常」"""
    if not isinstance(st, dict) or not st:
        return "状态未知"
    parts = []
    if "online" in st:
        parts.append(_bool_text(st.get("online"), "在线", "离线"))
    if "good" in st:
        parts.append(_bool_text(st.get("good"), "收发正常", "收发异常"))
    rest = []
    for k in sorted(st.keys()):
        if k in ("online", "good"):
            continue
        rest.append("%s=%s" % (k, _brief_value(st[k])))
    if not parts and rest:
        parts, rest = rest, []
    text = " · ".join(parts) if parts else "状态未知"
    if rest:
        text += "（%s）" % " ".join(rest)
    return text


def _action_label(action):
    """接口名 → 中文名称，例如 get_login_info → 获取登录号信息(get_login_info)"""
    act = str(action)
    try:
        for spec in ACTION_SPEC:
            if spec.get("action") == act:
                return "%s(%s)" % (spec.get("label") or act, act)
    except Exception:
        pass
    return act


def _params_text(params):
    """接口参数 → 一行可读文本"""
    if params is None or params == {} or params == []:
        return "无参数"
    try:
        return _brief_value(params)
    except Exception:
        return "参数无法解析"


def _resp_text(ret):
    """OneBot 回包 → 一行中文摘要：成功/失败 + 返回码 + 关键数据"""
    if not isinstance(ret, dict):
        return "回包格式异常"
    status = ret.get("status")
    status_text = {"ok": "成功", "failed": "失败", "async": "已受理（异步）"}.get(
        str(status), str(status) if status else "未知状态")
    parts = [status_text]
    rc = ret.get("retcode")
    if rc is not None:
        parts.append("返回码 %s" % rc)
    bad = str(status) == "failed"
    try:
        bad = bad or int(rc) < 0
    except Exception:
        pass
    if bad:
        why = ret.get("message") or ret.get("wording") or ret.get("msg")
        if why:
            parts.append("原因: %s" % _brief_value(why))
    data = ret.get("data")
    if isinstance(data, dict) and data:
        parts.append("数据: %s" % " ".join(
            "%s=%s" % (k, _brief_value(data[k])) for k in list(data.keys())[:6]))
    elif isinstance(data, (list, tuple)):
        parts.append("数据: %d 项" % len(data))
    elif data not in (None, ""):
        parts.append("数据: %s" % _brief_value(data))
    text = "，".join(parts)
    if len(text) > 220:
        text = text[:220] + "…"
    return text


def _parse_event(ev):
    """把 OneBot V11 事件解析为 (kind, tag, 单行摘要, 详情行列表, 结构化信息)

    extra 是给前端日志卡片用的结构化字段（谁 · 在哪个群 · 做了什么 · 说了什么），
    前端据此渲染头像 + 昵称 + 群名 + 内容，从而完全不需要展示原始 JSON。
    """
    if not isinstance(ev, dict):
        return "unknown", "未知", str(ev)[:200], [], {}

    post = ev.get("post_type")
    self_id = ev.get("self_id", "")

    if post in ("message", "message_sent"):
        mtype = ev.get("message_type")
        # 优先渲染消息段；缺失时回退到 raw_message（部分实现只带 raw_message）
        text = _render_segments(ev.get("message")) or str(ev.get("raw_message") or "")
        uid = str(ev.get("user_id", "") or "")
        gid = str(ev.get("group_id", "") or "")
        nick = _sender_name(ev.get("sender"))
        who = nick or _user_name(uid) or uid
        gname = str(ev.get("group_name") or "") or (_group_name(gid) if gid else "")
        if nick:
            _remember_user(uid, nick)
        if gid and gname:
            _remember_group(gid, gname)
        if mtype == "group":
            label = "%s(%s)" % (gname, gid) if gname else gid
            tag = "群消息" if post == "message" else "群消息(自身)"
            head = "%s(%s) @ %s" % (who, uid, label)
        elif mtype == "private":
            tag = "私聊消息" if post == "message" else "私聊消息(自身)"
            head = "%s(%s)" % (who, uid)
        else:
            tag = "消息"
            head = "%s(%s)" % (who, uid)
        detail = [
            "内容: %s" % text,
            "消息ID: %s   子类型: %s   字体: %s" % (ev.get("message_id", "-"),
                                                ev.get("sub_type", "-"),
                                                ev.get("font", "-")),
            "self_id: %s" % self_id,
        ]
        if mtype == "group":
            detail.append("群号: %s   身份: %s" % (gid or "-",
                                               (ev.get("sender") or {}).get("role", "-")))
        extra = {
            "uid": uid,
            "uname": who,
            "gid": gid,
            "gname": gname,
            "content": text,
            "message_id": str(ev.get("message_id", "") or ""),
            "post": str(post or ""),
            "mtype": str(mtype or ""),
            "av": "group" if mtype == "group" else "user",
        }
        return "message", tag, head, detail, extra

    if post == "notice":
        ntype = ev.get("notice_type")
        uid = str(ev.get("user_id", "") or "")
        gid = str(ev.get("group_id", "") or "")
        sub = ev.get("sub_type", "")
        sender = ev.get("sender") if isinstance(ev.get("sender"), dict) else {}
        if sender and str(sender.get("user_id") or "") == uid:
            _remember_user(uid, _sender_name(sender))
        uname = _user_name(uid) or uid
        gname = _group_name(gid) if gid else ""
        where = ("%s(%s)" % (gname, gid) if gname else gid) if gid else "私聊"
        if ntype == "group_upload":
            tag, head = "群文件", "%s 在 %s 上传了文件" % (uname, where)
        elif ntype == "group_admin":
            tag, head = "群管理", "%s 在 %s %s" % (
                uname, where, "成为管理员" if sub == "set" else "被取消管理员")
        elif ntype == "group_decrease":
            why = {"kick": "被踢出", "kick_me": "机器人被踢出", "leave": "主动退群"}.get(sub, sub or "离开")
            tag, head = "群成员减少", "%s %s了 %s" % (uname, why, where)
        elif ntype == "group_increase":
            why = {"approve": "管理员通过入群", "invite": "被邀请入群"}.get(sub, sub or "入群")
            tag, head = "群成员增加", "%s %s：%s" % (uname, why, where)
        elif ntype == "friend_add":
            tag, head = "好友增加", "%s 添加机器人为好友" % uname
        elif ntype == "group_recall":
            tag, head = "撤回消息", "%s 在 %s 撤回了一条消息" % (uname, where)
        elif ntype == "friend_recall":
            tag, head = "撤回消息", "%s 撤回了一条私聊消息" % uname
        elif ntype == "notify":
            tag = "提醒"
            if sub == "poke":
                tid = str(ev.get("target_id", "") or "")
                head = "%s 在 %s 戳了 %s" % (uname, where, _user_name(tid) or tid)
            elif sub == "lucky_king":
                head = "%s 在 %s 成为运气王" % (uname, where)
            elif sub == "honor":
                head = "%s 在 %s 获得荣誉 %s" % (uname, where, ev.get("honor_type", ""))
            else:
                head = "%s 在 %s 触发提醒 %s" % (uname, where, sub or "-")
        else:
            tag, head = "通知", "%s 触发了 %s 通知" % (uname, ntype or "未知")
        extra = {
            "uid": uid,
            "uname": uname,
            "gid": gid,
            "gname": gname,
            "content": "",
            "message_id": str(ev.get("message_id", "") or ""),
            "post": "notice",
            "mtype": str(ntype or ""),
            "av": "group" if gid else "user",
        }
        return "notice", tag, head, ["群号: %s   用户: %s   消息ID: %s" % (
            gid or "-", uid or "-", ev.get("message_id", "-"))], extra

    if post == "request":
        rtype = ev.get("request_type")
        uid = str(ev.get("user_id", "") or "")
        gid = str(ev.get("group_id", "") or "")
        uname = _user_name(uid) or uid
        gname = _group_name(gid) if gid else ""
        where = ("%s(%s)" % (gname, gid) if gname else gid) if gid else "私聊"
        if rtype == "friend":
            tag, head = "加好友请求", "%s 请求加机器人为好友（%s）" % (
                uname, ev.get("comment", "") or "无验证信息")
        elif rtype == "group":
            sub = ev.get("sub_type")
            tag = "加群请求" if sub == "add" else "邀请入群"
            head = "%s 请求%s（%s）" % (
                uname, "加入 " + where if sub == "add" else "把机器人拉进 " + where,
                ev.get("comment", "") or "无验证信息")
        else:
            tag, head = "请求", "%s 发起了 %s 请求" % (uname, rtype or "未知")
        extra = {
            "uid": uid, "uname": uname, "gid": gid, "gname": gname,
            "content": str(ev.get("comment", "") or ""),
            "message_id": "", "post": "request", "mtype": str(rtype or ""),
            "av": "group" if gid else "user", "flag": str(ev.get("flag", "") or ""),
        }
        return "request", tag, head, ["请求标识 flag: %s" % ev.get("flag", "-")], extra

    if post == "meta_event":
        mtype = ev.get("meta_event_type")
        if mtype == "lifecycle":
            sub = str(ev.get("sub_type") or "-")
            sub_text = {"connect": "已上线", "enable": "已启用", "disable": "已停用"}.get(sub, sub)
            detail = []
            if self_id:
                detail.append("机器人 QQ 号: %s" % self_id)
            return "meta", "生命周期", "机器人%s" % sub_text, detail, {}
        if mtype == "heartbeat":
            st = ev.get("status") or {}
            detail = ["心跳间隔: %s 毫秒" % ev.get("interval", "-")]
            if self_id:
                detail.append("机器人 QQ 号: %s" % self_id)
            return "heartbeat", "心跳", _status_text(st), detail, {}
        return "meta", "元事件", "收到一个 %s 元事件" % (mtype or "未知"), [], {}

    return "unknown", "未知事件", "收到一个无法识别的 %s 事件" % (post or "未知"), [], {}


# ----------------------------------------------------------------------------
# 客户端封装
# ----------------------------------------------------------------------------
class ClientBox(object):
    """包装一个 websockets 连接，附统计 / 待回包槽位 / 元信息"""

    def __init__(self, conn, path=""):
        self.conn = conn
        self.path = path or ""
        addr = getattr(conn, "remote_address", None)
        try:
            host, port = str(addr[0]), str(addr[1])
        except Exception:
            host, port = "?", "0"
        self.addr_text = "%s:%s" % (host, port)
        self.id = self.addr_text
        self.send_lock = threading.Lock()
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.connected_at = time.time()
        self.last_at = time.time()
        self.recv_count = 0
        self.sent_count = 0
        self.bytes_in = 0
        self.bytes_out = 0
        self.self_id = ""
        self.nickname = ""
        self.heartbeat_count = 0

    # ---------- 发送 ----------
    def send_text(self, text):
        try:
            with self.send_lock:
                self.conn.send(text)
        except Exception:
            return False
        n = len(text.encode("utf-8"))
        self.sent_count += 1
        self.bytes_out += n
        with _ev_lock:
            _counters["sent"] += 1
            _counters["bytes_out"] += n
        return True

    def close(self, code=1000, reason=""):
        try:
            self.conn.close(code, reason)
        except Exception:
            pass

    def fail_pending(self):
        with self.pending_lock:
            items = list(self.pending.values())
            self.pending.clear()
        for it in items:
            it["ret"] = {"status": "failed", "retcode": -1, "message": "连接已断开"}
            it["ev"].set()

    # ---------- 收包处理 ----------
    def on_text(self, text):
        try:
            ev = json.loads(text)
        except Exception:
            _log("WS", "%s 收到非 JSON 文本: %s" % (self.id, text[:300]), C.YELLOW)
            _push_event("raw", "原始文本", text[:300], text)
            return

        # 1) API 调用回包（带 echo）
        if isinstance(ev, dict) and "echo" in ev and ("status" in ev or "retcode" in ev):
            echo = ev.get("echo")
            with self.pending_lock:
                slot = self.pending.pop(echo, None)
            if slot:
                slot["ret"] = ev
                slot["ev"].set()
            else:
                dumped = json.dumps(ev, ensure_ascii=False)
                text = "回包（echo=%s）：%s" % (echo, _resp_text(ev))
                _log("接口", "%s 收到一个未匹配的回包 · %s" % (self.id, text), C.GREY)
                _push_event("api", "API 回包", text, dumped)
            return

        # 2) 对方发来的 API 调用请求（OneBot 双向通道；本服务器只做事件接入，不代为调用）
        if isinstance(ev, dict) and ev.get("action") and not ev.get("post_type"):
            act = str(ev.get("action"))
            params = ev.get("params")
            text = "对方请求调用 %s · 参数 %s" % (_action_label(act), _params_text(params))
            _log("接口", "%s %s（本服务器仅接收事件，不代为调用）" % (self.id, text), C.GREY)
            _push_event("api", "API 请求", text, json.dumps(ev, ensure_ascii=False))
            return

        # 3) 事件上报
        kind, tag, head, detail, extra = _parse_event(ev)
        raw = json.dumps(ev, ensure_ascii=False)

        if isinstance(ev, dict):
            sid = ev.get("self_id")
            if sid:
                self.self_id = str(sid)
            sender = ev.get("sender")
            sender = sender if isinstance(sender, dict) else {}
            nick = sender.get("nickname") or sender.get("card")
            s_uid = str(sender.get("user_id") or ev.get("user_id") or "")
            if nick and s_uid:
                _remember_user(s_uid, nick)
            # message_sent 的 sender 即机器人自身；或 sender 与 self_id 一致
            if nick and not self.nickname and (
                    ev.get("post_type") == "message_sent"
                    or (self.self_id and s_uid == self.self_id)):
                self.nickname = str(nick)
                _log("账号", "%s 已识别登录账号: %s（QQ %s）" % (
                    self.id, self.nickname, self.self_id or "未知"), C.GREEN)
            # 机器人自己发出的消息：记下 message_id，供「接口调试」按下拉选择
            if ev.get("post_type") == "message_sent":
                ttype = "group" if ev.get("message_type") == "group" else "private"
                tid = str(ev.get("group_id") or ev.get("user_id") or "")
                _remember_sent(
                    ev.get("message_id"), ttype, tid,
                    _group_name(tid) if ttype == "group" else _user_name(tid),
                    _render_segments(ev.get("message")) or str(ev.get("raw_message") or ""),
                    source="事件")
        if kind == "meta" and isinstance(ev, dict) and ev.get("sub_type") == "connect":
            self.heartbeat_count = 0

        with _ev_lock:
            _counters["event"] += 1

        color = {
            "message": C.GREEN, "notice": C.MAGENTA, "request": C.CYAN,
            "meta": C.BLUE, "heartbeat": C.BLUE, "unknown": C.YELLOW,
        }.get(kind, C.CYAN)

        # ---- 打印到终端 ----
        if kind == "heartbeat":
            self.heartbeat_count += 1
            st = ev.get("status") or {}
            bad = (st.get("online") is False) or (st.get("good") is False)
            # 心跳密集，只在首包 / 每 12 次（约 1 分钟）/ 状态异常时打印，避免刷屏
            if self.heartbeat_count == 1 or self.heartbeat_count % 12 == 0 or bad:
                _log("心跳", "%s 第 %d 次 · %s" % (self.id, self.heartbeat_count, head), C.BLUE)
        else:
            _log(tag, head, color)
            for line in detail:
                try:
                    print("        " + _c(line, C.GREY), flush=True)
                except Exception:
                    pass

        _push_event(kind, tag, head, raw, extra)

        # 事件里只有号码时，后台补拉昵称 / 群名（异步，不阻塞收包）
        ex = extra or {}
        if ex.get("uid") or ex.get("gid"):
            _ensure_names(ex.get("uid") or "", ex.get("gid") or "")

        # 3) 业务扩展钩子（自动回复等）
        _dispatch_event(ev, self)


# ----------------------------------------------------------------------------
# 事件分发钩子（保留扩展位）
# ----------------------------------------------------------------------------
_event_handlers = []


def add_event_handler(fn):
    """注册事件处理函数 fn(event_dict, client)"""
    if callable(fn) and fn not in _event_handlers:
        _event_handlers.append(fn)


def _dispatch_event(ev, client):
    for fn in list(_event_handlers):
        try:
            fn(ev, client)
        except Exception:
            traceback.print_exc()


# ----------------------------------------------------------------------------
# 服务器状态
# ----------------------------------------------------------------------------
_state = {
    "lock": threading.RLock(),
    "server": None,
    "running": False,
    "started_at": None,
    "thread": None,
    "clients": {},          # id -> ClientBox
    "error": None,
}

_path_lock = threading.Lock()
_path_map = {}              # id(connection) -> 请求路径（握手时记录，handler 中取出）


def is_running():
    with _state["lock"]:
        return bool(_state["running"])


# ----------------------------------------------------------------------------
# HTTP 握手阶段：鉴权 + 路径记录
# ----------------------------------------------------------------------------
def _process_request(connection, request):
    target = getattr(request, "path", "") or "/"
    parsed = urlsplit(target)
    path = parsed.path or "/"
    query = parse_qs(parsed.query)
    with _path_lock:
        _path_map[id(connection)] = path

    cfg = get_config()
    token = cfg.get("access_token") or ""
    if token:
        headers = getattr(request, "headers", None)
        auth = ""
        try:
            auth = headers.get("Authorization") or ""
        except Exception:
            auth = ""
        got = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not got:
            got = (query.get("access_token") or [""])[0]
        if got != token:
            try:
                who = connection.remote_address[0]
            except Exception:
                who = "?"
            _log("WS", "%s 拒绝连接：access token 校验失败" % who, C.RED)
            _push_event("system", "拒绝连接", "%s access token 校验失败" % who)
            if HAS_WEBSOCKETS:
                return Response(401, "Unauthorized",
                                Headers([("Content-Type", "text/plain; charset=utf-8")]),
                                b"access token invalid")
            return None

    if cfg.get("path") and path != cfg["path"]:
        _log("WS", "客户端路径 %s 与配置 %s 不同（仍接受）" % (path, cfg["path"]), C.YELLOW)
    return None


# ----------------------------------------------------------------------------
# 连接处理器
# ----------------------------------------------------------------------------
def _handle(conn):
    with _path_lock:
        path = _path_map.pop(id(conn), "")
    box = ClientBox(conn, path)
    with _state["lock"]:
        _state["clients"][box.id] = box
        online = len(_state["clients"])
        with _ev_lock:
            _counters["conn"] += 1
    _log("WS", "%s 已连接（当前在线 %d）" % (box.id, online), C.GREEN)
    _push_event("system", "连接", "%s 已建立 WebSocket 连接" % box.id)

    # 连接后主动补拉一次登录信息，避免「只有 QQ 号、没有昵称」
    threading.Thread(target=_pull_login_info, args=(box,),
                     name="ws-login-info", daemon=True).start()

    # 再批量补拉群列表 / 好友列表，让实时日志能直接显示群名与昵称
    def _warm_later():
        time.sleep(3.0)
        try:
            if _box_online(box):
                _warm_names()
        except Exception:
            pass

    threading.Thread(target=_warm_later, name="ws-warm-names", daemon=True).start()

    try:
        while True:
            try:
                raw = conn.recv()
            except ConnectionClosed:
                break

            box.last_at = time.time()
            if isinstance(raw, bytes):
                n = len(raw)
                box.recv_count += 1
                box.bytes_in += n
                with _ev_lock:
                    _counters["recv"] += 1
                    _counters["bytes_in"] += n
                _push_event("binary", "二进制帧", "%d 字节（已忽略）" % n)
                _log("WS", "%s 收到二进制帧 %d 字节（已忽略）" % (box.id, n), C.YELLOW)
                continue

            n = len(raw.encode("utf-8"))
            box.recv_count += 1
            box.bytes_in += n
            with _ev_lock:
                _counters["recv"] += 1
                _counters["bytes_in"] += n
            box.on_text(raw)
    except Exception:
        traceback.print_exc()
    finally:
        box.fail_pending()
        with _state["lock"]:
            _state["clients"].pop(box.id, None)
        code = getattr(conn, "close_code", None)
        _log("WS", "%s 已断开（收 %d / 发 %d 包）%s" % (
            box.id, box.recv_count, box.sent_count,
            "" if code is None else " 关闭码 %s" % code), C.GREY)
        _push_event("system", "断开", "%s 已断开连接" % box.id)


def _serve_forever_safe(srv):
    try:
        srv.serve_forever()
    except Exception:
        traceback.print_exc()
    _log("WS", "监听循环已退出", C.GREY)


def _safe_shutdown(srv, timeout=5.0):
    """关停服务器：先礼貌关闭所有客户端，再停监听循环并释放端口（便于立刻重启）。"""
    with _state["lock"]:
        boxes = list(_state["clients"].values())
    for b in boxes:
        try:
            b.conn.close(1001, "server shutdown")
        except Exception:
            pass

    done = threading.Event()

    def _do():
        try:
            srv.shutdown()
        except TypeError:
            try:                       # 兼容不同版本的签名差异
                srv.shutdown(close_connections=True)
            except Exception:
                traceback.print_exc()
        except Exception:
            traceback.print_exc()
        finally:
            done.set()

    t = threading.Thread(target=_do, name="ws-shutdown", daemon=True)
    t.start()
    if not done.wait(timeout):
        _log("WS", "关闭等待超时（%.0fs），监听端口已释放" % timeout, C.YELLOW)

    # 兜底：确保监听 socket 已关闭，避免同端口立刻重启时报 10048
    sock = getattr(srv, "socket", None)
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# 启停控制
# ----------------------------------------------------------------------------
def start():
    if not HAS_WEBSOCKETS:
        return {"ok": False, "error": "未安装 websockets 库（%s），请执行：pip install websockets" % _WS_IMPORT_ERROR}
    with _state["lock"]:
        if _state["running"]:
            return {"ok": False, "error": "WebSocket 服务器已在运行"}
        cfg = get_config()
        try:
            srv = _ws_serve(
                _handle,
                cfg["host"],
                cfg["port"],
                process_request=_process_request,
                max_size=MAX_FRAME,
                ping_interval=30,
                ping_timeout=25,
                close_timeout=5,
                compression="deflate",
                logger=_make_logger(),
            )
        except OSError as e:
            _state["error"] = "启动失败：%s" % e
            _log("WS", "启动失败（%s:%s）：%s" % (cfg["host"], cfg["port"], e), C.RED)
            _push_event("system", "错误", "启动失败：%s" % e)
            return {"ok": False, "error": "端口 %s 无法监听（可能被占用）：%s" % (cfg["port"], e)}
        except Exception as e:
            _state["error"] = "启动失败：%s" % e
            _log("WS", "启动异常：%s" % e, C.RED)
            return {"ok": False, "error": "启动异常：%s" % e}

        _state["server"] = srv
        _state["running"] = True
        _state["started_at"] = time.time()
        _state["error"] = None
        t = threading.Thread(target=_serve_forever_safe, args=(srv,), name="ws-accept", daemon=True)
        _state["thread"] = t
        t.start()

    _log("WS", "OneBot V11 WebSocket 服务器已启动 → ws://%s:%s%s" % (
        cfg["host"], cfg["port"], cfg["path"]), C.GREEN)
    if cfg.get("access_token"):
        _log("WS", "已启用 access_token 校验", C.GREY)
    _push_event("system", "启动", "监听 ws://%s:%s%s" % (cfg["host"], cfg["port"], cfg["path"]))
    return {"ok": True}


def _make_logger():
    """websockets 内部日志（握手失败等）转成简洁中文输出，避免刷屏。"""
    import logging

    class _H(logging.Handler):
        def emit(self, record):
            try:
                msg = record.getMessage()
            except Exception:
                return
            low = msg.lower()
            if "opening handshake failed" in low or "connection rejected" in low:
                _log("WS", "握手失败：%s" % msg.split("\n")[0][:200], C.YELLOW)
            elif record.levelno >= logging.ERROR:
                _log("WS", "%s" % msg[:200], C.YELLOW)

    lg = logging.getLogger("ilbb.ws")
    lg.setLevel(logging.INFO)
    lg.handlers = [_H()]
    lg.propagate = False
    return lg


def stop():
    with _state["lock"]:
        if not _state["running"]:
            return {"ok": False, "error": "WebSocket 服务器未运行"}
        _state["running"] = False
        srv = _state["server"]
        _state["server"] = None
    if srv is not None:
        _safe_shutdown(srv)
    with _state["lock"]:
        _state["clients"].clear()
    with _path_lock:
        _path_map.clear()
    _log("WS", "WebSocket 服务器已停止", C.YELLOW)
    _push_event("system", "停止", "WebSocket 服务器已停止")
    return {"ok": True}


def restart():
    stop()
    time.sleep(0.3)
    return start()


def disconnect(client_id):
    with _state["lock"]:
        box = _state["clients"].get(client_id)
    if not box:
        return {"ok": False, "error": "客户端不存在"}
    box.close(1000, "kicked by admin")
    _push_event("system", "断开", "已主动断开 %s" % client_id)
    return {"ok": True}


# ----------------------------------------------------------------------------
# 主动调用 OneBot 接口
# ----------------------------------------------------------------------------
_echo_seq = [0]


def _absorb_login_info(box, action, ret):
    """从 get_login_info 回包中补齐客户端的 self_id / 昵称（账号级权威信息）"""
    if action != "get_login_info" or not isinstance(ret, dict):
        return
    data = ret.get("data")
    if not isinstance(data, dict):
        data = ret
    uid = data.get("user_id")
    nick = data.get("nickname")
    if uid:
        box.self_id = str(uid)
    if nick:
        box.nickname = str(nick)


def _box_online(box):
    with _state["lock"]:
        return box.id in _state["clients"]


def _pull_login_info(box, delay=0.8, tries=3):
    """连接建立后主动补拉 get_login_info，补齐本机 QQ 号与昵称。

    事件流本身只有在 message_sent（自己发的消息）里才带机器人昵称，
    单纯连接 + 心跳时昵称会一直为空，因此在后台线程里主动问一次。
    """
    for i in range(tries):
        time.sleep(delay if i == 0 else 1.5)
        if not _box_online(box):
            return
        _echo_seq[0] += 1
        echo = "ilbb-login-%d-%d" % (int(time.time()), _echo_seq[0])
        slot = {"ev": threading.Event(), "ret": None}
        with box.pending_lock:
            box.pending[echo] = slot
        payload = json.dumps({"action": "get_login_info", "params": {}, "echo": echo},
                             ensure_ascii=False)
        if not box.send_text(payload):
            with box.pending_lock:
                box.pending.pop(echo, None)
            return
        if not slot["ev"].wait(5.0):
            with box.pending_lock:
                box.pending.pop(echo, None)
            continue
        ret = slot["ret"] or {}
        if isinstance(ret, dict) and ret:
            _absorb_login_info(box, "get_login_info", ret)
            if not (box.nickname or box.self_id):
                _log("账号", "%s 读取登录账号信息失败 · %s" % (box.id, _resp_text(ret)), C.YELLOW)
                return
        if box.nickname or box.self_id:
            who = "%s（QQ %s）" % (box.nickname or "未知昵称", box.self_id or "未知")
            _log("账号", "%s 已识别登录账号: %s" % (box.id, who), C.GREEN)
            _push_event("system", "账号", "已识别登录账号: %s" % who)
            return
    _log("账号", "%s 未能读取登录账号信息（对方可能不支持 get_login_info）" % box.id, C.YELLOW)


def call_api(action, params=None, timeout=6.0):
    with _state["lock"]:
        clients = list(_state["clients"].values())
    if not clients:
        return {"ok": False, "error": "当前没有已连接的客户端，请先在 NapCat 中完成反向 WS 配置"}
    box = clients[0]
    _echo_seq[0] += 1
    echo = "ilbb-%d-%d" % (int(time.time()), _echo_seq[0])
    slot = {"ev": threading.Event(), "ret": None}
    with box.pending_lock:
        box.pending[echo] = slot
    payload = json.dumps({"action": action, "params": params or {}, "echo": echo}, ensure_ascii=False)
    _log("接口", "→ 调用 %s · 参数 %s" % (_action_label(action), _params_text(params)), C.CYAN)
    if not box.send_text(payload):
        with box.pending_lock:
            box.pending.pop(echo, None)
        return {"ok": False, "error": "发送失败，连接可能已断开"}
    if slot["ev"].wait(timeout):
        ret = slot["ret"] or {}
        _absorb_login_info(box, action, ret)
        _absorb_names(action, ret)
        ok = isinstance(ret, dict) and ret.get("status") == "ok"
        _log("接口", "← %s 返回：%s" % (_action_label(action), _resp_text(ret)),
             C.GREEN if ok else C.YELLOW)
        # 机器人发出的消息 → 记入「最近发出的消息」，供 message_id 参数下拉选择
        if ok and action in ("send_private_msg", "send_group_msg", "send_msg"):
            data = ret.get("data")
            data = data if isinstance(data, dict) else {}
            p = params if isinstance(params, dict) else {}
            ttype = str(p.get("message_type") or "").strip()
            if not ttype:
                ttype = "group" if action == "send_group_msg" else (
                    "private" if action == "send_private_msg" else "")
            tid = str(p.get("group_id") or p.get("user_id") or "")
            content = p.get("message")
            if not isinstance(content, str):
                content = _render_segments(content)
            _remember_sent(data.get("message_id"), ttype, tid,
                           _group_name(tid) if ttype == "group" else _user_name(tid),
                           content, source="接口调试")
        _push_event("api", "API 调用", "%s · %s" % (_action_label(action), _resp_text(ret)),
                    json.dumps(ret, ensure_ascii=False),
                    {"api": str(action), "ok": bool(ok),
                     "av": "bot", "uname": box.nickname or ""})
        return {"ok": True, "response": ret}
    with box.pending_lock:
        box.pending.pop(echo, None)
    _log("接口", "← %s 等待回包超时（%.1f 秒）" % (_action_label(action), timeout), C.YELLOW)
    return {"ok": False, "error": "等待回包超时（%.1fs）" % timeout}


# ----------------------------------------------------------------------------
# OneBot V11 接口参数说明表（供 WebUI「接口调试」面板动态生成输入框）
# ----------------------------------------------------------------------------
# type: int / text / bool / enum / json
# widget: input（默认）/ textarea / select（enum 自动用）/ switch（bool 自动用）
ACTION_SPEC = [
    # ---------------- 账号信息 ----------------
    {
        "action": "get_login_info", "label": "获取登录号信息", "group": "账号信息",
        "desc": "获取当前 NapCat 登录的 QQ 号与昵称，无参数。",
        "params": [],
    },
    {
        "action": "get_status", "label": "获取运行状态", "group": "账号信息",
        "desc": "获取 NapCat 在线状态、是否可收发消息，无参数。",
        "params": [],
    },
    {
        "action": "get_version_info", "label": "获取版本信息", "group": "账号信息",
        "desc": "获取 NapCat / OneBot 实现版本号，无参数。",
        "params": [],
    },
    {
        "action": "can_send_image", "label": "检查能否发图", "group": "账号信息",
        "desc": "检查当前账号是否可发送图片，无参数。",
        "params": [],
    },
    {
        "action": "can_send_record", "label": "检查能否发语音", "group": "账号信息",
        "desc": "检查当前账号是否可发送语音，无参数。",
        "params": [],
    },
    # ---------------- 好友 / 群信息 ----------------
    {
        "action": "get_friend_list", "label": "获取好友列表", "group": "好友与群",
        "desc": "获取当前账号的好友列表，无参数。",
        "params": [],
    },
    {
        "action": "get_stranger_info", "label": "获取陌生人信息", "group": "好友与群",
        "desc": "查询任意 QQ 号的基础资料。",
        "params": [
            {"name": "user_id", "label": "目标 QQ 号", "type": "int", "required": True,
             "source": "friend", "placeholder": "", "hint": "从好友列表选择，也可直接输入 QQ 号"},
            {"name": "no_cache", "label": "跳过缓存", "type": "bool", "required": False,
             "placeholder": "", "hint": "勾选后强制向服务器实时拉取，不读本地缓存"},
        ],
    },
    {
        "action": "get_group_list", "label": "获取群列表", "group": "好友与群",
        "desc": "获取当前账号已加入的群列表，无参数。",
        "params": [],
    },
    {
        "action": "get_group_info", "label": "获取群信息", "group": "好友与群",
        "desc": "查询指定群的名称、人数、群主等信息。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择，也可直接输入群号"},
            {"name": "no_cache", "label": "跳过缓存", "type": "bool", "required": False,
             "placeholder": "", "hint": "勾选后强制实时拉取"},
        ],
    },
    {
        "action": "get_group_member_list", "label": "获取群成员列表", "group": "好友与群",
        "desc": "获取指定群的全部成员（大群返回较慢）。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "先选群聊，再拉取该群成员"},
        ],
    },
    {
        "action": "get_group_member_info", "label": "获取群成员信息", "group": "好友与群",
        "desc": "查询某群内单个成员的名片、头衔、等级等。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "user_id", "label": "成员 QQ 号", "type": "int", "required": True,
             "source": "group_member", "placeholder": "", "hint": "选择群号后自动加载该群成员"},
            {"name": "no_cache", "label": "跳过缓存", "type": "bool", "required": False,
             "placeholder": "", "hint": "勾选后强制实时拉取"},
        ],
    },
    {
        "action": "get_group_honor_info", "label": "获取群荣誉信息", "group": "好友与群",
        "desc": "获取群内的群主、活跃榜、龙王、群聊之火等荣誉信息。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "type", "label": "荣誉类型", "type": "enum", "required": True,
             "values": [{"value": "all", "label": "全部 all"},
                        {"value": "talkative", "label": "活跃榜 talkative"},
                        {"value": "performer", "label": "群聊之火 performer"},
                        {"value": "legend", "label": "群聊炽焰 legend"},
                        {"value": "strong_newbie", "label": "冒尖小春笋 strong_newbie"},
                        {"value": "emotion", "label": "快乐源泉 emotion"}],
             "placeholder": "all", "hint": "一般选 all 返回全部"},
        ],
    },
    {
        "action": "get_group_msg_history", "label": "获取群聊天记录", "group": "好友与群",
        "desc": "拉取指定群的历史消息（部分实现不支持）。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "message_seq", "label": "起始消息序号", "type": "int", "required": False,
             "placeholder": "留空则从最新开始", "hint": "从某条消息往前拉取，可留空"},
            {"name": "count", "label": "拉取条数", "type": "int", "required": False,
             "placeholder": "默认 20", "hint": "建议不超过 100"},
        ],
    },
    {
        "action": "get_friend_msg_history", "label": "获取好友聊天记录", "group": "好友与群",
        "desc": "拉取与指定好友的历史消息（部分实现不支持）。",
        "params": [
            {"name": "user_id", "label": "好友 QQ 号", "type": "int", "required": True,
             "source": "friend", "placeholder": "", "hint": "从好友列表选择"},
            {"name": "message_seq", "label": "起始消息序号", "type": "int", "required": False,
             "placeholder": "留空则从最新开始", "hint": "从某条消息往前拉取，可留空"},
            {"name": "count", "label": "拉取条数", "type": "int", "required": False,
             "placeholder": "默认 20", "hint": "建议不超过 100"},
        ],
    },
    {
        "action": "get_group_at_all_remain", "label": "查询剩余 @全体次数", "group": "好友与群",
        "desc": "查询当前账号在该群还能使用几次 @全体成员。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
        ],
    },
    # ---------------- 消息发送 ----------------
    {
        "action": "send_private_msg", "label": "发送私聊消息", "group": "消息发送",
        "desc": "向指定好友发送一条消息。",
        "params": [
            {"name": "user_id", "label": "目标 QQ 号", "type": "int", "required": True,
             "source": "friend", "placeholder": "", "hint": "从好友列表选择，也可直接输入 QQ 号"},
            {"name": "message", "label": "消息内容", "type": "text", "required": True,
             "widget": "textarea", "placeholder": "例如 你好，这是一条测试消息",
             "hint": "支持 CQ 码，如 [CQ:image,file=xxx]；纯文本直接填写"},
            {"name": "auto_escape", "label": "不解析 CQ 码", "type": "bool", "required": False,
             "placeholder": "", "hint": "勾选后消息按纯文本发送，CQ 码不会被解析"},
        ],
    },
    {
        "action": "send_group_msg", "label": "发送群聊消息", "group": "消息发送",
        "desc": "向指定群发送一条消息。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择，也可直接输入群号"},
            {"name": "message", "label": "消息内容", "type": "text", "required": True,
             "widget": "textarea", "placeholder": "例如 大家好，这是一条测试消息",
             "hint": "支持 CQ 码，如 [CQ:at,qq=10001]；纯文本直接填写"},
            {"name": "auto_escape", "label": "不解析 CQ 码", "type": "bool", "required": False,
             "placeholder": "", "hint": "勾选后消息按纯文本发送，CQ 码不会被解析"},
        ],
    },
    {
        "action": "send_msg", "label": "通用发送消息", "group": "消息发送",
        "desc": "按 message_type 自动区分私聊 / 群聊。",
        "params": [
            {"name": "message_type", "label": "消息类型", "type": "enum", "required": True,
             "values": [{"value": "private", "label": "私聊 private"},
                        {"value": "group", "label": "群聊 group"}],
             "placeholder": "private", "hint": "选择 private 则填 user_id，选择 group 则填 group_id"},
            {"name": "user_id", "label": "目标 QQ 号", "type": "int", "required": False,
             "source": "friend", "placeholder": "", "hint": "选择私聊时必填，从好友列表选择"},
            {"name": "group_id", "label": "群号", "type": "int", "required": False,
             "source": "group", "placeholder": "", "hint": "选择群聊时必填，从群聊列表选择"},
            {"name": "message", "label": "消息内容", "type": "text", "required": True,
             "widget": "textarea", "placeholder": "例如 测试消息", "hint": "支持 CQ 码"},
        ],
    },
    {
        "action": "delete_msg", "label": "撤回消息", "group": "消息发送",
        "desc": "撤回一条已发送的消息，直接从下拉里选机器人发过的消息即可。",
        "params": [
            {"name": "message_id", "label": "选择要撤回的消息", "type": "int", "required": True,
             "source": "message", "placeholder": "", "hint": "下拉里是机器人最近发出的消息，选择后自动填入消息 ID"},
        ],
    },
    {
        "action": "get_msg", "label": "获取消息详情", "group": "消息发送",
        "desc": "按 message_id 查询一条消息的完整内容，从下拉里选机器人发过的消息即可。",
        "params": [
            {"name": "message_id", "label": "选择要查询的消息", "type": "int", "required": True,
             "source": "message", "placeholder": "", "hint": "下拉里是机器人最近发出的消息，选择后自动填入消息 ID"},
        ],
    },
    {
        "action": "get_forward_msg", "label": "获取合并转发内容", "group": "消息发送",
        "desc": "解析一条合并转发消息的各个节点内容。",
        "params": [
            {"name": "message_id", "label": "选择合并转发消息", "type": "int", "required": True,
             "source": "message", "placeholder": "", "hint": "从机器人发出的消息中选择含合并转发的条目"},
        ],
    },
    {
        "action": "mark_msg_as_read", "label": "标记消息已读", "group": "消息发送",
        "desc": "把一条消息标记为已读（部分实现支持）。",
        "params": [
            {"name": "message_id", "label": "选择消息", "type": "int", "required": True,
             "source": "message", "placeholder": "", "hint": "从机器人发出的消息中选择"},
        ],
    },
    {
        "action": "send_like", "label": "给好友点赞", "group": "消息发送",
        "desc": "给指定好友的名片点赞。",
        "params": [
            {"name": "user_id", "label": "目标 QQ 号", "type": "int", "required": True,
             "source": "friend", "placeholder": "", "hint": "要点赞的好友，从好友列表选择"},
            {"name": "times", "label": "点赞次数", "type": "int", "required": False,
             "placeholder": "默认 1（上限 10）", "hint": "一次最多 10 次"},
        ],
    },
    # ---------------- 群管理 ----------------
    {
        "action": "set_group_kick", "label": "群踢人", "group": "群管理",
        "desc": "把指定成员移出群聊（需管理员权限）。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "user_id", "label": "成员 QQ 号", "type": "int", "required": True,
             "source": "group_member", "placeholder": "", "hint": "选择群号后自动加载该群成员"},
            {"name": "reject_add_request", "label": "拒绝再加群", "type": "bool", "required": False,
             "placeholder": "", "hint": "勾选后该成员被拒绝再次申请入群"},
        ],
    },
    {
        "action": "set_group_ban", "label": "群禁言", "group": "群管理",
        "desc": "禁言指定成员，或将 duration 设为 0 解除禁言。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "user_id", "label": "成员 QQ 号", "type": "int", "required": True,
             "source": "group_member", "placeholder": "", "hint": "选群后自动加载成员；禁言全群请选「全员」"},
            {"name": "duration", "label": "禁言时长（秒）", "type": "int", "required": True,
             "placeholder": "例如 600", "hint": "0 表示解除禁言，最大 2592000（30 天）"},
        ],
    },
    {
        "action": "set_group_whole_ban", "label": "全员禁言开关", "group": "群管理",
        "desc": "开启或关闭群全员禁言。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "enable", "label": "开启全员禁言", "type": "bool", "required": True,
             "placeholder": "", "hint": "勾选为开启，取消勾选为关闭"},
        ],
    },
    {
        "action": "set_group_card", "label": "设置群名片", "group": "群管理",
        "desc": "修改某成员在当前群的群名片。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "user_id", "label": "成员 QQ 号", "type": "int", "required": True,
             "source": "group_member", "placeholder": "", "hint": "选择群号后自动加载该群成员"},
            {"name": "card", "label": "新群名片", "type": "text", "required": True,
             "placeholder": "例如 ILBB 小助手", "hint": "留空则清空群名片"},
        ],
    },
    {
        "action": "set_group_name", "label": "修改群名称", "group": "群管理",
        "desc": "修改群聊名称。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "group_name", "label": "新群名称", "type": "text", "required": True,
             "placeholder": "例如 ILBB 交流群", "hint": "新的群名称"},
        ],
    },
    {
        "action": "set_group_leave", "label": "退出群聊", "group": "群管理",
        "desc": "机器人主动退出指定群。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择要退出的群"},
            {"name": "is_dismiss", "label": "解散该群", "type": "bool", "required": False,
             "placeholder": "", "hint": "仅群主可用，勾选表示解散群聊"},
        ],
    },
    {
        "action": "get_essence_msg_list", "label": "获取群精华消息", "group": "群管理",
        "desc": "列出该群已设为精华的消息。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
        ],
    },
    {
        "action": "set_essence_msg", "label": "设为精华消息", "group": "群管理",
        "desc": "把一条消息设为群精华（需管理员权限）。",
        "params": [
            {"name": "message_id", "label": "选择消息", "type": "int", "required": True,
             "source": "message", "placeholder": "", "hint": "从机器人发出的消息里选择要加精的那条"},
        ],
    },
    {
        "action": "delete_essence_msg", "label": "移除精华消息", "group": "群管理",
        "desc": "把一条消息从群精华中移除（需管理员权限）。",
        "params": [
            {"name": "message_id", "label": "选择消息", "type": "int", "required": True,
             "source": "message", "placeholder": "", "hint": "从机器人发出的消息里选择要取消加精的那条"},
        ],
    },
    {
        "action": "set_group_special_title", "label": "设置专属头衔", "group": "群管理",
        "desc": "给群成员设置专属头衔（需群主权限）。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
            {"name": "user_id", "label": "成员 QQ 号", "type": "int", "required": True,
             "source": "group_member", "placeholder": "", "hint": "选择群号后自动加载该群成员"},
            {"name": "special_title", "label": "头衔内容", "type": "text", "required": True,
             "placeholder": "例如 ILBB 铁粉", "hint": "留空则清除头衔"},
            {"name": "duration", "label": "有效期（秒）", "type": "int", "required": False,
             "placeholder": "-1 表示永久", "hint": "不填默认永久"},
        ],
    },
    {
        "action": "set_group_sign", "label": "群打卡", "group": "群管理",
        "desc": "在指定群执行一次群打卡。",
        "params": [
            {"name": "group_id", "label": "群号", "type": "int", "required": True,
             "source": "group", "placeholder": "", "hint": "从群聊列表选择"},
        ],
    },
    # ---------------- 系统与其它 ----------------
    {
        "action": "get_online_clients", "label": "获取在线客户端", "group": "系统与其它",
        "desc": "列出 NapCat 当前在线的设备列表。",
        "params": [],
    },
    {
        "action": "ocr_image", "label": "图片文字识别", "group": "系统与其它",
        "desc": "对一张图片做 OCR 文字识别（需实现支持）。",
        "params": [
            {"name": "image", "label": "图片文件或链接", "type": "text", "required": True,
             "placeholder": "例如 https://example.com/a.png", "hint": "图片消息段里的 file 字段或图片直链"},
        ],
    },
    {
        "action": "download_file", "label": "下载文件到本地", "group": "系统与其它",
        "desc": "让 NapCat 把远端文件下载到本地并以本地路径返回。",
        "params": [
            {"name": "url", "label": "文件直链", "type": "text", "required": True,
             "placeholder": "例如 https://example.com/a.zip", "hint": "支持 http / https 链接"},
            {"name": "thread_count", "label": "下载线程数", "type": "int", "required": False,
             "placeholder": "默认 1", "hint": "大文件可适当提高"},
        ],
    },
    {
        "action": "set_restart", "label": "重启 NapCat", "group": "系统与其它",
        "desc": "让 NapCat 拉起一次重启（会影响连接，请谨慎使用）。",
        "params": [
            {"name": "delay", "label": "延迟毫秒", "type": "int", "required": False,
             "placeholder": "默认 0", "hint": "留空立即重启"},
        ],
    },
    # ---------------- 请求处理 ----------------
    {
        "action": "set_friend_add_request", "label": "处理加好友请求", "group": "请求处理",
        "desc": "同意或拒绝一条加好友请求，flag 从实时事件日志的请求事件中获取。",
        "params": [
            {"name": "flag", "label": "请求 flag", "type": "text", "required": True,
             "placeholder": "从请求事件日志中复制", "hint": "NapCat 上报请求事件时给出的唯一标识"},
            {"name": "approve", "label": "同意该请求", "type": "bool", "required": True,
             "placeholder": "", "hint": "勾选为同意，取消勾选为拒绝"},
            {"name": "remark", "label": "好友备注", "type": "text", "required": False,
             "placeholder": "例如 B站观众", "hint": "同意时设置的备注名"},
        ],
    },
    {
        "action": "set_group_add_request", "label": "处理加群请求", "group": "请求处理",
        "desc": "同意或拒绝一条加群 / 邀请请求。",
        "params": [
            {"name": "flag", "label": "请求 flag", "type": "text", "required": True,
             "placeholder": "从请求事件日志中复制", "hint": "NapCat 上报请求事件时给出的唯一标识"},
            {"name": "sub_type", "label": "请求类型", "type": "enum", "required": True,
             "values": [{"value": "add", "label": "申请入群 add"},
                        {"value": "invite", "label": "邀请入群 invite"}],
             "placeholder": "add", "hint": "与事件中的 sub_type 保持一致"},
            {"name": "approve", "label": "同意该请求", "type": "bool", "required": True,
             "placeholder": "", "hint": "勾选为同意，取消勾选为拒绝"},
            {"name": "reason", "label": "拒绝理由", "type": "text", "required": False,
             "placeholder": "例如 申请信息不完整", "hint": "仅在拒绝时生效"},
        ],
    },
    # ---------------- 媒体 ----------------
    {
        "action": "get_image", "label": "获取图片文件", "group": "媒体",
        "desc": "获取图片的本地文件路径。",
        "params": [
            {"name": "file", "label": "图片文件名", "type": "text", "required": True,
             "placeholder": "例如 a1b2c3.image", "hint": "图片消息段里的 file 字段"},
        ],
    },
    {
        "action": "get_record", "label": "获取语音文件", "group": "媒体",
        "desc": "获取语音的本地文件路径（需 ffmpeg）。",
        "params": [
            {"name": "file", "label": "语音文件名", "type": "text", "required": True,
             "placeholder": "例如 a1b2c3.amr", "hint": "语音消息段里的 file 字段"},
            {"name": "out_format", "label": "输出格式", "type": "text", "required": False,
             "placeholder": "默认 mp3", "hint": "例如 mp3 / amr / wav"},
        ],
    },
    {
        "action": "get_cookies", "label": "获取 Cookies", "group": "媒体",
        "desc": "获取指定域名的 Cookies（部分实现不支持）。",
        "params": [
            {"name": "domain", "label": "域名", "type": "text", "required": False,
             "placeholder": "例如 qun.qq.com", "hint": "留空返回全部域名"},
        ],
    },
]


def actions():
    """返回「接口调试」面板使用的 OneBot V11 接口参数元数据（按分组组织）。"""
    groups = []
    index = {}
    for spec in ACTION_SPEC:
        gname = spec.get("group") or "其它"
        if gname not in index:
            index[gname] = {"name": gname, "actions": []}
            groups.append(index[gname])
        index[gname]["actions"].append(spec)
    return {"ok": True, "count": len(ACTION_SPEC), "groups": groups}


# ----------------------------------------------------------------------------
# 状态快照（供 WebUI 轮询）
# ----------------------------------------------------------------------------
def status(include_events=True, event_limit=120, include_raw=False):
    cfg = get_config()
    with _state["lock"]:
        running = _state["running"]
        started_at = _state["started_at"]
        clients = list(_state["clients"].values())
        error = _state["error"]
    now = time.time()
    with _ev_lock:
        counters = dict(_counters)
        events = list(_events)[-event_limit:][::-1]

    # 事件序列化：用当前的昵称 / 群名缓存补全 extra，
    # 这样「当时还没拉到名字」的历史事件，在名字补全后也能自愈显示。
    evs = []
    for e in events:
        it = dict(e)
        ex = dict(it.get("extra") or {})
        uid = str(ex.get("uid") or "")
        gid = str(ex.get("gid") or "")
        uname = str(ex.get("uname") or "")
        gname = str(ex.get("gname") or "")
        if uid and (not uname or uname == uid):
            uname = _user_name(uid) or uname
        if gid and not gname:
            gname = _group_name(gid)
        ex["uname"] = uname
        ex["gname"] = gname
        it["extra"] = ex
        if not include_raw:
            it["raw"] = ""
        evs.append(it)

    cl = []
    for b in clients:
        cl.append({
            "id": b.id,
            "addr": b.addr_text,
            "path": b.path,
            "self_id": b.self_id or "",
            "nickname": b.nickname or "",
            "connected_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(b.connected_at)),
            "uptime_sec": int(now - b.connected_at),
            "last_at": time.strftime("%H:%M:%S", time.localtime(b.last_at)),
            "recv": b.recv_count,
            "sent": b.sent_count,
            "bytes_in": b.bytes_in,
            "bytes_out": b.bytes_out,
        })
    cl.sort(key=lambda x: x["connected_at"])

    return {
        "ok": True,
        "has_lib": HAS_WEBSOCKETS,
        "running": running,
        "error": error,
        "config": cfg,
        "env_locked": ENV_LOCKED,
        "config_source": ".env" if ENV_LOCKED else "ws_config.json",
        "config_note": ENV_LOCK_MSG if ENV_LOCKED else "面板修改会保存到 ws_config.json",
        "listen": "ws://%s:%s%s" % (cfg["host"], cfg["port"], cfg["path"]),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)) if started_at else None,
        "uptime_sec": int(now - started_at) if (started_at and running) else 0,
        "client_count": len(cl),
        "clients": cl,
        "stats": {
            "total_conn": counters["conn"],
            "total_recv": counters["recv"],
            "total_sent": counters["sent"],
            "total_events": counters["event"],
            "bytes_in": counters["bytes_in"],
            "bytes_out": counters["bytes_out"],
        },
        "events": evs if include_events else [],
    }

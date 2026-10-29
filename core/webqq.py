# -*- coding: utf-8 -*-
"""WebQQ 后端：好友 / 群友列表、会话消息、发送、戳一戳、群成员。

设计要点
--------
1. 联系人（好友 / 群）与群成员走 OneBot V11 接口，带短时缓存，避免每次
   打开页面都去拉一遍。
2. 收发消息全部落在内存 + ``cache/webqq/history.json``：
   - 收到的消息来自 ``ws_server.add_event_handler``（真实 QQ 消息）；
   - 自己发出的消息在调用发送接口成功后立即入档，不等 ``message_sent`` 回显。
3. 图片：前端用 dataURL 上传，后端落盘到 ``cache/webqq/media/`` 并通过
   ``/api/webqq/media/<文件名>`` 提供访问，历史记录里只存 URL，不存 base64。
4. ``poll(since)`` 返回全局递增 ``seq`` 之后的所有条目，前端按会话分发。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid

import config

try:                                     # 宿主没装 websockets 时也能正常导入
    import ws_server
    _WS_ERR = ""
except Exception as _e:                  # pragma: no cover
    ws_server = None
    _WS_ERR = str(_e)

# ---------------------------------------------------------------------------
# 路径 / 容量
# ---------------------------------------------------------------------------
_BASE_DIR = os.path.join(config.CACHE_DIR, "webqq")
MEDIA_DIR = os.path.join(_BASE_DIR, "media")
HISTORY_PATH = os.path.join(_BASE_DIR, "history.json")

MAX_PER_CHAT = 200                       # 每个会话保留的消息条数
MAX_CHATS = 60                           # 最多保留的会话数
FEED_MAX = 1200                          # 全局增量队列容量
CONTACT_TTL = 300                        # 好友 / 群列表缓存秒数
MEMBER_TTL = 300                         # 群成员缓存秒数
MAX_IMAGE_BYTES = 12 * 1024 * 1024       # 单张图片上限（与 Web 会话一致）
SYNC_COUNT = 50                          # 单次从 QQ 侧同步的历史消息条数
SYNC_TTL = 20                            # 同一会话两次自动同步的最小间隔（秒）
MAX_NOTICES = 80                         # 通知中心保留的条数

for _d in (_BASE_DIR, MEDIA_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

_lock = threading.RLock()
_seq = 0
_history = {}                            # key -> [item]
_feed = []                               # 全局增量（item 引用）
_dirty = threading.Event()
_started = False

_friends = {"ts": 0.0, "ok": False, "items": []}
_groups = {"ts": 0.0, "ok": False, "items": []}
_members = {}                            # gid -> {"ts", "items"}
_sync_ts = {}                            # key -> 上次成功同步的时间戳
_notices = []                            # 通知中心（加群 / 退群 / 好友申请…）
_notice_id = 0                           # 通知自增 ID（前端增量拉取用）

_MEDIA_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp|bmp)$")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _chat_key(c_type, cid):
    return ("group:" if str(c_type) == "group" else "private:") + str(cid or "")


def _num(value):
    """OneBot 参数优先用整数（NapCat 两种都收，整数兼容性更好）。"""
    s = str(value or "").strip()
    return int(s) if s.isdigit() else s


def _avatar(kind, ident):
    return "/api/ws/avatar?type=%s&id=%s&s=100" % (kind, ident)


def _inner_ok(ret):
    if not isinstance(ret, dict):
        return False
    if str(ret.get("status") or "") == "ok":
        return True
    try:
        return int(ret.get("retcode")) == 0
    except (TypeError, ValueError):
        return False


def _api(action, params, timeout=10.0):
    """调用 OneBot 接口，返回 ``(data, error)``（error 为空表示成功）。"""
    if ws_server is None:
        return None, "ws_server 不可用：%s" % (_WS_ERR or "模块未加载")
    try:
        r = ws_server.call_api(action, params or {}, timeout)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)
    if not isinstance(r, dict) or not r.get("ok"):
        return None, str((r or {}).get("error") or "调用失败")
    ret = r.get("response")
    if not _inner_ok(ret):
        ret = ret if isinstance(ret, dict) else {}
        return None, str(ret.get("wording") or ret.get("message") or
                         ret.get("msg") or ("返回码 %s" % ret.get("retcode", "?")))
    return ret.get("data"), ""


def _me():
    """当前登录账号 {id, name, avatar}。"""
    info = {}
    if ws_server is not None:
        try:
            info = ws_server.self_account() or {}
        except Exception:
            info = {}
    uid = str(info.get("self_id") or "")
    return {"id": uid, "name": str(info.get("nickname") or "我"),
            "avatar": _avatar("user", uid) if uid else ""}


# ---------------------------------------------------------------------------
# 历史持久化
# ---------------------------------------------------------------------------
def _load():
    global _seq
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return
    if not isinstance(raw, dict):
        return
    try:
        _seq = int(raw.get("seq") or 0)
    except (TypeError, ValueError):
        _seq = 0
    chats = raw.get("chats")
    if not isinstance(chats, dict):
        return
    for key, items in chats.items():
        if not isinstance(items, list):
            continue
        clean = [it for it in items if isinstance(it, dict) and it.get("kind")]
        if clean:
            _history[str(key)] = clean[-MAX_PER_CHAT:]


def _write():
    with _lock:
        payload = {"seq": _seq,
                   "chats": {k: [dict(x) for x in v] for k, v in _history.items()}}
    tmp = HISTORY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, HISTORY_PATH)
    except Exception:
        pass


def _save_loop():
    while True:
        _dirty.wait()
        time.sleep(1.2)
        _dirty.clear()
        _write()


def _cleanup_media():
    """清掉 7 天前的图片，避免缓存目录无限膨胀。"""
    cutoff = time.time() - 7 * 24 * 3600
    try:
        for name in os.listdir(MEDIA_DIR):
            p = os.path.join(MEDIA_DIR, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def start():
    """加载历史并启动后台落盘线程（重复调用无副作用）。"""
    global _started
    if _started:
        return
    _started = True
    _load()
    _cleanup_media()
    threading.Thread(target=_save_loop, name="webqq-save", daemon=True).start()


# ---------------------------------------------------------------------------
# 条目
# ---------------------------------------------------------------------------
def _append_locked(item):
    global _seq
    _seq += 1
    item["seq"] = _seq
    if not item.get("time"):
        item["time"] = int(time.time())
    key = item.get("key") or _chat_key(item.get("chat_type"), item.get("chat_id"))
    item["key"] = key
    lst = _history.setdefault(key, [])
    lst.append(item)
    if len(lst) > MAX_PER_CHAT:
        del lst[:len(lst) - MAX_PER_CHAT]
    _feed.append(item)
    if len(_feed) > FEED_MAX:
        del _feed[:len(_feed) - FEED_MAX]
    if len(_history) > MAX_CHATS:
        order = sorted(_history, key=lambda k: (
            _history[k][-1].get("time") or 0) if _history[k] else 0)
        for k in order[:len(_history) - MAX_CHATS]:
            if k != key:
                _history.pop(k, None)
    _dirty.set()
    return item


def _previews():
    out = {}
    with _lock:
        for key, items in _history.items():
            for it in reversed(items):
                if it.get("kind") == "patch":
                    continue
                out[key] = {
                    "text": str(it.get("text") or "")[:80],
                    "time": it.get("time") or 0,
                    "self": bool(it.get("self")),
                    "kind": it.get("kind") or "message",
                }
                break
    return out


# ---------------------------------------------------------------------------
# 联系人
# ---------------------------------------------------------------------------
def _fetch_friends(force=False):
    now = time.time()
    with _lock:
        cached = dict(_friends)
    if not force and cached["ts"]:
        age = now - cached["ts"]
        if age < CONTACT_TTL:
            return list(cached["items"]), "" if cached["ok"] else "NapCat 未连接"
        if age < 15 and not cached["ok"]:
            return list(cached["items"]), "NapCat 未连接"
    data, err = _api("get_friend_list", {}, 10.0)
    items = []
    if isinstance(data, list):
        for f in data:
            if not isinstance(f, dict):
                continue
            uid = str(f.get("user_id") or f.get("uin") or "").strip()
            if not uid:
                continue
            nickname = str(f.get("nickname") or "")
            remark = str(f.get("remark") or "")
            items.append({"type": "private", "id": uid,
                          "name": remark or nickname or uid,
                          "nickname": nickname, "remark": remark,
                          "avatar": _avatar("user", uid)})
        items.sort(key=lambda x: x["name"])
    with _lock:
        if not err:
            _friends.update(ts=now, ok=True, items=items)
        else:
            _friends.update(ts=now, ok=False)
        return list(_friends["items"]), err


def _fetch_groups(force=False):
    now = time.time()
    with _lock:
        cached = dict(_groups)
    if not force and cached["ts"]:
        age = now - cached["ts"]
        if age < CONTACT_TTL:
            return list(cached["items"]), "" if cached["ok"] else "NapCat 未连接"
        if age < 15 and not cached["ok"]:
            return list(cached["items"]), "NapCat 未连接"
    data, err = _api("get_group_list", {}, 10.0)
    items = []
    if isinstance(data, list):
        for g in data:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("group_id") or "").strip()
            if not gid:
                continue
            try:
                count = int(g.get("member_count") or g.get("max_member_count") or 0)
            except (TypeError, ValueError):
                count = 0
            items.append({"type": "group", "id": gid,
                          "name": str(g.get("group_name") or gid),
                          "member_count": count,
                          "avatar": _avatar("group", gid)})
        items.sort(key=lambda x: x["name"])
    with _lock:
        if not err:
            _groups.update(ts=now, ok=True, items=items)
        else:
            _groups.update(ts=now, ok=False)
        return list(_groups["items"]), err


def bootstrap(force=False):
    """页面初始化：账号、好友、群、最近会话摘要、当前 seq。"""
    me = _me()
    if not me["id"]:
        data, err = _api("get_login_info", {}, 5.0)
        if not err and isinstance(data, dict):
            me["id"] = str(data.get("user_id") or "")
            me["name"] = str(data.get("nickname") or me["name"])
            if me["id"]:
                me["avatar"] = _avatar("user", me["id"])

    friends, ferr = _fetch_friends(force)
    groups, gerr = _fetch_groups(force)
    online = not (ferr and gerr)
    error = "" if online else (ferr or gerr or "NapCat 未连接")
    n = notices(0)
    recent = n["items"][-25:]
    return {"ok": True, "online": online, "me": me,
            "prefix": str(getattr(config, "BOT_PREFIX", "/") or "/"),
            "bot_name": str(getattr(config, "BOT_NAME", "") or ""),
            "friends": friends, "groups": groups,
            "previews": _previews(), "seq": _seq, "error": error,
            "notices": recent, "notice_seq": n["seq"],
            "notice_pending": n["pending"]}


def members(gid, force=False):
    """群成员列表（缓存 MEMBER_TTL 秒）。"""
    gid = str(gid or "").strip()
    if not gid:
        return {"ok": False, "error": "缺少群号"}
    now = time.time()
    with _lock:
        cached = _members.get(gid)
    if cached and not force and now - cached["ts"] < MEMBER_TTL:
        return {"ok": True, "items": list(cached["items"]), "cached": True}
    params = {"group_id": _num(gid)}
    if force:
        params["no_cache"] = True
    data, err = _api("get_group_member_list", params, 20.0)
    if err:
        with _lock:
            old = _members.get(gid)
        if old:
            return {"ok": True, "items": list(old["items"]), "warning": err,
                    "cached": True}
        return {"ok": False, "error": err}
    items = []
    if isinstance(data, list):
        for m in data:
            if not isinstance(m, dict):
                continue
            uid = str(m.get("user_id") or "").strip()
            if not uid:
                continue
            card = str(m.get("card") or "")
            nickname = str(m.get("nickname") or "")
            items.append({"id": uid, "name": card or nickname or uid,
                          "card": card, "nickname": nickname,
                          "role": str(m.get("role") or "member"),
                          "title": str(m.get("title") or ""),
                          "avatar": _avatar("user", uid)})
    order = {"owner": 0, "admin": 1, "member": 2}
    items.sort(key=lambda x: (order.get(x["role"], 3), x["name"]))
    with _lock:
        _members[gid] = {"ts": now, "items": items}
    return {"ok": True, "items": items}


# ---------------------------------------------------------------------------
# 消息段
# ---------------------------------------------------------------------------
def _norm_seg(seg):
    """把 OneBot 消息段裁成 WebQQ 需要的字段（丢弃超长 / 不可用数据）。"""
    if not isinstance(seg, dict):
        return None
    typ = str(seg.get("type") or "")
    data = seg.get("data")
    data = data if isinstance(data, dict) else {}
    if typ == "text":
        text = str(data.get("text") or "")
        return {"type": "text", "data": {"text": text}} if text else None
    if typ == "at":
        qq = str(data.get("qq") or "")
        name = str(data.get("name") or "")
        return {"type": "at", "data": {"qq": qq, "name": name}} if qq else None
    if typ == "face":
        fid = str(data.get("id") or "")
        return {"type": "face", "data": {"id": fid}} if fid else None
    if typ == "image":
        url = str(data.get("url") or "")
        fid = str(data.get("file") or "")
        if not url:
            url = fid if fid.startswith(("http://", "https://")) else ""
        # file 是文件名，file_id 才是 NapCat /get_image 真正认的标识；
        # 两个都留着，url 过期时可以换到新地址（群里老图非常常见）。
        return {"type": "image",
                "data": {"url": url,
                         "file": fid if not fid.startswith("http") else "",
                         "file_id": str(data.get("file_id") or ""),
                         "summary": str(data.get("summary") or "")}}
    if typ == "reply":
        rid = str(data.get("id") or "")
        return {"type": "reply", "data": {"id": rid}} if rid else None
    if typ in ("record", "video", "file"):
        url = str(data.get("url") or "")
        f = str(data.get("file") or "")
        if not url and f.startswith(("http://", "https://")):
            url = f
        return {"type": typ, "data": {
            "url": url,
            "file": f if not f.startswith(("http://", "https://")) else "",
            "file_id": str(data.get("file_id") or ""),
            "name": str(data.get("name") or f),
            "summary": str(data.get("summary") or "")}}
    if typ == "mface":
        # 商城表情（大表情 / 收藏表情）带图就存图，否则前端只能看到一行文字
        url = str(data.get("url") or "")
        return {"type": "mface", "data": {
            "url": url,
            "summary": str(data.get("summary") or data.get("name") or ""),
            "emoji_id": str(data.get("emoji_id") or ""),
            "package_id": str(data.get("emoji_package_id") or data.get("package_id") or ""),
            "key": str(data.get("key") or ""),
            "file": str(data.get("file") or ""),
            "file_id": str(data.get("file_id") or "")}}
    if typ in ("json", "xml"):
        return {"type": typ, "data": {}}
    if typ == "forward":
        raw = data.get("content") or data.get("messages") or []
        nodes = _norm_forward_nodes(raw)
        return {"type": "forward",
                "data": {"id": str(data.get("id") or data.get("message_id") or ""),
                         "nodes": nodes,
                         "count": len(nodes) or (len(raw) if isinstance(raw, list) else 0)}}
    return {"type": "unknown", "data": {"raw": typ}}


def _norm_forward_nodes(raw, limit=80):
    """把合并转发的节点裁成前端能展开的 ``{name,time,segs,text}`` 列表。

    NapCat 收到的 forward 段可能带 ``content``，也可能只有 ``id``（需要再调
    /get_forward_msg）；两种结构（node.data 与扁平 sender/message）都兼容。
    """
    nodes = []
    for node in (raw if isinstance(raw, list) else [])[:limit]:
        if not isinstance(node, dict):
            continue
        d = node.get("data") if isinstance(node.get("data"), dict) else node
        sender = d.get("sender")
        name = ""
        if isinstance(sender, dict):
            name = str(sender.get("card") or sender.get("nickname")
                       or sender.get("user_id") or "")
        if not name:
            name = str(d.get("nickname") or d.get("name")
                       or d.get("user_id") or d.get("uin") or "")
        content = d.get("content")
        if content is None:
            content = d.get("message")
        if isinstance(content, str):
            segs = [{"type": "text", "data": {"text": content}}] if content else []
        elif isinstance(content, list):
            segs = [s for s in (_norm_seg(x) for x in content) if s]
        else:
            segs = []
        # 有些实现直接把 node 本身当消息段上报
        if not segs and node.get("type") not in ("node", None):
            one = _norm_seg(node)
            if one:
                segs = [one]
        for s in segs:                         # 防止一条超长文本把历史文件撑爆
            if s.get("type") == "text" and len(str((s.get("data") or {}).get("text") or "")) > 3000:
                s["data"]["text"] = str(s["data"]["text"])[:3000] + "…"
        nodes.append({"name": name[:40],
                      "time": int(d.get("time") or 0),
                      "segs": segs,
                      "text": _render_text(segs)})
    return nodes


def _event_segs(ev):
    msg = ev.get("message")
    if isinstance(msg, list):
        return [s for s in (_norm_seg(x) for x in msg) if s]
    if isinstance(msg, str) and msg:
        return [{"type": "text", "data": {"text": msg}}]
    raw = str(ev.get("raw_message") or "")
    return [{"type": "text", "data": {"text": raw}}] if raw else []


def _render_text(segs):
    parts = []
    for seg in segs:
        typ = seg.get("type")
        data = seg.get("data") or {}
        if typ == "text":
            parts.append(str(data.get("text") or ""))
        elif typ == "at":
            qq = str(data.get("qq") or "")
            if qq == "all":
                parts.append("@全体成员")
            else:
                parts.append("@" + (str(data.get("name") or "") or qq))
        elif typ == "face":
            parts.append("[表情]")
        elif typ == "image":
            parts.append("[图片]")
        elif typ == "reply":
            parts.append("[回复]")
        elif typ == "record":
            parts.append("[语音]")
        elif typ == "video":
            parts.append("[视频]")
        elif typ == "file":
            parts.append("[文件]")
        elif typ in ("json", "xml"):
            parts.append("[卡片消息]")
        elif typ == "forward":
            parts.append("[聊天记录]")
        elif typ == "mface":
            parts.append("[商城表情]")
    return "".join(parts).strip()


def _admin_text(name, gname, is_set):
    return ("%s 成为了「%s」的管理员" if is_set else
            "%s 被取消了「%s」的管理员") % (name, gname)


def _admin_is_set(gid, uid, fallback_set):
    """「设置 / 取消管理员」到底是哪一种：以成员当前 role 为准。

    某些 NapCat 版本取消管理员时也回 sub_type=set，光看事件字段会把文案写反。
    """
    data, err = _api("get_group_member_info", {
        "group_id": _num(gid), "user_id": _num(uid), "no_cache": True}, 6.0)
    role = str((data or {}).get("role") or "") if not err else ""
    if role in ("admin", "owner"):
        return True
    if role:
        return False
    return bool(fallback_set)


# ---------------------------------------------------------------------------
# 事件钩子
# ---------------------------------------------------------------------------
def _on_message(ev):
    mtype = str(ev.get("message_type") or "")
    post = str(ev.get("post_type") or "")
    gid = str(ev.get("group_id") or "")
    uid = str(ev.get("user_id") or "")
    if mtype == "group" and gid:
        ctype, cid = "group", gid
    elif mtype == "private" and uid:
        ctype, cid = "private", uid
    else:
        return

    sender = ev.get("sender")
    sender = sender if isinstance(sender, dict) else {}
    self_id = str(ev.get("self_id") or "")
    is_self = (post == "message_sent") or bool(
        self_id and str(sender.get("user_id") or uid) == self_id)
    if is_self:
        me = _me()
        who = {"id": self_id or me["id"], "name": me["name"] or "我",
               "role": "owner" if ctype == "group" else ""}
    else:
        who = {"id": uid,
               "name": str(sender.get("card") or sender.get("nickname") or uid),
               "role": str(sender.get("role") or "")}

    segs = _event_segs(ev)
    mid = str(ev.get("message_id") or "")
    # 图片 / 合并转发可能没带完整内容，记下消息 id 供前端稍后按需刷新
    if mid:
        for s in segs:
            if s.get("type") in ("image", "forward", "video", "record", "file") \
                    and not (s.get("data") or {}).get("mid"):
                s["data"]["mid"] = mid
    key = _chat_key(ctype, cid)
    with _lock:
        if mid:
            for it in reversed(_history.get(key, [])):
                if it.get("kind") == "message" and it.get("mid") == mid:
                    return
        _append_locked({"kind": "message", "chat_type": ctype, "chat_id": cid,
                        "mid": mid, "self": bool(is_self), "sender": who,
                        "segs": segs, "text": _render_text(segs)})


def _on_notice(ev):
    ntype = str(ev.get("notice_type") or "")
    sub = str(ev.get("sub_type") or "")
    gid = str(ev.get("group_id") or "")
    uid = str(ev.get("user_id") or "")
    self_id = str(ev.get("self_id") or "")

    if ntype == "notify" and sub == "poke":
        if uid and self_id and uid == self_id:
            return                           # 自己戳的由 poke() 本地记一条
        ctype, cid = ("group", gid) if gid else ("private", uid)
        if not cid:
            return
        sender = ev.get("sender")
        sender = sender if isinstance(sender, dict) else {}
        actor = str(sender.get("card") or sender.get("nickname") or uid)
        target = str(ev.get("target_id") or "")
        target = "你" if (self_id and target == self_id) else (target or "你")
        _append_system(ctype, cid, "%s 戳了戳 %s" % (actor, target))
        return

    if ntype == "group_increase":
        gname = _group_name(gid)
        name = _name_of(uid, gid)
        op = str(ev.get("operator_id") or "")
        text = "%s 加入了「%s」" % (name, gname) if gname else "%s 加入了群聊" % name
        if op and op != uid:
            text += "（邀请人：%s）" % _name_of(op, gid)
        it = _push_notice({"kind": "group_increase", "chat_type": "group", "chat_id": gid,
                           "gid": gid, "gname": gname, "uid": uid, "name": name,
                           "operator": (_name_of(op, gid) if op and op != uid else ""),
                           "text": text})
        _append_system("group", gid, text)
        _bump_contacts(gid)
        _resolve_member(it["id"], gid, uid)
        return

    if ntype == "group_decrease":
        gname = _group_name(gid)
        name = _name_of(uid, gid)
        op = str(ev.get("operator_id") or "")
        if sub == "kick" and op and op != uid:
            text = "%s 被 %s 移出了「%s」" % (name, _name_of(op, gid), gname)
        else:
            text = "%s 退出了「%s」" % (name, gname)
        it = _push_notice({"kind": "group_decrease", "chat_type": "group", "chat_id": gid,
                           "gid": gid, "gname": gname, "uid": uid, "name": name,
                           "operator": (_name_of(op, gid) if op and op != uid else ""),
                           "text": text})
        _append_system("group", gid, text)
        _bump_contacts(gid)
        _resolve_member(it["id"], gid, uid)
        return

    if ntype == "group_admin":
        gname = _group_name(gid)
        name = _name_of(uid, gid)
        # 部分 NapCat 版本把「取消管理员」也报成 sub_type=set；这里以成员真实 role
        # 为准（同步查一次，管理员变更很少发生，值得多这一次请求）。
        is_set = str(sub).lower() in ("set", "enable", "add", "on", "1", "true")
        is_set = _admin_is_set(gid, uid, is_set)
        text = _admin_text(name, gname, is_set)
        op = str(ev.get("operator_id") or "")
        it = _push_notice({"kind": "group_admin", "chat_type": "group", "chat_id": gid,
                           "gid": gid, "gname": gname, "uid": uid, "name": name,
                           "operator": (_name_of(op, gid) if op and op != uid else ""),
                           "admin_set": bool(is_set), "text": text})
        _append_system("group", gid, text)
        _resolve_member(it["id"], gid, uid)
        _bump_contacts(gid)
        return

    if ntype == "friend_add":
        name = _name_of(uid)
        text = "%s 已添加你为好友" % name
        it = _push_notice({"kind": "friend_add", "chat_type": "private",
                           "chat_id": uid, "uid": uid, "name": name,
                           "operator": name, "text": text})
        _bump_contacts()
        _resolve_starter(it["id"], uid, "friend")
        return

    if ntype in ("group_recall", "friend_recall"):
        mid = str(ev.get("message_id") or "")
        if not mid:
            return
        ctype, cid = ("group", gid) if ntype == "group_recall" else ("private", uid)
        if not cid:
            return
        with _lock:
            _append_locked({"kind": "patch", "op": "recall", "mid": mid,
                            "chat_type": ctype, "chat_id": cid,
                            "text": "撤回了一条消息"})


# ---------------------------------------------------------------------------
# 通知中心（加群 / 退群 / 管理员变更 / 好友申请）
# ---------------------------------------------------------------------------
def _name_of(uid, gid=""):
    """把 QQ 号翻译成群名片 / 好友备注，只查本地缓存，不阻塞事件线程。"""
    uid = str(uid or "").strip()
    if not uid:
        return ""
    if gid:
        with _lock:
            cached = _members.get(str(gid))
        for m in (cached or {}).get("items") or []:
            if str(m.get("id")) == uid:
                return str(m.get("name") or uid)
    with _lock:
        friends = list(_friends["items"])
        groups = list(_groups["items"])
    for f in friends:
        if str(f.get("id")) == uid:
            return str(f.get("name") or uid)
    for g in groups:
        if str(g.get("id")) == uid:
            return str(g.get("name") or gid)
    return uid


def _group_name(gid):
    gid = str(gid or "")
    with _lock:
        for g in _groups["items"]:
            if str(g.get("id")) == gid:
                return str(g.get("name") or gid)
    return gid


def _notice_text(kind, name, gname="", comment="", sub=""):
    name = name or "未知用户"
    if kind == "friend_request":
        t = "%s 请求加你为好友" % name
    elif kind == "group_request":
        t = ("%s 邀请你加入「%s」" if sub == "invite" else
             "%s 申请加入「%s」") % (name, gname or "群聊")
    elif kind == "friend_add":
        t = "%s 已添加你为好友" % name
    elif kind == "group_increase":
        t = "%s 加入了「%s」" % (name, gname or "群聊")
    elif kind == "group_decrease":
        t = "%s 退出了「%s」" % (name, gname or "群聊")
    elif kind == "group_admin":
        t = "%s 成为了「%s」的管理员" % (name, gname or "群聊")
    else:
        return str(name)
    return t + ("：" + comment if comment else "")


def _push_notice(item):
    """写入通知中心（按时间正序，最新在末尾），返回副本。"""
    global _notice_id
    with _lock:
        _notice_id += 1
        it = {"id": _notice_id, "time": int(item.get("time") or time.time()),
              "handled": 0, "approved": False}
        it.update(item)
        _notices.append(it)
        if len(_notices) > MAX_NOTICES:
            del _notices[:len(_notices) - MAX_NOTICES]
        return dict(it)


def _patch_notice(nid, **kw):
    if not nid:
        return
    with _lock:
        for it in _notices:
            if it.get("id") == nid:
                it.update(kw)
                return


def _patch_name(nid, name):
    """补充昵称后同步刷新通知文案。"""
    if not nid or not name:
        return
    with _lock:
        for it in _notices:
            if it.get("id") == nid:
                it["name"] = name
                it["text"] = _notice_text(it.get("kind"), name, it.get("gname"),
                                          it.get("comment"), it.get("sub"))
                return


def _resolve_member(nid, gid, uid):
    """群通知只有 QQ 号时，后台补一次群名片。"""
    uid, gid = str(uid or ""), str(gid or "")
    if not uid or not gid:
        return

    def run():
        data, err = _api("get_group_member_info",
                         {"group_id": _num(gid), "user_id": _num(uid)}, 4.0)
        if err or not isinstance(data, dict):
            return
        name = str(data.get("card") or data.get("nickname") or "").strip()
        _patch_name(nid, name)

    threading.Thread(target=run, name="webqq-notice-member", daemon=True).start()


def _resolve_starter(nid, uid, kind):
    """好友申请 / 新好友事件只有 QQ 号，后台补一次昵称。"""
    uid = str(uid or "")
    if not uid:
        return

    def run():
        data, err = _api("get_stranger_info", {"user_id": _num(uid)}, 4.0)
        if err or not isinstance(data, dict):
            return
        name = str(data.get("nickname") or "").strip()
        _patch_name(nid, name)

    threading.Thread(target=run, name="webqq-notice-stranger", daemon=True).start()


def _bump_contacts(gid=""):
    """联系人缓存失效，下次打开页面时重新拉取。"""
    with _lock:
        _friends["ts"] = 0.0
        _groups["ts"] = 0.0
        if gid:
            gid = str(gid)
            _members.pop(gid, None)
            # 自己的身份缓存也一起失效：管理员被设 / 被撤之后，
            # 禁言、踢人、撤回这些入口要立刻跟着变
            _role_cache.pop(gid, None)


def _on_request(ev):
    rtype = str(ev.get("request_type") or "")
    uid = str(ev.get("user_id") or "")
    flag = str(ev.get("flag") or "")
    comment = str(ev.get("comment") or "").strip()
    gid = str(ev.get("group_id") or "")
    sub = str(ev.get("sub_type") or "")
    if not flag or not uid:
        return

    if rtype == "friend":
        name = _name_of(uid)
        it = _push_notice({"kind": "friend_request", "chat_type": "private",
                           "chat_id": uid, "uid": uid, "name": name,
                           "operator": name,
                           "flag": flag, "comment": comment, "sub": "",
                           "text": _notice_text("friend_request", name, "", comment)})
        _resolve_starter(it["id"], uid, "friend")
        return

    if rtype == "group":
        gname = _group_name(gid)
        name = _name_of(uid, gid)
        it = _push_notice({"kind": "group_request", "chat_type": "group",
                           "chat_id": gid, "gid": gid, "gname": gname,
                           "uid": uid, "name": name, "flag": flag,
                           "operator": name,
                           "comment": comment, "sub": sub,
                           "text": _notice_text("group_request", name, gname,
                                                comment, sub)})
        _resolve_member(it["id"], gid, uid)


def _append_system(ctype, cid, text, self_flag=False):
    with _lock:
        return _append_locked({"kind": "system", "chat_type": ctype,
                               "chat_id": cid, "self": bool(self_flag),
                               "text": str(text or "")})


def on_event(ev, client=None):
    """注册给 ws_server.add_event_handler 的入口。"""
    if not isinstance(ev, dict):
        return
    try:
        post = ev.get("post_type")
        if post in ("message", "message_sent"):
            _on_message(ev)
        elif post == "notice":
            _on_notice(ev)
        elif post == "request":
            _on_request(ev)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 图片落盘
# ---------------------------------------------------------------------------
def _looks_image(raw):
    """内容是不是真的图片（只认文件头，不看 Content-Type）。"""
    return (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff"
            or raw[:4] == b"GIF8" or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
            or raw[:2] == b"BM")


def _sniff_image(raw):
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if raw[:4] == b"GIF8":
        return "image/gif", "gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp", "webp"
    if raw[:2] == b"BM":
        return "image/bmp", "bmp"
    return "image/png", "png"


def _decode_data_url(raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    if s.startswith("base64://"):
        s = s[9:]
    elif s.startswith("data:"):
        i = s.find(",")
        if i < 0:
            return None
        s = s[i + 1:]
    try:
        data = base64.b64decode(s, validate=False)
    except Exception:
        return None
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    return data


def _save_image(raw):
    _, ext = _sniff_image(raw)
    name = uuid.uuid4().hex + "." + ext
    try:
        with open(os.path.join(MEDIA_DIR, name), "wb") as f:
            f.write(raw)
    except OSError:
        return ""
    return "/api/webqq/media/" + name


def _save_image_path(raw):
    """把图片存到 media 目录并返回绝对路径（NapCat 的公告接口收本地文件路径）。"""
    _, ext = _sniff_image(raw)
    name = uuid.uuid4().hex + "." + ext
    path = os.path.join(MEDIA_DIR, name)
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError:
        return ""
    return path


def media_path(name):
    name = str(name or "")
    if not _MEDIA_RE.match(name):
        return ""
    path = os.path.join(MEDIA_DIR, name)
    return path if os.path.isfile(path) else ""


# ---------------------------------------------------------------------------
# 远程图片代理（QQ 图床有防盗链，带 Referer 会返回「此图片来自QQ空间」占位图）
# ---------------------------------------------------------------------------
# 只允许代理 QQ 自己的图床域名，避免变成公开的任意 URL 代理（SSRF）。
_REMOTE_HOSTS = (".qpic.cn", ".gtimg.cn", ".qlogo.cn", ".qq.com",
                 ".qq.com.cn", ".myqcloud.com")
_REMOTE_EXTS = ("png", "jpg", "jpeg", "gif", "webp", "bmp")


def _remote_allowed(url):
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
    except Exception:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == h.lstrip(".") or host.endswith(h) for h in _REMOTE_HOSTS)


def remote_allowed(url):
    """给 app.py 的流媒体代理复用同一套域名白名单（视频 / 语音也走它）。"""
    return _remote_allowed(url)


def remote_image(url, file="", file_id="", mid=""):
    """下载远端图片到本地缓存，返回 ``(文件名, 错误)``。

    QQ 图片 url 只带约 2 小时有效的 rkey，过期后必须让 NapCat 刷新：
    依次用 ``file_id`` / ``file`` / 原 url 调 ``get_image``，仍失败再用 ``get_msg``
    按消息 id 重新解析整条消息，从里面找同 file_id 的新 url。
    缓存名按**原始 url** 的 sha1，换到新地址后也能命中，不用重复刷新。
    """
    url = str(url or "").strip()
    file = str(file or "").strip()
    file_id = str(file_id or "").strip()
    mid = str(mid or "").strip()
    if not url and not (file_id or file or mid):
        return "", "缺少图片地址"
    if url and not _remote_allowed(url):
        return "", "不在允许的域名内"

    base = hashlib.sha1((url or "|".join((file_id, file, mid))).encode("utf-8")).hexdigest()[:32]
    for ext in _REMOTE_EXTS:
        name = base + "." + ext
        path = os.path.join(MEDIA_DIR, name)
        if os.path.isfile(path):
            # 老版本可能把「签名过期后返回的 JSON」当成 PNG 缓存了，这种坏缓存直接丢掉重下
            try:
                with open(path, "rb") as f:
                    head = f.read(16)
            except OSError:
                head = b""
            if _looks_image(head):
                return name, ""
            try:
                os.remove(path)
            except OSError:
                pass

    def _download(u):
        import requests
        return requests.get(u, timeout=12, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0 Safari/537.36"),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "",
        })

    def _refresh_url():
        """让 NapCat 换一条新地址；拿不到返回空串。"""
        tries = []
        if file_id:
            tries.append({"file_id": file_id})
        if file:
            tries.append({"file": file})
        if url:
            tries.append({"file": url})
        for params in tries:
            data, e = _api("get_image", params, 8.0)
            if e:
                continue
            if isinstance(data, str):
                fresh = data
            else:
                fresh = str((data or {}).get("url") or (data or {}).get("file") or "")
            if fresh and _remote_allowed(fresh):
                return fresh, ""
        # get_image 都不行：按消息 id 把整条消息重新解析一遍，找同一张图的新 url
        if mid:
            data, e = _api("get_msg", {"message_id": _num(mid)}, 8.0)
            segs = (data or {}).get("message") if isinstance(data, dict) else None
            hits = []
            for seg in (segs if isinstance(segs, list) else []):
                if not isinstance(seg, dict) or seg.get("type") != "image":
                    continue
                d = seg.get("data") if isinstance(seg.get("data"), dict) else {}
                hits.append(d)
                if (file_id and str(d.get("file_id") or "") == file_id) or \
                        (file and str(d.get("file") or "") == file) or \
                        (url and str(d.get("url") or "") == url):
                    fresh = str(d.get("url") or "")
                    if fresh and _remote_allowed(fresh):
                        return fresh, ""
            if len(hits) == 1:                 # 消息里只有一张图，直接用它
                fresh = str(hits[0].get("url") or "")
                if fresh and _remote_allowed(fresh):
                    return fresh, ""
            if e:
                return "", e
        return "", "图片地址已失效"

    if not url:
        url, e2 = _refresh_url()
        if not url:
            return "", e2 or "图片地址已失效"

    resp = None
    err = ""
    for attempt in range(2):
        try:
            resp = _download(url)
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            resp = None
        if resp is not None and resp.status_code == 200 and resp.content \
                and _looks_image(resp.content):
            break
        # 第一次失败：QQ 图片 rkey 过期，找 NapCat 换新地址再试
        if attempt == 0 and (file_id or file or mid):
            fresh, e2 = _refresh_url()
            if fresh:
                url = fresh
                continue
            err = err or e2 or "图片地址已失效"
        else:
            break

    if resp is None or resp.status_code != 200 or not resp.content:
        return "", err or ("下载失败（HTTP %s）" % getattr(resp, "status_code", "?"))
    raw = resp.content
    if len(raw) > MAX_IMAGE_BYTES:
        return "", "图片过大"
    if not _looks_image(raw):
        return "", "拿到的是过期地址返回的非图片内容"
    _, ext = _sniff_image(raw)
    name = base + "." + ext
    try:
        with open(os.path.join(MEDIA_DIR, name), "wb") as f:
            f.write(raw)
    except OSError as e:
        return "", "写入失败：%s" % e
    return name, ""


def refresh_media(file="", file_id="", mid=""):
    """视频 / 语音 / 文件的地址过期后，让 NapCat 重新给一条可用 URL。

    先试 ``get_file``（file_id / 文件名），再退回 ``get_msg`` 按消息 id 重新解析。
    """
    file = str(file or "").strip()
    file_id = str(file_id or "").strip()
    mid = str(mid or "").strip()
    if not (file or file_id or mid):
        return ""
    tries = []
    if file_id:
        tries.append({"file_id": file_id})
    if file:
        tries.append({"file": file})
    for params in tries:
        data, err = _api("get_file", params, 8.0)
        if err:
            continue
        u = data if isinstance(data, str) else str((data or {}).get("url") or "")
        if u.startswith(("http://", "https://")) and _remote_allowed(u):
            return u
    if mid:
        data, err = _api("get_msg", {"message_id": _num(mid)}, 8.0)
        segs = (data or {}).get("message") if isinstance(data, dict) else None
        media = []
        for seg in (segs if isinstance(segs, list) else []):
            if not isinstance(seg, dict) or seg.get("type") not in (
                    "video", "record", "file"):
                continue
            d = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            media.append(d)
            if (file_id and str(d.get("file_id") or "") == file_id) or \
                    (file and str(d.get("file") or "") == file):
                u = str(d.get("url") or "")
                if u.startswith(("http://", "https://")) and _remote_allowed(u):
                    return u
        if len(media) == 1:
            u = str(media[0].get("url") or "")
            if u.startswith(("http://", "https://")) and _remote_allowed(u):
                return u
    return ""


def forward(fid, mid=""):
    """读取合并转发内容（WebQQ 里点「聊天记录」卡片时调用）。

    ``fid`` 是 forward 段的 id；部分实现只给消息 id，这时用 ``mid`` 先调
    ``get_msg`` 找到 forward 段，再查 ``get_forward_msg``。
    """
    fid = str(fid or "").strip()
    mid = str(mid or "").strip()
    if not fid and not mid:
        return {"ok": False, "error": "缺少合并转发 id"}

    data, err = None, ""
    if fid:
        for params in ({"id": fid}, {"message_id": fid}):
            data, err = _api("get_forward_msg", params, 12.0)
            if not err:
                break
    if (err or not fid) and mid:
        got, e2 = _api("get_msg", {"message_id": _num(mid)}, 10.0)
        segs = (got or {}).get("message") if isinstance(got, dict) else None
        for seg in (segs if isinstance(segs, list) else []):
            if isinstance(seg, dict) and seg.get("type") == "forward":
                d = seg.get("data") if isinstance(seg.get("data"), dict) else {}
                if d.get("content"):
                    data, err = {"messages": d.get("content")}, ""
                    break
                new_id = str(d.get("id") or d.get("message_id") or "")
                if new_id:
                    data, err = _api("get_forward_msg", {"id": new_id}, 12.0)
                    break
        if err:
            err = e2 or err
    if err:
        return {"ok": False, "error": err}
    raw = (data or {}).get("messages") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raw = (data or {}).get("content") if isinstance(data, dict) else []
    nodes = _norm_forward_nodes(raw)
    return {"ok": True, "nodes": nodes, "count": len(nodes)}


# ---------------------------------------------------------------------------
# 发送
# ---------------------------------------------------------------------------
def _sanitize_seg(seg):
    """返回 ``(发给 NapCat 的消息段, 入库存的消息段)``；无效时返回 (None, None)。"""
    if not isinstance(seg, dict):
        return None, None
    typ = str(seg.get("type") or "")
    data = seg.get("data")
    data = data if isinstance(data, dict) else {}

    if typ == "text":
        text = str(data.get("text") or "")
        if not text:
            return None, None
        return ({"type": "text", "data": {"text": text}},
                {"type": "text", "data": {"text": text}})

    if typ == "face":
        fid = str(data.get("id") or "").strip()
        if not fid.isdigit():
            return None, None
        return ({"type": "face", "data": {"id": fid}},
                {"type": "face", "data": {"id": fid}})

    if typ == "at":
        qq = str(data.get("qq") or "").strip()
        name = str(data.get("name") or "")
        if qq != "all" and not qq.isdigit():
            return None, None
        return ({"type": "at", "data": {"qq": qq, "name": name}},
                {"type": "at", "data": {"qq": qq, "name": name}})

    if typ == "reply":
        rid = str(data.get("id") or "").strip()
        if not rid:
            return None, None
        return ({"type": "reply", "data": {"id": rid}},
                {"type": "reply", "data": {"id": rid}})

    if typ == "image":
        # 只有真正的 dataURL / base64:// 才解码；file 可能只是文件名（a.png），
        # 直接当 base64 解会得到垃圾图片（转发/重发时的老 bug）。
        blob = str(data.get("data") or data.get("file") or "")
        raw = _decode_data_url(blob) if blob.startswith(("data:", "base64://")) else None
        if raw:
            url = _save_image(raw)
            sent = {"type": "image",
                    "data": {"file": "base64://" + base64.b64encode(raw).decode("ascii")}}
            stored = {"type": "image",
                      "data": {"url": url, "summary": str(data.get("summary") or "图片")}}
            return sent, stored
        link = str(data.get("url") or data.get("file") or "").strip()
        if link.startswith(("http://", "https://")):
            return ({"type": "image", "data": {"file": link}},
                    {"type": "image", "data": {"url": link,
                                               "summary": str(data.get("summary") or "图片")}})
        return None, None

    return None, None


def _sanitize(segments):
    sent, stored = [], []
    total = 0
    for seg in (segments or []):
        s, k = _sanitize_seg(seg)
        if not s:
            continue
        if s["type"] == "text":
            total += len(s["data"]["text"])
            if total > 8000:
                break
        sent.append(s)
        stored.append(k)
        if len(sent) >= 60:
            break
    return sent, stored


def send(c_type, cid, segments):
    """发送一条消息。返回 ``{ok, item}`` 或 ``{ok:False, error}``。"""
    ctype = "group" if str(c_type) == "group" else "private"
    cid = str(cid or "").strip()
    if not cid:
        return {"ok": False, "error": "缺少会话 ID"}
    sent, stored = _sanitize(segments)
    if not sent:
        return {"ok": False, "error": "消息为空"}

    if ctype == "group":
        action = "send_group_msg"
        params = {"group_id": _num(cid), "message": sent}
    else:
        action = "send_private_msg"
        params = {"user_id": _num(cid), "message": sent}

    data, err = _api(action, params, 25.0)
    if err:
        return {"ok": False, "error": err}

    me = _me()
    mid = ""
    if isinstance(data, dict):
        mid = str(data.get("message_id") or "")
    item = {"kind": "message", "chat_type": ctype, "chat_id": cid,
            "mid": mid, "self": True,
            "sender": {"id": me["id"], "name": me["name"], "role": ""},
            "segs": stored, "text": _render_text(stored)}
    with _lock:
        _append_locked(item)
    return {"ok": True, "item": dict(item)}


def poke(c_type, cid, user_id="", name=""):
    """戳一戳：群聊戳指定成员，私聊戳对方。"""
    ctype = "group" if str(c_type) == "group" else "private"
    cid = str(cid or "").strip()
    target = str(user_id or ("" if ctype == "group" else cid)).strip()
    if not cid or not target:
        return {"ok": False, "error": "缺少戳一戳目标"}
    if str((_me() or {}).get("id") or "") == target:
        return {"ok": False, "error": "不能戳自己（QQ 侧不允许自己戳自己）"}
    if not str((_me() or {}).get("id") or ""):
        return {"ok": False, "error": "QQ 未连接（请先在 NapCat 完成反向 WS 配置）"}

    # NapCat 的 /send_poke：群聊请求体必须是
    #   {"group_id": "...", "user_id": "...", "target_id": "..."}
    # 少 target_id 会直接报失败；私聊则只传 user_id。参数统一用字符串。
    # 其余 group_poke / friend_poke / poke 消息段只是老版本兼容回退。
    seg = [{"type": "poke", "data": {"qq": str(target)}}]
    if ctype == "group":
        tries = [
            ("send_poke", {"group_id": str(cid), "user_id": str(target),
                           "target_id": str(target)}),
            ("group_poke", {"group_id": str(cid), "user_id": str(target),
                            "target_id": str(target)}),
            # NapCat 的 /friend_poke 也接受 group_id：传群号时就是群内戳一戳
            ("friend_poke", {"group_id": str(cid), "user_id": str(target),
                             "target_id": str(target)}),
            ("send_group_msg", {"group_id": str(cid), "message": seg}),
        ]
    else:
        tries = [
            ("send_poke", {"user_id": str(target)}),
            ("friend_poke", {"user_id": str(target)}),
            ("send_private_msg", {"user_id": str(target), "message": seg}),
        ]

    errs = []
    for action, params in tries:
        data, err = _api(action, params, 8.0)
        if not err:
            label = str(name or "").strip() or (
                "群友" if ctype == "group" else "对方")
            item = _append_system(ctype, cid, "你戳了戳 %s" % label,
                                  self_flag=True)
            return {"ok": True, "item": dict(item)}
        errs.append("%s → %s" % (action, err))

    # 「能力不可用」是 QQ 服务端按「登录账号」返回的错误，不是 QQ 客户端版本问题：
    # 机器人号 / 企业号 / 部分登录协议没有 poke 能力。把每一条接口的原始返回都带上，
    # 方便在日志里直接看出是哪一层拒绝的（而不是误以为页面坏了）。
    blob = " | ".join(errs)
    # 失败时顺手带上 NapCat 自己的版本，方便判断是「账号没能力」还是「NapCat 太旧」
    ver = ""
    try:
        vinfo, _ = _api("get_version_info", {}, 5.0)
        if isinstance(vinfo, dict):
            ver = " · NapCat %s" % (vinfo.get("app_version") or vinfo.get("version") or "?")
    except Exception:
        ver = ""
    tag = ("（%s）" % ver.lstrip(" ·")) if ver else ""
    # ① 明确是「能力不可用」：QQ 服务端按登录账号拒绝，和 QQ 客户端版本无关
    if "能力不可用" in blob:
        return {"ok": False, "detail": errs, "error":
                "QQ 服务端返回「能力不可用」%s：这是按当前登录账号判定的，"
                "和 QQ 客户端版本无关；消息能正常发、只有戳一戳不行，"
                "说明这个账号没有 poke 能力（常见于机器人号 / 企业号 / 受限登录协议）。"
                "原始返回：%s" % (tag, errs[0] if errs else "能力不可用")}
    # ② API 本身不被识别：NapCat 版本 / 兼容层不支持这些 action 名
    if any(k in blob for k in ("不支持", "not support", "unsupported",
                               "未知", "unknown", "no such")):
        return {"ok": False, "detail": errs, "error":
                "当前 NapCat 不认识戳一戳接口（已依次尝试 "
                "send_poke / group_poke / friend_poke / poke 消息段）%s。"
                "这不是 QQ 客户端版本问题，需要升级 NapCat 或换支持 poke 的登录协议。"
                "原始返回：%s" % (ver, errs[0] if errs else "不支持")}
    return {"ok": False, "detail": errs,
            "error": "戳一戳失败%s：%s" % (ver, errs[-1] if errs else "未知原因")}


def _find_msg(mid):
    """按消息 id 在本地历史里找那条消息（找不到返回 None）。"""
    mid = str(mid or "")
    with _lock:
        for items in _history.values():
            for it in items:
                if it.get("kind") == "message" and str(it.get("mid") or "") == mid:
                    return it
    return None


def recall(mid, c_type="", cid=""):
    """撤回一条消息。

    权限区分（和 QQ 客户端一致）：
      * 自己发的消息：随时可撤（QQ 侧只有 2 分钟，超时由 QQ 拒绝）；
      * 私人会话：只能撤自己的，别人的撤不了；
      * 群聊别人的消息：只有群主 / 管理员能撤；
      * 管理员撤不了其他管理员 / 群主的消息，群主则不受这个限制。
    """
    mid = str(mid or "").strip()
    if not mid:
        return {"ok": False, "error": "缺少消息 id"}
    ctype = str(c_type or "").strip().lower()
    if ctype not in ("group", "private"):
        ctype = ""
    cid = str(cid or "").strip()

    target = _find_msg(mid)
    if target is not None:
        ctype = ctype or str(target.get("chat_type") or "")
        cid = cid or str(target.get("chat_id") or "")
    else:
        # 本地历史没有（比如刚清过缓存）：至少要知道会话类型才能判权限
        data, err = _api("get_msg", {"message_id": _num(mid)}, 8.0)
        if not err and isinstance(data, dict):
            mt = str(data.get("message_type") or "")
            if mt in ("group", "private"):
                ctype = ctype or mt
                cid = cid or str(data.get("group_id") if mt == "group"
                                 else data.get("user_id") or "")
            sender = data.get("sender") if isinstance(data.get("sender"), dict) else {}
            target = {
                "self": str(data.get("user_id") or "") ==
                        str((_me() or {}).get("id") or ""),
                "sender": {"id": str(sender.get("user_id") or ""),
                           "role": str(sender.get("role") or "")},
            }

    is_self = bool((target or {}).get("self"))
    if target is not None and not is_self:
        sender = (target or {}).get("sender") or {}
        uid = str(sender.get("id") or "")
        if ctype == "private":
            return {"ok": False, "error": "私聊只能撤回自己发送的消息"}
        if ctype == "group" and cid:
            gate = _need_manage(cid)
            if not gate.get("ok"):
                return {"ok": False, "error": "只有群主 / 管理员能撤回他人的消息"}
            role = _member_role(cid, uid, fresh=True) or str(sender.get("role") or "")
            if role == "owner":
                return {"ok": False, "error": "不能撤回群主的消息"}
            if role == "admin" and str(gate.get("role") or "") != "owner":
                return {"ok": False, "error": "管理员不能撤回其他管理员的消息"}

    data, err = _api("delete_msg", {"message_id": _num(mid)}, 8.0)
    if err:
        return {"ok": False, "error": err}
    _mark_recalled(mid, ctype, cid)
    return {"ok": True}


def _mark_recalled(mid, ctype="", cid=""):
    """把本地历史里的消息标成已撤回，并向增量队列发一条 patch。"""
    mid = str(mid or "")
    if not mid:
        return
    with _lock:
        hit = False
        for key, items in _history.items():
            for it in items:
                if str(it.get("mid") or "") == mid:
                    it["recalled"] = True
                    ctype = ctype or str(it.get("chat_type") or "")
                    cid = cid or str(it.get("chat_id") or "")
                    hit = True
        if not hit or not ctype or not cid:
            return
        _append_locked({"kind": "patch", "op": "recall", "mid": mid,
                        "chat_type": ctype, "chat_id": cid,
                        "text": "撤回了一条消息"})


def _forward_content(segs):
    """把 WebQQ 存的消息段转成 NapCat 可发送的消息段（去掉 reply）。"""
    out = []
    for seg in (segs or []):
        sent, _ = _sanitize_seg(seg)
        if sent and sent.get("type") != "reply":
            out.append(sent)
    return out


def _forward_nodes_out(nodes):
    """前端传来的 {name,segs,text} → OneBot node 数组（发送者用自己账号）。"""
    me = _me()
    uin = str(me["id"] or "10000")
    nick = str(me["name"] or "我")
    out = []
    for n in (nodes or [])[:100]:
        if not isinstance(n, dict):
            continue
        segs = _forward_content(n.get("segs") or [])
        if not segs:
            text = str(n.get("text") or "").strip()
            if text:
                segs = [{"type": "text", "data": {"text": text[:3000]}}]
        if not segs:
            continue
        name = str(n.get("name") or nick)[:40] or nick
        out.append({"type": "node", "data": {
            "user_id": uin, "uin": uin,
            "nickname": name, "name": name,
            "content": segs,
        }})
    return out


def forward_send(c_type, cid, nodes, mode="merge"):
    """把选中的消息转发到当前会话：merge = 合并转发，each = 逐条转发。"""
    ctype = "group" if str(c_type) == "group" else "private"
    cid = str(cid or "").strip()
    nodes = nodes if isinstance(nodes, list) else []
    if not cid:
        return {"ok": False, "error": "缺少会话 ID"}
    if not nodes:
        return {"ok": False, "error": "没有选中消息"}
    me = _me()

    if str(mode) == "each":
        action = "send_group_msg" if ctype == "group" else "send_private_msg"
        base = {"group_id": str(cid)} if ctype == "group" else {"user_id": str(cid)}
        sent, errs, items = 0, [], []
        for n in nodes[:100]:
            segs = _forward_content((n or {}).get("segs") or [])
            if not segs:
                text = str((n or {}).get("text") or "").strip()
                if text:
                    segs = [{"type": "text", "data": {"text": text}}]
            if not segs:
                continue
            data, err = _api(action, dict(base, message=segs), 10.0)
            if err:
                errs.append(str(err)[:60])
                continue
            item = {"kind": "message", "chat_type": ctype, "chat_id": cid,
                    "mid": str((data or {}).get("message_id") or ""),
                    "self": True,
                    "sender": {"id": me["id"], "name": me["name"], "role": ""},
                    "segs": segs, "text": _render_text(segs)}
            with _lock:
                _append_locked(item)
            items.append(dict(item))
            sent += 1
        return {"ok": sent > 0, "sent": sent, "items": items,
                "error": ("；".join(errs)[:160] if errs else "")}

    out = _forward_nodes_out(nodes)
    if not out:
        return {"ok": False, "error": "没有可转发的内容"}
    if ctype == "group":
        tries = [("send_group_forward_msg", {"group_id": str(cid)}),
                 ("send_forward_msg", {"message_type": "group", "group_id": str(cid)})]
    else:
        tries = [("send_private_forward_msg", {"user_id": str(cid)}),
                 ("send_forward_msg", {"message_type": "private", "user_id": str(cid)})]
    errs, err = [], ""
    for action, base in tries:
        params = dict(base, messages=out, message=out)
        data, err = _api(action, params, 45.0)
        if not err:
            fid = str((data or {}).get("forward_id") or
                      (data or {}).get("res_id") or "")
            stored_nodes = []
            for n in nodes[:100]:
                if not isinstance(n, dict):
                    continue
                stored_nodes.append({"name": str(n.get("name") or ""),
                                     "time": int(n.get("time") or 0),
                                     "segs": _forward_content(n.get("segs") or []),
                                     "text": str(n.get("text") or "")})
            item = {"kind": "message", "chat_type": ctype, "chat_id": cid,
                    "mid": "", "self": True,
                    "sender": {"id": me["id"], "name": me["name"], "role": ""},
                    "segs": [{"type": "forward", "data": {
                        "id": fid, "nodes": stored_nodes,
                        "count": len(stored_nodes)}}],
                    "text": "[聊天记录]"}
            with _lock:
                _append_locked(item)
            return {"ok": True, "item": dict(item)}
        errs.append("%s → %s" % (action, str(err)[:80]))
    return {"ok": False, "error": "；".join(errs)[:180]}


# ---------------------------------------------------------------------------
# 群管理：禁言 / 踢人 / 群公告
# ---------------------------------------------------------------------------
ROLE_TTL = 60                             # 自己在群里的角色缓存时间（秒）
_role_cache = {}                          # gid -> {"ts", "role"}


def group_role(gid, force=False):
    """自己在群里的角色：owner / admin / member（决定能否禁言、踢人、发公告）。

    ``force=True``（前端点开群管理 / 收到管理员变更通知时）跳过缓存直接向 QQ 单查，
    否则最多用 60 秒内的缓存。**不再优先吃群成员列表缓存** —— 那份数据最长可能旧
    5 分钟，刚被设成管理员（或刚被撤）时会让人误以为身份没更新。
    """
    gid = str(gid or "").strip()
    me = _me() or {}
    if not gid:
        return {"ok": False, "error": "缺少群号"}
    if not me.get("id"):
        return {"ok": False, "error": "QQ 未连接（请先在 NapCat 完成反向 WS 配置）"}
    now = time.time()
    with _lock:
        cached = _role_cache.get(gid)
        mm = _members.get(gid)
    role = ""
    if not force and cached and now - cached["ts"] < ROLE_TTL:
        role = cached["role"]
    if not role:
        data, err = _api("get_group_member_info", {
            "group_id": _num(gid), "user_id": _num(me["id"]),
            "no_cache": True}, 10.0)
        if not err:
            role = str((data or {}).get("role") or "member")
        elif mm:
            # 单查失败才退回成员列表缓存，至少还能显示上次的状态
            for it in mm["items"]:
                if it["id"] == me["id"]:
                    role = str(it.get("role") or "")
                    break
            if not role:
                return {"ok": False, "error": err}
        else:
            return {"ok": False, "error": err}
    with _lock:
        _role_cache[gid] = {"ts": now, "role": role}
    return {"ok": True, "gid": gid, "role": role,
            "can_manage": role in ("owner", "admin"),
            "label": {"owner": "群主", "admin": "管理员", "member": "成员"}.get(role, role)}


def _need_manage(gid):
    """禁言 / 踢人等操作前先确认自己是管理员，避免甩给 QQ 侧报错。"""
    r = group_role(gid)
    if not r.get("ok"):
        return r
    if not r.get("can_manage"):
        return {"ok": False, "error": "你不是该群管理员（当前身份：%s）" % r.get("label")}
    return {"ok": True, "role": r.get("role")}


def _member_role(gid, uid, fresh=False):
    """取成员在群里的真实身份（owner / admin / member），取不到返回空串。

    禁言、踢人、撤回都要按**对方的身份**区分：管理员动不了管理员和群主。
    优先走成员缓存，``fresh=True``（或被操作对象）时单查一次 ``no_cache``。
    """
    gid = str(gid or "").strip()
    uid = str(uid or "").strip()
    if not gid or not uid:
        return ""
    if uid == str((_me() or {}).get("id") or ""):
        r = group_role(gid)
        return str(r.get("role") or "") if r.get("ok") else ""
    if not fresh:
        with _lock:
            mm = _members.get(gid)
        if mm:
            for it in mm["items"]:
                if str(it.get("id")) == uid:
                    return str(it.get("role") or "member")
    data, err = _api("get_group_member_info", {
        "group_id": _num(gid), "user_id": _num(uid), "no_cache": True}, 10.0)
    if err:
        return ""
    return str((data or {}).get("role") or "member")


def _can_act_on(gid, uid, action="操作"):
    """确认「我能不能对这个成员执行管理操作」，返回 ``{ok, role, target_role}``。"""
    gate = _need_manage(gid)
    if not gate.get("ok"):
        return gate
    my_role = str(gate.get("role") or "")
    target = _member_role(gid, uid, fresh=True)
    if not target:
        return {"ok": False, "error": "读取该成员身份失败，请稍后重试"}
    if target == "owner":
        return {"ok": False, "error": "不能%s群主" % action}
    if target == "admin" and my_role != "owner":
        return {"ok": False, "error": "管理员不能%s其他管理员（只有群主可以）" % action}
    return {"ok": True, "role": my_role, "target_role": target}


def ban_member(gid, uid, duration=600):
    """禁言成员；duration 秒，0 表示解除禁言。"""
    gid = str(gid or "").strip()
    uid = str(uid or "").strip()
    if not gid or not uid:
        return {"ok": False, "error": "缺少群号或成员 QQ"}
    if uid == str((_me() or {}).get("id") or ""):
        return {"ok": False, "error": "不能禁言自己"}
    gate = _can_act_on(gid, uid, "禁言")
    if not gate.get("ok"):
        return gate
    try:
        sec = max(0, int(duration))
    except (TypeError, ValueError):
        sec = 600
    data, err = _api("set_group_ban", {
        "group_id": _num(gid), "user_id": _num(uid), "duration": sec}, 8.0)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "duration": sec,
            "text": "已解除禁言" if sec <= 0 else "已禁言 %s" % _dur_text(sec)}


def kick_member(gid, uid, reject=False):
    """把成员移出群聊；reject=True 时同时拒绝其再次申请。"""
    gid = str(gid or "").strip()
    uid = str(uid or "").strip()
    if not gid or not uid:
        return {"ok": False, "error": "缺少群号或成员 QQ"}
    if uid == str((_me() or {}).get("id") or ""):
        return {"ok": False, "error": "不能把自己踢出群"}
    gate = _can_act_on(gid, uid, "移出")
    if not gate.get("ok"):
        return gate
    data, err = _api("set_group_kick", {
        "group_id": _num(gid), "user_id": _num(uid),
        "reject_add_request": bool(reject)}, 10.0)
    if err:
        return {"ok": False, "error": err}
    with _lock:
        _members.pop(gid, None)
    _bump_contacts(gid)
    return {"ok": True}


def _dur_text(sec):
    sec = int(sec or 0)
    if sec >= 86400 and sec % 86400 == 0:
        return "%d 天" % (sec // 86400)
    if sec >= 3600 and sec % 3600 == 0:
        return "%d 小时" % (sec // 3600)
    if sec >= 60 and sec % 60 == 0:
        return "%d 分钟" % (sec // 60)
    return "%d 秒" % sec


def group_notices(gid):
    """读群公告（NapCat 两个版本分别叫 _get_group_notice / get_group_notice）。"""
    gid = str(gid or "").strip()
    if not gid:
        return {"ok": False, "error": "缺少群号"}
    data, err = None, ""
    for action in ("_get_group_notice", "get_group_notice"):
        data, err = _api(action, {"group_id": _num(gid)}, 12.0)
        if not err:
            break
    if err:
        return {"ok": False, "error": err}
    items = []
    for n in (data if isinstance(data, list) else []):
        if not isinstance(n, dict):
            continue
        msg = n.get("message")
        if isinstance(msg, dict):
            text = str(msg.get("text") or "")
            images = msg.get("images") or msg.get("image") or []
        else:
            text = str(msg or n.get("content") or "")
            images = n.get("images") or []
        try:
            ntype = int(n.get("type") or n.get("notice_type") or 1)
        except (TypeError, ValueError):
            ntype = 1
        items.append({
            "id": str(n.get("notice_id") or n.get("id") or ""),
            "text": text,
            "time": int(n.get("publish_time") or 0),
            "sender": str(n.get("sender_id") or ""),
            "images": len(images) if isinstance(images, list) else 0,
            "pinned": bool(n.get("pinned") or n.get("is_pinned")),
            # QQ 公告类型：1 = 普通公告，20 = 新人公告（只对进群新成员展示）
            "type": ntype,
        })
    items.sort(key=lambda x: x["time"], reverse=True)
    return {"ok": True, "items": items}


def publish_notice(gid, content, image="", pinned=False, notice_type=1):
    """发布 / 编辑群公告（QQ 侧没有「编辑」，重发即覆盖旧公告）。

    image 支持 dataURL / base64 / http 图片地址；``type`` 为 1（普通公告）或
    20（新人公告，只发送给新成员），``pinned`` 控制是否置顶。
    """
    gid = str(gid or "").strip()
    text = str(content or "").strip()
    image = str(image or "").strip()
    if not gid:
        return {"ok": False, "error": "缺少群号"}
    if not text and not image:
        return {"ok": False, "error": "公告内容不能为空"}
    gate = _need_manage(gid)
    if not gate.get("ok"):
        return gate

    img = ""
    if image:
        raw = _decode_data_url(image) if image.startswith(("data:", "base64://")) else None
        if raw:
            if not _looks_image(raw):
                return {"ok": False, "error": "公告配图不是有效的图片文件"}
            img = _save_image_path(raw)
            if not img:
                return {"ok": False, "error": "公告配图保存失败"}
        elif image.startswith(("http://", "https://")):
            img = image
        else:
            return {"ok": False, "error": "公告配图必须是图片文件"}

    try:
        ntype = int(notice_type or 1)
    except (TypeError, ValueError):
        ntype = 1
    base = {"group_id": _num(gid), "content": text}
    if img:
        base["image"] = img
    # 先按 NapCat 完整参数发；旧版 / go-cqhttp 只认 content(+image)，逐级回退
    # NapCat 的 pinned 只收 0/1（数字或字符串），不能传布尔值
    full = dict(base, pinned=1 if pinned else 0, type=ntype)
    err = ""
    for action, params in (("send_group_notice", full),
                           ("_send_group_notice", full),
                           ("send_group_notice", base),
                           ("_send_group_notice", base)):
        data, err = _api(action, params, 12.0)
        if not err:
            return {"ok": True, "pinned": bool(pinned), "type": ntype,
                    "has_image": bool(img)}
    return {"ok": False, "error": err}


# ---------------------------------------------------------------------------
# 同步 QQ 侧历史消息
# ---------------------------------------------------------------------------
def _history_api(c_type, cid):
    """返回读取历史用的 OneBot 接口与基础参数。"""
    if c_type == "group":
        return "get_group_msg_history", {"group_id": _num(cid)}
    return "get_friend_msg_history", {"user_id": _num(cid)}


def _convert_history(raw, c_type, cid, me=None):
    """把 get_*_msg_history 返回的一条消息转成 WebQQ 条目。"""
    if not isinstance(raw, dict):
        return None
    segs = _event_segs(raw)
    if not segs:
        return None
    me = me or _me()
    sender = raw.get("sender")
    sender = sender if isinstance(sender, dict) else {}
    uid = str(sender.get("user_id") or raw.get("user_id") or "")
    is_self = bool(me["id"] and uid == me["id"])
    if is_self:
        who = {"id": uid or me["id"], "name": me["name"] or "我",
               "role": "owner" if c_type == "group" else ""}
    else:
        who = {"id": uid,
               "name": str(sender.get("card") or sender.get("nickname") or uid),
               "role": str(sender.get("role") or "")}
    mid = str(raw.get("message_id") or raw.get("message_seq") or "")
    return {"kind": "message", "chat_type": c_type, "chat_id": cid,
            "mid": mid, "time": int(raw.get("time") or 0) or int(time.time()),
            "self": bool(is_self), "sender": who, "segs": segs,
            "text": _render_text(segs)}


def _merge_remote(key, converted):
    """把远端消息并进本地历史（按 mid 去重、按时间排序），返回新增条数。"""
    global _seq
    if not converted:
        return 0
    added = 0
    with _lock:
        lst = _history.setdefault(key, [])
        seen = {str(it.get("mid") or "") for it in lst if it.get("kind") == "message"}
        for it in converted:
            mid = str(it.get("mid") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            lst.append(it)
            added += 1
        if not added:
            return 0
        # 本地实时消息与 QQ 历史混排：统一按时间排序，再补上全局递增 seq
        lst.sort(key=lambda x: (int(x.get("time") or 0), str(x.get("mid") or "")))
        if len(lst) > MAX_PER_CHAT:
            del lst[:len(lst) - MAX_PER_CHAT]
        for it in lst:
            if not it.get("seq"):
                _seq += 1
                it["seq"] = _seq
        _dirty.set()
    return added


def sync_history(c_type, cid, count=SYNC_COUNT, before="", force=False):
    """从 QQ 侧拉取最近历史并合并到本地，返回 ``(新增条数, 错误)``。

    before 传入某条消息的 message_seq 时可继续往前翻页。同一会话默认 20 秒内
    不重复请求（force=True 可强制刷新）。
    """
    if c_type not in ("private", "group") or not cid:
        return 0, "缺少会话"
    key = _chat_key(c_type, cid)
    now = time.time()
    if not force:
        with _lock:
            last = _sync_ts.get(key) or 0
        if now - last < SYNC_TTL:
            return 0, ""

    action, params = _history_api(c_type, cid)
    params = dict(params)
    try:
        params["count"] = max(1, min(int(count), 100))
    except (TypeError, ValueError):
        params["count"] = SYNC_COUNT
    if before:
        params["message_seq"] = _num(before)
    data, err = _api(action, params, 15.0)
    if err:
        return 0, err

    msgs = data
    if isinstance(data, dict):
        msgs = data.get("messages")
        if msgs is None:
            msgs = data.get("message")
    if not isinstance(msgs, list):
        return 0, "返回格式不支持"

    me = _me()
    converted = [x for x in (_convert_history(m, c_type, cid, me) for m in msgs) if x]
    added = _merge_remote(key, converted)
    with _lock:
        _sync_ts[key] = now
    return added, ""


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def _item_out(it):
    """对外输出时给图片 / 合并转发补上消息 id（旧历史也能按 id 刷新）。"""
    out = dict(it)
    segs = it.get("segs")
    mid = str(it.get("mid") or "")
    if isinstance(segs, list) and mid:
        copy = []
        for s in segs:
            if isinstance(s, dict) and s.get("type") in (
                    "image", "forward", "video", "record", "file"):
                d = dict(s.get("data") or {})
                d.setdefault("mid", mid)
                s = dict(s, data=d)
            copy.append(s)
        out["segs"] = copy
    return out


def history(c_type, cid, limit=80, sync=False, force=False):
    try:
        n = max(1, min(int(limit), MAX_PER_CHAT))
    except (TypeError, ValueError):
        n = 80
    key = _chat_key(c_type, cid)
    synced, err = 0, ""
    if sync:
        try:
            synced, err = sync_history(c_type, cid, force=force)
        except Exception as e:
            err = str(e)
    with _lock:
        items = [_item_out(it) for it in (_history.get(key) or [])[-n:]]
        return {"ok": True, "items": items, "seq": _seq, "key": key,
                "synced": synced, "sync_error": err}


def poll(since=0, limit=400):
    try:
        since = int(since or 0)
    except (TypeError, ValueError):
        since = 0
    try:
        n = max(1, min(int(limit), FEED_MAX))
    except (TypeError, ValueError):
        n = 400
    with _lock:
        items = [_item_out(it) for it in _feed if int(it.get("seq") or 0) > since]
        if len(items) > n:
            items = items[-n:]
        return {"ok": True, "items": items, "seq": _seq}


# ---------------------------------------------------------------------------
# 通知中心：拉取 / 同意好友 / 同意入群
# ---------------------------------------------------------------------------
def notices(since=0):
    try:
        since = int(since or 0)
    except (TypeError, ValueError):
        since = 0
    with _lock:
        items = [dict(it) for it in _notices if int(it.get("id") or 0) > since]
        pending = sum(1 for it in _notices
                      if it.get("kind") in ("friend_request", "group_request")
                      and not it.get("handled"))
        return {"ok": True, "items": items, "seq": _notice_id, "pending": pending}


def handle_request(kind, flag, approve, reason=""):
    """同意 / 拒绝好友申请或入群申请。"""
    flag = str(flag or "").strip()
    if not flag:
        return {"ok": False, "error": "缺少 flag"}
    with _lock:
        target = next((it for it in _notices if it.get("flag") == flag), None)
    if target is None:
        return {"ok": False, "error": "申请已失效，请刷新通知"}

    approved = bool(approve)
    if str(kind) == "group" or target.get("kind") == "group_request":
        action = "set_group_add_request"
        params = {"flag": flag, "sub_type": target.get("sub") or "add",
                  "approve": approved}
        if not approved and reason:
            params["reason"] = str(reason)[:200]
    else:
        action = "set_friend_add_request"
        params = {"flag": flag, "approve": approved}

    data, err = _api(action, params, 10.0)
    if err:
        return {"ok": False, "error": err}
    _patch_notice(target.get("id"), handled=1, approved=approved)
    _bump_contacts(target.get("gid") or "")
    return {"ok": True, "approved": approved}


# ---------------------------------------------------------------------------
# QQ 官方表情
# ---------------------------------------------------------------------------
# 新版 QQ（QQNT）的表情 id 和 qzone 图床的编号不是同一套：
# 老代码拿 ``e{id}.gif`` 直接拼地址，144 之后的表情就会张冠李戴
# （例如 id 264 是「捂脸」，qzone 的 e264.gif 却是另一张脸，正确图号是 10264）。
# core/qq_faces.json 由 QQNT 官方表情定义生成（id → 名称 / qzone 图号 / 高清资源），
# 前端只认 id，图片统一走 /api/webqq/face 取，本地缓存一次之后就不再请求外网。
FACE_DIR = os.path.join(_BASE_DIR, "faces")
FACE_INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "qq_faces.json")
#: koishijs/QFace 的 QQNT 表情资源（GitHub 直连常被墙，优先走代理镜像）
QFACE_RAW = ("https://gh-proxy.com/https://raw.githubusercontent.com/"
             "koishijs/QFace/master/public/",
             "https://raw.githubusercontent.com/koishijs/QFace/master/public/")

_face_lock = threading.Lock()
_face_items = None
_face_by_id = {}


def _faces():
    """读取表情索引（只读一次，进程内复用）。"""
    global _face_items, _face_by_id
    with _face_lock:
        if _face_items is not None:
            return _face_items
        items = []
        try:
            with open(FACE_INDEX_PATH, "r", encoding="utf-8") as f:
                items = (json.load(f) or {}).get("items") or []
        except Exception as e:
            print("[webqq] 表情索引读取失败: %s" % e, flush=True)
        _face_items = [it for it in items if isinstance(it, dict)]
        _face_by_id = {str(it.get("id")): it for it in _face_items}
        try:
            os.makedirs(FACE_DIR, exist_ok=True)
        except OSError:
            pass
        return _face_items


def face_list():
    """表情面板数据：[{id, name}]"""
    return [{"id": it.get("id"), "name": it.get("name") or ""}
            for it in _faces()]


def face_name(fid):
    _faces()
    return str((_face_by_id.get(str(fid)) or {}).get("name") or "")


def _face_sources(it):
    """按优先级给出候选图源 ``[(url, timeout)]``。

    qzone 官方 CDN 最快，但只有一部分表情有对应图号；其余走 QFace 的高清资源
    （GitHub 直连在国内基本不通，所以默认先用代理镜像）。
    """
    q = str(it.get("q") or "")
    a = str(it.get("a") or "")
    out = []
    if q and it.get("qt"):
        out.append((q, 10))
    if a:
        out.append((QFACE_RAW[0] + a, 12))
    if q and not it.get("qt"):
        out.append((q, 10))
    if a:
        out.append((QFACE_RAW[1] + a, 6))
    return out


def face_path(name):
    """表情缓存文件名 → 绝对路径（只允许 ``<数字>.<扩展名>``）。"""
    name = str(name or "")
    if not re.fullmatch(r"\d{1,4}\.(png|gif|webp|jpg|jpeg|bmp)", name):
        return ""
    path = os.path.join(FACE_DIR, name)
    return path if os.path.isfile(path) else ""


def face_file(fid):
    """取表情图，返回 ``(缓存文件名, 错误)``；第一次会下载到 cache/webqq/faces。"""
    fid = str(fid or "").strip()
    if not fid.isdigit():
        return "", "表情 id 不合法"
    _faces()
    it = _face_by_id.get(fid)
    if it is None:
        return "", "未知的表情"
    for ext in _REMOTE_EXTS:
        name = fid + "." + ext
        if os.path.isfile(os.path.join(FACE_DIR, name)):
            return name, ""

    import requests
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    err = "下载失败"
    for u, tmo in _face_sources(it):
        for attempt in range(2):
            try:
                resp = requests.get(u, timeout=tmo, headers={
                    "User-Agent": ua, "Referer": ""})
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, e)
                continue
            if resp.status_code != 200 or not resp.content:
                err = "HTTP %s" % resp.status_code
                continue
            raw = resp.content
            if len(raw) > 4 * 1024 * 1024 or not _looks_image(raw):
                err = "拿到的不是图片"
                continue
            _, ext = _sniff_image(raw)
            name = fid + "." + ext
            tmp = os.path.join(FACE_DIR, name + ".tmp")
            try:
                with open(tmp, "wb") as f:
                    f.write(raw)
                os.replace(tmp, os.path.join(FACE_DIR, name))
            except OSError as e:
                err = "写入失败：%s" % e
                continue
            return name, ""
    return "", err

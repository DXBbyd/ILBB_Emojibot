# -*- coding: utf-8 -*-
"""ILBB 插件系统 —— plugins/ 下「一个文件夹 = 一个插件」。

目录约定::

    plugins/
      hello_world/
        plugin.json        插件清单（id / name / desc / entry / web / config ...）
        main.py            入口：必须提供 setup(ctx)，可选 teardown()

提供的能力：

  * **以文件夹为单位安装**：把文件夹丢进 plugins/ 即被识别为插件，
    增删文件夹在热重载开启时会自动生效，无需重启主服务。
  * **Web 改配置**：插件在 plugin.json 的 config 里声明自己需要的配置项，
    ILBB 自动生成表单；类型为 friend / group / group_member 的字段
    自动换成 ILBB 的下拉栏，选项来自 NapCat 当前登录 QQ 的好友 / 群聊 /
    群成员列表（插件侧只需写一个类型，不必自己调接口）。
  * **热重载**：轮询插件目录的文件 mtime，改代码 / 加删插件自动重载。
  * **热禁用**：单个插件可即时启用 / 停用，不必重启主服务。
  * **独立插件页面**：plugin.json 中写 ``"web": true`` 时，ILBB 会去探测
    插件自己起的 HTTP 服务（端口取 manifest 的 web_port，留空则从
    PLUGIN_WEB_PORT_BASE 起依次分配），并用内嵌网页显示，
    IP 取浏览器当前访问的主机名、端口自动匹配。

插件入口拿到的 ``ctx`` 见 :class:`PluginContext`。
"""

import importlib.util
import json
import os
import re
import sys
import threading
import time
import traceback
from urllib import error as urlerror
from urllib import request as urlrequest

import config
import ws_server

MANIFEST_NAME = "plugin.json"
DEFAULT_ENTRY = "main.py"
# 参与热重载指纹计算的文件后缀。
WATCH_SUFFIXES = (".py", ".json", ".html", ".js", ".css", ".txt", ".md", ".svg")
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]{0,31}$")
# 允许的配置项类型：friend / group / group_member 由 ILBB 提供下拉栏。
FIELD_TYPES = ("text", "textarea", "int", "bool", "enum",
               "friend", "group", "group_member")

_lock = threading.RLock()
_plugins = {}                 # id -> Plugin
_config = {"version": 1, "plugins": {}}
_commands = {}                # 触发词(小写) -> (plugin_id, fn)
_dispatcher_installed = False
_watcher_thread = None
_watcher_stop = threading.Event()
_last_signature = {}          # id -> 指纹
_last_scan = {}               # id -> (folder, manifest, manifest_path)
_bad = {}                     # 目录名 -> {folder, error}（装错了的插件文件夹，Web 上提示）
_started = False


# ----------------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------------
def _log(msg, color=None):
    try:
        ws_server._log("插件", msg, color or ws_server.C.MAGENTA)
    except Exception:
        print("[插件] " + str(msg), flush=True)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _atomic_write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    os.replace(tmp, path)


def _norm_abs(p):
    return os.path.normpath(os.path.abspath(p))


def plugin_root():
    """插件根目录（绝对路径，不存在时自动创建）。"""
    root = getattr(config, "PLUGIN_DIR", None) or "plugins"
    if not os.path.isabs(root):
        root = os.path.join(config.ROOT, root)
    root = _norm_abs(root)
    try:
        os.makedirs(root, exist_ok=True)
    except Exception:
        pass
    return root


def config_path():
    p = getattr(config, "PLUGIN_CONFIG_PATH", None) or "plugins_config.json"
    if not os.path.isabs(p):
        p = os.path.join(config.ROOT, p)
    return _norm_abs(p)


# ----------------------------------------------------------------------------
# 插件配置存储（plugins_config.json）
# ----------------------------------------------------------------------------
def _load_state():
    global _config
    data = _safe_read_json(config_path())
    if not isinstance(data, dict):
        data = {}
    plugs = data.get("plugins")
    _config = {"version": 1, "plugins": plugs if isinstance(plugs, dict) else {}}


def _save_state():
    try:
        _atomic_write_json(config_path(), _config)
        return True
    except Exception:
        traceback.print_exc()
        return False


def _state_of(pid):
    p = _config["plugins"].get(pid)
    if not isinstance(p, dict):
        p = {}
        _config["plugins"][pid] = p
    if not isinstance(p.get("config"), dict):
        p["config"] = {}
    return p


def _alloc_port(used):
    base = int(getattr(config, "PLUGIN_WEB_PORT_BASE", 7000) or 7000)
    port = base
    while port in used and port < 65535:
        port += 1
    used.add(port)
    return port


# ----------------------------------------------------------------------------
# 清单解析
# ----------------------------------------------------------------------------
def _normalize_fields(raw):
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        ftype = str(item.get("type") or "text").strip().lower()
        if ftype not in FIELD_TYPES:
            ftype = "text"
        opts = []
        for o in (item.get("options") or []):
            if isinstance(o, dict):
                opts.append({"value": str(o.get("value", "")), "label": str(o.get("label", ""))})
            else:
                opts.append({"value": str(o), "label": str(o)})
        out.append({
            "key": key,
            "label": str(item.get("label") or key),
            "type": ftype,
            "hint": str(item.get("hint") or ""),
            "placeholder": str(item.get("placeholder") or ""),
            "multi": bool(item.get("multi")),
            "options": opts,
            "default": item.get("default", _default_for(ftype, bool(item.get("multi")))),
        })
    return out


def _default_for(ftype, multi):
    if ftype in ("friend", "group", "group_member"):
        return [] if multi else ""
    if ftype == "bool":
        return False
    if ftype == "int":
        return 0
    return ""


def _read_manifest(folder):
    """读取插件清单；返回 (manifest, error)。"""
    mpath = os.path.join(folder, MANIFEST_NAME)
    if not os.path.isfile(mpath):
        return None, "缺少 %s" % MANIFEST_NAME
    data = _safe_read_json(mpath)
    if data is None:
        return None, "%s 不是合法的 JSON 对象" % MANIFEST_NAME
    folder_name = os.path.basename(folder)
    pid = str(data.get("id") or folder_name).strip() or folder_name
    if not _ID_RE.match(pid):
        return None, "id 不合法（只允许字母/数字/下划线/连字符）：%s" % pid
    entry = str(data.get("entry") or DEFAULT_ENTRY).strip() or DEFAULT_ENTRY
    if os.path.isabs(entry) or ".." in entry.replace("\\", "/").split("/"):
        return None, "entry 不允许使用绝对路径或上级目录"
    entry_path = os.path.join(folder, entry.replace("/", os.sep))
    if not os.path.isfile(entry_path):
        return None, "找不到入口文件 %s" % entry
    manifest = {
        "id": pid,
        "name": str(data.get("name") or pid),
        "version": str(data.get("version") or "0.0.0"),
        "author": str(data.get("author") or ""),
        "desc": str(data.get("desc") or ""),
        "entry": entry,
        "entry_path": entry_path,
        "web": bool(data.get("web")),
        "web_title": str(data.get("web_title") or data.get("name") or pid),
        "web_path": str(data.get("web_path") or "/"),
        "web_port": int(data.get("web_port") or 0),
        "enabled_by_default": bool(data.get("enabled", True)),
        "config": _normalize_fields(data.get("config")),
    }
    if manifest["web_port"] and not (1024 <= manifest["web_port"] <= 65535):
        manifest["web_port"] = 0
    return manifest, ""


# ----------------------------------------------------------------------------
# 插件运行上下文
# ----------------------------------------------------------------------------
class PluginContext:
    """交给插件 setup(ctx) 的能力集合。

    插件可用：
      ctx.id / ctx.name / ctx.version / ctx.folder / ctx.web_port
      ctx.cfg(key, default) / ctx.set_cfg(key, value)      读写自己的配置
      ctx.on_event(fn)                                     监听 OneBot 事件
      ctx.on_command(["echo"], fn)                         注册指令
      ctx.log(msg)
      ctx.send_group(gid, message) / ctx.send_private(uid, message)
      ctx.send_text(...) / ctx.send_image(bytes)（按事件上下文回复）
      ctx.call_api(action, params)                         直接调用 OneBot 接口
      ctx.friends() / ctx.groups() / ctx.group_members(gid)
      ctx.self_account()
      ctx.web_url()                                        自己的 Web 地址
    """

    def __init__(self, plugin):
        self._plugin = plugin

    # ---- 基础信息 ----
    @property
    def id(self):
        return self._plugin.id

    @property
    def name(self):
        return self._plugin.name

    @property
    def version(self):
        return self._plugin.manifest.get("version", "0.0.0")

    @property
    def folder(self):
        return self._plugin.folder

    @property
    def web_port(self):
        return self._plugin.web_port

    def log(self, msg):
        _log("[%s] %s" % (self.id, msg), ws_server.C.MAGENTA)

    # ---- 配置 ----
    def cfg(self, key=None, default=None):
        vals = self._plugin.values
        if key is None:
            return dict(vals)
        return vals.get(key, default)

    def set_cfg(self, key, value):
        p = _state_of(self.id)
        p["config"][str(key)] = value
        self._plugin.values[str(key)] = value
        _save_state()
        return True

    # ---- 事件 / 指令 ----
    def on_event(self, fn):
        if callable(fn):
            self._plugin.event_handlers.append(fn)

    def on_command(self, triggers, fn):
        if isinstance(triggers, str):
            triggers = [triggers]
        for t in (triggers or []):
            key = str(t).strip().lower()
            if key and callable(fn):
                _commands[key] = (self.id, fn)
        return True

    def log_event(self, ev):
        pass

    # ---- 收发 ----
    def call_api(self, action, params=None, timeout=6.0):
        return ws_server.call_api(action, params or {}, timeout=timeout)

    def send_group(self, group_id, message):
        return ws_server.call_api("send_group_msg",
                                  {"group_id": group_id, "message": message})

    def send_private(self, user_id, message):
        return ws_server.call_api("send_private_msg",
                                  {"user_id": user_id, "message": message})

    def send_text(self, ctx, text):
        if not text:
            return False
        segs = []
        if (ctx or {}).get("mtype") == "group" and (ctx or {}).get("uid"):
            segs.append({"type": "at", "data": {"qq": str(ctx["uid"])}})
            segs.append({"type": "text", "data": {"text": " "}})
        segs.append({"type": "text", "data": {"text": str(text)}})
        return self._send_to(ctx, segs)

    def send_image(self, ctx, data):
        if not data:
            return False
        import base64 as _b64
        b64 = _b64.b64encode(data).decode("ascii")
        return self._send_to(ctx, [{"type": "image", "data": {"file": "base64://" + b64}}])

    def _send_to(self, ctx, segments):
        ctx = ctx or {}
        if ctx.get("mtype") == "group" and ctx.get("gid"):
            return bool((self.send_group(ctx["gid"], segments) or {}).get("ok"))
        if ctx.get("uid"):
            return bool((self.send_private(ctx["uid"], segments) or {}).get("ok"))
        return False

    # ---- 数据源（插件不写接口也能拿名单） ----
    @staticmethod
    def _data(ret):
        if not isinstance(ret, dict) or not ret.get("ok"):
            return []
        resp = ret.get("response")
        if not isinstance(resp, dict):
            return []
        data = resp.get("data")
        return data if isinstance(data, list) else []

    def friends(self):
        return [{"user_id": str(f.get("user_id", "")),
                 "nickname": f.get("nickname") or "",
                 "remark": f.get("remark") or ""}
                for f in self._data(ws_server.call_api("get_friend_list", {}))]

    def groups(self):
        return [{"group_id": str(g.get("group_id", "")),
                 "group_name": g.get("group_name") or "",
                 "member_count": g.get("member_count") or 0}
                for g in self._data(ws_server.call_api("get_group_list", {}))]

    def group_members(self, group_id):
        return [{"user_id": str(m.get("user_id", "")),
                 "nickname": m.get("nickname") or "",
                 "card": m.get("card") or "",
                 "role": m.get("role") or ""}
                for m in self._data(ws_server.call_api(
                    "get_group_member_list", {"group_id": group_id}))]

    def self_account(self):
        return ws_server.self_account()

    # ---- 自己的 Web ----
    def web_url(self, host="127.0.0.1"):
        if not self._plugin.manifest.get("web") or not self.web_port:
            return ""
        scheme = getattr(config, "PLUGIN_WEB_SCHEME", "http") or "http"
        path = self._plugin.manifest.get("web_path") or "/"
        if not path.startswith("/"):
            path = "/" + path
        return "%s://%s:%d%s" % (scheme, host, self.web_port, path)


class Plugin:
    def __init__(self, pid, folder, manifest):
        self.id = pid
        self.folder = folder
        self.manifest = manifest
        self.name = manifest.get("name") or pid
        self.enabled = True
        self.loaded = False
        self.error = ""
        self.module = None
        self.event_handlers = []
        self.values = {}
        self.web_port = 0
        self.loaded_at = 0.0
        self.reload_count = 0

    def public(self):
        m = self.manifest
        return {
            "id": self.id,
            "name": self.name,
            "version": m.get("version", "0.0.0"),
            "author": m.get("author", ""),
            "desc": m.get("desc", ""),
            "folder": self.folder,
            "rel_folder": os.path.relpath(self.folder, plugin_root()),
            "enabled": bool(self.enabled),
            "loaded": bool(self.loaded),
            "error": self.error,
            "has_web": bool(m.get("web")),
            "web_port": self.web_port,
            "web_title": m.get("web_title", self.name),
            "commands": sorted([k for k, v in _commands.items() if v[0] == self.id]),
            "fields": m.get("config", []),
            "values": dict(self.values),
            "loaded_at": self.loaded_at,
            "reload_count": self.reload_count,
        }


# ----------------------------------------------------------------------------
# 配置值归一化
# ----------------------------------------------------------------------------
def _normalize_values(manifest, raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for f in manifest.get("config", []):
        key = f["key"]
        ftype = f["type"]
        val = raw.get(key, f.get("default"))
        if ftype in ("friend", "group", "group_member"):
            if f.get("multi"):
                if isinstance(val, str):
                    val = [s for s in re.split(r"[,\s]+", val) if s]
                if not isinstance(val, list):
                    val = []
                val = [str(v) for v in val if str(v).strip()]
            else:
                val = "" if val is None else str(val)
        elif ftype == "bool":
            val = bool(val)
        elif ftype == "int":
            try:
                val = int(val)
            except (TypeError, ValueError):
                val = int(f.get("default") or 0)
        elif ftype == "enum":
            allowed = [o["value"] for o in f.get("options", [])]
            val = str(val if val is not None else "")
            if allowed and val not in allowed:
                val = f.get("default") if f.get("default") in allowed else allowed[0]
        else:
            val = "" if val is None else str(val)
        out[key] = val
    return out


# ----------------------------------------------------------------------------
# 载入 / 卸载
# ----------------------------------------------------------------------------
def _purge_modules(prefix):
    for name in [n for n in list(sys.modules) if n == prefix or n.startswith(prefix + ".")]:
        sys.modules.pop(name, None)


def _import_module(path, mod_name):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("无法为 %s 建立模块规格" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _unload(plugin):
    """卸载插件的运行实例（不动状态文件）。"""
    for fn in plugin.event_handlers:
        pass
    plugin.event_handlers = []
    for key in [k for k, v in _commands.items() if v[0] == plugin.id]:
        _commands.pop(key, None)
    mod = plugin.module
    if mod is not None:
        fn = getattr(mod, "teardown", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                _log("[%s] teardown 异常\n%s" % (plugin.id, traceback.format_exc()),
                     ws_server.C.YELLOW)
    _purge_modules("ilbb_plugin_%s" % plugin.id)
    plugin.module = None
    plugin.loaded = False


def _load(plugin):
    """载入单个插件并调用 setup(ctx)。"""
    if not plugin.enabled:
        plugin.loaded = False
        return False
    manifest = plugin.manifest
    mod_name = "ilbb_plugin_%s" % plugin.id
    _purge_modules(mod_name)
    try:
        mod = _import_module(manifest["entry_path"], mod_name)
    except Exception as e:
        plugin.error = "导入失败：%s" % e
        plugin.loaded = False
        _log("[%s] 导入失败：%s" % (plugin.id, e), ws_server.C.RED)
        traceback.print_exc()
        return False
    plugin.module = mod
    setup = getattr(mod, "setup", None)
    if not callable(setup):
        plugin.error = "入口文件没有 setup(ctx) 函数"
        _log("[%s] %s" % (plugin.id, plugin.error), ws_server.C.RED)
        return False
    try:
        setup(PluginContext(plugin))
    except Exception as e:
        plugin.error = "setup 异常：%s" % e
        plugin.loaded = False
        _log("[%s] setup 异常：%s" % (plugin.id, e), ws_server.C.RED)
        traceback.print_exc()
        return False
    plugin.error = ""
    plugin.loaded = True
    plugin.loaded_at = time.time()
    plugin.reload_count += 1
    _log("[%s] 已载入 %s v%s%s" % (
        plugin.id, manifest.get("name") or "", manifest.get("version") or "",
        ("（Web 端口 %d）" % plugin.web_port) if plugin.web_port else ""),
        ws_server.C.GREEN)
    return True


# ----------------------------------------------------------------------------
# 扫描
# ----------------------------------------------------------------------------
def _scan():
    root = plugin_root()
    found = {}
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return found
    for name in names:
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or name.startswith(".") or name.startswith("_"):
            continue
        manifest, err = _read_manifest(folder)
        if manifest is None:
            # 没有清单 / 清单不合法：也报出来，方便在 Web 上看到「装错了」
            found["__bad__" + name] = (folder, None, err)
            continue
        found[manifest["id"]] = (folder, manifest, "")
    return found


def _signature(folder):
    """目录指纹：参与热重载判断（文件 mtime + 大小）。"""
    marks = []
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fn in sorted(files):
            if not fn.endswith(WATCH_SUFFIXES):
                continue
            fp = os.path.join(base, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            marks.append("%s:%d:%d" % (os.path.relpath(fp, folder), int(st.st_mtime), st.st_size))
    return "|".join(marks)


def sync(force=False):
    """扫描插件目录 + 应用状态，返回 (新增, 变更, 移除) 数量。"""
    added = changed = removed = 0
    with _lock:
        found = _scan()
        # 0) 装错了的文件夹（缺清单 / 清单不合法）：也报给 Web，方便排查
        _bad.clear()
        for key, (_folder, manifest, err) in list(found.items()):
            if manifest is None:
                _bad[os.path.basename(_folder)] = {"folder": _folder, "error": err}
                found.pop(key, None)
        # 1) 移除：目录没了
        for pid in list(_plugins):
            if pid not in found:
                _unload(_plugins[pid])
                _plugins.pop(pid, None)
                _config["plugins"].pop(pid, None)
                removed += 1
                _log("[%s] 插件目录已移除，已卸载" % pid, ws_server.C.YELLOW)

        used_ports = set()
        for pid, (folder, manifest, _err) in list(found.items()):
            used_ports.add(int(manifest.get("web_port") or 0))

        for pid, (folder, manifest, err) in list(found.items()):
            p = _plugins.get(pid)
            if p is None or p.folder != folder:
                if p is not None:
                    _unload(p)
                p = Plugin(pid, folder, manifest)
                _plugins[pid] = p
                added += 1
            else:
                p.manifest = manifest
                p.name = manifest.get("name") or pid

            st = _state_of(pid)
            if "enabled" not in st:
                st["enabled"] = bool(manifest.get("enabled_by_default", True))
            p.enabled = bool(st["enabled"]) and bool(getattr(config, "PLUGIN_ENABLED", True))

            # Web 端口：manifest 指定优先，否则按需分配并记住
            port = int(manifest.get("web_port") or 0)
            if manifest.get("web"):
                if not port:
                    port = int(st.get("web_port") or 0)
                    if not port:
                        port = _alloc_port(used_ports - {0})
                        st["web_port"] = port
                used_ports.add(port)
            p.web_port = port

            p.values = _normalize_values(manifest, st.get("config"))

            sig = _signature(folder)
            old_sig = _last_signature.get(pid)
            need = force or p.module is None or (old_sig is not None and old_sig != sig)
            if need and p.enabled:
                if p.module is not None:
                    _unload(p)
                _load(p)
                if old_sig is not None and old_sig != sig:
                    changed += 1
            elif not p.enabled and p.module is not None:
                _unload(p)
            _last_signature[pid] = sig

        if added or changed or removed:
            _save_state()
    return added, changed, removed


# ----------------------------------------------------------------------------
# 事件 / 指令分发
# ----------------------------------------------------------------------------
def _install_dispatcher():
    global _dispatcher_installed
    if _dispatcher_installed:
        return
    ws_server.add_event_handler(_dispatch_event)
    _dispatcher_installed = True


def _dispatch_event(ev, client=None):
    with _lock:
        targets = [(p.id, list(p.event_handlers)) for p in _plugins.values()
                   if p.loaded and p.event_handlers]
    if not targets:
        return
    for pid, handlers in targets:
        for fn in handlers:
            try:
                fn(ev, client)
            except Exception:
                _log("[%s] 事件处理异常\n%s" % (pid, traceback.format_exc()),
                     ws_server.C.YELLOW)


def dispatch_command(body, ctx=None):
    """插件指令入口。有插件认领返回 (images, texts)，否则返回 None。

    由 bot_commands.run_command 在「没有这条指令」之前调用。
    """
    body = str(body or "").strip()
    if not body:
        return None
    parts = body.split()
    head = parts[0].lower()
    if head.startswith("/"):
        head = head.lstrip("/")
    with _lock:
        hit = _commands.get(head)
    if not hit:
        return None
    pid, fn = hit
    try:
        out = fn(parts[1:], ctx or {}, PluginContext(_plugins[pid]))
    except Exception as e:
        _log("[%s] 指令 %s 异常：%s" % (pid, head, e), ws_server.C.RED)
        traceback.print_exc()
        try:
            import bot_render
            return ([bot_render.render_notice(
                "插件指令执行失败", ["插件 %s 的 /%s 出错：%s" % (pid, head, str(e)[:120])],
                "err")], [])
        except Exception:
            return ([], ["插件 %s 的 /%s 执行失败：%s" % (pid, head, str(e)[:120])])
    if out is None:
        return ([], [])
    if isinstance(out, tuple) and len(out) == 2:
        images, texts = out
        return (list(images or []), list(texts or []))
    if isinstance(out, str):
        return ([], [out])
    return ([], [])


# ----------------------------------------------------------------------------
# 热重载
# ----------------------------------------------------------------------------
def _watch_loop():
    while not _watcher_stop.is_set():
        try:
            sync(force=False)
        except Exception:
            traceback.print_exc()
        try:
            sec = max(2, int(getattr(config, "PLUGIN_POLL_SEC", 3) or 3))
        except Exception:
            sec = 3
        _watcher_stop.wait(sec)


def start_watcher():
    global _watcher_thread
    if not getattr(config, "PLUGIN_HOT_RELOAD", True):
        return False
    if _watcher_thread and _watcher_thread.is_alive():
        return True
    _watcher_stop.clear()
    _watcher_thread = threading.Thread(target=_watch_loop, name="ilbb-plugin-watch", daemon=True)
    _watcher_thread.start()
    return True


def stop_watcher():
    _watcher_stop.set()


def start():
    """app.py 启动时调用：载入全部插件 + 打开热重载轮询。"""
    global _started
    with _lock:
        if _started:
            return _summary()
        _started = True
    _load_state()
    if not getattr(config, "PLUGIN_ENABLED", True):
        _log("插件系统已关闭（PLUGIN_ENABLED=false）", ws_server.C.YELLOW)
        return _summary()
    _install_dispatcher()
    added, changed, removed = sync(force=True)
    start_watcher()
    _log("已扫描 %s · %d 个插件（新增 %d / 变更 %d / 移除 %d）"
         % (plugin_root(), len(_plugins), added, changed, removed),
         ws_server.C.MAGENTA)
    return _summary()


def _summary():
    with _lock:
        items = [p.public() for p in _plugins.values()]
        bad = [{"name": k, "folder": v["folder"], "error": v["error"]}
               for k, v in _bad.items()]
    return {
        "ok": True,
        "enabled": bool(getattr(config, "PLUGIN_ENABLED", True)),
        "hot_reload": bool(getattr(config, "PLUGIN_HOT_RELOAD", True)),
        "poll_sec": int(getattr(config, "PLUGIN_POLL_SEC", 3) or 3),
        "root": plugin_root(),
        "config_path": config_path(),
        "count": len(items),
        "loaded": len([i for i in items if i["loaded"]]),
        "plugins": sorted(items, key=lambda x: x["id"]),
        "bad": sorted(bad, key=lambda x: x["name"]),
    }


# ----------------------------------------------------------------------------
# 对外 API（给 app.py 的路由用）
# ----------------------------------------------------------------------------
def list_plugins():
    sync(force=False)
    return _summary()


def get_plugin(pid):
    with _lock:
        p = _plugins.get(str(pid or "").strip())
    return p


def set_enabled(pid, enabled):
    with _lock:
        p = _plugins.get(str(pid or "").strip())
        if p is None:
            return {"ok": False, "error": "插件不存在：%s" % pid}
        st = _state_of(p.id)
        st["enabled"] = bool(enabled)
        p.enabled = bool(enabled) and bool(getattr(config, "PLUGIN_ENABLED", True))
        _save_state()
        if p.enabled:
            _load(p)
        else:
            _unload(p)
            _log("[%s] 已热禁用" % p.id, ws_server.C.YELLOW)
        _last_signature[p.id] = _signature(p.folder)
        return {"ok": True, "plugin": p.public()}


def reload(pid=None):
    with _lock:
        if pid:
            p = _plugins.get(str(pid).strip())
            if p is None:
                return {"ok": False, "error": "插件不存在：%s" % pid}
            _unload(p)
            ok = _load(p)
            _last_signature[p.id] = _signature(p.folder)
            return {"ok": True, "loaded": ok, "plugin": p.public()}
        added, changed, removed = sync(force=True)
        return {"ok": True, "added": added, "changed": changed, "removed": removed,
                "summary": _summary()}


def get_config(pid):
    with _lock:
        p = _plugins.get(str(pid or "").strip())
        if p is None:
            return {"ok": False, "error": "插件不存在：%s" % pid}
        return {"ok": True, "id": p.id, "fields": p.manifest.get("config", []),
                "values": dict(p.values)}


def set_config(pid, values):
    with _lock:
        p = _plugins.get(str(pid or "").strip())
        if p is None:
            return {"ok": False, "error": "插件不存在：%s" % pid}
        vals = _normalize_values(p.manifest, values if isinstance(values, dict) else {})
        st = _state_of(p.id)
        st["config"] = vals
        p.values = vals
        _save_state()
        # 配置变了：让插件有机会感知（提供 on_config 时热应用，无需重载代码）
        mod = p.module
        fn = getattr(mod, "on_config", None) if mod is not None else None
        if callable(fn) and p.loaded:
            try:
                fn(vals, PluginContext(p))
            except Exception:
                _log("[%s] on_config 异常\n%s" % (p.id, traceback.format_exc()),
                     ws_server.C.YELLOW)
        return {"ok": True, "id": p.id, "values": vals}


def web_info(pid, host="127.0.0.1"):
    """插件独立页面信息：端口 / 地址 / 是否在线（探测一次）。"""
    p = get_plugin(pid)
    if p is None:
        return {"ok": False, "error": "插件不存在：%s" % pid}
    if not p.manifest.get("web") or not p.web_port:
        return {"ok": False, "error": "该插件没有开放独立 Web（plugin.json 里写 \"web\": true 才会显示）"}
    scheme = getattr(config, "PLUGIN_WEB_SCHEME", "http") or "http"
    path = p.manifest.get("web_path") or "/"
    if not path.startswith("/"):
        path = "/" + path
    url = "%s://%s:%d%s" % (scheme, host, p.web_port, path)
    return {"ok": True, "id": p.id, "title": p.manifest.get("web_title") or p.name,
            "scheme": scheme, "port": p.web_port, "path": path, "url": url,
            "enabled": p.enabled, "loaded": p.loaded, "up": probe_web(pid)}


def probe_web(pid):
    """探测插件的 Web 是否已经起来。"""
    p = get_plugin(pid)
    if p is None or not p.web_port:
        return False
    scheme = getattr(config, "PLUGIN_WEB_SCHEME", "http") or "http"
    try:
        timeout = max(1, int(getattr(config, "PLUGIN_WEB_TIMEOUT", 4) or 4))
    except Exception:
        timeout = 4
    url = "%s://127.0.0.1:%d/" % (scheme, p.web_port)
    try:
        req = urlrequest.Request(url, method="GET")
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 500
    except urlerror.HTTPError as e:
        return 200 <= int(e.code) < 500
    except Exception:
        return False

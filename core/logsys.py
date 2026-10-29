# -*- coding: utf-8 -*-
"""ILBB 统一日志系统

三件事：
1. 终端彩色输出：不同级别用不同颜色（DEBUG 灰 / INFO 青 / OK 绿 / WARN 黄 / ERROR 红）。
2. 内存环形缓冲：所有日志进缓冲区，供 WebUI「日志」页按级别筛选、搜索。
3. 接管标准输出：项目里既有的 print() 也会被收集；Werkzeug 的
   ``127.0.0.1 - - [...] "GET / 200"`` 这类正常访问日志直接丢弃（4xx/5xx 仍保留）。

对外 API
--------
    install()                            安装标准输出接管（app.py 启动时调一次）
    attach_logger(logger, source)        把标准 logging 记录接入本系统
    log(level, text, source="")          写入一条结构化日志
    tail(since, limit, levels, q)        WebUI 拉取
    clear()                              清空缓冲

级别：debug / info / success / warn / error（warning、err 等别名会自动归一）。
"""

import collections
import logging
import os
import re
import sys
import threading
import time

MAX_ENTRIES = 3000              # 环形缓冲上限（超出丢弃最旧的）

LEVELS = ("debug", "info", "success", "warn", "error")
_LABEL = {
    "debug": "DEBUG",
    "info": "INFO",
    "success": "OK",
    "warn": "WARN",
    "error": "ERROR",
}
_COLOR = {
    "debug": "\033[90m",
    "info": "\033[36m",
    "success": "\033[32m",
    "warn": "\033[33m",
    "error": "\033[31m",
}
_ALIAS = {
    "debug": "debug", "trace": "debug",
    "info": "info", "information": "info",
    "success": "success", "ok": "success",
    "warn": "warn", "warning": "warn",
    "error": "error", "err": "error", "fatal": "error", "critical": "error",
}

_lock = threading.RLock()
_entries = collections.deque(maxlen=MAX_ENTRIES)
_seq = 0
_out = sys.stdout             # 真正的终端输出流（绕过下面的 Tee，避免自己记录自己）
_color_ok = False
_installed = False

# 形如  "GET /path HTTP/1.1" 200   （Werkzeug 访问日志的核心片段）
_ACCESS_RE = re.compile(r'"[A-Z]+ [^"]*?HTTP/[0-9.]+" (\d{3})')
# 去掉 ANSI 转义，便于解析与 WebUI 展示
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
# 打印行前缀：[12:33:01] 【WS】 或 [webqq]
_PREFIX_RE = re.compile(r"^\s*(?:\[\d{2}:\d{2}:\d{2}\]\s*)?(?:【([^】]{1,20})】|\[([^\]\d][^\]]{0,19})\])?\s*(.*)$")

_ERR_HINTS = ("错误", "失败", "异常", "error", "exception", "traceback",
              "fatal", "critical", "✗", "拒绝", "无法")
_WARN_HINTS = ("警告", "warn", "⚠", "超时", "忽略", "失败重试", "未连接")
_OK_HINTS = ("成功", "已启动", "已停止", "已连接", "✓", "已保存", "已加载")


def _enable_vt():
    """Windows 控制台开启 ANSI 颜色支持。"""
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


def _norm(level):
    return _ALIAS.get(str(level or "info").strip().lower(), "info")


def _now():
    return time.strftime("%H:%M:%S")


def _paint(text, level):
    if not _color_ok:
        return text
    return _COLOR.get(level, "") + text + "\033[0m"


# ----------------------------------------------------------------------------
# 缓冲 + 终端输出
# ----------------------------------------------------------------------------
def _emit(level, source, text, styled=False):
    """写入缓冲区并打印。"""
    global _seq
    lv = _norm(level)
    text = str(text).replace("\r", "")
    with _lock:
        _seq += 1
        item = {"id": _seq, "t": time.time(), "level": lv,
                "source": str(source or ""), "text": text}
        _entries.append(item)
    try:
        src = ("[%s] " % item["source"]) if item["source"] else ""
        line = "%s %s %s%s" % (_paint("[" + _now() + "]", "debug"),
                               _paint("%-5s" % _LABEL[lv], lv),
                               _paint(src, "debug"), text)
        _out.write(line + "\n")
        _out.flush()
    except Exception:
        pass
    return item


def log(level, text, source=""):
    """写入一条结构化日志。"""
    return _emit(level, source, text)


def clear():
    with _lock:
        _entries.clear()


def tail(since=0, limit=300, levels=None, q=""):
    """WebUI 拉取：since=0 时返回最近 limit 条；否则返回 id 大于 since 的条目。"""
    try:
        since = int(since or 0)
    except (TypeError, ValueError):
        since = 0
    try:
        limit = max(1, min(int(limit or 300), 1000))
    except (TypeError, ValueError):
        limit = 300

    if levels:
        if isinstance(levels, str):
            wanted = {_norm(x) for x in levels.split(",") if x.strip()}
        else:
            wanted = {_norm(x) for x in levels}
    else:
        wanted = set()

    q = str(q or "").strip().lower()
    with _lock:
        seq = _seq
        items = list(_entries)

    if since > 0:
        items = [e for e in items if e["id"] > since]
    if wanted:
        items = [e for e in items if e["level"] in wanted]
    if q:
        items = [e for e in items
                 if q in e["text"].lower() or q in e["source"].lower()]
    items = items[-limit:]
    return {"ok": True, "seq": seq, "items": items}


# ----------------------------------------------------------------------------
# 标准输出接管
# ----------------------------------------------------------------------------
def _infer_level(text):
    low = text.lower()
    for h in _ERR_HINTS:
        if h in low:
            return "error"
    for h in _WARN_HINTS:
        if h in low:
            return "warn"
    for h in _OK_HINTS:
        if h in low:
            return "success"
    return "info"


def _consume(raw):
    """处理一行普通 print 输出：过滤访问日志、猜级别、猜来源，然后入库+着色输出。"""
    if not raw.strip():
        return
    plain = _ANSI_RE.sub("", raw)

    # 纯分隔线（==== 之类）不占日志篇幅
    if set(plain.strip()) == {"="}:
        return

    # 个别库会把 bytes 的 repr 直接写进 stderr，这里还原成正常文本
    if plain.startswith(("b'", 'b"')):
        try:
            import ast
            val = ast.literal_eval(plain.strip())
            if isinstance(val, bytes):
                plain = val.decode("utf-8", "replace")
                if not plain.strip():
                    return
        except Exception:
            pass

    # 正常访问日志（2xx/3xx）直接丢弃；4xx/5xx 保留为 warn/error
    m = _ACCESS_RE.search(plain)
    if m:
        code = int(m.group(1))
        if code < 400:
            return
        return _emit("error" if code >= 500 else "warn", "http", plain.strip())

    src = ""
    text = plain
    pm = _PREFIX_RE.match(plain)
    if pm:
        src = pm.group(1) or pm.group(2) or ""
        text = pm.group(3)
    if not text.strip():
        text = plain.strip()
    return _emit(_infer_level(plain), src, text)


class _Tee:
    """把写向标准流的文本转交给缓冲系统，同时原样写回终端。"""

    def __init__(self, real, name):
        self._real = real
        self._name = name
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        # 不再原样写回终端：所有内容统一走 _consume → _emit，
        # 保证每行只输出一次，且带上时间 / 级别 / 颜色。
        try:
            with _lock:
                self._buf += str(s)
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    _consume(line)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass
        try:
            with _lock:
                if self._buf:
                    line, self._buf = self._buf, ""
                    _consume(line)
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._real, name)


class _Bridge(logging.Handler):
    """标准 logging → 本系统。"""

    def __init__(self, source=None):
        logging.Handler.__init__(self)
        self._source = source

    def emit(self, record):
        try:
            msg = _ANSI_RE.sub("", record.getMessage())
            lv = _norm(record.levelname)
            m = _ACCESS_RE.search(msg)
            if m:
                code = int(m.group(1))
                if code < 400:
                    return
                lv = "error" if code >= 500 else "warn"
            src = self._source if self._source is not None else record.name
            _emit(lv, src, msg)
        except Exception:
            pass


def attach_logger(logger, source=None):
    """接管某个 logging logger（清空原有 handler，避免重复输出）。"""
    try:
        for h in list(logger.handlers):
            logger.removeHandler(h)
        logger.addHandler(_Bridge(source))
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    except Exception:
        pass


def install():
    """安装标准输出接管。重复调用无副作用。"""
    global _installed, _out, _color_ok
    if _installed:
        return
    _installed = True
    _enable_vt()
    _out = sys.stdout
    try:
        _color_ok = (os.environ.get("NO_COLOR") is None
                     and bool(getattr(_out, "isatty", lambda: False)()))
    except Exception:
        _color_ok = False
    sys.stdout = _Tee(_out, "stdout")
    sys.stderr = _Tee(sys.stderr, "stderr")

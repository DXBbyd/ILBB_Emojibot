# -*- coding: utf-8 -*-
"""插件依赖自动安装 —— 用宿主「当前虚拟环境」里的包管理器补齐插件声明的第三方库。

为什么需要
----------
插件可以自由依赖第三方库，但 ILBB 的插件是「把文件夹丢进 plugins/ 就生效」的，
用户往往不会先 pip install。插件 import 一失败，报错只有一句
``导入失败：No module named 'xxx'``，对不熟 Python 的用户基本无法自救。
这里在插件被导入**之前**先把缺口补上。

声明方式（两种都支持，同时写会合并去重）
----------------------------------------
1. ``plugin.json`` 顶层：``"requirements": ["requests>=2.28", "Pillow>=10,<11"]``
2. 插件目录下的标准 ``requirements.txt``（支持 ``#`` 注释与空行）

安全边界（每一条都别删）
------------------------
* **只在虚拟环境里装**：宿主跑在系统 Python 下时一律拒绝，只打印手动命令。
  往系统解释器里 pip install 会把用户的系统环境搞坏，而且装出来的东西
  下次换解释器又没了。
* **拒绝以 ``-`` 开头的条目**：否则插件能塞 ``--index-url`` / ``-r`` / ``-e``
  这类选项参数，把包管理器引到任意安装源 —— 等于把「安装什么」的决定权
  交给插件。凡是这种条目一律跳过并写日志。
* 只用参数列表调用 ``subprocess``（不经 shell），没有命令注入面。
* 有超时；装不上只影响这一个插件，绝不让宿主起不来。
* 同一插件 + 同一份依赖清单在同一进程里只尝试一次，避免热重载反复触发安装；
  Web 上手动「重载」会清掉这个记录，等于显式重试一次。

本模块不 import 业务层，只依赖标准库 + ``config``。
"""

import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from importlib import util as importlib_util

import config

try:
    # packaging 随 pip 一起装，正常环境里都在；万一没有就退化成「只查装没装」。
    from packaging.requirements import Requirement as _Requirement
except Exception:                                    # pragma: no cover - 环境相关
    _Requirement = None

#: 插件目录下可选的需求清单文件名。
REQ_FILE = "requirements.txt"
#: 需求条目必须以此开头（字母/数字）。顺带把 ``-``/``.`` 开头的选项挡在外面。
_REQ_OK = re.compile(r"^[A-Za-z0-9]")
#: 从需求串里切出「分发名」：``Pillow>=10,<11`` → ``pillow``。
_NAME_SPLIT = re.compile(r"[<>=!~\[;(\s]")
#: 注释：行首 ``#``，或空白之后的 ``#``（PEP 508 的写法）。
_COMMENT_RE = re.compile(r"(^|\s)#.*$")
#: 规格里的比较运算符。
_OP_RE = re.compile(r"(===|==|!=|>=|<=|~=|>|<)\s*([^,;\s]+)")
#: Windows 上不弹黑框（宿主用 pythonw 跑时尤其明显）。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
#: 安装超时兜底（秒），实际取 config.PLUGIN_INSTALL_TIMEOUT。
DEFAULT_TIMEOUT = 300

#: 插件 id -> 上次尝试结果。键里带上依赖清单，清单变了就会重新尝试。
_ATTEMPTED = {}


# ----------------------------------------------------------------------------
# 日志
# ----------------------------------------------------------------------------
def _log(msg, color=None):
    try:
        import ws_server
        ws_server._log("插件依赖", msg, color or ws_server.C.YELLOW)
    except Exception:
        print("[插件依赖] " + str(msg), flush=True)


def _color(name, default=None):
    try:
        import ws_server
        return getattr(ws_server.C, name, default)
    except Exception:
        return default


# ----------------------------------------------------------------------------
# 虚拟环境
# ----------------------------------------------------------------------------
def venv_python(prefix=None):
    """虚拟环境里的解释器路径；找不到返回空串。"""
    prefix = prefix or sys.prefix
    if not prefix:
        return ""
    for rel in (("Scripts", "python.exe"), ("bin", "python3"), ("bin", "python")):
        p = os.path.join(prefix, *rel)
        if os.path.isfile(p):
            return p
    return ""


def venv_info():
    """当前运行环境的虚拟环境体检结果（启动时与安装前都会查一次）。

    ``ok`` 为真才允许自动装依赖：跑在系统 Python 下时往里 pip install 会把
    用户的系统环境搞坏，所以那种情况只提示、不代劳。
    """
    prefix = str(getattr(sys, "prefix", "") or "")
    base = str(getattr(sys, "base_prefix", "") or prefix)
    env_dir = str(os.environ.get("VIRTUAL_ENV") or "").strip()
    in_venv = bool(prefix and base and prefix != base)
    if not in_venv and env_dir:
        # 少数启动方式下 sys.prefix 没跟着变，但 VIRTUAL_ENV 明确指了一个环境。
        prefix, in_venv = env_dir, True
    exists = bool(prefix) and os.path.isdir(prefix)
    py = venv_python(prefix) if exists else ""
    reasons = []
    if not in_venv:
        reasons.append("当前解释器不是虚拟环境（sys.prefix 与 sys.base_prefix 相同）")
    if not exists:
        reasons.append("虚拟环境目录不存在：%s" % (prefix or "(空)"))
    elif not py:
        reasons.append("虚拟环境里找不到 python 可执行文件：%s" % prefix)
    return {
        "in_venv": bool(in_venv),
        "prefix": prefix,
        "base_prefix": base,
        "exists": bool(exists),
        "python": py,
        "ok": bool(in_venv and exists and py),
        "detail": "；".join(reasons),
    }


def python_exe():
    """当前解释器（虚拟环境里的那个）。"""
    return sys.executable or venv_python() or "python"


# ----------------------------------------------------------------------------
# 需求声明解析
# ----------------------------------------------------------------------------
def _dist_name(req):
    """从需求串里取「分发名」：``Pillow>=10,<11`` → ``pillow``。"""
    return _NAME_SPLIT.split(str(req or "").strip(), 1)[0].strip().lower()


def _clean_entry(text):
    """清洗一条需求；非法返回 ``("", 原因)``。"""
    s = str(text or "").strip()
    if not s:
        return "", ""
    if s[0] in "-.":
        # ``-r`` / ``--index-url`` / ``-e`` / ``--target`` / ``./local`` 之类。
        # 放过去等于把「装什么、从哪装」的决定权交给插件，一律拒绝。
        return "", "看起来是包管理器选项或相对路径，不允许：%s" % s[:60]
    if not _REQ_OK.match(s):
        return "", "包名必须以字母或数字开头（PEP 508）：%s" % s[:60]
    return s, ""


def _iter_text_entries(text):
    for line in str(text or "").splitlines():
        line = _COMMENT_RE.sub("", line).strip()
        if line:
            yield line


def collect_requirements(manifest=None, folder="", extra_text=""):
    """汇总一个插件声明的依赖，返回 ``{"reqs": [...], "rejected": [...]}``。

    来源三处，按顺序合并、按分发名去重：``plugin.json`` 的 ``requirements``、
    插件目录下的 ``requirements.txt``、``extra_text``（给测试注入用）。
    """
    raw = []
    decl = (manifest or {}).get("requirements")
    if isinstance(decl, str):
        raw.append(decl)
    elif isinstance(decl, (list, tuple)):
        raw.extend([d for d in decl if isinstance(d, str)])
    if folder:
        p = os.path.join(folder, REQ_FILE)
        try:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    raw.append(f.read())
        except Exception as e:
            _log("读 %s 失败：%s" % (p, e), _color("RED"))
    if extra_text:
        raw.append(extra_text)

    reqs, rejected, seen = [], [], set()
    for block in raw:
        for entry in _iter_text_entries(block):
            item, why = _clean_entry(entry)
            if why:
                if entry not in [r["entry"] for r in rejected]:
                    rejected.append({"entry": entry, "why": why})
                continue
            key = _dist_name(item)
            if not key or key in seen:
                continue
            seen.add(key)
            reqs.append(item)
    return {"reqs": reqs, "rejected": rejected}


# ----------------------------------------------------------------------------
# 判断缺哪些
# ----------------------------------------------------------------------------
def installed_version(dist):
    """已安装的版本号；没装返回空串。"""
    try:
        return metadata.version(str(dist or "").strip())
    except Exception:
        return ""


def _vparts(text):
    """版本拆成可比较的片段：``10.3.1rc2`` → ``[10, 3, 1, 'rc', 2]``。"""
    out = []
    for part in re.split(r"[.\-_+]", str(text or "").strip()):
        if not part:
            continue
        out.append(int(part) if part.isdigit() else part.lower())
    return out


def _vcmp(a, b):
    """比较两个版本号，返回 -1 / 0 / 1。"""
    pa, pb = _vparts(a), _vparts(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x == y:
            continue
        # 类型不同说明到了预发布后缀（3.0 vs 3.0rc1）：数字段更大。
        if isinstance(x, int) and isinstance(y, str):
            return 1
        if isinstance(x, str) and isinstance(y, int):
            return -1
        return -1 if x < y else 1
    return 0


def _spec_ok(version, spec):
    """够不够格：spec 里逗号分隔的每个条件都得满足。

    这是 ``packaging`` 不在环境里时的兜底实现，覆盖 ``>= <= > < == != ~=``
    与「数字 + 字母后缀」的常见版本号。预发布的细节语义（``3.0.0rc1 < 3.0.0``
    之外的怪写法）不保证，那种情况交给包管理器自己判断。
    """
    for op, want in _OP_RE.findall(str(spec or "")):
        c = _vcmp(version, want)
        if op in ("==", "===") and c != 0:
            return False
        if op == "!=" and c == 0:
            return False
        if op == ">=" and c < 0:
            return False
        if op == "<=" and c > 0:
            return False
        if op == ">" and c <= 0:
            return False
        if op == "<" and c >= 0:
            return False
        if op == "~=":
            if c < 0:
                return False
            w, v = _vparts(want), _vparts(version)
            n = max(1, len(w) - 1)          # ~=1.4.2 → 前缀 1.4 必须一致
            if v[:n] != w[:n]:
                return False
    return True


def _raw_specifier(req):
    """从需求串里抠出规格部分：``Pillow>=10,<11`` → ``>=10,<11``（跳过 extras）。"""
    s = str(req or "").strip()
    m = _NAME_SPLIT.search(s)
    if not m:
        return ""
    rest = s[m.start():]
    if rest.startswith("["):
        end = rest.find("]")
        rest = rest[end + 1:].strip() if end >= 0 else rest
        m2 = _NAME_SPLIT.search(rest)
        rest = rest[m2.start():] if m2 else ""
    return rest.strip()


def missing_requirements(reqs):
    """返回还没满足的条目（没装，或装了但不满足版本区间）。"""
    out = []
    for req in reqs or []:
        name = _dist_name(req)
        if not name:
            continue
        have = installed_version(name)
        if not have:
            out.append(req)
            continue
        # 有 packaging 就用它（语义最准），没有就用内置比较兜底。
        spec = ""
        if _Requirement is not None:
            try:
                spec = str(_Requirement(req).specifier)
            except Exception:
                spec = _raw_specifier(req)
        else:
            spec = _raw_specifier(req)
        try:
            if spec and not _spec_ok(have, spec):
                out.append(req)
        except Exception:
            continue                     # 判不了就交给包管理器自己决定
    return out


# ----------------------------------------------------------------------------
# 安装
# ----------------------------------------------------------------------------
def installer_cmd(reqs, python_path=""):
    """挑一个包管理器，返回待执行的 argv；都不行返回 ``None``。

    优先 ``uv pip``（ILBB 一贯用它装依赖），没有 uv 再退到当前解释器的 ``pip``。
    两者都显式指定目标解释器，避免装错环境。
    """
    py = python_path or python_exe()
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", py] + list(reqs)
    try:
        if importlib_util.find_spec("pip") is not None:
            return [py, "-m", "pip", "install"] + list(reqs)
    except Exception:
        pass
    return None


def install_timeout():
    try:
        return max(15, int(getattr(config, "PLUGIN_INSTALL_TIMEOUT", DEFAULT_TIMEOUT)))
    except Exception:
        return DEFAULT_TIMEOUT


def install(reqs, timeout=None, python_path=""):
    """把 reqs 装进当前虚拟环境，返回 ``(ok, 输出或原因)``。"""
    reqs = [str(r).strip() for r in (reqs or []) if str(r).strip()]
    if not reqs:
        return True, "没有需要安装的依赖"

    info = venv_info()
    if not info["ok"]:
        return False, ("不在可用的虚拟环境里，已跳过（%s）。请自己在虚拟环境里执行："
                       "uv pip install %s" % (info["detail"], " ".join(reqs)))

    cmd = installer_cmd(reqs, info["python"])
    if cmd is None:
        return False, "uv 与 pip 都不可用，装不了：" + " ".join(reqs)

    timeout = int(timeout or install_timeout())
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = info["prefix"]      # 明确告诉 uv / pip 装进哪个环境
    env.pop("PYTHONHOME", None)
    index = str(getattr(config, "PLUGIN_PIP_INDEX", "") or "").strip()
    if index:
        cmd += ["--index-url", index]

    kwargs = {"capture_output": True, "text": True, "timeout": timeout, "env": env,
              "cwd": info["prefix"]}
    if _NO_WINDOW:
        kwargs["creationflags"] = _NO_WINDOW
    try:
        proc = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        return False, "安装超时（%d 秒），已放弃" % timeout
    except Exception as e:
        return False, "安装失败：%s" % e

    blob = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    tail = blob[-600:]
    if proc.returncode == 0:
        return True, tail or "ok"
    return False, "退出码 %d：%s" % (proc.returncode, tail)


# ----------------------------------------------------------------------------
# 对外主入口
# ----------------------------------------------------------------------------
def ensure(manifest, folder="", use_cache=True):
    """确保某个插件的依赖都就位，返回一份可日志 / 可上报的结果。

    返回值：
      ``declared``  声明了哪些依赖
      ``missing``   还没满足的（装完仍缺的就是它）
      ``installed`` 这次新装上的
      ``ok``        依赖现在是否齐了
      ``skipped``   没做自动安装的原因（关开关 / 不在虚拟环境 / 刚试过）
      ``detail``    包管理器原样输出，排查用
      ``rejected``  被拒绝的可疑条目
      ``python``    目标解释器
    """
    pid = str((manifest or {}).get("id") or os.path.basename(folder or "") or "?")
    got = collect_requirements(manifest, folder)
    reqs = got["reqs"]
    out = {"plugin": pid, "declared": list(reqs), "rejected": got["rejected"],
           "missing": [], "installed": [], "ok": True, "skipped": "", "detail": "",
           "python": venv_info()["python"]}

    for bad in got["rejected"]:
        _log("[%s] 忽略可疑的依赖条目：%s（%s）" % (pid, bad["entry"], bad["why"]),
             _color("RED"))

    if not reqs:
        return out

    miss = missing_requirements(reqs)
    if not miss:
        return out
    out["missing"] = list(miss)

    if not bool(getattr(config, "PLUGIN_AUTO_INSTALL", True)):
        out["ok"] = False
        out["skipped"] = "自动安装已关闭（PLUGIN_AUTO_INSTALL=false）"
        _log("[%s] 缺依赖：%s —— %s" % (pid, "、".join(miss), out["skipped"]),
             _color("RED"))
        return out

    key = (pid, tuple(reqs))
    if use_cache:
        prev = _ATTEMPTED.get(key)
        if prev is not None:
            # 命中缓存：``installed`` 清空 —— 「这次」确实什么都没装，
            # 免得每次热重载都报告一遍「刚装上了 xxx」。
            out.update(ok=bool(prev.get("ok")), installed=[],
                       missing=list(prev.get("missing") or miss),
                       detail=str(prev.get("detail") or ""),
                       skipped="本次进程已尝试过，不重复安装")
            return out

    info = venv_info()
    if not info["ok"]:
        out["ok"] = False
        out["skipped"] = info["detail"] + "，已跳过自动安装"
        _log("[%s] 缺依赖：%s —— %s\n  手动安装：uv pip install %s"
             % (pid, "、".join(miss), out["skipped"], " ".join(miss)), _color("RED"))
        _ATTEMPTED[key] = dict(out)
        return out

    tool = (installer_cmd([], info["python"]) or ["?"])[0]
    _log("[%s] 缺依赖：%s，正在用 %s 装进 %s（最长 %d 秒）…"
         % (pid, "、".join(miss), tool, info["prefix"], install_timeout()),
         _color("YELLOW"))

    ok, detail = install(miss, python_path=info["python"])
    out["detail"] = detail
    if ok:
        still = missing_requirements(miss)
        out["installed"] = [r for r in miss if r not in still]
        out["missing"] = list(still)
        out["ok"] = not still
        if still:
            _log("[%s] 装完仍缺：%s\n%s" % (pid, "、".join(still), detail[-400:]),
                 _color("RED"))
        else:
            _log("[%s] 依赖已就绪：%s" % (pid, "、".join(out["installed"])),
                 _color("GREEN"))
    else:
        out["ok"] = False
        _log("[%s] 自动安装失败：%s" % (pid, detail), _color("RED"))

    _ATTEMPTED[key] = dict(out)
    return out


def forget(pid=None):
    """清掉「已尝试」记录（Web 上手动重载时调用，等于允许重试一次）。"""
    pid = str(pid or "").strip()
    if not pid:
        _ATTEMPTED.clear()
        return
    for key in [k for k in list(_ATTEMPTED) if k[0] == pid]:
        _ATTEMPTED.pop(key, None)


def venv_summary():
    """给启动日志 / 引导页用的一行结论。"""
    info = venv_info()
    if info["ok"]:
        return "虚拟环境就绪：%s" % info["prefix"]
    return "未检测到可用的虚拟环境：%s" % (info["detail"] or "原因未知")


def failure_hint(exc, manifest=None, folder=""):
    """插件 import 失败时的补充提示（只在确实是「缺模块」时才给）。"""
    if not isinstance(exc, ModuleNotFoundError):
        return ""
    mod = str(getattr(exc, "name", "") or "").strip()
    where = venv_info()["python"] or python_exe()
    if mod:
        return ("缺少模块 %s：在本虚拟环境里执行 uv pip install %s"
                "（没有 uv 就用 %s -m pip install %s）" % (mod, mod, where, mod))
    return "疑似缺依赖：在本虚拟环境里执行 uv pip install <包名>"

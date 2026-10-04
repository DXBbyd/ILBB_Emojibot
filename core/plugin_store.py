# -*- coding: utf-8 -*-
"""ILBB 插件商店 —— 从「插件源服务器」(PSS) 拉列表，选加速地址后 git clone 进 plugins/。

它是 :mod:`plugin_manager` 的前置环节：本模块只负责「把插件文件夹弄到 plugins/ 下」，
之后的扫描 / 加载 / 热重载 / 改配置全部交给 plugin_manager，所以装完不需要重启。

四件事
------
1. **拉列表**：GET ``<PLUGIN_STORE_URL>/api/plugins``，带 q / tag / author 过滤，
   结果在内存里按 ``PLUGIN_STORE_TTL`` 秒缓存，避免反复打源站。
2. **加速地址**：一律按「前缀式」处理 —— ``<前缀>https://github.com/owner/repo.git``。
   「原 GitHub（直连）」= 不加任何前缀。地址清单来自 ``PLUGIN_GIT_PROXIES``
   （逗号 / 换行分隔，支持 ``名称|地址`` 写法）。
3. **测速**：对同一个仓库，分别请求各候选地址的
   ``<候选>/info/refs?service=git-upload-pack``（git smart-http 的真实入口），
   取「响应首字节」耗时排序。只有 status=200 且拿到数据才算通，其余记为失败。
4. **安装**：``git clone --depth 1 [--branch <分支>] <最终地址> plugins/<目录名>``，
   完成后自动重扫一次。仓库根目录没有 plugin.json、但唯一的非隐藏子目录里有，
   会自动把子目录内容「提」到根目录（兼容「仓库里套一层文件夹」的常见写法）。
   装过什么记在 ``plugins_store.json``，用于在商店列表里标「已安装」。

依赖：``requests``（已在 requirements.txt 里）+ 系统 ``git``。
"""

import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

try:
    import requests
except Exception:                                        # pragma: no cover
    requests = None

import config

MANIFEST_NAME = "plugin.json"
STATE_NAME = "plugins_store.json"
UA = "ILBB-PluginStore/1.0"
# 测速 / 拉列表用的默认仓库（商店里第一条记录就是它）。
DEFAULT_TEST_REPO = "https://github.com/DXBbyd/ilbb_plugin_example.git"

# config.PLUGIN_GIT_PROXIES 缺失时的兜底清单（正常情况用不到）。
_BUILTIN_PROXIES = [
    "https://gh.monlor.com/",
    "https://cdn.akaere.online/",
    "https://gh.llkk.cc/",
    "https://github-proxy.memory-echoes.cn/",
    "https://gitproxy.mrhjx.cn/",
    "https://ghfile.geekertao.top/",
    "https://ghproxy.imciel.com/",
    "https://ghf.xn--eqrr82bzpe.top/",
    "https://gh.xxooo.cf/",
    "https://gh.inkchills.cn/",
    "https://fastgit.cc/",
]

# 少数地址域名不好看（punycode / 过长），给个好读的名字。
_NICE_LABEL = {
    "ghf.xn--eqrr82bzpe.top": "ghf.苍梧.top",
    "github-proxy.memory-echoes.cn": "memory-echoes 代理",
    "gitproxy.mrhjx.cn": "mrhjx 代理",
    "ghfile.geekertao.top": "geekertao 文件代理",
}

_SPLIT_RE = re.compile(r"[\s,;，、]+")
_lock = threading.RLock()
_cache = {"key": "", "ts": 0.0, "data": None}


# ----------------------------------------------------------------------------
# 配置读取（每次调用现取 → 改完 .env 不用重启）
# ----------------------------------------------------------------------------
def _cfg(name, default=None):
    val = getattr(config, name, default)
    return default if val is None else val


def store_url():
    return str(_cfg("PLUGIN_STORE_URL", "") or "").rstrip("/")


def store_enabled():
    return bool(_cfg("PLUGIN_STORE_ENABLED", True))


def store_timeout():
    try:
        return max(2, int(_cfg("PLUGIN_STORE_TIMEOUT", 10) or 10))
    except (TypeError, ValueError):
        return 10


def store_ttl():
    try:
        return max(0, int(_cfg("PLUGIN_STORE_TTL", 60) or 0))
    except (TypeError, ValueError):
        return 60


def git_timeout():
    try:
        return max(10, int(_cfg("PLUGIN_GIT_TIMEOUT", 180) or 180))
    except (TypeError, ValueError):
        return 180


def git_bin():
    return str(_cfg("PLUGIN_GIT_BIN", "git") or "git").strip() or "git"


def git_depth():
    try:
        return max(1, int(_cfg("PLUGIN_GIT_DEPTH", 1) or 1))
    except (TypeError, ValueError):
        return 1


def test_repo():
    raw = str(_cfg("PLUGIN_GIT_TEST_REPO", "") or "").strip()
    return raw or DEFAULT_TEST_REPO


def _log(msg):
    try:
        import ws_server
        ws_server._log("插件商店", msg, ws_server.C.CYAN)
    except Exception:
        print("[插件商店] " + str(msg), flush=True)


# ----------------------------------------------------------------------------
# 加速地址
# ----------------------------------------------------------------------------
def _parse_proxies(raw):
    """把 ``PLUGIN_GIT_PROXIES`` 文本解析成 [{"prefix","label"}, ...]。"""
    out = []
    seen = set()
    for tok in _SPLIT_RE.split(str(raw or "")):
        tok = tok.strip()
        if not tok:
            continue
        label, prefix = "", tok
        if "|" in tok:
            label, prefix = tok.split("|", 1)
            label, prefix = label.strip(), prefix.strip()
        if not prefix.lower().startswith(("http://", "https://")):
            continue
        if not prefix.endswith("/"):
            prefix += "/"
        if prefix.lower() in seen:
            continue
        seen.add(prefix.lower())
        if not label:
            host = (urlparse(prefix).netloc or "").lower()
            label = _NICE_LABEL.get(host, host or prefix)
        out.append({"prefix": prefix, "label": label})
    return out


def proxies():
    raw = getattr(config, "PLUGIN_GIT_PROXIES", None)
    if raw is None:
        raw = ",".join(_BUILTIN_PROXIES)
    return _parse_proxies(raw)


def direct_option():
    """原 GitHub（不加任何前缀）。"""
    return {"prefix": "", "label": "原 GitHub（直连）", "direct": True}


def candidates():
    """候选地址清单：直连排第一，其余按配置顺序。"""
    items = [direct_option()]
    for p in proxies():
        items.append({"prefix": p["prefix"], "label": p["label"], "direct": False})
    for i, it in enumerate(items):
        it["id"] = i
    return items


def find_prefix(proxy):
    """把前端传来的值（'' / 'direct' / 序号 / 前缀 / 完整地址）解析成前缀。"""
    s = str(proxy if proxy is not None else "").strip()
    if s in ("", "direct", "origin", "github", "0"):
        return ""
    if s.isdigit():
        idx = int(s)
        cands = candidates()
        if 0 <= idx < len(cands):
            return cands[idx]["prefix"]
        return ""
    if not s.lower().startswith(("http://", "https://")):
        return ""
    if not s.endswith("/"):
        s += "/"
    return s


def apply_proxy(prefix, repo_url):
    """按前缀拼出真正要访问的地址。"""
    repo = str(repo_url or "").strip()
    if not repo:
        return ""
    p = str(prefix or "").strip()
    if not p:
        return repo
    if not p.endswith("/"):
        p += "/"
    if repo.lower().startswith(p.lower()):
        return repo
    return p + repo


def _norm_repo(url):
    """归一化仓库地址，用于「已安装」比对。"""
    u = str(url or "").strip().lower()
    u = u[:-4] if u.endswith(".git") else u
    return u.rstrip("/")


#: 商店条目的名字常带这些前后缀，本地目录名 / 清单 id 未必带 → 比对前先剥掉。
_ALIAS_STRIP = ("ilbb_plugin_", "ilbb-plugin-", "ilbb_", "ilbb-",
                "plugin_", "plugin-", "ilbbplugin")


def _alias_key(text):
    """插件身份别名：小写 + 剥常见前后缀 + 去分隔符。

    ``ilbb_plugin_example`` / ``ilbb-plugin-example`` / ``example`` 都会归到
    ``example`` —— 这样商店条目才能认出「手工放进 plugins/ 的同一个插件」。
    """
    s = str(text or "").strip().lower()
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    for pre in _ALIAS_STRIP:
        if s.startswith(pre):
            s = s[len(pre):]
            break
    return re.sub(r"[^a-z0-9]+", "", s)


def _git_remote(folder):
    """从 ``.git/config`` 读 origin 地址（不调用 git 命令；读不到返回 ``''``）。

    只用于「这个目录是从哪个仓库来的」这一条线索，读不到不影响其它判断。
    """
    dot = os.path.join(folder, ".git")
    cfg = os.path.join(dot, "config")
    if os.path.isfile(dot):                     # worktree / submodule：.git 是个文件
        try:
            with open(dot, "r", encoding="utf-8", errors="replace") as f:
                line = f.readline().strip()
            if line.lower().startswith("gitdir:"):
                cfg = os.path.join(line.split(":", 1)[1].strip(), "config")
        except Exception:
            return ""
    if not os.path.isfile(cfg):
        return ""
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return ""
    m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', text)
    return m.group(1).strip() if m else ""


def repo_of_clone_url(url):
    """把带前缀的地址还原成裸仓库地址（用于已安装比对 / 展示）。"""
    u = str(url or "").strip()
    m = re.search(r"https?://github\.com/[\w.\-]+/[\w.\-]+", u, re.I)
    if m:
        return m.group(0)
    for p in proxies():
        pre = p["prefix"]
        if u.lower().startswith(pre.lower()):
            return u[len(pre):]
    return u


def repo_name(url):
    """从仓库地址里取目录名。"""
    u = str(url or "").strip().rstrip("/")
    u = u[:-4] if u.lower().endswith(".git") else u
    name = u.rsplit("/", 1)[-1]
    return name or "plugin"


def safe_folder(name):
    """目录名规范化：只留字母数字下划线连字符，且不能以 . 或 _ 开头。"""
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(name or "")).strip("_")
    s = s.strip("-.") or "plugin"
    if s[0] in "._-":
        s = "p" + s
    s = s[:64].rstrip("-_.")
    if len(s) < 2:
        s = (s + "_plugin")[:64]
    return s


# ----------------------------------------------------------------------------
# 装过什么（plugins_store.json）
# ----------------------------------------------------------------------------
def _state_path():
    root = getattr(config, "ROOT", os.getcwd())
    return os.path.join(root, STATE_NAME)


def _load_installed():
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("installed"), dict):
            return data["installed"]
    except Exception:
        pass
    return {}


def _save_installed(items):
    path = _state_path()
    tmp = path + ".tmp"
    data = {"version": 1, "installed": items}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def disk_index():
    """扫描 plugins/ 里**真实存在**的插件目录（有 plugin.json 才算），返回记录列表。

    这是安装状态的事实来源：手工 clone / 复制进去、或 plugins_store.json 丢过，
    只要目录还在，就应当被认成「已安装」。
    """
    root = _plugin_root_safe()
    out = []
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return out
    for name in names:
        if name.startswith((".", "_")):
            continue
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or not _looks_like_plugin(folder):
            continue
        man = {}
        try:
            with open(os.path.join(folder, MANIFEST_NAME), "r", encoding="utf-8") as f:
                loaded = json.load(f)
            man = loaded if isinstance(loaded, dict) else {}
        except Exception:
            man = {}
        out.append({
            "folder": name,
            "path": folder,
            "id": str(man.get("id") or name),
            "name": str(man.get("name") or ""),
            "version": str(man.get("version") or ""),
            "author": str(man.get("author") or ""),
            "repo": _norm_repo(_git_remote(folder)),
            "source": "disk",
        })
    return out


def _aliases_of(rec):
    """一个本地插件目录可能被商店认出来的名字集合。"""
    keys = set()
    for field in ("folder", "id", "name"):
        k = _alias_key(rec.get(field))
        if k:
            keys.add(k)
    return keys


def _item_keys(item):
    """商店条目可能对应的「仓库地址集合 + 别名集合」。"""
    repos, aliases = set(), set()
    for field in ("clone_url", "repo", "ssh_url"):
        k = _norm_repo(item.get(field))
        if k:
            repos.add(k)
    for ver in item.get("versions") or []:
        if isinstance(ver, dict):
            k = _norm_repo(ver.get("clone_url") or ver.get("repo"))
            if k:
                repos.add(k)
    for field in ("name", "slug", "repo_full_name", "chinese_name"):
        k = _alias_key(item.get(field))
        if k:
            aliases.add(k)
    return repos, aliases


def installed_lookup():
    """安装状态总索引：**以本地磁盘为准**，再用安装记录补来源信息。

    返回 ``{"folders", "by_repo", "by_alias", "stale"}``：

    * ``folders`` —— {目录名: 记录}，磁盘上有 plugin.json 的目录一定在里面（``source='disk'``）；
      命中 ``plugins_store.json`` 记录时补 ``tracked=True`` 与安装来源（代理 / 分支 / 时间）。
    * ``stale`` —— 记录里写了但目录已经不在了的（这些**不再**算「已安装」）。
    """
    root = _plugin_root_safe()
    folders, by_repo, by_alias, stale = {}, {}, {}, []

    for rec in disk_index():
        folders[rec["folder"]] = rec

    for folder, raw in _load_installed().items():
        if not isinstance(raw, dict):
            continue
        key = safe_folder(folder)
        if not os.path.isdir(os.path.join(root, key)):
            stale.append({"folder": folder,
                          "repo": str(raw.get("repo") or raw.get("clone_url") or "")})
            continue
        rec = folders.get(key)
        if rec is None:
            continue
        rec["tracked"] = True
        rec["installed_at"] = str(raw.get("installed_at") or "")
        rec["proxy_label"] = str(raw.get("proxy_label") or "")
        rec["branch"] = str(raw.get("branch") or "")
        if not rec.get("repo"):
            rec["repo"] = _norm_repo(raw.get("repo") or raw.get("clone_url"))

    for rec in folders.values():
        rec.setdefault("tracked", False)
        repo = rec.get("repo") or ""
        if repo:
            by_repo.setdefault(repo, []).append(rec)
        for alias in _aliases_of(rec):
            by_alias.setdefault(alias, []).append(rec)

    return {"folders": folders, "by_repo": by_repo, "by_alias": by_alias, "stale": stale}


def installed_index():
    """{归一化仓库地址: [记录, ...]}（保留给旧调用点）。"""
    return installed_lookup()["by_repo"]


def reconcile_state():
    """把 ``plugins_store.json`` 里「目录已经不在了」的记录清掉（磁盘为准）。

    返回清掉的条数。只在真有变化时才写文件。
    """
    state = _load_installed()
    if not state:
        return 0
    root = _plugin_root_safe()
    keep, dropped = {}, []
    for folder, rec in state.items():
        if os.path.isdir(os.path.join(root, safe_folder(folder))):
            keep[folder] = rec
        else:
            dropped.append(folder)
    if not dropped:
        return 0
    try:
        _save_installed(keep)
    except Exception as e:
        _log("清理失效安装记录失败：%s" % e)
        return 0
    _log("清理 %d 条失效安装记录（目录已不在）：%s" % (len(dropped), "、".join(dropped)))
    return len(dropped)


def _drop_record(folder):
    """从 ``plugins_store.json`` 里删掉一个目录的记录。"""
    try:
        items = _load_installed()
        if folder in items:
            items.pop(folder, None)
            _save_installed(items)
            return True
    except Exception:
        pass
    return False


# ----------------------------------------------------------------------------
# 插件源（PSS）列表
# ----------------------------------------------------------------------------
def _fetch_store(q="", tag="", author=""):
    if requests is None:
        return {"ok": False, "error": "缺少 requests 库，无法访问插件源"}
    base = store_url()
    if not base:
        return {"ok": False, "error": "没有配置插件源地址（PLUGIN_STORE_URL）"}
    params = {}
    if q:
        params["q"] = q
    if tag:
        params["tag"] = tag
    if author:
        params["author"] = author
    try:
        r = requests.get(base + "/api/plugins", params=params,
                         timeout=store_timeout(), headers={"User-Agent": UA})
    except Exception as e:
        return {"ok": False, "error": "连不上插件源 %s：%s" % (base, e)}
    if r.status_code != 200:
        return {"ok": False, "error": "插件源返回 HTTP %s" % r.status_code}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": "插件源返回的不是 JSON，确认地址是否正确"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "插件源返回格式异常"}
    return {"ok": True, "data": data}


def _decorate(item, lookup):
    """给源站记录补上「已安装」等本地信息。

    判定顺序：**仓库地址精确匹配**优先（最可靠），其次才用「插件名别名」弱匹配
    （``ilbb_plugin_example`` ↔ 本地 ``example``）。命中的目录来自本地磁盘扫描，
    所以手工放进 plugins/ 的插件同样会被标成已安装。
    """
    rec = dict(item) if isinstance(item, dict) else {}
    repos, aliases = _item_keys(rec)
    hits, matched_by = [], ""
    for key in sorted(repos):
        got = lookup["by_repo"].get(key) or []
        if got:
            hits, matched_by = list(got), "repo"
            break
    if not hits:
        for alias in sorted(aliases):
            got = lookup["by_alias"].get(alias) or []
            if got:
                hits, matched_by = list(got), "alias"
                break
    seen, uniq = set(), []
    for h in hits:
        folder = h.get("folder")
        if folder and folder not in seen:
            seen.add(folder)
            uniq.append(h)
    rec["installed"] = bool(uniq)
    rec["installed_folders"] = [h["folder"] for h in uniq]
    rec["installed_ids"] = [h.get("id") for h in uniq if h.get("id")]
    rec["installed_entries"] = [{
        "folder": h.get("folder"), "id": h.get("id"), "version": h.get("version"),
        "author": h.get("author"), "tracked": bool(h.get("tracked")),
        "source": "store" if h.get("tracked") else "disk",
    } for h in uniq]
    rec["install_source"] = ("store" if any(h.get("tracked") for h in uniq)
                             else ("disk" if uniq else ""))
    rec["installed_matched_by"] = matched_by
    return rec


def list_plugins(q="", tag="", author="", force=False):
    """商店插件列表（带 TTL 缓存）。"""
    if not store_enabled():
        return {"ok": False, "error": "插件商店已在设置里关闭（PLUGIN_STORE_ENABLED=false）"}
    base = store_url()
    ckey = "|".join([base, str(q), str(tag), str(author)])
    now = time.time()
    with _lock:
        if (not force and _cache["data"] is not None and _cache["key"] == ckey
                and now - _cache["ts"] < store_ttl()):
            cached = dict(_cache["data"])
            cached["cached"] = True
            return cached

    resp = _fetch_store(q, tag, author)
    if not resp.get("ok"):
        return resp
    data = resp["data"]
    items = data.get("plugins")
    items = items if isinstance(items, list) else []
    reconcile_state()                       # 先把「目录已消失」的记录清掉，再算安装状态
    lookup = installed_lookup()
    out = [_decorate(it, lookup) for it in items]
    result = {
        "ok": True,
        "source": base,
        "store_url": base,
        "total": data.get("total", len(out)),
        "plugins": out,
        "updated_at": data.get("updated_at"),
        "cached": False,
        "can_install": git_available(),
        "installed_count": len(lookup["folders"]),
        "tracked_count": sum(1 for r in lookup["folders"].values() if r.get("tracked")),
        "stale_count": len(lookup["stale"]),
        "updated": int(now),
    }
    with _lock:
        _cache["key"] = ckey
        _cache["ts"] = now
        _cache["data"] = result
    return result


def clear_cache():
    with _lock:
        _cache["data"] = None
        _cache["ts"] = 0.0
        _cache["key"] = ""


def detail(key):
    """单个插件详情（源站 /api/plugins/<key>），补上本地安装信息。"""
    if not store_enabled():
        return {"ok": False, "error": "插件商店已在设置里关闭"}
    base = store_url()
    key = str(key or "").strip()
    if not base or not key:
        return {"ok": False, "error": "缺少插件标识"}
    if requests is None:
        return {"ok": False, "error": "缺少 requests 库"}
    try:
        r = requests.get(base + "/api/plugins/" + key, timeout=store_timeout(),
                         headers={"User-Agent": UA})
    except Exception as e:
        return {"ok": False, "error": "连不上插件源：%s" % e}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": "插件源返回的不是 JSON"}
    if not isinstance(data, dict) or not data.get("ok"):
        err = data.get("error") if isinstance(data, dict) else None
        return {"ok": False, "error": err or "插件源没有这个插件"}
    rec = data.get("plugin") or {}
    reconcile_state()
    return {"ok": True, "plugin": _decorate(rec, installed_lookup()),
            "manifest": data.get("manifest") or {}, "store_url": base}


# ----------------------------------------------------------------------------
# 测速
# ----------------------------------------------------------------------------
def _probe(prefix, repo):
    """请求 <候选>/info/refs?service=git-upload-pack —— git smart-http 的真实入口。"""
    base = apply_proxy(prefix, repo)
    url = base + "/info/refs?service=git-upload-pack"
    res = {"ok": False, "ms": None, "status": None, "error": ""}
    if requests is None:
        res["error"] = "缺少 requests 库"
        return res
    to = store_timeout()
    t0 = time.perf_counter()
    try:
        r = requests.get(url, stream=True, timeout=(min(6, to), to),
                         headers={"User-Agent": UA, "Accept": "*/*"})
        res["status"] = r.status_code
        head_ms = int((time.perf_counter() - t0) * 1000)
        try:
            chunk = r.raw.read(64)
        finally:
            r.close()
        first_ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            res["error"] = "HTTP %s" % r.status_code
            res["ms"] = head_ms
            return res
        if not chunk:
            res["error"] = "没拿到数据"
            res["ms"] = head_ms
            return res
        res["ok"] = True
        res["ms"] = first_ms
        res["ttfb_ms"] = head_ms
    except Exception as e:
        res["error"] = _brief(e)
        res["ms"] = int((time.perf_counter() - t0) * 1000)
    return res


def _brief(e):
    s = str(e)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:160] or e.__class__.__name__


def speedtest(repo_url="", only=""):
    """对候选地址并发测速，返回按候选顺序排列的结果 + 最快那个的 id。

    only 传候选 id（序号字符串）时只测那一条（「测当前线路」按钮用）。
    """
    if not store_enabled():
        return {"ok": False, "error": "插件商店已在设置里关闭"}
    repo = str(repo_url or "").strip() or test_repo()
    if not repo.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "仓库地址不合法"}
    cands = candidates()
    pick = str(only if only is not None else "").strip()
    if pick != "":
        kept = [c for c in cands if str(c["id"]) == pick or c["prefix"] == pick]
        if not kept:
            return {"ok": False, "error": "没找到这条线路"}
        cands = kept
    started = time.time()
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(cands)))) as pool:
        probes = list(pool.map(lambda c: _probe(c["prefix"], repo), cands))
    results = []
    for c, p in zip(cands, probes):
        results.append({
            "id": c["id"],
            "label": c["label"],
            "prefix": c["prefix"],
            "direct": c["direct"],
            "url": apply_proxy(c["prefix"], repo),
            "ok": p["ok"],
            "ms": p["ms"],
            "ttfb_ms": p.get("ttfb_ms"),
            "status": p.get("status"),
            "error": p["error"],
        })
    okers = [r for r in results if r["ok"]]
    for r in results:
        r["best"] = False
    best = None
    if okers:
        best = min(okers, key=lambda r: (r["ms"] if r["ms"] is not None else 10 ** 9))
        best["best"] = True
    return {
        "ok": True,
        "repo": repo,
        "results": results,
        "best": best["id"] if best else None,
        "best_label": best["label"] if best else "",
        "best_prefix": best["prefix"] if best else "",
        "best_ms": best["ms"] if best else None,
        "ok_count": len(okers),
        "total": len(results),
        "elapsed": round(time.time() - started, 2),
        "store_timeout": store_timeout(),
    }


# ----------------------------------------------------------------------------
# git
# ----------------------------------------------------------------------------
def git_available():
    try:
        r = subprocess.run([git_bin(), "--version"], capture_output=True,
                           timeout=10, encoding="utf-8", errors="replace")
        return r.returncode == 0
    except Exception:
        return False


def _git_env():
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"        # 绝不卡在交互式账号密码
    env["GIT_ASKPASS"] = "echo"
    env["GCM_INTERACTIVE"] = "never"
    env["LC_ALL"] = "C.UTF-8"
    return env


def git_version():
    try:
        r = subprocess.run([git_bin(), "--version"], capture_output=True,
                           timeout=10, encoding="utf-8", errors="replace")
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return _brief(e)


def _looks_like_plugin(folder):
    return os.path.isfile(os.path.join(folder, MANIFEST_NAME))


def _flatten(folder):
    """仓库根目录没有 plugin.json，而唯一的非隐藏子目录里有 → 把内容提到根目录。"""
    if _looks_like_plugin(folder):
        return ""
    try:
        subs = [n for n in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, n)) and not n.startswith(".")]
    except Exception:
        return ""
    if len(subs) != 1:
        return ""
    inner = os.path.join(folder, subs[0])
    if not _looks_like_plugin(inner):
        return ""
    moved = []
    for name in sorted(os.listdir(inner), reverse=True):
        src = os.path.join(inner, name)
        dst = os.path.join(folder, name)
        if os.path.exists(dst):
            return ""                       # 有同名冲突就整体放弃，保持原样
        shutil.move(src, dst)
        moved.append(name)
    try:
        os.rmdir(inner)
    except Exception:
        pass
    return subs[0]


def install(repo_url, proxy="", branch="", name="", force=False):
    """git clone 到 plugins/ 下，然后重扫一次让热重载认出来。"""
    if not store_enabled():
        return {"ok": False, "error": "插件商店已在设置里关闭"}
    repo = str(repo_url or "").strip()
    if not repo.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "仓库地址不合法（必须是 http/https）"}
    if not git_available():
        return {"ok": False, "error": "系统里找不到 git，请先安装 git 并确认在 PATH 里"}

    try:
        import plugin_manager
    except Exception as e:
        return {"ok": False, "error": "plugin_manager 模块不可用：%s" % e}

    prefix = find_prefix(proxy)
    url = apply_proxy(prefix, repo)
    cands = candidates()
    label = next((c["label"] for c in cands if c["prefix"] == prefix),
                 "原 GitHub（直连）" if not prefix else prefix)
    root = plugin_manager.plugin_root()
    folder = safe_folder(name or repo_name(repo))
    target = os.path.join(root, folder)
    if os.path.exists(target):
        if not force:
            return {"ok": False, "error": "plugins/%s 已经存在，换个名字或先删掉它" % folder,
                    "folder": folder, "exists": True}
        if not _rmtree_force(target):
            return {"ok": False, "error": "无法覆盖 plugins/%s：旧目录删不掉（可能被占用）" % folder}

    branch = str(branch or "").strip()
    cmd = [git_bin(), "-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30",
           "clone", "--depth", str(git_depth()), "--single-branch", "--no-tags"]
    if branch:
        cmd += ["--branch", branch]
    cmd += ["--", url, target]

    _log("开始安装 %s（%s）→ plugins/%s" % (repo, label, folder))
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=git_timeout(),
                              encoding="utf-8", errors="replace",
                              env=_git_env(), cwd=getattr(config, "ROOT", None) or None)
    except subprocess.TimeoutExpired:
        _rm(target)
        return {"ok": False, "error": "下载超时（%s 秒），换个加速地址试试" % git_timeout(),
                "url": url, "folder": folder}
    except FileNotFoundError:
        return {"ok": False, "error": "系统里找不到 git"}
    except Exception as e:
        _rm(target)
        return {"ok": False, "error": "git 执行失败：%s" % _brief(e)}

    if proc.returncode != 0:
        tail = _tail(proc.stderr or proc.stdout)
        _rm(target)
        return {"ok": False, "error": "git clone 失败", "detail": tail,
                "url": url, "folder": folder, "code": proc.returncode}

    flattened = _flatten(target)
    if not _looks_like_plugin(target):
        _rm(target)
        return {"ok": False,
                "error": "下载完成，但仓库里没有 plugin.json，不像一个 ILBB 插件（已清理）",
                "url": url}

    # 记录「装过什么」
    try:
        items = _load_installed()
        items[folder] = {
            "repo": repo_of_clone_url(repo),
            "clone_url": repo,
            "url": url,
            "proxy": prefix,
            "proxy_label": label,
            "branch": branch or "default",
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_installed(items)
    except Exception as e:
        _log("写 plugins_store.json 失败：%s" % e)

    # 立刻重扫，热重载会认出新目录
    pid = ""
    plugins = []
    try:
        plugin_manager.reload(None)
        summary = plugin_manager.list_plugins()
        for it in summary.get("plugins") or []:
            plugins.append(it.get("id"))
            if os.path.normpath(it.get("folder") or "") == os.path.normpath(target):
                pid = it.get("id") or ""
        if not pid:
            pid = os.path.basename(target)
    except Exception as e:
        _log("安装后重扫失败：%s" % e)

    clear_cache()
    elapsed = round(time.time() - t0, 2)
    _log("安装完成 plugins/%s → id=%s，耗时 %ss" % (folder, pid, elapsed))

    # 撞 id 检查：插件 id 全局唯一，两个目录声明同一个 id 时热重载只会留一个
    # （规则和 plugin_manager._scan 一致：目录名和 id 一致的那个生效）
    warn = ""
    try:
        man, _err = plugin_manager._read_manifest(target)
        new_id = (man or {}).get("id") or ""
        if new_id:
            for name in sorted(os.listdir(root)):
                sib = os.path.join(root, name)
                if os.path.normpath(sib) == os.path.normpath(target):
                    continue
                if name.startswith((".", "_")) or not os.path.isdir(sib):
                    continue
                sman, _e2 = plugin_manager._read_manifest(sib)
                if sman and sman.get("id") == new_id:
                    # 目录名 == id 的那个算"正主"，另一个会被扫描阶段忽略
                    ours_win = (folder == new_id) and (name != new_id)
                    loser = name if ours_win else folder
                    warn = ("插件 id「%s」和 plugins/%s 重复了，只会生效一个；"
                            "plugins/%s 会被忽略。删掉其中一个，或改掉新插件的 id。"
                            % (new_id, name, loser))
                    _log("警告：%s" % warn)
                    break
    except Exception:
        pass

    return {
        "ok": True,
        "id": pid,
        "folder": folder,
        "path": target,
        "repo": repo_of_clone_url(repo),
        "url": url,
        "proxy": prefix,
        "proxy_label": label,
        "branch": branch or "default",
        "depth": git_depth(),
        "flattened": flattened,
        "elapsed": elapsed,
        "plugins": sorted(plugins),
        "warn": warn,
        "msg": "已装到 plugins/%s，已自动识别为插件 %s" % (folder, pid or folder),
    }


def _rmtree_force(path):
    """删目录，遇到只读文件先摘掉只读位再删。

    Windows 上 git clone 出来的 ``.git/objects/pack/*.idx`` / ``*.pack`` 是只读的，
    裸 ``shutil.rmtree`` 会直接抛 ``[WinError 5] 拒绝访问``；这里在出错回调里
    ``chmod +w`` 后重试一次，跨平台都安全。
    """
    def _onerr(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except Exception:
            pass

    try:
        if os.path.isdir(path):
            shutil.rmtree(path, onerror=_onerr)
    except Exception:
        pass
    return not os.path.exists(path)


def _rm(path):
    """尽力清理一个半成品目录，失败也不抛（安装失败回滚用）。"""
    _rmtree_force(path)


def _tail(text, limit=900):
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return "…" + s[-limit:]


# ----------------------------------------------------------------------------
# 概览 / 卸载
# ----------------------------------------------------------------------------
def status():
    """商店概览：给前端一行式状态条用。"""
    reconcile_state()
    lookup = installed_lookup()
    return {
        "ok": True,
        "enabled": store_enabled(),
        "store_url": store_url(),
        "store_timeout": store_timeout(),
        "ttl": store_ttl(),
        "test_repo": test_repo(),
        "git": {"available": git_available(), "bin": git_bin(),
                "version": git_version(), "timeout": git_timeout(), "depth": git_depth()},
        "proxy_count": len(proxies()),
        "candidates": candidates(),
        "installed": _load_installed(),
        "disk": list(lookup["folders"].values()),
        "stale": lookup["stale"],
        "installed_count": len(lookup["folders"]),
        "state_path": _state_path(),
        "root": _plugin_root_safe(),
    }


def _plugin_root_safe():
    try:
        import plugin_manager
        return plugin_manager.plugin_root()
    except Exception:
        return getattr(config, "PLUGIN_DIR", "plugins")


def _pid_of_folder(path):
    """按目录路径反查插件 id（目录还没被扫描到时返回空串）。"""
    try:
        import plugin_manager
        summary = plugin_manager.list_plugins()
    except Exception:
        return ""
    target = os.path.normpath(path)
    for it in summary.get("plugins") or []:
        if os.path.normpath(str(it.get("folder") or "")) == target:
            return str(it.get("id") or "")
    return ""


def uninstall(folder, remove_files=True):
    """从 plugins/ 里删掉一个插件目录（危险操作，需前端二次确认）。

    顺序很重要：**先卸运行实例再删目录**。插件的 ``teardown()`` 会关掉自己
    打开的数据库 / Web 端口；带着这些句柄删目录，在 Windows 上会直接
    ``WinError 32`` 删不掉（表现为「卸载按钮点了没反应」）。删完再清掉它的
    安装记录与 ``plugins_config.json`` 里的配置，最后重扫让列表立刻刷新。
    """
    folder = str(folder or "").strip().strip("/\\")
    if not folder:
        return {"ok": False, "error": "缺少目录名"}
    try:
        import plugin_manager
        root = plugin_manager.plugin_root()
    except Exception as e:
        return {"ok": False, "error": "plugin_manager 模块不可用：%s" % e}
    safe = safe_folder(folder)
    target = os.path.join(root, safe)
    if os.path.normpath(os.path.dirname(target)) != os.path.normpath(root):
        return {"ok": False, "error": "目录不合法"}

    if not os.path.isdir(target):
        # 目录本来就不在了：把残留记录清掉，让商店状态跟着回到「未安装」
        dropped = _drop_record(safe)
        reconcile_state()
        clear_cache()
        return {"ok": False, "error": "plugins/%s 不存在" % safe,
                "missing": True, "folder": safe, "record_dropped": dropped}

    pid = _pid_of_folder(target)
    prev_enabled = False
    was_loaded = False
    if pid:
        try:
            for it in (plugin_manager.list_plugins().get("plugins") or []):
                if str(it.get("id")) == pid:
                    prev_enabled = bool(it.get("enabled"))
                    was_loaded = bool(it.get("loaded"))
                    break
        except Exception:
            pass

    # 1) 先卸运行实例（会调用插件 teardown，释放数据库 / 端口句柄）
    unloaded = False
    if pid and was_loaded:
        try:
            plugin_manager.set_enabled(pid, False)
            unloaded = True
        except Exception as e:
            _log("卸载前热禁用 %s 失败（继续删目录）：%s" % (pid, e))

    # 2) 删目录
    if remove_files:
        if not _rmtree_force(target):
            if unloaded and pid:            # 删不掉就把插件恢复原状，别留在半死状态
                try:
                    plugin_manager.set_enabled(pid, prev_enabled)
                except Exception:
                    pass
            return {"ok": False,
                    "error": "删除失败：plugins/%s 里还有文件删不掉"
                             "（常见于目录被占用，关掉编辑器 / 杀毒软件后再试）" % safe,
                    "folder": safe}

    # 3) 清安装记录 + 插件配置
    dropped = _drop_record(safe)
    forgot = False
    if pid:
        try:
            forget = getattr(plugin_manager, "forget", None)
            forgot = bool(forget(pid).get("ok")) if callable(forget) else False
        except Exception as e:
            _log("清理插件 %s 的配置失败：%s" % (pid, e))

    # 4) 重扫目录并清商店缓存，让插件列表 / 商店「已安装」立刻一致
    try:
        plugin_manager.reload(None)
    except Exception as e:
        _log("卸载后重扫失败：%s" % e)
    clear_cache()

    _log("已卸载 plugins/%s%s" % (safe, ("（插件 %s）" % pid) if pid else ""))
    return {
        "ok": True, "folder": safe, "id": pid,
        "unloaded": unloaded, "config_forgot": forgot, "record_dropped": dropped,
        "msg": "已删除 plugins/%s%s" % (safe, ("（插件 %s）" % pid) if pid else ""),
    }

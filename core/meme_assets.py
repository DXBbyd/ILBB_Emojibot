# -*- coding: utf-8 -*-
"""Meme 素材（表情图片）校验 / 下载 / 补全。

为什么不用上游自带的 `meme download`：
    vendor/meme-generator-main/meme_generator/cli.py 的 download 子命令**只有 --url**
    （换镜像源），落地目录在 download.py 里写死成「包目录 / memes」，
    没有任何参数能指定目标文件夹。
本模块按上游同一套资源规则自行实现，目标目录可选（默认仍是引擎包内 memes/，
这样 meme_generator 才能读到）：

    素材目录 = .env 的 MEME_ASSET_DIR（留空 = 引擎包内 memes/）
    资源清单 = {镜像}v{版本}/resources/resource_list.json
    资源文件 = {镜像}v{版本}/meme_generator/memes/{path}

清单每项形如 {"path": "图片相对路径", "hash": "该文件的 md5"}。

对外接口：
    asset_dir()        当前素材目录
    scan()             本地素材 vs 清单：总数 / 已有 / 缺失 / 损坏
    start_job()        后台补齐下载（进度用 job_snapshot() 查）
    job_snapshot()     下载任务快照

命令行（便于脱离 WebUI 手动补素材）：
    python meme_assets.py check             只体检，不下载
    python meme_assets.py download          补齐缺失素材
    python meme_assets.py download --dir D  下载到指定文件夹
"""
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import config

RESOURCE_LIST_NAME = "resources/resource_list.json"
ASSET_URL_PREFIX = "meme_generator/memes/"
MANIFEST_CACHE_NAME = "meme_resource_list.json"   # 清单磁盘缓存，落在 CACHE_DIR
# 超时拆两段：连不上就快速放弃（10s），连上了就给慢速 CDN 足够的传输时间。
# 实测 CDN 首次回源单个素材要 20~125s，单段 20s 会把「慢但能用」的镜像误判成坏的。
TIMEOUT = 60               # 读超时
CONNECT_TIMEOUT = 10       # 连接超时
# 并发数：瓶颈是「每个文件的往返延迟」而不是带宽，并发高一点才能把冷回源的文件叠起来
DEFAULT_WORKERS = 16
CHUNK = 1 << 16

_UA = {"User-Agent": "ILBB-setup/1.0 (meme asset fetcher)"}

# 上游默认镜像（meme_generator/config.py 的 ResourceConfig.resource_urls）
# 注意：不要依赖这个书写顺序 —— 实际顺序由 rank_bases() 探测后决定。
# 实测（国内网络）：jsdelivr 两站 ~3s，raw.githubusercontent ~83s，ghproxy/raw.gitmirror 已失效。
_DEFAULT_BASES = [
    "https://cdn.jsdelivr.net/gh/MemeCrafters/meme-generator@",
    "https://fastly.jsdelivr.net/gh/MemeCrafters/meme-generator@",
    "https://raw.githubusercontent.com/MemeCrafters/meme-generator/",
    "https://mirror.ghproxy.com/https://raw.githubusercontent.com/MemeCrafters/meme-generator/",
    "https://raw.gitmirror.com/MemeCrafters/meme-generator/",
]

# 镜像健康度（排序 + 冷板凳），避免逐个文件在死镜像上白等 timeout
MIRROR_RANK_NAME = "meme_mirror_rank.json"   # 排序缓存，落在 CACHE_DIR
PROBE_TIMEOUT = 6          # 探活单个镜像的超时（清单本身很小，6s 足够）
RANK_TTL = 6 * 3600        # 排序结果有效期：6 小时
FAIL_COOLDOWN = 180        # 某镜像刚失败 → 3 分钟内降到队尾，不再优先尝试
FAIL_STRIKES = 3           # 连续失败这么多次才进冷板凳（单次超时很常见，别一棒子打死）

_base_lock = threading.Lock()
_base_rank = []            # 探测出来的「快 → 慢」镜像顺序
_base_rank_at = 0
_base_fail = {}            # base -> 冷板凳截止时间戳
_base_strike = {}          # base -> 连续失败次数（成功即清零）
_base_good = ""            # 最近成功的镜像：粘性优选，后续文件先走它

# 每个下载线程复用一个 Session：省掉每个文件的 TLS 握手，冷启动成本能砍掉一截
_local = threading.local()


# ---------------------------------------------------------------------------
# 目录 / 版本 / 镜像
# ---------------------------------------------------------------------------
def engine_version():
    """meme 引擎版本号（决定资源 URL 里的 vX.Y.Z 段）。"""
    try:
        from meme_generator.version import __version__
        return str(__version__).strip()
    except Exception:
        return ""


def engine_dir():
    """meme_generator 包目录（vendor/meme-generator-main/meme_generator）。"""
    try:
        import meme_generator
        return os.path.dirname(os.path.abspath(meme_generator.__file__))
    except Exception:
        return ""


def asset_dir():
    """素材目录：优先 .env 的 MEME_ASSET_DIR，留空则用引擎包内 memes/。"""
    raw = (getattr(config, "MEME_ASSET_DIR", "") or "").strip()
    if raw:
        return config.get_path("MEME_ASSET_DIR", raw)
    d = engine_dir()
    return os.path.join(d, "memes") if d else ""


def resource_bases():
    """候选镜像前缀（尾部带 / 或 @，与上游 _resource_url 的拼法一致）。

    顺序：.env 的 MEME_RESOURCE_BASE → 引擎自带 resource_url / resource_urls → 内置兜底镜像。
    """
    out = []
    env_base = (getattr(config, "MEME_RESOURCE_BASE", "")
                or os.environ.get("MEME_RESOURCE_BASE") or "").strip()
    if env_base:
        out.append(env_base)
    try:
        from meme_generator.config import meme_config
        r = meme_config.resource
        if getattr(r, "resource_url", None):
            out.append(str(r.resource_url))
        for u in (getattr(r, "resource_urls", None) or []):
            out.append(str(u))
    except Exception:
        pass
    out.extend(_DEFAULT_BASES)
    seen, uniq = set(), []
    for u in out:
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _url(base, name):
    return "%sv%s/%s" % (base, engine_version(), name)


# ---------------------------------------------------------------------------
# 资源清单
# ---------------------------------------------------------------------------
def _manifest_cache_path():
    return os.path.join(config.CACHE_DIR, MANIFEST_CACHE_NAME)


def _read_manifest_cache():
    try:
        with open(_manifest_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("list"), list) and data["list"]:
            return data
    except Exception:
        pass
    return None


def _write_manifest_cache(items, base):
    try:
        p = _manifest_cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"version": engine_version(), "base": base,
                       "saved_at": int(time.time()), "list": items},
                      f, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 镜像健康度：探测排序 + 冷板凳 + 粘性优选
# ---------------------------------------------------------------------------
def _rank_cache_path():
    return os.path.join(config.CACHE_DIR, MIRROR_RANK_NAME)


def _read_rank_cache():
    try:
        with open(_rank_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("order"), list) and data["order"]:
            if int(time.time()) - int(data.get("saved_at") or 0) < RANK_TTL:
                return [str(b) for b in data["order"]]
    except Exception:
        pass
    return []


def _write_rank_cache(order):
    try:
        p = _rank_cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"saved_at": int(time.time()), "version": engine_version(),
                       "order": list(order)}, f, ensure_ascii=False)
    except Exception:
        pass


def _probe_bases(bases, timeout=PROBE_TIMEOUT):
    """并发探活：用资源清单（很小的 JSON）测各镜像，按「可用优先 → 延迟升序」排序。"""
    def probe(base):
        t0 = time.time()
        try:
            with requests.Session() as s:
                r = s.get(_url(base, RESOURCE_LIST_NAME), timeout=timeout, headers=_UA)
            ok = r.status_code == 200 and len(r.content) > 2
        except Exception:
            ok = False
        return (0 if ok else 1, round(time.time() - t0, 3), base)

    try:
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(bases)))) as pool:
            rows = list(pool.map(probe, bases))
    except Exception:
        return []
    rows.sort()
    return [b for _flag, _dt, b in rows]


def rank_bases(bases=None, force=False, timeout=PROBE_TIMEOUT):
    """给出实际尝试顺序：快的排前面，死镜像排最后（结果缓存 6 小时，落盘可复用）。

    探测全失败时退回原始顺序，绝不因为排序把下载卡住。
    """
    global _base_rank, _base_rank_at
    bases = list(bases or resource_bases())
    if len(bases) < 2:
        return bases
    now = time.time()
    with _base_lock:
        cached = list(_base_rank) if (not force and _base_rank
                                      and (now - _base_rank_at) < RANK_TTL) else []
    if not cached:
        cached = [] if force else _read_rank_cache()
    if cached:
        order = {b: i for i, b in enumerate(cached)}
        ranked = sorted(bases, key=lambda b: order.get(b, len(order)))
        with _base_lock:
            _base_rank, _base_rank_at = list(ranked), now
        return ranked
    ranked = _probe_bases(bases, timeout=timeout)
    if not ranked:                     # 探测整体失败：保持原顺序
        return bases
    with _base_lock:
        _base_rank, _base_rank_at = list(ranked), now
    _write_rank_cache(ranked)
    return ranked


def _note_base(base, ok):
    """记录镜像成败：成功则粘性优选 + 解除冷板凳；连续失败够次数才进冷板凳。

    冷启动的 CDN 偶发单个文件超时是常态，一次超时就把镜像降级会让剩下的文件
    全部退到 80s 级的备用镜像上，反而整体更慢。
    """
    global _base_good
    with _base_lock:
        if ok:
            _base_good = base
            _base_strike.pop(base, None)
            _base_fail.pop(base, None)
        else:
            n = _base_strike.get(base, 0) + 1
            _base_strike[base] = n
            if n >= FAIL_STRIKES:
                _base_fail[base] = time.time() + FAIL_COOLDOWN


def _thread_session():
    """每个下载线程复用一个 Session，省掉每个文件的握手开销。"""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        _local.session = s
    return s


def _drop_thread_session():
    """连接层出错时丢掉本线程的连接池，下一个文件重新建连，避免一直被坏连接绊住。"""
    s = getattr(_local, "session", None)
    if s is not None:
        try:
            s.close()
        except Exception:
            pass
        _local.session = None


def _order_bases(bases):
    """单次下载时的实际顺序：粘性优选 → 探测排序 → 冷板凳镜像垫底。"""
    now = time.time()
    with _base_lock:
        good = _base_good
        fail = dict(_base_fail)
        rank = list(_base_rank)
    head, mid, tail = [], [], []
    for b in bases:
        if fail.get(b, 0) > now:
            tail.append(b)
        elif b == good:
            head.append(b)
        else:
            mid.append(b)
    if rank:
        order = {b: i for i, b in enumerate(rank)}
        mid.sort(key=lambda b: order.get(b, len(order)))
    return head + mid + tail


def fetch_manifest(timeout=TIMEOUT):
    """联网拉资源清单，按镜像顺序重试。返回 (清单, 命中的镜像) 或 (None, 错误说明)。"""
    version = engine_version()
    if not version:
        return None, "未找到 meme 引擎版本号：vendor/meme-generator-main 是否已就位？"
    last_err = ""
    for base in rank_bases():
        url = _url(base, RESOURCE_LIST_NAME)
        try:
            r = requests.get(url, timeout=(CONNECT_TIMEOUT, timeout), headers=_UA)
            r.raise_for_status()
            data = json.loads(r.content.decode("utf-8"))
            if isinstance(data, list) and data:
                _note_base(base, True)
                return data, base
            last_err = "%s 返回的不是资源清单" % base
        except Exception as e:
            _note_base(base, False)
            last_err = "%s：%s" % (base, e)
    return None, (last_err or "没有可用的资源镜像")


def load_manifest(force=False, timeout=TIMEOUT):
    """取资源清单：默认走磁盘缓存（离线也能校验），force=True 强制联网刷新。

    返回 (清单, 来源)。来源为镜像地址 / 'cache' / 'cache(stale)'；失败返回 (None, 错误说明)。
    """
    if not force:
        cached = _read_manifest_cache()
        if cached:
            return cached["list"], "cache"
    items, base = fetch_manifest(timeout=timeout)
    if items is not None:
        _write_manifest_cache(items, base)
        return items, base
    cached = _read_manifest_cache()
    if cached:
        return cached["list"], "cache(stale)"
    return None, base


# ---------------------------------------------------------------------------
# 本地扫描
# ---------------------------------------------------------------------------
def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(CHUNK), b""):
            h.update(blk)
    return h.hexdigest()


def _safe_join(root, rel):
    """把清单里的相对路径安全地拼到素材目录下（拒绝越界 / 绝对路径）。"""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    root_n = os.path.normpath(root)
    p = os.path.normpath(os.path.join(root_n, rel.replace("/", os.sep)))
    if not p.startswith(root_n + os.sep):
        return None
    return p


def local_stats(d):
    """素材目录里的文件数与总字节数。"""
    files, size = 0, 0
    if d and os.path.isdir(d):
        for root, _dirs, names in os.walk(d):
            for fn in names:
                try:
                    size += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
                files += 1
    return files, size


def _manifest_entries(manifest):
    """清单 → [(相对路径, md5)]，跳过无效项。"""
    out = []
    for item in manifest or []:
        if isinstance(item, dict):
            rel = str(item.get("path") or "").strip()
            want = str(item.get("hash") or "").strip().lower()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            rel, want = str(item[0]).strip(), str(item[1]).strip().lower()
        else:
            continue
        if rel:
            out.append((rel, want))
    return out


def pending_items(manifest, d):
    """待处理项：[{"path", "hash", "reason": missing|broken}]。d 为空时全部视为待下载。"""
    out = []
    for rel, want in _manifest_entries(manifest):
        target = _safe_join(d, rel) if d else None
        if target and os.path.isfile(target):
            continue
        out.append({"path": rel, "hash": want, "reason": "missing"})
    return out


def pending_items_deep(manifest, d):
    """待处理项（含 md5 不符的损坏文件），比 pending_items 慢但更准。"""
    out = []
    for rel, want in _manifest_entries(manifest):
        target = _safe_join(d, rel) if d else None
        if target and os.path.isfile(target):
            if want:
                try:
                    if _md5(target) == want:
                        continue
                except OSError:
                    pass
                out.append({"path": rel, "hash": want, "reason": "broken"})
            continue
        out.append({"path": rel, "hash": want, "reason": "missing"})
    return out


def scan(deep=False, refresh=False, timeout=TIMEOUT):
    """素材体检：本地文件 vs 资源清单。

    deep=True   逐个校验 md5（准，稍慢）
    refresh=True 强制联网刷新清单（默认优先用磁盘缓存，可离线体检）
    """
    d = asset_dir()
    files, size = local_stats(d)
    out = {
        "dir": d,
        "exists": bool(d) and os.path.isdir(d),
        "engine_version": engine_version(),
        "engine_dir": engine_dir(),
        "local_files": files,
        "bytes": size,
        "manifest_source": "",
        "manifest_error": "",
        "total": 0,
        "present": 0,
        "missing": 0,
        "broken": 0,
        "sample": [],
        "complete": False,
        "checked_at": int(time.time()),
    }
    if not d:
        out["manifest_error"] = "未找到 meme 引擎目录，无法确定素材目录"
        return out
    manifest, src = load_manifest(force=refresh, timeout=timeout)
    out["manifest_source"] = str(src)
    if manifest is None:
        out["manifest_error"] = str(src)
        # 拿不到清单时退化判断：目录里有东西就算「不必下载」
        out["complete"] = files > 0
        return out
    entries = _manifest_entries(manifest)
    bad = pending_items_deep(manifest, d) if deep else pending_items(manifest, d)
    reason = {b["path"]: b["reason"] for b in bad}
    out["total"] = len(entries)
    out["missing"] = sum(1 for b in bad if b["reason"] == "missing")
    out["broken"] = sum(1 for b in bad if b["reason"] == "broken")
    out["present"] = len(entries) - len(bad)
    out["sample"] = [b["path"] for b in bad[:20]]
    out["complete"] = not bad
    out["deep"] = bool(deep)
    out["_reason"] = reason
    return out


# ---------------------------------------------------------------------------
# 下载任务（后台线程 + 可查询进度）
# ---------------------------------------------------------------------------
_job_lock = threading.Lock()
_job = {
    "state": "idle",          # idle | running | done | error | cancelled
    "total": 0, "done": 0, "ok": 0, "failed": 0,
    "bytes": 0,               # 已完整落盘的字节（整文件成功才累加）
    "recv": 0,                # 已接收的字节（含正在传输的分片，让进度条能实时动）
    "message": "", "dir": "",
    "cancelling": False,      # 已点取消、但还有请求卡在「等首字节」没收尾
    "started_at": 0, "finished_at": 0,
    "failed_sample": [], "bases": [],
}
_job_cancel = False
_job_thread = None

# 正在传输中的响应对象：thread_id -> requests.Response。
# 取消时逐个 close()，让卡在「等首字节」上的 iter_content 立刻报错退出，
# 否则要等到读超时（60s）才收手，用户点了取消却一直看进度条不动。
_inflight = {}
_inflight_lock = threading.Lock()


def _reg_inflight(r):
    with _inflight_lock:
        _inflight[threading.get_ident()] = r


def _unreg_inflight(r):
    with _inflight_lock:
        if _inflight.get(threading.get_ident()) is r:
            _inflight.pop(threading.get_ident(), None)


def job_snapshot():
    """当前下载任务快照（可直接 json 化给前端）。"""
    with _job_lock:
        snap = dict(_job)
    snap["percent"] = int(snap["done"] * 100 / snap["total"]) if snap["total"] else 0
    # 前端显示用：取「已落盘」与「已接收」的较大值。
    # CDN 冷回源时单个文件可能要几十秒，done 会长时间不动，
    # 这时用实时接收字节数兜底，用户至少能看到进度在走。
    snap["bytes_recv"] = max(int(snap.get("bytes") or 0), int(snap.get("recv") or 0))
    return snap


def cancel_job():
    global _job_cancel
    with _job_lock:
        if _job["state"] != "running":
            return False
        _job_cancel = True
        # 立刻给出反馈：已经建立的连接可以掐断，但「正在等首字节」的请求
        # 要等到读超时才退出（CDN 冷回源实测 TTFB 12~46s）。
        # 用 cancelling 让界面马上能显示「正在取消」，而不是傻等进度条不动。
        _job["cancelling"] = True
        _job["message"] = "正在取消…（已下载 %d 个，等待在途请求收尾）" % _job["ok"]
    with _inflight_lock:
        pending = list(_inflight.values())
    for r in pending:
        try:
            r.close()                        # 阻塞中的 iter_content 会立刻报错返回
        except Exception:
            pass
    return True


def _fetch_file(session, bases, rel, timeout, reuse=False, on_bytes=None):
    """按镜像顺序取一个素材文件的字节内容。

    顺序不是固定的：先走上次成功的镜像（粘性），死过的镜像垫底，
    避免每个文件都在失效镜像上白等一个 timeout。

    用流式读取而不是 r.content：一是能在传输过程中回调已收字节数（进度不再假死），
    二是取消请求能立刻中断正在传输的大文件。
    """
    name = ASSET_URL_PREFIX + rel
    timeout = (CONNECT_TIMEOUT, timeout)     # (连接超时, 读超时)
    for base in _order_bases(bases):
        if _job_cancel:                      # 已取消：连下一个镜像也不必再试
            break
        try:
            r = session.get(_url(base, name), timeout=timeout, headers=_UA, stream=True)
        except Exception:
            if reuse:                        # 复用的连接可能已失效：丢掉重建
                _drop_thread_session()
            _note_base(base, False)          # 连接层失败：记一次
            continue
        if r.status_code == 404:             # 只是这个镜像缺这个文件，不惩罚
            r.close()
            continue
        if r.status_code != 200:
            r.close()
            _note_base(base, False)
            continue
        buf = bytearray()
        broken = False
        _reg_inflight(r)                     # 登记：取消时能从别的线程把它掐断
        try:
            for chunk in r.iter_content(CHUNK):
                if _job_cancel:              # 取消：立刻断开，不再把大文件收完
                    broken = True
                    break
                if not chunk:
                    continue
                buf.extend(chunk)
                if on_bytes:
                    on_bytes(len(chunk))
        except Exception:
            broken = True                    # 传输中断：换下一个镜像
        finally:
            _unreg_inflight(r)
            r.close()
        if broken:
            _note_base(base, False)
            continue
        if buf:
            _note_base(base, True)
            return bytes(buf)
        _note_base(base, False)               # 200 但是空文件
    return None


def _download_one(session, bases, item, d, timeout):
    """下载单个素材：写临时文件 → 校验 md5 → 原子改名。返回 (状态, 字节数, 说明)。"""
    if _job_cancel:                      # 已请求取消：不再发起新的网络请求
        return "skip", 0, "已取消"
    rel = item["path"]
    target = _safe_join(d, rel)
    if not target:
        return "skip", 0, "路径非法：%s" % rel

    def on_bytes(n):
        with _job_lock:
            _job["recv"] += n

    if session is None:                  # 复用本线程的会话（连接池）
        content = _fetch_file(_thread_session(), bases, rel, timeout, reuse=True,
                              on_bytes=on_bytes)
    else:
        content = _fetch_file(session, bases, rel, timeout, on_bytes=on_bytes)
    if content is None:
        return "fail", 0, "下载失败（所有镜像都不通）"
    want = str(item.get("hash") or "").lower()
    if want and hashlib.md5(content).hexdigest() != want:
        return "fail", len(content), "md5 校验不通过"
    tmp = target + ".part"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, target)
    except Exception as e:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return "fail", len(content), "写入失败：%s" % e
    return "ok", len(content), ""


def start_job(workers=DEFAULT_WORKERS, timeout=TIMEOUT, refresh=False, deep=False):
    """启动后台补齐下载。已有任务在跑时返回 ok=False。"""
    global _job_thread, _job_cancel
    with _job_lock:
        if _job["state"] == "running":
            return {"ok": False, "error": "已有下载任务在进行中"}
    d = asset_dir()
    if not d:
        return {"ok": False, "error": "未找到 meme 引擎目录，无法确定素材目录"}
    manifest, src = load_manifest(force=refresh, timeout=timeout)
    if manifest is None:
        return {"ok": False, "error": "拿不到资源清单：%s" % src}
    pending = pending_items_deep(manifest, d) if deep else pending_items(manifest, d)
    if not pending:
        with _job_lock:
            _job.update(state="done", total=0, done=0, ok=0, failed=0, bytes=0,
                        recv=0, cancelling=False, message="素材已完整，无需下载", dir=d,
                        started_at=int(time.time()), finished_at=int(time.time()),
                        failed_sample=[])
        return {"ok": True, "started": False, "total": 0, "dir": d,
                "manifest_source": str(src), "bases": []}
    with _job_lock:
        _job.update(state="running", total=len(pending), done=0, ok=0, failed=0,
                    bytes=0, recv=0, cancelling=False, message="正在选择可用镜像…", dir=d,
                    started_at=int(time.time()), finished_at=0, failed_sample=[],
                    bases=[])
        _job_cancel = False
    # 先探活排序，再开下载：否则每个文件都会在失效镜像上白等一个 timeout
    bases = rank_bases()
    with _job_lock:
        _job["bases"] = list(bases)
        if _job["state"] == "running":
            _job["message"] = "正在下载…"

    def worker():
        global _job_cancel
        fails = []
        pool = ThreadPoolExecutor(max_workers=max(1, int(workers)))
        try:
            items = list(pending)
            # 两轮：第一轮全量，第二轮只补第一轮失败的。
            # CDN 首次回源偶发超时很常见（实测单个文件 20~125s），重试一轮能明显降低最终失败数。
            for round_no in (0, 1):
                if not items or _job_cancel:
                    break
                if round_no:
                    fails = []
                    with _job_lock:
                        if _job["state"] == "running":
                            _job["message"] = "正在重试 %d 个失败素材…" % len(items)
                # session 传 None：任务内部复用「本线程」的连接池，避免一次性建上千个 Session
                futures = {pool.submit(_download_one, None, bases, it, d, timeout): it
                           for it in items}
                # 按「完成顺序」统计：否则遇到慢文件会长时间卡在 0%
                retry = []
                for fut in as_completed(futures):
                    if _job_cancel:
                        break
                    it = futures[fut]
                    try:
                        status, nbytes, note = fut.result()
                    except Exception as e:
                        status, nbytes, note = "fail", 0, str(e)
                    with _job_lock:
                        if round_no == 0:
                            _job["done"] += 1
                        if status == "ok":
                            _job["ok"] += 1
                            _job["bytes"] += nbytes
                            if round_no:                  # 上一轮记过的失败，现在补回来了
                                _job["failed"] = max(0, _job["failed"] - 1)
                        elif status == "fail":
                            if round_no == 0:
                                _job["failed"] += 1
                            retry.append(it)
                            if len(fails) < 30:
                                fails.append("%s：%s" % (it.get("path"), note))
                items = retry
            with _job_lock:
                if _job_cancel:
                    _job["state"] = "cancelled"
                    _job["cancelling"] = False
                    _job["message"] = "已取消（已下载 %d 个）" % _job["ok"]
                elif _job["failed"]:
                    _job["state"] = "error"
                    _job["message"] = "有 %d 个文件下载失败，可重试" % _job["failed"]
                else:
                    _job["state"] = "done"
                    _job["message"] = "素材已补齐（共 %d 个文件）" % _job["ok"]
                _job["failed_sample"] = fails
                _job["finished_at"] = int(time.time())
        except Exception as e:                       # 兜底：线程异常也要落到状态里
            with _job_lock:
                _job["state"] = "error"
                _job["message"] = "下载异常：%s" % e
                _job["finished_at"] = int(time.time())
        finally:
            # 关键：不用 with 语句。ThreadPoolExecutor.__exit__ 会 wait=True，
            # 即便已请求取消也会把队列里剩下的任务全部跑完。
            # 这里丢弃未开始的任务，只等正在执行的几个收尾。
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:                        # Python < 3.9 兜底
                pool.shutdown(wait=False)
            _job_cancel = False

    _job_thread = threading.Thread(target=worker, name="meme-assets-download", daemon=True)
    _job_thread.start()
    return {"ok": True, "started": True, "total": len(pending), "dir": d,
            "manifest_source": str(src)}


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------
def _fmt_mb(n):
    return "%.1f MB" % (n / 1048576.0)


def _print_scan(info):
    print("素材目录 : %s" % (info["dir"] or "(未找到)"))
    print("引擎版本 : %s" % (info["engine_version"] or "(未知)"))
    print("清单来源 : %s" % (info["manifest_source"] or "(无)"))
    if info["manifest_error"]:
        print("清单错误 : %s" % info["manifest_error"])
    print("本地文件 : %d 个 / %s" % (info["local_files"], _fmt_mb(info["bytes"])))
    if info["total"]:
        print("清单总数 : %d 个（已有 %d，缺失 %d，损坏 %d）"
              % (info["total"], info["present"], info["missing"], info["broken"]))
    print("状态     : %s" % ("完整" if info["complete"] else "不完整，需要补全"))
    if info["sample"]:
        print("缺失示例 : %s%s" % (", ".join(info["sample"]),
                                   " …" if info["missing"] + info["broken"] > len(info["sample"]) else ""))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        prog="meme_assets",
        description="Meme 素材体检 / 下载（可指定目标文件夹，不依赖上游 meme download）")
    ap.add_argument("action", nargs="?", default="check",
                    choices=["check", "download", "mirrors"],
                    help="check=只体检；download=补齐缺失素材；mirrors=探测各镜像速度")
    ap.add_argument("--dir", dest="target", default="",
                    help="素材目录；默认取 .env 的 MEME_ASSET_DIR，留空则用引擎包内 memes/")
    ap.add_argument("--deep", action="store_true", help="逐个校验 md5（更准，稍慢）")
    ap.add_argument("--refresh", action="store_true", help="强制联网刷新资源清单")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help="并发数，默认 %d" % DEFAULT_WORKERS)
    args = ap.parse_args(argv)

    if args.target:
        os.environ["MEME_ASSET_DIR"] = args.target
        config.MEME_ASSET_DIR = args.target

    if args.action == "mirrors":
        cands = resource_bases()
        print("候选镜像（原始顺序）：")
        for b in cands:
            print("  %s" % b)
        print("\n正在探活（单个超时 %ss）…" % PROBE_TIMEOUT)
        ranked = rank_bases(cands, force=True)
        print("实际尝试顺序（快 → 慢）：")
        for i, b in enumerate(ranked, 1):
            print("  %d. %s" % (i, b))
        return 0

    info = scan(deep=args.deep, refresh=args.refresh)
    _print_scan(info)
    if args.action == "check" or info["complete"]:
        return 0

    res = start_job(workers=args.workers, refresh=args.refresh, deep=args.deep)
    if not res.get("ok"):
        print("启动下载失败：%s" % res.get("error"))
        return 2
    print("开始下载 %d 个文件 → %s" % (res["total"], res["dir"]))
    if res.get("bases"):
        print("镜像顺序 : %s" % " → ".join(b for b in res["bases"][:3]))
    last = -1
    while True:
        snap = job_snapshot()
        if snap["state"] != "running":
            print("\n%s" % snap["message"])
            for note in snap["failed_sample"][:5]:
                print("  ! %s" % note)
            return 0 if snap["state"] == "done" else 1
        if snap["percent"] != last:
            last = snap["percent"]
            print("\r进度 %3d%%  %d/%d  已下载 %s"
                  % (snap["percent"], snap["done"], snap["total"], _fmt_mb(snap["bytes"])),
                  end="", flush=True)
        time.sleep(0.4)


if __name__ == "__main__":
    raise SystemExit(main())

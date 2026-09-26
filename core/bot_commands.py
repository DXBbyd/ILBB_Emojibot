# -*- coding: utf-8 -*-
"""ILBB 机器人指令框架（OneBot V11 消息指令）。

职责
----
1. 注册 OneBot V11 消息事件处理器（ws_server.add_event_handler）。
2. 解析 /help、/meme、/pair、/quote 四类指令（前缀与开关见 config.BOT_*）。
3. 调用 bot_render 渲染与 WebUI 同款的图片，必要时调用 meme_service / WebUI
   主程序里的配对卡渲染器生成最终图片。
4. 通过 ws_server.call_api 回发图片或文本。

指令一览
--------
/help                          机器人图片菜单（全部指令总览）
/meme                          表情生成帮助（等同 /meme help）
/meme help                     表情生成帮助图
/meme help [ID|关键词]          单个表情的图文教程（底图 · 名称 · 预设 · 示例 · 教程）
/meme list [页码|关键词]        表情素材列表（每款带列表 ID）
/meme [关键词] [文本…] [键=值…]  直接合成表情并回图
/pair                          配对生图帮助（等同 /pair help）
/pair help                     配对生图帮助图
/pair [QQ|@某人] [标题] [键=值…] 生成配对卡片并回图
/quote                         名言图帮助（等同 /quote help）
/quote help                    名言图帮助图
/quote [@某人|QQ号] [文本…]     合成名言图（JPG：随机背景 + 黑色蒙版 + 方形圆角头像 + 笑死气泡 + 署名）

设计要点
--------
* 指令处理跑在独立线程里 —— WS 收包事件循环不能被生图/下载阻塞。
* run_command() 只负责「算出要回什么」，实际发送交给调用方，
  因此 WebUI「指令中心」可以干跑预览，不真的发消息。
"""
from __future__ import annotations

import base64
import io
import os
import sys
import threading
import time
import traceback

import requests
from PIL import Image

import bot_render
import config
import meme_service
import ws_server


# ----------------------------------------------------------------------------
# 开关与常量
# ----------------------------------------------------------------------------
_IMAGE_TIMEOUT = 12          # 拉取素材图片的超时（秒）
_REPLY_TIMEOUT = 25.0        # 回图调用超时（秒），图片大时要给足
_MAX_IN_BYTES = 16 * 1024 * 1024   # 单张输入素材体积上限


def _max_out_bytes() -> int:
    """回图体积上限（由 config.BOT_MAX_IMAGE_MB 决定）"""
    try:
        mb = max(1, int(config.BOT_MAX_IMAGE_MB))
    except Exception:
        mb = 8
    return mb * 1024 * 1024


# ----------------------------------------------------------------------------
# 终端日志（复用 ws_server 的彩色输出）
# ----------------------------------------------------------------------------
def _log(msg, color=None):
    try:
        ws_server._log("指令", msg, color if color is not None else ws_server.C.CYAN)
    except Exception:
        try:
            print("[指令] " + str(msg), flush=True)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# 运行时状态
# ----------------------------------------------------------------------------
_lock = threading.RLock()
_cooldown = {}          # uid -> 上次指令时间戳
_stats = {"total": 0, "ok": 0, "fail": 0, "last": "", "last_at": 0.0}
_installed = False
_webapp = None


def set_webapp(module):
    """由 app.py 注入自身模块，用于复用配对卡渲染器（避免循环导入）"""
    global _webapp
    _webapp = module


def _get_webapp():
    """拿到 WebUI 主程序模块：优先注入，其次从已加载模块里找"""
    if _webapp is not None and hasattr(_webapp, "generate_pair_image"):
        return _webapp
    for name in ("app", "__main__", "web_app"):
        m = sys.modules.get(name)
        if m is not None and hasattr(m, "generate_pair_image"):
            return m
    return None


def stats() -> dict:
    with _lock:
        d = dict(_stats)
    d.update({
        "enabled": bool(config.BOT_ENABLED),
        "prefix": config.BOT_PREFIX,
        "name": config.BOT_NAME,
        "installed": _installed,
        "group_need_at": bool(config.BOT_GROUP_NEED_AT),
        "allow_private": bool(config.BOT_ALLOW_PRIVATE),
        "cooldown": int(config.BOT_COOLDOWN_SEC),
        "list_page": int(config.BOT_MEME_LIST_PAGE),
        "memes": len(bot_render.all_memes()),
    })
    return d


# ----------------------------------------------------------------------------
# 媒体处理：从消息段 / 引用消息 / @ 拿图片
# ----------------------------------------------------------------------------
def _http(url: str) -> bytes:
    r = requests.get(url, timeout=_IMAGE_TIMEOUT)
    r.raise_for_status()
    data = r.content
    if not data:
        raise ValueError("空响应")
    if len(data) > _MAX_IN_BYTES:
        raise ValueError("图片过大（超过 %d MB）" % (_MAX_IN_BYTES // 1024 // 1024))
    return data


def _read_local(path: str):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def _from_get_image(file_id: str):
    """本地路径拿不到时，让 NapCat 把图片内容吐回来"""
    try:
        ret = ws_server.call_api("get_image", {"file": file_id}, timeout=8.0)
    except Exception:
        return None
    data = ((ret or {}).get("response") or {}).get("data") or {}
    raw = data.get("file") or data.get("path") or ""
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("base64://"):
        try:
            return base64.b64decode(raw[9:])
        except Exception:
            return None
    if raw.startswith("http"):
        try:
            return _http(raw)
        except Exception:
            return None
    return _read_local(raw)


def _segment_image(seg) -> bytes | None:
    """从一个 image 消息段里取出原始字节"""
    if not isinstance(seg, dict) or seg.get("type") != "image":
        return None
    d = seg.get("data") or {}
    if not isinstance(d, dict):
        d = {}
    url = str(d.get("url") or "")
    file = str(d.get("file") or "")
    if url.startswith("http"):
        try:
            return _http(url)
        except Exception:
            pass
    if file.startswith("base64://"):
        try:
            return base64.b64decode(file[9:])
        except Exception:
            return None
    if file.startswith("http"):
        try:
            return _http(file)
        except Exception:
            pass
    if file and os.path.exists(file):
        return _read_local(file)
    if file:
        return _from_get_image(file)
    return None


def _reply_images(reply_id: str) -> list:
    """取被引用消息里的所有图片"""
    if not reply_id:
        return []
    mid = reply_id
    if str(mid).lstrip("-").isdigit():
        try:
            mid = int(mid)
        except Exception:
            pass
    try:
        ret = ws_server.call_api("get_msg", {"message_id": mid}, timeout=8.0)
    except Exception:
        return []
    data = ((ret or {}).get("response") or {}).get("data") or {}
    segs = data.get("message")
    if not isinstance(segs, list):
        return []
    out = []
    for s in segs:
        raw = _segment_image(s)
        if raw:
            out.append(raw)
    return out


def _qq_avatar(qq) -> bytes | None:
    qq = str(qq or "").strip()
    if not qq.isdigit():
        return None
    for url in ("https://q1.qlogo.cn/g?b=qq&nk=%s&s=640" % qq,
                "https://q.qlogo.cn/headimg_dl?dst_uin=%s&spec=640" % qq):
        try:
            return _http(url)
        except Exception:
            continue
    return None


_PLACEHOLDER_CACHE = []


def _placeholder_image():
    """干跑预览专用的本地占位图（不联网）：用机器人头像顶替用户图片"""
    if not _PLACEHOLDER_CACHE:
        data = None
        for rel in ("static/favicon.jpg", "static/favicon.png",
                    "static/bili learning.jpg", "bili learning.jpg"):
            p = os.path.join(config.ROOT, rel)
            if os.path.exists(p):
                data = _read_local(p)
                if data:
                    break
        _PLACEHOLDER_CACHE.append(data or b"")
    return _PLACEHOLDER_CACHE[0] or None


def _ctx_images(ctx: dict) -> list:
    """懒加载当前指令可用的图片素材（消息自带 + 引用消息），只加载一次"""
    if ctx.get("_media_done"):
        return list(ctx.get("images") or [])
    ctx["_media_done"] = True
    imgs = [b for b in list(ctx.get("images") or []) if b]

    ev = ctx.get("ev")
    segs = []
    if isinstance(ev, dict) and isinstance(ev.get("message"), list):
        segs = ev["message"]
    else:
        segs = list(ctx.get("segments") or [])
    for s in segs:
        raw = _segment_image(s)
        if raw:
            imgs.append(raw)

    # 引用消息里的图片
    if not imgs:
        imgs.extend(_reply_images(ctx.get("reply_id") or ""))

    ctx["images"] = imgs
    return list(imgs)


def _to_pil(raw):
    if not raw:
        return None
    try:
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return None


def _shrink_gif(im, limit: int):
    """在体积上限内尽量保留动图：逐帧缩放 + 抽帧 + 减色，仍输出 GIF。

    成功返回 (gif_bytes, note)；无法处理（例如只有一帧）返回 None，交回静态流程。
    """
    try:
        n = int(getattr(im, "n_frames", 1) or 1)
    except Exception:
        n = 1
    frames, durs = [], []
    for i in range(n):
        try:
            im.seek(i)
            frames.append(im.convert("RGBA").copy())
            dur = int(im.info.get("duration", 0) or 0)
        except Exception:
            break
        durs.append(max(40, min(500, dur)) if dur > 0 else 100)
    if len(frames) < 2:
        return None
    w0, h0 = frames[0].size

    # 依次放低要求：先等比缩小，再抽帧减色，命中上限即返回。
    # 阶梯一直下探到 0.22 / 12 帧 / 64 色，尽量避免「压完还是超限」。
    best = None
    ladder = ((1.0, 60, 128), (0.75, 50, 128), (0.60, 40, 128),
              (0.45, 32, 96), (0.33, 24, 64), (0.22, 12, 64))
    for scale, cap, colors in ladder:
        step = max(1, (len(frames) + cap - 1) // cap)
        sel = frames[::step][:cap]
        sdur = durs[::step][:cap]
        w = max(1, int(w0 * scale))
        h = max(1, int(h0 * scale))
        imgs = []
        for fr in sel:
            sm = fr if scale >= 0.999 else fr.resize((w, h), Image.Resampling.LANCZOS)
            imgs.append(sm.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=colors))
        buf = io.BytesIO()
        try:
            imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:],
                         duration=sdur, loop=0, disposal=2, optimize=True)
        except Exception:
            continue
        out = buf.getvalue()
        if best is None or len(out) < len(best):
            best = out
        if len(out) <= limit:
            break
    if best:
        if len(best) > limit:
            # 极限压缩后依然超限：仍回动图（比退回静态更符合预期），提示体积偏大
            return best, "（动图已尽量压缩，体积仍偏大）"
        return best, "（原图较大，已压缩动图）"
    return None


def _shrink(data: bytes) -> tuple:
    """回图超过体积上限时降级。

    - 动图（GIF/WebP 等）：保留动图，等比缩小 + 抽帧减色，仍输出 GIF；
    - 静态图：等比缩小并转 JPG。
    返回 (data, note)
    """
    limit = _max_out_bytes()
    if not data or len(data) <= limit:
        return data, ""
    try:
        im = Image.open(io.BytesIO(data))
    except Exception:
        return data, ""

    animated = bool(getattr(im, "is_animated", False)) and int(getattr(im, "n_frames", 1) or 1) > 1
    if animated:
        got = _shrink_gif(im, limit)
        if got:
            return got

    try:
        flat = im.convert("RGB")
    except Exception:
        return data, ""

    # 静态图：等比缩小 + 逐步降质，命中上限即返回。
    # 阶梯下探到 0.12 倍 / q72，尽量避免「压完还是超限」。
    out = data
    hit = False
    for scale, quality in ((1.0, 92), (0.85, 90), (0.70, 90), (0.55, 88),
                           (0.40, 86), (0.28, 84), (0.20, 78), (0.12, 72)):
        w = max(1, int(flat.width * scale))
        h = max(1, int(flat.height * scale))
        buf = io.BytesIO()
        try:
            flat.resize((w, h), Image.Resampling.LANCZOS).save(buf, format="JPEG", quality=quality)
        except Exception:
            break
        out = buf.getvalue()
        if len(out) <= limit:
            hit = True
            break
    if hit:
        return out, "（原图较大，已压缩为静态图）"
    return out, "（原图极大，已尽量压缩，体积仍偏大）"


# ----------------------------------------------------------------------------
# 图片/文本回发
# ----------------------------------------------------------------------------
def _send_segments(ctx, segments) -> bool:
    mtype = ctx.get("mtype")
    if mtype == "group" and ctx.get("gid"):
        action, params = "send_group_msg", {"group_id": ctx["gid"], "message": segments}
    elif ctx.get("uid"):
        action, params = "send_private_msg", {"user_id": ctx["uid"], "message": segments}
    else:
        return False
    try:
        ret = ws_server.call_api(action, params, timeout=_REPLY_TIMEOUT)
    except Exception:
        traceback.print_exc()
        return False
    return bool((ret or {}).get("ok"))


def send_image(ctx, data: bytes) -> bool:
    if not data:
        return False
    b64 = base64.b64encode(data).decode("ascii")
    return _send_segments(ctx, [{"type": "image", "data": {"file": "base64://" + b64}}])


def send_text(ctx, text: str) -> bool:
    if not text:
        return False
    segs = []
    if ctx.get("mtype") == "group" and ctx.get("uid"):
        segs.append({"type": "at", "data": {"qq": str(ctx["uid"])}})
        segs.append({"type": "text", "data": {"text": " "}})
    segs.append({"type": "text", "data": {"text": str(text)}})
    return _send_segments(ctx, segs)


def deliver(ctx, images, texts) -> bool:
    ok = True
    for data in images or []:
        ok = send_image(ctx, data) and ok
    for t in texts or []:
        if t:
            ok = send_text(ctx, t) and ok
    return ok


# ----------------------------------------------------------------------------
# 错误翻译
# ----------------------------------------------------------------------------
def _zh_error(e, m, texts, images) -> str:
    name = type(e).__name__
    try:
        if isinstance(e, meme_service.ImageNumberMismatch):
            mn = int(m["min_images"] or 0)
            mx = int(m["max_images"] or 0)
            if mx <= 0:
                return "这个表情不用图片，把图去掉再发一次即可。"
            if mn == mx:
                return "图片数量不对：这个表情要 %d 张图，你给了 %d 张。" % (mn, len(images))
            return "图片数量不对：这个表情要 %d~%d 张图，你给了 %d 张。" % (mn, mx, len(images))
        if isinstance(e, meme_service.TextNumberMismatch):
            mn = int(m["min_texts"] or 0)
            mx = int(m["max_texts"] or 0)
            if mx <= 0:
                return "这个表情不用文本，把文字去掉再发一次即可。"
            if mn == mx:
                return "文本数量不对：这个表情要 %d 段文本，你给了 %d 段。" % (mn, len(texts))
            return "文本数量不对：这个表情要 %d~%d 段文本，你给了 %d 段。" % (mn, mx, len(texts))
        if isinstance(e, meme_service.TextOrNameNotEnough):
            return "文本或名字不够，再多给一段文本试试。"
        if isinstance(e, meme_service.TextOverLength):
            return "文字太长了，缩短一点再试。"
        if isinstance(e, meme_service.ArgModelMismatch):
            return "预设参数不对：%s" % str(e)[:120]
        if isinstance(e, meme_service.OpenImageFailed):
            return "图片打不开，换一张试试。"
    except Exception:
        pass
    return "%s：%s" % (name, str(e)[:140])


# ----------------------------------------------------------------------------
# 指令实现：/meme [关键词] …
# ----------------------------------------------------------------------------
def _gen_meme(args, ctx) -> tuple:
    prefix = config.BOT_PREFIX
    token = args[0]
    hit = bot_render.find_meme(token)
    if hit is None:
        return ([bot_render.render_notice(
            "找不到这个表情",
            ["没有匹配「%s」的表情素材。" % token,
             "发送 %smeme list 查看素材与列表 ID，" % prefix,
             "或发送 %smeme list 关键词 搜索，例如 %smeme list 摸头。" % (prefix, prefix)],
            "warn")], [])
    idx, m = hit
    key = m["key"]
    pid = "#%d" % idx

    # ---- 切参数：键=值 → 预设；纯数字 / @人 → 候选图片素材；其余 → 文本 ----
    opt_names = {o["name"]: o for o in m["options"]}
    seq, raw_args = [], {}
    for tok in args[1:]:
        if "=" in tok:
            k, v = tok.split("=", 1)
            if k in opt_names:
                raw_args[k] = v
                continue
        s = tok.strip()
        if s.startswith("@"):
            s = s[1:].strip()
            if s.startswith("[") and "]" in s:          # 兼容 @[CQ:at,qq=10001] 这种残留
                s = s.split("]", 1)[1].strip().lstrip("@")
        if 5 <= len(s) <= 12 and s.isdigit():
            seq.append(("qq", s))                       # 疑似 QQ 号，先记着
        else:
            seq.append(("text", tok))

    # ---- 图片素材：消息自带 / 引用消息 ----
    need_min_i = int(m["min_images"] or 0)
    need_max_i = None if m["max_images"] is None else int(m["max_images"])
    images = [b for b in _ctx_images(ctx) if b]
    dry = bool(ctx.get("_dry_run"))

    # 图片不够时依次补：先 @ 的人，再指令后面直接跟的 QQ 号（取头像当素材）
    if len(images) < need_min_i:
        for qq in (ctx.get("ats") or []):
            if len(images) >= need_min_i:
                break
            if str(qq) == str(ctx.get("self_id") or ""):
                continue
            av = _placeholder_image() if dry else _qq_avatar(qq)
            if av:
                images.append(av)
    used_qq = set()
    if len(images) < need_min_i:
        for pos, (kind, val) in enumerate(seq):
            if kind != "qq" or len(images) >= need_min_i:
                continue
            av = _placeholder_image() if dry else _qq_avatar(val)
            if av:
                images.append(av)
                used_qq.add(pos)

    # 干跑（WebUI 指令中心 / Web 会话）不联网取图：上面用 @ / QQ 号补的那部分是
    # 本地占位图。这里刻意「不」凭空补图 —— 缺图就该像真实发送一样提示图片不够，
    # 否则干跑会走到 generate() 而真实发送提前返回，两边结果对不上。

    # 真正被拿去当头像素材的 QQ 号不再算文本；没用上的仍然按文本处理
    texts = [v for i, (kind, v) in enumerate(seq) if not (kind == "qq" and i in used_qq)]

    # ---- 文本数量 ----
    need_min_t = int(m["min_texts"] or 0)
    need_max_t = None if m["max_texts"] is None else int(m["max_texts"])
    if len(texts) < need_min_t:
        for d in (m["default_texts"] or []):
            if len(texts) >= need_min_t:
                break
            texts.append(str(d))
    if len(texts) < need_min_t:
        return ([bot_render.render_notice(
            "文本数量不对",
            ["%s %s 需要 %d 段文本，你只给了 %d 段。" % (pid, key, need_min_t, len(texts)),
             "文本用空格分隔，例如：%smeme %s 第一段 第二段" % (prefix, key)],
            "err")], [])
    # max_texts=0 的素材（不支持文本）直接丢弃多余文本，而不是回一句「要 0~0 段文本」
    if need_max_t is not None and len(texts) > need_max_t:
        texts = texts[:need_max_t]

    # ---- 图片数量 ----
    # 同理：不需要图片的素材丢弃多余图片，需要 N 张就只取前 N 张
    if need_max_i is not None and len(images) > need_max_i:
        images = images[:need_max_i]
    if len(images) < need_min_i:
        if need_max_i is None or need_max_i <= need_min_i:
            want = "%d 张" % need_min_i
        else:
            want = "%d~%d 张" % (need_min_i, need_max_i)
        return ([bot_render.render_notice(
            "图片数量不对",
            ["%s %s 要 %s图片，你给了 %d 张。" % (pid, key, want, len(images)),
             "把图片和指令一起发送，或引用一条带图消息后再发指令；",
             "也可以 @ 群友，或直接在指令后面写 QQ 号，例如 %smeme %s 10001" % (prefix, key)],
            "err")], [])

    # ---- 生成 ----
    preset = {}
    if raw_args:
        try:
            preset = meme_service.coerce_args(dict({"_key": key}, **raw_args))
        except Exception:
            preset = dict(raw_args)
    try:
        out = meme_service.generate(key, images, texts, preset)
    except meme_service.KNOWN_ERRORS as e:
        return ([bot_render.render_notice("生成失败", [_zh_error(e, m, texts, images)], "err")], [])
    except Exception as e:
        traceback.print_exc()
        return ([bot_render.render_notice(
            "生成失败", [str(e)[:140],
                     "可在 WebUI「表情生成」里用同样参数试试，确认是否为素材本身的问题。"],
            "err")], [])
    data, note = _shrink(out)
    return ([data], [note] if note else [])


# ----------------------------------------------------------------------------
# 指令实现：/pair [QQ|@某人] [标题] [键=值…]
# ----------------------------------------------------------------------------
_PAIR_KEYS = ("template", "title", "bg", "btn", "font", "color")


def _build_bg(bg_raw, ctx) -> dict:
    v = str(bg_raw or "random").strip()
    lv = v.lower()
    if lv.startswith("#"):
        return {"type": "color", "color": v}
    if lv in ("color", "纯色"):
        return {"type": "color", "color": ctx.get("color_hex") or "#dce6f5"}
    if lv in ("gradient", "渐变"):
        return {"type": "gradient", "colors": ["#bcc9f0", "#eef4ff"]}
    if lv in ("image", "图片", "图"):
        imgs = _ctx_images(ctx)
        if imgs:
            return {"type": "image", "image": base64.b64encode(imgs[0]).decode("ascii")}
        return {"type": "gradient", "colors": ["#bcc9f0", "#eef4ff"]}
    return {"type": "gradient", "colors": ["#bcc9f0", "#eef4ff"]}


def _gen_pair(args, ctx) -> tuple:
    prefix = config.BOT_PREFIX
    opts, leftovers, qq = {}, [], ""

    ats = [str(q) for q in (ctx.get("ats") or [])
           if str(q) != str(ctx.get("self_id") or "") and str(q).isdigit()]
    if ats:
        qq = ats[0]

    for tok in args:
        if "=" in tok:
            k, v = tok.split("=", 1)
            if k in _PAIR_KEYS:
                opts[k] = v
                continue
        if not qq and tok.isdigit():
            qq = tok
            continue
        leftovers.append(tok)

    if not qq:
        return ([bot_render.render_notice(
            "缺少配对对象",
            ["用法：%spair [QQ号] 或 %spair @某人，后面可以再跟标题。" % prefix,
             "例如：%spair 10001 我们的配对结果" % prefix,
             "发送 %spair help 查看完整帮助。" % prefix],
            "warn")], [])

    web = _get_webapp()
    if web is None:
        return ([bot_render.render_notice(
            "配对生图不可用",
            ["没有找到 WebUI 主程序的配对卡渲染器。",
             "请确认机器人是随主程序一起启动的（app.py 会注册渲染器）。"],
            "err")], [])

    # ---- 昵称 / 头像 ----
    name, avatar = qq, None
    try:
        got_name, avatar_url = web.get_qq_info(qq)
        if got_name:
            name = got_name
        avatar = web.download_qq_avatar_from_url(avatar_url)
    except Exception:
        pass
    if avatar is None:
        avatar = _to_pil(_qq_avatar(qq))

    # ---- 标题 ----
    title = str(opts.get("title") or "").strip()
    if not title:
        extra = " ".join(leftovers).strip()
        title = extra if extra else "要与 {name} 配对吗？"
    final_title = title.replace("{name}", str(name))

    # ---- 模板 / 按钮 / 背景 / 字体 ----
    template = str(opts.get("template") or "classic").strip().lower()
    if template not in ("classic", "dark", "paper"):
        template = "classic"
    buttons = []
    raw_btn = str(opts.get("btn") or "").strip()
    if raw_btn:
        for t in [x.strip() for x in raw_btn.split("|") if x.strip()][:4]:
            buttons.append({"type": "text", "text": t, "icon": None})
    if not buttons:
        buttons = [{"type": "text", "text": "配对", "icon": None}]
    bg_config = _build_bg(opts.get("bg"), ctx)
    font_key = str(opts.get("font") or "default").strip() or "default"

    try:
        img = web.generate_pair_image(qq, final_title, avatar, font_key,
                                      template, bg_config, buttons)
    except Exception as e:
        traceback.print_exc()
        return ([bot_render.render_notice("配对卡生成失败", [str(e)[:140]], "err")], [])

    buf = io.BytesIO()
    try:
        img.convert("RGB").save(buf, format="PNG", optimize=True)
    except Exception:
        img.save(buf, format="PNG")
    data, note = _shrink(buf.getvalue())
    return ([data], [note] if note else [])


# ----------------------------------------------------------------------------
# 指令实现：/quote [@某人|QQ号] 文本…
# ----------------------------------------------------------------------------
def _quote_background() -> bytes | None:
    """随机背景图：调 config.BG_API（每次请求返回一张随机图）"""
    api = str(getattr(config, "BG_API", "") or "").strip()
    if not api:
        return None
    sep = "&" if "?" in api else "?"
    try:
        return _http(api + sep + "t=" + str(int(time.time() * 1000)))
    except Exception:
        return None


def _person_info(qq, gid="", dry=False) -> str:
    """取昵称：群聊优先群名片，其次昵称；私聊走陌生人信息。取不到返回空串。"""
    qq = str(qq or "").strip()
    if not qq or dry:
        return ""
    if gid:
        try:
            ret = ws_server.call_api("get_group_member_info",
                                     {"group_id": str(gid), "user_id": qq, "no_cache": True},
                                     timeout=6.0)
            data = ((ret or {}).get("response") or {}).get("data") or {}
            name = str(data.get("card") or "").strip() or str(data.get("nickname") or "").strip()
            if name:
                return name
        except Exception:
            pass
    try:
        ret = ws_server.call_api("get_stranger_info",
                                 {"user_id": qq, "no_cache": True}, timeout=6.0)
        data = ((ret or {}).get("response") or {}).get("data") or {}
        return str(data.get("nickname") or "").strip()
    except Exception:
        return ""


def _clean_name(name) -> str:
    """署名清洗：去掉换行/制表符、避免和破折号重复，并按配置截断"""
    s = "".join(ch for ch in str(name or "") if ch not in "\r\n\t").strip()
    s = s.replace("——", "-").replace("—", "-")
    try:
        mx = max(4, int(getattr(config, "QUOTE_NAME_MAX", 16)))
    except Exception:
        mx = 16
    if len(s) > mx:
        s = s[:mx] + "…"
    return s


def _gen_quote(args, ctx) -> tuple:
    prefix = config.BOT_PREFIX
    if not bool(getattr(config, "QUOTE_ENABLED", True)):
        return ([bot_render.render_notice(
            "名言合成已关闭",
            ["管理员在配置里关闭了 QUOTE_ENABLED（.env 可改回 true）。"], "warn")], [])

    dry = bool(ctx.get("_dry_run"))
    uid = str(ctx.get("uid") or "")
    gid = str(ctx.get("gid") or "")
    self_id = str(ctx.get("self_id") or "")

    # ---- 切参数：@某人 / 纯 QQ 号 → 头像与署名的来源；其余全部算正文 ----
    target = ""
    words = []
    for tok in args or []:
        s = str(tok).strip()
        if not target and s.startswith("@"):
            s2 = s[1:].strip()
            if s2.startswith("[") and "]" in s2:        # 兼容 @[CQ:at,qq=10001] 残留
                s2 = s2.split("]", 1)[1].strip().lstrip("@")
            if s2:
                target = s2
                continue
        if not target and 5 <= len(s) <= 12 and s.isdigit():
            target = s
            continue
        words.append(str(tok))

    if not target:
        for qq in (ctx.get("ats") or []):
            if str(qq) and str(qq) != self_id:
                target = str(qq)
                break
    if not target:
        target = uid
    body_text = " ".join(w for w in words if w).strip()

    # ---- 头像与署名 ----
    name = ""
    avatar = ctx.get("avatar") if isinstance(ctx.get("avatar"), (bytes, bytearray)) else None
    if str(target) == uid:
        name = str(ctx.get("uname") or "").strip()
    if not name:
        name = _person_info(target, gid, dry)
    if avatar is None:
        if dry:
            avatar = _placeholder_image()
        else:
            avatar = _qq_avatar(target)
    name = _clean_name(name) or str(getattr(config, "QUOTE_NAME", "无名氏"))

    # ---- 气泡内容：优先用消息里（或引用的）图当表情包，没有就给文字 ----
    images = [b for b in _ctx_images(ctx) if b]
    images = images[:1]
    if not body_text and not images:
        body_text = "这就是名言。"

    bg = None if dry else _quote_background()
    try:
        data = bot_render.render_quote(body_text, name, avatar, images, bg)
    except Exception as e:
        traceback.print_exc()
        return ([bot_render.render_notice("名言图生成失败", [str(e)[:140]], "err")], [])

    data, note = _shrink(data)
    return ([data], [note] if note else [])


# ----------------------------------------------------------------------------
# 指令路由
# ----------------------------------------------------------------------------
_HELP_ALIAS = ("help", "帮助", "教程", "?", "？")
_MENU_ALIAS = ("help", "帮助", "菜单", "menu", "?", "？")


def run_command(body, ctx=None) -> tuple:
    """解析一条指令（不含前缀），返回 (images, texts)。

    只计算「要回什么」，不发送任何东西 —— WebUI 预览与真实回复共用这一段逻辑。
    """
    ctx = ctx or {}
    prefix = config.BOT_PREFIX
    body = str(body or "").strip()
    parts = body.split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:]

    # 盐值含版式版本号与机器人昵称：改了帮助图版式或改名后，旧磁盘缓存自动失效
    salt = "%s|%s|%d|%d" % (prefix, config.BOT_NAME,
                            len(bot_render.all_memes()),
                            bot_render.RENDER_VERSION)
    ctag = lambda *ps: bot_render.cache_tag(salt, *ps)      # noqa: E731
    cpng = bot_render.cached_png

    # ===== /help —— 机器人图片菜单 =====
    if not cmd or cmd in _MENU_ALIAS:
        # 只回菜单图，不再附一段自我介绍文字
        return ([cpng(ctag("menu"), bot_render.render_menu)], [])

    # ===== /meme =====
    if cmd in ("meme", "表情", "生图"):
        if not args:
            return ([cpng(ctag("memehelp"), bot_render.render_meme_help)], [])
        sub = args[0].lower()
        if sub in _HELP_ALIAS:
            if len(args) >= 2:
                token = args[1]
                return ([cpng(ctag("detail", token),
                              lambda: bot_render.render_meme_detail(token))], [])
            return ([cpng(ctag("memehelp"), bot_render.render_meme_help)], [])
        if sub in ("list", "列表", "素材"):
            rest = args[1:]
            page, query = 1, ""
            if rest:
                if rest[0].isdigit():
                    page = int(rest[0])
                    query = " ".join(rest[1:])
                else:
                    query = " ".join(rest)
            return ([cpng(ctag("list", page, query),
                          lambda: bot_render.render_meme_list(page, query))], [])
        return _gen_meme(args, ctx)

    # ===== /pair =====
    if cmd in ("pair", "配对", "卡片"):
        if not args or args[0].lower() in _HELP_ALIAS:
            return ([cpng(ctag("pairhelp"), bot_render.render_pair_help)], [])
        return _gen_pair(args, ctx)

    # ===== /quote —— 名言图 =====
    if cmd in ("quote", "名言", "名言图"):
        if not args or args[0].lower() in _HELP_ALIAS:
            return ([cpng(ctag("quotehelp"), bot_render.render_quote_help)], [])
        return _gen_quote(args, ctx)

    # ===== 插件指令（plugins/ 下每个文件夹都可注册自己的触发词） =====
    if getattr(config, "PLUGIN_ENABLED", True):
        try:
            import plugin_manager
            plug_out = plugin_manager.dispatch_command(body, ctx)
            if plug_out is not None:
                return plug_out
        except Exception:
            traceback.print_exc()

    # ===== 未知指令 =====
    return ([bot_render.render_notice(
        "没有这条指令",
        ["「%s%s」不是可用指令。" % (prefix, cmd),
         "发送 %shelp 查看全部指令。" % prefix],
        "warn")], [])


def preview(body, ctx=None, dry: bool = True) -> tuple:
    """预览/干跑一条指令，返回 (images, texts)，不发送任何消息。

    dry=True（WebUI 指令中心「干跑预览」）：不联网取图，@ / QQ 号的头像用
    本地占位图顶替，判定与真实发送一致。
    dry=False（WebUI「Web 会话」）：完全按真实发送走，包括联网取 QQ 头像。
    """
    probe = {"mtype": "private", "uid": "0", "ats": [], "images": [],
             "self_id": "", "segments": []}
    probe.update(ctx or {})
    probe["_media_done"] = True
    probe["_dry_run"] = bool(dry)
    return run_command(body, probe)


# ----------------------------------------------------------------------------
# 事件处理
# ----------------------------------------------------------------------------
def _parse_message(ev) -> tuple:
    """从消息事件里取 (文本, @列表, 引用消息ID)"""
    segs = ev.get("message") if isinstance(ev.get("message"), list) else []
    text_parts, ats, reply_id = [], [], ""
    for s in segs:
        if not isinstance(s, dict):
            continue
        typ = s.get("type")
        d = s.get("data") if isinstance(s.get("data"), dict) else {}
        if typ == "text":
            text_parts.append(str(d.get("text") or ""))
        elif typ == "at":
            qq = str(d.get("qq") or "")
            if qq:
                ats.append(qq)
        elif typ == "reply":
            rid = str(d.get("id") or "")
            if rid:
                reply_id = rid
    text = "".join(text_parts)
    if not text:
        text = str(ev.get("raw_message") or "")
    return text, ats, reply_id


def _worker(body, ctx):
    try:
        with _lock:
            _stats["total"] += 1
            _stats["last"] = body[:80]
            _stats["last_at"] = time.time()
        t0 = time.time()
        images, texts = run_command(body, ctx)
        ok = deliver(ctx, images, texts)
        cost = time.time() - t0
        with _lock:
            _stats["ok" if ok else "fail"] += 1
        where = ("群 %s" % ctx.get("gid")) if ctx.get("mtype") == "group" else "私聊"
        _log("%s · %s(%s) · %s → %d 图 %d 文 · %.2fs"
             % (where, ctx.get("uname") or ctx.get("uid"), ctx.get("uid"),
                body[:40], len(images), len(texts), cost),
             ws_server.C.GREEN if ok else ws_server.C.YELLOW)
        try:
            ws_server._push_event(
                "command", "机器人指令",
                "%s(%s) @ %s · %s"
                % (ctx.get("uname") or ctx.get("uid"), ctx.get("uid"), where, body[:60]),
                "", {"uid": ctx.get("uid"), "uname": ctx.get("uname"),
                     "gid": ctx.get("gid"), "gname": ctx.get("gname"),
                     "content": body[:120], "post": "command",
                     "mtype": ctx.get("mtype"), "av": "bot",
                     "ok": bool(ok), "images": len(images)})
        except Exception:
            pass
    except Exception:
        traceback.print_exc()
        with _lock:
            _stats["fail"] += 1


def handle_event(ev, client=None):
    """OneBot V11 事件入口（注册给 ws_server.add_event_handler）"""
    if not config.BOT_ENABLED:
        return
    try:
        kind, tag, head, detail, extra = ws_server._parse_event(ev)
    except Exception:
        traceback.print_exc()
        return
    if kind != "message":
        return
    ex = extra or {}
    if ex.get("post") != "message":          # 忽略机器人自己发出的消息，避免自回
        return

    mtype = str(ex.get("mtype") or "")
    if mtype not in ("group", "private"):
        return
    if mtype == "private" and not config.BOT_ALLOW_PRIVATE:
        return

    uid = str(ex.get("uid") or "")
    gid = str(ex.get("gid") or "")
    self_id = str(ev.get("self_id") or "")
    if uid and uid == self_id:
        return

    text, ats, reply_id = _parse_message(ev)
    prefix = config.BOT_PREFIX
    stripped = text.strip()

    body = None
    if stripped.startswith(prefix):
        body = stripped[len(prefix):].strip()
    else:
        # 群里要求 @ 机器人时，允许「@bot 指令」不带前缀
        if mtype == "group" and config.BOT_GROUP_NEED_AT and self_id and self_id in ats:
            body = stripped
    if body is None:
        return
    if not body and not ats:
        return

    # ---- 冷却 ----
    cd = int(config.BOT_COOLDOWN_SEC or 0)
    if cd > 0 and uid:
        now = time.time()
        with _lock:
            last = _cooldown.get(uid) or 0
            if now - last < cd:
                _log("冷却中，忽略 %s(%s) 的指令：%s" % (ex.get("uname") or uid, uid, body[:40]),
                     ws_server.C.GREY)
                return
            _cooldown[uid] = now
            if len(_cooldown) > 2000:        # 简单防膨胀
                for k in sorted(_cooldown, key=lambda k: _cooldown[k])[:500]:
                    _cooldown.pop(k, None)

    ctx = {
        "mtype": mtype,
        "uid": uid,
        "uname": str(ex.get("uname") or uid),
        "gid": gid,
        "gname": str(ex.get("gname") or ""),
        "self_id": self_id,
        "ats": ats,
        "reply_id": reply_id,
        "message_id": str(ex.get("message_id") or ""),
        "images": [],
        "ev": ev,
    }
    _log("收到 · %s(%s) @ %s · %s"
         % (ctx["uname"], uid, ("群 %s" % gid) if mtype == "group" else "私聊", body[:50]),
         ws_server.C.CYAN)
    threading.Thread(target=_worker, args=(body, ctx), daemon=True).start()


# ----------------------------------------------------------------------------
# 安装
# ----------------------------------------------------------------------------
def setup(webapp=None) -> bool:
    """注册事件处理器（幂等）。app.py 启动时调用。"""
    global _installed
    if webapp is not None:
        set_webapp(webapp)
    if not config.BOT_ENABLED:
        _log("指令框架已禁用（BOT_ENABLED=false）", ws_server.C.YELLOW)
        return False
    if _installed:
        return True
    ws_server.add_event_handler(handle_event)
    _installed = True
    _log("指令框架已就绪 · 前缀 %s · %d 款表情素材 · 群聊%s需要 @ · 私聊%s"
         % (config.BOT_PREFIX, len(bot_render.all_memes()),
            "" if config.BOT_GROUP_NEED_AT else "不", "开启" if config.BOT_ALLOW_PRIVATE else "关闭"),
         ws_server.C.GREEN)
    return True

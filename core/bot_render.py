# -*- coding: utf-8 -*-
"""Bot 指令「图片渲染层」。

把指令的响应渲染成一张图片，视觉风格与 WebUI（static/css/style.css 的 :root）
保持一致：暖中性底色、白色圆角卡片、赤陶色品牌色、同一套信息层级。

对外提供的渲染器：
- render_menu()                  /help            机器人图片菜单（全部指令总览）
- render_meme_help()             /meme help       表情生成帮助
- render_meme_detail(token)      /meme help [ID]  单个表情的图文教程（含底图 / 预设 / 示例）
- render_meme_list(page, query)  /meme list       表情素材列表（带列表 ID 分页）
- render_pair_help()             /pair help       配对生图帮助
- render_quote(text, name, ...)  /名言 · /生成名言  名言图（横屏 16:9：左独立圆角头像 + 右半边磨砂玻璃面板 + 右下角署名）
- render_quote_help()            /名言 help       名言图帮助
- render_notice(title, lines)    通用提示 / 错误图
- render_plugin_list(plugins, bad) /plugin           插件列表（编号 + 状态 + 指令概览）
- render_plugin_help(info)         /plugin help N    单个插件的使用帮助

以及表情素材索引工具：all_memes() / indexed_memes() / find_meme()。

本模块不接触 HTTP、不接触 Flask，也不依赖 app.py（避免循环导入）：
只依赖 config 与 meme_service，绘图全部用 PIL 自己完成。
"""
from __future__ import annotations

import hashlib
import io
import json
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

import config
import meme_service

# ============================================================================
# 调色板（对齐 WebUI 的 CSS 变量）
# ============================================================================
BG = (250, 249, 245)          # --bg-1 #faf9f5
BG2 = (245, 244, 239)         # --bg-2 #f5f4ef
BG3 = (237, 233, 222)         # --bg-3 #ede9de
CARD = (255, 255, 255)        # --bg-0 #ffffff
BORDER = (227, 224, 212)      # --border #e3e0d4
INK = (61, 57, 41)            # --ink #3d3929
INK2 = (110, 109, 104)        # --ink-2 #6e6d68
INK3 = (152, 150, 142)
BRAND = (201, 100, 66)        # --brand #c96442
BRAND_D = (176, 86, 47)       # --brand-strong
BRAND_S = (244, 224, 213)     # --brand-soft
BLUE = (74, 111, 212)         # --blue #4a6fd4
BLUE_S = (228, 234, 250)
OK = (100, 118, 73)           # --ok #647649
OK_S = (231, 237, 219)
ERR = (184, 54, 54)           # --err #b83636
ERR_S = (246, 226, 226)
WARN = (176, 122, 32)
WARN_S = (250, 238, 214)

W = 960                       # 统一画布宽度
SIDE = 28                     # 左右留白

# 渲染版本号：改动版式/预览后 +1，会让 run_command 里的图片缓存自动失效重绘
RENDER_VERSION = 9

_CACHE_DIR = os.path.join(config.CACHE_DIR, "bot")   # 渲染结果缓存目录


# ============================================================================
# 字体
# ============================================================================
_FONT_READY = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
               "C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/arial.ttf"]
_FONT_BOLD = ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
              "C:/Windows/Fonts/simhei.ttf"]
_font_cache: dict = {}


def clear_font_cache():
    """清空字体对象缓存。

    设置页改了「全局字体 / 字体目录」后，config 会热重载并回调
    app.py 里的 _apply_config_reload，那里会调本函数 —— 否则旧字体对象还在缓存里，
    新配置不会生效。
    """
    _font_cache.clear()


def _family_path(family):
    """字体配置值 → 字体文件路径；system / 无效值 → None（交回系统字体查找）"""
    try:
        return config.font_path(family)
    except Exception:
        return None


def _resolve_family(family):
    """把 None / inherit / auto 归一成真正的字体配置值，再解析成文件路径"""
    fam = getattr(config, "FONT_FAMILY", "system") if family is None else family
    s = str(fam or "").strip()
    if s.lower() in ("", "inherit", "auto"):
        s = str(getattr(config, "FONT_FAMILY", "system") or "system")
    return s, _family_path(s)


def _pick_font_file(bold: bool, family=None):
    """按「全局字体（或指定字体）→ 系统字体 → 项目 font/ 目录」的顺序找字体文件"""
    _fam, p = _resolve_family(family)
    if p:
        return p
    for p2 in (_FONT_BOLD if bold else _FONT_READY):
        if os.path.exists(p2):
            return p2
    # 退一步用项目 font/ 目录里的字体
    try:
        names = sorted(os.listdir(config.FONT_DIR))
    except Exception:
        names = []
    for fn in names:
        if fn.lower().endswith((".ttf", ".otf", ".ttc")):
            return os.path.join(config.FONT_DIR, fn)
    return None


def font(size: int, bold: bool = False, family=None):
    """取字体对象（按「字体 + 字号 + 粗细」缓存）。

    family 传 None 或 "inherit" 时跟 config.FONT_FAMILY（全局字体）；
    找不到任何字体时退回 PIL 默认位图字体。
    """
    fam, _p = _resolve_family(family)
    key = (fam, int(size), bool(bold))
    f = _font_cache.get(key)
    if f is None:
        path = _pick_font_file(bold, fam)
        try:
            f = ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except Exception:
            try:
                f = ImageFont.load_default(size=size)
            except Exception:
                f = ImageFont.load_default()
        _font_cache[key] = f
    return f


def _lh(f, k: float = 1.5) -> int:
    """行高（PIL 默认字体没有 size 属性，兜底给个常数）"""
    return int(round(getattr(f, "size", 16) * k))


# ============================================================================
# 画布：先在一张很高的图上按游标往下画，最后裁掉多余部分
# ============================================================================
class Canvas:
    _MAX_H = 14000

    def __init__(self, width: int = W, bg=BG, top: int = 0):
        self.w = width
        self.img = Image.new("RGB", (width, self._MAX_H), bg)
        self.d = ImageDraw.Draw(self.img)
        self.y = top

    # ---------- 基础图元 ----------
    def card(self, x, y, w, h, radius=20, fill=CARD, outline=BORDER, width=2):
        self.d.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=radius,
                                 fill=fill, outline=outline, width=width)

    def bar(self, x, y, w, h, color, radius=0):
        if radius:
            self.d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=color)
        else:
            self.d.rectangle([x, y, x + w, y + h], fill=color)

    def line(self, x1, y1, x2, y2, color=BORDER, width=2):
        self.d.line([x1, y1, x2, y2], fill=color, width=width)

    def one(self, x, cy, s, f, fill=INK, anchor="lm"):
        """单行文本，cy 为垂直中心"""
        self.d.text((x, cy), s, font=f, fill=fill, anchor=anchor)

    def tw(self, s, f) -> float:
        return self.d.textlength(s, font=f)

    def para(self, x, y, max_w, s, f, fill=INK2, gap=6):
        """多行段落，返回结束后的 y"""
        for ln in _wrap(self.d, s, f, max_w):
            self.d.text((x, y), ln, font=f, fill=fill, anchor="la")
            y += _lh(f) + gap
        return y

    def chip(self, x, cy, s, f, fg, bg, padx=12, pady=7, radius=9, outline=None):
        """胶囊标签，cy 为垂直中心；返回 (宽, 高)"""
        tw = self.tw(s, f)
        h = int(getattr(f, "size", 16)) + pady * 2
        w = int(tw) + padx * 2
        self.d.rounded_rectangle([x, cy - h // 2, x + w, cy + h // 2],
                                 radius=radius, fill=bg, outline=outline, width=1)
        self.one(x + padx, cy, s, f, fg)
        return w, h

    def finish(self, bottom_pad=28, bg=BG):
        h = max(240, min(self._MAX_H, self.y + bottom_pad))
        out = self.img.crop((0, 0, self.w, h))
        return out.convert("RGB")


def _wrap(d, s, f, max_w):
    """按像素宽度逐字换行（中英混排够用），\n 强制换行"""
    if not s:
        return [""]
    lines, cur = [], ""
    for ch in str(s):
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        t = cur + ch
        if not cur or d.textlength(t, font=f) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = ch
    lines.append(cur)
    return lines or [""]


def _ellipsis(d, s, f, max_w):
    if d.textlength(s, font=f) <= max_w:
        return s
    out = ""
    for ch in s:
        if d.textlength(out + ch + "…", font=f) > max_w:
            break
        out += ch
    return (out + "…") if out else s[:1]


# ============================================================================
# 图片小工具
# ============================================================================
def _round_img(img: Image.Image, radius: int) -> Image.Image:
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    dr = ImageDraw.Draw(mask)
    box = [0, 0, img.size[0] - 1, img.size[1] - 1]
    if radius * 2 >= min(img.size):
        dr.ellipse(box, fill=255)          # 半径够大 → 直接画正圆
    else:
        dr.rounded_rectangle(box, radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _fit(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    iw, ih = img.size
    scale = min(box_w / max(1, iw), box_h / max(1, ih))
    return img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))),
                      Image.Resampling.LANCZOS)


def _first_frame(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    try:
        im.seek(0)
    except Exception:
        pass
    return im.convert("RGBA")


def _paste(cv: Canvas, im: Image.Image, x, y):
    """把带透明通道的图贴到画布上（兼容 RGB 画布）"""
    cv.img.paste(im, (int(x), int(y)), im if im.mode == "RGBA" else None)


def _logo(size: int) -> Image.Image | None:
    """机器人头像（与 WebUI 同源：static/favicon.jpg），裁成圆形"""
    path = os.path.join(config.ROOT, "static", "favicon.jpg")
    if not os.path.exists(path):
        return None
    try:
        src = Image.open(path).convert("RGB")
    except Exception:
        return None
    side = min(src.size)
    src = src.crop(((src.width - side) // 2, (src.height - side) // 2,
                    (src.width + side) // 2, (src.height + side) // 2))
    src = src.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(src, (0, 0), mask)
    return out


# ============================================================================
# 表情素材索引（列表 ID 与查找）
# ============================================================================
def all_memes() -> list:
    """全部表情元信息，按 key 排序（保证列表 ID 稳定）"""
    ms = meme_service.list_memes()
    ms.sort(key=lambda m: m["key"])
    return ms


def indexed_memes(query: str = "") -> list:
    """[(id, meme), ...]，id 为从 1 开始的全局稳定序号"""
    q = (query or "").strip().lower()
    out = []
    for i, m in enumerate(all_memes(), 1):
        if q:
            hay = " ".join([m["key"]] + list(m["keywords"])).lower()
            if q not in hay:
                continue
        out.append((i, m))
    return out


def find_meme(token) -> tuple | None:
    """按列表 ID（数字）或 key / 关键词解析一个表情；返回 (id, meme) 或 None"""
    t = str(token or "").strip()
    if not t:
        return None
    ms = all_memes()
    if t.isdigit():
        n = int(t)
        if 1 <= n <= len(ms):
            return (n, ms[n - 1])
        return None
    tl = t.lower()
    for i, m in enumerate(ms, 1):                      # 先精确
        if m["key"].lower() == tl or tl in [k.lower() for k in m["keywords"]]:
            return (i, m)
    for i, m in enumerate(ms, 1):                      # 再模糊
        if tl in m["key"].lower() or any(tl in k.lower() for k in m["keywords"]):
            return (i, m)
    return None


# ============================================================================
# 预览缩略图（帮助图里展示真实效果）
# ============================================================================
_THUMB_MAX = 320                  # 缩略图最长边（预览原图可能上千像素、几百 KB）
_THUMB_DIR = os.path.join(_CACHE_DIR, "thumb")
_thumb_mem: dict = {}


def _thumb(key: str, args: dict | None = None) -> Image.Image | None:
    """渲染某个表情（可带预设参数）的预览缩略图，失败返回 None。

    * 只取首帧：预览多是动图，帮助图里用不到动画。
    * 结果按 (key, 预设) 缓存进 cache/bot/thumb/，并做一层内存缓存，
      所以同一个表情第二次出现时不会再调用 meme 引擎。
    """
    ar = {k: v for k, v in dict(args or {}).items() if v is not None}
    try:
        tag = cache_tag("thumb", RENDER_VERSION, key,
                        json.dumps(ar, sort_keys=True, ensure_ascii=False))
    except Exception:
        tag = cache_tag("thumb", RENDER_VERSION, key)
    hit = _thumb_mem.get(tag)
    if hit is not None:
        return hit
    path = os.path.join(_THUMB_DIR, hashlib.md5(tag.encode("utf-8")).hexdigest() + ".png")
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            if data:
                im = Image.open(io.BytesIO(data)).convert("RGBA")
                _thumb_mem[tag] = im
                return im
    except Exception:
        pass
    try:
        im = _first_frame(meme_service.preview(key, ar))
    except Exception:
        _thumb_mem[tag] = None
        return None
    try:
        im = _fit(im, _THUMB_MAX, _THUMB_MAX)
    except Exception:
        pass
    try:
        os.makedirs(_THUMB_DIR, exist_ok=True)
        im.save(path, format="PNG", optimize=True)
    except Exception:
        pass
    _thumb_mem[tag] = im
    return im


def _opt_sample(o) -> tuple:
    """给一个预设选项取「用来预览的示例值」，返回 (值, 展示文本)"""
    t = o.get("type")
    if t == "bool":
        return True, "true"
    if t == "int":
        if o.get("min") is not None:
            v = o["min"]
        elif o.get("max") is not None:
            v = o["max"]
        else:
            v = o.get("default") or 1
        return v, str(v)
    if t == "float":
        v = o.get("default")
        if v is None:
            v = 1.0
        return v, str(v)
    if t == "choose":
        cs = list(o.get("choices") or [])
        if cs:
            return cs[0], cs[0]
        return o.get("default"), str(o.get("default") or "")
    d = o.get("default")
    if d in ("", None):
        return "示例", "示例"
    return d, str(d)


_PREVIEW_KEYS = ("petpet", "kiss", "rub", "bubble_tea", "alipay", "atri_pillow")


def _pick_previews(n: int = 4) -> list:
    """挑 n 个素材做「效果预览」：优先常见的名字，不够再按列表均匀取样"""
    out, seen = [], set()
    for k in _PREVIEW_KEYS:
        if len(out) >= n:
            break
        hit = find_meme(k)
        if hit and hit[0] not in seen:
            seen.add(hit[0])
            out.append(hit)
    ms = all_memes()
    total = len(ms)
    if total and len(out) < n:
        step = max(1, total // n)
        j = 0
        while len(out) < n and j * step < total:
            mid = min(total, j * step + 1)
            if mid not in seen:
                seen.add(mid)
                out.append((mid, ms[mid - 1]))
            j += 1
    return out[:n]


# ============================================================================
# 公共版式组件
# ============================================================================
def _appbar(cv: Canvas, active: str):
    """仿 WebUI 顶栏：logo + 标题 + 视图切换标签（装饰性，用于统一观感）"""
    h = 96
    cv.bar(0, 0, cv.w, h, CARD)
    cv.line(0, h, cv.w, h, BORDER, 2)

    lg = _logo(52)
    if lg is not None:
        _paste(cv, lg, SIDE, (h - 52) // 2)
    cv.one(SIDE + 52 + 14, h // 2 - 9, "我在哔哩学习 Emoji Bot", font(25, True), INK)
    cv.chip(SIDE + 52 + 14 + cv.tw("我在哔哩学习 Emoji Bot", font(25, True)) + 10,
            h // 2 - 9, "ILBB", font(17, True), BRAND, BRAND_S, padx=9, pady=5)

    tabs = ["配对卡片", "表情生成", "指令中心"]
    tf = font(19, True)
    widths = [int(cv.tw(t, tf)) + 34 for t in tabs]
    total = sum(widths) + 10 * (len(tabs) - 1)
    x = cv.w - SIDE - total
    cy = h // 2
    for t, tw_ in zip(tabs, widths):
        on = (t == active)
        cv.d.rounded_rectangle([x, cy - 19, x + tw_, cy + 19], radius=11,
                               fill=BRAND if on else BG2,
                               outline=None if on else BORDER, width=1)
        cv.one(x + tw_ / 2, cy, t, tf, (255, 255, 255) if on else INK2, anchor="mm")
        x += tw_ + 10
    cv.y = h


def _page_head(cv: Canvas, badge: str, title: str, subtitle: str):
    """品牌头卡（标题 + 副标题 + 右上角指令徽章）"""
    x, w = SIDE, cv.w - SIDE * 2
    f_t, f_s = font(40, True), font(22)
    bf = font(21, True)
    bw = int(cv.tw(badge, bf)) + 30
    pad = 30
    tlines = _wrap(cv.d, title, f_t, w - pad * 2 - bw - 24)
    h = pad + len(tlines) * _lh(f_t, 1.35) + 12 + _lh(f_s, 1.4) + pad - 6
    y = cv.y + 24
    cv.card(x, y, w, h, radius=24)
    # 左侧品牌竖条
    cv.bar(x + 6, y + pad, 7, h - pad * 2, BRAND, radius=4)
    tx = x + pad
    yy = y + pad
    for ln in tlines:
        cv.d.text((tx, yy), ln, font=f_t, fill=INK, anchor="la")
        yy += _lh(f_t, 1.35)
    cv.d.text((tx, yy + 8), subtitle, font=f_s, fill=INK2, anchor="la")
    # 右上角徽章
    cv.chip(x + w - pad - bw, y + pad + 21, badge, bf, BRAND_D, BRAND_S, padx=15, pady=9)
    cv.y = y + h


def _group(cv: Canvas, title: str, rows: list, accent=BRAND):
    """一个分组卡：组标题 + 若干「用法 + 说明」行"""
    x, w = SIDE, cv.w - SIDE * 2
    f_title = font(26, True)
    f_use = font(20, True)
    f_desc = font(20)

    inner_x = x + 26
    inner_w = w - 52
    tmp = 0
    layout = []
    for usage, desc in rows:
        uw = int(cv.tw(usage, f_use)) + 26
        uh = int(getattr(f_use, "size", 18)) + 16
        dw = inner_w - uw - 18
        if dw < 150:                      # 用法太长就把说明放到下一行
            dw = inner_w
            dlines = _wrap(cv.d, desc, f_desc, dw) if desc else []
            layout.append((usage, uw, uh, dlines, uh + (8 + len(dlines) * _lh(f_desc) if dlines else 0), False))
            tmp += layout[-1][4] + 14
        else:
            dlines = _wrap(cv.d, desc, f_desc, dw) if desc else []
            rh = max(uh, len(dlines) * _lh(f_desc))
            layout.append((usage, uw, uh, dlines, rh, True))
            tmp += rh + 14

    card_h = 22 + tmp - 14 + 22
    y0 = cv.y + 34
    # 组标题
    cv.bar(x + 2, y0 + 4, 6, 22, accent, radius=3)
    cv.one(x + 20, y0 + 15, title, f_title, INK)
    # 卡片
    top = y0 + 46
    cv.card(x, top, w, card_h, radius=20)
    yy = top + 22
    for usage, uw, uh, dlines, rh, inline in layout:
        cy = yy + rh // 2
        if inline:
            cv.chip(inner_x, cy, usage, f_use, BRAND_D, BRAND_S, padx=13, pady=8)
            ty = cy - (len(dlines) * _lh(f_desc)) // 2
            for ln in dlines:
                cv.d.text((inner_x + uw + 18, ty), ln, font=f_desc, fill=INK2, anchor="la")
                ty += _lh(f_desc)
        else:
            cv.chip(inner_x, yy + uh // 2, usage, f_use, BRAND_D, BRAND_S, padx=13, pady=8)
            ty = yy + uh + 8
            for ln in dlines:
                cv.d.text((inner_x, ty), ln, font=f_desc, fill=INK2, anchor="la")
                ty += _lh(f_desc)
        yy += rh + 14
    cv.y = top + card_h


def _group_media(cv: Canvas, title: str, items: list, accent=BRAND, thumb: int = 104):
    """带缩略图的分组卡：items = [(用法, 说明, 预览图 or None), ...]

    有预览图的行左侧放一枚缩略图（比如每个预设参数的实际效果），
    没有预览图的行退回 _group 的「胶囊 + 说明」排版。
    """
    x, w = SIDE, cv.w - SIDE * 2
    f_title, f_use, f_desc = font(26, True), font(20, True), font(20)
    inner_x, inner_w = x + 26, w - 52
    gap = 20

    rows = []
    for it in items:
        usage, desc = it[0], it[1]
        im = it[2] if len(it) > 2 else None
        uw = int(cv.tw(usage, f_use)) + 26
        uh = int(getattr(f_use, "size", 18)) + 16
        if im is not None:
            tx = inner_x + thumb + gap
            avail = inner_w - thumb - gap
            dlines = _wrap(cv.d, desc, f_desc, avail) if desc else []
            ch = uh + (8 + len(dlines) * _lh(f_desc) if dlines else 0)
            rows.append({"usage": usage, "uw": uw, "uh": uh, "dlines": dlines,
                         "h": max(thumb, ch), "chip_x": tx, "desc_x": tx,
                         "im": im, "mode": "thumb"})
        else:
            dw = inner_w - uw - 18
            if dw < 150:
                dlines = _wrap(cv.d, desc, f_desc, inner_w) if desc else []
                h = uh + (8 + len(dlines) * _lh(f_desc) if dlines else 0)
                rows.append({"usage": usage, "uw": uw, "uh": uh, "dlines": dlines,
                             "h": h, "chip_x": inner_x, "desc_x": inner_x,
                             "im": None, "mode": "stack"})
            else:
                dlines = _wrap(cv.d, desc, f_desc, dw) if desc else []
                rows.append({"usage": usage, "uw": uw, "uh": uh, "dlines": dlines,
                             "h": max(uh, len(dlines) * _lh(f_desc)),
                             "chip_x": inner_x, "desc_x": inner_x + uw + 18,
                             "im": None, "mode": "inline"})

    body = sum(r["h"] for r in rows) + 14 * max(0, len(rows) - 1)
    card_h = 22 + body + 22
    y0 = cv.y + 34
    cv.bar(x + 2, y0 + 4, 6, 22, accent, radius=3)
    cv.one(x + 20, y0 + 15, title, f_title, INK)
    top = y0 + 46
    cv.card(x, top, w, card_h, radius=20)

    yy = top + 22
    for r in rows:
        dlines = r["dlines"]
        if r["mode"] == "thumb":
            box = thumb
            by = yy + (r["h"] - box) // 2
            cv.d.rounded_rectangle([inner_x, by, inner_x + box - 1, by + box - 1],
                                   radius=14, fill=BG2, outline=BORDER, width=2)
            im = r["im"]
            fitted = _fit(im, box - 10, box - 10)
            _paste(cv, _round_img(fitted, 10),
                   inner_x + (box - fitted.width) // 2, by + (box - fitted.height) // 2)
            ch = r["uh"] + (8 + len(dlines) * _lh(f_desc) if dlines else 0)
            ty = yy + (r["h"] - ch) // 2
            cv.chip(r["chip_x"], ty + r["uh"] // 2, r["usage"], f_use,
                    BRAND_D, BRAND_S, padx=13, pady=8)
            ty += r["uh"] + 8
            for ln in dlines:
                cv.d.text((r["desc_x"], ty), ln, font=f_desc, fill=INK2, anchor="la")
                ty += _lh(f_desc)
        elif r["mode"] == "inline":
            cy = yy + r["h"] // 2
            cv.chip(r["chip_x"], cy, r["usage"], f_use, BRAND_D, BRAND_S, padx=13, pady=8)
            ty = cy - (len(dlines) * _lh(f_desc)) // 2
            for ln in dlines:
                cv.d.text((r["desc_x"], ty), ln, font=f_desc, fill=INK2, anchor="la")
                ty += _lh(f_desc)
        else:
            cv.chip(r["chip_x"], yy + r["uh"] // 2, r["usage"], f_use,
                    BRAND_D, BRAND_S, padx=13, pady=8)
            ty = yy + r["uh"] + 8
            for ln in dlines:
                cv.d.text((r["desc_x"], ty), ln, font=f_desc, fill=INK2, anchor="la")
                ty += _lh(f_desc)
        yy += r["h"] + 14
    cv.y = top + card_h


def _preview_strip(cv: Canvas, title: str, picks: list, cols: int = 4, accent=BLUE):
    """效果预览卡：一排真实预览缩略图（列表 ID + 名字）"""
    picks = [p for p in picks if p]
    if not picks:
        return
    x, w = SIDE, cv.w - SIDE * 2
    f_title, f_id, f_key = font(26, True), font(17, True), font(19, True)
    gap = 16
    inner_pad = 26
    cell_w = (w - inner_pad * 2 - gap * (cols - 1)) // cols
    box = cell_w
    label_h = 44
    rows_n = (len(picks) + cols - 1) // cols
    cell_h = box + label_h
    body = rows_n * cell_h + max(0, rows_n - 1) * gap
    card_h = inner_pad + body
    y0 = cv.y + 34
    cv.bar(x + 2, y0 + 4, 6, 22, accent, radius=3)
    cv.one(x + 20, y0 + 15, title, f_title, INK)
    top = y0 + 46
    cv.card(x, top, w, card_h, radius=20)
    for i, (mid, m, im) in enumerate(picks):
        rr, cc = divmod(i, cols)
        cxp = x + inner_pad + cc * (cell_w + gap)
        cyp = top + inner_pad // 2 + rr * (cell_h + gap)
        cv.d.rounded_rectangle([cxp, cyp, cxp + cell_w - 1, cyp + box - 1],
                               radius=14, fill=BG2, outline=BORDER, width=2)
        if im is not None:
            fitted = _fit(im, cell_w - 14, box - 14)
            _paste(cv, _round_img(fitted, 10),
                   cxp + (cell_w - fitted.width) // 2, cyp + (box - fitted.height) // 2)
        else:
            cv.one(cxp + cell_w / 2, cyp + box / 2, "无预览", font(18), INK3, anchor="mm")
        cv.chip(cxp + 8, cyp + box + 20, "#%d" % mid, f_id, BRAND_D, BRAND_S, padx=9, pady=5)
        kx = cxp + 8 + int(cv.tw("#%d" % mid, f_id)) + 18 + 9
        cv.d.text((kx, cyp + box + 12),
                  _ellipsis(cv.d, m["key"], f_key, cxp + cell_w - kx - 8),
                  font=f_key, fill=INK, anchor="la")
    cv.y = top + card_h


def _footer(cv: Canvas, extra: str = ""):
    x, w = SIDE, cv.w - SIDE * 2
    y = cv.y + 34
    cv.line(x + 40, y, x + w - 40, y, BORDER, 2)
    f = font(20, True)
    txt = config.BOT_FOOTER or "ILBB"
    cv.one(cv.w / 2, y + 30, txt, f, INK2, anchor="mm")
    if extra:
        cv.one(cv.w / 2, y + 58, extra, font(18), INK3, anchor="mm")
        cv.y = y + 76
    else:
        cv.y = y + 48


# ============================================================================
# 1) /help —— 机器人图片菜单
# ============================================================================
def render_menu() -> bytes:
    cv = Canvas(W, BG, top=0)
    _appbar(cv, "指令中心")
    total = len(all_memes())
    _page_head(cv, "总览", config.BOT_NAME + " · 图片菜单",
               "所有指令都在这里：表情合成 meme、配对生图 pair、名言合成 名言、通用 help。")

    p = config.BOT_PREFIX
    _group(cv, "表情生成 · meme", [
        (f"{p}meme",
         "打开表情生成器：查看用法、可用素材与快速上手说明。"),
        (f"{p}meme help",
         "表情生成帮助图：如何给图、给文本、写预设参数，以及常见报错原因。"),
        (f"{p}meme help [ID]",
         "查某个表情的图文教程：返回一张图，含该表情的底图、名称、支持的预设与使用示例（ID 见 "
         f"{p}meme list）。"),
        (f"{p}meme list",
         f"表情素材列表：分页浏览全部 {total} 款素材，每款带列表 ID。"),
        (f"{p}meme list [页码/关键词]",
         f"翻页或按名字、关键词检索素材，例如 {p}meme list 3 或 {p}meme list 摸头。"),
        (f"{p}meme [关键词] 文本…",
         "直接合成表情：关键词后跟文本，并附图（张数按该表情要求）。"
         f"也可以 @ 群友或直接写 QQ 号代替带图，如 {p}meme 摸头 10001。"),
    ])

    _group(cv, "配对生图 · pair", [
        (f"{p}pair", f"配对图生成帮助（等同 {p}pair help）。"),
        (f"{p}pair help", "配对生图帮助图：参数说明、可用模板与示例。"),
        (f"{p}pair [QQ/@] [标题]",
         "生成配对卡片：@某人或直接给 QQ 号，可选模板、标题与按钮文字，机器人回卡片图。"),
    ], accent=BLUE)

    _group(cv, "名言合成 · 名言", [
        (f"{p}名言", "引用一条消息发出去，就把那条消息做成名言图（署名＝被引用的人，文字/图片/@ 都保留）。"),
        (f"{p}名言 help", "名言图帮助图：布局、格式与用法说明。"),
        (f"{p}生成名言 文本…",
         "给自己合成名言图：随机二次元背景 + 灰色蒙版，画面正中一块全模糊托盘，"
         "托盘内左圆形头像（你自己）、右文字，右下角署名「—— 用户名」；"
         "静态内容出 JPG，动图出 GIF。"),
    ], accent=WARN)

    _group(cv, "通用 · help", [
        (f"{p}help", "查看本图片菜单（机器人全部指令总览）。"),
        (f"{p}plugin", "插件列表：列出 plugins/ 下已安装的插件与编号（图片）。"),
        (f"{p}plugin help [编号]", "插件帮助：查看某个插件怎么用（指令用法 / 说明 / 可配置项）。"),
    ], accent=OK)

    _preview_strip(cv, "效果预览（真实素材）",
                   [(mid, m, _thumb(m["key"])) for mid, m in _pick_previews(4)])

    _footer(cv, f"共 {total} 款表情素材 ｜ 输入 {p}meme list 查看全部")
    return _to_png(cv)


# ============================================================================
# 2) /meme help —— 表情生成帮助
# ============================================================================
def render_meme_help() -> bytes:
    p = config.BOT_PREFIX
    cv = Canvas(W, BG)
    _appbar(cv, "表情生成")
    _page_head(cv, "meme", "表情生成器 · 使用帮助",
               "发一条指令 +（可选）图片，机器人立刻把表情回给你。")

    _group(cv, "指令格式", [
        (f"{p}meme [关键词] [文本1] [文本2] …",
         "关键词是表情的名字或别名；文本用空格分隔，按表情要求给几段就给几段。"),
        (f"{p}meme help [ID]", f"查看某个表情的详细教程与预设（ID 见 {p}meme list）。"),
        (f"{p}meme list [页码]", f"分页查看全部素材；{p}meme list 摸头 可按关键词搜索。"),
    ])

    _group(cv, "怎么给图", [
        ("直接带图", "把指令和图片一起发出来：图片会按发送顺序作为第 1、2… 张素材使用。"),
        ("引用图片", "回复一条带图消息再发指令，会使用被引用消息里的图片。"),
        ("@某人", "需要头像素材的表情可以 @ 群友，机器人会取 TA 的头像当素材。"),
        ("直接写 QQ 号", f"指令后面写数字 QQ 号也行，例如 {p}meme 摸头 10001，"
                     "机器人会取该 QQ 的头像当素材，不用再带图。"),
    ], accent=BLUE)

    _group(cv, "预设参数怎么写", [
        ("键=值", "在文本后面追加 键=值，例如：mode=loop、num=3、name=小明。"),
        ("多个预设", "用空格分隔多个参数，顺序不限。"),
        ("查看预设", f"每个表情支持的预设不同，用 {p}meme help [ID] 查看它支持的项与取值。"),
    ], accent=OK)

    _group(cv, "常见报错", [
        ("图片数量不对", "该表情要求固定张数（如 1~2 张），请按提示增减图片。"),
        ("文本数量不对", "文本段数超出或不足，参考帮助图里的「需要文本」一栏。"),
        ("文字太长", "单段文本长度超出该表情上限，缩短后再试。"),
        ("找不到表情", f"关键词拼写不对或没有这个素材，用 {p}meme list 搜索正确名字。"),
    ], accent=ERR)

    _preview_strip(cv, "效果预览（真实素材）",
                   [(mid, m, _thumb(m["key"])) for mid, m in _pick_previews(4)])

    _footer(cv, f"没头绪？先发 {p}meme list 挑一个素材，再用 {p}meme help [ID] 看教程")
    return _to_png(cv)


# ============================================================================
# 3) /meme help [ID] —— 单个表情的图文教程
# ============================================================================
def _need_text(m) -> str:
    mn, mx = m["min_images"], m["max_images"]
    if mx == 0:
        return "不需要图片"
    if mn == mx:
        return "需要 %d 张图片" % mn
    return "需要 %d~%d 张图片" % (mn, mx)


def _need_texts(m) -> str:
    mn, mx = m["min_texts"], m["max_texts"]
    if mx == 0:
        return "不需要文本"
    if mn == mx:
        return "需要 %d 段文本" % mn
    return "需要 %d~%d 段文本" % (mn, mx)


def _opt_line(o) -> str:
    """把一个预设选项写成人话"""
    t = o.get("type")
    if t == "bool":
        return "开关：true / false（默认 %s）" % ("true" if o.get("default") else "false")
    if t == "int":
        if o.get("min") is not None and o.get("max") is not None:
            return "整数：%d~%d（默认 %s）" % (o["min"], o["max"], o.get("default"))
        return "整数（默认 %s）" % (o.get("default"),)
    if t == "float":
        return "小数（默认 %s）" % (o.get("default"),)
    if t == "choose":
        cs = o.get("choices") or []
        return "单选：%s（默认 %s）" % (" / ".join(cs) if cs else "—", o.get("default"))
    d = o.get("default")
    return "文本：%s" % (("默认「%s」" % d) if d not in ("", None) else "自定义填写")


def _example_lines(pid, m) -> list:
    """根据表情的图/文/预设生成使用示例"""
    kw = (m["keywords"] or [m["key"]])[0]
    texts = list(m["default_texts"] or [])
    max_t = int(m["max_texts"] or 0)
    if max_t <= 0:
        tpart = ""                       # 这个表情不接受文本，示例里就别带文本
    elif texts:
        tpart = " ".join(texts[:max_t])
    else:
        tpart = " ".join("文本%d" % (i + 1) for i in range(max(1, int(m["min_texts"] or 0))))
    if m["min_images"] == 0 and m["max_images"] > 0:
        img = "＋图片（可选）"
    elif m["min_images"] > 0:
        img = "＋%d 张图" % m["min_images"]
    else:
        img = ""

    lines = [" ".join(x for x in (f"{pid}meme", kw, tpart, img) if x)]

    if m["options"]:
        o = m["options"][0]
        t = o.get("type")
        if t == "bool":
            kv = "%s=true" % o["name"]
        elif t == "int":
            kv = "%s=%s" % (o["name"], o.get("min") if o.get("min") is not None
                            else (o.get("default") or 1))
        elif t == "choose" and o.get("choices"):
            kv = "%s=%s" % (o["name"], o["choices"][0])
        else:
            kv = "%s=自定义" % o["name"]
        lines.append(" ".join(x for x in (f"{pid}meme", kw, kv, tpart, img) if x))
    elif len(texts) > 1:
        lines.append(" ".join(x for x in (f"{pid}meme", kw, texts[0], img) if x))

    # 免带图示例：@ 群友，或直接在指令后面写 QQ 号
    if m["min_images"] > 0:
        lines.append(" ".join(x for x in (f"{pid}meme", kw, tpart, "10001") if x))
    return lines[:4]


def render_meme_detail(token) -> bytes:
    """token 可以是列表 ID（数字）或 key / 关键词；找不到则返回提示图"""
    hit = find_meme(token)
    if hit is None:
        return render_notice("找不到这个表情",
                             ["没有匹配「%s」的表情素材。" % token,
                              "用 %smeme list 查看全部素材与列表 ID。" % config.BOT_PREFIX],
                             kind="warn")
    idx, m = hit
    p = config.BOT_PREFIX
    cv = Canvas(W, BG)
    _appbar(cv, "表情生成")

    x, w = SIDE, W - SIDE * 2
    top = cv.y + 24

    # ---------- 主视觉卡：左底图 + 右元信息 ----------
    img_box_w, img_box_h = 356, 356
    pad = 28
    right_x = x + pad + img_box_w + 28
    right_w = w - pad * 2 - img_box_w - 28

    # 右侧内容先算高度
    f_key = font(40, True)
    f_meta = font(21)
    chips = [m["key"]] if False else []
    kw_chips = list(m["keywords"])[:6]
    tag_chips = list(m["tags"])[:5]
    opt_count = len(m["options"])

    rows = []
    rows.append(("需要图片", _need_text(m)))
    rows.append(("需要文本", _need_texts(m)))
    rows.append(("预设数量", ("%d 项" % opt_count) if opt_count else "无"))
    rh = _lh(f_meta, 1.6)
    right_h = _lh(f_key, 1.35) + 18 + (34 if kw_chips else 0) + (34 if tag_chips else 0) + len(rows) * rh
    card_h = max(pad * 2 + img_box_h, pad * 2 + right_h)

    cv.card(x, top, w, card_h, radius=24)

    # 左：底图（真实预览的第一帧）
    bx, by = x + pad, top + (card_h - img_box_h) // 2
    cv.d.rounded_rectangle([bx, by, bx + img_box_w - 1, by + img_box_h - 1],
                           radius=18, fill=BG2, outline=BORDER, width=2)
    try:
        prev = _first_frame(meme_service.preview(m["key"]))
        fitted = _fit(prev, img_box_w - 32, img_box_h - 32)
        _paste(cv, _round_img(fitted, 12),
               bx + (img_box_w - fitted.width) // 2, by + (img_box_h - fitted.height) // 2)
    except Exception as e:
        cv.one(bx + img_box_w / 2, by + img_box_h / 2, "预览生成失败", font(22, True), ERR, anchor="mm")
        cv.one(bx + img_box_w / 2, by + img_box_h / 2 + 34, str(e)[:24], font(17), INK3, anchor="mm")

    # 右：名称 / 关键词 / 标签 / 需求
    ry = top + pad
    cv.chip(right_x, ry + 22, "#%d" % idx, font(19, True), BRAND_D, BRAND_S, padx=12, pady=8)
    nx = right_x + int(cv.tw("#%d" % idx, font(19, True))) + 24 + 12
    cv.d.text((nx, ry), _ellipsis(cv.d, m["key"], f_key, right_x + right_w - nx),
              font=f_key, fill=INK, anchor="la")
    ry += _lh(f_key, 1.35) + 14
    if kw_chips:
        cxx = right_x
        for c in kw_chips:
            cw, _ = cv.chip(cxx, ry + 15, c, font(19, True), BRAND_D, BRAND_S, padx=12, pady=7)
            cxx += cw + 8
        ry += 34
    if tag_chips:
        cxx = right_x
        for c in tag_chips:
            cw, _ = cv.chip(cxx, ry + 15, "#" + c, font(18), INK2, BG3, padx=11, pady=6)
            cxx += cw + 8
        ry += 34
    for label, val in rows:
        cv.one(right_x, ry + rh // 2, label, font(21, True), INK)
        cv.one(right_x + 118, ry + rh // 2, val, f_meta, INK2)
        ry += rh
    cv.y = top + card_h

    # ---------- 预设参数（每一项都配一张真实渲染的预览小图） ----------
    opts = m["options"] or []
    if opts:
        items = []
        for o in opts:
            val, vtxt = _opt_sample(o)
            desc = "%s　—　%s" % (o.get("help") or "无说明", _opt_line(o))
            if val is not None:
                desc += "　（此项预览用 %s=%s）" % (o["name"], vtxt)
            items.append(("preset:%s" % o["name"], desc, _thumb(m["key"], {o["name"]: val})))
        _group_media(cv, "支持的预设参数（%d 项 · 左侧为该取值的效果预览）" % len(opts), items)
    else:
        _group(cv, "支持的预设参数", [
            ("无预设", "这个表情没有可选参数，直接按格式给图和文本即可。")])

    # ---------- 默认文本 ----------
    if m["default_texts"]:
        _group(cv, "默认文本（不给文本时使用）", [
            ("第 %d 段" % (i + 1), t) for i, t in enumerate(m["default_texts"][:6])
        ], accent=BLUE)

    # ---------- 使用示例 ----------
    _group(cv, "使用示例", [("示例 %d" % (i + 1), ln)
                            for i, ln in enumerate(_example_lines(p, m))], accent=OK)

    # ---------- 使用教程 ----------
    kw0 = (m["keywords"] or [m["key"]])[0]
    if int(m["max_texts"] or 0) <= 0:
        s1 = "在聊天框输入 %smeme %s，这个表情不用带文本。" % (p, kw0)
    else:
        s1 = ("在聊天框输入 %smeme %s，后面接上文本（有几段就给几段，用空格分隔）。" % (p, kw0))
    if int(m["max_images"] or 0) <= 0:
        s2 = "这个表情不用带图片，直接发送即可。"
    else:
        s2 = ("按需求带图片：%s。可以随指令一起发、先发图再引用，"
              "也可以 @ 群友或直接写 QQ 号（如 %smeme %s 10001）取头像当素材。" % (_need_text(m), p, kw0))
    steps = [
        ("第 1 步", s1),
        ("第 2 步", s2),
        ("第 3 步", "需要调预设时，在文本后面追加 键=值（见上面的预设参数）。"),
        ("第 4 步", "发送，机器人会把这个表情回给你。"),
    ]
    _group(cv, "使用教程", [(a, b) for a, b in steps], accent=BRAND)

    _footer(cv, "ID #%d ｜ %s meme help %d 可随时再看" % (idx, p, idx))
    return _to_png(cv)


# ============================================================================
# 4) /meme list —— 表情素材列表（带列表 ID）
# ============================================================================
def render_meme_list(page: int = 1, query: str = "") -> bytes:
    items = indexed_memes(query)
    total = len(items)
    per = max(4, int(config.BOT_MEME_LIST_PAGE))
    pages = max(1, (total + per - 1) // per)
    page = max(1, min(int(page or 1), pages))
    chunk = items[(page - 1) * per: page * per]

    cv = Canvas(W, BG)
    _appbar(cv, "表情生成")
    sub = ("关键词「%s」共 %d 款素材" % (query, total)) if query else ("共 %d 款表情素材" % total)
    _page_head(cv, "第 %d/%d 页" % (page, pages),
               "表情素材列表" + (" · 搜索：%s" % query if query else ""), sub)

    x, w = SIDE, W - SIDE * 2
    cols = 2
    gap = 18
    cell_w = (w - gap) // cols
    cell_h = 118
    box = 78                                   # 左侧真实预览缩略图边长
    rows = (len(chunk) + cols - 1) // cols
    grid_h = rows * cell_h + max(0, rows - 1) * 14
    top = cv.y + 22
    cv.card(x, top, w, grid_h + 36, radius=20)

    f_id = font(19, True)
    f_key = font(24, True)
    f_kw = font(18)
    f_meta = font(17, True)

    for i, (mid, m) in enumerate(chunk):
        r, c = divmod(i, cols)
        cxp = x + 18 + c * (cell_w + gap)
        cyp = top + 18 + r * (cell_h + 14)
        cv.d.rounded_rectangle([cxp, cyp, cxp + cell_w - 1, cyp + cell_h - 1],
                               radius=16, fill=BG2, outline=BORDER, width=2)
        # 左：真实预览缩略图（首帧，已做磁盘 + 内存缓存）
        by = cyp + (cell_h - box) // 2
        cv.d.rounded_rectangle([cxp + 14, by, cxp + 14 + box - 1, by + box - 1],
                               radius=12, fill=BG3, outline=BORDER, width=2)
        tim = _thumb(m["key"])
        if tim is not None:
            tf = _fit(tim, box - 8, box - 8)
            _paste(cv, _round_img(tf, 8),
                   cxp + 14 + (box - tf.width) // 2, by + (box - tf.height) // 2)
        else:
            cv.one(cxp + 14 + box / 2, by + box / 2, "—", font(22), INK3, anchor="mm")
        tx = cxp + 14 + box + 14
        tw = cell_w - (14 + box + 14) - 14
        # 列表 ID
        cv.chip(tx, cyp + 30, "#%d" % mid, f_id, (255, 255, 255), BRAND, padx=12, pady=7)
        kx = tx + int(cv.tw("#%d" % mid, f_id)) + 24 + 12
        cv.d.text((kx, cyp + 18), _ellipsis(cv.d, m["key"], f_key, tx + tw - kx),
                  font=f_key, fill=INK, anchor="la")
        # 关键词
        kw = " / ".join(list(m["keywords"])[:4]) or "—"
        cv.d.text((tx, cyp + 52), _ellipsis(cv.d, kw, f_kw, tw),
                  font=f_kw, fill=INK2, anchor="la")
        # 需求 + 预设
        meta = "%s ｜ %s" % (_need_text(m), _need_texts(m))
        cv.d.text((tx, cyp + 78), _ellipsis(cv.d, meta, f_meta, tw - 100 if m["options"] else tw),
                  font=f_meta, fill=INK3, anchor="la")
        if m["options"]:
            badge = "预设 %d" % len(m["options"])
            bw = int(cv.tw(badge, f_meta)) + 20
            cv.chip(cxp + cell_w - 14 - bw, cyp + cell_h - 20, badge, f_meta,
                    (255, 255, 255), BLUE, padx=10, pady=5)
    cv.y = top + grid_h + 36

    tip = ("发 %smeme list %d 看下一页" % (config.BOT_PREFIX, page + 1)) if page < pages \
        else ("已是最后一页，发 %smeme list 1 回到第一页" % config.BOT_PREFIX)
    _footer(cv, "发 %smeme help [ID] 查看某个素材的图文教程 ｜ %s" % (config.BOT_PREFIX, tip))
    return _to_png(cv)


# ============================================================================
# 5) /pair help —— 配对生图帮助
# ============================================================================
def render_pair_help() -> bytes:
    p = config.BOT_PREFIX
    cv = Canvas(W, BG)
    _appbar(cv, "配对卡片")
    _page_head(cv, "pair", "配对生图 · 使用帮助",
               "生成一张 QQ 风格的配对卡片：头像 + 标题 + 按钮，和 WebUI 配对生成器同款。")

    _group(cv, "指令格式", [
        ("%spair [QQ号] [标题]" % p, "给一个 QQ 号，机器人拉取头像并合成卡片；标题可省略。"),
        ("%spair @某人 [标题]" % p, "群里直接 @ 群友，取 TA 的头像当卡片头像。"),
        ("%spair help" % p, "就是这张帮助图。"),
        ("%spair" % p, "单独发送等于 help。"),
    ], accent=BLUE)

    _group(cv, "可选参数", [
        ("template=classic", "模板：classic 经典弹窗（浅蓝玻璃，默认）、dark 深邃玻璃、paper 清新纸张。"),
        ("title=文字", "卡片标题，也可以直接跟在 QQ 号后面（含空格时用 title= 更稳）。"),
        ("bg=random", "背景：random 随机（默认）、color 纯色、gradient 渐变、image 图片。"),
        ("btn=配对|接受|拒绝", "按钮文字，用 | 分隔，最多 4 个。"),
    ], accent=OK)

    _group(cv, "示例", [
        ("示例 1", "%spair 10001 我们的配对结果" % p),
        ("示例 2", "%spair @群友 title=今天也要加油 template=paper" % p),
        ("示例 3", "%spair 10001 btn=在一起|再想想 bg=random" % p),
    ], accent=BRAND)

    _group(cv, "小提示", [
        ("拿不到昵称", "会退回用 QQ 号当标题，属正常现象。"),
        ("头像拉取失败", "对方没有公开头像时会用默认灰头像。"),
        ("在 WebUI 里微调", "打开「配对卡片」视图可以可视化管理背景、字体与按钮，指令与面板共用同一套渲染。"),
    ], accent=WARN)

    _footer(cv, "输入 %spair [QQ号] 立刻生成一张配对卡片" % p)
    return _to_png(cv)


# ============================================================================
# 6) 通用提示 / 错误图
# ============================================================================
_KIND = {
    "info": (BLUE, BLUE_S),
    "ok": (OK, OK_S),
    "warn": (WARN, WARN_S),
    "err": (ERR, ERR_S),
}


def render_notice(title: str, lines: list, kind: str = "info") -> bytes:
    fg, soft = _KIND.get(kind, _KIND["info"])
    cv = Canvas(W, BG)
    _appbar(cv, "指令中心")
    x, w = SIDE, W - SIDE * 2
    f_t = font(32, True)
    f_l = font(21)
    pad = 28
    tlines = _wrap(cv.d, title, f_t, w - pad * 2)
    body = 0
    wrapped = []
    for ln in lines or []:
        ls = _wrap(cv.d, str(ln), f_l, w - pad * 2 - 18)
        wrapped.append(ls)
        body += len(ls) * _lh(f_l, 1.55)
    h = pad + len(tlines) * _lh(f_t, 1.35) + 16 + body + pad
    y = cv.y + 30
    cv.card(x, y, w, h, radius=22, fill=CARD, outline=BORDER)
    cv.bar(x + 6, y + pad, 7, h - pad * 2, fg, radius=4)
    yy = y + pad
    for ln in tlines:
        cv.d.text((x + pad, yy), ln, font=f_t, fill=INK, anchor="la")
        yy += _lh(f_t, 1.35)
    yy += 16
    for ls in wrapped:
        cv.d.ellipse([x + pad + 4, yy + _lh(f_l, 1.55) // 2 - 4,
                      x + pad + 12, yy + _lh(f_l, 1.55) // 2 + 4], fill=fg)
        for i, ln in enumerate(ls):
            cv.d.text((x + pad + 22, yy), ln, font=f_l, fill=INK2, anchor="la")
            yy += _lh(f_l, 1.55)
    cv.y = y + h
    _footer(cv)
    return _to_png(cv)


# ============================================================================
# 7) /plugin —— 插件列表与插件帮助（与 WebUI 同款视觉）
# ============================================================================
def _plugin_status(it: dict) -> str:
    if not it.get("enabled"):
        return "已停用"
    if it.get("loaded"):
        return "运行中"
    return "未载入"


def render_plugin_list(plugins: list, bad: list = None) -> bytes:
    p = config.BOT_PREFIX
    cv = Canvas(W, BG, top=0)
    _appbar(cv, "指令中心")
    plugins = plugins or []
    loaded = len([x for x in plugins if x.get("loaded")])
    _page_head(cv, "插件", config.BOT_NAME + " · 插件列表",
               "共 %d 个插件（已载入 %d）。发送 %splugin help <编号> 查看某个插件怎么用。"
               % (len(plugins), loaded, p))

    rows = []
    for it in plugins:
        idx = it.get("index")
        usages = [str(h.get("usage") or "").strip()
                  for h in (it.get("command_help") or [])
                  if str(h.get("usage") or "").strip()]
        if usages:
            cmdline = "、".join(usages[:6])
            if len(usages) > 6:
                cmdline += " 等 %d 条" % len(usages)
        else:
            cmds = it.get("commands") or []
            cmdline = "、".join("/" + str(c) for c in cmds[:8]) or "（未注册指令）"
            if len(cmds) > 8:
                cmdline += " 等 %d 条" % len(cmds)
        badge = " ｜ 独立页面" if it.get("has_web") else ""
        rows.append(("#%s  %s" % (idx, it.get("name") or it.get("id")),
                     "v%s ｜ %s ｜ %s%s\n%s\n指令：%s"
                     % (it.get("version", "0.0.0"), it.get("id", ""),
                        _plugin_status(it), badge,
                        str(it.get("desc") or "").strip(), cmdline)))
    if rows:
        _group(cv, "全部插件", rows)
    else:
        _group(cv, "全部插件", [("（空）", "plugins/ 目录下还没有可用的插件。")])

    if bad:
        _group(cv, "装错了的插件",
               [(str(b.get("name") or "?"), str(b.get("error") or "")) for b in bad],
               accent=ERR)

    _footer(cv, "发送 %splugin help <编号> 查看插件用法" % p)
    return _to_png(cv)


def render_plugin_help(info: dict) -> bytes:
    p = config.BOT_PREFIX
    cv = Canvas(W, BG, top=0)
    _appbar(cv, "指令中心")
    status = _plugin_status(info)
    if not info.get("loaded") and info.get("error"):
        status += "（%s）" % str(info.get("error"))[:40]
    _page_head(cv, "插件 #%s" % info.get("index", "?"),
               "%s · 使用帮助" % (info.get("name") or info.get("id")),
               "%s v%s ｜ %s"
               % (info.get("id", ""), info.get("version", "0.0.0"), status))

    rows = []
    for c in (info.get("help_commands") or []):
        usage = str(c.get("usage") or "").strip() or "（用法未说明）"
        rows.append((usage, str(c.get("desc") or "")))
    if rows:
        _group(cv, "指令用法", rows)

    notes = [str(n) for n in (info.get("notes") or []) if str(n).strip()]
    if info.get("has_web") and info.get("web_port"):
        notes.append("独立页面端口 %s，在 ILBB 后台「插件」面板的「独立页面」里打开。"
                     % info.get("web_port"))
    if notes:
        _group(cv, "使用说明", [("说明 %d" % (i + 1), n) for i, n in enumerate(notes)],
               accent=BLUE)

    fields = info.get("fields") or []
    if fields:
        labels = [str(f.get("label") or f.get("key") or "") for f in fields[:8]]
        line = "、".join([x for x in labels if x])
        if len(fields) > 8:
            line += " 等 %d 项" % len(fields)
        _group(cv, "可配置项",
               [("后台配置", line + "\n在 ILBB 后台「插件」面板里修改，保存后热生效。")],
               accent=OK)

    _footer(cv, "插件帮助 ｜ 发送 %splugin 返回插件列表" % p)
    return _to_png(cv)


# ============================================================================
# 8) /名言 · /生成名言 —— 名言图（横屏 16:9）
#    左侧一块独立的长方形圆角头像；右侧铺满右半边的白色磨砂玻璃面板，
#    面板左缘用横向渐变蒙版渐隐，和中间的背景有过渡（不会出现硬边）。
#    背景取自与主页同源的随机二次元图接口，其上叠一层灰色蒙版；
#    右下角「—— 用户名」（字体跟随全局 FONT_FAMILY）。
#    内容是动图表情包时输出 GIF，否则输出 JPG。
# ============================================================================
QUOTE_PAD_X = 56            # 左右留白
QUOTE_PAD_Y = 48            # 上下留白
QUOTE_AV = 236              # 左侧独立头像的宽度（高度 = 宽度 × QUOTE_AV_RATIO）
QUOTE_AV_RATIO = 1.32       # 头像高宽比（长方形圆角）
QUOTE_AV_R = 30             # 头像圆角
QUOTE_TRAY_PAD = 48         # 玻璃面板内边距
QUOTE_TRAY_GAP = 40         # 头像与玻璃面板之间的呼吸位
QUOTE_TRAY_BLUR = 30        # 玻璃面板的模糊半径（磨砂核心）
QUOTE_TRAY_GLASS = 0.58     # 玻璃浓度（越大越白、越不透）
QUOTE_TRAY_FADE = 0.16      # 面板左缘渐隐过渡区占面板宽度的比例
QUOTE_MAX_BODY = 460        # 内容区最大高度（可由 config.QUOTE_MAX_BODY 覆盖）
QUOTE_NAME_SIZE = 40        # 右下角署名（破折号 + 用户名）字号
QUOTE_NAME_DY = 56          # 署名基线距画布底部


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """按「填满并居中裁切」把图缩放到 w×h"""
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        return Image.new("RGB", (w, h), (24, 22, 28))
    scale = max(w / iw, h / ih)
    nw, nh = max(w, int(iw * scale + 0.5)), max(h, int(ih * scale + 0.5))
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    return img.crop(((nw - w) // 2, (nh - h) // 2,
                     (nw - w) // 2 + w, (nh - h) // 2 + h))


def _quote_bg(w: int, h: int, bg_bytes: bytes | None) -> Image.Image:
    """背景层：随机二次元图（与主页背景同一个接口）+ 灰色蒙版。

    蒙版不透明度取 config.QUOTE_MASK_ALPHA（默认 0.35 = 35% 灰，背景仍可辨认）。
    注意顺序：蒙版只叠在背景层上；托盘、头像与文字随后绘制，位于蒙版之上，
    也就是「背景 → 灰色蒙版 → 前景（托盘 / 头像 / 文字）」。
    """
    try:
        alpha = float(getattr(config, "QUOTE_MASK_ALPHA", 0.35))
    except Exception:
        alpha = 0.35
    alpha = min(1.0, max(0.0, alpha))

    base = None
    if bg_bytes:
        try:
            base = _cover(_first_frame(bg_bytes).convert("RGB"), w, h)
        except Exception:
            base = None
    if base is None:                       # 取不到背景时用深灰渐变兜底
        base = Image.new("RGB", (w, h), (48, 45, 54))
        dd = ImageDraw.Draw(base)
        for y in range(h):
            k = y / max(1, h - 1)
            dd.line([(0, y), (w, y)],
                    fill=(int(82 - 36 * k), int(78 - 34 * k), int(96 - 42 * k)))
    if alpha > 0:
        veil = Image.new("RGB", (w, h), (128, 128, 128))    # 灰色蒙版
        # 用 blend 按比例真正混色；旧版 composite 的 mask 只有 alpha*255，
        # 取整后基本全取原图，等于「蒙版被背景图完全挡住」。
        base = Image.blend(base, veil, alpha)
    return base


def _quote_default_avatar(size: int, ch: str = "") -> Image.Image:
    """没有头像时的占位：深色渐变长方形圆角 + 首字"""
    w = int(size)
    h = int(round(size * QUOTE_AV_RATIO))
    im = Image.new("RGB", (w, h), (52, 48, 60))
    dd = ImageDraw.Draw(im)
    for y in range(h):
        k = y / max(1, h - 1)
        dd.line([(0, y), (w, y)],
                fill=(int(78 - 30 * k), int(70 - 26 * k), int(92 - 34 * k)))
    if ch:
        try:
            f = font(max(18, int(w * 0.42)), True)
            dd.text((w / 2, h / 2), ch, font=f, fill=(255, 255, 255), anchor="mm")
        except Exception:
            pass
    return _round_img(im, min(QUOTE_AV_R, min(w, h) // 2))


def _quote_avatar(avatar: bytes | None, size: int, name: str) -> Image.Image:
    """左侧独立头像：长方形圆角，有图就用图（动图取首帧），否则占位"""
    w = int(size)
    h = int(round(size * QUOTE_AV_RATIO))
    if avatar:
        try:
            src = _cover(_first_frame(avatar).convert("RGB"), w, h)
            return _round_img(src, min(QUOTE_AV_R, min(w, h) // 2))
        except Exception:
            pass
    ch = ""
    for c in str(name or "").strip():
        if not c.isspace():
            ch = c
            break
    return _quote_default_avatar(size, ch)


def _quote_panel(canvas: Image.Image, x: int, y: int, w: int, h: int,
                 fade: int | None = None):
    """白色磨砂玻璃面板（铺满右半边）。

    做法：把面板覆盖范围内的背景（已经叠过灰色蒙版）整块裁出来做一次
    大半径高斯模糊 —— 这就是「磨砂」；再压一层高浓度暖白玻璃 + 顶部反光。
    贴回时用一张横向渐变蒙版：面板左缘 alpha 从 0 递增到满，
    于是左边缘整体透明、和中间的背景自然衔接（没有硬边）。

    面板属于「前景」，画在灰色蒙版之上、头像与文字之下。返回画布上的 ImageDraw。
    """
    x, y, w, h = int(x), int(y), int(w), int(h)
    region = canvas.crop((x, y, x + w, y + h)).convert("RGB")
    try:
        radius = float(getattr(config, "QUOTE_TRAY_BLUR", QUOTE_TRAY_BLUR) or QUOTE_TRAY_BLUR)
    except Exception:
        radius = float(QUOTE_TRAY_BLUR)
    try:
        blurred = region.filter(ImageFilter.GaussianBlur(radius=max(6.0, radius)))
    except Exception:
        blurred = region
    try:
        amount = float(getattr(config, "QUOTE_TRAY_GLASS", QUOTE_TRAY_GLASS) or QUOTE_TRAY_GLASS)
    except Exception:
        amount = float(QUOTE_TRAY_GLASS)
    glass = Image.new("RGB", (w, h), (255, 254, 251))
    fused = Image.blend(blurred, glass, min(0.96, max(0.20, amount)))
    try:
        fused = ImageEnhance.Brightness(fused).enhance(1.04)
    except Exception:
        pass

    if fade is None:
        fade = int(max(60.0, w * QUOTE_TRAY_FADE))
    fade = int(max(0, min(w, fade)))

    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    if fade > 0:
        # 左缘渐变：0 → 255，幂次让过渡更柔（前面慢、后面快）
        for i in range(fade):
            a = int(round(255.0 * ((i + 1) / float(fade)) ** 1.6))
            md.line([(i, 0), (i, h - 1)], fill=max(0, min(255, a)))
        if fade < w:
            md.rectangle([fade, 0, w - 1, h - 1], fill=255)
    else:
        md.rectangle([0, 0, w - 1, h - 1], fill=255)
    canvas.paste(fused, (x, y), mask)

    # 顶部一条淡淡的玻璃反光（同样跟随渐变蒙版，别在左缘切出硬边）
    shine = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shine).rectangle([0, 0, w - 1, max(8, int(h * 0.16))], fill=38)
    if fade > 0:
        for i in range(fade):
            k = (i + 1) / float(fade)
            for yy in range(0, max(8, int(h * 0.16))):
                cur = shine.getpixel((i, yy))
                shine.putpixel((i, yy), int(cur * (k ** 1.6)))
    canvas.paste(Image.new("RGB", (w, h), (255, 255, 255)), (x, y), shine)

    return ImageDraw.Draw(canvas)


def _quote_text_layout(meas, text: str, max_w: int, max_h: int):
    """自动字号：从大往小试探，直到换行后的总高度能装进玻璃面板内容区；返回 (font, lines, line_h)"""
    try:
        hi = int(getattr(config, "QUOTE_TEXT_MAX", 68))
    except Exception:
        hi = 68
    try:
        lo = int(getattr(config, "QUOTE_TEXT_MIN", 24))
    except Exception:
        lo = 24
    lo = max(12, lo)
    hi = max(lo, hi)
    text = str(text or "")
    size = hi
    while size >= lo:
        f = font(size)
        lines = _wrap(meas, text, f, max_w)
        lh = _lh(f, 1.42)
        if lh * len(lines) <= max_h:
            return f, lines, lh
        size -= 2
    f = font(lo)
    lines = _wrap(meas, text, f, max_w)
    lh = _lh(f, 1.42)
    keep = max(1, int(max_h // max(1, lh)))
    if len(lines) > keep:
        lines = lines[:keep]
        lines[-1] = _ellipsis(meas, lines[-1] + "…", f, max_w)
    return f, lines, lh


def _gif_frames(data: bytes) -> list:
    """把一张（可能是动图的）图片拆成 [(RGBA 帧, 时长ms), ...]；解析失败返回 []。"""
    out = []
    if not data:
        return out
    try:
        im = Image.open(io.BytesIO(data))
    except Exception:
        return out
    try:
        n = int(getattr(im, "n_frames", 1) or 1)
    except Exception:
        n = 1
    for i in range(max(1, n)):
        try:
            im.seek(i)
        except Exception:
            break
        try:
            dur = int(im.info.get("duration", 0) or 0)
        except Exception:
            dur = 0
        try:
            fr = im.convert("RGBA")
        except Exception:
            continue
        out.append((fr.copy(), dur))
    return out


def render_quote(text: str = "", name: str = "", avatar: bytes | None = None,
                 images: list | None = None, bg: bytes | None = None) -> bytes:
    """名言图（横屏 16:9）：

    - 左侧一块独立的长方形圆角头像（高度 = 宽度 × QUOTE_AV_RATIO），垂直居中；
    - 右侧是铺满右半边的白色磨砂玻璃面板，面板左缘做横向渐变渐隐，
      和中间的背景自然衔接；面板里放文字（自动字号）与图片（自适应缩放），
      二者可以一起摆——文字在上、图在下；若是动图则整块保留动画、不再拼文字；
    - 内容是动图时输出 GIF，否则输出 JPG；
    - 背景取自与主页同源的随机二次元图接口，其上叠一层灰色蒙版
      （不透明度 config.QUOTE_MASK_ALPHA，默认 0.35），蒙版只压背景，
      玻璃面板与头像都在蒙版之上；
    - 右下角「—— 用户名」，字体跟随全局 config.FONT_FAMILY（不单独配置）。

    返回 JPG 或 GIF 的字节流（调用方用 _sniff_image 判断 mime）。
    """
    width = max(480, int(getattr(config, "QUOTE_WIDTH", W) or W))
    height = max(270, int(getattr(config, "QUOTE_HEIGHT", 720) or 720))
    px, py = QUOTE_PAD_X, QUOTE_PAD_Y
    name = str(name or "").strip() or str(getattr(config, "QUOTE_NAME", "无名氏"))

    name_size = max(18, int(getattr(config, "QUOTE_NAME_SIZE", QUOTE_NAME_SIZE) or QUOTE_NAME_SIZE))

    # ---- 玻璃面板：铺满右半边（整高），左缘一段渐变用来「衔接」背景 ----
    panel_x = int(width // 2)
    panel_w = int(width - panel_x)
    fade = int(max(60.0, panel_w * QUOTE_TRAY_FADE))
    fade = int(min(fade, max(0, panel_w - 120)))

    # ---- 左侧独立头像：长方形圆角，垂直居中 ----
    av = max(96, int(getattr(config, "QUOTE_AVATAR", QUOTE_AV) or QUOTE_AV))
    av = int(min(av, max(96, panel_x - px - QUOTE_TRAY_GAP - 120)))
    av_h = int(round(av * QUOTE_AV_RATIO))
    if av_h > height - py * 2:
        av_h = max(120, height - py * 2)
        av = int(round(av_h / QUOTE_AV_RATIO))
    av_x = px
    av_y = max(py, (height - av_h) // 2)

    # ---- 面板内的内容区（避开左缘渐隐区，右下角给署名留位） ----
    tray_pad = QUOTE_TRAY_PAD
    inner_x = panel_x + fade + int(tray_pad * 0.6)
    inner_w = max(160, width - px - inner_x)
    inner_h = max(120, height - py * 2 - name_size - 24)

    meas = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    # ---- 内容：动图独占托盘；静态图与文字可以一起摆（文字在上、图在下） ----
    raw_frames = []
    if images:
        for data in images:
            raw_frames = _gif_frames(data)
            if raw_frames:
                break
    # 这里只筛「尺寸是否有效」；真正的缩放等版式定下来再做 ——
    # 先按整块 inner_h 预缩、之后再缩一次，会二次插值掉画质。
    valid_frames = [(fr, dur) for fr, dur in raw_frames
                    if fr.size[0] > 0 and fr.size[1] > 0]
    is_anim = len(valid_frames) > 1

    GAP = 16          # 图片与文字之间的间距
    body_frames = []
    stat_img = None
    f_text = lines = None
    line_h = text_h = t_w = img_h = img_w = 0
    if is_anim:
        # 动图逐帧保留动画，撑满托盘；再拼文字会跟动画抢位置，直接省掉
        for fr_img, dur in valid_frames:
            try:
                fitted = _fit(fr_img, inner_w, inner_h)
            except Exception:
                continue
            if fitted.size[0] > 0 and fitted.size[1] > 0:
                body_frames.append((fitted, dur))
        body_h = max([f.size[1] for f, _ in body_frames] or [0])
        content_w = max([f.size[0] for f, _ in body_frames] or [0])
    else:
        body_frames = valid_frames[:1]        # 静态：只留一张，供下面的 JPG 判定
        src_img = valid_frames[0][0] if valid_frames else None
        payload = str(text or "").strip()

        # ---- 自动配比：**先给图片留好位置，再让文字去适应剩下的空间**。
        #      如果反过来（先按整块内容区排文字），文字一长就会把图片挤没 ——
        #      所以这里图片先按「同框时最多 45% 内容区高度」占位，文字在剩余的
        #      text_zone 里自动缩字号 / 截断。这样图片一定放得进来。
        if src_img is not None and payload:
            stat_img = _fit(src_img, inner_w, max(60, int(inner_h * 0.45)))
            img_h, img_w = stat_img.size[1], stat_img.size[0]
            text_zone = max(60, inner_h - GAP - img_h)
        elif src_img is not None:
            stat_img = _fit(src_img, inner_w, inner_h)      # 只有图：撑满托盘
            img_h, img_w = stat_img.size[1], stat_img.size[0]
            text_zone = 0
        else:
            text_zone = inner_h                             # 只有文字：整块给它

        if payload:
            f_text, lines, line_h = _quote_text_layout(meas, payload, inner_w, text_zone)
            text_h = line_h * len(lines)
            try:
                t_w = max([int(meas.textlength(ln, font=f_text)) for ln in lines] or [0])
            except Exception:
                t_w = inner_w

        # ---- 文字没占满自己那块时，把余量还给图片（图片至多长到 55%）----
        if src_img is not None and payload and text_h < text_zone:
            grow_to = min(int(inner_h * 0.55), img_h + (text_zone - text_h))
            if grow_to > img_h:
                stat_img = _fit(src_img, inner_w, grow_to)
                img_h, img_w = stat_img.size[1], stat_img.size[0]

        gap = GAP if (text_h > 0 and img_h > 0) else 0
        body_h = text_h + gap + img_h
        content_w = max(t_w, img_w)

        # ---- 兜底：极端取整误差仍溢出时，只压图（文字不动）----
        if body_h > inner_h and img_h > 0:
            stat_img = _fit(stat_img, inner_w, max(40, img_h - (body_h - inner_h)))
            img_h, img_w = stat_img.size[1], stat_img.size[0]
            gap = GAP if (text_h > 0 and img_h > 0) else 0
            body_h = text_h + gap + img_h
            content_w = max(t_w, img_w)
    content_w = int(min(inner_w, max(120, content_w)))

    # ---- 背景（含灰色蒙版）→ 右半边磨砂玻璃 → 左侧头像 → 内容：前景全在蒙版之上 ----
    canvas = _quote_bg(width, height, bg)

    d = _quote_panel(canvas, panel_x, 0, panel_w, height, fade)

    av_img = _quote_avatar(avatar, av, name)
    canvas.paste(av_img, (av_x, av_y), av_img)

    body_ox = inner_x + max(0, (inner_w - content_w) // 2)
    body_oy = max(py, (height - body_h) // 2)

    # ---- 右下角：破折号 + 用户名（字体跟随全局字体，不再单独配置） ----
    nf = font(name_size, True)
    label = "—— " + name
    nx, ny = width - px, height - QUOTE_NAME_DY
    for dx, dy in ((2, 2), (-2, 2), (2, -2), (-2, -2)):
        d.text((nx + dx, ny + dy), label, font=nf, fill=(0, 0, 0), anchor="rs")
    d.text((nx, ny), label, font=nf, fill=(255, 255, 255), anchor="rs")

    # ---- 文字（在上）＋ 静态图（在下）→ JPG；动图 → 逐帧 GIF ----
    if not is_anim:
        if not lines and stat_img is None:
            # 既没文字也没图（调用方应已兜底），这里画默认文案防止空图
            payload = str(text or "").strip() or "……"
            f_text, lines, line_h = _quote_text_layout(meas, payload, inner_w, inner_h)
            yy0 = max(py, (height - line_h * len(lines)) // 2)
        else:
            yy0 = body_oy
        yy = yy0
        for ln in (lines or []):
            d.text((body_ox, yy), ln, font=f_text, fill=(38, 34, 28), anchor="la")
            yy += line_h
        if stat_img is not None:
            img_x = body_ox + max(0, (content_w - stat_img.size[0]) // 2)
            img_y = body_oy + text_h + (GAP if lines else 0)
            canvas.paste(stat_img, (int(img_x), int(img_y)), stat_img)

    if len(body_frames) <= 1:
        try:
            quality = int(getattr(config, "QUOTE_JPG_QUALITY", 92))
        except Exception:
            quality = 92
        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="JPEG", quality=max(60, min(100, quality)),
                                   optimize=True, progressive=True)
        return buf.getvalue()

    # ---- 多帧表情包 → GIF（共用一个底图，只换托盘里那一块） ----
    try:
        max_frames = max(2, int(getattr(config, "QUOTE_GIF_MAX_FRAMES", 60) or 60))
    except Exception:
        max_frames = 60
    try:
        min_ms = max(20, int(getattr(config, "QUOTE_GIF_MIN_MS", 40) or 40))
    except Exception:
        min_ms = 40

    step = max(1, (len(body_frames) + max_frames - 1) // max_frames)
    picked = body_frames[::step][:max_frames]

    out_frames, durations = [], []
    for img, dur in picked:
        frame = canvas.copy()
        ox = body_ox + max(0, (content_w - img.size[0]) // 2)
        oy = body_oy + max(0, (body_h - img.size[1]) // 2)
        frame.paste(img, (int(ox), int(oy)), img)
        out_frames.append(frame.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256))
        if dur > 0:
            durations.append(max(min_ms, min(500, dur)))
        else:
            durations.append(100)

    buf = io.BytesIO()
    out_frames[0].save(buf, format="GIF", save_all=True, append_images=out_frames[1:],
                       duration=durations, loop=0, disposal=2, optimize=True)
    return buf.getvalue()


def render_quote_help() -> bytes:
    """名言图帮助（/名言 或 /名言 help）"""
    p = config.BOT_PREFIX
    cv = Canvas(W, BG)
    _appbar(cv, "名言合成")
    _page_head(cv, "名言", "名言图 · 使用帮助",
               "引用一条消息，或自己写一句话，机器人把它合成名言图回给你。")

    _group(cv, "指令格式", [
        (f"{p}名言",
         "引用一条消息，直接把那条消息做成名言图：正文＝那条消息的文字＋@（会显示成 @昵称），"
         "那条消息带的图也会一起放进去；署名与头像＝发那条消息的人。"),
        (f"{p}生成名言 文本…",
         "给自己合成：指令后面空一格，再写你想合成的那句话，署名与头像就是你自己。"),
        (f"{p}名言 help", "查看本帮助图。"),
    ])

    _group(cv, "成品长什么样", [
        ("版式", "横屏 16:9，画面正中一块全模糊托盘，里面左头像、右内容。"),
        ("背景", "随机二次元图（与主页背景同一个接口）+ 灰色蒙版（默认不透明度 35%）。"),
        ("托盘", "托盘范围内的背景整块高斯模糊，再压一层暖白玻璃，边缘带亮边。"),
        ("头像", "托盘左侧的圆形头像（有图用图，动图取首帧）。"),
        ("内容", "托盘右侧放文字和图片：文字在上、图在下，可同框；图片自适应缩放。"),
        ("署名", "右下角「—— 用户名」，字体可单独设置。"),
        ("格式", "内容是静态（文字或图）→ JPG；内容是动图 → GIF。"),
    ], accent=BLUE)

    _group(cv, "小提示", [
        ("引用谁，就署谁", "名言严格看「被引用的那条消息」：谁发的，头像和署名就是谁。"),
        ("文字和图片都能保留", "引用的消息里既有文字又有图，两者会一起做进名言图（@ 也会原样显示）。"),
        ("文字太长也不怕", "文字太多时自动缩字号、必要时截断，把位置让给图片，图不会被挤出去。"),
        ("文字兜底", "引用的消息既没文字也没图时，会给一句占位文案，避免出空图。"),
    ], accent=OK)

    _footer(cv, f"输入 {p}名言 help 可随时回看这张图")
    return _to_png(cv)


# ============================================================================
# 输出与缓存
# ============================================================================
def _to_png(cv: Canvas) -> bytes:
    buf = io.BytesIO()
    cv.finish().save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# _CACHE_DIR 在文件顶部统一定义（cache/bot），这里直接复用


def cached_png(tag: str, builder) -> bytes:
    """按 tag 缓存渲染结果到 cache/bot/<tag>.png；渲染失败时直接返回渲染结果"""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = os.path.join(_CACHE_DIR, hashlib.md5(tag.encode("utf-8")).hexdigest() + ".png")
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            if data:
                return data
        data = builder()
        if data:
            with open(path, "wb") as f:
                f.write(data)
        return data
    except Exception:
        return builder()


def cache_tag(*parts) -> str:
    return "|".join(str(p) for p in parts)

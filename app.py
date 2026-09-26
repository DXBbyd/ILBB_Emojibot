# -*- coding: utf-8 -*-
from flask import (Flask, render_template, request, jsonify, send_file,
                   send_from_directory, redirect, session)
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import json
import sys
import requests
from io import BytesIO
import base64
import hashlib
import time
import re

# 模块脚本统一放在 core/ 里，这里把 core/ 加进模块搜索路径，
# 之后所有 import（config / ws_server / bot_render ...）都从 core/ 解析。
_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_HERE, 'core')
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import api_key_store
import config

app = Flask(__name__)

# 模板自动重载：WEB_DEBUG=false 时 Jinja 会缓存已编译模板，
# 导致改了 templates/*.html 后刷新页面看不到变化（必须重启服务）。
# 本地工具无性能压力，这里常开，改模板刷新即生效。
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ==================== 管理密码（持久化） ====================
# 密码保存在 api_keys.json 的 admin_hash 中，服务重启后保持不变。
# 只有「用户在界面上自己设的」密码算数：启动时随机生成（或取自 .env 的
# INIT_ADMIN_PASSWORD）的那枚只算临时密码，明文留在 api_keys.json 里，
# 每次启动都重新打印一遍，用户错过一次也不会被锁在门外。
# 用户确认后（引导页第 4 步或 设置→修改密码）临时密码作废，终端不再打印。
import random
import string


def _gen_admin_pwd(n=8):
    alph = string.ascii_uppercase + string.digits
    return ''.join(random.SystemRandom().choice(alph) for _ in range(n))


if api_key_store.admin_password_pending():
    _from_env = config.INIT_ADMIN_PASSWORD.strip()
    _init_pwd = api_key_store.admin_temp_password() or _from_env or _gen_admin_pwd()
    _init_src = "env" if _from_env else "auto"
    api_key_store.set_admin_password(_init_pwd, source=_init_src)
    print('=' * 56, flush=True)
    if _init_src == "env":
        print('[管理后台] 管理密码取自 .env 的 INIT_ADMIN_PASSWORD，你还没有在界面上确认过', flush=True)
    else:
        print('[管理后台] 临时管理密码: ' + _init_pwd + '（本次随机生成，重启后会再次打印）', flush=True)
    print('[管理后台] 打开 http://<本机IP>:' + str(config.WEB_PORT) + '/setup 设一个你自己的管理密码', flush=True)
    print('[管理后台] 设好后这枚临时密码作废，之后可在 设置→修改密码 中更换', flush=True)
    print('=' * 56, flush=True)
else:
    print('[管理后台] 使用已保存的管理密码登录（服务重启保持不变，可在 设置→修改密码 中更换）', flush=True)

# 图片以 base64 表单字段上传（头像/上传图可能很大），放宽请求体限制
# .env: WEB_MAX_UPLOAD_MB（默认 64）
app.config['MAX_CONTENT_LENGTH'] = config.WEB_MAX_UPLOAD_BYTES
app.config['MAX_FORM_MEMORY_SIZE'] = config.WEB_MAX_UPLOAD_BYTES

# 文件夹配置（.env: TEMP_DIR / CACHE_DIR / FONT_DIR / BG_DIR）
TEMP_DIR = config.TEMP_DIR
CACHE_DIR = config.CACHE_DIR
FONT_DIR = config.FONT_DIR
BG_DIR = config.BG_DIR
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(FONT_DIR, exist_ok=True)
os.makedirs(BG_DIR, exist_ok=True)

# 头像磁盘缓存目录（cache/avatars/，cache/ 已被 .gitignore 忽略）
# 说明：clear_cache / cache_status 只遍历 CACHE_DIR 顶层文件，子目录不会干扰统计
AVATAR_DIR = os.path.join(CACHE_DIR, 'avatars')
os.makedirs(AVATAR_DIR, exist_ok=True)

# 缓存过期时间（秒），.env: CACHE_EXPIRE_DAYS（默认 30 天）
CACHE_EXPIRE_SECONDS = config.CACHE_EXPIRE_SECONDS

# 进程启动时间，用于状态页计算运行时长
SERVER_START = time.time()

# 画布尺寸（.env: CANVAS_WIDTH / CANVAS_HEIGHT）
CANVAS_W, CANVAS_H = config.CANVAS_W, config.CANVAS_H

# ==================== 模板注册 ====================
# 每款模板对应一个绘制函数 render_<key>()
TEMPLATES = {
    'classic': ('classic', '经典弹窗（浅蓝玻璃）', '清爽蓝白毛玻璃'),
    'dark':    ('dark', '深邃玻璃（暗色高光）', '深色通透玻璃'),
    'paper':   ('paper', '清新纸张（温和证件）', '柔和信纸风'),
}


def get_available_fonts():
    """扫描font文件夹获取所有字体文件"""
    fonts = {}

    extensions = ('.ttf', '.ttc', '.otf', '.TTF', '.TTC', '.OTF')

    if os.path.exists(FONT_DIR):
        for filename in os.listdir(FONT_DIR):
            if filename.endswith(extensions):
                name_without_ext = os.path.splitext(filename)[0]
                display_name = name_without_ext.replace('_', ' ').replace('-', ' ').title()
                fonts[filename] = display_name

    if not fonts:
        fonts["default"] = "⚠️ 请将字体文件放入 font/ 文件夹"

    return fonts


def load_font(font_key, size):
    """加载字体。

    查找顺序统一交给 core.bot_render.font()：指定字体（font/ 下的文件名或绝对路径）
    → 全局字体 → Windows 字体 → 项目 font/ 目录 → 带 size 的 PIL 默认字体。
    这里不再自己拼 Windows 字体路径 —— 那套在 Linux 上会一路落空，最后拿到
    既没有中文字形、又不带 size 的 ImageFont.load_default()，配对卡上的中文就被画成
    极小方块，看上去像乱码。
    """
    try:
        if bot_render is not None:
            return bot_render.font(int(size), family=font_key)
    except Exception as e:
        print(f"加载字体 {font_key} 失败: {e}")

    # bot_render 不可用时的兜底：项目 font/ 目录，最后才用带 size 的默认字体
    try:
        for fn in sorted(os.listdir(FONT_DIR)):
            if fn.lower().endswith(('.ttf', '.ttc', '.otf')):
                return ImageFont.truetype(os.path.join(FONT_DIR, fn), size)
    except Exception:
        pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def get_qq_info(qq_number):
    """通过API一次性获取QQ昵称和头像URL"""
    url = f"https://api3.mhimg.cn/api/nickname?qq={qq_number}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            response.encoding = 'utf-8'
            data = response.json()
            if data.get("code") == "success":
                info = data.get("data", {})
                nickname = info.get("nickname", str(qq_number))
                avatar_url = info.get("avatar_url", "")
                return nickname, avatar_url
    except Exception as e:
        print(f"获取QQ信息出错: {e}")
    return str(qq_number), None


def download_qq_avatar_from_url(avatar_url):
    """从URL下载头像"""
    if not avatar_url:
        return None
    try:
        if 's=140' in avatar_url:
            avatar_url = avatar_url.replace('s=140', 's=640')
        response = requests.get(avatar_url, timeout=10)
        if response.status_code == 200:
            return Image.open(BytesIO(response.content)).convert("RGBA")
    except:
        pass
    return None


def crop_circle(avatar_img, size):
    """将头像裁剪成圆形"""
    avatar_img = avatar_img.resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse([0, 0, size, size], fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(avatar_img, (0, 0), mask)
    return result


# ==================== 背景系统 ====================
def hex_to_rgb(hex_str, fallback=(207, 217, 242)):
    h = str(hex_str or '').strip().lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return fallback
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def make_gradient(size, colors, direction='vertical'):
    """用插值放大生成平滑渐变层（速度快）"""
    w, h = size
    n = len(colors)
    if n < 1:
        colors = [(200, 200, 220)]
        n = 1
    if direction == 'diagonal':
        small = Image.new('RGB', (2, 2))
        px = small.load()
        c0 = colors[0]
        c1 = colors[-1]
        mid = colors[n // 2] if n > 2 else c0
        px[0, 0] = c0
        px[1, 0] = mid
        px[0, 1] = mid
        px[1, 1] = c1
    else:
        small = Image.new('RGB', (1, n))
        for i, c in enumerate(colors):
            small.putpixel((0, i), c)
    return small.resize((w, h), Image.Resampling.BICUBIC).convert('RGBA')


def cover_resize(img, w, h):
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale + 0.5), int(ih * scale + 0.5)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def build_background(size, bg_config):
    """根据配置构建模糊背景图，返回 RGBA 画布"""
    w, h = size
    bg_config = bg_config or {}
    btype = bg_config.get('type', 'gradient')
    blur = float(bg_config.get('blur', 0))

    img = None
    if btype == 'image':
        b64 = bg_config.get('image', '')
        if b64:
            try:
                raw = base64.b64decode(b64)
                src = Image.open(BytesIO(raw)).convert('RGB')
                img = cover_resize(src, w, h)
            except Exception as e:
                print(f"背景图解析失败: {e}")
                img = None

    if img is None:
        if btype == 'color':
            c = hex_to_rgb(bg_config.get('color', '#dce6f5'))
            img = Image.new('RGB', (w, h), c)
        else:
            colors = [hex_to_rgb(c) for c in bg_config.get('colors', ['#bcc9f0', '#eef4ff'])]
            dirn = bg_config.get('direction', 'vertical')
            img = make_gradient((w, h), colors, dirn)

    return img.filter(ImageFilter.GaussianBlur(radius=blur)).convert('RGBA')


def wrap_text(draw, text, font, max_width):
    """按像素宽度自动换行"""
    lines = []
    cur = ''
    for ch in text:
        txt = cur + ch
        bb = draw.textbbox((0, 0), txt, font=font)
        if (bb[2] - bb[0]) <= max_width:
            cur = txt
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [text]


def center_text(draw, lines, font, cx, start_y, line_height, fill):
    """居中绘制多行文字，返回最后一行底部 y"""
    y = start_y
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        tx = cx - bb[0] - (bb[2] - bb[0]) / 2
        draw.text((tx, y), line, font=font, fill=fill)
        y += line_height
    return y - line_height


def rounded_avatar(avatar, size, ring_color=None, ring_width=0, ring_expand=0):
    """圆形头像，可选描边光圈"""
    if avatar is None:
        base = Image.new('RGBA', (size, size), (200, 200, 200, 255))
    else:
        base = crop_circle(avatar, size)
    if ring_color and ring_width > 0:
        canvas = Image.new('RGBA', (size + ring_expand * 2, size + ring_expand * 2), (0, 0, 0, 0))
        mask = Image.new('L', (size + ring_expand * 2, size + ring_expand * 2), 0)
        m = ImageDraw.Draw(mask)
        m.ellipse([0, 0, size + ring_expand * 2, size + ring_expand * 2], fill=255)
        canvas.paste(ring_color + (255,), (0, 0), mask)
        canvas.alpha_composite(base, (ring_expand, ring_expand))
        return canvas, ring_expand
    return base, 0


def _full_avatar(avatar, size):
    """返回完整头像（无光圈时返回原图以保持布局一致）"""
    if avatar is None:
        return Image.new('RGBA', (size, size), (200, 200, 200, 255)), 0
    return avatar, 0


def get_fonts(font_key):
    return {
        'title': load_font(font_key, 30),
        'btn': load_font(font_key, 28),
        'small': load_font(font_key, 20),
    }


# ==================== 各模板绘制 ====================
def draw_card(bg, title_text, avatar, fonts, template, buttons):
    """根据模板分发绘制（按钮统一在 draw_buttons 处理）"""
    fn = DRAWERS.get(template)
    if fn is None:
        fn = render_classic
    img = fn(bg, title_text, avatar, fonts)
    draw_buttons(img, buttons, fonts, template)
    return img


def render_classic(bg, title_text, avatar, fonts):
    """经典弹窗：浅蓝玻璃"""
    width, height = bg.size
    dialog_x, dialog_y = 50, 150
    dialog_w, dialog_h = 500, 550
    corner = 40

    img = bg.copy()
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle([dialog_x, dialog_y, dialog_x + dialog_w, dialog_y + dialog_h],
                        radius=corner, fill=(255, 255, 255, 180))
    d.rounded_rectangle([dialog_x, dialog_y, dialog_x + dialog_w, dialog_y + dialog_h],
                        radius=corner, outline=(255, 255, 255, 120), width=2)
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)

    lines = wrap_text(draw, title_text, fonts['title'], dialog_w - 60)
    cx = width / 2
    last_y = center_text(draw, lines, fonts['title'], cx, dialog_y + 40, 50, (0, 0, 0))

    avatar_size = 160
    a, off = _full_avatar(avatar, avatar_size)
    if avatar:
        a, off = rounded_avatar(avatar, avatar_size, ring_color=(255, 255, 255), ring_width=4, ring_expand=8)
    a_off = off or 0
    ax = cx - (avatar_size + a_off * 2) / 2
    img.alpha_composite(a, (int(ax), int(last_y + 50)))

    return img


def _center_btn_text(draw, cx, cy, text, font, fill):
    bb = draw.textbbox((0, 0), text, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    # 用 bbox 左/上偏移补偿，使文字真正居中（避免部分字体 bbox 起点非 0 导致的错位）
    draw.text((cx - bb[0] - w / 2, cy - bb[1] - h / 2 - 2), text, font=font, fill=fill)


def draw_rounded_gradient(dst, box, radius, colors, direction='horizontal'):
    """在 dst(RGBA) 上绘制圆角渐变填充"""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0, y1 - y0
    grad = make_gradient((w, h), colors, 'horizontal' if direction == 'horizontal' else 'vertical')
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    dst.paste(grad, (x0, y0), mask)


def render_dark(bg, title_text, avatar, fonts):
    """深邃玻璃：暗色高光 + 光圈头像"""
    width, height = bg.size
    dialog_x, dialog_y = 50, 150
    dialog_w, dialog_h = 500, 550
    corner = 46

    img = bg.copy()
    # 顶部环境光斑
    glow = ImageDraw.Draw(img, 'RGBA')
    glow.ellipse([-80, -80, 420, 260], fill=(120, 90, 255, 40))
    glow.ellipse([300, -60, 720, 300], fill=(0, 200, 255, 35))

    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle([dialog_x, dialog_y, dialog_x + dialog_w, dialog_y + dialog_h],
                        radius=corner, fill=(20, 28, 55, 195))
    d.rounded_rectangle([dialog_x, dialog_y, dialog_x + dialog_w, dialog_y + dialog_h],
                        radius=corner, outline=(255, 255, 255, 70), width=2)
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)

    # 标题高光文字（投影）
    lines = wrap_text(draw, title_text, fonts['title'], dialog_w - 70)
    cx = width / 2
    y = dialog_y + 40
    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=fonts['title'])
        tx = cx - bb[0] - (bb[2] - bb[0]) / 2
        draw.text((tx + 1, y + 2 + i * 52), line, font=fonts['title'], fill=(0, 0, 0))
        draw.text((tx, y + i * 52), line, font=fonts['title'], fill=(255, 255, 255))
    last_y = y + (len(lines) - 1) * 52

    avatar_size = 150
    a, off = rounded_avatar(avatar, avatar_size, ring_color=(90, 150, 255), ring_width=5, ring_expand=10)
    ax = cx - (avatar_size + off * 2) / 2
    img.alpha_composite(a, (int(ax), int(last_y + 45)))

    btn_margin, btn_h = 30, 0
    return img


def render_paper(bg, title_text, avatar, fonts):
    """清新纸张：柔和证件风"""
    width, height = bg.size
    card_x, card_y = 50, 150
    card_w, card_h = 500, 550
    corner = 18

    img = bg.copy()
    # 柔和阴影（模糊黑块）
    shadow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    s = ImageDraw.Draw(shadow)
    s.rounded_rectangle([card_x + 8, card_y + 14, card_x + card_w + 8, card_y + card_h + 14],
                        radius=corner, fill=(0, 0, 0, 60))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=10)))

    cardinal = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(cardinal)
    d.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                        radius=corner, fill=(255, 253, 250, 240))
    d.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                        radius=corner, outline=(230, 214, 200, 180), width=1)
    img.alpha_composite(cardinal)
    draw = ImageDraw.Draw(img)

    # 顶部装饰线
    top_line_x = card_x + 30
    draw.rounded_rectangle([top_line_x, card_y + 26, top_line_x + 40, card_y + 32], radius=3, fill=(255, 159, 67))

    lines = wrap_text(draw, title_text, fonts['title'], card_w - 70)
    cx = width / 2
    y = card_y + 56
    for i, line in enumerate(lines):
        bb = draw.textbbox((0, 0), line, font=fonts['title'])
        tx = cx - bb[0] - (bb[2] - bb[0]) / 2
        draw.text((tx, y + i * 48), line, font=fonts['title'], fill=(60, 55, 48))
    last_y = y + (len(lines) - 1) * 48

    avatar_size = 150
    a, off = rounded_avatar(avatar, avatar_size, ring_color=(255, 159, 67), ring_width=3, ring_expand=6)
    ax = cx - (avatar_size + off * 2) / 2
    img.alpha_composite(a, (int(ax), int(last_y + 40)))

    return img


DRAWERS = {
    'classic': render_classic,
    'dark': render_dark,
    'paper': render_paper,
}

# ==================== 多按钮绘制 ====================
BTN_THEMES = {
    'classic': {'bg': (45, 120, 255), 'text': (255, 255, 255), 'radius': 15},
    'dark': {'bg': (90, 95, 255), 'text': (255, 255, 255), 'radius': 20},
    'paper': {'bg': (255, 159, 67), 'text': (255, 255, 255), 'radius': 18},
}


def _btn_fill(img, box, theme):
    radius = theme.get('radius', 15)
    if theme.get('grad'):
        draw_rounded_gradient(img, box, radius, theme['grad'], 'horizontal')
    else:
        ImageDraw.Draw(img).rounded_rectangle(box, radius=radius, fill=theme['bg'])


def _cover_round(img, box, radius, icon):
    """用图片 cover 填充圆角区域"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    ic = icon.convert('RGB')
    iw, ih = ic.size
    scale = max(w / iw, h / ih)
    nw, nh = int(iw * scale + 0.5), int(ih * scale + 0.5)
    ic = ic.resize((nw, nh), Image.Resampling.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    ic = ic.crop((left, top, left + w, top + h))
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    img.paste(ic, (x0, y0), mask)


def _btn_content(img, draw, box, b, font, theme):
    """绘制单个按钮内容（纯文字 / 图标+文字 / 纯图片）"""
    typ = b.get('type', 'text')
    text = str(b.get('text', '')).strip()
    icon = b.get('icon')
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    if typ == 'image' and icon is not None:
        _cover_round(img, box, theme.get('radius', 15), icon)
        return

    icon_size = 26
    has_icon = icon is not None

    # 度量文字
    tw = th = 0
    if text:
        bb = draw.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]

    if has_icon:
        total = icon_size + (8 if text else 0) + tw
    else:
        total = tw
    start_x = cx - total / 2

    if has_icon:
        ci = crop_circle(icon, icon_size)
        img.alpha_composite(ci, (int(start_x), int(cy - icon_size / 2)))
        start_x += icon_size + 8

    if text:
        bb = draw.textbbox((0, 0), text, font=font)
        draw.text((start_x - bb[0], cy - bb[1] - th / 2 - 1), text, font=font, fill=theme['text'])


def draw_buttons(img, buttons, fonts, template):
    """统一在卡片底部绘制按钮。buttons: [{type, text, icon(可选PIL)}]"""
    theme = BTN_THEMES.get(template, BTN_THEMES['classic'])
    if not buttons:
        buttons = [{'type': 'text', 'text': '配对', 'icon': None}]

    n = len(buttons)
    ax0, ax1 = 80, 520
    area_w = ax1 - ax0
    gap = 12
    draw = ImageDraw.Draw(img)

    if n == 1:
        box = [ax0, 610, ax1, 674]
        _btn_fill(img, box, theme)
        _btn_content(img, draw, box, buttons[0], fonts['btn'], theme)
    else:
        cols = 2
        rows = (n + 1) // 2
        cell_h = 52
        cell_w = (area_w - gap) / 2
        top = 696 - rows * cell_h - (rows - 1) * gap
        f = fonts['small']
        for i, b in enumerate(buttons[:4]):
            r_, c_ = divmod(i, 2)
            x0 = ax0 + c_ * (cell_w + gap)
            y0 = top + r_ * (cell_h + gap)
            box = [int(x0), int(y0), int(x0 + cell_w), int(y0 + cell_h)]
            _btn_fill(img, box, theme)
            _btn_content(img, draw, box, b, f, theme)


DEFAULT_BG_COLORS = {
    'classic': ['#bcc9f0', '#eef4ff'],
    'dark': ['#1a2547', '#3a2c6e'],
    'paper': ['#f7ecd9', '#fff8f0'],
}


# 卡片绘制版本号：改了字体或版式后 +1。
# 缓存键里带上它，群里和 WebUI 的旧缓存图才会失效重绘（对齐 bot_render.RENDER_VERSION 的做法）。
CARD_RENDER_VERSION = 2


def generate_cache_key(qq_number, title_text, btn_text, font_key, template, bg_config, buttons_meta=None):
    """生成缓存键（包含模板、背景与按钮配置）"""
    bg_json = json.dumps(bg_config or {}, sort_keys=True)
    bt = buttons_meta if buttons_meta else [{'type': 'text', 'text': btn_text, 'icon': ''}]
    bt_json = json.dumps(bt, ensure_ascii=False, sort_keys=True)
    content = f"{qq_number}|{title_text}|{font_key}|{template}|{bg_json}|{bt_json}|v{CARD_RENDER_VERSION}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def get_cached_image(cache_key):
    """读取缓存图片"""
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.png")
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < CACHE_EXPIRE_SECONDS:
            return cache_path
        else:
            os.remove(cache_path)
    return None


def save_cache_image(cache_key, image):
    """保存图片到缓存"""
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.png")
    image.convert("RGB").save(cache_path)
    return cache_path


def clean_old_cache():
    """清理过期缓存"""
    now = time.time()
    for filename in os.listdir(CACHE_DIR):
        filepath = os.path.join(CACHE_DIR, filename)
        if os.path.isfile(filepath):
            mtime = os.path.getmtime(filepath)
            if now - mtime > CACHE_EXPIRE_SECONDS:
                try:
                    os.remove(filepath)
                except:
                    pass


def get_safe_filename(name):
    """生成安全的文件名"""
    safe = re.sub(r'[\\/*?:"<>|]', '', name)
    if len(safe) > 50:
        safe = safe[:50]
    return safe.strip() or "配对"


def generate_pair_image(qq_number, title_text, avatar, font_key, template, bg_config, buttons):
    """生成卡片图片，固定尺寸 600x800"""
    bg = build_background((CANVAS_W, CANVAS_H), bg_config)
    fonts = get_fonts(font_key)
    final_img = draw_card(bg, title_text, avatar, fonts, template, buttons)
    return final_img


# ==================== 路由 ====================
# ---------- 背景图片（全局生效） ----------
# 路径与接口地址均由 .env 提供（BG_CONFIG_PATH / BG_API_URL）
BG_CONFIG_PATH = config.BG_CONFIG_PATH
BG_API = config.BG_API

# ---------- 配置热重载 ----------
# 上面的目录 / 画布尺寸 / 背景接口地址等都是 import 时固化的模块级常量。
# 「设置」页保存 .env 后，config.apply_updates() 会 reload 自己并回调这里，
# 把这些常量按新配置重算一遍，从而免重启生效（标 hot=false 的项仍需重启）。
def _apply_config_reload(changed=None):
    global TEMP_DIR, CACHE_DIR, FONT_DIR, BG_DIR, AVATAR_DIR
    global CACHE_EXPIRE_SECONDS, CANVAS_W, CANVAS_H
    global BG_CONFIG_PATH, BG_API

    TEMP_DIR = config.TEMP_DIR
    CACHE_DIR = config.CACHE_DIR
    FONT_DIR = config.FONT_DIR
    BG_DIR = config.BG_DIR
    AVATAR_DIR = os.path.join(CACHE_DIR, 'avatars')
    for _d in (TEMP_DIR, CACHE_DIR, FONT_DIR, BG_DIR, AVATAR_DIR):
        try:
            os.makedirs(_d, exist_ok=True)
        except Exception:
            pass
    CACHE_EXPIRE_SECONDS = config.CACHE_EXPIRE_SECONDS
    CANVAS_W, CANVAS_H = config.CANVAS_W, config.CANVAS_H
    BG_CONFIG_PATH = config.BG_CONFIG_PATH
    BG_API = config.BG_API
    # 全局字体 / 字体目录一改，必须把渲染层的字体对象缓存清掉，
    # 否则 ImageFont 旧对象还在，新字体不会生效。
    try:
        bot_render.clear_font_cache()
    except Exception:
        pass
    # 上传体积上限是 .env 的派生值，同样需要重新应用到 Flask
    app.config['MAX_CONTENT_LENGTH'] = config.WEB_MAX_UPLOAD_BYTES
    app.config['MAX_FORM_MEMORY_SIZE'] = config.WEB_MAX_UPLOAD_BYTES


config.on_reload(_apply_config_reload)


def _read_bg():
    try:
        with open(BG_CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
            if not isinstance(c, dict):
                raise ValueError
            # 兼容旧配置：缺失时补默认模糊/蒙版
            c.setdefault("blur", 0)
            c.setdefault("mask", 0.42)
            return c
    except Exception:
        return {"type": "remote", "ts": int(time.time()), "blur": 0, "mask": 0.42}


def _save_bg(c):
    with open(BG_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def _resolve_remote(url, timeout=None):
    """跟随跳转解析出随机的最终直链（如 list.yppp.net/d/image/xxx.png）。
    api.php?t=... 每次访问会重新随机，必须把解析后的稳定直链存下来。
    timeout 默认取 .env 的 BG_FETCH_TIMEOUT（每次调用现取，支持热重载）。"""
    if timeout is None:
        timeout = config.BG_FETCH_TIMEOUT
    try:
        r = requests.get(url, allow_redirects=True, stream=True, timeout=timeout)
        final = r.url
        r.close()
        return final or url
    except Exception:
        return url


def _bg_url(c):
    # 已解析出的稳定直链 / 已上传图片优先；否则退回 api.php?t=（不稳定，仅兜底）
    if c.get("url"):
        return c["url"]
    if c.get("type") == "upload":
        return ""
    ts = c.get("ts") or int(time.time())
    return BG_API + "?t=" + str(ts)


def _ensure_remote_url(c):
    """remote 型但还没有稳定直链时，解析一次并存盘，保证首次 GET 即返回稳定链接。"""
    if c.get("type") == "upload" or c.get("url"):
        return
    c["url"] = _resolve_remote(BG_API + "?t=" + str(c.get("ts") or int(time.time())))
    _save_bg(c)


@app.route('/api/background', methods=['GET'])
def background_get():
    c = _read_bg()
    _ensure_remote_url(c)
    return jsonify({"type": c.get("type", "remote"), "url": _bg_url(c),
                    "blur": c.get("blur", 0), "mask": c.get("mask", 0.42)})


@app.route('/api/background/set', methods=['POST'])
def background_set():
    d = request.get_json(silent=True) or {}
    c = _read_bg()
    if 'blur' in d and isinstance(d.get('blur'), (int, float)):
        c['blur'] = round(max(0.0, min(40.0, float(d['blur']))), 1)
    if 'mask' in d and isinstance(d.get('mask'), (int, float)):
        c['mask'] = round(max(0.0, min(0.9, float(d['mask']))), 2)
    _save_bg(c)
    return jsonify({"ok": True, "blur": c.get("blur", 0), "mask": c.get("mask", 0.42)})


@app.route('/api/background/refresh', methods=['POST'])
def background_refresh():
    c = _read_bg()
    c["type"] = "remote"
    c["ts"] = int(time.time() * 1000)
    c["url"] = _resolve_remote(BG_API + "?t=" + str(c["ts"]))
    _save_bg(c)
    return jsonify({"ok": True, "type": "remote", "url": c["url"],
                    "blur": c.get("blur", 0), "mask": c.get("mask", 0.42)})


@app.route(config.BG_URL_PREFIX + '/<path:name>')
def background_file(name):
    """从 .env 指定的 BG_DIR 提供背景图（默认 /bg/<文件名>）。

    这样 BG_DIR 可以移到 static 之外（甚至磁盘其他位置），前端链接依旧有效。
    """
    return send_from_directory(BG_DIR, name)


@app.route('/api/background/upload', methods=['POST'])
def background_upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({"error": "请选择图片文件"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
        return jsonify({"error": "不支持的图片格式"}), 400
    fname = "custom_" + str(int(time.time() * 1000)) + ext
    f.save(os.path.join(BG_DIR, fname))
    c = _read_bg()
    c["type"] = "upload"
    c["url"] = config.BG_URL_PREFIX + "/" + fname
    _save_bg(c)
    return jsonify({"ok": True, "type": "upload", "url": c["url"],
                    "blur": c.get("blur", 0), "mask": c.get("mask", 0.42)})


@app.route('/api/background/reset', methods=['POST'])
def background_reset():
    c = _read_bg()
    c["type"] = "remote"
    c["ts"] = int(time.time() * 1000)
    c["url"] = _resolve_remote(BG_API + "?t=" + str(c["ts"]))
    _save_bg(c)
    return jsonify({"ok": True, "type": "remote", "url": c["url"],
                    "blur": c.get("blur", 0), "mask": c.get("mask", 0.42)})


@app.route('/')
def index():
    # 管理密码待确认 / 引导未完成 / 素材缺失 → 先去引导页（/setup）
    _need, _why = _setup_needed()
    if _need:
        if _why == 'assets':
            return redirect('/setup?step=assets')
        if _why == 'password':
            return redirect('/setup?step=4')   # 直接落到「设置管理密码」那一步
        return redirect('/setup')
    # 工作台受管理密码保护（密码每次启动随机生成，见启动日志）
    if not session.get('admin_ok'):
        return render_template('lock.html')
    clean_old_cache()
    fonts = get_available_fonts()
    import re
    templates = [{'key': k, 'name': re.sub(r'[（(].*?[）)]', '', v[1]).strip(),
                  'desc': v[2], 'colors': DEFAULT_BG_COLORS.get(k, ['#bcc9f0', '#eef4ff'])} for k, v in TEMPLATES.items()]
    return render_template('index.html', font_options=fonts, templates=templates)


@app.route('/api/get_user_info', methods=['POST'])
def get_user_info():
    data = request.get_json()
    qq_number = data.get('qq', '').strip()

    if not qq_number or not qq_number.isdigit():
        return jsonify({'error': '请输入有效的QQ号'}), 400

    qq_name, avatar_url = get_qq_info(qq_number)

    avatar = None
    avatar_base64 = None
    if avatar_url:
        avatar = download_qq_avatar_from_url(avatar_url)
        if avatar:
            buffer = BytesIO()
            avatar.save(buffer, format='PNG')
            avatar_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return jsonify({
        'qq': qq_number,
        'name': qq_name,
        'avatar': avatar_base64
    })


@app.route('/api/generate_image', methods=['POST'])
def generate_image():
    data = request.get_json()
    qq_number = data.get('qq', '').strip()
    qq_name = data.get('name', '').strip()
    avatar_base64 = data.get('avatar', '')
    custom_text = data.get('text', '要与 {name} 配对吗？')
    btn_text = data.get('btn_text', '配对')
    font_key = data.get('font', 'default')
    template = data.get('template', 'classic')

    raw_bg = data.get('bg')
    bg_config = {}
    if isinstance(raw_bg, dict):
        bg_config = raw_bg
    elif isinstance(raw_bg, str):
        try:
            bg_config = json.loads(raw_bg) or {}
        except Exception:
            bg_config = {}

    if template not in DRAWERS:
        template = 'classic'

    final_title = custom_text.replace('{name}', qq_name)

    # 解析按钮数组
    buttons, buttons_meta = [], []
    raw_buttons = data.get('buttons')
    if raw_buttons and isinstance(raw_buttons, list):
        for b in raw_buttons[:4]:
            if not isinstance(b, dict):
                continue
            typ = b.get('type', 'text')
            text = str(b.get('text', '')).strip()
            ib64 = str(b.get('icon', '') or '')
            icon = None
            if ib64:
                try:
                    icon = Image.open(BytesIO(base64.b64decode(ib64))).convert('RGBA')
                except Exception:
                    icon = None
            if typ == 'image' and icon is not None:
                text = ''
            elif typ in ('icon_text', 'image') and icon is None:
                typ = 'text'  # 无图则退回纯文字
            if typ == 'text' and not text:
                continue  # 空按钮忽略
            buttons.append({'type': typ, 'text': text, 'icon': icon})
            buttons_meta.append({'type': typ, 'text': text, 'icon': ib64[:64]})

    if not buttons:
        buttons = [{'type': 'text', 'text': btn_text, 'icon': None}]
        buttons_meta = [{'type': 'text', 'text': btn_text, 'icon': ''}]

    cache_key = generate_cache_key(qq_number, final_title, btn_text, font_key, template, bg_config, buttons_meta)

    cached_path = get_cached_image(cache_key)
    if cached_path:
        print(f"✅ 命中缓存: {cache_key}")
        return jsonify({
            'download_url': f'/download_cache/{cache_key}',
            'preview_url': f'/api/preview/{cache_key}',
            'cached': True,
            'filename': f"要与{get_safe_filename(qq_name)}配对吗？.png"
        })

    avatar = None
    if avatar_base64:
        try:
            image_data = base64.b64decode(avatar_base64)
            avatar = Image.open(BytesIO(image_data)).convert("RGBA")
        except:
            pass

    img = generate_pair_image(qq_number, final_title, avatar, font_key, template, bg_config, buttons)
    save_cache_image(cache_key, img)
    print(f"✅ 生成并缓存: {cache_key}")

    return jsonify({
        'download_url': f'/download_cache/{cache_key}',
        'preview_url': f'/api/preview/{cache_key}',
        'cached': False,
        'filename': f"要与{get_safe_filename(qq_name)}配对吗？.png"
    })


@app.route('/api/preview/<cache_key>')
def preview_image(cache_key):
    """获取预览图片"""
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.png")
    if os.path.exists(cache_path):
        return send_file(cache_path, mimetype='image/png')
    return '图片不存在', 404


@app.route('/download_cache/<cache_key>')
def download_cache(cache_key):
    """从缓存下载图片"""
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.png")
    if os.path.exists(cache_path):
        filename = request.args.get('filename', '配对.png')
        safe_filename = re.sub(r'[\\/*?:"<>|]', '', filename)
        if not safe_filename.endswith(('.jpg', '.png', '.jpeg')):
            safe_filename += '.png'
        return send_file(cache_path, as_attachment=True, download_name=safe_filename)
    return '文件不存在或已过期', 404


@app.route('/api/clear_cache', methods=['POST'])
def clear_cache():
    try:
        for f in os.listdir(CACHE_DIR):
            filepath = os.path.join(CACHE_DIR, f)
            if os.path.isfile(filepath):
                os.remove(filepath)
        return jsonify({'success': True, 'message': '缓存已清空'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/cache_status', methods=['GET'])
def cache_status():
    files = os.listdir(CACHE_DIR)
    total_size = 0
    for f in files:
        filepath = os.path.join(CACHE_DIR, f)
        if os.path.isfile(filepath):
            total_size += os.path.getsize(filepath)
    return jsonify({
        'count': len(files),
        'size': round(total_size / 1024, 2)
    })


# ==================== Meme 表情包路由 ====================
import platform

QQ_NICK_API = "https://api3.mhimg.cn/api/nickname"


@app.route('/api/status', methods=['GET'])
def api_status():
    """状态检查：汇总服务器 / Meme 服务 / 缓存 / 字体 / 目录 / QQ 接口的实时状态。"""
    # 1) 目录存在性与可写性
    dirs = []
    for d in (TEMP_DIR, CACHE_DIR, FONT_DIR):
        exists = os.path.isdir(d)
        writable = False
        if exists:
            try:
                probe = os.path.join(d, '.wprobe')
                with open(probe, 'w') as f:
                    f.write('ok')
                os.remove(probe)
                writable = True
            except Exception:
                writable = False
        dirs.append({'name': d, 'exists': exists, 'writable': writable})

    # 2) Meme 表情服务体检（不抛异常，坏则记录 error）
    meme = {'total': 0, 'with_image': 0, 'no_image': 0, 'preview_ok': False, 'error': None}
    try:
        memes = meme_service.list_memes('')
        meme['total'] = len(memes)
        meme['with_image'] = sum(1 for m in memes if m['max_images'] > 0)
        meme['no_image'] = sum(1 for m in memes if m['max_images'] == 0)
        try:
            meme['preview_ok'] = len(meme_service.preview('always')) > 0
        except Exception:
            meme['preview_ok'] = False
        if not meme['total']:
            # 一个表情都没有时，把原因一并带出去，省得后台只显示一片空白
            meme['error'] = meme_service.load_error() or '表情列表为空，原因未知'
    except Exception as e:
        meme['error'] = str(e)

    # 3) 缓存统计
    cache = {'count': 0, 'size_kb': 0.0, 'error': None}
    try:
        files = [f for f in os.listdir(CACHE_DIR) if os.path.isfile(os.path.join(CACHE_DIR, f))]
        cache['count'] = len(files)
        cache['size_kb'] = round(sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f in files) / 1024.0, 1)
    except Exception as e:
        cache['error'] = str(e)

    # 4) 字体
    fonts = {'count': 0, 'files': [], 'error': None}
    try:
        fonts['files'] = sorted(get_available_fonts().keys())
        fonts['count'] = len(fonts['files'])
    except Exception as e:
        fonts['error'] = str(e)

    # 5) QQ 昵称/头像接口连通性（轻量探测）
    qq_api = {'reachable': None, 'http': None, 'error': None}
    try:
        r = requests.get(QQ_NICK_API, timeout=4)
        qq_api['reachable'] = r.status_code < 500
        qq_api['http'] = r.status_code
    except Exception as e:
        qq_api['reachable'] = False
        qq_api['error'] = str(e)[:80]

    return jsonify({
        'ok': True,
        'datetime': time.strftime('%Y-%m-%d %H:%M:%S'),
        'server': {
            'host': request.host,
            'debug': app.debug,
            'python': platform.python_version(),
            'started_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(SERVER_START)),
            'uptime_sec': int(time.time() - SERVER_START),
        },
        'dirs': dirs,
        'meme': meme,
        'cache': cache,
        'fonts': fonts,
        'qq_api': qq_api,
        'usage': usage.snapshot(),
    })


@app.route('/status')
def status_page():
    return redirect('/')


# ==================== Meme 表情包路由 ====================
import meme_service
from meme_service import (
    ArgModelMismatch,
    ImageNumberMismatch,
    NoSuchMeme,
    OpenImageFailed,
    TextNumberMismatch,
    TextOrNameNotEnough,
    TextOverLength,
)


def _meme_error(e):
    msg = f"{e}"
    if isinstance(e, NoSuchMeme):
        msg = "表情不存在"
    elif isinstance(e, ImageNumberMismatch):
        msg = f"图片数量不符（需 {e.min_images}~{e.max_images} 张）"
    elif isinstance(e, TextNumberMismatch):
        msg = f"文本数量不符（需 {e.min_texts}~{e.max_texts} 条）"
    elif isinstance(e, TextOverLength):
        msg = "文本过长，请缩短后重试"
    elif isinstance(e, ArgModelMismatch):
        msg = "选项参数不合法"
    elif isinstance(e, OpenImageFailed):
        msg = "图片无法解析，请换成 PNG/JPG/GIF"
    elif isinstance(e, TextOrNameNotEnough):
        msg = "文本(昵称)不足，该表情需要人名或文本"
    return jsonify({'ok': False, 'error': msg}), 400


@app.route('/api/meme/list', methods=['GET'])
def meme_list():
    query = request.args.get('q', '')
    try:
        items = meme_service.list_memes(query)
        out = {'ok': True, 'count': len(items), 'items': items}
        if not items and not query:
            # 整个表情库都是空的，把原因一起给前端，别只显示「没有匹配的表情」
            out['hint'] = meme_service.load_error()
        return jsonify(out)
    except Exception as e:
        return _meme_error(e)


@app.route('/api/meme/preview/<key>')
def meme_preview(key):
    """预览表情。可选 ?args=<json> 传入样式选项（如 {"mode":"loop"}）以预览不同风格。"""
    args = {}
    raw = request.args.get('args', '')
    if raw:
        try:
            args = json.loads(raw)
            if not isinstance(args, dict):
                args = {}
        except Exception:
            args = {}
    try:
        data = meme_service.preview(key, args)
        mime = 'image/gif' if data[:3] == b'GIF' else 'image/png'
        return send_file(BytesIO(data), mimetype=mime, max_age=3600)
    except NoSuchMeme:
        return _meme_error(NoSuchMeme(key))
    except Exception as e:
        return _meme_error(e)


@app.route('/api/meme/generate', methods=['POST'])
def meme_generate():
    try:
        key = request.form['key']
    except KeyError:
        return _meme_error(NoSuchMeme(''))

    import traceback
    try:
        b64diag = request.form.get('images_b64', '')
        print(f"[diag] key={key!r} b64len={len(b64diag)} b64head={b64diag[:40]!r} files={list(request.files.keys())}", flush=True)
    except Exception:
        traceback.print_exc()
    try:
        m = meme_service.get_meme(key)
    except NoSuchMeme:
        return _meme_error(NoSuchMeme(key))

    # 图片：允许 multipart 文件字段 images + 可选 base64(data uri) 兜底
    images = []
    files = request.files.getlist('images')
    for f in files:
        raw = f.read()
        if raw:
            images.append(raw)
    b64 = request.form.get('images_b64', '')
    if b64:
        for tok in b64.split(','):
            tok = tok.strip()
            if not tok:
                continue
            marker = ';base64,'
            idx = tok.find(marker)
            if idx >= 0:
                tok = tok[idx + len(marker):]
            try:
                images.append(base64.b64decode(tok))
            except Exception as e:
                print(f"[parse] tok len={len(tok)} head={tok[:24]!r} bad={type(e).__name__}: {e}", flush=True)

    try:
        texts = json.loads(request.form.get('texts', '[]'))
    except Exception:
        texts = []
    if isinstance(texts, str):
        texts = [texts] if texts else []

    try:
        args = json.loads(request.form.get('args', '{}') or '{}')
    except Exception:
        args = {}
    if not isinstance(args, dict):
        args = {'_value': args}
    args['_key'] = key

    try:
        args = meme_service.coerce_args(args)
        data = meme_service.generate(key, images, texts, args)
    except meme_service.KNOWN_ERRORS as e:
        return _meme_error(e)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    mime = 'image/gif' if data[:3] == b'GIF' else 'image/png'
    return send_file(
        BytesIO(data), mimetype=mime, as_attachment=True,
        download_name=f'{key}.gif' if mime == 'image/gif' else f'{key}.png',
    )


# 注册 OpenAI 兼容 API 层（/v1）
with app.app_context():
    try:
        from openai_api import bp as openai_bp
        app.register_blueprint(openai_bp)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[openai_api] 注册失败: {e}", flush=True)

# 注册管理后台蓝本（/admin）+ session 密钥
# session 密钥来源：.env 的 SECRET_KEY。留空则每次启动随机生成 ——
# 此时重启后旧登录 cookie 即失效，必须重新登录（默认行为，更安全）。
app.secret_key = config.SECRET_KEY or os.urandom(32)
try:
    from admin import bp as admin_bp
    app.register_blueprint(admin_bp)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"[admin] 注册失败: {e}", flush=True)

# 统一登录守卫：除公开资源外，主页业务接口须已登录（session.admin_ok）。
#  /static 静态资源、/v1（openai_api 走 Bearer）、登录流转端点、
#  GET /api/background（登录页需展示背景）始终放行。
@app.before_request
def _login_guard():
    p = request.path
    if p.startswith('/static') or p.startswith('/v1'):
        return None
    # 背景图（.env: BG_URL_PREFIX，默认 /bg）：登录页也要显示，始终放行
    if p == config.BG_URL_PREFIX or p.startswith(config.BG_URL_PREFIX + '/'):
        return None
    if p in ('/', '/setup', '/admin/api/session', '/admin/api/login',
             '/admin/api/logout', '/api/background'):
        return None
    # 引导页接口：首次运行时还没有管理密码，必须未登录可达（否则死锁）
    if p.startswith('/api/setup/'):
        return None
    if session.get('admin_ok'):
        return None
    if p == '/favicon.ico':       # 图标：不跳转、不报错
        return ('', 204)
    # 页面类请求（非 /api/*）：未登录时统一回到入口页，
    # 由入口页决定是去引导页(/setup)还是锁定页(lock.html)，
    # 避免在浏览器地址栏里直接看到 {"error":"未登录"} 这样的 JSON。
    if not p.startswith('/api/'):
        return redirect('/')
    return jsonify({'error': '未登录'}), 401

# 接口调用统计（/api/* 与 /v1/*）：钩子 + 在 api_status 中注入 usage
try:
    import usage
    from flask import g

    @app.before_request
    def _usage_start():
        g._req_start = time.perf_counter()
        g._req_route = request.path
        g._req_method = request.method
        g._req_is_api = request.path.startswith('/api/') or request.path.startswith('/v1/')

    @app.after_request
    def _usage_count(resp):
        # 页面(HTML)与前端脚本/样式强制不缓存，确保改动后浏览器总能拿到最新版，避免旧页面/脚本导致的诡异问题
        if resp.mimetype in ('text/html', 'application/javascript', 'text/javascript', 'text/css', 'image/jpeg', 'image/png'):
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
        if str(getattr(g, '_req_route', '')).startswith('/api/ws/'):
            return resp          # WS 面板轮询属纯 UI 行为，不计入接口统计
        ms = (time.perf_counter() - getattr(g, '_req_start', time.perf_counter())) * 1000
        usage.record(
            getattr(g, '_req_method', '?'),
            getattr(g, '_req_route', '?'),
            resp.status_code,
            ms,
            getattr(g, '_req_is_api', False),
        )
        return resp
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"[usage] 注册失败: {e}", flush=True)


@app.route('/api/card/meta')
def card_meta():
    import re
    fonts = get_available_fonts()
    templates = [{'key': k, 'name': re.sub(r'[（(].*?[）)]', '', v[1]).strip(),
                  'desc': v[2], 'colors': DEFAULT_BG_COLORS.get(k, ['#bcc9f0', '#eef4ff'])} for k, v in TEMPLATES.items()]
    return jsonify({'fonts': fonts, 'templates': templates})


# ==================== WS 服务器（OneBot V11 / NapCat 反向连接） ====================
# 本服务作为 WebSocket 服务端，等待 NapCat 以「反向 WS」方式连入。
# 全部实现位于 ws_server.py（基于 websockets 库）。
try:
    import ws_server
except Exception as _e:
    ws_server = None
    import traceback as _tb
    _tb.print_exc()
    print(f"[ws] ws_server 加载失败: {_e}", flush=True)


def _ws_ok():
    return ws_server is not None


# ==================== 机器人指令框架（/help · /meme · /pair） ====================
# 指令解析/路由/取材/回发全部位于 bot_commands.py；
# 渲染层位于 bot_render.py（与 WebUI 同款视觉）。本段只做接线与 WebUI 接口。
try:
    import bot_render
except Exception as _e:
    bot_render = None
    print(f"[bot] bot_render 加载失败: {_e}", flush=True)

try:
    import bot_commands
except Exception as _e:
    bot_commands = None
    import traceback as _tb2
    _tb2.print_exc()
    print(f"[bot] bot_commands 加载失败: {_e}", flush=True)


def _bot_ok():
    return bot_commands is not None and bot_render is not None and ws_server is not None


# ==================== 插件系统（plugins/ 一个文件夹 = 一个插件） ====================
# 加载 / 热重载 / 热禁用 / 配置读写 / 独立 Web 探测全部位于 plugin_manager.py
try:
    import plugin_manager
except Exception as _e:
    plugin_manager = None
    import traceback as _tb3
    _tb3.print_exc()
    print(f"[插件] plugin_manager 加载失败: {_e}", flush=True)


def _plugin_ok():
    return plugin_manager is not None and ws_server is not None and config.PLUGIN_ENABLED


# 指令目录：与 bot_render 渲染出的菜单图保持一致，供「指令中心」展示
BOT_CATALOG = [
    {"cmd": "help", "usage": "/help", "name": "图片菜单",
     "desc": "根指令：列出 ILBB 机器人的图片菜单，所有指令的入口。"},
    {"cmd": "meme", "usage": "/meme", "name": "Meme 生图帮助",
     "desc": "返回一张帮助图：怎么给图片、有哪些预设参数、常见报错怎么解。"},
    {"cmd": "meme help ID", "usage": "/meme help 12", "name": "素材详情",
     "desc": "按素材列表 ID 返回一张详情图：meme 名字、支持的预设、使用示例与教程。"},
    {"cmd": "meme list", "usage": "/meme list [页码|关键词]", "name": "素材列表",
     "desc": "获取 meme 素材列表（带列表 ID），ID 可直接用于「素材详情」。"},
    {"cmd": "meme 生成", "usage": "/meme 挠头 你好", "name": "Meme 生成",
     "desc": "调用 meme 引擎生成表情；可用 @ 的人头像，或同条/引用消息里的图片。"},
    {"cmd": "pair", "usage": "/pair", "name": "配对卡帮助",
     "desc": "返回配对卡帮助图：参数说明、模板样式、使用示例。"},
    {"cmd": "pair 生成", "usage": "/pair @123456 标题=跟我配对", "name": "配对卡生成",
     "desc": "调用配对卡渲染器生成卡片，支持 template/title/bg/btn/font 参数。"},
    {"cmd": "quote", "usage": "/quote", "name": "名言图帮助",
     "desc": "返回名言图帮助图：横屏版式、JPG/GIF 输出规则、署名与字体设置。"},
    {"cmd": "quote 生成", "usage": "/quote @某人 这就是名言", "name": "名言图生成",
     "desc": "合成名言图：随机二次元背景 + 灰色蒙版（默认不透明度 35%），"
             "画面正中一块全模糊托盘（托盘内背景整块高斯模糊 + 暖白玻璃），"
             "托盘内左圆形头像、右文字或表情包，右下角署名「—— 用户名」。"
             "静态内容出 JPG，动图表情包出 GIF。"},
]


def _sniff_image(data: bytes) -> str:
    if not data:
        return "image/png"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


@app.route('/api/bot/status', methods=['GET'])
def bot_status():
    """指令框架运行状态 + 指令目录。"""
    if not _bot_ok():
        return jsonify({'ok': False, 'error': 'bot_commands 模块不可用',
                        'catalog': BOT_CATALOG}), 500
    try:
        st = bot_commands.stats()
    except Exception as e:
        return jsonify({'ok': False, 'error': '读取状态失败：%s' % e}), 500
    st['ws_running'] = bool(_ws_ok() and ws_server.is_running())
    st['webui'] = True
    return jsonify({'ok': True, 'stats': st, 'catalog': BOT_CATALOG})


@app.route('/api/bot/memes', methods=['GET'])
def bot_memes():
    """meme 素材索引（含列表 ID），供指令中心 / 预览下拉使用。"""
    if not _bot_ok():
        return jsonify({'ok': False, 'error': 'bot_commands 模块不可用'}), 500
    q = (request.args.get('q') or '').strip()
    try:
        rows = []
        for i, m in bot_render.indexed_memes(q):
            opts = m.get('options') or []
            rows.append({
                'id': i,
                'key': m.get('key'),
                'keywords': list(m.get('keywords') or [])[:6],
                'min_images': m.get('min_images', 0),
                'max_images': m.get('max_images', 0),
                'min_texts': m.get('min_texts', 0),
                'max_texts': m.get('max_texts', 0),
                'presets': [{'name': o.get('name'), 'desc': o.get('help', '')} for o in opts],
            })
    except Exception as e:
        return jsonify({'ok': False, 'error': '读取素材失败：%s' % e}), 500
    return jsonify({'ok': True, 'count': len(rows), 'memes': rows,
                    'page': int(config.BOT_MEME_LIST_PAGE)})


@app.route('/api/bot/preview', methods=['GET', 'POST'])
def bot_preview():
    """干跑一条指令（不发送、不联网取图），返回渲染结果供指令中心预览。"""
    if not _bot_ok():
        return jsonify({'ok': False, 'error': 'bot_commands 模块不可用'}), 500
    payload = request.get_json(silent=True) or {} if request.method == 'POST' else {}
    body = payload.get('cmd') or request.args.get('cmd') or ''
    body = str(body).strip()
    prefix = config.BOT_PREFIX
    if body.startswith(prefix):
        body = body[len(prefix):].strip()
    ctx = {
        'mtype': payload.get('mtype') or 'private',
        'uid': str(payload.get('uid') or '0'),
        'uname': str(payload.get('uname') or '预览用户'),
        'gid': str(payload.get('gid') or ''),
        'gname': '',
        'self_id': '',
        'ats': [str(x) for x in (payload.get('ats') or [])],
    }
    try:
        images, texts = bot_commands.preview(body, ctx)
    except Exception as e:
        import traceback as _tb3
        _tb3.print_exc()
        return jsonify({'ok': False, 'error': '渲染失败：%s' % e}), 500

    out = []
    total = 0
    for raw in (images or []):
        if not raw:
            continue
        total += len(raw)
        if len(raw) > 12 * 1024 * 1024:
            continue
        out.append({'mime': _sniff_image(raw),
                    'bytes': len(raw),
                    'data': base64.b64encode(raw).decode('ascii')})
    return jsonify({'ok': True, 'cmd': body, 'count': len(out),
                    'bytes': total, 'images': out, 'texts': list(texts or [])})


# ==================== 名言图合成（/quote） ====================
# 与机器人 /quote 指令共用 bot_render.render_quote，前端「合成 → 名言图」表单走这里：
# 横屏 16:9；随机二次元背景 + 灰色蒙版（默认不透明度 35%）+ 左独立圆角头像
# + 右半边白色磨砂玻璃面板 + 右下角署名「—— 用户名」（字体跟随全局 FONT_FAMILY）；
# 静态出 JPG，动图出 GIF。
@app.route('/api/quote/config', methods=['GET'])
def quote_config():
    """名言图表单默认值（供前端填默认值与下拉/滑块范围）。"""
    return jsonify({
        'ok': True,
        'enabled': bool(getattr(config, 'QUOTE_ENABLED', True)),
        'width': int(getattr(config, 'QUOTE_WIDTH', 1280)),
        'height': int(getattr(config, 'QUOTE_HEIGHT', 720)),
        'mask_alpha': float(getattr(config, 'QUOTE_MASK_ALPHA', 0.35)),
        'jpg_quality': int(getattr(config, 'QUOTE_JPG_QUALITY', 92)),
        'avatar': int(getattr(config, 'QUOTE_AVATAR', 236)),
        'tray_blur': float(getattr(config, 'QUOTE_TRAY_BLUR', 30.0)),
        'tray_glass': float(getattr(config, 'QUOTE_TRAY_GLASS', 0.58)),
        'text_max': int(getattr(config, 'QUOTE_TEXT_MAX', 56)),
        'text_min': int(getattr(config, 'QUOTE_TEXT_MIN', 22)),
        'max_body': int(getattr(config, 'QUOTE_MAX_BODY', 500)),
        'gif_max_frames': int(getattr(config, 'QUOTE_GIF_MAX_FRAMES', 60)),
        'gif_min_ms': int(getattr(config, 'QUOTE_GIF_MIN_MS', 40)),
        'name_default': str(getattr(config, 'QUOTE_NAME', '无名氏')),
        'name_max': int(getattr(config, 'QUOTE_NAME_MAX', 16)),
        # 全局字体（跟随设置页 FONT_FAMILY），署名与正文都用它
        'font_current': str(getattr(config, 'FONT_FAMILY', 'system')),
        'font_options': config.font_options(),
        'prefix': config.BOT_PREFIX,
    })


@app.route('/api/quote/generate', methods=['POST'])
def quote_generate():
    """合成一张名言图，返回 base64 图片（JPG 或 GIF）。

    请求：{text, name, qq, gid, avatar:dataURL, images:[dataURL], bg:dataURL,
           no_bg:bool}
    """
    if not _bot_ok():
        return jsonify({'ok': False, 'error': 'bot_commands 模块不可用'}), 500
    if not bool(getattr(config, 'QUOTE_ENABLED', True)):
        return jsonify({'ok': False, 'error': '名言合成已关闭（QUOTE_ENABLED=false）'}), 400

    payload = request.get_json(silent=True) or {}
    text = str(payload.get('text') or '').strip()
    name = str(payload.get('name') or '').strip()
    qq = str(payload.get('qq') or '').strip()
    gid = str(payload.get('gid') or '').strip()

    # ---- 头像：显式上传 > QQ 号取图 ----
    avatar = _decode_data_url(payload.get('avatar'))
    if avatar is None and qq:
        try:
            avatar = bot_commands._qq_avatar(qq)
        except Exception:
            avatar = None
    # ---- 署名：显式填写 > 按 QQ 号查昵称 > 配置默认 ----
    if not name and qq:
        try:
            name = bot_commands._person_info(qq, gid, False) or ''
        except Exception:
            name = ''
    name = bot_commands._clean_name(name) or str(getattr(config, 'QUOTE_NAME', '无名氏'))

    # ---- 表情包内容：只取第一张 ----
    bubble = []
    for raw in (payload.get('images') or []):
        b = _decode_data_url(raw)
        if b:
            bubble.append(b)
    bubble = bubble[:1]

    if not text and not bubble:
        text = '这就是名言。'

    # ---- 背景：显式上传 > 随机 API；no_bg=true 时走内置深色渐变 ----
    bg = _decode_data_url(payload.get('bg'))
    if bg is None and not payload.get('no_bg'):
        try:
            bg = bot_commands._quote_background()
        except Exception:
            bg = None

    # ---- 署名：字体跟随全局 FONT_FAMILY，不再单独传字体 ----
    try:
        data = bot_render.render_quote(text, name, avatar, bubble, bg)
    except Exception as e:
        import traceback as _tb5
        _tb5.print_exc()
        return jsonify({'ok': False, 'error': '名言图生成失败：%s' % e}), 500
    if not data:
        return jsonify({'ok': False, 'error': '名言图生成失败：渲染结果为空'}), 500

    data, note = bot_commands._shrink(data)
    if len(data) > 12 * 1024 * 1024:
        return jsonify({'ok': False, 'error': '名言图过大（>12MB），请改用更小的表情包'}), 500
    mime = _sniff_image(data)
    return jsonify({'ok': True, 'mime': mime, 'bytes': len(data),
                    'data': base64.b64encode(data).decode('ascii'),
                    'name': name, 'note': note or '',
                    'animated': mime == 'image/gif',
                    'has_bg': bool(bg), 'has_avatar': bool(avatar),
                    'bubble_image': bool(bubble)})


# ==================== Web 会话（模拟私聊调试） ====================
# 「Web Chat」标签页用它把指令真的跑一遍：像私聊一样发消息，机器人回什么就显示什么。
# 会话状态（最近附带的图片素材）按 sid 存在内存里，模拟「引用带图消息」的效果。
import threading as _threading

_CHAT_LOCK = _threading.Lock()
_CHAT_SESSIONS = {}
_CHAT_MAX_SESSIONS = 64          # 最多保留多少个会话
_CHAT_KEEP_IMAGES = 3            # 每个会话最多记住几张图片素材
_CHAT_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CHAT_STATS = {'total': 0, 'images': 0, 'texts': 0, 'ms': 0.0, 'last': ''}


def _chat_session(sid):
    with _CHAT_LOCK:
        s = _CHAT_SESSIONS.get(sid)
        if s is None:
            s = {'images': [], 'at': time.time()}
            _CHAT_SESSIONS[sid] = s
            if len(_CHAT_SESSIONS) > _CHAT_MAX_SESSIONS:
                old = sorted(_CHAT_SESSIONS, key=lambda k: _CHAT_SESSIONS[k]['at'])
                for k in old[:16]:
                    _CHAT_SESSIONS.pop(k, None)
        s['at'] = time.time()
        return s


def _decode_data_url(raw):
    """把前端传来的 dataURL / 纯 base64 还原成图片字节"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    if s.startswith('data:'):
        i = s.find(',')
        if i < 0:
            return None
        head, s = s[:i], s[i + 1:]
        if 'base64' not in head:
            return None
    try:
        data = base64.b64decode(s, validate=False)
    except Exception:
        return None
    if not data or len(data) > _CHAT_MAX_IMAGE_BYTES:
        return None
    return data


@app.route('/api/bot/chat', methods=['POST'])
def bot_chat():
    """Web 会话：模拟一条私聊消息发给机器人，返回它要回复的图文。

    请求：{sid, text, images:[dataURL...], uid, uname, ats:[qq...], reset:bool}
    响应：{ok, replies:[{type:'text'|'image', ...}], cost_ms, session:{images:n}}
    """
    if not _bot_ok():
        return jsonify({'ok': False, 'error': 'bot_commands 模块不可用'}), 500

    payload = request.get_json(silent=True) or {}
    sid = str(payload.get('sid') or 'default')[:64] or 'default'
    s = _chat_session(sid)

    if payload.get('reset'):
        with _CHAT_LOCK:
            s['images'] = []
        return jsonify({'ok': True, 'replies': [], 'reset': True,
                        'session': {'images': 0}})

    uid = str(payload.get('uid') or '10001')
    uname = str(payload.get('uname') or '调试用户')

    # ---- 本轮附带图片（会作为素材被后续指令沿用，模拟引用带图消息） ----
    got = []
    for raw in (payload.get('images') or []):
        b = _decode_data_url(raw)
        if b:
            got.append(b)
    if got:
        with _CHAT_LOCK:
            s['images'] = (got + list(s['images']))[:_CHAT_KEEP_IMAGES]

    body = str(payload.get('text') or '').strip()
    prefix = config.BOT_PREFIX
    ats = [str(x) for x in (payload.get('ats') or []) if str(x).strip()]

    # 文本里直接写 @123456 也算 @（和群聊习惯一致）
    def _grab_at(m):
        qq = m.group(1)
        if qq not in ats:
            ats.append(qq)
        return ' '
    body = re.sub(r'@(\d{5,12})', _grab_at, body).strip()

    if body.startswith(prefix):
        body = body[len(prefix):].strip()

    if not body:
        return jsonify({'ok': True, 'replies': [], 'skipped': '空消息',
                        'session': {'images': len(s['images'])}})

    ctx = {
        'mtype': 'private',
        'uid': uid,
        'uname': uname,
        'gid': '',
        'gname': '',
        'self_id': '',
        'ats': ats,
        'images': list(s['images']),
        '_media_done': True,
    }

    t0 = time.time()
    try:
        # Web 会话按「真实发送」跑：@ / QQ 号的头像会真的联网取，不套占位图
        images, texts = bot_commands.preview(body, ctx, dry=False)
    except Exception as e:
        import traceback as _tb4
        _tb4.print_exc()
        return jsonify({'ok': False, 'error': '指令执行失败：%s' % e}), 500
    cost_ms = int((time.time() - t0) * 1000)

    replies = []
    for raw in (images or []):
        if not raw or len(raw) > 12 * 1024 * 1024:
            continue
        replies.append({'type': 'image',
                        'mime': _sniff_image(raw),
                        'bytes': len(raw),
                        'data': base64.b64encode(raw).decode('ascii')})
    for t in (texts or []):
        if t:
            replies.append({'type': 'text', 'text': str(t)})

    with _CHAT_LOCK:
        _CHAT_STATS['total'] += 1
        _CHAT_STATS['images'] += sum(1 for r in replies if r['type'] == 'image')
        _CHAT_STATS['texts'] += sum(1 for r in replies if r['type'] == 'text')
        _CHAT_STATS['ms'] = cost_ms
        _CHAT_STATS['last'] = body[:60]

    try:
        bot_commands._log('Web 会话 · %s(%s) · %s → %d 图 %d 文 · %.2fs'
                          % (uname, uid, body[:40],
                             sum(1 for r in replies if r['type'] == 'image'),
                             sum(1 for r in replies if r['type'] == 'text'),
                             cost_ms / 1000.0))
    except Exception:
        pass

    return jsonify({'ok': True, 'cmd': body, 'cost_ms': cost_ms,
                    'replies': replies, 'count': len(replies),
                    'session': {'images': len(s['images']), 'sid': sid},
                    'stats': dict(_CHAT_STATS)})


@app.route('/api/bot/chat/stats', methods=['GET'])
def bot_chat_stats():
    """Web 会话的累计计数（供侧栏展示）"""
    with _CHAT_LOCK:
        st = dict(_CHAT_STATS)
        sessions = len(_CHAT_SESSIONS)
    st['sessions'] = sessions
    return jsonify({'ok': True, 'stats': st})


def _bot_setup():
    """随主服务一起启动指令框架（幂等）。"""
    if not _bot_ok():
        if bot_commands is None:
            print("[bot] 指令框架未加载，跳过", flush=True)
        return
    try:
        import sys as _sys
        ok = bot_commands.setup(_sys.modules[__name__])
        if not ok:
            print("[bot] 指令框架未启用（BOT_ENABLED=false）", flush=True)
    except Exception as e:
        import traceback as _tb4
        _tb4.print_exc()
        print(f"[bot] 指令框架启动失败: {e}", flush=True)


@app.route('/api/ws/status', methods=['GET'])
def ws_status():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    try:
        limit = int(request.args.get('limit', 120))
    except (TypeError, ValueError):
        limit = 120
    with_events = request.args.get('events', '1') not in ('0', 'false', 'no')
    # 默认不下发原始 JSON（日志只展示可读内容），勾选「显示原始 JSON」时才带 raw=1
    with_raw = request.args.get('raw', '0') in ('1', 'true', 'yes')
    return jsonify(ws_server.status(include_events=with_events,
                                    event_limit=max(1, min(limit, 300)),
                                    include_raw=with_raw))


@app.route('/api/ws/messages', methods=['GET'])
def ws_messages():
    """机器人最近发出的消息，供「接口调试」里的 message_id 参数下拉选择。"""
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    try:
        limit = int(request.args.get('limit', 60))
    except (TypeError, ValueError):
        limit = 60
    items = ws_server.recent_messages(limit)
    return jsonify({'ok': True, 'count': len(items), 'messages': items})


@app.route('/api/ws/actions', methods=['GET'])
def ws_actions():
    """返回 OneBot V11 接口参数元数据，供「接口调试」面板动态生成参数输入框。"""
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    return jsonify(ws_server.actions())


@app.route('/api/ws/config', methods=['GET', 'POST'])
def ws_config():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    if request.method == 'GET':
        return jsonify({'ok': True, 'config': ws_server.get_config()})
    data = request.get_json(silent=True) or {}
    old = ws_server.get_config()
    r = ws_server.set_config(data)
    if not r.get('ok'):
        return jsonify(r), 400
    cfg = r.get('config') or {}
    # 监听地址/端口/路径发生变化且服务器正在运行 → 自动重启使其立即生效
    if ws_server.is_running() and (old.get('host'), old.get('port'), old.get('path')) != \
            (cfg.get('host'), cfg.get('port'), cfg.get('path')):
        rr = ws_server.restart()
        if not rr.get('ok'):
            r['restart_error'] = rr.get('error')
        r['restarted'] = bool(rr.get('ok'))
    return jsonify(r)


@app.route('/api/ws/start', methods=['POST'])
def ws_start():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    r = ws_server.start()
    return jsonify(r), (200 if r.get('ok') else 400)


@app.route('/api/ws/stop', methods=['POST'])
def ws_stop():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    r = ws_server.stop()
    return jsonify(r), (200 if r.get('ok') else 400)


@app.route('/api/ws/restart', methods=['POST'])
def ws_restart():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    r = ws_server.restart()
    return jsonify(r), (200 if r.get('ok') else 400)


@app.route('/api/ws/send', methods=['POST'])
def ws_send():
    """向已连接的 NapCat 主动调用 OneBot V11 接口（接口测试用）。"""
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()
    if not action:
        return jsonify({'ok': False, 'error': '缺少 action'}), 400
    params = data.get('params') or {}
    if isinstance(params, str):
        try:
            params = json.loads(params) if params.strip() else {}
        except Exception as e:
            return jsonify({'ok': False, 'error': f'params JSON 解析失败: {e}'}), 400
    if not isinstance(params, dict):
        return jsonify({'ok': False, 'error': 'params 必须是 JSON 对象'}), 400
    try:
        timeout = float(data.get('timeout') or 6.0)
    except (TypeError, ValueError):
        timeout = 6.0
    r = ws_server.call_api(action, params, timeout=max(0.5, min(timeout, 60.0)))
    return jsonify(r), (200 if r.get('ok') else 400)

# ==================== 头像代理（QQ 好友 / 群） ====================
# 背景：浏览器直连 p1.qlogo.cn 等节点会被重置（ConnectionResetError 10054），
# 因此统一走后端代理：多镜像轮询 → 磁盘缓存 → 占位图兜底。
AVATAR_USER_MIRRORS = [
    'https://q1.qlogo.cn/g?b=qq&nk={id}&s={s}',
    'https://q4.qlogo.cn/g?b=qq&nk={id}&s={s}',
    'https://q2.qlogo.cn/g?b=qq&nk={id}&s={s}',
    'https://q3.qlogo.cn/g?b=qq&nk={id}&s={s}',
    'https://thirdqq.qlogo.cn/g?b=qq&nk={id}&s={s}',
]
AVATAR_GROUP_MIRRORS = [
    'https://p.qlogo.cn/gh/{id}/{id}/{s}',
]
AVATAR_FETCH_TIMEOUT = 6.0
AVATAR_CACHE_SECONDS = 7 * 24 * 3600  # 磁盘缓存有效期（7 天）


def _avatar_placeholder(kind, size):
    """所有镜像均失败时绘制无字体依赖的占位图（不落盘，避免固化临时故障）。"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=max(3, size // 5),
                        fill=(236, 233, 224, 255))
    fg = (170, 163, 148, 255)
    s = float(size)
    if kind == 'group':
        d.ellipse([s * .24, s * .26, s * .50, s * .52], fill=fg)
        d.ellipse([s * .12, s * .56, s * .62, s * .92], fill=fg)
        d.ellipse([s * .58, s * .32, s * .82, s * .56], fill=fg)
        d.ellipse([s * .48, s * .60, s * .92, s * .92], fill=fg)
    else:
        d.ellipse([s * .30, s * .18, s * .70, s * .58], fill=fg)
        d.ellipse([s * .18, s * .62, s * .82, s * 1.28], fill=fg)
    return img


@app.route('/api/ws/avatar', methods=['GET'])
def ws_avatar():
    """头像代理：/api/ws/avatar?type=user|group&id=<QQ或群号>&s=100"""
    kind = (request.args.get('type') or 'user').strip().lower()
    if kind not in ('user', 'group'):
        kind = 'user'
    ident = (request.args.get('id') or '').strip()
    if not ident.isdigit():
        return jsonify({'ok': False, 'error': 'id 必须是纯数字'}), 400
    try:
        size = int(request.args.get('s') or 100)
    except (TypeError, ValueError):
        size = 100
    size = max(40, min(size, 640))

    cache_path = os.path.join(AVATAR_DIR, '%s_%s_%d.png' % (kind, ident, size))
    if os.path.isfile(cache_path):
        try:
            if (time.time() - os.path.getmtime(cache_path)) < AVATAR_CACHE_SECONDS:
                with open(cache_path, 'rb') as f:
                    cached = f.read()
                if cached:
                    resp = send_file(BytesIO(cached), mimetype='image/png', max_age=86400)
                    resp.headers['X-Avatar-Source'] = 'cache'
                    return resp
        except Exception:
            pass

    tpls = AVATAR_USER_MIRRORS if kind == 'user' else AVATAR_GROUP_MIRRORS
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://qzone.qq.com/',
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    }
    last_err = ''
    for tpl in tpls:
        url = tpl.format(id=ident, s=size)
        try:
            r = requests.get(url, timeout=AVATAR_FETCH_TIMEOUT, headers=headers)
            if r.status_code == 200 and r.content and len(r.content) > 64:
                mime = (r.headers.get('Content-Type') or '').split(';')[0].strip()
                if not mime.startswith('image/'):
                    mime = 'image/png'
                try:
                    with open(cache_path, 'wb') as f:
                        f.write(r.content)
                except Exception:
                    pass
                resp = send_file(BytesIO(r.content), mimetype=mime, max_age=86400)
                resp.headers['X-Avatar-Source'] = url
                return resp
            last_err = 'HTTP %s' % r.status_code
        except Exception as e:
            last_err = '%s: %s' % (type(e).__name__, e)

    try:
        buf = BytesIO()
        _avatar_placeholder(kind, size).save(buf, format='PNG')
        resp = send_file(BytesIO(buf.getvalue()), mimetype='image/png', max_age=60)
        resp.headers['X-Avatar-Source'] = 'placeholder'
        resp.headers['X-Avatar-Error'] = last_err[:200].encode('utf-8').decode('latin-1', 'ignore')
        return resp
    except Exception as e:
        return jsonify({'ok': False, 'error': '头像获取失败：%s' % (last_err or e)}), 502


@app.route('/api/ws/events/clear', methods=['POST'])
def ws_events_clear():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    ws_server.clear_events()
    return jsonify({'ok': True})


@app.route('/api/ws/disconnect', methods=['POST'])
def ws_disconnect():
    if not _ws_ok():
        return jsonify({'ok': False, 'error': 'ws_server 模块不可用'}), 500
    data = request.get_json(silent=True) or {}
    cid = (data.get('id') or '').strip()
    if not cid:
        return jsonify({'ok': False, 'error': '缺少客户端 id'}), 400
    r = ws_server.disconnect(cid)
    return jsonify(r), (200 if r.get('ok') else 400)


def _plugin_setup():
    """随主服务一起启动插件系统（幂等）。"""
    if plugin_manager is None:
        return
    if not config.PLUGIN_ENABLED:
        print("[插件] 插件系统未启用（PLUGIN_ENABLED=false），跳过", flush=True)
        return
    try:
        plugin_manager.start()
    except Exception as e:
        import traceback as _tb5
        _tb5.print_exc()
        print(f"[插件] 插件系统启动失败: {e}", flush=True)


def _plugin_err(resp):
    return jsonify(resp), (200 if resp.get("ok") else 400)


@app.route('/api/plugins/list', methods=['GET'])
def plugins_list():
    """插件清单 + 运行状态（一个文件夹 = 一个插件）。"""
    if plugin_manager is None:
        return jsonify({'ok': False, 'error': 'plugin_manager 模块不可用'}), 500
    return jsonify(plugin_manager.list_plugins())


@app.route('/api/plugins/toggle', methods=['POST'])
def plugins_toggle():
    """热启用 / 热禁用单个插件（不必重启主服务）。"""
    if plugin_manager is None:
        return jsonify({'ok': False, 'error': 'plugin_manager 模块不可用'}), 500
    data = request.get_json(silent=True) or {}
    pid = str(data.get('id') or '').strip()
    if not pid:
        return jsonify({'ok': False, 'error': '缺少插件 id'}), 400
    return _plugin_err(plugin_manager.set_enabled(pid, bool(data.get('enabled'))))


@app.route('/api/plugins/reload', methods=['POST'])
def plugins_reload():
    """热重载：带 id 重载单个插件，不带则整目录重新扫描。"""
    if plugin_manager is None:
        return jsonify({'ok': False, 'error': 'plugin_manager 模块不可用'}), 500
    data = request.get_json(silent=True) or {}
    pid = str(data.get('id') or '').strip()
    return _plugin_err(plugin_manager.reload(pid or None))


@app.route('/api/plugins/config', methods=['GET'])
def plugins_config_get():
    """读插件配置：fields 为插件声明的表单结构（friend/group 自动用下拉栏）。"""
    if plugin_manager is None:
        return jsonify({'ok': False, 'error': 'plugin_manager 模块不可用'}), 500
    pid = str(request.args.get('id') or '').strip()
    if not pid:
        return jsonify({'ok': False, 'error': '缺少插件 id'}), 400
    return _plugin_err(plugin_manager.get_config(pid))


@app.route('/api/plugins/config', methods=['POST'])
def plugins_config_set():
    """改插件配置：存到 PLUGIN_CONFIG_PATH，并即时通知插件（on_config）。"""
    if plugin_manager is None:
        return jsonify({'ok': False, 'error': 'plugin_manager 模块不可用'}), 500
    data = request.get_json(silent=True) or {}
    pid = str(data.get('id') or '').strip()
    if not pid:
        return jsonify({'ok': False, 'error': '缺少插件 id'}), 400
    return _plugin_err(plugin_manager.set_config(pid, data.get('values') or {}))


@app.route('/api/plugins/web', methods=['GET'])
def plugins_web():
    """插件独立页面：返回内嵌地址（自动匹配主机名 + 插件端口）与在线状态。"""
    if plugin_manager is None:
        return jsonify({'ok': False, 'error': 'plugin_manager 模块不可用'}), 500
    pid = str(request.args.get('id') or '').strip()
    if not pid:
        return jsonify({'ok': False, 'error': '缺少插件 id'}), 400
    host = str(request.args.get('host') or '').strip() or request.host.split(':')[0]
    return _plugin_err(plugin_manager.web_info(pid, host))


# ==================== 首次运行引导（/setup） ====================
# 三件事：
#   1) 启动后自动体检 meme 素材（本地文件 vs 资源清单），结果落 setup_state.json；
#   2) 首次运行（本次启动前还没有管理密码）→ 强制进引导页，引导完成 ILBB 基础配置；
#   3) 素材不完整 → 引导页里一键补全下载（meme_assets 后台任务 + 进度轮询）。
# 引导状态单独存文件，不写进 .env，避免污染配置。
import meme_assets

SETUP_STATE_PATH = os.path.join(config.ROOT, 'setup_state.json')
SETUP_STATE_VERSION = 1

# 引导页可以改的配置键（其余项仍只能在「设置」页登录后修改）
SETUP_CONFIG_GROUPS = [
    ("机器人", ["BOT_ENABLED", "BOT_NAME", "BOT_PREFIX",
                "BOT_GROUP_NEED_AT", "BOT_ALLOW_PRIVATE", "BOT_COOLDOWN_SEC"]),
    ("连接 NapCat（OneBot V11）", ["WS_HOST", "WS_PORT", "WS_PATH",
                                   "WS_ACCESS_TOKEN", "WS_AUTO_START"]),
    ("访问地址 / Meme 素材", ["WEB_HOST", "WEB_PORT",
                              "MEME_ASSET_DIR", "MEME_RESOURCE_BASE"]),
]

# 解释器要求（写死，不做自动适配）：
#   下界 3.10 —— 依赖里已有若干库要求 3.10+；
#   上界 3.13 —— vendor 里的 meme-generator 锁了 Pillow ^10.0.0，而 Pillow 10.x
#                没有 3.14 的预编译包（skia-python 反而有），3.14 上 pip 直接报找不到版本；
#   另需 64 位 —— skia-python 不发 32 位 wheel。
PY_SUPPORT_MIN = (3, 10)
PY_SUPPORT_MAX = (3, 13)
PY_SUPPORT_TEXT = "3.10 – 3.13（64 位）"
PY_SUPPORT_TIP = "换成 64 位 Python 3.13（3.10 – 3.13 都行，推荐 3.13）"


def _setup_python_dep():
    """解释器自检项：版本区间 + 位数，结论拼进依赖清单一起显示。"""
    ver = ".".join(str(n) for n in sys.version_info[:3])
    cur = sys.version_info[:2]
    item = {"module": ver, "label": "Python", "ok": True, "detail": "", "tip": "", "badge": ""}
    if sys.maxsize <= 2 ** 32:
        item.update(ok=False, badge="不兼容",
                    detail="当前是 32 位的 Python，skia-python 没有 32 位 wheel，装不上。",
                    tip=PY_SUPPORT_TIP)
    elif cur > PY_SUPPORT_MAX:
        item.update(ok=False, badge="不兼容",
                    detail="Python %d.%d 暂不支持：meme 引擎锁了 Pillow 10.x，"
                           "而 Pillow 10.x 没有 %d.%d 的预编译包，pip 会直接报找不到版本。"
                           % (cur[0], cur[1], cur[0], cur[1]),
                    tip=PY_SUPPORT_TIP)
    elif cur < PY_SUPPORT_MIN:
        item.update(ok=False, badge="不兼容",
                    detail="Python %d.%d 太旧，本项目依赖的库需要 3.10 及以上。" % (cur[0], cur[1]),
                    tip=PY_SUPPORT_TIP)
    return item


# 依赖自检清单：(import 名, 显示名, 装不上时的补救提示)
# 补救提示统一指向 requirements.txt：meme 引擎随项目自带源码、不走 pip 安装，
# 它声明的十几个依赖没法自动解析，照单个包名 pip install 非常容易漏。
_DEP_FIX = "uv pip install -r requirements.txt"
SETUP_DEP_MODULES = [
    ("flask", "Flask", _DEP_FIX),
    ("requests", "requests", _DEP_FIX),
    ("PIL", "Pillow", _DEP_FIX),
    ("websockets", "websockets", _DEP_FIX),
    ("skia", "skia-python", _DEP_FIX),
    ("numpy", "numpy", _DEP_FIX),
    ("meme_generator", "meme 引擎", "确认 vendor/meme-generator-main 已就位，然后跑 uv pip install -r requirements.txt"),
]


def _setup_state_read():
    """读引导状态（缺文件 / 坏文件都退回默认值）。"""
    st = {
        "version": SETUP_STATE_VERSION,
        "completed": False,       # 引导是否走完（走完就不再强制跳转）
        "assets_ok": False,       # 最近一次体检素材是否完整
        "assets_ack": False,      # 用户已确认「素材先不管」，不再提醒
        "assets": {},             # 最近一次体检摘要
        "checked_at": 0,
        "finished_at": 0,
    }
    try:
        with open(SETUP_STATE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            st.update(d)
    except Exception:
        pass
    # 管理密码是否待确认以 api_keys.json 为准，不信磁盘上的旧值
    st["admin_pwd_pending"] = api_key_store.admin_password_pending()
    return st


def _setup_state_write(patch):
    """增量写引导状态，返回写后的完整状态。"""
    st = _setup_state_read()
    st.pop("admin_pwd_pending", None)
    st.update(patch or {})
    try:
        tmp = SETUP_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETUP_STATE_PATH)
    except Exception as e:
        print(f"[setup] 写引导状态失败: {e}", flush=True)
    st["admin_pwd_pending"] = api_key_store.admin_password_pending()
    return st


def _setup_needed():
    """返回 (是否需要引导, 原因)。原因取值 password / setup / assets / ''。

    管理密码还没被用户确认过就先回引导页：引导页第 4 步是唯一能把密码设成
    「自己的」入口，用户错过终端里那串临时密码时只能靠它进来。
    """
    st = _setup_state_read()
    if api_key_store.admin_password_pending():
        return True, ("password" if st.get("completed") else "setup")
    if not st.get("completed"):
        return True, "setup"
    if not st.get("assets_ok") and not st.get("assets_ack"):
        return True, "assets"
    return False, ""


def _setup_slim(info):
    """去掉 scan() 里的内部字段（_reason 是个大 dict），便于 JSON / 落盘。"""
    return {k: v for k, v in (info or {}).items() if not k.startswith("_")}


def _setup_scan(refresh=False, deep=False):
    """体检素材并落盘（deep=True 逐个校验 md5，refresh=True 强制联网刷新清单）。"""
    try:
        info = meme_assets.scan(deep=deep, refresh=refresh)
    except Exception as e:
        info = {"dir": "", "exists": False, "engine_version": "", "engine_dir": "",
                "local_files": 0, "bytes": 0, "manifest_source": "",
                "manifest_error": f"体检异常：{e}", "total": 0, "present": 0,
                "missing": 0, "broken": 0, "sample": [], "complete": False,
                "checked_at": int(time.time())}
    _setup_state_write({"assets": _setup_slim(info),
                        "assets_ok": bool(info.get("complete")),
                        "checked_at": int(time.time()),
                        "assets_deep": bool(deep)})
    return info


def _setup_env_check():
    """依赖 / 引擎 / 目录自检，引导页第一步展示。"""
    deps = [_setup_python_dep()]          # 解释器排第一：版本不对，后面的包根本装不上
    for mod, label, tip in SETUP_DEP_MODULES:
        try:
            __import__(mod)
            deps.append({"module": mod, "label": label, "ok": True, "detail": "", "tip": tip})
        except Exception as e:
            deps.append({"module": mod, "label": label, "ok": False,
                         "detail": str(e), "tip": tip})
    dirs = []
    for label, p in (("临时文件", config.TEMP_DIR), ("图片缓存", config.CACHE_DIR),
                     ("字体", config.FONT_DIR), ("背景图", config.BG_DIR)):
        dirs.append({"label": label, "path": p, "exists": bool(p) and os.path.isdir(p)})
    meme_count = -1
    meme_hint = ""
    try:
        meme_count = len(meme_service.list_memes(""))
        if not meme_count:
            meme_hint = meme_service.load_error()
    except Exception:
        meme_count = -1
    return {
        "ok": all(d["ok"] for d in deps),
        "deps": deps,
        "dirs": dirs,
        "python": platform.python_version(),
        "python_ok": bool(deps[0].get("ok")),
        "python_require": PY_SUPPORT_TEXT,
        "engine_version": meme_assets.engine_version(),
        "asset_dir": meme_assets.asset_dir(),
        "meme_count": meme_count,
        "meme_hint": meme_hint,
        "admin_password_set": api_key_store.has_admin_password(),
        "admin_pwd_pending": api_key_store.admin_password_pending(),
        "admin_pwd_source": api_key_store.admin_password_source(),
        "env_file": config.ENV_FILE,
        "env_file_exists": os.path.isfile(config.ENV_FILE),
    }


def _setup_config_schema():
    """引导页用的配置表单：从完整设置项里挑出白名单键（保留控件元数据与当前值）。"""
    all_items = {}
    for g in config.env_schema():
        for it in g["items"]:
            all_items[it["key"]] = it
    groups = []
    for name, keys in SETUP_CONFIG_GROUPS:
        items = [all_items[k] for k in keys if k in all_items]
        if items:
            groups.append({"name": name, "items": items})
    return groups


_SETUP_CONFIG_ALLOWED = {k for _n, keys in SETUP_CONFIG_GROUPS for k in keys}


def _setup_bootstrap():
    """启动后台自检素材（不阻塞主服务）。"""
    def worker():
        time.sleep(2)                      # 避开启动日志，等配置与引擎就绪
        try:
            info = _setup_scan(refresh=False, deep=False)
            print(f"[setup] 素材自检：{info.get('dir') or '(未找到目录)'} "
                  f"本地 {info.get('local_files', 0)} 个 / 清单 {info.get('total', 0)} 个，"
                  f"{'完整' if info.get('complete') else '不完整'}", flush=True)
        except Exception as e:
            print(f"[setup] 启动素材自检失败: {e}", flush=True)

    _threading.Thread(target=worker, name="setup-asset-scan", daemon=True).start()


@app.route('/setup')
def setup_page():
    """引导页：必须在未登录时可访问（首次运行还没有密码）。"""
    return render_template('setup.html')


@app.route('/api/setup/state')
def setup_state_api():
    """引导页首屏数据（不联网、不扫盘，读缓存状态即可）。"""
    st = _setup_state_read()
    needed, why = _setup_needed()
    meme_hint = ""
    try:
        if not meme_service.get_memes():
            meme_hint = meme_service.load_error()
    except Exception:
        pass
    return jsonify({
        "ok": True,
        "needed": needed,
        "reason": why,
        "admin_pwd_pending": api_key_store.admin_password_pending(),
        "admin_pwd_source": api_key_store.admin_password_source(),
        "completed": bool(st.get("completed")),
        "assets_ok": bool(st.get("assets_ok")),
        "assets_ack": bool(st.get("assets_ack")),
        "assets": st.get("assets") or {},
        "checked_at": st.get("checked_at") or 0,
        "logged_in": bool(session.get("admin_ok")),
        "job": meme_assets.job_snapshot(),
        "config_groups": _setup_config_schema(),
        "meme_hint": meme_hint,
        "env_file": config.ENV_FILE,
        "env_file_exists": os.path.isfile(config.ENV_FILE),
    })


@app.route('/api/setup/env-check')
def setup_env_check_api():
    """依赖 / 引擎 / 目录自检。"""
    return jsonify({"ok": True, "check": _setup_env_check()})


@app.route('/api/setup/check')
def setup_check_api():
    """体检素材。默认走本地清单缓存 + 只查存在性（快）；?refresh=1 联网刷新清单，?deep=1 校验 md5。"""
    deep = str(request.args.get('deep', '')).lower() in ('1', 'true', 'yes')
    refresh = str(request.args.get('refresh', '')).lower() in ('1', 'true', 'yes')
    info = _setup_scan(refresh=refresh, deep=deep)
    payload = _setup_slim(info)
    payload["ok"] = True
    return jsonify(payload)


@app.route('/api/setup/assets/download', methods=['POST'])
def setup_assets_download_api():
    """补全下载缺失素材（后台任务，用 /api/setup/assets/progress 查进度）。"""
    d = request.get_json(silent=True) or {}
    workers = d.get("workers")
    try:
        workers = max(1, min(32, int(workers))) if workers else meme_assets.DEFAULT_WORKERS
    except (TypeError, ValueError):
        workers = meme_assets.DEFAULT_WORKERS
    res = meme_assets.start_job(workers=workers,
                                refresh=bool(d.get("refresh")),
                                deep=bool(d.get("deep")))
    res["job"] = meme_assets.job_snapshot()
    return jsonify(res), (200 if res.get("ok") else 400)


@app.route('/api/setup/assets/progress')
def setup_assets_progress_api():
    """下载进度；任务刚结束时顺带刷新一次体检，让页面立刻看到结果。"""
    snap = meme_assets.job_snapshot()
    st = _setup_state_read()
    if (snap.get("state") != "running" and snap.get("finished_at")
            and int(st.get("checked_at") or 0) < int(snap.get("finished_at") or 0)):
        try:
            _setup_scan(refresh=False, deep=False)
            st = _setup_state_read()
        except Exception:
            pass
    return jsonify({"ok": True, "job": snap, "assets": st.get("assets") or {}})


@app.route('/api/setup/assets/cancel', methods=['POST'])
def setup_assets_cancel_api():
    """取消正在进行的补全下载。"""
    return jsonify({"ok": meme_assets.cancel_job(), "job": meme_assets.job_snapshot()})


@app.route('/api/setup/config', methods=['GET'])
def setup_config_get_api():
    """引导页配置表单（仅白名单键）。"""
    return jsonify({"ok": True, "groups": _setup_config_schema(),
                    "state": _setup_state_read(),
                    "admin_pwd_pending": api_key_store.admin_password_pending(),
                    "env_file": config.ENV_FILE,
                    "env_file_exists": os.path.isfile(config.ENV_FILE)})


@app.route('/api/setup/config', methods=['POST'])
def setup_config_save_api():
    """保存引导页配置：复用设置页的校验 + 写回 .env + 热重载链路。"""
    d = request.get_json(silent=True) or {}
    updates = d.get("updates")
    if not isinstance(updates, dict):
        updates = {k: v for k, v in d.items() if not str(k).startswith('_')}
    bad = sorted(k for k in updates if k not in _SETUP_CONFIG_ALLOWED)
    if bad:
        return jsonify({"ok": False, "error": "引导页不允许修改：" + "、".join(bad)}), 400
    res = config.apply_updates(updates)
    payload = {"ok": bool(res.get("ok")), "groups": _setup_config_schema()}
    payload.update(res)
    return jsonify(payload), (200 if payload["ok"] else 400)


@app.route('/api/setup/complete', methods=['POST'])
def setup_complete_api():
    """完成引导。可顺带设置管理密码（密码还没被确认过时才允许，避免任何人随时改密码）。"""
    d = request.get_json(silent=True) or {}
    payload = {"ok": True}
    newpwd = str(d.get("admin_password") or "").strip()
    if newpwd:
        if not api_key_store.admin_password_pending():
            return jsonify({"ok": False, "error": "管理密码已设置过，请到「设置」里修改"}), 403
        if len(newpwd) < 4:
            return jsonify({"ok": False, "error": "管理密码至少 4 位"}), 400
        api_key_store.set_admin_password(newpwd)
        session['admin_ok'] = True
        session.permanent = True
        payload["admin_password_set"] = True
    try:
        payload["assets"] = _setup_slim(_setup_scan(refresh=False, deep=False))
    except Exception:
        pass
    # 只标记「走完了」，不要顺手把 assets_ack 重置为 False：
    # 用户刚点过「素材先不管」，一完成引导又被踢回素材步骤会很莫名。
    payload["state"] = _setup_state_write({"completed": True,
                                           "finished_at": int(time.time())})
    return jsonify(payload)


@app.route('/api/setup/skip', methods=['POST'])
def setup_skip_api():
    """跳过：what=assets 只确认素材（下次启动若仍缺失会再提醒）；其它值直接结束引导。"""
    d = request.get_json(silent=True) or {}
    what = str(d.get("what") or "assets").strip()
    if what == "assets":
        st = _setup_state_write({"assets_ack": True})
    else:
        st = _setup_state_write({"completed": True, "assets_ack": True,
                                 "finished_at": int(time.time())})
    return jsonify({"ok": True, "state": st})


_setup_bootstrap()


def _ws_autostart():
    """按配置中的 auto_start 决定是否随主服务一起启动。"""
    if not _ws_ok():
        return
    try:
        if not ws_server.get_config().get('auto_start'):
            return
        r = ws_server.start()
        if not r.get('ok'):
            print(f"[ws] 自动启动失败: {r.get('error')}", flush=True)
    except Exception as e:
        print(f"[ws] 自动启动异常: {e}", flush=True)


def _env_payload():
    """设置页需要的完整数据：配置项元数据 + 当前值 + 是否被系统环境变量接管。"""
    return {
        "ok": True,
        "env_file": config.ENV_FILE,
        "env_file_exists": os.path.isfile(config.ENV_FILE),
        "ws_locked": config.WS_ENV_LOCKED,
        "groups": config.env_schema(),
    }


@app.route('/api/env/config', methods=['GET'])
def env_config():
    """当前生效配置：全部来自 .env / 系统环境变量 / 内置默认值（含编辑元数据）。"""
    return jsonify(_env_payload())


@app.route('/api/env/config', methods=['POST'])
def env_config_save():
    """保存设置：校验 → 写回 .env → 热重载。

    返回 updated / hot（已生效）/ restart（需重启）/ locked（被系统环境变量接管）。
    """
    d = request.get_json(silent=True) or {}
    updates = d.get('updates')
    if not isinstance(updates, dict):
        updates = {k: v for k, v in d.items() if not str(k).startswith('_')}
    res = config.apply_updates(updates)
    payload = _env_payload()
    payload.update(res)
    payload['ok'] = bool(res.get('ok'))
    return jsonify(payload), (200 if payload['ok'] else 400)


_ws_autostart()
_bot_setup()
_plugin_setup()


if __name__ == '__main__':
    # 全部监听参数来自 .env：WEB_HOST / WEB_PORT / WEB_DEBUG / WEB_THREADED
    # use_reloader=False：避免重载器父子双进程抢占 WS 端口；
    # threaded=True：慢请求（背景图等）不阻塞登录与其他接口
    print('=' * 56, flush=True)
    for _line in config.startup_log_lines():
        print(_line, flush=True)
    print('  本机访问 http://127.0.0.1:%s' % config.WEB_PORT, flush=True)
    print('=' * 56, flush=True)
    app.run(debug=config.WEB_DEBUG, host=config.WEB_HOST, port=config.WEB_PORT,
            threaded=config.WEB_THREADED, use_reloader=False)
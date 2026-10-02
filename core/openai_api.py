"""OpenAI 兼容 API 层（/v1）。

把项目的全部生成能力包装成 OpenAI 风格接口：
- /v1/images/generations 、 /v1/images/edits  ->  Meme 表情生成
- /v1/cards                                   ->  配对卡生成
- /v1/models                                  ->  模板/模型枚举
- /v1/files/<name>                            ->  url 模式的产物下载

复用 meme_service（表情）与 app.py 的配对卡绘制与 QQ 信息工具，
本模块只负责格式转换与请求解析，不接触数据库。
"""
import base64
import hashlib
import json
import os
import time

from flask import Blueprint, jsonify, request, send_file, g

import api_key_store
import config
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

bp = Blueprint("openai_api", __name__, url_prefix="/v1")

# 产图目录由 .env 决定（OPENAI_V1_DIR，默认 cache/v1）
V1_DIR = config.OPENAI_V1_DIR
os.makedirs(V1_DIR, exist_ok=True)


# ---------- API Key 鉴权 ----------
# 公开端点（无需 Key）：/v1/models
# 受保护端点：/v1/images/*, /v1/cards, /v1/files/*
_OPEN_PATHS = {"/v1/models"}


@bp.before_request
def _check_key():
    if request.path in _OPEN_PATHS:
        return None
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
    if not token:
        return _err("缺少 API Key，请在 Authorization 头中提供 Bearer <key>", param="authorization", code="missing_api_key")
    if not api_key_store.is_valid_key(token):
        return _err("API Key 无效或已被禁用", "invalid_request_error", param="authorization", code="invalid_api_key")
    g.api_key = token
    return None


# ---------- app 侧工具（惰性导入，避免循环导入） ----------
def _app(*names):
    import app as A
    return [getattr(A, n) for n in names]  # names 顺序一致


def _meme_index():
    idx = {}
    for m in meme_service.list_memes(""):
        idx.setdefault(m["key"], m)
        for kw in m["keywords"]:
            idx.setdefault(kw, m)
    return idx


# ---------- OpenAI 风格错误 ----------
def _err(message, http_type="invalid_request_error", param=None, code=None):
    body = {"error": {"message": message, "type": http_type, "param": param, "code": code}}
    status = 400 if http_type in ("invalid_request_error", "unsupported_error", "server_error") else 422
    if http_type == "not_found_error":
        status = 404
    elif http_type == "server_error":
        status = 500
    return jsonify(body), status


def _meme_error_to_openai(e):
    if isinstance(e, NoSuchMeme):
        return _err("表情不存在", "not_found_error", param="model", code="model_not_found")
    if isinstance(e, ImageNumberMismatch):
        return _err(f"图片数量不符（需 {e.min_images}~{e.max_images} 张）", param="images")
    if isinstance(e, TextNumberMismatch):
        return _err(f"文本数量不符（需 {e.min_texts}~{e.max_texts} 条）", param="prompt")
    if isinstance(e, TextOverLength):
        return _err("文本过长，请缩短后重试", param="prompt")
    if isinstance(e, ArgModelMismatch):
        return _err("选项参数不合法", param="prompt")
    if isinstance(e, OpenImageFailed):
        return _err("图片无法解析，请换成 PNG/JPG/GIF", param="images")
    if isinstance(e, TextOrNameNotEnough):
        return _err("文本(昵称)不足，该表情需要人名或文本", param="prompt")
    return _err(str(e), "server_error")


# ---------- 产物存储（url 模式） ----------
def _save_bytes(data: bytes) -> str:
    is_gif = data[:3] == b"GIF"
    name = hashlib.md5(data).hexdigest() + (".gif" if is_gif else ".png")
    path = os.path.join(V1_DIR, name)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return name


def _response(data: bytes, fmt: str, url_prefix: str):
    if fmt == "url":
        name = _save_bytes(data)
        return jsonify({"created": int(time.time()), "data": [{"index": 0, "url": f"/v1/files/{name}", "revised_prompt": None}]})
    b64 = base64.b64encode(data).decode()
    return jsonify({"created": int(time.time()), "data": [{"index": 0, "b64_json": b64}]})


# ---------- Prompt DSL 解析 ----------
def _parse_prompt(prompt: str, model: str):
    """返回 {key, texts, args, qqs}。model 非 'meme' 时强制作为模板 key。"""
    idx = _meme_index()
    key = None
    if model and model != "meme":
        key = model
    args = {}
    qqs = []
    text_tokens = []
    tokens = (prompt or "").split()
    for i, t in enumerate(tokens):
        if t.startswith("#") and "=" in t:
            k, v = t[1:].split("=", 1)
            args[k] = v
        elif t.startswith("@") and t[1:].isdigit():
            qqs.append(t[1:])
        else:
            if key is None and i == 0:
                key = t  # 首个普通词 = 模板关键字
            else:
                text_tokens.append(t)
    texts = (" ".join(text_tokens)).split("|") if text_tokens else []
    return {"key": key, "texts": texts, "args": args, "qqs": qqs}


def _collect_images_from_body() -> list[bytes]:
    out = []
    # multiplart：edits 用 images[]/image
    for f in request.files.getlist("images[]"):
        raw = f.read()
        if raw:
            out.append(raw)
    if not out:
        for f in request.files.getlist("image"):
            raw = f.read()
            if raw:
                out.append(raw)
    # JSON body 里的 b64：image / images
    if request.is_json:
        d = request.get_json(silent=True) or {}
        for k in ("images",):
            arr = d.get(k)
            if isinstance(arr, list):
                for item in arr:
                    try:
                        out.append(base64.b64decode(str(item)))
                    except Exception:
                        pass
        raw_img = d.get("image")
        if raw_img and not out and isinstance(raw_img, str):
            try:
                out.append(base64.b64decode(raw_img.split(",", 1)[-1]))
            except Exception:
                pass
    return out


def _fetch_avatar_bytes(qq: str):
    try:
        get_qq_info, download_qq_avatar_from_url = _app("get_qq_info", "download_qq_avatar_from_url")
        _, url = get_qq_info(qq)
        if url:
            im = download_qq_avatar_from_url(url)
            if im is None:
                return None
            buf = __import__("io").BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
    except Exception:
        return None
    return None


@bp.route("/images/generations", methods=["POST"])
def images_generations():
    d = request.get_json(silent=True) or {}
    prompt = d.get("prompt", "")
    model = d.get("model", "meme")
    fmt = d.get("response_format", "b64_json")
    if fmt not in ("b64_json", "url"):
        return _err("response_format 仅支持 b64_json 或 url", param="response_format")

    if not prompt and (not model or model == "meme"):
        return _err("需要提供 prompt", param="prompt")
    if not prompt:
        prompt = model

    p = _parse_prompt(prompt, model)
    if not p["key"]:
        return _err("无法从 prompt 中解析出模板", param="prompt")
    idx = _meme_index()
    if p["key"] not in idx:
        return _err(f"未找到模板/表情：{p['key']}", "not_found_error", param="model", code="model_not_found")

    # 图片来源：body 内嵌 / @QQ 头像
    images = _collect_images_from_body()
    for qq in p["qqs"]:
        av = _fetch_avatar_bytes(qq)
        if av:
            images.append(av)

    try:
        coerce_args = meme_service.coerce_args({**p["args"], "_key": p["key"]})
        data = meme_service.generate(p["key"], images, p["texts"], coerce_args)
    except Exception as e:
        return _meme_error_to_openai(e)
    return _response(data, fmt, "/v1/files")


@bp.route("/images/edits", methods=["POST"])
def images_edits():
    prompt = request.form.get("prompt", "")
    model = request.form.get("model", "meme")
    fmt = request.form.get("response_format", "b64_json")
    if fmt not in ("b64_json", "url"):
        return _err("response_format 仅支持 b64_json 或 url", param="response_format")

    if not prompt and (not model or model == "meme"):
        return _err("需要提供 prompt", param="prompt")

    p = _parse_prompt(prompt if prompt else model, model)
    if not p["key"]:
        return _err("无法从 prompt 中解析出模板", param="prompt")
    idx = _meme_index()
    if p["key"] not in idx:
        return _err(f"未找到模板/表情：{p['key']}", "not_found_error", param="model", code="model_not_found")

    images = _collect_images_from_body()
    for qq in p["qqs"]:
        av = _fetch_avatar_bytes(qq)
        if av:
            images.append(av)

    try:
        coerce_args = meme_service.coerce_args({**p["args"], "_key": p["key"]})
        data = meme_service.generate(p["key"], images, p["texts"], coerce_args)
    except Exception as e:
        return _meme_error_to_openai(e)
    return _response(data, fmt, "/v1/files")


# ---------- 辅助 ----------
def _decode_image(b64):
    if not b64:
        return None
    try:
        from PIL import Image
        raw = base64.b64decode(b64.split(",", 1)[-1])
        return Image.open(__import__("io").BytesIO(raw)).convert("RGBA")
    except Exception:
        return None


# ---------- 配对卡 ----------
@bp.route("/cards", methods=["POST"])
def cards():
    """生成配对卡。字段：template/qq/name/avatar/text/btn_text/font/bg/buttons/response_format"""
    d = request.get_json(silent=True) or {}
    generate_pair_image, DRAWERS = _app("generate_pair_image", "DRAWERS")
    get_qq_info, download_qq_avatar_from_url = _app("get_qq_info", "download_qq_avatar_from_url")

    template = d.get("template", "classic")
    if template not in DRAWERS:
        return _err(f"未知配对卡模板：{template}", "not_found_error", param="template", code="template_not_found")
    fmt = d.get("response_format", "url")
    if fmt not in ("b64_json", "url"):
        return _err("response_format 仅支持 b64_json 或 url", param="response_format")

    qq = str(d.get("qq", "")).strip()
    name = str(d.get("name", "")).strip()
    btn_text = str(d.get("btn_text", "配对"))
    font = d.get("font", "default")
    bg = d.get("bg") or {}

    # 主头像
    avatar = _decode_image(d.get("avatar"))
    if avatar is None and qq.isdigit():
        qn, url = get_qq_info(qq)
        if not name:
            name = qn or name
        avatar = download_qq_avatar_from_url(url) if url else None

    # 标题必须在昵称解析之后再替换 {name}，否则自动取到的昵称会丢
    text = str(d.get("text", "要与 {name} 配对吗？")).replace("{name}", name)

    # 按钮
    buttons = []
    raw_buttons = d.get("buttons")
    if isinstance(raw_buttons, list):
        for b in raw_buttons[:4]:
            if not isinstance(b, dict):
                continue
            typ = b.get("type", "text")
            bt = str(b.get("text", "")).strip()
            ib64 = str(b.get("icon", "") or "")
            icon = _decode_image(ib64)
            if typ == "image" and icon is not None:
                bt = ""
            elif typ in ("icon_text", "image") and icon is None:
                typ = "text"
            if typ == "text" and not bt:
                continue
            buttons.append({"type": typ, "text": bt, "icon": icon})
    if not buttons:
        buttons = [{"type": "text", "text": btn_text, "icon": None}]

    img = generate_pair_image(qq, text, avatar, font, template, bg, buttons)
    buf = __import__("io").BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    return _response(data, fmt, "/v1/files")


# ---------- 模型枚举 ----------
@bp.route("/models", methods=["GET"])
def models():
    out = []
    for m in meme_service.list_memes(""):
        out.append({"id": m["key"], "object": "model", "created": 0, "owned_by": "meme-generator"})
    out.append({"id": "card", "object": "model", "created": 0, "owned_by": "pair-card"})
    return jsonify({"object": "list", "data": out})


# ---------- 产物下载 ----------
@bp.route("/files/<name>")
def files(name):
    path = os.path.join(V1_DIR, os.path.basename(name))
    if not os.path.exists(path):
        return _err("文件不存在或已过期", "not_found_error", code="file_not_found")
    return send_file(path, max_age=3600)
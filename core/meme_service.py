"""GIF 表情生成 Service 层：封装 meme-generator，供 API 层调用。

职责：
- 列出可用表情及参数结构
- 生成预览缩略图
- 按 key + 图片 + 文本 + 选项生成最终 GIF/图片
不接触 HTTP、不接触模板渲染。
"""
import io
import os
import re
import threading
import typing
from enum import Enum

from PIL import Image as PILImage

import config  # 必须排在引擎导入之前：config 会自举 vendor 并补出素材目录

from meme_generator import get_meme as _engine_get_meme
from meme_generator import get_memes as _engine_get_memes
from meme_generator import load_memes as _engine_load_memes
from meme_generator.exception import (
    ArgModelMismatch,
    ImageNumberMismatch,
    NoSuchMeme,
    OpenImageFailed,
    TextNumberMismatch,
    TextOrNameNotEnough,
    TextOverLength,
)

KNOWN_ERRORS = (
    NoSuchMeme,
    ImageNumberMismatch,
    TextNumberMismatch,
    TextOrNameNotEnough,
    TextOverLength,
    ArgModelMismatch,
    OpenImageFailed,
)

# 引擎只在 import meme_generator 那一刻扫一遍包内 memes/，而仓库不带素材本体
# （见 .gitignore 的 vendor 分层），新克隆的机器上这次扫描是空的。这里在首次
# 真正用到表情时按需补扫，素材补齐后无需重启；下载中途被抓到一半也没关系，
# 下次调用发现磁盘上的表情变多了会再补一次。
_memes_lock = threading.Lock()
_memes_tried = ()       # 上次补扫的「目录 + 个数」签名，避免反复白扫


def _asset_dir() -> str:
    """素材目录；取不到就返回空串。"""
    try:
        import meme_assets
        return meme_assets.asset_dir() or ""
    except Exception:
        return ""


def _meme_names(d: str) -> set:
    """素材目录下的表情目录名；目录不存在返回空集合。"""
    try:
        return {n for n in os.listdir(d)
                if not n.startswith("_") and os.path.isdir(os.path.join(d, n))}
    except OSError:
        return set()


def ensure_memes_loaded() -> int:
    """确保素材已挂进引擎，返回当前表情总数。"""
    global _memes_tried
    with _memes_lock:
        have = len(_engine_get_memes())
        d = _asset_dir()
        want = _meme_names(d) if d else set()
        sig = (d, len(want))
        if not want or have >= len(want) or sig == _memes_tried:
            return have
        _memes_tried = sig
        _engine_load_memes(d)
        return len(_engine_get_memes())


def get_meme(key: str):
    """按 key 取表情；首次调用会先补扫素材目录。"""
    ensure_memes_loaded()
    return _engine_get_meme(key)


def get_memes() -> list:
    """全部表情；首次调用会先补扫素材目录。"""
    ensure_memes_loaded()
    return _engine_get_memes()


def _option_choices(annotation):
    """从 Literal/Enum 注解提取可选值列表；非此类返回 None。"""
    try:
        origin = typing.get_origin(annotation)
    except Exception:
        origin = None
    if origin is typing.Literal:
        return [str(c) for c in typing.get_args(annotation)]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [str(m.value) for m in annotation]
    return None


def _field_type(annotation) -> str | None:
    s = str(annotation)
    if "bool" in s and not ("list" in s or "dict" in s or "UserInfo" in s):
        return "bool"
    if s in ("<class 'str'>",):
        return "text"
    if "float" in s:
        return "float"
    if "int" in s and "list" not in s and "dict" not in s:
        return "int"
    if _option_choices(annotation) is not None:
        return "choose"
    return None


def list_memes(query: str = "") -> list[dict]:
    """列出表情元信息，支持按 key/关键词模糊过滤。"""
    q = query.strip().lower()
    out = []
    for m in get_memes():
        if q:
            haystack = " ".join([m.key] + list(m.keywords))
            if q not in haystack.lower():
                continue
        pt = m.params_type
        opts = []
        if pt.args_type is not None:
            for name, field in pt.args_type.args_model.model_fields.items():
                if "UserInfo" in str(field.annotation):
                    continue  # 隐藏字段，前端不暴露
                ftype = _field_type(field.annotation)
                if ftype is None:
                    continue
                opt = {"name": name, "type": ftype, "default": field.default, "help": field.description or ""}
                if ftype == "choose":
                    opt["choices"] = _option_choices(field.annotation) or []
                if ftype == "int":
                    # 形如“范围为 1~21”的帮助文本指示该整数是变体选择器（如举牌编号）
                    mm = re.search(r"(\d+)\s*[~\-–—]\s*(\d+)", field.description or "")
                    if mm:
                        opt["min"] = int(mm.group(1))
                        opt["max"] = int(mm.group(2))
                opts.append(opt)
        out.append({
            "key": m.key,
            "keywords": m.keywords[:6],
            "tags": sorted(m.tags)[:6] if m.tags else [],
            "min_images": pt.min_images,
            "max_images": pt.max_images,
            "min_texts": pt.min_texts,
            "max_texts": pt.max_texts,
            "default_texts": pt.default_texts,
            "options": opts,
        })
    return out


def preview(key: str, args: dict | None = None) -> bytes:
    """用真实 meme 引擎实时生成预览，返回图片/GIF 字节。args 可传入样式选项（如 mode='loop'）以便预览不同风格。"""
    return get_meme(key).generate_preview(args=args or {}).getvalue()


def generate(key: str, images: list[bytes], texts: list[str], args: dict) -> bytes:
    """生成最终表情。images 为原始字节列表，texts 为文本列表，args 为选项。"""
    return get_meme(key)(images=images, texts=texts, args=args).getvalue()


def coerce_args(raw: dict) -> dict:
    """把前端传来的字符串选项按字段类型转成 python 值。"""
    m = get_meme(raw.pop("_key", "")) if "_key" in raw else None
    fields = None
    if m is not None and m.params_type.args_type is not None:
        fields = {n: f.annotation for n, f in m.params_type.args_type.args_model.model_fields.items()}
    out = {}
    for k, v in raw.items():
        if v is None or v == "":
            continue
        ann = (fields or {}).get(k, str)
        if _field_type(ann) == "bool":
            out[k] = str(v).lower() in ("1", "true", "yes")
        elif _field_type(ann) == "int":
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = v
        elif _field_type(ann) == "float":
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
        else:
            out[k] = v
    return out
"""GIF 表情生成 Service 层：封装 meme-generator，供 API 层调用。

职责：
- 列出可用表情及参数结构
- 生成预览缩略图
- 按 key + 图片 + 文本 + 选项生成最终 GIF/图片
不接触 HTTP、不接触模板渲染。
"""
import io
import re
import typing
from enum import Enum

from PIL import Image as PILImage

from meme_generator import get_meme, get_memes
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
"""管理后台蓝本（/admin）。

功能：
- 登录 / 登出（管理密码，首次访问时设置）
- 状态检查（复用 app.py 的 /api/status 数据）
- API Key 管理（增删查、启用/禁用）
"""
import functools
import time

from flask import Blueprint, jsonify, render_template, request, session, redirect, url_for, current_app

import api_key_store

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------- 登录校验 ----------
def login_required(fn):
    # 管理端点必须已登录（session.admin_ok）才可访问；未登录返回 401。
    # /v1 接口的 Bearer 鉴权仍保留在 openai_api.py。
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_ok'):
            return jsonify({"error": "未登录"}), 401
        return fn(*args, **kwargs)
    return wrapper


@bp.route("/")
def index():
    return redirect("/")


@bp.route("/login")
def login_page():
    return redirect("/")


# ---------- 登录 / 登出 API ----------
@bp.route("/api/login", methods=["POST"])
def api_login():
    d = request.get_json(silent=True) or {}
    pwd = (d.get("password") or "").strip()
    if not pwd:
        return jsonify({"error": "请输入密码"}), 400

    if not api_key_store.verify_admin_password(pwd):
        return jsonify({"error": "密码错误"}), 401

    session["admin_ok"] = True
    session.permanent = True
    return jsonify({"ok": True})


@bp.route("/api/password", methods=["POST"])
@login_required
def password_change():
    """修改管理密码：需校验当前密码，新密码至少 4 位。"""
    d = request.get_json(silent=True) or {}
    cur = (d.get("current") or "").strip()
    new = (d.get("new") or "").strip()
    if len(new) < 4:
        return jsonify({"error": "新密码至少 4 位"}), 400
    if not api_key_store.verify_admin_password(cur):
        return jsonify({"error": "当前密码不正确"}), 401
    api_key_store.set_admin_password(new)
    return jsonify({"ok": True})


@bp.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@bp.route("/api/session")
def api_session():
    return jsonify({"logged_in": bool(session.get("admin_ok"))})


# ---------- API Key 管理 ----------
@bp.route("/api/keys", methods=["GET"])
@login_required
def keys_list():
    return jsonify({"keys": api_key_store.list_keys()})


@bp.route("/api/keys", methods=["POST"])
@login_required
def keys_create():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    entry = api_key_store.create_key(name)
    return jsonify({"ok": True, "key": entry})


@bp.route("/api/keys/<path:k>", methods=["DELETE"])
@login_required
def keys_delete(k):
    api_key_store.delete_key(k)
    return jsonify({"ok": True})


@bp.route("/api/keys/<path:k>/toggle", methods=["POST"])
@login_required
def keys_toggle(k):
    entry = api_key_store.toggle_key(k)
    if not entry:
        return jsonify({"error": "未找到该 Key"}), 404
    return jsonify({"ok": True, "key": entry})


# ---------- 接口测试目录 ----------
@bp.route("/api/endpoints")
@login_required
def endpoints():
    return jsonify({"endpoints": [
        {"method": "GET", "path": "/api/status", "summary": "状态聚合：服务器 / Meme / 缓存 / 字体 / 接口统计", "needKey": False, "query": ""},
        {"method": "GET", "path": "/api/cache_status", "summary": "缓存文件数量与占用", "needKey": False, "query": ""},
        {"method": "GET", "path": "/api/meme/list", "summary": "表情模板列表（可关键词过滤）", "needKey": False, "query": "query=petpet"},
        {"method": "GET", "path": "/api/meme/preview/<key>", "summary": "表情预览图", "needKey": False, "query": ""},
        {"method": "GET", "path": "/v1/models", "summary": "OpenAI 兼容 - 模型/模板列表", "needKey": False, "query": ""},
        {"method": "GET", "path": "/admin/api/session", "summary": "后台会话状态", "needKey": False, "query": ""},
        {"method": "POST", "path": "/api/get_user_info", "summary": "获取 QQ 昵称与头像", "needKey": False,
         "body": {"qq": "3157037483"}},
        {"method": "POST", "path": "/api/generate_image", "summary": "配对卡生成（原生）", "needKey": False,
         "body": {"template": "classic", "qq": "3157037483", "name": "测试", "text": "要与 {name} 配对吗？", "btn_text": "配对"}},
        {"method": "POST", "path": "/v1/images/generations", "summary": "OpenAI 兼容 - Meme 表情生成", "needKey": True,
         "body": {"prompt": "petpet @3157037483", "response_format": "url"}},
        {"method": "POST", "path": "/v1/images/edits", "summary": "OpenAI 兼容 - 带图 Meme 生成", "needKey": True, "needFile": True,
         "body": {"prompt": "my_wife"}},
        {"method": "POST", "path": "/v1/cards", "summary": "OpenAI 兼容 - 配对卡生成", "needKey": True,
         "body": {"template": "classic", "qq": "3157037483", "name": "测试", "response_format": "url"}},
    ]})

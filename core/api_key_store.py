"""API Key 与管理后台密码的本地 JSON 存储。

数据文件：api_keys.json
{
  "admin_hash": "<werkzeug password hash>",
  "keys": [
    {"key":"sk-...","name":"...","created":123,"enabled":true,"last_used":null}
  ]
}
"""
import json
import os
import secrets
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

import config

# 数据文件路径由 .env 决定（API_KEYS_PATH，默认项目根下 api_keys.json）
_PATH = config.API_KEYS_PATH
_lock = threading.Lock()


def _load():
    if not os.path.exists(_PATH):
        return {"admin_hash": None, "keys": []}
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"admin_hash": None, "keys": []}


def _save(data):
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PATH)


# ---------- 管理后台密码 ----------
def has_admin_password():
    return bool(_load().get("admin_hash"))


def set_admin_password(password):
    with _lock:
        data = _load()
        data["admin_hash"] = generate_password_hash(password)
        _save(data)


def verify_admin_password(password):
    h = _load().get("admin_hash")
    if not h:
        return False
    return check_password_hash(h, password)


# ---------- API Key ----------
def list_keys():
    return _load().get("keys", [])


def create_key(name=""):
    raw = "sk-" + secrets.token_urlsafe(32)
    with _lock:
        data = _load()
        entry = {"key": raw, "name": name or "未命名", "created": int(time.time()), "enabled": True, "last_used": None}
        data.setdefault("keys", []).append(entry)
        _save(data)
    return entry


def delete_key(key):
    with _lock:
        data = _load()
        data["keys"] = [k for k in data.get("keys", []) if k["key"] != key]
        _save(data)


def toggle_key(key):
    with _lock:
        data = _load()
        for k in data.get("keys", []):
            if k["key"] == key:
                k["enabled"] = not k.get("enabled", True)
                _save(data)
                return k
    return None


def is_valid_key(raw):
    """校验 API Key 是否存在且启用，顺便更新 last_used。"""
    if not raw:
        return False
    with _lock:
        data = _load()
        for k in data.get("keys", []):
            if k["key"] == raw:
                if not k.get("enabled", True):
                    return False
                k["last_used"] = int(time.time())
                _save(data)
                return True
    return False

"""API Key 与管理后台密码的本地 JSON 存储。

数据文件：api_keys.json
{
  "admin_hash": "<werkzeug password hash>",
  "admin_pwd_source": "user | auto | env",
  "admin_temp_pwd": "<待确认期间的临时密码明文，确认后即删>",
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
# admin_pwd_source 记录密码来历，只有 user 才算「用户自己确认过」：
#   user = 用户在引导页或「设置 → 修改密码」里设的
#   env  = 启动时取自 .env 的 INIT_ADMIN_PASSWORD
#   auto = 启动时随机生成的临时密码
# 后两种都算「待确认」：临时密码明文记在 admin_temp_pwd 里，每次启动都会重新打印，
# 用户错过一次不至于被永久锁在门外；用户确认后这块明文立刻抹掉。
def has_admin_password():
    return bool(_load().get("admin_hash"))


def admin_password_source():
    """密码来历：user=用户自己设过；auto=启动时随机生成；env=取自 .env 的初始值。

    没有密码时返回空串。老数据没有这个字段，按 auto 处理。
    """
    d = _load()
    if not d.get("admin_hash"):
        return ""
    return str(d.get("admin_pwd_source") or "auto")


def admin_password_pending():
    """密码还没被用户确认过。

    启动时总会把初始密码写进去（随机生成或取自 .env），只认「有没有哈希」会把
    这种密码当成已设置好的：用户没记下终端里那串随机密码就再也进不去后台，
    引导页也不再让设。所以这里只认 user 来源。
    """
    return admin_password_source() != "user"


def admin_temp_password():
    """待确认期间那枚临时密码的明文；已确认（或没有密码）时返回空串。"""
    if not admin_password_pending():
        return ""
    return str(_load().get("admin_temp_pwd") or "")


def set_admin_password(password, source="user"):
    """写入管理密码。

    source=user 会抹掉临时密码明文；其余来源把它记下来，下次启动好再打印一遍。
    """
    src = str(source or "user")
    with _lock:
        data = _load()
        data["admin_hash"] = generate_password_hash(password)
        data["admin_pwd_source"] = src
        if src == "user":
            data.pop("admin_temp_pwd", None)
        else:
            data["admin_temp_pwd"] = str(password)
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

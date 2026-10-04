# -*- coding: utf-8 -*-
"""统一配置中心（.env 驱动）

设计
----
1. 项目所有可调参数（WebUI 监听地址/端口、WS 服务器、目录、缓存、画布尺寸…）
   都集中定义在项目根目录的 .env 文件中，代码里不再散落硬编码。
2. 加载顺序（后者不覆盖前者）：
       系统环境变量  >  .env 文件  >  config.py 内置默认值
   即 .env 通过 os.environ.setdefault() 注入，系统里已显式设置的同名变量优先。
3. 没有任何第三方依赖（不需要 python-dotenv），删掉 / 写错 .env 也不会导致启动失败，
   只会回落到内置默认值。

用法
----
    import config

    config.WEB_HOST          # '0.0.0.0'
    config.WEB_PORT          # 5000
    config.WS_DEFAULT_CONFIG # {'host': ..., 'port': ..., ...}
    config.describe()        # 供 WebUI 展示的「当前生效配置」清单（敏感项已脱敏）

改完 .env 一般需要重启服务；但 WebUI「设置」页可以直接编辑这些参数：
    config.env_schema()    # 分组 + 每项的标签/类型/可选值/当前值（供前端生成表单）
    config.apply_updates() # 把改动写回 .env 并热重载，标记 hot 的项立刻生效

WS 服务器另有 WS_CONFIG_PRIORITY 规则，见文件末尾。
"""

import importlib
import importlib.util
import os
import re
import sys

# ----------------------------------------------------------------------------
# .env 文件解析
# ----------------------------------------------------------------------------
# 本文件位于 <项目根>/core/，ROOT 必须指回项目根（.env、cache、temp、font、
# plugins、plugins_config.json 等都在根目录，取错会把所有相对路径带偏）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT, ".env")

# ----------------------------------------------------------------------------
# 表情引擎路径自举（vendor 里的 meme-generator 源码）
# ----------------------------------------------------------------------------
# 以前是 start.bat / deploy.bat 往 .venv 里写 meme_generator.pth 让引擎可导入；
# 一键脚本已移除，改为这里运行时兜底：环境里没装 meme_generator，而 vendor
# 里带着源码，就把 vendor 目录挂到 sys.path，省掉手写 .pth 这一步。
VENDOR_MEME_DIR = os.path.join(ROOT, "vendor", "meme-generator-main")

# 引擎包内的素材目录。素材本体不跟仓库走（.gitignore 只入库引擎源码、字体与素材
# 清单），克隆下来的仓库里这个目录并不存在；而 meme_generator 导入时会无条件
# 遍历它，目录缺失就抛 FileNotFoundError —— app 连 import meme_service 这一步都
# 过不去，那个负责下载素材的引导页自然也就进不去（先有鸡还是先有蛋）。这里先落
# 一个空目录把导入链打通，素材留给引导页联网补全。
VENDOR_MEME_ASSET_DIR = os.path.join(VENDOR_MEME_DIR, "meme_generator", "memes")


def _ensure_vendor_meme_dir():
    """建出引擎包内 memes/ 目录（空目录够用）。vendor 不在就什么都不做。"""
    if not os.path.isdir(VENDOR_MEME_DIR) or os.path.isdir(VENDOR_MEME_ASSET_DIR):
        return False
    try:
        os.makedirs(VENDOR_MEME_ASSET_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def _bootstrap_vendor_meme():
    """把 vendor 里的 meme-generator 挂进 sys.path（仅当环境里没装时）。"""
    if not os.path.isdir(os.path.join(VENDOR_MEME_DIR, "meme_generator")):
        return False
    try:
        if importlib.util.find_spec("meme_generator") is not None:
            return False
    except Exception:
        pass
    if VENDOR_MEME_DIR not in sys.path:
        sys.path.append(VENDOR_MEME_DIR)
    return True


_ensure_vendor_meme_dir()
VENDOR_MEME_BOOTSTRAPPED = _bootstrap_vendor_meme()

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TRUTHY = {"1", "true", "yes", "y", "on", "是", "开", "启用"}
_FALSY = {"0", "false", "no", "n", "off", "否", "关", "禁用", ""}


def parse_env_file(path=ENV_FILE):
    """解析 KEY=VALUE 形式的 .env，返回 dict（文件不存在返回空 dict）。

    支持：# 整行注释、空行、export 前缀、单/双引号包裹、行尾注释（# 前需有空白）。
    """
    out = {}
    try:
        if not os.path.isfile(path):
            return out
        with open(path, "r", encoding="utf-8-sig") as f:
            raw_lines = f.readlines()
    except Exception:
        return out

    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not _KEY_RE.match(key):
            continue

        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            quote = val[0]
            val = val[1:-1]
            if quote == '"':
                val = (val.replace("\\n", "\n").replace("\\t", "\t")
                          .replace('\\"', '"').replace("\\\\", "\\"))
        else:
            # 去掉行尾注释：只有 # 前面是空白（或行首）时才算注释
            for i, ch in enumerate(val):
                if ch == "#" and (i == 0 or val[i - 1] in " \t"):
                    val = val[:i]
                    break
            val = val.strip()
        out[key] = val
    return out


FILE_ENV = parse_env_file(ENV_FILE)
ENV_FILE_EXISTS = os.path.isfile(ENV_FILE)

# 注入 .env 之前先记下「进程本来就存在的环境变量」——这些键由系统接管，
# 写进 .env 重启后也不会生效，WebUI 会据此提示管理员。
if "_SYS_ENV_KEYS" not in globals():
    _SYS_ENV_KEYS = set(os.environ.keys())

# 注入进程环境：已有的系统环境变量优先，不被 .env 覆盖
for _k, _v in FILE_ENV.items():
    os.environ.setdefault(_k, _v)


# ----------------------------------------------------------------------------
# 取值辅助
# ----------------------------------------------------------------------------
def has(key):
    """该键是否被显式配置过（.env 或系统环境变量）。"""
    return key in os.environ


def get_str(key, default=""):
    v = os.environ.get(key)
    return default if v is None else v


def get_int(key, default=0):
    try:
        v = os.environ.get(key)
        if v is None or str(v).strip() == "":
            return default
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def get_float(key, default=0.0):
    try:
        v = os.environ.get(key)
        if v is None or str(v).strip() == "":
            return default
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def get_bool(key, default=False):
    v = os.environ.get(key)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    return default


def get_path(key, default):
    """目录/文件路径：相对路径一律相对于项目根目录解析成绝对路径。"""
    v = (os.environ.get(key) or "").strip() or default
    v = v.replace("\\", os.sep).replace("/", os.sep)
    return v if os.path.isabs(v) else os.path.normpath(os.path.join(ROOT, v))


# ----------------------------------------------------------------------------
# WebUI / Flask
# ----------------------------------------------------------------------------
WEB_HOST = get_str("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
WEB_PORT = get_int("WEB_PORT", 5000)
WEB_DEBUG = get_bool("WEB_DEBUG", False)
WEB_THREADED = get_bool("WEB_THREADED", True)
WEB_MAX_UPLOAD_MB = get_int("WEB_MAX_UPLOAD_MB", 64)
WEB_MAX_UPLOAD_BYTES = max(1, WEB_MAX_UPLOAD_MB) * 1024 * 1024

# 留空 = 每次启动随机生成（重启后旧登录 cookie 失效，必须重新登录）；
# 填固定值则重启后仍保持登录状态。
SECRET_KEY = get_str("SECRET_KEY", "")
SECRET_KEY_IS_RANDOM = SECRET_KEY.strip() == ""

# 设置自己的管理密码之前临时使用的密码；
# 留空 = 启动时随机生成 8 位并打印到启动日志。
INIT_ADMIN_PASSWORD = get_str("INIT_ADMIN_PASSWORD", "")


# ----------------------------------------------------------------------------
# 目录 / 数据文件
# ----------------------------------------------------------------------------
TEMP_DIR = get_path("TEMP_DIR", "temp")
CACHE_DIR = get_path("CACHE_DIR", "cache")
FONT_DIR = get_path("FONT_DIR", "font")
BG_DIR = get_path("BG_DIR", os.path.join("static", "bg"))
BG_CONFIG_PATH = get_path("BG_CONFIG_PATH", "bg_config.json")
API_KEYS_PATH = get_path("API_KEYS_PATH", "api_keys.json")
OPENAI_V1_DIR = get_path("OPENAI_V1_DIR", os.path.join("cache", "v1"))

# 上传背景图的对外 URL 前缀（后端用 /bg/<文件名> 从 BG_DIR 读取，与目录位置解耦）
BG_URL_PREFIX = "/" + get_str("BG_URL_PREFIX", "bg").strip().strip("/")


# ----------------------------------------------------------------------------
# 字体：全局字体
# 候选字体 = FONT_DIR 目录里放进去的字体文件；「system」= 用系统自带中文字体。
# ----------------------------------------------------------------------------
# 全局字体：所有机器人图片（菜单 / 帮助 / 名言图 …）统一使用，署名也用它。
FONT_FAMILY = get_str("FONT_FAMILY", "system").strip() or "system"

# 这些值都表示「不指定具体字体文件，交给系统字体查找」
_FONT_SYSTEM_ALIASES = ("", "system", "default", "inherit", "auto")


def font_choices():
    """FONT_DIR 里可用的字体 → [(文件名, 显示名)]，供设置页 / 前端下拉。"""
    out = []
    try:
        names = sorted(os.listdir(FONT_DIR))
    except Exception:
        names = []
    for fn in names:
        if not fn.lower().endswith((".ttf", ".otf", ".ttc")):
            continue
        base = os.path.splitext(fn)[0]
        # 去掉文件名尾部的「-2 / 2」之类版本号，让下拉更好看
        label = base.rstrip(" -_0123456789").strip() or base
        out.append((fn, label))
    return out


def font_path(name):
    """字体配置值 → 字体文件绝对路径；system / inherit / 无效值 → None（= 用系统字体）。"""
    n = str(name or "").strip()
    if n.lower() in _FONT_SYSTEM_ALIASES:
        return None
    p = n if os.path.isabs(n) else os.path.join(FONT_DIR, n)
    return p if os.path.isfile(p) else None


def font_options():
    """设置页字体下拉的选项：[[值, 显示名], ...]"""
    opts = [["system", "系统默认字体"]]
    opts.extend([[fn, label] for fn, label in font_choices()])
    return opts


# ----------------------------------------------------------------------------
# 缓存 / 画布
# ----------------------------------------------------------------------------
CACHE_EXPIRE_DAYS = max(1, get_int("CACHE_EXPIRE_DAYS", 30))
CACHE_EXPIRE_SECONDS = CACHE_EXPIRE_DAYS * 24 * 3600
CANVAS_W = get_int("CANVAS_WIDTH", 600)
CANVAS_H = get_int("CANVAS_HEIGHT", 800)


# ----------------------------------------------------------------------------
# 背景图 API
# ----------------------------------------------------------------------------
BG_API = get_str("BG_API_URL", "https://api.yppp.net/api.php")
BG_FETCH_TIMEOUT = max(1, get_int("BG_FETCH_TIMEOUT", 8))


# ----------------------------------------------------------------------------
# Meme 素材（vendor/meme-generator-main）
# ----------------------------------------------------------------------------
# 素材目录：留空 = 引擎包内 memes/。meme_generator 只会从包内 memes/ 读图，
# 所以除非你同步修改引擎的读取路径，否则这里保持留空。
MEME_ASSET_DIR = get_str("MEME_ASSET_DIR", "").strip()
# 资源镜像前缀（末尾要带 / 或 @）。留空 = 用引擎自带的镜像列表 + 内置兜底镜像。
MEME_RESOURCE_BASE = get_str("MEME_RESOURCE_BASE", "").strip()


# ----------------------------------------------------------------------------
# WS 服务器（OneBot V11 / NapCat 反向 WebSocket）
# ----------------------------------------------------------------------------
WS_HOST = get_str("WS_HOST", "0.0.0.0").strip() or "0.0.0.0"
WS_PORT = get_int("WS_PORT", 6700)
WS_ACCESS_TOKEN = get_str("WS_ACCESS_TOKEN", "")
WS_AUTO_START = get_bool("WS_AUTO_START", False)
WS_CONFIG_PATH = get_path("WS_CONFIG_PATH", "ws_config.json")
WS_EVENT_LIMIT = max(10, get_int("WS_EVENT_LIMIT", 300))
WS_RAW_LIMIT = max(200, get_int("WS_RAW_LIMIT", 4000))
WS_MAX_FRAME_MB = max(1, get_int("WS_MAX_FRAME_MB", 16))


def _norm_ws_path(p):
    p = (p or "").strip() or "/onebot/v11/ws"
    if not p.startswith("/"):
        p = "/" + p
    return p


WS_PATH = _norm_ws_path(get_str("WS_PATH", "/onebot/v11/ws"))

# 默认配置（.env 提供；WebUI 里保存过的改动写入 ws_config.json）
WS_DEFAULT_CONFIG = {
    "host": WS_HOST,
    "port": WS_PORT,
    "path": WS_PATH,
    "access_token": WS_ACCESS_TOKEN,
    "auto_start": WS_AUTO_START,
}

# 配置优先级：
#   file（默认）—— WebUI 保存的 ws_config.json 覆盖 .env 默认值，面板可改可存；
#   env          —— 强制以 .env 为准，忽略 ws_config.json，面板保存会被拒绝。
WS_CONFIG_PRIORITY = (get_str("WS_CONFIG_PRIORITY", "file").strip().lower() or "file")
if WS_CONFIG_PRIORITY not in ("file", "env"):
    WS_CONFIG_PRIORITY = "file"
WS_ENV_LOCKED = (WS_CONFIG_PRIORITY == "env")


# ----------------------------------------------------------------------------
# Bot 指令框架（OneBot V11 消息指令：/help、/meme、/pair）
# ----------------------------------------------------------------------------
# 指令总开关：false 时 bot_commands 不注册事件处理器，机器人不响应任何指令。
BOT_ENABLED = get_bool("BOT_ENABLED", True)
# 机器人昵称（帮助图标题与文案里显示的名字）。
BOT_NAME = get_str("BOT_NAME", "我在哔哩学习").strip() or "我在哔哩学习"
# 指令前缀，默认 “/”（可改成 “#” 等）。
BOT_PREFIX = (get_str("BOT_PREFIX", "/").strip() or "/")[:3]
# 群聊里是否必须 @ 机器人（或 @全体）才响应指令；false = 直接发指令即可。
BOT_GROUP_NEED_AT = get_bool("BOT_GROUP_NEED_AT", False)
# 是否响应私聊指令。
BOT_ALLOW_PRIVATE = get_bool("BOT_ALLOW_PRIVATE", True)
# /meme list 素材列表每页条数（超出自动分多张图）。
BOT_MEME_LIST_PAGE = max(4, get_int("BOT_MEME_LIST_PAGE", 12))
# 单次回图最大体积（MB），超过则压缩/放弃，避免撑爆 WS 单帧上限。
BOT_MAX_IMAGE_MB = max(1, get_int("BOT_MAX_IMAGE_MB", 8))
# 同一用户指令的最短间隔（秒），0 = 不限制（防刷屏）。
BOT_COOLDOWN_SEC = max(0, get_int("BOT_COOLDOWN_SEC", 3))
# 帮助图右下角展示的落款。
BOT_FOOTER = get_str("BOT_FOOTER", "我在哔哩学习 Emoji Bot · ILBB").strip()


# ----------------------------------------------------------------------------
# 名言图（/名言 · /生成名言）：横屏 16:9 + 随机背景 + 灰色蒙版 + 全模糊托盘
#                   （托盘内左圆形头像 + 右内容）+ 右下角署名
# ----------------------------------------------------------------------------
# 名言图总开关：false 时 /名言 与 /生成名言 都回提示图，不生成名言图。
QUOTE_ENABLED = get_bool("QUOTE_ENABLED", True)
# 画布宽度 / 高度：默认 1280×720（16:9 横屏），画面正中一块全模糊托盘。
# 托盘内是静态内容 → 出 JPG；托盘内是动图 → 出 GIF。
QUOTE_WIDTH = max(480, get_int("QUOTE_WIDTH", 1280))
QUOTE_HEIGHT = max(270, get_int("QUOTE_HEIGHT", 720))
# 背景与前景之间的灰色蒙版不透明度（0~1）。0.35 = 压 35% 灰，背景仍可辨认；
# 数值越大背景越暗，内容（托盘 / 头像 / 文字）始终绘制在蒙版之上。
QUOTE_MASK_ALPHA = min(1.0, max(0.0, get_float("QUOTE_MASK_ALPHA", 0.35)))
# 静态图（JPG）输出质量。
QUOTE_JPG_QUALITY = min(100, max(60, get_int("QUOTE_JPG_QUALITY", 92)))
# 托盘内左侧圆形头像的直径。
QUOTE_AVATAR = max(96, get_int("QUOTE_AVATAR", 236))
# 托盘内背景的模糊半径（「全模糊」的核心，越大越糊）。
QUOTE_TRAY_BLUR = max(6.0, get_float("QUOTE_TRAY_BLUR", 30.0))
# 模糊层之上叠加的暖白玻璃浓度（0.2~0.92，越大越白、越不透）。
QUOTE_TRAY_GLASS = min(0.92, max(0.20, get_float("QUOTE_TRAY_GLASS", 0.58)))
# 托盘内文字自动字号的上下限。
QUOTE_TEXT_MAX = max(20, get_int("QUOTE_TEXT_MAX", 56))
QUOTE_TEXT_MIN = max(12, get_int("QUOTE_TEXT_MIN", 22))
# 托盘内容区最大高度（超过则缩字号 / 截断）。
QUOTE_MAX_BODY = max(200, get_int("QUOTE_MAX_BODY", 500))
# 右下角署名字号。
QUOTE_NAME_SIZE = max(18, get_int("QUOTE_NAME_SIZE", 40))
# 没有署名时用的占位名字。
QUOTE_NAME = get_str("QUOTE_NAME", "无名氏").strip() or "无名氏"
# 署名最大显示字数（超出截断）。
QUOTE_NAME_MAX = max(4, get_int("QUOTE_NAME_MAX", 16))
# 动图（GIF）输出的最多帧数与单帧最短时长（毫秒）。
QUOTE_GIF_MAX_FRAMES = max(2, get_int("QUOTE_GIF_MAX_FRAMES", 60))
QUOTE_GIF_MIN_MS = max(20, get_int("QUOTE_GIF_MIN_MS", 40))


# ----------------------------------------------------------------------------
# 插件系统（plugins/ 一个文件夹 = 一个插件）
# ----------------------------------------------------------------------------
# 插件总开关。
PLUGIN_ENABLED = get_bool("PLUGIN_ENABLED", True)
# 插件根目录（相对项目根）。
PLUGIN_DIR = get_path("PLUGIN_DIR", "plugins")
# 插件配置文件（Web 里改的插件配置存这里）。
PLUGIN_CONFIG_PATH = get_path("PLUGIN_CONFIG_PATH", "plugins_config.json")
# 是否启用热重载（轮询 mtime：改文件 / 加删插件目录自动生效）。
PLUGIN_HOT_RELOAD = get_bool("PLUGIN_HOT_RELOAD", True)
# 热重载轮询间隔（秒），最小 2 秒。
PLUGIN_POLL_SEC = max(2, get_int("PLUGIN_POLL_SEC", 3))
# 插件自带 Web 服务的地址模板：web=true 的插件按下发端口起服务，
# ILBB 用 <PLUGIN_WEB_SCHEME>://<插件 host>:<插件 port> 嵌入显示。
PLUGIN_WEB_SCHEME = (get_str("PLUGIN_WEB_SCHEME", "http").strip().lower() or "http")
if PLUGIN_WEB_SCHEME not in ("http", "https"):
    PLUGIN_WEB_SCHEME = "http"
# 插件 Web 端口分配起始值（web_port 为空时按需顺延分配）。
PLUGIN_WEB_PORT_BASE = max(1024, get_int("PLUGIN_WEB_PORT_BASE", 7000))
# 插件 Web 探测超时（秒）。
PLUGIN_WEB_TIMEOUT = max(1, get_int("PLUGIN_WEB_TIMEOUT", 4))
# 单个插件单条指令回图上限（MB）。
PLUGIN_MAX_IMAGE_MB = max(1, get_int("PLUGIN_MAX_IMAGE_MB", 8))

# ---- 插件商店（从插件源服务器拉列表，选加速地址后 git clone 进 plugins/） ----
# 商店总开关。
PLUGIN_STORE_ENABLED = get_bool("PLUGIN_STORE_ENABLED", True)
# 插件源服务器地址（末尾斜杠会自动去掉）。
PLUGIN_STORE_URL = (get_str("PLUGIN_STORE_URL", "https://store.miao.os.kg").strip() or "").rstrip("/")
# 访问插件源 / 测速的超时（秒）。
PLUGIN_STORE_TIMEOUT = max(2, get_int("PLUGIN_STORE_TIMEOUT", 10))
# 插件列表缓存秒数（0 = 每次都重新拉）。
PLUGIN_STORE_TTL = max(0, get_int("PLUGIN_STORE_TTL", 60))
# git 可执行文件名（不在 PATH 里时填绝对路径）。
PLUGIN_GIT_BIN = get_str("PLUGIN_GIT_BIN", "git").strip() or "git"
# git clone 超时（秒）。
PLUGIN_GIT_TIMEOUT = max(10, get_int("PLUGIN_GIT_TIMEOUT", 180))
# git clone 深度（1 = 只拉最新一次提交，最快）。
PLUGIN_GIT_DEPTH = max(1, get_int("PLUGIN_GIT_DEPTH", 1))
# 测速 / 试用安装用的示例仓库（商店里第一条记录）。
PLUGIN_GIT_TEST_REPO = get_str(
    "PLUGIN_GIT_TEST_REPO", "https://github.com/DXBbyd/ilbb_plugin_example.git").strip()
# GitHub 加速地址清单：前缀式（<前缀>https://github.com/owner/repo.git），
# 逗号 / 换行分隔，支持「名称|地址」写法自定义显示名。
PLUGIN_GIT_PROXIES = get_str("PLUGIN_GIT_PROXIES", ",".join([
    "https://gh.monlor.com/",
    "https://cdn.akaere.online/",
    "https://gh.llkk.cc/",
    "https://github-proxy.memory-echoes.cn/",
    "https://gitproxy.mrhjx.cn/",
    "https://ghfile.geekertao.top/",
    "https://ghproxy.imciel.com/",
    "https://ghf.xn--eqrr82bzpe.top/",
    "https://gh.xxooo.cf/",
    "https://gh.inkchills.cn/",
    "https://fastgit.cc/",
])).strip()


# ----------------------------------------------------------------------------
# 供 WebUI 展示 / 启动日志
# ----------------------------------------------------------------------------
def _mask(token):
    if not token:
        return "（空）"
    if len(token) <= 4:
        return "*" * len(token)
    return token[:2] + "*" * (len(token) - 4) + token[-2:]


def _split_list(raw):
    """把「逗号 / 换行分隔」的文本切成列表（插件商店的加速地址清单用）。"""
    out = []
    for tok in re.split(r"[\s,;，、]+", str(raw or "")):
        tok = tok.strip()
        if tok:
            out.append(tok)
    return out


def describe():
    """当前生效配置清单（分组的 [[键, 值, 说明], ...]），敏感项已脱敏。"""
    wsl = "（.env 接管，面板不可改）" if WS_ENV_LOCKED else "（面板可覆盖并保存）"
    return [
        ("WebUI", [
            ["WEB_HOST", WEB_HOST, "监听地址，0.0.0.0 = 允许局域网访问"],
            ["WEB_PORT", WEB_PORT, "监听端口"],
            ["WEB_DEBUG", "true" if WEB_DEBUG else "false", "调试模式"],
            ["WEB_THREADED", "true" if WEB_THREADED else "false", "多线程处理请求"],
            ["WEB_MAX_UPLOAD_MB", WEB_MAX_UPLOAD_MB, "单次请求体上限"],
            ["SECRET_KEY", "（每次启动随机）" if SECRET_KEY_IS_RANDOM else "（已固定）",
             "留空则重启后需要重新登录"],
            ["INIT_ADMIN_PASSWORD",
             "（已由 .env 指定）" if INIT_ADMIN_PASSWORD else "（随机生成）",
             "设置自己的管理密码之前的临时密码，之后请在「设置」里改"],
        ]),
        ("WS 服务器", [
            ["WS_HOST", WS_HOST, "OneBot V11 监听地址"],
            ["WS_PORT", WS_PORT, "OneBot V11 监听端口"],
            ["WS_PATH", WS_PATH, "反向 WebSocket 路径"],
            ["WS_ACCESS_TOKEN", _mask(WS_ACCESS_TOKEN), "访问令牌"],
            ["WS_AUTO_START", "true" if WS_AUTO_START else "false", "随主服务自动启动"],
            ["WS_CONFIG_PRIORITY", WS_CONFIG_PRIORITY, "配置来源：" + wsl],
            ["WS_EVENT_LIMIT", WS_EVENT_LIMIT, "事件环形缓冲条数"],
            ["WS_MAX_FRAME_MB", WS_MAX_FRAME_MB, "单条消息上限(MB)"],
        ]),
        ("Bot 指令", [
            ["BOT_ENABLED", "true" if BOT_ENABLED else "false", "指令总开关"],
            ["BOT_NAME", BOT_NAME, "机器人昵称（帮助图标题）"],
            ["BOT_PREFIX", BOT_PREFIX, "指令前缀"],
            ["BOT_GROUP_NEED_AT", "true" if BOT_GROUP_NEED_AT else "false", "群聊需 @机器人"],
            ["BOT_ALLOW_PRIVATE", "true" if BOT_ALLOW_PRIVATE else "false", "允许私聊指令"],
            ["BOT_MEME_LIST_PAGE", BOT_MEME_LIST_PAGE, "/meme list 每页条数"],
            ["BOT_MAX_IMAGE_MB", BOT_MAX_IMAGE_MB, "单张回图上限(MB)"],
            ["BOT_COOLDOWN_SEC", BOT_COOLDOWN_SEC, "同一用户指令冷却(秒)，0=不限"],
        ]),
        ("目录 / 数据", [
            ["TEMP_DIR", TEMP_DIR, "临时文件"],
            ["CACHE_DIR", CACHE_DIR, "图片缓存"],
            ["FONT_DIR", FONT_DIR, "字体目录（放进去即可被选中）"],
            ["FONT_FAMILY", FONT_FAMILY, "全局字体"],
            ["BG_DIR", BG_DIR, "背景图存放"],
            ["BG_CONFIG_PATH", BG_CONFIG_PATH, "背景配置"],
            ["API_KEYS_PATH", API_KEYS_PATH, "管理密码与 API Key"],
            ["OPENAI_V1_DIR", OPENAI_V1_DIR, "OpenAI 兼容接口产图目录"],
        ]),
        ("名言图", [
            ["QUOTE_ENABLED", "true" if QUOTE_ENABLED else "false", "/名言 · /生成名言 开关"],
            ["QUOTE_WIDTH", QUOTE_WIDTH, "名言图画布宽度"],
            ["QUOTE_HEIGHT", QUOTE_HEIGHT, "名言图画布高度（默认 16:9）"],
            ["QUOTE_MASK_ALPHA", QUOTE_MASK_ALPHA, "灰色蒙版不透明度（0~1，0.35=压 35% 灰）"],
            ["QUOTE_AVATAR", QUOTE_AVATAR, "左侧独立圆角矩形头像的宽度"],
            ["QUOTE_TRAY_BLUR", QUOTE_TRAY_BLUR, "右侧玻璃面板的模糊半径（越大越糊）"],
            ["QUOTE_TRAY_GLASS", QUOTE_TRAY_GLASS, "右侧玻璃面板浓度（0.2~0.96，越大越白）"],
            ["QUOTE_TEXT_MAX", QUOTE_TEXT_MAX, "面板文字最大字号"],
            ["QUOTE_TEXT_MIN", QUOTE_TEXT_MIN, "面板文字最小字号"],
            ["QUOTE_MAX_BODY", QUOTE_MAX_BODY, "面板内容区最大高度"],
            ["QUOTE_NAME_SIZE", QUOTE_NAME_SIZE, "署名（面板右下角）字号"],
            ["QUOTE_NAME", QUOTE_NAME, "无署名时的占位名字"],
            ["QUOTE_JPG_QUALITY", QUOTE_JPG_QUALITY, "JPG 输出质量"],
            ["QUOTE_GIF_MAX_FRAMES", QUOTE_GIF_MAX_FRAMES, "动图最多保留帧数"],
        ]),
        ("插件系统", [
            ["PLUGIN_ENABLED", "true" if PLUGIN_ENABLED else "false", "插件总开关"],
            ["PLUGIN_DIR", PLUGIN_DIR, "插件目录（一个文件夹 = 一个插件）"],
            ["PLUGIN_CONFIG_PATH", PLUGIN_CONFIG_PATH, "插件配置存储文件"],
            ["PLUGIN_HOT_RELOAD", "true" if PLUGIN_HOT_RELOAD else "false", "热重载（改文件自动生效）"],
            ["PLUGIN_POLL_SEC", PLUGIN_POLL_SEC, "热重载轮询间隔(秒)"],
            ["PLUGIN_WEB_SCHEME", PLUGIN_WEB_SCHEME, "插件自带 Web 的协议"],
            ["PLUGIN_WEB_PORT_BASE", PLUGIN_WEB_PORT_BASE, "插件 Web 端口分配起始"],
            ["PLUGIN_STORE_ENABLED", "true" if PLUGIN_STORE_ENABLED else "false", "插件商店总开关"],
            ["PLUGIN_STORE_URL", PLUGIN_STORE_URL or "（未配置）", "插件源服务器地址"],
            ["PLUGIN_GIT_PROXIES", "%d 个加速地址" % len(_split_list(PLUGIN_GIT_PROXIES)),
             "插件商店可选的 GitHub 加速地址（含「原 GitHub」直连）"],
            ["PLUGIN_GIT_BIN", PLUGIN_GIT_BIN, "git 可执行文件（安装插件用）"],
            ["PLUGIN_GIT_TIMEOUT", PLUGIN_GIT_TIMEOUT, "git clone 超时(秒)"],
        ]),
        ("Meme 素材", [
            ["MEME_ASSET_DIR", MEME_ASSET_DIR or "（引擎包内 memes/）", "素材目录"],
            ["MEME_RESOURCE_BASE", MEME_RESOURCE_BASE or "（引擎自带镜像）", "资源镜像前缀"],
        ]),
        ("其他", [
            ["CACHE_EXPIRE_DAYS", CACHE_EXPIRE_DAYS, "缓存保留天数"],
            ["CANVAS_WIDTH", CANVAS_W, "配对卡画布宽"],
            ["CANVAS_HEIGHT", CANVAS_H, "配对卡画布高"],
            ["BG_API_URL", BG_API, "随机背景图接口"],
        ]),
    ]


# ----------------------------------------------------------------------------
# 可编辑配置元数据（WebUI「设置」页据此生成表单）
# ----------------------------------------------------------------------------
# 字段含义：
#   key        .env 里的键名（也是 os.environ 键名）
#   label      表单里显示的中文名
#   type       text | int | float | bool | select | secret | path
#   options    type=select 时的可选值 [[值, 显示名], ...]
#   min/max    type=int/float 的取值范围
#   maxlen     type=text 时的最大长度
#   hot        True = 保存后立即生效；False = 需要重启服务才生效
#   sensitive  True = 前端不回显原值（留空表示“不修改”）
#   clearable  sensitive 项允许保存为空（表示清空 / 回到随机）
#   desc       一句话说明
#   note       额外提示（前端显示为灰色小字）
ENV_SCHEMA = [
    ("WebUI", [
        {"key": "WEB_HOST", "label": "监听地址", "type": "text", "hot": False,
         "desc": "0.0.0.0 = 允许局域网访问，127.0.0.1 = 仅本机", "note": "需重启主服务"},
        {"key": "WEB_PORT", "label": "监听端口", "type": "int", "min": 1, "max": 65535,
         "hot": False, "desc": "WebUI 访问端口", "note": "需重启主服务"},
        {"key": "WEB_DEBUG", "label": "调试模式", "type": "bool", "hot": False,
         "desc": "Flask 调试模式（生产环境建议关闭）", "note": "需重启主服务"},
        {"key": "WEB_THREADED", "label": "多线程", "type": "bool", "hot": False,
         "desc": "多线程处理请求", "note": "需重启主服务"},
        {"key": "WEB_MAX_UPLOAD_MB", "label": "上传体积上限", "type": "int",
         "min": 1, "max": 2048, "hot": True, "desc": "单次请求体上限（MB）"},
        {"key": "SECRET_KEY", "label": "登录密钥", "type": "secret", "hot": False,
         "sensitive": True, "clearable": True,
         "desc": "固定后重启仍保持登录；留空 = 每次启动随机（重启后需重新登录）",
         "note": "需重启主服务"},
        {"key": "INIT_ADMIN_PASSWORD", "label": "初始管理密码", "type": "secret",
         "hot": False, "sensitive": True, "clearable": True,
         "desc": "设置自己的管理密码之前的临时密码；留空 = 随机生成",
         "note": "在引导页或「设置」里设好自己的密码后即作废"},
    ]),
    ("WS 服务器", [
        {"key": "WS_HOST", "label": "监听地址", "type": "text", "hot": False,
         "desc": "OneBot V11 反向 WS 监听地址"},
        {"key": "WS_PORT", "label": "监听端口", "type": "int", "min": 1, "max": 65535,
         "hot": False, "desc": "OneBot V11 反向 WS 监听端口"},
        {"key": "WS_PATH", "label": "连接路径", "type": "text", "hot": False,
         "desc": "反向 WebSocket 路径，需与 NapCat 配置一致"},
        {"key": "WS_ACCESS_TOKEN", "label": "访问令牌", "type": "secret", "hot": False,
         "sensitive": True, "clearable": True, "desc": "留空 = 不校验令牌"},
        {"key": "WS_AUTO_START", "label": "随主服务启动", "type": "bool", "hot": False,
         "desc": "主服务启动时自动拉起 WS 服务器"},
        {"key": "WS_CONFIG_PRIORITY", "label": "配置优先级", "type": "select", "hot": False,
         "options": [["file", "ws_config.json 优先（面板可改可存）"],
                     ["env", ".env 优先（面板只读）"]],
         "desc": "决定 WS 面板能否覆盖上面的默认值"},
        {"key": "WS_EVENT_LIMIT", "label": "事件缓冲条数", "type": "int",
         "min": 10, "max": 100000, "hot": False, "desc": "事件环形缓冲条数"},
        {"key": "WS_RAW_LIMIT", "label": "原始日志条数", "type": "int",
         "min": 200, "max": 200000, "hot": False, "desc": "原始报文日志条数"},
        {"key": "WS_MAX_FRAME_MB", "label": "单帧上限", "type": "int",
         "min": 1, "max": 512, "hot": False, "desc": "单条 WebSocket 消息上限（MB）"},
    ]),
    ("Bot 指令", [
        {"key": "BOT_ENABLED", "label": "指令总开关", "type": "bool", "hot": True,
         "desc": "关闭后机器人不响应任何指令"},
        {"key": "BOT_NAME", "label": "机器人昵称", "type": "text", "maxlen": 32,
         "hot": True, "desc": "帮助图标题与文案里显示的名字"},
        {"key": "BOT_PREFIX", "label": "指令前缀", "type": "text", "maxlen": 3,
         "hot": True, "desc": "如 / 或 #，最长 3 个字符"},
        {"key": "BOT_GROUP_NEED_AT", "label": "群聊需 @", "type": "bool", "hot": True,
         "desc": "群聊里必须 @机器人 才响应指令"},
        {"key": "BOT_ALLOW_PRIVATE", "label": "允许私聊", "type": "bool", "hot": True,
         "desc": "是否响应私聊指令"},
        {"key": "BOT_MEME_LIST_PAGE", "label": "素材每页条数", "type": "int",
         "min": 4, "max": 60, "hot": True, "desc": "/meme list 每页条数（超出分多张图）"},
        {"key": "BOT_MAX_IMAGE_MB", "label": "回图上限", "type": "int",
         "min": 1, "max": 50, "hot": True, "desc": "单张回图上限（MB）"},
        {"key": "BOT_COOLDOWN_SEC", "label": "指令冷却", "type": "int",
         "min": 0, "max": 3600, "hot": True, "desc": "同一用户指令最短间隔（秒），0 = 不限"},
        {"key": "BOT_FOOTER", "label": "帮助图落款", "type": "text", "maxlen": 64,
         "hot": True, "desc": "帮助图右下角展示的落款"},
    ]),
    ("目录 / 数据", [
        {"key": "TEMP_DIR", "label": "临时文件目录", "type": "path", "hot": True,
         "desc": "相对路径按项目根目录解析"},
        {"key": "CACHE_DIR", "label": "图片缓存目录", "type": "path", "hot": True,
         "desc": "生成图片的缓存位置", "note": "bot 渲染缓存子目录重启后迁移"},
        {"key": "FONT_DIR", "label": "字体目录", "type": "path", "hot": True,
         "desc": "把 .ttf/.otf/.ttc 丢进这个目录，即可在「全局字体」里选中"},
        {"key": "FONT_FAMILY", "label": "全局字体", "type": "select", "hot": True,
         "options": font_options(),
         "desc": "所有机器人图片统一使用的字体；选「系统默认」则用系统自带中文字体"},
        {"key": "BG_DIR", "label": "背景图目录", "type": "path", "hot": True,
         "desc": "上传的背景图存放位置"},
        {"key": "BG_CONFIG_PATH", "label": "背景配置文件", "type": "path", "hot": True,
         "desc": "保存当前背景选择的 json"},
        {"key": "API_KEYS_PATH", "label": "密码/密钥文件", "type": "path", "hot": False,
         "desc": "管理密码与 API Key 的存储文件", "note": "需重启服务"},
        {"key": "OPENAI_V1_DIR", "label": "接口产图目录", "type": "path", "hot": False,
         "desc": "OpenAI 兼容接口生成的图片目录", "note": "需重启服务"},
        {"key": "BG_URL_PREFIX", "label": "背景 URL 前缀", "type": "text", "hot": False,
         "desc": "背景图的对外访问前缀，默认 bg（即 /bg/<文件名>）",
         "note": "路由在启动时注册，需重启主服务"},
    ]),
    ("名言图", [
        {"key": "QUOTE_ENABLED", "label": "功能开关", "type": "bool", "hot": True,
         "desc": "关闭后 /名言 · /生成名言 只回提示图"},
        {"key": "QUOTE_WIDTH", "label": "画布宽度", "type": "int", "min": 480, "max": 4000,
         "hot": True, "desc": "横屏画布宽度（默认 1280；建议与高度保持 16:9）"},
        {"key": "QUOTE_HEIGHT", "label": "画布高度", "type": "int", "min": 270, "max": 4000,
         "hot": True, "desc": "横屏画布高度（默认 720）"},
        {"key": "QUOTE_MASK_ALPHA", "label": "蒙版不透明度", "type": "float",
         "min": 0, "max": 1, "hot": True,
         "desc": "背景上那层灰色蒙版强度（0~1）。0.35 = 压 35% 灰，背景仍可辨认；数值越大背景越暗；左侧头像、右侧玻璃面板与文字都在蒙版之上"},
        {"key": "QUOTE_JPG_QUALITY", "label": "JPG 质量", "type": "int",
         "min": 60, "max": 100, "hot": True, "desc": "静态图输出压缩质量"},
        {"key": "QUOTE_AVATAR", "label": "头像宽度", "type": "int", "min": 96, "max": 800,
         "hot": True, "desc": "画面左侧独立圆角矩形头像的宽度（高度约为它的 1.32 倍）"},
        {"key": "QUOTE_TRAY_BLUR", "label": "玻璃模糊半径", "type": "float",
         "min": 6, "max": 120, "hot": True,
         "desc": "右侧白色磨砂玻璃面板覆盖的背景整块高斯模糊，这里控制模糊强度（越大越糊）"},
        {"key": "QUOTE_TRAY_GLASS", "label": "玻璃浓度", "type": "float",
         "min": 0.2, "max": 0.96, "hot": True,
         "desc": "模糊层之上叠加的暖白玻璃浓度：越大越白、越不透，"
                 "0.2 左右「重模糊」，0.8 以上「牛奶玻璃」"},
        {"key": "QUOTE_TEXT_MAX", "label": "文字最大字号", "type": "int",
         "min": 20, "max": 200, "hot": True, "desc": "自动字号的上级"},
        {"key": "QUOTE_TEXT_MIN", "label": "文字最小字号", "type": "int",
         "min": 12, "max": 200, "hot": True, "desc": "自动字号的级"},
        {"key": "QUOTE_MAX_BODY", "label": "内容最大高度", "type": "int",
         "min": 200, "max": 3000, "hot": True, "desc": "超出则继续缩字号 / 截断"},
        {"key": "QUOTE_NAME_SIZE", "label": "署名字号", "type": "int",
         "min": 18, "max": 200, "hot": True, "desc": "玻璃面板右下角「—— 用户名」字号"},
        {"key": "QUOTE_NAME", "label": "占位署名", "type": "text", "maxlen": 32,
         "hot": True, "desc": "取不到昵称时使用的名字"},
        {"key": "QUOTE_NAME_MAX", "label": "署名最大字数", "type": "int",
         "min": 4, "max": 64, "hot": True, "desc": "超出截断，避免撑破画布"},
        {"key": "QUOTE_GIF_MAX_FRAMES", "label": "动图最大帧数", "type": "int",
         "min": 2, "max": 300, "hot": True,
         "desc": "面板内容是动图时输出 GIF，超过此帧数则等间隔抽帧"},
    ]),
    ("插件系统", [
        {"key": "PLUGIN_ENABLED", "label": "插件总开关", "type": "bool", "hot": False,
         "desc": "关闭后不加载插件", "note": "运行中改动不会卸载已注册指令，建议重启"},
        {"key": "PLUGIN_DIR", "label": "插件目录", "type": "path", "hot": True,
         "desc": "一个子文件夹 = 一个插件", "note": "保存后会按新目录重新扫描"},
        {"key": "PLUGIN_CONFIG_PATH", "label": "插件配置文件", "type": "path", "hot": True,
         "desc": "插件配置的存储文件"},
        {"key": "PLUGIN_HOT_RELOAD", "label": "热重载", "type": "bool", "hot": True,
         "desc": "轮询文件改动自动生效（无需重启）"},
        {"key": "PLUGIN_POLL_SEC", "label": "轮询间隔", "type": "int",
         "min": 2, "max": 120, "hot": True, "desc": "热重载轮询间隔（秒）"},
        {"key": "PLUGIN_WEB_SCHEME", "label": "插件 Web 协议", "type": "select", "hot": True,
         "options": [["http", "http"], ["https", "https"]],
         "desc": "插件自带 Web 服务的访问协议"},
        {"key": "PLUGIN_WEB_PORT_BASE", "label": "Web 端口起始", "type": "int",
         "min": 1024, "max": 65000, "hot": True, "desc": "插件 Web 端口按需顺延分配"},
        {"key": "PLUGIN_WEB_TIMEOUT", "label": "Web 探测超时", "type": "int",
         "min": 1, "max": 60, "hot": True, "desc": "探测插件 Web 是否就绪的超时（秒）"},
        {"key": "PLUGIN_MAX_IMAGE_MB", "label": "插件回图上限", "type": "int",
         "min": 1, "max": 50, "hot": True, "desc": "单个插件单条指令回图上限（MB）"},
        {"key": "PLUGIN_STORE_ENABLED", "label": "插件商店", "type": "bool", "hot": True,
         "desc": "在插件页显示「插件商店」子选项（从插件源拉列表并一键安装）"},
        {"key": "PLUGIN_STORE_URL", "label": "插件源地址", "type": "text", "hot": True,
         "maxlen": 200, "desc": "插件源服务器地址", "note": "末尾不用带斜杠；改完刷新插件页即可"},
        {"key": "PLUGIN_STORE_TIMEOUT", "label": "插件源超时", "type": "int",
         "min": 2, "max": 120, "hot": True,
         "desc": "拉列表 / 测速的单次请求超时（秒）", "note": "测速也用它，太大会等很久"},
        {"key": "PLUGIN_STORE_TTL", "label": "列表缓存", "type": "int",
         "min": 0, "max": 3600, "hot": True, "desc": "插件列表缓存秒数，0 = 每次都重新拉"},
        {"key": "PLUGIN_GIT_BIN", "label": "git 路径", "type": "text", "hot": True,
         "maxlen": 260, "desc": "git 可执行文件", "note": "不在 PATH 里时填绝对路径，例如 C:\\Program Files\\Git\\cmd\\git.exe"},
        {"key": "PLUGIN_GIT_TIMEOUT", "label": "clone 超时", "type": "int",
         "min": 10, "max": 1800, "hot": True, "desc": "安装插件的 git clone 超时（秒）"},
        {"key": "PLUGIN_GIT_DEPTH", "label": "clone 深度", "type": "int",
         "min": 1, "max": 100, "hot": True,
         "desc": "只拉最近几次提交，1 = 最快", "note": "改成 1 以上会明显变慢"},
        {"key": "PLUGIN_GIT_TEST_REPO", "label": "测速用仓库", "type": "text", "hot": True,
         "maxlen": 260, "desc": "「测速」默认拿这个仓库跑各加速地址"},
        {"key": "PLUGIN_GIT_PROXIES", "label": "GitHub 加速地址", "type": "text", "hot": True,
         "maxlen": 4000, "desc": "前缀式地址，逗号或换行分隔；「原 GitHub（直连）」无需写进来",
         "note": "支持「名称|地址」自定义显示名，例如 我的代理|https://gh.example.com/"},
    ]),
    ("Meme 素材", [
        {"key": "MEME_ASSET_DIR", "label": "素材目录", "type": "path", "hot": False,
         "clearable": True,
         "desc": "留空 = 引擎包内 memes/（推荐留空）",
         "note": "引擎只从包内 memes/ 读图，改成别处需同步改引擎读取路径；改完需重启"},
        {"key": "MEME_RESOURCE_BASE", "label": "素材镜像前缀", "type": "text", "hot": True,
         "maxlen": 200, "desc": "留空 = 使用引擎自带镜像；末尾需带 / 或 @",
         "note": "内网/自建镜像时填，例如 https://cdn.example.com/meme/"},
    ]),
    ("其他", [
        {"key": "CACHE_EXPIRE_DAYS", "label": "缓存保留天数", "type": "int",
         "min": 1, "max": 3650, "hot": True, "desc": "超过天数的图片缓存会被清理"},
        {"key": "CANVAS_WIDTH", "label": "配对卡画布宽", "type": "int",
         "min": 200, "max": 4000, "hot": True, "desc": "配对卡输出宽度"},
        {"key": "CANVAS_HEIGHT", "label": "配对卡画布高", "type": "int",
         "min": 200, "max": 4000, "hot": True, "desc": "配对卡输出高度"},
        {"key": "BG_API_URL", "label": "随机背景接口", "type": "text", "hot": True,
         "desc": "随机背景图 API 地址"},
        {"key": "BG_FETCH_TIMEOUT", "label": "取图超时", "type": "int",
         "min": 1, "max": 120, "hot": True, "desc": "请求背景图 API 的超时（秒）"},
    ]),
]

# 少数键的「.env 键名」与「模块属性名」不一致（历史原因，保持向后兼容）
_ATTR_ALIAS = {
    "CANVAS_WIDTH": "CANVAS_W",
    "CANVAS_HEIGHT": "CANVAS_H",
    "BG_API_URL": "BG_API",
}


def _schema_value(item):
    """取某项的当前值（供表单回显；敏感项返回空字符串，不回显原值）。"""
    if item.get("sensitive"):
        return ""
    attr = _ATTR_ALIAS.get(item["key"], item["key"])
    val = globals().get(attr)
    if val is None:
        val = os.environ.get(item["key"], "")
    if isinstance(val, bool):
        return "true" if val else "false"
    return "" if val is None else str(val)


def env_schema():
    """分组返回全部可编辑项（含当前值 / 控件类型 / 是否热生效）。"""
    groups = []
    for name, items in ENV_SCHEMA:
        cur = []
        for it in items:
            d = dict(it)
            d["value"] = _schema_value(it)
            d["sensitive"] = bool(it.get("sensitive"))
            d["hot"] = bool(it.get("hot"))
            d["options"] = [list(o) for o in it.get("options", [])]
            # 该键被系统环境变量接管：写 .env 也改不动它
            d["locked"] = it["key"] in _SYS_ENV_KEYS
            d["configured"] = bool(os.environ.get(it["key"], ""))
            cur.append(d)
        groups.append({"name": name, "items": cur})
    return groups


def env_keys():
    """全部可编辑键名（用于校验 + 快速判断）。"""
    return {it["key"] for _n, items in ENV_SCHEMA for it in items}


# ----------------------------------------------------------------------------
# 写回 .env + 热重载
# ----------------------------------------------------------------------------
def _env_quote(v):
    """把值序列化成 .env 里的字面量（必要时加双引号并转义）。"""
    s = "" if v is None else str(v)
    if s == "":
        return ""
    if (any(c in s for c in ('"', "\n", "\r", "\t")) or s != s.strip()
            or " #" in s or s.startswith("#")):
        return ('"' + s.replace("\\", "\\\\").replace('"', '\\"')
                 .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"')
    return s


def _coerce(item, raw):
    """按元数据校验并规范化单个值，返回写入 .env 的字符串；不合法抛 ValueError。"""
    typ = item["type"]
    key = item["key"]

    if typ == "secret":
        # 敏感项：留空 = 不修改（除非该项允许清空）
        if raw is None or str(raw) == "":
            if item.get("clearable"):
                return ""
            raise ValueError("留空即不修改，无需提交")
        return str(raw).strip()

    s = "" if raw is None else str(raw).strip()

    if typ == "bool":
        low = s.lower()
        if low in _TRUTHY:
            return "true"
        if low in _FALSY:
            return "false"
        raise ValueError("只能是 true / false")

    if typ == "select":
        opts = [str(o[0]) for o in item.get("options", [])]
        low = s.lower()
        hit = next((o for o in opts if o.lower() == low), None)
        if hit is None:
            raise ValueError("只能是 %s" % " / ".join(opts))
        return hit

    if typ == "int":
        if s == "":
            raise ValueError("不能为空")
        try:
            n = int(float(s))
        except (TypeError, ValueError):
            raise ValueError("需要整数")
        return str(_clamp(item, n, key, int, True))

    if typ == "float":
        if s == "":
            raise ValueError("不能为空")
        try:
            f = float(s)
        except (TypeError, ValueError):
            raise ValueError("需要数字")
        return str(_clamp(item, f, key, float, True))

    if typ == "text":
        m = item.get("maxlen")
        if m and len(s) > m:
            raise ValueError("最长 %d 个字符" % m)
        return s

    # path / 其他：原样返回（空字符串 = 用默认目录）
    return s


def _clamp(item, num, key, cast, strict):
    lo, hi = item.get("min"), item.get("max")
    if lo is not None and num < lo:
        if strict:
            raise ValueError("不能小于 %s" % lo)
        return cast(lo)
    if hi is not None and num > hi:
        if strict:
            raise ValueError("不能大于 %s" % hi)
        return cast(hi)
    return num


def _write_env_file(updates, path=ENV_FILE):
    """按行改写 .env（保留原有注释与顺序），缺失的键追加到文件末尾。"""
    existed = os.path.isfile(path)
    lines = []
    if existed:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        except Exception:
            lines = []

    where, prefix = {}, {}
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        pre = "export " if s.lower().startswith("export ") else ""
        body = s[7:].strip() if pre else s
        k = body.split("=", 1)[0].strip()
        if k and k not in where and _KEY_RE.match(k):
            where[k] = i
            prefix[k] = pre

    tail = []
    for k in sorted(updates):
        line = "%s%s=%s" % (prefix.get(k, ""), k, _env_quote(updates[k]))
        if k in where:
            lines[where[k]] = line
        else:
            tail.append(line)
    if tail:
        if lines and lines[-1].strip():
            lines.append("")
        if not existed:
            lines = ["# 由 WebUI「设置」页生成 / 维护", ""] + lines
        lines.extend(tail)

    text = "\n".join(lines).rstrip("\n") + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


if "_RELOAD_HOOKS" not in globals():
    _RELOAD_HOOKS = []


def on_reload(fn):
    """注册热重载回调：apply_updates() 写完 .env 后会调用 fn(changed_keys)。

    app.py 用它把 import 时固化的模块级常量（目录、画布尺寸…）重新算一遍。
    """
    if callable(fn) and fn not in _RELOAD_HOOKS:
        _RELOAD_HOOKS.append(fn)
    return fn


def apply_updates(updates):
    """把 {KEY: 值} 写回 .env 并热重载。

    返回 {"ok": True, "updated": [...], "hot": [...], "restart": [...],
          "locked": [...], "env_file": ..., "env_file_exists": ...}
    或   {"ok": False, "error": "..."}
    """
    if not isinstance(updates, dict) or not updates:
        return {"ok": False, "error": "没有需要保存的配置项"}

    meta = {it["key"]: it for _n, items in ENV_SCHEMA for it in items}

    clean = {}
    for key, raw in updates.items():
        item = meta.get(key)
        if item is None:
            return {"ok": False, "error": "未知配置项：%s" % key}
        try:
            clean[key] = _coerce(item, raw)
        except ValueError as e:
            return {"ok": False, "error": "%s：%s" % (item.get("label") or key, e)}
        if clean[key] == "" and item["type"] in ("int", "float"):
            return {"ok": False, "error": "%s：不能为空" % (item.get("label") or key)}

    # 值为空且不允许清空的项 → 视为「不修改」
    clean = {k: v for k, v in clean.items()
             if not (v == "" and not meta[k].get("clearable"))}
    if not clean:
        return {"ok": False, "error": "没有检测到改动"}

    try:
        _write_env_file(clean)
    except Exception as e:
        return {"ok": False, "error": "写入 .env 失败：%s" % e}

    # 立即作用到当前进程（被系统环境变量接管的键不动，避免重启后又被覆盖）
    locked = [k for k in clean if k in _SYS_ENV_KEYS]
    for k, v in clean.items():
        if k not in _SYS_ENV_KEYS:
            os.environ[k] = v

    # 重算本模块的全部常量与派生值（WEB_MAX_UPLOAD_BYTES / CACHE_EXPIRE_SECONDS ...）
    importlib.reload(sys.modules[__name__])

    hooks_failed = []
    changed = sorted(clean)
    for fn in list(_RELOAD_HOOKS):
        try:
            try:
                fn(changed)
            except TypeError:
                # 兼容只声明了 0 个参数的回调
                fn()
        except Exception as e:
            hooks_failed.append("%s: %s" % (getattr(fn, "__name__", "hook"), e))

    hot = sorted(k for k in clean if meta[k].get("hot"))
    restart = sorted(k for k in clean if not meta[k].get("hot"))
    result = {
        "ok": True,
        "updated": sorted(clean),
        "hot": hot,
        "restart": restart,
        "locked": locked,
        "env_file": ENV_FILE,
        "env_file_exists": os.path.isfile(ENV_FILE),
    }
    if hooks_failed:
        result["warnings"] = hooks_failed
    return result


def startup_log_lines():
    """启动时打印的配置摘要（已脱敏）。"""
    lines = [
        "配置来源：%s%s" % (ENV_FILE, "" if ENV_FILE_EXISTS else "（不存在，全部使用内置默认值）"),
        "  WebUI   http://%s:%s" % (WEB_HOST, WEB_PORT),
        "  WS 服务器 ws://%s:%s%s  [%s]" % (
            WS_HOST, WS_PORT, WS_PATH,
            "由 .env 接管" if WS_ENV_LOCKED else "面板可覆盖(ws_config.json)"),
    ]
    return lines

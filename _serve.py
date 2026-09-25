# -*- coding: utf-8 -*-
"""生产式启动入口：监听参数全部来自 .env（WEB_HOST / WEB_PORT / WEB_THREADED）。

用法：
    .venv\\Scripts\\python.exe _serve.py
"""
import os
import sys

# 模块脚本都在 core/ 里：先把 core/ 加进模块搜索路径，再导入。
_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(_HERE, 'core')
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import config

import app as _app


def main():
    print('=' * 56, flush=True)
    for line in config.startup_log_lines():
        print(line, flush=True)
    print('=' * 56, flush=True)
    # threaded=True：每个请求独立线程，避免背景图等慢请求串行阻塞登录/其他接口
    _app.app.run(debug=config.WEB_DEBUG, host=config.WEB_HOST,
                 port=config.WEB_PORT, threaded=config.WEB_THREADED,
                 use_reloader=False)


if __name__ == '__main__':
    main()

"""接口调用统计（内存态）。

记录每次 API 调用（/api/* 与 /v1/*）的次数、成功/失败、平均耗时与最近调用，
供管理后台「接口调用统计」专栏展示。仅在内存维护，重启服务即清零。
"""
import collections
import threading
import time

_lock = threading.Lock()
_START = time.time()

_total = 0          # 所有 HTTP 请求数（含页面/静态资源）
_api_total = 0      # 接口调用数（/api/* 与 /v1/*）
_by_route = {}      # route -> {count, ok, fail, total_ms}
_recent = collections.deque(maxlen=20)  # 最近 N 条接口调用


def record(method, path, status, ms, is_api):
    global _total, _api_total
    with _lock:
        _total += 1
        if not is_api:
            return
        # 状态检查轮询不计入接口调用统计，避免污染真实调用数据
        if path.split('?')[0] == '/api/status':
            return
        _api_total += 1
        b = _by_route.setdefault(path, {'count': 0, 'ok': 0, 'fail': 0, 'total_ms': 0})
        b['count'] += 1
        b['total_ms'] += ms
        if status < 400:
            b['ok'] += 1
        else:
            b['fail'] += 1
        _recent.appendleft({
            'ts': time.strftime('%H:%M:%S'),
            'method': method,
            'route': path,
            'status': status,
            'ms': round(ms, 1),
        })


def snapshot():
    with _lock:
        uptime = int(time.time() - _START)
        routes = []
        ok_total = 0
        for k, v in _by_route.items():
            routes.append({
                'route': k,
                'count': v['count'],
                'ok': v['ok'],
                'fail': v['fail'],
                'avg_ms': round(v['total_ms'] / v['count'], 1) if v['count'] else 0,
            })
            ok_total += v['ok']
        routes.sort(key=lambda r: -r['count'])
        total_counted = sum(r['count'] for r in routes)
        return {
            'total_requests': _total,
            'api_total': _api_total,
            'uptime_sec': uptime,
            'rate_per_sec': round(_api_total / uptime, 2) if uptime else 0,
            'success_rate': round(100 * ok_total / total_counted, 1) if total_counted else 0,
            'by_route': routes,
            'recent': list(_recent),
        }
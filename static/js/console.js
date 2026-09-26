/* console.js
 * 单页控制台：状态检查 + 接口统计 + 接口测试 + API Key 管理
 * 网页端免登录（admin 端点已公开），/v1 接口 Bearer 鉴权保持不变。
 * 视图切换由 meme.js 处理 active；本文件监听 tab 切换做惰性加载。
 */
(function () {
    'use strict';

    var loaded = { status: false, keys: false };

    // ---------- 工具 ----------
    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }
    function secTo(sec) {
        if (sec === undefined || sec === null) return '—';
        if (sec < 60) return Math.floor(sec) + ' 秒';
        if (sec < 3600) return (sec / 60).toFixed(1) + ' 分钟';
        return (sec / 3600).toFixed(1) + ' 小时';
    }
    function badge(ok, txt) {
        return '<span class="' + (ok ? 'badge-ok' : 'badge-err') + '">' + esc(txt || (ok ? '正常' : '异常')) + '</span>';
    }
    function skeletonCard(count, wide) {
        var w = wide ? 'style="grid-column:1/-1"' : '';
        var h = '<div class="status-card" ' + w + '><h3><span class="skeleton-bar sb-hint" style="margin:0"></span></h3>';
        for (var i = 0; i < count; i++) {
            h += '<div class="loading-line"><div class="spinner sm"></div><div class="skeleton-bar sb-title" style="flex:1;margin:0"></div></div>';
        }
        h += '</div>';
        return h;
    }

    // ---------- 状态检查 ----------
    function loadStatus() {
        var c = document.getElementById('statusBlock');
        c.innerHTML = '<div class="status-grid">'
            + skeletonCard(6) + skeletonCard(4) + skeletonCard(2)
            + skeletonCard(2) + skeletonCard(3) + skeletonCard(3)
            + '</div>';
        fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
            if (d && d.ok === false) { throw new Error(d.error || '状态异常'); }
            renderStatus(d);
        }).catch(function (e) { c.innerHTML = '<p class="console-empty">获取失败：' + esc(e.message) + '</p>'; });
    }

    function renderStatus(d) {
        var s = d.server || {}, m = d.meme || {}, c = d.cache || {}, qq = d.qq_api || {};
        var dirs = Array.isArray(d.dirs) ? d.dirs : [];
        var fontFiles = d.fonts && Array.isArray(d.fonts.files) ? d.fonts.files : [];
        var now = d.datetime || s.started_at || '';
        var host = s.host || ('127.0.0.1:5000');
        var el = document.getElementById('statusBlock');
        var h = '<div class="status-grid">';

        h += '<div class="status-card"><h3>服务器</h3>';
        [['监听地址', 'host', host], ['Debug 模式', 'debug', s.debug ? '开' : '关'], ['Python', 'python', s.python],
         ['启动时间', 'started', s.started_at], ['运行时长', 'uptime', secTo(s.uptime_sec)], ['当前时间', 'now', now]].forEach(function (r) {
            h += '<div class="status-row"><span class="k">' + esc(r[0]) + '</span><span class="v" data-f="' + r[1] + '">' + esc(String(r[2] !== undefined ? r[2] : '—')) + '</span></div>';
        });
        h += '</div>';

        h += '<div class="status-card"><h3>Meme 服务</h3>';
        [['总表情数', 'meme_total', m.total], ['需/支持图片', 'meme_img', m.with_image], ['纯文字', 'meme_notxt', m.no_image],
         ['预览可用', 'meme_preview', m.preview_ok ? '是' : '否']].forEach(function (r) {
            h += '<div class="status-row"><span class="k">' + esc(r[0]) + '</span><span class="v" data-f="' + r[1] + '">' + esc(String(r[2] !== undefined ? r[2] : '—')) + '</span></div>';
        });
        if (m.error) h += '<div class="status-row"><span class="k">错误</span><span class="v">' + esc(m.error) + '</span></div>';
        h += '</div>';

        h += '<div class="status-card"><h3>缓存</h3>';
        [['文件数', 'cache_count', c.count], ['大小', 'cache_kb', c.size_kb ? c.size_kb.toFixed(1) + ' KB' : '—']].forEach(function (r) {
            h += '<div class="status-row"><span class="k">' + esc(r[0]) + '</span><span class="v" data-f="' + r[1] + '">' + esc(String(r[2])) + '</span></div>';
        });
        if (c.error) h += '<div class="status-row"><span class="k">错误</span><span class="v">' + esc(c.error) + '</span></div>';
        h += '</div>';

        h += '<div class="status-card"><h3>QQ 接口</h3>';
        h += '<div class="status-row"><span class="k">连通性</span><span class="v" data-f="qq_reach">' + badge(qq.reachable, qq.reachable ? '可达' : '不可达') + '</span></div>';
        h += '<div class="status-row"><span class="k">HTTP 状态</span><span class="v" data-f="qq_http">' + esc(qq.http !== undefined ? String(qq.http) : '—') + '</span></div>';
        if (qq.error) h += '<div class="status-row"><span class="k">错误</span><span class="v">' + esc(qq.error) + '</span></div>';
        h += '</div>';

        h += '<div class="status-card"><h3>目录权限</h3>';
        if (!dirs.length) {
            h += '<div class="status-row"><span class="k">无数据</span><span class="v">-</span></div>';
        } else {
            dirs.forEach(function (v) {
                if (!v) return;
                h += '<div class="status-row"><span class="k">' + esc(v.name || '') + '</span><span class="v" data-f="dir:' + (v.name || '') + '">' + (v.exists ? badge(v.writable, '可写') : badge(false, '不存在')) + '</span></div>';
            });
        }
        h += '</div>';

        var eg = (d.fonts && d.fonts.engine) || {};
        h += '<div class="status-card"><h3>字体 (' + fontFiles.length + ')</h3>';
        h += '<div class="status-row"><span class="k">表情合成 · 中文字形</span><span class="v" data-f="font_cjk">' +
             (eg.error ? '未能探测' : (eg.cjk_ok ? esc(eg.cjk_family || '可用') : '缺失')) + '</span></div>';
        h += '<div class="status-row"><span class="k">表情合成 · 拉丁字形</span><span class="v" data-f="font_latin">' +
             (eg.latin_ok ? '可用' : '缺失') + '</span></div>';
        h += '<div class="status-row"><span class="k">项目字体（配对卡/名言图）</span><span class="v" data-f="font_proj">' +
             fontFiles.length + ' 个</span></div>';
        if (!fontFiles.length) {
            h += '<div class="status-row"><span class="k">无可用字体</span><span class="v">-</span></div>';
        } else {
            fontFiles.forEach(function (f) { h += '<div class="status-row"><span class="k">' + esc(f) + '</span><span class="v">✓</span></div>'; });
        }
        if (d.fonts && d.fonts.hint) h += '<div class="status-row"><span class="k">提示</span><span class="v">' + esc(d.fonts.hint) + '</span></div>';
        h += '</div></div>';

        el.innerHTML = h;
        // 记录运行时长起点，供本地秒针每秒校正（不闪烁）
        var u = el.querySelector('[data-f="uptime"]');
        if (u) { u.dataset.sbase = String(s.uptime_sec || '0'); u.dataset.st = String(Date.now()); }
    }

    // ---------- 接口统计 ----------
    function loadUsage() {
        var el = document.getElementById('usageBlock');
        el.innerHTML = '<div class="status-grid">' + skeletonCard(1, true) + '</div>';
        fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
            if (d && d.ok === false) { throw new Error(d.error || '状态异常'); }
            el.innerHTML = renderUsage(d.usage || {});
        }).catch(function (e) { el.innerHTML = '<p class="console-empty">获取失败：' + esc(e.message) + '</p>'; });
    }

    function renderUsage(u) {
        var routes = u.by_route || [], recent = u.recent || [];
        var maxCount = routes.length ? routes[0].count : 0;
        var h = '<div class="status-card usage-card"><h3>接口调用统计</h3>';
        h += '<div class="usage-overview">';
        [['接口调用', 'api_total', u.api_total || 0], ['成功率', 'success', u.success_rate !== undefined ? u.success_rate + '%' : '—'],
         ['平均速率', 'rate', u.rate_per_sec !== undefined ? u.rate_per_sec + '/s' : '—'], ['运行时长', 'uptime', secTo(u.uptime_sec)]].forEach(function (mm) {
            h += '<div class="usage-metric"><div class="num" data-m="' + mm[1] + '">' + esc(String(mm[2])) + '</div><div class="lab">' + mm[0] + '</div></div>';
        });
        h += '</div>';

        h += '<div class="usage-cols">';
        h += '<div class="usage-block"><h4>按接口排行</h4>';
        if (!routes.length) {
            h += '<div class="empty-state" style="padding:16px">暂无接口调用</div>';
        } else {
            h += '<table class="usage-table"><thead><tr><th>接口</th><th>调用</th><th>成功</th><th>失败</th><th>成功率</th><th>平均耗时</th></tr></thead><tbody>';
            routes.forEach(function (r) {
                var pct = Math.round(100 * r.count / maxCount);
                var sr = r.count ? (100 * r.ok / r.count).toFixed(0) : '0';
                h += '<tr><td class="route-cell" title="' + esc(r.route) + '">' + esc(r.route)
                    + '<span class="meter' + (r.fail === 0 ? ' ok' : '') + '" title="' + pct + '%"><span style="width:' + pct + '%"></span></span></td>'
                    + '<td class="count-cell">' + esc(String(r.count)) + '</td><td>' + esc(String(r.ok)) + '</td><td>'
                    + (r.fail ? '<span style="color:#c62828">' + esc(String(r.fail)) + '</span>' : '<span style="color:#8c8f9c">0</span>')
                    + '</td><td>' + sr + '%</td><td>' + (r.avg_ms !== undefined ? esc(String(r.avg_ms)) + 'ms' : '—') + '</td></tr>';
            });
            h += '</tbody></table>';
        }
        h += '</div>';
        h += '<div class="usage-block"><h4>最近调用</h4>';
        if (!recent.length) {
            h += '<div class="empty-state" style="padding:16px">暂无调用记录</div>';
        } else {
            h += '<div class="recent-list">';
            recent.forEach(function (r) {
                var cls = r.status < 400 ? 'good' : 'bad';
                h += '<div class="recent-item"><span class="rmethod">' + esc(r.method) + '</span><span class="rroute" title="' + esc(r.route) + '">' + esc(r.route) + '</span><span>' + esc(String(r.ms)) + 'ms</span><span class="rstatus ' + cls + '">' + esc(String(r.status)) + '</span></div>';
            });
            h += '</div>';
        }
        h += '</div></div></div>';
        // 记录接口统计运行时长起点，供秒针本地每秒递增（不闪烁）
        window._usageUptimeStart = Date.now();
        window._usageUptimeBase = u.uptime_sec || 0;
        return h;
    }

    // ---------- 接口测试 ----------
    var ENDPOINTS = [];
    function methodClass(m) { var c = m.toUpperCase(); if (c === 'GET') return 'meth-GET'; if (c === 'POST') return 'meth-POST'; if (c === 'PUT') return 'meth-PUT'; if (c === 'DELETE') return 'meth-DELETE'; return 'meth-GET'; }

    function loadEndpoints() {
        var box = document.getElementById('endpointsBlock');
        fetch('/admin/api/endpoints').then(function (r) { return r.json(); }).then(function (d) {
            ENDPOINTS = d.endpoints || [];
            renderEndpoints();
        }).catch(function () { box.innerHTML = '<p class="console-empty">加载失败</p>'; });
    }

    function renderEndpoints() {
        var box = document.getElementById('endpointsBlock');
        if (!ENDPOINTS.length) { box.innerHTML = '<p class="console-empty">暂无接口</p>'; return; }
        var h = '<div class="ep-list">';
        ENDPOINTS.forEach(function (ep, i) {
            var m = ep.method.toUpperCase();
            h += '<div class="ep-card" id="ep-' + i + '"><div class="ep-head" onclick="toggleEp(' + i + ')">'
                + '<span class="ep-method ' + methodClass(m) + '">' + esc(m) + '</span>'
                + '<span class="ep-path">' + esc(ep.path) + '</span>'
                + '<span class="ep-sum">' + esc(ep.summary || '') + '</span>'
                + '<span class="ep-arrow">▾</span></div>';
            h += '<div class="ep-body">';
            if (ep.needKey) {
                h += '<div class="ep-field-label">Authorization: Bearer (粘贴 /v1 Key)</div><input class="ep-input" id="k-' + i + '" placeholder="sk-..." style="font-weight:normal">';
            }
            if (m === 'POST') {
                h += '<div class="ep-field-label">请求体 JSON</div>'
                    + '<textarea class="ep-input" id="b-' + i + '" rows="' + Math.max(3, (JSON.stringify(ep.body || {}).length / 40) + 1) + '">' + esc(JSON.stringify(ep.body || {}, null, 2)) + '</textarea>';
                if (ep.needFile) {
                    h += '<div class="ep-field-label">上传图片（自动写入 image 字段，base64）</div><input type="file" accept="image/*" id="f-' + i + '" onchange="onEpFile(' + i + ',this)">';
                }
            } else {
                h += '<div class="ep-field-label">Query 参数（' + (ep.needKey ? '需 Bearer' : '无需鉴权') + '）</div>'
                    + '<div class="ep-queryline"><span>?</span><input class="ep-input" id="q-' + i + '" value="' + esc(ep.query || '') + '" placeholder="key=value&..."></div>';
            }
            h += '<div class="ep-actions"><button class="ep-run" onclick="runEp(' + i + ')">测试调用</button><span class="pipe-hint" id="st-' + i + '"></span></div>';
            h += '<div id="r-' + i + '"></div>';
            h += '</div></div>';
        });
        h += '</div>';
        box.innerHTML = h;
    }

    window.toggleEp = function (i) { document.getElementById('ep-' + i).classList.toggle('open'); };

    window.onEpFile = function (i, input) {
        var f = input.files && input.files[0]; if (!f) return;
        var reader = new FileReader();
        reader.onload = function (e) {
            var body = document.getElementById('b-' + i);
            var obj = {};
            try { obj = JSON.parse(body.value || '{}'); } catch (err) { obj = {}; }
            obj.image = e.target.result;
            body.value = JSON.stringify(obj, null, 2);
        };
        reader.readAsDataURL(f);
    };

    window.runEp = function (i) {
        var ep = ENDPOINTS[i];
        var st = document.getElementById('st-' + i), rbox = document.getElementById('r-' + i);
        var headers = {};
        if (ep.needKey) {
            var k = document.getElementById('k-' + i).value.trim();
            if (k) headers['Authorization'] = 'Bearer ' + k;
        }
        var url = ep.path, opts = { method: ep.method, headers: headers }, t0 = Date.now();
        if (ep.method === 'POST') {
            var bodyText = document.getElementById('b-' + i).value.trim();
            headers['Content-Type'] = 'application/json';
            opts.body = bodyText ? bodyText : '{}';
        } else {
            var q = document.getElementById('q-' + i).value.trim().replace(/^[?#]/, '');
            if (q) url += '?' + q;
        }
        st.textContent = '请求中...'; st.className = 'pipe-hint running';
        rbox.innerHTML = '<div class="loading-line"><div class="spinner sm"></div><span style="color:#8c8f9c;font-size:12px">调用中...</span></div>';
        fetch(url, opts).then(function (resp) {
            var ct = resp.headers.get('Content-Type') || '';
            return Promise.all([Promise.resolve(resp), Promise.resolve(ct), resp.blob()]);
        }).then(function (arr) {
            var resp = arr[0], ct = arr[1], blob = arr[2];
            var ms = Date.now() - t0;
            st.textContent = 'HTTP ' + resp.status + ' · ' + ms + 'ms';
            st.className = resp.status < 400 ? 'pipe-hint good' : 'pipe-hint bad';
            if (ct.indexOf('image/') === 0) {
                var ourl = URL.createObjectURL(blob);
                rbox.innerHTML = '<div class="ep-result" style="padding:8px"><img src="' + ourl + '" style="max-width:320px;border-radius:12px;border:1px solid #eef0f4"></div>';
            } else {
                return blob.text().then(function (txt) {
                    var pretty = txt;
                    try { pretty = JSON.stringify(JSON.parse(txt), null, 2); } catch (e) { pretty = txt.slice(0, 3000); }
                    rbox.innerHTML = '<pre class="ep-result">' + esc(pretty) + '</pre>';
                });
            }
        }).catch(function (e) {
            st.textContent = '请求失败'; st.className = 'pipe-hint bad';
            rbox.innerHTML = '<pre class="ep-result">' + esc(String(e.message || e)) + '</pre>';
        });
    };

    // ---------- 静默轮询（实时刷新，不重绘骨架屏） ----------
    function upField(k, d) {
        var s = d.server || {}, c = d.cache || {}, qq = d.qq_api || {}, m = d.meme || {};
        if (k === 'host') return { s: s.host || '127.0.0.1:5000' };
        if (k === 'debug') return { s: s.debug ? '开' : '关' };
        if (k === 'python') return { s: s.python == null ? '—' : String(s.python) };
        if (k === 'started') return { s: s.started_at == null ? '—' : String(s.started_at) };
        if (k === 'now') return { s: d.datetime || s.started_at || '' };
        if (k === 'meme_total') return { s: String(m.total == null ? '—' : m.total) };
        if (k === 'meme_img') return { s: String(m.with_image == null ? '—' : m.with_image) };
        if (k === 'meme_notxt') return { s: String(m.no_image == null ? '—' : m.no_image) };
        if (k === 'meme_preview') return { s: m.preview_ok ? '是' : '否' };
        if (k === 'cache_count') return { s: String(c.count == null ? '—' : c.count) };
        if (k === 'cache_kb') return { s: c.size_kb ? c.size_kb.toFixed(1) + ' KB' : '—' };
        if (k === 'qq_reach') return { s: (qq.reachable ? '可达' : '不可达'), c: (qq.reachable ? 'badge-ok' : 'badge-err') };
        if (k === 'qq_http') return { s: qq.http != null ? String(qq.http) : '—' };
        if (k.indexOf('dir:') === 0) {
            var v = null, i;
            for (i = 0; i < (d.dirs || []).length; i++) { if (d.dirs[i] && d.dirs[i].name === k.slice(4)) { v = d.dirs[i]; break; } }
            if (!v) return null;
            if (!v.exists) return { s: '不存在', c: 'badge-err' };
            return { s: v.writable ? '可写' : '不可写', c: v.writable ? 'badge-ok' : 'badge-err' };
        }
        return null;
    }
    function applyStatus(d) {
        var el = document.getElementById('statusBlock');
        var nodes = el.querySelectorAll('[data-f]');
        var i, n, val, k;
        for (i = 0; i < nodes.length; i++) {
            n = nodes[i]; k = n.dataset.f;
            if (k === 'uptime') continue; // 由秒针本地更新，避免每 3s 重排
            val = upField(k, d);
            if (!val) continue;
            if (n.textContent !== val.s) n.textContent = val.s;
            if (val.c && n.className.indexOf(val.c) !== 0) n.className = val.c;
        }
        var u = el.querySelector('[data-f="uptime"]');
        if (u) { u.dataset.sbase = String(((d.server || {}).uptime_sec) || '0'); u.dataset.st = String(Date.now()); }
    }
    function tickUptime() {
        var u = document.querySelector('#statusBlock [data-f="uptime"]');
        if (!u) return;
        var base = parseFloat(u.dataset.sbase || '0'); var st = parseFloat(u.dataset.st || Date.now());
        var sec = base + Math.max(0, (Date.now() - st) / 1000);
        var t = secTo(sec);
        if (u.textContent !== t) u.textContent = t;
    }
    function pollStatus() {
        fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
            if (d && d.ok === false) throw new Error(d.error || '状态异常');
            applyStatus(d);
        }).catch(function () { /* 静默，保留上次数据 */ });
    }
    function pollUsage() {
        fetch('/api/status').then(function (r) { return r.json(); }).then(function (d) {
            if (d && d.ok === false) return;
            applyUsage(d);
        }).catch(function () { /* 静默，保留上次数据 */ });
    }

        // ---------- 接口统计增量更新（避免整块重绘跳动） ----------
    function applyUsage(d) {
        var u = d.usage || {}, el = document.getElementById('usageBlock');
        // 更新顶部指标
        var nmap = {
            api_total: String(u.api_total || 0),
            success: (u.success_rate !== undefined ? u.success_rate + '%' : '—'),
            rate: (u.rate_per_sec !== undefined ? u.rate_per_sec + '/s' : '—'),
        };
        for (var k in nmap) {
            var nn = el.querySelector('[data-m="' + k + '"]');
            if (nn && nn.textContent !== nmap[k]) nn.textContent = nmap[k];
        }
        // 若最近调用列表或排行和上次不一致，才整块重刷表格+最近
        // 简单策略：每 3 轮只刷一次表格（因真实调用低频，这块极少改变）
        var lastRoutes = window._usageLastRoutes || 0;
        var cnt = u.by_route ? u.by_route.length : 0;
        if (cnt !== lastRoutes) {
            // 重新渲染整个 usage 区域
            el.innerHTML = renderUsage(u);
            window._usageLastRoutes = cnt;
        }
        // 更新运行时长节点由 tick 负责
    }
    function tickUptimeUsage() {
        var uel = document.querySelector('#usageBlock [data-m="uptime"]');
        if (!uel) return;
        // 起点来自 service uptime_sec，与 status 页秒针对齐
        // 计算本地增量，保证秒级跳动
        var sbase = (window._usageUptimeBase || 0);
        var t0 = (window._usageUptimeStart || Date.now());
        var sec = sbase + (Date.now() - t0) / 1000;
        var txt = secTo(sec);
        if (uel.textContent !== txt) uel.textContent = txt;
    }

    // ---------- API Key 管理 ----------
    function fmtTime(ts) {
        if (!ts) return '—';
        var d = new Date(ts * 1000);
        return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate() + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    }

    function loadKeys() {
        var c = document.getElementById('keysContent');
        c.innerHTML = '<p class="console-empty">加载中...</p>';
        fetch('/admin/api/keys').then(function (r) { return r.json(); }).then(function (d) {
            renderKeys(d.keys || []);
        }).catch(function () { c.innerHTML = '<p class="console-empty">获取失败</p>'; });
    }

    function renderKeys(keys) {
        var c = document.getElementById('keysContent');
        if (!keys.length) { c.innerHTML = '<p class="console-empty">暂无 API Key，点击上方「创建 Key」生成</p>'; return; }
        var h = '<table class="key-table"><thead><tr><th>名称</th><th>Key</th><th>状态</th><th>创建时间</th><th>最后使用</th><th>操作</th></tr></thead><tbody>';
        keys.forEach(function (k) {
            h += '<tr>';
            h += '<td>' + esc(k.name || '未命名') + '</td>';
            h += '<td class="key-cell" title="' + esc(k.key) + '">' + esc(k.key) + '</td>';
            h += '<td>' + (k.enabled ? '<span class="badge-ok">启用</span>' : '<span class="badge-err">禁用</span>') + '</td>';
            h += '<td>' + fmtTime(k.created) + '</td>';
            h += '<td>' + fmtTime(k.last_used) + '</td>';
            h += '<td><div class="key-actions">';
            h += '<button class="' + (k.enabled ? 'btn-toggle-off' : 'btn-toggle-on') + '" onclick="toggleKV(\'' + k.key + '\')">' + (k.enabled ? '禁用' : '启用') + '</button>';
            h += '<button class="btn-delete" onclick="deleteKV(\'' + k.key + '\')">删除</button>';
            h += '</div></td>';
            h += '</tr>';
        });
        h += '</tbody></table>';
        c.innerHTML = h;
    }

    // 原生 confirm() 在预览 / 内嵌 iframe 里会被静默拦截并直接返回 false，
    // 表现为「点了按钮没反应」。优先用 plugins.js 提供的页面内确认框，
    // 实在取不到（脚本没加载）才退回原生实现。
    function askConfirm(opts) {
        if (typeof window.uiConfirm === 'function') return window.uiConfirm(opts);
        return Promise.resolve(window.confirm(opts.text || '确定继续？'));
    }

    window.toggleKV = function (key) {
        fetch('/admin/api/keys/' + encodeURIComponent(key) + '/toggle', { method: 'POST' }).then(function (r) { return r.json(); }).then(function (d) {
            if (d.error) { alert(d.error); return; }
            loadKeys();
        });
    };

    window.deleteKV = function (key) {
        askConfirm({
            title: '删除 API Key',
            text: '确定删除此 API Key？此操作不可撤销。',
            tip: '删除后，正在使用该 Key 的调用会立刻失效',
            okText: '删除'
        }).then(function (yes) {
            if (!yes) return;
            fetch('/admin/api/keys/' + encodeURIComponent(key), { method: 'DELETE' }).then(function (r) { return r.json(); }).then(function (d) {
                if (d.error) { alert(d.error); return; }
                loadKeys();
            });
        });
    };

    // ---------- 惰性初始化（控制台各 Tab 独立加载） ----------
    var consoleLoaded = { status: false, usage: false, api: false, keys: false };
    function initStatus() { if (consoleLoaded.status) return; consoleLoaded.status = true; loadStatus(); }
    function initUsage() { if (consoleLoaded.usage) return; consoleLoaded.usage = true; loadUsage(); }
    function initApi() { if (consoleLoaded.api) return; consoleLoaded.api = true; loadEndpoints(); }
    function initKeys() { if (consoleLoaded.keys) return; consoleLoaded.keys = true; loadKeys(); }

    function bind() {
        if (document.getElementById('createKeyBtn')) {
            document.getElementById('createKeyBtn').addEventListener('click', function () {
                var name = document.getElementById('newKeyName').value.trim();
                fetch('/admin/api/keys', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name }) })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.error) { alert(d.error); return; }
                        document.getElementById('newKeyName').value = '';
                        var w = document.getElementById('newKeyWrap');
                        w.classList.remove('hidden');
                        w.innerHTML = '<div class="new-key-banner"><div class="label">新 Key 已创建（请立即复制保存）</div><div class="val">' + esc(d.key.key) + '</div><div class="hint">调用 /v1 接口时使用 Header：<code>Authorization: Bearer ' + esc(d.key.key) + '</code></div></div>';
                        loadKeys();
                    });
            });
            document.getElementById('refreshKeysBtn').addEventListener('click', loadKeys);
        }
        var sw = Array.prototype.slice.call(document.querySelectorAll('.view-switch'));
        var pollIv = null, upIv = null;
        function startPoll(fn, ms) { if (pollIv) clearInterval(pollIv); fn(); pollIv = setInterval(fn, ms); }
        function stopPoll() { if (pollIv) { clearInterval(pollIv); pollIv = null; } if (upIv) { clearInterval(upIv); upIv = null; } }
        sw.forEach(function (b) {
            b.addEventListener('click', function () {
                var t = b.getAttribute('data-view');
                if (t === 'status') { initStatus(); startPoll(pollStatus, 3000); if (upIv) clearInterval(upIv); upIv = setInterval(tickUptime, 1000); }
                else if (t === 'usage') { initUsage(); startPoll(pollUsage, 3000); if (upIv) clearInterval(upIv); upIv = setInterval(tickUptimeUsage, 1000); }
                else { stopPoll(); }
                if (t === 'api') initApi();
                if (t === 'keys') initKeys();
                if (t === 'settings' && window.BG && window.BG.initSettings) window.BG.initSettings();
            });
        });
        // 默认视图为 cards，不自动加载控制台
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();
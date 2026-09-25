/* ws.js
 * WS 服务器面板：OneBot V11（NapCat 反向 WebSocket）
 * 负责配置读写、启停控制、状态总览、连接列表、实时事件日志、接口调用测试。
 * 后端接口全部位于 /api/ws/*（app.py 转发到 ws_server.py）。
 * 本文件自带 tab 切换钩子，进入「WS 服务器」视图时开始轮询，离开即停止。
 */
(function () {
    'use strict';

    var POLL_MS = 2500;
    var inited = false;
    var cfgFilled = false;
    // 增量渲染状态：整块 innerHTML 重建会让动画与滚动位置反复重置，
    // 因此状态卡 / 客户端卡 / 事件日志都改按「行」就地更新。
    var lastEvtSig = '';          // '' = 需要整块重建（清空日志 / 切换原始 JSON 时置空）
    var lastEvtIds = {};          // 事件 id -> 已渲染的 DOM 行
    var lastCliSig = '';
    var lastCliIdSig = '';        // 客户端「身份」指纹：仅增删时触发入场动画
    var lastClientCount = null;   // 在线客户端数：变化时数字跳动
    var lastCliRows = {};         // 客户端 id -> 已渲染的 DOM 行
    var lastStatVals = {};        // 状态数值缓存：变化时高亮闪一下
    var lastStatStruct = '';      // 状态卡结构指纹：仅结构变化时重建骨架

    function $(id) { return document.getElementById(id); }

    function all(sel, root) {
        return Array.prototype.slice.call((root || document).querySelectorAll(sel));
    }

    function toggleAt(target, name, delay) {
        target.classList.remove(name);
        void target.offsetWidth;          // 强制重排，让动画可以重播
        target.classList.add(name);
        setTimeout(function () { target.classList.remove(name); }, delay || 600);
    }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function badge(ok, txt) {
        return '<span class="' + (ok ? 'badge-ok' : 'badge-err') + '">' + esc(txt || (ok ? '正常' : '异常')) + '</span>';
    }

    function secTo(sec) {
        if (sec === undefined || sec === null) return '—';
        sec = Number(sec);
        if (isNaN(sec)) return '—';
        if (sec < 60) return Math.floor(sec) + ' 秒';
        if (sec < 3600) return (sec / 60).toFixed(1) + ' 分钟';
        return (sec / 3600).toFixed(1) + ' 小时';
    }

    // 运行时长 / 保持时长用「秒级时钟」：每秒都在变，肉眼可见地实时跳动
    function secToLive(sec) {
        if (sec === undefined || sec === null) return '—';
        sec = Math.max(0, Math.floor(Number(sec)));
        if (isNaN(sec)) return '—';
        var d = Math.floor(sec / 86400);
        var h = Math.floor((sec % 86400) / 3600);
        var m = Math.floor((sec % 3600) / 60);
        var s = sec % 60;
        function p2(n) { return n < 10 ? '0' + n : '' + n; }
        var clock = (h < 10 ? '0' + h : '' + h) + ':' + p2(m) + ':' + p2(s);
        return d > 0 ? (d + ' 天 ' + clock) : clock;
    }

    function kb(n) {
        n = Number(n || 0);
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / 1024 / 1024).toFixed(2) + ' MB';
    }

    // 顶部提示条（复用 #wsLibWarn 容器），同内容不重复播动画
    var noticeTimer = null;
    var lastNotice = '';
    function notice(msg, kind) {
        var el = $('wsLibWarn');
        if (!el) return;
        if (!msg) {
            if (!lastNotice) return;
            lastNotice = '';
            if (noticeTimer) clearTimeout(noticeTimer);
            el.className = 'hidden';
            el.innerHTML = '';
            return;
        }
        var key = (kind || 'info') + '|' + msg;
        if (key === lastNotice) return;
        lastNotice = key;
        el.className = 'hidden';
        el.innerHTML = '';
        void el.offsetWidth;                              // 重排：让滑入动画重新播放
        el.className = 'ws-notice ' + (kind || 'info');
        el.innerHTML = esc(msg);
        if (noticeTimer) clearTimeout(noticeTimer);
        if (kind !== 'warn') {
            noticeTimer = setTimeout(function () { notice(''); }, 4000);
        }
    }

    function api(path, opts) {
        return fetch(path, opts).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
                if (!r.ok || d.ok === false) {
                    throw new Error(d.error || ('HTTP ' + r.status));
                }
                return d;
            });
        });
    }

    // ---------- 配置 ----------
    function fillConfig(cfg) {
        if (!cfg || cfgFilled) return;
        cfgFilled = true;
        if ($('wsHost')) $('wsHost').value = cfg.host || '0.0.0.0';
        if ($('wsPort')) $('wsPort').value = cfg.port == null ? 6700 : cfg.port;
        if ($('wsPath')) $('wsPath').value = cfg.path || '/onebot/v11/ws';
        if ($('wsToken')) $('wsToken').value = cfg.access_token || '';
        if ($('wsAutoStart')) $('wsAutoStart').checked = !!cfg.auto_start;
        updateAddrHint(cfg);
    }

    // NapCat 里应填写的地址提示（随 .env / 面板改动实时更新）
    function updateAddrHint(cfg) {
        var el = $('wsAddrHint');
        if (!el || !cfg) return;
        el.textContent = 'ws://<本机IP>:' + (cfg.port || 6700) + (cfg.path || '/onebot/v11/ws');
    }

    function loadConfig() {
        return api('/api/ws/config').then(function (d) {
            fillConfig(d.config);
        }).catch(function (e) {
            notice('配置读取失败：' + e.message, 'warn');
        });
    }

    function saveConfig() {
        var body = {
            host: ($('wsHost').value || '').trim() || '0.0.0.0',
            port: parseInt($('wsPort').value, 10),
            path: ($('wsPath').value || '').trim() || '/onebot/v11/ws',
            access_token: ($('wsToken').value || '').trim(),
            auto_start: !!$('wsAutoStart').checked
        };
        if (!body.port || body.port < 1 || body.port > 65535) {
            notice('端口不合法，应为 1-65535', 'warn');
            return Promise.resolve();
        }
        if (body.path.charAt(0) !== '/') body.path = '/' + body.path;
        var tip = $('wsSaveTip');
        tip.classList.add('on');
        tip.textContent = '保存中...';
        return api('/api/ws/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        }).then(function (d) {
            fillConfig(d.config);
            cfgFilled = true;
            if (d.restarted) {
                tip.textContent = '已保存并重启 ✓';
            } else if (d.restart_error) {
                tip.textContent = '已保存（重启失败）';
                notice('配置已保存，但重启失败：' + d.restart_error, 'warn');
            } else {
                tip.textContent = '已保存 ✓';
            }
            setTimeout(function () { tip.classList.remove('on'); }, 2600);
            pollWs();
        }).catch(function (e) {
            tip.classList.remove('on');
            notice('保存失败：' + e.message, 'warn');
        });
    }

    // ---------- 控制 ----------
    function ctrl(action) {
        var btn = $('ws' + action.charAt(0).toUpperCase() + action.slice(1) + 'Btn');
        var old = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = '处理中...'; }
        notice('');
        api('/api/ws/' + action, { method: 'POST' }).then(function () {
            notice('已' + ({ start: '启动', stop: '停止', restart: '重启' }[action] || action) + ' WS 服务器', 'info');
        }).catch(function (e) {
            notice('操作失败：' + e.message, 'warn');
        }).then(function () {
            if (btn) { btn.disabled = false; btn.textContent = old; }
            pollWs();
        });
    }

    // ---------- 状态渲染 ----------
    // 配置来源提示：.env 接管时禁用面板保存，避免「改了没生效」的困惑
    var _lastLocked = null;
    function renderCfgSource(d) {
        var box = $('wsCfgSource');
        if (!box) return;
        var locked = !!d.env_locked;
        box.style.display = '';
        box.className = 'ws-notice ' + (locked ? 'warn' : 'info');
        box.innerHTML = locked
            ? ('<b>配置来源：.env</b>（WS_CONFIG_PRIORITY=env）—— 面板保存已禁用，请直接编辑项目根目录的 .env 后重启服务。')
            : ('<b>配置来源：' + esc(d.config_source || 'ws_config.json') + '</b> —— ' +
               esc(d.config_note || '面板改动会保存到 ws_config.json') + '；.env 仅提供默认值。');
        if (_lastLocked === locked) return;
        _lastLocked = locked;
        ['wsHost', 'wsPort', 'wsPath', 'wsToken', 'wsAutoStart', 'wsSaveBtn'].forEach(function (id) {
            var el = $(id);
            if (!el) return;
            el.disabled = locked;
            if (el.tagName === 'INPUT') el.readOnly = locked && el.type !== 'checkbox';
        });
    }

    // 单个状态数值就地写入：值变化才动 DOM，并高亮闪一下
    function setStat(key, val, quiet) {
        var box = $('wsStatusBlock');
        if (!box) return;
        var n = box.querySelector('[data-f="' + key + '"]');
        if (!n) return;
        var v = String(val);
        if (n.textContent === v) return;
        n.textContent = v;
        var prev = lastStatVals[key];
        lastStatVals[key] = v;
        if (!quiet && prev !== undefined) toggleAt(n, 'ws-val-flash', 1050);
    }

    // 状态卡：骨架只建一次，之后逐行就地更新（不再整块 innerHTML 重渲染）
    function renderStatus(d) {
        var s = d.stats || {}, cl = d.clients || [];
        var running = !!d.running;
        renderCfgSource(d);
        updateAddrHint(d.config || {});
        var box = $('wsStatusBlock');
        if (!box) return;

        // 结构指纹：只有这些「会改变 DOM 结构」的字段变了才重建骨架
        var struct = [running ? 1 : 0, d.listen || '', d.started_at || '',
            d.has_lib ? 1 : 0, d.error || ''].join('|');
        if (struct !== lastStatStruct || !box.querySelector('.status-grid')) {
            lastStatStruct = struct;
            lastStatVals = {};
            var h = '<div class="status-grid">';

            h += '<div class="status-card"><h3>服务器</h3>';
            h += '<div class="status-row"><span class="k">运行状态</span><span class="v">' + badge(running, running ? '运行中' : '已停止') + '</span></div>';
            h += '<div class="status-row"><span class="k">监听地址</span><span class="v ws-mono" data-f="listen">' + esc(d.listen || '—') + '</span></div>';
            h += '<div class="status-row"><span class="k">启动时间</span><span class="v" data-f="started">' + esc(d.started_at || '—') + '</span></div>';
            h += '<div class="status-row"><span class="k">运行时长</span><span class="v ws-live" data-f="ws_uptime">' + (running ? secToLive(d.uptime_sec) : '—') + '</span></div>';
            h += '<div class="status-row"><span class="k">运行库</span><span class="v">' + (d.has_lib ? 'websockets' : badge(false, '未安装')) + '</span></div>';
            if (d.error) h += '<div class="status-row"><span class="k">错误</span><span class="v ws-err">' + esc(d.error) + '</span></div>';
            h += '</div>';

            h += '<div class="status-card"><h3>连接</h3>';
            h += '<div class="status-row"><span class="k">在线客户端</span><span class="v" data-f="cc">' + cl.length + '</span></div>';
            h += '<div class="status-row"><span class="k">累计连接</span><span class="v" data-f="total_conn">' + esc(s.total_conn || 0) + '</span></div>';
            h += '<div class="status-row"><span class="k">收到消息</span><span class="v" data-f="total_recv">' + esc(s.total_recv || 0) + '</span></div>';
            h += '<div class="status-row"><span class="k">发出消息</span><span class="v" data-f="total_sent">' + esc(s.total_sent || 0) + '</span></div>';
            h += '</div>';

            h += '<div class="status-card"><h3>事件 / 流量</h3>';
            h += '<div class="status-row"><span class="k">累计事件</span><span class="v" data-f="total_events">' + esc(s.total_events || 0) + '</span></div>';
            h += '<div class="status-row"><span class="k">接收流量</span><span class="v" data-f="bytes_in">' + esc(kb(s.bytes_in)) + '</span></div>';
            h += '<div class="status-row"><span class="k">发送流量</span><span class="v" data-f="bytes_out">' + esc(kb(s.bytes_out)) + '</span></div>';
            h += '</div>';

            h += '</div>';
            box.innerHTML = h;
            if (running) {
                window._wsUpBase = d.uptime_sec || 0;
                window._wsUpStart = Date.now();
            }
            popCount(cl.length);
            return;
        }

        // 逐行更新：只改数值节点，不触碰其它 DOM
        setStat('listen', d.listen || '—', true);
        setStat('started', d.started_at || '—', true);
        if (!(running && window._wsUpStart)) setStat('ws_uptime', running ? secToLive(d.uptime_sec) : '—');
        setStat('cc', cl.length);
        setStat('total_conn', s.total_conn || 0);
        setStat('total_recv', s.total_recv || 0);
        setStat('total_sent', s.total_sent || 0);
        setStat('total_events', s.total_events || 0);
        setStat('bytes_in', kb(s.bytes_in));
        setStat('bytes_out', kb(s.bytes_out));
        popCount(cl.length);
    }

    // 在线客户端数量变化时数字跳一下
    function popCount(n) {
        var el = $('wsClientCount');
        if (!el) return;
        var changed = lastClientCount !== null && String(lastClientCount) !== String(n);
        lastClientCount = n;
        el.textContent = n;
        if (changed) toggleAt(el, 'pop', 460);
    }

    // 每秒把「运行时长」往前推：本地累加，不等下一次轮询，做到无延迟跳动
    function tickWsUptime() {
        var n = document.querySelector('#wsStatusBlock [data-f="ws_uptime"]');
        if (!n || !window._wsUpStart) return;
        var sec = window._wsUpBase + (Date.now() - window._wsUpStart) / 1000;
        var t = secToLive(sec);
        if (n.textContent !== t) n.textContent = t;
    }

    // 每个连接行的「保持时长」同样逐秒本地累加
    function tickClientUptime() {
        var rows = document.querySelectorAll('#wsClientsBlock [data-cid]');
        Array.prototype.forEach.call(rows, function (row) {
            if (!row._upStart) return;
            var n = row.querySelector('[data-cf="uptime"]');
            if (!n) return;
            var t = secToLive(row._upBase + (Date.now() - row._upStart) / 1000);
            if (n.textContent !== t) n.textContent = t;
        });
    }

    // 每个连接行只建一次，之后按 id 就地更新字段；新连接才播入场动画
    function clientRowHtml(c) {
        var h = '<div class="ws-client-head"><span class="ws-client-id">' + esc(c.id) + '</span>'
            + '<span class="ws-client-addr">' + esc(c.addr || '') + '</span>'
            + '<span class="ws-client-spacer"></span>'
            + '<button class="ws-btn ws-btn-sm" data-disc="' + esc(c.id) + '">断开</button></div>';
        h += '<div class="ws-client-grid">';
        h += '<span class="k">QQ 号</span><span class="v" data-cf="self_id">' + esc(c.self_id || '未知') + '</span>';
        h += '<span class="k">昵称</span><span class="v" data-cf="nickname">' + esc(c.nickname || '未知') + '</span>';
        h += '<span class="k">路径</span><span class="v ws-mono" data-cf="path">' + esc(c.path || '') + '</span>';
        h += '<span class="k">接入时间</span><span class="v" data-cf="connected_at">' + esc(c.connected_at || '') + '</span>';
        h += '<span class="k">保持时长</span><span class="v ws-live" data-cf="uptime">' + esc(secToLive(c.uptime_sec)) + '</span>';
        h += '<span class="k">收 / 发</span><span class="v" data-cf="traffic">' + esc(c.recv) + ' / ' + esc(c.sent)
            + '　' + esc(kb(c.bytes_in)) + ' / ' + esc(kb(c.bytes_out)) + '</span>';
        h += '<span class="k">最后活动</span><span class="v" data-cf="last_at">' + esc(c.last_at || '—') + '</span>';
        h += '</div>';
        return h;
    }

    function bindDisc(box, node) {
        var b = node.querySelector('[data-disc]');
        if (!b) return;
        b.addEventListener('click', function () {
            var id = b.getAttribute('data-disc');
            b.disabled = true;
            api('/api/ws/disconnect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: id })
            }).catch(function (e) { notice('断开失败：' + e.message, 'warn'); })
                .then(function () { lastCliRows = {}; pollWs(); });
        });
    }

    function renderClients(d) {
        var cl = d.clients || [];
        var box = $('wsClientsBlock');
        if (!box) return;

        if (!cl.length) {
            if (box.querySelector('.ws-clients')) {
                box.innerHTML = '<p class="console-empty">暂无连接。请在 NapCat 中配置反向 WebSocket：'
                    + '<code class="ws-code">' + esc(d.listen || '') + '</code></p>';
                lastCliRows = {};
            }
            return;
        }

        var wrap = box.querySelector('.ws-clients');
        if (!wrap) {
            var fresh = cl.map(function (c) { return c.id; }).join(',') !== lastCliIdSig;
            lastCliIdSig = cl.map(function (c) { return c.id; }).join(',');
            box.innerHTML = '<div class="ws-clients' + (fresh ? ' anim' : '') + '"></div>';
            wrap = box.querySelector('.ws-clients');
            lastCliRows = {};
        }

        // 1) 移除已断开的行
        var alive = {};
        cl.forEach(function (c) { alive[c.id] = 1; });
        Object.keys(lastCliRows).forEach(function (id) {
            if (alive[id]) return;
            var n = lastCliRows[id];
            if (n && n.parentNode) n.parentNode.removeChild(n);
            delete lastCliRows[id];
        });

        // 2) 新连接：建行（带入场动画）；已存在的行：只改变动的字段
        cl.forEach(function (c, i) {
            var node = lastCliRows[c.id];
            if (!node) {
                node = document.createElement('div');
                node.className = 'ws-client';
                node.setAttribute('data-cid', c.id);
                node.style.animationDelay = Math.min(i * 0.06, 0.3) + 's';
                node.innerHTML = clientRowHtml(c);
                wrap.appendChild(node);
                lastCliRows[c.id] = node;
                bindDisc(box, node);
            } else {
                var f = { self_id: c.self_id || '未知', nickname: c.nickname || '未知',
                    path: c.path || '', connected_at: c.connected_at || '', last_at: c.last_at || '—',
                    traffic: esc(c.recv) + ' / ' + esc(c.sent) + '　' + esc(kb(c.bytes_in)) + ' / ' + esc(kb(c.bytes_out)) };
                Object.keys(f).forEach(function (k) {
                    var n = node.querySelector('[data-cf="' + k + '"]');
                    if (!n) return;
                    var v = String(f[k]);
                    if (n.textContent === v) return;
                    n.textContent = v;
                    if (k === 'traffic') toggleAt(n, 'ws-val-flash', 1050);
                });
            }
            // 每轮把「保持时长」的基准对齐服务器时间，避免本地累加漂移
            node._upBase = c.uptime_sec || 0;
            node._upStart = Date.now();
        });
        lastCliSig = cl.map(function (c) { return c.id + '|' + c.recv + '|' + c.sent; }).join(',');
    }

    var KIND_LABEL = {
        message: '消息', notice: '通知', request: '请求', meta: '元事件',
        api: 'API', binary: '二进制', raw: '原始', system: '系统'
    };

    // ---------- 实时事件日志：可读卡片（谁 · 在哪个群 · 做了什么 / 发了什么） ----------
    // 服务端把事件解析成 extra（uid/uname/gid/gname/content 等），前端只渲染人话，
    // 原始 JSON 仅在勾选「显示原始 JSON」时才附加，默认不展示。

    function evAvatar(ex) {
        if (ex.uid) return { kind: 'user', id: ex.uid };
        if (ex.gid) return { kind: 'group', id: ex.gid };
        return null;
    }

    // 卡片内部结构。e.extra 缺失时（旧数据 / 未知事件）退回纯文字行。
    function evCardHtml(e, showRaw) {
        var ex = e.extra || {};
        var kind = e.kind || 'system';
        var av = evAvatar(ex);
        var h = '';
        if (av) {
            h += '<span class="ws-ev-avwrap">'
                + '<img class="ws-ev-av" alt="" width="38" height="38" loading="lazy" src="'
                + esc(dynAvUrl(av.kind, av.id)) + '">'
                + (ex.gid && ex.uid
                    ? '<img class="ws-ev-av-mini" alt="" width="18" height="18" loading="lazy" src="'
                      + esc(dynAvUrl('group', ex.gid)) + '">'
                    : '')
                + '</span>';
        } else {
            h += '<span class="ws-ev-avwrap"><span class="ws-ev-av ws-ev-av-bot">ILBB</span></span>';
        }
        h += '<div class="ws-ev-body">';
        h += '<div class="ws-ev-top">';
        if (ex.uname) h += '<span class="ws-ev-name">' + esc(ex.uname) + '</span>';
        if (ex.gname || ex.gid) {
            h += '<span class="ws-ev-where">' + esc(ex.gname || ('群 ' + ex.gid)) + '</span>';
        } else if (!ex.uid) {
            h += '<span class="ws-ev-where">本机</span>';
        }
        h += '<span class="ws-ev-spacer"></span>';
        h += '<span class="ws-ev-kind">' + esc(KIND_LABEL[kind] || kind) + '</span>';
        h += '<span class="ws-ev-time">' + esc(e.t || '') + '</span>';
        h += '</div>';
        // 正文：消息事件显示聊了什么，其余显示服务端生成的一句话
        var body = ex.content ? ex.content : (e.text || '');
        h += '<div class="ws-ev-text">' + esc(body) + '</div>';
        if (ex.content && e.text) h += '<div class="ws-ev-sub">' + esc(e.text) + '</div>';
        if (ex.message_id) {
            h += '<div class="ws-ev-mid">消息 ID <code class="ws-code">' + esc(ex.message_id) + '</code></div>';
        }
        if (showRaw && e.raw) h += '<pre class="ws-ev-raw">' + esc(e.raw) + '</pre>';
        h += '</div>';
        return h;
    }

    function evRowClass(e) { return 'ws-event ws-ev-' + esc(e.kind || 'system'); }

    function evSig(e) { return JSON.stringify(e.extra || {}) + '|' + (e.text || '') + '|' + (e.raw ? 1 : 0); }

    // 逐行增量渲染：新事件只插入自己的那一行，旧行原地更新，
    // 不再整块重建，滚动位置与正在进行动画不受影响。
    function renderEvents(d) {
        var evts = d.events || [];
        var box = $('wsEventsBlock');
        if (!box) return;
        var showRaw = $('wsShowRaw') ? $('wsShowRaw').checked : false;
        var autoScroll = $('wsAutoScroll') ? $('wsAutoScroll').checked : true;
        var atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
        var force = lastEvtSig === '';

        if (!evts.length) {
            if (lastEvtSig === 'empty') return;
            lastEvtSig = 'empty';
            lastEvtIds = {};
            box.innerHTML = '<p class="console-empty">暂无事件。等待 NapCat 连接…</p>';
            return;
        }

        if (force) {
            box.innerHTML = '';
            lastEvtIds = {};
        }

        // 1) 清掉已不在列表里的行（清空日志、超出缓冲被丢弃）
        var alive = {};
        evts.forEach(function (e) { alive[String(e.id)] = 1; });
        Object.keys(lastEvtIds).forEach(function (id) {
            if (alive[id]) return;
            var n = lastEvtIds[id];
            if (n && n.parentNode) n.parentNode.removeChild(n);
            delete lastEvtIds[id];
        });

        // 2) 旧行：昵称 / 群名晚到（服务端自愈）时就地刷新内容
        evts.forEach(function (e) {
            var id = String(e.id);
            var node = lastEvtIds[id];
            if (!node) return;
            var sig = evSig(e);
            if (node.getAttribute('data-ev-sig') === sig) return;
            node.setAttribute('data-ev-sig', sig);
            node.className = evRowClass(e);
            node.innerHTML = evCardHtml(e, showRaw);
        });

        // 3) 新到的事件：倒序插入，保证最新一条在最上面
        var arrived = 0;
        for (var i = evts.length - 1; i >= 0; i--) {
            var e = evts[i];
            var id = String(e.id);
            if (lastEvtIds[id]) continue;
            var node = document.createElement('div');
            node.className = evRowClass(e);
            node.setAttribute('data-ev-id', id);
            node.setAttribute('data-ev-sig', evSig(e));
            node.innerHTML = evCardHtml(e, showRaw);
            // 只给「真正新到」的前 3 条播入场动画
            if (arrived < 3) {
                node.classList.add('is-new');
                node.style.animationDelay = (arrived * 0.05) + 's';
                arrived++;
            }
            lastEvtIds[id] = node;
            box.insertBefore(node, box.firstChild);
        }

        var ph = box.querySelector('.console-empty');
        if (ph) box.removeChild(ph);
        lastEvtSig = 'ready';
        if (autoScroll && (atBottom || arrived)) box.scrollTop = 0;
    }

    // 事件按时间倒序（最新在上），所以自动滚动是回到顶部
    function pollWs() {
        if (!document.getElementById('view-ws')) return;
        if ($('wsPausePoll') && $('wsPausePoll').checked) return;
        // 默认不下发原始 JSON，只有勾选「显示原始 JSON」时才向服务端索取
        var raw = $('wsShowRaw') && $('wsShowRaw').checked ? '&raw=1' : '';
        return api('/api/ws/status?limit=80' + raw).then(function (d) {
            renderStatus(d);
            renderClients(d);
            renderEvents(d);
            if (!cfgFilled) fillConfig(d.config);
            window._wsUpBase = d.uptime_sec || 0;
            window._wsUpStart = Date.now();
            if (!d.has_lib) {
                notice('未检测到 websockets 库，WS 服务器无法启动。请执行：pip install websockets', 'warn');
            }
        }).catch(function (e) {
            var box = $('wsStatusBlock');
            if (box) box.innerHTML = '<p class="console-empty">获取失败：' + esc(e.message) + '</p>';
        });
    }

    // ---------- 接口调试（二级面板） ----------
    var SPEC = null;          // /api/ws/actions 返回的元数据
    var specIndex = {};       // action -> spec
    var current = null;       // 当前选中的接口

    function loadActions() {
        if (SPEC) return Promise.resolve(SPEC);
        return api('/api/ws/actions').then(function (d) {
            SPEC = d;
            (d.groups || []).forEach(function (g) {
                (g.actions || []).forEach(function (a) { specIndex[a.action] = a; });
            });
            renderApiList('');
            if (!current) {
                var first = (d.groups && d.groups[0] && d.groups[0].actions && d.groups[0].actions[0]) || null;
                if (first) selectAction(first.action);
            }
            return SPEC;
        }).catch(function (e) {
            var box = $('wsApiList');
            if (box) box.innerHTML = '<p class="console-empty">接口清单加载失败：' + esc(e.message) + '</p>';
        });
    }

    function renderApiList(q) {
        var box = $('wsApiList');
        if (!box || !SPEC) return;
        q = (q || '').trim().toLowerCase();
        var h = '', total = 0, seq = 0;
        (SPEC.groups || []).forEach(function (g) {
            var picked = (g.actions || []).filter(function (a) {
                if (!q) return true;
                return (a.action + ' ' + (a.label || '') + ' ' + (g.name || '')).toLowerCase().indexOf(q) > -1;
            });
            if (!picked.length) return;
            total += picked.length;
            h += '<div class="ws-api-group">' + esc(g.name) + '<span class="ws-api-group-n">' + picked.length + '</span></div>';
            picked.forEach(function (a) {
                var d = Math.min(seq * 0.018, 0.24);   // 依次错开滑入
                seq++;
                h += '<button type="button" class="ws-api-item' + (current && current.action === a.action ? ' active' : '')
                    + '" data-action="' + esc(a.action) + '" style="animation-delay:' + d.toFixed(3) + 's">'
                    + '<span class="ws-api-label">' + esc(a.label || a.action) + '</span>'
                    + '<span class="ws-api-name">' + esc(a.action) + '</span>'
                    + '</button>';
            });
        });
        box.innerHTML = total ? h : '<p class="console-empty">没有匹配的接口</p>';
        Array.prototype.forEach.call(box.querySelectorAll('[data-action]'), function (b) {
            b.addEventListener('click', function () { selectAction(b.getAttribute('data-action')); });
        });
    }

    function fieldId(name) { return 'wsp_' + name; }

    function selectAction(action) {
        var spec = specIndex[action];
        if (!spec) return;
        current = spec;
        Array.prototype.forEach.call(document.querySelectorAll('#wsApiList .ws-api-item'), function (b) {
            b.classList.toggle('active', b.getAttribute('data-action') === action);
        });
        if ($('wsApiTitle')) $('wsApiTitle').textContent = spec.label || spec.action;
        if ($('wsApiAction')) $('wsApiAction').textContent = spec.action;
        if ($('wsApiDesc')) $('wsApiDesc').textContent = spec.desc || '';
        if ($('wsApiResetBtn')) $('wsApiResetBtn').classList.toggle('hidden', !(spec.params || []).length);
        var out = $('wsSendResult');
        if (out) out.classList.add('hidden');
        closeSelects();
        renderParams(spec);
    }

    function renderParams(spec) {
        var box = $('wsApiParams');
        if (!box) return;
        var ps = spec.params || [];
        if (!ps.length) {
            box.innerHTML = '<div class="ws-noparam">该接口不需要任何参数，直接点击「调用接口」即可。</div>';
            updatePreview();
            return;
        }
        var h = '';
        ps.forEach(function (p) {
            var id = fieldId(p.name);
            h += '<div class="ws-param" data-param="' + esc(p.name) + '">';
            h += '<div class="ws-param-head">'
                + '<label for="' + id + '">' + esc(p.label || p.name) + '</label>'
                + '<code class="ws-param-name">' + esc(p.name) + '</code>'
                + '<span class="' + (p.required ? 'ws-req' : 'ws-opt') + '">' + (p.required ? '必填' : '可选') + '</span>'
                + '</div>';
            if (p.type === 'bool') {
                h += '<label class="ws-check ws-param-check"><input type="checkbox" id="' + id + '"> 启用该项</label>';
            } else if (p.type === 'enum' || p.source) {
                // 自定义下拉：按钮 + 浮层选项；真实取值写在同 id 的隐藏 input 里。
                // 带 source 的参数（群号/QQ号/群成员）即使 type 是 int 也走下拉，
                // 选项由 NapCat 接口实时拉取，不再手输。
                var dyn = p.source ? String(p.source) : '';
                var vals = p.values || [];
                var head = vals[0] || { value: '', label: '' };
                h += '<input type="hidden" id="' + id + '" value="' + (dyn ? '' : esc(head.value)) + '">';
                h += '<div class="ilbb-select' + (dyn ? ' ilbb-select-dyn' : '') + '"'
                    + ' data-select="' + esc(p.name) + '" data-target="' + id + '"'
                    + (dyn ? ' data-source="' + esc(dyn) + '"' : '') + '>';
                h += '<button type="button" class="ilbb-select-btn" aria-haspopup="listbox" aria-expanded="false">';
                if (dyn) h += '<img class="ilbb-select-btn-av" alt="" aria-hidden="true" width="24" height="24" hidden>';
                h += '<span class="ilbb-select-text">'
                    + (dyn ? '正在获取' + esc(srcLabel(dyn)) + '…' : esc(head.label || head.value)) + '</span>';
                h += '<span class="ilbb-select-caret"></span>';
                h += '</button>';
                h += '<ul class="ilbb-select-menu" role="listbox">';
                if (dyn) {
                    // 动态数据源：列表由接口实时拉取，选项上方固定一个搜索框
                    h += '<li class="ilbb-select-searchwrap">'
                        + '<input type="text" class="ilbb-select-search" autocomplete="off"'
                        + ' placeholder="搜索' + esc(srcLabel(dyn)) + '…" aria-label="搜索' + esc(srcLabel(dyn)) + '">'
                        + '</li>';
                } else {
                    vals.forEach(function (v, vi) {
                        var on = vi === 0;
                        h += '<li class="ilbb-select-opt" role="option" data-value="' + esc(v.value) + '"'
                            + ' aria-selected="' + (on ? 'true' : 'false') + '">'
                            + '<span class="ilbb-select-opt-main">' + esc(v.label || v.value) + '</span>'
                            + '<span class="ilbb-select-opt-code">' + esc(v.value) + '</span>'
                            + '<span class="ilbb-select-tick">✓</span>'
                            + '</li>';
                    });
                }
                h += '</ul></div>';
            } else if (p.widget === 'textarea') {
                h += '<textarea id="' + id + '" rows="3" autocomplete="off" placeholder="'
                    + esc(p.placeholder || '') + '"></textarea>';
            } else {
                h += '<input type="' + (p.type === 'int' ? 'number' : 'text') + '" id="' + id
                    + '" autocomplete="off" placeholder="' + esc(p.placeholder || '') + '">';
            }
            if (p.hint) h += '<div class="ws-param-hint">' + esc(p.hint) + '</div>';
            h += '</div>';
        });
        box.innerHTML = h;
        initSelects(box);
        all('input:not([type=hidden]):not(.ilbb-select-search), textarea', box).forEach(function (el) {
            el.addEventListener('input', updatePreview);
            el.addEventListener('change', updatePreview);
            el.addEventListener('keydown', function (e) {
                if (e.key !== 'Enter') return;
                if (el.tagName === 'TEXTAREA' && !e.ctrlKey) return;
                e.preventDefault();
                if (!$('wsSendBtn').disabled) sendApi();
            });
        });
        updatePreview();
    }

    // ---------- 自定义下拉（枚举参数） ----------
    // 不使用浏览器默认 <select>：外层 .ilbb-select + 按钮 + 浮层菜单，带开合/勾选/键盘动效。
    // 真实取值仍存放在 id = wsp_<name> 的隐藏 input 中，collectParams()/resetParams() 无需改动。

    // ---------- 动态数据源（好友 / 群聊 / 群成员） ----------
    // ACTION_SPEC 里带 source 的参数不再手输：选项调用 NapCat 接口实时拉取，
    // 每项带头像（走 /api/ws/avatar 后端代理），支持搜索、重试、群号联动。
    var DYN_LABEL = { friend: '好友', group: '群聊', group_member: '群成员', message: '消息' };
    // 个别接口需要列表之外的「特殊值」，按 action/参数名 追加到列表顶部
    var DYN_EXTRA = {
        'set_group_ban/user_id': [{ value: 'all', label: '全员（整个群）', meta: '特殊', av: '' }]
    };
    var MEMBER_TTL = 5 * 60 * 1000;   // 群成员列表缓存 5 分钟
    var listCache = {};               // friend / group -> [{value,label,av,meta}]
    var memberCache = {};             // group_id -> {ts, list}

    function srcLabel(src) { return DYN_LABEL[src] || '选项'; }

    function callOneBot(action, params) {
        return api('/api/ws/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action, params: params || {}, timeout: 12 })
        }).then(function (d) { return d.response || {}; });
    }

    function dynDependency(sel, name) {
        // 依赖项默认取 #wsp_<name>；其它页面（如插件页）可用 data-dep 指定自己的隐藏 input id
        var dep = sel.getAttribute('data-dep');
        var el = $(dep ? dep : fieldId(name));
        return el ? String(el.value || '').trim() : '';
    }

    function roleText(r) {
        if (r === 'owner') return '群主';
        if (r === 'admin') return '管理员';
        return '';
    }

    // OneBot 回包解包：失败时抛错，让下拉显示可读原因（而不是空列表）
    function dynData(resp, label) {
        if (!resp || !Object.keys(resp).length) {
            throw new Error('机器人没有返回数据，请确认 NapCat 已连接');
        }
        if (resp.status === 'failed' || (resp.retcode !== undefined && resp.retcode !== 0)) {
            throw new Error(resp.wording || resp.message || (label + '接口返回失败'));
        }
        return Array.isArray(resp.data) ? resp.data : [];
    }

    function fetchFriendList() {
        if (listCache.friend) return Promise.resolve(listCache.friend);
        return callOneBot('get_friend_list', {}).then(function (resp) {
            var arr = dynData(resp, '好友列表');
            var out = [];
            arr.forEach(function (f) {
                var id = String(f.user_id == null ? '' : f.user_id);
                if (!id) return;
                out.push({ value: id, label: f.remark || f.nickname || id, av: 'user' });
            });
            listCache.friend = out;
            return out;
        });
    }

    function fetchGroupList() {
        if (listCache.group) return Promise.resolve(listCache.group);
        return callOneBot('get_group_list', {}).then(function (resp) {
            var arr = dynData(resp, '群列表');
            var out = [];
            arr.forEach(function (g) {
                var id = String(g.group_id == null ? '' : g.group_id);
                if (!id) return;
                out.push({
                    value: id, label: g.group_name || id, av: 'group',
                    meta: g.member_count ? (g.member_count + ' 人') : ''
                });
            });
            listCache.group = out;
            return out;
        });
    }

    function fetchMemberList(gid) {
        var key = String(gid || '');
        if (!key) return Promise.reject(new Error('请先选择群聊'));
        var hit = memberCache[key];
        if (hit && (Date.now() - hit.ts) < MEMBER_TTL) return Promise.resolve(hit.list);
        return callOneBot('get_group_member_list', { group_id: Number(key) || key }).then(function (resp) {
            var arr = dynData(resp, '群成员列表');
            var out = [];
            arr.forEach(function (m) {
                var id = String(m.user_id == null ? '' : m.user_id);
                if (!id) return;
                out.push({ value: id, label: m.card || m.nickname || id, av: 'user', meta: roleText(m.role) });
            });
            memberCache[key] = { ts: Date.now(), list: out };
            return out;
        });
    }

    // 机器人最近发出的消息（撤回 / 查详情等接口的 message_id 参数从这里选）
    // 不缓存：每次打开都重新拉，刚发出去的消息立刻可选。
    function fetchMessageList() {
        return api('/api/ws/messages?limit=60').then(function (d) {
            var arr = (d && d.messages) || [];
            var out = [];
            arr.forEach(function (m) {
                var mid = String(m.message_id == null ? '' : m.message_id);
                if (!mid) return;
                var isGroup = m.target_type === 'group';
                var tname = m.target_name || m.target_id || '';
                var txt = String(m.content == null ? '' : m.content).replace(/\s+/g, ' ').trim();
                out.push({
                    value: mid,
                    label: txt ? txt.slice(0, 42) : '（空消息 / 非文本）',
                    meta: (isGroup ? '群 ' : '私聊 ') + tname + ' · ' + (m.time || ''),
                    av: isGroup ? 'group' : 'user',
                    avId: String(m.target_id || '')
                });
            });
            return out;
        });
    }

    function dynAvUrl(kind, id) {
        return '/api/ws/avatar?type=' + (kind === 'group' ? 'group' : 'user')
            + '&id=' + encodeURIComponent(id) + '&s=100';
    }

    function dynOptHtml(o, cur) {
        var on = o.value === cur;
        var h = '<li class="ilbb-select-opt" role="option" data-value="' + esc(o.value) + '"'
            + ' data-search="' + esc((o.label || '') + ' ' + o.value) + '"'
            + ' aria-selected="' + (on ? 'true' : 'false') + '">';
           if (o.av) {
               h += '<img class="ilbb-select-av" alt="" aria-hidden="true" width="26" height="26"'
                   + ' data-src="' + esc(dynAvUrl(o.av, o.avId || o.value)) + '">';
           }
           h += '<span class="ilbb-select-opt-main">' + esc(o.label || o.value) + '</span>';
        if (o.meta) h += '<span class="ilbb-select-opt-meta">' + esc(o.meta) + '</span>';
        h += '<span class="ilbb-select-opt-code">' + esc(o.value) + '</span>';
        h += '<span class="ilbb-select-tick">✓</span></li>';
        return h;
    }

    // 只给「看得见」的选项加载头像：打开下拉不会一次打出几百个请求
    function dynHydrate(sel) {
        var menu = sel.querySelector('.ilbb-select-menu');
        if (!menu) return;
        var mr = menu.getBoundingClientRect();
        all('.ilbb-select-av[data-src]', menu).forEach(function (im) {
            var url = im.getAttribute('data-src');
            if (!url) return;
            if (!mr.height) { im.src = url; im.removeAttribute('data-src'); return; }
            var r = im.getBoundingClientRect();
            if (r.bottom >= mr.top - 160 && r.top <= mr.bottom + 160) {
                im.src = url;
                im.removeAttribute('data-src');
            }
        });
    }

    function dynClearBody(sel) {
        all('.ilbb-select-opt, .ilbb-dyn-state', sel).forEach(function (n) {
            if (n.parentNode) n.parentNode.removeChild(n);
        });
    }

    function dynState(sel, msg, cls) {
        var menu = sel.querySelector('.ilbb-select-menu');
        if (!menu) return null;
        var li = document.createElement('li');
        li.className = 'ilbb-dyn-state' + (cls ? ' ' + cls : '');
        li.textContent = msg;
        if (cls === 'retry') {
            li.addEventListener('click', function (e) { e.stopPropagation(); dynReload(sel); });
        }
        menu.appendChild(li);
        return li;
    }

    function dynSetText(sel, state, text) {
        sel.setAttribute('data-state', state);
        var t = sel.querySelector('.ilbb-select-text');
        if (t && text != null) t.textContent = text;
    }

    function dynReload(sel) {
        var src = sel.getAttribute('data-source');
        var gid;
        if (src === 'friend') delete listCache.friend;
        else if (src === 'group') delete listCache.group;
        else if (src === 'group_member') {
            gid = dynDependency(sel, 'group_id');
            if (gid) delete memberCache[gid];
        }
        dynLoad(sel);
    }

    function dynLoad(sel) {
        var src = sel.getAttribute('data-source');
        var label = srcLabel(src);
        var hid = $(sel.getAttribute('data-target'));
        dynSetText(sel, 'loading', '正在获取' + label + '…');
        dynClearBody(sel);

        var job = null;
        if (src === 'friend') {
            dynState(sel, '正在加载好友列表…', 'loading');
            job = fetchFriendList();
        } else if (src === 'group') {
            dynState(sel, '正在加载群列表…', 'loading');
            job = fetchGroupList();
        } else if (src === 'group_member') {
            var gid = dynDependency(sel, 'group_id');
            sel.setAttribute('data-gid', gid);
            if (!gid) {
                if (hid) hid.value = '';
                sel.setAttribute('data-gid', '');
                dynSetText(sel, 'error', '请先选择群聊');
                dynState(sel, '上方「群号」选好群后，这里会自动列出群成员', 'hint');
                syncOneSelect(sel);
                return;
            }
            dynState(sel, '正在加载群成员…', 'loading');
            job = fetchMemberList(gid);
        } else if (src === 'message') {
            dynState(sel, '正在加载机器人最近发出的消息…', 'loading');
            job = fetchMessageList();
        } else {
            dynSetText(sel, 'error', '未知数据源');
            dynState(sel, '参数元数据缺少有效的 source 字段', 'hint');
            return;
        }

        job.then(function (list) {
            var cur = hid ? hid.value : '';
            dynClearBody(sel);
            if (!list.length) {
                if (src === 'message') {
                    dynSetText(sel, 'error', '暂无已发出的消息');
                    dynState(sel, '机器人还没发过消息。先用「消息发送」里的 send_group_msg / send_private_msg 发一条，这里就会出现在下拉里', 'hint');
                } else {
                    dynSetText(sel, 'error', '没有获取到' + label);
                    dynState(sel, '接口返回空列表（点此重试）', 'retry');
                }
                return;
            }
            if (cur && !list.some(function (o) { return o.value === cur; })) {
                // 列表刷新后原选择已失效：群成员必须清空，避免把参数提交到别的群的人
                if (src === 'group_member' && hid) hid.value = '';
                cur = hid ? hid.value : '';
            }
            var menu = sel.querySelector('.ilbb-select-menu');
            var extras = DYN_EXTRA[((current && current.action) || '') + '/' + sel.getAttribute('data-select')];
            if (extras && (src !== 'group_member' || dynDependency(sel, 'group_id'))) {
                list = extras.concat(list);   // 例：群禁言需要「全员」这种特殊值
            }
            var tmp = document.createElement('ul');
            var body = '';
            list.forEach(function (o) { body += dynOptHtml(o, cur); });
            tmp.innerHTML = body;
            while (tmp.firstChild) menu.appendChild(tmp.firstChild);
            sel.setAttribute('data-state', 'ready');
            bindOptions(sel);
            syncOneSelect(sel);
            updatePreview();
            if (sel.classList.contains('open')) dynHydrate(sel);
        }).catch(function (e) {
            dynClearBody(sel);
            dynSetText(sel, 'error', '获取失败，点此重试');
            dynState(sel, (e && e.message ? e.message : '获取失败') + '（点此重试）', 'retry');
        });
    }

    function dynLoadAll(root) {
        all('.ilbb-select-dyn', root || document).forEach(dynLoad);
    }

    // 群号变化 → 群成员下拉重新拉取
    function dynReloadMembers() {
        all('.ilbb-select-dyn[data-source="group_member"]').forEach(function (sel) {
            var gid = dynDependency(sel, 'group_id');
            if (sel.getAttribute('data-gid') === gid && sel.getAttribute('data-state') === 'ready') return;
            dynLoad(sel);
        });
    }

    function afterPickDyn(sel) {
        if (sel.getAttribute('data-select') === 'group_id' || sel.getAttribute('data-source') === 'group') {
            dynReloadMembers();
        }
    }

    function dynFilter(sel) {
        var inp = sel.querySelector('.ilbb-select-search');
        var raw = inp ? inp.value : '';
        var q = raw.trim().toLowerCase();
        var menu = sel.querySelector('.ilbb-select-menu');
        var shown = 0;
        all('.ilbb-select-opt', sel).forEach(function (o) {
            if (o.classList.contains('ilbb-select-opt-manual')) return;   // 手动项单独维护
            var txt = (o.getAttribute('data-search') || '').toLowerCase();
            var hit = !q || txt.indexOf(q) !== -1;
            o.classList.toggle('dyn-hide', !hit);
            if (hit) shown++;
        });

        // 数字直填：好友 / 群聊 允许直接使用不在列表里的号码（例如给非好友发消息）
        var src = sel.getAttribute('data-source');
        var num = raw.trim();
        var manual = sel.querySelector('.ilbb-select-opt-manual');
        var usable = (src === 'friend' || src === 'group') && /^[1-9]\d{4,11}$/.test(num);
        if (usable) {
            all('.ilbb-select-opt', sel).forEach(function (o) {
                if (o.getAttribute('data-value') === num) usable = false;   // 列表里已有，不必重复
            });
        }
        if (!usable && manual && manual.parentNode) {
            manual.parentNode.removeChild(manual);
            manual = null;
        }
        if (usable) {
            if (!manual) {
                manual = document.createElement('li');
                manual.className = 'ilbb-select-opt ilbb-select-opt-manual';
                var wrap = sel.querySelector('.ilbb-select-searchwrap');
                if (wrap && wrap.nextSibling) menu.insertBefore(manual, wrap.nextSibling);
                else menu.appendChild(manual);
                bindOptions(sel);
            }
            manual.setAttribute('data-value', num);
            manual.setAttribute('data-search', num);
            manual.innerHTML = '<span class="ilbb-select-opt-main">直接使用 ' + num + '</span>'
                + '<span class="ilbb-select-opt-meta">手动</span>'
                + '<span class="ilbb-select-tick">✓</span>';
            shown++;
        }

        var no = sel.querySelector('.ilbb-dyn-nohit');
        if (q && !shown) {
            if (!no) {
                no = document.createElement('li');
                no.className = 'ilbb-dyn-state ilbb-dyn-nohit hint';
                menu.appendChild(no);
            }
            no.textContent = '没有匹配「' + raw.trim() + '」的' + srcLabel(src);
        } else if (no && no.parentNode) {
            no.parentNode.removeChild(no);
        }
    }

    function syncOneSelect(sel) {
        var hid = $(sel.getAttribute('data-target'));
        var val = hid ? hid.value : '';
        var hit = null;
        all('.ilbb-select-opt', sel).forEach(function (o) {
            var on = o.getAttribute('data-value') === val;
            o.setAttribute('aria-selected', on ? 'true' : 'false');
            if (on) hit = o;
        });
        var txt = sel.querySelector('.ilbb-select-text');
        if (txt) {
            // 加载中 / 未选群但需要依赖群号时，保留状态文案（如「请先选择群聊」）
            var st = sel.getAttribute('data-state');
            if (!(st === 'loading' || (st === 'error' && !val))) {
                var main = hit ? hit.querySelector('.ilbb-select-opt-main') : null;
                txt.textContent = main ? main.textContent : (val ? val : '请选择');
            }
        }
        // 动态下拉：按钮左侧同步所选对象头像
        var btnAv = sel.querySelector('.ilbb-select-btn-av');
        if (btnAv) {
            var srcAv = hit ? hit.querySelector('.ilbb-select-av') : null;
            var url = srcAv ? (srcAv.getAttribute('src') || srcAv.getAttribute('data-src')) : '';
            if (url) { btnAv.src = url; btnAv.removeAttribute('hidden'); }
            else { btnAv.removeAttribute('src'); btnAv.setAttribute('hidden', 'hidden'); }
        }
    }

    function syncSelects(root) {
        all('.ilbb-select', root || document).forEach(syncOneSelect);
    }

    function closeSelects(except) {
        all('#wsApiParams .ilbb-select.open').forEach(function (s) {
            if (s === except) return;
            s.classList.remove('open');
            var b = s.querySelector('.ilbb-select-btn');
            if (b) b.setAttribute('aria-expanded', 'false');
        });
    }

    function pickOption(sel, opt) {
        var hid = $(sel.getAttribute('data-target'));
        if (hid) hid.value = opt.getAttribute('data-value') || '';
        sel.classList.remove('open');
        var btn = sel.querySelector('.ilbb-select-btn');
        if (btn) {
            btn.setAttribute('aria-expanded', 'false');
            toggleAt(btn, 'just-picked', 360);
            btn.focus();                  // 选完把焦点交还按钮，键盘可继续操作
        }
        // 选完清掉搜索词，下次展开是完整列表
        var search = sel.querySelector('.ilbb-select-search');
        if (search && search.value) {
            search.value = '';
            dynFilter(sel);
        }
        syncSelects();
        updatePreview();
        afterPickDyn(sel);                // 群号变化 → 群成员下拉联动刷新
    }

    // 键盘上下键切换高亮项（跳过被搜索过滤掉的项）
    function moveHover(sel, dir) {
        var opts = all('.ilbb-select-opt', sel).filter(function (o) {
            return !o.classList.contains('dyn-hide');
        });
        if (!opts.length) return;
        var cur = -1, i;
        for (i = 0; i < opts.length && cur === -1; i++) {
            if (opts[i].classList.contains('hover')) cur = i;
        }
        if (cur === -1) {
            for (i = 0; i < opts.length && cur === -1; i++) {
                if (opts[i].getAttribute('aria-selected') === 'true') cur = i;
            }
        }
        var next = cur === -1 ? (dir > 0 ? 0 : opts.length - 1) : (cur + dir + opts.length) % opts.length;
        opts.forEach(function (o) { o.classList.remove('hover'); });
        opts[next].classList.add('hover');
        if (opts[next].scrollIntoView) opts[next].scrollIntoView({ block: 'nearest' });
    }

    // 绑定菜单里的选项（静态 enum 与动态拉取的列表共用，动态列表每次重载后需重新调用）
    function bindOptions(sel) {
        var opts = all('.ilbb-select-opt', sel);
        opts.forEach(function (o, i) {
            o.style.animationDelay = Math.min(i * 0.024, 0.22) + 's';
            if (o.getAttribute('data-bound')) return;   // 防止重载后重复绑定
            o.setAttribute('data-bound', '1');
            o.addEventListener('click', function (e) { e.stopPropagation(); pickOption(sel, o); });
            o.addEventListener('mouseleave', function () { o.classList.remove('hover'); });
        });
        return opts;
    }

    function initSelects(root) {
        if (!root) return;
        all('.ilbb-select', root).forEach(function (sel) {
            var btn = sel.querySelector('.ilbb-select-btn');
            if (!btn) return;
            var menu = sel.querySelector('.ilbb-select-menu');
            if (menu) {
                // 菜单内部的一切点击都不该冒泡到 document（否则会立刻收起）
                menu.addEventListener('click', function (e) { e.stopPropagation(); });
                menu.addEventListener('scroll', function () { dynHydrate(sel); });
            }
            var search = sel.querySelector('.ilbb-select-search');
            if (search) {
                // 搜索框自己处理键盘：不能让它触发全局的 Enter 调用接口
                search.addEventListener('input', function () { dynFilter(sel); });
                search.addEventListener('click', function (e) { e.stopPropagation(); });
                search.addEventListener('keydown', function (e) {
                    e.stopPropagation();
                    if (e.key === 'Escape') { e.preventDefault(); closeSelects(); btn.focus(); return; }
                    if (e.key === 'ArrowDown') { e.preventDefault(); moveHover(sel, 1); return; }
                    if (e.key === 'ArrowUp') { e.preventDefault(); moveHover(sel, -1); return; }
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        var h2 = sel.querySelector('.ilbb-select-opt.hover')
                            || sel.querySelector('.ilbb-select-opt[aria-selected="true"]');
                        if (h2) pickOption(sel, h2);
                    }
                });
            }
            bindOptions(sel);
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var willOpen = !sel.classList.contains('open');
                closeSelects(sel);
                all('.ilbb-select-opt', sel).forEach(function (o) { o.classList.remove('hover'); });
                sel.classList.toggle('open', willOpen);
                btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
                if (willOpen && search) search.focus();   // 动态下拉展开即聚焦搜索
                else btn.focus();                          // 点开就聚焦按钮，↑↓/Enter 立即可用
                if (willOpen) {
                    setTimeout(function () { dynHydrate(sel); }, 0);   // 展开后再按可视区补头像
                }
            });
            btn.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') { e.preventDefault(); closeSelects(); return; }
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (!sel.classList.contains('open')) { btn.click(); return; }
                    moveHover(sel, e.key === 'ArrowDown' ? 1 : -1);
                    return;
                }
                if (e.key === 'Enter' || e.key === ' ') {
                    if (!sel.classList.contains('open')) return;   // 交给 click 处理
                    e.preventDefault();
                    var hov = sel.querySelector('.ilbb-select-opt.hover');
                    if (hov) pickOption(sel, hov);
                }
            });
        });
        syncSelects(root);
        dynLoadAll(root);        // 带 source 的下拉自动去接口拉列表
    }

    // 把当前表单值收集成 params（空值不发送，bool 仅在勾选/必填时发送）
    function collectParams() {
        var out = {};
        if (!current) return out;
        (current.params || []).forEach(function (p) {
            var el = $(fieldId(p.name));
            if (!el) return;
            if (p.type === 'bool') {
                if (el.checked) out[p.name] = true;
                else if (p.required) out[p.name] = false;
                return;
            }
            var v = (el.value || '').trim();
            if (v === '') return;
            if (p.type === 'int') {
                var n = Number(v);
                out[p.name] = isNaN(n) ? v : n;
            } else {
                out[p.name] = v;
            }
        });
        return out;
    }

    var sending = false;   // 请求进行中标志：避免输入框变动把按钮提前解禁

    function updatePreview() {
        var box = $('wsApiPreview');
        if (!box || !current) return;
        var got = collectParams();
        box.textContent = JSON.stringify({ action: current.action, params: got }, null, 2);

        var missing = [];
        (current.params || []).forEach(function (p) {
            var bad = !!p.required && !(p.name in got);
            var wrap = document.querySelector('#wsApiParams .ws-param[data-param="' + p.name + '"]');
            if (wrap) {
                var wasMissing = wrap.classList.contains('ws-param-missing');
                wrap.classList.toggle('ws-param-missing', bad);
                if (bad && !wasMissing) toggleAt(wrap, 'ws-shake', 520);   // 刚变成缺必填：抖一下提醒
            }
            if (bad) missing.push(p.label || p.name);
        });
        var tip = $('wsSendTip'), btn = $('wsSendBtn');
        if (!tip || !btn) return;
        if (missing.length) {
            tip.textContent = '还缺必填参数：' + missing.join('、');
            tip.className = 'ws-send-tip warn';
            btn.disabled = true;
        } else {
            tip.textContent = '参数就绪，echo 由服务器自动生成';
            tip.className = 'ws-send-tip ok';
            btn.disabled = sending;
        }
    }

    function resetParams() {
        if (!current) return;
        (current.params || []).forEach(function (p) {
            var el = $(fieldId(p.name));
            if (!el) return;
            if (p.type === 'bool') el.checked = false;
            else el.value = p.type === 'enum' ? ((p.values && p.values[0] && p.values[0].value) || '') : '';
        });
        syncSelects();          // 枚举回到首项后同步下拉显示
        dynReloadMembers();     // 群号被清空 → 群成员下拉回到「请先选择群聊」
        updatePreview();
    }

    function sendApi() {
        if (!current) return;
        var out = $('wsSendResult');
        var btn = $('wsSendBtn');
        sending = true;
        out.classList.remove('hidden');
        btn.disabled = true;
        btn.textContent = '调用中...';
        out.textContent = '调用 ' + current.action + ' ...';
        api('/api/ws/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: current.action, params: collectParams(), timeout: 8 })
        }).then(function (d) {
            out.textContent = JSON.stringify(d.response !== undefined ? d.response : d, null, 2);
        }).catch(function (e) {
            out.textContent = '失败：' + e.message;
        }).then(function () {
            sending = false;
            btn.textContent = '调用接口';
            updatePreview();
        });
    }

    // 二级 tabs 底部滑块：跟随当前项滑动
    function movePill(instant) {
        var pill = $('wsTabsPill');
        var wrap = $('wsTabs');
        var act = document.querySelector('#wsTabs .ws-tab.active');
        if (!pill || !wrap || !act) return;
        var r = act.getBoundingClientRect();
        var b = wrap.getBoundingClientRect();
        if (!r.width) return;          // 视图隐藏时量不到尺寸，等可见后再定位
        var bl = parseFloat(getComputedStyle(wrap).borderLeftWidth) || 0;
        var x = (r.left - b.left) - bl;
        if (instant) pill.style.transition = 'none';
        pill.style.width = r.width + 'px';
        pill.style.transform = 'translateX(' + x + 'px)';
        if (instant) { void pill.offsetWidth; pill.style.transition = ''; }
    }

    // 二级切换：运行概览 / 接口调试
    function switchPane(name) {
        closeSelects();
        Array.prototype.forEach.call(document.querySelectorAll('#wsTabs .ws-tab'), function (b) {
            b.classList.toggle('active', b.getAttribute('data-ws-tab') === name);
        });
        if ($('wsPaneOverview')) $('wsPaneOverview').classList.toggle('active', name === 'overview');
        if ($('wsPaneDebug')) $('wsPaneDebug').classList.toggle('active', name === 'debug');
        if ($('wsTabsHint')) {
            $('wsTabsHint').textContent = name === 'debug'
                ? '选择接口 · 填参数 · 直接调用'
                : '连接状态 · 服务器配置 · 实时事件';
        }
        movePill();
        if (name === 'debug') loadActions();
    }

    // ---------- 事件绑定 ----------
    function bind() {
        if (!document.getElementById('view-ws')) return;
        if ($('wsSaveBtn')) $('wsSaveBtn').addEventListener('click', saveConfig);
        if ($('wsStartBtn')) $('wsStartBtn').addEventListener('click', function () { ctrl('start'); });
        if ($('wsStopBtn')) $('wsStopBtn').addEventListener('click', function () { ctrl('stop'); });
        if ($('wsRestartBtn')) $('wsRestartBtn').addEventListener('click', function () { ctrl('restart'); });
        if ($('wsClearEventsBtn')) {
            $('wsClearEventsBtn').addEventListener('click', function () {
                api('/api/ws/events/clear', { method: 'POST' }).then(function () {
                    lastEvtSig = '';
                    pollWs();
                }).catch(function (e) { notice('清空失败：' + e.message, 'warn'); });
            });
        }
        if ($('wsShowRaw')) {
            $('wsShowRaw').addEventListener('change', function () { lastEvtSig = ''; pollWs(); });
        }
        if ($('wsSendBtn')) $('wsSendBtn').addEventListener('click', sendApi);
        if ($('wsApiResetBtn')) $('wsApiResetBtn').addEventListener('click', resetParams);
        if ($('wsApiSearch')) {
            $('wsApiSearch').addEventListener('input', function () { renderApiList($('wsApiSearch').value); });
        }
        Array.prototype.forEach.call(document.querySelectorAll('#wsTabs .ws-tab'), function (b) {
            b.addEventListener('click', function () { switchPane(b.getAttribute('data-ws-tab')); });
        });
        if ($('wsPaneDebug') && $('wsPaneDebug').classList.contains('active')) loadActions();

        // 自定义下拉：点空白处 / 按 Esc 收起
        document.addEventListener('click', function () { closeSelects(); });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeSelects(); });

        // 二级 tabs 滑块：初始定位 + 窗口尺寸变化后重新贴合
        movePill(true);
        var rsTimer = null;
        window.addEventListener('resize', function () {
            if (rsTimer) clearTimeout(rsTimer);
            rsTimer = setTimeout(function () { movePill(true); }, 120);
        });

        // tab 切换：进入本视图开始轮询，离开停止
        var sw = Array.prototype.slice.call(document.querySelectorAll('.view-switch'));
        var iv = null, upIv = null;
        function start() {
            requestAnimationFrame(function () { movePill(true); });
            if (!inited) { inited = true; loadConfig().then(pollWs); }
            else pollWs();
            if (iv) clearInterval(iv);
            iv = setInterval(pollWs, POLL_MS);
            if (upIv) clearInterval(upIv);
            // 每秒本地推进「运行时长」与每行「保持时长」，不等轮询，做到无延迟跳动
            upIv = setInterval(function () { tickWsUptime(); tickClientUptime(); }, 1000);
            if ($('wsPaneDebug') && $('wsPaneDebug').classList.contains('active')) loadActions();
        }
        function stop() {
            if (iv) { clearInterval(iv); iv = null; }
            if (upIv) { clearInterval(upIv); upIv = null; }
        }
        sw.forEach(function (b) {
            b.addEventListener('click', function () {
                if (b.getAttribute('data-view') === 'ws') start(); else stop();
            });
        });
        if (document.querySelector('.view-switch.active[data-view="ws"]')) start();
    }

    // 把 ILBB 下拉栏暴露出去，供其它页面（插件页的插件配置表单）复用同一套交互与样式
    window.ILBBSelect = {
        fieldId: fieldId,
        init: initSelects,          // 初始化 root 内的 .ilbb-select（含自动拉取 data-source 列表）
        loadAll: dynLoadAll,
        loadOne: dynLoad,
        closeAll: closeSelects,
        sync: syncSelects,
        srcLabel: srcLabel,
        fetchFriends: fetchFriendList,
        fetchGroups: fetchGroupList,
        fetchMembers: fetchMemberList
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();

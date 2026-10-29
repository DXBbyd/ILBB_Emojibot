/* ============================================================================
   ILBB · Web 会话（Chat Console）
   模拟私聊窗口：把消息真的交给机器人指令管线跑一遍，显示它要回复的图文。
   依赖后端 POST /api/bot/chat（见 app.py）。
   ========================================================================== */
(function () {
    'use strict';

    var root = document.getElementById('view-webchat');
    if (!root) { return; }

    // ---------------------------------------------------------------- 工具
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function kb(n) {
        if (!n) { return '0 B'; }
        if (n < 1024) { return n + ' B'; }
        if (n < 1024 * 1024) { return (n / 1024).toFixed(1) + ' KB'; }
        return (n / 1024 / 1024).toFixed(2) + ' MB';
    }
    function now() {
        var d = new Date(), p = function (x) { return (x < 10 ? '0' : '') + x; };
        return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }
    function api(url, opt) {
        return fetch(url, Object.assign({
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin'
        }, opt || {})).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) { throw new Error(j.error || ('HTTP ' + r.status)); }
                return j;
            });
        });
    }

    var toastEl = null, toastTimer = null;
    function toast(msg, bad) {
        if (!toastEl) {
            toastEl = document.createElement('div');
            toastEl.className = 'bot-toast';
            document.body.appendChild(toastEl);
        }
        toastEl.textContent = msg;
        toastEl.className = 'bot-toast show' + (bad ? ' bad' : '');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            toastEl.className = 'bot-toast' + (bad ? ' bad' : '');
        }, 2600);
    }

    // ---------------------------------------------------------------- 元素
    var el = {
        stream: document.getElementById('wcStream'),
        input: document.getElementById('wcInput'),
        send: document.getElementById('wcSendBtn'),
        file: document.getElementById('wcFile'),
        attach: document.getElementById('wcAttach'),
        attachList: document.getElementById('wcAttachList'),
        clear: document.getElementById('wcClearBtn'),
        seed: document.getElementById('wcSeedBtn'),
        quick: document.getElementById('wcQuick'),
        panel: document.getElementById('wcPanel'),
        slash: document.getElementById('wcSlashBtn'),
        panelClose: document.getElementById('wcPanelClose'),
        uid: document.getElementById('wcUid'),
        uname: document.getElementById('wcUname'),
        peerName: document.getElementById('wcPeerName'),
        peerAvatar: document.getElementById('wcPeerAvatar'),
        peerSub: document.getElementById('wcPeerSub'),
        statTotal: document.getElementById('wcStatTotal'),
        statImages: document.getElementById('wcStatImages'),
        statTexts: document.getElementById('wcStatTexts'),
        statMs: document.getElementById('wcStatMs'),
        statMem: document.getElementById('wcStatMem'),
        lastCmd: document.getElementById('wcLastCmd')
    };
    if (!el.stream || !el.input) { return; }

    // ---------------------------------------------------------------- 状态
    var SID_KEY = 'ilbb_chat_sid';
    var sid = '';
    try {
        sid = sessionStorage.getItem(SID_KEY) || '';
        if (!sid) {
            sid = 'wc-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
            sessionStorage.setItem(SID_KEY, sid);
        }
    } catch (e) { sid = 'wc-default'; }

    var attach = [];          // 待发送图片（dataURL）
    var busy = false;
    var started = false;
    var botName = '我在哔哩学习';
    var prefix = '/';
    var captureSeq = 0;       // 插件收件箱游标：只取比它新的消息
    var lastUid = '10001';
    var capTimer = null;

    // 机器人头像：沿用页面里已经渲染好的那张（与站点 favicon 同源）
    var AVATAR_SRC = (function () {
        var img = el.peerAvatar ? el.peerAvatar.querySelector('img') : null;
        return (img && img.getAttribute('src')) || '/static/favicon.jpg';
    })();
    function botAvatarHtml() {
        return '<div class="wc-avatar wc-avatar-bot">' +
            '<img class="wc-avatar-img" src="' + esc(AVATAR_SRC) + '" alt="">' +
            '</div>';
    }

    // ---------------------------------------------------------------- 渲染
    // 自动滚动：新消息、图片解码完成都会把会话窗贴到底部。
    // 用户手动往上翻时暂停贴底，回到底部附近再自动恢复。
    var stickBottom = true;

    function scrollBottom(force) {
        if (!el.stream) { return; }
        if (!force && !stickBottom) { return; }
        var to = function () {
            // 用即时滚动：CSS 的 scroll-behavior:smooth 在内容连续变高时追不上底部
            var prev = el.stream.style.scrollBehavior;
            el.stream.style.scrollBehavior = 'auto';
            el.stream.scrollTop = el.stream.scrollHeight;
            el.stream.style.scrollBehavior = prev;
        };
        to();                                   // 立刻贴一次
        if (window.requestAnimationFrame) {
            requestAnimationFrame(function () {
                to();
                requestAnimationFrame(to);      // 下一帧再贴，兜住布局回流
            });
        }
        setTimeout(to, 60);                     // 图片解码 / 字体回流
        setTimeout(to, 220);
    }

    el.stream.addEventListener('scroll', function () {
        var gap = el.stream.scrollHeight - el.stream.scrollTop - el.stream.clientHeight;
        stickBottom = gap < 90;
    });

    // 图片加载完成后气泡会变高，补一次贴底
    function watchImages(node) {
        if (!node || !node.querySelectorAll) { return; }
        var imgs = node.querySelectorAll('img');
        for (var i = 0; i < imgs.length; i++) {
            (function (img) {
                if (img.complete) { return; }
                img.addEventListener('load', function () { scrollBottom(); });
                img.addEventListener('error', function () { scrollBottom(); });
            })(imgs[i]);
        }
    }

    function bubble(role, html, meta) {
        var row = document.createElement('div');
        row.className = 'wc-msg ' + role;
        var av = role === 'me'
            ? '<div class="wc-avatar wc-avatar-me">我</div>'
            : botAvatarHtml();
        row.innerHTML = av +
            '<div class="wc-bubble-wrap">' +
            '<div class="wc-bubble">' + html + '</div>' +
            '<div class="wc-meta">' + esc(meta || now()) + '</div>' +
            '</div>';
        el.stream.appendChild(row);
        watchImages(row);
        scrollBottom();
        return row;
    }

    function sysLine(text) {
        var d = document.createElement('div');
        d.className = 'wc-sys';
        d.innerHTML = '<span>' + esc(text) + '</span>';
        el.stream.appendChild(d);
        scrollBottom();
    }

    function textHtml(t) {
        return esc(t).replace(/\n/g, '<br>');
    }

    function imageHtml(mime, data, bytes) {
        var src = 'data:' + mime + ';base64,' + data;
        return '<div class="wc-img-box">' +
            '<img class="wc-img" src="' + src + '" alt="机器人回复图片">' +
            '<div class="wc-img-bar">' +
            '<span>' + esc(mime.replace('image/', '').toUpperCase()) + ' · ' + kb(bytes) + '</span>' +
            '<a class="wc-img-dl" href="' + src + '" download="ilbb-' + Date.now() + '">下载</a>' +
            '</div></div>';
    }

    // ---- 任意消息格式：文件 / 语音 / 视频 / @ / 表情 / JSON ----
    // 插件在指令里（或后台线程里）用 call_api 发的东西，后端拦下来拆成条目，
    // 这里按 type 渲染，不认识的类型就退化成一行灰色标签，不会白屏。
    var ICO = {
        file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
        audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg>',
        video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10l6-3v10l-6-3z"/></svg>'
    };

    function dataUrl(mime, data) {
        return 'data:' + (mime || 'application/octet-stream') + ';base64,' + data;
    }

    function fileCard(kind, it) {
        var src = it.data ? dataUrl(it.mime, it.data) : (it.url || '');
        var fallback = kind === 'record' ? '语音消息' : (kind === 'video' ? '视频' : '文件');
        var name = it.name || fallback;
        var sub = (kind === 'record' ? '语音' : (kind === 'video' ? '视频' : (it.mime || '文件')))
            + (it.bytes ? ' · ' + kb(it.bytes) : '');
        var body = '<div class="wc-file-ico">' + (ICO[kind] || ICO.file) + '</div>' +
            '<div class="wc-file-main">' +
                '<div class="wc-file-name">' + esc(name) + '</div>' +
                '<div class="wc-file-sub">' + esc(sub) + '</div>' +
            '</div>';
        if (!src) { return '<div class="wc-file">' + body + '</div>'; }
        return '<a class="wc-file" href="' + src + '" download="' + esc(name) +
            '" target="_blank" rel="noopener">' + body +
            '<span class="wc-file-act">下载</span></a>';
    }

    function recordHtml(it) {
        var playable = /^audio\/(mpeg|ogg|wav|flac|mp4|x-m4a)$/i.test(it.mime || '');
        if (playable && it.data) {
            var src = dataUrl(it.mime, it.data);
            return '<div class="wc-media-box">' +
                '<audio class="wc-audio" controls src="' + src + '"></audio>' +
                '<div class="wc-img-bar"><span>语音 · ' + kb(it.bytes || 0) + '</span>' +
                '<a class="wc-img-dl" href="' + src + '" download="voice">下载</a></div></div>';
        }
        return fileCard('record', it);
    }

    function videoHtml(it) {
        if (it.data) {
            return '<video class="wc-media" controls src="' +
                dataUrl(it.mime, it.data) + '"></video>';
        }
        return fileCard('video', it);
    }

    function jsonHtml(it) {
        var text = String(it.data || '');
        try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (e) { /* 原样展示 */ }
        return '<details class="wc-json"><summary>卡片消息（JSON）</summary>' +
            '<pre>' + esc(text) + '</pre></details>';
    }

    function forwardHtml(it) {
        var nodes = it.nodes || [];
        var rows = nodes.map(function (n) {
            return '<div class="wc-fwd-node">' +
                '<div class="wc-fwd-name">' + esc(n.name || '消息') + '</div>' +
                '<div class="wc-fwd-text">' + textHtml(n.text || '') + '</div>' +
                '</div>';
        }).join('');
        var count = it.count || nodes.length;
        return '<details class="wc-fwd"><summary>合并转发 · ' + count + ' 条</summary>' +
            '<div class="wc-fwd-body">' + rows + '</div></details>';
    }

    function itemHtml(it) {
        switch (it.type) {
        case 'text': return textHtml(it.text || '');
        case 'image':
            if (it.data) { return imageHtml(it.mime || 'image/png', it.data, it.bytes || 0); }
            if (it.url) {
                return '<div class="wc-img-box"><img class="wc-img" src="' +
                    esc(it.url) + '" alt="图片"></div>';
            }
            return '<span class="wc-face">[图片]</span>';
        case 'file': return fileCard('file', it);
        case 'record': return recordHtml(it);
        case 'video': return videoHtml(it);
        case 'at': return '<span class="wc-at">@' + esc(it.name || it.qq || '') + '</span>';
        case 'face': return '<span class="wc-face">[表情 ' + esc(it.id || '') + ']</span>';
        case 'reply': return '<span class="wc-quote">[引用消息]</span>';
        case 'json': return jsonHtml(it);
        case 'forward': return forwardHtml(it);
        default: return '<span class="wc-face">[' + esc(it.type || '未知') + ']</span>';
        }
    }

    // 一次 call_api 里的多个 segment 合到同一个气泡里（@ + 文本 + 图 才自然）
    function renderCaptured(items) {
        items = items || [];
        var groups = [];
        items.forEach(function (it) {
            var last = groups[groups.length - 1];
            if (!last || last.mid !== it.mid) {
                last = { mid: it.mid, list: [] };
                groups.push(last);
            }
            last.list.push(it);
        });
        groups.forEach(function (g) {
            var html = g.list.map(itemHtml).join('');
            if (html) { bubble('bot', html, now() + ' · 插件消息'); }
        });
    }

    function pollCapture() {
        if (!started) { return; }
        api('/api/bot/chat/capture?uid=' + encodeURIComponent(lastUid) +
            '&since=' + captureSeq).then(function (j) {
            if (j.seq != null) { captureSeq = j.seq; }
            if (j.items && j.items.length) { renderCaptured(j.items); }
        }).catch(function () { /* 网络抖动忽略，下次继续 */ });
    }

    function startCapture() {
        if (capTimer || !started) { return; }
        capTimer = setInterval(pollCapture, 2000);
        // 先把游标对到当前尾部，避免把上一次会话遗留的消息倒出来
        api('/api/bot/chat/capture?uid=' + encodeURIComponent(lastUid) + '&since=999999999')
            .then(function (j) { if (j.seq != null) { captureSeq = j.seq; } })
            .catch(function () { /* 忽略 */ });
    }

    function stopCapture() {
        if (capTimer) { clearInterval(capTimer); capTimer = null; }
    }

    function typing() {
        var row = document.createElement('div');
        row.className = 'wc-msg bot wc-typing-row';
        row.innerHTML = botAvatarHtml() +
            '<div class="wc-bubble wc-typing"><i></i><i></i><i></i></div>';
        el.stream.appendChild(row);
        scrollBottom();
        return row;
    }

    function renderAttach() {
        if (!attach.length) {
            el.attach.classList.add('hidden');
            el.attachList.innerHTML = '';
            return;
        }
        el.attach.classList.remove('hidden');
        el.attachList.innerHTML = attach.map(function (a, i) {
            return '<div class="wc-chip" data-i="' + i + '">' +
                '<img src="' + a + '" alt="">' +
                '<button type="button" class="wc-chip-x" data-i="' + i + '" title="移除">×</button>' +
                '</div>';
        }).join('');
    }

    // ---------------------------------------------------------------- 图片预览
    // 点会话里的图 → 全屏看；滚轮 / 双指缩放，拖动平移，双击复位，Esc 关闭。
    var lb = null, lbImg = null, lbPct = null, lbStage = null;
    var view = { s: 1, x: 0, y: 0 };
    var pointers = {}, dragStart = null, pinchStart = null;

    function lbApply() {
        if (!lbImg) { return; }
        lbImg.style.transform = 'translate(' + view.x + 'px,' + view.y +
            'px) scale(' + view.s + ')';
        if (lbPct) { lbPct.textContent = Math.round(view.s * 100) + '%'; }
    }

    function lbReset() {
        view = { s: 1, x: 0, y: 0 };
        lbApply();
    }

    function lbZoom(factor, cx, cy) {
        var s0 = view.s;
        var s1 = Math.max(0.2, Math.min(8, s0 * factor));
        if (Math.abs(s1 - s0) < 0.0005) { return; }
        var rect = lbStage.getBoundingClientRect();
        var px = (cx == null ? rect.width / 2 : cx - rect.left - rect.width / 2);
        var py = (cy == null ? rect.height / 2 : cy - rect.top - rect.height / 2);
        view.x = px - (px - view.x) * (s1 / s0);
        view.y = py - (py - view.y) * (s1 / s0);
        view.s = s1;
        lbApply();
    }

    function lbOpen(src, alt) {
        lbEnsure();
        lbReset();
        lbImg.src = src;
        lbImg.alt = alt || '图片预览';
        lb.classList.remove('hidden');
        document.body.classList.add('wc-lb-open');
    }

    function lbClose() {
        if (!lb) { return; }
        lb.classList.add('hidden');
        document.body.classList.remove('wc-lb-open');
        lbImg.removeAttribute('src');
        if (dragStart || pinchStart) { dragStart = pinchStart = null; pointers = {}; }
    }

    function lbPointerList() {
        return Object.keys(pointers).map(function (k) { return pointers[k]; });
    }

    function onLbDown(e) {
        if (e.target.closest && e.target.closest('.wc-lb-btn')) { return; }
        if (!e.isPrimary && Object.keys(pointers).length >= 2) { return; }
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var pts = lbPointerList();
        if (pts.length === 1) {
            dragStart = { x: e.clientX - view.x, y: e.clientY - view.y };
            lbImg.style.cursor = 'grabbing';
        } else if (pts.length === 2) {
            var dx = pts[0].x - pts[1].x, dy = pts[0].y - pts[1].y;
            pinchStart = { dist: Math.sqrt(dx * dx + dy * dy) || 1, s: view.s };
            dragStart = null;
        }
        try { lbStage.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
    }

    function onLbMove(e) {
        if (!pointers[e.pointerId]) { return; }
        pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
        var pts = lbPointerList();
        if (pts.length >= 2 && pinchStart) {
            var dx = pts[0].x - pts[1].x, dy = pts[0].y - pts[1].y;
            var dist = Math.sqrt(dx * dx + dy * dy) || 1;
            view.s = Math.max(0.2, Math.min(8, pinchStart.s * dist / pinchStart.dist));
            lbApply();
            return;
        }
        if (dragStart) {
            view.x = e.clientX - dragStart.x;
            view.y = e.clientY - dragStart.y;
            lbApply();
        }
    }

    function onLbUp(e) {
        delete pointers[e.pointerId];
        var pts = lbPointerList();
        if (pts.length < 2) { pinchStart = null; }
        if (pts.length === 1) {
            dragStart = { x: pts[0].x - view.x, y: pts[0].y - view.y };
        } else if (!pts.length) {
            dragStart = null;
            lbImg.style.cursor = 'grab';
        }
    }

    function lbEnsure() {
        if (lb) { return; }
        lb = document.createElement('div');
        lb.className = 'wc-lb hidden';
        lb.innerHTML =
            '<div class="wc-lb-bar">' +
                '<span class="wc-lb-pct">100%</span>' +
                '<button type="button" class="wc-lb-btn" data-act="out" title="缩小">−</button>' +
                '<button type="button" class="wc-lb-btn" data-act="in" title="放大">＋</button>' +
                '<button type="button" class="wc-lb-btn" data-act="fit" title="还原大小">1:1</button>' +
                '<button type="button" class="wc-lb-btn" data-act="close" title="关闭 (Esc)">关闭</button>' +
            '</div>' +
            '<div class="wc-lb-stage"><img class="wc-lb-img" alt="图片预览"></div>' +
            '<div class="wc-lb-hint">滚轮 / 双指缩放 · 拖动平移 · 双击复位 · Esc 关闭</div>';
        document.body.appendChild(lb);
        lbImg = lb.querySelector('.wc-lb-img');
        lbPct = lb.querySelector('.wc-lb-pct');
        lbStage = lb.querySelector('.wc-lb-stage');

        lb.addEventListener('click', function (e) {
            var btn = e.target.closest ? e.target.closest('.wc-lb-btn') : null;
            if (btn) {
                var act = btn.getAttribute('data-act');
                if (act === 'close') { lbClose(); }
                else if (act === 'in') { lbZoom(1.35); }
                else if (act === 'out') { lbZoom(1 / 1.35); }
                else { lbReset(); }
                return;
            }
            if (e.target === lb || e.target === lbStage) { lbClose(); }
        });
        lb.addEventListener('wheel', function (e) {
            e.preventDefault();
            lbZoom(Math.exp(-e.deltaY / 420), e.clientX, e.clientY);
        }, { passive: false });
        lb.addEventListener('dblclick', function (e) {
            e.preventDefault();
            if (view.s > 1.05) { lbReset(); } else { lbZoom(2.5, e.clientX, e.clientY); }
        });
        lb.addEventListener('pointerdown', onLbDown);
        lb.addEventListener('pointermove', onLbMove);
        lb.addEventListener('pointerup', onLbUp);
        lb.addEventListener('pointercancel', onLbUp);
    }

    // 会话里任意一张图（机器人回图 / 我自己发的图）都能点开
    el.stream.addEventListener('click', function (e) {
        var img = e.target.closest ? e.target.closest('img.wc-img') : null;
        if (!img) { return; }
        e.preventDefault();
        lbOpen(img.getAttribute('src'), img.getAttribute('alt'));
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && lb && !lb.classList.contains('hidden')) {
            lbClose();
        }
    });

    function setStats(st) {
        if (!st) { return; }
        if (el.statTotal) { el.statTotal.textContent = st.total || 0; }
        if (el.statImages) { el.statImages.textContent = st.images || 0; }
        if (el.statTexts) { el.statTexts.textContent = st.texts || 0; }
        if (el.statMs) { el.statMs.textContent = st.ms ? (st.ms + ' ms') : '—'; }
        if (el.lastCmd) {
            el.lastCmd.textContent = st.last ? ('最近一条：' + prefix + st.last) : '还没有发过指令。';
        }
    }

    function setMem(n) {
        if (el.statMem) { el.statMem.textContent = n || 0; }
    }

    // ---------------------------------------------------------------- 发送
    function send(text) {
        text = String(text == null ? el.input.value : text).trim();
        if (busy) { return; }
        if (!text && !attach.length) { return; }

        var uid = (el.uid && el.uid.value.trim()) || '10001';
        var uname = (el.uname && el.uname.value.trim()) || '调试用户';
        lastUid = uid;
        startCapture();
        var imgs = attach.slice();
        var shown = text;

        // 附件作为一条图片消息先发出去
        if (imgs.length) {
            imgs.forEach(function (src) {
                bubble('me', '<img class="wc-img" src="' + src + '" alt="我发送的图片">',
                    now());
            });
        }
        if (shown) {
            bubble('me', textHtml(shown), now());
        }

        el.input.value = '';
        attach = [];
        renderAttach();

        busy = true;
        el.send.disabled = true;
        var tp = typing();

        api('/api/bot/chat', {
            method: 'POST',
            body: JSON.stringify({
                sid: sid, text: text, images: imgs,
                uid: uid, uname: uname
            })
        }).then(function (j) {
            tp.remove();
            if (j.capture_seq != null) { captureSeq = j.capture_seq; }
            var reps = j.replies || [];
            var caps = j.captured || [];
            if (!reps.length && !caps.length) {
                sysLine(j.skipped ? ('机器人忽略了这条消息（' + j.skipped + '）') : '机器人没有回复。');
            } else {
                reps.forEach(function (r, i) {
                    var meta = now() + (i === 0 && j.cost_ms != null ? ' · ' + j.cost_ms + ' ms' : '');
                    if (r.type === 'image') {
                        bubble('bot', imageHtml(r.mime, r.data, r.bytes), meta);
                    } else {
                        bubble('bot', textHtml(r.text), meta);
                    }
                });
                // 指令里直接通过 call_api 发的消息（插件常用），按格式逐条渲染
                renderCaptured(caps);
            }
            setMem(j.session && j.session.images);
            setStats(j.stats);
        }).catch(function (e) {
            tp.remove();
            bubble('bot', '<span class="wc-err">指令执行失败：' + esc(e.message || e) + '</span>', now());
            toast('指令执行失败：' + (e.message || e), true);
        }).then(function () {
            busy = false;
            el.send.disabled = false;
            if (el.input) { el.input.focus(); }
        });
    }

    // ---------------------------------------------------------------- 快捷指令
    var FALLBACK_QUICK = [
        { usage: '/help', name: '图片菜单' },
        { usage: '/meme', name: 'Meme 帮助' },
        { usage: '/meme help 12', name: '素材详情' },
        { usage: '/meme list', name: '素材列表' },
        { usage: '/pair', name: '配对卡帮助' },
        { usage: '/pair 10001', name: '配对卡生成' }
    ];

    function withPrefix(usage) {
        var u = String(usage || '');
        var p = prefix || '/';
        if (!u) { return u; }
        // catalog 里的 usage 可能写死 /，统一换成后台配置的前缀
        return p + u.replace(/^[\/#\-]+/, '');
    }

    function renderQuick(list) {
        el.quick.innerHTML = (list || []).map(function (c) {
            var u = withPrefix(c.usage);
            return '<button type="button" class="bot-quick-chip" data-cmd="' + esc(u) + '"' +
                ' title="' + esc(c.desc || c.name || '') + '">' +
                '<b>' + esc(u) + '</b><span>' + esc(c.name || '') + '</span></button>';
        }).join('');
    }

    // ---------------------------------------------------------------- 斜杠面板
    // 原右侧栏（常用指令 / 模拟身份 / 会话信息）收进一个小面板，由输入框右侧的 / 开关
    function panelOpen() {
        if (!el.panel) { return; }
        el.panel.classList.remove('hidden');
        if (el.slash) {
            el.slash.classList.add('on');
            el.slash.setAttribute('aria-expanded', 'true');
        }
    }
    function panelClose() {
        if (!el.panel || el.panel.classList.contains('hidden')) { return; }
        el.panel.classList.add('hidden');
        if (el.slash) {
            el.slash.classList.remove('on');
            el.slash.setAttribute('aria-expanded', 'false');
        }
    }
    function panelToggle() {
        if (!el.panel) { return; }
        if (el.panel.classList.contains('hidden')) { panelOpen(); } else { panelClose(); }
    }

    if (el.slash) {
        el.slash.addEventListener('click', function (e) {
            e.stopPropagation();     // 别让外部点击监听立刻把它关掉
            panelToggle();
        });
    }
    if (el.panelClose) { el.panelClose.addEventListener('click', panelClose); }
    document.addEventListener('click', function (e) {
        if (!el.panel || el.panel.classList.contains('hidden')) { return; }
        if (el.panel.contains(e.target)) { return; }
        if (el.slash && el.slash.contains(e.target)) { return; }
        panelClose();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { panelClose(); }
    });

    // ---------------------------------------------------------------- 示例图
    function makeSampleImage() {
        var c = document.createElement('canvas');
        c.width = 480; c.height = 480;
        var g = c.getContext('2d');
        var grd = g.createLinearGradient(0, 0, 480, 480);
        grd.addColorStop(0, '#c96442');
        grd.addColorStop(1, '#f0c8a8');
        g.fillStyle = grd;
        g.fillRect(0, 0, 480, 480);
        g.fillStyle = 'rgba(255,255,255,.92)';
        g.beginPath();
        g.arc(240, 190, 92, 0, Math.PI * 2);
        g.fill();
        g.beginPath();
        g.ellipse(240, 430, 150, 120, 0, Math.PI, Math.PI * 2);
        g.fill();
        g.fillStyle = 'rgba(255,255,255,.95)';
        g.font = 'bold 30px "Microsoft YaHei", sans-serif';
        g.textAlign = 'center';
        g.fillText('ILBB 示例素材', 240, 452);
        return c.toDataURL('image/png');
    }

    // ---------------------------------------------------------------- 绑定
    el.send.addEventListener('click', function () { send(); });

    el.input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            send();
        }
    });

    el.file.addEventListener('change', function () {
        var files = Array.prototype.slice.call(el.file.files || []);
        el.file.value = '';
        if (!files.length) { return; }
        var left = 3 - attach.length;
        if (left <= 0) { toast('最多一次附带 3 张素材', true); return; }
        files.slice(0, left).forEach(function (f) {
            if (!/^image\//.test(f.type)) { toast('只能附带图片文件', true); return; }
            if (f.size > 8 * 1024 * 1024) { toast('「' + f.name + '」超过 8 MB，已跳过', true); return; }
            var rd = new FileReader();
            rd.onload = function () {
                if (attach.length >= 3) { toast('最多一次附带 3 张素材', true); return; }
                attach.push(String(rd.result));
                renderAttach();
            };
            rd.readAsDataURL(f);
        });
    });

    el.attachList.addEventListener('click', function (e) {
        var t = e.target;
        if (t && t.classList.contains('wc-chip-x')) {
            var i = parseInt(t.getAttribute('data-i'), 10);
            if (i >= 0) { attach.splice(i, 1); renderAttach(); }
        }
    });

    el.seed.addEventListener('click', function () {
        if (attach.length >= 3) { toast('最多一次附带 3 张素材', true); return; }
        attach.push(makeSampleImage());
        renderAttach();
        toast('已加入 1 张示例素材，直接发 /meme 素材名 就能用上');
    });

    el.clear.addEventListener('click', function () {
        api('/api/bot/chat', {
            method: 'POST',
            body: JSON.stringify({ sid: sid, reset: true })
        }).catch(function () { /* 忽略 */ });
        el.stream.innerHTML = '<div class="wc-daybreak"><span>今天</span></div>';
        attach = [];
        renderAttach();
        setMem(0);
        stickBottom = true;
        sysLine('会话已清空，可以重新开始测试。');
    });

    el.quick.addEventListener('click', function (e) {
        var chip = e.target.closest ? e.target.closest('.bot-quick-chip') : null;
        if (!chip) { return; }
        // 只填入输入框，不直接发送；改完再自己按发送
        if (el.input) {
            el.input.value = chip.getAttribute('data-cmd') || '';
            el.input.focus();
        }
        panelClose();
    });

    // ---------------------------------------------------------------- 启动
    function loadStatus() {
        return api('/api/bot/status').then(function (j) {
            var st = j.stats || {};
            botName = st.name || '我在哔哩学习';
            prefix = st.prefix || '/';
            if (el.peerName) { el.peerName.textContent = botName; }
            if (el.peerAvatar) {
                el.peerAvatar.innerHTML = '<img class="wc-avatar-img" src="' +
                    esc(AVATAR_SRC) + '" alt="">';
            }
            if (el.peerSub) {
                el.peerSub.textContent = '私聊调试 · ' +
                    (st.enabled ? '指令已启用' : '指令已禁用') +
                    ' · ' + (st.memes || 0) + ' 款素材 · 前缀 ' + prefix;
            }
            var quick = (j.catalog || []).map(function (c) {
                return { usage: c.usage, name: c.name, desc: c.desc };
            });
            // 书源插件：搜索 + 翻页，方便在 Web 会话里直接验证
            if (!quick.some(function (c) { return String(c.usage).indexOf('搜书') >= 0; })) {
                quick.push({ usage: '/搜书 剑来', name: '书源搜索' });
            }
            if (!quick.some(function (c) { return String(c.usage).indexOf('翻页') >= 0; })) {
                quick.push({ usage: '/翻页', name: '搜书下一页' });
            }
            renderQuick(quick);
            return api('/api/bot/chat/stats').then(function (j2) {
                setStats(j2.stats);
            }).catch(function () { /* 忽略 */ });
        }).catch(function () {
            renderQuick(FALLBACK_QUICK);
            if (el.peerSub) { el.peerSub.textContent = '私聊调试 · 状态读取失败'; }
        });
    }

    function greet() {
        if (el.stream.querySelector('.wc-msg')) { return; }
        var hour = new Date().getHours();
        var hi = hour < 6 ? '夜深了' : (hour < 11 ? '早上好' : (hour < 14 ? '中午好' : (hour < 19 ? '下午好' : '晚上好')));
        bubble('bot',
            '这里是 <b>' + esc(botName) + '</b> 的调试会话。<br>' +
            '直接发指令就能看到真实回复：<code class="ws-code">' + esc(prefix) + 'help</code> 看菜单、' +
            '<code class="ws-code">' + esc(prefix) + 'meme list</code> 查素材、' +
            '<code class="ws-code">' + esc(prefix) + 'pair 10001</code> 试配对卡。<br>' +
            '需要图片素材的表情，可以先点左下角 <b>＋</b> 附带图片（或点右上「示例图」）。',
            hi + ' · 调试会话');
        sysLine('提示：这里不会真的发消息到 QQ，只验证指令能不能跑通。');
    }

    function start() {
        if (el.uid && el.uid.value.trim()) { lastUid = el.uid.value.trim(); }
        if (started) {
            loadStatus();
            startCapture();
            return;
        }
        started = true;
        loadStatus().then(greet);
        startCapture();
        if (el.input) { el.input.focus(); }
    }

    function stop() {
        panelClose();
        stopCapture();
        /* 会话状态留在后端，无需清理 */
    }

    // 视图切换：进入才初始化，离开停掉
    var switches = document.querySelectorAll('.view-switch');
    Array.prototype.forEach.call(switches, function (b) {
        b.addEventListener('click', function () {
            if (b.getAttribute('data-view') === 'webchat') { start(); } else { stop(); }
        });
    });
    var active = document.querySelector('.view-switch.active');
    if (active && active.getAttribute('data-view') === 'webchat') { start(); }
})();

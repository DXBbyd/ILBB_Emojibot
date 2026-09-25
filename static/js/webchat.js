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
            var reps = j.replies || [];
            if (!reps.length) {
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

    function renderQuick(list) {
        el.quick.innerHTML = (list || []).map(function (c) {
            return '<button type="button" class="bot-quick-chip" data-cmd="' + esc(c.usage) + '"' +
                ' title="' + esc(c.desc || c.name || '') + '">' +
                '<b>' + esc(c.usage) + '</b><span>' + esc(c.name || '') + '</span></button>';
        }).join('');
    }

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
        var cmd = chip.getAttribute('data-cmd') || '';
        if (el.input) { el.input.value = cmd; }
        send(cmd);
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
            renderQuick((j.catalog || []).map(function (c) {
                return { usage: c.usage, name: c.name, desc: c.desc };
            }));
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
        if (started) {
            loadStatus();
            return;
        }
        started = true;
        loadStatus().then(greet);
        if (el.input) { el.input.focus(); }
    }

    function stop() { /* 会话状态留在后端，无需清理 */ }

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

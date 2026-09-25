/* ==========================================================================
   指令中心（Bot Commands） —— /help · /meme · /pair
   与 ws.js 同风格：进入视图才开始拉数据，离开即停止。
   ========================================================================== */
(function () {
    'use strict';

    var root = document.getElementById('view-bot');
    if (!root) return;

    var $ = function (id) { return document.getElementById(id); };

    var tabsWrap = $('botTabs');
    var pill = $('botTabsPill');
    var hint = $('botTabsHint');
    var warnBox = $('botWarn');
    var statusGrid = $('botStatusGrid');
    var catalogList = $('botCatalogList');
    var quickWrap = $('botQuickCmds');
    var previewInput = $('botPreviewInput');
    var previewBtn = $('botPreviewBtn');
    var previewClear = $('botPreviewClearBtn');
    var previewStage = $('botPreviewStage');
    var memeSearch = $('botMemeSearch');
    var memeRefresh = $('botMemeRefreshBtn');
    var memeGrid = $('botMemeGrid');
    var memeCount = $('botMemeCount');
    var prefixHint = $('botPrefixHint');

    var inited = false;
    var memesCache = null;
    var previewing = false;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function kb(n) {
        n = Number(n) || 0;
        if (n < 1024) return n + ' B';
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
        return (n / 1024 / 1024).toFixed(2) + ' MB';
    }

    function toast(msg, bad) {
        var t = document.createElement('div');
        t.className = 'bot-toast' + (bad ? ' bad' : '');
        t.textContent = msg;
        document.body.appendChild(t);
        requestAnimationFrame(function () { t.classList.add('show'); });
        setTimeout(function () {
            t.classList.remove('show');
            setTimeout(function () { t.remove(); }, 380);
        }, 2200);
    }

    /* ---------------- 二级 tab 滑块 ---------------- */
    function movePill() {
        if (!tabsWrap || !pill) return;
        var active = tabsWrap.querySelector('.ws-tab.active');
        if (!active) return;
        pill.style.width = active.offsetWidth + 'px';
        pill.style.transform = 'translateX(' + active.offsetLeft + 'px)';
    }

    function selectTab(name) {
        if (!tabsWrap) return;
        tabsWrap.querySelectorAll('.ws-tab').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-bot-tab') === name);
        });
        root.querySelectorAll('.ws-pane').forEach(function (p) {
            p.classList.toggle('active', p.id === 'botPane' + name.charAt(0).toUpperCase() + name.slice(1));
        });
        movePill();
        if (name === 'memes' && !memesCache) loadMemes('');
    }

    if (tabsWrap) {
        tabsWrap.querySelectorAll('.ws-tab').forEach(function (b) {
            b.addEventListener('click', function () {
                selectTab(b.getAttribute('data-bot-tab'));
            });
        });
        window.addEventListener('resize', function () { movePill(); });
    }

    /* ---------------- 状态 + 指令目录 ---------------- */
    function statCard(title, rows) {
        var html = '<div class="status-card"><h3>' + esc(title) + '</h3>';
        rows.forEach(function (r) {
            html += '<div class="status-row"><span class="k">' + esc(r[0]) + '</span>' +
                '<span class="v">' + r[1] + '</span></div>';
        });
        return html + '</div>';
    }

    function pillTag(text, tone) {
        return '<span class="bot-tag' + (tone ? ' ' + tone : '') + '">' + esc(text) + '</span>';
    }

    function renderStatus(data) {
        var st = data.stats || {};
        var on = !!st.enabled;
        var installed = !!st.installed;
        var wsRun = !!st.ws_running;

        statusGrid.innerHTML = [
            statCard('指令框架', [
                ['状态', on
                    ? (installed ? '<span class="bot-ok">已启用</span>' : '<span class="bot-warn">已启用 · 未注册</span>')
                    : '<span class="bot-off">已关闭</span>'],
                ['前缀', '<code class="ws-code">' + esc(st.prefix || '/') + '</code>'],
                ['机器人', esc(st.name || '-')],
                ['群聊需 @', st.group_need_at ? '是' : '否'],
                ['私聊开关', st.allow_private ? '开启' : '关闭'],
                ['冷却', (st.cooldown || 0) + ' 秒'],
            ]),
            statCard('运行统计', [
                ['累计指令', '<b>' + (st.total || 0) + '</b>'],
                ['成功 / 失败', '<span class="bot-ok">' + (st.ok || 0) + '</span> / <span class="bot-err">' + (st.fail || 0) + '</span>'],
                ['最近指令', st.last ? '<code class="ws-code">' + esc(st.last) + '</code>' : '—'],
                ['最近时间', st.last_at ? fmtTime(st.last_at) : '—'],
            ]),
            statCard('依赖与连接', [
                ['WS 服务器', wsRun ? '<span class="bot-ok">运行中</span>' : '<span class="bot-warn">未运行</span>'],
                ['meme 素材', (st.memes || 0) + ' 款'],
                ['列表每页', (st.list_page || 12) + ' 条'],
                ['渲染层', 'bot_render ✓'],
            ]),
        ].join('');

        if (!on || !wsRun) {
            var msgs = [];
            if (!on) msgs.push('指令总开关关闭（<code class="ws-code">BOT_ENABLED=false</code>），机器人不会响应任何指令。');
            if (!wsRun) msgs.push('WS 服务器未运行，NapCat 无法连入，指令不会到达。请到「WS 服务器」页启动。');
            warnBox.className = 'ws-notice warn';
            warnBox.innerHTML = msgs.join('<br>');
        } else {
            warnBox.className = 'hidden';
            warnBox.innerHTML = '';
        }

        var n = (data.catalog || []).length;
        hint.textContent = on
            ? '前缀 ' + (st.prefix || '/') + ' · ' + (st.memes || 0) + ' 款素材 · ' + n + ' 条指令'
            : '指令框架已关闭';

        if (prefixHint) prefixHint.textContent = (st.prefix || '/') + 'help';
        renderCatalog(data.catalog || []);
    }

    function renderCatalog(items) {
        if (!items.length) {
            catalogList.innerHTML = '<p class="console-empty">没有可用指令</p>';
            quickWrap.innerHTML = '';
            return;
        }
        var html = '';
        items.forEach(function (c) {
            html += '<button type="button" class="bot-cmd-row" data-cmd="' + esc(c.usage) + '">' +
                '<span class="bot-cmd-main">' +
                '<span class="bot-cmd-name">' + esc(c.name) + '</span>' +
                '<code class="bot-cmd-usage">' + esc(c.usage) + '</code>' +
                '</span>' +
                '<span class="bot-cmd-desc">' + esc(c.desc) + '</span>' +
                '</button>';
        });
        catalogList.innerHTML = html;
        catalogList.querySelectorAll('.bot-cmd-row').forEach(function (row) {
            row.addEventListener('click', function () {
                selectTab('preview');
                previewInput.value = row.getAttribute('data-cmd').replace(/^\//, '');
                runPreview();
            });
        });

        var q = '';
        items.slice(0, 6).forEach(function (c) {
            q += '<button type="button" class="bot-quick-chip" data-cmd="' + esc(c.usage) + '">' +
                esc(c.usage) + '</button>';
        });
        quickWrap.innerHTML = q;
        quickWrap.querySelectorAll('.bot-quick-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                previewInput.value = chip.getAttribute('data-cmd').replace(/^\//, '');
                runPreview();
            });
        });
    }

    function fmtTime(ts) {
        var d = new Date(Number(ts) * 1000);
        var p = function (n) { return (n < 10 ? '0' : '') + n; };
        return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
    }

    async function loadStatus(silent) {
        try {
            var res = await fetch('/api/bot/status');
            var data = await res.json();
            if (!data.ok) {
                if (!silent) toast('读取指令框架状态失败：' + (data.error || ''), true);
                return;
            }
            renderStatus(data);
        } catch (e) {
            if (!silent) toast('读取指令框架状态失败', true);
        }
    }

    /* ---------------- 干跑预览 ---------------- */
    function loadingStage(text) {
        previewStage.innerHTML =
            '<div class="bot-preview-loading"><span class="bot-spin"></span>' + esc(text || '正在渲染…') + '</div>';
    }

    async function runPreview() {
        if (previewing) return;
        var cmd = (previewInput.value || '').trim();
        if (!cmd) { toast('先输入一条指令', true); previewInput.focus(); return; }
        previewing = true;
        previewBtn.disabled = true;
        loadingStage('正在渲染 ' + cmd + ' …');
        var t0 = Date.now();
        try {
            var res = await fetch('/api/bot/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cmd: cmd }),
            });
            var data = await res.json();
            if (!data.ok) throw new Error(data.error || '渲染失败');
            renderPreview(data, Date.now() - t0);
        } catch (e) {
            previewStage.innerHTML = '<div class="bot-preview-error">渲染失败：' + esc(e.message || e) + '</div>';
        } finally {
            previewing = false;
            previewBtn.disabled = false;
        }
    }

    function renderPreview(data, ms) {
        var imgs = data.images || [];
        var texts = data.texts || [];
        var html = '<div class="bot-preview-meta">' +
            '<code class="ws-code">/' + esc(data.cmd) + '</code>' +
            pillTag(imgs.length + ' 张图', 'blue') +
            pillTag('共 ' + kb(data.bytes) ) +
            pillTag(ms + ' ms') +
            '</div>';

        if (!imgs.length && !texts.length) {
            html += '<div class="bot-preview-empty"><div>这条指令没有产生任何回复内容。</div></div>';
            previewStage.innerHTML = html;
            return;
        }

        imgs.forEach(function (im, i) {
            var src = 'data:' + im.mime + ';base64,' + im.data;
            html += '<div class="bot-preview-item">' +
                '<img class="bot-preview-img" src="' + src + '" alt="预览图 ' + (i + 1) + '">' +
                '<div class="bot-preview-bar">' +
                '<span>' + esc(im.mime) + ' · ' + kb(im.bytes) + '</span>' +
                '<a class="ws-btn ws-btn-sm" href="' + src + '" download="ilbb-' +
                esc(String(data.cmd).replace(/[^\w\u4e00-\u9fa5-]+/g, '_')) + '-' + (i + 1) + '.png">下载</a>' +
                '</div></div>';
        });

        if (texts.length) {
            html += '<div class="bot-preview-texts">';
            texts.forEach(function (t) {
                html += '<div class="bot-preview-text">' + esc(t) + '</div>';
            });
            html += '</div>';
        }
        previewStage.innerHTML = html;
    }

    /* ---------------- 素材索引 ---------------- */
    function renderMemes(list) {
        if (!list.length) {
            memeGrid.innerHTML = '<p class="console-empty">没有匹配的素材</p>';
            return;
        }
        var html = '';
        list.forEach(function (m) {
            var kw = (m.keywords || []).slice(0, 4);
            var need = '图 ' + m.min_images + '~' + m.max_images +
                (m.max_texts ? ' · 文 ' + m.min_texts + '~' + m.max_texts : '');
            html += '<button type="button" class="bot-meme-card" data-id="' + m.id + '">' +
                '<span class="bot-meme-top">' +
                '<span class="bot-meme-id">#' + m.id + '</span>' +
                '<span class="bot-meme-key">' + esc(m.key) + '</span>' +
                '</span>' +
                '<span class="bot-meme-kw">' + (kw.length ? esc(kw.join(' / ')) : '—') + '</span>' +
                '<span class="bot-meme-meta">' + esc(need) + '</span>' +
                (m.presets && m.presets.length
                    ? '<span class="bot-meme-presets">' + pillTag('预设 ' + m.presets.length, 'blue') + '</span>'
                    : '<span class="bot-meme-presets"><span class="bot-tag">无数值预设</span></span>') +
                '</button>';
        });
        memeGrid.innerHTML = html;
        memeGrid.querySelectorAll('.bot-meme-card').forEach(function (card) {
            card.addEventListener('click', function () {
                selectTab('preview');
                previewInput.value = 'meme help ' + card.getAttribute('data-id');
                runPreview();
            });
        });
    }

    async function loadMemes(q) {
        memeGrid.innerHTML = '<p class="console-empty">加载中...</p>';
        try {
            var res = await fetch('/api/bot/memes' + (q ? '?q=' + encodeURIComponent(q) : ''));
            var data = await res.json();
            if (!data.ok) throw new Error(data.error || '');
            memesCache = data.memes || [];
            memeCount.textContent = '共 ' + data.count + ' 款 · 列表每页 ' + data.page + ' 条 · 点击卡片预览详情图';
            renderMemes(memesCache);
        } catch (e) {
            memeGrid.innerHTML = '<p class="console-empty">加载失败：' + esc(e.message || e) + '</p>';
        }
    }

    /* ---------------- 交互绑定 ---------------- */
    if (previewBtn) previewBtn.addEventListener('click', runPreview);
    if (previewInput) {
        previewInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); runPreview(); }
        });
    }
    if (previewClear) {
        previewClear.addEventListener('click', function () {
            previewInput.value = '';
            previewStage.innerHTML = '<div class="bot-preview-empty">' +
                '<div class="bot-preview-empty-ico">🖼</div>' +
                '<div>输入一条指令后点击「生成预览」，这里会显示机器人回复的图片与文字。</div></div>';
            previewInput.focus();
        });
    }

    var memeTimer = null;
    if (memeSearch) {
        memeSearch.addEventListener('input', function () {
            if (memeTimer) clearTimeout(memeTimer);
            var q = memeSearch.value.trim();
            memeTimer = setTimeout(function () { loadMemes(q); }, 240);
        });
    }
    if (memeRefresh) memeRefresh.addEventListener('click', function () { loadMemes(memeSearch.value.trim()); });

    /* ---------------- 视图联动 ---------------- */
    function start() {
        requestAnimationFrame(movePill);
        if (!inited) {
            inited = true;
            loadStatus();
            selectTab('catalog');
        } else {
            loadStatus(true);
        }
    }

    var switches = Array.prototype.slice.call(document.querySelectorAll('.view-switch'));
    switches.forEach(function (b) {
        b.addEventListener('click', function () {
            if (b.getAttribute('data-view') === 'bot') start();
        });
    });
    if (document.querySelector('.view-switch.active[data-view="bot"]')) start();
})();

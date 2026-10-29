/* ==================== 全局日志视图 ==================== */
(function () {
    'use strict';

    var POLL_MS = 1500;
    var MAX_ROWS = 1500;
    var LABEL = {
        debug: 'DEBUG', info: 'INFO', success: 'OK', warn: 'WARN', error: 'ERROR'
    };

    var el = {
        view: document.getElementById('view-logs'),
        levels: document.getElementById('lgLevels'),
        search: document.getElementById('lgSearch'),
        auto: document.getElementById('lgAutoScroll'),
        pause: document.getElementById('lgPause'),
        clearBtn: document.getElementById('lgClearBtn'),
        count: document.getElementById('lgCount'),
        list: document.getElementById('lgList')
    };
    if (!el.view || !el.list) { return; }

    var state = {
        lastId: 0,
        level: 'all',
        q: '',
        paused: false,
        timer: null,
        rows: 0,
        searchTimer: null
    };

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function two(n) { return n < 10 ? '0' + n : String(n); }

    function fmtTime(t) {
        var d = new Date((Number(t) || 0) * 1000);
        return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
    }

    function active() {
        return el.view.classList.contains('active');
    }

    function nearBottom() {
        return el.list.scrollTop + el.list.clientHeight >= el.list.scrollHeight - 40;
    }

    function setCount() {
        el.count.textContent = state.rows + ' 条';
    }

    function rowHtml(it) {
        var lv = LABEL[it.level] ? it.level : 'info';
        var src = String(it.source || '');
        return '<div class="lg-row lg-' + lv + '">' +
            '<span class="lg-time">' + esc(fmtTime(it.t)) + '</span>' +
            '<span class="lg-lv">' + esc(LABEL[lv]) + '</span>' +
            '<span class="lg-src"' + (src ? ' title="' + esc(src) + '"' : '') + '>' + esc(src) + '</span>' +
            '<span class="lg-msg">' + esc(it.text) + '</span>' +
        '</div>';
    }

    function resetList() {
        state.rows = 0;
        state.lastId = 0;
        el.list.innerHTML = '';
        setCount();
    }

    function appendItems(items, reset) {
        var wasBottom = nearBottom();
        var frag = document.createDocumentFragment();
        items.forEach(function (it) {
            var d = document.createElement('div');
            d.innerHTML = rowHtml(it);
            frag.appendChild(d.firstChild);
        });
        var ph = el.list.querySelector('.console-empty');
        if (ph) { el.list.removeChild(ph); }
        el.list.appendChild(frag);
        state.rows += items.length;

        // 超出上限时从顶部裁掉
        while (el.list.children.length > MAX_ROWS) {
            el.list.removeChild(el.list.firstChild);
            state.rows -= 1;
        }
        setCount();
        if (!reset && el.auto && el.auto.checked && wasBottom) {
            el.list.scrollTop = el.list.scrollHeight;
        } else if (reset && el.auto && el.auto.checked) {
            el.list.scrollTop = el.list.scrollHeight;
        }
    }

    function load(reset) {
        if (!reset && state.paused) { return Promise.resolve(); }
        var qs = '/api/logs?since=' + (reset ? 0 : state.lastId) +
            '&limit=' + (reset ? 400 : 300) +
            '&levels=' + (state.level === 'all' ? '' : state.level) +
            '&q=' + encodeURIComponent(state.q);
        return fetch(qs, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (j) {
                if (!j || j.ok === false) { return; }
                if (reset) { resetList(); }
                state.lastId = Math.max(state.lastId, j.seq || 0);
                var items = j.items || [];
                if (items.length) {
                    appendItems(items, reset);
                } else if (!state.rows) {
                    el.list.innerHTML = '<p class="console-empty">' +
                        (reset ? '暂无匹配的日志' : '暂无日志') + '</p>';
                }
            })
            .catch(function () {
                if (!state.rows) {
                    el.list.innerHTML = '<p class="console-empty">日志接口不可用</p>';
                }
            });
    }

    function tick() {
        if (!active()) { return; }
        load(false);
    }

    function start() {
        if (state.timer) { return; }
        state.timer = setInterval(tick, POLL_MS);
    }

    function stop() {
        if (state.timer) { clearInterval(state.timer); state.timer = null; }
    }

    function setLevel(btn) {
        if (!btn) { return; }
        Array.prototype.forEach.call(el.levels.querySelectorAll('.lg-chip'), function (b) {
            b.classList.toggle('active', b === btn);
        });
        state.level = btn.getAttribute('data-level') || 'all';
        load(true);
    }

    el.levels.addEventListener('click', function (e) {
        var btn = e.target.closest('.lg-chip');
        if (btn) { setLevel(btn); }
    });

    el.search.addEventListener('input', function () {
        var v = el.search.value.trim();
        if (state.searchTimer) { clearTimeout(state.searchTimer); }
        state.searchTimer = setTimeout(function () {
            if (v === state.q) { return; }
            state.q = v;
            load(true);
        }, 300);
    });

    el.auto.addEventListener('change', function () {
        if (el.auto.checked) { el.list.scrollTop = el.list.scrollHeight; }
    });

    el.pause.addEventListener('change', function () {
        state.paused = !!el.pause.checked;
        if (!state.paused) { load(false); }
    });

    el.clearBtn.addEventListener('click', function () {
        fetch('/api/logs/clear', { method: 'POST', credentials: 'same-origin' })
            .then(function () { load(true); })
            .catch(function () { load(true); });
    });

    // 视图切换联动：进入日志页立即刷新，离开后停止轮询
    document.addEventListener('click', function (e) {
        var sw = e.target.closest('.view-switch');
        if (!sw) { return; }
        if (sw.getAttribute('data-view') === 'logs') {
            start();
            load(true);
        } else {
            stop();
        }
    });

    // 初始化：首次进入日志页时加载
    load(true);
    if (active()) { start(); }
})();

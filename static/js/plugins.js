/* 插件页：plugins/ 下一个文件夹 = 一个插件
 * 功能：插件列表 / 运行状态 / 热启用热禁用 / 热重载 / 改配置（friend|group|group_member 走 ILBB 下拉栏）
 * 子选项：「插件列表」（默认）与「独立页面」（只列 "web": true 的插件，右侧内嵌其页面）
 * 刷新：列表与状态不自动刷新，进入页面读一次，之后由用户点「手动刷新」更新
 * 依赖：ws.js 暴露的 window.ILBBSelect（同一套下拉栏交互与样式）
 */
(function () {
    'use strict';

    var API_LIST = '/api/plugins/list';
    var API_TOGGLE = '/api/plugins/toggle';
    var API_RELOAD = '/api/plugins/reload';
    var API_CFG = '/api/plugins/config';
    var API_WEB = '/api/plugins/web';

    var SRC_LABEL = { friend: '好友', group: '群聊', group_member: '群成员' };
    var TYPE_LABEL = {
        text: '文本', textarea: '长文本', int: '整数', bool: '开关', enum: '单选',
        friend: '好友', group: '群聊', group_member: '群成员'
    };

    var S = {
        summary: null,
        sel: '',
        filter: '',
        tab: 'list',         // 子选项：list | web
        detail: {},          // pid -> {fields, values}
        multi: {},           // pid|key -> [value, ...]
        web: {},             // pid -> {url, up, ...}
        dirty: false,
        inited: false,
        view: false
    };

    function $(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function fid(pid, key) { return 'pgf_' + pid + '_' + key; }

    function api(url, opts) {
        opts = opts || {};
        var init = { method: opts.method || 'GET', headers: {} };
        if (opts.body !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(opts.body);
        }
        return fetch(url, init).then(function (r) {
            return r.json().catch(function () { return { ok: false, error: 'HTTP ' + r.status }; });
        }).then(function (d) {
            if (!d || d.ok === false) throw new Error((d && d.error) || '请求失败');
            return d;
        });
    }

    var toastTimer = null;
    function toast(msg, kind) {
        var box = $('pgToast');
        if (!box) {
            box = document.createElement('div');
            box.id = 'pgToast';
            box.className = 'pg-toast';
            document.body.appendChild(box);
        }
        box.className = 'pg-toast ' + (kind || 'info') + ' show';
        box.textContent = msg;
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () { box.classList.remove('show'); }, 2600);
    }

    function pluginById(pid) {
        var list = (S.summary && S.summary.plugins) || [];
        for (var i = 0; i < list.length; i++) if (list[i].id === pid) return list[i];
        return null;
    }

    // ------------------------------------------------------------------
    // 列表 / 概况
    // ------------------------------------------------------------------
    function load(silent) {
        return api(API_LIST).then(function (d) {
            S.summary = d;
            renderStats();
            renderBad();
            renderList();
            renderWebList();
            if (S.sel && pluginById(S.sel)) renderDetail();
            else if (S.sel) selectPlugin('');
            if (!silent) $('pgRefreshedAt').textContent = new Date().toLocaleTimeString();
            prefetchWeb();      // 顺手探测独立页面插件的在线状态，切到那个子选项就是现成的
        }).catch(function (e) {
            if (!silent) toast('读取插件列表失败：' + e.message, 'err');
            var box = $('pgList');
            if (box) box.innerHTML = '<div class="console-empty">读取失败：' + esc(e.message) + '</div>';
        });
    }

    // 手动刷新：表单里还有没保存的改动时先确认一下，别让人白填
    function refreshPage() {
        if (S.dirty && !confirm('配置表单里还有没保存的改动，刷新会把它们丢掉。确定要刷新吗？')) return;
        load();
    }

    function renderStats() {
        var d = S.summary || {};
        var enabled = !!d.enabled, hot = !!d.hot_reload;
        $('pgSysEnabled').textContent = enabled ? '插件系统运行中' : '插件系统已关闭';
        $('pgSysEnabled').title = enabled ? '' : 'PLUGIN_ENABLED=false';
        $('pgSysCount').textContent = (d.count || 0) + ' / ' + (d.loaded || 0);
        $('pgSysHot').textContent = hot ? '开' : '关';
        $('pgSysHot').title = hot
            ? ('每 ' + (d.poll_sec || 3) + ' 秒扫描一次代码改动')
            : '已关闭，改代码后需手动点「重载」';
        $('pgSysPoll').textContent = (d.poll_sec || 3) + 's';
        var root = $('pgRoot'), cfg = $('pgCfgPath');
        root.textContent = d.root || '—'; root.title = d.root || '';
        cfg.textContent = d.config_path || '—'; cfg.title = d.config_path || '';
        var dot = $('pgSysDot');
        if (dot) dot.className = 'pg-ov-dot' + (enabled ? (hot ? '' : ' warn') : ' off');
    }

    function renderBad() {
        var bad = (S.summary && S.summary.bad) || [];
        var box = $('pgBad');
        if (!bad.length) { box.classList.add('hidden'); return; }
        box.classList.remove('hidden');
        $('pgBadHint').textContent = bad.length + ' 个文件夹被忽略';
        $('pgBadList').innerHTML = bad.map(function (b) {
            return '<div class="pg-bad-item">'
                + '<div class="pg-bad-name">' + esc(b.name) + '</div>'
                + '<div class="pg-bad-err">' + esc(b.error) + '</div>'
                + '<div class="pg-bad-path">' + esc(b.folder) + '</div>'
                + '</div>';
        }).join('');
    }

    function renderList() {
        var box = $('pgList');
        var list = (S.summary && S.summary.plugins) || [];
        var q = S.filter.trim().toLowerCase();
        if (q) {
            list = list.filter(function (p) {
                return (p.id + ' ' + p.name + ' ' + p.author + ' ' + p.desc).toLowerCase().indexOf(q) !== -1;
            });
        }
        $('pgCountHint').textContent = q
            ? ('匹配 ' + list.length + ' / 共 ' + ((S.summary && S.summary.count) || 0) + ' 个')
            : ('共 ' + list.length + ' 个');
        if (!list.length) {
            box.innerHTML = '<div class="console-empty">'
                + (q ? '没有匹配的插件' : 'plugins/ 里还没有插件。新建一个文件夹，放上 plugin.json 和 main.py 就会出现在这里。')
                + '</div>';
            return;
        }
        box.innerHTML = list.map(cardHtml).join('');
        Array.prototype.forEach.call(box.querySelectorAll('.pg-card'), function (card) {
            var pid = card.getAttribute('data-id');
            card.addEventListener('click', function (e) {
                var act = e.target && e.target.getAttribute && e.target.getAttribute('data-act');
                if (act === 'toggle') { e.stopPropagation(); togglePlugin(pid); return; }
                if (act === 'reload') { e.stopPropagation(); reloadPlugin(pid); return; }
                selectPlugin(pid);
            });
        });
    }

    function cardHtml(p) {
        var state = !p.enabled ? 'off' : (p.loaded ? 'on' : 'warn');
        var tags = [];
        tags.push('<span class="pg-tag ' + (p.enabled ? 'ok' : 'muted') + '">' + (p.enabled ? '已启用' : '已禁用') + '</span>');
        tags.push('<span class="pg-tag ' + (p.loaded ? 'ok' : 'muted') + '">' + (p.loaded ? '已加载' : '未加载') + '</span>');
        if ((p.commands || []).length) tags.push('<span class="pg-tag info">指令 ' + p.commands.length + '</span>');
        if (p.has_web) tags.push('<span class="pg-tag web">独立页面 :' + (p.web_port || '?') + '</span>');
        var err = p.error ? '<div class="pg-card-err">' + esc(p.error) + '</div>' : '';
        return '<article class="pg-card' + (p.id === S.sel ? ' active' : '') + '" data-id="' + esc(p.id) + '">'
            + '<div class="pg-card-main">'
            +   '<div class="pg-card-top">'
            +     '<span class="pg-dot ' + state + '"></span>'
            +     '<b class="pg-card-name">' + esc(p.name) + '</b>'
            +     '<span class="pg-card-ver">v' + esc(p.version) + '</span>'
            +   '</div>'
            +   '<div class="pg-card-id">' + esc(p.id) + (p.author ? ' · ' + esc(p.author) : '') + '</div>'
            +   (p.desc ? '<div class="pg-card-desc">' + esc(p.desc) + '</div>' : '')
            +   '<div class="pg-card-tags">' + tags.join('') + '</div>'
            +   err
            + '</div>'
            + '<div class="pg-card-ops">'
            +   '<button type="button" class="pg-mini" data-act="toggle">' + (p.enabled ? '禁用' : '启用') + '</button>'
            +   '<button type="button" class="pg-mini" data-act="reload">重载</button>'
            + '</div>'
            + '</article>';
    }

    // ------------------------------------------------------------------
    // 详情
    // ------------------------------------------------------------------
    function selectPlugin(pid) {
        S.sel = pid || '';
        S.dirty = false;
        renderList();
        renderWebList();
        if (!pid) {
            $('pgDetail').classList.add('hidden');
            $('pgDetailEmpty').classList.remove('hidden');
            $('pgWebBlock').classList.add('hidden');
            showWebEmpty(true);
            $('pgDetailTitle').textContent = '插件详情';
            $('pgDetailHint').textContent = '从左边的列表里选一个插件';
            return;
        }
        $('pgDetailEmpty').classList.add('hidden');
        $('pgDetail').classList.remove('hidden');
        loadConfig(pid);
        loadWeb(pid);
    }

    function loadConfig(pid) {
        return api(API_CFG + '?id=' + encodeURIComponent(pid)).then(function (d) {
            S.detail[pid] = { fields: d.fields || [], values: d.values || {} };
            (S.detail[pid].fields || []).forEach(function (f) {
                if (isMulti(f)) {
                    var v = S.detail[pid].values[f.key];
                    S.multi[pid + '|' + f.key] = Array.isArray(v) ? v.slice() : (v ? [String(v)] : []);
                }
            });
            renderDetail();
        }).catch(function (e) {
            toast('读取插件配置失败：' + e.message, 'err');
        });
    }

    // 右侧「无内容」占位（独立页面子选项里没选插件时显示）
    function showWebEmpty(on) {
        var e = $('pgWebEmpty');
        if (e) e.classList.toggle('hidden', !on);
    }

    // 探测某个插件的独立页面（自动匹配主机名 + 插件端口）
    function fetchWeb(pid) {
        return api(API_WEB + '?id=' + encodeURIComponent(pid)).then(function (d) {
            S.web[pid] = d;
            return d;
        }).catch(function (e) {
            S.web[pid] = { error: e.message };
            return S.web[pid];
        });
    }

    function loadWeb(pid) {
        var p = pluginById(pid);
        if (!p || !p.has_web) {
            delete S.web[pid];
            $('pgWebBlock').classList.add('hidden');
            showWebEmpty(true);
            return Promise.resolve(null);
        }
        return fetchWeb(pid).then(function () {
            renderWeb();
            renderWebList();
            return S.web[pid];
        });
    }

    function renderDetail() {
        var pid = S.sel;
        var p = pluginById(pid);
        var c = S.detail[pid];
        if (!p || !c) return;

        $('pgDetailTitle').textContent = p.name;
        $('pgDetailHint').textContent = p.enabled ? (p.loaded ? '运行中' : '已启用但未加载') : '已禁用';

        var meta = [
            ['ID', p.id],
            ['版本', 'v' + p.version],
            ['作者', p.author || '—'],
            ['文件夹', 'plugins/' + p.rel_folder],
            ['入口', 'main.py'],
            ['独立页面', p.has_web ? ('端口 ' + (p.web_port || '?')) : '未开放'],
            ['重载次数', String(p.reload_count || 0)],
            ['上次加载', p.loaded_at ? new Date(p.loaded_at * 1000).toLocaleString() : '—']
        ];
        $('pgMeta').innerHTML = meta.map(function (row) {
            return '<div class="pg-meta-row"><span class="k">' + esc(row[0]) + '</span>'
                + '<span class="v">' + esc(row[1]) + '</span></div>';
        }).join('');

        var cmds = (p.commands || []);
        var acts = [];
        acts.push('<button type="button" class="ws-btn" id="pgBtnToggle">' + (p.enabled ? '热禁用' : '热启用') + '</button>');
        acts.push('<button type="button" class="ws-btn" id="pgBtnReload">热重载</button>');
        if (p.has_web) acts.push('<button type="button" class="ws-btn" id="pgBtnWeb">独立页面</button>');
        $('pgActions').innerHTML = acts.join('')
            + '<div class="pg-cmds">'
            + (cmds.length
                ? cmds.map(function (k) { return '<code class="pg-cmd">' + esc(k) + '</code>'; }).join('')
                : '<span class="pg-tip-inline">没有注册指令（可能只监听事件，或只靠独立页面工作）</span>')
            + '</div>';
        if (p.error) $('pgActions').innerHTML += '<div class="pg-card-err">' + esc(p.error) + '</div>';

        $('pgBtnToggle').addEventListener('click', function () { togglePlugin(pid); });
        $('pgBtnReload').addEventListener('click', function () { reloadPlugin(pid); });
        if ($('pgBtnWeb')) $('pgBtnWeb').addEventListener('click', function () { openWebTab(pid); });

        renderFields();
        renderWeb();
    }

    function renderWeb() {
        var pid = S.sel;
        var p = pluginById(pid);
        var w = S.web[pid];
        var box = $('pgWebBlock');
        if (!p || !p.has_web || !w) { box.classList.add('hidden'); showWebEmpty(true); return; }
        box.classList.remove('hidden');
        showWebEmpty(false);
        $('pgWebTitle').textContent = (w.title || p.name) + ' · 独立页面';
        if (w.error) {
            $('pgWebHint').textContent = '不可用';
            $('pgWebUrl').value = '';
            $('pgWebTip').textContent = w.error;
            $('pgWebFrame').removeAttribute('src');
            return;
        }
        $('pgWebHint').textContent = w.up ? '在线' : '未响应';
        $('pgWebUrl').value = w.url || '';
        $('pgWebTip').textContent = w.up
            ? '端口 ' + w.port + ' 已就绪。刷新本页会重新探测。'
            : '端口 ' + w.port + ' 暂时探测不到（插件可能没启动 Web，或还在启动中）。点「重新加载」再试一次。';
        var frame = $('pgWebFrame');
        // 比对时忽略 "?t=时间戳" 这类防缓存参数，免得把「重新加载」刚设上的地址又冲掉
        var cur = (frame.getAttribute('src') || '').split('?')[0];
        var want = String(w.url || '').split('?')[0];
        if (w.up && cur !== want) frame.setAttribute('src', w.url);
        if (!w.up) frame.removeAttribute('src');
    }

    // ------------------------------------------------------------------
    // 子选项切换：插件列表 / 独立页面（复用 .ws-tabs 滑块组件）
    // ------------------------------------------------------------------
    var PG_PANES = { list: 'pgPaneList', web: 'pgPaneWeb' };
    var PG_HINTS = { list: '一个文件夹 = 一个插件', web: '带 "web": true 的插件 · 端口由 ILBB 分配' };

    function pgTabEls() {
        var wrap = $('pgTabs');
        return wrap ? Array.prototype.slice.call(wrap.querySelectorAll('.ws-tab')) : [];
    }

    // 滑块跟随选中项移动（视图隐藏时量不到尺寸 → 跳过，等可见后再定位）
    function movePgPill(instant) {
        var wrap = $('pgTabs');
        var pill = $('pgTabsPill');
        if (!wrap || !pill) return;
        var act = wrap.querySelector('.ws-tab.active');
        if (!act) return;
        var r = act.getBoundingClientRect();
        var b = wrap.getBoundingClientRect();
        if (!r.width) return;
        var bl = parseFloat(getComputedStyle(wrap).borderLeftWidth) || 0;
        var x = (r.left - b.left) - bl;
        if (instant) pill.style.transition = 'none';
        pill.style.width = r.width + 'px';
        pill.style.transform = 'translateX(' + x + 'px)';
        if (instant) { void pill.offsetWidth; pill.style.transition = ''; }
    }

    function switchPgTab(name) {
        if (!PG_PANES[name]) name = 'list';
        S.tab = name;
        pgTabEls().forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-pg-tab') === name);
        });
        Object.keys(PG_PANES).forEach(function (k) {
            var pane = $(PG_PANES[k]);
            if (pane) pane.classList.toggle('active', k === name);
        });
        var hint = $('pgTabsHint');
        if (hint) hint.textContent = PG_HINTS[name] || PG_HINTS.list;
        if (name === 'web') { renderWebList(); prefetchWeb(); }
        requestAnimationFrame(function () { movePgPill(); });
    }

    // 详情里的「独立页面」按钮：切到那个子选项，并选中这个插件
    function openWebTab(pid) {
        if (!pid) return;
        if (S.sel !== pid) selectPlugin(pid);
        switchPgTab('web');
    }

    // ------------------------------------------------------------------
    // 独立页面子选项：列出所有 "web": true 的插件
    // ------------------------------------------------------------------
    function webPlugins() {
        var list = (S.summary && S.summary.plugins) || [];
        return list.filter(function (p) { return !!p.has_web; });
    }

    // 逐个探测在线状态（一般就一两个，请求很少）
    function prefetchWeb() {
        webPlugins().forEach(function (p) {
            if (S.web[p.id]) return;
            fetchWeb(p.id).then(function () { renderWebList(); });
        });
    }

    function renderWebList() {
        var box = $('pgWebList');
        if (!box) return;
        var list = webPlugins();
        var hint = $('pgWebCountHint');
        if (hint) {
            var up = list.filter(function (p) { var w = S.web[p.id]; return !!(w && w.up); }).length;
            hint.textContent = list.length ? (list.length + ' 个 · 在线 ' + up) : '0 个';
        }
        if (!list.length) {
            box.innerHTML = '<div class="console-empty">还没有插件声明独立页面。'
                + '在插件的 <code class="ws-code">plugin.json</code> 里写 <code class="ws-code">"web": true</code>，'
                + 'ILBB 会自动给它分配端口，这里就会出现。</div>';
            return;
        }
        box.innerHTML = list.map(webCardHtml).join('');
        Array.prototype.forEach.call(box.querySelectorAll('.pg-card'), function (card) {
            var pid = card.getAttribute('data-id');
            card.addEventListener('click', function (e) {
                var act = e.target && e.target.getAttribute && e.target.getAttribute('data-act');
                if (act === 'open') {
                    e.stopPropagation();
                    var w = S.web[pid];
                    if (w && w.url) window.open(w.url, '_blank');
                    else toast('这个插件的页面还没就绪，点「重探」再试', 'err');
                    return;
                }
                if (act === 'recheck') {
                    e.stopPropagation();
                    delete S.web[pid];
                    renderWebList();
                    loadWeb(pid).then(function () { toast('已重新探测「' + (pluginById(pid) || {}).name + '」', 'info'); });
                    return;
                }
                selectPlugin(pid);
            });
        });
    }

    function webCardHtml(p) {
        var w = S.web[p.id];
        var state = !p.enabled ? 'off' : (p.loaded ? 'on' : 'warn');
        var tags = [];
        tags.push('<span class="pg-tag ' + (p.enabled ? 'ok' : 'muted') + '">' + (p.enabled ? '已启用' : '已禁用') + '</span>');
        if (!w) tags.push('<span class="pg-tag muted">探测中…</span>');
        else if (w.error) tags.push('<span class="pg-tag muted">探测失败</span>');
        else tags.push('<span class="pg-tag ' + (w.up ? 'ok' : 'muted') + '">' + (w.up ? '在线' : '未响应') + '</span>');
        tags.push('<span class="pg-tag web">端口 ' + (p.web_port || '?') + '</span>');
        return '<article class="pg-card' + (p.id === S.sel ? ' active' : '') + '" data-id="' + esc(p.id) + '">'
            + '<div class="pg-card-main">'
            +   '<div class="pg-card-top">'
            +     '<span class="pg-dot ' + state + '"></span>'
            +     '<b class="pg-card-name">' + esc(p.name) + '</b>'
            +     '<span class="pg-card-ver">v' + esc(p.version) + '</span>'
            +   '</div>'
            +   '<div class="pg-card-id">' + esc(p.id) + (p.author ? ' · ' + esc(p.author) : '') + '</div>'
            +   '<div class="pg-card-id">' + esc(w && w.url ? w.url : '（地址还没拿到）') + '</div>'
            +   '<div class="pg-card-tags">' + tags.join('') + '</div>'
            + '</div>'
            + '<div class="pg-card-ops">'
            +   '<button type="button" class="pg-mini" data-act="open">新窗口</button>'
            +   '<button type="button" class="pg-mini" data-act="recheck">重探</button>'
            + '</div>'
            + '</article>';
    }

    // ------------------------------------------------------------------
    // 配置表单
    // ------------------------------------------------------------------
    function isMulti(f) {
        return !!f.multi && (f.type === 'friend' || f.type === 'group' || f.type === 'group_member');
    }

    function depGroupKey(fields) {
        // 群成员字段要跟着一个「单选的群」走：多选群的隐藏域里存的是 JSON，不能直接当 group_id 用
        for (var i = 0; i < fields.length; i++) if (fields[i].type === 'group' && !fields[i].multi) return fields[i].key;
        for (var j = 0; j < fields.length; j++) if (fields[j].type === 'group') return fields[j].key;
        return '';
    }

    function selectHtml(pid, f, value) {
        var id = fid(pid, f.key);
        var src = (f.type === 'friend' || f.type === 'group' || f.type === 'group_member') ? f.type : '';
        var label = SRC_LABEL[src] || '选项';
        var h = '<input type="hidden" id="' + id + '" value="' + esc(value == null ? '' : value) + '">';
        h += '<div class="ilbb-select' + (src ? ' ilbb-select-dyn' : '') + '"'
            + ' data-select="pg_' + esc(pid) + '_' + esc(f.key) + '" data-target="' + id + '"';
        if (src) {
            h += ' data-source="' + src + '"';
            if (src === 'group_member') {
                var gk = depGroupKey((S.detail[pid] || {}).fields || []);
                if (gk) h += ' data-dep="' + fid(pid, gk) + '"';
            }
        }
        h += '>';
        h += '<button type="button" class="ilbb-select-btn" aria-haspopup="listbox" aria-expanded="false">';
        if (src) h += '<img class="ilbb-select-btn-av" alt="" aria-hidden="true" width="24" height="24" hidden>';
        if (src) {
            h += '<span class="ilbb-select-text">正在获取' + label + '…</span>';
        } else {
            var opts = f.options || [];
            var cur = opts.filter(function (o) { return String(o.value) === String(value); })[0] || opts[0] || { value: '', label: '请选择' };
            h += '<span class="ilbb-select-text">' + esc(cur.label || cur.value || '请选择') + '</span>';
        }
        h += '<span class="ilbb-select-caret"></span></button>';
        h += '<ul class="ilbb-select-menu" role="listbox">';
        if (src) {
            h += '<li class="ilbb-select-searchwrap">'
                + '<input type="text" class="ilbb-select-search" autocomplete="off"'
                + ' placeholder="搜索' + label + '…" aria-label="搜索' + label + '"></li>';
        } else {
            (f.options || []).forEach(function (o) {
                var on = String(o.value) === String(value);
                h += '<li class="ilbb-select-opt" role="option" data-value="' + esc(o.value) + '"'
                    + ' aria-selected="' + (on ? 'true' : 'false') + '">'
                    + '<span class="ilbb-select-opt-main">' + esc(o.label || o.value) + '</span>'
                    + '<span class="ilbb-select-opt-code">' + esc(o.value) + '</span>'
                    + '<span class="ilbb-select-tick">✓</span></li>';
            });
        }
        h += '</ul></div>';
        return h;
    }

    function multiHtml(pid, f, vals) {
        var id = fid(pid, f.key);
        var src = f.type;
        var label = SRC_LABEL[src] || '选项';
        var h = '<div class="pg-multi" data-pid="' + esc(pid) + '" data-key="' + esc(f.key) + '" data-source="' + src + '"';
        if (src === 'group_member') {
            var gk = depGroupKey((S.detail[pid] || {}).fields || []);
            if (gk) h += ' data-dep="' + fid(pid, gk) + '"';
        }
        h += '>';
        h += '<div class="pg-chips" data-chips="' + esc(f.key) + '"></div>';
        h += '<div class="ilbb-select pg-multi-select" data-multi="' + esc(f.key) + '"'
            + ' data-select="pgm_' + esc(pid) + '_' + esc(f.key) + '" data-target="' + id + '">'
            + '<button type="button" class="ilbb-select-btn" aria-haspopup="listbox" aria-expanded="false">'
            + '<span class="ilbb-select-text">添加' + label + '…</span><span class="ilbb-select-caret"></span></button>'
            + '<ul class="ilbb-select-menu" role="listbox">'
            + '<li class="ilbb-select-searchwrap"><input type="text" class="ilbb-select-search" autocomplete="off"'
            + ' placeholder="搜索' + label + '…" aria-label="搜索' + label + '"></li>'
            + '</ul></div>';
        h += '<input type="hidden" id="' + id + '" value="' + esc(JSON.stringify(vals || [])) + '">';
        h += '</div>';
        return h;
    }

    function fieldHtml(pid, f, values) {
        var id = fid(pid, f.key);
        var val = values[f.key];
        if (val === undefined || val === null) val = f.multi ? [] : '';
        var multi = isMulti(f);
        var h = '<div class="pg-field" data-key="' + esc(f.key) + '">';
        h += '<div class="pg-field-head">'
            + '<label for="' + id + '">' + esc(f.label || f.key) + '</label>'
            + '<code class="pg-field-key">' + esc(f.key) + '</code>'
            + '<span class="pg-field-type">' + esc(TYPE_LABEL[f.type] || f.type) + (multi ? ' · 可多选' : '') + '</span>'
            + '</div>';

        if (multi) {
            h += multiHtml(pid, f, Array.isArray(val) ? val : [val]);
        } else if (f.type === 'bool') {
            h += '<label class="pg-check"><input type="checkbox" id="' + id + '"' + (val ? ' checked' : '') + '> <span>开启</span></label>';
        } else if (f.type === 'textarea') {
            h += '<textarea id="' + id + '" rows="3" autocomplete="off" placeholder="'
                + esc(f.placeholder || '') + '">' + esc(val) + '</textarea>';
        } else if (f.type === 'enum' || f.type === 'friend' || f.type === 'group' || f.type === 'group_member') {
            h += selectHtml(pid, f, val);
        } else if (f.type === 'int') {
            h += '<input type="number" id="' + id + '" value="' + esc(val === '' ? '' : val) + '"'
                + ' autocomplete="off" placeholder="' + esc(f.placeholder || '') + '">';
        } else {
            h += '<input type="text" id="' + id + '" value="' + esc(val) + '"'
                + ' autocomplete="off" placeholder="' + esc(f.placeholder || '') + '">';
        }
        if (f.hint) h += '<div class="pg-field-hint">' + esc(f.hint) + '</div>';
        h += '</div>';
        return h;
    }

    function renderFields() {
        var pid = S.sel;
        var c = S.detail[pid];
        var box = $('pgCfg');
        var fields = c.fields || [];
        if (!fields.length) {
            box.innerHTML = '<div class="pg-empty">这个插件没有声明可配置项。'
                + '作者可以在 <code class="ws-code">plugin.json</code> 的 <code class="ws-code">config</code> 里声明字段，'
                + '这里就会自动生成表单。</div>';
            $('pgCfgHint').textContent = '';
            $('pgSaveBtn').disabled = true;
            $('pgResetBtn').disabled = true;
            return;
        }
        $('pgSaveBtn').disabled = false;
        $('pgResetBtn').disabled = false;
        $('pgCfgHint').textContent = '改动保存后立即生效，不需要重载插件';
        box.innerHTML = fields.map(function (f) { return fieldHtml(pid, f, c.values); }).join('');

        // ILBB 下拉栏（静态 enum + 动态 friend/group/group_member）
        if (window.ILBBSelect && window.ILBBSelect.init) window.ILBBSelect.init(box);
        // 多选组件（自实现：复选 + chips）
        initMulti(box);
        initChips();

        Array.prototype.forEach.call(
            box.querySelectorAll('input:not([type=hidden]):not(.ilbb-select-search), textarea'),
            function (el) {
                el.addEventListener('input', markDirty);
                el.addEventListener('change', markDirty);
            }
        );
        // 隐藏 input 由下拉栏写入，值变化同样算脏，用于提示「有未保存的改动」
        Array.prototype.forEach.call(box.querySelectorAll('input[type=hidden]'), function (el) {
            el.addEventListener('change', markDirty);
        });
        renderChips(pid);
    }

    function markDirty() {
        S.dirty = true;
        $('pgSaveTip').textContent = '有未保存的改动';
        $('pgSaveTip').className = 'pg-tip-inline warn';
    }

    // ------------------------------------------------------------------
    // 多选组件
    // ------------------------------------------------------------------
    function avUrl(kind, id) {
        return '/api/ws/avatar?type=' + (kind === 'group' ? 'group' : 'user')
            + '&id=' + encodeURIComponent(id) + '&s=100';
    }

    function multiList(pid, key) { return S.multi[pid + '|' + key] || []; }

    function setMulti(pid, key, arr) {
        S.multi[pid + '|' + key] = arr;
        var hid = $(fid(pid, key));
        if (hid) {
            hid.value = JSON.stringify(arr);
            hid.dispatchEvent(new Event('change', { bubbles: true }));
        }
        renderChips(pid);
    }

    function renderChips(pid) {
        var c = S.detail[pid];
        if (!c) return;
        Array.prototype.forEach.call(document.querySelectorAll('#pgCfg .pg-multi'), function (wrap) {
            var key = wrap.getAttribute('data-key');
            var vals = multiList(pid, key);
            var box = wrap.querySelector('.pg-chips');
            if (!box) return;
            if (!vals.length) {
                box.innerHTML = '<span class="pg-chips-empty">还没有选择</span>';
                return;
            }
            box.innerHTML = vals.map(function (v) {
                return '<span class="pg-chip" data-value="' + esc(v) + '">'
                    + '<span class="pg-chip-t">' + esc(v) + '</span>'
                    + '<button type="button" class="pg-chip-x" title="移除">×</button></span>';
            }).join('');
            Array.prototype.forEach.call(box.querySelectorAll('.pg-chip'), function (chip) {
                chip.querySelector('.pg-chip-x').addEventListener('click', function (e) {
                    e.stopPropagation();
                    var v = chip.getAttribute('data-value');
                    setMulti(pid, key, multiList(pid, key).filter(function (x) { return x !== v; }));
                    var sel = wrap.querySelector('.ilbb-select');
                    if (sel) {
                        var o = sel.querySelector('.ilbb-select-opt[data-value="' + cssEsc(v) + '"]');
                        if (o) o.setAttribute('aria-selected', 'false');
                    }
                    markDirty();
                });
            });
        });
    }

    function cssEsc(v) { return String(v).replace(/"/g, '\\"'); }

    function initChips() { /* 占位：chips 绑定在 renderChips 中完成 */ }

    function initMulti(root) {
        Array.prototype.forEach.call(root.querySelectorAll('.pg-multi'), function (wrap) {
            var pid = wrap.getAttribute('data-pid');
            var key = wrap.getAttribute('data-key');
            var src = wrap.getAttribute('data-source');
            var dep = wrap.getAttribute('data-dep') || '';
            var sel = wrap.querySelector('.ilbb-select');
            var btn = sel.querySelector('.ilbb-select-btn');
            var menu = sel.querySelector('.ilbb-select-menu');
            var search = sel.querySelector('.ilbb-select-search');
            var label = SRC_LABEL[src] || '选项';
            var loaded = false;

            menu.addEventListener('click', function (e) { e.stopPropagation(); });
            if (search) {
                search.addEventListener('click', function (e) { e.stopPropagation(); });
                search.addEventListener('input', function () {
                    var q = search.value.trim().toLowerCase();
                    Array.prototype.forEach.call(menu.querySelectorAll('.ilbb-select-opt'), function (o) {
                        var t = (o.getAttribute('data-search') || '').toLowerCase();
                        o.classList.toggle('dyn-hide', !!q && t.indexOf(q) === -1);
                    });
                });
                search.addEventListener('keydown', function (e) { e.stopPropagation(); });
            }
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var willOpen = !sel.classList.contains('open');
                sel.classList.toggle('open', willOpen);
                btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
                if (willOpen) {
                    if (search) search.focus();
                    if (!loaded) { loaded = true; fillMultiMenu(pid, key, src, dep, sel, menu); }
                }
            });
        });
    }

    function fillMultiMenu(pid, key, src, dep, sel, menu) {
        var api2 = window.ILBBSelect;
        var job = null;
        if (src === 'friend' && api2) job = api2.fetchFriends();
        else if (src === 'group' && api2) job = api2.fetchGroups();
        else if (src === 'group_member' && api2) {
            var gid = dep ? (($(dep) || {}).value || '') : '';
            if (!gid) {
                setMultiText(sel, '请先选择群聊');
                return;
            }
            job = api2.fetchMembers(gid);
        }
        if (!job) { setMultiText(sel, '无法获取' + (SRC_LABEL[src] || '选项')); return; }
        setMultiText(sel, '正在获取' + (SRC_LABEL[src] || '选项') + '…');
        job.then(function (list) {
            var chosen = multiList(pid, key);
            var body = list.map(function (o) {
                var on = chosen.indexOf(String(o.value)) !== -1;
                return '<li class="ilbb-select-opt" role="option" data-value="' + esc(o.value) + '"'
                    + ' data-search="' + esc((o.label || '') + ' ' + o.value) + '"'
                    + ' aria-selected="' + (on ? 'true' : 'false') + '">'
                    + (o.av
                        ? '<img class="ilbb-select-av" alt="" aria-hidden="true" width="26" height="26" src="'
                          + esc(avUrl(o.av, o.value)) + '">'
                        : '')
                    + '<span class="ilbb-select-opt-main">' + esc(o.label || o.value) + '</span>'
                    + (o.meta ? '<span class="ilbb-select-opt-meta">' + esc(o.meta) + '</span>' : '')
                    + '<span class="ilbb-select-opt-code">' + esc(o.value) + '</span>'
                    + '<span class="ilbb-select-tick">✓</span></li>';
            }).join('');
            // 保留搜索框，替换选项
            Array.prototype.forEach.call(menu.querySelectorAll('.ilbb-select-opt, .ilbb-dyn-state'), function (n) {
                if (n.parentNode) n.parentNode.removeChild(n);
            });
            var tmp = document.createElement('ul');
            tmp.innerHTML = body;
            while (tmp.firstChild) menu.appendChild(tmp.firstChild);
            setMultiText(sel, list.length ? '添加' + (SRC_LABEL[src] || '选项') + '…' : '没有可选项');
            Array.prototype.forEach.call(menu.querySelectorAll('.ilbb-select-opt'), function (o) {
                o.addEventListener('click', function (e) {
                    e.stopPropagation();
                    var v = o.getAttribute('data-value');
                    var arr = multiList(pid, key).slice();
                    var i = arr.indexOf(v);
                    if (i === -1) { arr.push(v); o.setAttribute('aria-selected', 'true'); }
                    else { arr.splice(i, 1); o.setAttribute('aria-selected', 'false'); }
                    setMulti(pid, key, arr);
                    markDirty();
                });
            });
        }).catch(function (e) {
            setMultiText(sel, '获取失败，点此重试');
            var li = document.createElement('li');
            li.className = 'ilbb-dyn-state retry';
            li.textContent = (e && e.message ? e.message : '获取失败') + '（点此重试）';
            li.addEventListener('click', function (ev) {
                ev.stopPropagation();
                if (li.parentNode) li.parentNode.removeChild(li);
                fillMultiMenu(pid, key, src, dep, sel, menu);
            });
            menu.appendChild(li);
        });
    }

    function setMultiText(sel, text) {
        var t = sel.querySelector('.ilbb-select-text');
        if (t) t.textContent = text;
    }

    // ------------------------------------------------------------------
    // 收集 / 保存
    // ------------------------------------------------------------------
    function collect() {
        var pid = S.sel;
        var c = S.detail[pid];
        var out = {};
        (c.fields || []).forEach(function (f) {
            if (isMulti(f)) { out[f.key] = multiList(pid, f.key).slice(); return; }
            var el = $(fid(pid, f.key));
            if (!el) { out[f.key] = f.multi ? [] : ''; return; }
            if (f.type === 'bool') { out[f.key] = !!el.checked; return; }
            var v = String(el.value == null ? '' : el.value).trim();
            if (f.type === 'int') { out[f.key] = v === '' ? 0 : (Number(v) || 0); return; }
            out[f.key] = v;
        });
        return out;
    }

    function saveConfig() {
        var pid = S.sel;
        if (!pid) return;
        var btn = $('pgSaveBtn');
        btn.disabled = true;
        var old = btn.textContent;
        btn.textContent = '保存中…';
        api(API_CFG, { method: 'POST', body: { id: pid, values: collect() } }).then(function (d) {
            S.dirty = false;
            $('pgSaveTip').textContent = '已保存 · ' + new Date().toLocaleTimeString();
            $('pgSaveTip').className = 'pg-tip-inline ok';
            if (S.detail[pid]) S.detail[pid].values = d.values || {};
            toast('「' + (pluginById(pid) || {}).name + '」配置已保存', 'ok');
        }).catch(function (e) {
            toast('保存失败：' + e.message, 'err');
        }).then(function () {
            btn.disabled = false;
            btn.textContent = old;
        });
    }

    function reloadConfig() {
        var pid = S.sel;
        if (!pid) return;
        S.dirty = false;
        loadConfig(pid).then(function () {
            toast('已还原为保存过的配置', 'info');
        });
    }

    // ------------------------------------------------------------------
    // 操作
    // ------------------------------------------------------------------
    function togglePlugin(pid) {
        var p = pluginById(pid);
        if (!p) return;
        api(API_TOGGLE, { method: 'POST', body: { id: pid, enabled: !p.enabled } }).then(function () {
            toast('「' + p.name + '」已' + (p.enabled ? '禁用' : '启用'), p.enabled ? 'info' : 'ok');
            return load(true);
        }).catch(function (e) { toast('操作失败：' + e.message, 'err'); });
    }

    function reloadPlugin(pid) {
        var p = pluginById(pid);
        api(API_RELOAD, { method: 'POST', body: pid ? { id: pid } : {} }).then(function (d) {
            toast(pid ? ('「' + ((p || {}).name || pid) + '」已重载') : ('目录已重扫：新增 ' + (d.added || 0) + ' / 变更 ' + (d.changed || 0) + ' / 移除 ' + (d.removed || 0)), 'ok');
            return load(true).then(function () {
                if (pid) loadConfig(pid);
            });
        }).catch(function (e) { toast('重载失败：' + e.message, 'err'); });
    }

    // ------------------------------------------------------------------
    // 绑定
    // ------------------------------------------------------------------
    function bind() {
        if (S.inited) return;
        S.inited = true;

        $('pgRefreshBtn').addEventListener('click', refreshPage);
        $('pgRescanBtn').addEventListener('click', function () { reloadPlugin(''); });
        $('pgReloadAllBtn').addEventListener('click', function () { reloadPlugin(''); });
        $('pgSaveBtn').addEventListener('click', saveConfig);
        $('pgResetBtn').addEventListener('click', reloadConfig);
        $('pgSearch').addEventListener('input', function () { S.filter = this.value || ''; renderList(); });

        // 子选项：插件列表 / 独立页面
        pgTabEls().forEach(function (b) {
            b.addEventListener('click', function () { switchPgTab(b.getAttribute('data-pg-tab')); });
        });
        var rt = null;
        window.addEventListener('resize', function () {
            clearTimeout(rt);
            rt = setTimeout(function () { movePgPill(true); }, 120);
        });

        var frame = $('pgWebFrame');
        $('pgWebReloadBtn').addEventListener('click', function () {
            var pid = S.sel;
            if (!pid) return;
            var w = S.web[pid];
            if (w && w.url) frame.setAttribute('src', w.url + (w.url.indexOf('?') === -1 ? '?t=' : '&t=') + Date.now());
            loadWeb(pid);
        });
        $('pgWebOpenBtn').addEventListener('click', function () {
            var w = S.web[S.sel];
            if (w && w.url) window.open(w.url, '_blank');
        });

        // 视图激活：进入时读取一次；之后不再自动刷新，完全由用户点「手动刷新」
        var sw = Array.prototype.slice.call(document.querySelectorAll('.view-switch'));
        function enterPlugins() {
            S.view = true;
            load();
            // 视图此刻才可见，滑块要重新量一次尺寸
            requestAnimationFrame(function () { movePgPill(true); });
        }
        sw.forEach(function (b) {
            b.addEventListener('click', function () {
                if (b.getAttribute('data-view') === 'plugins') enterPlugins();
                else S.view = false;
            });
        });
        if (document.querySelector('.view-switch.active[data-view="plugins"]')) enterPlugins();
        else load(true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();

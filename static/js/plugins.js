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
    var API_UNINSTALL = '/api/plugins/uninstall';

    var SRC_LABEL = { friend: '好友', group: '群聊', group_member: '群成员' };
    var TYPE_LABEL = {
        text: '文本', textarea: '长文本', int: '整数', bool: '开关', enum: '单选',
        friend: '好友', group: '群聊', group_member: '群成员'
    };

    var S = {
        summary: null,
        sel: '',
        filter: '',
        tab: 'list',         // 子选项：list | store | web
        detail: {},          // pid -> {fields, values}
        multi: {},           // pid|key -> [value, ...]
        web: {},             // pid -> {url, up, ...}
        // ---- 插件商店 ----
        store: null,         // /store/list 的结果
        storeStatus: null,   // /store/status 的结果（含加速地址清单 / git 情况）
        storeSel: '',        // 选中的插件 key
        storeDetail: {},     // key -> 源站详情（后面补的更全的那份）
        storeQ: '',          // 商店搜索词
        storeProxy: null,    // 选中的线路前缀（'' = 原 GitHub 直连；null = 还没选过）
        storeBusy: '',       // '' | 'speed' | 'install'
        storeLoaded: false,
        storePage: 1,        // 商店网格当前页（每页 15 个 = 3 列 × 5 行）
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

    // 页面内自建确认框。原生 confirm() 在预览 / 内嵌 iframe 里会被浏览器
    // 静默拦截并直接返回 false，表现为「点了按钮没反应」，所以这里自己实现。
    var confirmCb = null;
    function uiConfirm(opts) {
        opts = opts || {};
        return new Promise(function (resolve) {
            var mod = $('pgConfirmModal');
            if (!mod) { toast('确认弹窗没加载出来，刷新页面再试', 'err'); resolve(false); return; }
            var t = $('pgConfirmTitle');
            if (t) t.textContent = opts.title || '确认操作';
            var b = $('pgConfirmBody');
            if (b) b.textContent = opts.text || '';
            var tip = $('pgConfirmTip');
            if (tip) tip.textContent = opts.tip || '';
            var ok = $('pgConfirmOkBtn');
            if (ok) {
                ok.textContent = opts.okText || '确定';
                ok.className = 'ws-btn ' + (opts.danger === false ? 'pg-btn-primary' : 'pg-btn-danger');
            }
            var cancel = $('pgConfirmCancelBtn');
            if (cancel) cancel.textContent = opts.cancelText || '取消';

            confirmCb = function (yes) {
                confirmCb = null;
                closeConfirmModal();
                resolve(!!yes);
            };
            mod.classList.remove('hidden');
            document.body.classList.add('pg-modal-open');
            if (ok && ok.focus) ok.focus({ preventScroll: true });
        });
    }

    function closeConfirmModal() {
        var mod = $('pgConfirmModal');
        if (!mod || mod.classList.contains('hidden')) return;
        mod.classList.add('hidden');
        var inst = $('pgStoreModal');
        if (!inst || inst.classList.contains('hidden')) document.body.classList.remove('pg-modal-open');
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
        if (!S.dirty) { load(); return; }
        uiConfirm({
            title: '放弃未保存的改动？',
            text: '配置表单里还有没保存的改动，刷新会把它们丢掉。',
            tip: '刷新后表单会回到上次保存的状态',
            okText: '刷新',
            cancelText: '先不刷新'
        }).then(function (yes) { if (yes) load(); });
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
                if (act === 'uninstall') { e.stopPropagation(); uninstallPlugin(pid); return; }
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
            +   '<button type="button" class="pg-mini danger" data-act="uninstall" title="删除 plugins/ 下的这个插件目录">卸载</button>'
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
        acts.push('<button type="button" class="ws-btn pg-btn-danger" id="pgBtnUninstall" title="删除 plugins/ 下的整个插件目录">卸载</button>');
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
        if ($('pgBtnUninstall')) $('pgBtnUninstall').addEventListener('click', function () { uninstallPlugin(pid); });

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
    // 子选项切换：插件列表 / 插件商店 / 独立页面（复用 .ws-tabs 滑块组件）
    // ------------------------------------------------------------------
    var PG_PANES = { list: 'pgPaneList', store: 'pgPaneStore', web: 'pgPaneWeb' };
    var PG_HINTS = {
        list: '一个文件夹 = 一个插件',
        store: '来自插件源 · 选加速地址后一键装进 plugins/',
        web: '带 "web": true 的插件 · 端口由 ILBB 分配'
    };

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
        // 窄屏下标签条可横向滚动，滑块是 wrap 的子元素会跟着滚，位移必须补上 scrollLeft
        var x = (r.left - b.left) - bl + wrap.scrollLeft;
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
        if (name === 'store' && !S.storeLoaded) loadStore(false, true);
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
        // data-ilbb-skip：告诉 ILBBSelect 不要接管这个下拉 —— 它复用 .ilbb-select 的
        // 样式，但开合与选中由下面的 initMulti / fillMultiMenu 自己实现。
        // 少了这个标记，两套 handler 会挂在同一个按钮上互相抵消（点了没反应）。
        h += '<div class="ilbb-select pg-multi-select" data-ilbb-skip="1"'
            + ' data-multi="' + esc(f.key) + '"'
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
                // 与静态下拉一致：展开前先收起别的，避免同页多个下拉同时摊开
                if (willOpen && window.ILBBSelect && window.ILBBSelect.closeAll) {
                    window.ILBBSelect.closeAll(sel);
                }
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

    // 卸载：后端会先卸运行实例（触发插件 teardown 释放数据库 / 端口句柄）再删目录，
    // 删完清掉安装记录与配置。这里成功后再刷插件列表 + 商店的「已安装」标记。
    function uninstallPlugin(pid) {
        var p = pluginById(pid);
        if (!p) return;
        var folder = String(p.rel_folder || p.id || '').replace(/^[.\\/]+/, '').replace(/[\\/]+$/, '');
        if (!folder) { toast('拿不到这个插件的目录名，先点「重扫目录」再试', 'err'); return; }
        uiConfirm({
            title: '卸载插件',
            text: '确定要删除 plugins/' + folder + '/ 吗？\n\n'
                + '整个插件目录、它的配置和安装记录都会被清掉，这个操作不能撤销。',
            tip: '会删除 plugins/' + folder + '/',
            okText: '卸载',
            cancelText: '先不删'
        }).then(function (yes) {
            if (!yes) return;
            return api(API_UNINSTALL, { method: 'POST', body: { folder: folder } })
                .then(function (d) {
                    toast(d.msg || ('已删除 plugins/' + folder), 'ok');
                    S.detail = {};
                    if (S.sel === pid) S.sel = '';
                    return load(true).then(function () {
                        if (!S.storeLoaded) return;
                        S.storeDetail = {};                  // 商店详情的「已安装」也要跟着重算
                        return loadStore(true, true).then(function () {
                            if (S.storeSel) renderStoreDetail();
                        });
                    });
                })
                .catch(function (e) { toast('卸载失败：' + e.message, 'err'); });
        });
    }

    // ------------------------------------------------------------------
    // 插件商店子选项
    //   主区：可搜索的插件网格（3 列 × 5 行，每页 15 个）
    //   右侧：插件详情（简介 / 作者 / star / 版本 …）
    //   安装：点「安装」弹出弹窗 → 在里面挑加速地址、测速、改目录名 / 分支 → git clone
    // ------------------------------------------------------------------
    var ST_PAGE_SIZE = 15;                  // 3 列 × 5 行

    var ST_STATUS = '/api/plugins/store/status';
    var ST_LIST = '/api/plugins/store/list';
    var ST_DETAIL = '/api/plugins/store/detail';
    var ST_SPEED = '/api/plugins/store/speedtest';
    var ST_INSTALL = '/api/plugins/store/install';
    var ST_UNINSTALL = '/api/plugins/store/uninstall';

    var ST_PROXY_LS = 'ilbb_store_proxy';   // 记住上次选的线路

    // 读不到返回 null（跟「显式选中直连」的空字符串区分开）
    function lsGet(k) { try { var v = localStorage.getItem(k); return v === null ? null : v; } catch (e) { return null; } }
    function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 隐私模式忽略 */ } }

    function fmtMs(ms) {
        if (ms == null || ms === undefined) return '—';
        if (ms < 1000) return ms + ' ms';
        return (ms / 1000).toFixed(2) + ' s';
    }

    // 把「前缀 + 仓库地址」拼成真正会访问的地址（跟后端 apply_proxy 一个逻辑）
    function realUrl(prefix, repo) {
        var r = String(repo || '').trim();
        if (!r) return '';
        if (!prefix) return r;
        if (r.indexOf(prefix) === 0) return r;
        return String(prefix).replace(/\/+$/, '') + '/' + r.replace(/^\/+/, '');
    }

    // 仓库名 → 候选目录名（默认目录名，装完前给用户看一眼）
    function guessFolder(url) {
        var s = String(url || '').replace(/[?#].*$/, '').replace(/\/+$/, '');
        var seg = s.split('/').pop() || '';
        seg = seg.replace(/\.git$/i, '').replace(/[^A-Za-z0-9_\-]/g, '_');
        if (/^[._\-]/.test(seg)) seg = 'p' + seg;
        return seg.slice(0, 64);
    }

    function storeList() {
        var st = S.storeStatus || {};
        return Array.isArray(st.candidates) ? st.candidates : [];
    }

    // 当前线路：S.storeProxy 为 null = 还没选过 → 默认第一条加速站（直连国内太慢，不适合当默认）
    function proxyCurrent() {
        var list = storeList();
        if (!list.length) return '';
        for (var i = 0; i < list.length; i++) {
            if (S.storeProxy !== null && list[i].prefix === S.storeProxy) return list[i].prefix;
        }
        for (var j = 0; j < list.length; j++) if (!list[j].direct) return list[j].prefix;
        return '';
    }

    function proxyLabel(prefix) {
        var list = storeList();
        for (var i = 0; i < list.length; i++) if (list[i].prefix === prefix) return list[i].label;
        return prefix || '原 GitHub（直连）';
    }

    function proxyEl(prefix) {
        var box = $('pgStoreProxies');
        if (!box) return null;
        var nodes = box.querySelectorAll('.pg-proxy');
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].getAttribute('data-prefix') === prefix) return nodes[i];
        }
        return null;
    }

    // 前缀 -> 候选序号（后端测速用 id 定位单条线路）
    function proxyId(prefix) {
        var list = storeList();
        for (var i = 0; i < list.length; i++) {
            if (list[i].prefix === prefix) return String(list[i].id);
        }
        return '';
    }

    function setProxy(prefix, quiet) {
        S.storeProxy = prefix;
        lsSet(ST_PROXY_LS, prefix);
        syncProxyUI();
        if (quiet !== true) renderStoreRealUrl();
    }

    function syncProxyUI() {
        var cur = proxyCurrent();
        var box = $('pgStoreProxies');
        if (box) {
            var nodes = box.querySelectorAll('.pg-proxy');
            for (var i = 0; i < nodes.length; i++) {
                nodes[i].classList.toggle('active', nodes[i].getAttribute('data-prefix') === cur);
            }
        }
        renderStoreRealUrl();
    }

    function renderStoreRealUrl() {
        var box = $('pgStoreRealUrl');
        if (!box) return;
        var p = curStorePlugin();
        var repo = p ? (p.clone_url || p.repo || '') : '';
        if (!p) { box.textContent = ''; return; }
        var real = realUrl(proxyCurrent(), repo);
        box.innerHTML = '<span class="k">实际下载地址</span><code class="pg-mono">' + esc(real || '—') + '</code>';
    }

    // ---- 加速地址列表 ----
    function renderStoreProxies() {
        var box = $('pgStoreProxies');
        if (!box) return;
        var list = storeList();
        if (!list.length) {
            box.innerHTML = '<div class="pg-tip-inline">没读到加速地址。检查设置里的「GitHub 加速地址」，'
                + '或本页的 PLUGIN_GIT_PROXIES 配置。</div>';
            return;
        }
        var cur = proxyCurrent();
        box.innerHTML = list.map(function (c) {
            return '<div class="pg-proxy' + (c.prefix === cur ? ' active' : '') + (c.direct ? ' direct' : '') + '"'
                + ' data-prefix="' + esc(c.prefix) + '" data-id="' + esc(c.id) + '"'
                + ' title="' + esc(c.direct ? '官方地址，不加任何前缀' : c.prefix) + '">'
                + '<span class="pg-proxy-radio" aria-hidden="true"></span>'
                + '<div class="pg-proxy-main">'
                +   '<b class="pg-proxy-name">' + esc(c.label) + '</b>'
                +   '<code class="pg-proxy-url">' + esc(c.direct ? 'https://github.com/…' : String(c.prefix).replace(/\/+$/, '')) + '</code>'
                + '</div>'
                + '<span class="pg-proxy-ms">未测</span>'
                + '</div>';
        }).join('');
        Array.prototype.forEach.call(box.querySelectorAll('.pg-proxy'), function (el) {
            el.addEventListener('click', function () {
                setProxy(el.getAttribute('data-prefix'));
                var tip = $('pgStoreSpeedTip');
                if (tip) tip.textContent = '已选：' + proxyLabel(S.storeProxy);
            });
        });
        syncProxyUI();
    }

    function paintProxyResult(d) {
        var box = $('pgStoreProxies');
        if (!box) return;
        var map = {};
        (d.results || []).forEach(function (r) { map[r.prefix + '\u0000' + r.id] = r; });
        Array.prototype.forEach.call(box.querySelectorAll('.pg-proxy'), function (el) {
            var prefix = el.getAttribute('data-prefix');
            var id = el.getAttribute('data-id');
            var r = map[prefix + '\u0000' + id];
            if (!r) return;
            var ms = el.querySelector('.pg-proxy-ms');
            el.classList.remove('ok', 'bad', 'best', 'testing');
            if (r.best) el.classList.add('best');
            if (r.ok) {
                el.classList.add('ok');
                if (ms) { ms.textContent = fmtMs(r.ms); ms.title = '首字节 ' + fmtMs(r.ms) + '（握手 ' + fmtMs(r.ttfb_ms) + '）'; }
            } else {
                el.classList.add('bad');
                if (ms) { ms.textContent = '失败'; ms.title = r.error || ('HTTP ' + r.status); }
            }
        });
        var okn = $('pgStoreSpeedHint');
        if (okn) {
            okn.textContent = d.ok_count + ' / ' + d.total + ' 条可用 · 耗时 ' + d.elapsed + 's';
        }
    }

    // ---- 测速：只测一条 / 测全部并自动跳到最快 ----
    function runSpeed(only) {
        if (S.storeBusy === 'speed') return;
        var repo = (S.storeStatus && S.storeStatus.test_repo) || '';
        var body = { repo: repo };
        if (only !== undefined) body.only = only;
        S.storeBusy = 'speed';
        var btn = $('pgStoreSpeedBtn');
        var old = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = '测速中…'; }
        var box = $('pgStoreProxies');
        if (box) Array.prototype.forEach.call(box.querySelectorAll('.pg-proxy'), function (el) {
            el.classList.remove('ok', 'bad', 'best');
            el.classList.add('testing');
            var ms = el.querySelector('.pg-proxy-ms');
            if (ms) ms.textContent = '…';
        });
        var tip = $('pgStoreSpeedTip');
        if (tip) tip.textContent = '正在测速' + (only === undefined ? '（全部线路）' : '（当前线路）') + '…';

        api(ST_SPEED, { method: 'POST', body: body }).then(function (d) {
            paintProxyResult(d);
            var best = null;
            (d.results || []).forEach(function (r) { if (r.best) best = r; });
            if (only !== undefined) {
                // 只测当前线路：不抢选择权，只报结果
                var one = (d.results || [])[0] || null;
                if (tip) {
                    tip.textContent = (one && one.ok)
                        ? ('当前线路可用：' + fmtMs(one.ms))
                        : ('当前线路没测通' + (one && one.error ? '：' + one.error : ''));
                }
                if (one && one.ok) toast('当前线路可用 · ' + fmtMs(one.ms), 'ok');
                else toast('当前线路没测通，换一条或点「测速选最快」', 'err');
                return;
            }
            if (best) {
                setProxy(best.prefix);
                var el = proxyEl(best.prefix);
                if (el) {
                    el.classList.add('best');
                    // 自动滑动到最快的那条
                    if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                    else el.scrollIntoView(false);
                }
                if (tip) tip.textContent = '最快：' + best.label + '（' + fmtMs(best.ms) + '）已自动选中';
                toast('已选中最快线路：' + best.label + ' · ' + fmtMs(best.ms), 'ok');
            } else {
                if (tip) tip.textContent = '全部线路都没测通，检查网络或换一条试试';
                toast('所有线路都测不通，可先试试「原 GitHub（直连）」', 'err');
            }
        }).catch(function (e) {
            if (tip) tip.textContent = '测速失败：' + e.message;
            toast('测速失败：' + e.message, 'err');
            if (box) Array.prototype.forEach.call(box.querySelectorAll('.pg-proxy'), function (el) {
                el.classList.remove('testing');
            });
        }).then(function () {
            S.storeBusy = '';
            if (btn) { btn.disabled = false; btn.textContent = old || '测速选最快'; }
        });
    }

    // ---- 商店列表 ----
    function loadStore(force, silent) {
        var jobs = [];
        var needStatus = force || !S.storeStatus;
        if (needStatus) {
            jobs.push(api(ST_STATUS).then(function (d) {
                S.storeStatus = d;
                renderStoreProxies();
                renderStoreSrc();
            }));
        }
        jobs.push(api(ST_LIST + (force ? '?force=1' : '')).then(function (d) {
            S.store = d;
            S.storeLoaded = true;
            if (force) S.storePage = 1;
            renderStoreList();
            renderStoreSrc();
        }));
        return Promise.all(jobs).catch(function (e) {
            var box = $('pgStoreList');
            if (box) box.innerHTML = '<div class="console-empty">读取插件源失败：' + esc(e.message)
                + '</div><div class="pg-tip-inline">插件源地址在「设置 → 插件系统 → 插件源地址」里改。</div>';
            var tip = $('pgStoreSrcTip');
            if (tip) tip.textContent = '插件源：读取失败 · ' + e.message;
            if (!silent) toast('读取插件源失败：' + e.message, 'err');
            throw e;
        });
    }

    function renderStoreSrc() {
        var tip = $('pgStoreSrcTip');
        var st = S.storeStatus || {};
        var d = S.store;
        var parts = [];
        parts.push('插件源：' + (st.store_url || (d && d.store_url) || '（未配置）'));
        if (d && d.total !== undefined) parts.push('共 ' + d.total + ' 个');
        if (st.git) parts.push(st.git.available ? ('git ' + (st.git.version || '可用')) : 'git 不可用，无法安装');
        if (st.proxy_count !== undefined) parts.push('加速地址 ' + st.proxy_count + ' 条');
        if (d && d.cached) parts.push('缓存结果，点「刷新列表」重新拉');
        if (tip) tip.textContent = parts.join(' · ');
    }

    function storeFiltered() {
        var list = (S.store && S.store.plugins) || [];
        var q = String(S.storeQ || '').trim().toLowerCase();
        if (!q) return list;
        return list.filter(function (p) {
            var hay = [p.name, p.slug, p.chinese_name, p.author, p.about, p.description,
                       p.repo_full_name, (p.tags || []).join(' ')].join(' ').toLowerCase();
            return hay.indexOf(q) !== -1;
        });
    }

    // 当前筛选结果的页码信息（顺便把越界的 S.storePage 拉回来）
    function storePages() {
        var list = storeFiltered();
        var pages = Math.max(1, Math.ceil(list.length / ST_PAGE_SIZE));
        if (S.storePage > pages) S.storePage = pages;
        if (!S.storePage || S.storePage < 1) S.storePage = 1;
        return { list: list, pages: pages };
    }

    function renderStoreList() {
        var box = $('pgStoreList');
        if (!box) return;
        if (!S.store) {
            box.innerHTML = '<div class="console-empty">正在读取插件源…</div>';
            renderStorePager();
            return;
        }
        var pg = storePages();
        var list = pg.list;
        var total = (S.store.plugins || []).length;
        var hint = $('pgStoreCountHint');
        if (hint) {
            hint.textContent = (S.storeQ ? ('匹配 ' + list.length + ' / 共 ' + total) : ('共 ' + total + ' 个'))
                + (S.store.installed_count ? ' · 已装 ' + S.store.installed_count : '')
                + (list.length > ST_PAGE_SIZE ? ' · 第 ' + S.storePage + '/' + pg.pages + ' 页' : '');
        }
        if (!list.length) {
            box.innerHTML = '<div class="console-empty">'
                + (S.storeQ ? '没有匹配的插件，换个关键词试试。' : '插件源里还没有插件。')
                + '</div>';
            renderStorePager();
            return;
        }
        // 3 列 × 5 行 = 一页 15 个
        var start = (S.storePage - 1) * ST_PAGE_SIZE;
        var slice = list.slice(start, start + ST_PAGE_SIZE);
        box.innerHTML = slice.map(storeCardHtml).join('');
        Array.prototype.forEach.call(box.querySelectorAll('.pg-card'), function (card) {
            card.addEventListener('click', function () {
                selectStorePlugin(card.getAttribute('data-key'));
            });
            var qi = card.querySelector('.pg-card-install');
            if (qi) qi.addEventListener('click', function (ev) {
                ev.stopPropagation();
                selectStorePlugin(card.getAttribute('data-key'));
                openInstallModal();
            });
        });
        renderStorePager();
    }

    // 分页器：上一页 / 页码窗口 / 下一页
    function renderStorePager() {
        var box = $('pgStorePager');
        if (!box) return;
        if (!S.store) { box.innerHTML = ''; return; }
        var list = storeFiltered();
        var pages = Math.max(1, Math.ceil(list.length / ST_PAGE_SIZE));
        if (pages <= 1) { box.innerHTML = ''; return; }
        var cur = S.storePage;
        var out = [];
        out.push('<button type="button" class="pg-page-btn pg-page-nav" data-page="' + (cur - 1) + '"'
            + (cur <= 1 ? ' disabled' : '') + '>上一页</button>');
        var from = Math.max(1, cur - 2);
        var to = Math.min(pages, cur + 2);
        if (from > 1) {
            out.push(pageBtnHtml(1, cur));
            if (from > 2) out.push('<span class="pg-page-gap">…</span>');
        }
        for (var i = from; i <= to; i++) out.push(pageBtnHtml(i, cur));
        if (to < pages) {
            if (to < pages - 1) out.push('<span class="pg-page-gap">…</span>');
            out.push(pageBtnHtml(pages, cur));
        }
        out.push('<button type="button" class="pg-page-btn pg-page-nav" data-page="' + (cur + 1) + '"'
            + (cur >= pages ? ' disabled' : '') + '>下一页</button>');
        out.push('<span class="pg-page-info">共 ' + list.length + ' 个 · ' + pages + ' 页</span>');
        box.innerHTML = out.join('');
        Array.prototype.forEach.call(box.querySelectorAll('.pg-page-btn'), function (b) {
            b.addEventListener('click', function () {
                var n = parseInt(b.getAttribute('data-page'), 10);
                if (!n || n === S.storePage || n < 1 || n > pages) return;
                S.storePage = n;
                renderStoreList();
                var blk = $('pgStoreList');
                if (blk && blk.scrollIntoView) blk.scrollIntoView({ block: 'start', behavior: 'smooth' });
            });
        });
    }

    function pageBtnHtml(n, cur) {
        return '<button type="button" class="pg-page-btn' + (n === cur ? ' active' : '') + '"'
            + ' data-page="' + n + '"' + (n === cur ? ' aria-current="page"' : '') + '>' + n + '</button>';
    }

    // 卡片：插件名 + 中文名 + 简介 + 作者 + GitHub star
    function storeCardHtml(p) {
        var key = storeKey(p);
        var tags = [];
        if (p.installed) {
            var where = (p.installed_folders || []).join('、');
            tags.push('<span class="pg-tag ok" title="'
                + esc('plugins/' + where + (p.install_source === 'store' ? '（本商店安装）' : '（本地已有目录）'))
                + '">已安装</span>');
        }
        if (p.latest_version) tags.push('<span class="pg-tag info">v' + esc(p.latest_version) + '</span>');
        if (p.archived) tags.push('<span class="pg-tag warn">已归档</span>');
        (p.tags || []).slice(0, 2).forEach(function (t) {
            tags.push('<span class="pg-tag">' + esc(t) + '</span>');
        });
        var name = p.name || p.slug || key;
        var cn = p.chinese_name || '';
        var desc = String(p.about || p.description || '').replace(/\s+/g, ' ').trim();
        var author = p.author || p.owner || '';
        var stars = (p.stars === null || p.stars === undefined) ? 0 : p.stars;
        return '<article class="pg-card' + (key === S.storeSel ? ' active' : '') + '" data-key="' + esc(key) + '"'
            + ' title="' + esc(p.repo_full_name || name) + '">'
            + '<button type="button" class="pg-card-install" title="安装这个插件">安装</button>'
            + '<div class="pg-card-top">'
            +   '<span class="pg-dot ' + (p.installed ? 'on' : 'off') + '"></span>'
            +   '<b class="pg-card-name">' + esc(name) + '</b>'
            + '</div>'
            + (cn && cn !== name ? '<div class="pg-card-cn">' + esc(cn) + '</div>' : '')
            + '<div class="pg-card-desc">' + esc(desc ? desc.slice(0, 96) : '这个插件没有写简介。') + '</div>'
            + '<div class="pg-card-foot">'
            +   '<span class="pg-card-author" title="作者"><svg viewBox="0 0 16 16" aria-hidden="true">'
            +     '<circle cx="8" cy="5.3" r="2.7"></circle>'
            +     '<path d="M2.9 13.6c0-2.7 2.3-4.3 5.1-4.3s5.1 1.6 5.1 4.3"></path></svg>'
            +     esc(author || '未知作者') + '</span>'
            +   '<span class="pg-card-star" title="GitHub 星标数"><svg viewBox="0 0 16 16" aria-hidden="true">'
            +     '<path d="M8 1.9l1.86 3.84 4.24.6-3.07 2.95.73 4.21L8 11.5l-3.76 2 .73-4.21L1.9 6.34l4.24-.6z"></path>'
            +     '</svg>' + esc(stars) + '</span>'
            + '</div>'
            + (tags.length ? '<div class="pg-card-tags">' + tags.join('') + '</div>' : '')
            + '</article>';
    }

    function storeKey(p) {
        return String(p.slug || p.repo_full_name || p.repo || p.name || '').trim();
    }

    function storePlugin(key) {
        var list = (S.store && S.store.plugins) || [];
        for (var i = 0; i < list.length; i++) if (storeKey(list[i]) === key) return list[i];
        return null;
    }

    function curStorePlugin() {
        return S.storeSel ? storePlugin(S.storeSel) : null;
    }

    function selectStorePlugin(key) {
        S.storeSel = key || '';
        renderStoreList();
        renderStoreDetail();
        var box = $('pgStoreList');
        if (box && key) {
            var card = box.querySelector('.pg-card[data-key="' + cssAttr(key) + '"]');
            if (card) card.classList.add('active');
        }
        // 详情里补一份源站数据（列表里可能没带全）
        var p = curStorePlugin();
        if (!p || S.storeDetail[key]) return;
        api(ST_DETAIL + '?key=' + encodeURIComponent(key)).then(function (d) {
            S.storeDetail[key] = d.plugin || {};
            if (S.storeSel === key) renderStoreDetail();
        }).catch(function () { /* 详情拿不到就用列表里的信息，不打扰用户 */ });
    }

    function cssAttr(s) {
        return String(s).replace(/["\\]/g, '\\$&');
    }

    function storeInfo() {
        var p = curStorePlugin();
        if (!p) return null;
        var rich = S.storeDetail[S.storeSel];
        return rich ? mergeStore(p, rich) : p;
    }

    function mergeStore(base, rich) {
        var out = {};
        Object.keys(base).forEach(function (k) { out[k] = base[k]; });
        Object.keys(rich || {}).forEach(function (k) {
            if (rich[k] !== null && rich[k] !== undefined && rich[k] !== '') out[k] = rich[k];
        });
        return out;
    }

    function renderStoreDetail() {
        var empty = $('pgStoreEmpty');
        var det = $('pgStoreDetail');
        var title = $('pgStoreDetailTitle');
        var hint = $('pgStoreDetailHint');
        var p = storeInfo();
        if (!p) {
            if (empty) empty.classList.remove('hidden');
            if (det) det.classList.add('hidden');
            if (title) title.textContent = '插件详情';
            if (hint) hint.textContent = '从左边的网格里选一个插件';
            return;
        }
        if (empty) empty.classList.add('hidden');
        if (det) det.classList.remove('hidden');
        if (title) title.textContent = p.name || p.slug || '插件详情';
        var fold = guessFolder(p.clone_url || p.repo || '');
        // 已安装的目录来自后端「磁盘扫描 ∪ 安装记录」，所以本地手工放进去的插件也会显示在这
        if (hint) hint.textContent = p.installed
            ? ('已装在 plugins/' + (p.installed_folders || []).join('、')
               + (p.install_source === 'store' ? '（本商店安装）' : '（本地已有目录）'))
            : ('将装到 plugins/' + (fold || '?'));

        var rows = [
            ['仓库', p.repo_full_name || '—', p.repo || ''],
            ['作者', p.author || '—'],
            ['许可', p.license || '—'],
            ['版本', (p.latest_version ? 'v' + p.latest_version : '—') + (p.version_count > 1 ? '（共 ' + p.version_count + ' 个）' : '')],
            ['分支', p.latest_branch || p.default_branch || '—'],
            ['星标', p.stars == null ? '—' : (p.stars + ' ★ / ' + (p.forks || 0) + ' fork')],
            ['最低 ILBB', p.min_ilbb || '—'],
            ['更新时间', p.updated_at || p.uploaded_at || '—'],
        ];
        if ((p.tags || []).length) rows.push(['标签', (p.tags || []).join(' / ')]);
        var meta = $('pgStoreMeta');
        if (meta) {
            meta.innerHTML = rows.map(function (r) {
                return '<div class="pg-meta-row"><span class="k">' + esc(r[0]) + '</span>'
                    + '<span class="v"' + (r[2] ? ' title="' + esc(r[2]) + '"' : '') + '>'
                    + esc(String(r[1])) + '</span></div>';
            }).join('');
        }

        var about = $('pgStoreAbout');
        if (about) {
            var text = p.description || p.about || '';
            about.innerHTML = text
                ? '<p>' + esc(text).replace(/\n/g, '<br>') + '</p>'
                : '<p class="pg-tip-inline">这个插件没有写介绍。</p>';
        }

        var nameEl = $('pgStoreName');
        if (nameEl) nameEl.placeholder = '默认：' + (fold || '仓库名');

        var acts = $('pgStoreActions');
        if (acts) {
            var h = '<button type="button" class="ws-btn pg-btn-primary" id="pgStoreOpenModalBtn">'
                + (p.installed ? '重新安装…' : '安装到 plugins/…') + '</button>';
            if (p.detail_url || p.repo) {
                h += '<button type="button" class="ws-btn" id="pgStoreOpenBtn">源站页面</button>';
            }
            if (p.installed) {
                h += '<button type="button" class="ws-btn pg-btn-danger" id="pgStoreDelBtn">卸载</button>';
            }
            acts.innerHTML = h;
            bindStoreActions(p);
        }
        renderStoreRealUrl();
        var ih = $('pgStoreInstallHint');
        if (ih) {
            ih.textContent = 'clone 深度 ' + ((S.storeStatus && S.storeStatus.git && S.storeStatus.git.depth) || 1)
                + ' · 装好后热重载自动识别，不用重启';
        }
        if (!S.storeStatus || !S.storeStatus.git || !S.storeStatus.git.available) {
            if (ih) ih.textContent = '没找到 git，装不了。请在设置里填「git 路径」或装上 git';
        }
    }

    function bindStoreActions(p) {
        var ins = $('pgStoreOpenModalBtn');
        if (ins) ins.addEventListener('click', openInstallModal);
        var del = $('pgStoreDelBtn');
        if (del) del.addEventListener('click', function () { doStoreUninstall(p); });
        var op = $('pgStoreOpenBtn');
        if (op) op.addEventListener('click', function () {
            var u = p.detail_url || p.repo;
            if (!u) return;
            var w = null;
            try { w = window.open(u, '_blank'); } catch (e) { w = null; }
            // 预览 / 内嵌环境常常拦掉新窗口，此时把地址给用户自己复制
            if (!w) toast('浏览器拦了新窗口，地址：' + u, 'err');
        });
    }

    // ---- 安装弹窗：在这里挑加速地址 + 调安装参数 ----
    function openInstallModal() {
        var p = curStorePlugin();
        if (!p) { toast('先选一个插件', 'err'); return; }
        if (!S.storeStatus || !S.storeStatus.git || !S.storeStatus.git.available) {
            toast('没找到 git，装不了。请在设置里填「git 路径」或装上 git', 'err');
            return;
        }
        var mod = $('pgStoreModal');
        if (!mod) return;
        var fold = guessFolder(p.clone_url || p.repo || '');

        var mt = $('pgStoreModalTitle');
        if (mt) mt.textContent = p.installed ? '重新安装插件' : '安装插件';
        var mn = $('pgStoreModalName');
        if (mn) mn.textContent = p.name || p.slug || p.chinese_name || '插件';
        var mr = $('pgStoreModalRepo');
        if (mr) mr.textContent = (p.author ? '作者 ' + p.author + ' · ' : '')
            + (p.repo_full_name || p.repo || '');

        var sh = $('pgStoreSpeedHint');
        if (sh) sh.textContent = '共 ' + storeList().length + ' 条线路可选';
        var st = $('pgStoreSpeedTip');
        if (st) st.textContent = '还没测速';

        var nameEl = $('pgStoreName');
        if (nameEl) {
            nameEl.value = '';
            nameEl.placeholder = '默认：' + (fold || '仓库名');
        }
        var brEl = $('pgStoreBranch');
        if (brEl) brEl.value = '';
        var foEl = $('pgStoreForce');
        if (foEl) foEl.checked = !!p.installed;      // 已装过的默认勾上，方便直接覆盖重装

        var tip = $('pgStoreModalTip');
        if (tip) tip.textContent = '装好后热重载自动识别，不用重启';
        var ins = $('pgStoreInstallBtn');
        if (ins) { ins.disabled = false; ins.textContent = p.installed ? '重新安装' : '开始安装'; }

        mod.classList.remove('hidden');
        document.body.classList.add('pg-modal-open');

        renderStoreProxies();       // 内部会 syncProxyUI + 刷新实际地址
        renderStoreRealUrl();
        if (ins && ins.focus) ins.focus({ preventScroll: true });
    }

    function closeInstallModal() {
        var mod = $('pgStoreModal');
        if (!mod || mod.classList.contains('hidden')) return;
        mod.classList.add('hidden');
        document.body.classList.remove('pg-modal-open');
        var b = $('pgStoreInstallBtn');
        if (b && S.storeBusy !== 'install') {
            var p = curStorePlugin();
            b.textContent = (p && p.installed) ? '重新安装' : '开始安装';
        }
    }

    function storeLog(kind, lines) {
        var box = $('pgStoreLog');
        if (!box) return;
        box.classList.remove('hidden');
        box.className = 'pg-store-log ' + (kind || '');
        box.innerHTML = lines.map(function (l) {
            return '<div class="pg-store-log-line">' + esc(l) + '</div>';
        }).join('');
    }

    function doStoreInstall() {
        if (S.storeBusy) return;
        var p = curStorePlugin();
        if (!p) { toast('先选一个插件', 'err'); return; }
        if (!S.storeStatus || !S.storeStatus.git || !S.storeStatus.git.available) {
            toast('没找到 git，无法安装', 'err');
            return;
        }
        var repo = p.clone_url || p.repo || '';
        if (!repo) { toast('这个插件没有仓库地址', 'err'); return; }
        var prefix = proxyCurrent();
        var label = proxyLabel(prefix);
        var nameEl = $('pgStoreName');
        var brEl = $('pgStoreBranch');
        var foEl = $('pgStoreForce');
        var name = (nameEl && nameEl.value || '').trim();
        var branch = (brEl && brEl.value || '').trim();
        var force = !!(foEl && foEl.checked);
        var folder = name ? guessFolder(name) : guessFolder(repo);
        var real = realUrl(prefix, repo);

        S.storeBusy = 'install';
        var btn = $('pgStoreInstallBtn');
        if (btn) { btn.disabled = true; btn.textContent = '安装中…'; }
        var tip = $('pgStoreModalTip');
        if (tip) tip.textContent = '正在用 ' + label + ' 拉取…';
        storeLog('', [
            '正在用 ' + label + ' 拉取…',
            'git clone ' + real,
            '目录 plugins/' + (folder || '(仓库名)') + '/'
                + (branch ? ' · 分支 ' + branch : '')
                + (force ? ' · 覆盖重装' : '')
        ]);

        api(ST_INSTALL, {
            method: 'POST',
            body: { repo: repo, proxy: prefix, branch: branch, name: name, force: force }
        }).then(function (d) {
            if (tip) tip.textContent = '✓ ' + (d.msg || '安装完成');
            storeLog('ok', [
                '✓ ' + (d.msg || '安装完成'),
                '仓库：' + (d.repo || repo),
                '线路：' + (d.proxy_label || label) + (d.proxy_ms ? '（' + fmtMs(d.proxy_ms) + '）' : ''),
                '分支：' + (d.branch || 'default') + ' · 深度 ' + (d.depth || 1) + ' · 耗时 ' + (d.elapsed || 0) + 's'
            ].concat(d.flattened ? ['提示：仓库里套了一层目录，已自动把内容提到 plugins/' + d.folder + '/'] : [])
             .concat(d.warn ? ['警告：' + d.warn] : []));
            toast(d.warn ? ('已装好，但有冲突：' + (d.id || d.folder)) : ('已装好：' + (d.id || d.folder)),
                  d.warn ? 'err' : 'ok');
            // 刷新商店（已安装标记）与插件列表（新插件）
            return loadStore(true, true).then(function () {
                if (S.storeSel) renderStoreDetail();
                return load(true);
            });
        }).catch(function (e) {
            if (tip) tip.textContent = '✗ 安装失败：' + e.message;
            storeLog('err', ['✗ 安装失败：' + e.message]);
            toast('安装失败：' + e.message, 'err');
        }).then(function () {
            S.storeBusy = '';
            var b = $('pgStoreInstallBtn');
            if (b) {
                b.disabled = false;
                b.textContent = p.installed ? '重新安装' : '开始安装';
            }
        });
    }

    function doStoreUninstall(p) {
        if (S.storeBusy) { toast('上一个操作还没跑完，稍等一下', 'err'); return; }
        var folders = (p && p.installed_folders) || [];
        if (!folders.length) {
            // 已安装标记和目录列表是同一次后端计算出来的，理论上不会只缺一个；
            // 真缺了就让用户手动刷一下商店，别在这里瞎猜目录名删错东西。
            toast('没找到它在 plugins/ 里的目录。点一下「刷新列表」再试', 'err');
            storeLog('err', ['✗ 后端没给出这个插件的 plugins/ 目录名，'
                + '点「刷新列表」重新读取一遍再试。']);
            return;
        }
        var folder = String(folders[0]);
        uiConfirm({
            title: '卸载插件',
            text: '确定要把 plugins/' + folder + '/ 整个删掉吗？\n\n'
                + '该插件的配置文件也会被删掉，这个操作不能撤销。',
            tip: '会删除 plugins/' + folder + '/',
            okText: '卸载',
            cancelText: '先不删'
        }).then(function (yes) {
            if (!yes) return;
            S.storeBusy = 'install';
            storeLog('', ['正在删除 plugins/' + folder + '/ …']);
            return api(ST_UNINSTALL, { method: 'POST', body: { folder: folder } }).then(function (d) {
                storeLog('ok', ['✓ ' + (d.msg || '已卸载')]);
                toast('已卸载 ' + folder, 'ok');
                S.storeDetail = {};
                return loadStore(true, true).then(function () {
                    if (S.storeSel) renderStoreDetail();
                    return load(true);
                });
            }).catch(function (e) {
                storeLog('err', ['✗ 卸载失败：' + e.message]);
                toast('卸载失败：' + e.message, 'err');
            }).then(function () { S.storeBusy = ''; });
        });
    }

    function checkStoreEnv() {
        api(ST_STATUS).then(function (d) {
            S.storeStatus = d;
            renderStoreProxies();
            renderStoreSrc();
            var g = d.git || {};
            toast('插件源 ' + (d.store_url || '未配置') + ' · '
                + (g.available ? ('git ' + (g.version || '')) : 'git 不可用')
                + ' · 加速地址 ' + d.proxy_count + ' 条', g.available ? 'ok' : 'err');
        }).catch(function (e) { toast('检查失败：' + e.message, 'err'); });
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

        // 子选项：插件列表 / 插件商店 / 独立页面
        pgTabEls().forEach(function (b) {
            b.addEventListener('click', function () { switchPgTab(b.getAttribute('data-pg-tab')); });
        });

        // ---- 插件商店 ----
        S.storeProxy = lsGet(ST_PROXY_LS);          // 记住上次选的线路
        $('pgStoreRefreshBtn').addEventListener('click', function () {
            loadStore(true).then(function () { toast('插件源列表已刷新', 'ok'); })
                .catch(function () { /* loadStore 里已经提示过了 */ });
        });
        $('pgStoreStatusBtn').addEventListener('click', checkStoreEnv);
        $('pgStoreSearch').addEventListener('input', function () {
            S.storeQ = this.value || '';
            S.storePage = 1;                    // 换了关键词就回到第一页
            renderStoreList();
        });
        $('pgStoreSpeedBtn').addEventListener('click', function () { runSpeed(); });
        $('pgStoreProxyTestBtn').addEventListener('click', function () {
            var tip = $('pgStoreSpeedTip');
            if (tip) tip.textContent = '只测当前线路…';
            runSpeed(proxyId(proxyCurrent()));
        });

        // 安装弹窗：遮罩 / 右上角 × / 取消 都带 data-pg-close，交给安装按钮
        var mod = $('pgStoreModal');
        if (mod) {
            mod.addEventListener('click', function (ev) {
                var t = ev.target;
                if (t && t.getAttribute && t.getAttribute('data-pg-close')) closeInstallModal();
            });
        }
        $('pgStoreInstallBtn').addEventListener('click', doStoreInstall);

        // 通用确认弹窗：确定 / 取消 / 遮罩 / × 都用 data-pg-confirm 标记
        var cmod = $('pgConfirmModal');
        if (cmod) {
            cmod.addEventListener('click', function (ev) {
                var t = ev.target;
                if (!t || !t.getAttribute) return;
                var v = t.getAttribute('data-pg-confirm');
                if (v === null) return;
                if (confirmCb) confirmCb(v === '1'); else closeConfirmModal();
            });
        }
        document.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Escape' && ev.key !== 'Esc') return;
            if (cmod && !cmod.classList.contains('hidden')) {
                if (confirmCb) confirmCb(false); else closeConfirmModal();
                return;
            }
            if (mod && !mod.classList.contains('hidden')) closeInstallModal();
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

    // 其它脚本（console.js / main.js 等）复用同一套页面内确认框。
    // 原生 confirm() 在预览 / 内嵌 iframe 里会被静默拦截并返回 false，
    // 所以统一走这里；没有这个函数时调用方要自己兜底。
    window.uiConfirm = uiConfirm;
    window.uiConfirmClose = closeConfirmModal;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();

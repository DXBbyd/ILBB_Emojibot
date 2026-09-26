/* setup.js — 首次运行引导页（/setup）
 * 四步向导：环境自检 → Meme 素材 → 基础配置 → 完成
 * 对接接口（均在 app.py 内，未登录可访问）：
 *   GET  /api/setup/state               首屏状态（不联网、不扫盘）
 *   GET  /api/setup/env-check           依赖 / 引擎 / 目录自检
 *   GET  /api/setup/check?deep=&refresh= 体检素材
 *   POST /api/setup/assets/download     补全下载（后台任务）
 *   GET  /api/setup/assets/progress     下载进度
 *   POST /api/setup/assets/cancel       取消下载
 *   GET  /api/setup/config              配置表单（白名单）
 *   POST /api/setup/config              保存配置（写 .env + 热重载）
 *   POST /api/setup/complete            完成引导（首次运行可顺带设管理密码）
 *   POST /api/setup/skip                跳过（what=assets|all）
 */
(function () {
    'use strict';

    var API = '/api/setup';

    var S = {
        step: 1,
        state: null,
        envLoaded: false,
        assetLoaded: false,
        cfgLoaded: false,
        cfgGroups: [],
        pollTimer: null,
        busy: false,
        toastTimer: null,
        finished: false
    };

    // ---------- 小工具 ----------
    function $(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function fmtBytes(n) {
        n = Number(n) || 0;
        if (n < 1024) return n + ' B';
        var u = ['KB', 'MB', 'GB', 'TB'], i = -1;
        do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
        return (n >= 100 ? n.toFixed(0) : n.toFixed(1)) + ' ' + u[i];
    }

    function fmtTime(ts) {
        ts = Number(ts) || 0;
        if (!ts) return '—';
        var d = new Date(ts * 1000);
        function p(x) { return (x < 10 ? '0' : '') + x; }
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
            ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }

    function toast(msg, kind) {
        var t = $('toast');
        t.className = 'toast show' + (kind ? ' ' + kind : '');
        t.textContent = msg;
        if (S.toastTimer) clearTimeout(S.toastTimer);
        S.toastTimer = setTimeout(function () { t.className = 'toast'; }, 3600);
    }

    // 带超时护栏的 fetch（避免请求卡住页面）
    function api(path, opts, timeoutMs) {
        opts = opts || {};
        var ctrl = new AbortController();
        var timer = setTimeout(function () { ctrl.abort(); }, timeoutMs || 30000);
        var init = {
            method: opts.method || 'GET',
            cache: 'no-store',
            signal: ctrl.signal
        };
        if (opts.body) {
            init.headers = { 'Content-Type': 'application/json' };
            init.body = JSON.stringify(opts.body);
        }
        return fetch(API + path, init).then(function (res) {
            clearTimeout(timer);
            return res.json().catch(function () { return null; }).then(function (data) {
                if (!data || typeof data !== 'object') {
                    throw new Error('服务返回异常（HTTP ' + res.status + '）');
                }
                if (data.ok === undefined) data.ok = res.ok;
                if (!res.ok && !data.error) data.error = 'HTTP ' + res.status;
                return data;
            });
        }, function (e) {
            clearTimeout(timer);
            throw (e && e.name === 'AbortError') ? new Error('请求超时，请稍后重试') : e;
        });
    }

    // ---------- 步骤切换 ----------
    function goto(step) {
        step = Math.max(1, Math.min(4, Number(step) || 1));
        S.step = step;
        var panels = document.querySelectorAll('.panel');
        for (var i = 0; i < panels.length; i++) {
            panels[i].classList.toggle('active', panels[i].id === 'panel' + step);
        }
        var steps = document.querySelectorAll('.step');
        for (var j = 0; j < steps.length; j++) {
            var n = Number(steps[j].getAttribute('data-step'));
            steps[j].classList.toggle('active', n === step);
            steps[j].classList.toggle('done', n < step);
        }
        window.scrollTo({ top: 0, behavior: 'smooth' });

        if (step === 1 && !S.envLoaded) runEnvCheck();
        if (step === 2 && !S.assetLoaded) runScan(false, false);
        if (step === 3 && !S.cfgLoaded) loadConfig();
        if (step === 4) renderDone();
    }

    // ---------- 第 1 步：环境自检 ----------
    function runEnvCheck() {
        var box = $('envBox');
        box.innerHTML = '<div class="loading"><span class="spin"></span>正在检测依赖与目录…</div>';
        $('btnEnvReload').disabled = true;
        return api('/env-check', {}, 120000).then(function (r) {
            S.envLoaded = true;
            renderEnv(r.check || {});
        }).catch(function (e) {
            box.innerHTML = '<div class="tip err"><span class="ic">×</span><span>自检失败：' + esc(e.message) + '</span></div>';
        }).then(function () {
            $('btnEnvReload').disabled = false;
        });
    }

    function renderEnv(c) {
        var deps = c.deps || [], bad = 0, h = '';
        deps.forEach(function (d) { if (!d.ok) bad++; });

        if (bad === 0) {
            h += '<div class="tip ok"><span class="ic">✓</span><span>解释器与依赖都就绪，可以直接往下走。</span></div>';
        } else {
            h += '<div class="tip err"><span class="ic">!</span><span>有 ' + bad + ' 项没通过自检，' +
                '请按下面每一项的提示逐个处理（在项目目录里用本项目的 Python 执行），处理完点「重新检测」。</span></div>';
        }

        h += '<div class="sec-t">运行依赖</div><div class="rows">';
        deps.forEach(function (d) {
            h += '<div class="row">' +
                '<span class="pill ' + (d.ok ? 'ok' : 'err') + '">' + (d.ok ? '正常' : (d.badge || '缺失')) + '</span>' +
                '<div class="r-main">' +
                '<div class="r-name">' + esc(d.label) + ' <span class="k">' + esc(d.module) + '</span></div>' +
                (d.ok ? '' : '<div class="r-sub">' + esc(d.detail || '') +
                    (d.tip ? '　→ 试试：<b>' + esc(d.tip) + '</b>' : '') + '</div>') +
                '</div></div>';
        });
        h += '</div>';

        var dirs = c.dirs || [];
        if (dirs.length) {
            h += '<div class="sec-t">必要目录</div><div class="rows">';
            dirs.forEach(function (d) {
                h += '<div class="row">' +
                    '<span class="pill ' + (d.exists ? 'ok' : 'warn') + '">' + (d.exists ? '存在' : '待创建') + '</span>' +
                    '<div class="r-main"><div class="r-name">' + esc(d.label) + '</div>' +
                    '<div class="r-sub mono">' + esc(d.path || '—') + '</div></div></div>';
            });
            h += '</div>';
        }

        h += '<div class="sec-t">运行环境</div><div class="rows">';
        h += envRow('Python 版本', 'v' + (c.python || '—') +
            (c.python_ok === false ? '　需 ' + (c.python_require || '3.10 – 3.13（64 位）') : ''), true);
        h += envRow('Meme 引擎版本', c.engine_version || '未识别', false);
        h += envRow('可识别表情数', (c.meme_count >= 0 ? c.meme_count + ' 个' : '读取失败'), false);
        h += envRow('素材目录', c.asset_dir || '—', false);
        h += envRow('配置文件', (c.env_file || '—') + (c.env_file_exists ? '' : '（尚未生成，保存配置后可创建）'), false);
        h += envRow('管理密码', c.admin_password_set ? '已设置' : '未设置（首次运行）', false);
        h += '</div>';

        $('envBox').innerHTML = h;
        $('btnToAssets').textContent = bad === 0 ? '下一步：检查素材' : '仍要继续：检查素材';
    }

    function envRow(name, value, mono) {
        return '<div class="row"><div class="r-main">' +
            '<div class="r-name">' + esc(name) + '</div>' +
            '<div class="r-sub' + (mono ? ' mono' : '') + '">' + esc(value) + '</div>' +
            '</div></div>';
    }

    // ---------- 第 2 步：Meme 素材 ----------
    function runScan(deep, refresh) {
        var box = $('assetBox');
        box.innerHTML = '<div class="loading"><span class="spin"></span>' +
            (deep ? '正在逐个校验 md5（较慢，请稍等）…' : refresh ? '正在联网刷新资源清单…' : '正在核对本地素材…') + '</div>';
        lockScan(true);
        return api('/check?deep=' + (deep ? 1 : 0) + '&refresh=' + (refresh ? 1 : 0), {}, 180000)
            .then(function (r) {
                S.assetLoaded = true;
                renderAssets(r);
                if (S.state) S.state.assets = r;
            })
            .catch(function (e) {
                box.innerHTML = '<div class="tip err"><span class="ic">×</span><span>体检失败：' + esc(e.message) + '</span></div>';
            })
            .then(function () { lockScan(false); });
    }

    function renderAssets(a) {
        a = a || {};
        var total = Number(a.total) || 0;
        var present = Number(a.present) || 0;
        var missing = Number(a.missing) || 0;
        var broken = Number(a.broken) || 0;
        var localFiles = Number(a.local_files) || 0;
        var complete = !!a.complete;
        var h = '';

        if (complete) {
            h += '<div class="tip ok"><span class="ic">✓</span><span>素材完整：清单里的 ' + total +
                ' 个文件本地都有，可以直接使用。</span></div>';
        } else if (a.manifest_error && !total) {
            h += '<div class="tip warn"><span class="ic">!</span><span>拿不到资源清单（' + esc(a.manifest_error) +
                '）。如果你不需要补全下载，可以点「素材先跳过」继续。</span></div>';
        } else {
            h += '<div class="tip warn"><span class="ic">!</span><span>素材不完整：缺 ' + missing +
                ' 个、损坏 ' + broken + ' 个。点右下角「补全下载」自动补齐（只补缺的，可重复执行）。</span></div>';
        }

        h += '<div class="sec-t">素材统计</div><div class="stats">' +
            stat('清单总数', total, '') +
            stat('本地已有', present, present >= total && total > 0 ? 'ok' : '') +
            stat('缺失', missing, missing > 0 ? 'warn' : 'ok') +
            stat('损坏', broken, broken > 0 ? 'err' : 'ok') +
            stat('本地文件', localFiles, '') +
            stat('占用体积', fmtBytes(a.bytes), '') +
            '</div>';

        h += '<div class="sec-t">素材信息</div><div class="rows">' +
            infoRow('素材目录', a.dir || '—', true) +
            infoRow('引擎目录', a.engine_dir || '—', true) +
            infoRow('引擎版本', a.engine_version || '未识别', false) +
            infoRow('清单来源', manifestLabel(a.manifest_source), false) +
            infoRow('体检时间', fmtTime(a.checked_at) + (a.deep ? '（已做 md5 深度校验）' : '（仅检查文件是否存在）'), false) +
            '</div>';

        var sample = a.sample || [];
        if (sample.length) {
            h += '<div class="sec-t">待补全样例（最多 20 个）</div><div class="chips">';
            sample.forEach(function (s) { h += '<span class="chip">' + esc(s) + '</span>'; });
            h += '</div>';
        }

        $('assetBox').innerHTML = h;
        $('btnToConfig').style.display = complete ? '' : 'none';
        if (complete) setProgVisible(false);
    }

    function stat(label, value, kind) {
        return '<div class="stat ' + (kind || '') + '"><span>' + esc(label) + '</span><b>' + esc(value) + '</b></div>';
    }

    function infoRow(name, value, mono) {
        return '<div class="row"><div class="r-main">' +
            '<div class="r-name">' + esc(name) + '</div>' +
            '<div class="r-sub' + (mono ? ' mono' : '') + '">' + esc(value) + '</div>' +
            '</div></div>';
    }

    function manifestLabel(src) {
        if (!src) return '未知（未取到清单）';
        if (src === 'cache') return '本地缓存';
        if (src === 'cache(stale)') return '本地缓存（过期，离线可用）';
        return '在线镜像：' + src;
    }

    function lockScan(busy) {
        ['btnScan', 'btnScanDeep', 'btnScanRefresh', 'btnDownload'].forEach(function (id) {
            var b = $(id);
            if (b) b.disabled = busy;
        });
    }

    function setProgVisible(on) {
        $('progWrap').style.display = on ? '' : 'none';
    }

    function renderJob(job) {
        job = job || {};
        var st = job.state || 'idle';
        var total = Number(job.total) || 0;
        var done = Number(job.done) || 0;
        var pct = total ? Math.min(100, Math.round(done * 100 / total)) : (st === 'done' ? 100 : 0);

        $('progPct').textContent = pct + '%';
        $('progInner').style.width = pct + '%';
        $('progBar').classList.toggle('idle', st === 'idle');

        var cancelling = !!job.cancelling;
        var label = { idle: '空闲', running: '正在下载…', done: '下载完成', error: '下载出错', cancelled: '已取消' }[st] || st;
        if (cancelling) label = '正在取消…';
        $('progText').textContent = label + '（' + done + ' / ' + total + '）';

        var note = [];
        var recv = Number(job.bytes_recv || job.bytes || 0);
        if (recv) note.push('已接收 ' + fmtBytes(recv));
        if (job.ok) note.push('成功 ' + job.ok + ' 个');
        if (job.failed) note.push('失败 ' + job.failed + ' 个');
        // 点了取消之后，卡在「等首字节」的请求要读到超时才退出，
        // 这段时间状态仍是 running，明确说明是在收尾，免得用户以为按钮没生效。
        if (cancelling) note.push('已停止派发新请求，正在等待在途请求收尾');
        else if (job.message) note.push(job.message);
        // done 长时间是 0 不代表卡死：单个素材冷回源可能要几十秒。
        // 用「是否已收到字节」区分「在收但没凑完一个文件」和「还在等第一个响应」。
        if (st === 'running' && !done && !cancelling) {
            note.push(recv ? '正在接收数据，首个素材落盘后才开始计数'
                           : '正在等待首个素材响应（CDN 冷回源可能较慢，请稍候）');
        }
        if (job.bases && job.bases.length) note.push('镜像：' + String(job.bases[0]).replace(/^https?:\/\//, '').replace(/\/$/, ''));
        if (job.dir) note.push('目录：' + job.dir);
        if (job.state === 'running' && job.started_at) note.push('开始于 ' + fmtTime(job.started_at));
        var fails = job.failed_sample || [];
        if (fails.length) {
            note.push('失败样例：' + fails.slice(0, 5).join('、'));
        }
        $('progNote').innerHTML = note.map(function (s) { return esc(s); }).join('　·　');

        var running = st === 'running';
        $('btnDownload').style.display = running ? 'none' : '';
        $('btnCancelDl').style.display = running ? '' : 'none';
        $('btnCancelDl').disabled = cancelling;   // 收尾期间别让用户重复点
        $('btnDownload').disabled = running;
    }

    function startDownload() {
        if (S.busy) return;
        S.busy = true;
        setProgVisible(true);
        $('progText').textContent = '正在启动下载任务…';
        $('progPct').textContent = '0%';
        $('progInner').style.width = '0%';
        $('progNote').textContent = '';
        $('btnDownload').disabled = true;

        api('/assets/download', { method: 'POST', body: { workers: 16 } }, 60000).then(function (r) {
            if (!r.ok) throw new Error(r.error || '启动下载失败');
            renderJob(r.job || {});
            if (!r.total) {
                toast('没有需要补全的文件', 'ok');
                setProgVisible(false);
                return runScan(false, false);
            }
            toast('开始补全 ' + r.total + ' 个文件', 'ok');
            pollStart();
        }).catch(function (e) {
            toast(e.message, 'err');
            setProgVisible(false);
        }).then(function () {
            S.busy = false;
            $('btnDownload').disabled = false;
        });
    }

    function pollStart() {
        pollStop();
        S.pollTimer = setInterval(pollTick, 900);
        pollTick();
    }

    function pollStop() {
        if (S.pollTimer) { clearInterval(S.pollTimer); S.pollTimer = null; }
    }

    function pollTick() {
        api('/assets/progress', {}, 20000).then(function (r) {
            var job = r.job || {};
            renderJob(job);
            if (job.state !== 'running') {
                pollStop();
                if (r.assets) {
                    renderAssets(r.assets);
                    if (S.state) S.state.assets = r.assets;
                }
                if (job.state === 'done') {
                    toast(job.failed ? ('下载结束，成功 ' + (job.ok || 0) + ' 个、失败 ' + job.failed + ' 个')
                                     : ('下载完成，共 ' + (job.ok || 0) + ' 个'), job.failed ? '' : 'ok');
                } else if (job.state === 'cancelled') {
                    toast('已取消下载', '');
                } else if (job.state === 'error') {
                    toast('下载出错：' + (job.message || '未知原因'), 'err');
                }
            }
        }).catch(function () { /* 轮询失败不打断，下一轮再试 */ });
    }

    function cancelDownload() {
        api('/assets/cancel', { method: 'POST' }, 15000).then(function (r) {
            if (r.job) renderJob(r.job);
            toast('已请求取消', '');
        }).catch(function (e) { toast(e.message, 'err'); });
    }

    // ---------- 第 3 步：基础配置 ----------
    function loadConfig() {
        var box = $('cfgBox');
        box.innerHTML = '<div class="loading"><span class="spin"></span>正在读取配置项…</div>';
        return api('/config', {}, 30000).then(function (r) {
            S.cfgLoaded = true;
            S.cfgGroups = r.groups || [];
            renderConfig(S.cfgGroups);
        }).catch(function (e) {
            box.innerHTML = '<div class="tip err"><span class="ic">×</span><span>读取配置失败：' + esc(e.message) + '</span></div>';
        });
    }

    function renderConfig(groups) {
        var h = '';
        if (!groups.length) {
            h = '<div class="tip warn"><span class="ic">!</span><span>没有可编辑的配置项，可跳过这一步。</span></div>';
        }
        groups.forEach(function (g) {
            h += '<div class="sec-t">' + esc(g.name) + '</div><div class="fgrid">';
            (g.items || []).forEach(function (it) { h += fieldHtml(it); });
            h += '</div>';
        });
        $('cfgBox').innerHTML = h;
    }

    function fieldHtml(it) {
        var key = it.key;
        var type = it.type || 'text';
        var val = it.value == null ? '' : String(it.value);
        var id = 'f_' + key;
        var dis = it.locked ? ' disabled' : '';
        var ctrl;

        if (type === 'bool') {
            var on = (val === 'true' || val === 'True' || val === '1');
            ctrl = '<label class="sw"><input type="checkbox" id="' + id + '" data-key="' + esc(key) + '" data-type="bool"' +
                (on ? ' checked' : '') + dis + '><span class="sw-track"></span>' +
                '<span class="sw-txt" data-sw="' + id + '">' + (on ? '开' : '关') + '</span></label>';
        } else if (type === 'select') {
            var opts = (it.options || []).map(function (o) {
                var v = o[0], lb = (o.length > 1 && o[1] !== '') ? o[1] : o[0];
                return '<option value="' + esc(v) + '"' + (String(v) === val ? ' selected' : '') + '>' + esc(lb) + '</option>';
            }).join('');
            ctrl = '<select class="inp" id="' + id + '" data-key="' + esc(key) + '">' + opts + '</select>';
        } else if (type === 'secret') {
            ctrl = '<input type="password" class="inp" id="' + id + '" data-key="' + esc(key) + '" data-type="secret" value=""' +
                ' placeholder="' + (it.configured ? '已设置，留空表示不改动' : '未设置') + '" autocomplete="new-password"' + dis + '>';
        } else if (type === 'secret-clear' || (type === 'text' && it.sensitive)) {
            ctrl = '<input type="password" class="inp" id="' + id + '" data-key="' + esc(key) + '" data-type="secret" value=""' +
                ' placeholder="留空表示不改动" autocomplete="new-password"' + dis + '>';
        } else if (type === 'int' || type === 'float') {
            ctrl = '<input type="number" class="inp" id="' + id + '" data-key="' + esc(key) + '" value="' + esc(val) + '"' +
                ' step="' + (type === 'float' ? '0.1' : '1') + '"' +
                (it.min != null ? ' min="' + esc(it.min) + '"' : '') +
                (it.max != null ? ' max="' + esc(it.max) + '"' : '') + dis + '>';
        } else {
            ctrl = '<input type="text" class="inp" id="' + id + '" data-key="' + esc(key) + '" value="' + esc(val) + '"' +
                (it.maxlen ? ' maxlength="' + esc(it.maxlen) + '"' : '') + dis + '>';
        }

        var tags = '';
        if (it.hot) tags += '<span class="pill info">热生效</span>';
        if (it.locked) tags += '<span class="pill warn">被系统环境变量接管</span>';

        return '<div class="field">' +
            '<label>' + esc(it.label || key) + ' <span class="k">' + esc(key) + '</span>' + tags + '</label>' +
            ctrl +
            (it.desc ? '<div class="fnote">' + esc(it.desc) + '</div>' : '') +
            (it.note ? '<div class="fnote">' + esc(it.note) + '</div>' : '') +
            '</div>';
    }

    function collectConfig() {
        var out = {};
        var els = document.querySelectorAll('#cfgBox [data-key]');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (el.disabled) continue;
            var k = el.getAttribute('data-key');
            if (el.type === 'checkbox') {
                out[k] = el.checked ? 'true' : 'false';
            } else if (el.getAttribute('data-type') === 'secret') {
                if (el.value !== '') out[k] = el.value;   // 留空 = 不改动
            } else {
                out[k] = el.value;
            }
        }
        return out;
    }

    function saveConfig(silent) {
        var btn = $('btnCfgSave');
        btn.disabled = true;
        $('cfgSaved').textContent = '正在保存…';
        return api('/config', { method: 'POST', body: { updates: collectConfig() } }, 60000)
            .then(function (r) {
                if (!r.ok) throw new Error(r.error || '保存失败');
                S.cfgGroups = r.groups || S.cfgGroups;
                renderConfig(S.cfgGroups);
                $('cfgSaved').textContent = '已保存于 ' + new Date().toLocaleTimeString('zh-CN', { hour12: false });
                if (!silent) toast('配置已保存并生效', 'ok');
                if (S.state) {
                    S.state.env_file_exists = true;
                    if (r.state) S.state.completed = r.state.completed;
                }
                return r;
            })
            .catch(function (e) {
                $('cfgSaved').textContent = '';
                toast('保存失败：' + e.message, 'err');
                throw e;
            })
            .then(function (r) { btn.disabled = false; return r; },
                  function (e) { btn.disabled = false; throw e; });
    }

    // ---------- 第 4 步：完成 ----------
    function renderDone() {
        var st = S.state || {};
        var a = st.assets || {};
        var sums = [];

        sums.push(['管理密码', st.first_run ? (st.logged_in ? '已在本次引导设置' : '未设置（将用启动时控制台打印的随机密码）') : '已设置']);
        sums.push(['Meme 素材', a.complete
            ? ('完整（' + (Number(a.present) || 0) + ' 个）')
            : ('缺失 ' + (Number(a.missing) || 0) + ' / 损坏 ' + (Number(a.broken) || 0) + '（可稍后补全）')]);
        sums.push(['素材目录', a.dir || '—']);
        sums.push(['配置文件', st.env_file || '—']);
        sums.push(['进入方式', '浏览器打开 http://' + location.host + '/']);

        var h = '';
        sums.forEach(function (s) {
            h += '<div class="sum-i"><span>' + esc(s[0]) + '</span><b>' + esc(s[1]) + '</b></div>';
        });
        $('doneSum').innerHTML = h;

        $('pwdWrap').style.display = st.first_run ? '' : 'none';
        if (st.first_run) {
            $('doneSub').textContent = '建议先设一个管理密码，然后完成引导。';
        } else {
            $('doneSub').textContent = '确认下面的信息，然后完成引导。';
        }

        if (S.finished) {
            $('btnFinish').style.display = 'none';
            $('btnEnter').style.display = '';
            $('doneNote').textContent = '引导已完成。';
        } else {
            $('btnFinish').style.display = '';
            $('btnEnter').style.display = 'none';
            $('doneNote').textContent = '';
        }
    }

    function finish() {
        if (S.busy) return;
        var body = {};
        if (S.state && S.state.first_run) {
            var p1 = ($('pwd1').value || '').trim();
            var p2 = ($('pwd2').value || '').trim();
            if (p1 || p2) {
                if (p1.length < 4) return toast('管理密码至少 4 位', 'err');
                if (p1 !== p2) return toast('两次输入的密码不一致', 'err');
                body.admin_password = p1;
            }
        }

        S.busy = true;
        $('btnFinish').disabled = true;
        $('doneNote').textContent = '正在完成…';

        api('/complete', { method: 'POST', body: body }, 120000).then(function (r) {
            if (!r.ok) throw new Error(r.error || '完成失败');
            S.finished = true;
            if (S.state) {
                S.state.completed = true;
                S.state.reason = '';
                if (r.state) { S.state.assets_ok = r.state.assets_ok; }
                if (r.assets) S.state.assets = r.assets;
                if (r.admin_password_set) S.state.logged_in = true;
            }
            if (r.assets) renderAssets(r.assets);
            renderDone();
            $('doneNote').textContent = '引导已完成。';
            toast(r.admin_password_set ? '引导完成，管理密码已设置' : '引导完成', 'ok');
        }).catch(function (e) {
            $('doneNote').textContent = '';
            toast('完成失败：' + e.message, 'err');
        }).then(function () {
            S.busy = false;
            $('btnFinish').disabled = false;
        });
    }

    function skipAssets() {
        api('/skip', { method: 'POST', body: { what: 'assets' } }, 20000).then(function (r) {
            if (S.state) S.state.assets_ack = true;
            toast('已跳过素材检查（下次启动若仍缺失会再提醒）', '');
            goto(3);
        }).catch(function (e) { toast(e.message, 'err'); });
    }

    // ---------- 绑定 ----------
    function bind() {
        // 步骤条可点击跳转
        var steps = document.querySelectorAll('.step');
        for (var i = 0; i < steps.length; i++) {
            (function (el) {
                el.addEventListener('click', function () {
                    goto(Number(el.getAttribute('data-step')));
                });
            })(steps[i]);
        }

        $('btnEnvReload').addEventListener('click', function () { runEnvCheck(); });
        $('btnToAssets').addEventListener('click', function () { goto(2); });

        $('btnScan').addEventListener('click', function () { runScan(false, false); });
        $('btnScanDeep').addEventListener('click', function () { runScan(true, false); });
        $('btnScanRefresh').addEventListener('click', function () { runScan(false, true); });
        $('btnDownload').addEventListener('click', startDownload);
        $('btnCancelDl').addEventListener('click', cancelDownload);
        $('btnSkipAssets').addEventListener('click', skipAssets);
        $('btnToConfig').addEventListener('click', function () { goto(3); });

        $('btnCfgBack').addEventListener('click', function () { goto(2); });
        $('btnCfgSave').addEventListener('click', function () { saveConfig(false); });
        $('btnCfgNext').addEventListener('click', function () {
            saveConfig(true).then(function () { goto(4); },
                                  function () { /* 保存失败就不前进 */ });
        });

        $('btnDoneBack').addEventListener('click', function () { goto(3); });
        $('btnFinish').addEventListener('click', finish);
        $('btnEnter').addEventListener('click', function () { location.href = '/'; });

        // 开关文案同步
        document.addEventListener('change', function (e) {
            var el = e.target;
            if (el && el.getAttribute && el.getAttribute('data-type') === 'bool') {
                var t = document.querySelector('[data-sw="' + el.id + '"]');
                if (t) t.textContent = el.checked ? '开' : '关';
            }
        });
    }

    // ---------- 启动 ----------
    function init() {
        bind();
        var qs = new URLSearchParams(location.search);
        var want = parseInt(qs.get('step'), 10);

        api('/state', {}, 25000).then(function (st) {
            S.state = st || {};
            if (S.state.first_run) {
                $('hdSub').textContent = '首次运行：跟着三步走，机器人就能跑起来。';
            } else if (S.state.reason === 'assets') {
                $('hdSub').textContent = '检测到 Meme 素材不完整，先把它补全。';
            } else {
                $('hdSub').textContent = '引导已完成，可随时回来查看自检结果。';
            }
            $('hdWho').textContent = S.state.logged_in ? '已登录' : '';

            // 上次没跑完的下载任务：继续显示进度
            var job = S.state.job || {};
            if (job.state === 'running') {
                setProgVisible(true);
                renderJob(job);
                pollStart();
            }

            var step = want;
            if (!(step >= 1 && step <= 4)) {
                step = (S.state.reason === 'assets') ? 2 : 1;
            }
            goto(step);
        }).catch(function (e) {
            $('hdSub').textContent = '读取引导状态失败：' + e.message;
            goto(1);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

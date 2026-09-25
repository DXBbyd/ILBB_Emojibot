/* bg.js — 全局背景图片
 * body 通过 CSS 变量注入背景：--bg-image 背景图、--bg-blur 背景模糊、--bg-mask 蒙版暗度。
 * 登录页仅用 init() 加载背景；工作台的「设置」视图用 initSettings() 绑定交互（刷新/上传/模糊/蒙版）。
 */
(function () {
    'use strict';

    function qs(id) { return document.getElementById(id); }

    var _fadeTimer = null;

    // 将后端背景配置应用到壁纸层 #bgWall（全局生效，登录页 + 工作台共用）
    // 切换图片时先淡出旧图、再淡入新图，实现交叉过渡。
    // 同时将 blur 值应用到 .workspace 的 backdrop-filter。
    function applyGlobals(d) {
        if (!d) return;
        var wall = document.getElementById('bgWall');
        var url = d.url ? "url('" + d.url + "')" : 'none';
        if (_fadeTimer) clearTimeout(_fadeTimer);
        document.body.classList.add('bg-loading');
        _fadeTimer = setTimeout(function () {
            if (wall) wall.style.backgroundImage = url;
            else document.body.style.setProperty('--bg-image', url);
            document.body.classList.remove('bg-loading');
            _fadeTimer = null;
        }, 250);

        // 应用磨砂模糊度到工作台
        var blur = parseFloat(d.blur) || 0;
        applyBlur(blur);
    }

    // 将模糊度应用到 .workspace 元素
    function applyBlur(px) {
        var ws = document.querySelector('.workspace');
        if (!ws) return;
        var v = Math.max(0, Math.min(40, parseFloat(px) || 0));
        if (v > 0) {
            ws.style.backdropFilter = 'blur(' + v + 'px) saturate(160%)';
            ws.style.webkitBackdropFilter = 'blur(' + v + 'px) saturate(160%)';
        } else {
            // 0 = 纯透明，不加模糊
            ws.style.backdropFilter = 'none';
            ws.style.webkitBackdropFilter = 'none';
        }
        // 同步滑块 UI
        var slider = qs('blurSlider'), valLabel = qs('blurValue');
        if (slider) slider.value = v;
        if (valLabel) valLabel.textContent = v;
        // 同步预设按钮高亮
        var presets = document.querySelectorAll('.blur-preset');
        presets.forEach(function (b) {
            b.classList.toggle('active', parseFloat(b.getAttribute('data-val')) === v);
        });
    }

    // 更新设置卡：当前链接 + 预览
    function setSettingsUI(d) {
        var link = qs('bgCurrentLink');
        if (link) link.value = d.url || '';
        var prev = qs('bgPreview');
        if (prev) {
            prev.style.backgroundImage = d.url ? "url('" + d.url + "')" : 'none';
            prev.style.backgroundSize = 'cover';
            prev.style.backgroundPosition = 'center';
        }
    }

    function bindPasswordChange() {
        var btn = qs('chgPwdBtn');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var cur = qs('pwdCurrent').value, n1 = qs('pwdNew').value, n2 = qs('pwdNew2').value;
            var err = qs('chgPwdTip'), nice = function (t, ok) { err.style.opacity = '1'; err.textContent = t; err.style.color = ok ? '#2e7d32' : '#d32f2f'; err.style.fontWeight = '600'; };
            if (!cur) { nice('请输入当前密码', false); return; }
            if (n1.length < 4) { nice('新密码至少 4 位', false); return; }
            if (n1 !== n2) { nice('两次输入的新密码不一致', false); return; }
            btn.disabled = true;
            fetch('/admin/api/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current: cur, new: n1 })
            }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
              .then(function (res) {
                  btn.disabled = false;
                  if (res.ok) {
                      nice('密码已修改，请牢记新密码 ✓', true);
                      qs('pwdCurrent').value = ''; qs('pwdNew').value = ''; qs('pwdNew2').value = '';
                  } else {
                      nice(res.d.error || '修改失败', false);
                  }
              }).catch(function () { btn.disabled = false; nice('网络错误', false); });
        });
    }

    // ===== 服务配置（.env）：表单编辑 + 保存后热重载 =====
    var _envCfgLoaded = false;
    var _envOrigin = {};   // 渲染时的值，用来判断「有没有改动」
    var _envMeta = {};     // key -> 元数据（type / locked / hot ...）

    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function envBadges(it) {
        var h = '';
        h += it.hot ? '<span class="env-tag hot" title="保存后立即生效">热生效</span>'
                    : '<span class="env-tag cold" title="需重启主服务后才生效">需重启</span>';
        if (it.locked) h += '<span class="env-tag lock" title="该项由系统环境变量提供，写 .env 不会影响当前进程">系统环境变量</span>';
        if (it.sensitive) h += '<span class="env-tag sec">敏感</span>';
        return h;
    }

    function envControl(it) {
        var v = it.value == null ? '' : String(it.value);
        var a = 'data-env-key="' + escHtml(it.key) + '"';
        if (it.locked) a += ' disabled';
        if (it.type === 'bool') {
            var on = (v === 'true');
            return '<select class="env-inp" ' + a + '>' +
                '<option value="true"' + (on ? ' selected' : '') + '>开启</option>' +
                '<option value="false"' + (!on ? ' selected' : '') + '>关闭</option>' +
                '</select>';
        }
        if (it.type === 'select') {
            return '<select class="env-inp" ' + a + '>' + (it.options || []).map(function (o) {
                return '<option value="' + escHtml(o[0]) + '"' +
                    (String(o[0]).toLowerCase() === v.toLowerCase() ? ' selected' : '') + '>' +
                    escHtml(o[1] || o[0]) + '</option>';
            }).join('') + '</select>';
        }
        if (it.type === 'secret') {
            return '<input type="password" class="env-inp ws-mono" ' + a +
                ' value="" placeholder="留空 = 不修改" autocomplete="new-password">';
        }
        if (it.type === 'int' || it.type === 'float') {
            var step = it.type === 'float' ? '0.01' : '1', extra = '';
            if (it.min != null) extra += ' min="' + it.min + '"';
            if (it.max != null) extra += ' max="' + it.max + '"';
            return '<input type="number" class="env-inp ws-mono" ' + a + ' value="' + escHtml(v) +
                '" step="' + step + '"' + extra + '>';
        }
        return '<input type="text" class="env-inp ws-mono" ' + a + ' value="' + escHtml(v) + '"' +
            (it.maxlen ? ' maxlength="' + it.maxlen + '"' : '') + '>';
    }

    function renderEnvConfig(d) {
        var pathEl = qs('envCfgPath'), stateEl = qs('envCfgState'), gridEl = qs('envCfgGrid');
        if (pathEl) pathEl.textContent = d.env_file || '—';
        if (stateEl) {
            if (d.env_file_exists) {
                stateEl.className = 'ws-notice info';
                stateEl.innerHTML = '已读取 <code class="ws-code">.env</code>。' +
                    '敏感项（如 <code class="ws-code">SECRET_KEY</code>）不会回显原值，留空即保持不变。';
            } else {
                stateEl.className = 'ws-notice warn';
                stateEl.innerHTML = '未找到 <code class="ws-code">.env</code>，当前全部使用内置默认值。' +
                    '保存任意一项后会自动创建该文件。';
            }
        }
        if (!gridEl) return;
        _envOrigin = {}; _envMeta = {};
        var h = '';
        (d.groups || []).forEach(function (g) {
            h += '<div class="status-card"><h3>' + escHtml(g.name) + '</h3>';
            (g.items || []).forEach(function (it) {
                _envOrigin[it.key] = it.value == null ? '' : String(it.value);
                _envMeta[it.key] = it;
                h += '<div class="env-row">' +
                     '<div class="env-head">' +
                       '<span class="env-key ws-mono">' + escHtml(it.key) + '</span>' +
                       '<span class="env-label">' + escHtml(it.label || '') + '</span>' +
                     '</div>' +
                     '<div class="env-ctrl">' + envControl(it) + '</div>' +
                     '<div class="env-tags">' + envBadges(it) + '</div>' +
                     '<div class="env-desc">' + escHtml(it.desc || '') +
                       (it.note ? ' <span class="env-note">' + escHtml(it.note) + '</span>' : '') +
                     '</div>' +
                     '</div>';
            });
            h += '</div>';
        });
        gridEl.innerHTML = h;
        updateEnvDirty();
    }

    // 收集改动（敏感项留空 = 不修改）
    function collectEnvChanges() {
        var out = {}, n = 0;
        Array.prototype.forEach.call(document.querySelectorAll('[data-env-key]'), function (el) {
            var key = el.getAttribute('data-env-key'), meta = _envMeta[key] || {};
            if (el.disabled || meta.locked) return;
            var val = el.value == null ? '' : String(el.value);
            if (meta.type === 'secret') {
                if (val !== '') { out[key] = val; n++; }
                return;
            }
            var orig = _envOrigin[key] == null ? '' : _envOrigin[key];
            if (val !== orig) { out[key] = val; n++; }
        });
        return out;
    }

    function updateEnvDirty() {
        var el = qs('envCfgDirty');
        if (!el) return;
        var n = Object.keys(collectEnvChanges()).length;
        el.textContent = n ? ('有 ' + n + ' 项待保存') : '';
        el.classList.toggle('on', n > 0);
    }

    function showEnvTip(html, kind) {
        var el = qs('envCfgSaveTip');
        if (!el) return;
        el.className = 'ws-notice ' + (kind || 'info');
        el.innerHTML = html;
        el.style.display = 'block';
    }

    function saveEnvConfig() {
        var btn = qs('envCfgSaveBtn');
        var changes = collectEnvChanges(), keys = Object.keys(changes);
        if (!keys.length) {
            showEnvTip('没有检测到改动。若要清空敏感项（如 <code class="ws-code">SECRET_KEY</code>），' +
                '请直接在 <code class="ws-code">.env</code> 里删除该行或留空。', 'warn');
            return;
        }
        if (btn) btn.disabled = true;
        fetch('/api/env/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ updates: changes })
        }).then(function (r) {
            return r.json().then(function (d) { return { ok: r.ok, d: d }; },
                                     function () { return { ok: false, d: {} }; });
        }).then(function (res) {
            if (btn) btn.disabled = false;
            var d = res.d || {};
            if (!res.ok || !d.ok) {
                showEnvTip('保存失败：' + escHtml(d.error || '未知错误'), 'warn');
                return;
            }
            var p = ['已保存 <b>' + (d.updated || []).length + '</b> 项'];
            if ((d.hot || []).length) p.push('<b>已热生效</b>：<span class="ws-mono">' + escHtml(d.hot.join(', ')) + '</span>');
            if ((d.restart || []).length) p.push('<b>需重启主服务</b>：<span class="ws-mono">' + escHtml(d.restart.join(', ')) + '</span>');
            if ((d.locked || []).length) p.push('<b>被系统环境变量接管</b>（已写入 .env，当前进程不变）：<span class="ws-mono">' + escHtml(d.locked.join(', ')) + '</span>');
            if ((d.warnings || []).length) p.push('部分刷新失败：' + escHtml(d.warnings.join('；')));
            showEnvTip(p.join('<br>'), 'info');
            _envCfgLoaded = false;
            loadEnvConfig(true);
        }).catch(function () {
            if (btn) btn.disabled = false;
            showEnvTip('网络错误，保存失败', 'warn');
        });
    }

    function loadEnvConfig(force) {
        if (_envCfgLoaded && !force) return;
        var gridEl = qs('envCfgGrid');
        if (!gridEl) return;
        fetch('/api/env/config')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || d.ok === false) throw new Error('bad payload');
                _envCfgLoaded = true;
                renderEnvConfig(d);
            })
            .catch(function () {
                var stateEl = qs('envCfgState');
                if (stateEl) { stateEl.className = 'ws-notice warn'; stateEl.textContent = '配置读取失败'; }
            });
    }

    function bindEnvConfig() {
        var save = qs('envCfgSaveBtn'), reset = qs('envCfgResetBtn'), grid = qs('envCfgGrid');
        if (grid) {
            grid.addEventListener('change', updateEnvDirty);
            grid.addEventListener('input', updateEnvDirty);
        }
        if (save) save.addEventListener('click', saveEnvConfig);
        if (reset) reset.addEventListener('click', function () {
            var tip = qs('envCfgSaveTip');
            if (tip) tip.style.display = 'none';
            loadEnvConfig(true);
        });
    }

    window.BG = {
        applyGlobals: applyGlobals,
        loadEnvConfig: loadEnvConfig,
        init: function () {
            fetch('/api/background')
                .then(function (r) { return r.json(); })
                .then(applyGlobals)
                .catch(function () {});
        },
        initSettings: function () {
            // 每次进入「设置」都刷新一次配置展示（.env 可能刚被改过）
            loadEnvConfig(true);
            if (window._bgBound) return;
            window._bgBound = true;

            bindPasswordChange();
            bindEnvConfig();

            var refresh = qs('bgRefreshBtn'),
                upload = qs('bgUploadBtn'), file = qs('bgFile');
            var done = function (d) { if (d && d.error) { alert(d.error); return; } applyGlobals(d); setSettingsUI(d); };
            if (refresh) refresh.addEventListener('click', function () {
                fetch('/api/background/refresh', { method: 'POST' })
                    .then(function (r) { return r.json(); }).then(done).catch(function () { alert('刷新失败'); });
            });
            if (upload && file) upload.addEventListener('click', function () {
                var f = file.files && file.files[0];
                if (!f) { alert('请先选择图片'); return; }
                var fd = new FormData(); fd.append('file', f);
                fetch('/api/background/upload', { method: 'POST', body: fd })
                    .then(function (r) { return r.json(); }).then(done).catch(function () { alert('上传失败'); });
            });

            // ===== 磨砂模糊度滑块 =====
            var blurSlider = qs('blurSlider'), blurValue = qs('blurValue'),
                blurTip = qs('blurSavedTip');
            var blurSaveTimer = null;
            function showBlurSaved() {
                if (!blurTip) return;
                blurTip.classList.add('on');
                if (blurSaveTimer) clearTimeout(blurSaveTimer);
                blurSaveTimer = setTimeout(function () { blurTip.classList.remove('on'); blurSaveTimer = null; }, 1500);
            }
            if (blurSlider) {
                blurSlider.addEventListener('input', function () {
                    var v = parseInt(blurSlider.value, 10);
                    blurValue.textContent = v;
                    applyBlur(v);
                    // 防抖保存到后端
                    if (blurSaveTimer) clearTimeout(blurSaveTimer);
                    blurSaveTimer = setTimeout(function () {
                        fetch('/api/background/set', {
                            method: 'POST',
                            keepalive: true,
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ blur: v })
                        }).then(function () { showBlurSaved(); }).catch(function () {});
                        blurSaveTimer = null;
                    }, 500);
                });
            }
            // 预设按钮
            document.querySelectorAll('.blur-preset').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var v = parseInt(btn.getAttribute('data-val'), 10);
                    applyBlur(v);
                    showBlurSaved();
                    fetch('/api/background/set', {
                        method: 'POST',
                        keepalive: true,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ blur: v })
                    }).catch(function () {});
                });
            });

            fetch('/api/background').then(function (r) { return r.json(); })
                .then(function (d) { applyGlobals(d); setSettingsUI(d); })
                .catch(function () {});
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { window.BG.init(); });
    } else {
        window.BG.init();
    }
})();
/* ============================================================================
   ILBB · 快捷合成
   名言图 / 配对卡 / Meme（全参数）快速合成，生成后可直接发送到 QQ 好友 / 群。
   依赖后端 /api/quote/generate · /api/generate_image · /api/meme/* ·
   /api/webqq/bootstrap · /api/webqq/send。
   ========================================================================== */
(function () {
    'use strict';

    // 快捷合成现在是 WebQQ 里弹出的弹窗，不再是独立视图
    var root = document.getElementById('fcModal');
    if (!root) { return; }

    var el = {
        close: document.getElementById('fcClose'),
        mask: document.getElementById('fcMask'),
        tabs: document.getElementById('fcTabs'),
        target: document.getElementById('fcTarget'),
        targetPick: document.getElementById('fcTargetPick'),
        targetBtn: document.getElementById('fcTargetBtn'),
        targetAv: document.getElementById('fcTargetAv'),
        targetText: document.getElementById('fcTargetText'),
        targetPop: document.getElementById('fcTargetPop'),
        targetList: document.getElementById('fcTargetList'),
        targetSearch: document.getElementById('fcTargetSearch'),
        targetManual: document.getElementById('fcTargetManual'),
        targetManualGo: document.getElementById('fcTargetManualGo'),
        targetRefresh: document.getElementById('fcTargetRefresh'),
        online: document.getElementById('fcOnline'),
        panes: {
            quote: document.getElementById('fcPaneQuote'),
            pair: document.getElementById('fcPanePair'),
            meme: document.getElementById('fcPaneMeme')
        },
        quoteText: document.getElementById('fcQuoteText'),
        quoteName: document.getElementById('fcQuoteName'),
        quoteQQ: document.getElementById('fcQuoteQQ'),
        quoteImages: document.getElementById('fcQuoteImages'),
        quoteThumbs: document.getElementById('fcQuoteThumbs'),
        pairQQ: document.getElementById('fcPairQQ'),
        pairName: document.getElementById('fcPairName'),
        pairText: document.getElementById('fcPairText'),
        pairBtn: document.getElementById('fcPairBtn'),
        pairTpl: document.getElementById('fcPairTpl'),
        pairTplSel: document.getElementById('fcPairTplSel'),
        pairFont: document.getElementById('fcPairFont'),
        pairFontSel: document.getElementById('fcPairFontSel'),
        memeSearch: document.getElementById('fcMemeSearch'),
        memeGrid: document.getElementById('fcMemeGrid'),
        memeForm: document.getElementById('fcMemeForm'),
        memeName: document.getElementById('fcMemeName'),
        memeKey: document.getElementById('fcMemeKey'),
        memeReset: document.getElementById('fcMemeReset'),
        memeNeed: document.getElementById('fcMemeNeed'),
        memeFiles: document.getElementById('fcMemeFiles'),
        memeThumbs: document.getElementById('fcMemeThumbs'),
        memeTexts: document.getElementById('fcMemeTexts'),
        memeOpts: document.getElementById('fcMemeOpts'),
        memeStyles: document.getElementById('fcMemeStyles'),
        memeQQ: document.getElementById('fcMemeQQ'),
        memeFill: document.getElementById('fcMemeFill'),
        preview: document.getElementById('fcPreview'),
        empty: document.getElementById('fcEmpty'),
        generate: document.getElementById('fcGenerate'),
        send: document.getElementById('fcSend'),
        download: document.getElementById('fcDownload'),
        status: document.getElementById('fcStatus')
    };

    var st = {
        tab: 'quote',
        targets: [],
        targetsLoaded: false,
        metaLoaded: false,
        memesLoaded: false,
        memes: [],
        meme: null,
        quoteImages: [],
        output: null,
        objUrl: '',
        busy: false
    };

    // ---------------------------------------------------------------- 工具
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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

    function api(url, opt) {
        var o = Object.assign({ credentials: 'same-origin' }, opt || {});
        if (o.body && !o.headers) { o.headers = { 'Content-Type': 'application/json' }; }
        return fetch(url, o).then(function (r) {
            return r.text().then(function (txt) {
                var j = {};
                try { j = txt ? JSON.parse(txt) : {}; } catch (e) { j = {}; }
                if (!r.ok || j.ok === false) {
                    throw new Error(j.error || ('HTTP ' + r.status));
                }
                return j;
            });
        });
    }

    function blobToDataUrl(blob) {
        return new Promise(function (resolve, reject) {
            var fr = new FileReader();
            fr.onload = function () { resolve(String(fr.result || '')); };
            fr.onerror = function () { reject(new Error('图片读取失败')); };
            fr.readAsDataURL(blob);
        });
    }

    function setStatus(text) {
        if (el.status) { el.status.textContent = text || ''; }
    }

    // ---------------------------------------------------------------- ILBB 下拉
    // 站内所有下拉都必须是主页那套 ILBB 自定义下拉（.ilbb-select + 浮层菜单），
    // 不用浏览器原生 <select>。真实取值仍写在隐藏 input 里，
    // 交互（开合 / 勾选 / 键盘 / 点空白收起）由 ws.js 的 window.ILBBSelect 统一接管。
    function selOptHtml(value, label, code) {
        return '<li class="ilbb-select-opt" role="option" data-value="' + esc(value) +
            '" data-search="' + esc(String(label || '') + ' ' + String(code == null ? value : code)) +
            '" aria-selected="false">' +
            '<span class="ilbb-select-opt-main">' + esc(label) + '</span>' +
            '<span class="ilbb-select-opt-code">' + esc(code == null ? value : code) +
            '</span><span class="ilbb-select-tick">✓</span></li>';
    }

    function selMenu(sel) {
        return sel ? sel.querySelector('.ilbb-select-menu') : null;
    }

    // ws.js 已提供 window.ilbbInit（内部会等 ILBBSelect 就绪），这里只做转发
    function ilbbInit(host) {
        if (!host) { return; }
        if (window.ilbbInit) { window.ilbbInit(host); return; }
        var api = window.ILBBSelect;
        if (api && api.init) { api.init(host); }
    }

    // 程序里改了隐藏 input 的值之后，让按钮上的文字/勾选状态跟着变
    function ilbbSync(host) {
        var api = window.ILBBSelect;
        if (api && api.sync) { api.sync(host || document); }
    }

    // ---------------------------------------------------------------- 发送目标
    function targetName(value) {
        var hit = (st.targets || []).filter(function (t) { return t.value === value; })[0];
        return hit ? hit.name : '';
    }

    function currentTarget() {
        var v = el.target.value;
        if (!v) { return null; }
        var i = v.indexOf(':');
        return { type: v.slice(0, i), id: v.slice(i + 1), name: targetName(v) };
    }

    function renderTargetList(q) {
        if (!el.targetList) { return; }
        q = String(q || '').trim().toLowerCase();
        var rows = (st.targets || []).filter(function (t) {
            return !q || (t.name + ' ' + t.code).toLowerCase().indexOf(q) !== -1;
        });
        if (!rows.length) {
            el.targetList.innerHTML = '<div class="fc-target-empty">没有匹配的群 / 好友</div>';
            return;
        }
        el.targetList.innerHTML = rows.map(function (t) {
            var on = t.value === el.target.value;
            return '<div class="fc-target-row' + (on ? ' active' : '') +
                '" data-value="' + esc(t.value) + '"' +
                ' data-search="' + esc(t.name + ' ' + t.code) + '">' +
                (t.avatar ? '<img src="' + esc(t.avatar) + '" alt="" loading="lazy">' :
                    '<span class="fc-target-noav">' + (t.value ? '?' : '✕') + '</span>') +
                '<div class="fc-target-row-main"><b>' + esc(t.name) + '</b>' +
                '<span>' + esc(t.sub || '') + '</span></div>' +
                (on ? '<span class="fc-target-tick">✓</span>' : '') +
            '</div>';
        }).join('');
    }

    function filterTargets(q) {
        var list = el.targetList;
        if (!list) { return; }
        q = String(q || '').trim().toLowerCase();
        Array.prototype.forEach.call(
            list.querySelectorAll('.fc-target-row'), function (row) {
                var txt = (row.getAttribute('data-search') || row.textContent || '').toLowerCase();
                row.style.display = (!q || txt.indexOf(q) !== -1) ? '' : 'none';
            });
    }

    function syncTarget() {
        var v = el.target.value;
        var hit = (st.targets || []).filter(function (t) { return t.value === v; })[0];
        if (el.targetText) {
            el.targetText.textContent = hit ? hit.name : '仅生成，不发送';
        }
        if (el.targetAv) {
            if (hit && hit.avatar) {
                el.targetAv.src = hit.avatar;
                el.targetAv.classList.remove('hidden');
            } else {
                el.targetAv.removeAttribute('src');
                el.targetAv.classList.add('hidden');
            }
        }
        renderTargetList(el.targetSearch ? el.targetSearch.value : '');
    }

    function pickManualTarget() {
        var v = String(el.targetManual ? el.targetManual.value : '').trim();
        if (!/^[1-9]\d{4,11}$/.test(v)) {
            toast('群号格式不对，填 5~12 位数字', true);
            return;
        }
        var val = 'group:' + v;
        if (!(st.targets || []).some(function (t) { return t.value === val; })) {
            st.targets.push({ value: val, name: '群 ' + v, code: v,
                              sub: '群聊（手动输入）', avatar: '' });
        }
        if (el.targetManual) { el.targetManual.value = ''; }
        pickTarget(val);
    }

    function pickTarget(value) {
        el.target.value = value;
        var t = currentTarget();
        if (t && t.type === 'private' && el.memeQQ && !el.memeQQ.value) {
            el.memeQQ.value = t.id;
        }
        syncTarget();
        closeTargetPop();
    }

    function openTargetPop() {
        if (!el.targetPop) { return; }
        var box = root.querySelector('.wq-fc-dialog');
        if (box && el.targetBtn) {
            var rb = box.getBoundingClientRect();
            var r = el.targetBtn.getBoundingClientRect();
            var below = rb.bottom - r.bottom;
            var above = r.top - rb.top;
            el.targetPick.classList.toggle('drop-up', below < 380 && above > below);
        }
        el.targetPop.classList.remove('hidden');
        if (el.targetBtn) { el.targetBtn.setAttribute('aria-expanded', 'true'); }
        if (el.targetSearch) {
            el.targetSearch.value = '';
            filterTargets('');
            setTimeout(function () { el.targetSearch.focus(); }, 20);
        }
        renderTargetList('');
    }

    function closeTargetPop() {
        if (!el.targetPop) { return; }
        el.targetPop.classList.add('hidden');
        if (el.targetBtn) { el.targetBtn.setAttribute('aria-expanded', 'false'); }
    }

    function loadTargets(force) {
        if (st.targetsLoaded && !force) { return Promise.resolve(); }
        el.online.textContent = '读取会话…';
        el.online.className = 'fc-online';
        return api('/api/webqq/bootstrap' + (force ? '?force=1' : '')).then(function (j) {
            var groups = j.groups || [], friends = j.friends || [];
            if (!groups.length && !force) {
                // 群列表没回来时强制再拉一次，避免下拉里只有好友 / 仅生成
                st.targetsLoaded = false;
                return loadTargets(true);
            }
            st.targets = [{ value: '', name: '仅生成，不发送', code: '',
                           sub: '不发送到 QQ', avatar: '' }];
            groups.forEach(function (g) {
                st.targets.push({ value: 'group:' + g.id, name: g.name || g.id,
                    code: g.id, sub: '群聊',
                    avatar: g.avatar || ('/api/ws/avatar?type=group&id=' +
                        encodeURIComponent(g.id) + '&s=100') });
            });
            friends.forEach(function (f) {
                st.targets.push({ value: 'private:' + f.id, name: f.name || f.id,
                    code: f.id, sub: '好友',
                    avatar: f.avatar || ('/api/ws/avatar?type=user&id=' +
                        encodeURIComponent(f.id) + '&s=100') });
            });
            var keep = el.target.value;
            var found = st.targets.some(function (t) { return t.value === keep; });
            if (!found) { el.target.value = ''; }
            syncTarget();
            st.targetsLoaded = true;
            el.online.textContent = j.online ? 'QQ 在线' : 'QQ 未连接';
            el.online.className = 'fc-online ' + (j.online ? 'ok' : 'bad');
        }).catch(function () {
            st.targetsLoaded = false;
            el.online.textContent = '会话读取失败';
            el.online.className = 'fc-online bad';
        });
    }

    function preselectTarget(chat) {
        if (!chat || !chat.id) { return; }
        var v = (chat.type === 'group' ? 'group:' : 'private:') + chat.id;
        if (!(st.targets || []).some(function (t) { return t.value === v; })) { return; }
        el.target.value = v;
        syncTarget();
    }

    // 发送目标按钮（隐藏 input 没法聚焦，失败提示时聚焦到它）
    function targetButton() {
        return el.targetBtn;
    }

    // ---------------------------------------------------------------- 输出
    function setOutput(o) {
        st.output = o;
        if (st.objUrl) {
            URL.revokeObjectURL(st.objUrl);
            st.objUrl = '';
        }
        if (o.blob) {
            st.objUrl = URL.createObjectURL(o.blob);
            el.preview.src = st.objUrl;
        } else {
            el.preview.src = o.preview || o.url;
        }
        el.preview.hidden = false;
        el.empty.hidden = true;
        el.send.disabled = false;
        el.download.disabled = false;
    }

    function outputBlob() {
        if (!st.output) { return Promise.reject(new Error('还没有生成图片')); }
        if (st.output.blob) { return Promise.resolve(st.output.blob); }
        return fetch(st.output.url, { credentials: 'same-origin' }).then(function (r) {
            if (!r.ok) { throw new Error('图片下载失败'); }
            return r.blob();
        });
    }

    function sendOutput() {
        var t = currentTarget();
        if (!t) {
            toast('请先在右上角选择要发送的好友或群', true);
            var tb = targetButton();
            if (tb) { tb.focus(); }
            return;
        }
        if (!st.output) { return; }
        el.send.disabled = true;
        setStatus('发送中…');
        outputBlob().then(blobToDataUrl).then(function (dataUrl) {
            return api('/api/webqq/send', {
                method: 'POST',
                body: JSON.stringify({
                    type: t.type, id: t.id,
                    segments: [{ type: 'image', data: { data: dataUrl } }]
                })
            });
        }).then(function () {
            toast('已发送到「' + t.name + '」');
            setStatus('已发送 ✓');
        }).catch(function (e) {
            toast('发送失败：' + e.message, true);
            setStatus('发送失败');
        }).then(function () {
            el.send.disabled = false;
        });
    }

    function downloadOutput() {
        if (!st.output) { return; }
        var a = document.createElement('a');
        if (st.output.blob) {
            a.href = URL.createObjectURL(st.output.blob);
            a.download = st.output.name || 'image.png';
            a.click();
            setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
        } else {
            a.href = st.output.download || st.output.url;
            a.download = st.output.name || 'image.png';
            a.click();
        }
    }

    // ---------------------------------------------------------------- 名言图
    function renderQuoteThumbs() {
        el.quoteThumbs.innerHTML = st.quoteImages.map(function (d, i) {
            return '<div class="fc-thumb"><img src="' + d + '" alt="">' +
                '<button type="button" data-qi="' + i + '">×</button></div>';
        }).join('');
    }

    function readQuoteFiles(files) {
        var list = Array.prototype.slice.call(files || []).slice(0, 3);
        Promise.all(list.map(function (f) {
            return new Promise(function (resolve) {
                var fr = new FileReader();
                fr.onload = function () { resolve(String(fr.result || '')); };
                fr.onerror = function () { resolve(''); };
                fr.readAsDataURL(f);
            });
        })).then(function (list2) {
            st.quoteImages = st.quoteImages.concat(list2.filter(Boolean)).slice(0, 3);
            renderQuoteThumbs();
        });
    }

    function loadUrlImages(urls) {
        return Promise.all((urls || []).slice(0, 3).map(function (u) {
            var src = /^https?:\/\//i.test(u) ?
                '/api/webqq/img?u=' + encodeURIComponent(u) : u;
            return fetch(src, { credentials: 'same-origin' }).then(function (r) {
                if (!r.ok) { throw new Error('图片读取失败'); }
                return r.blob();
            }).then(blobToDataUrl).catch(function () { return ''; });
        })).then(function (list) {
            st.quoteImages = list.filter(Boolean).slice(0, 3);
            renderQuoteThumbs();
        });
    }

    function genQuote() {
        var text = el.quoteText.value.trim();
        if (!text) { return Promise.reject(new Error('先写一点文字')); }
        var t = currentTarget();
        var payload = {
            text: text,
            name: el.quoteName.value.trim(),
            qq: el.quoteQQ.value.trim(),
            gid: t && t.type === 'group' ? t.id : '',
            images: st.quoteImages.slice(0, 1)
        };
        return api('/api/quote/generate', {
            method: 'POST', body: JSON.stringify(payload)
        }).then(function (j) {
            if (!j.data) { throw new Error('渲染结果为空'); }
            var dataUrl = 'data:' + (j.mime || 'image/png') + ';base64,' + j.data;
            return fetch(dataUrl).then(function (r) { return r.blob(); });
        }).then(function (blob) {
            setOutput({
                blob: blob,
                name: 'quote-' + Date.now() + (blob.type === 'image/gif' ? '.gif' : '.jpg'),
                label: '名言图'
            });
        });
    }

    // ---------------------------------------------------------------- 配对卡
    function loadMeta() {
        if (st.metaLoaded) { return Promise.resolve(); }
        return api('/api/card/meta').then(function (j) {
            var tpl = j.templates || [];
            var tplMenu = selMenu(el.pairTplSel);
            if (tplMenu) {
                tplMenu.innerHTML = tpl.map(function (t) {
                    return selOptHtml(t.key, t.name + (t.desc ? ' · ' + t.desc : ''), t.key);
                }).join('');
            }
            var fonts = j.fonts || {};
            var keys = Object.keys(fonts);
            var fontMenu = selMenu(el.pairFontSel);
            if (fontMenu) {
                fontMenu.innerHTML = keys.map(function (k) {
                    return selOptHtml(k, fonts[k], k);
                }).join('');
            }
            if (!el.pairTpl.value && tpl.length) { el.pairTpl.value = tpl[0].key; }
            if (!el.pairFont.value && keys.length) { el.pairFont.value = keys[0]; }
            ilbbInit(el.pairTplSel);
            ilbbInit(el.pairFontSel);
            ilbbSync(el.pairTplSel);
            ilbbSync(el.pairFontSel);
            st.metaLoaded = true;
        }).catch(function () { /* 元数据失败时保留默认项 */ });
    }

    function fetchAvatarBase64(qq) {
        if (!qq || !/^\d+$/.test(qq)) { return Promise.resolve(''); }
        return fetch('/api/ws/avatar?type=user&id=' + encodeURIComponent(qq) + '&s=640',
            { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.blob() : Promise.reject(); })
            .then(blobToDataUrl)
            .then(function (d) { return d ? d.split(',')[1] || '' : ''; })
            .catch(function () { return ''; });
    }

    function genPair() {
        return loadMeta().then(function () {
            var qq = el.pairQQ.value.trim();
            return fetchAvatarBase64(qq).then(function (avatar) {
                return api('/api/generate_image', {
                    method: 'POST',
                    body: JSON.stringify({
                        qq: qq,
                        name: el.pairName.value.trim(),
                        avatar: avatar,
                        text: el.pairText.value.trim() || '要与 {name} 配对吗？',
                        btn_text: el.pairBtn.value.trim() || '配对',
                        font: el.pairFont.value || 'default',
                        template: el.pairTpl.value || 'classic'
                    })
                });
            });
        }).then(function (j) {
            if (!j.preview_url) { throw new Error('渲染结果为空'); }
            setOutput({
                url: j.preview_url,
                preview: j.preview_url,
                download: j.download_url,
                name: j.filename || 'pair.png',
                label: '配对卡'
            });
        });
    }

    // ---------------------------------------------------------------- Meme
    function renderMemeGrid() {
        var q = (el.memeSearch.value || '').trim().toLowerCase();
        var items = st.memes.filter(function (m) {
            if (!q) { return true; }
            var hay = (m.key + ' ' + (m.keywords || []).join(' ') + ' ' +
                (m.tags || []).join(' ')).toLowerCase();
            return hay.indexOf(q) >= 0;
        });
        if (!items.length) {
            el.memeGrid.innerHTML = '<div class="fc-empty-note">' +
                (st.memesLoaded ? '没有匹配的 meme' : '正在加载表情库…') + '</div>';
            return;
        }
        el.memeGrid.innerHTML = items.map(function (m) {
            var cur = st.meme && st.meme.key === m.key ? ' active' : '';
            return '<button type="button" class="fc-meme' + cur + '" data-key="' +
                esc(m.key) + '" title="' + esc(m.key) + '">' +
                '<img loading="lazy" src="/api/meme/preview/' +
                    encodeURIComponent(m.key) + '?t=0" alt="">' +
                '<span>' + esc(m.key) + '</span>' +
            '</button>';
        }).join('');
    }

    function loadMemes() {
        if (st.memesLoaded) { return Promise.resolve(); }
        el.memeGrid.innerHTML = '<div class="fc-empty-note">正在加载表情库…</div>';
        return api('/api/meme/list').then(function (j) {
            st.memes = j.items || [];
            st.memesLoaded = true;
            renderMemeGrid();
        }).catch(function (e) {
            el.memeGrid.innerHTML = '<div class="fc-empty-note">加载失败：' +
                esc(e.message) + '</div>';
        });
    }

    function optControl(o) {
        var name = esc(o.name);
        var val = o.default;
        if (o.type === 'bool') {
            return '<input type="checkbox" data-opt="' + name + '" data-otype="bool"' +
                (val ? ' checked' : '') + '>';
        }
        if (o.type === 'int' || o.type === 'float') {
            return '<input type="number" step="' + (o.type === 'float' ? '0.1' : '1') +
                '" data-opt="' + name + '" data-otype="' + o.type +
                '" value="' + esc(val == null ? 0 : val) + '">';
        }
        if (o.type === 'array' || o.type === 'list') {
            // 列表参数不让用户手写 JSON：一行一个值，提交时再拼成数组
            var rawVal = Array.isArray(val) ? val.join('\n') : (val == null ? '' : String(val));
            return '<textarea rows="3" data-opt="' + name + '" data-otype="lines"' +
                ' placeholder="每行一个值">' + esc(rawVal) + '</textarea>';
        }
        if (o.type === 'choose') {
            // ILBB 自定义下拉：隐藏 input 带 data-opt，readMemeOpts 照旧读它的 value
            var hid = 'fcOpt_' + String(o.name).replace(/[^A-Za-z0-9_-]/g, '_');
            var sel = 'fcOptSel_' + hid;
            var choices = o.choices || [];
            return '<div class="ilbb-select" id="' + sel + '" data-select="' + name +
                    '" data-target="' + hid + '">' +
                '<input type="hidden" id="' + hid + '" data-opt="' + name +
                    '" data-otype="choose" value="' + esc(val == null ? '' : val) + '">' +
                '<button type="button" class="ilbb-select-btn" aria-haspopup="listbox"' +
                    ' aria-expanded="false"><span class="ilbb-select-text">' +
                    esc(val == null ? '' : val) + '</span>' +
                    '<span class="ilbb-select-caret"></span></button>' +
                '<ul class="ilbb-select-menu" role="listbox">' +
                choices.map(function (c) {
                    return selOptHtml(c, c, c);
                }).join('') + '</ul>' +
            '</div>';
        }
        return '<input type="text" data-opt="' + name + '" data-otype="text" value="' +
            esc(val == null ? '' : val) + '">';
    }

    function renderOpts(item) {
        var opts = item.options || [];
        if (!opts.length) {
            el.memeOpts.innerHTML = '<div class="fc-hint">这个 meme 没有额外参数。</div>';
            return;
        }
        el.memeOpts.innerHTML = opts.map(function (o) {
            return '<div class="fc-opt"><span class="fc-opt-name">' + esc(o.name) +
                '</span>' + optControl(o) +
                (o.help ? '<span class="fc-opt-help">' + esc(o.help) + '</span>' : '') +
            '</div>';
        }).join('');
        // 参数里新渲染出来的 ILBB 下拉要重新挂交互
        ilbbInit(el.memeOpts);
        ilbbSync(el.memeOpts);
    }

    function renderStyles(item) {
        var chooses = (item.options || []).filter(function (o) {
            return o.type === 'choose' && (o.choices || []).length;
        });
        if (!chooses.length) {
            el.memeStyles.innerHTML = '';
            return;
        }
        el.memeStyles.innerHTML = chooses.map(function (o) {
            var row = (o.choices || []).map(function (c) {
                var args = {};
                args[o.name] = c;
                var url = '/api/meme/preview/' + encodeURIComponent(item.key) +
                    '?args=' + encodeURIComponent(JSON.stringify(args));
                return '<button type="button" class="fc-style" data-sopt="' +
                    esc(o.name) + '" data-sval="' + esc(c) + '">' +
                    '<img loading="lazy" src="' + url + '" alt="">' +
                    '<span>' + esc(c) + '</span></button>';
            }).join('');
            return '<div><div class="fc-style-name">' + esc(o.name) +
                ' 预设样式（点击切换）</div><div class="fc-style-row">' + row +
                '</div></div>';
        }).join('');
    }

    function selectMeme(key) {
        var item = null;
        st.memes.forEach(function (m) { if (m.key === key) { item = m; } });
        if (!item) { return; }
        st.meme = item;
        st.output = null;
        el.memeForm.classList.remove('hidden');
        el.memeName.textContent = item.key;
        el.memeKey.textContent = (item.keywords || []).join(' / ');
        el.memeNeed.textContent = (item.min_images || 0) + ' ~ ' +
            (item.max_images || 0);
        el.memeTexts.value = (item.default_texts || []).join('\n');
        el.memeFiles.value = '';
        el.memeThumbs.innerHTML = '';
        renderOpts(item);
        renderStyles(item);
        renderMemeGrid();
        el.preview.src = '/api/meme/preview/' + encodeURIComponent(item.key);
        el.preview.hidden = false;
        el.empty.hidden = true;
        el.send.disabled = true;
        el.download.disabled = true;
        setStatus('默认样式预览，点「生成」后可发送');
    }

    function readMemeOpts() {
        var args = {};
        Array.prototype.forEach.call(
            el.memeOpts.querySelectorAll('[data-opt]'), function (node) {
                var name = node.getAttribute('data-opt');
                var type = node.getAttribute('data-otype');
                var v;
                if (type === 'bool') { v = !!node.checked; }
                else if (type === 'int') {
                    v = parseInt(node.value, 10);
                    if (isNaN(v)) { v = 0; }
                } else if (type === 'float') {
                    v = parseFloat(node.value);
                    if (isNaN(v)) { v = 0; }
                } else if (type === 'lines') {
                    v = String(node.value || '').split(/\r?\n/)
                        .map(function (x) { return x.trim(); })
                        .filter(Boolean);
                } else {
                    v = node.value;
                }
                args[name] = v;
            });
        return args;
    }

    function fillAvatarB64() {
        var t = currentTarget();
        var qq = (el.memeQQ.value || '').trim() ||
            (t && t.type === 'private' ? t.id : '');
        var need = (st.meme ? (st.meme.min_images || 0) : 0) -
            (el.memeFiles.files ? el.memeFiles.files.length : 0);
        if (!el.memeFill.checked || need <= 0) { return Promise.resolve(''); }
        return fetchAvatarBase64(qq);
    }

    function genMeme() {
        if (!st.meme) { return Promise.reject(new Error('先选择一个 meme')); }
        var item = st.meme;
        var form = new FormData();
        form.append('key', item.key);
        form.append('args', JSON.stringify(readMemeOpts()));
        var texts = (el.memeTexts.value || '').split(/\r?\n/)
            .map(function (s) { return s.trim(); })
            .filter(function (s) { return !!s; });
        form.append('texts', JSON.stringify(texts));
        var files = el.memeFiles.files || [];
        for (var i = 0; i < files.length; i++) {
            form.append('images', files[i], files[i].name);
        }
        return fillAvatarB64().then(function (b64) {
            if (b64) { form.append('images_b64', b64); }
            return fetch('/api/meme/generate', {
                method: 'POST', body: form, credentials: 'same-origin'
            });
        }).then(function (r) {
            if (!r.ok) {
                return r.text().then(function (txt) {
                    var msg = 'HTTP ' + r.status;
                    try {
                        var j = JSON.parse(txt);
                        msg = j.error || msg;
                    } catch (e) { /* 非 JSON 错误 */ }
                    throw new Error(msg);
                });
            }
            return r.blob();
        }).then(function (blob) {
            setOutput({
                blob: blob,
                name: item.key + '-' + Date.now() + '.png',
                label: 'Meme'
            });
        });
    }

    // ---------------------------------------------------------------- 生成 / 发送
    function generate() {
        if (st.busy) { return; }
        st.busy = true;
        el.generate.disabled = true;
        setStatus('生成中…');
        var job;
        if (st.tab === 'quote') { job = genQuote(); }
        else if (st.tab === 'pair') { job = genPair(); }
        else { job = genMeme(); }
        job.then(function () {
            setStatus('生成完成');
        }).catch(function (e) {
            toast(e.message || '生成失败', true);
            setStatus('生成失败');
        }).then(function () {
            st.busy = false;
            el.generate.disabled = false;
        });
    }

    // ---------------------------------------------------------------- 交互
    function setTab(tab) {
        st.tab = tab;
        Array.prototype.forEach.call(
            el.tabs.querySelectorAll('.fc-tab'), function (b) {
                b.classList.toggle('active', b.getAttribute('data-fc-tab') === tab);
            });
        Object.keys(el.panes).forEach(function (k) {
            el.panes[k].classList.toggle('active', k === tab);
        });
        if (tab === 'meme') { loadMemes(); }
        if (tab === 'pair') { loadMeta(); }
    }

    // ---------------------------------------------------------------- 弹窗
    function applyDetail(d) {
        if (!d) { return; }
        setTab('quote');
        loadTargets(false).then(function () {
            if (d.chat) { preselectTarget(d.chat); }
            if (d.text) { el.quoteText.value = d.text; }
            if (d.name) { el.quoteName.value = d.name; }
            if (d.qq) { el.quoteQQ.value = d.qq; }
            if (d.images && d.images.length) { loadUrlImages(d.images); }
        });
    }

    var closeTimer = 0;
    function openModal(detail) {
        clearTimeout(closeTimer);
        root.classList.remove('hidden');
        root.classList.remove('closing');
        loadTargets(false);
        if (st.tab === 'meme') { loadMemes(); }
        if (st.tab === 'pair') { loadMeta(); }
        applyDetail(detail);
        setTimeout(function () {
            if (detail && el.quoteText) { el.quoteText.focus(); }
        }, 60);
    }

    function closeModal() {
        if (root.classList.contains('hidden') || root.classList.contains('closing')) { return; }
        closeTargetPop();
        var api = window.ILBBSelect;
        if (api && api.closeAll) { try { api.closeAll(); } catch (e) { /* 忽略 */ } }
        // 先播放收起动画（wq-fc-out / wq-fc-fade-out），160ms 后再隐藏
        root.classList.add('closing');
        clearTimeout(closeTimer);
        closeTimer = setTimeout(function () {
            root.classList.add('hidden');
            root.classList.remove('closing');
        }, 160);
    }

    window.ILBBFastCompose = { open: openModal, close: closeModal };

    function bind() {
        el.tabs.addEventListener('click', function (e) {
            var b = e.target.closest('.fc-tab');
            if (b) { setTab(b.getAttribute('data-fc-tab')); }
        });

        // 左栏是滚动容器，ILBB 浮层展开会被裁掉：按「距面板底部的空间」改判向上展开。
        // 冒泡顺序在 ILBB 自己的按钮 handler 之后，此时 .open 状态已就绪。
        var side = document.querySelector('.fc-side');
        if (side) {
            side.addEventListener('click', function (e) {
                var sel = e.target.closest('.ilbb-select');
                if (!sel || !sel.classList.contains('open')) { return; }
                var btn = sel.querySelector('.ilbb-select-btn');
                if (!btn) { return; }
                var pr = side.getBoundingClientRect(), r = btn.getBoundingClientRect();
                var need = 278;                       // 浮层最大高度 + 间距
                var below = pr.bottom - r.bottom;
                var up = below < need && (r.top - pr.top) > below;
                sel.classList.toggle('drop-up', up);
            });
        }

        // 发送目标选择面板：按钮开合、搜索、点头像行选中
        if (el.targetBtn) {
            el.targetBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                if (el.targetPop.classList.contains('hidden')) { openTargetPop(); }
                else { closeTargetPop(); }
            });
        }
        if (el.targetSearch) {
            el.targetSearch.addEventListener('click', function (e) { e.stopPropagation(); });
            el.targetSearch.addEventListener('input', function () {
                filterTargets(el.targetSearch.value);
            });
            el.targetSearch.addEventListener('keydown', function (e) {
                e.stopPropagation();
                if (e.key === 'Escape') {
                    el.targetSearch.value = '';
                    filterTargets('');
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    var first = el.targetList.querySelector('.fc-target-row');
                    if (first) { pickTarget(first.getAttribute('data-value')); }
                }
            });
        }
        if (el.targetList) {
            el.targetList.addEventListener('click', function (e) {
                var row = e.target.closest('.fc-target-row');
                if (row) { pickTarget(row.getAttribute('data-value')); }
            });
        }
        if (el.targetManualGo) {
            el.targetManualGo.addEventListener('click', pickManualTarget);
        }
        if (el.targetManual) {
            el.targetManual.addEventListener('click', function (e) { e.stopPropagation(); });
            el.targetManual.addEventListener('keydown', function (e) {
                e.stopPropagation();
                if (e.key === 'Enter') { e.preventDefault(); pickManualTarget(); }
                else if (e.key === 'Escape') { closeTargetPop(); }
            });
        }
        document.addEventListener('click', function (e) {
            if (!el.targetPop || el.targetPop.classList.contains('hidden')) { return; }
            if (el.targetPop.contains(e.target) || el.targetBtn.contains(e.target)) { return; }
            closeTargetPop();
        });

        el.targetRefresh.addEventListener('click', function () {
            st.targetsLoaded = false;
            loadTargets(true);
        });

        el.target.addEventListener('change', function () {
            var t = currentTarget();
            if (t && t.type === 'private' && !el.memeQQ.value) {
                el.memeQQ.value = t.id;
            }
        });

        el.quoteImages.addEventListener('change', function () {
            readQuoteFiles(el.quoteImages.files);
        });
        el.quoteThumbs.addEventListener('click', function (e) {
            var b = e.target.closest('button[data-qi]');
            if (!b) { return; }
            st.quoteImages.splice(parseInt(b.getAttribute('data-qi'), 10), 1);
            renderQuoteThumbs();
        });

        el.memeSearch.addEventListener('input', renderMemeGrid);
        el.memeGrid.addEventListener('click', function (e) {
            var b = e.target.closest('.fc-meme');
            if (b) { selectMeme(b.getAttribute('data-key')); }
        });
        el.memeStyles.addEventListener('click', function (e) {
            var b = e.target.closest('.fc-style');
            if (!b) { return; }
            var name = b.getAttribute('data-sopt');
            var val = b.getAttribute('data-sval');
            var hid = el.memeOpts.querySelector('[data-opt="' + name + '"]');
            if (hid) {
                hid.value = val;
                ilbbSync(el.memeOpts);          // 同步下拉按钮上的显示文字
            }
            Array.prototype.forEach.call(
                b.parentNode.querySelectorAll('.fc-style'), function (x) {
                    x.classList.toggle('active', x === b);
                });
        });
        el.memeReset.addEventListener('click', function () {
            if (!st.meme) { return; }
            renderOpts(st.meme);
            renderStyles(st.meme);
            el.memeTexts.value = (st.meme.default_texts || []).join('\n');
            toast('参数已重置');
        });
        el.memeFiles.addEventListener('change', function () {
            var files = el.memeFiles.files || [];
            el.memeThumbs.innerHTML = Array.prototype.map.call(files, function (f) {
                return '<div class="fc-thumb"><img src="' +
                    esc(URL.createObjectURL(f)) + '" alt=""></div>';
            }).join('');
        });

        el.generate.addEventListener('click', generate);
        el.send.addEventListener('click', sendOutput);
        el.download.addEventListener('click', downloadOutput);

        // 打开 / 关闭弹窗
        if (el.close) { el.close.addEventListener('click', closeModal); }
        if (el.mask) {
            el.mask.addEventListener('click', function (e) {
                if (e.target === el.mask) { closeModal(); }
            });
        }
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape' || root.classList.contains('hidden')) { return; }
            if (el.targetPop && !el.targetPop.classList.contains('hidden')) {
                closeTargetPop();
                return;
            }
            closeModal();
        });

        // WebQQ 右键「合成名言图（可编辑）」带过来的一次性数据
        document.addEventListener('ilbb:fastcompose', function (e) {
            openModal(e.detail);
        });

        // Enter 快速生成（textarea / input 里 Ctrl+Enter）
        root.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                generate();
            }
        });
    }

    bind();
})();

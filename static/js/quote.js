/* ============================================================
 * 名言图（Quote）—— 合成大类 → 子选项「名言图」
 * 横屏 16:9：随机二次元背景 + 灰色蒙版（默认不透明度 35%）
 *          + 左侧独立长方形圆角头像 + 右侧铺满右半边的白色磨砂玻璃面板
 *          + 右下角「—— 署名」（字体跟随全局 FONT_FAMILY）；静态出 JPG，动图出 GIF
 * 字体下拉复用主页那套 ILBB 自定义下拉（window.ILBBSelect）
 * 生成走后端 POST /api/quote/generate
 * ============================================================ */
document.addEventListener('DOMContentLoaded', function() {
    var $ = function(id) { return document.getElementById(id); };

    var qqInput = $('quoteQQ');
    var fetchBtn = $('quoteFetchQQ');
    var qqStatus = $('quoteQQStatus');
    var nameInput = $('quoteName');

    var seg = $('quoteSeg');
    var modeText = $('quoteModeText');
    var modeImage = $('quoteModeImage');
    var textInput = $('quoteText');

    var drop = $('quoteDrop');
    var imgInput = $('quoteImgInput');
    var dropLabel = $('quoteDropLabel');

    var bgRow = $('quoteBgRow');
    var bgUpload = $('quoteBgUpload');
    var bgInput = $('quoteBgInput');
    var bgLabel = $('quoteBgLabel');

    var genBtn = $('quoteGenerateBtn');
    var loading = $('quoteLoading');
    var dlBtn = $('quoteDownloadBtn');

    var globalFontSel = $('quoteGlobalFont');

    var meta = $('quoteMeta');
    var metaName = $('quoteMetaName');
    var metaFont = $('quoteMetaFont');
    var metaBg = $('quoteMetaBg');
    var metaBubble = $('quoteMetaBubble');
    var metaFormat = $('quoteMetaFormat');

    var ph = $('quotePlaceholder');
    var previewWrap = $('quotePreviewWrap');
    var previewImg = $('quotePreviewImg');
    var previewTip = $('quotePreviewTip');

    if (!genBtn) return;   // 不在本页

    var state = {
        mode: 'text',      // text | image
        bg: 'random',      // random | upload | none
        bubbleDataURL: '', // 表情包 dataURL
        bgDataURL: '',     // 自定义背景 dataURL
        resultData: '',    // 上次生成结果的 base64（不含前缀）
        resultMime: 'image/jpeg',
        resultName: 'quote.jpg',
        cfg: {}
    };

    function toast(msg) {
        var e = document.querySelector('.toast');
        if (e) e.remove();
        var t = document.createElement('div');
        t.className = 'toast';
        t.textContent = msg;
        document.body.appendChild(t);
        requestAnimationFrame(function() { t.classList.add('show'); });
        setTimeout(function() { t.classList.remove('show'); setTimeout(function() { t.remove(); }, 400); }, 2500);
    }

    function setStatus(msg, color) {
        qqStatus.classList.remove('hidden');
        qqStatus.textContent = msg;
        qqStatus.style.color = color || '#8c8f9c';
    }

    function readFile(file, cb) {
        var fr = new FileReader();
        fr.onload = function() { cb(fr.result); };
        fr.onerror = function() { toast('读取文件失败'); };
        fr.readAsDataURL(file);
    }

    // ===== 字体下拉 =====
    // 与主页同款 ILBB 自定义下拉：真实取值写在与 data-target 同 id 的隐藏 input 里，
    // 选项是 ul.ilbb-select-menu 里的一串 li.ilbb-select-opt，交互由 ws.js 的
    // window.ILBBSelect 统一接管。这里只负责「填选项 + 同步显示 + 初始化」。
    var fontBox = $('quoteFontBox');

    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function escAttr(s) {
        return escHtml(s).replace(/"/g, '&quot;');
    }

    function selOf(hid) {
        if (!hid || !hid.closest) return null;
        return hid.closest('.ilbb-select');
    }

    // 填选项并同步隐藏 input；current 不在候选里就退回第一项
    function fillFontSelect(hid, options, current) {
        var sel = selOf(hid);
        if (!sel) return;
        var menu = sel.querySelector('.ilbb-select-menu');
        if (!menu) return;
        if (!options || !options.length) {
            menu.innerHTML = '';
            sel.setAttribute('data-state', 'error');
            syncFontSelects();
            return;
        }
        var val = current == null ? '' : String(current);
        var has = options.some(function(o) { return String(o[0]) === val; });
        if (!has) val = String(options[0][0]);
        if (hid) hid.value = val;
        sel.removeAttribute('data-state');
        menu.innerHTML = options.map(function(o) {
            var v = String(o[0]);
            var label = o[1] || v;
            return '<li class="ilbb-select-opt" role="option" data-value="' + escAttr(v) + '"'
                + ' data-search="' + escAttr(label + ' ' + v) + '" aria-selected="false">'
                + '<span class="ilbb-select-opt-main">' + escHtml(label) + '</span>'
                + '<span class="ilbb-select-opt-code">' + escHtml(v) + '</span>'
                + '<span class="ilbb-select-tick">✓</span></li>';
        }).join('');
        syncFontSelects();
    }

    // quote.js 比 ws.js 先加载，此刻 window.ILBBSelect 可能还没挂上：轮询等它就绪
    var fontInitTimer = 0;
    function syncFontSelects() {
        if (!fontBox) return;
        var api = window.ILBBSelect;
        if (api && api.init) { api.init(fontBox); return; }
        if (fontInitTimer) return;
        fontInitTimer = setInterval(function() {
            if (window.ILBBSelect && window.ILBBSelect.init) {
                clearInterval(fontInitTimer);
                fontInitTimer = 0;
                window.ILBBSelect.init(fontBox);
            }
        }, 60);
    }

    // 字体下拉的按钮（写着状态文案的那个），保存期间禁用它
    function fontBtnOf(hid) {
        var sel = selOf(hid);
        return sel ? sel.querySelector('.ilbb-select-btn') : null;
    }

    function fontLabel(options, value) {
        var v = String(value == null ? '' : value);
        var hit = (options || []).filter(function(o) { return String(o[0]) === v; })[0];
        return hit ? (hit[1] || hit[0]) : (v || '跟随全局');
    }

    // 配置读不到时别把「读取中…」一直挂着——直接写明失败原因
    function fontCfgFailed(msg) {
        [globalFontSel].forEach(function(hid) {
            var sel = selOf(hid);
            if (!sel) return;
            sel.setAttribute('data-state', 'error');
            var txt = sel.querySelector('.ilbb-select-text');
            if (txt) txt.textContent = (sel.getAttribute('data-prefix') || '') + msg;
        });
    }

    (async function loadCfg() {
        try {
            var res = await fetch('/api/quote/config');
            var data = await res.json();
            if (data && data.ok) {
                state.cfg = data;
                if (!nameInput.getAttribute('placeholder') || true) {
                    nameInput.setAttribute('placeholder',
                        '留空则用昵称 / 默认「' + (data.name_default || '无名氏') + '」');
                }
                fillFontSelect(globalFontSel, data.font_options, data.font_current);
                if (!data.enabled) {
                    genBtn.disabled = true;
                    genBtn.textContent = '名言合成已关闭';
                    setStatus('后端 QUOTE_ENABLED=false，名言合成已关闭', '#e05555');
                } else {
                    setStatus('输出 JPG / GIF · ' + data.width + '×' + (data.height || 720) +
                        ' · 蒙版不透明度 ' + Math.round((data.mask_alpha == null ? 0.35 : data.mask_alpha) * 100) + '%',
                        '#8c8f9c');
                }
            } else {
                fontCfgFailed('读取失败（' + res.status + '），刷新重试');
            }
        } catch (e) {
            fontCfgFailed('读取失败，刷新重试');
        }
    })();

    // ===== 字体：全局字体立即写入设置并热生效（署名跟随全局字体） =====
    // 监听的是隐藏 input 的 change（ILBB 下拉选完会广播一次），
    // 这样「用下拉选」和「代码里直接改 value」两条路径都能被同一处接住。
    if (globalFontSel) {
        globalFontSel.addEventListener('change', async function() {
            var val = globalFontSel.value;
            if (!val) return;
            var gBtn = fontBtnOf(globalFontSel);
            if (gBtn) gBtn.disabled = true;
            try {
                var res = await fetch('/api/env/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ updates: { FONT_FAMILY: val } })
                });
                var d = await res.json();
                if (!res.ok || !d || d.ok === false) {
                    toast('全局字体保存失败：' + ((d && d.error) || '未知错误'));
                    return;
                }
                toast('全局字体已切换为「' + fontLabel(state.cfg.font_options, val) + '」' +
                    ((d.restart || []).length ? '（部分项需重启）' : ''));
                // 全局字体变了，署名跟着变，所以重新拉一次配置刷新下拉
                try {
                    var r2 = await fetch('/api/quote/config');
                    var d2 = await r2.json();
                    if (d2 && d2.ok) {
                        state.cfg = d2;
                        fillFontSelect(globalFontSel, d2.font_options, d2.font_current);
                    }
                } catch (e2) { /* 刷新失败不影响已保存 */ }
            } catch (e) {
                toast('网络错误，全局字体保存失败');
            } finally {
                if (gBtn) gBtn.disabled = false;
            }
        });
    }

    // ===== QQ 号取头像 + 昵称 =====
    fetchBtn.addEventListener('click', async function() {
        var qq = (qqInput.value || '').trim();
        if (!/^\d{5,11}$/.test(qq)) { toast('请输入 5-11 位有效 QQ 号'); return; }
        fetchBtn.disabled = true;
        setStatus('正在获取...', '#8c8f9c');
        try {
            var res = await fetch('/api/get_user_info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ qq: qq })
            });
            var data = await res.json();
            if (!data || data.error) {
                setStatus('获取失败：' + ((data && data.error) || '未知错误'), '#e05555');
                return;
            }
            window.__avatar = data.avatar;
            window.__qq = data.qq;
            window.__qqName = data.name || data.qq;
            if (!nameInput.value) nameInput.value = data.name || data.qq || '';
            setStatus('已获取「' + (data.name || data.qq) + '」的头像与昵称', '#34c759');
        } catch (e) {
            setStatus('网络错误，请重试', '#e05555');
        } finally {
            fetchBtn.disabled = false;
        }
    });

    qqInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') { e.preventDefault(); fetchBtn.click(); }
    });

    // ===== 面板内容：文字 / 表情包 =====
    Array.prototype.slice.call(seg.querySelectorAll('.quote-seg-btn')).forEach(function(btn) {
        btn.addEventListener('click', function() {
            Array.prototype.slice.call(seg.querySelectorAll('.quote-seg-btn')).forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');
            state.mode = btn.getAttribute('data-qmode');
            modeText.classList.toggle('hidden', state.mode !== 'text');
            modeImage.classList.toggle('hidden', state.mode !== 'image');
        });
    });

    // 表情包：点击 / 拖拽
    imgInput.addEventListener('change', function() {
        var f = imgInput.files && imgInput.files[0];
        if (!f) return;
        readFile(f, function(url) {
            state.bubbleDataURL = url;
            drop.classList.add('has-file');
            dropLabel.textContent = '已选择：' + f.name + '（点击可更换）';
        });
    });

    ['dragenter', 'dragover'].forEach(function(ev) {
        drop.addEventListener(ev, function(e) {
            e.preventDefault(); e.stopPropagation();
            drop.classList.add('dragover');
        });
    });
    ['dragleave', 'drop'].forEach(function(ev) {
        drop.addEventListener(ev, function(e) {
            e.preventDefault(); e.stopPropagation();
            drop.classList.remove('dragover');
        });
    });
    drop.addEventListener('drop', function(e) {
        var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (!f) return;
        if (!/^image\//.test(f.type)) { toast('请拖入图片文件'); return; }
        readFile(f, function(url) {
            state.bubbleDataURL = url;
            drop.classList.add('has-file');
            dropLabel.textContent = '已选择：' + f.name + '（点击可更换）';
        });
    });

    // ===== 背景三选 =====
    if (bgRow) {
        Array.prototype.slice.call(bgRow.querySelectorAll('.bg-type')).forEach(function(btn) {
            btn.addEventListener('click', function() {
                Array.prototype.slice.call(bgRow.querySelectorAll('.bg-type')).forEach(function(b) {
                    b.classList.remove('active');
                });
                btn.classList.add('active');
                state.bg = btn.getAttribute('data-qbg');
                bgUpload.classList.toggle('hidden', state.bg !== 'upload');
            });
        });
    }

    bgInput.addEventListener('change', function() {
        var f = bgInput.files && bgInput.files[0];
        if (!f) return;
        readFile(f, function(url) {
            state.bgDataURL = url;
            bgLabel.textContent = '已选择：' + f.name + '（点击可更换）';
        });
    });

    // ===== 生成 =====
    genBtn.addEventListener('click', async function() {
        var text = state.mode === 'text' ? (textInput.value || '').trim() : '';
        if (state.mode === 'text' && !text) { toast('请先写点什么，或切到「表情包」'); return; }
        if (state.mode === 'image' && !state.bubbleDataURL) { toast('请先选择一张表情包'); return; }

        var payload = {
            text: text,
            name: (nameInput.value || '').trim(),
            qq: (qqInput.value || '').trim(),
            images: state.mode === 'image' && state.bubbleDataURL ? [state.bubbleDataURL] : [],
            no_bg: state.bg === 'none'
        };
        if (state.bg === 'upload' && state.bgDataURL) payload.bg = state.bgDataURL;
        // 自定义背景但没选图 → 当作随机图（后端会走随机 API）
        // 头像：优先用已获取的 QQ 头像（不传则由后端按 qq 拉取）
        if (window.__avatar && (qqInput.value || '').trim() && window.__qq === (qqInput.value || '').trim()) {
            payload.avatar = 'data:image/jpeg;base64,' + window.__avatar;
        }

        genBtn.disabled = true;
        loading.classList.remove('hidden');
        dlBtn.classList.add('hidden');
        try {
            var res = await fetch('/api/quote/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            var data = await res.json();
            if (!res.ok || !data || !data.ok) {
                toast((data && data.error) || ('生成失败 (' + res.status + ')'));
                return;
            }
            state.resultData = data.data;
            state.resultMime = data.mime || 'image/jpeg';
            var ext = (state.resultMime === 'image/gif') ? '.gif'
                    : (state.resultMime === 'image/webp') ? '.webp'
                    : (state.resultMime === 'image/png') ? '.png' : '.jpg';
            state.resultName = 'quote_' + Date.now() + ext;
            var src = 'data:' + state.resultMime + ';base64,' + data.data;
            previewImg.src = src;
            ph.style.display = 'none';
            previewWrap.style.display = 'block';
            previewTip.textContent = (data.bytes ? (Math.round(data.bytes / 1024) + ' KB · ') : '') +
                (state.resultMime === 'image/gif' ? 'GIF 动图 · ' : '') + state.resultName;

            metaName.textContent = data.name || '(未署名)';
            if (metaFont) {
                // 署名没有独立字体了：恒为「跟随全局」+ 当前全局字体名
                metaFont.textContent = '跟随全局 · ' +
                    fontLabel(state.cfg.font_options, state.cfg.font_current);
            }
            metaBg.textContent = data.has_bg ? (state.bg === 'upload' ? '自定义图' : '随机图') : '内置底色';
            metaBubble.textContent = data.bubble_image ? '表情包' : '文字';
            if (metaFormat) metaFormat.textContent = data.animated ? 'GIF（动图）' : 'JPG（静态）';
            meta.classList.remove('hidden');
            dlBtn.textContent = data.animated ? '下载 GIF' : '下载图片';
            dlBtn.classList.remove('hidden');
            if (data.note) toast(data.note);
        } catch (e) {
            toast('生成失败：' + e.message);
        } finally {
            genBtn.disabled = false;
            loading.classList.add('hidden');
        }
    });

    // ===== 下载 =====
    dlBtn.addEventListener('click', function() {
        if (!state.resultData) { toast('请先生成名言图'); return; }
        var bin = atob(state.resultData);
        var buf = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
        var url = URL.createObjectURL(new Blob([buf], { type: state.resultMime || 'image/jpeg' }));
        var a = document.createElement('a');
        a.href = url;
        a.download = state.resultName;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function() { URL.revokeObjectURL(url); }, 4000);
    });

    // 暴露给其它面板 / 插件页复用同一套渲染逻辑
    window.ILBBQuote = {
        state: state,
        generate: function(payload) {
            return fetch('/api/quote/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function(r) { return r.json(); });
        }
    };
});

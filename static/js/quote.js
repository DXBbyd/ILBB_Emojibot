/* ============================================================
 * 名言图（Quote）—— 合成大类 → 子选项「名言图」
 * 输出 JPG：随机背景 + 90% 黑色蒙版 + 左侧方形圆角头像
 *          + 右侧笑死气泡（文字 / 表情包）+ 右下角「—— 署名」
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

    var meta = $('quoteMeta');
    var metaName = $('quoteMetaName');
    var metaBg = $('quoteMetaBg');
    var metaBubble = $('quoteMetaBubble');

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

    // ===== 配置默认值 =====
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
                if (!data.enabled) {
                    genBtn.disabled = true;
                    genBtn.textContent = '名言合成已关闭';
                    setStatus('后端 QUOTE_ENABLED=false，名言合成已关闭', '#e05555');
                } else {
                    setStatus('输出 JPG · ' + data.width + 'px 宽 · 蒙版 ' +
                        Math.round((data.mask_alpha || 0.9) * 100) + '%', '#8c8f9c');
                }
            }
        } catch (e) { /* 配置接口不可用不影响生成 */ }
    })();

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

    // ===== 气泡内容：文字 / 表情包 =====
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
            state.resultName = 'quote_' + Date.now() + '.jpg';
            var src = 'data:' + (data.mime || 'image/jpeg') + ';base64,' + data.data;
            previewImg.src = src;
            ph.style.display = 'none';
            previewWrap.style.display = 'block';
            previewTip.textContent = (data.bytes ? (Math.round(data.bytes / 1024) + ' KB · ') : '') + state.resultName;

            metaName.textContent = data.name || '(未署名)';
            metaBg.textContent = data.has_bg ? (state.bg === 'upload' ? '自定义图' : '随机图') : '纯黑底';
            metaBubble.textContent = data.bubble_image ? '表情包' : '文字';
            meta.classList.remove('hidden');
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
        var url = URL.createObjectURL(new Blob([buf], { type: 'image/jpeg' }));
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

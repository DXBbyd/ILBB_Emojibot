document.addEventListener('DOMContentLoaded', function() {
    var qqInput = document.getElementById('qqInput');
    var textPart1 = document.getElementById('textPart1');
    var textPart2 = document.getElementById('textPart2');
    var btnTextInput = document.getElementById('btnTextInput');
    var fontSelect = document.getElementById('fontSelect');
    var fetchBtn = document.getElementById('fetchBtn');
    var loadingBar = document.getElementById('loadingBar');
    var placeholder = document.getElementById('placeholder');
    var previewImageContainer = document.getElementById('previewImageContainer');
    var previewImage = document.getElementById('previewImage');
    var downloadBtn = document.getElementById('downloadBtn');
    var userInfoPreview = document.getElementById('userInfoPreview');
    var previewQQ = document.getElementById('previewQQ');
    var previewName = document.getElementById('previewName');
    var previewCache = document.getElementById('previewCache');
    var previewFilename = document.getElementById('previewFilename');
    var cacheStatusRow = document.getElementById('cacheStatusRow');
    var filenameRow = document.getElementById('filenameRow');
    var cacheBadge = document.getElementById('cacheBadge');
    var clearCacheBtn = document.getElementById('clearCacheBtn');

    // ===== 模板与背景相关 =====
    var tplItems = Array.prototype.slice.call(document.querySelectorAll('.tpl-item'));
    // 仅配对卡自己的背景按钮（名言图表单的 .bg-type 用 data-qbg，由 quote.js 负责）
    var bgTypeButtons = Array.prototype.slice.call(document.querySelectorAll('.bg-type[data-bgtype]'));
    var bgEditors = { gradient: document.getElementById('bgEditorGradient'),
                      color: document.getElementById('bgEditorColor'),
                      image: document.getElementById('bgEditorImage') };
    var gColor1 = document.getElementById('gColor1');
    var gColor2 = document.getElementById('gColor2');
    var bgDirButtons = Array.prototype.slice.call(document.querySelectorAll('.bg-dir'));
    var solidColor = document.getElementById('solidColor');
    var bgImageInput = document.getElementById('bgImageInput');
    var bgUploadLabel = document.getElementById('bgUploadLabel');

    // ===== 选项按钮（单/多） =====
    var btnModeButtons = Array.prototype.slice.call(document.querySelectorAll('.btnmode'));
    var btnSingle = document.getElementById('btnSingle');
    var btnMulti = document.getElementById('btnMulti');
    var btnSlotGrid = document.getElementById('btnSlotGrid');
    var currentMode = 'single';
    var slotState = [];   // 每个槽: {type, text, icon(base64)}

    var currentData = null;
    var downloadUrl = null;
    var currentFilename = null;
    var currentTemplate = 'classic';
    var currentBg = null;   // 上传图片的 base64（仅 image 类型）

    // ===== 渲染4个按钮槽 =====
    function renderSlots() {
        btnSlotGrid.innerHTML = '';
        for (var i = 0; i < 4; i++) {
            (function(idx) {
                var slot = document.createElement('div');
                slot.className = 'btn-slot';

                // 类型选择用 ILBB 自定义下拉（不用浏览器原生 select）；
                // sel 仍是承载真实值的隐藏 input，sel.value / change 契约完全不变。
                var sel = document.createElement('input');
                sel.type = 'hidden';
                sel.className = 'slot-type';
                sel.id = 'slotType' + idx;
                sel.value = 'text';

                var selBox = document.createElement('div');
                selBox.className = 'ilbb-select';
                selBox.setAttribute('data-select', 'slot_type_' + idx);
                selBox.setAttribute('data-target', sel.id);

                var selBtn = document.createElement('button');
                selBtn.type = 'button';
                selBtn.className = 'ilbb-select-btn';
                selBtn.setAttribute('aria-haspopup', 'listbox');
                selBtn.setAttribute('aria-expanded', 'false');
                var selTxt = document.createElement('span');
                selTxt.className = 'ilbb-select-text';
                selTxt.textContent = '请选择';
                var selCaret = document.createElement('span');
                selCaret.className = 'ilbb-select-caret';
                selBtn.appendChild(selTxt);
                selBtn.appendChild(selCaret);

                var selMenu = document.createElement('ul');
                selMenu.className = 'ilbb-select-menu';
                selMenu.setAttribute('role', 'listbox');
                var opts = [['text', '纯文字'], ['icon_text', '图标+文字'], ['image', '纯图片']];
                opts.forEach(function(o) {
                    var li = document.createElement('li');
                    li.className = 'ilbb-select-opt';
                    li.setAttribute('role', 'option');
                    li.setAttribute('data-value', o[0]);
                    li.setAttribute('data-search', o[1]);
                    li.setAttribute('aria-selected', 'false');
                    var liMain = document.createElement('span');
                    liMain.className = 'ilbb-select-opt-main';
                    liMain.textContent = o[1];
                    var liTick = document.createElement('span');
                    liTick.className = 'ilbb-select-tick';
                    liTick.textContent = '✓';
                    li.appendChild(liMain);
                    li.appendChild(liTick);
                    selMenu.appendChild(li);
                });

                selBox.appendChild(sel);
                selBox.appendChild(selBtn);
                selBox.appendChild(selMenu);

                var inp = document.createElement('input');
                inp.type = 'text'; inp.className = 'slot-text'; inp.placeholder = '按钮文字';

                var up = document.createElement('label');
                up.className = 'slot-upload';
                var fi = document.createElement('input');
                fi.type = 'file'; fi.accept = 'image/*';
                Object.assign(fi.style, { display: 'none' });
                var lbl = document.createElement('span');
                lbl.className = 'slot-upload-label'; lbl.textContent = '上传图片';
                up.appendChild(fi); up.appendChild(lbl);

                slot.appendChild(selBox);
                slot.appendChild(inp);
                slot.appendChild(up);

                slotState[idx] = { type: 'text', text: '', icon: '' };

                function syncUI() {
                    var typ = sel.value;
                    slotState[idx].type = typ;
                    if (typ === 'image') {
                        inp.style.display = 'none';
                    } else {
                        inp.style.display = '';
                    }
                    if (typ === 'text') {
                        up.style.display = 'none';
                    } else {
                        up.style.display = '';
                        Object.assign(inp.style, typ === 'icon_text' ? {} : {});
                    }
                }

                sel.addEventListener('change', function() {
                    syncUI();
                    slotUpdate();
                });
                inp.addEventListener('input', function() {
                    slotState[idx].text = inp.value;
                    slotUpdate();
                });
                fi.addEventListener('change', function() {
                    var file = fi.files[0];
                    if (!file) return;
                    var rd = new FileReader();
                    rd.onload = function(e) {
                        slotState[idx].icon = e.target.result.split(',')[1];
                        lbl.textContent = '已上传';
                        slotUpdate();
                    };
                    rd.readAsDataURL(file);
                });

                btnSlotGrid.appendChild(slot);
                syncUI();
            })(i);
        }
        // 槽位是动态生成的，渲染完统一初始化里面的自定义下拉
        if (window.ilbbInit) window.ilbbInit(btnSlotGrid);
    }

    function slotUpdate() {
        // 由 input 事件触发，但只记录数据，不自动合成
    }

    // 构建按钮 payload（按模式）
    function buildButtonsPayload() {
        if (currentMode === 'single') {
            var t = btnTextInput.value.trim() || '配对';
            return [{ type: 'text', text: t }];
        }
        var arr = [];
        for (var i = 0; i < slotState.length; i++) {
            var s = slotState[i];
            if (s.type === 'text') {
                if (s.text) arr.push({ type: 'text', text: s.text });
            } else if (s.type === 'icon_text') {
                if (s.text && s.icon) arr.push({ type: 'icon_text', text: s.text, icon: s.icon });
                else if (s.text) arr.push({ type: 'text', text: s.text });
                else if (s.icon) arr.push({ type: 'image', text: '', icon: s.icon });
            } else if (s.type === 'image') {
                if (s.icon) arr.push({ type: 'image', text: '', icon: s.icon });
            }
            if (arr.length >= 4) break;
        }
        return arr.length ? arr : [{ type: 'text', text: '配对' }];
    }

    // 按钮模式切换
    btnModeButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            btnModeButtons.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentMode = btn.getAttribute('data-mode');
            btnSingle.style.display = currentMode === 'single' ? '' : 'none';
            btnMulti.classList.toggle('hidden', currentMode !== 'multi');
        });
    });

    // ===== 更新缓存状态 =====
    async function updateCacheStatus() {
        try {
            var response = await fetch('/api/cache_status');
            var data = await response.json();
            cacheBadge.textContent = '缓存: ' + data.count;
        } catch (e) {
            console.error('获取缓存状态失败', e);
        }
    }
    updateCacheStatus();

    // 原生 confirm() 在预览 / 内嵌 iframe 里会被静默拦截并直接返回 false，
    // 表现为「点了按钮没反应」。优先用 plugins.js 提供的页面内确认框，
    // 实在取不到（脚本没加载）才退回原生实现。
    function askConfirm(opts) {
        if (typeof window.uiConfirm === 'function') return window.uiConfirm(opts);
        return Promise.resolve(window.confirm(opts.text || '确定继续？'));
    }

    // ===== 清空缓存 =====
    clearCacheBtn.addEventListener('click', async function() {
        var yes = await askConfirm({
            title: '清空缓存',
            text: '确定要清空所有缓存图片吗？',
            tip: '清空后图片会在下次用到时重新下载',
            okText: '清空'
        });
        if (!yes) return;
        try {
            var response = await fetch('/api/clear_cache', { method: 'POST' });
            var data = await response.json();
            if (data.success) {
                showToast('缓存已清空');
                updateCacheStatus();
            } else {
                showToast('清空失败: ' + data.message);
            }
        } catch (e) {
            showToast('请求失败');
        }
    });

    // ===== 输入限制 =====
    qqInput.addEventListener('input', function() {
        this.value = this.value.replace(/\D/g, '');
    });

    // ===== 模板切换 =====
    tplItems.forEach(function(btn) {
        btn.addEventListener('click', function() {
            tplItems.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            currentTemplate = btn.getAttribute('data-key');
            try {
                var cols = JSON.parse(btn.getAttribute('data-colors') || '[]');
                setGradientType();
                if (cols.length >= 2) {
                    gColor1.value = cols[0];
                    gColor2.value = cols[1];
                }
            } catch (e) {}
        });
    });

    // ===== 背景类型切换 =====
    bgTypeButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            bgTypeButtons.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            var type = btn.getAttribute('data-bgtype');
            Object.keys(bgEditors).forEach(function(k) {
                bgEditors[k].classList.toggle('hidden', k !== type);
            });
        });
    });

    // 渐变方向
    bgDirButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            bgDirButtons.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
        });
    });

    // 背景上传
    bgImageInput.addEventListener('change', function() {
        var file = bgImageInput.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function(e) {
            currentBg = { data: e.target.result.split(',')[1], name: file.name };
            var kb = Math.round(file.size / 1024);
            bgUploadLabel.textContent = file.name.slice(0, 12) + ' (' + kb + 'KB)';
        };
        reader.readAsDataURL(file);
    });

    function setGradientType() {
        bgTypeButtons.forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-bgtype') === 'gradient');
        });
        Object.keys(bgEditors).forEach(function(k) {
            bgEditors[k].classList.toggle('hidden', k !== 'gradient');
        });
    }

    // 构建背景配置
    function buildBgConfig() {
        var type = 'gradient';
        var activeType = bgTypeButtons.find(function(b) { return b.classList.contains('active'); });
        if (activeType) type = activeType.getAttribute('data-bgtype');

        var cfg = { type: type, blur: 0 };
        if (type === 'gradient') {
            var dir = 'vertical';
            var activeDir = bgDirButtons.find(function(b) { return b.classList.contains('active'); });
            if (activeDir) dir = activeDir.getAttribute('data-dir');
            cfg.colors = [gColor1.value, gColor2.value];
            cfg.direction = dir;
        } else if (type === 'color') {
            cfg.color = solidColor.value;
        } else if (type === 'image') {
            if (currentBg && currentBg.data) {
                cfg.image = currentBg.data;
            } else {
                return { type: 'gradient', blur: 0, colors: [gColor1.value, gColor2.value], direction: 'vertical' };
            }
        }
        return cfg;
    }

    // ===== 构建完整文字 =====
    function buildFullText(name) {
        var part1 = textPart1.value || '';
        var part2 = textPart2.value || '';
        return part1 + name + part2;
    }

    // ===== 获取用户信息 =====
    fetchBtn.addEventListener('click', fetchUserInfo);
    qqInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') fetchUserInfo();
    });

    async function fetchUserInfo() {
        var qq = qqInput.value.trim();
        if (!qq || !qq.match(/^\d{5,11}$/)) {
            showToast('请输入5-11位有效QQ号');
            return;
        }

        fetchBtn.disabled = true;
        fetchBtn.innerHTML = '加载中...';
        loadingBar.classList.remove('hidden');
        downloadBtn.classList.add('hidden');
        userInfoPreview.classList.add('hidden');
        cacheStatusRow.style.display = 'none';
        filenameRow.style.display = 'none';
        previewImageContainer.style.display = 'none';
        placeholder.style.display = 'block';
        downloadUrl = null;

        try {
            var response = await fetch('/api/get_user_info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ qq: qq })
            });

            var data = await response.json();

            if (data.error) {
                showToast(data.error);
                return;
            }

            currentData = data;
            window.__avatar = data.avatar;   // 供 Meme 表情视图复用头像
            window.__qq = data.qq;

            previewQQ.textContent = data.qq;
            previewName.textContent = data.name;
            userInfoPreview.classList.remove('hidden');

            var fullText = buildFullText(data.name);

            await generateImage(data, fullText);

        } catch (error) {
            console.error(error);
            showToast('网络错误，请重试');
        } finally {
            fetchBtn.disabled = false;
            fetchBtn.innerHTML = '获取信息并生成';
            loadingBar.classList.add('hidden');
        }
    }

    // ===== 生成图片 =====
    async function generateImage(data, titleText) {
        try {
            var font = fontSelect.value || 'default';
            var bgConfig = buildBgConfig();
            var buttons = buildButtonsPayload();
            var response = await fetch('/api/generate_image', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    qq: data.qq,
                    name: data.name,
                    avatar: data.avatar,
                    text: titleText,
                    btn_text: '配对',
                    font: font,
                    template: currentTemplate,
                    bg: bgConfig,
                    buttons: buttons
                })
            });

            var result = await response.json();
            if (result.download_url) {
                downloadUrl = result.download_url;
                currentFilename = result.filename || '配对.png';
                downloadBtn.classList.remove('hidden');

                if (result.preview_url) {
                    previewImage.src = result.preview_url + '?t=' + Date.now();
                    previewImage.setAttribute('draggable', 'true');
                    previewImage.setAttribute('data-fname', result.filename || currentFilename || '配对.png');
                    previewImage.classList.add('draggable-img');
                    previewImageContainer.style.display = 'block';
                    placeholder.style.display = 'none';
                    // iPhone 式 Q弹弹出动画
                    previewImage.classList.remove('generated');
                    void previewImage.offsetWidth;
                    previewImage.classList.add('generated');
                }

                if (result.cached) {
                    previewCache.textContent = '已缓存';
                    previewCache.style.color = '#34c759';
                } else {
                    previewCache.textContent = '新生成';
                    previewCache.style.color = '#2d7aff';
                }
                cacheStatusRow.style.display = 'flex';

                previewFilename.textContent = currentFilename;
                filenameRow.style.display = 'flex';

                updateCacheStatus();
            }
        } catch (error) {
            console.error(error);
            showToast('生成图片失败');
        }
    }

    // ===== 下载 =====
    downloadBtn.addEventListener('click', function() {
        if (downloadUrl && currentFilename) {
            var encodedFilename = encodeURIComponent(currentFilename);
            window.location.href = downloadUrl + '?filename=' + encodedFilename;
            this.textContent = '已下载';
            setTimeout(function() {
                downloadBtn.textContent = '下载图片';
            }, 2000);
        }
    });

    // ===== Toast =====
    function showToast(message) {
        var existing = document.querySelector('.toast');
        if (existing) existing.remove();

        var toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = message;
        document.body.appendChild(toast);

        requestAnimationFrame(function() {
            toast.classList.add('show');
        });

        setTimeout(function() {
            toast.classList.remove('show');
            setTimeout(function() { toast.remove(); }, 400);
        }, 2500);
    }

    renderSlots();
});
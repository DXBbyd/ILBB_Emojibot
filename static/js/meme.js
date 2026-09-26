document.addEventListener('DOMContentLoaded', function() {
    var memeList = document.getElementById('memeList');
    var memeSearch = document.getElementById('memeSearch');
    var memeSelKey = document.getElementById('memeSelKey');
    var memeSelDesc = document.getElementById('memeSelDesc');
    var memeForm = document.getElementById('memeForm');
    var memeGenerateBtn = document.getElementById('memeGenerateBtn');
    var memeLoading = document.getElementById('memeLoading');
    var memeResult = document.getElementById('memeResult');
    var memeResultImg = document.getElementById('memeResultImg');
    var memeDownloadLink = document.getElementById('memeDownloadLink');
    var memeFillAvatar = document.getElementById('memeFillAvatar');
    var memeQQ = document.getElementById('memeQQ');
    var memeFetchQQ = document.getElementById('memeFetchQQ');
    var memeQQStatus = document.getElementById('memeQQStatus');

    var allMemes = [];
    var memeHint = '';     // 表情库为空时后端给出的原因
    var selected = null;   // {item, imagesDataURL[], texts[], args[]}
    var filterType = 'all';   // all | img | text

    function showToast(msg) {
        var e = document.querySelector('.toast');
        if (e) e.remove();
        var t = document.createElement('div');
        t.className = 'toast';
        t.textContent = msg;
        document.body.appendChild(t);
        requestAnimationFrame(function() { t.classList.add('show'); });
        setTimeout(function() { t.classList.remove('show'); setTimeout(function() { t.remove(); }, 400); }, 2500);
    }

    // ===== 视图切换 =====
    var switches = Array.prototype.slice.call(document.querySelectorAll('.view-switch'));
    switches.forEach(function(btn) {
        btn.addEventListener('click', function() {
            switches.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            var target = btn.getAttribute('data-view');
            var views = document.querySelectorAll('.view');
            views.forEach(function(v) { v.classList.toggle('active', v.id === 'view-' + target); });
        });
    });

    // ===== 加载表情列表 =====
    async function loadMemes() {
        memeList.innerHTML = '<div style="color:#b0b4c0;padding:12px;">加载中...</div>';
        try {
            var res = await fetch('/api/meme/list');
            var data = await res.json();
            if (!data.ok) { memeList.innerHTML = '<div style="color:#e05555;padding:12px;">加载失败: ' + (data.error || '') + '</div>'; return; }
            allMemes = data.items;
            memeHint = data.hint || '';
            renderList('');
        } catch (e) {
            memeList.innerHTML = '<div style="color:#e05555;padding:12px;">加载失败</div>';
        }
    }

    function renderList(q) {
        var qq = (q || '').trim().toLowerCase();
        var items = allMemes.filter(function(m) {
            if (filterType === 'img' && m.max_images === 0) return false;
            if (filterType === 'text' && m.max_images > 0) return false;
            var hay = m.key + ' ' + (m.keywords || []).join(' ') + ' ' + (m.tags || []).join(' ');
            if (qq && hay.toLowerCase().indexOf(qq) === -1) return false;
            return true;
        });
        memeList.innerHTML = '';
        if (!items.length) {
            // 一条都没有多半不是「搜不到」，而是表情库没加载出来，把原因说清楚
            var tip = (allMemes.length && q) ? '没有匹配的表情' : (memeHint || '没有匹配的表情');
            memeList.innerHTML = '<div style="color:#b0b4c0;padding:12px;line-height:1.6;">' + esc(tip) + '</div>';
            return;
        }
        items.forEach(function(m) {
            var row = document.createElement('button');
            row.type = 'button';
            row.className = 'meme-item';
            var zh = (m.keywords && m.keywords[0]) || m.key;
            row.innerHTML = '<span class="meme-item-key">' + esc(zh) + ' <i>|</i> <em>' + esc(m.key) + '</em></span>' +
                '<span class="meme-item-meta">图 ' + m.min_images + '~' + m.max_images +
                (m.min_texts ? ' · 文 ' + m.min_texts + '~' + m.max_texts : '') + '</span>';
            if (selected && selected.item.key === m.key) row.classList.add('active');
            (function(m) {
                row.addEventListener('click', function() { selectMeme(m); });
            })(m);
            memeList.appendChild(row);
        });
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    // 写进 HTML 属性（data-value / value）时还得把双引号也转掉
    function escAttr(s) {
        return esc(s).replace(/"/g, '&quot;');
    }

    memeSearch.addEventListener('input', function() { renderList(memeSearch.value); });

    // ===== 选择表情，渲染表单 =====
    function selectMeme(item) {
        selected = { item: item, imagesDataURL: [], texts: [], args: {} };
        memeSelKey.textContent = item.key;
        memeSelDesc.textContent = ['图' + item.min_images + '~' + item.max_images + '张',
                                   item.min_texts ? ('文本' + item.min_texts + '~' + item.max_texts + '条') : '无需文本'
                                  ].join('  ·  ');
        renderForm(item);
        var rows = memeList.querySelectorAll('.meme-item');
        rows.forEach(function(r) {
            r.classList.toggle('active', r.querySelector('.meme-item-key').textContent === item.key);
        });
        memeResult.classList.add('hidden');
    }

    function textTypeLabel(t) {
        return t === 'text' ? '文字' : (t === 'int' ? '整数' : (t === 'float' ? '数字' : '开关'));
    }

    function renderForm(item) {
        var html = '';
        // 图片槽
        if (item.max_images > 0) {
            var show = Math.min(item.max_images, 6);
            html += '<div class="form-group"><label>图片（需 ' + item.min_images + '~' + item.max_images + ' 张）</label><div class="meme-imgslots">';
            for (var i = 0; i < show; i++) {
                html += '<div class="meme-imgslot">' +
                        '<label class="meme-uploader">' +
                        '<input type="file" accept="image/*" data-idx="' + i + '" style="display:none">' +
                        '<span class="meme-imgph" data-ph="' + i + '">第' + (i + 1) + '张<br>点击上传</span>' +
                        '<img class="meme-imgthumb" data-thumb="' + i + '" alt="img" style="display:none">' +
                        '</label>' +
                        '<button type="button" class="meme-fillone" data-idx="' + i + '">填QQ头像</button>' +
                        '</div>';
            }
            html += '</div><div style="font-size:12px;color:#b0b4c0;margin-top:6px;">点框上传图片；多图时每个槽下方的「填QQ头像」只填充对应槽位，不会全填</div></div>';
        }
        // 文本槽
        if (item.max_texts > 0) {
            // 文本框数量 = 全部所需 max_texts，避免 some meme 需要 7+ 条文本时填不满
            var tn = item.max_texts;
            var dt = item.default_texts || [];
            var inputs = '<div class="form-group"><label>文本（需 ' + item.min_texts + '~' + item.max_texts + ' 条）</label>';
            for (var ti = 0; ti < tn; ti++) {
                var val = dt[ti] || '';
                inputs += '<input type="text" class="meme-text" data-idx="' + ti + '" placeholder="文本' + (ti + 1) + '" value="' + val + '">';
            }
            html += inputs + '</div>';
        }
        // 选项
        if (item.options && item.options.length) {
            html += '<div class="form-group"><label>选项</label>';
            item.options.forEach(function(o, oi) {
                var glued = o.default == null ? '' : String(o.default);
                var optId = 'meme_opt_' + oi;   // 每个选项控件的 id（ILBB 下拉靠它认隐藏 input）
                // 布尔开关：渲染为拨杆式 toggle（meme-switch）而非裸复选框；data-type="bool" 供 collectOpts 读取并提交 true/false（避免误报 "on"）。
                if (o.type === 'bool') {
                    var _on = glued === 'True' || glued === 'true';
                    html += '<label class="meme-opt-row"><span>' + esc(o.name) + '</span><span class="meme-switch">' +
                        '<input type="checkbox" class="meme-opt" data-name="' + esc(o.name) + '" data-type="bool"' + (_on ? ' checked' : '') + '>' +
                        '<span class="track"></span></span></label>';
                } else if (o.type === 'int' && o.min != null && o.max != null) {
                    // 变体选择器（如举牌编号）：ILBB 自定义下拉，第一项“随机/自动”对应默认值（通常 0）
                    var men = '<li class="ilbb-select-opt" role="option" data-value="' + escAttr(glued) +
                        '" data-search="随机/自动(' + escAttr(glued) + ')" aria-selected="false">' +
                        '<span class="ilbb-select-opt-main">随机/自动(' + esc(glued) + ')</span>' +
                        '<span class="ilbb-select-opt-code">' + esc(glued) + '</span>' +
                        '<span class="ilbb-select-tick">✓</span></li>';
                    for (var vv = o.min; vv <= o.max; vv++) {
                        men += '<li class="ilbb-select-opt" role="option" data-value="' + vv +
                            '" data-search="' + vv + '" aria-selected="false">' +
                            '<span class="ilbb-select-opt-main">' + vv + '</span>' +
                            '<span class="ilbb-select-opt-code">' + vv + '</span>' +
                            '<span class="ilbb-select-tick">✓</span></li>';
                    }
                    html += '<div class="meme-opt-row"><span>' + esc(o.name) + '</span>' +
                        '<div class="ilbb-select" data-select="meme_int" data-target="' + optId + '">' +
                        '<input type="hidden" class="meme-opt" id="' + optId + '"' +
                        ' data-name="' + escAttr(o.name) + '" data-type="int" value="' + escAttr(glued) + '">' +
                        '<button type="button" class="ilbb-select-btn" aria-haspopup="listbox" aria-expanded="false">' +
                        '<span class="ilbb-select-text">请选择</span><span class="ilbb-select-caret"></span></button>' +
                        '<ul class="ilbb-select-menu" role="listbox">' + men + '</ul></div></div>';
                } else if (o.type === 'int') {
                    html += '<div class="meme-opt-row"><span>' + o.name + '</span><input type="number" step="1" class="meme-opt" data-name="' + o.name + '" data-type="' + o.type + '" value="' + glued + '"></div>';
                } else if (o.type === 'float') {
                    html += '<div class="meme-opt-row"><span>' + o.name + '</span><input type="number" step="0.1" class="meme-opt" data-name="' + o.name + '" data-type="' + o.type + '" value="' + glued + '"></div>';
                } else if (o.type === 'choose') {
                    var cs = (o.choices || []).slice();
                    if (glued !== '' && cs.indexOf(glued) < 0) cs.unshift(glued);
                    // ILBB 自定义下拉（同主页那套），真实值写进隐藏 input 供 collectOpts 读
                    var men2 = cs.map(function(c) {
                        return '<li class="ilbb-select-opt" role="option" data-value="' + escAttr(c) +
                            '" data-search="' + escAttr(c) + '" aria-selected="false">' +
                            '<span class="ilbb-select-opt-main">' + esc(c) + '</span>' +
                            '<span class="ilbb-select-tick">✓</span></li>';
                    }).join('');
                    html += '<div class="meme-opt-row"><span>' + esc(o.name) + '</span>' +
                        '<div class="ilbb-select" data-select="meme_choose" data-target="' + optId + '">' +
                        '<input type="hidden" class="meme-opt" id="' + optId + '"' +
                        ' data-name="' + escAttr(o.name) + '" data-type="choose" value="' + escAttr(glued) + '">' +
                        '<button type="button" class="ilbb-select-btn" aria-haspopup="listbox" aria-expanded="false">' +
                        '<span class="ilbb-select-text">请选择</span><span class="ilbb-select-caret"></span></button>' +
                        '<ul class="ilbb-select-menu" role="listbox">' + men2 + '</ul></div></div>';
                } else {
                    html += '<div class="meme-opt-row"><span>' + o.name + '</span><input type="text" class="meme-opt" data-name="' + o.name + '" data-type="text" value="' + glued + '"></div>';
                }
            });
            html += '</div>';
        }
        memeForm.innerHTML = html || '<div style="color:#b0b4c0;padding:8px;">该表情无需额外参数，点击生成即可</div>';

        // 样式预览：对带 choose 或 变体int 选项的 meme，逐选项列出每个可选值的预览小图
        if (item.options && item.options.length) {
            var styleCount = 0;
            var sb = '';
            item.options.forEach(function(o) {
                var vals = null;
                if (o.type === 'choose' && o.choices && o.choices.length) vals = o.choices;
                else if (o.type === 'int' && o.min != null && o.max != null) {
                    vals = []; for (var vv = o.min; vv <= o.max; vv++) vals.push(String(vv));
                }
                if (!vals) return;
                sb += '<div class="meme-style-group"><span class="meme-style-opt">' + esc(o.name) + '</span><div class="meme-style-row">';
                vals.forEach(function(c) {
                    var q = {}; q[o.name] = c;
                    var url = '/api/meme/preview/' + encodeURIComponent(item.key) + '?args=' + encodeURIComponent(JSON.stringify(q));
                    sb += '<figure class="meme-style" data-name="' + esc(o.name) + '" data-val="' + esc(c) + '" title="选择' + esc(o.name) + '=' + esc(c) + '">' +
                          '<img loading="lazy" src="' + url + '"><figcaption>' + esc(c) + '</figcaption></figure>';
                    styleCount++;
                });
                sb += '</div></div>';
            });
            if (styleCount) {
                memeForm.insertAdjacentHTML('beforeend',
                    '<div class="form-group meme-styles"><label>样式预览（实时生成，点击选用）</label>' + sb +
                    '<div class="meme-styles-hint">点击某张小图可直接选用该样式；正式生成以上方选项为准</div></div>');
                // 点击样式图 → 把对应选项控件切到该值
                memeForm.querySelectorAll('.meme-style').forEach(function(fig) {
                    fig.addEventListener('click', function() {
                        var name = fig.getAttribute('data-name');
                        var val = fig.getAttribute('data-val');
                        var ctl = memeForm.querySelector('.meme-opt[data-name="' + name + '"]');
                        if (!ctl) return;
                        ctl.value = val;
                        // 自定义下拉：改的是隐藏 input，得同步一下按钮上的显示文字
                        if (window.ILBBSelect && window.ILBBSelect.sync) window.ILBBSelect.sync(memeForm);
                        collectOpts();
                        var act = memeForm.querySelector('.meme-style.active');
                        if (act) act.classList.remove('active');
                        fig.classList.add('active');
                    });
                });
            }
        }

        // 绑定图片上传
        memeForm.querySelectorAll('.meme-imgslot input[type=file]').forEach(function(inp) {
            inp.addEventListener('change', function() {
                var file = inp.files[0];
                if (!file) return;
                var rd = new FileReader();
                rd.onload = function(e) {
                    var idx = parseInt(inp.getAttribute('data-idx'), 10);
                    selected.imagesDataURL[idx] = e.target.result;
                    setSlot(idx, e.target.result);
                };
                rd.readAsDataURL(file);
            });
        });
        // 每个图片槽的“填QQ头像”：只填充对应槽位
        memeForm.querySelectorAll('.meme-fillone').forEach(function(btn) {
            btn.addEventListener('click', function() {
                if (!window.__avatar) { showToast('请先在左上方输入QQ号并点「获取头像」'); return; }
                var idx = parseInt(btn.getAttribute('data-idx'), 10);
                var dataURL = 'data:image/jpeg;base64,' + window.__avatar;
                selected.imagesDataURL[idx] = dataURL;
                setSlot(idx, dataURL);
                showToast('已用QQ头像填充第 ' + (idx + 1) + ' 个图片位');
            });
        });
        memeForm.querySelectorAll('.meme-text').forEach(function(inp) {
            inp.addEventListener('input', function() {
                var idx = parseInt(inp.getAttribute('data-idx'), 10);
                selected.texts[idx] = inp.value;
            });
            selected.texts[parseInt(inp.getAttribute('data-idx'), 10)] = inp.value;
        });
        memeForm.querySelectorAll('.meme-opt').forEach(function(c) {
            c.addEventListener('change', collectOpts);
            c.addEventListener('input', collectOpts);
        });
        // 接管本表单里刚渲染出来的 ILBB 自定义下拉（按钮文案 / 选中态同步）
        if (window.ilbbInit) window.ilbbInit(memeForm);
        collectOpts();
    }

    function setSlot(idx, dataURL) {
        var ph = memeForm.querySelector('.meme-imgph[data-ph="' + idx + '"]');
        var th = memeForm.querySelector('.meme-imgthumb[data-thumb="' + idx + '"]');
        if (ph) ph.style.display = 'none';
        if (th) { th.src = dataURL; th.style.display = 'block'; }
    }

    function collectOpts() {
        var out = {};
        memeForm.querySelectorAll('.meme-opt').forEach(function(c) {
            var name = c.getAttribute('data-name');
            var type = c.getAttribute('data-type');
            if (type === 'bool') out[name] = c.checked;
            else out[name] = c.value;
        });
        selected.args = out;
    }

    // ===== 全局 QQ 号（Meme 选项卡独立获取，无需先到配对卡） =====
    memeFetchQQ.addEventListener('click', async function() {
        var qq = (memeQQ.value || '').trim();
        if (!qq || !/^\d{5,11}$/.test(qq)) { showToast('请输入5-11位有效QQ号'); return; }
        memeQQStatus.classList.remove('hidden');
        memeQQStatus.textContent = '正在获取...';
        memeQQStatus.style.color = '#8c8f9c';
        try {
            var res = await fetch('/api/get_user_info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ qq: qq })
            });
            var data = await res.json();
            if (data.error) {
                memeQQStatus.textContent = '获取失败：' + data.error;
                memeQQStatus.style.color = '#e05555';
                return;
            }
            window.__avatar = data.avatar;
            window.__qq = data.qq;
            window.__qqName = data.name || data.qq;
            memeQQStatus.textContent = '已获取 ' + (data.name || data.qq) + ' 的头像，可用「填入QQ头像」';
            memeQQStatus.style.color = '#34c759';
        } catch (e) {
            memeQQStatus.textContent = '网络错误，请重试';
            memeQQStatus.style.color = '#e05555';
        }
    });

    // ===== 条件过滤 =====
    var filterButtons = Array.prototype.slice.call(document.querySelectorAll('.meme-filter'));
    filterButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            filterButtons.forEach(function(b) { b.classList.remove('active'); });
            btn.classList.add('active');
            filterType = btn.getAttribute('data-ft');
            renderList(memeSearch.value);
        });
    });

    // 一键填入QQ头像（只填空位，不覆盖已上传）
    memeFillAvatar.addEventListener('click', function() {
        if (!window.__avatar) { showToast('请先在左上方输入QQ号并点「获取头像」'); return; }
        if (!selected) { showToast('请先选择一个表情'); return; }
        if (!selected.item.max_images) { showToast('该表情不需要图片'); return; }
        var filled = 0;
        for (var i = 0; i < selected.item.max_images; i++) {
            if (selected.imagesDataURL[i]) continue; // 已有（上传）则不覆盖
            var dataURL = 'data:image/jpeg;base64,' + window.__avatar;
            selected.imagesDataURL[i] = dataURL;
            setSlot(i, dataURL);
            filled++;
        }
        showToast(filled ? ('已用QQ头像填充 ' + filled + ' 个空图片位') : '已有上传图片，未覆盖');
    });

    // ===== 生成 =====
    memeGenerateBtn.addEventListener('click', async function() {
        if (!selected) { showToast('请先选择一个表情'); return; }
        var item = selected.item;
        var nImages = selected.imagesDataURL.filter(Boolean).length;
        var texts = (selected.texts || []).filter(function(t) { return t && String(t).trim() !== ''; });
        if (nImages < item.min_images) {
            showToast('至少需要 ' + item.min_images + ' 张图片');
            return;
        }
        if (texts.length < item.min_texts) {
            showToast('至少需要 ' + item.min_texts + ' 条文本');
            return;
        }

        memeGenerateBtn.disabled = true;
        memeLoading.classList.remove('hidden');
        memeResult.classList.add('hidden');
        try {
            // base64 字符集不含逗号，去掉 data:...;base64, 前缀后可直接用逗号分隔，
            // 服务端按逗号切分即得到每张图的纯 base64（data URL 里的逗号不会再破坏切分）
            const toRaw = function(src) { var i = src.indexOf(','); return i >= 0 ? src.slice(i + 1) : src; };
            var rawImgs = (selected.imagesDataURL.filter(Boolean) || []).map(toRaw);
            var fd = new FormData();
            fd.append('key', item.key);
            fd.append('images_b64', rawImgs.join(','));
            fd.append('texts', JSON.stringify(texts));
            var args = selected.args || {};
            fd.append('args', JSON.stringify(args));

            var res = await fetch('/api/meme/generate', { method: 'POST', body: fd });
            if (!res.ok) {
                var ejson = null;
                try { ejson = await res.json(); } catch (e) {}
                showToast((ejson && ejson.error) || ('生成失败 (' + res.status + ')'));
                return;
            }
            var blob = await res.blob();
            var url = URL.createObjectURL(blob);
            var isGif = blob.type.indexOf('gif') !== -1 || (blob.size >= 6 && blob[0] === 0x47);
            memeResultImg.src = url;
            memeResultImg.setAttribute('draggable', 'true');
            memeResultImg.classList.add('draggable-img');
            var fname = item.key + (isGif ? '.gif' : '.png');
            memeResultImg.setAttribute('data-fname', fname);
            // 触发 iPhone 式 Q弹弹出动画：每次生成都重新播放
            memeResultImg.classList.remove('generated');
            void memeResultImg.offsetWidth; // 强制 reflow 让动画能重新触发
            memeResultImg.classList.add('generated');
            memeDownloadLink.href = url;
            memeDownloadLink.setAttribute('download', fname);
            memeDownloadLink.textContent = '下载 ' + fname;
            memeResult.classList.remove('hidden');
        } catch (e) {
            showToast('生成失败: ' + e.message);
        } finally {
            memeGenerateBtn.disabled = false;
            memeLoading.classList.add('hidden');
        }
    });

    loadMemes();
});
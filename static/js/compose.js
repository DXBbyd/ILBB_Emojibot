/* ============================================================
 * 合成大类（Compose）—— 子选项切换：Meme 表情 / 配对卡 / 名言图
 * 复用 WS 页的 .ws-tabs 滑块组件（复刻 ws.js 的 movePill / switchPane）
 * ============================================================ */
document.addEventListener('DOMContentLoaded', function() {
    var tabsWrap = document.getElementById('composeTabs');
    var pill = document.getElementById('composeTabsPill');
    var hint = document.getElementById('composeTabsHint');

    var PANES = {
        meme: 'composePaneMeme',
        pair: 'composePanePair',
        quote: 'composePaneQuote'
    };
    var HINTS = {
        meme: '表情合成 · 配对生图 · 名言图',
        pair: '表情合成 · 配对生图 · 名言图',
        quote: '随机背景 · 灰蒙版 · 全模糊托盘 · 署名'
    };

    if (!tabsWrap || !pill) return;

    function tabEls() {
        return Array.prototype.slice.call(tabsWrap.querySelectorAll('.ws-tab'));
    }

    // 滑块跟随选中项移动（视图隐藏时量不到尺寸 → 直接跳过，等可见后再定位）
    function movePill(instant) {
        var act = tabsWrap.querySelector('.ws-tab.active');
        if (!act) return;
        var r = act.getBoundingClientRect();
        var b = tabsWrap.getBoundingClientRect();
        if (!r.width) return;
        var bl = parseFloat(getComputedStyle(tabsWrap).borderLeftWidth) || 0;
        var x = (r.left - b.left) - bl;
        if (instant) pill.style.transition = 'none';
        pill.style.width = r.width + 'px';
        pill.style.transform = 'translateX(' + x + 'px)';
        if (instant) { void pill.offsetWidth; pill.style.transition = ''; }
    }

    function switchPane(name) {
        if (!PANES[name]) name = 'meme';
        tabEls().forEach(function(b) {
            b.classList.toggle('active', b.getAttribute('data-compose-tab') === name);
        });
        Object.keys(PANES).forEach(function(k) {
            var p = document.getElementById(PANES[k]);
            if (p) p.classList.toggle('active', k === name);
        });
        if (hint) hint.textContent = HINTS[name] || HINTS.meme;
        movePill();
        // 切换后通知各子面板（让懒加载/重绘的模块有机会刷新）
        try {
            document.dispatchEvent(new CustomEvent('compose:pane', { detail: { pane: name } }));
        } catch (e) { /* 老浏览器忽略 */ }
    }

    tabEls().forEach(function(btn) {
        btn.addEventListener('click', function() {
            switchPane(btn.getAttribute('data-compose-tab'));
        });
    });

    // 工具栏切到「合成」时重新定位滑块（此时视图才可见）
    Array.prototype.slice.call(document.querySelectorAll('.view-switch')).forEach(function(btn) {
        btn.addEventListener('click', function() {
            if (btn.getAttribute('data-view') !== 'compose') return;
            requestAnimationFrame(function() { movePill(true); });
        });
    });

    var rt = null;
    window.addEventListener('resize', function() {
        clearTimeout(rt);
        rt = setTimeout(function() { movePill(true); }, 120);
    });

    // 首屏：默认 Meme 面板
    switchPane('meme');
    requestAnimationFrame(function() { movePill(true); });

    // 供其它模块（如插件页 / 机器人指令页）复用
    window.ILBBCompose = { switch: switchPane, move: movePill };
});

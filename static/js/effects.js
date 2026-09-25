/* effects.js — 全局鼠标拖尾 & 点击反馈（覆盖整个 WebUI）
 * 拖尾：跟随鼠标的彩色渐变圆点，随时间缩小淡出。
 * 点击：按下的位置扩散一个蓝色涟漪。
 * 纯 Canvas 覆盖层，pointer-events:none，不拦截任何交互。
 */
(function () {
    'use strict';

    function makeLayer(className) {
        var d = document.createElement('div');
        d.className = className;
        document.body.appendChild(d);
        return d;
    }

    // ---------- 拖尾 ----------
    var trail = makeLayer('trail-layer');
    var tcv = document.createElement('canvas');
    tcv.style.position = 'absolute'; tcv.style.left = '0'; tcv.style.top = '0';
    trail.appendChild(tcv);
    var tctx = tcv.getContext('2d');
    var dots = [];
    var lastPos = { x: -99, y: -99 };
    var lastSpawn = 0;
    var TRAIL_LIFE = 26;          // 帧寿命
    var SPAWN_GAP = 18;           // 相邻两点最小间距(px)

    function resizeTrail() {
        tcv.width = window.innerWidth; tcv.height = window.innerHeight;
        tcv.style.width = tcv.width + 'px'; tcv.style.height = tcv.height + 'px';
    }
    window.addEventListener('resize', resizeTrail);
    resizeTrail();

    document.addEventListener('mousemove', function (ev) {
        var dx = ev.clientX - lastPos.x, dy = ev.clientY - lastPos.y;
        if (Math.hypot(dx, dy) < SPAWN_GAP && dots.length) { lastPos.x = ev.clientX; lastPos.y = ev.clientY; return; }
        lastPos.x = ev.clientX; lastPos.y = ev.clientY;
        dots.push({ x: ev.clientX, y: ev.clientY, life: TRAIL_LIFE, hue: (lastSpawn * 26) % 360 });
        lastSpawn++;
    });

    function trailTick() {
        tctx.clearRect(0, 0, tcv.width, tcv.height);
        for (var i = dots.length - 1; i >= 0; i--) {
            var d = dots[i];
            d.life--;
            if (d.life <= 0) { dots.splice(i, 1); continue; }
            var p = 1 - d.life / TRAIL_LIFE;         // 0 → 1
            var r = 10 * (1 - p * 0.7);
            var a = (1 - p) * 0.55;
            tctx.beginPath();
            tctx.arc(d.x, d.y, r, 0, Math.PI * 2);
            tctx.fillStyle = 'hsla(' + d.hue + ', 85%, 58%, ' + a.toFixed(3) + ')';
            tctx.fill();
        }
        requestAnimationFrame(trailTick);
    }
    requestAnimationFrame(trailTick);

    // ---------- 点击反馈 ----------
    var clickLayer = makeLayer('click-layer');
    var ccv = document.createElement('canvas');
    ccv.style.position = 'absolute'; ccv.style.left = '0'; ccv.style.top = '0';
    clickLayer.appendChild(ccv);
    var cctx = ccv.getContext('2d');
    var ripples = [];

    function resizeClick() {
        ccv.width = window.innerWidth; ccv.height = window.innerHeight;
        ccv.style.width = ccv.width + 'px'; ccv.style.height = ccv.height + 'px';
    }
    window.addEventListener('resize', resizeClick);
    resizeClick();

    document.addEventListener('pointerdown', function (ev) {
        ripples.push({ x: ev.clientX, y: ev.clientY, p: 0, max: 26 });
    });

    function clickTick() {
        cctx.clearRect(0, 0, ccv.width, ccv.height);
        for (var i = ripples.length - 1; i >= 0; i--) {
            var r = ripples[i];
            r.p++;
            if (r.p > r.max) { ripples.splice(i, 1); continue; }
            var t = r.p / r.max;
            var rad = 6 + t * 34;
            var a = (1 - t) * 0.5;
            cctx.beginPath();
            cctx.arc(r.x, r.y, rad, 0, Math.PI * 2);
            cctx.strokeStyle = 'rgba(45, 122, 255, ' + a.toFixed(3) + ')';
            cctx.lineWidth = 2.2 * (1 - t) + 0.5;
            cctx.stroke();
        }
        requestAnimationFrame(clickTick);
    }
    requestAnimationFrame(clickTick);

    // ---------- 图片可拖拽为附件（QQ 等外部应用识别） ----------
    // 生成图片默认是 blob:/同源 URL，浏览器拖拽不携带图片数据，QQ 无法接收。
    // 这里在拖拽开始前把图片字节抓取成 data URL 并作为文件写入 DataTransfer，
    // 使其可被拖入 QQ 聊天框 / 桌面等。
    function blobToDataURL(blob, cb) {
        var r = new FileReader();
        r.onload = function () { cb(r.result); };
        r.readAsDataURL(blob);
    }
    // data URL → Blob
    function dataURLToBlob(dataUrl) {
        var parts = dataUrl.split(',');
        var mime = (parts[0].match(/data:([^;]+)/) || [])[1] || 'image/png';
        var bin = atob(parts[1]);
        var arr = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        return new Blob([arr], { type: mime });
    }

    // 缓存已抓取的 data URL，避免重复请求
    var dragCache = {};
    document.addEventListener('dragstart', function (ev) {
        var t = ev.target;
        if (!t || !(t.tagName === 'IMG') || !t.classList.contains('draggable-img')) return;
        ev.preventDefault(); // 先阻止默认，自行写入完整数据
        var img = t;
        var src = img.src;
        var name = (img.getAttribute('data-fname')) || extractName(src) || 'image.png';

        function send(dataUrl) {
            var blob = dataURLToBlob(dataUrl);
            var file = new File([blob], name, { type: blob.type });
            // 设置拖拽数据：文本 / URI / 文件 都提供，最大化 QQ 兼容
            var dt = ev.dataTransfer;
            dt.setData('text/uri-list', dataUrl);
            dt.setData('text/plain', dataUrl);
            dt.setData('DownloadURL', blob.type + ':' + name + ':' + dataUrl);
            // 附加为文件
            try { dt.items.add(file); } catch (e) {}
        }

        if (dragCache[src]) { send(dragCache[src]); return; }

        // 优先 fetch 真实字节（blob URL / 同源 URL 均可）
        fetch(src).then(function (r) { return r.blob(); }).then(function (blob) {
            blobToDataURL(blob, function (dataUrl) {
                dragCache[src] = dataUrl;
                send(dataUrl);
            });
        }).catch(function () {
            // fallback：src 本身是 data URL
            if (src.indexOf('data:') === 0) { dragCache[src] = src; send(src); }
        });
    });

    function extractName(src) {
        if (src.indexOf('data:') === 0) return 'image.png';
        var m = src.match(/\/([^\/?#]+)\.(png|jpe?g|gif|webp)/i);
        return m ? m[1] + '.' + m[2] : 'image.png';
    }
})();
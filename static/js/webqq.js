/* ============================================================================
   ILBB · WebQQ
   真实 QQ 好友 / 群会话：联系人、收发消息、官方表情、@群友、引用回复、
   图片、戳一戳、群成员，以及图片预览缩放。
   依赖后端 /api/webqq/*（见 app.py + core/webqq.py）。
   ========================================================================== */
(function () {
    'use strict';

    var root = document.getElementById('view-webqq');
    if (!root) { return; }

    // ---------------------------------------------------------------- 元素
    var el = {
        meAvatar: document.getElementById('wqMeAvatar'),
        meName: document.getElementById('wqMeName'),
        net: document.getElementById('wqNet'),
        sideTitle: document.getElementById('wqSideTitle'),
        refresh: document.getElementById('wqRefreshBtn'),
        search: document.getElementById('wqSearch'),
        tabs: document.getElementById('wqTabs'),
        contacts: document.getElementById('wqContacts'),
        recentCount: document.getElementById('wqRecentCount'),
        friendCount: document.getElementById('wqFriendCount'),
        groupCount: document.getElementById('wqGroupCount'),
        peerAvatar: document.getElementById('wqPeerAvatar'),
        peerName: document.getElementById('wqPeerName'),
        peerSub: document.getElementById('wqPeerSub'),
        syncBtn: document.getElementById('wqSyncBtn'),
        pokeBtn: document.getElementById('wqPokeBtn'),
        memberBtn: document.getElementById('wqMemberBtn'),
        groupBtn: document.getElementById('wqGroupBtn'),
        groupPanel: document.getElementById('wqGroupPanel'),
        groupClose: document.getElementById('wqGroupClose'),
        groupRole: document.getElementById('wqGroupRole'),
        noticeList: document.getElementById('wqNoticeList'),
        noticeRefresh: document.getElementById('wqNoticeRefresh'),
        noticeForm: document.getElementById('wqNoticeForm'),
        noticeReadonly: document.getElementById('wqNoticeReadonly'),
        noticePinned: document.getElementById('wqNoticePinned'),
        noticeNewMember: document.getElementById('wqNoticeNewMember'),
        noticeImageBtn: document.getElementById('wqNoticeImageBtn'),
        noticeImage: document.getElementById('wqNoticeImage'),
        noticeThumb: document.getElementById('wqNoticeThumb'),
        noticeThumbImg: document.getElementById('wqNoticeThumbImg'),
        noticeImgClear: document.getElementById('wqNoticeImgClear'),
        noticeInput: document.getElementById('wqNoticeInput'),
        noticeSend: document.getElementById('wqNoticeSend'),
        noticeTip: document.getElementById('wqNoticeTip'),
        fwdPanel: document.getElementById('wqFwdPanel'),
        fwdTitle: document.getElementById('wqFwdTitle'),
        fwdClose: document.getElementById('wqFwdClose'),
        fwdSearch: document.getElementById('wqFwdSearch'),
        fwdList: document.getElementById('wqFwdList'),
        stream: document.getElementById('wqStream'),
        replyBar: document.getElementById('wqReplyBar'),
        replyName: document.getElementById('wqReplyName'),
        replyText: document.getElementById('wqReplyText'),
        replyClose: document.getElementById('wqReplyClose'),
        attach: document.getElementById('wqAttach'),
        emojiBtn: document.getElementById('wqEmojiBtn'),
        imageBtn: document.getElementById('wqImageBtn'),
        atBtn: document.getElementById('wqAtBtn'),
        input: document.getElementById('wqInput'),
        tip: document.getElementById('wqTip'),
        send: document.getElementById('wqSendBtn'),
        file: document.getElementById('wqFile'),
        emojiPanel: document.getElementById('wqEmojiPanel'),
        emojiGrid: document.getElementById('wqEmojiGrid'),
        emojiClose: document.getElementById('wqEmojiClose'),
        atPanel: document.getElementById('wqAtPanel'),
        atList: document.getElementById('wqAtList'),
        atClose: document.getElementById('wqAtClose'),
        members: document.getElementById('wqMembers'),
        membersClose: document.getElementById('wqMembersClose'),
        memberCount: document.getElementById('wqMemberCount'),
        memberSearch: document.getElementById('wqMemberSearch'),
        memberList: document.getElementById('wqMemberList'),
        viewer: document.getElementById('wqViewer'),
        viewerImg: document.getElementById('wqViewerImg'),
        viewerPct: document.getElementById('wqViewerPct'),
        viewerIn: document.getElementById('wqViewerIn'),
        viewerOut: document.getElementById('wqViewerOut'),
        viewerReset: document.getElementById('wqViewerReset'),
        viewerClose: document.getElementById('wqViewerClose'),
        noticeCount: document.getElementById('wqNoticeCount'),
        navNotice: document.getElementById('wqNavNotice'),
        menu: document.getElementById('wqMenu'),
        multiBar: document.getElementById('wqMultiBar'),
        multiInfo: document.getElementById('wqMultiInfo'),
        cmdBtn: document.getElementById('wqCmdBtn'),
        cmdPanel: document.getElementById('wqCmdPanel'),
        cmdList: document.getElementById('wqCmdList'),
        cmdClose: document.getElementById('wqCmdClose')
    };
    if (!el.stream || !el.input) { return; }

    // ---------------------------------------------------------------- 工具
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function escRe(s) {
        return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    function token() { return 'wq-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8); }
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function chatKey(type, id) { return (type === 'group' ? 'group:' : 'private:') + String(id); }
    function keyParts(key) {
        var i = String(key).indexOf(':');
        return { type: key.slice(0, i) === 'group' ? 'group' : 'private', id: key.slice(i + 1) };
    }
    function avatarFor(type, id) {
        return '/api/ws/avatar?type=' + (type === 'group' ? 'group' : 'user') +
            '&id=' + encodeURIComponent(id) + '&s=100';
    }
    function fmtClock(t) {
        var d = new Date((t || 0) * 1000);
        if (!t) { return ''; }
        var p = function (x) { return (x < 10 ? '0' : '') + x; };
        return p(d.getHours()) + ':' + p(d.getMinutes());
    }
    function dayKey(t) { return new Date((t || 0) * 1000).toDateString(); }
    function dayLabel(t) {
        var d = new Date((t || 0) * 1000), n = new Date();
        var zero = new Date(n.getFullYear(), n.getMonth(), n.getDate());
        var one = new Date(zero.getTime() - 86400000);
        if (d >= zero) { return '今天'; }
        if (d >= one) { return '昨天'; }
        return (d.getMonth() + 1) + '月' + d.getDate() + '日';
    }
    function fmtShort(t) {
        if (!t) { return ''; }
        var d = new Date(t * 1000), n = new Date();
        if (d.toDateString() === n.toDateString()) { return fmtClock(t); }
        var zero = new Date(n.getFullYear(), n.getMonth(), n.getDate());
        if (d >= new Date(zero.getTime() - 86400000)) { return '昨天'; }
        return (d.getMonth() + 1) + '/' + d.getDate();
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

    // ---------------------------------------------------------------- 官方表情
    // 新版 QQ（QQNT）的表情编号和 qzone 图床编号不是同一套：老代码直接拼
    // e{id}.gif，144 之后的表情就会张冠李戴（264 是「捂脸」，qzone 的 e264.gif
    // 却是另一张脸，正确图号是 10264）。所以图片和名称统一交给后端：
    //   GET /api/webqq/faces        → [{id, name}]
    //   GET /api/webqq/face?id=xxx  → 该表情的图片（后端带映射和本地缓存）
    // 下面这张表只保留「id → 近似 Unicode」，用于把用户手打的 emoji 还原成 face 段，
    // 以及图片加载失败时退回文字；表情名以后端清单为准。
    var FACES = [
        [0, '😮', '惊讶'], [1, '😒', '撇嘴'], [2, '😍', '色'], [3, '😠', '发怒'],
        [4, '😎', '得意'], [5, '😭', '流泪'], [6, '😊', '害羞'], [7, '🤐', '闭嘴'],
        [8, '😴', '睡'], [9, '😭', '大哭'], [10, '😅', '尴尬'], [11, '😡', '发怒'],
        [12, '😜', '调皮'], [13, '😁', '呲牙'], [14, '🙂', '微笑'], [15, '🙁', '难过'],
        [16, '😎', '酷'], [17, '😫', '抓狂'], [18, '🤮', '吐'], [19, '🤭', '偷笑'],
        [20, '😊', '可爱'], [21, '🙄', '白眼'], [22, '😤', '傲慢'], [23, '😋', '饥饿'],
        [24, '😪', '困'], [25, '😱', '惊恐'], [26, '😓', '流汗'], [27, '😄', '憨笑'],
        [28, '😅', '大兵'], [29, '😤', '奋斗'], [30, '🤬', '咒骂'], [31, '🤔', '疑问'],
        [32, '🤫', '嘘'], [33, '😵', '晕'], [34, '😖', '折磨'], [35, '😞', '衰'],
        [36, '💀', '骷髅'], [37, '🔨', '敲打'], [38, '👋', '再见'], [39, '😅', '擦汗'],
        [40, '😏', '抠鼻'], [41, '👏', '鼓掌'], [42, '😳', '糗大了'], [43, '😏', '坏笑'],
        [44, '😤', '左哼哼'], [45, '😤', '右哼哼'], [46, '🥱', '哈欠'], [47, '😒', '鄙视'],
        [48, '🥺', '委屈'], [49, '🥹', '快哭了'], [50, '😏', '阴险'], [51, '😘', '亲亲'],
        [52, '😨', '吓'], [53, '🥺', '可怜'], [54, '🔪', '菜刀'], [55, '🍉', '西瓜'],
        [56, '🍺', '啤酒'], [57, '🏀', '篮球'], [58, '🏓', '乒乓'], [59, '☕', '咖啡'],
        [60, '🍚', '饭'], [61, '🐷', '猪头'], [62, '🌹', '玫瑰'], [63, '🥀', '凋谢'],
        [64, '😘', '示爱'], [65, '❤️', '爱心'], [66, '💔', '心碎'], [67, '🎂', '蛋糕'],
        [68, '⚡', '闪电'], [69, '💣', '炸弹'], [70, '🔪', '刀'], [71, '⚽', '足球'],
        [72, '🐞', '瓢虫'], [73, '💩', '便便'], [74, '🌙', '月亮'], [75, '☀️', '太阳'],
        [76, '🎁', '礼物'], [77, '🤗', '拥抱'], [78, '👍', '强'], [79, '👎', '弱'],
        [80, '🤝', '握手'], [81, '✌️', '胜利'], [82, '🙏', '抱拳'], [83, '😉', '勾引'],
        [84, '👊', '拳头'], [85, '👎', '差劲'], [86, '😍', '爱你'], [87, '🙅', 'NO'],
        [88, '👌', 'OK'], [89, '💑', '爱情'], [90, '😘', '飞吻'], [91, '🕺', '跳跳'],
        [92, '🥶', '发抖'], [93, '😡', '怄火'], [94, '🌀', '转圈'], [95, '🙇', '磕头'],
        [96, '🔙', '回头'], [97, '🤸', '跳绳'], [98, '👋', '挥手'], [99, '🤩', '激动'],
        [100, '🕺', '街舞'], [101, '😘', '献吻'], [102, '☯️', '左太极'], [103, '☯️', '右太极'],
        [104, '🎊', '双喜'], [105, '🧨', '鞭炮'], [106, '🏮', '灯笼'], [107, '💰', '发财'],
        [108, '🎤', 'K歌'], [109, '🛍️', '购物'], [110, '✉️', '邮件'], [111, '😎', '帅'],
        [112, '🥤', '喝水'], [113, '🎎', '囍'], [114, '🧣', '围脖'], [115, '😄', '快乐'],
        [116, '🎤', '唱K'], [117, '👋', '招手'], [118, '👀', '偷看'], [119, '🙌', '万岁'],
        [120, '🦸', '奥特曼'], [121, '😋', '美滋滋'], [122, '🥵', '大忙人'], [123, '💪', '一起加油'],
        [124, '💡', '好主意'], [125, '🙏', '求求了'], [126, '🫡', '敬礼'], [127, '🍋', '我酸了'],
        [128, '😡', '生气'], [129, '🎉', '恭喜'], [130, '🙏', '感谢'], [131, '🤔', '疑问'],
        [132, '👋', '打脸'], [133, '😠', '恨'], [134, '👏', '鼓掌'], [135, '😂', '笑哭'],
        [136, '😷', '口罩'], [137, '💪', '加油'], [138, '🙄', '白眼'], [139, '🥺', '委屈'],
        [140, '😏', '抠鼻'], [141, '🥱', '哈欠'], [142, '😴', '困'], [143, '😠', '发怒'],
        [144, '😲', '惊讶']
    ];
    var FACE_BY_CHAR = {}, FACE_CHAR_BY_ID = {};
    var FACE_NAME_BY_ID = {}, FACE_ID_BY_NAME = {}, FACE_LIST = [], FACES_LOADED = false;

    FACES.forEach(function (f) {
        FACE_CHAR_BY_ID[String(f[0])] = f[1];
        if (!FACE_BY_CHAR[f[1]]) { FACE_BY_CHAR[f[1]] = String(f[0]); }
    });

    function faceName(id) {
        return FACE_NAME_BY_ID[String(id)] || '';
    }

    function faceUrl(id) {
        return '/api/webqq/face?id=' + encodeURIComponent(String(id));
    }

    // 表情清单：一次拉取后缓存，图片按 id 走 /api/webqq/face（后端带映射 + 本地缓存）
    function loadFaces() {
        if (FACES_LOADED) { return Promise.resolve(); }
        return api('/api/webqq/faces').then(function (j) {
            FACE_LIST = (j.items || []).filter(function (it) {
                return it && /^\d+$/.test(String(it.id));
            });
            FACE_LIST.forEach(function (it) {
                var id = String(it.id);
                FACE_NAME_BY_ID[id] = it.name || ('#' + id);
                if (!FACE_ID_BY_NAME[it.name]) { FACE_ID_BY_NAME[it.name] = id; }
            });
            FACES_LOADED = true;
            renderEmojiGrid();
        }).catch(function () { FACES_LOADED = true; });
    }

    // 消息里的图片同样可能来自 QQ 图床（gchat.qpic.cn 等），走代理规避防盗链
    function imgSrc(u, d) {
        u = String(u || '');
        d = d || {};
        var link = /^https?:\/\//i.test(u) ? u : '';
        // 有的实现只给 file_id / 消息 id、不给 url，这种也要走后端让 NapCat 现取。
        if (!link && !(d.file_id || d.file || d.mid)) { return u; }
        // file / file_id / mid 都是给后端刷新过期 url 用的：
        // QQ 图片的 rkey 只有约 2 小时有效，过期后只能让 NapCat 重新给地址。
        var qs = [];
        if (link) { qs.push('u=' + encodeURIComponent(link)); }
        if (d.file) { qs.push('file=' + encodeURIComponent(d.file)); }
        if (d.file_id) { qs.push('fid=' + encodeURIComponent(d.file_id)); }
        if (d.mid) { qs.push('mid=' + encodeURIComponent(d.mid)); }
        return '/api/webqq/img?' + qs.join('&');
    }

    // 视频 / 语音走流式代理（支持 Range，能拖进度条）；QQ 的媒体地址常带时效签名，
    // 浏览器直接引用多半 403，所以一律经后端代取。
    function rawSrc(u, d) {
        u = String(u || '');
        d = d || {};
        var link = /^https?:\/\//i.test(u) ? u : '';
        // 地址可能过期，甚至完全没给 url；带上 file/file_id/mid 让后端现取
        if (!link && !(d.file_id || d.file || d.mid)) { return u; }
        var qs = [];
        if (link) { qs.push('u=' + encodeURIComponent(link)); }
        if (d.file) { qs.push('file=' + encodeURIComponent(d.file)); }
        if (d.file_id) { qs.push('fid=' + encodeURIComponent(d.file_id)); }
        if (d.mid) { qs.push('mid=' + encodeURIComponent(d.mid)); }
        return '/api/webqq/raw?' + qs.join('&');
    }

    // 代理失败（图床 404 / 签名过期）时兜底直连原地址：
    // 页面已声明 no-referrer，直连 qpic 这类 CDN 通常反而能出图。
    document.addEventListener('error', function (e) {
        var n = e.target;
        if (!n || !n.getAttribute) { return; }
        var fb = n.getAttribute('data-fb');
        if (!fb || n.getAttribute('data-fb-used') === '1') { return; }
        n.setAttribute('data-fb-used', '1');
        n.src = fb;
        if (/^(VIDEO|AUDIO)$/.test(n.tagName || '')) {
            try { n.load(); } catch (x) { /* 忽略 */ }
        }
    }, true);

    // ---------------------------------------------------------------- 状态
    var state = {
        loaded: false,
        online: false,
        me: { id: '', name: '', avatar: '' },
        friends: [],
        groups: [],
        previews: {},
        members: {},
        current: null,
        messages: [],
        lastSeq: 0,
        unread: {},
        replyTo: null,
        attachments: [],
        atPicks: [],
        faceTokens: [],
        tab: 'recent',
        filter: '',
        pollTimer: null,
        polling: false,
        busy: false,
        memberFilter: '',
        notices: [],
        noticeLastId: 0,
        noticePending: 0,
        selecting: false,
        selected: {},
        roles: {},                      // gid -> {role, can_manage, label}
        noticeImageData: '',            // 待发布的公告配图（dataURL）
        prefix: '/',                    // 机器人指令前缀（bootstrap 里回填）
        fwd: null                       // 待转发的消息 {msgs, mode}
    };

    function contactOf(type, id) {
        var list = type === 'group' ? state.groups : state.friends;
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].id) === String(id)) { return list[i]; }
        }
        return null;
    }
    function metaOf(type, id) {
        var c = contactOf(type, id);
        if (c) { return c; }
        var key = chatKey(type, id);
        return {
            type: type, id: String(id), name: String(id),
            avatar: avatarFor(type, id), member_count: 0,
            _fromHistory: true, _key: key
        };
    }
    function isGroup() { return state.current && state.current.type === 'group'; }

    // ---------------------------------------------------------------- 联系人栏
    function unreadOf(key) { return state.unread[key] || 0; }

    function contactRow(type, id, preview) {
        var meta = metaOf(type, id);
        var key = chatKey(type, id);
        if (state.current && state.current.key === key) {
            // 当前会话不再显示未读
        }
        var sub;
        if (preview) {
            sub = (preview.self ? '我: ' : '') + (preview.text || '');
            if (preview.kind === 'system') { sub = preview.text || ''; }
        } else if (type === 'group') {
            sub = '群号 ' + id + (meta.member_count ? ' · ' + meta.member_count + ' 人' : '');
        } else {
            sub = 'QQ ' + id;
        }
        var n = unreadOf(key);
        return '<div class="wq-contact' + (state.current && state.current.key === key ? ' active' : '') +
            '" data-type="' + type + '" data-id="' + esc(id) + '" data-key="' + esc(key) + '">' +
            '<img class="wq-contact-avatar" src="' + esc(meta.avatar) + '" alt="" loading="lazy">' +
            '<div class="wq-contact-main">' +
                '<div class="wq-contact-name">' + esc(meta.name) + '</div>' +
                '<div class="wq-contact-sub">' + esc(sub) + '</div>' +
            '</div>' +
            '<div class="wq-contact-meta">' +
                '<span class="wq-contact-time">' + esc(preview ? fmtShort(preview.time) : '') + '</span>' +
                (n ? '<span class="wq-badge">' + (n > 99 ? '99+' : n) + '</span>' : '') +
            '</div>' +
        '</div>';
    }

    function renderContacts() {
        var top = el.contacts.scrollTop;
        var items = [];
        var q = state.filter.trim().toLowerCase();

        if (state.tab === 'notices') {
            renderNotices(q);
            el.contacts.scrollTop = top;
            el.recentCount.textContent = Object.keys(state.previews).length;
            el.friendCount.textContent = state.friends.length;
            el.groupCount.textContent = state.groups.length;
            return;
        }

        if (state.tab === 'recent') {
            Object.keys(state.previews).forEach(function (key) {
                var p = state.previews[key];
                var kp = keyParts(key);
                var meta = metaOf(kp.type, kp.id);
                if (q && meta.name.toLowerCase().indexOf(q) < 0 && String(kp.id).indexOf(q) < 0) { return; }
                items.push({ key: key, type: kp.type, id: kp.id, preview: p, time: p.time || 0 });
            });
            items.sort(function (a, b) { return b.time - a.time; });
        } else {
            var list = state.tab === 'groups' ? state.groups : state.friends;
            list.forEach(function (c) {
                if (q && c.name.toLowerCase().indexOf(q) < 0 && String(c.id).indexOf(q) < 0) { return; }
                items.push({ key: chatKey(c.type, c.id), type: c.type, id: c.id,
                             preview: state.previews[chatKey(c.type, c.id)] });
            });
        }

        if (!items.length) {
            el.contacts.innerHTML = '<div class="wq-empty">' +
                (q ? '没有匹配的联系人' :
                    (state.tab === 'recent'
                        ? '还没有会话消息<br>去「好友」或「群聊」里选一个开始聊天'
                        : (state.online ? '列表为空' : '尚未读取到联系人<br>请确认 NapCat 已连接'))) +
                '</div>';
        } else {
            el.contacts.innerHTML = items.map(function (it) {
                return contactRow(it.type, it.id, it.preview);
            }).join('');
        }
        el.contacts.scrollTop = top;
        el.recentCount.textContent = Object.keys(state.previews).length;
        el.friendCount.textContent = state.friends.length;
        el.groupCount.textContent = state.groups.length;
    }

    // ---------------------------------------------------------------- 通知中心
    var NOTICE_TAG = {
        group_increase: '加群', group_decrease: '退群', group_admin: '管理',
        friend_add: '好友', friend_request: '申请', group_request: '申请'
    };

    function noticeRow(n) {
        var tag = NOTICE_TAG[n.kind] || '通知';
        var danger = n.kind === 'group_decrease';
        var pending = (n.kind === 'friend_request' || n.kind === 'group_request') &&
            !n.handled;
        var actions = '';
        if (pending) {
            var kind = n.kind === 'group_request' ? 'group' : 'friend';
            actions = '<div class="wq-notice-actions">' +
                '<button type="button" data-approve="1" data-flag="' + esc(n.flag) +
                    '" data-kind="' + kind + '">同意</button>' +
                '<button type="button" class="ghost" data-approve="0" data-flag="' +
                    esc(n.flag) + '" data-kind="' + kind + '">拒绝</button>' +
            '</div>';
        } else if (n.handled) {
            actions = '<div class="wq-notice-done">' +
                (n.approved ? '已同意' : '已拒绝') + '</div>';
        }
        var isGroup = n.chat_type === 'group' || n.gid;
        var gname = n.gname || (n.gid ? ('群 ' + n.gid) : '');
        var title = isGroup ? (gname || n.chat_id || '') :
            (n.kind === 'friend_add' || n.kind === 'friend_request' ?
                '好友通知' : '通知');
        var av = isGroup ? avatarFor('group', n.gid || n.chat_id) :
            avatarFor('user', n.uid || n.chat_id);
        var operator = n.operator || '';
        if (!operator) {
            if (n.kind === 'friend_add' || n.kind === 'friend_request') {
                operator = n.name || n.uid || '本人';
            } else if (n.kind === 'group_decrease') {
                operator = '本人（主动退出）';
            } else if (n.kind === 'group_increase') {
                operator = '本人（自主入群）';
            } else {
                operator = n.name || n.uid || '—';
            }
        }
        // 不在通知里做「点一下跳转到群」：这里只交代群名、发生了什么、操作者是谁
        return '<div class="wq-notice">' +
            '<div class="wq-notice-head">' +
                '<img class="wq-notice-av" src="' + esc(av) + '" alt="" loading="lazy">' +
                '<span class="wq-notice-title">' + esc(title) + '</span>' +
                '<span class="wq-notice-tag' + (danger ? ' danger' : '') + '">' +
                    esc(tag) + '</span>' +
                '<span class="wq-notice-time">' + esc(fmtShort(n.time)) + '</span>' +
            '</div>' +
            '<div class="wq-notice-event">' + esc(n.text || '') + '</div>' +
            '<div class="wq-notice-op">操作者：' + esc(operator) + '</div>' +
            actions +
        '</div>';
    }

    function renderNotices(q) {
        var items = (state.notices || []).slice().reverse();
        if (q) {
            items = items.filter(function (n) {
                return ((n.text || '') + ' ' + (n.name || '') + ' ' + (n.gname || ''))
                    .toLowerCase().indexOf(q) >= 0;
            });
        }
        if (!items.length) {
            el.contacts.innerHTML = '<div class="wq-empty">' +
                (q ? '没有匹配的通知'
                   : '暂无通知<br>加群 / 退群 / 好友申请会显示在这里') + '</div>';
            return;
        }
        el.contacts.innerHTML = items.map(noticeRow).join('');
    }

    function updateNoticeBadge() {
        var n = state.noticePending || 0;
        if (el.noticeCount) { el.noticeCount.textContent = n; }
        if (el.navNotice) {
            el.navNotice.textContent = n > 99 ? '99+' : n;
            el.navNotice.classList.toggle('hidden', !n);
        }
    }

    function mergeNotices(items) {
        if (!items || !items.length) { return 0; }
        var ids = {};
        state.notices.forEach(function (n) { ids[n.id] = 1; });
        var added = 0;
        items.forEach(function (n) {
            if (!ids[n.id]) { state.notices.push(n); added++; }
        });
        if (state.notices.length > 80) {
            state.notices = state.notices.slice(-80);
        }
        return added;
    }

    function applyMemberChange(n) {
        // 管理员变更 / 进退群 → 成员列表和「我的身份」立刻失效，重新拉一次
        var gid = String(n.gid || (n.chat_type === 'group' ? n.chat_id : '') || '');
        if (!gid) { return; }
        delete state.members[gid];
        delete state.roles[gid];
        if (!state.current || state.current.type !== 'group' ||
                String(state.current.id) !== gid) { return; }
        loadRole(gid, true).then(function () {
            if (!state.current || String(state.current.id) !== gid) { return; }
            if (el.groupPanel && !el.groupPanel.classList.contains('hidden')) {
                var r = state.roles[gid] || {};
                el.groupRole.textContent = r.ok ? (r.label || '') : '';
                el.groupRole.className = 'wq-role ' + (r.ok ? String(r.role || '') : '');
            }
            renderHeader();
        });
        if (!el.members.classList.contains('hidden')) {
            loadMembers(gid, true, function () {
                renderMembers();
                renderHeader();
            });
        }
    }

    function pullNotices() {
        var since = state.noticeLastId;
        api('/api/webqq/notices?since=' + since).then(function (j) {
            var items = j.items || [];
            var added = mergeNotices(items);
            state.noticeLastId = Math.max(state.noticeLastId, j.seq || 0);
            state.noticePending = j.pending || 0;
            updateNoticeBadge();
            items.forEach(function (n) {
                if (n && /^group_(admin|increase|decrease)$/.test(n.kind || '')) {
                    applyMemberChange(n);
                }
            });
            if (added) {
                if (state.tab === 'notices') {
                    renderNotices(state.filter.trim().toLowerCase());
                }
                var last = items[items.length - 1];
                if (last) { toast(last.text || '收到一条通知'); }
            }
        }).catch(function () {});
    }

    function approveNotice(btn) {
        var flag = btn.getAttribute('data-flag');
        var kind = btn.getAttribute('data-kind') || 'friend';
        var ok = btn.getAttribute('data-approve') === '1';
        btn.disabled = true;
        api('/api/webqq/request', {
            method: 'POST',
            body: JSON.stringify({ kind: kind, flag: flag, approve: ok })
        }).then(function () {
            toast(ok ? '已同意申请' : '已拒绝申请');
            load(true);
        }).catch(function (e) {
            btn.disabled = false;
            toast('处理失败：' + e.message, true);
        });
    }

    function setTab(tab) {
        state.tab = tab;
        Array.prototype.forEach.call(el.tabs.querySelectorAll('button'), function (b) {
            b.classList.toggle('active', b.getAttribute('data-wq-tab') === tab);
        });
        Array.prototype.forEach.call(root.querySelectorAll('.wq-rail-btn'), function (b) {
            var nav = b.getAttribute('data-wq-nav');
            var on = (tab === 'recent' && nav === 'recent') ||
                (tab === 'friends' && nav === 'friends') ||
                (tab === 'groups' && nav === 'groups') ||
                (tab === 'notices' && nav === 'notices');
            b.classList.toggle('active', on);
        });
        el.sideTitle.textContent = tab === 'recent' ? '消息' :
            (tab === 'friends' ? '好友' : (tab === 'groups' ? '群聊' : '通知'));
        renderContacts();
    }

    // ---------------------------------------------------------------- 聊天头部
    function updateMe() {
        var av = state.me.avatar || '/static/favicon.jpg';
        el.meAvatar.src = av;
        el.meAvatar.onerror = function () { this.onerror = null; this.src = '/static/favicon.jpg'; };
        el.meName.textContent = state.me.name || '未登录';
        el.meName.title = state.me.id ? ('QQ ' + state.me.id) : '';
    }
    function updateNet(err) {
        el.net.className = 'wq-net ' + (state.online ? 'ok' : 'bad');
        var txt = el.net.querySelector('span');
        if (txt) { txt.textContent = state.online ? '在线' : '未连接'; }
        el.net.title = err || (state.online ? 'NapCat 已连接' : 'NapCat 未连接');
    }
    function headerSub() {
        if (!state.current) { return '从左侧选择一个好友或群开始聊天'; }
        if (!state.online) { return 'NapCat 未连接 · 请到「WS 服务器」页连接'; }
        if (state.current.type === 'group') {
            var n = (state.members[state.current.id] || []).length ||
                (state.current.member_count || 0);
            return '群号 ' + state.current.id + (n ? ' · ' + n + ' 名成员' : '');
        }
        return 'QQ ' + state.current.id;
    }
    function renderHeader() {
        if (state.current) {
            el.peerName.textContent = state.current.name || state.current.id;
            el.peerAvatar.src = state.current.avatar || '/static/favicon.jpg';
            el.memberBtn.classList.toggle('hidden', state.current.type !== 'group');
            el.groupBtn.classList.toggle('hidden', state.current.type !== 'group');
            el.atBtn.classList.toggle('hidden', state.current.type !== 'group');
            el.pokeBtn.disabled = false;
            if (el.syncBtn) { el.syncBtn.disabled = false; }
        } else {
            el.peerName.textContent = 'WebQQ';
            el.peerAvatar.src = '/static/favicon.jpg';
            el.memberBtn.classList.add('hidden');
            el.groupBtn.classList.add('hidden');
            el.atBtn.classList.add('hidden');
            el.pokeBtn.disabled = true;
            if (el.syncBtn) { el.syncBtn.disabled = true; }
        }
        el.peerAvatar.onerror = function () { this.onerror = null; this.src = '/static/favicon.jpg'; };
        el.peerSub.textContent = headerSub();
    }

    // ---------------------------------------------------------------- 消息渲染
    function avatarOf(it) {
        if (it.self) { return state.me.avatar || '/static/favicon.jpg'; }
        return avatarFor('user', (it.sender && it.sender.id) || '');
    }

    function msgSummary(it) {
        if (!it) { return ''; }
        if (it.kind === 'system') { return it.text || ''; }
        var t = String(it.text || '').trim();
        if (t) { return t; }
        var segs = it.segs || [];
        for (var i = 0; i < segs.length; i++) {
            var s = segs[i];
            if (s.type === 'image') { return '[图片]'; }
            if (s.type === 'face') { return '[表情]'; }
            if (s.type === 'record') { return '[语音]'; }
            if (s.type === 'video') { return '[视频]'; }
            if (s.type === 'file') { return '[文件]'; }
        }
        return '';
    }

    function findMsg(mid) {
        if (!mid) { return null; }
        for (var i = 0; i < state.messages.length; i++) {
            if (String(state.messages[i].mid) === String(mid)) { return state.messages[i]; }
        }
        return null;
    }

    function quoteHtml(rid) {
        var q = findMsg(rid);
        var name = q ? ((q.sender && q.sender.name) || (q.self ? '我' : '')) : '';
        var text = q ? msgSummary(q) : '消息内容不可见';
        return '<div class="wq-quote">' +
            '<span class="wq-quote-name">' + esc(name || '回复') + '</span>' +
            '<span class="wq-quote-text">' + esc(text || '...') + '</span>' +
            '</div>';
    }

    var ICO_FILE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';
    var ICO_FORWARD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h16M4 18h10"/><path d="M17 16l3 2-3 2"/></svg>';

    function forwardNodeHtml(n) {
        var segs = (n && n.segs) || [];
        var body = segs.length ? segs.map(segHtml).join('') : esc((n && n.text) || '');
        return '<div class="wq-fwd-item">' +
            '<div class="wq-fwd-meta"><span class="wq-fwd-name">' + esc((n && n.name) || '未知') +
            '</span>' + (n && n.time ? '<span>' + esc(fmtShort(n.time)) + '</span>' : '') +
            '</div><div class="wq-fwd-text">' + body + '</div></div>';
    }

    function forwardHtml(d) {
        var nodes = d.nodes || [];
        var count = d.count || nodes.length;
        var body = nodes.length ? nodes.map(forwardNodeHtml).join('') :
            '<div class="wq-fwd-empty">点开加载聊天记录…</div>';
        return '<div class="wq-forward" data-fid="' + esc(d.id || '') +
            '" data-mid="' + esc(d.mid || '') + '"' +
            (nodes.length ? ' data-loaded="1"' : '') + '>' +
            '<div class="wq-forward-head"><span class="wq-forward-ico">' + ICO_FORWARD + '</span>' +
            '<b>聊天记录</b><span class="wq-forward-count">' +
            esc(count ? count + ' 条' : '点击查看') + '</span>' +
            '<span class="wq-forward-caret"></span></div>' +
            '<div class="wq-forward-body">' + body + '</div></div>';
    }

    function loadForward(card) {
        var body = card.querySelector('.wq-forward-body');
        var fid = card.getAttribute('data-fid') || '';
        var mid = card.getAttribute('data-mid') || '';
        if (!fid && !mid) {
            body.innerHTML = '<div class="wq-fwd-empty">这条聊天记录没有可读取的 id</div>';
            card.setAttribute('data-loaded', '1');
            return;
        }
        body.innerHTML = '<div class="wq-fwd-empty"><span class="wq-spin"></span>正在读取聊天记录…</div>';
        api('/api/webqq/forward?id=' + encodeURIComponent(fid) +
            '&mid=' + encodeURIComponent(mid)).then(function (j) {
            var nodes = j.nodes || [];
            body.innerHTML = nodes.length ? nodes.map(forwardNodeHtml).join('') :
                '<div class="wq-fwd-empty">聊天记录是空的</div>';
            card.setAttribute('data-loaded', '1');
        }).catch(function (err) {
            body.innerHTML = '<div class="wq-fwd-empty">读取失败：' + esc(err.message) + '</div>';
        });
    }

    function toggleForward(card) {
        if (card.getAttribute('data-loaded') === '1') {
            card.classList.toggle('open');
            return;
        }
        card.classList.add('open');
        loadForward(card);
    }

    function segHtml(seg) {
        var t = seg.type, d = seg.data || {};
        if (t === 'text') {
            return '<span class="wq-seg-text">' + esc(d.text) + '</span>';
        }
        if (t === 'at') {
            var nm = d.qq === 'all' ? '全体成员' : (d.name || d.qq);
            return '<span class="wq-seg-at">@' + esc(nm) + '</span>';
        }
        if (t === 'face') {
            var fid = String(d.id == null ? '' : d.id);
            if (!/^\d+$/.test(fid)) { return '<span class="wq-seg-face">[表情]</span>'; }
            var nm = faceName(fid) || FACE_CHAR_BY_ID[fid] || '';
            return '<img class="wq-seg-face-img" src="' + faceUrl(fid) +
                '" alt="' + esc(nm || '表情') + '" title="' + esc((nm ? nm + ' ' : '') + '#' + fid) +
                '" data-fb="' + esc(nm || '[表情]') + '" loading="lazy" referrerpolicy="no-referrer">';
        }
        if (t === 'image') {
            if (d.url || d.file_id || d.file || d.mid) {
                return '<img class="wq-seg-img" src="' + esc(imgSrc(d.url, d)) + '"' +
                    (d.url ? ' data-fb="' + esc(d.url) + '"' : '') +
                    ' alt="图片" loading="lazy" data-wq-img="1" referrerpolicy="no-referrer">';
            }
            return '<div class="wq-card">[图片]</div>';
        }
        if (t === 'reply') {
            return quoteHtml(d.id);
        }
        if (t === 'record') {
            if (d.url || d.file_id || d.file || d.mid) {
                return '<audio class="wq-audio" controls preload="none"' +
                    (d.url ? ' data-fb="' + esc(d.url) + '"' : '') +
                    ' src="' + esc(rawSrc(d.url, d)) + '"></audio>';
            }
            return '<div class="wq-card">[语音]</div>';
        }
        if (t === 'video') {
            var vname = d.name || d.summary || '视频';
            if (d.url || d.file_id || d.file || d.mid) {
                var vsrc = esc(rawSrc(d.url, d));
                return '<div class="wq-video-wrap">' +
                    '<video class="wq-video" controls preload="metadata"' +
                        (d.url ? ' data-fb="' + esc(d.url) + '"' : '') +
                        ' src="' + vsrc + '"></video>' +
                    '<div class="wq-video-bar"><span>' + esc(vname) + '</span>' +
                        '<a href="' + vsrc + '" target="_blank" rel="noopener">新窗口打开</a>' +
                    '</div></div>';
            }
            return '<div class="wq-card">[视频]</div>';
        }
        if (t === 'file') {
            var name = d.name || '文件';
            var body = ICO_FILE + '<div><div class="wq-file-name">' + esc(name) +
                '</div><div class="wq-file-sub">文件</div></div>';
            if (d.url || d.file_id || d.file || d.mid) {
                return '<a class="wq-file" href="' + esc(rawSrc(d.url, d)) +
                    '" target="_blank" rel="noopener">' + body + '</a>';
            }
            return '<div class="wq-file">' + body + '</div>';
        }
        if (t === 'json' || t === 'xml') {
            return '<div class="wq-card">[卡片消息]</div>';
        }
        if (t === 'forward') {
            return forwardHtml(d);
        }
        if (t === 'mface') {
            var mname = d.summary || d.name || '表情';
            if (d.url || d.file_id || d.file || d.mid) {
                return '<img class="wq-seg-mface" src="' + esc(imgSrc(d.url, d)) + '"' +
                    (d.url ? ' data-fb="' + esc(d.url) + '"' : '') +
                    ' alt="' + esc(mname) + '" title="' + esc(mname) +
                    '" data-wq-img="1" loading="lazy" referrerpolicy="no-referrer">';
            }
            return '<span class="wq-seg-face">[' + esc(mname) + ']</span>';
        }
        return '';
    }

    function messageHtml(it, recalled) {
        if (it.kind === 'system') {
            return '<div class="wq-system"><span>' + esc(it.text || '') + '</span></div>';
        }
        if (it.kind === 'patch') { return ''; }
        var self = !!it.self;
        var sender = it.sender || {};
        var name = self ? '我' : (sender.name || sender.id || '');
        var body;
        if (recalled || it.recalled) {
            body = '<div class="wq-recalled">消息已撤回</div>';
        } else {
            var segs = it.segs || [];
            if (!segs.length && it.text) {
                body = '<span class="wq-seg-text">' + esc(it.text) + '</span>';
            } else {
                body = segs.map(segHtml).join('');
            }
            if (!body) { body = '<span class="wq-seg-text">' + esc(it.text || '') + '</span>'; }
        }
        var tools = '';
        if (!recalled && !it.recalled) {
            tools = '<div class="wq-msg-tools">' +
                '<button type="button" data-act="reply">回复</button>' +
                '<button type="button" data-act="menu" title="更多操作">⋯</button>' +
            '</div>';
        }
        var showName = !!name && (state.current && state.current.type === 'group') && !self;
        var mkey = msgKey(it);
        return '<div class="wq-msg' + (self ? ' self' : '') +
            (state.selecting ? ' selectable' : '') +
            (state.selected[mkey] ? ' selected' : '') +
            '" data-seq="' + esc(it.seq || '') +
            '" data-mid="' + esc(it.mid || '') + '" data-mkey="' + esc(mkey) + '">' +
            '<img class="wq-msg-avatar" src="' + esc(avatarOf(it)) + '" alt="" loading="lazy"' +
            ' data-uid="' + esc(sender.id || '') + '" data-name="' + esc(name) + '">' +
            '<div class="wq-msg-main">' +
                (showName ? '<div class="wq-msg-name">' + esc(name) + '</div>' : '') +
                '<div class="wq-bubble">' + body + '</div>' +
                tools +
            '</div>' +
        '</div>';
    }

    function dayHtml(t) {
        return '<div class="wq-day"><span>' + esc(dayLabel(t)) + '</span></div>';
    }

    function recallMap(items) {
        var m = {};
        (items || []).forEach(function (it) {
            if (it.kind === 'patch' && it.op === 'recall' && it.mid) {
                m[String(it.mid)] = true;
            }
        });
        return m;
    }

    function nearBottom() {
        return el.stream.scrollHeight - el.stream.scrollTop - el.stream.clientHeight < 140;
    }
    function scrollBottom(force) {
        if (!force && !nearBottom()) { return; }
        var to = function () {
            var prev = el.stream.style.scrollBehavior;
            el.stream.style.scrollBehavior = 'auto';
            el.stream.scrollTop = el.stream.scrollHeight;
            el.stream.style.scrollBehavior = prev;
        };
        to();
        if (window.requestAnimationFrame) {
            requestAnimationFrame(function () {
                to();
                requestAnimationFrame(to);
            });
        }
        setTimeout(to, 80);
        setTimeout(to, 260);
    }

    function renderMessages() {
        if (!state.current) {
            el.stream.innerHTML = '<div class="wq-empty-chat">' +
                '<div class="wq-empty-ico"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M42 23a17 17 0 0 1-17 16.8 18 18 0 0 1-7.8-1.8L6 42l4-10.2A16.6 16.6 0 0 1 8 23 17 17 0 0 1 25 6a17 17 0 0 1 17 17z"/><path d="M17 22h.1M25 22h.1M33 22h.1"/></svg></div>' +
                '<b>这里像 QQ 一样聊天</b><span>支持文字、官方表情、图片、@ 群友、引用回复、戳一戳</span></div>';
            return;
        }
        var out = [];
        if (!state.online) {
            out.push('<div class="wq-offline">NapCat 未连接：请到「WS 服务器」页面启动服务，并让 NapCat 以反向 WS 接入。</div>');
        }
        if (!state.messages.length) {
            out.push('<div class="wq-empty-chat" style="min-height:240px">' +
                '<div class="wq-empty-ico"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M42 23a17 17 0 0 1-17 16.8 18 18 0 0 1-7.8-1.8L6 42l4-10.2A16.6 16.6 0 0 1 8 23 17 17 0 0 1 25 6a17 17 0 0 1 17 17z"/><path d="M17 22h.1M25 22h.1M33 22h.1"/></svg></div>' +
                '<b>' + esc(state.current.name) + '</b>' +
                '<span>' + (state.current.type === 'group' ? '群号 ' : 'QQ ') + esc(state.current.id) +
                ' · 还没有消息，打个招呼吧</span></div>');
        } else {
            var recalls = recallMap(state.messages);
            var lastDay = '';
            state.messages.forEach(function (it) {
                if (it.kind === 'patch') { return; }
                var dk = dayKey(it.time);
                if (dk !== lastDay) {
                    out.push(dayHtml(it.time));
                    lastDay = dk;
                }
                out.push(messageHtml(it, recalls[String(it.mid)]));
            });
        }
        el.stream.innerHTML = out.join('');
        scrollBottom(true);
    }

    function appendLive(it) {
        if (!state.current) { return; }
        if (it.kind === 'system') {
            el.stream.insertAdjacentHTML('beforeend', messageHtml(it));
            scrollBottom();
            return;
        }
        if (it.kind === 'patch') {
            if (it.op === 'recall' && it.mid) {
                var idx = -1;
                for (var i = 0; i < state.messages.length; i++) {
                    if (String(state.messages[i].mid) === String(it.mid)) { idx = i; break; }
                }
                if (idx >= 0) {
                    state.messages[idx].recalled = true;
                    var node = el.stream.querySelector('[data-mid="' + cssQuote(it.mid) + '"]');
                    if (node) {
                        node.outerHTML = messageHtml(state.messages[idx], true);
                    }
                }
            }
            return;
        }
        if (!state.messages.length || dayKey(state.messages[state.messages.length - 1].time) !== dayKey(it.time)) {
            el.stream.insertAdjacentHTML('beforeend', dayHtml(it.time));
        }
        el.stream.insertAdjacentHTML('beforeend', messageHtml(it));
        scrollBottom();
    }

    function cssQuote(s) {
        return String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }
    function msgKey(it) {
        return String(it.mid || ('seq-' + (it.seq || 0)));
    }
    function msgByKey(key) {
        for (var i = 0; i < state.messages.length; i++) {
            if (msgKey(state.messages[i]) === String(key)) { return state.messages[i]; }
        }
        return null;
    }

    // ---------------------------------------------------------------- 选择会话
    function selectChat(type, id) {
        var meta = metaOf(type, id);
        state.current = {
            type: type, id: String(id), key: chatKey(type, id),
            name: meta.name, avatar: meta.avatar,
            member_count: meta.member_count || 0
        };
        state.messages = [];
        state.replyTo = null;
        state.attachments = [];
        state.atPicks = [];
        state.faceTokens = [];
        state.unread[state.current.key] = 0;
        renderReply();
        renderAttachments();
        renderHeader();
        renderContacts();
        closePopups();
        closeMembers();
        closeGroupPanel();
        el.stream.innerHTML = '<div class="wq-empty"><span class="wq-spin"></span>正在加载会话…</div>';
        // 进群会话时顺带确认自己的身份（群主 / 管理员才有禁言、踢人、发公告入口）
        if (type === 'group') {
            loadRole(id, true).then(function (r) {
                if (state.current && state.current.key === chatKey(type, id)) {
                    renderHeader();
                    el.groupBtn.title = r && r.ok ?
                        '群管理（我的身份：' + (r.label || '成员') + '）' :
                        '群管理（身份未确认）';
                }
            });
        }

        // sync=1：打开会话时顺带从 QQ 拉一次最近历史（服务端 20 秒内不重复请求）
        var url = '/api/webqq/history?type=' + encodeURIComponent(type) +
            '&id=' + encodeURIComponent(id) + '&limit=100&sync=1';
        api(url).then(function (j) {
            if (!state.current || state.current.key !== chatKey(type, id)) { return; }
            state.messages = j.items || [];
            toggleOfflineBanner();
            renderMessages();
            state.lastSeq = Math.max(state.lastSeq, j.seq || 0);
            if (type === 'group' && !el.members.classList.contains('hidden')) {
                loadMembers(id, false);
            }
            el.input.focus();
        }).catch(function (e) {
            if (!state.current || state.current.key !== chatKey(type, id)) { return; }
            el.stream.innerHTML = '<div class="wq-empty">加载会话失败：' + esc(e.message) + '</div>';
        });
    }

    function toggleOfflineBanner() { /* 渲染时统一处理 */ }

    function selectFirst() {
        var keys = Object.keys(state.previews);
        if (keys.length) {
            keys.sort(function (a, b) { return (state.previews[b].time || 0) - (state.previews[a].time || 0); });
            var kp = keyParts(keys[0]);
            selectChat(kp.type, kp.id);
            return;
        }
        if (state.friends.length) { selectChat('private', state.friends[0].id); return; }
        if (state.groups.length) { selectChat('group', state.groups[0].id); return; }
        renderHeader();
        renderMessages();
    }

    // ---------------------------------------------------------------- 初始化
    function load(force) {
        var url = '/api/webqq/bootstrap' + (force ? '?force=1' : '');
        return api(url).then(function (j) {
            state.me = j.me || state.me;
            state.friends = j.friends || [];
            state.groups = j.groups || [];
            state.previews = j.previews || {};
            state.online = !!j.online;
            state.lastSeq = j.seq || 0;
            state.notices = j.notices || state.notices;
            state.noticeLastId = j.notice_seq || state.noticeLastId;
            state.noticePending = j.notice_pending || 0;
            if (j.prefix) { state.prefix = String(j.prefix); }
            updateNoticeBadge();
            updateMe();
            updateNet(j.error);
            renderHeader();
            renderContacts();
            renderCommands();
            if (!state.current) {
                selectFirst();
            } else {
                var m = contactOf(state.current.type, state.current.id);
                if (m) {
                    state.current.name = m.name;
                    state.current.avatar = m.avatar;
                    state.current.member_count = m.member_count || 0;
                }
                renderHeader();
            }
        }).catch(function (e) {
            state.online = false;
            updateNet(e.message);
            renderContacts();
            if (!state.current) { renderHeader(); renderMessages(); }
            toast('读取 WebQQ 失败：' + e.message, true);
        });
    }

    function start() {
        if (!state.loaded) {
            state.loaded = true;
            bindEvents();
            load(false);
        } else {
            load(false);
        }
        loadFaces();
        startPoll();
    }

    function stop() {
        stopPoll();
    }

    // ---------------------------------------------------------------- 轮询
    function startPoll() {
        if (state.polling) { return; }
        state.polling = true;
        pollOnce();
    }
    function stopPoll() {
        state.polling = false;
        if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
    }
    function pollOnce() {
        if (!state.polling) { return; }
        state.pollTimer = setTimeout(function () {
            state.pollTimer = null;
            pullNotices();
            var since = state.lastSeq;
            api('/api/webqq/poll?since=' + since).then(function (j) {
                if ((j.seq || 0) < state.lastSeq) {
                    state.lastSeq = j.seq || 0;
                    if (state.current) { selectChat(state.current.type, state.current.id); }
                    return;
                }
                (j.items || []).forEach(handleIncoming);
                state.lastSeq = Math.max(state.lastSeq, j.seq || 0);
                if (!j.items || !j.items.length) {
                    // 静默，不刷新界面
                }
            }).catch(function () {
                /* 轮询失败不弹提示，避免刷屏；连接状态由手动刷新更新 */
            }).then(function () {
                if (state.polling) { pollOnce(); }
            });
        }, 1500);
    }

    var contactsTimer = null;
    function scheduleContacts() {
        if (contactsTimer) { return; }
        contactsTimer = setTimeout(function () {
            contactsTimer = null;
            renderContacts();
        }, 90);
    }

    function handleIncoming(it) {
        var key = it.key || chatKey(it.chat_type, it.chat_id);
        if (it.kind !== 'patch') {
            state.previews[key] = {
                text: it.kind === 'system' ? (it.text || '') : msgSummary(it),
                time: it.time || Math.floor(Date.now() / 1000),
                self: !!it.self,
                kind: it.kind || 'message'
            };
        }
        if (state.current && state.current.key === key) {
            if (it.kind === 'patch') {
                appendLive(it);
            } else if (!hasSeq(it.seq)) {
                state.messages.push(it);
                appendLive(it);
            }
        } else if (it.kind !== 'patch' && !it.self) {
            state.unread[key] = unreadOf(key) + 1;
        }
        scheduleContacts();
    }

    function hasSeq(seq) {
        if (!seq) { return false; }
        for (var i = 0; i < state.messages.length; i++) {
            if (String(state.messages[i].seq) === String(seq)) { return true; }
        }
        return false;
    }

    // ---------------------------------------------------------------- 发送
    function autoGrow() {
        el.input.style.height = 'auto';
        el.input.style.height = Math.min(el.input.scrollHeight, 160) + 'px';
    }

    function insertText(str) {
        var start = el.input.selectionStart == null ? el.input.value.length : el.input.selectionStart;
        var end = el.input.selectionEnd == null ? el.input.value.length : el.input.selectionEnd;
        el.input.value = el.input.value.slice(0, start) + str + el.input.value.slice(end);
        var pos = start + str.length;
        el.input.selectionStart = el.input.selectionEnd = pos;
        el.input.focus();
        autoGrow();
    }

    function buildTextSegs(text) {
        var arr = [], map = {}, pats = [];
        state.atPicks.forEach(function (a) {
            var p = '@' + a.name;
            if (!map[p]) {
                map[p] = { at: a };
                pats.push(p);
            }
        });
        Object.keys(FACE_BY_CHAR).forEach(function (ch) {
            if (!map[ch]) {
                map[ch] = { face: FACE_BY_CHAR[ch] };
                pats.push(ch);
            }
        });
        // 新版表情没有 Unicode：点选/手打的是 /表情名，这里还原成 face 段
        Object.keys(FACE_ID_BY_NAME).forEach(function (nm) {
            var key = '/' + nm;
            if (nm && !map[key]) {
                map[key] = { face: FACE_ID_BY_NAME[nm] };
                pats.push(key);
            }
        });
        if (!pats.length) {
            if (text.trim()) { arr.push({ type: 'text', data: { text: text } }); }
            return arr;
        }
        pats.sort(function (a, b) { return b.length - a.length; });
        var re = new RegExp('(' + pats.map(escRe).join('|') + ')', 'g');
        var last = 0, m;
        while ((m = re.exec(text)) !== null) {
            if (!m[0]) { re.lastIndex += 1; continue; }
            if (m.index > last) {
                arr.push({ type: 'text', data: { text: text.slice(last, m.index) } });
            }
            var tok = map[m[0]];
            if (tok.at) {
                arr.push({ type: 'at', data: { qq: tok.at.qq, name: tok.at.name } });
            } else {
                // 优先用表情面板里点选的原生 face ID（同一个字符可能对应多个 QQ 表情）
                var fid = tok.face, idx = -1;
                for (var i = 0; i < state.faceTokens.length; i++) {
                    if (state.faceTokens[i].ch === m[0]) { idx = i; break; }
                }
                if (idx >= 0) {
                    fid = state.faceTokens[idx].id;
                    state.faceTokens.splice(idx, 1);
                }
                arr.push({ type: 'face', data: { id: fid } });
            }
            last = m.index + m[0].length;
        }
        if (last < text.length) {
            arr.push({ type: 'text', data: { text: text.slice(last) } });
        }
        return arr;
    }

    function buildSegments() {
        var segs = [];
        if (state.replyTo && state.replyTo.mid) {
            segs.push({ type: 'reply', data: { id: String(state.replyTo.mid) } });
        }
        buildTextSegs(el.input.value).forEach(function (s) { segs.push(s); });
        state.attachments.forEach(function (a) {
            segs.push({ type: 'image', data: { data: a.dataUrl, name: a.name } });
        });
        return segs;
    }

    function setBusy(on) {
        state.busy = on;
        el.send.disabled = on;
        el.send.textContent = on ? '发送中…' : '发送';
    }

    function doSend() {
        if (!state.current) { toast('先选择一个好友或群', true); return; }
        if (state.busy) { return; }
        var segs = buildSegments();
        if (!segs.length || (!el.input.value.trim() && !state.attachments.length)) {
            toast('消息不能为空', true);
            el.input.focus();
            return;
        }
        setBusy(true);
        api('/api/webqq/send', {
            method: 'POST',
            body: JSON.stringify({ type: state.current.type, id: state.current.id, segments: segs })
        }).then(function (j) {
            if (j.item) {
                handleIncoming(j.item);
                if (state.current && j.item.key === state.current.key) {
                    // handleIncoming 已负责追加
                }
            }
            el.input.value = '';
            state.attachments = [];
            state.replyTo = null;
            state.atPicks = [];
            state.faceTokens = [];
            renderReply();
            renderAttachments();
            autoGrow();
            el.input.focus();
        }).catch(function (e) {
            toast('发送失败：' + e.message, true);
        }).then(function () {
            setBusy(false);
        });
    }

    // ---------------------------------------------------------------- 附件
    function renderAttachments() {
        if (!state.attachments.length) {
            el.attach.classList.add('hidden');
            el.attach.innerHTML = '';
            return;
        }
        el.attach.classList.remove('hidden');
        el.attach.innerHTML = state.attachments.map(function (a, i) {
            return '<div class="wq-attach-item" data-i="' + i + '">' +
                '<img src="' + esc(a.dataUrl) + '" alt="">' +
                '<button type="button" class="wq-attach-x" title="移除">×</button>' +
            '</div>';
        }).join('');
    }

    function addFiles(files) {
        var list = Array.prototype.slice.call(files || []);
        if (!list.length) { return; }
        list.forEach(function (f) {
            if (!/^image\//.test(f.type)) { toast('只能发送图片：' + f.name, true); return; }
            if (f.size > 12 * 1024 * 1024) { toast('图片超过 12MB：' + f.name, true); return; }
            if (state.attachments.length >= 6) { toast('一次最多附带 6 张图片', true); return; }
            var r = new FileReader();
            r.onload = function () {
                state.attachments.push({ name: f.name, dataUrl: String(r.result || '') });
                renderAttachments();
            };
            r.onerror = function () { toast('读取图片失败：' + f.name, true); };
            r.readAsDataURL(f);
        });
    }

    // ---------------------------------------------------------------- 引用
    function renderReply() {
        if (!state.replyTo) {
            el.replyBar.classList.add('hidden');
            return;
        }
        el.replyBar.classList.remove('hidden');
        el.replyName.textContent = state.replyTo.name || '';
        el.replyText.textContent = state.replyTo.text || '';
    }
    function setReply(it) {
        if (!it || !it.mid) { return; }
        state.replyTo = {
            mid: it.mid,
            name: it.self ? '我' : ((it.sender && it.sender.name) || ''),
            text: msgSummary(it)
        };
        renderReply();
        el.input.focus();
    }

    // ---------------------------------------------------------------- 表情 / @
    function renderEmojiGrid() {
        var list = FACE_LIST.length ? FACE_LIST : FACES.map(function (f) {
            return { id: String(f[0]), name: '' };
        });
        el.emojiGrid.innerHTML = list.map(function (it) {
            var id = String(it.id);
            var nm = it.name || faceName(id) || '';
            return '<button type="button" data-face="' + esc(id) + '" title="' +
                esc((nm || '表情') + ' #' + id) + '">' +
                '<img src="' + faceUrl(id) + '" alt="' + esc(nm || '表情') +
                    '" loading="lazy" referrerpolicy="no-referrer">' +
                '<span class="wq-face-fb">' + esc(FACE_CHAR_BY_ID[id] || '') + '</span>' +
            '</button>';
        }).join('');
        Array.prototype.forEach.call(el.emojiGrid.querySelectorAll('button'), function (b) {
            var img = b.querySelector('img');
            if (img) {
                img.addEventListener('error', function () {
                    img.style.display = 'none';
                    var fb = b.querySelector('.wq-face-fb');
                    if (fb) { fb.style.display = 'grid'; }
                });
            }
        });
    }
    function showEmoji(show) {
        el.emojiPanel.classList.toggle('hidden', !show);
        el.emojiBtn.classList.toggle('active', !!show);
        if (show) { hideAt(); }
    }
    function hideEmoji() {
        el.emojiPanel.classList.add('hidden');
        el.emojiBtn.classList.remove('active');
    }
    function showAt(show) {
        el.atPanel.classList.toggle('hidden', !show);
        el.atBtn.classList.toggle('active', !!show);
        if (show) { hideEmoji(); }
    }
    function hideAt() {
        el.atPanel.classList.add('hidden');
        el.atBtn.classList.remove('active');
    }
    function closePopups() {
        hideEmoji(); hideAt(); hideCmd();
        if (el.fwdPanel) { closeForwardPicker(); }
    }

    function loadMembers(gid, force, cb) {
        if (!force && state.members[gid]) {
            if (cb) { cb(state.members[gid]); }
            return Promise.resolve(state.members[gid]);
        }
        return api('/api/webqq/members?gid=' + encodeURIComponent(gid) + (force ? '&force=1' : ''))
            .then(function (j) {
                state.members[gid] = j.items || [];
                if (j.warning) { toast('群成员可能不是最新的：' + j.warning, true); }
                if (cb) { cb(state.members[gid]); }
                return state.members[gid];
            }).catch(function (e) {
                toast('读取群成员失败：' + e.message, true);
                return [];
            });
    }

    function renderAtList(items) {
        var html = '<div class="wq-at-all" data-qq="all" data-name="全体成员">@全体成员</div>';
        html += items.map(function (m) {
            return '<div class="wq-at-item" data-qq="' + esc(m.id) + '" data-name="' + esc(m.name) + '">' +
                '<img src="' + esc(m.avatar) + '" alt="" loading="lazy">' +
                '<span>' + esc(m.name) + '</span><b>' + esc(m.id) + '</b>' +
            '</div>';
        }).join('');
        el.atList.innerHTML = html;
    }

    function openAt() {
        if (!isGroup()) { toast('只有群聊可以 @ 人', true); return; }
        showAt(true);
        if (state.members[state.current.id]) {
            renderAtList(state.members[state.current.id]);
            return;
        }
        el.atList.innerHTML = '<div class="wq-empty"><span class="wq-spin"></span>正在读取群成员…</div>';
        loadMembers(state.current.id, false, function (items) {
            if (!el.atPanel.classList.contains('hidden')) { renderAtList(items); }
        });
    }

    function pickAt(qq, name) {
        state.atPicks.push({ qq: String(qq), name: String(name) });
        insertText('@' + name + ' ');
        hideAt();
    }

    // ---------------------------------------------------------------- 群成员
    function closeMembers() {
        el.members.classList.add('hidden');
        el.memberBtn.classList.remove('active');
    }
    function openMembers() {
        if (!isGroup()) { return; }
        el.members.classList.remove('hidden');
        el.memberBtn.classList.add('active');
        state.memberFilter = '';
        el.memberSearch.value = '';
        if (state.members[state.current.id]) {
            renderMembers();
        } else {
            el.memberList.innerHTML = '<div class="wq-empty"><span class="wq-spin"></span>正在读取群成员…</div>';
        }
        // 每次打开都从 QQ 重新拉一遍：谁刚被设成管理员、谁被撤了，右键菜单才跟得上
        loadMembers(state.current.id, true, function () {
            if (!el.members.classList.contains('hidden')) { renderMembers(); }
        });
    }
    function toggleMembers() {
        if (el.members.classList.contains('hidden')) { openMembers(); } else { closeMembers(); }
    }
    function renderMembers() {
        if (!state.current) { return; }
        var items = state.members[state.current.id] || [];
        el.memberCount.textContent = items.length ? '(' + items.length + ')' : '';
        var q = state.memberFilter.trim().toLowerCase();
        var rows = items.filter(function (m) {
            return !q || m.name.toLowerCase().indexOf(q) >= 0 || String(m.id).indexOf(q) >= 0;
        });
        if (!rows.length) {
            el.memberList.innerHTML = '<div class="wq-empty">' + (q ? '没有匹配的群成员' : '暂无成员数据') + '</div>';
            return;
        }
        el.memberList.innerHTML = rows.map(function (m) {
            var role = m.role === 'owner' ? '<span class="wq-role owner">群主</span>' :
                (m.role === 'admin' ? '<span class="wq-role admin">管理员</span>' : '');
            return '<div class="wq-member" data-uid="' + esc(m.id) + '" data-name="' + esc(m.name) +
                '" data-role="' + esc(m.role || 'member') + '">' +
                '<img src="' + esc(m.avatar) + '" alt="" loading="lazy">' +
                '<div class="wq-member-main">' +
                    '<div class="wq-member-name">' + esc(m.name) + '</div>' +
                    '<div class="wq-member-sub">' + esc(m.card && m.nickname && m.card !== m.nickname ? m.nickname : m.id) + '</div>' +
                '</div>' + role +
            '</div>';
        }).join('');
    }

    // ---------------------------------------------------------------- 群管理
    // 禁言 / 踢人 / 群公告都只有群主或管理员能做：先用 /api/webqq/group/role 判断身份，
    // 没有权限就不在菜单里出现这些项，避免点了才被 QQ 侧拒绝。
    function loadRole(gid, force) {
        gid = String(gid || '');
        if (!gid) { return Promise.resolve(null); }
        if (!force && state.roles[gid]) { return Promise.resolve(state.roles[gid]); }
        return api('/api/webqq/group/role?gid=' + encodeURIComponent(gid) +
            (force ? '&force=1' : ''))
            .then(function (j) {
                state.roles[gid] = j;
                return j;
            })
            .catch(function (e) {
                state.roles[gid] = { ok: false, error: e.message };
                return state.roles[gid];
            });
    }

    function myRole() {
        if (!state.current || state.current.type !== 'group') { return {}; }
        return state.roles[state.current.id] || {};
    }

    function canManage() {
        var r = myRole();
        return !!(r.ok && r.can_manage);
    }

    // 群成员身份：优先用消息自带的 role（事件里最准），再查成员列表缓存
    function memberRoleOf(uid) {
        if (!state.current || state.current.type !== 'group') { return ''; }
        var items = state.members[state.current.id] || [];
        uid = String(uid || '');
        for (var i = 0; i < items.length; i++) {
            if (String(items[i].id) === uid) { return String(items[i].role || ''); }
        }
        return '';
    }

    // 能不能对某个成员执行管理操作（禁言 / 踢人 / 撤回），和 QQ 的规则一致：
    // 群主可以动任何人（除自己），管理员只能动普通成员，谁都不能动群主。
    function canActOn(uid, roleHint) {
        var r = myRole();
        if (!r.ok || !r.can_manage) { return false; }
        uid = String(uid || '');
        if (uid && uid === String((state.me && state.me.id) || '')) { return false; }
        var tr = memberRoleOf(uid) || String(roleHint || '') || 'member';
        if (tr === 'owner') { return false; }
        if (tr === 'admin' && r.role !== 'owner') { return false; }
        return true;
    }

    function fmtNoticeTime(ts) {
        ts = Number(ts || 0);
        if (!ts) { return ''; }
        var d = new Date(ts * 1000);
        var p = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
            ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }

    function loadNotices(gid) {
        gid = gid || (state.current && state.current.id);
        if (!gid) { return; }
        el.noticeList.innerHTML =
            '<div class="wq-empty"><span class="wq-spin"></span>正在读取群公告…</div>';
        api('/api/webqq/group/notice?gid=' + encodeURIComponent(gid))
            .then(function (j) {
                if (!state.current || state.current.id !== String(gid)) { return; }
                var items = j.items || [];
                if (!items.length) {
                    el.noticeList.innerHTML = '<div class="wq-empty">该群还没有公告</div>';
                    return;
                }
                el.noticeList.innerHTML = items.map(function (n) {
                    return '<div class="wq-notice-item" data-text="' + esc(n.text) + '">' +
                        '<div class="wq-notice-meta">' + esc(fmtNoticeTime(n.time) || '公告') +
                            (n.images ? ' · 含 ' + n.images + ' 张图' : '') +
                            (n.pinned ? ' · 置顶' : '') +
                            (n.type === 20 ? ' · 新人公告' : '') + '</div>' +
                        '<div class="wq-notice-text">' + esc(n.text) + '</div>' +
                        (canManage() ? '<button type="button" class="wq-mini" data-notice-use="1">引用重发</button>' : '') +
                    '</div>';
                }).join('');
            })
            .catch(function (e) {
                el.noticeList.innerHTML = '<div class="wq-empty">读取失败：' + esc(e.message) + '</div>';
            });
    }

    function openGroupPanel() {
        if (!isGroup()) { return; }
        el.groupPanel.classList.remove('hidden');
        el.groupRole.textContent = '';
        el.noticeForm.classList.add('hidden');
        el.noticeReadonly.classList.add('hidden');
        el.noticeList.innerHTML =
            '<div class="wq-empty"><span class="wq-spin"></span>正在读取群公告…</div>';
        loadRole(state.current.id, true).then(function (r) {
            if (!state.current) { return; }
            el.groupRole.textContent = r && r.ok ? (r.label || '') : '';
            el.groupRole.className = 'wq-role ' + (r && r.ok ? String(r.role || '') : '');
            var can = canManage();
            // 不是群主 / 管理员：发布区整块不出现，只保留查看公告
            el.noticeForm.classList.toggle('hidden', !can);
            el.noticeReadonly.classList.toggle('hidden', can);
            el.noticeSend.disabled = !can;
            el.noticeTip.textContent = '发布后会覆盖该群当前公告';
            loadNotices(state.current.id);
        });
    }

    function clearNoticeImage() {
        state.noticeImageData = '';
        if (el.noticeThumb) { el.noticeThumb.classList.add('hidden'); }
        if (el.noticeThumbImg) { el.noticeThumbImg.removeAttribute('src'); }
        if (el.noticeImage) { el.noticeImage.value = ''; }
    }

    function readNoticeImage(file) {
        if (!file) { return; }
        if (!/^image\//.test(file.type || '')) { toast('只能选择图片文件', true); return; }
        var fr = new FileReader();
        fr.onload = function () {
            state.noticeImageData = String(fr.result || '');
            el.noticeThumbImg.src = state.noticeImageData;
            el.noticeThumb.classList.remove('hidden');
        };
        fr.onerror = function () { toast('图片读取失败', true); };
        fr.readAsDataURL(file);
    }

    function closeGroupPanel() {
        el.groupPanel.classList.add('hidden');
    }

    function publishNotice() {
        if (!isGroup()) { return; }
        if (!canManage()) { toast('只有群主 / 管理员可以发布公告', true); return; }
        var content = el.noticeInput.value.trim();
        if (!content) { toast('公告内容不能为空', true); return; }
        el.noticeSend.disabled = true;
        api('/api/webqq/group/notice', {
            method: 'POST',
            body: JSON.stringify({
                gid: state.current.id,
                content: content,
                image: state.noticeImageData || '',
                pinned: !!(el.noticePinned && el.noticePinned.checked),
                // 20 = 新人公告（只发给新成员），1 = 普通公告
                type: el.noticeNewMember && el.noticeNewMember.checked ? 20 : 1
            })
        }).then(function () {
            el.noticeSend.disabled = false;
            el.noticeInput.value = '';
            if (el.noticePinned) { el.noticePinned.checked = false; }
            if (el.noticeNewMember) { el.noticeNewMember.checked = false; }
            clearNoticeImage();
            toast('群公告已发布');
            loadNotices(state.current.id);
        }).catch(function (e) {
            el.noticeSend.disabled = false;
            toast('发布失败：' + e.message, true);
        });
    }

    function doBan(uid, name, sec) {
        if (!isGroup() || !uid) { return; }
        api('/api/webqq/group/ban', {
            method: 'POST',
            body: JSON.stringify({ gid: state.current.id, uid: uid, duration: sec })
        }).then(function (j) {
            toast((j.text || '操作成功') + '：' + (name || uid));
        }).catch(function (e) {
            toast('禁言失败：' + e.message, true);
        });
    }

    function doKick(uid, name) {
        if (!isGroup() || !uid) { return; }
        if (!window.confirm('确定把「' + (name || uid) + '」移出本群？')) { return; }
        api('/api/webqq/group/kick', {
            method: 'POST',
            body: JSON.stringify({ gid: state.current.id, uid: uid, reject: false })
        }).then(function () {
            toast('已移出本群：' + (name || uid));
            delete state.members[state.current.id];
            loadMembers(state.current.id, true, renderMembers);
        }).catch(function (e) {
            toast('移出失败：' + e.message, true);
        });
    }

    // ---------------------------------------------------------------- 戳一戳
    function doPoke(uid, name) {
        if (!state.current) { return; }
        if (!uid) { toast('没有可戳的对象', true); return; }
        api('/api/webqq/poke', {
            method: 'POST',
            body: JSON.stringify({
                type: state.current.type, id: state.current.id,
                user_id: String(uid), name: String(name || '')
            })
        }).then(function (j) {
            if (j.item) { handleIncoming(j.item); }
            toast('已戳一戳 ' + (name || uid));
        }).catch(function (e) {
            // 后端已把 NapCat 的原始报错（如「能力不可用」）翻译成人话，直接显示即可
            toast(e.message || '戳一戳失败', true);
        });
    }

    function headerPoke() {
        if (!state.current) { return; }
        if (state.current.type === 'private') {
            doPoke(state.current.id, state.current.name);
            return;
        }
        for (var i = state.messages.length - 1; i >= 0; i--) {
            var it = state.messages[i];
            if (it.kind === 'message' && !it.self && it.sender && it.sender.id) {
                doPoke(it.sender.id, it.sender.name);
                return;
            }
        }
        loadMembers(state.current.id, false, function (items) {
            var me = String((state.me && state.me.id) || '');
            var target = null;
            for (var i = 0; i < items.length; i++) {
                if (String(items[i].id) !== me) { target = items[i]; break; }
            }
            if (target) { doPoke(target.id, target.name); }
            else { toast('群里还没有可戳的成员', true); }
        });
    }

    // 手动同步：强制从 QQ 侧拉一次历史（自动同步在打开会话时已触发）
    function syncCurrent() {
        if (!state.current) { return; }
        var cur = state.current;
        var key = cur.key;
        if (el.syncBtn) { el.syncBtn.disabled = true; }
        toast('正在同步历史消息…');
        var url = '/api/webqq/history?type=' + encodeURIComponent(cur.type) +
            '&id=' + encodeURIComponent(cur.id) + '&limit=100&sync=1&force=1';
        api(url).then(function (j) {
            if (!state.current || state.current.key !== key) { return; }
            state.messages = j.items || [];
            renderMessages();
            state.lastSeq = Math.max(state.lastSeq, j.seq || 0);
            if (j.synced) { toast('已同步 ' + j.synced + ' 条历史消息'); }
            else if (j.sync_error) { toast('同步失败：' + j.sync_error, true); }
            else { toast('没有新的历史消息'); }
        }).catch(function (e) {
            toast('同步失败：' + e.message, true);
        }).then(function () {
            if (el.syncBtn && state.current && state.current.key === key) {
                el.syncBtn.disabled = false;
            }
        });
    }

    // ---------------------------------------------------------------- 图片预览
    var vw = { s: 1, x: 0, y: 0, down: false, moved: false, sx: 0, sy: 0, ox: 0, oy: 0 };
    function vwApply() {
        el.viewerImg.style.transform = 'translate(' + vw.x + 'px,' + vw.y + 'px) scale(' + vw.s + ')';
        el.viewerPct.textContent = Math.round(vw.s * 100) + '%';
    }
    function vwReset() {
        vw.s = 1; vw.x = 0; vw.y = 0;
        vwApply();
    }
    function vwZoomAt(px, py, factor) {
        var s0 = vw.s;
        var s1 = clamp(s0 * factor, 0.15, 8);
        var cx = window.innerWidth / 2 + vw.x;
        var cy = window.innerHeight / 2 + vw.y;
        vw.x = (px - (px - cx) * (s1 / s0)) - window.innerWidth / 2;
        vw.y = (py - (py - cy) * (s1 / s0)) - window.innerHeight / 2;
        vw.s = s1;
        vwApply();
    }
    function openViewer(src) {
        el.viewerImg.src = src;
        vwReset();
        el.viewer.classList.remove('hidden');
    }
    function closeViewer() {
        el.viewer.classList.add('hidden');
        el.viewerImg.removeAttribute('src');
    }

    // ---------------------------------------------------------------- 多选
    function msgText(it) {
        if (!it) { return ''; }
        if (it.text) { return String(it.text); }
        var parts = [];
        (it.segs || []).forEach(function (s) {
            if (s.type === 'text') { parts.push((s.data && s.data.text) || ''); }
            else if (s.type === 'image') { parts.push('[图片]'); }
            else if (s.type === 'face') { parts.push('[表情]'); }
        });
        return parts.join('');
    }

    function fallbackCopy(text, done) {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); }
        catch (err) { toast('复制失败', true); }
        document.body.removeChild(ta);
    }
    function copyText(text) {
        text = String(text == null ? '' : text);
        if (!text) { toast('没有可复制的文字', true); return; }
        var done = function () { toast('已复制'); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done).catch(function () {
                fallbackCopy(text, done);
            });
        } else {
            fallbackCopy(text, done);
        }
    }

    function selectedMsgs() {
        return state.messages.filter(function (it) {
            return state.selected[msgKey(it)];
        });
    }
    function uniqueSenders(msgs) {
        var seen = {}, out = [];
        (msgs || []).forEach(function (it) {
            if (it.self) { return; }
            var s = it.sender || {};
            var id = String(s.id || '');
            if (!id || seen[id]) { return; }
            seen[id] = 1;
            out.push({ id: id, name: String(s.name || id) });
        });
        return out;
    }

    function enterSelect(it) {
        hideMenu();
        state.selecting = true;
        state.selected = {};
        if (it) { state.selected[msgKey(it)] = true; }
        renderMessages();
        updateMultiBar();
    }
    function exitSelect() {
        state.selecting = false;
        state.selected = {};
        updateMultiBar();
        if (state.current) { renderMessages(); }
    }
    function toggleSelect(it) {
        var k = msgKey(it);
        if (state.selected[k]) { delete state.selected[k]; }
        else { state.selected[k] = true; }
        var node = el.stream.querySelector('[data-mkey="' + cssQuote(k) + '"]');
        if (node) { node.classList.toggle('selected', !!state.selected[k]); }
        updateMultiBar();
    }
    function updateMultiBar() {
        if (!el.multiBar) { return; }
        var n = Object.keys(state.selected).length;
        el.multiBar.classList.toggle('hidden', !state.selecting);
        if (el.multiInfo) { el.multiInfo.textContent = '已选 ' + n + ' 条'; }
    }

    function multiAction(act) {
        var msgs = selectedMsgs();
        if (act === 'cancel') { exitSelect(); return; }
        if (!msgs.length) { toast('先选择消息', true); return; }
        if (act === 'copy') {
            copyText(msgs.map(msgText).filter(Boolean).join('\n'));
            exitSelect();
            return;
        }
        if (act === 'at') {
            if (!isGroup()) { toast('只有群聊可以 @ 人', true); return; }
            var ppl = uniqueSenders(msgs);
            if (!ppl.length) { toast('所选消息里没有可 @ 的人', true); return; }
            ppl.forEach(function (p) {
                state.atPicks.push({ qq: p.id, name: p.name });
                insertText('@' + p.name + ' ');
            });
            exitSelect();
            el.input.focus();
            toast('已 @ ' + ppl.length + ' 人');
            return;
        }
        if (act === 'poke') {
            var ppl2 = uniqueSenders(msgs);
            if (!ppl2.length) { toast('所选消息里没有可戳的人', true); return; }
            exitSelect();
            var chain = Promise.resolve();
            ppl2.forEach(function (p) {
                chain = chain.then(function () { doPoke(p.id, p.name); });
            });
            return;
        }
        if (act === 'forward') {
            openForwardPicker(msgs, 'merge');
            return;
        }
        if (act === 'each') {
            openForwardPicker(msgs, 'each');
            return;
        }
        if (act === 'recall') {
            var targets = msgs.filter(function (it) {
                return it.mid && canRecall(it);
            });
            if (!targets.length) {
                toast('只能撤回自己的消息（群主 / 管理员可撤回普通成员）', true);
                return;
            }
            var chainRc = Promise.resolve(), okRc = 0, badRc = 0, errRc = '';
            targets.forEach(function (it) {
                chainRc = chainRc.then(function () {
                    return recallOne(it).then(function () { okRc += 1; })
                        .catch(function (e) { badRc += 1; errRc = errRc || e.message; });
                });
            });
            chainRc.then(function () {
                exitSelect();
                toast('已撤回 ' + okRc + ' 条' +
                      (badRc ? ('，' + badRc + ' 条失败：' + errRc) : ''), badRc > 0);
            });
            return;
        }
        if (act === 'quote') {
            quoteToChat(msgs);
            exitSelect();
        }
    }

    // ---------------------------------------------------------------- 右键菜单
    var menuActions = {}, menuSeq = 0;
    var menuTimer = 0;
    function hideMenu() {
        if (!el.menu || el.menu.classList.contains('hidden')) { return; }
        // 先播放收起动画（wq-menu-out），120ms 后再真正隐藏，点空白处不再「啪」地消失
        el.menu.classList.add('closing');
        clearTimeout(menuTimer);
        menuTimer = setTimeout(function () {
            el.menu.classList.add('hidden');
            el.menu.classList.remove('closing');
            el.menu.innerHTML = '';
        }, 120);
        menuActions = {};
    }
    function showMenu(x, y, items) {
        if (!el.menu) { return; }
        clearTimeout(menuTimer);
        el.menu.classList.remove('hidden');
        el.menu.classList.remove('closing');
        menuActions = {};
        var html = [];
        (items || []).forEach(function (it) {
            if (!it) { return; }
            if (it.sep) { html.push('<div class="wq-menu-sep"></div>'); return; }
            if (it.title) {
                html.push('<div class="wq-menu-title">' + esc(it.title) + '</div>');
                return;
            }
            var id = 'm' + (++menuSeq);
            menuActions[id] = it.fn;
            html.push('<button type="button" class="' + (it.danger ? 'danger' : '') +
                '" data-mi="' + id + '">' + esc(it.label) + '</button>');
        });
        el.menu.innerHTML = html.join('');
        el.menu.classList.remove('hidden');
        var host = el.menu.parentNode;
        var box = host.getBoundingClientRect();
        var left = clamp(x - box.left, 8, Math.max(8, box.width - el.menu.offsetWidth - 8));
        var top = clamp(y - box.top, 8, Math.max(8, box.height - el.menu.offsetHeight - 8));
        el.menu.style.left = left + 'px';
        el.menu.style.top = top + 'px';
    }
    function canRecall(it) {
        if (!it || !it.mid) { return false; }
        if (it.self) { return true; }
        if (!isGroup()) { return false; }
        var s = it.sender || {};
        return canActOn(s.id, s.role);
    }

    function recallOne(it) {
        var cur = state.current || {};
        return api('/api/webqq/recall', {
            method: 'POST', body: JSON.stringify({
                mid: String(it.mid || ''),
                type: cur.type || '', id: cur.id || ''
            })
        });
    }

    function recallMsg(it) {
        if (!it.mid) { toast('这条消息没有可撤回的 id', true); return; }
        recallOne(it).then(function () {
            toast('已撤回');
        }).catch(function (e) {
            toast('撤回失败：' + e.message, true);
        });
    }

    function buildForwardNodes(msgs) {
        return (msgs || []).map(function (it) {
            var s = it.sender || {};
            return {
                name: it.self ? ((state.me && state.me.name) || '我') : (s.name || s.id || ''),
                time: it.time || 0,
                text: msgText(it),
                segs: (it.segs || []).slice()
            };
        });
    }

    function forwardSelected(msgs, mode, type, id, name) {
        if (!msgs || !msgs.length) { toast('先选择消息', true); return; }
        var target = (type && id) ? { type: type, id: id, name: name || id } :
            state.current;
        if (!target) { toast('先选择一个会话', true); return; }
        var nodes = buildForwardNodes(msgs);
        api('/api/webqq/forward/send', {
            method: 'POST',
            body: JSON.stringify({ type: target.type, id: target.id,
                                   mode: mode, nodes: nodes })
        }).then(function (j) {
            (j.items || []).forEach(handleIncoming);
            if (j.item) { handleIncoming(j.item); }
            exitSelect();
            toast((mode === 'merge' ? '已合并转发 ' : '已逐条转发 ') +
                  nodes.length + ' 条到「' + (target.name || target.id) + '」');
        }).catch(function (e) {
            toast('转发失败：' + e.message, true);
        });
    }

    function forwardTargetRows(q) {
        q = String(q || '').trim().toLowerCase();
        var out = [];
        (state.groups || []).forEach(function (g) {
            out.push({ type: 'group', id: g.id, name: g.name || g.id,
                       sub: '群号 ' + g.id, avatar: g.avatar });
        });
        (state.friends || []).forEach(function (f) {
            out.push({ type: 'private', id: f.id, name: f.name || f.id,
                       sub: 'QQ ' + f.id, avatar: f.avatar });
        });
        return q ? out.filter(function (r) {
            return (r.name + ' ' + r.id).toLowerCase().indexOf(q) !== -1;
        }) : out;
    }

    function renderForwardTargets(q) {
        if (!el.fwdList) { return; }
        var rows = forwardTargetRows(q);
        if (!rows.length) {
            el.fwdList.innerHTML = '<div class="wq-empty">没有匹配的群 / 好友</div>';
            return;
        }
        el.fwdList.innerHTML = rows.map(function (r) {
            return '<div class="wq-fwd-row" data-type="' + esc(r.type) +
                '" data-id="' + esc(r.id) + '" data-name="' + esc(r.name) + '">' +
                '<img src="' + esc(r.avatar || avatarFor(r.type, r.id)) +
                    '" alt="" loading="lazy">' +
                '<div><b>' + esc(r.name) + '</b><span>' + esc(r.sub) + '</span></div>' +
            '</div>';
        }).join('');
    }

    function openForwardPicker(msgs, mode) {
        if (!msgs || !msgs.length) { toast('先选择消息', true); return; }
        state.fwd = { msgs: msgs.slice(), mode: mode };
        el.fwdTitle.textContent = (mode === 'merge' ? '合并转发到' : '逐条转发到');
        el.fwdSearch.value = '';
        renderForwardTargets('');
        el.fwdPanel.classList.remove('hidden');
        setTimeout(function () { el.fwdSearch.focus(); }, 50);
    }

    function closeForwardPicker() {
        if (!el.fwdPanel) { return; }
        el.fwdPanel.classList.add('hidden');
        state.fwd = null;
    }

    function messageMenu(it) {
        var s = it.sender || {};
        var items = [];
        if (it.kind === 'message') {
            items.push({ label: '回复', fn: function () { setReply(it); } });
            items.push({ label: '复制文字', fn: function () { copyText(msgText(it)); } });
        }
        if (isGroup() && !it.self && s.id) {
            items.push({ label: '@ ' + (s.name || s.id),
                         fn: function () { pickAt(s.id, s.name || s.id); } });
            items.push({ label: '戳一戳 ' + (s.name || ''),
                         fn: function () { doPoke(s.id, s.name); } });
            if (canActOn(s.id, s.role)) {
                items.push({ sep: true });
                items.push({ label: '禁言 ' + (s.name || s.id) + ' 1 小时',
                             fn: function () { doBan(s.id, s.name, 3600); } });
                items.push({ label: '解除禁言',
                             fn: function () { doBan(s.id, s.name, 0); } });
                items.push({ label: '移出本群', danger: true,
                             fn: function () { doKick(s.id, s.name); } });
            }
        }
        if (it.kind === 'message') {
            items.push({ sep: true });
            if (it.mid && canRecall(it)) {
                items.push({ label: '撤回消息', danger: true,
                             fn: function () { recallMsg(it); } });
            }
            items.push({ label: '合并转发',
                         fn: function () { openForwardPicker([it], 'merge'); } });
            items.push({ label: '逐条转发',
                         fn: function () { openForwardPicker([it], 'each'); } });
            items.push({ label: '合成名言图并发送', fn: function () { quoteToChat([it]); } });
            items.push({ label: '合成名言图（可编辑）', fn: function () { gotoCompose(it); } });
            items.push({ label: '多选消息', fn: function () { enterSelect(it); } });
        }
        return items;
    }

    // ---------------------------------------------------------------- 名言图
    function proxySrc(u, d) {
        u = String(u || '');
        d = d || {};
        if (/^https?:\/\//i.test(u)) {
            return '/api/webqq/img?u=' + encodeURIComponent(u) +
                (d.file ? '&file=' + encodeURIComponent(d.file) : '') +
                (d.file_id ? '&fid=' + encodeURIComponent(d.file_id) : '') +
                (d.mid ? '&mid=' + encodeURIComponent(d.mid) : '');
        }
        return u;
    }
    function fetchDataUrl(u, d) {
        return fetch(proxySrc(u, d), { credentials: 'same-origin' }).then(function (r) {
            if (!r.ok) { throw new Error('图片读取失败'); }
            return r.blob();
        }).then(function (blob) {
            return new Promise(function (resolve, reject) {
                var fr = new FileReader();
                fr.onload = function () { resolve(String(fr.result || '')); };
                fr.onerror = function () { reject(new Error('图片读取失败')); };
                fr.readAsDataURL(blob);
            });
        });
    }
    function quoteImages(items) {
        var imgs = [];
        (items || []).forEach(function (it) {
            (it.segs || []).forEach(function (s) {
                if (s.type === 'image' && s.data && s.data.url) {
                    imgs.push({ url: s.data.url, file: s.data.file || '',
                                file_id: s.data.file_id || '', mid: s.data.mid || '' });
                }
            });
        });
        imgs = imgs.slice(0, 6);
        return Promise.all(imgs.map(function (o) {
            return fetchDataUrl(o.url, o).catch(function () { return ''; });
        })).then(function (list) {
            return list.filter(Boolean);
        });
    }
    function quoteToChat(items) {
        hideMenu();
        items = items || [];
        if (!state.current) { toast('先选择一个会话', true); return; }
        if (!items.length) { toast('先选择消息', true); return; }
        // 多选时把选中的文字按时间顺序拼成一段；超过名言图上限就截断
        var it = items[items.length - 1];
        var text = items.map(msgText).filter(Boolean).join('\n').trim();
        if (text.length > 500) { text = text.slice(0, 499) + '…'; }
        if (!text) { toast('选中的消息没有可用的文字', true); return; }
        var cur = { type: state.current.type, id: state.current.id,
                    name: state.current.name };
        var sender = it.sender || {};
        var self = !!it.self;
        var payload = {
            text: text,
            name: self ? ((state.me && state.me.name) || '我') : (sender.name || ''),
            qq: self ? ((state.me && state.me.id) || '') : (sender.id || ''),
            gid: cur.type === 'group' ? cur.id : ''
        };
        toast('正在合成名言图…');
        quoteImages(items).then(function (imgs) {
            payload.images = imgs;
            return api('/api/quote/generate', {
                method: 'POST', body: JSON.stringify(payload)
            });
        }).then(function (j) {
            if (!j.data) { throw new Error('渲染结果为空'); }
            var dataUrl = 'data:' + (j.mime || 'image/png') + ';base64,' + j.data;
            return api('/api/webqq/send', {
                method: 'POST',
                body: JSON.stringify({ type: cur.type, id: cur.id,
                    segments: [{ type: 'image', data: { data: dataUrl } }] })
            });
        }).then(function (j) {
            if (j.item) { handleIncoming(j.item); }
            toast('名言图已发送到「' + (cur.name || cur.id) + '」');
        }).catch(function (e) {
            toast('合成名言图失败：' + e.message, true);
        });
    }
    function gotoCompose(it) {
        hideMenu();
        var detail = null;
        if (it) {
            var s = it.sender || {};
            detail = {
                text: msgText(it),
                name: it.self ? ((state.me && state.me.name) || '我') : (s.name || ''),
                qq: it.self ? ((state.me && state.me.id) || '') : (s.id || ''),
                images: (it.segs || []).filter(function (x) {
                    return x.type === 'image' && x.data && x.data.url;
                }).map(function (x) { return x.data.url; }),
                chat: state.current ? { type: state.current.type,
                    id: state.current.id, name: state.current.name } : null
            };
        }
        // 快捷合成是弹窗（不再切到独立页面）；后端加载稍晚时用事件兜底
        if (window.ILBBFastCompose && window.ILBBFastCompose.open) {
            window.ILBBFastCompose.open(detail);
            return;
        }
        document.dispatchEvent(new CustomEvent('ilbb:fastcompose',
            { detail: detail }));
    }

    // ---------------------------------------------------------------- 快捷指令
    // 前缀不写死：/、# 等由后台「指令前缀」决定，bootstrap 回填 state.prefix
    var COMMANDS = [
        { path: 'help', desc: '指令总览' },
        { path: 'meme help', desc: '全部表情与用法' },
        { path: 'meme help 举牌', desc: '单个表情的参数教程（含预设样式）' },
        { path: 'meme 摸头', desc: '按关键词生成表情' },
        { path: 'pair help', desc: '配对卡用法' },
        { path: 'quote help', desc: '名言图用法' },
        { act: 'compose', code: '快捷合成', desc: '名言图 / 配对卡 / Meme 面板' }
    ];
    function commandText(c) {
        return c.act ? c.code : (state.prefix + c.path);
    }
    function renderCommands() {
        if (!el.cmdList) { return; }
        el.cmdList.innerHTML = COMMANDS.map(function (c, i) {
            return '<div class="wq-cmd-item' + (c.act ? ' act' : '') +
                '" data-i="' + i + '">' +
                '<span class="wq-cmd-code">' + esc(commandText(c)) + '</span>' +
                '<span class="wq-cmd-desc">' + esc(c.desc) + '</span>' +
            '</div>';
        }).join('');
    }
    function showCmd(show) {
        if (!el.cmdPanel) { return; }
        el.cmdPanel.classList.toggle('hidden', !show);
        el.cmdBtn.classList.toggle('active', !!show);
        if (show) { hideEmoji(); hideAt(); }
    }
    function hideCmd() {
        if (!el.cmdPanel) { return; }
        el.cmdPanel.classList.add('hidden');
        el.cmdBtn.classList.remove('active');
    }

    // ---------------------------------------------------------------- 事件绑定
    var bound = false;
    function bindEvents() {
        if (bound) { return; }
        bound = true;

        renderEmojiGrid();

        el.tabs.addEventListener('click', function (e) {
            var b = e.target.closest('button[data-wq-tab]');
            if (b) { setTab(b.getAttribute('data-wq-tab')); }
        });
        Array.prototype.forEach.call(root.querySelectorAll('.wq-rail-btn'), function (b) {
            var nav = b.getAttribute('data-wq-nav');
            if (nav) {
                b.addEventListener('click', function () { setTab(nav); });
                return;
            }
            b.addEventListener('click', function () {
                var view = b.getAttribute('data-wq-goto');
                if (view === 'fastcompose') { gotoCompose(null); return; }
                var sw = document.querySelector('.view-switch[data-view="' + view + '"]');
                if (sw) { sw.click(); }
            });
        });

        el.search.addEventListener('input', function () {
            state.filter = el.search.value || '';
            renderContacts();
        });

        el.contacts.addEventListener('click', function (e) {
            var ap = e.target.closest('[data-approve]');
            if (ap) { e.preventDefault(); approveNotice(ap); return; }
            var row = e.target.closest('.wq-contact');
            if (row) {
                selectChat(row.getAttribute('data-type'), row.getAttribute('data-id'));
                return;
            }
            // 通知只是信息展示：不再点击跳转到对应群 / 好友
        });
        el.contacts.addEventListener('contextmenu', function (e) {
            var row = e.target.closest('.wq-contact');
            if (!row) { return; }
            e.preventDefault();
            var type = row.getAttribute('data-type');
            var id = row.getAttribute('data-id');
            var meta = metaOf(type, id);
            var items = [
                { label: '打开会话', fn: function () { selectChat(type, id); } },
                { label: type === 'group' ? '查看群成员' : '戳一戳', fn: function () {
                    selectChat(type, id);
                    setTimeout(function () {
                        if (type === 'group') { openMembers(); }
                        else { doPoke(id, meta.name); }
                    }, 140);
                } },
                { sep: true },
                { label: '复制' + (type === 'group' ? '群号' : 'QQ 号'),
                  fn: function () { copyText(id); } }
            ];
            if (type === 'group') {
                items.push({ sep: true });
                items.push({ label: '查看 / 发布群公告', fn: function () {
                    selectChat(type, id);
                    setTimeout(openGroupPanel, 160);
                } });
            }
            showMenu(e.clientX, e.clientY, items);
        });

        // 群成员右键：@ / 戳一戳 / 禁言 / 移出本群（最后两项仅群主·管理员可见）
        el.memberList.addEventListener('contextmenu', function (e) {
            var row = e.target.closest('.wq-member');
            if (!row || !isGroup()) { return; }
            e.preventDefault();
            var uid = row.getAttribute('data-uid');
            var name = row.getAttribute('data-name');
            var role = row.getAttribute('data-role') || '';
            var items = [
                { label: '@ ' + (name || uid), fn: function () { pickAt(uid, name); } },
                { label: '戳一戳 ' + (name || ''), fn: function () { doPoke(uid, name); } }
            ];
            if (canActOn(uid, role)) {
                items.push({ sep: true });
                items.push({ label: '禁言 10 分钟', fn: function () { doBan(uid, name, 600); } });
                items.push({ label: '禁言 1 小时', fn: function () { doBan(uid, name, 3600); } });
                items.push({ label: '禁言 1 天', fn: function () { doBan(uid, name, 86400); } });
                items.push({ label: '解除禁言', fn: function () { doBan(uid, name, 0); } });
                items.push({ label: '移出本群', danger: true, fn: function () { doKick(uid, name); } });
            }
            items.push({ sep: true });
            items.push({ label: '复制 QQ 号', fn: function () { copyText(uid); } });
            showMenu(e.clientX, e.clientY, items);
        });

        // 群管理面板（群公告）
        if (el.groupBtn) {
            el.groupBtn.addEventListener('click', function () {
                if (!isGroup()) { return; }
                if (el.groupPanel.classList.contains('hidden')) { openGroupPanel(); }
                else { closeGroupPanel(); }
            });
        }
        el.groupClose.addEventListener('click', closeGroupPanel);
        if (el.fwdClose) { el.fwdClose.addEventListener('click', closeForwardPicker); }
        if (el.fwdSearch) {
            el.fwdSearch.addEventListener('input', function () {
                renderForwardTargets(el.fwdSearch.value);
            });
        }
        if (el.fwdList) {
            el.fwdList.addEventListener('click', function (e) {
                var row = e.target.closest('.wq-fwd-row');
                var st = state.fwd;
                if (!row || !st) { return; }
                var type = row.getAttribute('data-type');
                var id = row.getAttribute('data-id');
                var name = row.getAttribute('data-name') || id;
                var msgs = st.msgs;
                var mode = st.mode;
                closeForwardPicker();
                forwardSelected(msgs, mode, type, id, name);
            });
        }
        el.noticeRefresh.addEventListener('click', function () {
            loadRole(state.current.id, true).then(function () { loadNotices(state.current.id); });
        });
        el.noticeSend.addEventListener('click', publishNotice);
        if (el.noticeImageBtn) {
            el.noticeImageBtn.addEventListener('click', function () {
                if (!canManage()) { toast('只有群主 / 管理员可以发布公告', true); return; }
                el.noticeImage.click();
            });
        }
        if (el.noticeImage) {
            el.noticeImage.addEventListener('change', function () {
                readNoticeImage(el.noticeImage.files && el.noticeImage.files[0]);
            });
        }
        if (el.noticeImgClear) {
            el.noticeImgClear.addEventListener('click', clearNoticeImage);
        }
        el.noticeList.addEventListener('click', function (e) {
            var b = e.target.closest('[data-notice-use]');
            if (!b) { return; }
            var card = b.closest('.wq-notice-item');
            if (!card) { return; }
            el.noticeInput.value = card.getAttribute('data-text') || '';
            el.noticeInput.focus();
        });

        el.refresh.addEventListener('click', function () {
            el.refresh.classList.add('spin');
            load(true).then(function () {
                if (state.current && state.current.type === 'group' &&
                    !el.members.classList.contains('hidden')) {
                    loadMembers(state.current.id, true, renderMembers);
                }
            }).then(function () {
                el.refresh.classList.remove('spin');
            });
        });

        el.send.addEventListener('click', doSend);
        el.input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                doSend();
            }
        });
        el.input.addEventListener('input', autoGrow);

        el.imageBtn.addEventListener('click', function () { el.file.click(); });
        el.file.addEventListener('change', function () {
            addFiles(el.file.files);
            el.file.value = '';
        });
        el.attach.addEventListener('click', function (e) {
            var x = e.target.closest('.wq-attach-x');
            if (!x) { return; }
            var box = x.closest('.wq-attach-item');
            var i = parseInt(box.getAttribute('data-i'), 10);
            state.attachments.splice(i, 1);
            renderAttachments();
        });

        el.emojiBtn.addEventListener('click', function () {
            showEmoji(el.emojiPanel.classList.contains('hidden'));
        });
        el.emojiClose.addEventListener('click', hideEmoji);
        el.emojiGrid.addEventListener('click', function (e) {
            var b = e.target.closest('button[data-face]');
            if (!b) { return; }
            var id = String(b.getAttribute('data-face'));
            var nm = faceName(id);
            if (nm) {
                // 新版表情大多没有对应的 Unicode 字符，用 QQ 自己的 /名称 文本占位，
                // 发送时再解析回 face 段（和 QQ 手打 /捂脸 的效果一致）
                insertText('/' + nm);
                state.faceTokens.push({ ch: '/' + nm, id: id });
                return;
            }
            var ch = FACE_CHAR_BY_ID[id];
            if (ch) {
                insertText(ch);
                state.faceTokens.push({ ch: ch, id: id });
            }
        });

        el.atBtn.addEventListener('click', openAt);
        el.atClose.addEventListener('click', hideAt);
        el.atList.addEventListener('click', function (e) {
            var it = e.target.closest('[data-qq]');
            if (!it) { return; }
            pickAt(it.getAttribute('data-qq'), it.getAttribute('data-name'));
        });

        el.replyClose.addEventListener('click', function () {
            state.replyTo = null;
            renderReply();
        });

        if (el.syncBtn) { el.syncBtn.addEventListener('click', syncCurrent); }
        el.pokeBtn.addEventListener('click', headerPoke);
        el.memberBtn.addEventListener('click', toggleMembers);
        el.membersClose.addEventListener('click', closeMembers);
        el.memberSearch.addEventListener('input', function () {
            state.memberFilter = el.memberSearch.value || '';
            renderMembers();
        });

        var memberTimer = null;
        el.memberList.addEventListener('click', function (e) {
            var row = e.target.closest('.wq-member');
            if (!row) { return; }
            if (memberTimer) { clearTimeout(memberTimer); }
            memberTimer = setTimeout(function () {
                memberTimer = null;
                pickAt(row.getAttribute('data-uid'), row.getAttribute('data-name'));
            }, 220);
        });
        el.memberList.addEventListener('dblclick', function (e) {
            var row = e.target.closest('.wq-member');
            if (!row) { return; }
            if (memberTimer) { clearTimeout(memberTimer); memberTimer = null; }
            doPoke(row.getAttribute('data-uid'), row.getAttribute('data-name'));
        });

        el.stream.addEventListener('click', function (e) {
            if (state.selecting) {
                var node = e.target.closest('.wq-msg');
                if (node) {
                    var sel = msgByKey(node.getAttribute('data-mkey'));
                    if (sel) { toggleSelect(sel); }
                    return;
                }
            }
            var fwd = e.target.closest('.wq-forward');
            if (fwd) {
                // 只点标题栏展开/收起，点里面的图片/视频仍走原来的预览逻辑
                if (e.target.closest('.wq-forward-head')) { toggleForward(fwd); return; }
            }
            var img = e.target.closest('img.wq-seg-img, img.wq-seg-mface');
            if (img) { openViewer(img.getAttribute('src')); return; }
            var actBtn = e.target.closest('[data-act]');
            if (actBtn) {
                var msg = actBtn.closest('.wq-msg');
                if (!msg) { return; }
                var it = msgByKey(msg.getAttribute('data-mkey'));
                if (actBtn.getAttribute('data-act') === 'reply') {
                    setReply(it || findMsg(msg.getAttribute('data-mid')));
                } else if (actBtn.getAttribute('data-act') === 'menu') {
                    var r = actBtn.getBoundingClientRect();
                    showMenu(r.left + 6, r.bottom + 4, messageMenu(it));
                }
            }
        });
        el.stream.addEventListener('contextmenu', function (e) {
            var node = e.target.closest('.wq-msg');
            if (!node || !state.current) { return; }
            var it = msgByKey(node.getAttribute('data-mkey'));
            if (!it) { return; }
            e.preventDefault();
            if (state.selecting) { toggleSelect(it); return; }
            showMenu(e.clientX, e.clientY, messageMenu(it));
        });
        el.stream.addEventListener('dblclick', function (e) {
            var av = e.target.closest('.wq-msg-avatar');
            if (av && state.current) {
                doPoke(av.getAttribute('data-uid'), av.getAttribute('data-name'));
            }
        });
        el.stream.addEventListener('error', function (e) {
            var img = e.target;
            if (!img || !img.classList) { return; }
            if (img.classList.contains('wq-seg-face-img')) {
                var sp = document.createElement('span');
                sp.className = 'wq-seg-face';
                sp.textContent = img.getAttribute('data-fb') || '';
                if (img.parentNode) { img.parentNode.replaceChild(sp, img); }
                return;
            }
            if (!img.classList.contains('wq-seg-img')) { return; }
            var card = document.createElement('div');
            card.className = 'wq-card';
            card.textContent = '[图片加载失败]';
            if (img.parentNode) { img.parentNode.replaceChild(card, img); }
        }, true);
        el.stream.addEventListener('scroll', function () { /* 保持简单：新消息只在贴近底部时贴底 */ });

        if (el.multiBar) {
            el.multiBar.addEventListener('click', function (e) {
                var b = e.target.closest('button[data-mact]');
                if (b) { multiAction(b.getAttribute('data-mact')); }
            });
        }
        if (el.menu) {
            el.menu.addEventListener('click', function (e) {
                var b = e.target.closest('button[data-mi]');
                if (!b) { return; }
                var fn = menuActions[b.getAttribute('data-mi')];
                hideMenu();
                if (fn) {
                    try { fn(); } catch (err) { /* 忽略单个菜单动作异常 */ }
                }
            });
        }

        if (el.cmdBtn) {
            renderCommands();
            el.cmdBtn.addEventListener('click', function () {
                showCmd(el.cmdPanel.classList.contains('hidden'));
            });
            el.cmdClose.addEventListener('click', hideCmd);
            el.cmdList.addEventListener('click', function (e) {
                var row = e.target.closest('.wq-cmd-item');
                if (!row) { return; }
                var c = COMMANDS[parseInt(row.getAttribute('data-i'), 10)];
                hideCmd();
                if (!c) { return; }
                if (c.act === 'compose') { gotoCompose(null); return; }
                insertText(commandText(c) + ' ');
                el.input.focus();
            });
        }

        // 图片预览
        el.viewerClose.addEventListener('click', closeViewer);
        el.viewer.addEventListener('click', function (e) {
            if (e.target === el.viewer) { closeViewer(); }
        });
        el.viewerIn.addEventListener('click', function () {
            vwZoomAt(window.innerWidth / 2, window.innerHeight / 2, 1.25);
        });
        el.viewerOut.addEventListener('click', function () {
            vwZoomAt(window.innerWidth / 2, window.innerHeight / 2, 0.8);
        });
        el.viewerReset.addEventListener('click', vwReset);
        el.viewer.addEventListener('wheel', function (e) {
            e.preventDefault();
            vwZoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY / 420));
        }, { passive: false, capture: true });
        el.viewerImg.addEventListener('dblclick', vwReset);
        el.viewerImg.addEventListener('pointerdown', function (e) {
            vw.down = true; vw.moved = false;
            vw.sx = e.clientX; vw.sy = e.clientY;
            vw.ox = vw.x; vw.oy = vw.y;
            el.viewerImg.classList.add('dragging');
            try { el.viewerImg.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
        });
        el.viewerImg.addEventListener('pointermove', function (e) {
            if (!vw.down) { return; }
            var dx = e.clientX - vw.sx, dy = e.clientY - vw.sy;
            if (Math.abs(dx) > 2 || Math.abs(dy) > 2) { vw.moved = true; }
            vw.x = vw.ox + dx;
            vw.y = vw.oy + dy;
            vwApply();
        });
        el.viewerImg.addEventListener('pointerup', function (e) {
            vw.down = false;
            el.viewerImg.classList.remove('dragging');
            try { el.viewerImg.releasePointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
        });

        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') { return; }
            if (!el.viewer.classList.contains('hidden')) { closeViewer(); return; }
            if (el.menu && !el.menu.classList.contains('hidden')) { hideMenu(); return; }
            if (el.fwdPanel && !el.fwdPanel.classList.contains('hidden')) {
                closeForwardPicker();
                return;
            }
            if (el.groupPanel && !el.groupPanel.classList.contains('hidden')) {
                closeGroupPanel();
                return;
            }
            if (state.selecting) { exitSelect(); return; }
            closePopups();
        });
        document.addEventListener('click', function (e) {
            if (!root.contains(e.target)) { return; }
            var t = e.target;
            if (!el.emojiPanel.contains(t) && !el.emojiBtn.contains(t)) { hideEmoji(); }
            if (!el.atPanel.contains(t) && !el.atBtn.contains(t)) { hideAt(); }
            if (el.cmdPanel && !el.cmdPanel.contains(t) && !el.cmdBtn.contains(t)) {
                hideCmd();
            }
            if (el.menu && !el.menu.contains(t)) { hideMenu(); }
        });
    }

    // ---------------------------------------------------------------- 视图联动
    var switches = document.querySelectorAll('.view-switch');
    Array.prototype.forEach.call(switches, function (b) {
        b.addEventListener('click', function () {
            if (b.getAttribute('data-view') === 'webqq') { start(); } else { stop(); }
        });
    });
    var active = document.querySelector('.view-switch.active');
    if (active && active.getAttribute('data-view') === 'webqq') { start(); }
})();

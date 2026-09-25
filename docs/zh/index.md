# ILBB 文档

[English](../en/index.md) ｜ **中文**

本目录是「我在哔哩学习 Emoji Bot（ILBB）」的完整文档。README 只讲"是什么、怎么最快跑起来"，细节都在这里。

---

## 从这里开始

**第一次接触这个项目** → 先看根目录的 [README](../../README.md)，按「快速开始」把服务在本机跑起来，再回来看文档。

**已经跑起来了** → 按下面的表挑你想做的事。

| 我想…… | 看这篇 | 英文版 |
| --- | --- | --- |
| 在 Windows 上部署 | [deploy-windows.md](deploy-windows.md) | [English](../en/deploy-windows.md) |
| 在 Linux 上部署 | [deploy-linux.md](deploy-linux.md) | [English](../en/deploy-linux.md) |
| 在安卓手机上部署 | [deploy-android.md](deploy-android.md) | [English](../en/deploy-android.md) |
| 搞清楚所有指令怎么用 | [commands.md](commands.md) | [English](../en/commands.md) |
| 自己写一个插件 | [plugin-dev.md](plugin-dev.md) | [English](../en/plugin-dev.md) |
| 把 QQ（NapCat）接上来 | [platform-integration.md](platform-integration.md) | [English](../en/platform-integration.md) |
| 查某个配置项是干什么的 | [configuration.md](configuration.md) | [English](../en/configuration.md) |

---

## 三条部署路线怎么选

| 场景 | 推荐路线 | 理由 |
| --- | --- | --- |
| 个人电脑上自己玩、调试 | **Windows** | 一条命令启动，引导页点完就能用 |
| 长期挂机、给群里用 | **Linux** | 稳定、省资源，可配 systemd 守护与自动重启 |
| 没有服务器、只有旧手机 | **Android** | Termux 里跑得起来，但**未充分验证**，当作实验性方案 |

> 无论走哪条路线，都建议先在 Windows 或 Linux 上把 `/setup` 引导页跑通、把素材下载完，再考虑迁移。

---

## 全部平台共用的三个概念

理解这三个东西，文档读起来会顺很多。

**1. 配置有三层，优先级从高到低**
系统环境变量 → `.env` 文件 → 代码内置默认值。引导页和后台面板改的值会写回文件，效果和手改 `.env` 一样。

**2. 启动必须在项目根目录**
项目里 `cache`、`temp`、`font` 走的是相对路径。在别的目录启动会报找不到目录。

**3. ILBB 是 WebSocket 服务端，NapCat 是客户端**
不是 ILBB 去连 NapCat，而是 NapCat 以「反向 WebSocket」连到 ILBB 的 `6700` 端口。方向搞反了永远连不上。详见 [platform-integration.md](platform-integration.md)。

---

## 一句话架构

```
QQ 客户端
   │  （NapCat 登录 QQ）
   ▼
NapCat ──反向 WebSocket──▶ core/ws_server.py（6700 端口）
                              │
                              ├─▶ core/bot_commands.py  指令路由（/meme /pair /quote）
                              │        └─▶ core/meme_service.py  表情合成
                              │        └─▶ core/bot_render.py   帮助图渲染
                              │        └─▶ plugin_manager     插件指令
                              │
                              └─▶ app.py（Flask，5000 端口）WebUI / REST / OpenAI 兼容层 /v1
```

---

## 遇到问题

1. 先看对应部署文档末尾的「常见问题」。
2. 再看根目录 README 的「常见问题」。
3. 还不行就启动时看终端日志——ILBB 的日志是中文的，绝大多数报错会直接告诉你缺什么、要装什么。

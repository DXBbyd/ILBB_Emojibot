# ILBB 文档

[English](../en/index.md) ｜ **中文**

本目录是「我在哔哩学习 Emoji Bot（ILBB）」的完整文档。根目录的 [README](../../README.md) 只讲这个项目是什么，部署与使用的细节全在这里。

---

## 从这里开始

**第一次部署** → 进 [选择部署方式](deploy.md)，按你的机器挑一条路线。三条路线都要用 uv 建环境、装依赖，公共部分也写在那篇里。

**已经跑起来了** → 直接在下面按分类找要看的东西。

---

## 部署

| 内容 | 入口 | 英文版 |
| --- | --- | --- |
| 三条路线怎么选、共有前置与 uv 用法 | [选择部署方式](deploy.md) | [English](../en/deploy.md) |
| 在 Windows 上部署 | [deploy-windows.md](deploy-windows.md) | [English](../en/deploy-windows.md) |
| 在 Linux 上部署 | [deploy-linux.md](deploy-linux.md) | [English](../en/deploy-linux.md) |
| 在安卓手机上部署 | [deploy-android.md](deploy-android.md) | [English](../en/deploy-android.md) |

## 使用

| 内容 | 入口 | 英文版 |
| --- | --- | --- |
| 所有指令怎么用 | [commands.md](commands.md) | [English](../en/commands.md) |
| 每个配置项是干什么的 | [configuration.md](configuration.md) | [English](../en/configuration.md) |
| 把 QQ（NapCat）接上来 | [platform-integration.md](platform-integration.md) | [English](../en/platform-integration.md) |

## 开发

| 内容 | 入口 | 英文版 |
| --- | --- | --- |
| 自己写一个插件 | [plugin-dev.md](plugin-dev.md) | [English](../en/plugin-dev.md) |

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
                              ├─▶ core/bot_commands.py  指令路由（/meme /pair /名言）
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

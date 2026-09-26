# Command Manual

**English** ｜ [中文](../zh/commands.md) ｜ [Docs Home](index.md)

This document covers all ILBB commands in QQ (OneBot V11). Every command can be dry-run previewed in the "Command Center" of the WebUI, so you do not need to actually send it to a group to try it out.

---

## 1. Trigger Rules

| Rule | Controlled by | Default |
| --- | --- | --- |
| Command prefix | `BOT_PREFIX` | `/` (at most 3 characters, can be changed to `#` etc.) |
| Whether group chats must @ the bot | `BOT_GROUP_NEED_AT` | `false` (just send `/help` and it replies) |
| Whether private chats are allowed | `BOT_ALLOW_PRIVATE` | `true` |
| Minimum interval for the same user's commands | `BOT_COOLDOWN_SEC` | `3` seconds (silently ignored during cooldown) |
| Master switch for commands | `BOT_ENABLED` | `true` (set to `false` and everything is silent, including `/help`) |

A few behaviors that are easy to overlook:

- When group chats require @-ing the bot, the form **without the prefix**, such as `@机器人 /meme 摸头`, is also recognized.
- The bot **does not reply to its own messages** (when `self_id` equals the sender it is skipped outright), so it never talks to itself.
- During the cooldown period **no hint is given at all**; the command is simply ignored, to avoid spamming the chat.
- The bot only handles `message` type events; notices, requests, and meta events are only shown in the backend logs and the event stream, and get no response.

---

## 2. Command Overview

| Command | Aliases | Purpose |
| --- | --- | --- |
| `/help` | `/菜单` `/menu` `/?` `/？` | Returns the image-based command overview menu |
| `/meme` | `/表情` `/生图` | Emoji generation (表情 = emoji, 生图 = generate image) |
| `/pair` | `/配对` `/卡片` | Generates a QQ-style pairing card (配对 = pairing, 卡片 = card) |
| `/quote` | `/名言` `/名言图` | Generates a quote image (名言 = famous quote, 名言图 = quote image) |
| `<插件触发词>` | — | Declared by the plugin's `plugin.json` |

> If you send any unknown word other than `/help` on its own, the bot replies with a hint image saying "there is no such command" and tells you to use `/help` to see all commands.

---

## 3. `/help` —— Image Menu

```
/help
```

Returns a well-laid-out **image** menu (not text), containing:

- The usage and a one-line description of every command
- Effect previews of 4 real assets
- The total asset count and a signature line (the signature text is controlled by `BOT_FOOTER`)

It stays legible on mobile too, so it is suitable for forwarding directly to group members as an instruction sheet.

---

## 4. `/meme` —— Emoji Generation

### 4.1 Three Ways to Use It

```
/meme                      打开表情生成器用法说明（帮助图）
/meme list [页码/关键词]    浏览 / 搜索素材
/meme help [ID]            单个表情的图文教程
/meme [关键词] [文本…]      直接合成表情
```

### 4.2 Direct Composition

```
/meme 摸头
/meme 摸头 你好呀
/meme 摸头 @某人
/meme 摸头 10001
/meme 摸头 文本1 文本2
```

Parameter parsing rules (in this order):

1. **`key=value`** —— if the key name is a preset option supported by that emoji, it is used as a preset parameter, for example `mode=loop`, `num=3`, `name=小明`. Separate multiple presets with spaces; the order does not matter.
2. **`@某人`** —— extracts the QQ number of the @-ed person for later use.
3. **5~12 pure digits** —— treated as a QQ number (therefore **text that happens to be 5~12 digits will be treated as a QQ number**; put such text in another position or switch to the `key=value` form).
4. **Everything else** —— treated as a text segment, corresponding in order to the 1st, 2nd… text segments the emoji requires.

### 4.3 How to Supply Images

| Method | How to write it | Explanation |
| --- | --- | --- |
| Attach images directly | Send the command together with the images | The images are used as the 1st, 2nd… assets in sending order |
| Quote an image | Reply to a message with an image, then send the command | Uses the image(s) in the quoted message |
| @ someone | `/meme 摸头 @群友` | The bot takes their avatar as the asset |
| Write a QQ number | `/meme 摸头 10001` | The bot takes that QQ account's avatar as the asset, no image needed |

When there are not enough images, the bot **automatically fills in avatars in the order of "the people @-ed first, then the QQ numbers in the command"**. So for an emoji needing 2 images, `/meme 亲亲 @A @B` works directly.

### 4.4 Browsing and Searching Assets

```
/meme list            第 1 页
/meme list 3          第 3 页
/meme list 摸头        按关键词搜索
/meme list 2 摸头      搜索结果的第 2 页
```

The number of entries per page is controlled by `BOT_MEME_LIST_PAGE` (default 12); anything beyond that is automatically split into multiple images to send. Every asset in the list carries a **list ID** for use by the next command.

### 4.5 Viewing the Tutorial for a Single Emoji

```
/meme help 42
```

Returns one image containing the emoji's base image, name, **supported preset options and their values**, how many images are needed, how many text segments are needed, and a usage example. Send this first whenever you are unsure how to use an emoji.

### 4.6 Preset Parameters

Different emojis support completely different presets (for example `mode=loop`, `num=3`, `name=小明`); **there is no unified list**, so check with `/meme help [ID]`.

### 4.7 Common Errors

| Message | Cause | What to do |
| --- | --- | --- |
| 找不到这个表情 (cannot find this emoji) | The keyword is misspelled, or the assets have not been downloaded | Search for the correct name with `/meme list 关键词`; confirm that assets were downloaded in the wizard page |
| 图片数量不对 (wrong number of images) | That emoji requires a fixed number of images | Add or remove images as prompted, or @ more people |
| 文本数量不对 (wrong number of text segments) | The number of text segments does not match what the emoji requires | Refer to the description in `/meme help [ID]` |
| 文字太长 (text too long) | A single text segment exceeds that emoji's limit | Shorten the text |
| 图片过大 (image too large) | Exceeds `BOT_MAX_IMAGE_MB` | The bot will try to compress; if it cannot, it gives up |

---

## 5. `/pair` —— Pairing Card

Generates a QQ-style pairing card (avatar + title + buttons), the same as the pairing generator in the WebUI.

```
/pair                        帮助图
/pair 10001                  用 QQ 号 10001 的头像
/pair 10001 我们的配对结果     带标题
/pair @某人 我们的配对结果     群里 @ 群友
```

### Optional Parameters

| Parameter | Values | Explanation |
| --- | --- | --- |
| `template=` | `classic` / `dark` / `paper` | Template: classic popup (light blue glass, default) / deep glass / fresh paper |
| `title=` | Any text | Card title; use `title=` when the title contains spaces, it is more reliable |
| `bg=` | `random` / `color` / `gradient` / `image` | Background: random (default) / solid color / gradient / image |
| `btn=` | Text separated by `|` | Button text, up to 4, for example `btn=配对|接受|拒绝` |

### Examples

```
/pair 10001 我们的配对结果
/pair 10001 title=今天的缘分 template=paper
/pair @某人 btn=接受|拒绝 bg=gradient
```

---

## 6. `/quote` —— Quote Image

Give it an avatar + a sentence (or an emoji/sticker image) and it composes a quote image, output as JPG.

```
/quote 这就是名言                     署名默认是发送者昵称（群聊取群名片）
/quote @某人 这就是名言                用被 @ 者的头像与昵称
/quote 10001 这就是名言               直接写 QQ 号
/quote help                          帮助图
```

Structure of the result:

- **Layout** —— landscape 16:9 (`QUOTE_WIDTH` × `QUOTE_HEIGHT`, default 1280×720): an independent rounded rectangle avatar on the left, and a white frosted-glass panel filling the right half, holding the text or emoji/sticker
- **Background** —— a random anime image from the same API as the home page background (`BG_API`), with a grey mask layered over it (`QUOTE_MASK_ALPHA`, default `0.35` = 35% grey, the background stays recognisable); the glass panel, avatar and text are all drawn above the mask
- **Frosted-glass panel** —— fills the right half (full height): the background inside it is blurred as a whole (`QUOTE_TRAY_BLUR`, default `30`), then a warm white glass layer (`QUOTE_TRAY_GLASS`, default `0.58`) and a top highlight are added on top; its left edge fades out through a horizontal gradient (`QUOTE_TRAY_FADE`) so the left border is fully transparent and blends into the middle background without a hard edge; text automatically tries font sizes from large to small and truncates with an ellipsis if it does not fit, while emoji/stickers scale adaptively
- **Avatar** —— an independent rounded rectangle avatar on the left (`QUOTE_AVATAR`, default width 236, height = width × 1.32); a built-in placeholder is used when none is given
- **Signature** —— "—— 用户名" in the bottom right corner; its font follows the global `FONT_FAMILY` and is no longer configurable on its own

Output: a JPG when the panel content is static, a GIF when it is an animated emoji/sticker (**the animation is preserved**). The "Quote image" form in the web UI lets you switch the global font directly (the same ILBB custom dropdown as the home page), and the signature follows it.

All layout-related parameters are adjustable; see [configuration.md](configuration.md#4-quote-image-quote).

> To turn this feature off: `QUOTE_ENABLED=false`; in that case it only replies with a hint image.

---

## 7. Plugin Commands

Plugins can register their own trigger words, and the usage is defined by the plugin itself:

```
/<插件触发词> [参数…]
```

The `plugins/example/` sample plugin registers:

| Command | Purpose |
| --- | --- |
| `/example` | Replies with a sample message (demonstrating config options and image replies) |
| `/echodemo 内容` | Echoes the content back verbatim |
| `/exampleinfo` | Shows the plugin's current configuration and runtime information |

The parsing priority of plugin commands is **lower than built-in commands**: if a plugin trigger word collides with `/meme`, the built-in command wins. When writing a plugin, avoid the built-in names (`help` `menu` `meme` `表情` `生图` `pair` `配对` `卡片` `quote` `名言` `名言图`).

See [plugin-dev.md](plugin-dev.md) for details.

---

## 8. Trying Commands in the WebUI

If you do not want to actually send to a group, use the WebUI's **Command Center**:

| Mode | Behavior |
| --- | --- |
| **Dry run preview** | Does not fetch images over the network; avatars for @ / QQ numbers are substituted with local placeholder images; the decision logic is exactly the same as a real send |
| **Web session** | Follows a real send completely, including fetching QQ avatars over the network |

The two share the same block of command parsing code (`run_command()`), so the preview result is the real result.

---

## 9. Quick Reference Card

```
/help                                菜单（图片）
/meme                                表情生成帮助
/meme 摸头 你好呀                     合成表情
/meme 摸头 @某人                      用群友头像当素材
/meme 摸头 10001                      用 QQ 头像当素材
/meme 摸头 mode=loop num=3            带预设参数
/meme list                           素材列表第 1 页
/meme list 摸头                       搜索素材
/meme help 42                        第 42 号表情的教程
/pair 10001 我们的配对结果             配对卡片
/pair @某人 template=paper btn=A|B    带模板与按钮
/quote 这就是名言                     名言图
/quote @某人 这就是名言                指名道姓的名言图
```

[Back to docs home](index.md) ｜ [中文](../zh/commands.md)

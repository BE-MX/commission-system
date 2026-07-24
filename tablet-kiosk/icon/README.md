# APP 图标（品牌花体 S）

**墨底金 S**——主体是品牌字标 `leshine-logo-gold.png` 里那个花体 **S**，按连通域从原图
**原尺抠出**（bbox `424,57,1220,772`），保留手写笔锋，不是重画的字母。配色沿用 kiosk 页面的黑金语系
（墨底 `#0c0a08`，金渐变 `#f7e3b0 → #D4941C`）。

## 为什么是 S 而不是完整 logo

APP 图标实际显示只有 48–64dp，且 Android 自适应图标只有**中心 72dp 是安全区**（外围会被系统裁）。
- 完整字标 `leShine Hair` 塞进方形后每个字母只剩几像素，不可读
- 展会图形标（海棠+孔雀+侧脸）羽毛纹理在 48dp 下糊成一团色块——试过，废弃
- 花体 S 宽高比 1.11:1 近正方形、笔画连贯，是品牌资产里唯一扛得住这个尺寸的元素

试过但废弃的方向：四瓣海棠环承托 S（环与 S 在小尺寸互相干扰）、金环徽标（环退化成糊圈）、
金底墨 S（可读性更强，但与品牌「黑底金字」语系相反）。

## 重新生成

一条命令，从品牌字标直出全套资源（路径全是项目相对，换机器不用改）：

```bash
cd backend && ./.venv/Scripts/python.exe ../tablet-kiosk/icon/build_icon.py
```

改大小调 `S_HEIGHT`（当前 232 = 安全区 288 的 80%，再大会顶到圆形 mask 边缘）；
换配色调 `INK` / `GOLD` 系常量；品牌字标换版时先重新探测 `S_BBOX`（连通域里面积最大的那个就是 S）。

## 产物

| 文件 | 用途 |
|---|---|
| `source_background.png` / `source_foreground.png` | 432×432 母版，自适应图标两层 |
| `preview_512.png` | 展示/文档用合成图 |
| `res/mipmap-*/ic_launcher_{background,foreground,monochrome}.png` | 自适应图标三层，五档密度 |
| `res/mipmap-*/ic_launcher{,_round}.png` | legacy 回退（部分启动器仍读），48dp 五档 |

`monochrome` 层供 Android 13+ 主题图标使用，是 foreground 去掉金晕后的纯白剪影
（带晕染的 alpha 在单色染色下会糊成脏边）。

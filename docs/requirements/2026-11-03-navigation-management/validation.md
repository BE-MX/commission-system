# 导航管理设计验收记录

2026-11-03；验证对象为独立 HTML 原型，不是生产功能。

## 交付内容

- `README.md`：需求、范围、现状证据、层级/角标/权限规则、交互状态、版本机制、实施契约和验收标准。
- `prototype.html`、`prototype.css`、`prototype.js`：无需安装依赖的本地交互原型，可直接打开 HTML；通过本地 HTTP 预览时可稳定保存演示草稿。
- `snapshot.js`：由工作区 `navigation.js` 导出的展示快照，共 23 个现有一级分类、141 个现有入口，加 1 个拟新增的导航管理入口。
- `generate-snapshot.cjs`：重新生成上述快照的脚本，内置组件加载函数不会执行；输出含源文件 SHA-256，源文件变化时不复用旧原型缓存。
- `preview-desktop.jpg`、`preview-mobile.jpg`、`preview-publish.jpg`：实际浏览器截图。

## 已执行检查

| 检查 | 实际结果 |
|---|---|
| `node --check .../prototype.js`、`snapshot.js` | 通过 |
| 本地 HTTP GET `prototype.html` | 200 |
| HTML/文件静态检查 | 23 个 ID 唯一，4 个本地资源引用存在，本次新增文本无尾随空格 |
| `python scripts/check_conventions.py` | exit 0，增量无违规；保留既有 UI 债务基线 |
| `python scripts/git_sweep.py --no-fetch` | exit 0，生成本地快照看板；main 领先本地 origin/main 8 个提交，未对其他分支/工作区采取动作 |
| `git diff --check -- docs/handoff.md` | 发现既有文件末尾空行（本轮只插入文件顶部记录）；未顺手修改他人内容，不能报告整份 handoff 差异无警告 |
| 浏览器改名、图标搜索与选择、文字角标 | 实际操作通过 |
| 导航搜索、创建一级与二级分类、页面移至二级分类 | 实际操作通过 |
| 保存草稿、刷新恢复、预览发布差异、模拟发布 | 实际操作通过 |
| 恢复历史版本为草稿，再发布 | 实际操作通过；恢复后导航内容等同初始快照 |
| 折叠预览 | 实际操作通过 |
| 390×844 窄屏 | 搜索、选择、属性内容可用；三栏纵向堆叠，需向下滚动至编辑区 |
| 动效规范自查 | 无列表重排动画；toast 仅 opacity/transform 180ms ease-out；reduced-motion 关闭过渡 |

浏览器验收由 `gpt-6.1-terra` / `xhigh` 子代理执行，使用获准浏览器工具。流程测试产生过 V1/V2/V3 演示历史，V3 内容已恢复初始导航；全景补拍展示初始 V1。不同浏览器站点存储独立，这些版本不对应生产版本。

## 验证边界

- 未实现或测试真实服务端持久化、真实 RBAC、动态计数、并发版本冲突、多人同步与生产发布；这些由设计文档定义后续实现验收。
- 排序/删除/错误校验已提供原型交互，但本轮浏览器报告没有覆盖所有拖拽、键盘和异常组合，不将其称为完整测试覆盖。
- 本次新增的是设计文件，未运行与其无关的生产前端构建或数据库测试。约定检查的现有脚本不等于 HTML 原型视觉验收，实际浏览器检查单独列出。
- 主工作区原有改动保持，`docs/handoff.md` 仅增补本次设计记录；没有 commit、push、合并、部署或业务数据写入。

## 本地打开

直接打开 `prototype.html`。若浏览器限制 file URL 下的本地存储，可在本目录执行：

```powershell
python -m http.server 8874 --bind 127.0.0.1
```

然后访问 `http://127.0.0.1:8874/prototype.html`。演示数据只保存在该浏览器对应站点的 localStorage，键为 `ark-navigation-design-v1`。

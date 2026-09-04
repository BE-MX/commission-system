# Login ICP Footer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在主站登录页底部展示可点击的备案号与主办单位名称，并保证桌面端、移动端均可读。

**Architecture:** 仅修改现有 `LoginPage.vue`，把备案栏放在右侧登录区域内部并绝对定位到底部，因此不会依赖桌面端才显示的品牌区。新增一个 Node 源码回归测试，锁定备案文案、工信部链接、安全属性和响应式样式，不引入运行时依赖或后端接口。

**Tech Stack:** Vue 3 单文件组件、现有登录页 CSS、Node.js `node:test`

---

## File Map

- Create: `frontend/tests/loginIcpFooter.test.mjs` — 验证备案内容、链接、安全属性和布局约束。
- Modify: `frontend/src/views/auth/LoginPage.vue` — 渲染备案栏并提供桌面端、移动端样式。

### Task 1: 登录页备案栏

**Files:**
- Create: `frontend/tests/loginIcpFooter.test.mjs`
- Modify: `frontend/src/views/auth/LoginPage.vue`

- [ ] **Step 1: 写入失败的回归测试**

创建 `frontend/tests/loginIcpFooter.test.mjs`：

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/views/auth/LoginPage.vue', import.meta.url),
  'utf8',
)

test('login page exposes the ICP registration and organizer on every viewport', () => {
  const formSideIndex = source.indexOf('class="form-side')
  const filingIndex = source.indexOf('aria-label="网站备案信息"')

  assert.ok(formSideIndex >= 0, 'login form area should exist')
  assert.ok(filingIndex > formSideIndex, 'filing information should live in the always-visible form area')
  assert.match(source, />\s*鲁ICP备2023012060号-3\s*<\/a>/)
  assert.match(source, />\s*鄄城莱莎发制品有限公司\s*<\/span>/)
})

test('ICP registration opens the MIIT site safely in a new tab', () => {
  assert.match(
    source,
    /<a\s+href="https:\/\/beian\.miit\.gov\.cn\/"\s+target="_blank"\s+rel="noopener noreferrer"/,
  )
})

test('filing footer is pinned below the form and adapts on narrow screens', () => {
  assert.match(
    source,
    /\.site-filing\s*\{[\s\S]*?position:\s*absolute;[\s\S]*?bottom:\s*18px;/,
  )
  assert.match(source, /@media \(max-width:\s*640px\)\s*\{[\s\S]*?\.site-filing\s*\{[\s\S]*?flex-wrap:\s*wrap;/)
})
```

- [ ] **Step 2: 运行测试并确认因功能缺失而失败**

Run:

```bash
cd frontend
node --test tests/loginIcpFooter.test.mjs
```

Expected: 3 个测试失败，失败信息指向缺少备案栏、工信部链接和 `.site-filing` 样式。

- [ ] **Step 3: 写入最小页面实现**

把登录区根节点改为相对定位：

```vue
<div class="form-side relative flex-1 flex items-center justify-center p-6">
```

在登录卡片之后、登录区结束标签之前加入：

```vue
<footer
  class="site-filing will-animate animate-fade-in delay-650"
  aria-label="网站备案信息"
>
  <a
    href="https://beian.miit.gov.cn/"
    target="_blank"
    rel="noopener noreferrer"
  >鲁ICP备2023012060号-3</a>
  <span class="site-filing__divider" aria-hidden="true"></span>
  <span>鄄城莱莎发制品有限公司</span>
</footer>
```

在当前 scoped style 末尾加入：

```css
.form-side { padding-bottom: 76px; }

.site-filing {
  position: absolute; right: 24px; bottom: 18px; left: 24px;
  display: flex; align-items: center; justify-content: center; gap: 12px;
  font-size: 12px; line-height: 1.5; letter-spacing: 0.03em;
  color: rgba(255, 255, 255, 0.34);
}
.site-filing a {
  color: rgba(212, 175, 110, 0.68); text-decoration: none;
  transition: color 180ms ease;
}
.site-filing a:hover { color: rgba(249, 236, 198, 0.92); }
.site-filing a:focus-visible {
  outline: 1px solid currentColor; outline-offset: 4px; border-radius: 2px;
}
.site-filing__divider {
  width: 1px; height: 12px; flex: none;
  background: rgba(255, 255, 255, 0.16);
}
@media (max-width: 640px) {
  .form-side { padding-bottom: 88px; }
  .site-filing { bottom: 18px; flex-wrap: wrap; gap: 4px 10px; }
  .site-filing__divider { display: none; }
  .site-filing span:last-child { flex-basis: 100%; text-align: center; }
}
```

- [ ] **Step 4: 运行定向测试并确认通过**

Run:

```bash
cd frontend
node --test tests/loginIcpFooter.test.mjs
```

Expected: `3 pass, 0 fail`。

- [ ] **Step 5: 运行项目级验证**

Run:

```bash
python scripts/check_conventions.py
cd frontend
npm run build
```

Expected: 规范检查无红项，Vite 生产构建成功且无编译错误。

- [ ] **Step 6: 检查改动并提交**

Run:

```bash
git diff --check
git status --short
git branch --show-current
git add frontend/src/views/auth/LoginPage.vue frontend/tests/loginIcpFooter.test.mjs
git commit -m "feat: show ICP registration on login page"
```

Expected: 当前分支为 `codex/login-icp-footer`，提交只包含登录页与对应测试。

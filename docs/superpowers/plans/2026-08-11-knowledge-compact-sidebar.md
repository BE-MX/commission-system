# Knowledge Compact Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将企业知识库左栏改为知识库条目内嵌目录，并提高左栏和文档编辑区的信息密度。

**Architecture:** 保持现有 API、选中状态和目录数据流不变，只调整 `KnowledgeSidebar` 的 DOM 归属与知识库工作台相关 scoped CSS。目录树继续复用当前选中知识库的 `tree` 数据，因此同一时间只渲染一个展开目录，不增加额外请求或前端状态。

**Tech Stack:** Vue 3、Element Plus、Tiptap、scoped CSS、Node.js `node:test`

---

### Task 1: 锁定嵌套目录与紧凑密度契约

**Files:**
- Modify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] **Step 1: 写入失败回归测试**

新增测试，断言目录区域使用 `library.id === selectedLibraryId` 嵌在知识库循环内部，旧的列表尾部目录条件不存在；同时断言工作台左栏为 `280px`、正文为 `15px/1.7`、工具栏控件高度为 `30px`。

```js
test('selected library expands its directory tree inline with compact editor density', () => {
  const sidebar = read('../src/views/knowledge/components/KnowledgeSidebar.vue')
  const editor = read('../src/views/knowledge/components/KnowledgeEditor.vue')
  const toolbar = read('../src/views/knowledge/components/EditorToolbar.vue')
  const workbench = read('../src/views/knowledge/KnowledgeWorkbench.vue')
  assert.match(sidebar, /v-if="library\.id === selectedLibraryId" class="tree-section"/)
  assert.doesNotMatch(sidebar, /v-if="selectedLibraryId" class="tree-section"/)
  assert.match(workbench, /grid-template-columns:\s*280px minmax\(0,\s*1fr\)/)
  assert.match(editor, /font-size:\s*15px;\s*line-height:\s*1\.7/)
  assert.match(toolbar, /height:\s*30px/)
})
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run: `node --test tests/knowledgeEditor.test.mjs`

Expected: 新增用例因目录仍位于所有知识库下方且密度值尚未调整而失败。

### Task 2: 将目录树嵌入选中知识库

**Files:**
- Modify: `frontend/src/views/knowledge/components/KnowledgeSidebar.vue`

- [ ] **Step 1: 调整模板归属**

将每个知识库包装为 `.library-entry`，保留 `.library-row` 的选择和删除操作，并把目录标题、创建按钮及 `el-tree` 移入选中条目：

```vue
<div v-for="(library, index) in libraries" :key="library.id" class="library-entry">
  <div class="library-row" :class="{ active: library.id === selectedLibraryId }">...</div>
  <div v-if="library.id === selectedLibraryId" class="tree-section">...</div>
</div>
```

- [ ] **Step 2: 收紧左栏密度**

使用 13px 知识库文字、12px 目录文字、30–34px 行高、8px 列表内边距，并用左侧细边框表达目录从属于当前知识库。保留现有滚动、删除权限、状态点和 reduced-motion 规则。

- [ ] **Step 3: 运行目标测试**

Run: `node --test tests/knowledgeEditor.test.mjs`

Expected: 嵌套结构断言通过，编辑密度断言仍失败。

### Task 3: 压缩工作台与文档编辑区域

**Files:**
- Modify: `frontend/src/views/knowledge/KnowledgeWorkbench.vue`
- Modify: `frontend/src/views/knowledge/components/KnowledgeEditor.vue`
- Modify: `frontend/src/views/knowledge/components/EditorToolbar.vue`
- Modify: `frontend/src/views/knowledge/components/EditorOutline.vue`

- [ ] **Step 1: 压缩工作台框架**

将左栏从 300px 调整为 280px，页头和工作区外边距各减少 4px，并降低桌面最小高度限制；900px 以下仍保持现有单独响应式规则。

- [ ] **Step 2: 压缩编辑页头与画布**

标题调整为 22px，正文调整为 15px/1.7，正文最大阅读宽度从 780px 放宽至 840px；同步缩小标题区、正文画布、标题层级、引用、代码块和表格单元格间距。

- [ ] **Step 3: 压缩工具栏与大纲**

工具栏控件高度和最小宽度调整为 30px，工具栏内边距调整为 `5px 14px`；大纲宽度调整为 170px，字号 11.5–13px，缩小纵向间距。

- [ ] **Step 4: 运行目标测试**

Run: `node --test tests/knowledgeEditor.test.mjs`

Expected: 全部用例通过。

### Task 4: 验证并提交

**Files:**
- Verify: `frontend/src/views/knowledge/**`
- Verify: `frontend/tests/knowledgeEditor.test.mjs`

- [ ] **Step 1: 运行生产构建**

Run: `npm.cmd run build`

Expected: Vite 构建退出码为 0；允许保留项目已有的大 chunk 警告。

- [ ] **Step 2: 检查改动范围和动画规范**

Run: `git diff --check`

Expected: 无空白错误；不新增 `transition: all`、`ease-in`、布局属性动画或未受 reduced-motion 控制的移动动画。

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/plans/2026-08-11-knowledge-compact-sidebar.md frontend/tests/knowledgeEditor.test.mjs frontend/src/views/knowledge/KnowledgeWorkbench.vue frontend/src/views/knowledge/components/KnowledgeSidebar.vue frontend/src/views/knowledge/components/KnowledgeEditor.vue frontend/src/views/knowledge/components/EditorToolbar.vue frontend/src/views/knowledge/components/EditorOutline.vue
git commit -m "feat(knowledge): compact editor navigation"
```

<template>
  <div class="matrix-wrap" :class="{ readonly: matrix.readonly }">
    <table class="perm-matrix">
      <thead>
        <tr>
          <th class="mod">
            模块
            <span v-if="!matrix.readonly" class="cb" :class="matrix.allState" @click="matrix.toggleAll()" />
          </th>
          <th v-for="col in columns" :key="col.key">
            {{ col.label }}
            <span v-if="!matrix.readonly" class="cb" :class="matrix.colState(col.key)" @click="matrix.toggleCol(col.key)" />
          </th>
          <th class="special-col">特殊（数据范围 / 业务动作）</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="group in treeGroups" :key="group.label">
          <tr class="grp" @click="toggleFoldGroup(group.label)">
            <td :colspan="columns.length + 2">
              <div class="grp-line">
                <span class="chev" :class="{ open: isGroupOpen(group.label) }" />
                <span class="grp-name">{{ group.label }}</span>
                <span class="gcnt">已选 {{ groupSelected(group) }}/{{ groupTotal(group) }}</span>
                <span
                  v-if="!matrix.readonly"
                  class="cb grp-cb"
                  :class="matrix.rowsState(group.rows)"
                  @click.stop="matrix.toggleRows(group.rows)"
                />
              </div>
            </td>
          </tr>
          <template v-if="isGroupOpen(group.label)">
            <tr v-for="item in group.visible" :key="item.row.prefix" :class="{ 'child-row': item.depth > 0 }">
              <td class="mod" :class="{ child: item.depth > 0 }">
                <span
                  v-if="item.childCount"
                  class="chev domain-chev"
                  :class="{ open: item.open }"
                  role="button"
                  @click="toggleFoldDomain(item.row.prefix)"
                />
                <span v-else-if="!item.depth" class="chev-slot" />
                <span v-else class="tree-tick" />
                <span class="nm">{{ item.row.label }}</span>
                <span
                  v-if="item.childCount && !item.open"
                  class="fold-hint"
                  @click="toggleFoldDomain(item.row.prefix)"
                >+{{ item.childCount }} 子页</span>
                <span class="cnt">{{ matrix.rowSelectedCount(item.row) }}/{{ item.row.perms.length }}</span>
                <span v-if="!matrix.readonly" class="cb" :class="matrix.rowState(item.row)" @click="onToggleRow(item)" />
              </td>
              <td v-for="col in columns" :key="col.key">
                <el-tooltip v-if="item.row.cells[col.key]" :content="cellTip(item.row.cells[col.key])" placement="top">
                  <span
                    class="cb"
                    :class="[{ on: matrix.isSelected(item.row.cells[col.key]), diff: matrix.isTemplateDiff(item.row.cells[col.key]) }]"
                    @click="matrix.toggleCell(item.row.cells[col.key])"
                  />
                </el-tooltip>
                <span v-else class="na">—</span>
              </td>
              <td class="special-cell">
                <template v-if="item.row.specials.length">
                  <el-tooltip v-for="p in item.row.specials" :key="p.id" :content="cellTip(p)" placement="top">
                    <span
                      class="chip"
                      :class="{ on: matrix.isSelected(p), diff: matrix.isTemplateDiff(p) }"
                      @click="matrix.toggleCell(p)"
                    >{{ actionOf(p) }} <i class="k">{{ kindLabel(p) }}</i></span>
                  </el-tooltip>
                </template>
                <span v-else class="none">无</span>
              </td>
            </tr>
          </template>
        </template>
        <tr v-if="!treeGroups.length">
          <td :colspan="columns.length + 2" class="empty">没有匹配「{{ matrix.searchText }}」的模块或权限</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { MATRIX_COLUMNS, KIND_LABELS, PAGE_PARENTS } from '../composables/usePermissionMatrix'

const props = defineProps({
  matrix: { type: Object, required: true },
})

const columns = MATRIX_COLUMNS

// ── 折叠状态（纯视图态，不进 composable）────────────────
// 搜索时无视折叠：命中的行被折叠藏住会让搜索"看起来没结果"
const foldedGroups = ref(new Set())
const foldedDomains = ref(new Set())
const searching = computed(() => !!(props.matrix.searchText || '').trim())

function toggleFoldGroup(label) {
  if (searching.value) return // 搜索态折叠被强制展开，此时翻转状态只会在清空搜索后"莫名折上"
  const next = new Set(foldedGroups.value)
  next.has(label) ? next.delete(label) : next.add(label)
  foldedGroups.value = next
}

function toggleFoldDomain(prefix) {
  if (searching.value) return
  const next = new Set(foldedDomains.value)
  next.has(prefix) ? next.delete(prefix) : next.add(prefix)
  foldedDomains.value = next
}

/** 勾选父域行时若子页折叠着，自动展开——避免"以为勾了整域"的误读（子页码不随父行勾选） */
function onToggleRow(item) {
  props.matrix.toggleRow(item.row)
  if (item.childCount && !item.open) toggleFoldDomain(item.row.prefix)
}

function isGroupOpen(label) {
  return searching.value || !foldedGroups.value.has(label)
}

/**
 * 分组 → 树状可见行。父域行在前，其页面码子行按 PAGE_PARENTS 缩进挂载；
 * 父域折叠时子行不进 visible（行数据本身不动，勾选逻辑与折叠无关）。
 */
const treeGroups = computed(() => props.matrix.filteredGroups.map(g => {
  const nodeByPrefix = new Map(g.rows.map(r => [r.prefix, { row: r, children: [] }]))
  const top = []
  for (const r of g.rows) {
    const parent = PAGE_PARENTS[r.prefix]
    if (parent && nodeByPrefix.has(parent)) nodeByPrefix.get(parent).children.push(nodeByPrefix.get(r.prefix))
    else top.push(nodeByPrefix.get(r.prefix))
  }
  const visible = []
  for (const n of top) {
    const open = searching.value || !foldedDomains.value.has(n.row.prefix)
    visible.push({ row: n.row, depth: 0, childCount: n.children.length, open })
    if (open) n.children.forEach(c => visible.push({ row: c.row, depth: 1, childCount: 0, open: true }))
  }
  return { label: g.label, rows: g.rows, visible }
}))

function groupSelected(group) {
  return group.rows.reduce((sum, r) => sum + props.matrix.rowSelectedCount(r), 0)
}

function groupTotal(group) {
  return group.rows.reduce((sum, r) => sum + r.perms.length, 0)
}

function actionOf(perm) {
  return perm.code.split(':')[1] || perm.action
}

function kindLabel(perm) {
  return KIND_LABELS[perm.kind] || '动作'
}

function cellTip(perm) {
  return `${perm.code} · ${perm.label}`
}
</script>

<style scoped>
.matrix-wrap {
  overflow: auto;
  border: 1px solid var(--border-color, #e2e5ef);
  border-radius: 10px;
}

.perm-matrix {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: var(--text-primary);
}
.perm-matrix th,
.perm-matrix td {
  border-bottom: 1px solid var(--border-color, #e2e5ef);
  padding: 9px 10px;
  text-align: center;
}
.perm-matrix thead th {
  background: #fafbfe;
  font-size: 12px;
  color: var(--text-secondary, #718096);
  font-weight: 600;
  position: sticky;
  top: 0;
  z-index: 1;
}
th.mod, td.mod { text-align: left; padding-left: 20px; width: 210px; }
th.special-col { width: 300px; }
td.special-cell { text-align: left; }
td.mod .nm { font-weight: 600; }
td.mod .cnt { font-size: 11px; color: var(--text-secondary, #718096); margin: 0 8px 0 8px; }
.perm-matrix tbody tr:hover { background: #fffdf6; }
tr.grp td {
  background: #f7f4ec;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: #8b6914;
  text-align: left;
  padding: 0;
  font-weight: 700;
  cursor: pointer;
  user-select: none;
}
.grp-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 20px 6px 12px;
}
.gcnt {
  font-weight: 400;
  letter-spacing: normal;
  font-size: 11px;
  color: var(--text-secondary);
}
.grp-cb { margin-left: auto; }

/* ── 折叠 chevron（150ms 强 ease-out，仅 transform） ── */
.chev {
  width: 0;
  height: 0;
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  border-left: 5px solid var(--text-secondary);
  display: inline-block;
  flex: none;
  transition: transform 150ms cubic-bezier(0.23, 1, 0.32, 1);
  cursor: pointer;
}
.chev.open { transform: rotate(90deg); }
.domain-chev { margin-right: 8px; vertical-align: middle; }
.chev-slot { display: inline-block; width: 13px; }

/* ── 树状子行 ── */
.tree-tick {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin: 0 6px 4px 14px;
  border-left: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
  border-bottom-left-radius: 4px;
  vertical-align: middle;
}
td.mod.child .nm { font-weight: 400; }
.fold-hint {
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--color-primary-light);
  border-radius: 8px;
  padding: 0 7px;
  margin-left: 6px;
  cursor: pointer;
  user-select: none;
}
td.empty { color: var(--text-secondary, #718096); padding: 28px 0; }

/* ── 三态 checkbox（对照原型 .cb） ── */
.cb {
  display: inline-block;
  width: 17px;
  height: 17px;
  border: 1.5px solid #c5cce0;
  border-radius: 4px;
  position: relative;
  vertical-align: middle;
  background: #fff;
  cursor: pointer;
  transition: transform 120ms cubic-bezier(0.23, 1, 0.32, 1),
    background-color 120ms ease, border-color 120ms ease;
}
.matrix-wrap:not(.readonly) .cb:active { transform: scale(0.88); }
.cb.on { background: var(--color-primary); border-color: var(--color-primary); }
.cb.on::after {
  content: "";
  position: absolute;
  left: 5px; top: 2px;
  width: 4px; height: 8px;
  border: solid #fff;
  border-width: 0 2px 2px 0;
  transform: rotate(40deg);
}
.cb.half { background: var(--color-primary-light, rgba(212, 148, 28, 0.08)); border-color: var(--color-primary); }
.cb.half::after {
  content: "";
  position: absolute;
  left: 3px; top: 6.5px;
  width: 9px; height: 2px;
  background: var(--color-primary);
}
.cb.diff { box-shadow: 0 0 0 2px var(--gold-line, #f5e0b5); } /* 模板差异金边 */
.na { color: #cbd5e1; }
.none { font-size: 11px; color: #cbd5e1; }

/* ── 特殊权限 chip ── */
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  border: 1px solid var(--border-color, #e2e5ef);
  border-radius: 12px;
  padding: 2px 9px;
  margin: 2px;
  color: var(--text-secondary, #718096);
  background: #fafbfe;
  cursor: pointer;
  user-select: none;
  transition: transform 120ms cubic-bezier(0.23, 1, 0.32, 1),
    background-color 120ms ease, border-color 120ms ease, color 120ms ease;
}
.matrix-wrap:not(.readonly) .chip:active { transform: scale(0.95); }
.chip.on {
  border-color: var(--color-primary);
  color: var(--color-primary-hover, #bb8218);
  background: var(--color-primary-light, rgba(212, 148, 28, 0.08));
}
.chip.diff { box-shadow: 0 0 0 2px var(--gold-line, #f5e0b5); }
.chip .k { font-size: 9px; background: #eef1f7; border-radius: 6px; padding: 0 4px; color: #8b95a5; font-style: normal; }
.chip.on .k { background: #f7e8c8; color: #8b6914; }

/* readonly 模式：去掉可点击暗示（折叠仍可用） */
.matrix-wrap.readonly .cb,
.matrix-wrap.readonly .chip { cursor: default; }

@media (prefers-reduced-motion: reduce) {
  .chev, .cb, .chip { transition: none; }
  .matrix-wrap:not(.readonly) .cb:active,
  .matrix-wrap:not(.readonly) .chip:active { transform: none; }
}
</style>

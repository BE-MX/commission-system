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
        <template v-for="group in matrix.filteredGroups" :key="group.label">
          <tr class="grp"><td :colspan="columns.length + 2">{{ group.label }}</td></tr>
          <tr v-for="row in group.rows" :key="row.prefix">
            <td class="mod">
              <span class="nm">{{ row.label }}</span>
              <span class="cnt">{{ matrix.rowSelectedCount(row) }}/{{ row.perms.length }}</span>
              <span v-if="!matrix.readonly" class="cb" :class="matrix.rowState(row)" @click="matrix.toggleRow(row)" />
            </td>
            <td v-for="col in columns" :key="col.key">
              <el-tooltip v-if="row.cells[col.key]" :content="cellTip(row.cells[col.key])" placement="top">
                <span
                  class="cb"
                  :class="[{ on: matrix.isSelected(row.cells[col.key]), diff: matrix.isTemplateDiff(row.cells[col.key]) }]"
                  @click="matrix.toggleCell(row.cells[col.key])"
                />
              </el-tooltip>
              <span v-else class="na">—</span>
            </td>
            <td class="special-cell">
              <template v-if="row.specials.length">
                <el-tooltip v-for="p in row.specials" :key="p.id" :content="cellTip(p)" placement="top">
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
        <tr v-if="!matrix.filteredGroups.length">
          <td :colspan="columns.length + 2" class="empty">没有匹配「{{ matrix.searchText }}」的模块或权限</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { MATRIX_COLUMNS, KIND_LABELS } from '../composables/usePermissionMatrix'

defineProps({
  matrix: { type: Object, required: true },
})

const columns = MATRIX_COLUMNS

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
  padding: 5px 20px;
  font-weight: 700;
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
}
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
}
.chip.on {
  border-color: var(--color-primary);
  color: var(--color-primary-hover, #bb8218);
  background: var(--color-primary-light, rgba(212, 148, 28, 0.08));
}
.chip.diff { box-shadow: 0 0 0 2px var(--gold-line, #f5e0b5); }
.chip .k { font-size: 9px; background: #eef1f7; border-radius: 6px; padding: 0 4px; color: #8b95a5; font-style: normal; }
.chip.on .k { background: #f7e8c8; color: #8b6914; }

/* readonly 模式：去掉可点击暗示 */
.matrix-wrap.readonly .cb,
.matrix-wrap.readonly .chip { cursor: default; }
</style>

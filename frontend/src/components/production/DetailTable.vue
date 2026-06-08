<template>
  <div class="db-detail-table-wrap">
    <table class="db-detail-table">
      <thead class="db-detail-table__head">
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            class="db-detail-table__th"
            :style="col.width ? { width: col.width } : {}"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody class="db-detail-table__body">
        <tr
          v-for="(row, rowIdx) in rows"
          :key="rowIdx"
          class="db-detail-table__tr"
        >
          <td
            v-for="col in columns"
            :key="col.key"
            class="db-detail-table__td"
          >
            <!-- 自定义 slot：v-slot:[col.key]="{ row }" -->
            <slot :name="col.key" :row="row" :value="row[col.key]">
              {{ row[col.key] ?? '—' }}
            </slot>
          </td>
        </tr>

        <tr v-if="!rows || rows.length === 0">
          <td :colspan="columns.length" class="db-detail-table__empty">
            暂无数据
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({
  columns: { type: Array, default: () => [] },
  rows:    { type: Array, default: () => [] },
})
</script>

<style scoped>
.db-detail-table-wrap {
  width: 100%;
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid var(--db-border);
}

.db-detail-table-wrap::-webkit-scrollbar {
  height: 4px;
}
.db-detail-table-wrap::-webkit-scrollbar-track {
  background: transparent;
}
.db-detail-table-wrap::-webkit-scrollbar-thumb {
  background: var(--db-scrollbar);
  border-radius: 2px;
}

.db-detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

/* 表头 */
.db-detail-table__head {
  background: var(--db-table-head-bg);
  position: sticky;
  top: 0;
  z-index: 2;
}

.db-detail-table__th {
  text-align: left;
  padding: 10px 14px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--db-text-muted);
  white-space: nowrap;
  border-bottom: 1px solid var(--db-border);
}

/* 表格行 */
.db-detail-table__tr {
  transition: background 0.12s;
}

.db-detail-table__tr:hover {
  background: var(--db-hover-bg);
}

.db-detail-table__tr:not(:last-child) .db-detail-table__td {
  border-bottom: 1px solid var(--db-border-subtle);
}

.db-detail-table__td {
  padding: 10px 14px;
  color: var(--db-text-primary);
  vertical-align: middle;
  white-space: nowrap;
}

/* 空状态 */
.db-detail-table__empty {
  text-align: center;
  padding: 32px 14px;
  color: var(--db-text-muted);
  font-size: 13px;
}
</style>

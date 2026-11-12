<template>
  <section class="unlinked">
    <div class="list panel">
      <div class="scope" role="group" aria-label="会话处理状态">
        <button v-for="item in scopes" :key="item.key" type="button" class="chip board-focus" :class="{ on: desk.scope.value === item.key }" @click="desk.scope.value = item.key">{{ item.label }}</button>
        <span class="spacer" />
        <el-input v-model="desk.keyword.value" clearable placeholder="搜索会话" aria-label="搜索未关联会话" />
      </div>
      <p v-if="desk.loading.value" class="muted center" role="status">正在读取会话…</p>
      <div v-else-if="desk.error.value" class="empty-state"><h3>暂时无法读取</h3><p>{{ desk.error.value }}</p><el-button @click="desk.loadList(false)">重试</el-button></div>
      <template v-else>
        <button v-for="row in desk.rows.value" :key="row.conversation_uid" type="button" class="item board-focus" :class="{ on: desk.selectedChat.value?.conversation_uid === row.conversation_uid }" @click="desk.select(row, false)">
          <span class="avatar" aria-hidden="true">{{ initials(row.name || row.display_name || 'WA') }}</span>
          <span class="copy"><b>{{ row.name || row.display_name || 'WhatsApp 会话' }}</b><span class="muted">{{ row.phone_masked || '号码未同步' }} · {{ row.last_touch_at ? formatBeijingShortDateTime(row.last_touch_at) : '时间未知' }}</span></span>
        </button>
        <div v-if="!desk.rows.value.length" class="empty-state"><h3>暂无匹配会话</h3></div>
        <el-pagination v-if="desk.total.value > 20" v-model:current-page="desk.page.value" v-model:page-size="desk.pageSize.value" class="pager" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" :total="desk.total.value" />
      </template>
    </div>
    <div class="panel side">
      <template v-if="chat">
        <h4>{{ chat.name || chat.display_name || 'WhatsApp 会话' }}</h4>
        <p class="muted">{{ chat.phone_masked || '' }}</p>
        <p>关联前不展示聊天正文，也不进入客户画像。请选择本人私海里的客户。</p>
        <div class="actions" v-permission="'client_desk:write'">
          <el-button type="primary" @click="desk.open('link')">{{ desk.scope.value === 'linked' ? '更换关联客户' : '关联到客户' }}</el-button>
          <el-button :loading="desk.saving.value" @click="desk.ignoreChat">{{ desk.scope.value ? '撤销处理' : '不是客户' }}</el-button>
        </div>
        <el-alert v-if="desk.detailError.value" :title="desk.detailError.value" type="error" :closable="false" />
      </template>
      <p v-else class="muted">从左侧选择一个会话进行关联。</p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { initials } from './boardModel'

const props = defineProps({ desk: { type: Object, required: true } })
const scopes = [{ key: '', label: '待关联' }, { key: 'ignored', label: '已忽略' }, { key: 'linked', label: '已关联' }]
const chat = computed(() => props.desk.selectedChat.value)
</script>

<style src="./board.css" scoped></style>
<style scoped>
.unlinked { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(260px, 1fr); gap: 16px; margin-top: 16px; align-items: start; }
.panel + .panel { margin-top: 0; }
.scope { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 8px; }
.scope .el-input { width: 220px; }
.spacer { flex: 1; }
.chip { padding: 3px 10px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--card-bg); color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.chip.on { border-color: var(--tag-gold-border); background: var(--tag-gold-bg); color: var(--tag-gold-text); }
.item { display: flex; align-items: center; gap: 12px; width: 100%; padding: 12px 6px; border: 0; border-top: 1px solid var(--border-color); background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.item.on { background: var(--button-primary-soft); }
.copy { display: grid; min-width: 0; }
.side p { line-height: 1.7; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions .el-button + .el-button { margin-left: 0; }
.center { padding: 30px; text-align: center; }
.pager { margin-top: 12px; }
@media (hover: hover) and (pointer: fine) { .item:hover { background: var(--button-primary-soft); } }
@media (max-width: 720px) { .unlinked { grid-template-columns: 1fr; } .scope .el-input { width: 100%; } }
</style>

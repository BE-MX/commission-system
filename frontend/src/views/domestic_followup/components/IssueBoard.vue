<template>
  <div class="issue-board table-card">
    <div class="toolbar">
      <el-segmented v-model="query.status" :options="STATE_OPTIONS" @change="load(1)" />
      <el-select v-model="query.kind" clearable placeholder="类型" class="filter-w-sm" @change="load(1)">
        <el-option value="issue" label="异常" /><el-option value="suggestion" label="意见建议" />
      </el-select>
      <el-select v-model="query.category" clearable placeholder="分类" class="filter-w-sm" @change="load(1)">
        <el-option v-for="v in categories" :key="v" :value="v" :label="v" />
      </el-select>
      <el-checkbox v-model="query.mine" @change="load(1)">只看我处理的</el-checkbox>
    </div>
    <el-table v-loading="loading" :data="rows" row-key="id" border class="list-table" v-sticky-scrollbar>
      <el-table-column label="客户" prop="shop_name" min-width="140" show-overflow-tooltip>
        <template #default="{ row }"><GlassButton variant="link" @click="$emit('timeline', row.customer_id)">{{ row.shop_name }}</GlassButton></template>
      </el-table-column>
      <el-table-column label="类型" min-width="80"><template #default="{ row }">{{ row.kind === 'issue' ? '异常' : '意见' }}</template></el-table-column>
      <el-table-column label="分类" prop="category" min-width="100" />
      <el-table-column label="内容" prop="text" min-width="240" show-overflow-tooltip />
      <el-table-column label="紧急" min-width="80">
        <template #default="{ row }"><StatusBadge v-if="row.severity === '紧急'" :value="row.severity" :dictionary="SEVERITY_STATUS" size="small" /></template>
      </el-table-column>
      <el-table-column label="处理人" prop="handler_name" min-width="100" />
      <el-table-column label="记录日" min-width="110"><template #default="{ row }">{{ formatBeijingDate(row.created_at) }}</template></el-table-column>
      <el-table-column v-if="query.status === 'open'" class-name="table-action-column" label="操作" min-width="160" fixed="right">
        <template #default="{ row }">
          <GlassButton v-permission="'domestic_followup:write'" variant="link" left-icon="Check" @click="resolve(row)">处理</GlassButton>
          <GlassButton v-permission="'domestic_followup:write'" variant="link" left-icon="Switch" @click="openTransfer(row)">转交</GlassButton>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page" v-model:page-size="pageSize" :total="total"
      :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
      class="pager" @current-change="load" @size-change="load(1)"
    />

    <el-dialog v-model="transfer.visible" title="转交给" width="480px" append-to-body>
      <el-select v-model="transfer.toUserId" filterable remote :remote-method="searchUsers" placeholder="输入姓名" class="transfer-field">
        <el-option v-for="u in users" :key="u.id" :value="u.id" :label="u.real_name" />
      </el-select>
      <el-input v-model="transfer.note" placeholder="交代一句（可选）" maxlength="200" class="transfer-field transfer-note" />
      <template #footer>
        <GlassButton @click="transfer.visible = false">取消</GlassButton>
        <GlassButton variant="primary" :disabled="!transfer.toUserId" :loading="transfer.saving" @click="submitTransfer">转交</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { formatBeijingDate } from '@/utils/datetime'
import { isFeedbackCancelled, msgError, msgSuccessText, promptAction } from '@/utils/feedback'
import { SEVERITY_STATUS } from '../followupStatus'

defineProps({ categories: { type: Array, default: () => [] } })
const emit = defineEmits(['timeline', 'changed'])
const STATE_OPTIONS = [{ label: '未处理', value: 'open' }, { label: '已解决', value: 'resolved' }, { label: '不处理', value: 'closed_no_action' }]
const query = reactive({ status: 'open', kind: '', category: '', mine: false })
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const users = ref([])
const transfer = reactive({ visible: false, item: null, toUserId: null, note: '', saving: false })

async function load(p = page.value) {
  page.value = p
  loading.value = true
  try {
    const res = await followupApi.items({ ...query, kind: query.kind || undefined, category: query.category || undefined, page: p, page_size: pageSize.value })
    rows.value = res.items
    total.value = res.total
  } catch (e) { msgError(apiError(e, '加载失败'), e) } finally { loading.value = false }
}

async function resolve(row) {
  try {
    const { value } = await promptAction(`「${row.text}」怎么解决的？`, '标记已处理', { inputPlaceholder: '如：已补发 2 顶 / 已退款' })
    await followupApi.resolveItem(row.id, { status: 'resolved', resolution: value })
    msgSuccessText('已处理')
    await load()
    emit('changed')
  } catch (e) { if (!isFeedbackCancelled(e)) msgError(apiError(e, '处理失败'), e) }
}

function openTransfer(row) {
  Object.assign(transfer, { visible: true, item: row, toUserId: null, note: '' })
  searchUsers('')
}

async function searchUsers(q) {
  try { users.value = await followupApi.users(q) } catch (e) { msgError(apiError(e, '人员加载失败'), e) }
}

async function submitTransfer() {
  transfer.saving = true
  try {
    await followupApi.transferItem(transfer.item.id, { to_user_id: transfer.toUserId, note: transfer.note })
    msgSuccessText('已转交')
    transfer.visible = false
    await load()
    emit('changed')
  } catch (e) { msgError(apiError(e, '转交失败'), e) } finally { transfer.saving = false }
}

onMounted(() => load(1))
defineExpose({ load })
</script>

<style scoped>
.transfer-field { width: 100%; }
.transfer-note { margin-top: 8px; }
</style>

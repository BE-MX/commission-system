<template>
  <section v-loading="loading">
    <div class="actions">
      <el-button :icon="Refresh" @click="load">刷新</el-button>
      <el-button v-permission="'announcement:admin'" :icon="MagicStick" @click="generate(false)">生成上周周报预览</el-button>
      <el-button v-permission="'announcement:admin'" :icon="Edit" @click="generate(true)">重新生成预览</el-button>
    </div>
    <p>每周一自动汇总上周公告。手动生成只保存预览，发送更正版需点击发送。</p>
    <el-empty v-if="!rows.length" description="暂无公告周报" />
    <el-collapse v-else>
      <el-collapse-item v-for="row in rows" :key="row.id" :name="row.id" :title="`${formatBeijingDate(row.period_start)} · ${labels[row.status] || row.status} · 第 ${row.generation} 版`">
        <el-alert v-if="row.error" :title="row.error" type="warning" :closable="false" />
        <div class="weekly-body" v-html="render(row.body)" />
        <el-button v-if="['ready', 'degraded'].includes(row.status)" v-permission="'announcement:admin'" :icon="Promotion" @click="send(row)">发送此版周报到公告群</el-button>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Refresh, MagicStick, Edit, Promotion } from '@element-plus/icons-vue'
import { announcementApi as api } from '@/api/announcement'
import { formatBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
const rows = ref([]), loading = ref(false)
const labels = { queued: '待生成', generating: '生成中', ready: '已生成', degraded: '目录版本', failed: '生成失败' }
// Escape all HTML. Only server-created links to this feature become clickable.
function render(text = '') {
  const escaped = text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;')
  return escaped.replace(/\[查看原公告\]\(https?:\/\/[^\s)]+\/announcements\/(\d+)\)/g, '<a href="/announcements/$1" target="_blank" rel="noopener">查看原公告</a>')
}
async function load() { loading.value = true; try { rows.value = await api.get('/weekly') } finally { loading.value = false } }
async function generate(regenerate) { await api.post('/weekly', { regenerate }); await load(); msgSuccess('加入周报生成队列') }
async function send(row) {
  try { await ElMessageBox.confirm('将此版周报发送至公告群；若此前已发送旧版，群内会收到更正版。', '发送周报', { confirmButtonText: '发送', cancelButtonText: '取消' }) } catch { return }
  await api.post(`/weekly/${row.id}/send`); msgSuccess('加入发送队列')
}
onMounted(load)
</script>

<style scoped>
.actions { display: flex; gap: 12px; flex-wrap: wrap; }
p { color: var(--text-secondary); }
.weekly-body { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 15px; line-height: 1.8; padding: 16px 0; }
.weekly-body :deep(a) { color: var(--color-primary); }
</style>

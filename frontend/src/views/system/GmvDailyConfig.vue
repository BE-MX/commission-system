<template>
  <div class="gmv-config" v-loading="loading">
    <div class="gmv-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="page-header">
      <div>
        <h2>GMV 日报配置</h2>
        <p>每天北京时间 08:00 按 account_date 统计昨天有效订单，并点对点发送到队长和指定管理员。</p>
      </div>
      <div class="header-actions">
        <el-date-picker
          v-model="reportDate"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="不选则统计昨天"
          :clearable="true"
        />
        <GlassButton variant="ghost" left-icon="View" @click="showPreview">预览</GlassButton>
        <GlassButton variant="secondary" left-icon="Promotion" :loading="sending" @click="sendNow">立即发送</GlassButton>
        <GlassButton variant="primary" left-icon="Check" :loading="saving" @click="save">保存配置</GlassButton>
      </div>
    </header>

    <el-alert
      v-if="!config.persisted"
      class="defaults-alert"
      type="warning"
      :closable="false"
      title="当前展示的是首次上线默认名单；请核对队伍并选择管理员接收人后保存，定时任务才会开始发送。"
    />
    <el-alert
      v-else-if="hasUnsavedChanges"
      class="defaults-alert"
      type="info"
      :closable="false"
      title="当前有未保存修改；预览、立即发送和定时任务继续使用已保存配置，请先保存。"
    />

    <section class="glass-card admin-card">
      <div class="section-heading">
        <div>
          <h3>管理员日报接收人</h3>
          <p>只有这里勾选且已绑定钉钉的人员会收到全公司明细，不按 admin 角色自动群发。</p>
        </div>
      </div>
      <el-select
        v-model="config.admin_recipient_user_ids"
        multiple
        filterable
        collapse-tags
        collapse-tags-tooltip
        placeholder="选择具体接收人"
        class="wide-select"
      >
        <el-option
          v-for="item in options.admin_recipients"
          :key="item.ark_user_id"
          :label="adminLabel(item)"
          :value="item.ark_user_id"
          :disabled="!item.has_dingtalk"
        />
      </el-select>
    </section>

    <section class="team-grid">
      <article v-for="team in config.teams" :key="team.department_id" class="glass-card team-card">
        <div class="team-title-row">
          <div>
            <h3>{{ team.name }}</h3>
            <span>OKKI 部门 {{ team.department_id }}</span>
          </div>
          <div class="team-switches">
            <el-switch v-model="team.is_active" active-text="启用" />
            <GlassButton variant="link" left-icon="Delete" @click="removeTeam(team)">移除</GlassButton>
          </div>
        </div>

        <el-form label-position="top" class="team-form">
          <el-form-item label="队长及钉钉接收人">
            <el-select v-model="team.captain_okki_user_id" filterable class="wide-select" placeholder="选择队长">
              <el-option
                v-for="item in options.captains"
                :key="item.okki_user_id"
                :label="captainLabel(item)"
                :value="item.okki_user_id"
                :disabled="!item.has_dingtalk"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <div class="member-header">
          <strong>在职成员</strong>
          <span>零 GMV 也会显示；排除只作用于本队汇总。</span>
        </div>
        <el-table :data="team.members" border class="member-table list-table">
          <el-table-column prop="name" label="姓名" min-width="120" />
          <el-table-column prop="okki_user_id" label="OKKI ID" min-width="120" />
          <el-table-column label="在职" min-width="80">
            <template #default="{ row }"><el-switch v-model="row.is_active" /></template>
          </el-table-column>
          <el-table-column label="不计汇总" min-width="105">
            <template #default="{ row }"><el-switch v-model="row.exclude_from_total" /></template>
          </el-table-column>
          <el-table-column label="操作" min-width="70">
            <template #default="{ row }">
              <GlassButton
                variant="link"
                left-icon="Close"
                aria-label="移除成员"
                title="移除成员"
                @click="removeMember(team, row)"
              />
            </template>
          </el-table-column>
        </el-table>

        <div class="add-member-row">
          <el-select
            v-model="memberSelections[team.department_id]"
            filterable
            placeholder="添加在职成员"
            class="member-select"
          >
            <el-option
              v-for="item in availableMembers(team)"
              :key="item.okki_user_id"
              :label="`${item.name} · ${item.okki_user_id}`"
              :value="item.okki_user_id"
            />
          </el-select>
          <GlassButton variant="ghost" left-icon="Plus" @click="addMember(team)">添加</GlassButton>
        </div>
      </article>
    </section>

    <section class="glass-card add-team-card">
      <el-select v-model="newDepartmentId" filterable placeholder="选择一个尚未配置的 OKKI 部门">
        <el-option
          v-for="item in availableDepartments"
          :key="item.department_id"
          :label="`${item.name} · ${item.department_id}`"
          :value="item.department_id"
        />
      </el-select>
      <GlassButton variant="ghost" left-icon="Plus" :disabled="!newDepartmentId" @click="addTeam">新增队伍</GlassButton>
    </section>

    <el-dialog v-model="previewVisible" title="GMV 日报预览" width="760px" destroy-on-close>
      <el-tabs v-if="preview" v-model="activePreview">
        <el-tab-pane label="管理员日报" name="admin">
          <pre class="markdown-preview">{{ preview.admin_markdown }}</pre>
        </el-tab-pane>
        <el-tab-pane
          v-for="message in preview.team_messages"
          :key="message.department_id"
          :label="message.team_name"
          :name="String(message.department_id)"
        >
          <pre class="markdown-preview">{{ message.markdown }}</pre>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
  </div>
</template>

<script setup>
import { useGmvDailyConfig } from './composables/useGmvDailyConfig'

const {
  activePreview, addMember, addTeam, adminLabel, availableDepartments, availableMembers,
  captainLabel, config, hasUnsavedChanges, loading, memberSelections, newDepartmentId, options, preview,
  previewVisible, removeMember, removeTeam, reportDate, save, saving, sendNow, sending,
  showPreview,
} = useGmvDailyConfig()
</script>

<style scoped>
.gmv-config { padding: 24px 28px; position: relative; }
.gmv-aurora { inset: -24px -28px; }
.gmv-config > :not(.gmv-aurora) { position: relative; z-index: 1; }
.page-header { display: flex; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.page-header h2 { margin: 0; color: var(--text-primary); font-family: var(--font-display); font-size: 22px; }
.page-header p, .section-heading p { margin: 5px 0 0; color: var(--text-muted); font-size: 13px; }
.header-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 10px; }
.defaults-alert { margin-bottom: 16px; }
.glass-card {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}
.admin-card { padding: 18px 20px; margin-bottom: 18px; }
.section-heading h3, .team-title-row h3 { margin: 0; color: var(--text-primary); font-size: 16px; }
.wide-select { width: 100%; margin-top: 14px; }
.team-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.team-card { padding: 18px; min-width: 0; }
.team-title-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.team-title-row span, .member-header span { color: var(--text-muted); font-size: 12px; }
.team-switches { display: flex; align-items: center; gap: 8px; }
.team-form { margin-top: 12px; }
.member-header { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.member-header strong { color: var(--text-primary); font-size: 14px; }
.member-table { width: 100%; }
.member-table :deep(.el-table), .member-table :deep(.el-table__inner-wrapper) { background: transparent; }
.add-member-row { display: flex; gap: 10px; margin-top: 12px; }
.member-select { flex: 1; }
.add-team-card { display: flex; justify-content: center; gap: 10px; margin-top: 18px; padding: 18px; }
.add-team-card .el-select { width: min(460px, 70%); }
.markdown-preview {
  margin: 0;
  padding: 16px;
  max-height: 58vh;
  overflow: auto;
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
  color: var(--text-primary);
  font-family: var(--font-mono);
  line-height: 1.65;
  white-space: pre-wrap;
}
@media (max-width: 1100px) {
  .team-grid { grid-template-columns: 1fr; }
  .page-header { flex-direction: column; }
  .header-actions { justify-content: flex-start; }
}
</style>

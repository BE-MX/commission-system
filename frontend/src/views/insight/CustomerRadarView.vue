<template>
  <div class="customer-radar">
    <!-- 页头 -->
    <div class="cr-header">
      <div>
        <h1>今日客户经营雷达</h1>
        <p class="cr-subtitle">AI 把新询盘、样单反馈、大客户、复购和公海客户放在同一张雷达里，直接告诉你今天先看谁、为什么、怎么做。</p>
      </div>
      <div class="cr-header-actions">
        <el-button @click="refresh" :icon="RefreshRight" :loading="loading">刷新信号</el-button>
        <el-button type="primary" :icon="CircleCheck" @click="selectThread('all')">按推荐先看</el-button>
      </div>
    </div>

    <!-- 三栏工作区 -->
    <div class="cr-workspace">
      <!-- 左栏：经营线索导航 -->
      <div class="cr-thread-panel">
        <div class="cr-panel-title">
          <span>经营线索</span>
          <el-tag size="small" type="info">{{ threadNav.length - 1 }}</el-tag>
        </div>
        <div class="cr-thread-list">
          <button
            v-for="thread in threadNav"
            :key="thread.group"
            class="cr-thread-card"
            :class="{ active: selectedThread === thread.group || (!selectedThread && thread.group === 'all') }"
            @click="selectThread(thread.group)"
          >
            <div class="cr-thread-top">
              <span class="cr-thread-name">{{ thread.label }}</span>
              <el-tag size="small" :type="tagType(thread.color)" round>{{ thread.count }}</el-tag>
            </div>
            <div class="cr-thread-priority" v-if="thread.priority_label">
              <el-tag size="small" :type="tagType(thread.color)" effect="plain">{{ thread.priority_label }}</el-tag>
            </div>
            <div class="cr-thread-desc">{{ thread.desc }}</div>
          </button>
        </div>
        <div class="cr-thread-note">
          这里不是新的任务清单，而是帮业务员避免只盯着最新询盘。
        </div>
      </div>

      <!-- 中栏：行动列表 -->
      <div class="cr-action-panel">
        <div class="cr-toolbar">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索客户、建议、线索、产品"
            :prefix-icon="Search"
            clearable
            size="default"
            style="max-width: 320px"
          />
          <span class="cr-toolbar-meta">当前显示 {{ filteredActions.length }} 条建议</span>
        </div>
        <div class="cr-action-list" v-loading="loading">
          <div
            v-for="action in filteredActions"
            :key="action.id"
            class="cr-action-row"
            :class="{ active: selectedActionId === action.id, done: action.action_status === 'done' }"
            @click="selectAction(action)"
          >
            <div class="cr-action-main">
              <div class="cr-customer-name">{{ action.customer_name }}</div>
              <div class="cr-customer-meta">
                <span>{{ action.customer_region }}</span>
                <el-tag size="small" :type="tagType(action.thread_color)" effect="plain">{{ action.thread_label }}</el-tag>
              </div>
              <div class="cr-action-reason">{{ action.action_reason }}</div>
            </div>
            <div class="cr-action-next" v-if="action.suggested_next_action">
              <div class="cr-cell-label">下一步建议</div>
              <div class="cr-action-text">{{ action.suggested_next_action }}</div>
            </div>
          </div>
          <el-empty v-if="!loading && filteredActions.length === 0" description="没有符合条件的建议" />
        </div>
      </div>

      <!-- 右栏：活画像面板 -->
      <div class="cr-profile-panel" v-if="selectedProfile">
        <div class="cr-profile-head">
          <div>
            <h2>{{ selectedProfile.customer_name }}</h2>
            <div class="cr-profile-meta">
              <el-tag v-if="selectedAction" size="small" :type="tagType(selectedAction.thread_color)" effect="plain">
                {{ selectedAction.thread_label }}
              </el-tag>
              <el-tag size="small" type="info" effect="plain">{{ selectedProfile.customer_region }}</el-tag>
            </div>
          </div>
        </div>

        <div class="cr-profile-scroll">
          <!-- 画像判断 -->
          <div class="cr-section">
            <div class="cr-section-title"><el-icon><MagicStick /></el-icon>活画像判断</div>
            <div class="cr-judgement">{{ selectedProfile.profile_judgement || '暂无画像判断' }}</div>
          </div>

          <!-- 画像标签 -->
          <div class="cr-section">
            <div class="cr-section-title"><el-icon><PriceTag /></el-icon>画像标签</div>
            <div class="cr-tags">
              <el-tag v-for="(tag, i) in (selectedProfile.profile_tags || [])" :key="i" size="small"
                :type="tagColor(i)" effect="plain" round>{{ tag }}</el-tag>
            </div>
          </div>

          <!-- 最近信号 -->
          <div class="cr-section">
            <div class="cr-section-title"><el-icon><Aim /></el-icon>最近信号</div>
            <div class="cr-signal-list">
              <div v-for="(signal, i) in (selectedProfile.profile_signals_json || []).slice(0, 5)" :key="i" class="cr-signal-item">
                <el-icon color="#258060"><SuccessFilled /></el-icon>
                <span>{{ signal }}</span>
                <el-button link size="small" @click="openSources('opportunity')">原文</el-button>
              </div>
            </div>
          </div>

          <!-- 本次建议 -->
          <div class="cr-section" v-if="selectedAction">
            <div class="cr-section-title"><el-icon><Position /></el-icon>本次建议</div>
            <div class="cr-judgement">{{ selectedAction.action_reason }}</div>
          </div>

          <!-- 推荐话术 -->
          <div class="cr-section" v-if="selectedAction?.suggested_message">
            <div class="cr-section-title"><el-icon><ChatDotRound /></el-icon>建议话术</div>
            <div class="cr-message-box">
              <div class="cr-message-head">
                <span>{{ selectedAction.suggested_next_action || '跟进消息' }}</span>
                <el-button size="small" @click="copyText(selectedAction.suggested_message)">复制</el-button>
              </div>
              <el-input type="textarea" v-model="selectedAction.suggested_message" :autosize="{ minRows: 3, maxRows: 6 }" />
            </div>
          </div>

          <!-- 系统会记住 -->
          <div class="cr-section" v-if="selectedAction">
            <div class="cr-section-title"><el-icon><RefreshRight /></el-icon>系统会记住</div>
            <div class="cr-signal-list">
              <div class="cr-signal-item">
                <el-icon color="#087c8e"><RefreshRight /></el-icon>
                <span>如果客户反馈正面，系统会把ta转入更高优先级。</span>
              </div>
              <div class="cr-signal-item">
                <el-icon color="#087c8e"><RefreshRight /></el-icon>
                <span>如果客户无回复，后续会降低提醒强度。</span>
              </div>
              <div class="cr-signal-item">
                <el-icon color="#087c8e"><RefreshRight /></el-icon>
                <span>你的反馈会让后续推荐更准确。</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="cr-profile-actions">
          <el-button type="primary" @click="completeAction(selectedActionId)">
            <el-icon><SuccessFilled /></el-icon>已跟进
          </el-button>
          <el-button @click="snoozeAction(selectedActionId, snoozeUntil)">
            <el-icon><Clock /></el-icon>今天先不看
          </el-button>
          <el-button @click="sendFeedback(selectedActionId, 'useful')">
            <el-icon><Top /></el-icon>客户质量更高
          </el-button>
          <el-button @click="sendFeedback(selectedActionId, 'not_useful')">
            <el-icon><Bottom /></el-icon>推荐不准
          </el-button>
        </div>
      </div>

      <!-- 未选中时占位 -->
      <div class="cr-profile-panel cr-empty-panel" v-else>
        <el-empty description="选择一条建议查看活画像" />
      </div>
    </div>

    <!-- 原始记录抽屉 -->
    <el-drawer v-model="sourceDrawerVisible" title="原始记录" size="480px" direction="rtl">
      <el-tabs v-model="sourceTab" @tab-change="(tab) => loadSources(selectedProfile?.id, tab === 'all' ? null : tab)">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="询盘" name="opportunity" />
        <el-tab-pane label="事件" name="event" />
        <el-tab-pane label="备注" name="note" />
      </el-tabs>
      <div class="cr-source-list">
        <div v-for="record in sourceRecords" :key="record.title + record.occurred_at" class="cr-source-record">
          <div class="cr-source-title">
            <span>{{ record.title }}</span>
            <el-tag size="small" :type="tagType(record.color)" effect="plain">{{ record.type }}</el-tag>
          </div>
          <div class="cr-source-meta">{{ record.meta }}</div>
          <div class="cr-source-summary" v-if="record.summary">{{ record.summary }}</div>
          <pre class="cr-source-raw">{{ record.raw }}</pre>
        </div>
        <el-empty v-if="sourceRecords.length === 0" description="暂无原始记录" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useCustomerRadar } from './composables/useCustomerRadar'
import {
  RefreshRight, CircleCheck, Search, MagicStick, PriceTag, Aim,
  Position, ChatDotRound, SuccessFilled, Clock, Top, Bottom,
} from '@element-plus/icons-vue'

const {
  loading, focusData, threadCounts, threadNav,
  selectedThread, selectedActionId, selectedAction, selectedProfile,
  profileLoading, filteredActions, allActions,
  sourceDrawerVisible, sourceRecords, sourceTab, searchKeyword,
  loadFocus, selectThread, selectAction,
  completeAction, dismissAction, snoozeAction, sendFeedback,
  loadSources, saveNote, refresh,
} = useCustomerRadar()

const snoozeUntil = new Date(Date.now() + 24 * 3600 * 1000).toISOString().slice(0, 16)

function tagType(color) {
  const map = { gold: 'warning', green: 'success', blue: '', purple: 'info', teal: 'success', red: 'danger', gray: 'info' }
  return map[color] || ''
}

function tagColor(i) {
  const colors = ['warning', '', 'success', 'info', 'success']
  return colors[i % colors.length]
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('话术已复制')
  }).catch(() => {
    ElMessage.warning('复制失败，请手动选中文本')
  })
}

function openSources(type) {
  sourceDrawerVisible.value = true
  sourceTab.value = type || 'all'
  if (selectedProfile.value) {
    loadSources(selectedProfile.value.id, type === 'all' ? null : type)
  }
}

import { ElMessage } from 'element-plus'
</script>

<style scoped>
.customer-radar { padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; height: calc(100vh - 56px); overflow: hidden; }

.cr-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-shrink: 0; }
.cr-header h1 { margin: 0; font-size: 22px; font-weight: 800; }
.cr-subtitle { margin: 4px 0 0; color: #788395; font-size: 13px; }
.cr-header-actions { display: flex; gap: 8px; }

.cr-workspace { flex: 1; min-height: 0; display: grid; grid-template-columns: 220px minmax(380px, 1fr) 380px; gap: 12px; overflow: hidden; }

/* 左栏 */
.cr-thread-panel, .cr-action-panel, .cr-profile-panel {
  background: #fff; border: 1px solid #e0e6ef; border-radius: 8px; box-shadow: 0 1px 2px rgba(15,23,42,.05);
  display: flex; flex-direction: column; overflow: hidden;
}
.cr-panel-title { min-height: 42px; padding: 0 13px; border-bottom: 1px solid #e0e6ef; display: flex; align-items: center; justify-content: space-between; font-weight: 800; font-size: 14px; }
.cr-thread-list { padding: 8px; overflow: auto; display: flex; flex-direction: column; gap: 5px; flex: 1; }
.cr-thread-card { width: 100%; min-height: 56px; border-radius: 8px; border: 1px solid transparent; background: #fff; padding: 8px; text-align: left; cursor: pointer; color: #344155; transition: all .15s; }
.cr-thread-card:hover { background: #fffdf8; }
.cr-thread-card.active { background: #fff7e8; border-color: #f0d8a7; color: #87570b; }
.cr-thread-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-weight: 800; }
.cr-thread-name { font-size: 13px; }
.cr-thread-priority { margin-top: 2px; }
.cr-thread-desc { margin-top: 3px; color: #788395; font-size: 11px; line-height: 1.4; }
.cr-thread-note { padding: 8px 10px; border-top: 1px solid #e0e6ef; color: #788395; font-size: 11px; line-height: 1.5; }

/* 中栏 */
.cr-toolbar { min-height: 44px; display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid #e0e6ef; }
.cr-toolbar-meta { margin-left: auto; color: #788395; font-size: 12px; }
.cr-action-list { overflow: auto; flex: 1; min-height: 0; }
.cr-action-row { min-height: 90px; border-bottom: 1px solid #e0e6ef; display: grid; grid-template-columns: 1fr 140px; gap: 12px; padding: 12px; cursor: pointer; transition: all .15s; }
.cr-action-row:hover { background: #fffdf8; }
.cr-action-row.active { background: #fffaf0; box-shadow: inset 3px 0 0 #c98716; }
.cr-action-row.done { opacity: .5; }
.cr-customer-name { font-weight: 800; margin-bottom: 4px; }
.cr-customer-meta { display: flex; gap: 6px; color: #788395; font-size: 12px; flex-wrap: wrap; }
.cr-action-reason { margin-top: 6px; color: #344155; font-size: 12px; line-height: 1.45; }
.cr-cell-label { color: #788395; font-size: 11px; margin-bottom: 4px; }
.cr-action-text { font-weight: 800; font-size: 12px; color: #344155; line-height: 1.4; }

/* 右栏 */
.cr-profile-head { padding: 12px 14px; border-bottom: 1px solid #e0e6ef; flex-shrink: 0; }
.cr-profile-head h2 { margin: 0; font-size: 17px; }
.cr-profile-meta { display: flex; gap: 5px; margin-top: 6px; flex-wrap: wrap; }
.cr-profile-scroll { padding: 10px 14px; overflow: auto; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 10px; }

.cr-section { border-bottom: 1px solid #e0e6ef; padding-bottom: 10px; }
.cr-section:last-child { border-bottom: 0; padding-bottom: 0; }
.cr-section-title { display: flex; align-items: center; gap: 6px; font-weight: 800; font-size: 13px; margin-bottom: 8px; color: #162033; }
.cr-section-title .el-icon { color: #c98716; }
.cr-judgement { border-radius: 8px; border: 1px solid #f0d8a7; background: #fff7e8; color: #493412; padding: 10px; font-size: 12px; line-height: 1.55; font-weight: 600; }
.cr-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.cr-signal-list { display: flex; flex-direction: column; gap: 6px; }
.cr-signal-item { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; color: #344155; line-height: 1.45; }
.cr-signal-item .el-button { margin-left: auto; flex-shrink: 0; }

.cr-message-box { border: 1px solid #f0d8a7; border-radius: 8px; overflow: hidden; }
.cr-message-head { display: flex; justify-content: space-between; align-items: center; padding: 5px 8px; background: #fff7e8; color: #7d530b; font-weight: 800; font-size: 12px; }

.cr-profile-actions { padding: 10px 14px; border-top: 1px solid #e0e6ef; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; flex-shrink: 0; }
.cr-empty-panel { display: flex; align-items: center; justify-content: center; }

/* 抽屉 */
.cr-source-list { display: flex; flex-direction: column; gap: 10px; }
.cr-source-record { border: 1px solid #e0e6ef; border-radius: 8px; padding: 10px; }
.cr-source-title { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; font-weight: 800; }
.cr-source-meta { color: #788395; font-size: 11px; margin-top: 4px; }
.cr-source-summary { border-radius: 6px; background: #fff7e8; border: 1px solid #f0d8a7; color: #493412; padding: 8px; font-size: 12px; margin-top: 6px; }
.cr-source-raw { white-space: pre-wrap; word-break: break-word; background: #f7f9fc; border: 1px solid #e0e6ef; border-radius: 6px; padding: 8px; font-size: 11px; margin-top: 6px; font-family: Consolas, monospace; }

@media (max-width: 1100px) {
  .cr-workspace { grid-template-columns: 200px 1fr 340px; }
  .cr-action-row { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .cr-workspace { grid-template-columns: 1fr; }
  .customer-radar { height: auto; overflow: visible; }
}
</style>

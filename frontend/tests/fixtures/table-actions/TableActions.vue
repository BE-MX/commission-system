<template>
  <main :class="{ legacy }">
    <h1>操作列回归验证</h1>
    <p>隔离数据，不连接业务 API。已点击：<output>{{ lastAction || '无' }}</output></p>
    <label><input v-model="legacy" type="checkbox">模拟旧版单行裁切</label>
    <label><input v-model="canEdit" type="checkbox">显示编辑权限按钮</label>
    <label><input v-model="narrow" type="checkbox">320px 窄容器</label>
    <div :style="{ maxWidth: narrow ? '320px' : '100%' }">
      <h2>内贸订单 · 草稿五按钮 / 待审核 / 已终止</h2>
      <el-table :data="orders" border class="list-table" scrollbar-always-on>
        <el-table-column label="订单" prop="name" min-width="140" fixed="left" />
        <el-table-column label="客户" min-width="120" fixed="left"><template #default>测试客户</template></el-table-column>
        <el-table-column label="备注" min-width="420" show-overflow-tooltip><template #default>普通文本列仍然采用省略展示，不受操作列布局影响。</template></el-table-column>
        <el-table-column label="操作" min-width="270" class-name="table-action-column">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="act('详情')">详情</GlassButton>
            <GlassButton variant="link" left-icon="Download" @click="act('导出')">导出</GlassButton>
            <template v-if="row.status === 5">
              <GlassButton variant="link" left-icon="Stamp" @click="act('通过')">通过</GlassButton>
              <GlassButton variant="link" left-icon="CircleClose" @click="act('驳回')">驳回</GlassButton>
            </template>
            <GlassButton v-if="canEdit && row.status === 0" variant="link" left-icon="EditPen" @click="act('编辑')">编辑</GlassButton>
            <GlassButton v-if="row.status === 0" variant="link" left-icon="Promotion" @click="act('提交')">提交</GlassButton>
            <GlassButton v-else variant="link" left-icon="CircleClose" :disabled="row.status === 4" @click="act('终止')">终止</GlassButton>
            <GlassButton variant="link" left-icon="Delete" link-tone="danger" @click="act('删除')">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>

      <h2>固定列 · 发票按钮组 / 下拉菜单 / 加载态</h2>
      <el-table :data="[{}]" border class="list-table" scrollbar-always-on>
        <el-table-column label="编号" min-width="140" fixed="left"><template #default>INV-TEST</template></el-table-column>
        <el-table-column label="商品" min-width="480"><template #default>测试产品</template></el-table-column>
        <el-table-column label="操作" min-width="356" fixed="right" class-name="table-action-column">
          <template #default>
            <div class="table-actions">
              <el-button link @click="act('编辑发票')"><el-icon><Edit /></el-icon>编辑</el-button>
              <el-dropdown trigger="click" @command="act">
                <el-button link><el-icon><Download /></el-icon>导出<el-icon><ArrowDown /></el-icon></el-button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="Excel">Excel</el-dropdown-item><el-dropdown-item command="PDF">PDF</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
              <el-button link loading>同步中</el-button>
              <el-button link @click="act('日志')">日志</el-button>
              <el-button link @click="act('处理待核对')">处理待核对</el-button>
              <el-popconfirm title="确认测试删除？" @confirm="act('确认删除')"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <h2>小列宽 · 长文字 / 64px 图标 / 普通表格</h2>
      <el-table :data="[{}]" border scrollbar-always-on>
        <el-table-column label="商品" min-width="120"><template #default>测试产品</template></el-table-column>
        <el-table-column label="操作" width="100" class-name="table-action-column"><template #default><GlassButton variant="link" left-icon="Edit" @click="act('修改邮箱/密码')">修改邮箱/密码</GlassButton></template></el-table-column>
        <el-table-column label="操作" width="64" class-name="table-action-column"><template #default><el-button link aria-label="删除产品" @click="act('删除产品')"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
        <el-table-column label="操作" width="160" class-name="table-action-column"><template #default><div class="table-actions"><el-button plain @click="act('AI')">AI</el-button><el-button plain @click="act('生产下单')"><el-icon><Plus /></el-icon>生产下单</el-button></div></template></el-table-column>
      </el-table>
    </div>
  </main>
</template>

<script setup>
import { ref } from 'vue'
const legacy = ref(false), narrow = ref(false), canEdit = ref(true), lastAction = ref('')
const orders = [{ name: '草稿', status: 0 }, { name: '待审核', status: 5 }, { name: '已终止', status: 4 }]
const act = name => { lastAction.value = name }
</script>

<style scoped>
main { padding: 16px; }
h1 { font-size: 20px; }
h2 { font-size: 16px; margin-top: 24px; }
label { display: inline-block; margin: 0 16px 12px 0; }
.legacy :deep(.el-table .el-table__body td.table-action-column > .cell) { display: block; white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis; }
.legacy :deep(.table-actions) { flex-wrap: nowrap; }
.legacy :deep(.table-action-column .glass-button) { white-space: nowrap; }
</style>

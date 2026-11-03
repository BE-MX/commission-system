<template>
  <el-form v-if="node" label-position="top" class="navigation-form" :disabled="disabled">
    <div class="node-origin"><el-tag size="small">{{ node.kind === 'group' ? (node.parent ? '二级分类' : '一级分类') : '页面入口' }}</el-tag><StatusBadge v-if="node.protected" size="small" type="warning" effect="plain">受保护</StatusBadge></div>
    <el-form-item label="导航名称" :error="nodeErrors.find(e => e.message.includes('名称'))?.message"><el-input v-model="node.label" maxlength="48" /></el-form-item>
    <el-form-item label="导航图标"><el-select v-model="node.icon" filterable placeholder="搜索英文图标名称" class="full-width"><el-option v-for="icon in icons" :key="icon" :label="`${iconLabels[icon] || ''} ${icon}`" :value="icon"><el-icon><component :is="iconSet[icon]" /></el-icon> {{ iconLabels[icon] || icon }} <small>{{ iconLabels[icon] ? icon : '' }}</small></el-option></el-select></el-form-item>
    <el-form-item label="所属分类"><el-select v-model="node.parent" placeholder="主导航" :disabled="node.protected || node.builtin && node.kind === 'group'" class="full-width" @change="node.order = nextSiblingOrder(nodes, node.parent, node.id)"><el-option v-if="node.kind === 'group' || !node.external" label="主导航" value=""/><el-option v-for="group in parents" :key="group.id" :label="`${group.parent ? '　' : ''}${group.label}`" :value="group.id" /></el-select></el-form-item>
    <el-divider />
    <el-form-item label="文字角标" :error="nodeErrors.find(e => e.message.includes('角标'))?.message"><el-input v-model="node.badge" placeholder="如：新上线" maxlength="16" clearable /></el-form-item>
    <div class="navigation-field-pair"><el-form-item label="角标位置"><el-select v-model="node.badgePlace"><el-option label="名称右侧" value="text"/><el-option label="图标右上角" value="icon"/></el-select></el-form-item><el-form-item label="角标色调"><el-select v-model="node.badgeTone"><el-option label="品牌金" value="gold"/><el-option label="信息蓝" value="blue"/><el-option label="中性灰" value="neutral"/></el-select></el-form-item></div>
    <div class="navigation-setting"><div><strong>在导航中显示</strong><p v-if="node.kind === 'group'">关闭将隐藏 {{ descendantIds(nodes, node.id).size - 1 }} 个后代入口，保留内部配置。</p><p v-else>仅影响入口展示，保留已有访问权限。</p></div><el-switch v-model="node.visible" :disabled="node.protected" /></div>
    <div v-if="node.kind === 'page'" class="navigation-setting"><div><strong>同步页面标题</strong><p>同步页签与浏览器标题，页面地址保持不变。</p></div><el-switch v-model="node.titleSync"/></div>
    <section v-if="node.kind === 'page'" class="navigation-source"><strong>注册来源 · 只读</strong><p>{{ node.path || '已注册页面' }}</p><p v-if="node.rule">访问规则：{{ typeof node.rule === 'string' ? node.rule : JSON.stringify(node.rule) }}</p><p v-if="node.phase">业务阶段：{{ node.phase }}</p><p v-if="node.business">业务提醒：{{ typeof node.business === 'string' ? node.business : JSON.stringify(node.business) }}。提醒优先于文字角标，数量由业务系统提供。</p></section>
    <el-alert v-for="item in nodeErrors.filter(e => !e.message.includes('名称') && !e.message.includes('角标'))" :key="item.message" :title="item.message" type="error" :closable="false"/>
    <div class="navigation-editor-actions"><el-button v-permission="'navigation:write'" :disabled="filtered || !canUp" @click="$emit('move', -1)" aria-label="将当前节点上移">↑ 上移</el-button><el-button v-permission="'navigation:write'" :disabled="filtered || !canDown" @click="$emit('move', 1)" aria-label="将当前节点下移">↓ 下移</el-button><el-button v-permission="'navigation:write'" v-if="node.kind === 'group' && !node.parent" @click="$emit('add', node.id)">新增二级分类</el-button></div>
    <el-button v-permission="'navigation:write'" v-if="!node.protected && (!node.builtin && node.kind === 'group' || node.missing)" type="danger" plain :disabled="nodes.some(n => n.parent === node.id)" @click="$emit('remove')">{{ node.missing ? '移除下线引用' : '删除空分类' }}</el-button>
  </el-form>
  <el-empty v-else description="选择一个导航节点开始编辑" />
</template>
<script setup>
import { computed } from 'vue'
import StatusBadge from '@/components/StatusBadge.vue'
import * as iconSet from '@element-plus/icons-vue'
import { childrenOf, descendantIds, nextSiblingOrder } from './navigationEditor'
const iconLabels = { Folder: '分类 文件夹', Document: '单据 文档', Setting: '设置 系统', User: '用户 人员', UserFilled: '用户 人员', House: '首页 工作台', HomeFilled: '首页 工作台', DataAnalysis: '分析 数据', OfficeBuilding: '公司 客户', Box: '库存 备货', Picture: '图片 素材', Reading: '阅读 知识', Connection: '连接 导航', Money: '金额 财务', ShoppingCart: '购物 订单', Search: '搜索', Bell: '通知 提醒', Calendar: '日历 排期', Truck: '物流 发货', Lock: '锁 权限', Clock: '时间 历史', Message: '邮件 消息', Star: '星标 收藏', Menu: '菜单 导航', Tools: '工具' }
const props = defineProps({ node: Object, nodes: Array, icons: Array, errors: Array, disabled: Boolean, filtered: Boolean })
defineEmits(['move', 'add', 'remove'])
const nodeErrors = computed(() => props.errors.filter(e => e.id === props.node?.id))
const parents = computed(() => props.nodes.filter(n => n.kind === 'group' && !descendantIds(props.nodes, props.node?.id).has(n.id) && (props.node?.kind !== 'group' || !n.parent)))
const siblings = computed(() => childrenOf(props.nodes, props.node?.parent))
const canUp = computed(() => siblings.value.indexOf(props.node) > 0)
const canDown = computed(() => siblings.value.indexOf(props.node) < siblings.value.length - 1)
</script>

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import * as api from '@/api/navigationConfig'
import { confirmAction, isFeedbackCancelled, msgError, msgSuccessText, msgWarning, promptAction } from '@/utils/feedback'
import { childrenOf, descendantIds, diffNodes, mergeNodes, nextSiblingOrder, reorderNode, restoreSourceIcons, sameWritableNodes, validateNodes, writableNodes } from './navigationEditor'
export function useNavigationEditor() {
  const nodes = ref([]), catalog = ref([]), icons = ref([]), versions = ref([]), selectedId = ref('')
  const loading = ref(false), busy = ref(false), blocked = ref(false), error = ref(''), conflict = ref(false)
  const revision = ref(0), baseVersion = ref(0), catalogHash = ref(''), saved = ref(''), baseline = ref([])
  const pendingSave = ref(null)
  const historyOpen = ref(false), publishOpen = ref(false), publishRequest = ref('')
  const selected = computed(() => nodes.value.find(node => node.id === selectedId.value))
  const snapshot = computed(() => JSON.stringify(writableNodes(nodes.value)))
  const dirty = computed(() => snapshot.value !== saved.value)
  const errors = computed(() => validateNodes(nodes.value, icons.value))
  const changes = computed(() => diffNodes(baseline.value, writableNodes(nodes.value)))
  const emptyGroups = computed(() => nodes.value.filter(node => node.kind === 'group' && !childrenOf(nodes.value, node.id).length))
  function acceptDraft(data) {
    publishRequest.value = ''; pendingSave.value = null
    nodes.value = mergeNodes(catalog.value, data.nodes || [])
    revision.value = data.draft_revision; baseVersion.value = data.base_version
    catalogHash.value = data.catalog_hash || catalogHash.value
    saved.value = snapshot.value
    const current = versions.value.find(item => item.version === baseVersion.value)
    baseline.value = writableNodes(current?.nodes || catalog.value)
    if (!nodes.value.some(node => node.id === selectedId.value)) selectedId.value = nodes.value[0]?.id || ''
  }
  async function load() {
    loading.value = true; error.value = ''
    try {
      const [c, d, v] = await Promise.all([api.getNavigationCatalog(), api.getNavigationDraft(), api.getNavigationVersions()])
      catalog.value = c.data.nodes; icons.value = (c.data.icons || []).map(icon => typeof icon === 'string' ? icon : icon.key || icon.name)
      catalogHash.value = c.data.catalog_hash; versions.value = v.data.items || []
      acceptDraft(d.data); conflict.value = false; blocked.value = false
    } catch (e) { error.value = '导航配置加载失败，请重试'; msgError(error.value, e) }
    finally { loading.value = false }
  }
  function handleError(e, action) {
    const status = e.response?.status
    if (status === 409) { conflict.value = true; msgWarning('共享草稿或目录已变化，本地编辑已保留。请先查看最新版本，再重新载入。') }
    else if (status === 403) { blocked.value = true; msgWarning('编辑权限已变更，本地输入已保留，当前停止提交。') }
    else msgError(`${action}失败，输入已保留`, e)
  }
  function metadata() { return { draft_revision: revision.value, base_version: baseVersion.value, catalog_hash: catalogHash.value } }
  async function reconcileSave() {
    const pending = pendingSave.value
    try {
      const { data } = await api.getNavigationDraft()
      if (data.draft_revision > pending.draft_revision && data.base_version === pending.base_version && data.catalog_hash === pending.catalog_hash && sameWritableNodes(data.nodes, pending.nodes) && sameWritableNodes(nodes.value, pending.nodes)) {
        acceptDraft(data); msgSuccessText('已核对服务器，草稿已保存，尚未发布'); return true
      }
      pendingSave.value = null; conflict.value = true
      msgWarning('保存结果与本地提交不一致，本地编辑已保留。请查看最新草稿后重新载入。'); return false
    } catch (e) {
      if (e.response?.status === 403) handleError(e, '核对保存结果')
      else msgError('暂时无法核对保存结果，输入已保留；再次保存将先核对服务器，不会重复写入。', e)
      return false
    }
  }
  async function save() {
    if (busy.value || blocked.value || conflict.value) return false
    if (errors.value.length) { selectedId.value = errors.value[0].id; msgWarning(errors.value[0].message); return false }
    busy.value = true
    try {
      if (pendingSave.value) return await reconcileSave()
      const request = { ...metadata(), nodes: writableNodes(nodes.value) }
      pendingSave.value = request
      const result = await api.saveNavigationDraft(request)
      acceptDraft(result.data); publishRequest.value = ''; msgSuccessText('草稿已保存，尚未发布'); return true
    } catch (e) {
      if (!e.response) return await reconcileSave()
      pendingSave.value = null; handleError(e, '保存'); return false
    }
    finally { busy.value = false }
  }
  async function preparePublish() {
    if (dirty.value && !await save()) return
    if (!errors.value.length) publishOpen.value = true
  }
  async function publish() {
    if (busy.value || blocked.value || conflict.value) return
    publishRequest.value ||= crypto.randomUUID(); busy.value = true
    try {
      await api.publishNavigationDraft({ ...metadata(), request_id: publishRequest.value })
      publishOpen.value = false; publishRequest.value = ''; window.dispatchEvent(new CustomEvent('ark-navigation-updated'))
      msgSuccessText('导航已发布'); await load()
    } catch (e) { handleError(e, '发布'); if (!e.response) msgWarning('发布结果暂未确认。再次提交会使用相同请求标识，避免重复发布。') }
    finally { busy.value = false }
  }
  async function addGroup(parent = '') {
    try {
      const { value } = await promptAction('请输入分类名称（1–24 字符）', parent ? '新增二级分类' : '新增一级分类', { inputValidator: value => !!value.trim() && [...value.trim()].length <= 24 || '请输入 1–24 个字符', confirmButtonText: '新增', cancelButtonText: '取消' })
      const node = { id: `custom-${crypto.randomUUID()}`, kind: 'group', label: value.trim(), icon: 'Folder', parent, order: nextSiblingOrder(nodes.value, parent), visible: true, badge: '', badgePlace: 'text', badgeTone: 'gold', titleSync: false, builtin: false }
      nodes.value.push(node); selectedId.value = node.id
    } catch (e) { if (!isFeedbackCancelled(e)) msgError('新增失败', e) }
  }
  async function removeSelected() {
    const node = selected.value
    if (!node || node.protected || node.builtin || node.kind !== 'group' && !node.missing) return
    if (childrenOf(nodes.value, node.id).length) { msgWarning('请先移动分类内的页面和子分类'); return }
    try {
      await confirmAction(`删除「${node.label}」？仅删除导航配置引用。`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
      nodes.value = nodes.value.filter(item => item.id !== node.id); selectedId.value = nodes.value[0]?.id || ''
    } catch (e) { if (!isFeedbackCancelled(e)) msgError('删除失败', e) }
  }
  function move(direction) {
    const node = selected.value; if (!node) return
    const siblings = childrenOf(nodes.value, node.parent), index = siblings.indexOf(node), target = siblings[index + direction]
    if (!target) return
    if (direction < 0) reorderNode(nodes.value, node.id, target.id)
    else reorderNode(nodes.value, target.id, node.id)
  }
  async function restore(version) {
    try {
      await confirmAction(`将 V${version.version} 复制为共享草稿？${dirty.value ? '当前未保存编辑将被替换。' : ''}线上版本保持不变。`, '恢复为草稿', { confirmButtonText: '恢复草稿', cancelButtonText: '取消' })
      busy.value = true
      const result = await api.restoreNavigationVersion(version.id, metadata()); acceptDraft(result.data)
      historyOpen.value = false; msgSuccessText('已恢复为草稿，请检查后发布')
    } catch (e) { if (!isFeedbackCancelled(e)) handleError(e, '恢复') }
    finally { busy.value = false }
  }
  async function leave() {
    if (!dirty.value) return true
    try {
      await confirmAction('存在未保存修改，是否保存后离开？', '离开导航管理', { distinguishCancelAndClose: true, confirmButtonText: '保存并离开', cancelButtonText: '放弃修改' })
      return await save()
    } catch (e) {
      if (e === 'cancel') { nodes.value = mergeNodes(catalog.value, JSON.parse(saved.value)); return true }
      return false
    }
  }
  async function restoreDefaultIcons() {
    if (busy.value || loading.value || blocked.value || conflict.value || pendingSave.value) return
    const restored = restoreSourceIcons(nodes.value, catalog.value)
    const count = restored.filter((node, i) => node.icon !== nodes.value[i].icon).length
    if (!count) { msgSuccessText('已是系统默认图标'); return }
    try {
      await confirmAction(`将 ${count} 个内置导航恢复为系统默认图标？名称、分类、角标和自建分类图标保持原样；确认后仅修改当前编辑内容，保存草稿或发布需另行操作。`, '恢复系统默认图标', { confirmButtonText: '恢复图标', cancelButtonText: '取消' })
      nodes.value = restored; publishRequest.value = ''
      msgSuccessText('默认图标已恢复到当前编辑内容，请预览后保存')
    } catch (e) { if (!isFeedbackCancelled(e)) msgError('恢复默认图标失败', e) }
  }
  function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
  onBeforeRouteLeave(leave)
  onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
  return { nodes, catalog, icons, versions, selectedId, selected, loading, busy, blocked, error, conflict, baseVersion, dirty, errors, changes, emptyGroups, historyOpen, publishOpen, load, save, preparePublish, publish, addGroup, removeSelected, move, restore, restoreDefaultIcons, descendantIds }
}

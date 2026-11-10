import { computed, onUnmounted, ref, watch } from 'vue'
import { alibabaFeedApi as api } from '@/api/alibabaFeed'
import { clientDeskApi } from '@/api/clientDesk'
import { useAuthStore } from '@/stores/auth'
import { useListPage } from '@/composables/useListPage'
import { errorMessage } from '@/utils/errors'
import { confirmAction, isFeedbackCancelled, msgSuccessText } from '@/utils/feedback'
import { analysisSelection, createReadScope, createRequestTask, canReadRecord, visibilityLabel } from './feedState'

export function useAlibabaFeed(showRecords) {
  const auth = useAuthStore()
  const detail = ref(null), detailVisible = ref(false), detailLoading = ref(false), detailError = ref('')
  const selected = ref([]), saving = ref(false), actionError = ref(''), uncertain = ref(false)
  const linkVisible = ref(false), linkRow = ref(null), companyId = ref(''), customerKeyword = ref('')
  const customers = ref([]), customerTotal = ref(0), customerPage = ref(1), customerPageSize = ref(20), customerLoading = ref(false), customerError = ref('')
  const detailScope = createReadScope(), customerScope = createReadScope(), task = createRequestTask()
  let authority = 0
  function clearDetail() {
    detailScope.clear(); detail.value = null; detailVisible.value = false; detailLoading.value = false; detailError.value = ''
  }
  function clearCustomers() {
    customerScope.clear(); customers.value = []; customerTotal.value = 0; customerLoading.value = false
    companyId.value = ''; customerError.value = ''
  }
  const listPage = useListPage(async (params, { signal, isCurrent }) => {
    selected.value = []
    // A failed read must never leave another authority's private rows visible.
    listPage.list.value = []; listPage.total.value = 0
    try { return await api.records(params, signal) }
    catch (error) {
      if (isCurrent() && [401, 403, 404, 503].includes(error.response?.status)) {
        clearDetail(); clearCustomers(); linkVisible.value = false
      }
      throw error
    }
  }, { immediate: false, searchForm: { linked: 'unlinked', keyword: '' } })
  const listError = computed(() => {
    const status = listPage.error.value?.response?.status
    if (status === 503) return 'TM 资料试点尚未启用'
    if (status === 403) return '当前账号没有 TM 资料试点的访问权限'
    return listPage.errorMessage.value
  })
  const selection = computed(() => analysisSelection(selected.value))

  watch(() => JSON.stringify([auth.user?.id, auth.permissions, auth.roles, showRecords.value]), () => {
    authority += 1
    clearDetail(); clearCustomers(); selected.value = []; linkVisible.value = false
    listPage.cancel(); listPage.list.value = []; listPage.total.value = 0
    actionError.value = ''; uncertain.value = false; saving.value = false; task.complete()
    if (showRecords.value) listPage.fetchList()
  }, { immediate: true, flush: 'sync' })

  async function openDetail(row) {
    if (!canReadRecord(row)) { clearDetail(); actionError.value = visibilityLabel(row); return }
    clearDetail(); detailVisible.value = true; detailLoading.value = true
    const scope = detailScope.begin()
    try {
      const value = await api.record(row.id, scope.signal)
      if (scope.isCurrent()) detail.value = value
    } catch (error) {
      if (scope.isCurrent()) detailError.value = error.response?.status === 503 ? 'TM资料尚未开放' : errorMessage(error)
    } finally { if (scope.isCurrent()) detailLoading.value = false }
  }
  async function searchCustomers(page = 1) {
    companyId.value = ''; customers.value = []; customerTotal.value = 0; customerError.value = ''
    customerPage.value = page; customerLoading.value = true
    const scope = customerScope.begin()
    try {
      const data = await api.customers({ keyword: customerKeyword.value, page, page_size: customerPageSize.value }, scope.signal)
      if (scope.isCurrent()) { customers.value = data.items; customerTotal.value = data.total }
    } catch (error) { if (scope.isCurrent()) customerError.value = errorMessage(error) }
    finally { if (scope.isCurrent()) customerLoading.value = false }
  }
  function openLink(row) {
    if (saving.value || uncertain.value) return
    clearCustomers(); linkRow.value = row; linkVisible.value = true; customerKeyword.value = ''
    searchCustomers()
  }
  // Mutations never retry automatically. Unknown outcomes retain their request task.
  async function mutate(work, success) {
    if (saving.value || uncertain.value || !auth.hasPermission('client_desk:write')) return
    const current = authority
    saving.value = true; actionError.value = ''
    try {
      await work()
      if (current !== authority) return
      task.complete(); clearDetail(); clearCustomers(); linkVisible.value = false
      msgSuccessText(success)
      await listPage.refreshUpdate()
    } catch (error) {
      if (current !== authority) return
      if (!error.response || error.response.status >= 500) {
        uncertain.value = true; task.uncertain()
        actionError.value = '操作结果待核对，未自动重试。请刷新资料核对关联；分析任务请到私海助理查看。'
      } else {
        task.complete(); actionError.value = errorMessage(error)
        if ([401, 403, 404, 409].includes(error.response.status)) {
          clearDetail(); clearCustomers(); linkVisible.value = false
          await listPage.refreshUpdate()
        }
      }
    } finally { if (current === authority) saving.value = false }
  }
  function linkCustomer() {
    const row = linkRow.value
    if (!row || !companyId.value || !customers.value.some(c => String(c.company_id) === String(companyId.value))) return
    const data = { item_id: row.id, company_id: companyId.value, expected_mapping_version: row.mapping_version }
    data.client_request_id = task.begin('link', data)
    return mutate(() => api.link(data), '资料已关联，客户归属未变更')
  }
  async function unlink(row) {
    if (!row.link || saving.value || uncertain.value) return
    try { await confirmAction('撤销资料匹配后，将清空当前详情。客户归属不会改变。', '撤销关联', { confirmButtonText: '撤销关联', cancelButtonText: '取消', type: 'warning' }) }
    catch (error) { if (isFeedbackCancelled(error)) return; throw error }
    clearDetail(); selected.value = []
    task.begin('unlink', [row.link.id, row.link.version])
    return mutate(() => api.unlink(row.link.id, row.link.version), '资料关联已撤销')
  }
  async function reanalyze() {
    if (!selection.value.valid || saving.value || uncertain.value) return
    const chosen = selection.value
    const current = authority
    try { await confirmAction(`将 ${chosen.itemIds.length} 条历史资料用于当前关联客户的本次人工分析；不进入早报，计入该客户每日 3 次额度。`, '选入人工重分析', { confirmButtonText: '提交本次分析', cancelButtonText: '取消' }) }
    catch (error) { if (isFeedbackCancelled(error)) return; throw error }
    if (current !== authority || !selection.value.valid || JSON.stringify(selection.value.itemIds) !== JSON.stringify(chosen.itemIds)) return
    const clientRequestId = task.begin('analysis', [chosen.companyId, [...chosen.itemIds].sort((a, b) => a - b)])
    return mutate(() => clientDeskApi.reanalyze(chosen.companyId, { client_request_id: clientRequestId, feed_item_ids: chosen.itemIds }), '分析任务已提交，请到私海助理查看结果')
  }
  watch(detailVisible, visible => { if (!visible) clearDetail() })
  watch(linkVisible, visible => { if (!visible) { clearCustomers(); linkRow.value = null } })
  onUnmounted(() => { authority += 1; clearDetail(); clearCustomers() })
  return { listPage, listError, detail, detailVisible, detailLoading, detailError, clearDetail, openDetail,
    selected, selection, saving, actionError, uncertain, linkVisible, linkRow, companyId, customerKeyword,
    customers, customerTotal, customerPage, customerPageSize, customerLoading, customerError, searchCustomers, openLink, linkCustomer, unlink, reanalyze }
}

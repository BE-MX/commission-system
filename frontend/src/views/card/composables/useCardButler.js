/**
 * 名片管家页 state + 方法（宪法 12：页面逻辑全量下沉 composable，主文件留薄壳）。
 * 三块：客户档案（口令绑定+纪要）/ 询盘 / 业务员档案。
 */
import { onMounted, reactive, ref } from 'vue'
import {
  createCustomer, createEntry, deleteCustomer, deleteEntry,
  getCustomers, getEntries, getInquiries, getSalespersons,
  updateCustomer, updateInquiry, upsertSalesperson,
} from '@/api/card'
import { useListPage } from '@/composables/useListPage'
import { confirmDanger, msgError, msgSuccess } from '@/utils/feedback'

export function useCardButler() {
  // ---------- 业务员档案 ----------
  const salespersons = ref([])
  const spDialogVisible = ref(false)
  const spSaving = ref(false)
  const spForm = reactive({ slug: '', name: '', title: 'Sales Manager', email: '', whatsapp: '', intro: '', is_active: 1 })

  async function fetchSalespersons() {
    const res = await getSalespersons()
    salespersons.value = res.data ?? res ?? []
  }

  function openSpDialog(row) {
    Object.assign(spForm, {
      slug: row?.slug ?? '', name: row?.name ?? '', title: row?.title ?? 'Sales Manager',
      email: row?.email ?? '', whatsapp: row?.whatsapp ?? '', intro: row?.intro ?? '',
      is_active: row?.is_active ?? 1,
    })
    spDialogVisible.value = true
  }

  async function saveSalesperson() {
    if (!spForm.slug || !spForm.name || !spForm.email) { msgError('slug / 英文名 / 邮箱必填'); return }
    spSaving.value = true
    try {
      await upsertSalesperson({ ...spForm, whatsapp: spForm.whatsapp || null, intro: spForm.intro || null })
      spDialogVisible.value = false
      msgSuccess('保存')
      await fetchSalespersons()
    } finally {
      spSaving.value = false
    }
  }

  // ---------- 客户档案 ----------
  const customerPage = useListPage(async params => {
    const res = await getCustomers({
      page: params.page, page_size: params.page_size,
      salesperson_id: params.salesperson_id || undefined,
      keyword: params.keyword || undefined,
    })
    const payload = res.data ?? res
    return { items: payload.items, total: payload.total }
  }, { searchForm: { salesperson_id: null, keyword: '' } })

  const customerDialogVisible = ref(false)
  const customerSaving = ref(false)
  const customerForm = reactive({
    id: null, salesperson_id: null, display_name: '', email: '', whatsapp: '', expo_code: '2026-08', remark: '',
  })

  function openCustomerDialog(row) {
    Object.assign(customerForm, {
      id: row?.id ?? null,
      salesperson_id: row?.salesperson_id ?? customerPage.searchForm.salesperson_id ?? null,
      display_name: row?.display_name ?? '',
      email: row?.email_norm ?? '',
      whatsapp: row?.whatsapp_norm ?? '',
      expo_code: row?.expo_code ?? '2026-08',
      remark: row?.remark ?? '',
    })
    customerDialogVisible.value = true
  }

  async function saveCustomer() {
    if (!customerForm.display_name) { msgError('客户称呼必填'); return }
    if (!customerForm.email && !customerForm.whatsapp) { msgError('邮箱和 WhatsApp 至少填一个——它就是客户口令'); return }
    if (!customerForm.id && !customerForm.salesperson_id) { msgError('请选择归属业务员'); return }
    customerSaving.value = true
    try {
      const body = {
        display_name: customerForm.display_name,
        email: customerForm.email, whatsapp: customerForm.whatsapp,
        expo_code: customerForm.expo_code, remark: customerForm.remark || null,
      }
      if (customerForm.id) {
        await updateCustomer(customerForm.id, body)
      } else {
        await createCustomer({ ...body, salesperson_id: customerForm.salesperson_id })
      }
      customerDialogVisible.value = false
      msgSuccess('保存')
      await customerPage.fetchList()
    } finally {
      customerSaving.value = false
    }
  }

  async function removeCustomer(row) {
    try {
      await confirmDanger('删除', row.display_name, '将连带删除全部纪要，客户口令随即失效。')
    } catch { return }
    await deleteCustomer(row.id)
    msgSuccess('删除')
    await customerPage.fetchList()
  }

  // ---------- 沟通纪要抽屉 ----------
  const entriesVisible = ref(false)
  const entriesLoading = ref(false)
  const entrySaving = ref(false)
  const entries = ref([])
  const currentCustomer = ref(null)
  const entryForm = reactive({ title: '', content: '' })
  const entryFiles = ref([]) // AppUpload v-model [{path,url,name}]

  async function openEntries(row) {
    currentCustomer.value = row
    entriesVisible.value = true
    entryForm.title = ''
    entryForm.content = ''
    entryFiles.value = []
    await refreshEntries()
  }

  async function refreshEntries() {
    if (!currentCustomer.value) return
    entriesLoading.value = true
    try {
      const res = await getEntries(currentCustomer.value.id)
      entries.value = res.data ?? res ?? []
    } finally {
      entriesLoading.value = false
    }
  }

  async function saveEntry() {
    const hasText = entryForm.content.trim()
    const files = entryFiles.value
    if (!hasText && !files.length) { msgError('写点内容或传张图') ; return }
    entrySaving.value = true
    try {
      if (files.length) {
        // 一张图一条纪要；文字内容随第一条走
        for (let i = 0; i < files.length; i++) {
          await createEntry(currentCustomer.value.id, {
            title: entryForm.title || null,
            content: i === 0 ? (entryForm.content || null) : null,
            attachment_path: files[i].path,
          })
        }
      } else {
        await createEntry(currentCustomer.value.id, {
          title: entryForm.title || null, content: entryForm.content, attachment_path: null,
        })
      }
      msgSuccess('录入')
      entryForm.title = ''
      entryForm.content = ''
      entryFiles.value = []
      await refreshEntries()
      await customerPage.fetchList()
    } finally {
      entrySaving.value = false
    }
  }

  async function removeEntry(entry) {
    try {
      await confirmDanger('删除', entry.title || '这条纪要')
    } catch { return }
    await deleteEntry(entry.id)
    msgSuccess('删除')
    await refreshEntries()
  }

  // ---------- 询盘 ----------
  const inquiryPage = useListPage(async params => {
    const res = await getInquiries({
      page: params.page, page_size: params.page_size,
      status: params.status || undefined,
      salesperson_id: params.salesperson_id || undefined,
    })
    const payload = res.data ?? res
    return { items: payload.items, total: payload.total }
  }, { searchForm: { status: 'new', salesperson_id: null } })

  async function markHandled(row) {
    await updateInquiry(row.id, { status: row.status === 'new' ? 'handled' : 'new' })
    msgSuccess('更新')
    await inquiryPage.fetchList()
  }

  onMounted(fetchSalespersons)

  return {
    salespersons, fetchSalespersons,
    spDialogVisible, spSaving, spForm, openSpDialog, saveSalesperson,
    customerPage, customerDialogVisible, customerSaving, customerForm,
    openCustomerDialog, saveCustomer, removeCustomer,
    entriesVisible, entriesLoading, entrySaving, entries, currentCustomer,
    entryForm, entryFiles, openEntries, saveEntry, removeEntry,
    inquiryPage, markHandled,
  }
}

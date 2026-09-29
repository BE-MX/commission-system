import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as customerMediaApi from '@/api/customerMedia'

export function useCustomerMediaPortalPreview({
  api = customerMediaApi,
  route,
  router,
} = {}) {
  const customers = ref([])
  const selectedCustomerId = ref('')
  const detail = ref(null)
  const customerSearch = ref('')
  const loadingCustomers = ref(false)
  const loadingDetail = ref(false)
  const detailError = ref('')
  let customerRequestVersion = 0
  let detailRequestVersion = 0

  const filteredCustomers = computed(() => {
    const query = customerSearch.value.trim().toLowerCase()
    if (!query) return customers.value
    return customers.value.filter(customer => [
      customer.customer_name,
      customer.customer_id,
      customer.login_email,
    ].some(value => String(value || '').toLowerCase().includes(query)))
  })

  const activeCustomer = computed(() => (
    customers.value.find(row => row.customer_id === selectedCustomerId.value) || null
  ))

  async function selectCustomer(
    customerId,
    { updateRoute = true, replaceRoute = false } = {},
  ) {
    if (!customerId) {
      selectedCustomerId.value = ''
      detail.value = null
      detailError.value = ''
      return true
    }
    const requestVersion = ++detailRequestVersion
    selectedCustomerId.value = customerId
    loadingDetail.value = true
    detailError.value = ''
    if (updateRoute && router) {
      const navigate = replaceRoute ? router.replace : router.push
      navigate.call(router, {
        query: { ...route?.query, customer: customerId },
      }).catch(() => {})
    }
    try {
      const response = await api.getSalesPortalCustomer(customerId)
      if (requestVersion === detailRequestVersion) detail.value = response.data || null
      return true
    } catch (error) {
      if (requestVersion === detailRequestVersion) {
        detail.value = null
        detailError.value = error?.response?.data?.detail
          || error?.message || '客户视图加载失败'
        ElMessage.error(detailError.value)
      }
      return false
    } finally {
      if (requestVersion === detailRequestVersion) loadingDetail.value = false
    }
  }

  async function loadCustomers({ preserveSelection = true } = {}) {
    const requestVersion = ++customerRequestVersion
    loadingCustomers.value = true
    let response
    try {
      response = await api.getSalesPortalCustomers()
    } catch (error) {
      if (requestVersion === customerRequestVersion) {
        customers.value = []
        detail.value = null
        detailError.value = ''
        ElMessage.error(error?.response?.data?.detail || error?.message || '客户素材门户加载失败')
      }
    } finally {
      if (requestVersion === customerRequestVersion) loadingCustomers.value = false
    }
    if (!response || requestVersion !== customerRequestVersion) return
    customers.value = response.data || []
    const requestedId = String(route?.query?.customer || '')
    const preferredId = preserveSelection ? selectedCustomerId.value : requestedId
    const nextId = [preferredId, requestedId]
      .find(id => id && customers.value.some(row => row.customer_id === id))
      || customers.value[0]?.customer_id
      || ''
    await selectCustomer(nextId, {
      updateRoute: nextId !== requestedId,
      replaceRoute: true,
    })
  }

  watch(() => route?.query?.customer, customerId => {
    const nextId = String(customerId || '')
    if (nextId && nextId !== selectedCustomerId.value
        && customers.value.some(row => row.customer_id === nextId)) {
      selectCustomer(nextId, { updateRoute: false })
    }
  })

  onMounted(() => loadCustomers({ preserveSelection: false }))

  return {
    customers,
    filteredCustomers,
    activeCustomer,
    selectedCustomerId,
    detail,
    customerSearch,
    loadingCustomers,
    loadingDetail,
    detailError,
    loadCustomers,
    selectCustomer,
  }
}

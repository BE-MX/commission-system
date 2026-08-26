/**
 * 内贸下单页逻辑（宪法 12：全部 state + 方法在此，页面只留薄壳）。
 *
 * 关键交互决策：工艺路线不让下单人选。选完属性后前端就地查「工艺→路线」映射，
 * 当场显示会走哪条路线；没配映射的当场标红提示，而不是等下单成功后才在列表里发现开不了工。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createOrder, getOptions, listCraftRoutes, listCustomers, uploadImage,
} from '@/api/domestic'
import { msgError } from '@/utils/feedback'
import { currentBeijingDate } from '@/utils/datetime'

function todayStr() {
  return currentBeijingDate()
}

function makeRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `order-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

function emptyItem() {
  return {
    key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    attrs: { product_type: 'cap', craft: '', net_color: '', size: '', length: '', density: '' },
    order_qty: 1,
    unit_price: 0,
    hairstyle: '', hairstyle_images: [],
    color: '', color_images: [],
    style_requirement: '', style_images: [],
    remark: '', remark_images: [],
  }
}

export function useDomesticOrderCreate() {
  const router = useRouter()

  const loading = ref(false)
  const submitting = ref(false)
  const options = ref({ product_types: [], order_types: [], attr_dicts: {}, values: {} })
  const craftRoutes = ref([])
  const customers = ref([])
  const customerLoading = ref(false)
  const orderRequestId = ref(makeRequestId())

  const form = reactive({
    order_no: '',
    order_date: todayStr(),
    customer_id: null,
    customer_shop_name: '',
    order_type: 'normal',
    remark: '',
    items: [emptyItem()],
  })

  // 'cap|递针旋全头套' → { route_id, route_name }
  const routeByCraft = computed(() => Object.fromEntries(
    craftRoutes.value.map(r => [`${r.product_type}|${r.craft}`, r]),
  ))

  function attrOptions(productType, field) {
    const dictType = options.value.attr_dicts?.[productType]?.[field]
    return dictType ? (options.value.values?.[dictType] || []) : []
  }

  function hasField(productType, field) {
    return Boolean(options.value.attr_dicts?.[productType]?.[field])
  }

  function routeOf(item) {
    if (!item.attrs.craft) return null
    return routeByCraft.value[`${item.attrs.product_type}|${item.attrs.craft}`] || null
  }

  const unroutedCount = computed(
    () => form.items.filter(i => i.attrs.craft && !routeOf(i)).length,
  )

  const orderTotal = computed(() => form.items.reduce(
    (sum, item) => sum + Number(item.order_qty || 0) * Number(item.unit_price || 0),
    0,
  ))

  const selectedCustomer = computed(
    () => customers.value.find(c => c.id === form.customer_id) || null,
  )

  function onProductTypeChange(item) {
    // 换类型后旧属性值域已失效，清空避免带着头套的尺寸下发片单
    Object.assign(item.attrs, { craft: '', net_color: '', size: '', length: '', density: '' })
  }

  function addItem() {
    form.items.push(emptyItem())
  }

  function copyItem(index) {
    const source = form.items[index]
    form.items.splice(index + 1, 0, {
      ...JSON.parse(JSON.stringify(source)),
      key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    })
  }

  function removeItem(index) {
    if (form.items.length <= 1) {
      ElMessage.warning('至少保留一行明细')
      return
    }
    form.items.splice(index, 1)
  }

  // AppUpload 的 v-model 回写在并发上传时会丢行（组件头注释里写明了），
  // 所以走它文档推荐的 show-list=false + uploadFn 自管状态：
  // 直接 push 进 reactive 数组，每次调用各自独立，不依赖 props 快照
  function makeUploadFn(item, imageKey) {
    return async file => {
      const res = await uploadImage(file)
      item[imageKey].push({
        path: res.data.path,
        name: res.data.name,
        url: URL.createObjectURL(file),
      })
      return res.data
    }
  }

  function removeImage(item, imageKey, index) {
    const [removed] = item[imageKey].splice(index, 1)
    if (removed?.url) URL.revokeObjectURL(removed.url)
  }

  onBeforeUnmount(() => {
    for (const item of form.items) {
      for (const section of ['hairstyle_images', 'color_images', 'style_images', 'remark_images']) {
        item[section].forEach(f => f.url && URL.revokeObjectURL(f.url))
      }
    }
  })

  async function searchCustomers(keyword) {
    customerLoading.value = true
    try {
      const res = await listCustomers({ page: 1, page_size: 50, keyword, status: 1 })
      customers.value = res.data?.items || []
    } finally {
      customerLoading.value = false
    }
  }

  function validate() {
    if (!form.order_no.trim()) return '请填写客户订单号'
    if (!form.order_date) return '请选择下单日期'
    if (!form.customer_id && !form.customer_shop_name.trim()) return '请选择或填写客户店名'
    for (const [idx, item] of form.items.entries()) {
      const label = `第 ${idx + 1} 行明细`
      for (const field of ['craft', 'size', 'length', 'density']) {
        if (hasField(item.attrs.product_type, field) && !item.attrs[field]) {
          return `${label}的属性没选全`
        }
      }
      if (!(item.order_qty > 0)) return `${label}的数量要大于 0`
      if (!(Number(item.unit_price) >= 0)) return `${label}的单价不能小于 0`
    }
    return ''
  }

  function buildPayload() {
    return {
      request_id: orderRequestId.value,
      order_no: form.order_no.trim(),
      order_date: form.order_date,
      customer_id: form.customer_id || null,
      customer_shop_name: form.customer_id ? null : form.customer_shop_name.trim(),
      order_type: form.order_type,
      remark: form.remark || null,
      items: form.items.map(item => ({
        attrs: {
          ...item.attrs,
          net_color: item.attrs.product_type === 'cap' ? (item.attrs.net_color || null) : null,
        },
        order_qty: item.order_qty,
        unit_price: Number(item.unit_price || 0),
        hairstyle: item.hairstyle || null,
        hairstyle_images: item.hairstyle_images.map(f => f.path),
        color: item.color || null,
        color_images: item.color_images.map(f => f.path),
        style_requirement: item.style_requirement || null,
        style_images: item.style_images.map(f => f.path),
        remark: item.remark || null,
        remark_images: item.remark_images.map(f => f.path),
      })),
    }
  }

  async function submit(isDraft = false) {
    const error = validate()
    if (error) {
      msgError(error)
      return
    }
    if (!isDraft && !form.customer_id && orderTotal.value > 0) {
      msgError('新客户还没有充值账户：请先保存草稿，到客户管理充值后再提交')
      return
    }
    if (
      !isDraft && selectedCustomer.value
      && Number(selectedCustomer.value.balance || 0) < orderTotal.value
    ) {
      msgError(`客户余额不足：当前 ¥${Number(selectedCustomer.value.balance || 0).toFixed(2)}，订单需 ¥${orderTotal.value.toFixed(2)}`)
      return
    }
    if (unroutedCount.value && !isDraft) {
      try {
        await ElMessageBox.confirm(
          `有 ${unroutedCount.value} 行明细的工艺还没配工艺路线，下单后这些货暂时不能开工（配好映射即可补上）。要继续吗？`,
          '有明细不能开工',
          { type: 'warning', confirmButtonText: '仍然下单', cancelButtonText: '返回修改' },
        )
      } catch {
        return
      }
    }

    submitting.value = true
    try {
      const res = await createOrder({ ...buildPayload(), is_draft: isDraft })
      const data = res.data || {}
      ElMessage.success(`${isDraft ? '草稿已保存' : '下单成功'}：${data.domestic_no}`)
      router.push({ name: 'DomesticOrders', query: { keyword: data.domestic_no } })
    } catch { /* 拦截器已提示 */ } finally {
      submitting.value = false
    }
  }

  onMounted(async () => {
    loading.value = true
    try {
      const [optRes, craftRes] = await Promise.all([getOptions(), listCraftRoutes()])
      options.value = optRes.data || options.value
      craftRoutes.value = craftRes.data || []
      await searchCustomers('')
    } catch { /* 拦截器已提示 */ } finally {
      loading.value = false
    }
  })

  return {
    loading, submitting, options, customers, customerLoading, form,
    attrOptions, hasField, routeOf, unroutedCount, orderTotal, selectedCustomer,
    onProductTypeChange, addItem, copyItem, removeItem,
    makeUploadFn, removeImage, searchCustomers, submit,
  }
}

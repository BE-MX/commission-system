/**
 * 内贸下单页逻辑（宪法 12：全部 state + 方法在此，页面只留薄壳）。
 *
 * 关键交互决策：工艺路线不让下单人选。选完属性后前端就地查「工艺→路线」映射，
 * 当场显示会走哪条路线；没配映射的当场标红提示，而不是等下单成功后才在列表里发现开不了工。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createOrder, getOptions, listCraftRoutes, listCustomers, uploadImage,
} from '@/api/domestic'
import { msgError } from '@/utils/feedback'

function todayStr() {
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function emptyItem() {
  return {
    key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    attrs: { product_type: 'cap', craft: '', net_color: '', size: '', length: '', density: '' },
    order_qty: 1,
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

  async function handleUpload(file) {
    const res = await uploadImage(file)
    return { path: res.data.path, name: res.data.name, url: URL.createObjectURL(file) }
  }

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
    }
    return ''
  }

  function buildPayload() {
    return {
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

  async function submit() {
    const error = validate()
    if (error) {
      msgError(error)
      return
    }
    if (unroutedCount.value) {
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
      const res = await createOrder(buildPayload())
      const data = res.data || {}
      ElMessage.success(`下单成功：${data.domestic_no}`)
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
    attrOptions, hasField, routeOf, unroutedCount,
    onProductTypeChange, addItem, copyItem, removeItem,
    handleUpload, searchCustomers, submit,
  }
}

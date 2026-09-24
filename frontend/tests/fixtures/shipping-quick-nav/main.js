import { createApp } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { shippingClient } from '../../../src/api/clients'
import ShippingScan from '../../../src/views/shipping/ShippingScan.vue'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'

let refreshCount = 0
const operator = { id: 1, name: '张敏' }
const items = Array.from({ length: 18 }, (_, index) => ({
  item_id: `item-${index + 1}`,
  qty: index + 2,
  unit: '顶',
  model: `LW-LACE-${String(index + 1).padStart(2, '0')}`,
  size: `${18 + index % 5} 英寸`,
  color: '自然黑 / #1B',
  product_name: '真人发假发',
}))
function payload() {
  return {
    session_id: 'demo-session', operator, items,
    record: { outbound_no: 'CK-DEMO-001', customer_name: '模拟客户', outbound_date: '2026-09-24', remark: refreshCount ? `更新后的出库资料：${'请核对当前批次。'.repeat(5)}` : '模拟出库单' },
    photos: [], videos: [], inspection: { status: 'draft', edit_version: refreshCount + 1, remark: '' },
  }
}
shippingClient.defaults.adapter = async config => {
  let data
  if (config.url.endsWith('/operators')) data = [operator]
  else if (config.url.endsWith('/scan')) data = payload()
  else if (config.url.endsWith('/sessions/demo-session')) { refreshCount++; data = payload() }
  else throw new Error(`Unexpected mock request: ${config.url}`)
  return { data: { code: 200, data }, status: 200, statusText: 'OK', headers: {}, config }
}
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
const app = createApp(ShippingScan)
app.use(router)
app.directive('any-permission', { mounted() {} })
app.mount('#app')
document.querySelector('#seed').addEventListener('click', async () => {
  const station = app._instance.setupState
  station.choose(operator)
  await station.decoded('ARK-I:demo')
  document.querySelector('#seed').hidden = true
})

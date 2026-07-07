<template>
  <!-- 对外库存查询页：客户官网外链嵌入（lislahairfactory.com 同风格），无登录，全英文 -->
  <div class="pi-page">
    <header class="pi-header">
      <span class="pi-brand">lislahair factory store</span>
      <span class="pi-title">Live Inventory</span>
    </header>

    <main class="pi-main">
      <h1>Stock Availability</h1>
      <p class="pi-sub">Real-time inventory, updated directly from our factory warehouse.</p>

      <!-- 链接无 key / key 无效 -->
      <div v-if="keyMissing || invalidKey" class="pi-notice">
        This inventory link is invalid or has expired.<br />
        Please contact your sales representative for an updated link.
      </div>

      <template v-else>
        <form class="pi-search" @submit.prevent="doSearch">
          <input
            v-model="keyword"
            type="text"
            placeholder="Search by product name or model…"
            aria-label="Search products"
          />
          <button type="submit">Search</button>
        </form>

        <div class="pi-table-wrap">
          <table class="pi-table">
            <thead>
              <tr><th>Product</th><th>Model</th><th class="num">Available</th><th>Status</th></tr>
            </thead>
            <tbody v-if="!loading && items.length">
              <tr v-for="item in items" :key="item.product_id">
                <td>{{ item.name }}</td>
                <td class="model">{{ item.model || '—' }}</td>
                <td class="num">{{ item.available }}</td>
                <td><span class="badge" :class="item.availability">{{ TIER_LABELS[item.availability] }}</span></td>
              </tr>
            </tbody>
            <tbody v-else-if="loading">
              <tr v-for="i in 6" :key="'s' + i" class="skeleton"><td colspan="4"><span /></td></tr>
            </tbody>
            <tbody v-else>
              <tr><td colspan="4" class="empty">{{ errorText || 'No products match your search.' }}</td></tr>
            </tbody>
          </table>
        </div>

        <nav v-if="total > pageSize" class="pi-paging">
          <button :disabled="page <= 1 || loading" @click="go(page - 1)">‹ Prev</button>
          <span>Page {{ page }} of {{ totalPages }}</span>
          <button :disabled="page >= totalPages || loading" @click="go(page + 1)">Next ›</button>
        </nav>
      </template>
    </main>

    <footer class="pi-footer">
      <span>© {{ year }} lislahair factory store</span>
      <span>Trusted by professionals worldwide. Dedicated to excellence in every strand.</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getPublicInventory } from '@/api/stock'

const TIER_LABELS = {
  in_stock: 'In Stock',
  low_stock: 'Low Stock',
  out_of_stock: 'Out of Stock',
}

const route = useRoute()
const accessKey = String(route.query.key || '')
const keyMissing = !accessKey
const invalidKey = ref(false)

const keyword = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const errorText = ref('')
const year = new Date().getFullYear()

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

async function fetchData() {
  loading.value = true
  errorText.value = ''
  try {
    const res = await getPublicInventory({
      key: accessKey, page: page.value, page_size: pageSize,
      keyword: keyword.value.trim() || undefined,
    })
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e) {
    if (e?.response?.status === 403) invalidKey.value = true
    else errorText.value = 'Unable to load inventory right now. Please try again shortly.'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function doSearch() {
  page.value = 1
  fetchData()
}

function go(p) {
  page.value = p
  fetchData()
}

onMounted(() => {
  document.title = 'Stock Availability | lislahair factory store' // 覆盖守卫默认的中文站名后缀
  if (!keyMissing) fetchData()
})
</script>

<style scoped>
/* Lisla 官网风格：极简白底 / 深灰黑文字 / sans-serif / 弱化按钮（细边框矩形）。
   刻意不用 tokens.css：本页嵌入客户官网，跟随客户品牌而非方舟设计系统（同 expo kiosk 例外） */
.pi-page {
  min-height: 100dvh; display: flex; flex-direction: column;
  background: #fff; color: #1a1a1a;
  font-family: -apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
}
.pi-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 18px clamp(16px, 5vw, 48px); border-bottom: 1px solid #e8e8e8;
}
.pi-brand { font-size: 15px; letter-spacing: 0.04em; font-weight: 600; text-transform: lowercase; }
.pi-title { font-size: 12px; color: #6b6b6b; letter-spacing: 0.12em; text-transform: uppercase; }

.pi-main { flex: 1; width: min(920px, 92vw); margin: 0 auto; padding: 40px 0 56px; }
.pi-main h1 { font-size: 26px; font-weight: 600; margin: 0 0 6px; }
.pi-sub { color: #6b6b6b; font-size: 14px; margin: 0 0 28px; }

.pi-notice {
  margin-top: 24px; padding: 28px; text-align: center; line-height: 1.8;
  border: 1px solid #e8e8e8; color: #6b6b6b; font-size: 14px;
}

.pi-search { display: flex; gap: 10px; margin-bottom: 22px; }
.pi-search input {
  flex: 1; height: 42px; padding: 0 14px; font-size: 14px;
  border: 1px solid #d9d9d9; border-radius: 2px; outline: none; color: #1a1a1a;
  transition: border-color 160ms ease;
}
.pi-search input:focus { border-color: #1a1a1a; }
.pi-search button {
  height: 42px; padding: 0 26px; font-size: 13px; letter-spacing: 0.08em;
  background: #1a1a1a; color: #fff; border: 1px solid #1a1a1a; border-radius: 2px;
  cursor: pointer; transition: opacity 160ms ease, transform 160ms ease;
}
.pi-search button:hover { opacity: 0.85; }
.pi-search button:active { transform: scale(0.97); }

.pi-table-wrap { overflow-x: auto; border: 1px solid #e8e8e8; }
.pi-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.pi-table th {
  text-align: left; font-weight: 600; font-size: 12px; letter-spacing: 0.08em;
  text-transform: uppercase; color: #6b6b6b;
  padding: 12px 16px; border-bottom: 1px solid #e8e8e8; background: #fafafa;
}
.pi-table td { padding: 13px 16px; border-bottom: 1px solid #f0f0f0; }
.pi-table tr:last-child td { border-bottom: none; }
.pi-table .model { color: #6b6b6b; }
.pi-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.pi-table th.num { text-align: right; }
.empty { text-align: center; color: #9a9a9a; padding: 36px 16px; }

.badge { display: inline-block; font-size: 12px; padding: 3px 10px; border: 1px solid; border-radius: 2px; }
.badge.in_stock { color: #1e7f4f; border-color: #bfe3d0; background: #f2faf6; }
.badge.low_stock { color: #9a6b00; border-color: #ecd9a8; background: #fdf8ec; }
.badge.out_of_stock { color: #8a8a8a; border-color: #dcdcdc; background: #f7f7f7; }

.pi-paging {
  display: flex; justify-content: center; align-items: center; gap: 18px;
  margin-top: 24px; font-size: 13px; color: #6b6b6b;
}
.pi-paging button {
  padding: 8px 18px; font-size: 13px; background: #fff; color: #1a1a1a;
  border: 1px solid #d9d9d9; border-radius: 2px; cursor: pointer;
  transition: border-color 160ms ease, transform 160ms ease;
}
.pi-paging button:hover:not(:disabled) { border-color: #1a1a1a; }
.pi-paging button:active:not(:disabled) { transform: scale(0.97); }
.pi-paging button:disabled { color: #c0c0c0; cursor: default; }

.pi-footer {
  display: flex; flex-direction: column; gap: 4px; align-items: center;
  padding: 22px 16px; border-top: 1px solid #e8e8e8;
  font-size: 12px; color: #9a9a9a; text-align: center;
}
.skeleton td { padding: 13px 16px; }
.skeleton span {
  display: block; height: 14px; border-radius: 2px;
  background: linear-gradient(90deg, #f2f2f2 25%, #e9e9e9 45%, #f2f2f2 65%);
  background-size: 300% 100%; animation: pi-shimmer 1.4s linear infinite;
}
@keyframes pi-shimmer { from { background-position: 120% 0; } to { background-position: -180% 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton span { animation: none; } }
@media (max-width: 560px) {
  .pi-main h1 { font-size: 21px; }
  .pi-search { flex-direction: column; }
  .pi-search button { width: 100%; }
}
</style>

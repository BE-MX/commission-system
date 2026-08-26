<template>
  <!-- 对外库存查询页：leshine.work/inventory 全公开（无登录无 key），全英文。
       列收敛为 类型/尺寸/颜色/克重/是否有货，不出具体库存数量。 -->
  <div class="pi-page">
    <header class="pi-header">
      <span class="pi-brand">lislahair factory store</span>
      <span class="pi-live"><i class="pi-live-dot" />Live Inventory</span>
    </header>

    <main class="pi-main">
      <section class="pi-hero">
        <p class="pi-overline">Factory Direct · Wholesale</p>
        <h1>Stock <em>Availability</em></h1>
        <p class="pi-sub">
          Live availability from our factory warehouse, synced directly from our inventory
          system. Contact your sales representative to place an order.
        </p>
      </section>

      <section class="pi-toolbar">
        <form class="pi-search" @submit.prevent="doSearch">
          <svg class="pi-search-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <circle cx="9" cy="9" r="6" stroke="currentColor" stroke-width="1.6" />
            <path d="m13.5 13.5 3.5 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
          <input
            v-model="keyword"
            type="text"
            placeholder="Search texture, length or color…"
            aria-label="Search products"
          />
          <button type="submit">Search</button>
        </form>
        <label class="pi-toggle">
          <input v-model="inStockOnly" type="checkbox" @change="doSearch" />
          <span class="pi-toggle-track"><span class="pi-toggle-thumb" /></span>
          <span class="pi-toggle-label">In stock only</span>
        </label>
      </section>

      <section class="pi-card">
        <table class="pi-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Size</th>
              <th>Color</th>
              <th>Weight</th>
              <th class="avail">Availability</th>
            </tr>
          </thead>
          <tbody v-if="!loading && items.length">
            <tr v-for="item in items" :key="item.product_id">
              <td data-label="Type" class="type">{{ item.type || '—' }}</td>
              <td data-label="Size">{{ item.size || '—' }}</td>
              <td data-label="Color">{{ item.color || '—' }}</td>
              <td data-label="Weight">{{ item.weight || '—' }}</td>
              <td data-label="Availability" class="avail">
                <span class="pi-pill" :class="item.in_stock ? 'in' : 'out'">
                  <i class="pi-pill-dot" />{{ item.in_stock ? 'In Stock' : 'Out of Stock' }}
                </span>
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="loading">
            <tr v-for="i in 8" :key="'s' + i" class="skeleton"><td colspan="5"><span /></td></tr>
          </tbody>
          <tbody v-else>
            <tr>
              <td colspan="5" class="empty">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M4 8.5 12 4l8 4.5v7L12 20l-8-4.5v-7Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
                  <path d="M4 8.5 12 13l8-4.5M12 13v7" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
                </svg>
                {{ errorText || emptyText }}
              </td>
            </tr>
          </tbody>
        </table>

        <nav v-if="total > 0" class="pi-paging">
          <span class="pi-paging-info">Showing {{ rangeStart }}–{{ rangeEnd }} of {{ total }} products</span>
          <span class="pi-paging-btns">
            <button :disabled="page <= 1 || loading" @click="go(page - 1)">‹ Prev</button>
            <button :disabled="page >= totalPages || loading" @click="go(page + 1)">Next ›</button>
          </span>
        </nav>
      </section>
    </main>

    <footer class="pi-footer">
      <span>© {{ year }} lislahair factory store</span>
      <span>Trusted by professionals worldwide. Dedicated to excellence in every strand.</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getPublicInventory } from '@/api/stock'
import { currentBeijingDate } from '@/utils/datetime'

const keyword = ref('')
const inStockOnly = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const errorText = ref('')
const year = Number(currentBeijingDate().slice(0, 4))

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const rangeStart = computed(() => (page.value - 1) * pageSize + 1)
const rangeEnd = computed(() => Math.min(page.value * pageSize, total.value))
const emptyText = computed(() =>
  keyword.value.trim()
    ? `No products match “${keyword.value.trim()}”.`
    : 'No products available right now.',
)

async function fetchData() {
  loading.value = true
  errorText.value = ''
  try {
    const res = await getPublicInventory({
      page: page.value,
      page_size: pageSize,
      keyword: keyword.value.trim() || undefined,
      in_stock_only: inStockOnly.value || undefined,
    })
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } catch {
    errorText.value = 'Unable to load inventory right now. Please try again shortly.'
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
  fetchData()
})
</script>

<style scoped>
/* Lisla 官网风格二期：暖纸底 + 墨色 + 铜金点缀 + 衬线大标题（编辑目录感）。
   刻意不用 tokens.css：本页面向外部客户，跟随客户品牌而非方舟设计系统（同 expo kiosk 例外） */
.pi-page {
  --ink: #1c1917;
  --muted: #78716c;
  --faint: #a8a29e;
  --line: #ece7df;
  --accent: #a97844;
  --accent-dark: #8f6537;
  --paper: #faf7f2;
  min-height: 100dvh; display: flex; flex-direction: column;
  background:
    radial-gradient(1100px 480px at 85% -10%, rgba(169, 120, 68, 0.10), transparent 60%),
    radial-gradient(900px 420px at 5% 0%, rgba(169, 120, 68, 0.07), transparent 55%),
    var(--paper);
  color: var(--ink);
  font-family: -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

.pi-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px clamp(20px, 5vw, 56px);
}
.pi-brand { font-size: 15px; letter-spacing: 0.04em; font-weight: 600; }
.pi-live {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted);
}
.pi-live-dot { width: 7px; height: 7px; border-radius: 50%; background: #16a34a; animation: pi-ping 2.4s ease-out infinite; }

.pi-main { flex: 1; width: min(980px, 92vw); margin: 0 auto; padding: 32px 0 64px; }

.pi-hero { text-align: center; margin-bottom: 34px; animation: pi-rise 480ms ease both; }
.pi-overline {
  font-size: 11px; letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--accent); margin: 0 0 12px; font-weight: 600;
}
.pi-hero h1 {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(30px, 5vw, 44px); font-weight: 500; margin: 0 0 14px; letter-spacing: 0.01em;
}
.pi-hero h1 em { font-style: italic; color: var(--accent); }
.pi-sub {
  max-width: 560px; margin: 0 auto; color: var(--muted);
  font-size: 14.5px; line-height: 1.7;
}

.pi-toolbar {
  display: flex; gap: 14px; align-items: center; justify-content: space-between;
  margin-bottom: 18px; flex-wrap: wrap;
  animation: pi-rise 480ms 80ms ease both;
}
.pi-search {
  flex: 1; min-width: 260px; display: flex; align-items: center; gap: 8px;
  height: 46px; padding: 0 6px 0 16px;
  background: #fff; border: 1px solid var(--line); border-radius: 999px;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.pi-search:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(169, 120, 68, 0.14); }
.pi-search-icon { width: 17px; height: 17px; color: var(--faint); flex: none; }
.pi-search input {
  flex: 1; min-width: 0; border: none; outline: none; background: transparent;
  font-size: 14px; color: var(--ink);
}
.pi-search input::placeholder { color: var(--faint); }
.pi-search button {
  height: 36px; padding: 0 22px; font-size: 13px; letter-spacing: 0.06em;
  background: var(--ink); color: #fff; border: none; border-radius: 999px;
  cursor: pointer; transition: background 160ms ease, transform 160ms ease;
}
.pi-search button:hover { background: var(--accent-dark); }
.pi-search button:active { transform: scale(0.97); }

.pi-toggle { display: inline-flex; align-items: center; gap: 10px; cursor: pointer; user-select: none; padding: 6px 2px; }
.pi-toggle input { position: absolute; opacity: 0; width: 0; height: 0; }
.pi-toggle-track {
  width: 38px; height: 22px; border-radius: 999px; background: #e7e2d9;
  display: inline-flex; align-items: center; padding: 2px;
  transition: background 180ms ease;
}
.pi-toggle-thumb {
  width: 18px; height: 18px; border-radius: 50%; background: #fff;
  box-shadow: 0 1px 3px rgba(28, 25, 23, 0.25);
  transition: transform 180ms ease;
}
.pi-toggle input:checked + .pi-toggle-track { background: #16a34a; }
.pi-toggle input:checked + .pi-toggle-track .pi-toggle-thumb { transform: translateX(16px); }
.pi-toggle input:focus-visible + .pi-toggle-track { outline: 2px solid var(--accent); outline-offset: 2px; }
.pi-toggle-label { font-size: 13.5px; color: var(--muted); }

.pi-card {
  background: #fff; border: 1px solid var(--line); border-radius: 18px;
  box-shadow: 0 18px 45px -30px rgba(28, 25, 23, 0.28);
  overflow: hidden;
  animation: pi-rise 480ms 160ms ease both;
}
.pi-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.pi-table th {
  text-align: left; font-weight: 600; font-size: 11px; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--faint);
  padding: 15px 20px; border-bottom: 1px solid var(--line); background: #fcfbf8;
}
.pi-table td { padding: 15px 20px; border-bottom: 1px solid #f3efe9; color: #44403c; }
.pi-table tbody tr { transition: background 120ms ease; }
.pi-table tbody tr:hover { background: #fbf8f3; }
.pi-table tbody tr:last-child td { border-bottom: none; }
.pi-table .type { color: var(--ink); font-weight: 550; }
.pi-table th.avail, .pi-table td.avail { text-align: right; }

.pi-pill {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 12.5px; font-weight: 600; padding: 5px 12px;
  border: 1px solid; border-radius: 999px; white-space: nowrap;
}
.pi-pill-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.pi-pill.in { color: #15803d; border-color: #bbe6c9; background: #f2fbf5; }
.pi-pill.in .pi-pill-dot { animation: pi-ping 2.4s ease-out infinite; }
.pi-pill.out { color: #8a8580; border-color: #e7e5e4; background: #f7f6f5; }

.pi-paging {
  display: flex; justify-content: space-between; align-items: center; gap: 14px;
  padding: 14px 20px; border-top: 1px solid var(--line); background: #fcfbf8;
  font-size: 12.5px; color: var(--muted); flex-wrap: wrap;
}
.pi-paging-btns { display: inline-flex; gap: 8px; }
.pi-paging button {
  padding: 7px 16px; font-size: 12.5px; background: #fff; color: var(--ink);
  border: 1px solid var(--line); border-radius: 999px; cursor: pointer;
  transition: border-color 160ms ease, transform 160ms ease;
}
.pi-paging button:hover:not(:disabled) { border-color: var(--ink); }
.pi-paging button:active:not(:disabled) { transform: scale(0.97); }
.pi-paging button:disabled { color: #d0ccc5; cursor: default; }

.empty { text-align: center; color: var(--faint); padding: 44px 16px !important; font-size: 14px; }
.empty svg { width: 34px; height: 34px; display: block; margin: 0 auto 12px; color: #d8d2c8; }

.pi-footer {
  display: flex; flex-direction: column; gap: 4px; align-items: center;
  padding: 24px 16px 30px; font-size: 12px; color: var(--faint); text-align: center;
}

.skeleton td { padding: 16px 20px; }
.skeleton span {
  display: block; height: 14px; border-radius: 999px;
  background: linear-gradient(90deg, #f4f1eb 25%, #eae6de 45%, #f4f1eb 65%);
  background-size: 300% 100%; animation: pi-shimmer 1.4s linear infinite;
}
@keyframes pi-shimmer { from { background-position: 120% 0; } to { background-position: -180% 0; } }
@keyframes pi-ping {
  0% { box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.35); }
  70% { box-shadow: 0 0 0 6px rgba(22, 163, 74, 0); }
  100% { box-shadow: 0 0 0 0 rgba(22, 163, 74, 0); }
}
@keyframes pi-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }

@media (prefers-reduced-motion: reduce) {
  .pi-hero, .pi-toolbar, .pi-card { animation: none; }
  .pi-live-dot, .pi-pill.in .pi-pill-dot { animation: none; }
  .skeleton span { animation: none; }
}

/* 移动端：表格折成带标签的行卡片，Availability 徽章保持醒目 */
@media (max-width: 640px) {
  .pi-main { padding-top: 20px; }
  .pi-toolbar { flex-direction: column; align-items: stretch; }
  .pi-toggle { align-self: flex-start; }
  .pi-table thead { display: none; }
  .pi-table tbody tr { display: block; padding: 8px 0; border-bottom: 1px solid #f3efe9; }
  .pi-table tbody tr:hover { background: transparent; }
  .pi-table td {
    display: flex; justify-content: space-between; align-items: center; gap: 16px;
    padding: 7px 18px; border-bottom: none;
  }
  .pi-table td::before {
    content: attr(data-label);
    font-size: 10.5px; font-weight: 600; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--faint);
  }
  .pi-table td.avail { text-align: right; }
  .pi-table td[colspan] { display: block; text-align: center; }
  .pi-table td[colspan]::before { content: none; }
  .pi-paging { justify-content: center; }
}
</style>

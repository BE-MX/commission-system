<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  products: { type: Array, default: () => [] },
  coverUrls: { type: Object, default: () => ({}) },
  customerName: { type: String, default: '' },
})

defineEmits(['select'])

const search = ref('')
const category = ref('全部')
const categories = computed(() => ['全部', ...new Set(props.products.map(product => product.category).filter(Boolean))])
const visibleProducts = computed(() => {
  const term = search.value.trim().toLocaleLowerCase('zh-CN')
  return props.products.filter(product => {
    const categoryMatches = category.value === '全部' || product.category === category.value
    const searchMatches = !term || `${product.name} ${product.description || ''}`.toLocaleLowerCase('zh-CN').includes(term)
    return categoryMatches && searchMatches
  })
})
</script>

<template>
  <main class="catalog-shell">
    <header class="catalog-header">
      <div>
        <p class="eyebrow">专属产品效果图</p>
        <h1>{{ customerName ? `${customerName}，选择要设计的产品` : '选择要设计的产品' }}</h1>
        <p>选好产品后，上传 LOGO 并确认预设参数即可生成。</p>
      </div>
      <label class="search-field">
        <span>搜索</span>
        <input v-model="search" type="search" placeholder="搜索产品名称">
      </label>
    </header>

    <nav class="category-list" aria-label="产品分类">
      <button
        v-for="item in categories"
        :key="item"
        type="button"
        :class="{ active: category === item }"
        @click="category = item"
      >
        {{ item }}
      </button>
    </nav>

    <section v-if="visibleProducts.length" class="product-grid" aria-label="产品列表">
      <article v-for="product in visibleProducts" :key="product.id" class="product-card">
        <div class="product-image">
          <img v-if="coverUrls[product.id]" :src="coverUrls[product.id]" :alt="product.name">
          <span v-else>{{ product.category || '产品' }}</span>
        </div>
        <div class="product-copy">
          <small>{{ product.category }}</small>
          <h2>{{ product.name }}</h2>
          <p>{{ product.description || '上传品牌 LOGO，快速查看产品应用效果。' }}</p>
          <button type="button" @click="$emit('select', product)">立即设计</button>
        </div>
      </article>
    </section>
    <div v-else class="search-empty">
      <strong>没有找到匹配的产品</strong>
      <p>换个关键词或分类试试。</p>
      <button type="button" @click="search = ''; category = '全部'">查看全部产品</button>
    </div>
  </main>
</template>

<style scoped>
.catalog-shell { width: min(1180px, calc(100% - 40px)); margin: 0 auto; padding: 54px 0 72px; }
.catalog-header { display: flex; align-items: end; justify-content: space-between; gap: 32px; }
.eyebrow { color: var(--cip-accent-strong); font-size: 12px; font-weight: 700; letter-spacing: .12em; }
h1 { max-width: 720px; margin: 8px 0 10px; color: var(--cip-ink); font-size: clamp(28px, 4vw, 44px); line-height: 1.12; letter-spacing: -.025em; }
.catalog-header p { margin: 0; color: var(--cip-muted); line-height: 1.65; }
.search-field { display: grid; min-width: min(320px, 100%); gap: 7px; color: var(--cip-muted); font-size: 11px; }
.search-field input { min-height: 44px; padding: 0 14px; border: 1px solid var(--cip-border); border-radius: 11px; outline: none; color: var(--cip-ink); background: var(--cip-surface); }
.search-field input:focus { border-color: var(--cip-accent); box-shadow: 0 0 0 3px var(--cip-focus); }
.category-list { display: flex; gap: 8px; margin: 34px 0 20px; overflow-x: auto; scrollbar-width: none; }
.category-list button, .search-empty button { min-height: 44px; padding: 0 16px; cursor: pointer; border: 1px solid var(--cip-border); border-radius: 999px; color: var(--cip-muted); background: var(--cip-surface); white-space: nowrap; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.category-list button.active { border-color: var(--cip-accent); color: var(--cip-accent-strong); background: var(--cip-accent-soft); }
.category-list button:active, .search-empty button:active { transform: scale(.98); }
.product-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.product-card { overflow: hidden; border: 1px solid var(--cip-border); border-radius: 18px; background: var(--cip-surface); box-shadow: 0 8px 28px var(--cip-shadow); }
.product-image { display: grid; aspect-ratio: 4 / 3; place-items: center; overflow: hidden; color: var(--cip-muted); background: var(--cip-canvas); }
.product-image img { width: 100%; height: 100%; object-fit: cover; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.product-copy { display: grid; gap: 8px; padding: 18px; }
.product-copy small { color: var(--cip-accent-strong); font-size: 11px; }
.product-copy h2 { margin: 0; color: var(--cip-ink); font-size: 18px; }
.product-copy p { min-height: 42px; margin: 0; color: var(--cip-muted); font-size: 12px; line-height: 1.65; }
.product-copy button { min-height: 44px; margin-top: 5px; cursor: pointer; border: 0; border-radius: 10px; color: var(--cip-on-accent); background: var(--cip-accent); font-weight: 700; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.product-copy button:active { transform: scale(.98); }
.search-empty { display: grid; min-height: 280px; place-items: center; align-content: center; gap: 9px; border: 1px dashed var(--cip-border-strong); border-radius: 18px; color: var(--cip-ink); }
.search-empty p { margin: 0; color: var(--cip-muted); }
@media (hover: hover) and (pointer: fine) { .product-card:hover img { transform: scale(1.025); } .product-copy button:hover { background: var(--cip-accent-hover); } }
@media (max-width: 900px) { .product-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .catalog-shell { width: min(100% - 28px, 1180px); padding-top: 30px; } .catalog-header { display: grid; } .search-field { min-width: 0; } .product-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .category-list button, .search-empty button, .product-image img, .product-copy button { transition: none; } .category-list button:active, .search-empty button:active, .product-copy button:active { transform: none; } .product-card:hover img { transform: none; } }
</style>

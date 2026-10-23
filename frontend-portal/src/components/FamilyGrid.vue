<script setup>
import ProductImage from './ProductImage.vue'
const props = defineProps({ families: { type: Array, required: true }, ungrouped: { type: Number, default: 0 } })
const emit = defineEmits(['open', 'all'])
const lengths = family => family.lengths.length ? (family.lengths.length > 1 ? `${family.lengths[0]}"–${family.lengths.at(-1)}"` : `${family.lengths[0]}"`) : ''
const ordering = family => `Min. ${family.min_order_qty} ${family.sale_unit}` + (Number(family.step_qty) > 1 ? `, steps of ${family.step_qty}` : '')
</script>

<template>
  <div class="product-grid family-grid">
    <article v-for="family in props.families" :key="family.code" class="product-card">
      <a :href="`/collection/${family.code}`" class="product-open" @click.prevent="emit('open', family.code)">
        <div class="product-art"><ProductImage :url="family.image_url" size="full" :alt="family.display_name" /></div>
        <div class="product-caption"><div class="product-line"><h2>{{ family.display_name }}</h2><span aria-hidden="true">↗</span></div><p class="muted">{{ lengths(family) }}<span v-if="family.grades.length"> · {{ family.grades.length }} {{ family.grades.length > 1 ? 'ratios' : 'ratio' }}</span> · {{ family.variant_count }} options</p><p class="small muted">{{ ordering(family) }}</p></div>
      </a>
    </article>
    <article v-if="ungrouped" class="product-card">
      <button type="button" class="product-open" @click="emit('all')">
        <div class="product-art"><div class="product-monogram" aria-hidden="true">L<span>S</span></div></div>
        <div class="product-caption"><div class="product-line"><h2>Other products</h2><span aria-hidden="true">↗</span></div><p class="muted">Accessories and other items · {{ ungrouped }} items</p></div>
      </button>
    </article>
  </div>
</template>

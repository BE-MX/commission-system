<script setup>
import ProductImage from './ProductImage.vue'
const props = defineProps({ families: { type: Array, required: true }, ungrouped: { type: Number, default: 0 } })
const emit = defineEmits(['open', 'all'])
const lengths = family => family.lengths.length ? (family.lengths.length > 1 ? `${family.lengths[0]}"–${family.lengths.at(-1)}"` : `${family.lengths[0]}"`) : ''
</script>

<template>
  <div class="product-grid family-grid">
    <article v-for="family in props.families" :key="family.code" class="product-card">
      <a :href="`/collection/${family.code}`" class="product-open" @click.prevent="emit('open', family.code)">
        <div class="product-art"><span class="product-kind">HAIR COLLECTION</span><ProductImage :url="family.image_url" :alt="family.display_name" /></div>
        <div class="product-caption"><div class="product-line"><span class="small muted">{{ family.variant_count }} options</span><span aria-hidden="true">↗</span></div><h2>{{ family.display_name }}</h2><p class="muted">{{ lengths(family) }}<span v-if="family.grades.length"> · {{ family.grades.length }} {{ family.grades.length > 1 ? 'ratios' : 'ratio' }}</span></p><p class="small muted">Minimum {{ family.min_order_qty }} {{ family.sale_unit }}, in steps of {{ family.step_qty }}</p></div>
      </a>
    </article>
    <article v-if="ungrouped" class="product-card">
      <button type="button" class="product-open" @click="emit('all')">
        <div class="product-art"><span class="product-kind">MORE</span><div class="product-monogram" aria-hidden="true">L<span>S</span></div></div>
        <div class="product-caption"><div class="product-line"><span class="small muted">{{ ungrouped }} items</span><span aria-hidden="true">↗</span></div><h2>Other products</h2><p class="muted">Accessories and other items in your collection</p></div>
      </button>
    </article>
  </div>
</template>

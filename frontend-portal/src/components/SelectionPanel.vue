<script setup>
import { computed, ref } from 'vue'
import { unitPrice } from '../presentation.mjs'
import { minimumQuantity } from '../state/checkout.mjs'
import { formatGrams, gramsFor, selectionWeight, stepQuantity } from '../state/family.mjs'
const props = defineProps({ checkout: { type: Object, required: true }, state: { type: Object, required: true } })
const emit = defineEmits(['checkout'])
const error = ref('')
const weight = computed(() => selectionWeight(props.state.lines))
function act(operation) {
  error.value = ''
  try { operation() } catch (problem) { error.value = problem.message }
}
function step(line, direction) {
  act(() => props.checkout.quantity(line.item_id, stepQuantity(line.quantity, line.step_qty, minimumQuantity(line), direction)))
}
</script>

<template>
  <aside class="selection-panel" aria-labelledby="selection-title">
    <header><h2 id="selection-title">Your selection</h2><span class="nav-count">{{ state.lines.length }}</span></header>
    <p v-if="!state.lines.length" class="small muted">Products you add appear here. Adjust quantities before you finish.</p>
    <ul v-else>
      <li v-for="line in state.lines" :key="line.item_id" :class="{ unavailable: line.unavailable }">
        <div><p class="selection-name">{{ line.model_name }}</p><p class="small muted">{{ line.color_name }} · {{ line.length_display }} · {{ unitPrice(line.unit_price) }} / {{ line.sale_unit }}</p></div>
        <div class="stepper compact"><button type="button" class="icon-button" :aria-label="`Decrease ${line.model_name}, ${line.color_name}`" :disabled="line.unavailable || line.quantity <= minimumQuantity(line)" @click="step(line, -1)">−</button><span aria-live="polite">{{ line.quantity }}</span><button type="button" class="icon-button" :aria-label="`Increase ${line.model_name}, ${line.color_name}`" :disabled="line.unavailable" @click="step(line, 1)">+</button></div>
        <p class="small muted">{{ formatGrams(gramsFor(line)) }}</p>
        <button type="button" class="text-button small" :aria-label="`Remove ${line.model_name}, ${line.color_name}`" @click="act(() => checkout.remove(line.item_id))">Remove</button>
      </li>
    </ul>
    <p v-if="error" class="alert error small" role="alert">{{ error }}</p>
    <footer v-if="state.lines.length">
      <p><span class="muted">Total weight</span> <strong>{{ formatGrams(weight.grams) }}</strong><span v-if="!weight.complete" class="small muted"> + items with unconfirmed weight</span></p>
      <button type="button" class="button primary" @click="emit('checkout')">Finish selection</button>
    </footer>
  </aside>
</template>

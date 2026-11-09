import { computed, watch } from 'vue'

export function useImageModelOptions(config, model, size, quality) {
  const selectedModel = computed(() => config.value.models?.find(option => option.id === model.value))
  const modelSizes = computed(() => selectedModel.value?.sizes || config.value.sizes || [])
  const modelQualities = computed(() => selectedModel.value?.qualities || config.value.qualities || [])
  const selectedModelAvailable = computed(() => selectedModel.value?.available)
  watch(selectedModel, (option, previous) => {
    if (!option) return
    const sizes = option.sizes || config.value.sizes || []
    const qualities = option.qualities || config.value.qualities || []
    size.value = previous?.id === option.id && sizes.includes(size.value) ? size.value : option.default_size || config.value.default_size || sizes[0] || ''
    quality.value = previous?.id === option.id && qualities.includes(quality.value) ? quality.value : option.default_quality || config.value.default_quality || qualities[0] || ''
  })
  return { selectedModelAvailable, modelSizes, modelQualities }
}

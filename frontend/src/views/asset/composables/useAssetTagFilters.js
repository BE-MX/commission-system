import { computed, ref } from 'vue'

export function useAssetTagFilters({ dimensions, filterKeyword, activeFilters, assets, availableTagIds, hasActiveTagFilter }) {
  // 根据关键字过滤后的维度（只包含有匹配标签值的维度）
  const filteredDimensions = computed(() => {
    const dims = dimensions.value
    if (!filterKeyword.value.trim()) {
      return dims.filter(dim => dim.values?.length > 0)
    }
    const kw = filterKeyword.value.toLowerCase()
    return dims.filter(dim => dim.values?.some(v => v.value.toLowerCase().includes(kw)))
  })

  // 分组渐进展示：细分维度收进「高级筛选」折叠区（体系 v2 切换后生效；
  // 旧体系维度不在此集合，展示行为不变）
  const ADVANCED_DIM_NAMES = new Set(['color_code', 'texture', 'shoot_style', 'process_step', 'theme', 'media_trait'])
  const showAdvanced = ref(false)
  const commonDimensions = computed(() => filteredDimensions.value.filter(d => !ADVANCED_DIM_NAMES.has(d.name)))
  const advancedDimensions = computed(() => filteredDimensions.value.filter(d => ADVANCED_DIM_NAMES.has(d.name)))

  // 跨维度 parent 级联：content_type 的值挂靠 content_category 的值
  const categorySelectedIds = computed(() => new Set(activeFilters['content_category'] || []))

  // 获取某个维度下过滤后的标签值
  function filteredValues(dim) {
    let values = dim.values || []
    if (filterKeyword.value.trim()) {
      const kw = filterKeyword.value.toLowerCase()
      values = values.filter(v => v.value.toLowerCase().includes(kw))
    }
    // 级联：已选内容大类时，内容子类只显示挂靠该大类的值
    if (dim.name === 'content_type' && categorySelectedIds.value.size > 0) {
      values = values.filter(v => !v.parent_value_id || categorySelectedIds.value.has(v.parent_value_id))
    }
    // 联动筛选：当用户已选择某些标签且已加载素材时，只显示当前结果中存在的标签
    if (hasActiveTagFilter.value && assets.value.length > 0 && availableTagIds.value.size > 0) {
      values = values.filter(v => availableTagIds.value.has(v.id))
    }
    return values
  }

  // 检查标签是否被选中
  function isTagSelected(dimName, valId) {
    return (activeFilters[dimName] || []).includes(valId)
  }

  // 同维度子级（产品族展开：选中「发帘类」= 族值+全部子型号一起进筛选）
  function sameDimChildren(dim, valId) {
    if (!dim?.values) return []
    const ownIds = new Set(dim.values.map(v => v.id))
    return dim.values.filter(v => v.parent_value_id === valId && ownIds.has(v.parent_value_id)).map(v => v.id)
  }

  // 切换标签选中状态
  function toggleTag(dimName, valId, dim) {
    if (!activeFilters[dimName]) {
      activeFilters[dimName] = []
    }
    const group = [valId, ...sameDimChildren(dim, valId)]
    const idx = activeFilters[dimName].indexOf(valId)
    if (idx >= 0) {
      activeFilters[dimName] = activeFilters[dimName].filter(id => !group.includes(id))
    } else {
      activeFilters[dimName] = [...new Set([...activeFilters[dimName], ...group])]
    }
  }

  // 获取标签样式（选中时显示标签库颜色）
  function getTagStyle(dimName, valId, colorHex) {
    if (!isTagSelected(dimName, valId)) return {}
    const color = colorHex || 'var(--color-primary)'
    // 如果颜色是 rgb 格式，直接返回；如果是 hex，判断亮度决定文字颜色
    return {
      backgroundColor: color,
      color: colorHex && isLightColor(colorHex) ? 'var(--text-primary)' : 'var(--card-bg)',
      borderColor: 'transparent',
    }
  }

  // 简单判断颜色亮度
  function isLightColor(color) {
    if (!color) return false
    // 处理 rgb(r,g,b) 格式
    const rgbMatch = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
    if (rgbMatch) {
      const r = parseInt(rgbMatch[1])
      const g = parseInt(rgbMatch[2])
      const b = parseInt(rgbMatch[3])
      return (r * 299 + g * 587 + b * 114) / 1000 > 160
    }
    // 处理 hex 格式
    let hex = color.replace('#', '')
    if (hex.length === 3) hex = hex.split('').map(c => c + c).join('')
    if (hex.length !== 6) return false
    const r = parseInt(hex.substr(0, 2), 16)
    const g = parseInt(hex.substr(2, 2), 16)
    const b = parseInt(hex.substr(4, 2), 16)
    return (r * 299 + g * 587 + b * 114) / 1000 > 160
  }

  // 获取维度分隔色条样式：取该维度下第一个有颜色的标签值
  function getDimDividerStyle(dim) {
    const color = dim.values?.find(v => v.color_hex)?.color_hex
    if (!color) return {}
    return {
      borderLeft: `3px solid ${color}`,
      backgroundColor: color + '10',
    }
  }

  return { showAdvanced, commonDimensions, advancedDimensions, filteredValues, isTagSelected, toggleTag, getTagStyle, getDimDividerStyle }
}

import { getMaterials } from '@/api/semifinished'

// Selectors need the complete catalog rather than the current visible server page.
export async function loadMaterialOptions({ signal, isCurrent }) {
  const config = { signal, suppressToast: true }
  const first = await getMaterials({ page: 1, page_size: 100 }, config)
  const items = [...(first.items || [])]
  const pages = Math.ceil(Number(first.total || items.length) / 100)
  for (let page = 2; page <= pages && isCurrent(); page += 1) {
    const next = await getMaterials({ page, page_size: 100 }, config)
    items.push(...(next.items || []))
  }
  return items
}

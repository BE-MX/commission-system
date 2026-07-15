export function emptyAccessoryPriceForm() {
  return {
    id: null,
    product_id: null,
    sku_id: null,
    accessory_name: '',
    accessory_model: '',
    accessory_color: '',
    price: null,
    currency: 'USD',
  }
}

function candidateFromRow(row) {
  if (!row) return null
  return {
    product_id: row.product_id,
    sku_id: row.sku_id,
    accessory_name: row.accessory_name,
    accessory_model: row.accessory_model,
    accessory_color: row.accessory_color,
  }
}

export function buildAccessoryEditorState(row) {
  const candidate = candidateFromRow(row)
  return {
    candidate,
    form: row
      ? {
          ...emptyAccessoryPriceForm(),
          ...candidate,
          id: row.id,
          price: Number(row.standard_price),
          currency: row.currency || 'USD',
        }
      : emptyAccessoryPriceForm(),
  }
}

export function createLatestAccessorySearch({ request, applyItems, applyLoading }) {
  let latestRequestId = 0
  const search = async params => {
    const requestId = ++latestRequestId
    applyLoading(true)
    try {
      const result = await request(params)
      if (requestId === latestRequestId) applyItems(result.items || [])
      return result
    } catch (error) {
      if (requestId === latestRequestId) applyItems([])
      throw error
    } finally {
      if (requestId === latestRequestId) applyLoading(false)
    }
  }
  search.invalidate = () => {
    latestRequestId += 1
    applyLoading(false)
  }
  return search
}

export function shouldShowAccessoryLocalError(error) {
  return !error?.isAxiosError
}

export async function saveAccessoryPriceForm({ form, save, onSuccess }) {
  const payload = { ...form, price: Number(form.price).toFixed(2) }
  const result = await save(payload)
  await onSuccess(result)
  return result
}

function isDialogCancellation(error) {
  const action = typeof error === 'string' ? error : error?.action || error?.message
  return action === 'cancel' || action === 'close'
}

export async function deleteAccessoryPriceRow({ row, confirm, remove, onSuccess }) {
  try {
    await confirm(row)
  } catch (error) {
    if (isDialogCancellation(error)) return false
    throw error
  }
  await remove(row.id)
  await onSuccess?.()
  return true
}

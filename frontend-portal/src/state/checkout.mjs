import { PortalError } from '../api/client.mjs'

const blankDelivery = () => ({ contact_name: '', phone: '', address_line1: '', address_line2: '', city: '', region: '', postal_code: '', country_code: '' })
const pending = status => ['submitting', 'checking', 'uncertain'].includes(status)
const fail = (code, message) => { throw new PortalError(code, message) }
const freeze = value => {
  if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value) }
  return value
}
export function minimumQuantity(item) {
  const { min_order_qty: minimum, step_qty: step } = item
  if (!Number.isSafeInteger(minimum) || !Number.isSafeInteger(step) || minimum < 1 || step < 1) return null
  const value = Math.ceil(minimum / step) * step
  return value <= 10000 ? value : null
}
export function quantityFor(item, raw) {
  if (!(typeof raw === 'number' || typeof raw === 'string') || !/^[1-9][0-9]*$/.test(String(raw))) fail('INVALID_QUANTITY', 'Enter a whole quantity greater than zero.')
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value > 10000 || minimumQuantity(item) === null || value < item.min_order_qty || value % item.step_qty) {
    fail('INVALID_QUANTITY', `Request at least ${minimumQuantity(item) ?? 'the minimum'} in multiples of ${item.step_qty}, up to 10,000.`)
  }
  return value
}
// Ark business datetimes without offsets are always Beijing time, never browser-local.
export function quoteDeadline(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})?$/.test(value)) return NaN
  return Date.parse(/(Z|[+-]\d{2}:\d{2})$/.test(value) ? value : value + '+08:00')
}
function validQuote(quote, now) {
  if (!quote?.quote_id || !/^[a-f0-9]{64}$/i.test(quote.content_hash) || quote.currency !== 'USD' || quote.status !== 'valid' || !(quoteDeadline(quote.expires_at) > now) || !quote.items?.length) fail('QUOTE_UNAVAILABLE', 'This quote is unavailable or has expired. Request a fresh review.')
}

/** One in-memory draft per verified session. Only submission keys may survive refresh. */
export function createCheckout({ api, submission, now = () => Date.now() }) {
  const listeners = new Set()
  let sequence = 0
  let state = freeze({ lines: [], delivery: blankDelivery(), customer_po: '', remark: '', quote: null,
    quoting: false, acknowledged: false, error: null, receipt: null, submission: submission.state })
  function update(patch) { state = freeze({ ...state, ...patch }); for (const listener of listeners) listener(state) }
  function writable() {
    if (!api.session?.capabilities?.place_order) fail('ORDERING_UNAVAILABLE', 'Your access does not allow order requests. Please contact your representative.')
    if (pending(state.submission.status)) fail('SUBMISSION_PENDING', 'Confirm the previous request result before changing this selection.')
  }
  function edit(patch) {
    writable(); sequence++
    update({ ...patch, quote: null, quoting: false, acknowledged: false, error: null, receipt: null })
  }
  const offSubmission = submission.subscribe(value => {
    if (value.status === 'confirmed') {
      sequence++
      update({ submission: value, receipt: value.receipt, lines: [], delivery: blankDelivery(), customer_po: '', remark: '', quote: null, acknowledged: false, quoting: false, error: null })
    } else update({ submission: value, ...(value.status === 'failed' ? { error: value.error, quote: null, acknowledged: false } : {}) })
  })
  const offSession = api.subscribe(({ reason }) => {
    if (reason === 'authenticated') return
    sequence++
    update({ lines: [], delivery: blankDelivery(), customer_po: '', remark: '', quote: null,
      quoting: false, acknowledged: false, error: null, receipt: null, submission: submission.state })
  })
  return {
    get state() { return state },
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    add(item, raw) {
      writable()
      if (item.availability !== 'available' || item.unit_price == null || minimumQuantity(item) === null) fail('ITEM_UNAVAILABLE', 'This product is not available to request. Please refresh your collection.')
      const amount = quantityFor(item, raw), previous = state.lines.find(line => line.item_id === item.item_id)
      const quantity = quantityFor(item, amount + (previous?.quantity || 0))
      if (!previous && state.lines.length >= 100) fail('CART_LIMIT', 'A request can contain up to 100 different products.')
      const snapshot = Object.fromEntries(['item_id', 'model_name', 'color_name', 'customer_sku', 'length_display', 'weight_display', 'sale_unit', 'unit_price', 'min_order_qty', 'step_qty'].map(key => [key, item[key]]))
      const lines = state.lines.filter(line => line.item_id !== item.item_id)
      lines.push({ ...snapshot, quantity })
      edit({ lines })
    },
    quantity(id, raw) {
      const item = state.lines.find(line => line.item_id === id)
      if (!item || item.unavailable) fail('ITEM_UNAVAILABLE', 'Remove this unavailable product, or refresh your collection before adding it again.')
      const quantity = quantityFor(item, raw)
      edit({ lines: state.lines.map(line => line.item_id === id ? { ...line, quantity } : line) })
    },
    remove(id) { edit({ lines: state.lines.filter(line => line.item_id !== id) }) },
    delivery(field, value) {
      if (!(field in blankDelivery()) || typeof value !== 'string') fail('INVALID_INPUT', 'Check your delivery details.')
      edit({ delivery: { ...state.delivery, [field]: field === 'country_code' ? value.toUpperCase() : value } })
    },
    details(field, value) {
      if (!['customer_po', 'remark'].includes(field) || typeof value !== 'string') fail('INVALID_INPUT', 'Check your request details.')
      edit({ [field]: value })
    },
    acknowledge(value) { writable(); update({ acknowledged: value === true }) },
    async reorder(requestId, lineKeys, { replace = false, signal } = {}) {
      writable()
      if (signal?.aborted) fail('REQUEST_ABORTED', 'The repeat request was closed.')
      if (state.quoting) fail('QUOTE_PENDING', 'Wait for the current quote to finish.')
      if (state.lines.length && !replace) fail('REPLACEMENT_REQUIRED', 'Confirm replacement of your current selection first.')
      if (!Array.isArray(lineKeys) || !lineKeys.length || lineKeys.length > 100 || new Set(lineKeys).size !== lineKeys.length) fail('INVALID_SELECTION', 'Choose one or more different products from this request.')
      const selected = [...lineKeys], started = ++sequence
      update({ quoting: true, quote: null, acknowledged: false, error: null })
      const aborted = () => {
        if (started === sequence) { sequence++; update({ quoting: false }) }
      }
      signal?.addEventListener('abort', aborted, { once: true })
      try {
        const quote = await api.reorder(requestId, selected, signal)
        if (started !== sequence || signal?.aborted) return false
        validQuote(quote, now())
        if (quote.reorder?.source_request_id !== requestId || quote.customer_po !== '' || quote.total_amount !== null || quote.fees?.status !== 'pending') fail('INVALID_RESPONSE', 'The repeat request needs a fresh review. Your existing selection has been kept.')
        const ids = new Set()
        const lines = quote.items.map(line => {
          const display = line.display_snapshot
          if (!display || !line.item_id || ids.has(line.item_id)) fail('INVALID_RESPONSE', 'The repeated selection is unavailable.')
          ids.add(line.item_id)
          const item = { item_id: line.item_id, model_name: display.model_name, color_name: display.color_name,
            customer_sku: display.customer_sku, length_display: String(display.length), weight_display: String(display.weight),
            sale_unit: display.unit, unit_price: line.unit_price, min_order_qty: line.min_order_qty, step_qty: line.step_qty }
          return { ...item, quantity: quantityFor(item, line.quantity) }
        })
        if (lines.length !== selected.length || !quote.delivery || typeof quote.remark !== 'string') fail('INVALID_RESPONSE', 'The repeated selection is incomplete. Please review it again.')
        writable()
        update({ lines, delivery: { ...blankDelivery(), ...structuredClone(quote.delivery) }, customer_po: '',
          remark: quote.remark, quote: structuredClone(quote), receipt: null, acknowledged: false })
        return true
      } finally { signal?.removeEventListener('abort', aborted); if (started === sequence) update({ quoting: false }) }
    },
    async quote() {
      writable()
      if (state.quoting) return
      if (!state.lines.length) fail('EMPTY_CART', 'Add a product to your selection first.')
      const delivery = Object.fromEntries(Object.entries(state.delivery).map(([key, value]) => [key, value.trim()]))
      if (!delivery.contact_name || !delivery.address_line1 || delivery.phone.length < 3 || !/^[A-Z]{2}$/.test(delivery.country_code)) fail('INVALID_DELIVERY', 'Enter a contact, phone, address and two-letter country code.')
      const started = ++sequence
      const body = { items: state.lines.map(({ item_id, quantity }) => ({ item_id, quantity })), delivery, customer_po: state.customer_po, remark: state.remark }
      update({ quoting: true, quote: null, acknowledged: false, error: null })
      try {
        const quote = await api.quote(body)
        if (started !== sequence) return
        validQuote(quote, now())
        update({ quote: structuredClone(quote), lines: state.lines.map(line => ({ ...line, unavailable: false })) })
      } catch (error) {
        if (started === sequence && error.code !== 'STALE_SCOPE') {
          const requested = new Set(body.items.map(line => line.item_id))
          const unavailable = new Set(error.code === 'RESOURCE_NOT_FOUND' && Array.isArray(error.issues)
            ? error.issues.filter(issue => issue?.code === 'ITEM_UNAVAILABLE' && requested.has(issue.item_id)).map(issue => issue.item_id) : [])
          update({ error, lines: state.lines.map(line => unavailable.has(line.item_id) ? { ...line, unavailable: true } : line) })
        }
      }
      finally { if (started === sequence) update({ quoting: false }) }
    },
    submit() {
      writable()
      const quote = state.quote
      if (!quote || !(quoteDeadline(quote.expires_at) > now())) fail('QUOTE_EXPIRED', 'Your review has expired. Refresh it before submitting.')
      if (!state.acknowledged) fail('CONFIRMATION_REQUIRED', 'Confirm the reviewed products and delivery details first.')
      return submission.begin({ quote_id: quote.quote_id, quote_content_hash: quote.content_hash, customer_po: quote.customer_po, remark: quote.remark })
    },
    dispose() { sequence++; offSession(); offSubmission(); listeners.clear() },
  }
}

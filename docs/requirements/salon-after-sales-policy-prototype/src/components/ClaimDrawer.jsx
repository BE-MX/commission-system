import { Check, CheckCircle, ClipboardText, FileMagnifyingGlass, ShieldCheck, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'

export default function ClaimDrawer({ open, onClose, policy, lang, c }) {
  const [order, setOrder] = useState('')
  const [quantity, setQuantity] = useState('')
  const [productSku, setProductSku] = useState('')
  const [colourLength, setColourLength] = useState('')
  const [batch, setBatch] = useState('')
  const [deliveryInstall, setDeliveryInstall] = useState('')
  const [careFacts, setCareFacts] = useState('')
  const [noticed, setNoticed] = useState('')
  const [checked, setChecked] = useState({})
  const [message, setMessage] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const closeButton = useRef(null)
  const drawer = useRef(null)
  const fieldRefs = useRef({})
  const restoreFocus = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const previousOverflow = document.body.style.overflow
    restoreFocus.current = document.activeElement
    setMessage('')
    setFieldErrors({})
    document.body.style.overflow = 'hidden'
    window.setTimeout(() => closeButton.current?.focus(), 0)
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose()
      if (event.key !== 'Tab') return
      const focusable = [...(drawer.current?.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href]',
      ) || [])]
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
      window.setTimeout(() => restoreFocus.current?.focus(), 0)
    }
  }, [open, onClose])

  useEffect(() => {
    setChecked({})
    setMessage('')
    setFieldErrors({})
  }, [policy.id])

  if (!open) return null

  const copySummary = async () => {
    const values = { order, productSku, colourLength, batch, quantity, deliveryInstall, noticed, careFacts }
    const requiredFields = ['order', 'productSku', 'colourLength', 'batch', 'quantity', 'deliveryInstall', 'noticed']
    if (policy.stage !== 'receiving') requiredFields.push('careFacts')
    const missing = requiredFields.filter((field) => !values[field].trim())
    if (missing.length > 0) {
      setMessage(c.requiredHint)
      setFieldErrors(Object.fromEntries(missing.map((field) => [field, true])))
      fieldRefs.current[missing[0]]?.focus()
      return
    }

    const readyEvidence = policy.evidence
      .filter((_, index) => checked[index])
      .map((item) => `- ${item[lang]}`)
      .join('\n')
    const summary = [
      `LeShine ${policy.code} — ${policy.title[lang]}`,
      `${c.orderNumber}: ${order.trim()}`,
      `${c.productSku}: ${productSku.trim() || '—'}`,
      `${c.colourLength}: ${colourLength.trim() || '—'}`,
      `${c.batchLabel}: ${batch.trim() || '—'}`,
      `${c.affectedQuantity}: ${quantity.trim() || '—'}`,
      `${c.deliveryInstall}: ${deliveryInstall.trim() || '—'}`,
      `${c.firstNoticed}: ${noticed.trim() || '—'}`,
      `${c.careFacts}: ${careFacts.trim() || '—'}`,
      `${c.reviewWindow}: ${policy.window[lang]}`,
      `${c.notifyBy}: ${policy.notify[lang]}`,
      '',
      `${c.evidenceReady}:`,
      readyEvidence || '—',
    ].join('\n')

    let success = false
    try {
      await navigator.clipboard.writeText(summary)
      success = true
    } catch {
      let input
      try {
        input = document.createElement('textarea')
        input.value = summary
        document.body.appendChild(input)
        input.select()
        success = document.execCommand('copy')
      } catch {
        success = false
      } finally {
        input?.remove()
      }
    }
    setMessage(success ? c.copied : c.copyFailed)
    window.setTimeout(() => setMessage(''), 2200)
  }

  const clearFieldError = (field) => {
    setFieldErrors((current) => ({ ...current, [field]: false }))
    setMessage('')
  }

  const errorProps = (field) => ({
    'aria-invalid': Boolean(fieldErrors[field]),
    'aria-describedby': fieldErrors[field] ? 'claim-error' : undefined,
  })

  return (
    <div className="drawer-layer" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <aside ref={drawer} className="claim-drawer" role="dialog" aria-modal="true" aria-labelledby="claim-title" aria-describedby="claim-intro">
        <header>
          <div>
            <span><ShieldCheck size={18} weight="duotone" /> {policy.code}</span>
            <h2 id="claim-title">{c.claimTitle}</h2>
            <p id="claim-intro">{c.claimIntro}</p>
          </div>
          <button ref={closeButton} type="button" onClick={onClose} aria-label={c.close}><X size={21} /></button>
        </header>

        <div className="claim-policy-summary">
          <small>{c.selectedPolicy}</small>
          <strong>{policy.title[lang]}</strong>
          <span>{policy.window[lang]}</span>
        </div>

        <div className="claim-fields">
          <label>
            <span>{c.orderNumber} *</span>
            <input
              ref={(node) => { fieldRefs.current.order = node }}
              value={order}
              onChange={(event) => { setOrder(event.target.value); clearFieldError('order') }}
              placeholder={c.orderPlaceholder}
              {...errorProps('order')}
            />
          </label>
          <label>
            <span>{c.productSku} *</span>
            <input ref={(node) => { fieldRefs.current.productSku = node }} value={productSku} onChange={(event) => { setProductSku(event.target.value); clearFieldError('productSku') }} placeholder={c.productSkuPlaceholder} {...errorProps('productSku')} />
          </label>
          <label>
            <span>{c.colourLength} *</span>
            <input ref={(node) => { fieldRefs.current.colourLength = node }} value={colourLength} onChange={(event) => { setColourLength(event.target.value); clearFieldError('colourLength') }} placeholder={c.colourLengthPlaceholder} {...errorProps('colourLength')} />
          </label>
          <label>
            <span>{c.batchLabel} *</span>
            <input ref={(node) => { fieldRefs.current.batch = node }} value={batch} onChange={(event) => { setBatch(event.target.value); clearFieldError('batch') }} placeholder={c.batchLabelPlaceholder} {...errorProps('batch')} />
          </label>
          <label>
            <span>{c.affectedQuantity} *</span>
            <input ref={(node) => { fieldRefs.current.quantity = node }} value={quantity} onChange={(event) => { setQuantity(event.target.value); clearFieldError('quantity') }} placeholder={c.quantityPlaceholder} {...errorProps('quantity')} />
          </label>
          <label>
            <span>{c.deliveryInstall} *</span>
            <input ref={(node) => { fieldRefs.current.deliveryInstall = node }} value={deliveryInstall} onChange={(event) => { setDeliveryInstall(event.target.value); clearFieldError('deliveryInstall') }} placeholder={c.deliveryInstallPlaceholder} {...errorProps('deliveryInstall')} />
          </label>
          <label>
            <span>{c.firstNoticed} *</span>
            <input ref={(node) => { fieldRefs.current.noticed = node }} value={noticed} onChange={(event) => { setNoticed(event.target.value); clearFieldError('noticed') }} placeholder={c.noticedPlaceholder} {...errorProps('noticed')} />
          </label>
          <label>
            <span>{c.careFacts}{policy.stage !== 'receiving' ? ' *' : ''}</span>
            <textarea ref={(node) => { fieldRefs.current.careFacts = node }} value={careFacts} onChange={(event) => { setCareFacts(event.target.value); clearFieldError('careFacts') }} placeholder={c.careFactsPlaceholder} rows="3" {...errorProps('careFacts')} />
          </label>
        </div>

        <fieldset className="evidence-checklist">
          <legend><FileMagnifyingGlass size={18} weight="duotone" /> {c.evidenceReady}</legend>
          {policy.evidence.map((item, index) => (
            <label key={item[lang]}>
              <input
                type="checkbox"
                checked={Boolean(checked[index])}
                onChange={(event) => setChecked((value) => ({ ...value, [index]: event.target.checked }))}
              />
              <span aria-hidden="true">{checked[index] ? <Check size={14} weight="bold" /> : null}</span>
              <em>{item[lang]}</em>
            </label>
          ))}
        </fieldset>

        <div className="claim-drawer__footer">
          {message && <p id={Object.values(fieldErrors).some(Boolean) ? 'claim-error' : undefined} className={message === c.copied ? 'is-success' : ''} aria-live="polite">
            {message === c.copied && <CheckCircle size={16} weight="fill" />} {message}
          </p>}
          <button type="button" onClick={copySummary}><ClipboardText size={18} weight="bold" /> {c.buildSummary}</button>
        </div>
      </aside>
    </div>
  )
}

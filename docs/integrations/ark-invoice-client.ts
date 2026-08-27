/**
 * Minimal server-side client for the Ark external invoice API.
 *
 * Pass configuration from the site's server environment. Do not bundle this
 * file, its token, or a constructed client into code sent to a browser.
 */

export type MoneyString = string
export type ProductKind = 'hair' | 'accessory'
export type OrderType = 'stock' | 'production'

export interface CustomerContactSubmission {
  name?: string | null
  email?: string | null
  phone?: string | null
}

export interface CustomerSubmission {
  ark_customer_id?: string | null
  name?: string | null
  contact?: CustomerContactSubmission
}

export interface CatalogReference {
  product_id: number
  sku_id: number
}

export interface ProductDescriptionSubmission {
  product_display?: string | null
  model?: string | null
  color?: string | null
  length?: string | null
  unit?: string | null
}

export interface InvoiceLineSubmission {
  external_line_id?: string | null
  product_kind: ProductKind
  catalog_ref?: CatalogReference | null
  description?: ProductDescriptionSubmission
  quantity: number
  unit_price: MoneyString
  discount_amount?: MoneyString
}

export interface InvoiceSubmission {
  schema_version: '1.0'
  external_order_id: string
  order_type: OrderType
  invoice_date: string
  currency: string
  customer: CustomerSubmission
  delivery: {
    address?: string | null
    express_channel?: string | null
  }
  fees?: {
    packaging_amount?: MoneyString
    packaging_quantity?: number
    shipping_amount?: MoneyString
    surcharge?: {
      name?: string | null
      amount?: MoneyString
    }
  }
  declared_totals?: {
    product_amount: MoneyString
    total_amount: MoneyString
  } | null
  items: InvoiceLineSubmission[]
  payment_term?: string | null
  remark?: string | null
}

export interface ValidationIssue {
  code: string
  field: string
  message: string
}

export interface CanonicalCustomer {
  ark_customer_id: string
  name: string
  country_name: string | null
  contact: {
    name: string | null
    email: string | null
    phone: string | null
  }
}

export interface CanonicalProduct {
  product_kind: ProductKind
  catalog_ref: CatalogReference
  description: {
    product_name: string
    product_display: string
    model: string
    color: string
    length: string
    unit: string
  }
}

export interface ValidationResult {
  schema_version: '1.0'
  external_order_id: string
  order_type: OrderType
  invoice_date: string
  currency: string
  customer: CanonicalCustomer
  delivery: {
    address: string | null
    express_channel: string | null
  }
  fees: {
    packaging_amount: MoneyString
    packaging_quantity: number
    shipping_amount: MoneyString
    surcharge: {
      name: string | null
      amount: MoneyString
    }
  }
  payment_term: string | null
  remark: string | null
  items: Array<CanonicalProduct & {
    external_line_id: string | null
    quantity: number
    unit_price: MoneyString
    discount_amount: MoneyString
    standard_price: MoneyString | null
    customer_price: MoneyString | null
    price_source: string
    total_price: MoneyString
  }>
  totals: {
    product_amount: MoneyString
    total_amount: MoneyString
  }
  warnings: ValidationIssue[]
}

export interface CreateResult {
  request_id: string
  replayed: boolean
  external_order_id: string
  invoice_id: number
  invoice_no: string
  status: string
  sync_status: string
  totals: {
    product_amount: MoneyString
    total_amount: MoneyString
  }
  review_url: string
}

interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

interface ErrorData {
  error_code?: string
  issues?: ValidationIssue[]
  warnings?: ValidationIssue[]
  action?: string
  field?: string
  external_order_id?: string
  request_id?: string | null
}

function cleanErrorData(value: unknown): ErrorData {
  if (!isRecord(value)) return {}
  const result: ErrorData = {}
  if (typeof value.error_code === 'string') result.error_code = value.error_code
  if (Array.isArray(value.issues)) result.issues = value.issues.filter(isValidationIssue)
  if (Array.isArray(value.warnings)) result.warnings = value.warnings.filter(isValidationIssue)
  if (typeof value.action === 'string') result.action = value.action
  if (typeof value.field === 'string') result.field = value.field
  if (typeof value.external_order_id === 'string') {
    result.external_order_id = value.external_order_id
  }
  if (value.request_id === null || typeof value.request_id === 'string') {
    result.request_id = value.request_id
  }
  return result
}

function retryAfterMilliseconds(value: string | null): number | null {
  if (!value) return null
  const seconds = Number(value)
  if (Number.isFinite(seconds) && seconds >= 0) return Math.min(seconds * 1_000, 30_000)
  const date = Date.parse(value)
  if (!Number.isFinite(date)) return null
  return Math.min(Math.max(0, date - new Date().getTime()), 30_000)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const CURRENCY_PATTERN = /^[A-Z]{3}$/
const MONEY_2_PATTERN = /^\d+\.\d{2}$/
const SIGNED_MONEY_2_PATTERN = /^-?\d+\.\d{2}$/
const MONEY_4_PATTERN = /^\d+\.\d{4}$/

function isMoney2(value: unknown): value is string {
  return typeof value === 'string' && MONEY_2_PATTERN.test(value)
}

function isMoney4(value: unknown): value is string {
  return typeof value === 'string' && MONEY_4_PATTERN.test(value)
}

function isNullableMoney4(value: unknown): value is string | null {
  return value === null || isMoney4(value)
}

function isCatalogReference(value: unknown): value is CatalogReference {
  return isRecord(value)
    && Number.isInteger(value.product_id)
    && Number.isInteger(value.sku_id)
}

function isCanonicalDescription(value: unknown): boolean {
  return isRecord(value)
    && typeof value.product_name === 'string'
    && typeof value.product_display === 'string'
    && typeof value.model === 'string'
    && typeof value.color === 'string'
    && typeof value.length === 'string'
    && typeof value.unit === 'string'
}

function isValidationIssue(value: unknown): value is ValidationIssue {
  return isRecord(value)
    && typeof value.code === 'string'
    && typeof value.field === 'string'
    && typeof value.message === 'string'
}

function isCanonicalCustomer(value: unknown): value is CanonicalCustomer {
  if (!isRecord(value) || !isRecord(value.contact)) return false
  return typeof value.ark_customer_id === 'string'
    && typeof value.name === 'string'
    && isNullableString(value.country_name)
    && isNullableString(value.contact.name)
    && isNullableString(value.contact.email)
    && isNullableString(value.contact.phone)
}

function isValidationLine(value: unknown): boolean {
  if (!isRecord(value) || !isRecord(value.description)) return false
  return isNullableString(value.external_line_id)
    && (value.product_kind === 'hair' || value.product_kind === 'accessory')
    && isCatalogReference(value.catalog_ref)
    && isCanonicalDescription(value.description)
    && Number.isInteger(value.quantity)
    && isMoney4(value.unit_price)
    && typeof value.discount_amount === 'string'
    && SIGNED_MONEY_2_PATTERN.test(value.discount_amount)
    && isNullableMoney4(value.standard_price)
    && isNullableMoney4(value.customer_price)
    && typeof value.price_source === 'string'
    && isMoney2(value.total_price)
}

function isValidationResult(value: unknown, externalOrderId: string): value is ValidationResult {
  if (
    !isRecord(value)
    || !isCanonicalCustomer(value.customer)
    || !isRecord(value.delivery)
    || !isRecord(value.fees)
    || !isRecord(value.fees.surcharge)
    || !isRecord(value.totals)
  ) return false

  return value.schema_version === '1.0'
    && value.external_order_id === externalOrderId
    && (value.order_type === 'stock' || value.order_type === 'production')
    && typeof value.invoice_date === 'string'
    && ISO_DATE_PATTERN.test(value.invoice_date)
    && typeof value.currency === 'string'
    && CURRENCY_PATTERN.test(value.currency)
    && isNullableString(value.delivery.address)
    && isNullableString(value.delivery.express_channel)
    && isMoney2(value.fees.packaging_amount)
    && Number.isInteger(value.fees.packaging_quantity)
    && isMoney2(value.fees.shipping_amount)
    && isNullableString(value.fees.surcharge.name)
    && isMoney2(value.fees.surcharge.amount)
    && isNullableString(value.payment_term)
    && isNullableString(value.remark)
    && Array.isArray(value.items)
    && value.items.every(isValidationLine)
    && isMoney2(value.totals.product_amount)
    && isMoney2(value.totals.total_amount)
    && Array.isArray(value.warnings)
    && value.warnings.every(isValidationIssue)
}

function isCreateResult(value: unknown, externalOrderId: string): value is CreateResult {
  if (!isRecord(value) || !isRecord(value.totals)) return false
  return typeof value.request_id === 'string'
    && typeof value.replayed === 'boolean'
    && value.external_order_id === externalOrderId
    && Number.isInteger(value.invoice_id)
    && typeof value.invoice_no === 'string'
    && typeof value.status === 'string'
    && typeof value.sync_status === 'string'
    && isMoney2(value.totals.product_amount)
    && isMoney2(value.totals.total_amount)
    && typeof value.review_url === 'string'
}

export class ArkInvoiceApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly data: ErrorData,
    public readonly retryAfterMs: number | null = null,
  ) {
    super(message)
    this.name = 'ArkInvoiceApiError'
  }
}

export class ArkInvoiceTransportError extends Error {
  constructor(
    public readonly kind: 'timeout' | 'network',
    message: string,
  ) {
    super(message)
    this.name = 'ArkInvoiceTransportError'
  }
}

export class ArkInvoiceSuccessfulResponseError extends Error {
  constructor(public readonly status: number) {
    super('Ark invoice API returned an invalid successful response')
    this.name = 'ArkInvoiceSuccessfulResponseError'
  }
}

export class ArkInvoiceResultUnknownError extends Error {
  constructor(
    public readonly externalOrderId: string,
    public readonly lastError: unknown,
  ) {
    super(`Ark invoice result is still unknown for external order ${externalOrderId}`)
    this.name = 'ArkInvoiceResultUnknownError'
  }
}

export interface ArkInvoiceClientOptions {
  baseUrl: string
  token: string
  timeoutMs?: number
  recoveryDelayMs?: number
  recoveryAttempts?: number
  allowInsecureLocalhost?: boolean
  fetchImpl?: typeof fetch
}

export class ArkInvoiceClient {
  private readonly baseUrl: string
  private readonly token: string
  private readonly timeoutMs: number
  private readonly recoveryDelayMs: number
  private readonly recoveryAttempts: number
  private readonly fetchImpl: typeof fetch

  constructor(options: ArkInvoiceClientOptions) {
    let baseUrl: URL
    try {
      baseUrl = new URL(options.baseUrl)
    } catch {
      throw new TypeError('Ark invoice baseUrl must be an absolute HTTPS URL')
    }
    const localhost = ['localhost', '127.0.0.1', '[::1]'].includes(baseUrl.hostname)
    const allowedLocalHttp = options.allowInsecureLocalhost === true
      && baseUrl.protocol === 'http:'
      && localhost
    if (baseUrl.protocol !== 'https:' && !allowedLocalHttp) {
      throw new TypeError('Ark invoice baseUrl must use HTTPS')
    }
    if (baseUrl.username || baseUrl.password || baseUrl.search || baseUrl.hash) {
      throw new TypeError('Ark invoice baseUrl cannot contain credentials, query, or fragment')
    }
    if (!options.token.startsWith('ark_live_')) {
      throw new TypeError('Ark invoice token is missing or invalid')
    }
    if (
      options.timeoutMs !== undefined
      && (!Number.isFinite(options.timeoutMs) || options.timeoutMs <= 0)
    ) {
      throw new TypeError('timeoutMs must be a finite number greater than zero')
    }
    if (
      options.recoveryDelayMs !== undefined
      && (!Number.isFinite(options.recoveryDelayMs) || options.recoveryDelayMs < 0)
    ) {
      throw new TypeError('recoveryDelayMs must be a finite non-negative number')
    }
    if (
      options.recoveryAttempts !== undefined
      && (!Number.isInteger(options.recoveryAttempts)
        || options.recoveryAttempts < 1
        || options.recoveryAttempts > 10)
    ) {
      throw new TypeError('recoveryAttempts must be an integer from 1 to 10')
    }

    this.baseUrl = baseUrl.toString().replace(/\/+$/, '')
    this.token = options.token
    this.timeoutMs = options.timeoutMs ?? 15_000
    this.recoveryDelayMs = options.recoveryDelayMs ?? 500
    this.recoveryAttempts = options.recoveryAttempts ?? 3
    this.fetchImpl = options.fetchImpl ?? fetch
  }

  validateInvoice(payload: InvoiceSubmission): Promise<ValidationResult> {
    return this.request<ValidationResult>('/invoices/validate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, (response, envelope) => {
      if (
        response.status !== 200
        || envelope.code !== 200
        || envelope.message !== 'ok'
        || !isValidationResult(envelope.data, payload.external_order_id)
      ) throw new ArkInvoiceSuccessfulResponseError(response.status)
      return envelope.data
    })
  }

  async createInvoice(payload: InvoiceSubmission): Promise<CreateResult> {
    let initialError: unknown
    try {
      return await this.createOnce(payload)
    } catch (error) {
      if (!this.isAmbiguousCreateError(error)) throw error
      initialError = error
    }
    return this.recoverCreate(payload, initialError)
  }

  private async recoverCreate(
    payload: InvoiceSubmission,
    initialError: unknown,
  ): Promise<CreateResult> {
    let lastError = initialError
    let retriedCreate = false

    for (let attempt = 0; attempt < this.recoveryAttempts; attempt += 1) {
      await this.waitBeforeRecovery(lastError, attempt)
      try {
        return await this.getInvoiceByExternalId(payload.external_order_id)
      } catch (lookupError) {
        if (this.isExternalOrderChanged(lookupError)) throw lookupError

        if (lookupError instanceof ArkInvoiceApiError && lookupError.status === 404) {
          lastError = lookupError
          if (!retriedCreate) {
            retriedCreate = true
            await this.waitBeforeRecovery(lookupError, attempt)
            try {
              return await this.createOnce(payload)
            } catch (retryError) {
              if (!this.isAmbiguousCreateError(retryError)) throw retryError
              lastError = retryError
            }
          }
          continue
        }

        if (!this.isRetryableLookupError(lookupError)) throw lookupError
        lastError = lookupError
      }
    }

    throw new ArkInvoiceResultUnknownError(payload.external_order_id, lastError)
  }

  getInvoiceByExternalId(externalOrderId: string): Promise<CreateResult> {
    return this.request<CreateResult>(
      `/invoices/by-external-id/${encodeURIComponent(externalOrderId)}`,
      { method: 'GET' },
      (response, envelope) => {
        if (
          response.status !== 200
          || envelope.code !== 200
          || envelope.message !== 'invoice replayed'
          || !isCreateResult(envelope.data, externalOrderId)
          || envelope.data.replayed !== true
        ) throw new ArkInvoiceSuccessfulResponseError(response.status)
        return envelope.data
      },
    )
  }

  private createOnce(payload: InvoiceSubmission): Promise<CreateResult> {
    return this.request<CreateResult>('/invoices', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, (response, envelope) => {
      if (!isCreateResult(envelope.data, payload.external_order_id)) {
        throw new ArkInvoiceSuccessfulResponseError(response.status)
      }
      const firstCreate = response.status === 201
        && envelope.code === 201
        && envelope.message === 'invoice created'
        && envelope.data.replayed === false
      const replay = response.status === 200
        && envelope.code === 200
        && envelope.message === 'invoice replayed'
        && envelope.data.replayed === true
      if (!firstCreate && !replay) throw new ArkInvoiceSuccessfulResponseError(response.status)
      return envelope.data
    })
  }

  private isAmbiguousCreateError(error: unknown): boolean {
    return error instanceof ArkInvoiceTransportError
      || error instanceof ArkInvoiceSuccessfulResponseError
      || (error instanceof ArkInvoiceApiError && (
        error.status >= 500
        || error.status === 429
        || (error.status === 409 && error.data.error_code === 'INVOICE_PROCESSING')
      ))
  }

  private isRetryableLookupError(error: unknown): boolean {
    return error instanceof ArkInvoiceTransportError
      || error instanceof ArkInvoiceSuccessfulResponseError
      || (error instanceof ArkInvoiceApiError && (
        error.status === 404
        || error.status === 429
        || error.status >= 500
        || (error.status === 409 && error.data.error_code === 'INVOICE_PROCESSING')
      ))
  }

  private isExternalOrderChanged(error: unknown): boolean {
    return error instanceof ArkInvoiceApiError
      && error.status === 409
      && error.data.error_code === 'EXTERNAL_ORDER_CHANGED'
  }

  private async waitBeforeRecovery(error: unknown, attempt: number): Promise<void> {
    const retryAfterMs = error instanceof ArkInvoiceApiError
      ? error.retryAfterMs
      : null
    const backoffMs = Math.min(this.recoveryDelayMs * (2 ** attempt), 5_000)
    const delayMs = retryAfterMs ?? backoffMs
    if (delayMs > 0) await new Promise(resolve => setTimeout(resolve, delayMs))
  }

  private async request<T>(
    path: string,
    init: RequestInit,
    parseSuccess: (
      response: Response,
      envelope: Partial<ApiEnvelope<unknown>>,
    ) => T,
  ): Promise<T> {
    const controller = new AbortController()
    let timedOut = false
    const timeout = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, this.timeoutMs)

    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${this.token}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...init.headers,
        },
      })

      let parsed: unknown
      try {
        parsed = await this.readJson(response, controller.signal)
      } catch (error) {
        if (timedOut) throw error
        if (response.ok) {
          throw new ArkInvoiceSuccessfulResponseError(response.status)
        }
        throw new ArkInvoiceApiError(
          response.status,
          'Ark invoice API returned an invalid response',
          {},
          retryAfterMilliseconds(response.headers.get('Retry-After')),
        )
      }

      const envelope = isRecord(parsed)
        ? parsed as Partial<ApiEnvelope<unknown>>
        : {}

      if (!response.ok) {
        throw new ArkInvoiceApiError(
          response.status,
          typeof envelope.message === 'string'
            ? envelope.message
            : 'Ark invoice API rejected the request',
          cleanErrorData(envelope.data),
          retryAfterMilliseconds(response.headers.get('Retry-After')),
        )
      }
      return parseSuccess(response, envelope)
    } catch (error) {
      if (
        error instanceof ArkInvoiceApiError
        || error instanceof ArkInvoiceSuccessfulResponseError
        || error instanceof ArkInvoiceTransportError
      ) throw error
      throw new ArkInvoiceTransportError(
        timedOut ? 'timeout' : 'network',
        timedOut ? 'Ark invoice request timed out' : 'Ark invoice network request failed',
      )
    } finally {
      clearTimeout(timeout)
    }
  }

  private readJson(response: Response, signal: AbortSignal): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const abort = () => reject(new Error('Ark invoice response body aborted'))
      signal.addEventListener('abort', abort, { once: true })
      response.json().then(resolve, reject).finally(() => {
        signal.removeEventListener('abort', abort)
      })
    })
  }
}

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

export interface ArkInvoiceClientOptions {
  baseUrl: string
  token: string
  timeoutMs?: number
  fetchImpl?: typeof fetch
}

export class ArkInvoiceClient {
  private readonly baseUrl: string
  private readonly token: string
  private readonly timeoutMs: number
  private readonly fetchImpl: typeof fetch

  constructor(options: ArkInvoiceClientOptions) {
    if (!/^https?:\/\//.test(options.baseUrl)) {
      throw new TypeError('Ark invoice baseUrl must be an absolute HTTP(S) URL')
    }
    if (!options.token.startsWith('ark_live_')) {
      throw new TypeError('Ark invoice token is missing or invalid')
    }
    if (options.timeoutMs !== undefined && options.timeoutMs <= 0) {
      throw new TypeError('timeoutMs must be greater than zero')
    }

    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.token = options.token
    this.timeoutMs = options.timeoutMs ?? 15_000
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
    try {
      return await this.createOnce(payload)
    } catch (error) {
      if (!this.isAmbiguousCreateError(error)) throw error
    }

    try {
      return await this.getInvoiceByExternalId(payload.external_order_id)
    } catch (lookupError) {
      if (!(lookupError instanceof ArkInvoiceApiError && lookupError.status === 404)) {
        throw lookupError
      }
    }

    // A lookup can briefly return 404 while the first request is still reaching
    // Ark. Retrying the unchanged payload is safe because Ark keys idempotency by
    // the same Integration App and payload.external_order_id.
    try {
      return await this.createOnce(payload)
    } catch (retryError) {
      if (!this.isAmbiguousCreateError(retryError)) throw retryError
      return this.getInvoiceByExternalId(payload.external_order_id)
    }
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
      || (error instanceof ArkInvoiceApiError && error.status >= 500)
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

    let response: Response
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${this.token}`,
          'Content-Type': 'application/json',
          Accept: 'application/json',
          ...init.headers,
        },
      })
    } catch {
      throw new ArkInvoiceTransportError(
        timedOut ? 'timeout' : 'network',
        timedOut ? 'Ark invoice request timed out' : 'Ark invoice network request failed',
      )
    } finally {
      clearTimeout(timeout)
    }

    let parsed: unknown
    try {
      parsed = await response.json()
    } catch {
      if (response.ok) {
        throw new ArkInvoiceSuccessfulResponseError(response.status)
      }
      throw new ArkInvoiceApiError(
        response.status,
        'Ark invoice API returned an invalid response',
        {},
      )
    }

    const envelope = isRecord(parsed)
      ? parsed as Partial<ApiEnvelope<unknown>>
      : {}

    if (!response.ok) {
      throw new ArkInvoiceApiError(
        response.status,
        envelope.message || 'Ark invoice API rejected the request',
        (envelope.data || {}) as ErrorData,
      )
    }
    return parseSuccess(response, envelope)
  }
}

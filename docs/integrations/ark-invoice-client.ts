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
    )
  }

  private createOnce(payload: InvoiceSubmission): Promise<CreateResult> {
    return this.request<CreateResult>('/invoices', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  }

  private isAmbiguousCreateError(error: unknown): boolean {
    return error instanceof ArkInvoiceTransportError
      || error instanceof ArkInvoiceSuccessfulResponseError
      || (error instanceof ArkInvoiceApiError && error.status >= 500)
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
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

    const envelope = parsed as Partial<ApiEnvelope<T | ErrorData>>
    if (
      response.ok
      && (
        parsed === null
        || typeof parsed !== 'object'
        || !Object.prototype.hasOwnProperty.call(parsed, 'data')
        || envelope.data === null
        || envelope.data === undefined
      )
    ) {
      throw new ArkInvoiceSuccessfulResponseError(response.status)
    }

    if (!response.ok) {
      throw new ArkInvoiceApiError(
        response.status,
        envelope.message || 'Ark invoice API rejected the request',
        (envelope.data || {}) as ErrorData,
      )
    }
    return envelope.data as T
  }
}

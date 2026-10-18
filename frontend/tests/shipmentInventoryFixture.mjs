// Sufficient synthetic stock for existing shipment-flow browser fixtures.
export const shipmentInventoryFixture = invoice => ({ invoice_id: invoice.id, source: 'okki_live',
  warehouse_id: '17', queried_at: '2026-10-16T00:01:00', items: invoice.items.map(row => ({
    invoice_item_id: row.id, product_id: row.product_id ?? null, sku_id: row.sku_id ?? null,
    available_stock: '100', reason: '' })) })

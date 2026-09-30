export function createCustomerMediaPreviewPayload(batch, dimensions = []) {
  // postMessage cannot clone Vue proxies; copy only fields used by the client portal.
  return {
    type: 'customer-media-preview',
    customer: {
      customer_id: batch.customer_id,
      customer_name: batch.customer_name,
    },
    batch: {
      id: batch.id,
      title: `拍摄素材 · ${batch.customer_name}`,
      seq: 1,
      published_at: batch.published_at,
      shoot_type: batch.shoot_type,
      assets: (batch.assets || []).map(asset => ({
        id: asset.id,
        file_name: asset.file_name,
        file_size: asset.file_size,
        media_type: asset.media_type,
        content_url: asset.content_url,
        tags: (asset.tags || []).map(tag => ({
          dimension_id: tag.dimension_id,
          dimension_label: tag.dimension_label,
          tag_value_id: tag.tag_value_id,
          value: tag.value,
        })),
      })),
    },
    dimensions: dimensions.map(dimension => ({
      id: dimension.id,
      name: dimension.name,
      label: dimension.label,
    })),
  }
}

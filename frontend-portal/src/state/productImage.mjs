// Only authorized portal image paths may become browser requests.
export function productImageSource(url, size) {
  if (!/^\/api\/portal\/v1\/catalog\/(swatches\/)?[a-f0-9-]{36}\/image\?version=[1-9][0-9]*(&size=(thumb|full))?$/i.test(url || '')) return null
  // Swatches default to 96px; gallery images must opt into the 1200px rendition.
  if (['thumb', 'full'].includes(size)) return url.replace(/&size=(thumb|full)$/i, '') + '&size=' + size
  return url
}

export function downloadUrl(url) {
  const a = document.createElement('a')
  a.href = url
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function downloadFilename(disposition, fallback) {
  const starMatch = disposition.match(/(?:^|;)\s*filename\*=UTF-8'[^']*'([^;]*)/i)
  const plainMatch = disposition.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]*))/i)
  let extended = ''
  if (starMatch) {
    try {
      extended = decodeURIComponent(starMatch[1].trim())
    } catch {
      // A malformed optional filename must not prevent saving valid file bytes.
    }
  }
  const filename = extended || plainMatch?.[1] || plainMatch?.[2] || fallback
  return filename.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/[. ]+$/, '') || fallback
}

export function downloadBlob(response, fallbackFilename = 'export.xlsx') {
  const headers = response.headers || {}
  const filename = downloadFilename(headers['content-disposition'] || '', fallbackFilename)
  // Axios already supplies a typed Blob. Rewrapping without a type loses its MIME type.
  const data = response.data
  const blob = data instanceof Blob && data.type
    ? data
    : new Blob([data], { type: headers['content-type'] || '' })

  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  try {
    a.click()
  } finally {
    document.body.removeChild(a)
    // Give the browser time to take ownership of the download; click() is asynchronous.
    // This grace period is not a signal that the file has finished saving to disk.
    setTimeout(() => window.URL.revokeObjectURL(url), 60000)
  }
}

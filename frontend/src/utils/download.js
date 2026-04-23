export function downloadUrl(url) {
  const a = document.createElement('a')
  a.href = url
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

export function downloadBlob(response) {
  const disposition = response.headers['content-disposition'] || ''
  const match = disposition.match(/filename=(.+?)(?:;|$)/)
  const filename = match ? decodeURIComponent(match[1]) : 'export.xlsx'

  const url = window.URL.createObjectURL(new Blob([response.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

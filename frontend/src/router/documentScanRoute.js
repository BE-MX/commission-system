export const DOCUMENT_SCAN_PATH = '/document-scan'

export function isDocumentScanPath(path) {
  return String(path || '').split(/[?#]/)[0].replace(/\/+$/, '') === DOCUMENT_SCAN_PATH
}

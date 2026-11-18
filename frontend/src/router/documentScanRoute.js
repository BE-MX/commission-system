export const DOCUMENT_SCAN_PATH = '/document-scan'

export const FACTORY_INBOUND_SCAN_PATH = '/factory-inbound/scan'

export function isFactoryInboundScanPath(path) {
  return String(path || '').split(/[?#]/)[0].replace(/\/+$/, '') === FACTORY_INBOUND_SCAN_PATH
}

export function isDocumentScanPath(path) {
  return String(path || '').split(/[?#]/)[0].replace(/\/+$/, '') === DOCUMENT_SCAN_PATH
}

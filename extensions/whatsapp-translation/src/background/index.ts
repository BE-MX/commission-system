chrome.runtime.onMessage.addListener((_request, _sender, sendResponse) => {
  sendResponse({ type: 'error', message: 'not_implemented' })
  return false
})


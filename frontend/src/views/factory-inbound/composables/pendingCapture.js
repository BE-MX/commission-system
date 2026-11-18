function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('ark-factory-inbound', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('captures')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
    request.onblocked = () => reject(new Error('Capture storage blocked'))
  })
}

async function accessCapture(actor, operation) {
  if (actor == null) return null
  let db
  try {
    db = await openDatabase()
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('captures', operation === null ? 'readonly' : 'readwrite')
      const request = operation === null
        ? tx.objectStore('captures').get(String(actor))
        : operation === false
          ? tx.objectStore('captures').delete(String(actor))
          : tx.objectStore('captures').put(operation, String(actor))
      tx.oncomplete = () => resolve(request.result ?? null)
      tx.onabort = () => reject(tx.error)
      tx.onerror = () => reject(tx.error)
    })
  } catch {
    // Browser privacy settings may disable IndexedDB.
    return null
  } finally {
    db?.close()
  }
}

export const loadCapture = actor => accessCapture(actor, null)
export const storeCapture = (actor, capture) => accessCapture(actor, capture)
export const clearCapture = actor => accessCapture(actor, false)

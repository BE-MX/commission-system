// One authenticated request and one ZIP download for the entire selection.
export async function requestArchive(assetIds, signal) {
  const ids = [...new Set(assetIds)];
  if (!ids.length) throw new Error('Select at least one file.');
  const response = await fetch('/api/customer-media/portal/downloads/zip', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_ids: ids }),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = typeof error.detail === 'string' ? error.detail : '';
    throw new Error(response.status === 401 ? 'Your session has expired. Please sign in again.'
      : detail || 'Unable to prepare the ZIP. Please try again.');
  }
  if (!response.headers.get('content-type')?.includes('application/zip')) {
    throw new Error('The ZIP could not be downloaded. Please try again.');
  }
  return response.blob();
}

export function saveArchive(blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  try {
    link.href = url;
    link.download = 'LeShine-materials.zip';
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    // Keep the Blob alive long enough for the browser's download manager to consume it.
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
}

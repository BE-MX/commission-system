export const JPG_LIMIT = 25 * 1024 * 1024;
export const PSD_PART_SIZE = 8 * 1024 * 1024;
export const PSD_MAX_PARTS = 32;
export const PSD_LIMIT = PSD_PART_SIZE * PSD_MAX_PARTS;

export function isJpeg(bytes: Uint8Array) {
  return bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
}

export function jpegDimensions(bytes: Uint8Array) {
  if (!isJpeg(bytes)) return null;
  const startOfFrame = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
  let offset = 2;
  while (offset + 8 < bytes.length) {
    if (bytes[offset] !== 0xff) { offset += 1; continue; }
    while (offset < bytes.length && bytes[offset] === 0xff) offset += 1;
    const marker = bytes[offset];
    offset += 1;
    if (marker === 0xd8 || marker === 0x01) continue;
    if (marker === 0xd9 || marker === 0xda || offset + 1 >= bytes.length) break;
    const segmentLength = (bytes[offset] << 8) | bytes[offset + 1];
    if (segmentLength < 2 || offset + segmentLength > bytes.length) return null;
    if (startOfFrame.has(marker) && segmentLength >= 7) {
      const height = (bytes[offset + 3] << 8) | bytes[offset + 4];
      const width = (bytes[offset + 5] << 8) | bytes[offset + 6];
      return width > 0 && height > 0 ? { width, height } : null;
    }
    offset += segmentLength;
  }
  return null;
}

export function isPsd(bytes: Uint8Array) {
  return bytes.length >= 4 && bytes[0] === 0x38 && bytes[1] === 0x42 && bytes[2] === 0x50 && bytes[3] === 0x53;
}

export function psdDimensions(bytes: Uint8Array) {
  if (bytes.length < 26 || !isPsd(bytes)) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const version = view.getUint16(4, false);
  const height = view.getUint32(14, false);
  const width = view.getUint32(18, false);
  if ((version !== 1 && version !== 2) || !width || !height || width > 300000 || height > 300000) return null;
  return { width, height };
}

export function normalizedParts(value: unknown) {
  if (!Array.isArray(value) || !value.length || value.length > PSD_MAX_PARTS) return null;
  const parts = value.map((raw) => {
    const input = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
    return {
      partNumber: Number(input.partNumber),
      etag: typeof input.etag === 'string' ? input.etag : '',
    };
  }).sort((a, b) => a.partNumber - b.partNumber);
  if (parts.some((part, index) => (
    !Number.isInteger(part.partNumber) ||
    part.partNumber !== index + 1 ||
    !part.etag ||
    part.etag.length > 256
  ))) return null;
  return parts;
}

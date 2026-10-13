import { createCipheriv, createDecipheriv, hkdfSync, randomBytes, timingSafeEqual } from 'node:crypto'
import { BufferJSON } from 'baileys'

export function error(code, status = 409) {
  return Object.assign(new Error(code), { code, statusCode: status })
}

export class Cipher {
  constructor(base64, version = '1') {
    if (!/^[A-Za-z0-9+/]{43}=$/.test(base64 || '')) throw error('encryption_key_required', 500)
    const master = Buffer.from(base64, 'base64')
    if (master.length !== 32 || master.toString('base64') !== base64) throw error('invalid_encryption_key', 500)
    if (!/^[A-Za-z0-9_-]{1,32}$/.test(version)) throw error('invalid_key_version', 500)
    this.version = version
    this.keys = Object.fromEntries(['auth', 'data'].map(domain => [domain,
      Buffer.from(hkdfSync('sha256', master, 'ark-whatsapp-connector', domain, 32))]))
  }

  seal(value, domain, identity) {
    const iv = randomBytes(12)
    const cipher = createCipheriv('aes-256-gcm', this.keys[domain], iv)
    cipher.setAAD(Buffer.from(`${domain}:${this.version}:${identity}`))
    const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value, BufferJSON.replacer)), cipher.final()])
    return JSON.stringify({ key_version: this.version, iv: iv.toString('base64'),
      tag: cipher.getAuthTag().toString('base64'), ciphertext: ciphertext.toString('base64') })
  }

  open(blob, domain, identity) {
    try {
      const item = JSON.parse(blob)
      if (item.key_version !== this.version) throw error('encryption_key_version_mismatch', 500)
      const decipher = createDecipheriv('aes-256-gcm', this.keys[domain], Buffer.from(item.iv, 'base64'))
      decipher.setAAD(Buffer.from(`${domain}:${item.key_version}:${identity}`))
      decipher.setAuthTag(Buffer.from(item.tag, 'base64'))
      return JSON.parse(Buffer.concat([decipher.update(Buffer.from(item.ciphertext, 'base64')),
        decipher.final()]).toString(), BufferJSON.reviver)
    } catch (err) {
      throw error(err.code === 'encryption_key_version_mismatch' ? err.code : 'encrypted_store_unreadable', 500)
    }
  }
}

export function bearerMatches(value, expected) {
  const a = Buffer.from(String(value || ''))
  const b = Buffer.from(`Bearer ${expected}`)
  return a.length === b.length && timingSafeEqual(a, b)
}

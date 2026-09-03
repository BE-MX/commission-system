import { JSDOM } from 'jsdom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const popupHtml = `
  <main id="popup" data-state="loading">
    <section id="loading"></section>
    <section id="unpaired" hidden><button id="start-pairing"></button></section>
    <section id="pairing" hidden><button id="check-pairing"></button></section>
    <section id="ready" hidden>
      <p id="employee"></p>
      <p id="expiry"></p>
      <input id="enabled" type="checkbox" />
      <select id="language"><option value="zh-CN">中文</option></select>
      <button id="reauthorize"></button>
    </section>
    <section id="blocked" hidden></section>
    <section id="error" hidden></section>
  </main>
`

beforeEach(() => {
  vi.resetModules()
  const dom = new JSDOM(popupHtml)
  vi.stubGlobal('document', dom.window.document)
  vi.stubGlobal('HTMLElement', dom.window.HTMLElement)
  vi.stubGlobal('HTMLInputElement', dom.window.HTMLInputElement)
  vi.stubGlobal('HTMLSelectElement', dom.window.HTMLSelectElement)
})

describe('popup pairing recovery', () => {
  it('finishes a stored pairing automatically after the popup is reopened', async () => {
    const sendMessage = vi.fn(async (request: { type: string }) => {
      if (request.type === 'session/refresh') {
        const refreshCount = sendMessage.mock.calls
          .filter(([call]) => call.type === 'session/refresh').length
        if (refreshCount === 1) return { type: 'error', message: 'device_token_missing' }
        return {
          type: 'session/refresh',
          session: {
            deviceId: 7,
            expiresAt: '2027-03-02T10:00:00',
          },
        }
      }
      if (request.type === 'pairing/resume') {
        return {
          type: 'pairing/resume',
          state: { authorizeUrl: '', deviceCode: 'stored-device-code', status: 'ready' },
        }
      }
      if (request.type === 'preferences/get') {
        return { type: 'preferences/get', enabled: true, targetLanguage: 'zh-CN' }
      }
      return { type: 'error', message: 'unexpected_request' }
    })
    vi.stubGlobal('chrome', { runtime: { sendMessage } })

    await import('@/popup/index')

    await vi.waitFor(() => {
      expect(document.getElementById('popup')?.dataset.state).toBe('ready')
    })
    expect(sendMessage).toHaveBeenCalledWith({ type: 'pairing/resume' })
    expect(document.getElementById('employee')?.textContent).toBe('已授权设备 #7')
  })

  it('restores the completion button while server approval is still pending', async () => {
    const sendMessage = vi.fn(async (request: { type: string }) => {
      if (request.type === 'session/refresh') {
        return { type: 'error', message: 'device_token_missing' }
      }
      if (request.type === 'pairing/resume') {
        return {
          type: 'pairing/resume',
          state: { authorizeUrl: '', deviceCode: 'stored-device-code', status: 'pending' },
        }
      }
      return { type: 'error', message: 'unexpected_request' }
    })
    vi.stubGlobal('chrome', { runtime: { sendMessage } })

    await import('@/popup/index')

    await vi.waitFor(() => {
      expect(document.getElementById('popup')?.dataset.state).toBe('pairing')
    })
    expect(document.getElementById('check-pairing')?.hidden).toBe(false)
  })

  it('shows an error without discarding a pending pairing when recovery fails', async () => {
    const sendMessage = vi.fn(async (request: { type: string }) => {
      if (request.type === 'session/refresh') {
        return { type: 'error', message: 'device_token_missing' }
      }
      if (request.type === 'pairing/resume') {
        return { type: 'error', message: 'network_error' }
      }
      return { type: 'error', message: 'unexpected_request' }
    })
    vi.stubGlobal('chrome', { runtime: { sendMessage } })

    await import('@/popup/index')

    await vi.waitFor(() => {
      expect(document.getElementById('popup')?.dataset.state).toBe('error')
    })
    expect(document.getElementById('unpaired')?.hidden).toBe(true)
  })
})

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  MCP_ENDPOINT,
  buildAgentConfig,
  copyToClipboard,
  filterTokens,
  isKnowledgeReady,
} from '../src/views/system/mcpTokenManagement.js'


test('knowledge readiness requires both platform permission and library membership', () => {
  assert.equal(isKnowledgeReady({ has_knowledge_read: true, knowledge_library_count: 1 }), true)
  assert.equal(isKnowledgeReady({ has_knowledge_read: false, knowledge_library_count: 2 }), false)
  assert.equal(isKnowledgeReady({ has_knowledge_read: true, knowledge_library_count: 0 }), false)
})


test('token filters combine account or label keyword with status', () => {
  const rows = [
    { label: 'Sales agent', username: 'li', real_name: 'Li Ming', is_active: true },
    { label: 'Old service', username: 'wang', real_name: 'Wang', is_active: false },
  ]
  assert.deepEqual(filterTokens(rows, { keyword: 'sales', status: 'active' }), [rows[0]])
  assert.deepEqual(filterTokens(rows, { keyword: 'wang', status: 'revoked' }), [rows[1]])
})


test('agent config uses the fixed production MCP endpoint and bearer token', () => {
  assert.equal(MCP_ENDPOINT, 'https://leshine.work/mcp/')
  const config = JSON.parse(buildAgentConfig('secret-token'))
  assert.deepEqual(config, {
    mcpServers: {
      leshineArk: {
        type: 'streamable-http',
        url: MCP_ENDPOINT,
        headers: { Authorization: 'Bearer secret-token' },
      },
    },
  })
})


test('credential copy prefers the Clipboard API', async () => {
  const writes = []
  const copied = await copyToClipboard('token-value', {
    clipboard: { writeText: async (value) => writes.push(value) },
    documentRef: null,
  })

  assert.equal(copied, true)
  assert.deepEqual(writes, ['token-value'])
})


test('credential copy falls back when the Clipboard API is rejected', async () => {
  const textarea = {
    style: {},
    setAttribute() {},
    focus() {},
    select() {},
    setSelectionRange() {},
    removeCalled: false,
    remove() { this.removeCalled = true },
  }
  const documentRef = {
    body: { appendChild() {} },
    createElement: () => textarea,
    execCommand: (command) => command === 'copy',
  }

  const copied = await copyToClipboard('full-agent-config', {
    clipboard: { writeText: async () => { throw new Error('permission denied') } },
    documentRef,
  })

  assert.equal(copied, true)
  assert.equal(textarea.value, 'full-agent-config')
  assert.equal(textarea.removeCalled, true)
})


test('credential copy falls back when the Clipboard API is unavailable', async () => {
  const textarea = {
    style: {},
    setAttribute() {},
    focus() {},
    select() {},
    setSelectionRange() {},
    remove() {},
  }
  const documentRef = {
    body: { appendChild() {} },
    createElement: () => textarea,
    execCommand: () => true,
  }

  assert.equal(await copyToClipboard('token-value', { clipboard: null, documentRef }), true)
})


test('credential copy reports failure when neither copy mechanism is available', async () => {
  const copied = await copyToClipboard('token-value', {
    clipboard: undefined,
    documentRef: undefined,
  })

  assert.equal(copied, false)
})


test('navigation is permission protected and the page never persists plaintext secrets', () => {
  const navigation = readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/views/system/McpTokenManagement.vue', import.meta.url), 'utf8')
  assert.match(navigation, /path: '\/system\/mcp-tokens'/)
  assert.match(navigation, /permission: 'mcp:admin'/)
  assert.match(page, /@closed="clearIssuedSecret"/)
  assert.doesNotMatch(page, /localStorage|sessionStorage|console\.log/)
})

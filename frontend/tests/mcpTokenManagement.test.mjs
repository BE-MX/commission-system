import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  MCP_ENDPOINT,
  buildAgentConfig,
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


test('navigation is permission protected and the page never persists plaintext secrets', () => {
  const navigation = readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/views/system/McpTokenManagement.vue', import.meta.url), 'utf8')
  assert.match(navigation, /path: '\/system\/mcp-tokens'/)
  assert.match(navigation, /permission: 'mcp:admin'/)
  assert.match(page, /@closed="clearIssuedSecret"/)
  assert.doesNotMatch(page, /localStorage|sessionStorage|console\.log/)
})

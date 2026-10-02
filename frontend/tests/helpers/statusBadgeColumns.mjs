import { parse } from '@vue/compiler-dom'
import { parseExpression, parse as parseScript } from '@babel/parser'

// Inspect templates without mounting business pages or making API calls.
export function statusBadgeColumns(source, file = '') {
  const ast = parse(source, { parseMode: 'sfc' })
  const rows = []
  const hasBadge = node => node.tag === 'StatusBadge' || (node.children || []).some(hasBadge)
  function visit(node) {
    if (node.tag === 'el-table-column' && hasBadge(node)) {
      const attributes = Object.fromEntries(node.props.map(prop => prop.type === 6
        ? [prop.name, prop.value?.content ?? true]
        : [prop.arg?.content ? ':' + prop.arg.content : 'v-' + prop.name, prop.exp?.content ?? true]))
      const labels = []
      function badgeText(child) {
        if (child.tag === 'StatusBadge') {
          for (const part of child.children || []) {
            if (part.type === 2 && part.content.trim()) labels.push(part.content.trim())
            if (part.type === 5) labels.push(...expressionLabels(part.content.content))
          }
          const label = child.props.find(prop => prop.type === 6 && prop.name === 'label')
          if (label?.value) labels.push(label.value.content)
        }
        for (const part of child.children || []) badgeText(part)
      }
      badgeText(node)
      const lastProp = node.props.at(-1)
      const openingEnd = source.indexOf('>', lastProp?.loc.end.offset ?? node.loc.start.offset) + 1
      rows.push({
        file, line: node.loc.start.line, start: node.loc.start.offset, openingEnd, attributes, labels,
        width: dimension(attributes.width ?? attributes['min-width']),
        requiredWidth: badgeColumnWidth(labels),
        detailExpansion: attributes.type === 'expand',
      })
    }
    for (const child of node.children || []) visit(child)
  }
  visit(ast)
  return rows
}

function dimension(value) {
  return typeof value === 'string' && /^\d+(?:px)?$/.test(value) ? Number.parseInt(value, 10) : null
}

// Only displayed branches count; machine codes in a ternary test do not.
function expressionLabels(source) {
  try {
    const node = parseExpression(source)
    function labels(value) {
      if (!value) return []
      if (value.type === 'StringLiteral') return [value.value]
      if (value.type === 'ConditionalExpression') return [...labels(value.consequent), ...labels(value.alternate)]
      if (value.type === 'LogicalExpression') return [...labels(value.left), ...labels(value.right)]
      return []
    }
    return labels(node)
  } catch {
    return []
  }
}

export function badgeColumnWidth(labels = []) {
  // 50px cell padding/border + 20px badge padding/border; 12px workspace tag text.
  const textWidth = value => [...value].reduce((sum, char) => sum + (/[^\x00-\x7f]/.test(char) ? 12.5 : /\s/.test(char) ? 4 : 7.5), 0)
  return Math.max(100, ...labels.map(value => Math.ceil((70 + textWidth(value)) / 10) * 10))
}

export function withDictionary(column, dictionary) {
  const labels = [...column.labels, ...Object.values(dictionary).map(status => typeof status === 'string' ? status : status.label)]
  return { ...column, labels, requiredWidth: badgeColumnWidth(labels) }
}

// Read local display maps without executing a business page's setup or APIs.
export function statusFunctionDictionary(source, functionName) {
  const script = source.match(/<script\b[^>]*>([\s\S]*?)<\/script>/)?.[1]
  if (!script) throw new Error('Vue script not found')
  const ast = parseScript(script, { sourceType: 'module' })
  let displayFunction
  function visit(node, callback) {
    if (!node || typeof node !== 'object') return
    callback(node)
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(child => visit(child, callback))
      else if (value?.type) visit(value, callback)
    }
  }
  visit(ast, node => {
    if (node.type === 'FunctionDeclaration' && node.id?.name === functionName) displayFunction = node
    if (node.type === 'VariableDeclarator' && node.id?.name === functionName) displayFunction = node.init
  })
  const dictionary = {}
  visit(displayFunction, node => {
    if (node.type === 'ObjectProperty' && node.value.type === 'StringLiteral') {
      dictionary[node.key.name ?? node.key.value] = node.value.value
    }
  })
  if (!Object.keys(dictionary).length) throw new Error(`Display map not found: ${functionName}`)
  return dictionary
}

export function columnIssues(column) {
  if (column.detailExpansion || column.width === null) return []
  const issues = []
  if (column.width < column.requiredWidth) issues.push(`badge column needs at least ${column.requiredWidth}px, found ${column.width}px`)
  const maximum = dimension(column.attributes['max-width'])
  if (maximum !== null && maximum < column.width) issues.push('max-width is below min-width')
  return issues
}

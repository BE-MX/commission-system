import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { statusBadgeColumns, columnIssues, withDictionary, statusFunctionDictionary } from '../tests/helpers/statusBadgeColumns.mjs'
import { CASE_STATUS } from '../src/views/aftersales/aftersalesRules.js'
import { SALARY_STATUS } from '../src/views/salary/salaryStatus.js'
import { JOB_STATUS } from '../src/views/mail_outreach/presentation.js'
import { TRACKING_STATUS } from '../src/views/tracking/trackingStatus.js'
import { COLOR_TYPE_TEXT } from '../src/views/invoice/invoicePricePresentation.js'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src')
const rows = []
function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name)
    if (entry.isDirectory()) walk(file)
    else if (file.endsWith('.vue')) rows.push(...statusBadgeColumns(fs.readFileSync(file, 'utf8'), path.relative(root, file).replaceAll('\\', '/')))
  }
}
walk(root)
// These dynamic labels have browser coverage using the same real dictionaries.
const dictionaryColumns = [
  ['views/aftersales/AfterSalesList.vue', 'status', CASE_STATUS],
  ['views/salary/SalaryPeriods.vue', 'status', SALARY_STATUS],
  ['views/mail_outreach/MailOutreachQueue.vue', 'status', JOB_STATUS],
  ['views/tracking/TrackingList.vue', 'current-status', TRACKING_STATUS],
  ['views/invoice/InvoicePriceConfig.vue', 'color-type', COLOR_TYPE_TEXT],
  ['views/invoice/InvoicePriceConfig.vue', 'type', COLOR_TYPE_TEXT],
  ...[
    ['views/order_intelligence/OrderIntelligence.vue', 'risk', 'riskLabel'],
    ['views/insight/IntelligenceLibrary.vue', 'credibility', 'credibilityLabel'],
  ].map(([file, key, display]) => [file, key, statusFunctionDictionary(fs.readFileSync(path.join(root, file), 'utf8'), display)]),
]
for (const [file, key, dictionary] of dictionaryColumns) {
  const index = rows.findIndex(row => row.file === file && row.attributes['v-if']?.includes("'" + key + "'"))
  if (index === -1) throw new Error(`Dictionary status column not found: ${file} ${key}`)
  rows[index] = withDictionary(rows[index], dictionary)
}
const issues = rows.flatMap(row => columnIssues(row).map(message => `${row.file}:${row.line} ${message}`))
const dynamic = rows.filter(row => !row.detailExpansion && row.width === null)
// This page is the sole dynamic column template; widths live in its controller.
for (const row of dynamic) {
  if (row.file !== 'views/invoice/InvoiceManage.vue') {
    issues.push(`${row.file}:${row.line} badge column width needs an explicit review`)
    continue
  }
  const source = fs.readFileSync(path.join(root, 'views/invoice/composables/useInvoiceManagePage.js'), 'utf8')
  const widths = new Map([...source.matchAll(/key: '([^']+)'[^}]*minWidth: (\d+)/g)].map(match => [match[1], Number(match[2])]))
  for (const key of ['order_type', 'status', 'sync_status']) {
    if ((widths.get(key) ?? 0) < 100) issues.push(`${row.file} dynamic ${key} column is too narrow`)
  }
}
const reportIndex = process.argv.indexOf('--report')
if (reportIndex !== -1) {
  const target = path.resolve(process.argv[reportIndex + 1])
  fs.mkdirSync(path.dirname(target), { recursive: true })
  fs.writeFileSync(target, JSON.stringify({ columns: rows, issues }, null, 2) + '\n')
}
if (issues.length) {
  issues.forEach(message => console.error(message))
  process.exitCode = 1
} else {
  console.log(`StatusBadge columns: ${rows.length} checked, ${dynamic.length} dynamic template reviewed, no narrow columns.`)
}

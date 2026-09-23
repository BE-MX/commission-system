import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const hairTable = read('../src/views/invoice/components/InvoiceHairTable.vue')
const accessoryTable = read('../src/views/invoice/components/InvoiceAccessoryTable.vue')

// 明细可能几十上百行：两张表都吃当前页切片、固定窗口高度、窗内分页
for (const [name, source] of [['hair', hairTable], ['accessory', accessoryTable]]) {
  test(`${name} detail table paginates within a fixed-height window`, () => {
    assert.match(source, /:data="pagedItems"/)
    assert.match(source, /max-height="560"/)
    assert.match(source, /const pagedItems = computed\(\(\) => props\.items\.slice\(\(page\.value - 1\) \* pageSize\.value, page\.value \* pageSize\.value\)\)/)
    // 行号跨页连续（不因翻页从 1 重排）
    assert.match(source, /type="index" :index="indexBase"/)
    assert.match(source, /const indexBase = computed\(\(\) => \(page\.value - 1\) \* pageSize\.value \+ 1\)/)
    // 窗内分页器
    assert.match(source, /v-model:current-page="page"/)
    assert.match(source, /v-model:page-size="pageSize"/)
    assert.match(source, /:page-sizes="\[10, 20, 50\]"/)
    assert.match(source, /:total="items\.length"/)
    // 页码策略：初次装载回第一页；新增/导入跟到末页；删行后收敛页码
    assert.match(source, /if \(!before\) page\.value = 1/)
    assert.match(source, /else if \(now > before\) page\.value = pages/)
    assert.match(source, /else if \(page\.value > pages\) page\.value = pages/)
  })
}

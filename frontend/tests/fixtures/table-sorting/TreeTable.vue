<template>
  <section class="commission-fixture">
    <h2>主管提成树表</h2>
    <CommissionDetailTable :rows="commissionRows" role="second_supervisor" />
  </section>
  <section class="task-fixture">
    <h2>任务树表</h2>
    <TaskTreeView :nodes="taskNodes" :modules-by-key="modules" today="2026-10-04" @open="openedTask = $event" />
    <p data-testid="opened-task">{{ openedTask }}</p>
  </section>
  <pre data-testid="source-snapshot" hidden>{{ JSON.stringify({ commissionRows, taskNodes }) }}</pre>
</template>

<script setup>
import { ref } from 'vue'
import CommissionDetailTable from '../../../src/views/commission/components/CommissionDetailTable.vue'
import TaskTreeView from '../../../src/views/task/components/TaskTreeView.vue'

const openedTask = ref(null)
const commissionRows = [
  { id: 1, collection_date: '2026-01-02', order_name: 'January 10', payment_amount: '10.00', service_fee: '1.00', second_supervisor_rate: '0.10', second_supervisor_commission: '10.00' },
  { id: 2, collection_date: '2026-01-01', order_name: 'January 2', payment_amount: '2.00', service_fee: '0.20', second_supervisor_rate: '0.02', second_supervisor_commission: '2.00' },
  { id: 3, collection_date: '2026-02-02', order_name: 'February 20', payment_amount: '20.00', service_fee: '2.00', second_supervisor_rate: '0.20', second_supervisor_commission: '20.00' },
  { id: 4, collection_date: '2026-02-01', order_name: 'February 100', payment_amount: '100.00', service_fee: '10.00', second_supervisor_rate: '1.00', second_supervisor_commission: '100.00' },
  { id: 5, collection_date: null, order_name: 'Undated 3', payment_amount: '3.00', service_fee: null, second_supervisor_rate: null, second_supervisor_commission: '3.00' },
]
const task = (id, title, due_date, children) => ({ id, title, due_date, priority: 'P2', status: 'todo', module_key: 'commission', ...(children ? { children } : {}) })
const taskNodes = [
  task(10, 'Task 10', '2027-01-01', [
    task(101, 'Child 10', '2027-01-01', [task(1002, 'Grandchild 2', '2026-12-31'), task(1001, 'Grandchild 10', '2027-01-01')]),
    task(102, 'Child 2', '2026-12-31'),
  ]),
  task(2, 'Task 2', '2026-12-31', [task(21, 'Child 10', '2027-01-01'), task(22, 'Child 2', '2026-12-31')]),
]
const modules = { commission: { group_title: '经营', title: '提成' } }
</script>

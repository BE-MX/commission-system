<template>
  <div>
    <div class="form-card">
      <div class="form-card-header">
        <h3>提交设计预约</h3>
        <p>填写拍摄需求信息，提交后将进入审批流程</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="110px"
        label-position="right"
        class="submit-form"
      >
        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="客户名称" prop="customer_name">
              <el-input v-model="form.customer_name" placeholder="请输入客户名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="业务员" prop="salesperson_name">
              <el-input v-model="form.salesperson_name" placeholder="请输入业务员姓名" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="拍摄类型" prop="shoot_type">
              <el-select v-model="form.shoot_type" placeholder="请选择拍摄类型" style="width: 100%">
                <el-option
                  v-for="item in SHOOT_TYPE_OPTIONS"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12" v-if="form.shoot_type === 'other'">
            <el-form-item label="类型备注" prop="shoot_type_remark">
              <el-input v-model="form.shoot_type_remark" placeholder="请说明拍摄类型" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="16">
            <el-form-item label="期望日期" prop="startDate">
              <DatePeriodPicker
                v-model:start-date="form.startDate"
                v-model:start-period="form.startPeriod"
                v-model:end-date="form.endDate"
                v-model:end-period="form.endPeriod"
                :disabled-date="disablePastDate"
                @change="onDateRangeChange"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="优先级" prop="priority">
              <el-radio-group v-model="form.priority">
                <el-radio value="normal">普通</el-radio>
                <el-radio value="urgent">加急</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- Conflict alert -->
        <ConflictAlert
          v-if="conflictResult"
          :conflict-result="conflictResult"
          class="conflict-alert"
        />

        <el-form-item label="备注" prop="remark">
          <el-input
            v-model="form.remark"
            type="textarea"
            :rows="3"
            placeholder="拍摄要求、特殊说明等（选填）"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :icon="Promotion" @click="handleSubmit" :loading="submitting">提交预约</el-button>
          <el-button :icon="RefreshLeft" @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Promotion, RefreshLeft } from '@element-plus/icons-vue'
import { submitRequest, checkConflict, getUnavailableDates } from '@/api/design'
import ConflictAlert from '@/components/design/ConflictAlert.vue'
import DatePeriodPicker from '@/components/design/DatePeriodPicker.vue'

const router = useRouter()
const formRef = ref()
const submitting = ref(false)

const SHOOT_TYPE_OPTIONS = [
  { label: '产品图', value: 'product_photo' },
  { label: '模特图', value: 'model_photo' },
  { label: '视频', value: 'video' },
  { label: '产品视频', value: 'product_video' },
  { label: '其他', value: 'other' },
]

const form = reactive({
  customer_name: '',
  salesperson_name: '',
  shoot_type: '',
  shoot_type_remark: '',
  startDate: '',
  startPeriod: 'am',
  endDate: '',
  endPeriod: 'pm',
  priority: 'normal',
  remark: '',
})

const rules = {
  customer_name: [{ required: true, message: '请输入客户名称', trigger: 'blur' }],
  salesperson_name: [{ required: true, message: '请输入业务员姓名', trigger: 'blur' }],
  shoot_type: [{ required: true, message: '请选择拍摄类型', trigger: 'change' }],
  shoot_type_remark: [{ required: true, message: '请说明拍摄类型', trigger: 'blur',
    validator: (rule, value, callback) => {
      if (form.shoot_type === 'other' && !value) callback(new Error('请说明拍摄类型'))
      else callback()
    }
  }],
  startDate: [{ required: true, message: '请选择期望开始日期', trigger: 'change' }],
  priority: [{ required: true, message: '请选择优先级', trigger: 'change' }],
}

const conflictResult = ref(null)
const unavailableDateSet = ref(new Set())

function disablePastDate(date) {
  if (date < new Date(new Date().setHours(0, 0, 0, 0))) return true
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return unavailableDateSet.value.has(`${y}-${m}-${d}`)
}

async function fetchUnavailableDates() {
  try {
    const res = await getUnavailableDates()
    const dates = res.data || []
    unavailableDateSet.value = new Set(dates.map(d => typeof d === 'string' ? d : d.date))
  } catch {
    // ignore
  }
}

onMounted(() => {
  fetchUnavailableDates()
})

let conflictTimer = null
function onDateRangeChange(val) {
  clearTimeout(conflictTimer)
  conflictResult.value = null
  if (!val || !val.startDate || !val.endDate) return
  conflictTimer = setTimeout(() => {
    doConflictCheck(val.startDate, val.endDate, val.startPeriod, val.endPeriod)
  }, 300)
}

async function doConflictCheck(start, end, startPeriod, endPeriod) {
  try {
    const res = await checkConflict({
      start_date: start,
      end_date: end,
      start_period: startPeriod || 'am',
      end_period: endPeriod || 'pm',
      shoot_type: form.shoot_type || undefined,
    })
    const data = res.data
    conflictResult.value = {
      has_conflict: data.has_conflict || data.has_unavailable || false,
      unavailable_dates: data.unavailable_dates || [],
      overloaded_dates: data.overloaded_dates || [],
      route: data.route || null,
    }
  } catch {
    // ignore conflict check error
  }
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = {
      customer_name: form.customer_name,
      salesperson_name: form.salesperson_name,
      salesperson_id: 1,
      shoot_type: form.shoot_type,
      shoot_type_remark: form.shoot_type === 'other' ? form.shoot_type_remark : '',
      expect_start_date: form.startDate,
      expect_start_period: form.startPeriod,
      expect_end_date: form.endDate,
      expect_end_period: form.endPeriod,
      priority: form.priority,
      remark: form.remark,
      operator_id: 1,
      operator_name: form.salesperson_name || '业务员',
      operator_role: 'salesperson',
    }
    await submitRequest(payload)
    ElMessage.success('预约提交成功，等待审批')
    router.push('/design/my-requests')
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  formRef.value?.resetFields()
  conflictResult.value = null
}
</script>

<style scoped>
.form-card {
  background: #fff;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  overflow: hidden;
}
.form-card-header {
  background: linear-gradient(135deg, #141210 0%, #1E1B18 60%, #141210 100%);
  padding: 24px 32px;
  color: #fff;
}
.form-card-header h3 {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 700;
  font-family: var(--font-display);
}
.form-card-header p {
  margin: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
}
.submit-form {
  padding: 28px 32px;
  max-width: 900px;
}
.conflict-alert {
  margin-bottom: 18px;
}
</style>

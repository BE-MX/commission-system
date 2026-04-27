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
          <el-col :span="12">
            <el-form-item label="期望日期" prop="dateRange">
              <el-date-picker
                v-model="form.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                value-format="YYYY-MM-DD"
                :disabled-date="disablePastDate"
                style="width: 100%"
                @change="onDateRangeChange"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级" prop="priority">
              <el-radio-group v-model="form.priority">
                <el-radio value="normal">普通</el-radio>
                <el-radio value="urgent">加急</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- Conflict alert -->
        <el-alert
          v-if="conflictInfo.hasConflict"
          :title="conflictInfo.title"
          :type="conflictInfo.type"
          :description="conflictInfo.description"
          show-icon
          :closable="false"
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
          <el-button type="primary" @click="handleSubmit" :loading="submitting">提交预约</el-button>
          <el-button @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { submitRequest, checkConflict } from '@/api/design'

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
  dateRange: null,
  priority: 'normal',
  remark: '',
})

const rules = {
  customer_name: [{ required: true, message: '请输入客户名称', trigger: 'blur' }],
  salesperson_name: [{ required: true, message: '请输入业务员姓名', trigger: 'blur' }],
  shoot_type: [{ required: true, message: '请选择拍摄类型', trigger: 'change' }],
  shoot_type_remark: [{ required: true, message: '请说明拍摄类型', trigger: 'blur' }],
  dateRange: [{ required: true, message: '请选择期望日期范围', trigger: 'change' }],
  priority: [{ required: true, message: '请选择优先级', trigger: 'change' }],
}

const conflictInfo = reactive({
  hasConflict: false,
  type: 'warning',
  title: '',
  description: '',
})

function disablePastDate(date) {
  return date < new Date(new Date().setHours(0, 0, 0, 0))
}

let conflictTimer = null
function onDateRangeChange(val) {
  clearTimeout(conflictTimer)
  conflictInfo.hasConflict = false
  if (!val || val.length !== 2) return
  conflictTimer = setTimeout(() => {
    doConflictCheck(val[0], val[1])
  }, 300)
}

async function doConflictCheck(start, end) {
  try {
    const res = await checkConflict({
      start_date: start,
      end_date: end,
      shoot_type: form.shoot_type || undefined,
    })
    const data = res.data
    if (data.has_unavailable) {
      conflictInfo.hasConflict = true
      conflictInfo.type = 'error'
      conflictInfo.title = '日期冲突'
      conflictInfo.description = `以下日期不可用：${data.unavailable_dates?.join('、') || '存在不可用日期'}`
    } else if (data.has_conflict) {
      conflictInfo.hasConflict = true
      conflictInfo.type = 'warning'
      conflictInfo.title = '排期拥挤'
      conflictInfo.description = data.message || '该时段已有较多预约，建议调整日期'
    } else {
      conflictInfo.hasConflict = false
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
      expect_start_date: form.dateRange[0],
      expect_end_date: form.dateRange[1],
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
  conflictInfo.hasConflict = false
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

<template>
  <div>
    <div class="form-card">
      <div class="form-card-header">
        <h3>提交设计预约</h3>
        <p>填写拍摄需求信息，日期无冲突时直接进入排期，有冲突时进入审批流程</p>
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
            <el-form-item label="客户等级" prop="customer_level">
              <el-select v-model="form.customer_level" placeholder="请选择客户等级" style="width: 100%" clearable>
                <el-option
                  v-for="item in customerLevelOptions"
                  :key="item.code"
                  :label="item.label"
                  :value="item.code"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="12">
            <el-form-item label="业务员" prop="salesperson_name">
              <el-input v-model="form.salesperson_name" placeholder="请输入业务员姓名" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="拍摄类型" prop="shoot_type">
              <el-select
                v-model="form.shoot_type"
                placeholder="请选择拍摄类型"
                style="width: 100%"
                multiple
                collapse-tags
                collapse-tags-tooltip
              >
                <el-option
                  v-for="item in shootTypeOptions"
                  :key="item.code"
                  :label="item.label"
                  :value="item.code"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="24">
          <el-col :span="24" v-if="form.shoot_type.includes('other')">
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

        <el-form-item label="附件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :file-list="fileList"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :limit="10"
            :on-exceed="() => ElMessage.warning('最多上传 10 个附件')"
            multiple
            accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar"
          >
            <GlassButton :icon="UploadFilled">选择文件</GlassButton>
            <template #tip>
              <div class="upload-tip">支持图片、文档、压缩包等，单个文件不超过 20MB，最多 10 个</div>
            </template>
          </el-upload>
        </el-form-item>

        <el-form-item>
          <GlassButton variant="primary" :icon="Promotion" @click="handleSubmit" :loading="submitting">提交预约</GlassButton>
          <GlassButton :icon="RefreshLeft" @click="resetForm">重置</GlassButton>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Promotion, RefreshLeft, UploadFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { submitRequest, checkConflict, getUnavailableDates, uploadAttachment } from '@/api/design'
import { getDictItems } from '@/api/system'
import ConflictAlert from '@/components/design/ConflictAlert.vue'
import DatePeriodPicker from '@/components/design/DatePeriodPicker.vue'

const router = useRouter()
const authStore = useAuthStore()
const formRef = ref()
const submitting = ref(false)
const uploadRef = ref()
const fileList = ref([])

const shootTypeOptions = ref([])
const customerLevelOptions = ref([])

const form = reactive({
  customer_name: '',
  customer_level: '',
  salesperson_name: authStore.user?.real_name || authStore.user?.username || '',
  shoot_type: [],
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
  shoot_type: [
    { required: true, message: '请选择拍摄类型', trigger: 'change' },
    {
      validator: (rule, value, callback) => {
        if (!Array.isArray(value) || value.length === 0) callback(new Error('请选择拍摄类型'))
        else callback()
      }, trigger: 'change',
    },
  ],
  shoot_type_remark: [
    { required: true, message: '请说明拍摄类型', trigger: 'blur',
      validator: (rule, value, callback) => {
        if (form.shoot_type.includes('other') && !value) callback(new Error('请说明拍摄类型'))
        else callback()
      }
    }
  ],
  startDate: [{ required: true, message: '请选择期望开始日期', trigger: 'change' }],
  priority: [{ required: true, message: '请选择优先级', trigger: 'change' }],
}

const conflictResult = ref(null)
// Key: "YYYY-MM-DD" (full day disabled) or "YYYY-MM-DD_am" / "YYYY-MM-DD_pm" (half-day)
const unavailableDateSet = ref(new Set())

function disablePastDate(date) {
  if (date < new Date(new Date().setHours(0, 0, 0, 0))) return true
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const key = `${y}-${m}-${d}`
  // Disable the whole day only when there is a full-day record (period=null)
  // or both am and pm records exist for the same date
  return (
    unavailableDateSet.value.has(key) ||
    (unavailableDateSet.value.has(`${key}_am`) && unavailableDateSet.value.has(`${key}_pm`))
  )
}

async function fetchUnavailableDates() {
  try {
    const res = await getUnavailableDates()
    const dates = res.data || []
    const s = new Set()
    for (const item of dates) {
      const dateStr = typeof item === 'string' ? item : item.date
      const period = typeof item === 'object' ? item.period : null
      if (!period) {
        // Full-day unavailable → add plain date key
        s.add(dateStr)
      } else {
        // Half-day unavailable → add period-specific key
        s.add(`${dateStr}_${period}`)
      }
    }
    unavailableDateSet.value = s
  } catch {
    // ignore
  }
}

async function loadDicts() {
  try {
    const [stRes, clRes] = await Promise.all([
      getDictItems('shoot_type', true),
      getDictItems('customer_level', true),
    ])
    shootTypeOptions.value = stRes.data || []
    customerLevelOptions.value = clRes.data || []
  } catch {
    // ignore
  }
}

onMounted(() => {
  fetchUnavailableDates()
  loadDicts()
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
      shoot_type: form.shoot_type.join(',') || undefined,
    })
    const data = res.data
    const hasUnavailable = (data.unavailable_dates?.length > 0 || data.conflicting_unavailable_slots?.length > 0)
    conflictResult.value = {
      has_conflict: data.has_conflict || hasUnavailable || false,
      unavailable_dates: data.unavailable_dates || [],
      conflicting_unavailable_slots: data.conflicting_unavailable_slots || [],
      overloaded_dates: data.overloaded_dates || [],
      route: data.route || null,
    }
  } catch {
    // ignore conflict check error
  }
}

function handleFileChange(file, uploadFiles) {
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.warning('文件大小不能超过 20MB')
    uploadFiles.splice(uploadFiles.indexOf(file), 1)
    return
  }
  fileList.value = uploadFiles
}

function handleFileRemove(file, uploadFiles) {
  fileList.value = uploadFiles
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    const payload = {
      customer_name: form.customer_name,
      customer_level: form.customer_level || undefined,
      salesperson_name: form.salesperson_name,
      salesperson_id: authStore.user?.id || 1,
      shoot_type: form.shoot_type.join(','),
      shoot_type_remark: form.shoot_type.includes('other') ? form.shoot_type_remark : '',
      expect_start_date: form.startDate,
      expect_start_period: form.startPeriod,
      expect_end_date: form.endDate,
      expect_end_period: form.endPeriod,
      priority: form.priority,
      remark: form.remark,
      operator_id: authStore.user?.id || 1,
      operator_name: form.salesperson_name || '业务员',
      operator_role: 'salesperson',
    }
    const res = await submitRequest(payload)
    const requestId = res.data?.id

    // 上传附件（如果有）
    if (requestId && fileList.value.length > 0) {
      let uploadOk = 0
      for (const f of fileList.value) {
        try {
          await uploadAttachment(requestId, f.raw, {
            operator_id: authStore.user?.id || 1,
            operator_name: form.salesperson_name || '业务员',
          })
          uploadOk++
        } catch {
          // 单个附件失败不阻断
        }
      }
      if (uploadOk < fileList.value.length) {
        ElMessage.warning(`${fileList.value.length - uploadOk} 个附件上传失败，请稍后在详情中补传`)
      }
    }

    const hasConflict = conflictResult.value?.has_conflict
    if (hasConflict) {
      ElMessage.success('预约提交成功，存在排期冲突，等待审批')
    } else {
      ElMessage.success('预约提交成功，已进入排期流程')
    }
    router.push('/design/my-requests')
  } finally {
    submitting.value = false
  }
}

function resetForm() {
  formRef.value?.resetFields()
  conflictResult.value = null
  fileList.value = []
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
.upload-tip {
  font-size: 12px;
  color: var(--text-secondary, #999);
  margin-top: 4px;
}
</style>

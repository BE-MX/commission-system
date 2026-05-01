<template>
  <div class="profile-page">
    <!-- 基本信息 -->
    <el-card shadow="never" class="profile-card">
      <template #header>
        <div class="card-header">基本信息</div>
      </template>
      <el-form :model="profileForm" label-width="80px" style="max-width: 480px">
        <el-form-item label="用户名">
          <el-input :model-value="profileForm.username" disabled />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="profileForm.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="profileForm.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="profileForm.phone" placeholder="选填" />
        </el-form-item>
        <el-form-item>
          <GlassButton variant="primary" :loading="savingProfile" @click="submitProfile" left-icon="Check">
            保存资料
          </GlassButton>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 修改密码 -->
    <el-card shadow="never" class="profile-card">
      <template #header>
        <div class="card-header">修改密码</div>
      </template>
      <el-form :model="pwdForm" label-width="100px" style="max-width: 480px">
        <el-form-item label="当前密码">
          <el-input v-model="pwdForm.old_password" type="password" placeholder="输入当前密码" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" placeholder="至少 6 位" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwdForm.confirm_password" type="password" placeholder="再次输入新密码" show-password />
        </el-form-item>
        <el-form-item>
          <GlassButton variant="primary" :loading="savingPwd" @click="submitPassword" left-icon="Key">
            确认修改
          </GlassButton>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { updateProfile, changePassword } from '@/api/userManagement'

const authStore = useAuthStore()

// ── 基本信息 ────────────────────────────────────────
const profileForm = ref({ username: '', real_name: '', email: '', phone: '' })
const savingProfile = ref(false)

function loadProfile() {
  const user = authStore.user || {}
  profileForm.value = {
    username: user.username || '',
    real_name: user.real_name || '',
    email: user.email || '',
    phone: user.phone || '',
  }
}

async function submitProfile() {
  if (!profileForm.value.real_name) {
    ElMessage.warning('请填写姓名')
    return
  }
  savingProfile.value = true
  try {
    await updateProfile({
      real_name: profileForm.value.real_name,
      email: profileForm.value.email || null,
      phone: profileForm.value.phone || null,
    })
    ElMessage.success('资料已更新')
    // 刷新 store 中的用户信息
    await authStore.fetchMe()
    loadProfile()
  } catch {
    // handled by interceptor
  } finally {
    savingProfile.value = false
  }
}

// ── 修改密码 ────────────────────────────────────────
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const savingPwd = ref(false)

async function submitPassword() {
  if (!pwdForm.value.old_password) {
    ElMessage.warning('请输入当前密码')
    return
  }
  if (!pwdForm.value.new_password || pwdForm.value.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.value.new_password !== pwdForm.value.confirm_password) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  savingPwd.value = true
  try {
    await changePassword({
      old_password: pwdForm.value.old_password,
      new_password: pwdForm.value.new_password,
    })
    ElMessage.success('密码已修改，下次登录请使用新密码')
    pwdForm.value = { old_password: '', new_password: '', confirm_password: '' }
  } catch {
    // handled by interceptor
  } finally {
    savingPwd.value = false
  }
}

onMounted(() => {
  authStore.fetchMe().then(loadProfile).catch(loadProfile)
})
</script>

<style scoped>
.profile-page {
  max-width: 560px;
}
.profile-card {
  margin-bottom: 20px;
}
.card-header {
  font-weight: 600;
  font-size: 15px;
}
</style>

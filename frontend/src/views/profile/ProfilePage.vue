<template>
  <div class="profile-page">
    <!-- 头像 -->
    <el-card shadow="never" class="profile-card">
      <template #header>
        <div class="card-header">头像</div>
      </template>
      <div class="avatar-section">
        <el-upload
          class="avatar-uploader"
          action=""
          :auto-upload="false"
          :show-file-list="false"
          :on-change="handleAvatarChange"
          accept="image/*"
        >
          <div v-if="avatarPreview" class="avatar-preview">
            <img :src="avatarPreview" alt="avatar" />
          </div>
          <div v-else class="avatar-placeholder">
            <el-icon><Plus /></el-icon>
            <span>点击上传</span>
          </div>
          <div v-if="avatarLoading" class="avatar-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
          </div>
        </el-upload>
        <p class="avatar-hint">支持 JPG、PNG、GIF、WebP，最大 2MB</p>
      </div>
    </el-card>

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
import { updateProfile, changePassword, uploadAvatar } from '@/api/userManagement'
import { Plus } from '@element-plus/icons-vue'

const authStore = useAuthStore()

// ── 头像 ────────────────────────────────────────────
const avatarLoading = ref(false)
const avatarPreview = ref('')

function loadAvatar() {
  avatarPreview.value = authStore.user?.avatar_url || ''
}

async function handleAvatarChange(file) {
  const isImage = file.raw.type.startsWith('image/')
  const isLt2M = file.raw.size / 1024 / 1024 < 2
  if (!isImage) {
    ElMessage.error('请上传图片文件')
    return
  }
  if (!isLt2M) {
    ElMessage.error('图片大小不能超过 2MB')
    return
  }
  avatarLoading.value = true
  try {
    const res = await uploadAvatar(file.raw)
    avatarPreview.value = res.data?.avatar_url || ''
    await authStore.fetchMe()
    loadAvatar()
    ElMessage.success('头像上传成功')
  } catch {
    // handled by interceptor
  } finally {
    avatarLoading.value = false
  }
}

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
  loadAvatar()
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
      avatar_url: avatarPreview.value || null,
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

/* 头像上传 */
.avatar-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.avatar-uploader :deep(.el-upload) {
  cursor: pointer;
  position: relative;
  overflow: hidden;
}

.avatar-preview {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid var(--border-color);
  transition: all 0.25s ease;
}
.avatar-preview:hover {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px var(--color-primary-light);
}
.avatar-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-placeholder {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  border: 2px dashed var(--border-color);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: var(--text-muted);
  transition: all 0.25s ease;
}
.avatar-placeholder:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.avatar-placeholder .el-icon {
  font-size: 24px;
}
.avatar-placeholder span {
  font-size: 12px;
}

.avatar-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 50%;
  font-size: 24px;
  color: var(--color-primary);
}

.avatar-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
}
</style>

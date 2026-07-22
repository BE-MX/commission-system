/**
 * 培训速递编辑器（四步向导）全部 state + 方法（500 行红线：主文件留薄壳）
 * 步骤：① 基本信息 → ② 丢材料 + AI 提炼 → ③ 逐区校对 → ④ 预览发布
 * 强引导：★分区客户端校验与后端 validate_for_publish 同一套阈值，不过不给发。
 */
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createDigest, getDigest, updateDigest, uploadDigestFile, deleteDigestFile,
  updateDigestFileMeta, inferFileType, generateDraft, publishDigest,
} from '@/api/training'
import { msgSuccess, msgError, confirmDanger } from '@/utils/feedback'

// 与后端 draft_service.ROLE_OPTIONS / service 校验阈值保持同一口径
export const ROLE_OPTIONS = ['业务/销售', '电商运营', '设计', '生产', '管理层', 'AI/技术', '全员']
export const TAG_SUGGESTIONS = [
  'TikTok', '亚马逊', 'Temu', '独立站', 'AI 工具', '投流广告', '选品', '素材制作', '直播', '客服话术',
]
export const MIN_HIGHLIGHTS = 3
export const MAX_HIGHLIGHTS = 5
export const MIN_REVIEW_CHARS = 15
export const MAX_SUMMARY_CHARS = 100

const STEP_TITLES = ['基本信息', '丢材料 · AI 提炼', '逐区校对', '预览发布']

export function useTrainingEditor() {
  const route = useRoute()
  const router = useRouter()

  const digestId = ref(route.params.id ? Number(route.params.id) : null)
  const step = ref(1)
  const status = ref('draft')
  const loading = ref(false)
  const saving = ref(false)
  const drafting = ref(false)
  const publishing = ref(false)
  const draftDone = ref(false)

  const basic = reactive({
    title: '',
    org: '',
    lecturer: '',
    trained_at: new Date().toISOString().slice(0, 10),
    attendees: [],
    tags: [],
  })
  const summary = ref('')
  const sections = reactive({
    highlights: [],
    new_insights: [],
    applications: [],
    methods: [],
    review: '',
  })
  const files = ref([]) // [{id, file_name, file_size, mime_type, file_type, remark}]
  const textMaterials = ref('')
  // 上传栏批次选择：类型默认按扩展名自动识别，可整批覆盖；备注整批套用
  const attach = reactive({ fileType: 'auto', remark: '' })

  // ---------- 校验（与后端同口径，发布按钮的唯一开关） ----------
  const step1Problems = computed(() => {
    const p = []
    if (!basic.title.trim()) p.push('培训名称未填写')
    if (!basic.trained_at) p.push('培训日期未选择')
    return p
  })

  const publishProblems = computed(() => {
    const p = []
    const s = summary.value.trim()
    if (!s) p.push('「一句话总结」未填写')
    else if (s.length > MAX_SUMMARY_CHARS) p.push(`「一句话总结」超过 ${MAX_SUMMARY_CHARS} 字`)

    const hl = sections.highlights.filter(h => h.title.trim())
    if (hl.length < MIN_HIGHLIGHTS) p.push(`「重点」至少 ${MIN_HIGHLIGHTS} 条（当前 ${hl.length} 条）`)
    else if (hl.length > MAX_HIGHLIGHTS) p.push(`「重点」最多 ${MAX_HIGHLIGHTS} 条`)

    const apps = sections.applications.filter(a => a.point.trim())
    if (!apps.length) p.push('「可应用点」至少 1 条')
    apps.forEach((a, i) => {
      if (!a.roles.length) p.push(`「可应用点」第 ${i + 1} 条未选适用岗位`)
      if (!a.first_step.trim()) p.push(`「可应用点」第 ${i + 1} 条未写落地第一步`)
    })

    if (sections.review.trim().length < MIN_REVIEW_CHARS) {
      p.push(`「参训人点评」至少 ${MIN_REVIEW_CHARS} 字（AI 不代写，这是你的判断）`)
    }
    return [...step1Problems.value, ...p]
  })

  // ---------- 数据往返 ----------
  function fillFrom(data) {
    status.value = data.status
    basic.title = data.title || ''
    basic.org = data.org || ''
    basic.lecturer = data.lecturer || ''
    basic.trained_at = data.trained_at || basic.trained_at
    basic.attendees = data.attendees || []
    basic.tags = data.tags || []
    summary.value = data.summary || ''
    Object.assign(sections, {
      highlights: data.sections?.highlights || [],
      new_insights: data.sections?.new_insights || [],
      applications: data.sections?.applications || [],
      methods: data.sections?.methods || [],
      review: data.sections?.review || '',
    })
    files.value = data.files || []
    files.value.forEach(rememberFileMeta)
  }

  async function load() {
    if (!digestId.value) return
    loading.value = true
    try {
      const res = await getDigest(digestId.value)
      if (!res.data.can_edit) {
        msgError('这条速递只有发布人本人或管理员可以编辑')
        router.replace(`/training/digests/${digestId.value}`)
        return
      }
      fillFrom(res.data)
      if (sections.highlights.length || summary.value) draftDone.value = true
    } finally {
      loading.value = false
    }
  }

  function payload() {
    return {
      title: basic.title.trim(),
      org: basic.org.trim(),
      lecturer: basic.lecturer.trim(),
      trained_at: basic.trained_at,
      attendees: basic.attendees,
      tags: basic.tags,
      summary: summary.value,
      sections: {
        highlights: sections.highlights.filter(h => h.title.trim()),
        new_insights: sections.new_insights.filter(s => s.trim()),
        applications: sections.applications.filter(a => a.point.trim()),
        methods: sections.methods.filter(m => m.name.trim()),
        review: sections.review,
      },
    }
  }

  /** 步骤 1 完成时创建草稿（拿 id 才能传附件）；已存在则保存基本信息 */
  async function ensureCreated() {
    if (digestId.value) {
      await updateDigest(digestId.value, payload())
      return digestId.value
    }
    const res = await createDigest({
      title: basic.title.trim(),
      org: basic.org.trim(),
      lecturer: basic.lecturer.trim(),
      trained_at: basic.trained_at,
      attendees: basic.attendees,
      tags: basic.tags,
    })
    digestId.value = res.data.id
    // 换成编辑路由，刷新/回退不丢草稿
    router.replace(`/training/digests/${digestId.value}/edit`)
    return digestId.value
  }

  async function saveDraft(silent = false) {
    if (step1Problems.value.length) {
      msgError(step1Problems.value[0])
      step.value = 1
      return false
    }
    saving.value = true
    try {
      await ensureCreated()
      if (!silent) msgSuccess('草稿保存')
      return true
    } finally {
      saving.value = false
    }
  }

  async function nextStep() {
    if (step.value === 1) {
      if (step1Problems.value.length) {
        msgError(step1Problems.value[0])
        return
      }
      saving.value = true
      try {
        await ensureCreated()
      } finally {
        saving.value = false
      }
    }
    if (step.value < 4) step.value += 1
  }

  function prevStep() {
    if (step.value > 1) step.value -= 1
  }

  // ---------- 附件（AppUpload 注入式契约，页面自渲染富列表 show-list=false） ----------
  async function uploadFn(file, onProgress) {
    const id = await ensureCreated()
    const res = await uploadDigestFile(id, file, {
      fileType: attach.fileType === 'auto' ? inferFileType(file.name) : attach.fileType,
      remark: attach.remark,
      onProgress,
    })
    files.value = [...files.value, res.data]
    rememberFileMeta(res.data)
    return { path: String(res.data.id), url: '', name: res.data.file_name }
  }

  // 只读映射：给 AppUpload 做数量上限判断；增删都走 uploadFn / removeFile，
  // 不走 v-model 回写（多选并发上传时 emit 的快照是旧数组，回写会误删刚传完的文件）
  const filesModel = computed(() => files.value.map(f => ({ path: String(f.id), url: '', name: f.file_name })))

  async function removeFile(f) {
    try {
      await confirmDanger('删除', `附件 ${f.file_name}`)
    } catch {
      return
    }
    await deleteDigestFile(f.id)
    files.value = files.value.filter(x => x.id !== f.id)
    msgSuccess('删除')
  }

  // 行内输入框 v-model 直接改行对象，这里存"最后保存成功"的快照供失败回滚
  const savedFileMeta = new Map()
  function rememberFileMeta(f) {
    savedFileMeta.set(f.id, { file_type: f.file_type ?? null, remark: f.remark ?? null })
  }

  /** 行内改类型/备注，成功以后端返回值为准（备注去空白等）；失败回滚显示值，不让 UI 冒充已保存 */
  async function saveFileMeta(f, patch) {
    try {
      const res = await updateDigestFileMeta(f.id, patch)
      files.value = files.value.map(x => (x.id === f.id ? { ...x, ...res.data } : x))
      rememberFileMeta(res.data)
    } catch {
      // 拦截器已弹错误提示，这里只负责把行内值恢复成最后保存成功的状态
      const before = savedFileMeta.get(f.id)
      if (before) files.value = files.value.map(x => (x.id === f.id ? { ...x, ...before } : x))
    }
  }

  // ---------- AI 提炼 ----------
  const hasDraftContent = computed(
    () => Boolean(summary.value.trim()) || sections.highlights.length > 0,
  )

  async function runDraft() {
    if (!textMaterials.value.trim() && !files.value.length) {
      msgError('先粘贴文字笔记，或上传现场照片 / PDF，AI 才有料可提')
      return
    }
    if (hasDraftContent.value) {
      try {
        await ElMessageBox.confirm(
          'AI 草稿将覆盖已填写的「总结 / 重点 / 亮点 / 可应用点 / 方法」，「参训人点评」不受影响。继续？',
          '覆盖确认',
          { confirmButtonText: '覆盖生成', cancelButtonText: '取消', type: 'warning' },
        )
      } catch {
        return
      }
    }
    drafting.value = true
    try {
      const id = await ensureCreated()
      const res = await generateDraft(id, textMaterials.value)
      const d = res.data || {}
      summary.value = d.summary || ''
      sections.highlights = d.highlights || []
      sections.new_insights = d.new_insights || []
      sections.applications = d.applications || []
      sections.methods = d.methods || []
      draftDone.value = true
      // 立即静默落库：AI 结果只在内存的话，关页即丢、token 白烧
      try {
        await updateDigest(id, payload())
      } catch { /* 保存失败拦截器已提示，不阻断进入校对 */ }
      msgSuccess('AI 草稿生成')
      step.value = 3
    } finally {
      drafting.value = false
    }
  }

  // ---------- 分区条目增删 ----------
  const addHighlight = () => sections.highlights.push({ title: '', detail: '' })
  const addInsight = () => sections.new_insights.push('')
  const addApplication = () => sections.applications.push({ point: '', roles: [], first_step: '' })
  const addMethod = () => sections.methods.push({ name: '', steps: '' })
  const removeAt = (list, i) => list.splice(i, 1)

  // ---------- 发布 ----------
  async function publish() {
    if (publishProblems.value.length) {
      msgError('还差一点：' + publishProblems.value[0])
      return
    }
    publishing.value = true
    try {
      await ensureCreated()
      const res = await publishDigest(digestId.value)
      // 用后端 message：推送失败时会指路"可在详情页重推"
      ElMessage.success(res.message || '已发布')
      router.replace(`/training/digests/${digestId.value}`)
    } finally {
      publishing.value = false
    }
  }

  return {
    STEP_TITLES, ROLE_OPTIONS, TAG_SUGGESTIONS,
    MIN_HIGHLIGHTS, MAX_HIGHLIGHTS, MIN_REVIEW_CHARS, MAX_SUMMARY_CHARS,
    digestId, step, status, loading, saving, drafting, publishing, draftDone,
    basic, summary, sections, files, textMaterials, filesModel, attach,
    step1Problems, publishProblems, hasDraftContent,
    load, saveDraft, nextStep, prevStep, uploadFn, removeFile, saveFileMeta, runDraft, publish,
    addHighlight, addInsight, addApplication, addMethod, removeAt,
  }
}

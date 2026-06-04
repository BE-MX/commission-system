/**
 * Stimulsoft Reports.JS 动态加载 composable
 *
 * 职责：
 * 1. 按需加载 Stimulsoft JS（仅访问报表页时触发）
 * 2. 设置中文本地化
 * 3. 暴露 createViewer 方法
 *
 * 使用方式：
 *   const { ready, error, createViewer } = useStimulsoft()
 *   await createViewer(containerEl, report, options)
 */
import { ref } from 'vue'

const SCRIPTS_BASE = '/vendor/stimulsoft/reports-js'

// 使用非 pack 版本（Demo/scripts/），包含 License 校验逻辑
const VIEWER_SCRIPTS = [
  `${SCRIPTS_BASE}/stimulsoft.reports.js`,
  `${SCRIPTS_BASE}/stimulsoft.viewer.js`,
]

const DESIGNER_SCRIPTS = [
  `${SCRIPTS_BASE}/stimulsoft.designer.js`,
  `${SCRIPTS_BASE}/stimulsoft.blockly.editor.js`,
]

// 可选：导出和图表（pack 版本无 License 校验）
const OPTIONAL_SCRIPTS = [
  `${SCRIPTS_BASE}/stimulsoft.reports.export.pack.js`,
  `${SCRIPTS_BASE}/stimulsoft.reports.chart.pack.js`,
]

// 模块级状态：所有调用者共享同一份加载状态
let _loadPromise = null
let _designerLoaded = false
const _loaded = ref(false)
const _error = ref(null)

function _loadScript(src) {
  return new Promise((resolve, reject) => {
    // 如果已经存在同 src 的 script 标签，直接跳过
    const existing = document.querySelector(`script[src="${src}"]`)
    if (existing) {
      resolve()
      return
    }
    const script = document.createElement('script')
    script.src = src
    script.onload = resolve
    script.onerror = () => reject(new Error(`加载脚本失败: ${src}`))
    document.head.appendChild(script)
  })
}

async function _ensureLoaded() {
  if (_loaded.value) return
  if (_loadPromise) {
    await _loadPromise
    return
  }

  _loadPromise = (async () => {
    try {
      // 按顺序加载核心 + Viewer 脚本
      for (const src of VIEWER_SCRIPTS) {
        await _loadScript(src)
      }

      // 加载可选模块（export/chart）
      for (const src of OPTIONAL_SCRIPTS) {
        await _loadScript(src)
      }

      // 激活授权 + 中文本地化
      if (window.Stimulsoft) {
        window.Stimulsoft.Base.StiLicense.Key = '6vJhGtLLLz2GNviWmUTrhSqnOItdDwjBylQzQcAOiHk7L+DpBomizhxktwUA2MAnr05hFS2qQbKbL1AvbLDq1K4WK7MQeS9/r7ykAs+ftpEX5J1AsOg8tuvYE/mtCwO8YA8aeiWWL7DqfXtT7TmviwrzzNPAG6/nDWkvZiA6KgB50tg/P2pfu5OHN4OKAZ9hLi7d/mV6K+/JpN1zkhr/xn0bDoZEmjXHYufPYqIE754rvlQx/aWCM0PbApDJzU9iswYUuKM0l2GRDmjX/DtSrLTx5c0/8bgGhIgVlOdH4Hz9vqv62RwzEXK88J9F1+UML/uFApZXqoS4BW8dKfM6fJiD2Kno1ImC5YbJbfJ8hY3gs+t9JzdWQKqppa7N88mXIhzi91Uv9J86QhemD1tdxQR56ZKsSBxznUg4OcL0MrKWAJvyCaZn6jM0Y85VhtGFCncwAkAchGgxu6AFKlL7WLNL9EttxueXYENmEhqaRSGygCUMEDq9HpfL2H73/hzRxkBCypqGvZbZfVQdhoeLKKE56iXrhjB1dsdi2G/J73o4tHgMmVsG1Bli/E/wUY65QrxYUJaN7txvmVjSoUakexUM+AKXAjRWgsErLtmpT2ZtbX2oMuNYD0xlVrx+24/iHMO8FEQkuNMAOB3Ao+PAPzK4mebJ1G8ItUeE4BlctYY='
        window.Stimulsoft.Base.Localization.StiLocalization.setLocalizationFile(
          `${SCRIPTS_BASE}/localization/zh-CHS.xml`,
        )
      }

      _loaded.value = true
    } catch (e) {
      _error.value = e.message
      _loadPromise = null
      throw e
    }
  })()

  await _loadPromise
}

async function _ensureDesignerLoaded() {
  await _ensureLoaded()
  if (_designerLoaded) return

  // 额外加载 Designer 脚本
  for (const src of DESIGNER_SCRIPTS) {
    await _loadScript(src)
  }
  _designerLoaded = true
}

export function useStimulsoft() {
  const loading = ref(!_loaded.value)
  const error = ref(_error.value)

  /**
   * 创建 Stimulsoft Viewer 并挂载到指定 DOM 元素
   *
   * @param {HTMLElement} containerEl - 挂载容器
   * @param {object} report - 已加载的 StiReport 实例
   * @param {object} [viewerOptions] - 可选 Viewer 配置
   * @returns {object} viewer 实例
   */
  async function createViewer(containerEl, report, viewerOptions = {}) {
    loading.value = true
    error.value = null

    try {
      await _ensureLoaded()

      const Stimulsoft = window.Stimulsoft

      const options = new Stimulsoft.Viewer.StiViewerOptions()

      // 基础配置
      options.height = '100%'
      options.appearance.scrollbarsMode = true
      options.appearance.theme = Stimulsoft.Viewer.StiViewerTheme.Office2013WhiteBlue

      // 工具栏配置
      options.toolbar.showDesignButton = false
      options.toolbar.printDestination = Stimulsoft.Viewer.StiPrintDestination.Direct

      // 导出配置
      options.exports.showExportToPdf = true
      options.exports.showExportToExcel2007 = true
      options.exports.showExportToCsv = false

      // 允许外部覆盖
      if (viewerOptions && typeof viewerOptions === 'object') {
        Object.keys(viewerOptions).forEach(key => {
          try {
            const keys = key.split('.')
            let target = options
            for (let i = 0; i < keys.length - 1; i++) {
              target = target[keys[i]]
            }
            target[keys[keys.length - 1]] = viewerOptions[key]
          } catch {
            // 忽略无效的配置路径
          }
        })
      }

      // 创建 Viewer 实例（第三个参数 false = 不自动渲染，手动控制）
      const viewer = new Stimulsoft.Viewer.StiViewer(options, 'StiViewer_' + Date.now(), false)

      // 先渲染 DOM，再赋值 report（赋值会触发 renderAsync2）
      containerEl.innerHTML = ''
      viewer.renderHtml(containerEl)

      // 赋值 report 触发内部渲染（包含 setTimeout + renderAsync2，不 await 也不会阻塞）
      viewer.report = report

      loading.value = false
      return viewer
    } catch (e) {
      error.value = e.message
      loading.value = false
      throw e
    }
  }

  /**
   * 创建 Stimulsoft Designer 并挂载到指定 DOM 元素
   *
   * @param {HTMLElement} containerEl - 挂载容器
   * @param {string|null} mrtContent - .mrt 模板 JSON 字符串（null 则创建空报表）
   * @param {function} onSave - 保存回调，参数为 .mrt JSON 字符串
   * @param {object} [sampleParams] - 样例数据查询参数，用于注入字典树字段结构
   * @param {string} [reportCode] - 报表编码，用于加载样例数据
   * @returns {object} designer 实例
   */
  async function createDesigner(containerEl, mrtContent, onSave, sampleParams, reportCode) {
    loading.value = true
    error.value = null

    try {
      await _ensureDesignerLoaded()

      const Stimulsoft = window.Stimulsoft

      // 在 Designer 脚本加载完毕后创建 StiReport
      const report = new Stimulsoft.Report.StiReport()
      if (mrtContent) {
        report.load(mrtContent)
      }
      report.dictionary.databases.clear()

      // 注入样例数据，让字典树出现字段结构
      if (reportCode && sampleParams) {
        try {
          const { getReportData } = await import('@/api/reportCenter')
          const dataRes = await getReportData(reportCode, sampleParams)
          const reportData = dataRes?.data ?? dataRes
          if (reportData) {
            const dataSet = new Stimulsoft.System.Data.DataSet('data')
            dataSet.readJson(JSON.stringify(reportData))
            report.regData('data', 'data', dataSet)
            report.dictionary.synchronize()
          }
        } catch {
          // 没有样例数据也能打开设计器，字典树可能为空
        }
      }

      const options = new Stimulsoft.Designer.StiDesignerOptions()
      options.appearance.theme = Stimulsoft.Designer.StiDesignerTheme.Office2013WhiteBlue
      options.appearance.fullScreenMode = false

      const designer = new Stimulsoft.Designer.StiDesigner(options, 'StiDesigner_' + Date.now(), false)
      designer.report = report

      // 保存回调
      if (onSave && typeof onSave === 'function') {
        designer.onSaveReport = function (event) {
          const mrtText = event.report.saveToJsonString()
          onSave(mrtText)
        }
      }

      // 清空容器后挂载
      containerEl.innerHTML = ''
      designer.renderHtml(containerEl)

      loading.value = false
      return designer
    } catch (e) {
      error.value = e.message
      loading.value = false
      throw e
    }
  }

  return {
    ready: _loaded,
    loading,
    error,
    createViewer,
    createDesigner,
    ensureLoaded: _ensureLoaded,
  }
}

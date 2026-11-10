/* 项目雷达原型样例数据。版本号、日期、更新内容均为演示，不代表真实项目现状。
   类型与方舟模块在真实实现中来自字典表，运行时注入 AI 提示词。 */
window.RADAR_DATA = (() => {
  const TYPES = ['开源项目', 'SaaS 工具', 'AI 模型', 'MCP / Skill', '开发工具', '文章教程'];
  const MODULES = ['展会 AI 试戴', '设计生图', '素材管理', '方舟洞见', '知识库', '培训速递', '订单发票', '私海助手',
    'WhatsApp 助手', 'MCP 网关', 'Agent 任务中心', '报表中心', '生产报工'];
  const STATUS = { inbox: '待看', trying: '试用中', adopted: '已采用', dropped: '已放弃' };
  const WATCH = { key: '重点', normal: '普通', adopted: '已采用', silent: '静默' };

  const items = [
    {
      id: 1, kind: 'repo', host: 'github.com', path: 'browser-use/browser-use', title: 'browser-use',
      type: '开源项目', oneLiner: '让 AI Agent 像人一样操作浏览器，完成登录、点击、填表等多步任务',
      modules: [
        { name: '订单发票', reason: 'OKKI 后台无接口的操作可交给 Agent 代点，减少人工搬运', effort: '中' },
        { name: '私海助手', reason: '客户官网、社媒主页的批量信息采集', effort: '中' },
      ],
      version: 'v0.9.0', prevVersion: 'v0.8.2', updatedAt: '2026-11-09 22:14', stars: '7.1 万', license: 'MIT', lang: 'Python',
      status: 'trying', watch: 'key', unread: 'key', readState: 'ok', addedAt: '2026-10-21 09:12', tags: ['Agent', '自动化'],
      updateSummary: ['新增多标签页并行执行，长流程任务中断率下降', '支持复用本机 Chrome 登录态', '移除旧版 Controller API（升级需改调用）'],
      impact: '方舟若接入，需按新接口写调用；多标签页并行适合批量采集客户信息。',
      levelReason: '规则：release notes 含「移除」→ 关键；AI 复核：维持关键（你正在试用，升级需改调用）',
      detail: '基于 Playwright 的浏览器自动化框架，由大模型读取页面结构后决定下一步操作。支持自定义动作、结构化输出、录制回放。需要 Python 3.11+，可本地运行或使用官方云服务。适合没有 API 的后台系统做半自动化；对验证码与强风控站点无能为力。',
      timeline: [
        { date: '2026-11-09', level: 'key', title: 'v0.9.0 正式版', text: '多标签页并行；复用本机登录态；移除旧 Controller API' },
        { date: '2026-10-28', level: 'normal', title: 'v0.8.2', text: '修复表单填写时的焦点丢失' },
        { date: '2026-10-21', level: 'info', title: '收录', text: '来自 X 帖子，经钉钉收录' },
      ],
      sources: [{ channel: '钉钉', from: 'x.com/@某开发者/status/18…', at: '2026-10-21 09:12', text: '这个可以给 OKKI 自动化用' }],
      note: '先在测试账号上跑 OKKI 推单流程，看能不能稳定 20 次。', locked: [],
    },
    {
      id: 2, kind: 'repo', host: 'github.com', path: 'microsoft/markitdown', title: 'MarkItDown',
      type: '开源项目', oneLiner: '把 PDF、Word、Excel、PPT 等文件转换成 Markdown，方便喂给大模型',
      modules: [
        { name: '知识库', reason: '上传文档统一转 Markdown 后再切片，提升检索质量', effort: '低' },
        { name: '培训速递', reason: '培训课件 PPT 一键转文字稿供 AI 提炼', effort: '低' },
      ],
      version: 'v0.2.1', prevVersion: 'v0.2.0', updatedAt: '2026-11-09 16:40', stars: '6.3 万', license: 'MIT', lang: 'Python',
      status: 'trying', watch: 'key', unread: 'normal', readState: 'ok', addedAt: '2026-10-30 21:03', tags: ['文档处理'],
      levelReason: '规则：补丁版本 → 普通；AI 复核：维持普通',
      updateSummary: ['新增 EPUB 转换', 'PDF 表格识别准确度改进'],
      impact: '表格识别改进对报价单、装箱单类 PDF 有帮助。',
      detail: '微软开源的轻量文件转换工具，命令行与 Python 库两种用法，可选接入 OCR 与图片描述。输出保留标题、列表、表格结构。对复杂排版 PDF 的版面还原有限。',
      timeline: [
        { date: '2026-11-09', level: 'normal', title: 'v0.2.1', text: '新增 EPUB；PDF 表格识别改进' },
        { date: '2026-10-30', level: 'info', title: '收录', text: '来自公众号文章，经钉钉收录' },
      ],
      sources: [{ channel: '钉钉', from: 'mp.weixin.qq.com/s/… 《10 个外贸人必备 AI 工具》', at: '2026-10-30 21:03', text: '' }],
      note: '', locked: [],
    },
    {
      id: 3, kind: 'site', host: 'klingai.com', path: '', title: '可灵 AI',
      type: 'SaaS 工具', oneLiner: '文本或图片生成短视频，支持人物动作与镜头运动控制',
      modules: [
        { name: '素材管理', reason: '产品图生成 5 秒展示短视频，补充社媒素材', effort: '低' },
        { name: '展会 AI 试戴', reason: '试戴效果图转动态视频，提升现场展示效果', effort: '高' },
      ],
      version: '', prevVersion: '', updatedAt: '2026-11-09 10:00', stars: '', license: '', lang: '',
      status: 'trying', watch: 'key', unread: 'normal', readState: 'ok', addedAt: '2026-09-18 13:40', tags: ['视频生成'],
      levelReason: '规则：追踪页（价格页、API 文档）文本变化 18% → 普通；AI 复核：维持普通',
      updateSummary: ['价格页新增团队版套餐', '开放 API 文档新增图生视频首尾帧参数'],
      impact: '若走 API 接入，首尾帧参数可控制假发展示的起止姿态。',
      detail: '国内可直接访问的视频生成服务，网页端与 API 两种用法，按生成次数计费。商用授权以官网条款为准。',
      timeline: [
        { date: '2026-11-09', level: 'normal', title: '官网更新', text: '价格页新增团队版；API 文档新增首尾帧参数' },
        { date: '2026-09-18', level: 'info', title: '收录', text: '方舟页面手动收录' },
      ],
      sources: [{ channel: '方舟页面', from: 'klingai.com', at: '2026-09-18 13:40', text: '' }],
      note: '', locked: ['oneLiner'],
    },
    {
      id: 4, kind: 'repo', host: 'github.com', path: 'comfyanonymous/ComfyUI', title: 'ComfyUI',
      type: '开源项目', oneLiner: '节点式图像生成工作流，可串联模型、蒙版、换色等步骤',
      modules: [
        { name: '设计生图', reason: '把发色替换、背景合成固化成可复用工作流', effort: '高' },
        { name: '展会 AI 试戴', reason: '本地部署可降低单次生图成本', effort: '高' },
      ],
      version: 'v0.3.66', prevVersion: '', updatedAt: '2026-11-06 03:12', stars: '9.4 万', license: 'GPL-3.0', lang: 'Python',
      status: 'inbox', watch: 'normal', unread: '', readState: 'ok', addedAt: '2026-10-20 08:55', tags: ['生图', '本地部署'], sleepy: 21,
      updateSummary: ['修复若干节点内存泄漏'], impact: '',
      detail: '社区最活跃的 Stable Diffusion / Flux 工作流前端，需要 GPU。GPL 协议，嵌入商业产品需评估。',
      timeline: [
        { date: '2026-11-06', level: 'noise', title: '常规提交', text: '修复节点内存泄漏（未推送）' },
        { date: '2026-10-20', level: 'info', title: '收录', text: '来自 X 帖子' },
      ],
      sources: [{ channel: '钉钉', from: 'x.com/@某设计师/status/18…', at: '2026-10-20 08:55', text: '#展会' }],
      note: '', locked: [],
    },
    {
      id: 5, kind: 'repo', host: 'github.com', path: 'anthropics/claude-code', title: 'Claude Code',
      type: '开发工具', oneLiner: '终端里的 AI 编程助手，可读写代码、跑命令、接 MCP',
      modules: [{ name: 'MCP 网关', reason: '已作为日常开发主力，方舟 MCP 网关直接服务它', effort: '低' }],
      version: 'v2.4.1', prevVersion: 'v2.4.0', updatedAt: '2026-11-05 19:30', stars: '', license: '', lang: 'TypeScript',
      status: 'adopted', watch: 'adopted', unread: '', readState: 'ok', addedAt: '2026-07-02 10:00', tags: ['开发'],
      updateSummary: ['新增会话分章与任务清单面板'], impact: '',
      detail: 'Anthropic 官方 CLI 编程助手。', timeline: [
        { date: '2026-11-05', level: 'normal', title: 'v2.4.1', text: '会话分章与任务清单面板（已采用级别：非破坏性，未推送）' },
      ],
      sources: [{ channel: '方舟页面', from: 'github.com', at: '2026-07-02 10:00', text: '' }], note: '', locked: [],
    },
    {
      id: 6, kind: 'repo', host: 'github.com', path: 'mem0ai/mem0', title: 'Mem0',
      type: '开源项目', oneLiner: '给 AI Agent 加长期记忆层，跨会话记住用户与项目事实',
      modules: [{ name: 'Agent 任务中心', reason: '已用于跨 Agent 共享记忆', effort: '低' }],
      version: 'v1.1.0', prevVersion: '', updatedAt: '2026-10-29 11:00', stars: '4.2 万', license: 'Apache-2.0', lang: 'Python',
      status: 'adopted', watch: 'adopted', unread: '', readState: 'ok', addedAt: '2026-08-14 15:22', tags: ['记忆'],
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '方舟页面', from: 'github.com', at: '2026-08-14 15:22', text: '' }], note: '', locked: [],
    },
    {
      id: 7, kind: 'repo', host: 'github.com', path: 'firecrawl/firecrawl', title: 'Firecrawl',
      type: '开源项目', oneLiner: '把任意网页抓成干净的 Markdown 或结构化 JSON',
      modules: [{ name: '方舟洞见', reason: '信源采集已在用', effort: '低' }],
      version: 'v2.3.0', prevVersion: '', updatedAt: '2026-10-27 09:40', stars: '4.8 万', license: 'AGPL-3.0', lang: 'TypeScript',
      status: 'adopted', watch: 'silent', unread: '', readState: 'ok', addedAt: '2026-07-25 16:10', tags: ['采集'],
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '方舟页面', from: 'github.com', at: '2026-07-25 16:10', text: '' }], note: '', locked: [],
    },
    {
      id: 8, kind: 'repo', host: 'github.com', path: 'n8n-io/n8n', title: 'n8n',
      type: '开源项目', oneLiner: '可视化工作流自动化，连接 400+ 应用，可自托管',
      modules: [{ name: 'Agent 任务中心', reason: '非开发同事可自己拖拽搭简单自动化', effort: '中' }],
      version: 'v2.0.0', prevVersion: 'v1.118.0', updatedAt: '2026-11-05 14:00', stars: '15 万', license: 'Sustainable Use', lang: 'TypeScript',
      status: 'inbox', watch: 'normal', unread: '', readState: 'ok', addedAt: '2026-11-02 22:31', tags: ['自动化'],
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '钉钉', from: 'github.com', at: '2026-11-02 22:31', text: '' }], note: '', locked: [],
    },
    {
      id: 9, kind: 'repo', host: 'github.com', path: 'modelcontextprotocol/servers', title: 'MCP Servers 官方合集',
      type: 'MCP / Skill', oneLiner: 'MCP 官方参考服务器合集：文件、Git、数据库、浏览器等',
      modules: [{ name: 'MCP 网关', reason: '对照官方实现完善方舟 MCP 工具规范', effort: '低' }],
      version: '', prevVersion: '', updatedAt: '2026-11-03 08:20', stars: '7.6 万', license: 'MIT', lang: 'TypeScript',
      status: 'inbox', watch: 'normal', unread: '', readState: 'ok', addedAt: '2026-11-03 21:15', tags: ['MCP'],
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '钉钉', from: 'github.com', at: '2026-11-03 21:15', text: '' }], note: '', locked: [],
    },
    {
      id: 10, kind: 'site', host: 'elevenlabs.io', path: '', title: 'ElevenLabs',
      type: 'SaaS 工具', oneLiner: '仅获取到标题，正文读取受限', modules: [],
      version: '', prevVersion: '', updatedAt: '', stars: '', license: '', lang: '',
      status: 'inbox', watch: 'normal', unread: '', readState: 'limited', readNote: '网站拦截了自动读取，只拿到页面标题（已连续 1 天）。补一句说明后可完成分析；更新检测会继续重试。', addedAt: '2026-11-09 23:48', tags: [],
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '钉钉', from: 'elevenlabs.io', at: '2026-11-09 23:48', text: '' }], note: '', locked: [],
    },
    {
      id: 13, kind: 'site', host: 'suno.com', path: '', title: 'Suno',
      type: 'SaaS 工具', oneLiner: 'AI 生成带人声的歌曲和背景音乐，可指定风格与时长',
      modules: [{ name: '素材管理', reason: '产品短视频配乐，免去版权音乐采购', effort: '低' }],
      version: '', prevVersion: '', updatedAt: '2026-10-28 09:00', stars: '', license: '', lang: '',
      status: 'inbox', watch: 'normal', unread: '', readState: 'ok', addedAt: '2026-11-09 23:48', tags: ['音乐'],
      scanMode: 'agent', lastAgentCheck: '2026-11-09 06:04', agentNote: '官网没有 changelog 和 RSS，更新只发在首页横幅和博客，已改为 agent 每周检查。上次检查：未发现新内容（浏览 4 页）。',
      updateSummary: [], impact: '', detail: '', timeline: [
        { date: '2026-11-09', level: 'info', title: 'agent 检查', text: '浏览首页、博客、价格页、帮助中心，未发现新内容' },
        { date: '2026-11-09', level: 'info', title: '收录', text: '读取受限，经钉钉补充说明后完成分析' },
      ],
      sources: [{ channel: '钉钉', from: 'suno.com', at: '2026-11-09 23:48', text: 'AI 生成背景音乐，可以给产品短视频配乐' }], note: '', locked: [],
    },
    {
      id: 11, kind: 'article', host: 'mp.weixin.qq.com', path: '', title: '10 个外贸人必备 AI 工具',
      type: '文章教程', oneLiner: '盘点外贸场景的 AI 工具，含翻译、建站、视频与询盘处理', modules: [{ name: '培训速递', reason: '可作为销售培训素材', effort: '低' }],
      version: '', prevVersion: '', updatedAt: '2026-10-30 07:00', stars: '', license: '', lang: '',
      status: 'inbox', watch: 'silent', unread: '', readState: 'ok', addedAt: '2026-10-30 21:03', tags: ['外贸'], articleNote: '文章不追踪更新；文中提到的 MarkItDown 已单独收录',
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '钉钉', from: 'mp.weixin.qq.com', at: '2026-10-30 21:03', text: '' }], note: '', locked: [],
    },
    {
      id: 12, kind: 'repo', host: 'github.com', path: 'langgenius/dify', title: 'Dify',
      type: '开源项目', oneLiner: '可视化搭建大模型应用与知识库问答', modules: [{ name: '知识库', reason: '与方舟现有 AI facade 与知识库重叠', effort: '高' }],
      version: 'v1.9.2', prevVersion: '', updatedAt: '2026-10-25 12:00', stars: '11 万', license: 'Dify OSL', lang: 'Python',
      status: 'dropped', watch: 'silent', unread: '', readState: 'ok', addedAt: '2026-06-12 10:20', tags: [],
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '方舟页面', from: 'github.com', at: '2026-06-12 10:20', text: '' }], note: '方舟已有统一 AI 入口和知识库，重复建设，放弃。', locked: [],
    },
  ];

  /* 收录模拟：输入不同链接时原型给出的 AI 分析结果 */
  const samples = {
    repo: {
      kind: 'repo', host: 'github.com', path: 'openai/openai-agents-python', title: 'OpenAI Agents SDK',
      type: '开源项目', oneLiner: '轻量多 Agent 编排框架，内置工具调用、交接与追踪',
      modules: [{ name: 'Agent 任务中心', reason: '多 Agent 交接机制可参考用于派单流水线', effort: '中' }],
      version: 'v0.6.1', updatedAt: '2026-11-09 18:02', stars: '1.9 万', license: 'MIT', lang: 'Python', tags: ['Agent'],
    },
    articleCandidates: [
      { title: 'LobeHub', path: 'lobehub/lobe-chat', oneLiner: '开源 AI 对话界面，支持多模型与插件', checked: true },
      { title: 'Cherry Studio', path: 'CherryHQ/cherry-studio', oneLiner: '桌面端多模型 AI 客户端', checked: false },
      { title: 'Open WebUI', path: 'open-webui/open-webui', oneLiner: '自托管的大模型网页界面', checked: true },
    ],
  };

  return { TYPES, MODULES, STATUS, WATCH, items, samples, today: '2026-11-10' };
})();

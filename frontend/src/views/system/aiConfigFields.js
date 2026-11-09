export const transportFields = [
  { key: 'timeout_sec', label: '文本超时（秒）', type: 'number', min: 1, max: 3600 },
  { key: 'multimodal_timeout_sec', label: '多模态超时（秒）', type: 'number', min: 1, max: 3600, hint: '未设置时至少 120 秒；业务可限制本次调用时长。' },
  { key: 'image_timeout_sec', label: '生图超时（秒）', type: 'number', min: 1, max: 3600, hint: '未设置时至少 300 秒；业务可限制单次调用时长，整个任务还受原有看门狗约束。' },
  { key: 'connect_timeout_sec', label: '连接超时（秒）', type: 'number', min: 1, max: 120 },
  { key: 'write_timeout_sec', label: '发送超时（秒）', type: 'number', min: 1, max: 3600 },
  { key: 'image_max_attempts', label: '生图最多尝试次数', type: 'number', min: 1, max: 3, hint: '含首次请求，默认 3 次。业务自行管理重试时可限制为 1 次。' },
  { key: 'image_retry_backoff_sec', label: '生图重试间隔（秒）', type: 'number', min: 0, max: 10, hint: '默认 1.5 秒，按尝试次数递增。' },
  { key: 'image_retry_statuses', label: '生图重试状态码', type: 'json', hint: '默认 [502,503]；可填 [] 禁用 HTTP 错误重试，允许 429、502、503。超时不会自动重试。' },
  { key: 'image_parameter_fallback', label: '不支持的生图参数自动移除重试', type: 'boolean', hint: '默认启用；业务明确禁止时不能覆盖。' },
]

export const providerFields = [
  { key: 'chat_path', label: '文本 / Chat 图片端点', hint: '相对于 API Base，如 chat/completions；留空自动拼接。' },
  { key: 'image_generation_path', label: '图片生成端点', hint: '如 images/generations。' },
  { key: 'image_edit_path', label: '图片编辑端点', hint: '如 images/edits；与生成端点独立。' },
  { key: 'auth_header', label: '认证请求头', hint: '如 Authorization、x-api-key；留空按协议选择。密钥始终读取加密 API Key。' },
  { key: 'auth_scheme', label: '认证前缀', hint: '如 Bearer；自定义认证头时留空表示直接发送密钥。' },
  { key: 'anthropic_version', label: 'Anthropic 协议版本', hint: '默认 2023-06-01，附加请求头同名值优先。' },
  { key: 'token_parameter', label: '输出 Token 参数名', options: ['max_tokens', 'max_completion_tokens'] },
  { key: 'image_proxy', label: '生图请求代理地址', hint: '可配置 HTTP(S)/SOCKS5，不含账号密码；未设置沿用部署网络配置。JSON 中空字符串表示直连。' },
  ...transportFields.map(field => field.key === 'timeout_sec' ? { ...field, label: '文本超时覆盖（秒）', hint: '留空使用上方提供商默认超时。' } : field),
  { key: 'test_model', label: '连通性测试模型', hint: '文本模型名；留空使用启用的文本预设。图片模型请用预设测试。' },
  { key: 'test_message', label: '连通性测试消息', hint: '默认 hi。' },
  { key: 'test_max_tokens', label: '连通性测试 Token 上限', type: 'number', min: 1, max: 256, hint: '默认 10。' },
]

export const presetFields = [
  { key: 'workflow.max_attempts', label: '展会 / 培训最多尝试次数', type: 'number', min: 1, max: 4, hint: '只影响这些功能已有的重试；培训和展会策略最多 3 次，试戴/分析最多 4 次。' },
  { key: 'workflow.retry_backoff_sec', label: '展会 / 培训重试间隔（秒）', type: 'number', min: 0, max: 10 },
  { key: 'workflow.json_repair_attempts', label: '展会 / 培训 JSON 修复重试次数', type: 'number', min: 0, max: 1 },
  { key: 'test_mode', label: '预设测试类型', options: ['text', 'image'], hint: 'text 用于文本/识图，image 用于生成/编辑；与是否显示在 AI 生图中独立。' },
  { key: 'temperature', label: '温度', type: 'number', min: 0, max: 2 },
  { key: 'max_tokens', label: '输出 Token 上限', type: 'number', min: 1, max: 1000000 },
  { key: 'top_p', label: 'Top P', type: 'number', min: 0, max: 1 },
  { key: 'request_parameters', label: '供应商扩展参数', type: 'json', hint: 'JSON 对象；不得覆盖模型、消息、工具、图片数量等业务字段。' },
  ...transportFields.map(field => ({ ...field, key: `transport.${field.key}` })),
]

export const imageFields = [
  { key: 'workflow.expo_tryon_size', label: '展会试戴图片尺寸', hint: '配置在 expo_wig_composite；默认 1024x1536。新任务固化尺寸，历史任务保持不变。' },
  { key: 'workflow.expo_scene_size', label: '展会场景图片尺寸', hint: '留空采用预设默认尺寸。' },
  { key: 'size', label: '默认图片尺寸', hint: '如 1024x1536；本次请求指定的尺寸优先。' },
  { key: 'quality', label: '默认图片质量', hint: '如 medium、high；需供应商支持。' },
  { key: 'size_parameter', label: '尺寸参数格式', options: ['size', 'aspect_ratio'] },
  { key: 'max_reference_images', label: '参考图数量上限', type: 'number', min: 0, max: 5 },
  { key: 'output_format', label: '图片文件格式', options: ['png', 'jpeg', 'webp'] },
  { key: 'response_format', label: '图片返回格式', options: ['b64_json', 'url'] },
  { key: 'download_hosts', label: '图片下载域名', type: 'json', hint: '如 ["images.example.com"]；仅填真实供应商域名，不含协议和路径。' },
  { key: 'background', label: '背景', options: ['auto', 'opaque', 'transparent'] },
  { key: 'input_fidelity', label: '参考图保真度', options: ['low', 'high'] },
  { key: 'moderation', label: '审核档位', options: ['auto', 'low'] },
  { key: 'output_compression', label: '图片压缩质量', type: 'number', min: 0, max: 100 },
]

export function parseConfig(value) {
  try {
    const parsed = JSON.parse(value || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch { return null }
}

export function getConfigValue(config, key) {
  return key.split('.').reduce((value, part) => value?.[part], config)
}

export function setConfigValue(value, key, next) {
  const config = parseConfig(value)
  if (!config) throw new Error('请先修正参数 JSON')
  const keys = key.split('.')
  let target = config
  for (const part of keys.slice(0, -1)) {
    if (target[part] !== undefined && (!target[part] || typeof target[part] !== 'object' || Array.isArray(target[part]))) {
      throw new Error(`${part} 必须是 JSON 对象`)
    }
    target = target[part] ??= {}
  }
  if (next === undefined || next === null || next === '') delete target[keys.at(-1)]
  else target[keys.at(-1)] = next
  return JSON.stringify(config, null, 2)
}

export default {
  title: '全局控制配置',
  description:
    '统一管理平台侧全局行为配置：模型运行时降级、外部素材获取、会话 Checkpoint、技能目录同步、图像请求策略与视觉兜底模型，以及桌面客户端连接地址。',
  loadFailed: '加载全局控制配置失败',
  saved: '全局控制配置已保存',
  saveFailed: '保存全局控制配置失败',
  save: '保存全部配置',
  sections: {
    runtimeFallback: {
      title: '模型运行时降级',
      description: '控制模型请求失败时的自动重连行为。',
    },
    mediaFetch: {
      title: '外部素材获取',
      description: '控制对话中获取外部图片等素材的能力，以及未报告体积时的估算上限。',
    },
    agentCheckpoint: {
      title: '会话 Checkpoint',
      description: '控制会话级 Checkpoint 是否开启，用于会话状态保存与恢复。',
    },
    skillCatalogSync: {
      title: '技能目录同步',
      description: '控制启动时是否自动将技能目录同步到知识库。',
    },
    imageRequestPolicy: {
      title: '图像请求策略',
      description: '控制图像生成类请求在绑定模型不可用时的处理策略。',
    },
    visionFallback: {
      title: '视觉兜底模型',
      description: '配置视觉理解能力的兜底模型，主模型不可用时自动切换。',
    },
    desktopClient: {
      title: '桌面客户端连接',
      description: '配置桌面客户端的 API 服务器地址，留空表示与当前服务器同源连接。',
    },
  },
  fields: {
    enabled: '启用',
    retryAttempts: '重连次数',
    retryAttemptsHint: '模型请求失败时自动重试的次数，默认 5 次，需大于 0。',
    retryAttemptsInvalid: '重连次数必须大于 0',
    maxBytesMb: '素材体积上限 (MB)',
    maxBytesMbHint: '外部素材未报告体积时按此上限估算，默认 512 MB，需大于 0。',
    maxBytesMbInvalid: '素材体积上限必须大于 0',
    policy: '请求策略',
    policyHint: 'strict：仅使用绑定模型；auto_upgrade：绑定模型不可用时自动升级到更高档位模型。',
    policyStrict: '严格（strict）',
    policyAutoUpgrade: '自动升级（auto_upgrade）',
    provider: '供应商',
    providerPlaceholder: '如 openai',
    model: '模型',
    modelPlaceholder: '如 gpt-4o',
    apiOrigin: '连接地址（API 服务器）',
    apiOriginPlaceholder: '如 http://127.0.0.1 或 https://your-domain.com',
  },
}

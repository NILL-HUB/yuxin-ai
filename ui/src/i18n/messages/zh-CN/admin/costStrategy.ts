export default  {
      title: '成本策略',
      description: '维护各档位的单请求最大成本、计费模式与升级阈值，属于计费运营域。',
      stats: {
        total: '策略总数',
        byToken: '按 Token',
        byRequest: '按请求',
        byCredit: '按算力值',
      },
      columns: {
        policyName: '策略名称',
        modelTier: '模型档位',
        maxCostPerRequest: '单请求最大成本',
        billingMode: '计费模式',
        upgradeThreshold: '升级阈值',
        actions: '操作',
      },
      actions: {
        create: '新建成本策略',
        edit: '编辑',
      },
      billingModes: {
        token: '按 Token',
        request: '按请求',
        credit: '按算力值',
      },
      empty: '暂无成本策略',
      modal: {
        editTitle: '编辑成本策略',
        placeholders: {
          policyName: '例如: default',
          price: '0.000000',
        },
      },
      messages: {
        loadFailed: '加载成本策略失败',
        created: '成本策略创建成功',
        updated: '成本策略已更新',
        createFailed: '创建成本策略失败',
        updateFailed: '更新成本策略失败',
      },
    }

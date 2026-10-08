export default {
  title: '机密记忆读取确认',
  desc: '本次提问命中机密记忆（身份证 / 手机号 / 银行卡 / 密码 / 验证码 / 密钥）。确认后 30 分钟内可直接读取这一批记忆。',
  allow: '允许读取',
  deny: '暂不读取',
  allowed: '已允许读取',
  denied: '已拒绝读取',
  needAskAgain: '已允许读取，正在为你重新提问…',
  expired: '确认记录已过期或不存在',
  types: {
    email: '邮箱',
    phone: '手机号',
    id_card: '身份证',
    bank_card: '银行卡',
    password: '密码',
    otp: '验证码',
    secret: '密钥',
  },
}

# 0001 - 原生微信小程序，不用 uni-app

项目只发布微信小程序端、明确不做 App 和多端，uni-app"一套代码多端"的核心卖点不成立，反而多一层编译转换：`wx.scanCode`、`wx.requestSubscribeMessage` 等原生能力隔层调用，报错栈不直观，且依赖 uView Plus 等第三方组件库的维护状态。故前端采用原生小程序（WXML/WXSS + TypeScript），状态管理用 MobX-miniprogram 或自研 Behavior。

## Considered Options

- uni-app + Vue3 + TS（原任务书 v4.0 方案）：保留 Vue 开发体验，若未来要多端可重议
- 原生小程序 + TS：✅ wx API 零隔层、报错直达源码、构建链最轻

## Consequences

- 任务书第 2.1 节技术栈表作废，全部 `uni.*` API 改为 `wx.*`
- 放弃 Vue 语法；UI 组件用 WeUI 或自研组件

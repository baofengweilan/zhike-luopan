# 0007 - AI 服务改接腾讯云开发 CloudBase（混元 hy3），MoMA 降级为备选

日期：2026-10-02。用户 2026-10-02 确认：移动云 MoMA 的 Key 迟迟未批下来，而微信小程序大赛要求 2026-10-17 正式发布（唯一路径 = 微信云托管，同属腾讯云开发生态），故决定改用「小程序成长计划」赠送的 CloudBase AI 资源包（混元 hy3，约 2 亿 Token）。

## 为什么可行（零代码改动）

CloudBase HTTP API（`POST /v1/ai/:provider/:path`，provider 取 `hunyuan-v3`）原生支持 OpenAI Chat Completions 协议，与本项目 `app/services/ai.py` 的 `_llm_chat`（原 `_moma_chat`，ADR-0002 设计的 OpenAI 兼容调用层）完全对得上。切换只需改 `.env` 三个值：

```
AI_BASE_URL=https://<你的环境ID>.tcloudbase.com/v1/ai/hunyuan-v3   # 以控制台"AI 设置"页给出的为准
AI_API_KEY=<CloudBase 控制台创建的 API Key>
AI_MODEL=hy3
```

## 关键约束（务必知道）

1. **⚠️ 免费额度不能直接 HTTP 调（2026-10-02 实测踩坑）**：成长计划资源包只允许
   「小程序 SDK / 云开发 SDK」两种调用通道，直接拿 API Key 调 OpenAI 兼容 HTTP 接口
   报 403 `AI_CHANNEL_NOT_ALLOWED`（错误码文档：docs.cloudbase.net/error-code/service/AI_CHANNEL_NOT_ALLOWED）。
   **解法 = 云函数代理**（见下）。另：Python 直连 `*.tcloudbasegateway.com` 有证书链
   不完整问题（服务器只发叶子证书），`ai.py` 已用 truststore（借 Windows 证书机制）
   解决，truststore 进了 pyproject 依赖。
2. **云函数代理架构**：`cloudbase/ai-proxy/`（部署指南见其 README）——云函数内部走
   `@cloudbase/node-sdk` 的 `ai.createModel().generateText()`（合规通道），对外暴露
   OpenAI Chat Completions 兼容子集 + 共享密钥鉴权（PROXY_SECRET 环境变量，与后端
   `AI_API_KEY` 同值）。后端依旧零改动，`AI_BASE_URL` 指向函数的 HTTP 访问地址。
3. **MoMA 不删除**：`.env.example` 保留 MoMA 注释样例。若赛前拿到 MoMA Key，改回三个环境变量即可，代码不用动——这是 ADR-0002 OpenAI 兼容设计的直接红利。
4. 模型选 `hy3`（混元 Flash 档）：课表规则解析/数据问答是结构化轻任务，Flash 档够用且省 Token（同 ADR-0002 对 MoMA 的选型逻辑）。

## 后续动作

- [x] 用户报名「小程序成长计划」并开通云开发环境（环境 ID：sofh-d0gldtpq594bcf60e）
- [x] CloudBase 控制台创建 API Key（注：该 Key 因通道限制暂不用于 HTTP 直调，留作备查）
- [x] 2026-10-02 云函数 ai-proxy 已部署并上线（ZCode 浏览器自动化完成；CLI 不支持 miniapp 环境故走控制台）：
  - 函数：普通云函数，Node.js 20.19，超时 60s，环境变量 PROXY_SECRET
  - HTTP 网关路由：https://sofh-d0gldtpq594bcf60e-1499165857.ap-shanghai.app.tcloudbase.com/ai-proxy
  - 验收：错误密钥 401 拒绝 ✓；正确密钥调 hy3 返回 200 ✓；后端 /api/ai/ask 端到端 200 ✓
- [x] `.env` AI_BASE_URL 已指向网关路由，AI 正式启用（规则引擎自动退为兜底）

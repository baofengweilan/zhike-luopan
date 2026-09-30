# 0002 - AI 服务走移动云 MoMA，不用智谱 API

本项目参加移动云杯，比赛提供的一站式模型服务平台是 MoMA（moma.cmecloud.cn，OpenAI 兼容网关，接入九天/DeepSeek/GLM 等 300+ 模型，新认证用户有 2500 万 Token 额度）。用赛方平台既是评审加分项又免自购 API 费用，故 AI_BASE_URL 指向 MoMA，模型 code 从 MoMA 控制台"订购模型管理"获取；课表规则解析这类结构化任务用 DeepSeek/Glm 的 Flash 档即可。Key 到位前阶段 6 全部 mock。

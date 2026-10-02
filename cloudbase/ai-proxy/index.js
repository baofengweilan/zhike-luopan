/**
 * 智课罗盘 - AI 代理云函数（ADR 0007）
 *
 * 为什么存在这个函数：
 *   小程序成长计划赠送的 AI 资源包，官方限制只允许「小程序 SDK / 云开发 SDK」调用
 *   （直接 HTTP 调用报 AI_CHANNEL_NOT_ALLOWED）。本项目后端是 FastAPI（Python），
 *   无法直接用云开发 SDK，所以在云环境里放这个云函数当"翻译官"：
 *
 *     FastAPI 后端 --HTTP(带密钥)--> 本云函数 --云开发SDK(合规通道)--> 混元 hy3
 *
 * 对外契约：兼容 OpenAI Chat Completions 的一个子集——
 *   请求：POST /chat/completions，body = { model, messages, temperature? }
 *   响应：{ choices: [ { message: { content } } ] }
 *   后端 app/services/ai.py 的 _llm_chat 按此契约调用，改 Base URL 即接入，零代码改动。
 *
 * 安全：请求头 Authorization: Bearer <PROXY_SECRET> 必须匹配（PROXY_SECRET 在
 *   云函数环境变量里配置，与后端 .env 的 AI_API_KEY 相同值），防止公网白嫖额度。
 */

const cloudbase = require("@cloudbase/node-sdk");

// 初始化：SYMBOL_CURRENT_ENV = 自动取当前云环境，不用写死环境 ID。
// timeout 60s：官方建议，AI 生成可能耗时较长（官方文档 nodejs-access 页示例同款）
const app = cloudbase.init({ env: cloudbase.SYMBOL_CURRENT_ENV, timeout: 60000 });

// HTTP 访问服务入口（event 为 API 网关风格的请求结构）
exports.main = async function (event) {
  // ---- 1. 鉴权：比对共享密钥（放最前面，验不过一律 401）----
  const headers = event.headers || {};
  // header 名在网关里可能被转成小写，两种取法都试
  const auth = headers.Authorization || headers.authorization || "";
  const secret = process.env.PROXY_SECRET || "";
  if (!secret || auth !== `Bearer ${secret}`) {
    return reply(401, { error: { message: "proxy key mismatch" } });
  }

  // ---- 2. 解析 OpenAI 格式请求体 ----
  let body;
  try {
    body = typeof event.body === "string" ? JSON.parse(event.body) : event.body || {};
  } catch (e) {
    return reply(400, { error: { message: "invalid json body" } });
  }

  const model = body.model || "hy3"; // 默认混元 hy3（成长计划赠送额度覆盖的模型）
  const messages = Array.isArray(body.messages) ? body.messages : null;
  if (!messages) {
    return reply(400, { error: { message: "messages required" } });
  }

  // ---- 3. 走云开发 SDK 调大模型（这是唯一被成长计划允许的通道）----
  // 官方写法（docs.cloudbase.net/ai/model/nodejs-access）：
  //   createModel 的参数是"供应商名"（免费额度走 "cloudbase" 分组），
  //   具体模型名（hy3）放在 generateText 的参数里，别搞反。
  try {
    const ai = app.ai();
    const chat = ai.createModel("cloudbase");
    const result = await chat.generateText({
      model: model, // 请求体里的 model 字段，默认 hy3
      messages: messages,
      temperature: typeof body.temperature === "number" ? body.temperature : 0,
    });
    // generateText 返回 { text }，包成 OpenAI 响应形状给后端
    return reply(200, {
      id: "cloudbase-proxy",
      object: "chat.completion",
      choices: [
        {
          index: 0,
          message: { role: "assistant", content: result.text || "" },
          finish_reason: "stop",
        },
      ],
    });
  } catch (err) {
    // 模型名不对/额度问题都会落到这里，把原始信息带回给后端方便排查
    console.error("AI 调用失败:", err);
    return reply(502, {
      error: { message: "upstream ai error", detail: String(err && err.message ? err.message : err) },
    });
  }
};

// 统一包装 HTTP 访问服务要求的响应结构
function reply(statusCode, jsonBody) {
  return {
    statusCode: statusCode,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(jsonBody),
  };
}

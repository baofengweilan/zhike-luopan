import { getToken, clearToken } from "./token";
import { logger } from "./logger";

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  data?: Record<string, unknown>;
  /** 401 时自动跳登录页（默认 true） */
  redirectOn401?: boolean;
}

/** 业务错误：message 给 toast 用，detail 保留后端结构化错误体（如 409 的冲突列表） */
export class ApiError extends Error {
  statusCode: number;
  detail: unknown;

  constructor(message: string, statusCode: number, detail?: unknown) {
    super(message);
    this.statusCode = statusCode;
    this.detail = detail;
  }
}

/**
 * wx.request 的 Promise 封装：自动附带 JWT，401 统一清理并跳登录，
 * 非 2xx 统一抛 ApiError（detail 保留后端结构化错误体）。
 */
export function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", data, redirectOn401 = true } = options;
  const baseUrl = getApp<IAppOption>().globalData.baseUrl;
  const startedAt = Date.now();

  return new Promise<T>((resolve, reject) => {
    logger.debug("req", `→ ${method} ${path}`, data ? { body: data } : "");
    wx.request({
      url: `${baseUrl}${path}`,
      method,
      data,
      header: { Authorization: `Bearer ${getToken() ?? ""}` },
      success(res) {
        logger.debug("req", `← ${method} ${path} ${res.statusCode} (${Date.now() - startedAt}ms)`);
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T);
          return;
        }
        // FastAPI 错误体：{detail: string} 或 {detail: {message, conflicts, ...}}
        const raw = (res.data as { detail?: unknown })?.detail;
        const message =
          typeof raw === "string"
            ? raw
            : ((raw as { message?: string })?.message ?? `请求失败（${res.statusCode}）`);
        logger.warn("req", `${method} ${path} 失败：${res.statusCode} ${message}`);
        if (res.statusCode === 401) {
          logger.warn("req", "401：清除本地 token 并跳登录页");
          clearToken();
          if (redirectOn401) wx.reLaunch({ url: "/pages/login/login" });
        }
        reject(new ApiError(message, res.statusCode, raw));
      },
      fail(err) {
        logger.error("req", `${method} ${path} 网络异常：${err.errMsg}`);
        reject(new ApiError(err.errMsg || "网络异常", 0));
      },
    });
  });
}

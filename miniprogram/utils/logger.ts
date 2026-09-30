/**
 * 统一日志封装：统一前缀 + 按环境分级。
 *
 * debug 仅在开发版（envVersion === "develop"）输出；
 * trial（体验版）输出 info 及以上；release 只输出 warn/error。
 * 用法：logger.debug("req", "GET /api/semesters", res.statusCode)
 */

type Level = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: Record<Level, number> = { debug: 0, info: 1, warn: 2, error: 3 };

/** 环境阈值只算一次；取不到环境信息时按 release 处理（fail-closed，不泄漏日志） */
const floor = (() => {
  try {
    const env = wx.getAccountInfoSync().miniProgram.envVersion;
    if (env === "develop") return LEVEL_ORDER.debug;
    if (env === "trial") return LEVEL_ORDER.info;
    return LEVEL_ORDER.warn;
  } catch {
    return LEVEL_ORDER.warn;
  }
})();

function emit(level: Level, tag: string, args: unknown[]): void {
  if (LEVEL_ORDER[level] < floor) return;
  const prefix = `[智课罗盘:${tag}]`;
  const method = level === "debug" ? "log" : level;
  console[method as "log"](prefix, ...args);
}

export const logger = {
  debug: (tag: string, ...args: unknown[]) => emit("debug", tag, args),
  info: (tag: string, ...args: unknown[]) => emit("info", tag, args),
  warn: (tag: string, ...args: unknown[]) => emit("warn", tag, args),
  error: (tag: string, ...args: unknown[]) => emit("error", tag, args),
};

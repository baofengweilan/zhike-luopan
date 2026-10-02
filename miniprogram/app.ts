import { getToken } from "./utils/token";
import { logger } from "./utils/logger";

App({
  globalData: {
    // 开发期本地后端；生产改为已备案的 https 域名（任务书 2.4）
    baseUrl: "http://127.0.0.1:8000",
    // 跨页学期上下文（ADR 0006）：semesters/ai 跳课表前写入，schedule.onShow 取走即清
    pendingSemesterId: "",
  },

  onLaunch() {
    if (!getToken()) {
      logger.debug("app", "无本地 token，跳登录页");
      wx.reLaunch({ url: "/pages/login/login" });
    } else {
      logger.debug("app", "已有本地 token，直接进入");
    }
  },
});

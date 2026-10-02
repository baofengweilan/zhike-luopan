import { request } from "../../utils/request";
import { getToken } from "../../utils/token";
import { logger } from "../../utils/logger";

interface Me {
  id: string;
  nickname: string | null;
  avatar_url: string | null;
  timezone: string;
}

/**
 * 「我的」tab（ADR 0006）：原首页导航卡片降级为这里的二级入口。
 * 课表配置组只放「学期管理」——时令/作息/校历/模板是学期子资源，
 * 由学期管理页携带学期上下文进入，天然保住层级关系。
 */
Page({
  data: {
    me: null as Me | null,
  },

  onShow() {
    // tab 页登录守卫：无 token 直接回登录页（与 schedule/ai 同策略）
    if (!getToken()) {
      logger.debug("profile", "无 token，跳登录页");
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    this.loadMe();
  },

  async loadMe() {
    try {
      const me = await request<Me>("/api/auth/me");
      logger.debug("profile", "用户信息加载完成", me.id);
      this.setData({ me });
    } catch {
      // 401 已由 request 封装统一跳登录；其余错误静默（顶栏不阻塞入口使用）
    }
  },

  // ---- 课表配置组 ----

  goSemesters() {
    logger.debug("profile", "进入学期管理");
    wx.navigateTo({ url: "/pages/semesters/semesters" });
  },

  // ---- 学习工具组 ----

  goTextbooks() {
    logger.debug("profile", "进入我的教材");
    wx.navigateTo({ url: "/pages/textbooks/textbooks" });
  },

  goPhotos() {
    logger.debug("profile", "进入教室相册");
    wx.navigateTo({ url: "/pages/photos/photos" });
  },

  goReminders() {
    logger.debug("profile", "进入提醒管理");
    wx.navigateTo({ url: "/pages/reminders/reminders" });
  },
});

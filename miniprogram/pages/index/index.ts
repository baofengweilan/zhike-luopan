import { request } from "../../utils/request";
import { getToken } from "../../utils/token";
import { listSemesters } from "../../utils/api";

interface Me {
  id: string;
  nickname: string | null;
  avatar_url: string | null;
  timezone: string;
}

Page({
  data: {
    me: null as Me | null,
    hasActiveSemester: false,
  },

  onShow() {
    if (!getToken()) {
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    this.loadMe();
    this.checkActiveSemester();
  },

  async loadMe() {
    try {
      const me = await request<Me>("/api/auth/me");
      this.setData({ me });
    } catch {
      // 401 已由 request 封装统一跳登录；其余错误静默
    }
  },

  async checkActiveSemester() {
    try {
      const semesters = await listSemesters();
      this.setData({ hasActiveSemester: semesters.some((s) => s.is_active) });
    } catch {
      // 静默
    }
  },

  goSemesters() {
    wx.navigateTo({ url: "/pages/semesters/semesters" });
  },

  goSchedule() {
    wx.navigateTo({ url: "/pages/schedule/schedule" });
  },

  goAI() {
    wx.navigateTo({ url: "/pages/ai/ai" });
  },
});

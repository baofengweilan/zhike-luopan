import { silentLogin } from "../../utils/auth";
import { logger } from "../../utils/logger";

Page({
  data: {
    loading: false,
  },

  async onLogin() {
    if (this.data.loading) return;
    this.setData({ loading: true });
    try {
      logger.debug("login", "开始登录流程");
      await silentLogin();
      logger.info("login", "登录成功，进入首页");
      wx.reLaunch({ url: "/pages/index/index" });
    } catch (e) {
      logger.error("login", "登录失败：", e);
      wx.showToast({ title: (e as Error).message || "登录失败", icon: "none" });
    } finally {
      this.setData({ loading: false });
    }
  },
});

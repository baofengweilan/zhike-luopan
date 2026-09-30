import {
  Reminder,
  batchClassReminders,
  createHolidayReminders,
  deleteReminder,
  getSubscribeConfig,
  listReminders,
  listSemesters,
  recordSubscribe,
} from "../../utils/api";
import { logger } from "../../utils/logger";

const TYPE_LABELS: Record<string, string> = {
  class_change: "课前提醒",
  holiday: "假期提醒",
  season_switch: "时令切换",
  task: "任务提醒",
};

Page({
  data: {
    semesterId: "",
    reminders: [] as (Reminder & { typeLabel: string; timeLabel: string; statusLabel: string })[],
    wxConfigured: false,
    templates: [] as string[],
    generating: false,
  },

  onShow() {
    this.init();
  },

  async init() {
    try {
      const active = (await listSemesters()).find((s) => s.is_active);
      this.setData({ semesterId: active?.id ?? "" });
      const config = await getSubscribeConfig();
      this.setData({ wxConfigured: config.wx_configured, templates: config.templates });
      await this.load();
    } catch (e) {
      logger.error("reminders", "初始化失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  async load() {
    try {
      const reminders = await listReminders();
      this.setData({
        reminders: reminders.map((r) => ({
          ...r,
          typeLabel: TYPE_LABELS[r.reminder_type] ?? r.reminder_type,
          timeLabel: r.trigger_time.slice(5, 16).replace("T", " ").replace("-", "/"),
          statusLabel:
            r.status === "sent"
              ? r.channel === "wechat"
                ? "已推送"
                : "站内提醒"
              : "待发送",
        })),
      });
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  /** 一键生成未来 7 天课前提醒（A16，幂等） */
  async onGenerateClass() {
    if (!this.data.semesterId) {
      wx.showToast({ title: "先创建当前学期", icon: "none" });
      return;
    }
    this.setData({ generating: true });
    try {
      const r = await batchClassReminders(this.data.semesterId, 7, 30);
      wx.showToast({ title: `新建 ${r.created} 条`, icon: "none" });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    } finally {
      this.setData({ generating: false });
    }
  },

  /** 假期/时令切换提醒（A17/A18） */
  async onGenerateHoliday() {
    if (!this.data.semesterId) {
      wx.showToast({ title: "先创建当前学期", icon: "none" });
      return;
    }
    try {
      const r = await createHolidayReminders(this.data.semesterId);
      wx.showToast({ title: `新建 ${r.created} 条`, icon: "none" });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  /**
   * 微信订阅授权（A16 的推送侧）。
   * 一次性订阅：每次授权只能发一条，提示用户多选几次攒额度；
   * 无微信密钥（mock 模式）时隐藏按钮——授权动线真实上线后才开放。
   */
  async onSubscribe() {
    if (this.data.templates.length === 0) return;
    try {
      const res = await wx.requestSubscribeMessage({ tmplIds: this.data.templates });
      logger.info("reminders", "订阅授权结果", res);
      for (const tplId of this.data.templates) {
        if (res[tplId] === "accept") {
          await recordSubscribe(tplId, 1);
        }
      }
      wx.showToast({ title: "授权已记录", icon: "success" });
    } catch (e) {
      logger.warn("reminders", "授权失败或取消", e);
    }
  },

  onDelete(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除提醒",
      content: "确定删除这条提醒？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteReminder(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

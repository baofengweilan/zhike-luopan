import {
  Semester,
  activateSemester,
  createSemester,
  deleteSemester,
  listSemesters,
} from "../../utils/api";
import { logger } from "../../utils/logger";

function today(): string {
  const d = new Date();
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

Page({
  data: {
    semesters: [] as Semester[],
    showForm: false,
    form: { name: "", start_date: today(), end_date: "", total_weeks: 18 },
    today: today(),
    submitting: false,
  },

  onShow() {
    this.load();
  },

  async load() {
    try {
      this.setData({ semesters: await listSemesters() });
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  toggleForm() {
    this.setData({ showForm: !this.data.showForm });
  },

  onField(e: WechatMiniprogram.Input) {
    this.setData({ [`form.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  onDate(e: WechatMiniprogram.PickerChange) {
    this.setData({ [`form.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  /**
   * 第 1 周 = start_date 所在完整自然周（周一起算），软性提示建议选周一。
   */
  getWeekdayHint(): string {
    const { start_date } = this.data.form;
    if (!start_date) return "";
    // 标准 ISO 构造（schedule.ts mondayOf 同款坑：- 换 / 再拼 T 会得到 Invalid Date）
    const d = new Date(`${start_date}T00:00:00`);
    return d.getDay() === 1 ? "" : "提示：建议学期开始日选周一，周次计算更直观";
  },

  async onSubmit() {
    const f = this.data.form;
    if (!f.name || !f.start_date || !f.end_date) {
      wx.showToast({ title: "请填写完整", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      await createSemester({
        name: f.name,
        start_date: f.start_date,
        end_date: f.end_date,
        total_weeks: Number(f.total_weeks) || 18,
      });
      this.setData({
        showForm: false,
        form: { name: "", start_date: today(), end_date: "", total_weeks: 18 },
      });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  },

  async onActivate(e: WechatMiniprogram.Touch) {
    try {
      await activateSemester(e.currentTarget.dataset.id);
      await this.load();
    } catch (err) {
      wx.showToast({ title: (err as Error).message, icon: "none" });
    }
  },

  onDelete(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除学期",
      content: "学期下的时令、节次会一并删除，确定？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteSemester(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },

  goSeasons(e: WechatMiniprogram.Touch) {
    wx.navigateTo({ url: `/pages/seasons/seasons?semesterId=${e.currentTarget.dataset.id}` });
  },

  goCalendar(e: WechatMiniprogram.Touch) {
    wx.navigateTo({ url: `/pages/calendar/calendar?semesterId=${e.currentTarget.dataset.id}` });
  },

  goTemplates(e: WechatMiniprogram.Touch) {
    wx.navigateTo({ url: `/pages/templates/templates?semesterId=${e.currentTarget.dataset.id}` });
  },

  goSchedule(e: WechatMiniprogram.Touch) {
    // 课表已是 tab 页（ADR 0006）：navigateTo 携参非法，学期上下文走 globalData
    const semesterId = String(e.currentTarget.dataset.id);
    logger.debug("semesters", "跳转课表 tab，携带学期", semesterId);
    getApp<IAppOption>().globalData.pendingSemesterId = semesterId;
    wx.switchTab({ url: "/pages/schedule/schedule" });
  },
});

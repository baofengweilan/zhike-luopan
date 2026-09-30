import { Bell, createBell, deleteBell, hhmm, listBells } from "../../utils/api";

interface TimelineRow extends Bell {
  label: string;
  startTime: string;
  endTime: string;
}

Page({
  data: {
    seasonId: "",
    seasonLabel: "",
    timeline: [] as TimelineRow[],
    form: { period_number: "", start_time: "08:00", end_time: "08:45", is_break: false },
    submitting: false,
  },

  onLoad(options: { seasonId?: string; seasonName?: string }) {
    this.setData({
      seasonId: options.seasonId ?? "",
      seasonLabel: decodeURIComponent(options.seasonName ?? ""),
    });
    wx.setNavigationBarTitle({ title: `${this.data.seasonLabel} · 作息` });
  },

  onShow() {
    this.load();
  },

  async load() {
    try {
      const bells = await listBells(this.data.seasonId);
      this.setData({
        timeline: bells.map((b) => ({
          ...b,
          label: b.is_break ? "课间" : `第 ${b.period_number} 节`,
          startTime: hhmm(b.start_time),
          endTime: hhmm(b.end_time),
        })),
      });
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  onField(e: WechatMiniprogram.Input) {
    this.setData({ [`form.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  onTime(e: WechatMiniprogram.PickerChange) {
    this.setData({ [`form.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  onBreakToggle() {
    this.setData({ "form.is_break": !this.data.form.is_break });
  },

  async onSubmit() {
    const f = this.data.form;
    const period = Number(f.period_number);
    if (!period || period < 1) {
      wx.showToast({ title: "请填写节次序号", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      await createBell(this.data.seasonId, {
        period_number: period,
        start_time: f.start_time,
        end_time: f.end_time,
        is_break: f.is_break,
      });
      this.setData({ form: { period_number: "", start_time: "08:00", end_time: "08:45", is_break: false } });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  },

  onDelete(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除节次",
      content: "确定删除这一节的时间安排？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteBell(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

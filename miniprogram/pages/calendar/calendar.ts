import {
  DAY_TYPE_LABELS,
  Override,
  WEEKDAY_LABELS,
  createOverride,
  deleteOverride,
  listOverrides,
  syncHolidays,
} from "../../utils/api";

const DAY_TYPES = ["holiday", "workday", "school_holiday", "temp_cancel"];

Page({
  data: {
    semesterId: "",
    overrides: [] as (Override & { typeLabel: string; followLabel: string })[],
    form: { date: "", day_type: "", follow_weekday: -1, note: "" },
    dayTypes: DAY_TYPES.map((t) => ({ value: t, label: DAY_TYPE_LABELS[t] })),
    weekdays: WEEKDAY_LABELS,
    submitting: false,
  },

  onLoad(options: { semesterId?: string }) {
    this.setData({ semesterId: options.semesterId ?? "" });
  },

  onShow() {
    this.load();
  },

  async load() {
    try {
      const overrides = await listOverrides(this.data.semesterId);
      this.setData({
        overrides: overrides.map((o) => ({
          ...o,
          typeLabel: DAY_TYPE_LABELS[o.day_type] ?? o.day_type,
          followLabel:
            o.day_type === "workday" && o.follow_weekday !== null
              ? `按${WEEKDAY_LABELS[o.follow_weekday]}课表`
              : "",
        })),
      });
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  onDate(e: WechatMiniprogram.PickerChange) {
    this.setData({ "form.date": e.detail.value });
  },

  onType(e: WechatMiniprogram.PickerChange) {
    const idx = Number(e.detail.value);
    this.setData({ "form.day_type": this.data.dayTypes[idx].value });
  },

  onFollow(e: WechatMiniprogram.PickerChange) {
    this.setData({ "form.follow_weekday": Number(e.detail.value) });
  },

  onNote(e: WechatMiniprogram.Input) {
    this.setData({ "form.note": e.detail.value });
  },

  async onSubmit() {
    const f = this.data.form;
    if (!f.date || !f.day_type) {
      wx.showToast({ title: "请选择日期和类型", icon: "none" });
      return;
    }
    if (f.day_type === "workday" && f.follow_weekday < 0) {
      wx.showToast({ title: "补班日需选择按周几课表", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      await createOverride(this.data.semesterId, {
        date: f.date,
        day_type: f.day_type,
        follow_weekday: f.day_type === "workday" ? f.follow_weekday : null,
        note: f.note || null,
      });
      this.setData({ form: { date: "", day_type: "", follow_weekday: -1, note: "" } });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  },

  async onSync() {
    try {
      const { added } = await syncHolidays(this.data.semesterId);
      wx.showToast({ title: added > 0 ? `已同步 ${added} 天` : "已是最新", icon: "none" });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  onDelete(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除覆盖",
      content: "删除后该日期恢复按常规课表执行，确定？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteOverride(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

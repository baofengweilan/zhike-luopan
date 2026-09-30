import { SEASON_LABELS, Season, createSeason, deleteSeason, listSeasons } from "../../utils/api";

const ALL_SEASONS = ["spring", "summer", "autumn", "winter"];

Page({
  data: {
    semesterId: "",
    seasons: [] as Season[],
    /** 尚未创建的时令，供下拉选择 */
    remaining: [] as { name: string; label: string }[],
    form: { name: "", start_date: "", end_date: "" },
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
      const seasons = await listSeasons(this.data.semesterId);
      this.setData({ seasons });
      this.recomputeRemaining();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  recomputeRemaining() {
    const used = new Set(this.data.seasons.map((s) => s.name));
    this.setData({
      remaining: ALL_SEASONS.filter((n) => !used.has(n)).map((n) => ({
        name: n,
        label: SEASON_LABELS[n],
      })),
    });
  },

  onName(e: WechatMiniprogram.PickerChange) {
    this.setData({ "form.name": e.detail.value });
  },

  onDate(e: WechatMiniprogram.PickerChange) {
    this.setData({ [`form.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  async onSubmit() {
    const f = this.data.form;
    if (!f.name || !f.start_date || !f.end_date) {
      wx.showToast({ title: "请选择时令和日期区间", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      await createSeason(this.data.semesterId, f);
      this.setData({ form: { name: "", start_date: "", end_date: "" } });
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
      title: "删除时令",
      content: "该时令下的节次时间表会一并删除，确定？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteSeason(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },

  goBells(e: WechatMiniprogram.Touch) {
    const { id, name } = e.currentTarget.dataset;
    wx.navigateTo({
      url: `/pages/bells/bells?seasonId=${id}&seasonName=${encodeURIComponent(name)}`,
    });
  },
});

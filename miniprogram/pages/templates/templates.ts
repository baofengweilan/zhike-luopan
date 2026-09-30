import {
  PATTERN_LABELS,
  Template,
  WEEKDAY_LABELS,
  createTemplate,
  deleteTemplate,
  listTemplates,
} from "../../utils/api";

const PATTERNS = ["all", "odd", "even", "custom"];

Page({
  data: {
    semesterId: "",
    /** 按 weekday 分组：[{ weekday, label, items }] */
    groups: [] as { weekday: number; label: string; items: Template[] }[],
    weekdays: WEEKDAY_LABELS,
    patterns: PATTERNS.map((p) => ({
      value: p,
      label: p === "custom" ? "自定义周区间" : PATTERN_LABELS[p],
    })),
    form: {
      weekday: -1,
      period_number: "",
      pattern: "",
      pattern_label: "",
      custom_pattern: "",
      course_name: "",
      location: "",
      teacher: "",
    },
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
      const templates = await listTemplates(this.data.semesterId);
      const groups = WEEKDAY_LABELS.map((label, weekday) => ({
        weekday,
        label,
        items: templates
          .filter((t) => t.weekday === weekday)
          .map((t) => ({ ...t, patternLabel: PATTERN_LABELS[t.week_pattern] ?? t.week_pattern })),
      })).filter((g) => g.items.length > 0);
      this.setData({ groups });
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  onField(e: WechatMiniprogram.Input) {
    this.setData({ [`form.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  onWeekday(e: WechatMiniprogram.PickerChange) {
    this.setData({ "form.weekday": Number(e.detail.value) });
  },

  onPattern(e: WechatMiniprogram.PickerChange) {
    const picked = this.data.patterns[Number(e.detail.value)];
    this.setData({ "form.pattern": picked.value, "form.pattern_label": picked.label });
  },

  async onSubmit() {
    const f = this.data.form;
    if (f.weekday < 0 || !f.course_name || !f.period_number) {
      wx.showToast({ title: "请填星期、节次和课程名", icon: "none" });
      return;
    }
    const pattern = f.pattern === "custom" ? f.custom_pattern.trim() : f.pattern || "all";
    if (f.pattern === "custom" && !pattern) {
      wx.showToast({ title: "请填写周区间，如 1-8,10-16", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      await createTemplate(this.data.semesterId, {
        weekday: f.weekday,
        period_number: Number(f.period_number),
        week_pattern: pattern,
        course_name: f.course_name,
        location: f.location || null,
        teacher: f.teacher || null,
      });
      this.setData({
        form: {
          weekday: -1,
          period_number: "",
          pattern: "",
          pattern_label: "",
          custom_pattern: "",
          course_name: "",
          location: "",
          teacher: "",
        },
      });
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
      title: "删除模板",
      content: "重新生成实例课表后该课不再出现，确定？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteTemplate(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

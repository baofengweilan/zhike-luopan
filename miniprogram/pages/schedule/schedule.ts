import {
  Adjustment,
  FEEDBACK_TYPE_LABELS,
  Instance,
  adjustInstance,
  createFeedback,
  feedbackToConstraint,
  generateInstances,
  hhmm,
  listAdjustments,
  listInstances,
  listSemesters,
  rollbackAdjustment,
} from "../../utils/api";
import { ApiError } from "../../utils/request";
import { logger } from "../../utils/logger";

interface DayItem {
  date: string;
  weekdayLabel: string;
  dayLabel: string;
  isToday: boolean;
  items: (Instance & { startTime: string; endTime: string; statusLabel: string })[];
}

type PopupView = "detail" | "adjust" | "feedback" | "feedbackDone" | "history";

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const STATUS_LABELS: Record<string, string> = {
  adjusted: "已调整",
  cancelled: "已取消",
};

function fmt(d: Date): string {
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 本周周一：周日按 7 算（与 CONTEXT.md"第 1 周"同款锚定习惯） */
function mondayOf(dateStr: string): Date {
  const d = new Date(`${dateStr.replace(/-/g, "/")}T00:00:00`);
  const day = d.getDay() === 0 ? 7 : d.getDay();
  d.setDate(d.getDate() - (day - 1));
  return d;
}

function shift(dateStr: string, days: number): string {
  const d = new Date(`${dateStr.replace(/-/g, "/")}T00:00:00`);
  d.setDate(d.getDate() + days);
  return fmt(d);
}

Page({
  data: {
    semesterId: "",
    mode: "day" as "day" | "week",
    currentDate: fmt(new Date()),
    today: fmt(new Date()),
    dayItems: [] as DayItem["items"],
    week: [] as DayItem[],
    // ---- 详情弹层（任务书 3.8 详情 + 阶段五调整/反馈/历史动线） ----
    selected: null as DayItem["items"][number] | null,
    popupView: "detail" as PopupView,
    conflicts: [] as string[], // A14：后端 409 带回的冲突描述，渲染给用户决策
    adjustForm: { new_date: "", new_period: "", new_location: "", reason: "", force: false },
    feedbackForm: { type: "", desc: "" },
    feedbackTypes: Object.entries(FEEDBACK_TYPE_LABELS).map(([value, label]) => ({ value, label })),
    feedbackId: "",
    feedbackResult: "",
    history: [] as Adjustment[],
  },

  onLoad(options: { semesterId?: string }) {
    if (options.semesterId) {
      this.setData({ semesterId: options.semesterId });
      this.load();
    } else {
      // 未指定学期：取当前激活学期
      listSemesters()
        .then((semesters) => {
          const active = semesters.find((s) => s.is_active);
          if (!active) {
            wx.showToast({ title: "请先创建学期", icon: "none" });
            setTimeout(() => wx.navigateBack(), 800);
            return;
          }
          this.setData({ semesterId: active.id });
          this.load();
        })
        .catch((e) => wx.showToast({ title: (e as Error).message, icon: "none" }));
    }
  },

  setMode(e: WechatMiniprogram.Touch) {
    this.setData({ mode: e.currentTarget.dataset.mode });
    this.load();
  },

  onPrev() {
    this.setData({ currentDate: shift(this.data.currentDate, this.data.mode === "week" ? -7 : -1) });
    this.load();
  },

  onNext() {
    this.setData({ currentDate: shift(this.data.currentDate, this.data.mode === "week" ? 7 : 1) });
    this.load();
  },

  onToday() {
    this.setData({ currentDate: this.data.today });
    this.load();
  },

  async load() {
    const { semesterId, currentDate, today } = this.data;
    const monday = fmt(mondayOf(currentDate));
    const sunday = shift(monday, 6);
    try {
      const instances = await listInstances(semesterId, monday, sunday);
      const week: DayItem[] = [];
      for (let i = 0; i < 7; i++) {
        const date = shift(monday, i);
        week.push({
          date,
          weekdayLabel: WEEKDAYS[i],
          dayLabel: date.slice(5).replace("-", "/"),
          isToday: date === today,
          items: instances
            .filter((inst) => inst.date === date)
            .map((inst) => ({
              ...inst,
              startTime: hhmm(inst.start_time),
              endTime: hhmm(inst.end_time),
              statusLabel: STATUS_LABELS[inst.status] ?? "",
            })),
        });
      }
      const current = week.find((x) => x.date === currentDate) ?? week[0];
      this.setData({ week, dayItems: current?.items ?? [] });
    } catch (e) {
      logger.error("schedule", "加载课表失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  async onRegenerate() {
    try {
      const r = await generateInstances(this.data.semesterId);
      wx.showToast({ title: `已生成 ${r.created} 节课`, icon: "none" });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  onPickDay(e: WechatMiniprogram.Touch) {
    this.setData({ currentDate: e.currentTarget.dataset.date, mode: "day" });
    this.load();
  },

  // ==== 弹层入口 ====

  onShowDetail(e: WechatMiniprogram.Touch) {
    const instance =
      this.data.dayItems.find((i) => i.id === e.currentTarget.dataset.id) ??
      this.data.week.flatMap((d) => d.items).find((i) => i.id === e.currentTarget.dataset.id);
    if (!instance) return;
    logger.debug("schedule", "打开详情弹层", instance.id);
    this.setData({
      selected: instance,
      popupView: "detail",
      conflicts: [],
      history: [],
      adjustForm: {
        new_date: instance.date,
        new_period: "",
        new_location: "",
        reason: "",
        force: false,
      },
      feedbackForm: { type: "", desc: "" },
    });
  },

  onCloseDetail() {
    this.setData({ selected: null });
  },

  switchView(e: WechatMiniprogram.Touch) {
    const view = e.currentTarget.dataset.view as PopupView;
    this.setData({ popupView: view, conflicts: [] });
    if (view === "history") this.loadHistory();
  },

  // ---- 调整（A14：点击调整 + 实时冲突提示） ----

  onAdjustField(e: WechatMiniprogram.Input) {
    this.setData({ [`adjustForm.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  onAdjustDate(e: WechatMiniprogram.PickerChange) {
    this.setData({ "adjustForm.new_date": e.detail.value });
  },

  onForceToggle() {
    this.setData({ "adjustForm.force": !this.data.adjustForm.force });
  },

  async onAdjustSubmit() {
    const form = this.data.adjustForm;
    const selected = this.data.selected;
    if (!selected) return;
    if (!form.new_date) {
      wx.showToast({ title: "请选择日期", icon: "none" });
      return;
    }
    const payload: Record<string, unknown> = {
      new_date: form.new_date,
      reason: form.reason || undefined,
      force: form.force,
    };
    if (form.new_period) payload.new_period = Number(form.new_period);
    if (form.new_location) payload.new_location = form.new_location;
    logger.debug("schedule", "提交调整", payload);
    try {
      const result = await adjustInstance(selected.id, payload);
      logger.info("schedule", "调整成功", result.summary);
      wx.showToast({ title: "已调整", icon: "success" });
      this.setData({ selected: null, popupView: "detail" });
      await this.load();
    } catch (err) {
      // A14：409 带回结构化冲突列表 → 渲染在弹层里；软冲突可勾"强行应用"重试
      if (err instanceof ApiError && err.statusCode === 409) {
        const detail = err.detail as { conflicts?: string[] };
        this.setData({ conflicts: detail?.conflicts ?? [err.message] });
        return;
      }
      wx.showToast({ title: (err as Error).message, icon: "none" });
    }
  },

  async onCancelClass() {
    const selected = this.data.selected;
    if (!selected) return;
    wx.showModal({
      title: "取消本节",
      content: `确定取消「${selected.course_name}」这节课？`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adjustInstance(selected.id, { cancel: true, reason: "手动取消" });
          wx.showToast({ title: "已取消", icon: "success" });
          this.setData({ selected: null });
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },

  // ---- 反馈纠错（A23） ----

  onFeedbackType(e: WechatMiniprogram.PickerChange) {
    this.setData({ "feedbackForm.type": this.data.feedbackTypes[Number(e.detail.value)].value });
  },

  onFeedbackDesc(e: WechatMiniprogram.Input) {
    this.setData({ "feedbackForm.desc": e.detail.value });
  },

  async onFeedbackSubmit() {
    const { type, desc } = this.data.feedbackForm;
    const selected = this.data.selected;
    if (!selected || !type || !desc.trim()) {
      wx.showToast({ title: "请选择类型并描述问题", icon: "none" });
      return;
    }
    try {
      const fb = await createFeedback({
        semester_id: this.data.semesterId,
        instance_id: selected.id,
        feedback_type: type,
        description: desc,
      });
      logger.info("schedule", "反馈已提交", fb.id);
      this.setData({ popupView: "feedbackDone", feedbackId: fb.id, feedbackResult: "" });
    } catch (err) {
      wx.showToast({ title: (err as Error).message, icon: "none" });
    }
  },

  /** 一键转约束：反馈 → avoid 约束 / 校历覆盖 → 课表立即变化（演示动线核心） */
  async onFeedbackToConstraint() {
    try {
      const result = await feedbackToConstraint(this.data.feedbackId);
      logger.info("schedule", "反馈已转约束", result.constraint_json);
      this.setData({ feedbackResult: "已转为约束并重新生成课表！" });
      await this.load();
    } catch (err) {
      this.setData({ feedbackResult: (err as Error).message });
    }
  },

  // ---- 调整历史 + 回滚（A15） ----

  async loadHistory() {
    const selected = this.data.selected;
    if (!selected) return;
    try {
      this.setData({ history: await listAdjustments(selected.id) });
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  async onRollback(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "回滚调整",
      content: "把这节课恢复到这次调整之前的状态？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await rollbackAdjustment(id);
          wx.showToast({ title: "已回滚", icon: "success" });
          this.setData({ selected: null });
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

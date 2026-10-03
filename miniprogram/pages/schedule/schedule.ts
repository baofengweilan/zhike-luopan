import {
  Adjustment,
  FEEDBACK_TYPE_LABELS,
  ImportedCourse,
  Instance,
  adjustInstance,
  createFeedback,
  feedbackToConstraint,
  generateInstances,
  hhmm,
  importScheduleApply,
  importScheduleParse,
  listAdjustments,
  listInstances,
  listSemesters,
  rollbackAdjustment,
} from "../../utils/api";
import { AdjustSuggestion } from "../../utils/api";
import { ApiError } from "../../utils/request";
import { getToken } from "../../utils/token";
import { logger } from "../../utils/logger";

interface DayItem {
  date: string;
  weekdayLabel: string;
  dayLabel: string;
  isToday: boolean;
  items: LessonItem[];
}

/** 单节课渲染项：Instance + 格式化时间/状态 + 当前节/下一节高亮标记（ADR 0006 首屏信息） */
type LessonItem = Instance & {
  startTime: string;
  endTime: string;
  statusLabel: string;
  isCurrent: boolean;
  isNext: boolean;
};

type PopupView = "detail" | "adjust" | "feedback" | "feedbackDone" | "history";

/** 周网格课程卡（ADR 0009 §4 完美校园风格）：按星期列 × 节次行绝对定位 */
interface GridCourse {
  id: string;
  course_name: string;
  location: string;
  color: string;
  cancelled: boolean;
  col: number; // 0-6 周一为 0
  left: number; // 定位百分比（列宽 = 100/7 %）
  width: number;
  top: number; // rpx（ROW_H × (起始节-1)）
  height: number; // rpx（ROW_H × 连堂数 - 卡片间隙）
}

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

// 周网格几何常量（rpx）：与 wxss 里 .grid-card/.grid-times 行高保持一致
const GRID_ROW_H = 108;
const GRID_MAX_PERIOD = 12; // 行数上限（一般作息 ≤ 12 节）
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
  // 注意：必须用 "YYYY-MM-DDT00:00:00"（标准 ISO）构造。
  // 旧写法把 - 换成 / 再拼 T（"2026/10/01T00:00:00"）是非法混合格式，
  // 部分引擎（含开发者工具模拟器）直接返回 Invalid Date → 全页日期 NaN。
  const d = new Date(`${dateStr}T00:00:00`);
  const day = d.getDay() === 0 ? 7 : d.getDay();
  d.setDate(d.getDate() - (day - 1));
  return d;
}

function shift(dateStr: string, days: number): string {
  // 同 mondayOf：保持标准 ISO 格式，不要做 - → / 替换
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + days);
  return fmt(d);
}

/** "HH:MM" → 当日分钟数，用于当前节/下一节判定 */
function toMin(hhmmStr: string): number {
  const [h, m] = hhmmStr.split(":").map(Number);
  return h * 60 + m;
}

Page({
  data: {
    semesterId: "",
    baseUrl: "", // 教材封面等静态资源走后端 /uploads/
    // 无任何学期时的首屏引导态（ADR 0006：入口不灰置，给创建学期的主动作）
    noSemester: false,
    mode: "week" as "day" | "week", // ADR 0009 §4：周网格为默认首屏（课表即首页）
    currentDate: fmt(new Date()),
    today: fmt(new Date()),
    dayItems: [] as DayItem["items"],
    week: [] as DayItem[],
    // ---- 周网格（ADR 0009 §4）：彩色课程卡 + 节次时间轴 + 周次角标 ----
    weekNo: 0, // 当前查看的是第几周（0 = 不在学期范围内）
    gridPeriods: [] as number[],
    gridTimes: [] as string[], // 与 gridPeriods 一一对应的作息开始时间（无数据留空）
    gridCourses: [] as GridCourse[],
    semesterStart: "",
    totalWeeks: 0,
    // ---- 详情弹层（任务书 3.8 详情 + 阶段五调整/反馈/历史动线） ----
    selected: null as DayItem["items"][number] | null,
    popupView: "detail" as PopupView,
    conflicts: [] as string[], // A14：后端 409 带回的冲突描述，渲染给用户决策
    suggestions: [] as AdjustSuggestion[], // A21：AI 调课建议（无冲突候选时段）
    adjustForm: { new_date: "", new_period: "", new_location: "", reason: "", force: false },
    feedbackForm: { type: "", desc: "" },
    feedbackTypes: Object.entries(FEEDBACK_TYPE_LABELS).map(([value, label]) => ({ value, label })),
    feedbackId: "",
    feedbackResult: "",
    history: [] as Adjustment[],
    // ---- ADR 0009：导入确认卡片（草稿 → 执行才入库） ----
    importCard: {
      visible: false,
      importing: false,
      filename: "",
      rows: [] as string[], // 每门课一行的人类可读摘要
      warnings: [] as string[],
      courses: [] as ImportedCourse[],
      clearExisting: false,
    },
  },

  onLoad(options: { semesterId?: string }) {
    this.setData({ baseUrl: getApp<IAppOption>().globalData.baseUrl });
    // 兼容旧路径携带 ?semesterId=（tab 页正常入口是 onShow + globalData，见 ADR 0006）
    if (options.semesterId) {
      logger.debug("schedule", "onLoad 携带学期参数，转入 pendingSemesterId", options.semesterId);
      getApp<IAppOption>().globalData.pendingSemesterId = options.semesterId;
    }
  },

  onShow() {
    // tab 页每次切回都触发：登录守卫 → 重新解析学期上下文 → 刷新数据
    // （顺带重算"当前节"高亮，回到首屏看到的永远是此刻的课表）
    if (!getToken()) {
      logger.debug("schedule", "无 token，跳登录页");
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    const app = getApp<IAppOption>();
    const pending = app.globalData.pendingSemesterId;
    if (pending) {
      logger.debug("schedule", "取走跨页学期上下文", pending);
      app.globalData.pendingSemesterId = "";
    }
    this.resolveSemester(pending);
  },

  /**
   * 解析学期上下文（ADR 0006）：优先用跨页传入的学期，否则取当前激活学期。
   * 无任何学期时进入首屏引导态——不灰置、不 toast 踢回，给"创建学期"的主动作。
   */
  async resolveSemester(preferredId: string) {
    try {
      const semesters = await listSemesters();
      const target =
        semesters.find((s) => s.id === preferredId) ?? semesters.find((s) => s.is_active);
      if (!target) {
        logger.debug("schedule", "无学期，进入首屏引导态");
        this.setData({ noSemester: true, semesterId: "", dayItems: [], week: [] });
        return;
      }
      if (target.id !== this.data.semesterId) {
        logger.debug("schedule", "切换学期上下文", { from: this.data.semesterId, to: target.id });
        // 换学期时把日期拨回今天，避免停在上个学期翻到的页
        this.setData({
          noSemester: false,
          semesterId: target.id,
          currentDate: this.data.today,
          semesterStart: target.start_date,
          totalWeeks: target.total_weeks,
        });
      } else {
        this.setData({ noSemester: false });
      }
      await this.load();
    } catch (e) {
      logger.error("schedule", "解析学期失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  /** 首屏引导卡 → 学期管理（navigateTo 合法：semesters 不是 tab 页） */
  goCreateSemester() {
    logger.debug("schedule", "引导卡点击 → 学期管理");
    wx.navigateTo({ url: "/pages/semesters/semesters" });
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
              // 高亮标记由 markNow() 在 setData 前计算
              isCurrent: false,
              isNext: false,
            })),
        });
      }
      const current = week.find((x) => x.date === currentDate) ?? week[0];
      const dayItems = current?.items ?? [];
      this.markNow(dayItems);
      const grid = this.buildGrid(instances, monday);
      this.setData({ week, dayItems, ...grid });
    } catch (e) {
      logger.error("schedule", "加载课表失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  /**
   * 构建周网格数据（ADR 0009 §4 完美校园风格）。
   * 实例是单节的，同一天相邻同名的连堂课合并为一张跨行卡片；
   * 已取消的课保留灰色卡片（时间轴完整，也符合"这节被调走了"的心智）。
   */
  buildGrid(instances: Instance[], monday: string): {
    weekNo: number;
    gridPeriods: number[];
    gridTimes: string[];
    gridCourses: GridCourse[];
  } {
    // 周次角标：查看周的周一相对学期首周周一的偏移；不在范围内显示 0（前端隐藏）
    let weekNo = 0;
    if (this.data.semesterStart) {
      const startMonday = fmt(mondayOf(this.data.semesterStart));
      const diff = Math.round((new Date(`${monday}T00:00:00`).getTime() - new Date(`${startMonday}T00:00:00`).getTime()) / 86400000);
      const no = Math.round(diff / 7) + 1;
      weekNo = no >= 1 && no <= this.data.totalWeeks ? no : 0;
    }

    // 节次行：1..max(12, 本周实际最大节次)；时间轴取该节次本周第一次出现的开始时间
    const maxPeriod = instances.reduce((m, i) => Math.max(m, i.period_number), 0);
    const periods: number[] = [];
    const times: string[] = [];
    const timeMap = new Map<number, string>();
    for (const inst of instances) {
      if (!timeMap.has(inst.period_number)) timeMap.set(inst.period_number, hhmm(inst.start_time));
    }
    for (let p = 1; p <= Math.max(GRID_MAX_PERIOD, maxPeriod); p++) {
      periods.push(p);
      times.push(timeMap.get(p) ?? "");
    }

    // 单节实例 → 网格卡片；同日相邻同名连堂合并（跨度 = 节数）
    type Merged = { inst: Instance; col: number; span: number };
    const byKey = new Map<string, Merged>();
    for (const inst of instances) {
      const d = new Date(`${inst.date}T00:00:00`);
      const col = (d.getDay() === 0 ? 7 : d.getDay()) - 1;
      const key = `${inst.date}|${inst.course_name}|${inst.location ?? ""}|${inst.status}`;
      const prev = byKey.get(key);
      if (prev && prev.inst.period_number + prev.span === inst.period_number) {
        prev.span += 1; // 相邻同槽连堂 → 延伸卡片
      } else {
        byKey.set(key, { inst, col, span: 1 });
      }
    }
    const colW = 100 / 7;
    const gridCourses: GridCourse[] = [...byKey.values()].map(({ inst, col, span }) => ({
      id: inst.id,
      course_name: inst.course_name,
      location: inst.location ?? "",
      color: inst.color,
      cancelled: inst.status === "cancelled",
      col,
      left: col * colW,
      width: colW,
      top: (inst.period_number - 1) * GRID_ROW_H,
      height: span * GRID_ROW_H - 8,
    }));
    logger.debug("schedule", "周网格构建", {
      实例: instances.length,
      卡片: gridCourses.length,
      节次行: periods.length,
      周次: weekNo,
    });
    return { weekNo, gridPeriods: periods, gridTimes: times, gridCourses };
  },

  /**
   * 当前节/下一节高亮（ADR 0006"课表即首页"首屏信息）。
   * 仅当天生效：正在进行的节标 isCurrent，当天第一节日时间未到的节标 isNext。
   * 已取消的课也按原时间参与"下一节"判定，保持时间轴与真实作息一致。
   * 直接在传入对象上打标（与 week 内同引用，setData 前完成即可）。
   */
  markNow(items: LessonItem[]) {
    if (items.length === 0) return;
    const isToday = this.data.currentDate === this.data.today;
    const now = new Date();
    const nowMin = now.getHours() * 60 + now.getMinutes();
    let nextPending = isToday;
    for (const it of items) {
      const start = toMin(it.startTime);
      const end = toMin(it.endTime);
      it.isCurrent = isToday && nowMin >= start && nowMin < end;
      it.isNext = nextPending && start > nowMin;
      if (it.isNext) nextPending = false;
    }
    logger.debug("schedule", "当前节高亮计算", {
      isToday,
      nowMin,
      currentCount: items.filter((i) => i.isCurrent).length,
      nextCount: items.filter((i) => i.isNext).length,
    });
  },

  /**
   * 导出 ICS → 分享文件（A35"订阅到日历"）。
   * ics 无法在小程序内直接打开（openDocument 不支持），可靠路径是
   * shareFileMessage 发给文件传输助手，手机上点开即导入系统日历。
   */
  onExportICS() {
    const baseUrl = getApp<IAppOption>().globalData.baseUrl;
    wx.downloadFile({
      url: `${baseUrl}/api/export/ics?semester_id=${this.data.semesterId}`,
      header: { Authorization: `Bearer ${getToken() ?? ""}` },
      success: (res) => {
        if (res.statusCode !== 200) {
          wx.showToast({ title: `导出失败（${res.statusCode}）`, icon: "none" });
          return;
        }
        logger.info("schedule", "ICS 已下载", res.tempFilePath);
        if (wx.shareFileMessage) {
          wx.shareFileMessage({
            filePath: res.tempFilePath,
            fileName: "我的课表.ics",
            success: () => wx.showToast({ title: "已发送，打开可导入日历", icon: "none" }),
            fail: () => wx.showToast({ title: "已取消分享", icon: "none" }),
          });
        } else {
          wx.showToast({ title: "当前微信版本不支持分享文件", icon: "none" });
        }
      },
      fail: (err) => {
        logger.error("schedule", "ICS 下载失败", err);
        wx.showToast({ title: "下载失败", icon: "none" });
      },
    });
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

  // ==== ADR 0009：文件导入课表（确认卡片流程） ====

  /** 入口：从微信聊天记录选课表文件（docx/xlsx/pdf/txt），图片路径赛后再接 */
  onImportTap() {
    wx.chooseMessageFile({
      count: 1,
      type: "file",
      extension: ["docx", "xlsx", "pdf", "txt"],
      success: async (res) => {
        const file = res.tempFiles[0];
        logger.debug("schedule", "选中课表文件", file.name);
        wx.showLoading({ title: "AI 识别中…" });
        try {
          const draft = await importScheduleParse(file.path);
          wx.hideLoading();
          // 每门课一行人类可读摘要：名称 · 周X 第a-b节 · 周次 · 地点
          const rows = draft.courses.map((c) => {
            const span =
              c.end_period && c.end_period !== c.start_period
                ? `${c.start_period}-${c.end_period}`
                : `${c.start_period}`;
            const parts = [
              `${c.course_name} · ${WEEKDAYS[c.weekday]} 第${span}节`,
              c.week_pattern === "all" ? "每周" : c.week_pattern === "odd" ? "单周" : c.week_pattern === "even" ? "双周" : `第${c.week_pattern}周`,
            ];
            if (c.location) parts.push(c.location);
            if (c.teacher) parts.push(c.teacher);
            return parts.join(" · ");
          });
          this.setData({
            importCard: {
              visible: true,
              importing: false,
              filename: draft.filename,
              rows,
              warnings: draft.warnings,
              courses: draft.courses,
              clearExisting: false,
            },
          });
        } catch (e) {
          wx.hideLoading();
          logger.error("schedule", "导入解析失败", e);
          wx.showToast({ title: (e as Error).message, icon: "none", duration: 3000 });
        }
      },
    });
  },

  onImportToggleClear() {
    this.setData({ "importCard.clearExisting": !this.data.importCard.clearExisting });
  },

  async onImportConfirm() {
    if (this.data.importCard.importing) return;
    this.setData({ "importCard.importing": true });
    try {
      const r = await importScheduleApply(
        this.data.semesterId,
        this.data.importCard.courses,
        this.data.importCard.clearExisting
      );
      logger.info("schedule", "导入入库完成", r);
      this.setData({ importCard: { ...this.data.importCard, visible: false, importing: false } });
      wx.showToast({ title: r.message, icon: "none", duration: 3000 });
      await this.load();
    } catch (e) {
      this.setData({ "importCard.importing": false });
      logger.error("schedule", "导入入库失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none", duration: 3000 });
    }
  },

  onImportCancel() {
    this.setData({ importCard: { ...this.data.importCard, visible: false } });
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

  /** 点选一条调课建议：直接把表单填成该时段（A21 动线闭环） */
  onPickSuggestion(e: WechatMiniprogram.Touch) {
    const s = this.data.suggestions[Number(e.currentTarget.dataset.index)];
    if (!s) return;
    logger.debug("schedule", "采纳调课建议", s);
    this.setData({
      "adjustForm.new_date": s.date,
      "adjustForm.new_period": String(s.period_number),
      conflicts: [],
    });
  },

  switchView(e: WechatMiniprogram.Touch) {
    const view = e.currentTarget.dataset.view as PopupView;
    this.setData({ popupView: view, conflicts: [], suggestions: [] });
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
        const detail = err.detail as { conflicts?: string[]; suggestions?: AdjustSuggestion[] };
        this.setData({
          conflicts: detail?.conflicts ?? [err.message],
          suggestions: detail?.suggestions ?? [],
        });
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

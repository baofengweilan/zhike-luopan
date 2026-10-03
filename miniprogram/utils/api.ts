import { request } from "./request";
import { getToken } from "./token";

export interface Semester {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  total_weeks: number;
  is_active: boolean;
}

export interface Season {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
}

export interface Bell {
  id: string;
  period_number: number;
  start_time: string; // "HH:MM:SS"
  end_time: string;
  is_break: boolean;
}

export const SEASON_LABELS: Record<string, string> = {
  spring: "春季作息",
  summer: "夏季作息",
  autumn: "秋季作息",
  winter: "冬季作息",
};

export const hhmm = (t: string) => t.slice(0, 5);

// ==== 学期 ====

export const listSemesters = () => request<Semester[]>("/api/semesters");

export const createSemester = (data: {
  name: string;
  start_date: string;
  end_date: string;
  total_weeks: number;
}) => request<Semester>("/api/semesters", { method: "POST", data });

export const activateSemester = (id: string) =>
  request<Semester>(`/api/semesters/${id}`, { method: "PUT", data: { is_active: true } });

export const deleteSemester = (id: string) =>
  request<void>(`/api/semesters/${id}`, { method: "DELETE" });

// ==== 时令 ====

export const listSeasons = (semesterId: string) =>
  request<Season[]>(`/api/semesters/${semesterId}/seasons`);

export const createSeason = (semesterId: string, data: { name: string; start_date: string; end_date: string }) =>
  request<Season>(`/api/semesters/${semesterId}/seasons`, { method: "POST", data });

export const deleteSeason = (id: string) =>
  request<void>(`/api/seasons/${id}`, { method: "DELETE" });

// ==== 节次 ====

export const listBells = (seasonId: string) =>
  request<Bell[]>(`/api/seasons/${seasonId}/bells`);

export const createBell = (
  seasonId: string,
  data: { period_number: number; start_time: string; end_time: string; is_break: boolean }
) => request<Bell>(`/api/seasons/${seasonId}/bells`, { method: "POST", data });

export const deleteBell = (id: string) => request<void>(`/api/bells/${id}`, { method: "DELETE" });

// ==== 校历 ====

export interface Override {
  id: string;
  date: string;
  day_type: string;
  follow_weekday: number | null;
  note: string | null;
}

export const DAY_TYPE_LABELS: Record<string, string> = {
  holiday: "法定假期",
  workday: "调休补班",
  school_holiday: "自定义放假",
  temp_cancel: "临时停课",
};

export const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export const listOverrides = (semesterId: string) =>
  request<Override[]>(`/api/semesters/${semesterId}/overrides`);

export const createOverride = (
  semesterId: string,
  data: { date: string; day_type: string; follow_weekday?: number | null; note?: string | null }
) => request<Override>(`/api/semesters/${semesterId}/overrides`, { method: "POST", data });

export const deleteOverride = (id: string) =>
  request<void>(`/api/overrides/${id}`, { method: "DELETE" });

export const syncHolidays = (semesterId: string) =>
  request<{ added: number }>(`/api/semesters/${semesterId}/holidays/sync`, { method: "POST" });

// ==== 模板课表 ====

export interface Template {
  id: string;
  weekday: number; // 0=周一
  period_number: number;
  week_pattern: string;
  course_name: string;
  location: string | null;
  teacher: string | null;
  color: string;
}

export const PATTERN_LABELS: Record<string, string> = {
  all: "每周",
  odd: "单周",
  even: "双周",
};

export const listTemplates = (semesterId: string) =>
  request<Template[]>(`/api/semesters/${semesterId}/templates`);

export const createTemplate = (
  semesterId: string,
  data: {
    weekday: number;
    period_number: number;
    week_pattern: string;
    course_name: string;
    location?: string | null;
    teacher?: string | null;
  }
) => request<Template>(`/api/semesters/${semesterId}/templates`, { method: "POST", data });

export const deleteTemplate = (id: string) =>
  request<void>(`/api/templates/${id}`, { method: "DELETE" });

// ==== 实例课表 ====

export interface Instance {
  id: string;
  date: string;
  period_number: number;
  start_time: string;
  end_time: string;
  course_name: string;
  location: string | null;
  teacher: string | null;
  color: string;
  status: string;
}

export const listInstances = (semesterId: string, start: string, end: string) =>
  request<Instance[]>(`/api/semesters/${semesterId}/instances?start_date=${start}&end_date=${end}`);

export const generateInstances = (semesterId: string) =>
  request<{ created: number; skipped: number; version: number }>(
    `/api/semesters/${semesterId}/instances/generate`,
    { method: "POST" }
  );

// ==== AI 助手（阶段 3.5） ====

export interface ParseRuleResult {
  rule: { action: string; message?: string } | null;
  applied: boolean;
  message: string;
  regenerate: { created: number; skipped: number } | null;
}

export const aiParseRule = (semesterId: string, text: string) =>
  request<ParseRuleResult>("/api/ai/parse-rule", {
    method: "POST",
    data: { semester_id: semesterId, text },
  });

export const aiAsk = (semesterId: string | null, question: string) =>
  request<{ answer: string }>("/api/ai/ask", {
    method: "POST",
    data: { semester_id: semesterId, question },
  });

// ==== 实时调整 / 反馈（阶段五） ====

export interface Adjustment {
  id: string;
  instance_id: string;
  old_value: Record<string, string>;
  new_value: Record<string, string>;
  reason: string | null;
  source: string;
  created_at: string;
}

export interface AdjustPayload {
  new_date?: string;
  new_period?: number;
  new_location?: string;
  new_teacher?: string;
  cancel?: boolean;
  reason?: string;
  force?: boolean;
}

/** 409 冲突时后端返回 detail.message + detail.conflicts */
export const adjustInstance = (instanceId: string, payload: AdjustPayload) =>
  request<{ instance_id: string; status: string; summary: string }>(
    `/api/instances/${instanceId}/adjust`,
    { method: "POST", data: { ...payload } }
  );

export const listAdjustments = (instanceId: string) =>
  request<Adjustment[]>(`/api/instances/${instanceId}/adjustments`);

export const rollbackAdjustment = (adjustmentId: string) =>
  request<{ instance_id: string; version: number }>(
    `/api/adjustments/${adjustmentId}/rollback`,
    { method: "POST" }
  );

export const FEEDBACK_TYPE_LABELS: Record<string, string> = {
  wrong_time: "时间错了",
  wrong_holiday: "假期错了",
  wrong_week: "单双周错了",
  wrong_textbook: "教材错了",
};

export const createFeedback = (data: {
  semester_id: string;
  instance_id?: string;
  feedback_type: string;
  description: string;
}) => request<{ id: string }>("/api/feedback", { method: "POST", data });

export const feedbackToConstraint = (feedbackId: string) =>
  request<{ applied: boolean; constraint_json: Record<string, unknown> }>(
    `/api/feedback/${feedbackId}/to-constraint`,
    { method: "POST" }
  );

// ==== 教材 / 照片（阶段四） ====

export interface Textbook {
  id: string;
  isbn: string | null;
  title: string;
  author: string | null;
  publisher: string | null;
  edition: string | null;
  cover_local_path: string | null;
}

export interface ScanResult {
  isbn: string;
  status: "found" | "exists" | "need_manual";
  textbook: Textbook | null;
}

export const scanIsbn = (isbn: string) =>
  request<ScanResult>("/api/textbooks/scan", { method: "POST", data: { isbn } });

export const batchScanIsbn = (isbns: string[]) =>
  request<{ results: ScanResult[] }>("/api/textbooks/batch-scan", {
    method: "POST",
    data: { isbns },
  });

export const listTextbooks = () => request<Textbook[]>("/api/textbooks");

export const createTextbook = (data: {
  isbn?: string | null;
  title: string;
  author?: string | null;
  publisher?: string | null;
}) => request<Textbook>("/api/textbooks", { method: "POST", data });

export const deleteTextbook = (id: string) =>
  request<void>(`/api/textbooks/${id}`, { method: "DELETE" });

export const bindTextbook = (templateId: string, textbookId: string | null) =>
  request<{ template_id: string; textbook_id: string | null }>(
    `/api/templates/${templateId}/bind-textbook`,
    { method: "POST", data: { textbook_id: textbookId } }
  );

export interface LocationPhoto {
  id: string;
  location_name: string;
  photo_type: string;
  photo_path: string;
}

export const listPhotos = () => request<LocationPhoto[]>("/api/location-photos");

export const deletePhoto = (id: string) =>
  request<void>(`/api/location-photos/${id}`, { method: "DELETE" });

/**
 * wx.uploadFile 的 Promise 封装：带 JWT，返回 JSON 字段。
 * 图片上传（封面/教室照片）统一走这里。
 */
export function uploadFile<T = unknown>(
  path: string,
  filePath: string,
  formData?: Record<string, string>,
  timeoutMs = 60000
): Promise<T> {
  const baseUrl = getApp<IAppOption>().globalData.baseUrl;
  return new Promise<T>((resolve, reject) => {
    wx.uploadFile({
      url: `${baseUrl}${path}`,
      filePath,
      name: "file",
      formData,
      timeout: timeoutMs,
      header: { Authorization: `Bearer ${getToken() ?? ""}` },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(JSON.parse(res.data) as T);
          return;
        }
        let message = `上传失败（${res.statusCode}）`;
        try {
          const raw = JSON.parse(res.data).detail;
          message = typeof raw === "string" ? raw : raw?.message ?? message;
        } catch {
          /* 保留默认错误信息 */
        }
        reject(new Error(message));
      },
      fail(err) {
        reject(new Error(err.errMsg || "上传失败"));
      },
    });
  });
}

// ==== 提醒 / 订阅（阶段六） ====

export interface Reminder {
  id: string;
  reminder_type: string;
  trigger_time: string;
  status: string;
  channel: string | null;
  message: string;
}

export const listReminders = () => request<Reminder[]>("/api/reminders");

export const batchClassReminders = (semesterId: string, days = 7, minutesBefore = 30) =>
  request<{ created: number; skipped: number; wx_configured: boolean }>(
    "/api/reminders/batch",
    { method: "POST", data: { semester_id: semesterId, days, minutes_before: minutesBefore } }
  );

export const createHolidayReminders = (semesterId: string) =>
  request<{ created: number }>("/api/reminders/holiday", {
    method: "POST",
    data: { semester_id: semesterId },
  });

export const deleteReminder = (id: string) =>
  request<void>(`/api/reminders/${id}`, { method: "DELETE" });

export interface SubscribeConfig {
  wx_configured: boolean;
  templates: string[];
}

export const getSubscribeConfig = () =>
  request<SubscribeConfig>("/api/wechat/subscribe-config");

export const recordSubscribe = (templateId: string, grantedCount = 1) =>
  request<{ granted_count: number; used_count: number }>("/api/wechat/subscribe", {
    method: "POST",
    data: { template_id: templateId, granted_count: grantedCount },
  });

/** AI 解析放假公告 → 校历覆盖 → 重新生成（A19） */
export const parseHoliday = (semesterId: string, text: string) =>
  request<{ added: string[]; skipped: unknown[]; source: string; regenerated: number }>(
    "/api/ai/parse-holiday",
    { method: "POST", data: { semester_id: semesterId, text } }
  );

export interface AdjustSuggestion {
  date: string;
  period_number: number;
  start_time: string;
  end_time: string;
}

// ==== ADR 0009：文件导入课表 ====

export interface ImportedCourse {
  course_name: string;
  teacher: string | null;
  weekday: number; // 0=周一
  start_period: number;
  end_period: number | null;
  week_pattern: string; // all / odd / even / 12-13,15
  location: string | null;
}

export interface ImportParseResult {
  file_type: string;
  filename: string;
  raw_chars: number;
  courses: ImportedCourse[];
  warnings: string[];
}

export interface ImportApplyResult {
  message: string;
  templates_added: number;
  batch_skipped: number;
  regenerated: { created: number; skipped: number };
}

/** 上传课表文件 → 混元结构化 → 返回导入草稿（不入库，等确认卡片执行）
 *  整学期课表混元要跑几十秒，超时放宽到 200s（后端/网关/云函数均已配套放宽） */
export const importScheduleParse = (filePath: string) =>
  uploadFile<ImportParseResult>("/api/ai/import-schedule/parse", filePath, undefined, 200000);

/** 确认卡片点「执行」→ 草稿写入模板课表并重生成实例 */
export const importScheduleApply = (
  semesterId: string,
  courses: ImportedCourse[],
  clearExisting = false
) =>
  request<ImportApplyResult>("/api/ai/import-schedule/apply", {
    method: "POST",
    data: { semester_id: semesterId, courses, clear_existing: clearExisting },
  });

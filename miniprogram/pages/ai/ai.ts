import {
  ImportedCourse,
  aiAsk,
  aiParseRule,
  importScheduleApply,
  importScheduleParse,
  listSemesters,
} from "../../utils/api";
import { getToken } from "../../utils/token";
import { logger } from "../../utils/logger";

interface ChatMsg {
  role: "user" | "ai" | "link" | "card";
  text: string;
  // card 角色（ADR 0009）：文件导入确认卡片
  courses?: ImportedCourse[];
  filename?: string;
  warnings?: string[];
}

const QUICK_PROMPTS = ["明天有什么课？", "最近什么时候放假？", "把周一第3节数学改到第5节"];

/** 疑似调课指令 → 走 parse-rule；否则走问答 */
function looksLikeRule(text: string): boolean {
  return /第.{1,3}节|周[一二三四五六日天]/.test(text) && /(改|换|调|挪|加|添加|删|去掉|取消)/.test(text);
}

Page({
  data: {
    messages: [
      {
        role: "ai",
        text: "你好！我是课表助手。可以问我课表问题，也可以直接用一句话调课。",
      },
    ] as ChatMsg[],
    quickPrompts: QUICK_PROMPTS,
    input: "",
    sending: false,
    scrollInto: "",
    semesterId: "",
  },

  onLoad() {
    // tab 页 onLoad 只跑一次；登录守卫与学期解析放 onShow（ADR 0006），
    // 保证用户中途建好学期后切回 AI tab 能拿到正确的激活学期。
  },

  onShow() {
    if (!getToken()) {
      logger.debug("ai", "无 token，跳登录页");
      wx.reLaunch({ url: "/pages/login/login" });
      return;
    }
    this.resolveActiveSemester();
  },

  /** 每次切回都重新解析激活学期（首次进入会提示一次"先去建学期"） */
  resolveActiveSemester() {
    listSemesters()
      .then((semesters) => {
        const active = semesters.find((s) => s.is_active);
        if (!active) {
          if (!this.data.semesterId) {
            this.pushAi("还没有当前学期。先去「我的 → 学期管理」创建一个，再来找我调课。");
          }
          return;
        }
        if (active.id !== this.data.semesterId) {
          logger.debug("ai", "激活学期更新", active.id);
        }
        this.setData({ semesterId: active.id });
      })
      .catch((e) => this.pushAi((e as Error).message));
  },

  pushAi(text: string) {
    const messages = this.data.messages.concat({ role: "ai", text } as ChatMsg);
    this.setData({ messages, scrollInto: `msg-${messages.length - 1}` });
  },

  // ==== ADR 0009：发文件给 AI 助手 → 确认卡片 → 执行导入 ====

  /** 📎 入口：从微信聊天记录选课表文件，AI 解析后回一张确认卡片 */
  onAttachFile() {
    if (this.data.sending) return;
    wx.chooseMessageFile({
      count: 1,
      type: "file",
      extension: ["docx", "xlsx", "pdf", "txt"],
      success: async (res) => {
        const file = res.tempFiles[0];
        logger.debug("ai", "选中课表文件", file.name);
        this.setData({ sending: true });
        const messages = this.data.messages.concat({
          role: "user",
          text: `📎 发来课表文件：${file.name}`,
        } as ChatMsg);
        this.setData({ messages, scrollInto: `msg-${messages.length - 1}` });
        try {
          const draft = await importScheduleParse(file.path);
          logger.debug("ai", "文件解析完成", draft.courses.length);
          const card = {
            role: "card",
            text: `我读完了《${draft.filename}》，识别到 ${draft.courses.length} 门课。确认无误就点「执行导入」，我会帮你写进课表。`,
            courses: draft.courses,
            filename: draft.filename,
            warnings: draft.warnings,
          } as ChatMsg;
          const messages2 = this.data.messages.concat(card as ChatMsg);
          this.setData({ messages: messages2, scrollInto: `msg-${messages2.length - 1}` });
        } catch (e) {
          logger.error("ai", "文件解析失败", e);
          this.pushAi(`文件没读明白：${(e as Error).message}`);
        } finally {
          this.setData({ sending: false });
        }
      },
    });
  },

  /** 确认卡片「执行导入」：草稿入库 + 重生成课表 */
  async onCardConfirm(e: WechatMiniprogram.Touch) {
    const index = Number(e.currentTarget.dataset.index);
    const card = this.data.messages[index];
    if (!card || card.role !== "card" || !card.courses) return;
    if (!this.data.semesterId) {
      wx.showToast({ title: "请先创建当前学期", icon: "none" });
      return;
    }
    this.setData({ sending: true });
    try {
      const r = await importScheduleApply(this.data.semesterId, card.courses);
      logger.info("ai", "卡片导入完成", r);
      const messages = this.data.messages.concat({ role: "ai", text: r.message } as ChatMsg);
      this.setData({ messages, scrollInto: `msg-${messages.length - 1}` });
    } catch (err) {
      logger.error("ai", "卡片导入失败", err);
      this.pushAi(`导入失败：${(err as Error).message}`);
    } finally {
      this.setData({ sending: false });
    }
  },

  /** 确认卡片「取消」 */
  onCardCancel() {
    this.pushAi("好的，没有导入。文件内容随时可以再发给我。");
  },

  onInput(e: WechatMiniprogram.Input) {
    this.setData({ input: e.detail.value });
  },

  onQuick(e: WechatMiniprogram.Touch) {
    this.send(e.currentTarget.dataset.text);
  },

  onSend() {
    this.send(this.data.input);
  },

  async send(raw: string) {
    const text = (raw ?? "").trim();
    if (!text || this.data.sending) return;
    if (!this.data.semesterId) {
      wx.showToast({ title: "请先创建当前学期", icon: "none" });
      return;
    }
    const messages = this.data.messages.concat({ role: "user", text } as ChatMsg);
    this.setData({ messages, input: "", sending: true, scrollInto: `msg-${messages.length - 1}` });
    try {
      const asRule = looksLikeRule(text);
      logger.debug("ai", `收到消息（${asRule ? "调课指令" : "问答"}）：${text}`);
      if (asRule) {
        const result = await aiParseRule(this.data.semesterId, text);
        logger.debug("ai", "parse-rule 结果：", result);
        const messages2 = this.data.messages.concat({ role: "ai", text: result.message } as ChatMsg);
        if (result.applied) {
          messages2.push({ role: "link", text: "课表已更新，点这里查看 →" } as ChatMsg);
        }
        this.setData({ messages: messages2, scrollInto: `msg-${messages2.length - 1}` });
      } else {
        const { answer } = await aiAsk(this.data.semesterId, text);
        this.pushAi(answer);
      }
    } catch (e) {
      logger.error("ai", "请求失败：", e);
      this.pushAi(`出错了：${(e as Error).message}`);
    } finally {
      this.setData({ sending: false });
    }
  },

  goSchedule() {
    // tab 页禁止 navigateTo 携参 → 学期上下文走 globalData（ADR 0006），
    // schedule.onShow 取走 pendingSemesterId 后会渲染对应学期。
    getApp<IAppOption>().globalData.pendingSemesterId = this.data.semesterId;
    wx.switchTab({ url: "/pages/schedule/schedule" });
  },
});

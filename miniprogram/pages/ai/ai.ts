import {
  ImportedCourse,
  aiAgent,
  aiAgentExecute,
  importScheduleApply,
  importScheduleParse,
  listSemesters,
  listTemplates,
} from "../../utils/api";
import { getToken } from "../../utils/token";
import { logger } from "../../utils/logger";

/** 待确认动作草稿（ADR 0008 §2 第二档） */
interface AgentAction {
  tool: string;
  params: Record<string, unknown>;
  summary: string;
}

interface ChatMsg {
  role: "user" | "ai" | "link" | "card";
  text: string;
  // card 角色：cardKind 区分文件导入卡片（ADR 0009）与 Agent 动作卡片（ADR 0008）
  cardKind?: "import" | "action";
  action?: AgentAction;
  courses?: ImportedCourse[];
  filename?: string;
  warnings?: string[];
}

// ADR 0008 §5：按本地状态条件渲染三套静态建议集（每条都落到真实存在的功能）
const QUICK_NO_SEMESTER = ["帮我建这学期课表", "先设置时令作息"];
const QUICK_EMPTY_SCHEDULE = ["添加一门课", "帮我生成课表"];
const QUICK_WITH_SCHEDULE = ["明天有什么课？", "这周有什么假"];

Page({
  data: {
    messages: [
      {
        role: "ai",
        text: "你好！我是课表助手，能查课、查放假，也能替你调课、建提醒、建学期。直接说需求就行。",
      },
    ] as ChatMsg[],
    quickPrompts: QUICK_WITH_SCHEDULE,
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

  /** 每次切回都重新解析激活学期 + 刷新建议集（ADR 0008 §5 按状态条件渲染） */
  resolveActiveSemester() {
    listSemesters()
      .then(async (semesters) => {
        const active = semesters.find((s) => s.is_active);
        if (!active) {
          if (!this.data.semesterId) {
            this.pushAi("还没有当前学期。直接跟我说「帮我建这学期课表」就行，我来办。");
          }
          this.setData({ quickPrompts: QUICK_NO_SEMESTER, semesterId: "" });
          return;
        }
        if (active.id !== this.data.semesterId) {
          logger.debug("ai", "激活学期更新", active.id);
        }
        this.setData({ semesterId: active.id });
        // 课表是否为空决定第二/第三套建议集（一次轻量查询，失败不阻塞对话）
        try {
          const templates = await listTemplates(active.id);
          this.setData({
            quickPrompts: templates.length > 0 ? QUICK_WITH_SCHEDULE : QUICK_EMPTY_SCHEDULE,
          });
        } catch (e) {
          logger.debug("ai", "模板查询失败，建议集用默认", e);
          this.setData({ quickPrompts: QUICK_WITH_SCHEDULE });
        }
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
      extension: ["docx", "xlsx", "pdf", "txt", "jpg", "jpeg", "png"],
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
            cardKind: "import",
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

  // ==== ADR 0008：Agent 动作卡片（拟执行动作 → 用户授权 → 执行反馈） ====

  /** 动作卡片「执行」：调 /agent/execute 真正落库 */
  async onActionConfirm(e: WechatMiniprogram.Touch) {
    const index = Number(e.currentTarget.dataset.index);
    const card = this.data.messages[index];
    if (!card || !card.action) return;
    this.setData({ sending: true });
    try {
      const r = await aiAgentExecute(
        card.action.tool,
        card.action.params,
        this.data.semesterId || null
      );
      logger.info("ai", "Agent 动作执行完成", r.message);
      const messages = this.data.messages.concat({ role: "ai", text: r.message } as ChatMsg);
      this.setData({ messages, scrollInto: `msg-${messages.length - 1}` });
      // 建学期类动作会改变激活学期 → 重新解析（顺带刷新建议集）
      if (card.action.tool === "create_semester") {
        this.resolveActiveSemester();
      }
    } catch (err) {
      logger.error("ai", "Agent 动作执行失败", err);
      this.pushAi(`没执行成功：${(err as Error).message}`);
    } finally {
      this.setData({ sending: false });
    }
  },

  /** 动作卡片「取消」 */
  onActionCancel() {
    this.pushAi("好的，先不动。需要时再跟我说一声。");
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
    // ADR 0008 §3：无学期也可对话（Agent 会引导 AI 代建），不再拦「请先创建学期」
    const messages = this.data.messages.concat({ role: "user", text } as ChatMsg);
    this.setData({ messages, input: "", sending: true, scrollInto: `msg-${messages.length - 1}` });
    try {
      // 带最近 8 条纯文本对话给规划器当上下文（卡片/链接类不进历史）
      const history = this.data.messages
        .filter((m) => m.role === "user" || m.role === "ai")
        .slice(-8)
        .map((m) => ({
          role: m.role === "user" ? ("user" as const) : ("assistant" as const),
          content: m.text,
        }));
      logger.debug("ai", `Agent 收到消息：${text}`);
      const r = await aiAgent(text, this.data.semesterId || null, history);
      logger.debug("ai", "Agent 规划结果：", r.mode, r.action?.tool ?? "");
      if (r.mode === "reply") {
        this.pushAi(r.text || "好的。");
        return;
      }
      if (!r.action) {
        this.pushAi("我拿不准这句话的意思，换个说法试试？");
        return;
      }
      // mutate 工具：渲染动作卡片，等用户授权（ADR 0008 §2 第二档）
      const card = {
        role: "card",
        cardKind: "action",
        text: `我准备这样办：${r.action.summary}`,
        action: r.action,
      } as ChatMsg;
      const messages2 = this.data.messages.concat(card as ChatMsg);
      this.setData({ messages: messages2, scrollInto: `msg-${messages2.length - 1}` });
    } catch (e) {
      logger.error("ai", "Agent 请求失败：", e);
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

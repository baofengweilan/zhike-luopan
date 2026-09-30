import {
  Template,
  Textbook,
  bindTextbook,
  createTextbook,
  deleteTextbook,
  listSemesters,
  listTemplates,
  listTextbooks,
  scanIsbn,
  uploadFile,
} from "../../utils/api";
import { logger } from "../../utils/logger";

Page({
  data: {
    baseUrl: "", // 封面图片走后端静态挂载 /uploads/
    books: [] as Textbook[],
    showManual: false,
    manual: { isbn: "", title: "", author: "", publisher: "" },
    submitting: false,
    /** 绑定课程用：当前学期的模板列表 + picker 下标 */
    templates: [] as Template[],
    bindTarget: "", // 正在绑定的教材 id
    bindIndex: -1,
  },

  onShow() {
    this.setData({ baseUrl: getApp<IAppOption>().globalData.baseUrl });
    this.load();
  },

  async load() {
    try {
      this.setData({ books: await listTextbooks() });
      // 预取当前学期模板，供"绑定到课程"选择
      const active = (await listSemesters()).find((s) => s.is_active);
      if (active) {
        this.setData({ templates: await listTemplates(active.id) });
      }
    } catch (e) {
      logger.error("textbooks", "书架加载失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  // ==== 扫码（A11） ====

  async onScan() {
    try {
      const scanRes = await wx.scanCode({ scanType: ["barCode"] });
      logger.debug("textbooks", "扫码结果", scanRes.result);
      await this.handleScan(scanRes.result);
    } catch (e) {
      // 用户取消扫码不算错误
      logger.debug("textbooks", "扫码取消或失败", e);
    }
  },

  /** 连续扫码模式：批量录书时每扫完一本自动开下一次（A32），直到用户取消 */
  async onBatchScan() {
    let count = 0;
    for (;;) {
      try {
        const scanRes = await wx.scanCode({ scanType: ["barCode"] });
        const result = await this.handleScan(scanRes.result, true);
        if (result !== "need_manual") count++;
        const goOn = await new Promise<boolean>((resolve) => {
          wx.showModal({
            title: `已录 ${count} 本`,
            content: result === "need_manual" ? "这本书没查到，稍后手动补录" : "继续扫下一本？",
            cancelText: "结束",
            confirmText: "继续扫",
            success: (r) => resolve(!!r.confirm),
          });
        });
        if (!goOn) break;
      } catch {
        break; // 用户取消
      }
    }
    await this.load();
  },

  /** 单本扫码处理：found/exists 直接提示；need_manual 打开手动表单预填 ISBN */
  async handleScan(rawIsbn: string, quiet = false): Promise<string> {
    try {
      const result = await scanIsbn(rawIsbn);
      if (result.status === "need_manual") {
        this.setData({ showManual: true, manual: { ...this.data.manual, isbn: result.isbn } });
        if (!quiet) wx.showToast({ title: "没查到，请手动补录", icon: "none" });
        return "need_manual";
      }
      wx.showToast({
        title: result.status === "found" ? `已录入：${result.textbook?.title.slice(0, 10)}` : "书库已有",
        icon: "none",
      });
      await this.load();
      return result.status;
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
      return "error";
    }
  },

  // ==== 手动录入（A12 兜底） ====

  toggleManual() {
    this.setData({ showManual: !this.data.showManual });
  },

  onManualField(e: WechatMiniprogram.Input) {
    this.setData({ [`manual.${e.currentTarget.dataset.field}`]: e.detail.value });
  },

  /** 手动录入提交后，引导拍一张封面（可跳过） */
  async onManualSubmit() {
    const m = this.data.manual;
    if (!m.title.trim()) {
      wx.showToast({ title: "书名必填", icon: "none" });
      return;
    }
    this.setData({ submitting: true });
    try {
      const book = await createTextbook({
        isbn: m.isbn || null,
        title: m.title,
        author: m.author || null,
        publisher: m.publisher || null,
      });
      this.setData({
        showManual: false,
        manual: { isbn: "", title: "", author: "", publisher: "" },
      });
      await this.load();
      // 兜底的另一半：拍封面（A12）
      const shot = await new Promise<string | null>((resolve) => {
        wx.chooseMedia({
          count: 1,
          mediaType: ["image"],
          success: (r) => resolve(r.tempFiles[0]?.tempFilePath ?? null),
          fail: () => resolve(null),
        });
      });
      if (shot) {
        await uploadFile(`/api/textbooks/${book.id}/upload-cover`, shot);
        await this.load();
      }
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    } finally {
      this.setData({ submitting: false });
    }
  },

  // ==== 绑定到课程（A13） ====

  onBind(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    if (this.data.templates.length === 0) {
      wx.showToast({ title: "先在课表模板里建课程", icon: "none" });
      return;
    }
    this.setData({ bindTarget: id, bindIndex: -1 });
  },

  onBindPick(e: WechatMiniprogram.PickerChange) {
    const idx = Number(e.detail.value);
    const tpl = this.data.templates[idx];
    this.setData({ bindIndex: idx });
    if (!tpl) return;
    bindTextbook(tpl.id, this.data.bindTarget)
      .then(() => wx.showToast({ title: `已绑定到：${tpl.course_name}`, icon: "none" }))
      .catch((err) => wx.showToast({ title: (err as Error).message, icon: "none" }));
  },

  onDelete(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除教材",
      content: "确定从书架删除这本书？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deleteTextbook(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

import { deletePhoto, listPhotos, LocationPhoto, uploadFile } from "../../utils/api";
import { logger } from "../../utils/logger";

Page({
  data: {
    baseUrl: "",
    photos: [] as LocationPhoto[],
    saving: false,
  },

  onShow() {
    this.setData({ baseUrl: getApp<IAppOption>().globalData.baseUrl });
    this.load();
  },

  async load() {
    try {
      this.setData({ photos: await listPhotos() });
    } catch (e) {
      logger.error("photos", "照片加载失败", e);
      wx.showToast({ title: (e as Error).message, icon: "none" });
    }
  },

  /** 拍照/选图 → 填地点名 → 上传（A24：提前认教室、认楼） */
  async onUpload() {
    try {
      const shot = await new Promise<string | null>((resolve) => {
        wx.chooseMedia({
          count: 1,
          mediaType: ["image"],
          sourceType: ["camera", "album"],
          success: (r) => resolve(r.tempFiles[0]?.tempFilePath ?? null),
          fail: () => resolve(null),
        });
      });
      if (!shot) return;
      const { confirm, inputValue } = await new Promise<{ confirm: boolean; inputValue: string }>(
        (resolve) => {
          wx.showModal({
            title: "这是哪里？",
            editable: true,
            placeholderText: "如：教学楼 A-101 正门",
            success: (r) => resolve({ confirm: !!r.confirm, inputValue: r.content || "" }),
            fail: () => resolve({ confirm: false, inputValue: "" }),
          });
        }
      );
      if (!confirm) return;
      this.setData({ saving: true });
      await uploadFile("/api/location-photos", shot, {
        location_name: inputValue || "未命名地点",
        photo_type: "classroom",
      });
      wx.showToast({ title: "已保存", icon: "success" });
      await this.load();
    } catch (e) {
      wx.showToast({ title: (e as Error).message, icon: "none" });
    } finally {
      this.setData({ saving: false });
    }
  },

  onPreview(e: WechatMiniprogram.Touch) {
    const urls = this.data.photos.map((p) => `${this.data.baseUrl}/uploads/${p.photo_path}`);
    wx.previewImage({ urls, current: e.currentTarget.dataset.url });
  },

  onDelete(e: WechatMiniprogram.Touch) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: "删除照片",
      content: "确定删除这张照片？",
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await deletePhoto(id);
          await this.load();
        } catch (err) {
          wx.showToast({ title: (err as Error).message, icon: "none" });
        }
      },
    });
  },
});

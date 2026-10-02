/// <reference path="../node_modules/miniprogram-api-typings/index.d.ts" />

/** app.ts 的 globalData 约定 */
interface IAppOption {
  globalData: {
    baseUrl: string;
    /**
     * 跨页传递的"目标学期 id"（ADR 0006）。
     * tabBar 页面禁止 navigateTo 携参，semesters/ai 跳课表前先把学期 id 放这里，
     * schedule.onShow 取走后立即清空。空字符串表示无待传递学期。
     */
    pendingSemesterId: string;
  };
}

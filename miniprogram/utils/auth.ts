import { request } from "./request";
import { setToken, getToken } from "./token";

interface TokenResponse {
  access_token: string;
  token_type: string;
  is_new_user: boolean;
}

/**
 * 静默登录：wx.login 取 code → 后端 code2session 换 JWT。
 * 首次登录后拉取资料页让用户补昵称/头像。
 */
export async function silentLogin(): Promise<TokenResponse> {
  const { code } = await wx.login();
  const data = await request<TokenResponse>("/api/auth/wx-login", {
    method: "POST",
    data: { code },
    redirectOn401: false,
  });
  setToken(data.access_token);
  return data;
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}

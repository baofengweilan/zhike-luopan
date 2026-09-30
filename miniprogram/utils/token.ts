const TOKEN_KEY = "access_token";

export function getToken(): string | null {
  return wx.getStorageSync(TOKEN_KEY) || null;
}

export function setToken(token: string): void {
  wx.setStorageSync(TOKEN_KEY, token);
}

export function clearToken(): void {
  wx.removeStorageSync(TOKEN_KEY);
}

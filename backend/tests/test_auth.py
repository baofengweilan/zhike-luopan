"""阶段一验收（任务书 A01）：微信登录 → Token 有效 → 能请求后端。"""

import pytest

from app.core.security import create_access_token, decode_access_token


def _login(client, code="the-code"):
    resp = client.post("/api/auth/wx-login", json={"code": code})
    assert resp.status_code == 200
    return resp.json()


def test_first_login_creates_user(client, mock_wx):
    data = _login(client)
    assert data["is_new_user"] is True
    assert data["access_token"]


def test_second_login_same_openid_reuses_user(client, mock_wx):
    first = _login(client)
    second = _login(client)
    assert second["is_new_user"] is False
    # 用同一 token 主体校验：解码 sub 一致
    assert decode_access_token(second["access_token"]) == decode_access_token(
        first["access_token"]
    )


def test_me_requires_token(client, mock_wx):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_token(client, mock_wx):
    token = _login(client)["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "Asia/Shanghai"


def test_me_with_invalid_token(client, mock_wx):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_update_me(client, mock_wx):
    token = _login(client)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.put("/api/auth/me", json={"nickname": "小明"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["nickname"] == "小明"
    assert client.get("/api/auth/me", headers=headers).json()["nickname"] == "小明"


def test_jwt_roundtrip():
    token = create_access_token("user-123")
    assert decode_access_token(token) == "user-123"
    assert decode_access_token("garbage") is None


@pytest.mark.parametrize("bad_body", [{}, {"code": ""}])
def test_login_validates_code(client, mock_wx, bad_body):
    assert client.post("/api/auth/wx-login", json=bad_body).status_code == 422

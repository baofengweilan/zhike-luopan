from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserOut, UserUpdate, WxLoginRequest
from app.services.wechat import WeChatAuthError, code2session

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/wx-login", response_model=TokenResponse)
def wx_login(body: WxLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        session = code2session(body.code)
    except WeChatAuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e

    user = db.scalar(select(User).where(User.wx_openid == session.openid))
    is_new = user is None
    if is_new:
        user = User(wx_openid=session.openid, wx_unionid=session.unionid)
        db.add(user)
        db.flush()

    return TokenResponse(access_token=create_access_token(user.id), is_new_user=is_new)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.put("/me", response_model=UserOut)
def update_me(
    body: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url
    db.add(user)
    return user

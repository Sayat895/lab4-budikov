from fastapi import APIRouter, Depends, HTTPException, Request

from controllers.dependencies import (
    bearer_scheme,
    create_session,
    get_current_user,
    get_database,
)
from controllers.schemas import LoginRequest, SessionResponse


router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request, database=Depends(get_database)):
    user = database.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")
    return {"access_token": create_session(request, user), "user": user}


@router.get("/me")
def current_session(user: dict = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    credentials=Depends(bearer_scheme),
    _user: dict = Depends(get_current_user),
):
    request.app.state.sessions.pop(credentials.credentials, None)

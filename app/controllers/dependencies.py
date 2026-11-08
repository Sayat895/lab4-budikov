import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import Database


bearer_scheme = HTTPBearer(auto_error=False)
CASHIER_MANAGED_POSITIONS = frozenset(
    {
        "Кассир дневной",
        "Кассир ночной",
        "Продавец-кассир СП",
        "Продавец-кассир СП дневной",
        "Продавец-кассир СП ночной",
    }
)


def cashier_can_manage_employee(employee: dict) -> bool:
    return employee["position"] in CASHIER_MANAGED_POSITIONS


def get_database(request: Request) -> Database:
    return request.app.state.database


def create_session(request: Request, user: dict) -> str:
    token = secrets.token_urlsafe(32)
    request.app.state.sessions[token] = user
    return token


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация.")
    user = request.app.state.sessions.get(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Сеанс завершен. Войдите снова.")
    return user


def require_manager(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "Руководитель":
        raise HTTPException(status_code=403, detail="Действие доступно только руководителю.")
    return user


def scoped_branch_id(user: dict, requested_branch_id: int | None) -> int | None:
    if user["role"] == "Руководитель":
        return requested_branch_id
    branch_id = user["branch_id"]
    if requested_branch_id is not None and requested_branch_id != branch_id:
        raise HTTPException(status_code=403, detail="Нет доступа к выбранному филиалу.")
    return branch_id


def validate_shift_employee(
    database: Database, branch_id: int, employee_id: int | None, user: dict
):
    validate_branch_id(database, branch_id)
    if employee_id is None:
        return
    employees = database.get_branch_employees(branch_id)
    employee = next((item for item in employees if item["id"] == employee_id), None)
    if employee is None:
        raise HTTPException(
            status_code=422,
            detail="Сотрудник должен работать и не находиться в отпуске или на больничном.",
        )
    if user["role"] == "Старший кассир" and not cashier_can_manage_employee(employee):
        raise HTTPException(
            status_code=403,
            detail="Старший кассир может регистрировать смены только своих кассиров.",
        )


def validate_branch_id(database: Database, branch_id: int):
    if not any(branch["id"] == branch_id for branch in database.get_branches()):
        raise HTTPException(status_code=422, detail="Выбранный филиал не существует.")

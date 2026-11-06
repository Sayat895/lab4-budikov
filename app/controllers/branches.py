from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import IntegrityError

from controllers.dependencies import get_current_user, get_database, require_manager
from controllers.schemas import BranchRequest


router = APIRouter(prefix="/api/branches", tags=["branches"])


@router.get("")
def list_branches(
    user: dict = Depends(get_current_user),
    database=Depends(get_database),
):
    branches = database.get_branches()
    if user["role"] == "Руководитель":
        return branches
    return [branch for branch in branches if branch["id"] == user["branch_id"]]


@router.post("", status_code=201)
def create_branch(
    payload: BranchRequest,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    try:
        database.save_branch(None, payload.name, payload.address)
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="Филиал с таким названием уже существует.") from error
    return {"message": "Филиал добавлен."}


@router.put("/{branch_id}")
def update_branch(
    branch_id: int,
    payload: BranchRequest,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    if not any(branch["id"] == branch_id for branch in database.get_branches()):
        raise HTTPException(status_code=404, detail="Филиал не найден.")
    try:
        database.save_branch(branch_id, payload.name, payload.address)
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="Филиал с таким названием уже существует.") from error
    return {"message": "Данные филиала обновлены."}


@router.delete("/{branch_id}", status_code=204)
def delete_branch(
    branch_id: int,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    if not any(branch["id"] == branch_id for branch in database.get_branches()):
        raise HTTPException(status_code=404, detail="Филиал не найден.")
    try:
        database.delete_branch(branch_id)
    except IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить филиал, который используется в записях.",
        ) from error

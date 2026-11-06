from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import IntegrityError

from controllers.dependencies import (
    get_current_user,
    get_database,
    require_manager,
    scoped_branch_id,
    validate_shift_employee,
)
from controllers.schemas import ShiftRequest


router = APIRouter(prefix="/api/shifts", tags=["shifts"])


@router.get("")
def list_shifts(
    start_date: date | None = None,
    end_date: date | None = None,
    branch_id: int | None = None,
    user: dict = Depends(get_current_user),
    database=Depends(get_database),
):
    end = end_date or date.today()
    start = start_date or end - timedelta(days=30)
    if start > end:
        raise HTTPException(status_code=422, detail="Начальная дата позже конечной.")
    return database.get_shifts(start, end, scoped_branch_id(user, branch_id))


@router.post("", status_code=201)
def create_shift(
    payload: ShiftRequest,
    user: dict = Depends(get_current_user),
    database=Depends(get_database),
):
    branch_id = scoped_branch_id(user, payload.branch_id)
    validate_shift_employee(database, branch_id, payload.employee_id)
    database.save_shift(
        None,
        branch_id,
        payload.employee_id,
        payload.work_date,
        payload.shift_name,
        payload.hours,
        payload.shortage,
        payload.surplus,
        payload.notes,
        user["id"],
    )
    return {"message": "Смена сохранена."}


@router.put("/{shift_id}")
def update_shift(
    shift_id: int,
    payload: ShiftRequest,
    database=Depends(get_database),
    user: dict = Depends(require_manager),
):
    validate_shift_employee(database, payload.branch_id, payload.employee_id)
    database.save_shift(
        shift_id,
        payload.branch_id,
        payload.employee_id,
        payload.work_date,
        payload.shift_name,
        payload.hours,
        payload.shortage,
        payload.surplus,
        payload.notes,
        user["id"],
    )
    return {"message": "Смена сохранена."}


@router.delete("/{shift_id}", status_code=204)
def delete_shift(
    shift_id: int,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    try:
        database.delete_shift(shift_id)
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="Не удалось удалить запись о смене.") from error

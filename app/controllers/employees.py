from fastapi import APIRouter, Depends, HTTPException
from psycopg2 import IntegrityError

from controllers.dependencies import (
    get_current_user,
    get_database,
    cashier_can_manage_employee,
    require_manager,
    scoped_branch_id,
    validate_branch_id,
)
from controllers.schemas import EmployeeRequest


router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("")
def list_employees(
    branch_id: int | None = None,
    database=Depends(get_database),
    user: dict = Depends(get_current_user),
):
    return database.get_employees(scoped_branch_id(user, branch_id))


@router.get("/branch/{branch_id}")
def list_branch_employees(
    branch_id: int,
    user: dict = Depends(get_current_user),
    database=Depends(get_database),
):
    scoped_branch_id(user, branch_id)
    employees = database.get_branch_employees(branch_id)
    if user["role"] == "Старший кассир":
        return [employee for employee in employees if cashier_can_manage_employee(employee)]
    return employees


@router.post("", status_code=201)
def create_employee(
    payload: EmployeeRequest,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    validate_branch_id(database, payload.branch_id)
    database.save_employee(
        None, payload.branch_id, payload.full_name, payload.position, payload.phone, payload.status
    )
    return {"message": "Сотрудник добавлен."}


@router.put("/{employee_id}")
def update_employee(
    employee_id: int,
    payload: EmployeeRequest,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    validate_branch_id(database, payload.branch_id)
    database.save_employee(
        employee_id,
        payload.branch_id,
        payload.full_name,
        payload.position,
        payload.phone,
        payload.status,
    )
    return {"message": "Данные сотрудника обновлены."}


@router.delete("/{employee_id}", status_code=204)
def delete_employee(
    employee_id: int,
    database=Depends(get_database),
    _user: dict = Depends(require_manager),
):
    try:
        database.delete_employee(employee_id)
    except IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить сотрудника, который указан в сменах.",
        ) from error

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class BranchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        if not value.strip():
            raise ValueError("Название филиала не может быть пустым.")
        return value.strip()


class EmployeeRequest(BaseModel):
    branch_id: int
    full_name: str = Field(min_length=1, max_length=200)
    position: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=10, max_length=50)
    status: str = "Работает"

    @field_validator("full_name", "position")
    @classmethod
    def validate_required_text(cls, value):
        if not value.strip():
            raise ValueError("Поле не может быть пустым.")
        return value.strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value):
        digits = re.sub(r"\D", "", value)
        if len(digits) == 10:
            digits = f"7{digits}"
        elif len(digits) == 11 and digits.startswith("8"):
            digits = f"7{digits[1:]}"
        if len(digits) != 11 or not digits.startswith("7"):
            raise ValueError("Укажите телефон Казахстана в формате +7XXXXXXXXXX.")
        return f"+{digits}"

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        allowed = {"Работает", "В отпуске", "На больничном", "Не работает"}
        if value not in allowed:
            raise ValueError("Выберите допустимый статус сотрудника.")
        return value


class ShiftRequest(BaseModel):
    branch_id: int
    employee_id: int | None = None
    work_date: date
    shift_name: str = Field(min_length=1, max_length=100)
    hours: Decimal = Field(ge=0, le=24)
    shortage: Decimal = Field(default=Decimal("0"), ge=0)
    surplus: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str = Field(default="", max_length=2000)

    @field_validator("shift_name")
    @classmethod
    def validate_shift_name(cls, value):
        if not value.strip():
            raise ValueError("Укажите тип смены.")
        return value.strip()


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

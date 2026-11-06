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
    phone: str = Field(default="", max_length=50)
    active: bool = True

    @field_validator("full_name", "position")
    @classmethod
    def validate_required_text(cls, value):
        if not value.strip():
            raise ValueError("Поле не может быть пустым.")
        return value.strip()


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

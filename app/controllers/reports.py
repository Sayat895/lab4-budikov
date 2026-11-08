from datetime import date
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from controllers.dependencies import get_current_user, get_database, scoped_branch_id


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/shifts.xlsx")
def export_shifts(
    start_date: date,
    end_date: date,
    branch_id: int | None = None,
    user: dict = Depends(get_current_user),
    database=Depends(get_database),
):
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="Начальная дата позже конечной.")
    branch_scope = scoped_branch_id(user, branch_id)
    shifts = database.get_shifts(start_date, end_date, branch_scope)
    employees = database.get_employees(branch_scope)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Смены"
    sheet.append(
        [
            "Дата", "Филиал", "Сотрудник", "Смена", "Часы",
            "Недостача, ₸", "Излишек, ₸", "Комментарий", "Внесено пользователем",
        ]
    )
    for shift in shifts:
        sheet.append(
            [
                shift["work_date"],
                shift["branch"],
                shift["employee"] or "",
                shift["shift_name"],
                float(shift["hours"]),
                float(shift["shortage"]),
                float(shift["surplus"]),
                shift["notes"],
                shift["created_by"] or "",
            ]
        )

    staff_sheet = workbook.create_sheet("Сотрудники")
    staff_sheet.append(["ФИО", "Должность", "Телефон", "Филиал", "Статус"])
    for employee in employees:
        staff_sheet.append(
            [
                employee["full_name"],
                employee["position"],
                employee["phone"],
                employee["branch"],
                employee["status"],
            ]
        )

    for worksheet in workbook.worksheets:
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="14213D")
            cell.alignment = Alignment(horizontal="center")
        for column in worksheet.columns:
            width = min(max(len(str(cell.value or "")) for cell in column) + 2, 42)
            worksheet.column_dimensions[column[0].column_letter].width = width

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    filename = f"Отчет_по_сменам_{start_date:%Y%m%d}-{end_date:%Y%m%d}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="shift-report.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
            )
        },
    )

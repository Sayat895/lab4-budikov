import base64
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from desktop_api import DesktopApi
from db import hash_password, verify_password
from main import create_app


class FakeDatabase:
    manager = {"id": 7, "username": "director", "role": "Руководитель", "branch_id": None}
    cashier = {"id": 8, "username": "cashier", "role": "Старший кассир", "branch_id": 1}

    def __init__(self):
        self.branches = [
            {"id": 1, "name": "Главный", "address": "Адрес 1"},
            {"id": 2, "name": "Второй", "address": "Адрес 2"},
        ]
        self.employees = [
            {
                "id": 11,
                "branch_id": 1,
                "full_name": "Кассир",
                "position": "Кассир",
                "phone": "+77001234567",
                "status": "Работает",
                "active": True,
                "branch": "Главный",
            },
            {
                "id": 12,
                "branch_id": 2,
                "full_name": "Другой кассир",
                "position": "Кассир",
                "phone": "+77007654321",
                "status": "Работает",
                "active": True,
                "branch": "Второй",
            },
        ]
        self.shifts = []
        self.saved_shift = None
        self.saved_employee = None
        self.saved_branch = None

    def authenticate(self, username, password):
        if password != "correct":
            return None
        if username == "director":
            return self.manager
        if username == "cashier":
            return self.cashier
        return None

    def get_branches(self):
        return self.branches

    def get_dashboard_summary(self, branch_id=None):
        self.dashboard_branch_id = branch_id
        return {
            "employees": 1,
            "shifts": 2,
            "today_shifts": 1,
            "shortage": 10,
            "surplus": 5,
            "shortage_shifts": 1,
            "surplus_shifts": 1,
            "no_deviation_shifts": 0,
        }

    def get_employees(self, branch_id=None):
        if branch_id is None:
            return self.employees
        return [employee for employee in self.employees if employee["branch_id"] == branch_id]

    def get_branch_employees(self, branch_id):
        return [
            {"id": employee["id"], "full_name": employee["full_name"], "position": employee["position"]}
            for employee in self.employees
            if employee["branch_id"] == branch_id and employee["status"] == "Работает"
        ]

    def get_shifts(self, start_date, end_date, branch_id=None):
        self.shift_query = (start_date, end_date, branch_id)
        return self.shifts

    def save_shift(self, *args):
        self.saved_shift = args

    def delete_shift(self, _shift_id):
        return None

    def save_branch(self, *_args):
        self.saved_branch = _args

    def delete_branch(self, _branch_id):
        return None

    def save_employee(self, *_args):
        self.saved_employee = _args

    def delete_employee(self, _employee_id):
        return None


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.database = FakeDatabase()
        self.application = create_app(self.database, initialize_database=False)
        self.client = TestClient(self.application)

    def login(self, username="director"):
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "correct"},
        )
        self.assertEqual(response.status_code, 200)
        self.client.headers.update(
            {"Authorization": f"Bearer {response.json()['access_token']}"}
        )

    def test_password_hash_is_salted_and_verified(self):
        first = hash_password("example password")
        second = hash_password("example password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("example password", first))
        self.assertFalse(verify_password("wrong password", first))

    def test_authentication_and_logout(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "director", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/auth/me").json()["role"], "Руководитель")
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_cashier_is_restricted_to_the_assigned_branch(self):
        self.login("cashier")
        self.assertEqual(
            [branch["id"] for branch in self.client.get("/api/branches").json()],
            [1],
        )
        self.assertEqual(self.client.get("/api/dashboard").status_code, 200)
        self.assertEqual(self.database.dashboard_branch_id, 1)
        employees = self.client.get("/api/employees").json()
        self.assertEqual([employee["id"] for employee in employees], [11])
        self.assertEqual(employees[0]["status"], "Работает")
        self.assertEqual(employees[0]["phone"], "+77001234567")
        self.assertEqual(self.client.get("/api/employees/branch/1").status_code, 200)
        self.assertEqual(
            self.client.get("/api/employees/branch/2").status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/employees?branch_id=2").status_code, 403)
        self.assertEqual(
            self.client.get("/api/dashboard?branch_id=2").status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/shifts?branch_id=2").status_code,
            403,
        )

    def test_only_manager_can_manage_staff_and_branches(self):
        self.login("cashier")
        response = self.client.post(
            "/api/branches",
            json={"name": "Новый", "address": ""},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/employees").status_code, 200)
        response = self.client.post(
            "/api/employees",
            json={
                "branch_id": 1,
                "full_name": "Тест",
                "position": "Кассир",
                "phone": "+77001234568",
                "status": "Работает",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_branch_and_employee(self):
        self.login()
        response = self.client.post(
            "/api/branches",
            json={"name": "Новый", "address": "Улица"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.database.saved_branch, (None, "Новый", "Улица"))
        response = self.client.post(
            "/api/employees",
            json={
                "branch_id": 1,
                "full_name": "Новый сотрудник",
                "position": "Кассир",
                "phone": "8 (700) 123-45-67",
                "status": "Работает",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.database.saved_employee[1:3], (1, "Новый сотрудник"))
        self.assertEqual(self.database.saved_employee[4:], ("+77001234567", "Работает"))

    def test_manager_can_save_employee_leave_status_and_phone_is_normalized(self):
        self.login()
        response = self.client.post(
            "/api/employees",
            json={
                "branch_id": 1,
                "full_name": "Сотрудник",
                "position": "Пекарь",
                "phone": "+7 (701) 555-12-34",
                "status": "В отпуске",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.database.saved_employee[4:], ("+77015551234", "В отпуске"))

    def test_employee_phone_and_status_validation(self):
        self.login()
        payload = {
            "branch_id": 1,
            "full_name": "Сотрудник",
            "position": "Продавец",
            "phone": "+77015551234",
            "status": "В отпуске",
        }
        payload["phone"] = "123"
        self.assertEqual(self.client.post("/api/employees", json=payload).status_code, 422)
        payload["phone"] = "+77015551234"
        payload["status"] = "Неизвестный статус"
        self.assertEqual(self.client.post("/api/employees", json=payload).status_code, 422)
        self.assertIsNone(self.database.saved_employee)

    def test_employee_on_leave_or_sick_cannot_be_assigned_to_shift(self):
        self.login()
        for status in ("В отпуске", "На больничном", "Не работает"):
            self.database.employees[0]["status"] = status
            payload = {
                "branch_id": 1,
                "employee_id": 11,
                "work_date": date.today().isoformat(),
                "shift_name": "Дневная",
                "hours": 8,
            }
            response = self.client.post("/api/shifts", json=payload)
            self.assertEqual(response.status_code, 422, status)
        self.assertIsNone(self.database.saved_shift)

    def test_cashier_can_add_shift_only_to_own_branch(self):
        self.login("cashier")
        payload = {
            "branch_id": 2,
            "employee_id": 11,
            "work_date": date.today().isoformat(),
            "shift_name": "Дневная",
            "hours": 8,
            "shortage": 0,
            "surplus": 0,
            "notes": "",
        }
        response = self.client.post("/api/shifts", json=payload)
        self.assertEqual(response.status_code, 403)
        payload["branch_id"] = 1
        payload["employee_id"] = 12
        response = self.client.post("/api/shifts", json=payload)
        self.assertEqual(response.status_code, 422)
        payload["employee_id"] = 11
        response = self.client.post("/api/shifts", json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.database.saved_shift[1], 1)
        self.assertEqual(self.database.saved_shift[-1], self.database.cashier["id"])
        self.assertEqual(self.client.put("/api/shifts/1", json=payload).status_code, 403)
        self.assertEqual(self.client.delete("/api/shifts/1").status_code, 403)

    def test_excel_report_contains_both_sheets_and_is_branch_scoped(self):
        self.login("cashier")
        response = self.client.get(
            "/api/reports/shifts.xlsx",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.database.shift_query[2], 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            path.write_bytes(response.content)
            workbook = load_workbook(path)
            self.assertEqual(workbook.sheetnames, ["Смены", "Сотрудники"])
            self.assertEqual(workbook["Смены"].cell(1, 1).value, "Дата")
            self.assertEqual(workbook["Сотрудники"].cell(1, 1).value, "ФИО")
            self.assertEqual(workbook["Сотрудники"].cell(2, 5).value, "Работает")

    def test_desktop_export_saves_xlsx_through_native_file_dialog(self):
        report = self.client.post(
            "/api/auth/login",
            json={"username": "director", "password": "correct"},
        ).json()
        token = report["access_token"]
        response = self.client.get(
            "/api/reports/shifts.xlsx",
            params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report"
            window = Mock()
            window.create_file_dialog.return_value = str(target)
            desktop_api = DesktopApi()
            desktop_api._window = window
            result = desktop_api.save_report(
                "report.xlsx",
                base64.b64encode(response.content).decode(),
            )
            saved_path = target.with_suffix(".xlsx")
            self.assertEqual(result, {"cancelled": False, "path": str(saved_path)})
            self.assertTrue(saved_path.is_file())
            workbook = load_workbook(saved_path)
            self.assertEqual(workbook.sheetnames, ["Смены", "Сотрудники"])
            window.create_file_dialog.assert_called_once()

    def test_desktop_export_reports_cancelled_dialog(self):
        window = Mock()
        window.create_file_dialog.return_value = None
        desktop_api = DesktopApi()
        desktop_api._window = window
        result = desktop_api.save_report("report.xlsx", "UEs=")
        self.assertEqual(result, {"cancelled": True})


if __name__ == "__main__":
    unittest.main()

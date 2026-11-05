import asyncio
import os
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

import aiohttp
import psycopg2
from openpyxl import load_workbook
from PyQt5.QtWidgets import QApplication, QHeaderView, QMessageBox

from db import Database, hash_password, verify_password
from main import APP_STYLE, MainWindow


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.qt_app = QApplication.instance() or QApplication([])
        cls.database = Database()
        cls.manager = cls.database.authenticate(
            os.environ["APP_ADMIN_USER"],
            os.environ["APP_ADMIN_PASSWORD"],
        )
        cls.cashier = cls.database.authenticate(
            os.environ["APP_CASHIER_USER"],
            os.environ["APP_CASHIER_PASSWORD"],
        )
        if cls.manager is None or cls.cashier is None:
            raise RuntimeError("Demo users were not initialized in the database")

    def test_password_hash_is_salted_and_verified(self):
        first = hash_password("example password")
        second = hash_password("example password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("example password", first))
        self.assertFalse(verify_password("wrong password", first))

    def test_database_crud_for_branch_employee_and_shift(self):
        branch_name = f"test-{uuid.uuid4()}"
        self.database.save_branch(None, branch_name, "test address")
        branch = next(item for item in self.database.get_branches() if item["name"] == branch_name)
        employee_id = None
        shift_id = None
        try:
            self.database.save_employee(
                None, branch["id"], "Test Employee", "Cashier", "000", True
            )
            employee = next(
                item for item in self.database.get_employees(branch["id"])
                if item["full_name"] == "Test Employee"
            )
            employee_id = employee["id"]
            self.database.save_employee(
                employee_id, branch["id"], "Updated Employee", "Senior Cashier", "111", True
            )

            self.database.save_shift(
                None,
                branch["id"],
                employee_id,
                date.today(),
                "Day",
                8,
                10.25,
                2.5,
                "integration test",
                self.manager["id"],
            )
            shift = next(
                item for item in self.database.get_shifts(date.today(), date.today(), branch["id"])
                if item["notes"] == "integration test"
            )
            shift_id = shift["id"]
            self.assertEqual(shift["employee"], "Updated Employee")
            self.assertEqual(float(shift["shortage"]), 10.25)
            self.assertEqual(float(shift["surplus"]), 2.5)

            self.database.save_shift(
                shift_id,
                branch["id"],
                employee_id,
                date.today(),
                "Night",
                7,
                5,
                1,
                "updated integration test",
                self.manager["id"],
            )
            updated_shift = next(
                item for item in self.database.get_shifts(date.today(), date.today(), branch["id"])
                if item["id"] == shift_id
            )
            self.assertEqual(updated_shift["shift_name"], "Night")
            self.assertEqual(updated_shift["notes"], "updated integration test")

            self.database.save_branch(branch["id"], branch_name, "updated address")
            updated_branch = next(
                item for item in self.database.get_branches() if item["id"] == branch["id"]
            )
            self.assertEqual(updated_branch["address"], "updated address")
        finally:
            if shift_id is not None:
                self.database.delete_shift(shift_id)
            if employee_id is not None:
                self.database.delete_employee(employee_id)
            self.database.delete_branch(branch["id"])

    def test_role_specific_interface_and_magnum_inspired_palette(self):
        manager_window = MainWindow(self.database, self.manager)
        cashier_window = MainWindow(self.database, self.cashier)
        self.assertEqual(manager_window.tabs.count(), 4)
        self.assertEqual(cashier_window.tabs.count(), 2)
        self.assertFalse(cashier_window.shift_branch_filter.isEnabled())
        self.assertIn("color: #171717", APP_STYLE)
        self.assertIn("#a51f32", APP_STYLE)
        self.assertIn('font-family: "DejaVu Sans"', APP_STYLE)
        self.assertIn("font-size: 15px", APP_STYLE)
        self.assertIn("QLabel#brand {\n    background: transparent;\n    color: white;", APP_STYLE)
        self.assertTrue(manager_window.shift_table.wordWrap())
        self.assertEqual(manager_window.shift_table.horizontalHeader().minimumSectionSize(), 100)
        self.assertGreaterEqual(manager_window.shift_branch_filter.minimumWidth(), 210)
        full_name = "Длинное имя сотрудника, которое не должно обрезаться"
        manager_window._set_model(
            manager_window.employee_table,
            ["ФИО"],
            [{"id": 1, "values": [full_name]}],
        )
        self.assertEqual(manager_window.employee_table.model().item(0, 0).toolTip(), full_name)
        self.assertEqual(
            manager_window.employee_table.verticalHeader().sectionResizeMode(0),
            QHeaderView.ResizeToContents,
        )
        self.assertEqual(len(manager_window.kpi_values), 5)

    def test_excel_report_contains_shifts_and_staff_sheets(self):
        temporary_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        report_path = Path(temporary_file.name)
        temporary_file.close()
        report_path.unlink()
        manager_window = MainWindow(self.database, self.manager)
        with patch(
            "main.QFileDialog.getSaveFileName",
            return_value=(str(report_path), "Книга Excel (*.xlsx)"),
        ), patch("main.QMessageBox.information", return_value=QMessageBox.Ok):
            try:
                manager_window.export_excel()
                workbook = load_workbook(report_path)
                self.assertEqual(workbook.sheetnames, ["Смены", "Сотрудники"])
                self.assertEqual(workbook["Смены"].freeze_panes, "A2")
                self.assertEqual(workbook["Смены"].cell(1, 1).value, "Дата")
            finally:
                if report_path.exists():
                    report_path.unlink()

    def test_browser_page_and_vnc_websocket_are_available(self):
        async def verify():
            async with aiohttp.ClientSession() as session:
                async with session.get("http://127.0.0.1:6080/vnc.html") as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("noVNC", await response.text())

                async with session.ws_connect(
                    "http://127.0.0.1:6080/websockify",
                    timeout=aiohttp.ClientWSTimeout(ws_receive=15),
                ) as websocket:
                    message = await websocket.receive(timeout=15)
                    self.assertEqual(message.type, aiohttp.WSMsgType.BINARY)
                    self.assertTrue(message.data.startswith(b"RFB "))

        asyncio.run(verify())


if __name__ == "__main__":
    unittest.main()

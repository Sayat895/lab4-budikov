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
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QStandardItem
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QDialog, QHeaderView, QMessageBox

from db import Database, hash_password, verify_password
from main import APP_STYLE, ApplicationController, LoginDialog, MainWindow, ShiftDialog


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

    def test_dashboard_summarizes_shortage_surplus_and_no_deviation(self):
        branch_name = f"summary-{uuid.uuid4()}"
        self.database.save_branch(None, branch_name, "test address")
        branch = next(item for item in self.database.get_branches() if item["name"] == branch_name)
        employee_id = None
        try:
            self.database.save_employee(None, branch["id"], "Summary Test", "Cashier", "", True)
            employee = next(
                item for item in self.database.get_employees(branch["id"])
                if item["full_name"] == "Summary Test"
            )
            employee_id = employee["id"]
            for index, (shortage, surplus) in enumerate(
                [(1250, 0), (0, 750), (0, 0)]
            ):
                self.database.save_shift(
                    None,
                    branch["id"],
                    employee_id,
                    date.today(),
                    "Day",
                    8,
                    shortage,
                    surplus,
                    f"summary-{index}",
                    self.manager["id"],
                )

            summary = self.database.get_dashboard_summary(branch["id"])
            self.assertEqual(summary["shifts"], 3)
            self.assertEqual(summary["shortage_shifts"], 1)
            self.assertEqual(summary["shortage"], 1250)
            self.assertEqual(summary["surplus_shifts"], 1)
            self.assertEqual(summary["surplus"], 750)
            self.assertEqual(summary["no_deviation_shifts"], 1)
            scoped_cashier = dict(self.cashier, branch_id=branch["id"])
            dashboard = MainWindow(self.database, scoped_cashier)
            self.assertIn("1 смен · 1 250.00 ₸", dashboard.kpi_values["shortage"][0].text())
            self.assertIn("1 смен · 750.00 ₸", dashboard.kpi_values["surplus"][0].text())
            self.assertIn("1 смен", dashboard.kpi_values["no_deviation"][0].text())
        finally:
            with self.database.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM shifts WHERE branch_id = %s", (branch["id"],))
            if employee_id is not None:
                self.database.delete_employee(employee_id)
            self.database.delete_branch(branch["id"])

    def test_manager_can_edit_a_shift_from_the_interface(self):
        branch = self.database.get_branches()[0]
        employee = self.database.get_branch_employees(branch["id"])[0]
        original_notes = f"ui-edit-{uuid.uuid4()}"
        updated_notes = f"ui-edited-{uuid.uuid4()}"
        self.database.save_shift(
            None,
            branch["id"],
            employee["id"],
            date.today(),
            "Дневная",
            8,
            500,
            0,
            original_notes,
            self.manager["id"],
        )
        shift = next(
            item for item in self.database.get_shifts(date.today(), date.today(), branch["id"])
            if item["notes"] == original_notes
        )
        window = MainWindow(self.database, self.manager)
        row = next(
            row for row in range(window.shift_table.model().rowCount())
            if window.shift_table.model().item(row, 0).data(Qt.UserRole) == shift["id"]
        )
        window.shift_table.setCurrentIndex(window.shift_table.model().index(row, 0))
        dialog = ShiftDialog(self.database, [branch], shift=shift)
        dialog.shift_name.setCurrentText("Ночная")
        dialog.hours.setValue(10)
        dialog.shortage.setValue(1250)
        dialog.notes.setText(updated_notes)
        with patch("main.ShiftDialog", return_value=dialog), patch.object(
            dialog, "exec_", return_value=QDialog.Accepted
        ):
            try:
                window.edit_shift()
                updated_shift = next(
                    item for item in self.database.get_shifts(
                        date.today(), date.today(), branch["id"]
                    )
                    if item["id"] == shift["id"]
                )
                self.assertEqual(updated_shift["shift_name"], "Ночная")
                self.assertEqual(float(updated_shift["hours"]), 10)
                self.assertEqual(float(updated_shift["shortage"]), 1250)
                self.assertEqual(updated_shift["notes"], updated_notes)
            finally:
                self.database.delete_shift(shift["id"])

    def test_role_specific_interface_and_magnum_inspired_palette(self):
        manager_window = MainWindow(self.database, self.manager)
        cashier_window = MainWindow(self.database, self.cashier)
        self.assertEqual(manager_window.tabs.count(), 4)
        self.assertEqual(cashier_window.tabs.count(), 2)
        self.assertFalse(cashier_window.shift_branch_filter.isEnabled())
        self.assertIn("background: #f5f5f2", APP_STYLE)
        self.assertIn("#a51f32", APP_STYLE)
        self.assertIn('font-family: "DejaVu Sans"', APP_STYLE)
        self.assertIn("font-size: 14px", APP_STYLE)
        self.assertIn(
            "QLabel#brand {\n    background: transparent;\n    color: #a51f32;",
            APP_STYLE,
        )
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
        self.assertEqual(len(manager_window.kpi_values), 6)
        self.assertEqual(manager_window.logout_button.text(), "Выйти")
        self.assertEqual(cashier_window.logout_button.text(), "Выйти")
        self.assertEqual(manager_window.refresh_shortcut.key().toString(), "Ctrl+R")
        self.assertEqual(manager_window.logout_shortcut.key().toString(), "Ctrl+Q")
        self.assertEqual(len(manager_window.tab_shortcuts), manager_window.tabs.count())
        self.assertEqual(manager_window.shift_table.copy_shortcut.key().toString(), "Ctrl+C")
        manager_window.shift_table.model().clear()
        manager_window.shift_table.model().setColumnCount(2)
        manager_window.shift_table.model().appendRow(
            [QStandardItem("Тест"), QStandardItem("Смена")]
        )
        manager_window.shift_table.selectRow(0)
        manager_window.copy_selected_row(manager_window.shift_table)
        self.assertEqual(QApplication.clipboard().text(), "Тест\tСмена")

        login = LoginDialog(self.database)
        QApplication.clipboard().setText("paste-test")
        QTest.keyClick(login.username, Qt.Key_V, Qt.ControlModifier)
        self.assertEqual(login.username.text(), "paste-test")

    def test_logout_authenticates_again_and_switches_user(self):
        controller = ApplicationController(self.database, self.qt_app)
        initial_window = MainWindow(self.database, self.manager)
        initial_window.logout_requested.connect(controller.show_login)
        controller.window = initial_window

        login_dialog = LoginDialog(self.database)
        login_dialog.user = self.cashier
        with patch("main.LoginDialog", return_value=login_dialog), patch.object(
            login_dialog, "exec_", return_value=QDialog.Accepted
        ):
            initial_window.logout_button.click()

        self.assertEqual(controller.window.user["username"], self.cashier["username"])
        self.assertEqual(controller.window.tabs.currentIndex(), 0)
        self.assertFalse(initial_window.isVisible())
        self.assertEqual(controller.window.logout_button.text(), "Выйти")
        controller.window.deleteLater()
        initial_window.deleteLater()
        self.qt_app.processEvents()

    def test_initial_novnc_connection_does_not_queue_a_second_login(self):
        controller = ApplicationController(self.database, self.qt_app)
        controller.request_reauthentication()
        self.assertFalse(controller.reauthentication_pending)

        controller.session_active = True
        controller.request_reauthentication()
        self.assertTrue(controller.reauthentication_pending)
        with patch.object(controller, "show_login") as show_login:
            controller.process_pending_reauthentication()
            show_login.assert_called_once_with()
        self.assertFalse(controller.reauthentication_pending)

    def test_excel_report_contains_shifts_and_staff_sheets(self):
        temporary_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        report_path = Path(temporary_file.name)
        temporary_file.close()
        report_path.unlink()
        manager_window = MainWindow(self.database, self.manager)
        branch = self.database.get_branches()[0]
        employee = self.database.get_branch_employees(branch["id"])[0]
        notes = f"excel-export-{uuid.uuid4()}"
        self.database.save_shift(
            None,
            branch["id"],
            employee["id"],
            date.today(),
            "Day",
            8,
            0,
            0,
            notes,
            self.manager["id"],
        )
        shifts = self.database.get_shifts(date.today(), date.today(), branch["id"])
        shift_id = next(item["id"] for item in shifts if item["notes"] == notes)
        manager_window.shift_branch_filter.setCurrentIndex(
            manager_window.shift_branch_filter.findData(branch["id"])
        )
        today = QDate(date.today().year, date.today().month, date.today().day)
        manager_window.date_from.setDate(today)
        manager_window.date_to.setDate(today)
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
                self.assertGreater(workbook["Смены"].max_row, 1)
                self.assertTrue(
                    any(
                        row[7].value == notes
                        for row in workbook["Смены"].iter_rows(min_row=2)
                    )
                )
                self.assertGreater(workbook["Сотрудники"].max_row, 1)
            finally:
                self.database.delete_shift(shift_id)
                if report_path.exists():
                    report_path.unlink()

    def test_browser_page_and_vnc_websocket_are_available(self):
        async def verify():
            async with aiohttp.ClientSession() as session:
                async with session.get("http://127.0.0.1:6080/vnc.html") as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("noVNC", await response.text())

                async with session.get("http://127.0.0.1:6080/app/ui.js") as response:
                    self.assertEqual(response.status, 200)
                    ui_script = await response.text()
                    self.assertIn("Could not read the browser clipboard", ui_script)
                    self.assertIn("stopImmediatePropagation", ui_script)

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

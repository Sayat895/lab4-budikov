import sys
from decimal import Decimal

import psycopg2
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db import Database


APP_STYLE = """
QWidget {
    background: #f4f7fb;
    color: #171717;
    font-family: "DejaVu Sans";
    font-size: 15px;
}
QMainWindow { background: #f7f5f1; }
QLabel#pageTitle { font-size: 25px; font-weight: 700; color: #171717; }
QLabel#muted { color: #555555; }
QLabel#brand {
    background: transparent;
    color: white;
    font-size: 22px;
    font-weight: 700;
}
QLabel#roleBadge {
    background: #f5d65e;
    color: #3b2b00;
    border-radius: 12px;
    padding: 6px 12px;
    font-weight: 600;
}
QWidget#topBar { background: #871b2a; border-radius: 12px; }
QTabWidget::pane {
    background: white;
    border: 1px solid #e7e0d6;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #494949;
    padding: 11px 18px;
    margin-right: 5px;
    font-weight: 600;
}
QTabBar::tab:selected {
    color: #871b2a;
    border-bottom: 3px solid #e1b922;
}
QPushButton {
    background: white;
    color: #171717;
    border: 1px solid #d8d1c7;
    border-radius: 7px;
    padding: 8px 13px;
    min-height: 24px;
    font-weight: 600;
}
QPushButton:hover { background: #f8f2e7; }
QPushButton#primaryButton {
    color: white;
    background: #a51f32;
    border: 1px solid #a51f32;
}
QPushButton#primaryButton:hover { background: #871b2a; }
QPushButton#dangerButton { color: #a51f32; }
QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox {
    background: white;
    color: #171717;
    border: 1px solid #ccc4b9;
    border-radius: 6px;
    padding: 8px 10px;
    min-height: 24px;
}
QTableView {
    background: white;
    alternate-background-color: #faf8f4;
    color: #171717;
    border: 1px solid #e1dbd1;
    border-radius: 7px;
    gridline-color: #eee9e1;
    selection-background-color: #f5e7b0;
    selection-color: #171717;
}
QHeaderView::section {
    background: #f2eee7;
    color: #343434;
    border: none;
    border-bottom: 1px solid #ddd6cb;
    padding: 10px 9px;
    font-weight: 600;
}
QLabel#card {
    background: white;
    color: #171717;
    border: 1px solid #e7e0d6;
    border-radius: 9px;
    padding: 16px;
}
"""


def show_error(parent, title, error):
    QMessageBox.critical(parent, title, str(error))


def format_money(value):
    return f"{Decimal(value):,.2f}".replace(",", " ")


class LoginDialog(QDialog):
    def __init__(self, database):
        super().__init__()
        self.database = database
        self.user = None
        self.setWindowTitle("Вход в систему")
        self.setFixedWidth(390)

        layout = QVBoxLayout(self)
        title = QLabel("Управление филиалом")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Войдите под своей учетной записью")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        form = QFormLayout()
        self.username = QLineEdit()
        self.username.setPlaceholderText("Например, manager")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Пароль")
        form.addRow("Логин", self.username)
        form.addRow("Пароль", self.password)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.error_label)
        self.login_button = QPushButton("Войти")
        self.login_button.setObjectName("primaryButton")
        layout.addWidget(self.login_button)
        self.login_button.clicked.connect(self.authenticate)
        self.username.returnPressed.connect(self.authenticate)
        self.password.returnPressed.connect(self.authenticate)
        self.username.setFocus()

    def authenticate(self):
        try:
            user = self.database.authenticate(self.username.text(), self.password.text())
        except psycopg2.Error as error:
            show_error(self, "Не удалось выполнить вход", error)
            return
        if user is None:
            self.error_label.setText("Проверьте логин и пароль.")
            return
        self.user = user
        self.accept()


class BranchDialog(QDialog):
    def __init__(self, branches, branch=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Филиал" if branch else "Новый филиал")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(branch["name"] if branch else "")
        self.address = QLineEdit(branch["address"] if branch else "")
        form.addRow("Название", self.name)
        form.addRow("Адрес", self.address)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.branch_id = branch["id"] if branch else None

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Проверьте данные", "Укажите название филиала.")
            return
        super().accept()


class EmployeeDialog(QDialog):
    def __init__(self, branches, employee=None, default_branch_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Карточка сотрудника" if employee else "Новый сотрудник")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.full_name = QLineEdit(employee["full_name"] if employee else "")
        self.position = QLineEdit(employee["position"] if employee else "")
        self.phone = QLineEdit(employee["phone"] if employee else "")
        self.branch = QComboBox()
        self.branch_map = {}
        for branch in branches:
            self.branch.addItem(branch["name"], branch["id"])
            self.branch_map[branch["id"]] = branch["name"]
        branch_id = employee["branch_id"] if employee else default_branch_id
        if branch_id is not None:
            index = self.branch.findData(branch_id)
            if index >= 0:
                self.branch.setCurrentIndex(index)
        self.active = QCheckBox("Сотрудник работает")
        self.active.setChecked(employee["active"] if employee else True)
        form.addRow("ФИО", self.full_name)
        form.addRow("Должность", self.position)
        form.addRow("Телефон", self.phone)
        form.addRow("Филиал", self.branch)
        form.addRow("", self.active)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.employee_id = employee["id"] if employee else None

    def accept(self):
        if not self.full_name.text().strip() or not self.position.text().strip():
            QMessageBox.warning(self, "Проверьте данные", "Заполните ФИО и должность.")
            return
        super().accept()


class ShiftDialog(QDialog):
    def __init__(self, database, branches, shift=None, default_branch_id=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("Запись о смене" if shift else "Новая смена")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.branch = QComboBox()
        for branch in branches:
            self.branch.addItem(branch["name"], branch["id"])
        self.employee = QComboBox()
        self.work_date = QDateEdit()
        self.work_date.setCalendarPopup(True)
        self.work_date.setDisplayFormat("dd.MM.yyyy")
        self.work_date.setDate(QDate.currentDate())
        self.shift_name = QComboBox()
        self.shift_name.addItems(["Дневная", "Ночная", "Полная"])
        self.hours = QDoubleSpinBox()
        self.hours.setRange(0, 24)
        self.hours.setDecimals(2)
        self.hours.setSuffix(" ч")
        self.shortage = QDoubleSpinBox()
        self.shortage.setRange(0, 1_000_000_000)
        self.shortage.setDecimals(2)
        self.shortage.setSuffix(" ₸")
        self.surplus = QDoubleSpinBox()
        self.surplus.setRange(0, 1_000_000_000)
        self.surplus.setDecimals(2)
        self.surplus.setSuffix(" ₸")
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Комментарий при необходимости")

        branch_id = shift["branch_id"] if shift else default_branch_id
        if branch_id is not None:
            index = self.branch.findData(branch_id)
            if index >= 0:
                self.branch.setCurrentIndex(index)

        form.addRow("Филиал", self.branch)
        form.addRow("Сотрудник", self.employee)
        form.addRow("Дата", self.work_date)
        form.addRow("Тип смены", self.shift_name)
        form.addRow("Отработано", self.hours)
        form.addRow("Недостача", self.shortage)
        form.addRow("Излишек", self.surplus)
        form.addRow("Комментарий", self.notes)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.shift_id = shift["id"] if shift else None
        self.branch.currentIndexChanged.connect(self.load_employees)
        self.load_employees()
        if shift:
            self.work_date.setDate(QDate(shift["work_date"].year, shift["work_date"].month, shift["work_date"].day))
            index = self.shift_name.findText(shift["shift_name"])
            if index >= 0:
                self.shift_name.setCurrentIndex(index)
            self.hours.setValue(float(shift["hours"]))
            self.shortage.setValue(float(shift["shortage"]))
            self.surplus.setValue(float(shift["surplus"]))
            self.notes.setText(shift["notes"])
            employee_index = self.employee.findData(shift["employee_id"])
            if employee_index >= 0:
                self.employee.setCurrentIndex(employee_index)

    def load_employees(self):
        selected_id = self.employee.currentData() if self.employee.count() else None
        self.employee.clear()
        self.employee.addItem("Не выбран", None)
        branch_id = self.branch.currentData()
        if branch_id is not None:
            for employee in self.database.get_branch_employees(branch_id):
                self.employee.addItem(
                    f"{employee['full_name']} — {employee['position']}", employee["id"]
                )
        index = self.employee.findData(selected_id)
        if index >= 0:
            self.employee.setCurrentIndex(index)


class MainWindow(QMainWindow):
    def __init__(self, database, user):
        super().__init__()
        self.database = database
        self.user = user
        self.is_manager = user["role"] == "Руководитель"
        self.setWindowTitle("Управление филиалом")
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(1280, screen.width() - 32)
        height = min(760, screen.height() - 32)
        self.resize(width, height)
        self.setMinimumSize(min(900, width), min(620, height))
        self.move(screen.left() + (screen.width() - width) // 2,
                  screen.top() + (screen.height() - height) // 2)
        self.branches = self.database.get_branches()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(16)

        header = QWidget()
        header.setObjectName("topBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        brand = QLabel("Филиал · учет и смены")
        brand.setObjectName("brand")
        role = QLabel(f"{user['role']}  ·  {user['username']}")
        role.setObjectName("roleBadge")
        header_layout.addWidget(brand)
        header_layout.addStretch()
        header_layout.addWidget(role)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dashboard(), "Обзор")
        if self.is_manager:
            self.tabs.addTab(self._build_employees(), "Сотрудники")
        self.tabs.addTab(self._build_shifts(), "База смен")
        if self.is_manager:
            self.tabs.addTab(self._build_branches(), "Филиалы")
        root.addWidget(self.tabs)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.refresh_all()

    def _make_button(self, text, slot, primary=False, danger=False):
        button = QPushButton(text)
        if primary:
            button.setObjectName("primaryButton")
        elif danger:
            button.setObjectName("dangerButton")
        button.clicked.connect(slot)
        return button

    def _make_table(self, headers):
        table = QTableView()
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.setSelectionMode(QTableView.SingleSelection)
        table.setEditTriggers(QTableView.NoEditTriggers)
        table.setSortingEnabled(True)
        table.setTextElideMode(Qt.ElideRight)
        table.setWordWrap(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(38)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setMinimumSectionSize(100)
        table.setModel(QStandardItemModel())
        table.model().setHorizontalHeaderLabels(headers)
        return table

    def _page(self, title, subtitle):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(13)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        description = QLabel(subtitle)
        description.setObjectName("muted")
        description.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(description)
        return page, layout

    def _build_dashboard(self):
        page, layout = self._page(
            "Добро пожаловать",
            "Сводка по сотрудникам и сменам. Данные хранятся в PostgreSQL.",
        )
        self.kpi_values = {}
        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        for index, (key, title) in enumerate(
            [
                ("employees", "Активных сотрудников"),
                ("today_shifts", "Смен сегодня"),
                ("shifts", "Смен за месяц"),
                ("shortage", "Недостачи за месяц"),
                ("surplus", "Излишки за месяц"),
            ]
        ):
            card = QLabel()
            card.setObjectName("card")
            card.setMinimumHeight(112)
            card.setWordWrap(True)
            card.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cards.addWidget(card, index // 3, index % 3)
            self.kpi_values[key] = (card, title)
        for column in range(3):
            cards.setColumnStretch(column, 1)
        layout.addLayout(cards)

        info = QLabel(
            "Начните с добавления сотрудников и филиалов. "
            "Старший кассир может регистрировать смены, а руководитель — "
            "управлять данными и выгружать отчеты в Excel."
        )
        info.setWordWrap(True)
        info.setObjectName("card")
        layout.addWidget(info)
        layout.addStretch()
        return page

    def _build_employees(self):
        page, layout = self._page(
            "Сотрудники",
            "Карточки персонала филиалов. Для увольнения снимите отметку «Сотрудник работает».",
        )
        toolbar = QHBoxLayout()
        self.employee_branch_filter = QComboBox()
        self._fill_branch_combo(self.employee_branch_filter, include_all=True)
        self.employee_branch_filter.currentIndexChanged.connect(self.refresh_employees)
        toolbar.addWidget(QLabel("Филиал"))
        toolbar.addWidget(self.employee_branch_filter)
        toolbar.addStretch()
        toolbar.addWidget(self._make_button("Добавить сотрудника", self.add_employee, primary=True))
        toolbar.addWidget(self._make_button("Изменить", self.edit_employee))
        toolbar.addWidget(self._make_button("Удалить", self.delete_employee, danger=True))
        layout.addLayout(toolbar)

        self.employee_table = self._make_table(
            ["ФИО", "Должность", "Телефон", "Филиал", "Статус"]
        )
        layout.addWidget(self.employee_table)
        return page

    def _build_shifts(self):
        page, layout = self._page(
            "Смены и отчеты",
            "Учет отработанного времени, недостач и излишков с фильтром по датам.",
        )
        filters = QHBoxLayout()
        self.shift_branch_filter = QComboBox()
        self.shift_branch_filter.setMinimumWidth(210)
        self._fill_branch_combo(self.shift_branch_filter, include_all=self.is_manager)
        if not self.is_manager:
            self.shift_branch_filter.setEnabled(False)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setDate(QDate.currentDate())
        self.shift_branch_filter.currentIndexChanged.connect(self.refresh_shifts)
        self.date_from.dateChanged.connect(self.refresh_shifts)
        self.date_to.dateChanged.connect(self.refresh_shifts)
        filters.addWidget(QLabel("Филиал"))
        filters.addWidget(self.shift_branch_filter)
        filters.addSpacing(10)
        filters.addWidget(QLabel("С"))
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("по"))
        filters.addWidget(self.date_to)
        filters.addStretch()
        if self.is_manager:
            filters.addWidget(self._make_button("Экспорт в Excel", self.export_excel))
        layout.addLayout(filters)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._make_button("Добавить смену", self.add_shift, primary=True))
        if self.is_manager:
            toolbar.addWidget(self._make_button("Изменить", self.edit_shift))
            toolbar.addWidget(self._make_button("Удалить", self.delete_shift, danger=True))
        toolbar.addStretch()
        self.shift_count_label = QLabel("")
        self.shift_count_label.setObjectName("muted")
        toolbar.addWidget(self.shift_count_label)
        layout.addLayout(toolbar)

        self.shift_table = self._make_table(
            ["Дата", "Смена", "Сотрудник", "Филиал", "Часы", "Недостача", "Излишек", "Комментарий"]
        )
        layout.addWidget(self.shift_table)
        return page

    def _build_branches(self):
        page, layout = self._page(
            "Филиалы",
            "Филиальная структура позволяет разделять сотрудников и смены.",
        )
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        toolbar.addWidget(self._make_button("Добавить филиал", self.add_branch, primary=True))
        toolbar.addWidget(self._make_button("Изменить", self.edit_branch))
        toolbar.addWidget(self._make_button("Удалить", self.delete_branch, danger=True))
        layout.addLayout(toolbar)
        self.branch_table = self._make_table(["Название", "Адрес"])
        layout.addWidget(self.branch_table)
        return page

    def _fill_branch_combo(self, combo, include_all, selected_id=None):
        combo.clear()
        if include_all:
            combo.addItem("Все филиалы", None)
        for branch in self.branches:
            combo.addItem(branch["name"], branch["id"])
        if selected_id is not None:
            index = combo.findData(selected_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        elif not include_all and not self.is_manager:
            index = combo.findData(self.user["branch_id"])
            if index >= 0:
                combo.setCurrentIndex(index)

    def _branch_scope(self, combo):
        if not self.is_manager:
            return self.user["branch_id"]
        return combo.currentData()

    def _selected_record(self, table, records):
        index = table.currentIndex()
        if not index.isValid():
            QMessageBox.information(self, "Выберите запись", "Сначала выберите строку в таблице.")
            return None
        return records.get(table.model().item(index.row(), 0).data(Qt.UserRole))

    def _set_model(self, table, headers, rows, id_key="id"):
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(headers)
        for record in rows:
            values = record["values"]
            items = []
            for value in values:
                item = QStandardItem("" if value is None else str(value))
                item.setEditable(False)
                items.append(item)
            items[0].setData(record[id_key], Qt.UserRole)
            model.appendRow(items)
        table.setModel(model)
        table.resizeColumnsToContents()
        for column in range(model.columnCount()):
            table.setColumnWidth(column, min(max(table.columnWidth(column), 100), 280))
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        for row in range(model.rowCount()):
            for column in range(model.columnCount()):
                item = model.item(row, column)
                item.setToolTip(item.text())

    def refresh_dashboard(self):
        branch_id = self.user["branch_id"] if not self.is_manager else None
        summary = self.database.get_dashboard_summary(branch_id)
        for key, (label, title) in self.kpi_values.items():
            value = summary[key]
            if key in ("shortage", "surplus"):
                value = f"{format_money(value)} ₸"
            label.setText(
                f"<span style='color:#555555'>{title}</span><br>"
                f"<span style='font-size:23px;font-weight:700;color:#171717'>{value}</span>"
            )

    def refresh_employees(self):
        if not hasattr(self, "employee_table"):
            return
        records = self.database.get_employees(self.employee_branch_filter.currentData())
        rows = [
            {
                "id": item["id"],
                "values": [
                    item["full_name"],
                    item["position"],
                    item["phone"],
                    item["branch"],
                    "Работает" if item["active"] else "Не работает",
                ],
            }
            for item in records
        ]
        self.employee_records = {item["id"]: item for item in records}
        self._set_model(self.employee_table, ["ФИО", "Должность", "Телефон", "Филиал", "Статус"], rows)

    def refresh_shifts(self):
        if not hasattr(self, "shift_table"):
            return
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()
        if start > end:
            self.shift_count_label.setText("Начальная дата позже конечной")
            self.shift_table.setModel(QStandardItemModel())
            return
        records = self.database.get_shifts(
            start,
            end,
            self._branch_scope(self.shift_branch_filter),
        )
        rows = [
            {
                "id": item["id"],
                "values": [
                    item["work_date"].strftime("%d.%m.%Y"),
                    item["shift_name"],
                    item["employee"] or "—",
                    item["branch"],
                    f"{Decimal(item['hours']):.2f}",
                    format_money(item["shortage"]),
                    format_money(item["surplus"]),
                    item["notes"],
                ],
            }
            for item in records
        ]
        self.shift_records = {item["id"]: item for item in records}
        self._set_model(
            self.shift_table,
            ["Дата", "Смена", "Сотрудник", "Филиал", "Часы", "Недостача", "Излишек", "Комментарий"],
            rows,
        )
        self.shift_count_label.setText(f"Записей: {len(records)}")

    def refresh_branches(self):
        if not self.is_manager:
            return
        self.branches = self.database.get_branches()
        rows = [
            {"id": item["id"], "values": [item["name"], item["address"]]}
            for item in self.branches
        ]
        self.branch_records = {item["id"]: item for item in self.branches}
        self._set_model(self.branch_table, ["Название", "Адрес"], rows)
        if hasattr(self, "employee_branch_filter"):
            selected = self.employee_branch_filter.currentData()
            self._fill_branch_combo(self.employee_branch_filter, True, selected)
        if hasattr(self, "shift_branch_filter"):
            selected = self.shift_branch_filter.currentData()
            self._fill_branch_combo(self.shift_branch_filter, self.is_manager, selected)

    def refresh_all(self):
        try:
            self.refresh_dashboard()
            self.refresh_employees()
            self.refresh_shifts()
            self.refresh_branches()
        except psycopg2.Error as error:
            show_error(self, "Не удалось загрузить данные", error)

    def _run_database_action(self, action, success_message):
        try:
            action()
            self.refresh_all()
            self.statusBar().showMessage(success_message, 5000)
        except psycopg2.errors.ForeignKeyViolation:
            QMessageBox.warning(
                self,
                "Запись используется",
                "Нельзя удалить запись, на которую ссылаются смены или учетные записи.",
            )
        except psycopg2.Error as error:
            show_error(self, "Не удалось сохранить данные", error)

    def add_employee(self):
        dialog = EmployeeDialog(
            self.branches,
            default_branch_id=self.employee_branch_filter.currentData(),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        self._run_database_action(
            lambda: self.database.save_employee(
                None,
                dialog.branch.currentData(),
                dialog.full_name.text(),
                dialog.position.text(),
                dialog.phone.text(),
                dialog.active.isChecked(),
            ),
            "Сотрудник добавлен.",
        )

    def edit_employee(self):
        employee = self._selected_record(self.employee_table, self.employee_records)
        if employee is None:
            return
        dialog = EmployeeDialog(self.branches, employee=employee, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._run_database_action(
            lambda: self.database.save_employee(
                employee["id"],
                dialog.branch.currentData(),
                dialog.full_name.text(),
                dialog.position.text(),
                dialog.phone.text(),
                dialog.active.isChecked(),
            ),
            "Данные сотрудника обновлены.",
        )

    def delete_employee(self):
        employee = self._selected_record(self.employee_table, self.employee_records)
        if employee is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить сотрудника",
            f"Удалить карточку сотрудника «{employee['full_name']}»?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._run_database_action(
                lambda: self.database.delete_employee(employee["id"]),
                "Карточка сотрудника удалена.",
            )

    def add_shift(self):
        branches = self.branches
        if not self.is_manager:
            branches = [
                branch for branch in self.branches if branch["id"] == self.user["branch_id"]
            ]
        dialog = ShiftDialog(
            self.database,
            branches,
            default_branch_id=self._branch_scope(self.shift_branch_filter),
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        self._save_shift(dialog)

    def edit_shift(self):
        shift = self._selected_record(self.shift_table, self.shift_records)
        if shift is None:
            return
        dialog = ShiftDialog(self.database, self.branches, shift=shift, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._save_shift(dialog)

    def _save_shift(self, dialog):
        self._run_database_action(
            lambda: self.database.save_shift(
                dialog.shift_id,
                dialog.branch.currentData(),
                dialog.employee.currentData(),
                dialog.work_date.date().toPyDate(),
                dialog.shift_name.currentText(),
                dialog.hours.value(),
                dialog.shortage.value(),
                dialog.surplus.value(),
                dialog.notes.text(),
                self.user["id"],
            ),
            "Смена сохранена.",
        )

    def delete_shift(self):
        shift = self._selected_record(self.shift_table, self.shift_records)
        if shift is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить смену",
            "Удалить выбранную запись о смене?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._run_database_action(
                lambda: self.database.delete_shift(shift["id"]),
                "Запись о смене удалена.",
            )

    def export_excel(self):
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()
        if start > end:
            QMessageBox.warning(self, "Проверьте период", "Начальная дата должна быть не позже конечной.")
            return
        suggested_name = f"Отчет_по_сменам_{start:%Y%m%d}-{end:%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчет",
            suggested_name,
            "Книга Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            shifts = self.database.get_shifts(start, end, self.shift_branch_filter.currentData())
            employees = self.database.get_employees(self.shift_branch_filter.currentData())
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Смены"
            headers = [
                "Дата", "Филиал", "Сотрудник", "Смена", "Часы",
                "Недостача, ₸", "Излишек, ₸", "Комментарий", "Внесено пользователем",
            ]
            sheet.append(headers)
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
                        "Работает" if employee["active"] else "Не работает",
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
            workbook.save(path)
        except (OSError, psycopg2.Error) as error:
            show_error(self, "Не удалось сохранить Excel-отчет", error)
            return
        QMessageBox.information(self, "Отчет готов", f"Файл сохранен:\n{path}")

    def add_branch(self):
        dialog = BranchDialog(self.branches, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._run_database_action(
            lambda: self.database.save_branch(None, dialog.name.text(), dialog.address.text()),
            "Филиал добавлен.",
        )

    def edit_branch(self):
        branch = self._selected_record(self.branch_table, self.branch_records)
        if branch is None:
            return
        dialog = BranchDialog(self.branches, branch=branch, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._run_database_action(
            lambda: self.database.save_branch(
                branch["id"], dialog.name.text(), dialog.address.text()
            ),
            "Данные филиала обновлены.",
        )

    def delete_branch(self):
        branch = self._selected_record(self.branch_table, self.branch_records)
        if branch is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить филиал",
            f"Удалить филиал «{branch['name']}»? Используемый филиал удалить нельзя.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._run_database_action(
                lambda: self.database.delete_branch(branch["id"]),
                "Филиал удален.",
            )


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    database = Database()
    try:
        database.initialize_when_ready()
    except psycopg2.Error as error:
        show_error(None, "Не удалось подключиться к базе данных", error)
        return 1

    login = LoginDialog(database)
    if login.exec_() != QDialog.Accepted:
        return 0
    window = MainWindow(database, login.user)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())

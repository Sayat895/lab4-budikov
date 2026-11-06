import hashlib
import hmac
import os
import secrets
import time

import psycopg2
from psycopg2.extras import RealDictCursor


PASSWORD_ITERATIONS = 310_000


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


class Database:
    def __init__(self):
        self.settings = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "dbname": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "app_db")),
            "user": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "admin")),
            "password": os.getenv("DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
            "connect_timeout": 4,
        }

    def connect(self):
        return psycopg2.connect(**self.settings)

    def initialize_when_ready(self):
        last_error = None
        for _ in range(60):
            try:
                self.initialize()
                return
            except psycopg2.OperationalError as error:
                last_error = error
                time.sleep(2)
        raise last_error

    def initialize(self):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS branches (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        address TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS employees (
                        id SERIAL PRIMARY KEY,
                        branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
                        full_name TEXT NOT NULL,
                        position TEXT NOT NULL,
                        phone TEXT NOT NULL DEFAULT '',
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_users (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL CHECK (role IN ('Руководитель', 'Старший кассир')),
                        branch_id INTEGER REFERENCES branches(id) ON DELETE RESTRICT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shifts (
                        id SERIAL PRIMARY KEY,
                        branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
                        employee_id INTEGER REFERENCES employees(id) ON DELETE RESTRICT,
                        work_date DATE NOT NULL,
                        shift_name TEXT NOT NULL,
                        hours NUMERIC(5, 2) NOT NULL CHECK (hours >= 0 AND hours <= 24),
                        shortage NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (shortage >= 0),
                        surplus NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (surplus >= 0),
                        notes TEXT NOT NULL DEFAULT '',
                        created_by INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS shifts_work_date_idx ON shifts(work_date)")
                cursor.execute("CREATE INDEX IF NOT EXISTS employees_branch_idx ON employees(branch_id)")

                cursor.execute(
                    """
                    INSERT INTO branches (name, address) VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (
                        os.getenv("APP_BRANCH_NAME", "Главный филиал"),
                        os.getenv("APP_BRANCH_ADDRESS", ""),
                    ),
                )
                cursor.execute(
                    "SELECT id FROM branches WHERE name = %s",
                    (os.getenv("APP_BRANCH_NAME", "Главный филиал"),),
                )
                branch_id = cursor.fetchone()[0]
                accounts = (
                    (
                        "Руководитель",
                        os.getenv("APP_ADMIN_USER", ""),
                        os.getenv("APP_ADMIN_PASSWORD", ""),
                        None,
                    ),
                    (
                        "Старший кассир",
                        os.getenv("APP_CASHIER_USER", ""),
                        os.getenv("APP_CASHIER_PASSWORD", ""),
                        branch_id,
                    ),
                )
                if any(not username or not password for _, username, password, _ in accounts):
                    raise ValueError("Set both application accounts in the .env file.")
                if accounts[0][1] == accounts[1][1]:
                    raise ValueError("Manager and cashier accounts must use different usernames.")

                for role, username, password, account_branch_id in accounts:
                    cursor.execute(
                        "SELECT id FROM app_users WHERE role = %s ORDER BY id LIMIT 1",
                        (role,),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        cursor.execute(
                            """
                            UPDATE app_users
                            SET username = %s, password_hash = %s, branch_id = %s
                            WHERE id = %s
                            """,
                            (username, hash_password(password), account_branch_id, existing[0]),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO app_users (username, password_hash, role, branch_id)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (username, hash_password(password), role, account_branch_id),
                        )

    def authenticate(self, username, password):
        with self.connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, username, password_hash, role, branch_id
                    FROM app_users WHERE username = %s
                    """,
                    (username.strip(),),
                )
                user = cursor.fetchone()
        if user and verify_password(password, user["password_hash"]):
            return {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "branch_id": user["branch_id"],
            }
        return None

    def get_branches(self):
        with self.connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id, name, address FROM branches ORDER BY name")
                return cursor.fetchall()

    def save_branch(self, branch_id, name, address):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                if branch_id is None:
                    cursor.execute(
                        "INSERT INTO branches (name, address) VALUES (%s, %s)",
                        (name.strip(), address.strip()),
                    )
                else:
                    cursor.execute(
                        "UPDATE branches SET name = %s, address = %s WHERE id = %s",
                        (name.strip(), address.strip(), branch_id),
                    )

    def delete_branch(self, branch_id):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM branches WHERE id = %s", (branch_id,))

    def get_employees(self, branch_id=None):
        query = """
            SELECT e.id, e.branch_id, e.full_name, e.position, e.phone, e.active, b.name AS branch
            FROM employees e JOIN branches b ON b.id = e.branch_id
        """
        parameters = ()
        if branch_id is not None:
            query += " WHERE e.branch_id = %s"
            parameters = (branch_id,)
        query += " ORDER BY e.active DESC, e.full_name"
        with self.connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchall()

    def get_branch_employees(self, branch_id):
        with self.connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id, full_name, position FROM employees "
                    "WHERE branch_id = %s AND active = TRUE ORDER BY full_name",
                    (branch_id,),
                )
                return cursor.fetchall()

    def save_employee(self, employee_id, branch_id, full_name, position, phone, active):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                if employee_id is None:
                    cursor.execute(
                        """
                        INSERT INTO employees (branch_id, full_name, position, phone, active)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (branch_id, full_name.strip(), position.strip(), phone.strip(), active),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE employees
                        SET branch_id = %s, full_name = %s, position = %s, phone = %s, active = %s
                        WHERE id = %s
                        """,
                        (branch_id, full_name.strip(), position.strip(), phone.strip(), active, employee_id),
                    )

    def delete_employee(self, employee_id):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM employees WHERE id = %s", (employee_id,))

    def get_shifts(self, start_date, end_date, branch_id=None):
        query = """
            SELECT s.id, s.branch_id, s.employee_id, s.work_date, s.shift_name, s.hours, s.shortage, s.surplus,
                   s.notes, b.name AS branch, e.full_name AS employee, u.username AS created_by
            FROM shifts s
            JOIN branches b ON b.id = s.branch_id
            LEFT JOIN employees e ON e.id = s.employee_id
            LEFT JOIN app_users u ON u.id = s.created_by
            WHERE s.work_date BETWEEN %s AND %s
        """
        parameters = [start_date, end_date]
        if branch_id is not None:
            query += " AND s.branch_id = %s"
            parameters.append(branch_id)
        query += " ORDER BY s.work_date DESC, s.id DESC"
        with self.connect() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchall()

    def save_shift(
        self,
        shift_id,
        branch_id,
        employee_id,
        work_date,
        shift_name,
        hours,
        shortage,
        surplus,
        notes,
        user_id,
    ):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                if shift_id is None:
                    cursor.execute(
                        """
                        INSERT INTO shifts
                            (branch_id, employee_id, work_date, shift_name, hours,
                             shortage, surplus, notes, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            branch_id,
                            employee_id,
                            work_date,
                            shift_name,
                            hours,
                            shortage,
                            surplus,
                            notes.strip(),
                            user_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE shifts
                        SET branch_id = %s, employee_id = %s, work_date = %s,
                            shift_name = %s, hours = %s, shortage = %s,
                            surplus = %s, notes = %s
                        WHERE id = %s
                        """,
                        (
                            branch_id,
                            employee_id,
                            work_date,
                            shift_name,
                            hours,
                            shortage,
                            surplus,
                            notes.strip(),
                            shift_id,
                        ),
                    )

    def delete_shift(self, shift_id):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM shifts WHERE id = %s", (shift_id,))

    def get_dashboard_summary(self, branch_id=None):
        branch_filter = "WHERE branch_id = %s" if branch_id is not None else ""
        parameters = (branch_id,) if branch_id is not None else ()
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM employees {branch_filter}"
                    f"{' AND' if branch_id is not None else ' WHERE'} active = TRUE",
                    parameters,
                )
                employee_count = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT COUNT(*),
                           COALESCE(SUM(shortage), 0),
                           COALESCE(SUM(surplus), 0),
                           COUNT(*) FILTER (WHERE shortage > 0),
                           COUNT(*) FILTER (WHERE surplus > 0),
                           COUNT(*) FILTER (WHERE shortage = 0 AND surplus = 0)
                    FROM shifts
                    WHERE work_date >= DATE_TRUNC('month', CURRENT_DATE)::date
                    """
                    + (" AND branch_id = %s" if branch_id is not None else ""),
                    parameters,
                )
                (
                    monthly_shifts,
                    monthly_shortage,
                    monthly_surplus,
                    shortage_shifts,
                    surplus_shifts,
                    no_deviation_shifts,
                ) = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM shifts WHERE work_date = CURRENT_DATE"
                    + (" AND branch_id = %s" if branch_id is not None else ""),
                    parameters,
                )
                today_shifts = cursor.fetchone()[0]
        return {
            "employees": employee_count,
            "shifts": monthly_shifts,
            "today_shifts": today_shifts,
            "shortage": monthly_shortage,
            "surplus": monthly_surplus,
            "shortage_shifts": shortage_shifts,
            "surplus_shifts": surplus_shifts,
            "no_deviation_shifts": no_deviation_shifts,
        }

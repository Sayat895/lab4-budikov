import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { getDesktopApi, queryString, request, setAccessToken } from "./api.js";

const localDate = (date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const today = localDate(new Date());
const monthAgo = localDate(new Date(Date.now() - 30 * 86400000));
const employeeStatuses = ["Работает", "В отпуске", "На больничном", "Не работает"];
function money(value) {
  return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2 }).format(Number(value || 0));
}
function statusClass(status) {
  return {
    "Работает": "active",
    "В отпуске": "vacation",
    "На больничном": "sick-leave",
    "Не работает": "inactive",
  }[status] || "";
}

function App() {
  const [user, setUser] = useState(null);
  const [view, setView] = useState("dashboard");
  const [pageData, setPageData] = useState({ branches: [], employees: [], shifts: [], summary: {} });
  const [branchFilter, setBranchFilter] = useState("");
  const [employeeBranchFilter, setEmployeeBranchFilter] = useState("");
  const [employeePositionFilter, setEmployeePositionFilter] = useState("");
  const [employeeStatusFilter, setEmployeeStatusFilter] = useState("");
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [startDate, setStartDate] = useState(monthAgo);
  const [endDate, setEndDate] = useState(today);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const isManager = user?.role === "Руководитель";

  const loadData = useCallback(async () => {
    if (!user) return;
    setError("");
    try {
      const branchId = isManager ? branchFilter || undefined : user.branch_id;
      const [branches, summary, employees, shifts] = await Promise.all([
        request("/branches"),
        request(`/dashboard${queryString({ branch_id: branchId })}`),
        request(`/employees${queryString({ branch_id: isManager ? undefined : user.branch_id })}`),
        request(
          `/shifts${queryString({
            start_date: startDate,
            end_date: endDate,
            branch_id: branchId,
          })}`,
        ),
      ]);
      setPageData({ branches, summary, employees, shifts });
    } catch (loadError) {
      setError(loadError.message);
    }
  }, [branchFilter, endDate, isManager, startDate, user]);

  useEffect(() => {
    if (user) loadData();
  }, [loadData, user]);

  useEffect(() => {
    if (!user) return undefined;
    const onKeyDown = (event) => {
      if (event.ctrlKey && event.key.toLowerCase() === "r") {
        event.preventDefault();
        loadData();
      }
      if (event.ctrlKey && event.key.toLowerCase() === "q") {
        event.preventDefault();
        logout();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [loadData, user]);

  async function login(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const session = await request("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });
      setAccessToken(session.access_token);
      setUser(session.user);
    } catch (loginError) {
      setError(loginError.message);
    }
  }

  async function logout() {
    try {
      await request("/auth/logout", { method: "POST" });
    } catch (logoutError) {
      setError(logoutError.message);
    } finally {
      setAccessToken(null);
      setUser(null);
      setPageData({ branches: [], employees: [], shifts: [], summary: {} });
      setView("dashboard");
    }
  }

  async function saveRecord(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const values = Object.fromEntries(form.entries());
    const { type, record } = modal;
    let path;
    let method;
    let body;

    if (type === "branch") {
      path = record ? `/branches/${record.id}` : "/branches";
      method = record ? "PUT" : "POST";
      body = { name: values.name.trim(), address: values.address.trim() };
    } else if (type === "employee") {
      path = record ? `/employees/${record.id}` : "/employees";
      method = record ? "PUT" : "POST";
      body = {
        branch_id: Number(values.branch_id),
        full_name: values.full_name.trim(),
        position: values.position.trim(),
        phone: values.phone.trim(),
        status: values.status,
      };
    } else {
      path = record ? `/shifts/${record.id}` : "/shifts";
      method = record ? "PUT" : "POST";
      body = {
        branch_id: Number(values.branch_id),
        employee_id: values.employee_id ? Number(values.employee_id) : null,
        work_date: values.work_date,
        shift_name: values.shift_name,
        hours: Number(values.hours),
        shortage: Number(values.shortage),
        surplus: Number(values.surplus),
        notes: values.notes.trim(),
      };
    }

    try {
      const result = await request(path, { method, body: JSON.stringify(body) });
      setModal(null);
      setNotice(result?.message || "Изменения сохранены.");
      await loadData();
    } catch (saveError) {
      setError(saveError.message);
    }
  }

  async function deleteRecord(type, record) {
    const label = type === "branch" ? `филиал «${record.name}»` : type === "employee"
      ? `сотрудника «${record.full_name}»`
      : "выбранную смену";
    if (!window.confirm(`Удалить ${label}?`)) return;
    try {
      await request(`/${type === "branch" ? "branches" : type === "employee" ? "employees" : "shifts"}/${record.id}`, {
        method: "DELETE",
      });
      setNotice("Запись удалена.");
      await loadData();
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  async function exportReport() {
    if (startDate > endDate) {
      setError("Начальная дата должна быть не позже конечной.");
      return;
    }
    const params = queryString({
      start_date: startDate,
      end_date: endDate,
      branch_id: isManager ? branchFilter || undefined : user.branch_id,
    });
    setExporting(true);
    try {
      const response = await request(`/reports/shifts.xlsx${params}`);
      const filename = `Отчет_по_сменам_${startDate.replaceAll("-", "")}-${endDate.replaceAll("-", "")}.xlsx`;
      const bytes = new Uint8Array(await response.arrayBuffer());
      let binary = "";
      for (let offset = 0; offset < bytes.length; offset += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
      }

      if (new URLSearchParams(window.location.search).get("desktop") === "1") {
        const desktopApi = await getDesktopApi();
        const result = await desktopApi.save_report(filename, window.btoa(binary));
        if (!result.cancelled) setNotice(`Отчет сохранен: ${result.path}`);
      } else {
        const url = URL.createObjectURL(new Blob([bytes], { type: response.headers.get("content-type") }));
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        setNotice("Отчет загружен.");
      }
    } catch (exportError) {
      setError(exportError.message);
    } finally {
      setExporting(false);
    }
  }

  const visibleShifts = pageData.shifts;
  const employeePositions = [...new Set(pageData.employees.map((employee) => employee.position))]
    .sort((left, right) => left.localeCompare(right, "ru"));
  const normalizedEmployeeSearch = employeeSearch.trim().toLocaleLowerCase("ru");
  const visibleEmployees = pageData.employees.filter((employee) => {
    const matchesSearch = !normalizedEmployeeSearch
      || [employee.full_name, employee.position, employee.phone, employee.branch]
        .join(" ")
        .toLocaleLowerCase("ru")
        .includes(normalizedEmployeeSearch);
    const matchesBranch = !employeeBranchFilter || String(employee.branch_id) === employeeBranchFilter;
    const matchesPosition = !employeePositionFilter || employee.position === employeePositionFilter;
    const matchesStatus = !employeeStatusFilter || employee.status === employeeStatusFilter;
    return matchesSearch && matchesBranch && matchesPosition && matchesStatus;
  });
  const navigation = [
    ["dashboard", "Обзор", "◫"],
    ["employees", "Сотрудники", "♙"],
    ["shifts", "Смены и отчеты", "▤"],
    ...(isManager ? [["branches", "Филиалы", "⌂"]] : []),
  ];

  if (!user) {
    return (
      <main className="login-shell">
        <section className="login-brand-panel">
          <div className="brand-mark">Ф</div>
          <div>
            <p className="eyebrow">УЧЕТ И ОПЕРАЦИИ</p>
            <h2>Каждая смена<br />под контролем.</h2>
            <p>Рабочее пространство для людей, филиалов и ежедневных результатов.</p>
          </div>
          <span className="login-panel-footer">ОПЕРАЦИИ · УЧЕТ · РЕЗУЛЬТАТ</span>
        </section>
        <form className="login-card" onSubmit={login}>
          <p className="eyebrow">УПРАВЛЕНИЕ ФИЛИАЛОМ</p>
          <h1>Добро пожаловать</h1>
          <p className="muted">Войдите в рабочее пространство</p>
          <label>Логин<input name="username" autoComplete="username" required autoFocus /></label>
          <label>Пароль<input name="password" type="password" autoComplete="current-password" required /></label>
          {error && <p className="error">{error}</p>}
          <button className="primary full-width" type="submit">Войти</button>
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark small">Ф</span><span>Филиал<small>Учет и смены</small></span></div>
        <nav>
          <span className="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</span>
          {navigation.map(([id, title, icon]) => (
            <button key={id} className={`nav-item ${view === id ? "selected" : ""}`} onClick={() => setView(id)}>
              <span className="nav-icon">{icon}</span>{title}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="user-avatar">{user.username.slice(0, 1).toUpperCase()}</div>
          <div className="user-info"><strong>{user.username}</strong><small>{user.role}</small></div>
          <button className="icon-button" title="Выйти" onClick={logout}>↪</button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div><span className="eyebrow">РАБОЧАЯ ПАНЕЛЬ</span><h1>{navigation.find(([id]) => id === view)?.[1]}</h1></div>
          <div className="top-actions">
            <span className="role-pill">{user.role}</span>
            <button className="button" onClick={loadData}>Обновить</button>
          </div>
        </header>
        <section className="content">
          {error && <div className="alert" role="alert">{error}<button onClick={() => setError("")}>×</button></div>}
          {notice && <div className="notice" role="status">{notice}<button onClick={() => setNotice("")}>×</button></div>}

          {view === "dashboard" && (
            <>
              <div className="page-intro"><div><h2>Добро пожаловать</h2><p>Сводка по сотрудникам и сменам за текущий месяц.</p></div><span className="date-chip">{new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}</span></div>
              <div className="kpi-grid">
                <Metric title="Активных сотрудников" value={pageData.summary.employees ?? "—"} accent="red" />
                <Metric title="Смен сегодня" value={pageData.summary.today_shifts ?? "—"} />
                <Metric title="Смен за месяц" value={pageData.summary.shifts ?? "—"} />
                <Metric title="Недостачи за месяц" value={`${pageData.summary.shortage_shifts ?? 0} смен`} detail={`${money(pageData.summary.shortage)} ₸`} accent="red" />
                <Metric title="Излишки за месяц" value={`${pageData.summary.surplus_shifts ?? 0} смен`} detail={`${money(pageData.summary.surplus)} ₸`} accent="gold" />
                <Metric title="Без отклонений" value={`${pageData.summary.no_deviation_shifts ?? 0} смен`} accent="green" />
              </div>
              <div className="panel welcome-panel"><div className="welcome-icon">✦</div><div><h3>Рабочее пространство филиала</h3><p>Регистрируйте смены, отслеживайте кассовые отклонения и формируйте отчеты. Данные хранятся в PostgreSQL.</p></div></div>
            </>
          )}

          {view === "employees" && (
            <Panel
              title="Сотрудники"
              description={isManager
                ? "Карточки персонала филиалов."
                : "Сотрудники вашего филиала. Редактирование доступно руководителю."}
            >
              <div className="toolbar">
                <SelectField
                  ariaLabel="Фильтр по филиалу"
                  className="filter-select employee-filter-select"
                  value={employeeBranchFilter}
                  onChange={setEmployeeBranchFilter}
                  options={[
                    { value: "", label: "Все филиалы", detail: "Все доступные филиалы" },
                    ...pageData.branches.map((branch) => ({
                      value: branch.id,
                      label: branch.name,
                      detail: branch.address,
                    })),
                  ]}
                />
                <SelectField
                  ariaLabel="Фильтр по должности"
                  className="filter-select employee-filter-select"
                  value={employeePositionFilter}
                  onChange={setEmployeePositionFilter}
                  options={[
                    { value: "", label: "Все должности" },
                    ...employeePositions.map((position) => ({ value: position, label: position })),
                  ]}
                />
                <SelectField
                  ariaLabel="Фильтр по статусу"
                  className="filter-select employee-filter-select"
                  value={employeeStatusFilter}
                  onChange={setEmployeeStatusFilter}
                  options={[
                    { value: "", label: "Любой статус" },
                    { value: "Работает", label: "Работает" },
                    { value: "В отпуске", label: "В отпуске" },
                    { value: "На больничном", label: "На больничном" },
                    { value: "Не работает", label: "Не работает" },
                  ]}
                />
                <input
                  className="employee-search"
                  type="search"
                  aria-label="Поиск сотрудников"
                  placeholder="Имя, должность или телефон"
                  value={employeeSearch}
                  onChange={(event) => setEmployeeSearch(event.target.value)}
                />
                {isManager && <>
                  <span className="spacer" />
                  <button className="primary" onClick={() => setModal({ type: "employee" })}>＋ Добавить сотрудника</button>
                </>}
              </div>
              <DataTable columns={["ФИО", "Должность", "Телефон", "Филиал", "Статус", ...(isManager ? [""] : [])]} rows={visibleEmployees.map((employee) => [
                employee.full_name, employee.position, employee.phone || "—", employee.branch,
                <span className={`status ${statusClass(employee.status)}`} key="status">{employee.status}</span>,
                ...(isManager ? [<RowActions key="actions" onEdit={() => setModal({ type: "employee", record: employee })} onDelete={() => deleteRecord("employee", employee)} />] : []),
              ])} />
              <div className="table-footer">Показано: {visibleEmployees.length} из {pageData.employees.length}</div>
            </Panel>
          )}

          {view === "shifts" && (
            <Panel title="Смены и отчеты" description="Учет отработанного времени, недостач и излишков.">
              <div className="toolbar filters">
                {isManager && (
                  <SelectField
                    ariaLabel="Фильтр по филиалу"
                    className="filter-select"
                    value={branchFilter}
                    onChange={setBranchFilter}
                    options={[
                      { value: "", label: "Все филиалы", detail: "Все доступные филиалы" },
                      ...pageData.branches.map((branch) => ({
                        value: branch.id,
                        label: branch.name,
                        detail: branch.address,
                      })),
                    ]}
                  />
                )}
                <label>С<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                <label>По<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
                <span className="spacer" />
                <button className="button export-button" onClick={exportReport} disabled={exporting}>
                  <span aria-hidden="true">↓</span>{exporting ? "Формируем отчет…" : "Экспорт в Excel"}
                </button>
                <button className="primary" onClick={() => setModal({ type: "shift" })}>＋ Добавить смену</button>
              </div>
              <DataTable columns={["Дата", "Смена", "Сотрудник", "Филиал", "Часы", "Недостача", "Излишек", "Комментарий", ...(isManager ? [""] : [])]} rows={visibleShifts.map((shift) => [
                new Date(`${shift.work_date}T00:00:00`).toLocaleDateString("ru-RU"),
                shift.shift_name, shift.employee || "—", shift.branch, Number(shift.hours).toFixed(2),
                `${money(shift.shortage)} ₸`, `${money(shift.surplus)} ₸`, shift.notes || "—",
                ...(isManager ? [<RowActions key="actions" onEdit={() => setModal({ type: "shift", record: shift })} onDelete={() => deleteRecord("shift", shift)} />] : []),
              ])} />
              <div className="table-footer">Записей: {visibleShifts.length}</div>
            </Panel>
          )}

          {view === "branches" && isManager && (
            <Panel title="Филиалы" description="Филиальная структура позволяет разделять сотрудников и смены.">
              <div className="toolbar"><span className="spacer" /><button className="primary" onClick={() => setModal({ type: "branch" })}>＋ Добавить филиал</button></div>
              <DataTable columns={["Название", "Адрес", ""]} rows={pageData.branches.map((branch) => [
                branch.name, branch.address || "—",
                <RowActions key="actions" onEdit={() => setModal({ type: "branch", record: branch })} onDelete={() => deleteRecord("branch", branch)} />,
              ])} />
            </Panel>
          )}
        </section>
      </main>

      {modal && <RecordModal modal={modal} branches={pageData.branches} defaultBranchId={branchFilter || user.branch_id} onClose={() => setModal(null)} onSubmit={saveRecord} onError={setError} />}
    </div>
  );
}

function Metric({ title, value, detail, accent = "blue" }) {
  return <article className={`metric ${accent}`}><span className="metric-dot" /><p>{title}</p><strong>{value}</strong>{detail && <small>{detail}</small>}</article>;
}

function Panel({ title, description, children }) {
  return <article className="panel"><div className="panel-heading"><div><h2>{title}</h2><p>{description}</p></div></div>{children}</article>;
}

function DataTable({ columns, rows }) {
  if (!rows.length) return <div className="empty-state"><span>▤</span><strong>Нет записей</strong><p>Измените фильтры или добавьте новую запись.</p></div>;
  return <div className="table-wrap"><table><thead><tr>{columns.map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

function RowActions({ onEdit, onDelete }) {
  return <div className="row-actions"><button title="Изменить" onClick={onEdit}>Изменить</button><button title="Удалить" className="delete-action" onClick={onDelete}>Удалить</button></div>;
}

function SelectField({
  value,
  onChange,
  options,
  ariaLabel,
  name,
  className = "",
  disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const searchRef = useRef(null);
  const menuRef = useRef(null);
  const menuId = useId();
  const normalizedOptions = options.map((option) => ({
    ...option,
    value: String(option.value),
  }));
  const selected = normalizedOptions.find((option) => option.value === String(value ?? ""));
  const isSearchable = normalizedOptions.length > 6;
  const visibleOptions = normalizedOptions.filter((option) =>
    `${option.label} ${option.detail || ""}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );

  useEffect(() => {
    if (!open) return undefined;
    window.requestAnimationFrame(() => {
      if (isSearchable) searchRef.current?.focus();
      else menuRef.current?.querySelector('[aria-selected="true"]')?.focus();
    });
    const closeOnOutsideClick = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isSearchable, open]);

  function chooseOption(option) {
    onChange(option.value);
    setOpen(false);
    setSearch("");
    buttonRef.current?.focus();
  }

  function handleTriggerKeyDown(event) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen(true);
    }
  }

  function handleOptionKeyDown(event) {
    const optionButtons = Array.from(
      menuRef.current?.querySelectorAll('[role="option"]') || [],
    );
    const currentIndex = optionButtons.indexOf(document.activeElement);
    let nextIndex;
    if (event.key === "ArrowDown") nextIndex = Math.min(currentIndex + 1, optionButtons.length - 1);
    if (event.key === "ArrowUp") nextIndex = Math.max(currentIndex - 1, 0);
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = optionButtons.length - 1;
    if (nextIndex !== undefined) {
      event.preventDefault();
      optionButtons[nextIndex]?.focus();
    }
  }

  return (
    <div className={`select-field ${className} ${open ? "is-open" : ""}`} ref={rootRef}>
      {name && <input type="hidden" name={name} value={value ?? ""} />}
      <button
        ref={buttonRef}
        type="button"
        className="select-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={handleTriggerKeyDown}
      >
        <span className="select-value">{selected?.label || "Выберите значение"}</span>
        <span className="select-chevron" aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div ref={menuRef} className="select-menu" id={menuId} role="listbox" aria-label={ariaLabel}>
          {isSearchable && (
            <div className="select-search-wrap">
              <span aria-hidden="true">⌕</span>
              <input
                ref={searchRef}
                className="select-search"
                type="search"
                value={search}
                placeholder="Найти в списке…"
                aria-label="Поиск по списку"
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          )}
          <div className="select-options">
            {visibleOptions.length ? visibleOptions.map((option) => {
              const isSelected = option.value === String(value ?? "");
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  className={`select-option ${isSelected ? "selected" : ""}`}
                  onClick={() => chooseOption(option)}
                  onKeyDown={handleOptionKeyDown}
                >
                  <span className="select-option-copy">
                    <span>{option.label}</span>
                    {option.detail && <small>{option.detail}</small>}
                  </span>
                  {isSelected && <span className="select-check" aria-hidden="true">✓</span>}
                </button>
              );
            }) : <p className="select-no-results">Ничего не найдено</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function RecordModal({ modal, branches, defaultBranchId, onClose, onSubmit, onError }) {
  const [employees, setEmployees] = useState([]);
  const initialBranch = modal.record?.branch_id ?? defaultBranchId ?? branches[0]?.id ?? "";
  const [selectedBranch, setSelectedBranch] = useState(String(initialBranch));
  const [selectedEmployeeStatus, setSelectedEmployeeStatus] = useState(
    modal.record?.status || (modal.record?.active === false ? "Не работает" : "Работает"),
  );
  const [selectedEmployee, setSelectedEmployee] = useState(String(modal.record?.employee_id ?? ""));
  const [selectedShiftName, setSelectedShiftName] = useState(modal.record?.shift_name || "Дневная");
  useEffect(() => {
    if (modal.type !== "shift" || !selectedBranch) {
      setEmployees([]);
      return;
    }
    let active = true;
    request(`/employees/branch/${selectedBranch}`)
      .then((result) => {
        if (active) setEmployees(result);
      })
      .catch((loadError) => {
        if (active) setEmployees([]);
        if (active) onError(loadError.message);
      });
    return () => { active = false; };
  }, [modal.type, onError, selectedBranch]);
  const { type, record } = modal;
  const title = `${record ? "Изменить" : "Добавить"} ${type === "branch" ? "филиал" : type === "employee" ? "сотрудника" : "смену"}`;
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal" onSubmit={onSubmit}>
        <div className="modal-heading"><div><span className="eyebrow">КАРТОЧКА ЗАПИСИ</span><h2>{title}</h2></div><button type="button" className="icon-button" onClick={onClose}>×</button></div>
        {type === "branch" && <>
          <label>Название<input name="name" required maxLength="200" defaultValue={record?.name || ""} autoFocus /></label>
          <label>Адрес<input name="address" maxLength="500" defaultValue={record?.address || ""} /></label>
        </>}
        {type === "employee" && <>
          <label>ФИО<input name="full_name" required defaultValue={record?.full_name || ""} autoFocus /></label>
          <label>Должность<input name="position" required defaultValue={record?.position || ""} /></label>
          <label>Телефон<input name="phone" type="tel" required maxLength="50" placeholder="+7 700 000 00 00" defaultValue={record?.phone || ""} /></label>
          <label className="select-label">Филиал
            <SelectField
              name="branch_id"
              ariaLabel="Филиал"
              value={selectedBranch}
              onChange={setSelectedBranch}
              options={branches.map((branch) => ({
                value: branch.id,
                label: branch.name,
                detail: branch.address,
              }))}
            />
          </label>
          <label className="select-label">Статус
            <SelectField
              name="status"
              ariaLabel="Статус сотрудника"
              value={selectedEmployeeStatus}
              onChange={setSelectedEmployeeStatus}
              options={employeeStatuses.map((status) => ({ value: status, label: status }))}
            />
          </label>
        </>}
        {type === "shift" && <>
          <label className="select-label">Филиал
            <SelectField
              name="branch_id"
              ariaLabel="Филиал"
              value={selectedBranch}
              onChange={(value) => {
                setSelectedBranch(value);
                setSelectedEmployee("");
              }}
              options={branches.map((branch) => ({
                value: branch.id,
                label: branch.name,
                detail: branch.address,
              }))}
            />
          </label>
          <label className="select-label">Сотрудник
            <SelectField
              name="employee_id"
              ariaLabel="Сотрудник"
              value={selectedEmployee}
              onChange={setSelectedEmployee}
              options={[
                { value: "", label: "Не выбран", detail: "Смену можно сохранить без сотрудника" },
                ...employees.map((employee) => ({
                  value: employee.id,
                  label: employee.full_name,
                  detail: employee.position,
                })),
              ]}
            />
          </label>
          <label>Дата<input name="work_date" type="date" required defaultValue={record?.work_date || today} /></label>
          <label className="select-label">Тип смены
            <SelectField
              name="shift_name"
              ariaLabel="Тип смены"
              value={selectedShiftName}
              onChange={setSelectedShiftName}
              options={["Дневная", "Ночная", "Полная"].map((name) => ({ value: name, label: name }))}
            />
          </label>
          <div className="form-grid">
            <label>Отработано, ч<input name="hours" type="number" min="0" max="24" step="0.25" defaultValue={record?.hours ?? 8} /></label>
            <label>Недостача, ₸<input name="shortage" type="number" min="0" step="0.01" defaultValue={record?.shortage ?? 0} /></label>
            <label>Излишек, ₸<input name="surplus" type="number" min="0" step="0.01" defaultValue={record?.surplus ?? 0} /></label>
          </div>
          <label>Комментарий<input name="notes" maxLength="2000" defaultValue={record?.notes || ""} /></label>
        </>}
        <div className="modal-actions"><button type="button" className="button" onClick={onClose}>Отмена</button><button className="primary" type="submit">Сохранить</button></div>
      </form>
    </div>
  );
}

export default App;

const API_ROOT = "/api";
let accessToken = null;

export function setAccessToken(token) {
  accessToken = token;
}

export function getDesktopApi() {
  if (window.pywebview?.api?.save_report) {
    return Promise.resolve(window.pywebview.api);
  }
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("pywebviewready", onReady);
      reject(new Error("Не удалось подключиться к окну сохранения. Перезапустите приложение."));
    }, 10000);
    function onReady() {
      window.clearTimeout(timeout);
      if (window.pywebview?.api?.save_report) resolve(window.pywebview.api);
      else reject(new Error("Окно приложения не поддерживает сохранение файлов."));
    }
    window.addEventListener("pywebviewready", onReady, { once: true });
  });
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_ROOT}${path}`, { ...options, headers });
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    const body = contentType.includes("application/json") ? await response.json() : null;
    throw new Error(body?.detail || `Ошибка запроса (${response.status}).`);
  }
  if (contentType.includes("application/json")) return response.json();
  return response;
}

export function queryString(values) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  });
  const result = query.toString();
  return result ? `?${result}` : "";
}

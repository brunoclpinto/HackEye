// Thin fetch wrapper. Errors become toasts using FastAPI's {"detail": ...}.
import { toast } from "./util.js";

export async function api(path, { method = "GET", body, quiet = false } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    if (!quiet) toast(`${method} ${path}: network error (${e.message})`);
    throw e;
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j && j.detail !== undefined) {
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      }
    } catch { /* non-JSON error body */ }
    if (!quiet) toast(`${method} ${path}: ${detail}`);
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

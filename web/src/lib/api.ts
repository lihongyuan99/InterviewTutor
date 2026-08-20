/**
 * 统一的 API 访问层。
 * 后端固定运行在 127.0.0.1:8001，可通过 VITE_API_BASE_URL 覆盖。
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001/api/v1";

export const ENABLE_STREAMING: boolean =
  (import.meta.env.VITE_ENABLE_STREAMING ?? "true").toString().toLowerCase() !== "false";

/** 从错误响应体中提取可读信息 */
export async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (data && typeof data.detail === "string" && data.detail.trim()) {
      return data.detail;
    }
  } catch {
    // 非 JSON 响应，忽略
  }
  return `请求失败（${response.status}）`;
}

/** 统一 fetch 封装：非 2xx 时抛出带后端 detail 的 Error */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return response;
}

/** GET JSON 便捷方法 */
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  return (await response.json()) as T;
}

/** 发送 JSON 的便捷方法（POST/PUT/PATCH/DELETE） */
export async function apiSend<T = unknown>(
  path: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const response = await apiFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
  });
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

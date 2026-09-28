// REST API (ルーム作成・参加) の薄いラッパー。
// fetchの失敗・4xx/5xxレスポンスをここで一箇所にまとめてApiErrorに変換し、
// 呼び出し側(top.js / room.js)はtry/catchだけ書けばよいようにする。

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

async function request(path, options) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail ?? {};
    throw new ApiError(detail.code ?? "UNKNOWN_ERROR", detail.message ?? "通信に失敗しました");
  }
  return body;
}

export function createRoom(settings) {
  return request("/api/rooms", { method: "POST", body: JSON.stringify(settings) });
}

export function joinRoom(code, name) {
  return request(`/api/rooms/${encodeURIComponent(code)}/join`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getRoomInfo(code) {
  return request(`/api/rooms/${encodeURIComponent(code)}`, { method: "GET" });
}

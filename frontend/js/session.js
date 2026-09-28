// ルームごとのセッション情報(player_id / token)をsessionStorageに保存する。
// localStorageではなくsessionStorageを使うのは、タブを閉じれば自動的に
// 消える方が「別人が同じ端末の別タブで参加する」誤操作を防ぎやすいため。

const PREFIX = "hitblow_session_";

export function saveSession(roomCode, playerId, token) {
  sessionStorage.setItem(PREFIX + roomCode, JSON.stringify({ playerId, token }));
}

export function loadSession(roomCode) {
  const raw = sessionStorage.getItem(PREFIX + roomCode);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearSession(roomCode) {
  sessionStorage.removeItem(PREFIX + roomCode);
}

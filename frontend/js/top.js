// トップページ(index.html)のロジック:
// ルーム作成 / ひとりで遊ぶ(CPU相手) / コードで参加、の3操作をここでまとめる。

import { createRoom, joinRoom, ApiError } from "./api.js";
import { saveSession } from "./session.js";
import { showToast } from "./dom.js";

const nameInput = document.getElementById("input-name");
const formPlay = document.getElementById("form-play");
const btnSolo = document.getElementById("btn-solo");
const formJoin = document.getElementById("form-join");

function readSettings() {
  const digits = Number(document.querySelector('input[name="digits"]:checked').value);
  const allowDuplicate = document.getElementById("input-allow-duplicate").checked;
  const maxAttempts = Number(document.getElementById("input-max-attempts").value);
  const timeLimitSec = Number(document.getElementById("input-time-limit").value);
  return {
    digits,
    allow_duplicate: allowDuplicate,
    max_attempts: maxAttempts,
    time_limit_sec: timeLimitSec,
  };
}

async function startRoom(mode) {
  const hostName = nameInput.value.trim();
  if (!hostName) {
    showToast("なまえを入力してください");
    return;
  }
  try {
    const result = await createRoom({ host_name: hostName, mode, ...readSettings() });
    saveSession(result.room_code, result.player_id, result.token);
    location.href = `/room/${result.room_code}`;
  } catch (err) {
    showToast(err instanceof ApiError ? err.message : "ルームを作成できませんでした");
  }
}

formPlay.addEventListener("submit", (event) => {
  event.preventDefault();
  startRoom("race");
});

btnSolo.addEventListener("click", () => {
  startRoom("solo");
});

formJoin.addEventListener("submit", async (event) => {
  event.preventDefault();
  const code = document.getElementById("join-code").value.trim().toUpperCase();
  const name = document.getElementById("join-name").value.trim();
  if (!code || !name) {
    showToast("ルームコードとなまえを入力してください");
    return;
  }
  try {
    const result = await joinRoom(code, name);
    saveSession(result.room_code, result.player_id, result.token);
    location.href = `/room/${result.room_code}`;
  } catch (err) {
    showToast(err instanceof ApiError ? err.message : "ルームに参加できませんでした");
  }
});

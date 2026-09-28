// 対戦画面(PLAYING)と結果画面(RESULT)の描画。
// 秘密の数字はサーバーから一切送られてこないため、このファイルは
// 「サーバーが返したヒット/ブローをそのまま表示する」ことに専念する。

import { el, showToast } from "./dom.js";

const state = {
  digits: 4,
  maxAttempts: 10,
  timeLimitSec: 0,
  startedAtMs: 0,
  timerHandle: null,
  playersById: new Map(),
};

export function initGameControls(socket) {
  document.getElementById("btn-submit-guess").addEventListener("click", () => {
    submitGuess(socket);
  });

  document.getElementById("btn-rematch").addEventListener("click", () => {
    socket.rematch();
  });

  document.getElementById("btn-leave-game").addEventListener("click", () => {
    socket.leave();
    location.href = "/";
  });
}

function buildDigitInputs() {
  const container = document.getElementById("digit-inputs");
  container.innerHTML = "";
  for (let i = 0; i < state.digits; i += 1) {
    const input = el("input", {
      attrs: {
        type: "text",
        inputmode: "numeric",
        pattern: "[0-9]",
        maxlength: "1",
        "data-index": String(i),
      },
    });
    input.addEventListener("input", () => {
      input.value = input.value.replace(/[^0-9]/g, "");
      if (input.value && i < state.digits - 1) {
        container.children[i + 1].focus();
      }
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Backspace" && !input.value && i > 0) {
        container.children[i - 1].focus();
      }
    });
    container.appendChild(input);
  }
}

function readDigitInputs() {
  const container = document.getElementById("digit-inputs");
  const values = [...container.children].map((input) => input.value);
  if (values.some((v) => v === "")) return null;
  return values.map(Number);
}

function clearDigitInputs() {
  const container = document.getElementById("digit-inputs");
  for (const input of container.children) input.value = "";
  container.children[0]?.focus();
}

function submitGuess(socket) {
  const numbers = readDigitInputs();
  if (!numbers) {
    showToast(`${state.digits}桁すべて入力してください`);
    return;
  }
  socket.guess(numbers);
  clearDigitInputs();
}

function startTimer() {
  stopTimer();
  const label = document.getElementById("play-time-left");
  if (state.timeLimitSec <= 0) {
    label.textContent = "";
    return;
  }
  const tick = () => {
    const remaining = state.timeLimitSec - (Date.now() - state.startedAtMs) / 1000;
    const clamped = Math.max(0, Math.round(remaining));
    label.textContent = `残り時間: ${clamped}秒`;
    label.classList.toggle("time-warning", clamped <= 10);
  };
  tick();
  state.timerHandle = setInterval(tick, 1000);
}

function stopTimer() {
  if (state.timerHandle) clearInterval(state.timerHandle);
  state.timerHandle = null;
}

function historyCardFor(playerId) {
  let card = document.querySelector(`[data-history-player="${playerId}"]`);
  if (card) return card;

  const player = state.playersById.get(playerId);
  const name = player ? player.name : "プレイヤー";
  card = el("div", { className: "history-player", attrs: { "data-history-player": playerId } });
  card.appendChild(el("div", { className: "history-player-head", text: name }));
  const table = el("table", {}, [
    el("thead", {}, [
      el("tr", {}, [
        el("th", { text: "#" }),
        el("th", { text: "予想" }),
        el("th", { text: "ヒット" }),
        el("th", { text: "ブロー" }),
      ]),
    ]),
    el("tbody"),
  ]);
  card.appendChild(table);
  document.getElementById("history-board").appendChild(card);
  return card;
}

export function setupPlayingScreen(gameStartedPayload, players) {
  state.digits = gameStartedPayload.settings.digits;
  state.maxAttempts = gameStartedPayload.settings.max_attempts;
  state.timeLimitSec = gameStartedPayload.settings.time_limit_sec;
  state.startedAtMs = new Date(gameStartedPayload.started_at).getTime();
  state.playersById = new Map(players.map((p) => [p.id, p]));

  document.getElementById("play-digits").textContent = `${state.digits}桁`;
  document.getElementById("history-board").innerHTML = "";
  buildDigitInputs();
  startTimer();
  updateAttemptsLeft(0);
}

export function restoreFromSnapshot(snapshot, selfId, players) {
  // 再接続時に room_state だけでは分からない「対戦の中身」を
  // game_snapshot から丸ごと組み立て直す。以後は通常の
  // recordGuessResult (guess_resultイベント) で更新を追記していく。
  state.digits = snapshot.settings.digits;
  state.maxAttempts = snapshot.settings.max_attempts;
  state.timeLimitSec = snapshot.settings.time_limit_sec;
  state.startedAtMs = snapshot.started_at ? new Date(snapshot.started_at).getTime() : Date.now();
  state.playersById = new Map(players.map((p) => [p.id, p]));

  document.getElementById("play-digits").textContent = `${state.digits}桁`;
  document.getElementById("history-board").innerHTML = "";
  buildDigitInputs();
  startTimer();
  updateAttemptsLeft(0);

  for (const [playerId, records] of Object.entries(snapshot.history)) {
    for (const record of records) {
      recordGuessResult({ player_id: playerId, ...record }, selfId);
    }
  }
}

function updateAttemptsLeft(usedAttempts) {
  const label = document.getElementById("play-attempts-left");
  if (state.maxAttempts > 0) {
    label.textContent = `残り試行: ${Math.max(0, state.maxAttempts - usedAttempts)} / ${state.maxAttempts}`;
  }
}

export function recordGuessResult(payload, selfId) {
  const card = historyCardFor(payload.player_id);
  const tbody = card.querySelector("tbody");
  const numbersText = "numbers" in payload ? payload.numbers.join("") : "非公開";
  tbody.appendChild(
    el("tr", {}, [
      el("td", { text: String(payload.attempt_no) }),
      el("td", { className: "numbers", text: numbersText }),
      el("td", { text: String(payload.hit) }),
      el("td", { text: String(payload.blow) }),
    ])
  );
  if (payload.player_id === selfId) updateAttemptsLeft(payload.attempt_no);
}

export function renderResultScreen(payload, players, isHost) {
  stopTimer();
  const playersById = new Map(players.map((p) => [p.id, p]));

  document.getElementById("result-secret").textContent = payload.secret_number.join("");

  const tbody = document.querySelector("#result-ranking tbody");
  tbody.innerHTML = "";
  for (const entry of payload.rankings) {
    const name = playersById.get(entry.player_id)?.name ?? "プレイヤー";
    const row = el("tr", { className: entry.rank === 1 ? "rank-1" : "" }, [
      el("td", { text: entry.solved ? String(entry.rank) : "-" }),
      el("td", { text: name }),
      el("td", { text: entry.solved ? String(entry.attempts) : "未正解" }),
      el("td", { text: entry.time_sec != null ? `${entry.time_sec.toFixed(1)}秒` : "-" }),
    ]);
    tbody.appendChild(row);
  }

  document.getElementById("btn-rematch").classList.toggle("hidden", !isHost);
}

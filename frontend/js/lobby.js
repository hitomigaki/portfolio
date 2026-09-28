// ロビー画面(WAITING状態)の描画とホスト操作。
// room_state を受け取るたびに renderLobby() を呼べば画面が最新化されるように、
// 「今の状態を渡せば表示が決まる」関数として作っている(差分計算はしない)。

import { el, showToast } from "./dom.js";
import { renderQrCode } from "./qrcode.js";

const DIFFICULTY_LABEL = { easy: "弱", normal: "普通", hard: "強" };

// クリックハンドラから参照するための最新状態(静的なイベントリスナーは1回だけ張る)
const state = { isHost: false, isReady: false, roomCode: "" };

export function initLobbyControls(socket) {
  document.getElementById("btn-toggle-ready").addEventListener("click", () => {
    socket.setReady(!state.isReady);
  });

  document.getElementById("btn-save-settings").addEventListener("click", () => {
    const digits = Number(
      document.querySelector('input[name="settings-digits"]:checked')?.value ?? 4
    );
    socket.updateSettings({
      digits,
      allow_duplicate: document.getElementById("settings-allow-duplicate").checked,
      max_attempts: Number(document.getElementById("settings-max-attempts").value),
      time_limit_sec: Number(document.getElementById("settings-time-limit").value),
      mode: document.body.dataset.mode ?? "race",
    });
  });

  document.getElementById("btn-add-cpu").addEventListener("click", () => {
    const difficulty = document.getElementById("cpu-difficulty").value;
    socket.addCpu(difficulty);
  });

  document.getElementById("btn-start-game").addEventListener("click", () => {
    socket.startGame();
  });

  document.getElementById("btn-leave-room").addEventListener("click", () => {
    socket.leave();
    location.href = "/";
  });

  document.getElementById("btn-copy-link").addEventListener("click", async () => {
    const url = `${location.origin}/room/${state.roomCode}`;
    try {
      await navigator.clipboard.writeText(url);
      showToast("リンクをコピーしました");
    } catch {
      showToast(url);
    }
  });

  document.getElementById("btn-toggle-qr").addEventListener("click", () => {
    const container = document.getElementById("qr-container");
    container.classList.toggle("hidden");
    if (!container.classList.contains("hidden")) {
      renderQrCode(container, `${location.origin}/room/${state.roomCode}`);
    }
  });

  document.getElementById("player-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-cpu]");
    if (button) socket.removeCpu(button.dataset.removeCpu);
  });
}

function playerRow(player, hostId) {
  const badges = [];
  if (player.id === hostId) badges.push(el("span", { className: "badge host", text: "ホスト" }));
  if (player.is_cpu) {
    badges.push(
      el("span", {
        className: "badge cpu",
        text: `CPU・${DIFFICULTY_LABEL[player.cpu_difficulty] ?? player.cpu_difficulty}`,
      })
    );
  } else if (!player.connected) {
    badges.push(el("span", { className: "badge offline", text: "オフライン" }));
  }
  badges.push(
    el("span", {
      className: `badge ${player.is_ready ? "ready" : "not-ready"}`,
      text: player.is_ready ? "準備完了" : "準備中",
    })
  );

  const nameNode = el("span", { className: "name", text: player.name }); // textContentでエスケープ
  const left = el("div", {}, [nameNode]);

  const right = el("div", { className: "btn-row", attrs: { style: "width:auto" } }, badges);

  if (player.is_cpu && state.isHost) {
    right.appendChild(
      el("button", {
        className: "secondary",
        text: "削除",
        attrs: { type: "button", "data-remove-cpu": player.id, style: "width:auto" },
      })
    );
  }

  return el("li", { className: "player-row" }, [left, right]);
}

function syncSettingsFormIfIdle(settings) {
  const form = document.getElementById("host-controls");
  if (form.contains(document.activeElement)) return; // 編集中は上書きしない

  const digitsInput = document.querySelector(`input[name="settings-digits"][value="${settings.digits}"]`);
  if (digitsInput) digitsInput.checked = true;
  document.getElementById("settings-allow-duplicate").checked = settings.allow_duplicate;
  document.getElementById("settings-max-attempts").value = settings.max_attempts;
  document.getElementById("settings-time-limit").value = settings.time_limit_sec;
}

export function renderLobby(payload, selfId, roomCode) {
  state.roomCode = roomCode;
  state.isHost = payload.host_id === selfId;
  const self = payload.players.find((p) => p.id === selfId);
  state.isReady = self?.is_ready ?? false;
  document.body.dataset.mode = payload.settings.mode;

  document.getElementById("lobby-room-code").textContent = roomCode;

  const list = document.getElementById("player-list");
  list.innerHTML = "";
  for (const player of payload.players) list.appendChild(playerRow(player, payload.host_id));

  const readyButton = document.getElementById("btn-toggle-ready");
  readyButton.textContent = state.isReady ? "準備完了を取り消す" : "準備完了にする";
  readyButton.classList.toggle("secondary", state.isReady);

  document.getElementById("host-controls").classList.toggle("hidden", !state.isHost);
  syncSettingsFormIfIdle(payload.settings);

  const humans = payload.players.filter((p) => !p.is_cpu);
  const allReady = humans.length > 0 && humans.every((p) => p.is_ready);
  document.getElementById("btn-start-game").disabled = !allReady;

  const qrContainer = document.getElementById("qr-container");
  if (!qrContainer.classList.contains("hidden")) {
    renderQrCode(qrContainer, `${location.origin}/room/${roomCode}`);
  }
}

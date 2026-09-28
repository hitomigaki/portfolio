// room.html のエントリーポイント。
// 「今どの画面を出すか」はサーバーから届く room_state / game_started /
// game_snapshot / game_result のイベントだけで決める
// (クライアント側で勝手に画面を進めない)。

import { getRoomInfo, joinRoom, ApiError } from "./api.js";
import { loadSession, saveSession } from "./session.js";
import { showToast } from "./dom.js";
import { RoomSocket } from "./ws.js";
import { initLobbyControls, renderLobby } from "./lobby.js";
import {
  initGameControls,
  setupPlayingScreen,
  restoreFromSnapshot,
  recordGuessResult,
  renderResultScreen,
} from "./game.js";

const SCREEN_IDS = [
  "screen-loading",
  "screen-join-error",
  "screen-join",
  "screen-lobby",
  "screen-countdown",
  "screen-playing",
  "screen-result",
];

function showScreen(id) {
  for (const screenId of SCREEN_IDS) {
    document.getElementById(screenId).classList.toggle("hidden", screenId !== id);
  }
}

function showJoinError(message) {
  document.getElementById("join-error-message").textContent = message;
  showScreen("screen-join-error");
}

const roomCode = location.pathname.split("/").filter(Boolean).pop().toUpperCase();

function showJoinForm() {
  document.getElementById("join-room-code").textContent = roomCode;
  showScreen("screen-join");

  const form = document.getElementById("screen-join");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const name = document.getElementById("join-name-input").value.trim();
    if (!name) {
      showToast("なまえを入力してください");
      return;
    }
    try {
      const result = await joinRoom(roomCode, name);
      saveSession(roomCode, result.player_id, result.token);
      connectAndPlay(result.player_id, result.token);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "参加できませんでした");
    }
  };
}

function connectAndPlay(playerId, token) {
  const socket = new RoomSocket(roomCode, playerId, token);
  initLobbyControls(socket);
  initGameControls(socket);

  let latestPlayers = [];
  let latestHostId = null;

  socket.on("room_state", (payload) => {
    latestPlayers = payload.players;
    latestHostId = payload.host_id;

    if (payload.phase === "WAITING") {
      renderLobby(payload, playerId, roomCode);
      showScreen("screen-lobby");
    } else if (payload.phase === "READY") {
      showScreen("screen-countdown");
    }
    // PLAYING/RESULTでの(再)接続は、この直後に届く game_snapshot が
    // 画面の組み立てまで担当するので、ここでは何もしない。
  });

  socket.on("game_started", (payload) => {
    setupPlayingScreen(payload, latestPlayers);
    showScreen("screen-playing");
  });

  socket.on("game_snapshot", (payload) => {
    if (payload.phase === "PLAYING") {
      restoreFromSnapshot(payload, playerId, latestPlayers);
      showScreen("screen-playing");
    } else if (payload.phase === "RESULT") {
      renderResultScreen(
        { secret_number: payload.secret_number, rankings: payload.rankings },
        latestPlayers,
        latestHostId === playerId
      );
      showScreen("screen-result");
    }
  });

  socket.on("guess_result", (payload) => {
    recordGuessResult(payload, playerId);
  });

  socket.on("game_result", (payload) => {
    renderResultScreen(payload, latestPlayers, latestHostId === playerId);
    showScreen("screen-result");
  });

  socket.on("error", (payload) => {
    showToast(payload.message);
  });

  socket.on("_reconnecting", ({ attempt, maxAttempts }) => {
    showToast(`接続が切れました。再接続しています…(${attempt}/${maxAttempts})`);
  });

  socket.on("_reconnect_failed", () => {
    showToast("再接続できませんでした。ページを再読み込みしてください。");
  });

  socket.connect();
}

async function init() {
  const session = loadSession(roomCode);
  if (session) {
    connectAndPlay(session.playerId, session.token);
    return;
  }

  try {
    const info = await getRoomInfo(roomCode);
    if (info.phase !== "WAITING") {
      showJoinError("このルームはすでに開始しているため参加できません。");
      return;
    }
    if (info.player_count >= info.max_players) {
      showJoinError("このルームは満員です。");
      return;
    }
    showJoinForm();
  } catch (err) {
    showJoinError(err instanceof ApiError ? err.message : "ルームが見つかりません。");
  }
}

init();

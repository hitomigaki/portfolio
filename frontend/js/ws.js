// WebSocket接続のラッパー。
// 接続直後にauthメッセージを送る(トークンをURLに含めない設計)、
// 受信メッセージをtypeごとにリスナーへ配るだけの薄い層にしている。
// ゲームの状態(ロビーか対戦中かなど)はここでは一切持たない。
//
// 切断・再接続について:
// ネットワークの瞬断やタブのスリープ復帰などでWebSocketが予期せず
// 閉じることがある。leave()などで自分から切った場合(_manualClose)は
// 再接続しないが、それ以外は短い間隔を空けて自動的に再接続を試みる。
// 再接続後はサーバー側の ws_endpoint が room_state / game_snapshot を
// 送り直してくれるので、このクラス自体は「繋ぎ直す」ことだけに専念する。

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 8000;
const RECONNECT_MAX_ATTEMPTS = 5;

export class RoomSocket {
  constructor(roomCode, playerId, token) {
    this.roomCode = roomCode;
    this.playerId = playerId;
    this.token = token;
    this._listeners = new Map();
    this._ws = null;
    this._manualClose = false;
    this._reconnectAttempts = 0;
  }

  connect() {
    this._manualClose = false;
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    this._ws = new WebSocket(`${protocol}://${location.host}/ws/${this.roomCode}`);

    this._ws.addEventListener("open", () => {
      this._reconnectAttempts = 0;
      this._send({ type: "auth", payload: { player_id: this.playerId, token: this.token } });
      this._emit("_open");
    });

    this._ws.addEventListener("message", (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      this._emit(data.type, data.payload);
    });

    this._ws.addEventListener("close", (event) => {
      this._emit("_close", event);
      if (!this._manualClose) this._scheduleReconnect();
    });
  }

  _scheduleReconnect() {
    if (this._reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
      this._emit("_reconnect_failed");
      return;
    }
    this._reconnectAttempts += 1;
    const delay = Math.min(
      RECONNECT_BASE_DELAY_MS * 2 ** (this._reconnectAttempts - 1),
      RECONNECT_MAX_DELAY_MS
    );
    this._emit("_reconnecting", { attempt: this._reconnectAttempts, maxAttempts: RECONNECT_MAX_ATTEMPTS });
    setTimeout(() => this.connect(), delay);
  }

  on(type, handler) {
    if (!this._listeners.has(type)) this._listeners.set(type, new Set());
    this._listeners.get(type).add(handler);
    return () => this._listeners.get(type)?.delete(handler);
  }

  _emit(type, payload) {
    this._listeners.get(type)?.forEach((fn) => fn(payload));
  }

  _send(message) {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(message));
    }
  }

  setReady(isReady) {
    this._send({ type: "ready", payload: { is_ready: isReady } });
  }

  updateSettings(settings) {
    this._send({ type: "update_settings", payload: settings });
  }

  addCpu(difficulty) {
    this._send({ type: "add_cpu", payload: { difficulty } });
  }

  removeCpu(playerId) {
    this._send({ type: "remove_cpu", payload: { player_id: playerId } });
  }

  startGame() {
    this._send({ type: "start_game", payload: {} });
  }

  guess(numbers) {
    this._send({ type: "guess", payload: { numbers } });
  }

  leave() {
    this._send({ type: "leave", payload: {} });
    this.close(); // 自分から退出したので再接続はしない
  }

  rematch() {
    this._send({ type: "rematch", payload: {} });
  }

  close() {
    this._manualClose = true;
    this._ws?.close();
  }
}

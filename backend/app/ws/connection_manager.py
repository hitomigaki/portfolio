"""WebSocket接続の保持と送信だけを担当する。

ゲームのルールは一切知らない(room_code・player_id・WebSocketの対応関係を
管理するだけ)。ハンドラ層(handlers.py)がゲームロジックを呼んだ結果を
「誰に何を送るか」という形でここに渡す。
"""

from __future__ import annotations

from typing import Callable

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        # room_code -> { player_id -> WebSocket }
        self._rooms: dict[str, dict[str, WebSocket]] = {}

    def register(self, room_code: str, player_id: str, websocket: WebSocket) -> None:
        self._rooms.setdefault(room_code, {})[player_id] = websocket

    def unregister(self, room_code: str, player_id: str, websocket: WebSocket) -> None:
        sockets = self._rooms.get(room_code)
        if sockets is None:
            return
        # 再接続で既に新しいソケットに差し替わっている場合、古い方の後始末で
        # 新しい接続を消してしまわないようにする。
        if sockets.get(player_id) is websocket:
            del sockets[player_id]
        if not sockets:
            self._rooms.pop(room_code, None)

    async def send_to(self, room_code: str, player_id: str, message: dict) -> None:
        websocket = self._rooms.get(room_code, {}).get(player_id)
        if websocket is None:
            return
        await self._safe_send(websocket, message)

    async def broadcast(self, room_code: str, message: dict) -> None:
        for _, websocket in self._snapshot(room_code):
            await self._safe_send(websocket, message)

    async def broadcast_personalized(
        self, room_code: str, build_message: Callable[[str], dict | None]
    ) -> None:
        """受信者ごとに異なるpayloadを送る(guess_resultで本人以外にnumbersを隠すために使う)。"""

        for player_id, websocket in self._snapshot(room_code):
            message = build_message(player_id)
            if message is None:
                continue
            await self._safe_send(websocket, message)

    def connected_player_ids(self, room_code: str) -> set[str]:
        return set(self._rooms.get(room_code, {}).keys())

    def _snapshot(self, room_code: str) -> list[tuple[str, WebSocket]]:
        # 送信中に接続が切れてunregisterされても辞書のイテレーションが壊れないようコピーする
        return list(self._rooms.get(room_code, {}).items())

    @staticmethod
    async def _safe_send(websocket: WebSocket, message: dict) -> None:
        try:
            await websocket.send_json(message)
        except Exception:
            # 送信失敗は「相手が切断済み」程度の意味しか持たないため、ここで握りつぶす。
            # 実際の切断処理(leave_room呼び出し)は receive側のループが検知して行う。
            pass

"""ルームコードの発行・登録・検索・空室の自動削除を担当する。

WebSocket接続やHTTPは扱わず、メモリ上の辞書だけを操作する。
将来DB化する場合は、このクラスのメソッドシグネチャを保ったまま
中身だけ差し替えれば済むようにしている(呼び出し側のws/api層は
RoomManagerの中身がメモリかDBかを意識しない)。
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.errors import GameError
from app.core.room import GamePhase, GameSettings, Player, Room

# ルームコードで使う文字種。0/O/1/I など見間違えやすい文字を除外する。
ROOM_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
ROOM_CODE_LENGTH = 6
_MAX_CODE_GENERATION_ATTEMPTS = 20

# 参加時に発行するセッショントークンの長さ(バイト数、URLセーフBase64で出力)
TOKEN_BYTES = 24

# 人間プレイヤーが誰も接続していない状態がこの秒数続いたらルームを削除する
DEFAULT_EMPTY_ROOM_TIMEOUT_SEC = 600


def _new_player_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class JoinResult:
    room: Room
    player: Player
    token: str


class RoomManager:
    def __init__(self, empty_room_timeout_sec: int = DEFAULT_EMPTY_ROOM_TIMEOUT_SEC) -> None:
        self._rooms: dict[str, Room] = {}
        # (room_code, player_id) -> token。認証情報なのでログに出せる場所には置かない。
        self._tokens: dict[tuple[str, str], str] = {}
        self.empty_room_timeout_sec = empty_room_timeout_sec

    # ---- 参照 -----------------------------------------------------

    def get_room(self, code: str) -> Room | None:
        return self._rooms.get(code)

    def room_count(self) -> int:
        return len(self._rooms)

    def all_rooms(self) -> list[Room]:
        """バックグラウンドの定期処理(ws/handlers.py)向けに全ルームを返す。"""

        return list(self._rooms.values())

    # ---- 作成・参加 --------------------------------------------------

    def create_room(self, host_name: str, settings: GameSettings, now: datetime) -> JoinResult:
        code = self._generate_unique_code()
        host = Player(id=_new_player_id(), name=host_name)
        if settings.mode == "solo":
            # ソロモードはホスト1人で即開始できるよう、準備完了状態にしておく。
            host.is_ready = True
        room = Room(
            code=code,
            host_id=host.id,
            settings=settings,
            created_at=now,
            last_activity_at=now,
        )
        room.players[host.id] = host
        self._rooms[code] = room
        token = self._issue_token(code, host.id)
        return JoinResult(room=room, player=host, token=token)

    def join_room(self, code: str, name: str, now: datetime) -> JoinResult:
        room = self._require_room(code)
        if room.phase != GamePhase.WAITING:
            raise GameError("ROOM_NOT_JOINABLE", "このルームは現在参加を受け付けていません")
        from app.core.game_state import add_player  # 遅延import(循環import回避)

        player = Player(id=_new_player_id(), name=name)
        add_player(room, player)  # 満員チェックなどはgame_state側に一本化
        room.last_activity_at = now
        token = self._issue_token(code, player.id)
        return JoinResult(room=room, player=player, token=token)

    def remove_room(self, code: str) -> None:
        self._rooms.pop(code, None)
        for key in [k for k in self._tokens if k[0] == code]:
            del self._tokens[key]

    def touch(self, code: str, now: datetime) -> None:
        room = self._rooms.get(code)
        if room is not None:
            room.last_activity_at = now

    # ---- 認証 -------------------------------------------------------

    def _issue_token(self, code: str, player_id: str) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        self._tokens[(code, player_id)] = token
        return token

    def verify_token(self, code: str, player_id: str, token: str) -> bool:
        expected = self._tokens.get((code, player_id))
        # secrets.compare_digestでタイミング攻撃を避ける
        return expected is not None and secrets.compare_digest(expected, token)

    # ---- 空室の自動削除 ------------------------------------------------

    def sweep_expired_rooms(self, now: datetime) -> list[str]:
        """人間の接続が誰もおらず、猶予時間を過ぎたルームを削除して返す。"""

        expired = [
            code
            for code, room in self._rooms.items()
            if room.is_empty()
            and (now - room.last_activity_at) >= timedelta(seconds=self.empty_room_timeout_sec)
        ]
        for code in expired:
            self.remove_room(code)
        return expired

    # ---- 内部ヘルパー --------------------------------------------------

    def _require_room(self, code: str) -> Room:
        room = self._rooms.get(code)
        if room is None:
            raise GameError("ROOM_NOT_FOUND", "ルームが見つかりません")
        return room

    def _generate_unique_code(self) -> str:
        for _ in range(_MAX_CODE_GENERATION_ATTEMPTS):
            code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
            if code not in self._rooms:
                return code
        raise GameError("ROOM_CODE_EXHAUSTED", "ルームコードの発行に失敗しました。再度お試しください")

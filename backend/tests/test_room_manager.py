"""core/room_manager.py の単体テスト。

ルームコードの発行規則、参加処理、トークン検証、空室の自動削除を確認する。
"""

from datetime import datetime, timedelta

import pytest

from app.core.errors import GameError
from app.core.room import GamePhase, GameSettings
from app.core.room_manager import (
    DEFAULT_EMPTY_ROOM_TIMEOUT_SEC,
    ROOM_CODE_ALPHABET,
    ROOM_CODE_LENGTH,
    RoomManager,
)

NOW = datetime(2026, 1, 1, 12, 0, 0)


def make_manager() -> RoomManager:
    return RoomManager(empty_room_timeout_sec=60)


class TestCreateRoom:
    def test_code_has_correct_length_and_charset(self) -> None:
        manager = make_manager()
        result = manager.create_room("ホスト", GameSettings(), NOW)
        assert len(result.room.code) == ROOM_CODE_LENGTH
        assert all(c in ROOM_CODE_ALPHABET for c in result.room.code)

    def test_confusing_characters_are_excluded(self) -> None:
        for c in "0O1I":
            assert c not in ROOM_CODE_ALPHABET

    def test_created_room_is_in_waiting_phase(self) -> None:
        manager = make_manager()
        result = manager.create_room("ホスト", GameSettings(), NOW)
        assert result.room.phase == GamePhase.WAITING
        assert result.room.host_id == result.player.id

    def test_solo_mode_host_is_auto_ready(self) -> None:
        manager = make_manager()
        result = manager.create_room("ソロ", GameSettings(mode="solo"), NOW)
        assert result.player.is_ready is True

    def test_race_mode_host_is_not_auto_ready(self) -> None:
        manager = make_manager()
        result = manager.create_room("ホスト", GameSettings(mode="race"), NOW)
        assert result.player.is_ready is False

    def test_codes_are_unique_across_many_rooms(self) -> None:
        manager = make_manager()
        codes = {manager.create_room("H", GameSettings(), NOW).room.code for _ in range(50)}
        assert len(codes) == 50


class TestJoinRoom:
    def test_join_adds_player_with_distinct_token(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        joined = manager.join_room(created.room.code, "ゲスト", NOW)
        assert joined.player.id in joined.room.players
        assert joined.token != created.token

    def test_join_nonexistent_room_raises(self) -> None:
        manager = make_manager()
        with pytest.raises(GameError) as exc_info:
            manager.join_room("ZZZZZZ", "ゲスト", NOW)
        assert exc_info.value.code == "ROOM_NOT_FOUND"

    def test_join_after_game_started_raises(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        created.room.phase = GamePhase.PLAYING
        with pytest.raises(GameError) as exc_info:
            manager.join_room(created.room.code, "遅刻者", NOW)
        assert exc_info.value.code == "ROOM_NOT_JOINABLE"


class TestVerifyToken:
    def test_correct_token_passes(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        assert manager.verify_token(created.room.code, created.player.id, created.token) is True

    def test_wrong_token_fails(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        assert manager.verify_token(created.room.code, created.player.id, "invalid-token") is False

    def test_token_for_wrong_player_fails(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        joined = manager.join_room(created.room.code, "ゲスト", NOW)
        # ホストのトークンをゲストIDで検証しようとしても通らない
        assert manager.verify_token(created.room.code, joined.player.id, created.token) is False

    def test_token_invalid_after_room_removed(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        manager.remove_room(created.room.code)
        assert manager.verify_token(created.room.code, created.player.id, created.token) is False


class TestSweepExpiredRooms:
    def test_empty_room_removed_after_timeout(self) -> None:
        manager = make_manager()  # timeout=60秒
        created = manager.create_room("ホスト", GameSettings(), NOW)
        created.room.players[created.player.id].connected = False

        removed = manager.sweep_expired_rooms(NOW + timedelta(seconds=61))
        assert removed == [created.room.code]
        assert manager.get_room(created.room.code) is None

    def test_room_kept_before_timeout(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        created.room.players[created.player.id].connected = False

        removed = manager.sweep_expired_rooms(NOW + timedelta(seconds=30))
        assert removed == []
        assert manager.get_room(created.room.code) is not None

    def test_room_with_connected_human_is_never_swept(self) -> None:
        manager = make_manager()
        created = manager.create_room("ホスト", GameSettings(), NOW)
        # WebSocket接続済み(connected=True)を明示的に再現する
        created.room.players[created.player.id].connected = True

        removed = manager.sweep_expired_rooms(NOW + timedelta(seconds=999))
        assert removed == []

    def test_default_timeout_is_ten_minutes(self) -> None:
        assert DEFAULT_EMPTY_ROOM_TIMEOUT_SEC == 600

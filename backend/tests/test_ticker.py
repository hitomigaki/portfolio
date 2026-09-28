"""ws/handlers.py の tick_once (制限時間切れ検知・空室掃除) のテスト。

実際に asyncio.sleep で待つ代わりに、started_at / last_activity_at を
過去の時刻に設定しておくことで「時間が経過した状態」を再現する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core import game_state as gs
from app.core.room import GamePhase, GameSettings
from app.core.room_manager import RoomManager
from app.ws.connection_manager import ConnectionManager
from app.ws.handlers import tick_once


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_tick_once_finishes_room_past_time_limit() -> None:
    manager = RoomManager()
    connections = ConnectionManager()
    now = _now()
    settings = GameSettings(digits=4, allow_duplicate=False, max_attempts=10, time_limit_sec=1)
    created = manager.create_room("Alice", settings, now)
    room = created.room

    gs.set_ready(room, created.player.id, True)
    gs.start_game(room, created.player.id, now)
    gs.begin_play(room, now + timedelta(seconds=gs.READY_COUNTDOWN_SEC))
    room.started_at = now - timedelta(seconds=1000)  # 制限時間(1秒)をとっくに超過させる

    await tick_once(manager, connections)

    assert room.phase == GamePhase.RESULT


@pytest.mark.asyncio
async def test_tick_once_keeps_room_within_time_limit() -> None:
    manager = RoomManager()
    connections = ConnectionManager()
    now = _now()
    settings = GameSettings(digits=4, allow_duplicate=False, max_attempts=10, time_limit_sec=300)
    created = manager.create_room("Alice", settings, now)
    room = created.room

    gs.set_ready(room, created.player.id, True)
    gs.start_game(room, created.player.id, now)
    gs.begin_play(room, now + timedelta(seconds=gs.READY_COUNTDOWN_SEC))

    await tick_once(manager, connections)

    assert room.phase == GamePhase.PLAYING


@pytest.mark.asyncio
async def test_tick_once_sweeps_empty_room() -> None:
    manager = RoomManager(empty_room_timeout_sec=1)
    connections = ConnectionManager()
    now = _now()
    created = manager.create_room("Alice", GameSettings(), now)
    created.room.players[created.player.id].connected = False
    created.room.last_activity_at = now - timedelta(seconds=1000)

    await tick_once(manager, connections)

    assert manager.get_room(created.room.code) is None


@pytest.mark.asyncio
async def test_tick_once_keeps_room_with_connected_player() -> None:
    manager = RoomManager(empty_room_timeout_sec=1)
    connections = ConnectionManager()
    now = _now()
    created = manager.create_room("Alice", GameSettings(), now)
    created.room.players[created.player.id].connected = True
    created.room.last_activity_at = now - timedelta(seconds=1000)

    await tick_once(manager, connections)

    assert manager.get_room(created.room.code) is not None

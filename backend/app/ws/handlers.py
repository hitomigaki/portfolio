"""WebSocketメッセージの受付・振り分け。

このファイルは「メッセージを受け取り、core層の関数を呼び、結果を
connection_managerで配信する」という薄い橋渡し役に徹する。
ゲームのルール判断(フェーズチェックなど)は一切ここに書かず、
core.game_state / core.room_manager に問い合わせる。

認証トークンの扱いについて:
WebSocketの接続URL自体はリバースプロキシやブラウザ履歴・アクセスログに
残ることがあるため、トークンをURLのクエリパラメータには含めない。
代わりに、接続直後に最初のメッセージとして { "type": "auth", ... } を
送らせ、そこでのみトークンを受け取る。WebSocketのメッセージ本文は
通常のHTTPアクセスログの対象にならないため、ログ残留のリスクを減らせる。
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app import config
from app.core import cpu as cpu_logic
from app.core import game_state as gs
from app.core.errors import GameError
from app.core.judge import GameRules
from app.core.room import GamePhase, GameSettings, Player
from app.core.room_manager import RoomManager
from app.schemas.messages import (
    AddCpuMessage,
    AuthMessage,
    GuessMessage,
    LeaveMessage,
    ReadyMessage,
    RematchMessage,
    RemoveCpuMessage,
    StartGameMessage,
    UpdateSettingsMessage,
    parse_client_message,
)
from app.ws.connection_manager import ConnectionManager
from app.ws.serializers import (
    serialize_error,
    serialize_game_result,
    serialize_game_snapshot,
    serialize_game_started,
    serialize_guess_result_for_guesser,
    serialize_guess_result_for_others,
    serialize_room_state,
)

_DIFFICULTY_LABEL = {"easy": "弱", "normal": "普通", "hard": "強"}

# 発行したタスクの参照を保持しておかないとGC対象になり得るため、ここに集めておく
_background_tasks: set[asyncio.Task] = set()

# CPUが1手打つごとに置く「考えている」間隔(秒)。0にすると全CPUの手が
# 同一イベントループティックで処理され、対戦としての臨場感がなくなるため、
# 実際の思考時間の有無に関わらず一定のばらつきを入れている。
CPU_GUESS_DELAY_RANGE_SEC = (0.8, 1.8)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


async def ws_endpoint(
    websocket: WebSocket,
    room_code: str,
    room_manager: RoomManager,
    connections: ConnectionManager,
) -> None:
    room_code = room_code.upper()
    await websocket.accept()

    player_id = await _authenticate(websocket, room_code, room_manager)
    if player_id is None:
        return

    room = room_manager.get_room(room_code)
    player = room.players.get(player_id) if room is not None else None
    if room is None or player is None:
        await _safe_close(websocket, 4404, "ルームまたはプレイヤーが見つかりません")
        return

    player.connected = True
    connections.register(room_code, player_id, websocket)
    room_manager.touch(room_code, _now())
    await connections.broadcast(room_code, serialize_room_state(room))

    if room.phase in (GamePhase.PLAYING, GamePhase.RESULT):
        # 対戦中/結果表示中に(再)接続してきた場合、room_stateだけでは
        # 進行中の対戦内容(開始時刻・各自の回答履歴・結果)が分からないため、
        # 本人にだけ追加でスナップショットを送って画面を復元させる。
        await connections.send_to(room_code, player_id, serialize_game_snapshot(room, player_id))

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_message(raw, room_code, player_id, room_manager, connections)
    except WebSocketDisconnect:
        pass
    finally:
        connections.unregister(room_code, player_id, websocket)
        room = room_manager.get_room(room_code)
        if room is not None:
            gs.leave_room(room, player_id, _now())
            room_manager.touch(room_code, _now())
            if room.players:
                await connections.broadcast(room_code, serialize_room_state(room))


async def _authenticate(websocket: WebSocket, room_code: str, room_manager: RoomManager) -> str | None:
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=config.AUTH_TIMEOUT_SEC)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await _safe_close(websocket, 4401, "認証がタイムアウトしました")
        return None

    try:
        message = parse_client_message(json.loads(raw))
    except (ValueError, ValidationError):
        await _safe_close(websocket, 4400, "不正なメッセージです")
        return None

    if not isinstance(message, AuthMessage):
        await _safe_close(websocket, 4401, "最初にauthメッセージを送ってください")
        return None

    if not room_manager.verify_token(room_code, message.payload.player_id, message.payload.token):
        await _safe_close(websocket, 4401, "認証に失敗しました")
        return None

    return message.payload.player_id


async def _handle_message(
    raw: str,
    room_code: str,
    player_id: str,
    room_manager: RoomManager,
    connections: ConnectionManager,
) -> None:
    room = room_manager.get_room(room_code)
    if room is None:
        return

    try:
        message = parse_client_message(json.loads(raw))
    except (ValueError, ValidationError):
        await connections.send_to(
            room_code, player_id, serialize_error("INVALID_MESSAGE", "メッセージを解釈できませんでした")
        )
        return

    now = _now()
    try:
        await _dispatch(message, room, room_code, player_id, now, room_manager, connections)
        room_manager.touch(room_code, now)
    except GameError as e:
        await connections.send_to(room_code, player_id, serialize_error(e.code, e.message))


async def _dispatch(message, room, room_code, player_id, now, room_manager, connections) -> None:
    if isinstance(message, ReadyMessage):
        gs.set_ready(room, player_id, message.payload.is_ready)
        await connections.broadcast(room_code, serialize_room_state(room))

    elif isinstance(message, UpdateSettingsMessage):
        settings = GameSettings(**message.payload.model_dump())
        gs.update_settings(room, player_id, settings)
        await connections.broadcast(room_code, serialize_room_state(room))

    elif isinstance(message, AddCpuMessage):
        difficulty = message.payload.difficulty
        cpu_count = sum(1 for p in room.players.values() if p.is_cpu) + 1
        cpu = Player(
            id=f"cpu-{uuid.uuid4().hex[:8]}",
            name=f"CPU{cpu_count}({_DIFFICULTY_LABEL[difficulty]})",
            cpu_difficulty=difficulty,
        )
        gs.add_cpu(room, player_id, cpu)
        await connections.broadcast(room_code, serialize_room_state(room))

    elif isinstance(message, RemoveCpuMessage):
        gs.remove_cpu(room, player_id, message.payload.player_id)
        await connections.broadcast(room_code, serialize_room_state(room))

    elif isinstance(message, StartGameMessage):
        gs.start_game(room, player_id, now)
        await connections.broadcast(room_code, serialize_room_state(room))
        _spawn(_run_countdown(room_code, room_manager, connections))

    elif isinstance(message, GuessMessage):
        record = gs.record_guess(room, player_id, message.payload.numbers, now)
        await _broadcast_guess_result(room_code, connections, player_id, record)
        await _finish_round_if_over(room, room_code, now, connections)

    elif isinstance(message, RematchMessage):
        gs.rematch(room, player_id, now)
        await connections.broadcast(room_code, serialize_room_state(room))

    elif isinstance(message, LeaveMessage):
        gs.leave_room(room, player_id, now)
        if room.players:
            await connections.broadcast(room_code, serialize_room_state(room))

    else:
        raise GameError("UNSUPPORTED_MESSAGE", "このタイミングでは処理できないメッセージです")


async def _run_countdown(room_code: str, room_manager: RoomManager, connections: ConnectionManager) -> None:
    await asyncio.sleep(gs.READY_COUNTDOWN_SEC)
    room = room_manager.get_room(room_code)
    if room is None or room.phase != GamePhase.READY:
        return
    gs.begin_play(room, _now())
    await connections.broadcast(room_code, serialize_game_started(room))

    for player in room.players.values():
        if player.is_cpu:
            _spawn(_run_cpu_turn_loop(room_code, player.id, room_manager, connections))


async def _broadcast_guess_result(room_code: str, connections: ConnectionManager, guesser_id: str, record) -> None:
    await connections.broadcast_personalized(
        room_code,
        lambda pid: (
            serialize_guess_result_for_guesser(guesser_id, record)
            if pid == guesser_id
            else serialize_guess_result_for_others(guesser_id, record)
        ),
    )


async def _finish_round_if_over(room, room_code: str, now: datetime, connections: ConnectionManager) -> None:
    try:
        if gs.is_round_over(room, now):
            rankings = gs.finish_game(room, now)
            await connections.broadcast(room_code, serialize_game_result(room, rankings))
    except GameError:
        # 別プレイヤー(人間 or 他のCPU)の手と競合し、既に結果が確定していた場合。
        # ゲーム自体は正しく終了しているので、ここでは何もしない。
        pass


async def _run_cpu_turn_loop(
    room_code: str, player_id: str, room_manager: RoomManager, connections: ConnectionManager
) -> None:
    """CPUプレイヤーが自分の番を自動で打ち続けるループ。

    人間の操作と同じ record_guess / ブロードキャスト経路を通すことで、
    「CPUは特別扱いされていない」ことをコードの上でも保証している。
    """

    while True:
        await asyncio.sleep(random.uniform(*CPU_GUESS_DELAY_RANGE_SEC))

        room = room_manager.get_room(room_code)
        if room is None or room.phase != GamePhase.PLAYING:
            return
        player = room.players.get(player_id)
        if player is None or player.finished:
            return

        rules = GameRules(digits=room.settings.digits, allow_duplicate=room.settings.allow_duplicate)
        guess = cpu_logic.next_guess(player.cpu_difficulty, rules, player.guesses)

        now = _now()
        try:
            record = gs.record_guess(room, player_id, guess, now)
        except GameError:
            # フェーズが直前に変わった等、理論上稀なレース。次のループで抜ける。
            continue

        await _broadcast_guess_result(room_code, connections, player_id, record)
        await _finish_round_if_over(room, room_code, now, connections)


async def tick_once(room_manager: RoomManager, connections: ConnectionManager) -> None:
    """全ルームを1回だけ見回す(制限時間切れの検知・空室掃除)。

    ループ本体から切り出しておくことで、テストからは実際にsleepせず
    この関数だけを直接呼んで検証できるようにしている。
    """

    now = _now()
    for room in room_manager.all_rooms():
        if room.phase != GamePhase.PLAYING:
            continue
        try:
            if gs.is_round_over(room, now):
                rankings = gs.finish_game(room, now)
                await connections.broadcast(room.code, serialize_game_result(room, rankings))
        except GameError:
            continue
    room_manager.sweep_expired_rooms(now)


async def run_room_ticker(room_manager: RoomManager, connections: ConnectionManager) -> None:
    while True:
        await asyncio.sleep(config.TICK_INTERVAL_SEC)
        await tick_once(room_manager, connections)

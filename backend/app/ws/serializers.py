"""core層のオブジェクト(Room, Playerなど)をWebSocket送信用JSONに変換する。

秘密の数字(room.secret_number)は game_result 以外では絶対に含めない、
他人の予想の中身(numbers)は guess_result で本人以外に含めない、
というセキュリティ上の制約をこのファイルに閉じ込める
(呼び出し側でうっかり漏らすことがないようにする)。
"""

from __future__ import annotations

from app.core.room import GamePhase, GuessRecord, Player, RankingEntry, Room


def _serialize_settings(room: Room) -> dict:
    return {
        "digits": room.settings.digits,
        "allow_duplicate": room.settings.allow_duplicate,
        "max_attempts": room.settings.max_attempts,
        "time_limit_sec": room.settings.time_limit_sec,
        "mode": room.settings.mode,
    }


def _serialize_player(player: Player) -> dict:
    return {
        "id": player.id,
        "name": player.name,
        "is_cpu": player.is_cpu,
        "cpu_difficulty": player.cpu_difficulty,
        "is_ready": player.is_ready,
        "connected": player.connected,
    }


def serialize_room_state(room: Room) -> dict:
    return {
        "type": "room_state",
        "payload": {
            "phase": room.phase.value,
            "host_id": room.host_id,
            "settings": _serialize_settings(room),
            "players": [_serialize_player(p) for p in room.players.values()],
        },
    }


def serialize_game_started(room: Room) -> dict:
    assert room.started_at is not None
    return {
        "type": "game_started",
        "payload": {
            "phase": room.phase.value,
            "started_at": room.started_at.isoformat(),
            "settings": _serialize_settings(room),
        },
    }


def serialize_guess_result_for_guesser(player_id: str, record: GuessRecord) -> dict:
    return {
        "type": "guess_result",
        "payload": {
            "player_id": player_id,
            "attempt_no": record.attempt_no,
            "numbers": record.numbers,
            "hit": record.hit,
            "blow": record.blow,
        },
    }


def serialize_guess_result_for_others(player_id: str, record: GuessRecord) -> dict:
    return {
        "type": "guess_result",
        "payload": {
            "player_id": player_id,
            "attempt_no": record.attempt_no,
            "hit": record.hit,
            "blow": record.blow,
        },
    }


def _serialize_rankings(rankings: list[RankingEntry]) -> list[dict]:
    return [
        {
            "player_id": r.player_id,
            "rank": r.rank,
            "attempts": r.attempts,
            "solved": r.solved,
            "time_sec": r.time_sec,
        }
        for r in rankings
    ]


def serialize_game_result(room: Room, rankings: list[RankingEntry]) -> dict:
    return {
        "type": "game_result",
        "payload": {
            "secret_number": room.secret_number,
            "rankings": _serialize_rankings(rankings),
        },
    }


def serialize_game_snapshot(room: Room, viewer_id: str) -> dict:
    """再接続してきたプレイヤーへ、進行中/終了済みの対戦状況を1通で送る。

    room_state (ロビー情報) だけでは PLAYING/RESULT の詳細
    (開始時刻・各プレイヤーの回答履歴・結果) が復元できないため、
    認証成功直後にこのメッセージを追加で送ることで、リロードしても
    対戦画面をその場で組み立て直せるようにする。
    """

    history: dict[str, list[dict]] = {}
    for pid, player in room.players.items():
        history[pid] = [
            {
                "attempt_no": g.attempt_no,
                "hit": g.hit,
                "blow": g.blow,
                **({"numbers": g.numbers} if pid == viewer_id else {}),
            }
            for g in player.guesses
        ]

    payload: dict = {
        "phase": room.phase.value,
        "settings": _serialize_settings(room),
        "history": history,
    }
    if room.phase == GamePhase.PLAYING and room.started_at is not None:
        payload["started_at"] = room.started_at.isoformat()
    if room.phase == GamePhase.RESULT:
        payload["secret_number"] = room.secret_number
        payload["rankings"] = _serialize_rankings(room.last_rankings or [])

    return {"type": "game_snapshot", "payload": payload}


def serialize_error(code: str, message: str) -> dict:
    return {"type": "error", "payload": {"code": code, "message": message}}

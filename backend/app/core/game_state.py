"""ルームの状態遷移ロジック。

WAITING → READY → PLAYING → RESULT (→ WAITING) という進行を、
このモジュールの関数だけが変更してよいというルールにする。
ws/handlers.py はここに定義された関数を呼ぶだけで、
「今この操作をしてよいか」の判定(フェーズチェック・権限チェック)は
すべてこちら側に集約する。

現在時刻は引数 now で受け取る(このモジュール自身は時計を読まない)。
これにより、タイマー処理は呼び出し側(ws/ や main.py の asyncio)に置きつつ、
このモジュール自体は「時刻を渡せば結果が決まる」純粋関数のまま保て、
pytest で datetime を固定してテストできる。
"""

from __future__ import annotations

from datetime import datetime

from app.core.errors import GameError
from app.core.judge import (
    GameRules,
    calculate_hits_and_blows,
    generate_secret_number,
    validate_guess,
)
from app.core.room import (
    MAX_PLAYERS,
    GamePhase,
    GameSettings,
    GuessRecord,
    Player,
    RankingEntry,
    Room,
)

# READY突入からPLAYING突入までのカウントダウン秒数
READY_COUNTDOWN_SEC = 3


def _rules(settings: GameSettings) -> GameRules:
    return GameRules(digits=settings.digits, allow_duplicate=settings.allow_duplicate)


def _require_phase(room: Room, *allowed: GamePhase) -> None:
    if room.phase not in allowed:
        raise GameError(
            "INVALID_PHASE",
            f"この操作は{[p.value for p in allowed]}状態でのみ行えます(現在: {room.phase.value})",
        )


def _require_host(room: Room, requester_id: str) -> None:
    if requester_id != room.host_id:
        raise GameError("NOT_HOST", "ホストのみが行える操作です")


def _get_player(room: Room, player_id: str) -> Player:
    player = room.players.get(player_id)
    if player is None:
        raise GameError("PLAYER_NOT_FOUND", "プレイヤーが見つかりません")
    return player


# ---- WAITING中の操作 -------------------------------------------------


def add_player(room: Room, player: Player) -> None:
    _require_phase(room, GamePhase.WAITING)
    if len(room.players) >= MAX_PLAYERS:
        raise GameError("ROOM_FULL", "このルームは満員です")
    room.players[player.id] = player


def add_cpu(room: Room, requester_id: str, cpu: Player) -> None:
    _require_phase(room, GamePhase.WAITING)
    _require_host(room, requester_id)
    if len(room.players) >= MAX_PLAYERS:
        raise GameError("ROOM_FULL", "このルームは満員です")
    cpu.is_cpu = True
    cpu.is_ready = True  # CPUは常に準備完了扱い
    room.players[cpu.id] = cpu


def remove_cpu(room: Room, requester_id: str, cpu_id: str) -> None:
    _require_phase(room, GamePhase.WAITING)
    _require_host(room, requester_id)
    cpu = _get_player(room, cpu_id)
    if not cpu.is_cpu:
        raise GameError("NOT_A_CPU", "CPU以外は削除できません")
    del room.players[cpu_id]


def set_ready(room: Room, player_id: str, is_ready: bool) -> None:
    _require_phase(room, GamePhase.WAITING)
    player = _get_player(room, player_id)
    if player.is_cpu:
        return  # CPUの準備状態は常にTrueなので無視する
    player.is_ready = is_ready


def update_settings(room: Room, requester_id: str, settings: GameSettings) -> None:
    _require_phase(room, GamePhase.WAITING)
    _require_host(room, requester_id)
    _rules(settings)  # 桁数などのバリデーション(不正ならGameErrorが飛ぶ)
    room.settings = settings


def is_all_ready(room: Room) -> bool:
    humans = room.human_players()
    return len(humans) > 0 and all(p.is_ready for p in humans)


# ---- フェーズ遷移 ------------------------------------------------------


def start_game(room: Room, requester_id: str, now: datetime) -> None:
    """WAITING → READY。ホストが開始ボタンを押したときに呼ぶ。"""

    _require_phase(room, GamePhase.WAITING)
    _require_host(room, requester_id)
    if not is_all_ready(room):
        raise GameError("NOT_ALL_READY", "全員が準備完了していません")
    room.phase = GamePhase.READY
    room.ready_at = now


def begin_play(room: Room, now: datetime) -> None:
    """READY → PLAYING。カウントダウン終了時に呼ぶ(秘密の数字を生成)。

    「カウントダウンが実際に経過したか」は呼び出し側(ws/handlers.pyの
    _run_countdown)が asyncio.sleep で保証する。asyncio.sleep はイベント
    ループの単調増加クロックを基準にするため実時間の経過を確実に待てるが、
    ここで壁時計(datetime.now)同士を比較して二重に検証すると、コンテナの
    起動直後などOS側の時刻補正で壁時計が巻き戻るケースで
    「now < ready_at + COUNTDOWN」が誤って真になり、実際には十分待った
    はずのカウントダウンが失敗してしまう。そのため壁時計による再検証は
    行わず、フェーズが正しいことだけを確認する。
    """

    _require_phase(room, GamePhase.READY)

    rules = _rules(room.settings)
    room.secret_number = generate_secret_number(rules)
    for player in room.players.values():
        player.reset_for_new_round()
    room.started_at = now
    room.phase = GamePhase.PLAYING


def record_guess(room: Room, player_id: str, numbers: list[int], now: datetime) -> GuessRecord:
    """プレイヤーの予想を判定し、履歴に積む。"""

    _require_phase(room, GamePhase.PLAYING)
    player = _get_player(room, player_id)
    if player.finished:
        raise GameError("ALREADY_FINISHED", "すでに終了しています")

    rules = _rules(room.settings)
    validate_guess(numbers, rules)  # 不正ならGuessValidationError(GameErrorのサブクラス)

    assert room.secret_number is not None
    hit, blow = calculate_hits_and_blows(room.secret_number, numbers)

    player.attempts += 1
    record = GuessRecord(attempt_no=player.attempts, numbers=list(numbers), hit=hit, blow=blow)
    player.guesses.append(record)

    solved = hit == room.settings.digits
    exhausted = player.attempts >= room.settings.max_attempts
    if solved or exhausted:
        player.finished = True
        player.solved = solved
        assert room.started_at is not None
        player.finished_at_sec = (now - room.started_at).total_seconds()

    return record


def time_remaining_sec(room: Room, now: datetime) -> float | None:
    """制限時間までの残り秒数。時間無制限(0)ならNone。PLAYING以外でもNone。"""

    if room.phase != GamePhase.PLAYING or room.settings.time_limit_sec <= 0:
        return None
    assert room.started_at is not None
    elapsed = (now - room.started_at).total_seconds()
    return max(0.0, room.settings.time_limit_sec - elapsed)


def is_round_over(room: Room, now: datetime) -> bool:
    """全員終了 or 制限時間到達で True。ws側はこれを見てfinish_gameを呼ぶ。"""

    _require_phase(room, GamePhase.PLAYING)
    if all(p.finished for p in room.players.values()):
        return True
    remaining = time_remaining_sec(room, now)
    return remaining is not None and remaining <= 0


def finish_game(room: Room, now: datetime) -> list[RankingEntry]:
    """PLAYING → RESULT。未終了者は不正解扱いで打ち切り、順位を確定する。"""

    _require_phase(room, GamePhase.PLAYING)
    assert room.started_at is not None
    elapsed = (now - room.started_at).total_seconds()

    for player in room.players.values():
        if not player.finished:
            player.finished = True
            player.solved = False
            player.finished_at_sec = elapsed

    rankings = _build_rankings(room)
    room.last_rankings = rankings
    room.phase = GamePhase.RESULT
    return rankings


def _build_rankings(room: Room) -> list[RankingEntry]:
    """正解者は attempts 昇順→time_sec 昇順、未正解者は最後(元の順序を維持)。"""

    solved = [p for p in room.players.values() if p.solved]
    unsolved = [p for p in room.players.values() if not p.solved]
    solved.sort(key=lambda p: (p.attempts, p.finished_at_sec))

    ordered = solved + unsolved
    return [
        RankingEntry(
            player_id=p.id,
            rank=i + 1,
            attempts=p.attempts,
            solved=p.solved,
            time_sec=p.finished_at_sec,
        )
        for i, p in enumerate(ordered)
    ]


def rematch(room: Room, requester_id: str, now: datetime) -> None:
    """RESULT → WAITING。設定と参加者は維持し、対戦成績だけリセットする。"""

    _require_phase(room, GamePhase.RESULT)
    _require_host(room, requester_id)
    room.secret_number = None
    room.ready_at = None
    room.started_at = None
    room.last_rankings = None
    for player in room.players.values():
        player.reset_for_new_round()
        if not player.is_cpu:
            player.is_ready = False
    room.phase = GamePhase.WAITING


# ---- 退出・切断 --------------------------------------------------------


def leave_room(room: Room, player_id: str, now: datetime) -> None:
    """プレイヤーの退出/切断を処理する。

    WAITING中は完全に離脱(席を空ける)。
    ゲーム中〜結果表示中は connected=False にするだけで席は残す
    (再接続すれば履歴・順位を保ったまま復帰できるようにするため)。
    ホストが離脱した場合、WAITING中であれば次の人間プレイヤーへ
    ホスト権限を自動的に引き継ぐ。
    """

    player = room.players.get(player_id)
    if player is None:
        return

    if room.phase == GamePhase.WAITING:
        del room.players[player_id]
        if room.host_id == player_id:
            remaining_humans = room.human_players()
            if remaining_humans:
                room.host_id = remaining_humans[0].id
    else:
        player.connected = False

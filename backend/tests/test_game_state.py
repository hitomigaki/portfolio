"""core/game_state.py の単体テスト。

時刻は datetime を固定値として渡すことで、カウントダウンや
制限時間切れの境界を決定的にテストできるようにしている。
"""

from datetime import datetime, timedelta

import pytest

from app.core import game_state as gs
from app.core.errors import GameError
from app.core.judge import GuessValidationError
from app.core.room import GamePhase, GameSettings, Player, Room

NOW = datetime(2026, 1, 1, 12, 0, 0)


def make_room(**settings_kwargs) -> Room:
    settings = GameSettings(
        digits=4, allow_duplicate=False, max_attempts=10, time_limit_sec=300, mode="race"
    )
    for key, value in settings_kwargs.items():
        setattr(settings, key, value)
    room = Room(
        code="ABCDEF",
        host_id="host",
        settings=settings,
        created_at=NOW,
        last_activity_at=NOW,
    )
    host = Player(id="host", name="ホスト")
    gs.add_player(room, host)
    return room


def add_guest(room: Room, player_id: str = "guest", name: str = "ゲスト") -> Player:
    player = Player(id=player_id, name=name)
    gs.add_player(room, player)
    return player


def ready_all_humans(room: Room) -> None:
    for p in room.human_players():
        gs.set_ready(room, p.id, True)


class TestAddPlayerAndCpu:
    def test_add_player_success(self) -> None:
        room = make_room()
        add_guest(room)
        assert "guest" in room.players

    def test_room_full_raises(self) -> None:
        room = make_room()
        for i in range(7):  # host含めてMAX_PLAYERS=8まで埋める
            add_guest(room, player_id=f"p{i}")
        with pytest.raises(GameError) as exc_info:
            add_guest(room, player_id="overflow")
        assert exc_info.value.code == "ROOM_FULL"

    def test_add_player_wrong_phase_raises(self) -> None:
        room = make_room()
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        with pytest.raises(GameError) as exc_info:
            add_guest(room)
        assert exc_info.value.code == "INVALID_PHASE"

    def test_add_cpu_is_auto_ready(self) -> None:
        room = make_room()
        cpu = Player(id="cpu1", name="CPU-1")
        gs.add_cpu(room, "host", cpu)
        assert room.players["cpu1"].is_cpu is True
        assert room.players["cpu1"].is_ready is True

    def test_add_cpu_requires_host(self) -> None:
        room = make_room()
        add_guest(room)
        cpu = Player(id="cpu1", name="CPU-1")
        with pytest.raises(GameError) as exc_info:
            gs.add_cpu(room, "guest", cpu)
        assert exc_info.value.code == "NOT_HOST"

    def test_remove_cpu_requires_host(self) -> None:
        room = make_room()
        add_guest(room)
        cpu = Player(id="cpu1", name="CPU-1")
        gs.add_cpu(room, "host", cpu)
        with pytest.raises(GameError) as exc_info:
            gs.remove_cpu(room, "guest", "cpu1")
        assert exc_info.value.code == "NOT_HOST"

    def test_remove_cpu_on_human_raises(self) -> None:
        room = make_room()
        add_guest(room)
        with pytest.raises(GameError) as exc_info:
            gs.remove_cpu(room, "host", "guest")
        assert exc_info.value.code == "NOT_A_CPU"


class TestReadyAndSettings:
    def test_set_ready_toggle(self) -> None:
        room = make_room()
        add_guest(room)
        gs.set_ready(room, "guest", True)
        assert room.players["guest"].is_ready is True
        gs.set_ready(room, "guest", False)
        assert room.players["guest"].is_ready is False

    def test_cpu_ready_is_ignored(self) -> None:
        room = make_room()
        cpu = Player(id="cpu1", name="CPU-1")
        gs.add_cpu(room, "host", cpu)
        gs.set_ready(room, "cpu1", False)
        assert room.players["cpu1"].is_ready is True

    def test_is_all_ready_false_when_no_players(self) -> None:
        room = Room(
            code="X", host_id="none", settings=GameSettings(), created_at=NOW, last_activity_at=NOW
        )
        assert gs.is_all_ready(room) is False

    def test_is_all_ready_true_when_all_humans_ready(self) -> None:
        room = make_room()
        add_guest(room)
        ready_all_humans(room)
        assert gs.is_all_ready(room) is True

    def test_update_settings_requires_host(self) -> None:
        room = make_room()
        add_guest(room)
        with pytest.raises(GameError) as exc_info:
            gs.update_settings(room, "guest", GameSettings(digits=5))
        assert exc_info.value.code == "NOT_HOST"

    def test_update_settings_validates_digits(self) -> None:
        room = make_room()
        with pytest.raises(GameError):
            gs.update_settings(room, "host", GameSettings(digits=2))


class TestStartAndBeginPlay:
    def test_start_game_requires_host(self) -> None:
        room = make_room()
        add_guest(room)
        ready_all_humans(room)
        with pytest.raises(GameError) as exc_info:
            gs.start_game(room, "guest", NOW)
        assert exc_info.value.code == "NOT_HOST"

    def test_start_game_requires_all_ready(self) -> None:
        room = make_room()
        add_guest(room)  # guestはreadyにしない
        with pytest.raises(GameError) as exc_info:
            gs.start_game(room, "host", NOW)
        assert exc_info.value.code == "NOT_ALL_READY"

    def test_start_game_transitions_to_ready(self) -> None:
        room = make_room()
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        assert room.phase == GamePhase.READY
        assert room.ready_at == NOW

    def test_begin_play_does_not_recheck_wall_clock(self) -> None:
        # begin_play はREADYフェーズであることだけを条件にする。
        # 「実際にカウントダウン秒数だけ待ったか」はws/handlers.pyの
        # asyncio.sleep(単調増加クロック基準)が保証する担当分であり、
        # ここで壁時計を再比較すると、コンテナ起動直後の時刻補正などで
        # 壁時計が巻き戻った場合に誤って失敗してしまうため、あえて
        # 検証を行わない設計にしている。境界値(カウントダウン未経過の
        # 時刻)を渡しても正常に完了することを確認する。
        room = make_room()
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        too_early = NOW + timedelta(seconds=1)
        gs.begin_play(room, too_early)
        assert room.phase == GamePhase.PLAYING

    def test_begin_play_wrong_phase_raises(self) -> None:
        room = make_room()
        with pytest.raises(GameError) as exc_info:
            gs.begin_play(room, NOW)
        assert exc_info.value.code == "INVALID_PHASE"

    def test_begin_play_after_countdown_starts_playing(self) -> None:
        room = make_room()
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        after = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, after)
        assert room.phase == GamePhase.PLAYING
        assert room.secret_number is not None
        assert len(room.secret_number) == 4
        assert room.started_at == after


class TestRecordGuess:
    def _playing_room(self) -> Room:
        room = make_room(max_attempts=3)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        gs.begin_play(room, NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC))
        return room

    def test_record_guess_wrong_phase_raises(self) -> None:
        room = make_room()
        with pytest.raises(GameError) as exc_info:
            gs.record_guess(room, "host", [1, 2, 3, 4], NOW)
        assert exc_info.value.code == "INVALID_PHASE"

    def test_record_guess_unknown_player_raises(self) -> None:
        room = self._playing_room()
        with pytest.raises(GameError) as exc_info:
            gs.record_guess(room, "nobody", [1, 2, 3, 4], NOW)
        assert exc_info.value.code == "PLAYER_NOT_FOUND"

    def test_record_guess_invalid_format_raises(self) -> None:
        room = self._playing_room()
        with pytest.raises(GuessValidationError):
            gs.record_guess(room, "host", [1, 2, 3], NOW)  # 桁数不足

    def test_record_guess_correct_marks_solved(self) -> None:
        room = self._playing_room()
        secret = room.secret_number
        guess_time = room.started_at + timedelta(seconds=5)
        record = gs.record_guess(room, "host", secret, guess_time)
        assert record.hit == 4
        assert room.players["host"].finished is True
        assert room.players["host"].solved is True
        assert room.players["host"].finished_at_sec == 5.0

    def test_record_guess_exhausts_attempts(self) -> None:
        room = self._playing_room()  # max_attempts=3
        # 秘密の数字と必ず異なる予想を作る
        wrong = [(d + 1) % 10 for d in room.secret_number]
        for _ in range(3):
            gs.record_guess(room, "host", wrong, NOW)
        assert room.players["host"].finished is True
        assert room.players["host"].solved is False

    def test_record_guess_after_finished_raises(self) -> None:
        room = self._playing_room()
        secret = room.secret_number
        gs.record_guess(room, "host", secret, NOW)
        with pytest.raises(GameError) as exc_info:
            gs.record_guess(room, "host", secret, NOW)
        assert exc_info.value.code == "ALREADY_FINISHED"


class TestTimeAndRoundOver:
    def test_time_remaining_none_when_unlimited(self) -> None:
        room = make_room(time_limit_sec=0)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        gs.begin_play(room, NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC))
        assert gs.time_remaining_sec(room, NOW) is None

    def test_time_remaining_counts_down(self) -> None:
        room = make_room(time_limit_sec=60)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        start = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, start)
        remaining = gs.time_remaining_sec(room, start + timedelta(seconds=10))
        assert remaining == 50.0

    def test_is_round_over_when_all_finished(self) -> None:
        room = make_room(max_attempts=1)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        start = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, start)
        wrong = [(d + 1) % 10 for d in room.secret_number]
        gs.record_guess(room, "host", wrong, start)
        assert gs.is_round_over(room, start) is True

    def test_is_round_over_when_time_exceeded(self) -> None:
        room = make_room(time_limit_sec=30)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        start = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, start)
        later = start + timedelta(seconds=31)
        assert gs.is_round_over(room, later) is True

    def test_is_round_over_false_when_still_playing(self) -> None:
        room = make_room(time_limit_sec=30)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        start = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, start)
        assert gs.is_round_over(room, start + timedelta(seconds=5)) is False


class TestFinishGameRanking:
    def test_ranking_order_by_attempts_then_time(self) -> None:
        room = make_room(max_attempts=5)
        add_guest(room)
        cpu = Player(id="cpu1", name="CPU-1")
        gs.add_cpu(room, "host", cpu)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        start = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, start)
        secret = room.secret_number
        wrong = [(d + 1) % 10 for d in secret]

        # host: 2手で正解(速い)
        gs.record_guess(room, "host", wrong, start)
        gs.record_guess(room, "host", secret, start + timedelta(seconds=10))
        # guest: 1手で正解だが時間はhostより後
        gs.record_guess(room, "guest", secret, start + timedelta(seconds=20))
        # cpu1: 不正解のまま終了させる(finish_gameで強制終了)

        rankings = gs.finish_game(room, start + timedelta(seconds=25))
        by_id = {r.player_id: r for r in rankings}

        assert by_id["guest"].rank == 1  # 1手で正解が最速
        assert by_id["host"].rank == 2  # 2手で正解
        assert by_id["cpu1"].rank == 3  # 未正解は最後
        assert by_id["cpu1"].solved is False
        assert room.phase == GamePhase.RESULT

    def test_finish_game_wrong_phase_raises(self) -> None:
        room = make_room()
        with pytest.raises(GameError) as exc_info:
            gs.finish_game(room, NOW)
        assert exc_info.value.code == "INVALID_PHASE"


class TestRematch:
    def _result_room(self) -> Room:
        room = make_room(max_attempts=1)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        start = NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC)
        gs.begin_play(room, start)
        wrong = [(d + 1) % 10 for d in room.secret_number]
        gs.record_guess(room, "host", wrong, start)
        gs.finish_game(room, start)
        return room

    def test_rematch_requires_host(self) -> None:
        room = self._result_room()
        with pytest.raises(GameError) as exc_info:
            gs.rematch(room, "someone-else", NOW)
        assert exc_info.value.code == "NOT_HOST"

    def test_rematch_resets_state(self) -> None:
        room = self._result_room()
        gs.rematch(room, "host", NOW)
        assert room.phase == GamePhase.WAITING
        assert room.secret_number is None
        assert room.players["host"].is_ready is False
        assert room.players["host"].attempts == 0
        assert room.players["host"].guesses == []


class TestLeaveRoom:
    def test_leave_during_waiting_removes_player(self) -> None:
        room = make_room()
        add_guest(room)
        gs.leave_room(room, "guest", NOW)
        assert "guest" not in room.players

    def test_host_leaving_waiting_transfers_host(self) -> None:
        room = make_room()
        add_guest(room)
        gs.leave_room(room, "host", NOW)
        assert room.host_id == "guest"

    def test_leave_during_playing_marks_disconnected_without_removing(self) -> None:
        room = make_room()
        add_guest(room)
        ready_all_humans(room)
        gs.start_game(room, "host", NOW)
        gs.begin_play(room, NOW + timedelta(seconds=gs.READY_COUNTDOWN_SEC))
        gs.leave_room(room, "guest", NOW)
        assert "guest" in room.players
        assert room.players["guest"].connected is False

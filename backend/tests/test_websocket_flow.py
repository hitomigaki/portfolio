"""WebSocket経由のゲーム進行(レースモード)の結合テスト。

FastAPIのTestClientでREST→WebSocketの一連の流れを、実際にJSONメッセージを
やり取りしながら検証する。カウントダウンは READY_COUNTDOWN_SEC を
monkeypatchして0秒にし、テストを実時間の待ちに依存させないようにしている。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import game_state
from app.main import create_app


@pytest.fixture
def fast_countdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(game_state, "READY_COUNTDOWN_SEC", 0)


def _auth(payload_id: str, token: str) -> dict:
    return {"type": "auth", "payload": {"player_id": payload_id, "token": token}}


class TestFullRaceFlow:
    def test_two_players_race_to_the_answer(self, fast_countdown: None) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 3,
                    "allow_duplicate": True,
                    "max_attempts": 5,
                    "time_limit_sec": 0,
                    "mode": "race",
                },
            ).json()
            code = created["room_code"]
            alice_id, alice_token = created["player_id"], created["token"]

            joined = c.post(f"/api/rooms/{code}/join", json={"name": "Bob"}).json()
            bob_id, bob_token = joined["player_id"], joined["token"]

            with c.websocket_connect(f"/ws/{code}") as alice, c.websocket_connect(
                f"/ws/{code}"
            ) as bob:
                # BobはこのWebSocket接続より前にREST(/join)で既に room.players に
                # 登録済みなので、Aliceの最初の room_state 時点で人数は2人
                # (Bobはまだ connected=False)。
                alice.send_json(_auth(alice_id, alice_token))
                msg = alice.receive_json()
                assert msg["type"] == "room_state"
                players_by_id = {p["id"]: p for p in msg["payload"]["players"]}
                assert len(players_by_id) == 2
                assert players_by_id[alice_id]["connected"] is True
                assert players_by_id[bob_id]["connected"] is False

                bob.send_json(_auth(bob_id, bob_token))
                msg = alice.receive_json()
                assert {p["id"]: p["connected"] for p in msg["payload"]["players"]} == {
                    alice_id: True,
                    bob_id: True,
                }
                assert bob.receive_json()["type"] == "room_state"

                alice.send_json({"type": "ready", "payload": {"is_ready": True}})
                assert alice.receive_json()["type"] == "room_state"
                assert bob.receive_json()["type"] == "room_state"

                bob.send_json({"type": "ready", "payload": {"is_ready": True}})
                assert alice.receive_json()["type"] == "room_state"
                assert bob.receive_json()["type"] == "room_state"

                alice.send_json({"type": "start_game", "payload": {}})
                assert alice.receive_json()["payload"]["phase"] == "READY"
                assert bob.receive_json()["payload"]["phase"] == "READY"

                assert alice.receive_json()["type"] == "game_started"
                assert bob.receive_json()["type"] == "game_started"

                room = app.state.room_manager.get_room(code)
                secret = room.secret_number
                assert len(secret) == 3
                wrong = [(d + 1) % 10 for d in secret]

                # Aliceが1回目(はずれ)
                alice.send_json({"type": "guess", "payload": {"numbers": wrong}})
                r_self = alice.receive_json()
                assert r_self["type"] == "guess_result"
                assert r_self["payload"]["numbers"] == wrong
                r_other = bob.receive_json()
                assert "numbers" not in r_other["payload"]
                assert r_other["payload"]["player_id"] == alice_id

                # Aliceが2回目(正解、2手で決着)
                alice.send_json({"type": "guess", "payload": {"numbers": secret}})
                assert alice.receive_json()["payload"]["hit"] == 3
                assert bob.receive_json()["payload"]["hit"] == 3

                # Bobが1回目でいきなり正解(1手で決着)→全員終了でgame_resultも届く
                bob.send_json({"type": "guess", "payload": {"numbers": secret}})
                assert alice.receive_json()["type"] == "guess_result"
                assert bob.receive_json()["type"] == "guess_result"

                result_alice = alice.receive_json()
                result_bob = bob.receive_json()
                assert result_alice["type"] == "game_result"
                assert result_bob["type"] == "game_result"
                assert result_alice["payload"]["secret_number"] == secret

                rankings = {r["player_id"]: r for r in result_alice["payload"]["rankings"]}
                assert rankings[bob_id]["rank"] == 1
                assert rankings[bob_id]["attempts"] == 1
                assert rankings[alice_id]["rank"] == 2
                assert rankings[alice_id]["attempts"] == 2


class TestCpuLobbyOperations:
    def test_add_and_remove_cpu(self) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()  # 初期room_state

                alice.send_json({"type": "add_cpu", "payload": {"difficulty": "hard"}})
                msg = alice.receive_json()
                cpus = [p for p in msg["payload"]["players"] if p["is_cpu"]]
                assert len(cpus) == 1
                assert cpus[0]["cpu_difficulty"] == "hard"
                assert cpus[0]["is_ready"] is True

                alice.send_json({"type": "remove_cpu", "payload": {"player_id": cpus[0]["id"]}})
                msg = alice.receive_json()
                assert len([p for p in msg["payload"]["players"] if p["is_cpu"]]) == 0

    def test_non_host_cannot_add_cpu(self) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            code = created["room_code"]
            joined = c.post(f"/api/rooms/{code}/join", json={"name": "Bob"}).json()

            with c.websocket_connect(f"/ws/{code}") as alice, c.websocket_connect(
                f"/ws/{code}"
            ) as bob:
                alice.send_json(_auth(created["player_id"], created["token"]))
                alice.receive_json()
                bob.send_json(_auth(joined["player_id"], joined["token"]))
                alice.receive_json()
                bob.receive_json()

                bob.send_json({"type": "add_cpu", "payload": {"difficulty": "easy"}})
                err = bob.receive_json()
                assert err["type"] == "error"
                assert err["payload"]["code"] == "NOT_HOST"


class TestPermissionAndValidationErrors:
    def test_non_host_cannot_start_game(self) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            code = created["room_code"]
            joined = c.post(f"/api/rooms/{code}/join", json={"name": "Bob"}).json()

            with c.websocket_connect(f"/ws/{code}") as alice, c.websocket_connect(
                f"/ws/{code}"
            ) as bob:
                alice.send_json(_auth(created["player_id"], created["token"]))
                alice.receive_json()
                bob.send_json(_auth(joined["player_id"], joined["token"]))
                alice.receive_json()
                bob.receive_json()

                bob.send_json({"type": "start_game", "payload": {}})
                err = bob.receive_json()
                assert err["type"] == "error"
                assert err["payload"]["code"] == "NOT_HOST"

    def test_invalid_guess_returns_error(self, fast_countdown: None) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()

                alice.send_json({"type": "ready", "payload": {"is_ready": True}})
                alice.receive_json()
                alice.send_json({"type": "start_game", "payload": {}})
                alice.receive_json()  # room_state(READY)
                alice.receive_json()  # game_started

                alice.send_json({"type": "guess", "payload": {"numbers": [1, 2]}})
                err = alice.receive_json()
                assert err["type"] == "error"
                assert err["payload"]["code"] == "INVALID_LENGTH"

    def test_wrong_token_closes_connection(self) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            code, alice_id = created["room_code"], created["player_id"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, "invalid-token"))
                with pytest.raises(Exception):
                    alice.receive_json()


class TestCpuAutoPlay:
    def test_cpu_guesses_automatically_without_any_trigger(
        self, fast_countdown: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.ws import handlers

        # 実際の思考間隔(0.8〜1.8秒)を待っているとテストが遅くなるため短縮する
        monkeypatch.setattr(handlers, "CPU_GUESS_DELAY_RANGE_SEC", (0, 0.01))

        app = create_app()
        with TestClient(app) as c:
            created = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 3,
                    "allow_duplicate": False,
                    "max_attempts": 8,
                    "time_limit_sec": 0,
                    "mode": "race",
                },
            ).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()  # 初期room_state

                alice.send_json({"type": "add_cpu", "payload": {"difficulty": "easy"}})
                msg = alice.receive_json()
                cpu_id = next(p["id"] for p in msg["payload"]["players"] if p["is_cpu"])

                alice.send_json({"type": "ready", "payload": {"is_ready": True}})
                alice.receive_json()

                alice.send_json({"type": "start_game", "payload": {}})
                assert alice.receive_json()["payload"]["phase"] == "READY"
                assert alice.receive_json()["type"] == "game_started"

                # 誰からも指示していないのに、CPUが自動的に予想を送ってくるはず
                msg = alice.receive_json()
                assert msg["type"] == "guess_result"
                assert msg["payload"]["player_id"] == cpu_id
                assert "numbers" not in msg["payload"]  # Aliceは本人ではないので非公開

    def test_hard_cpu_keeps_guessing_and_eventually_solves(
        self, fast_countdown: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 注意: ここではホスト(Alice)自身は一度も予想を送らない。
        # is_round_over は「全員終了」で判定されるため、ラウンド全体の終了
        # (game_result)まで待つとAliceが未終了のまま止まってしまう。
        # そのため、このテストはCPUが複数手にわたって自動的に予想を続け、
        # 最終的に正解できることだけをguess_resultのストリームから確認する。
        from app.ws import handlers

        monkeypatch.setattr(handlers, "CPU_GUESS_DELAY_RANGE_SEC", (0, 0.01))

        app = create_app()
        with TestClient(app) as c:
            created = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 3,
                    "allow_duplicate": False,
                    "max_attempts": 10,
                    "time_limit_sec": 0,
                    "mode": "solo",
                },
            ).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()

                alice.send_json({"type": "add_cpu", "payload": {"difficulty": "hard"}})
                alice.receive_json()

                alice.send_json({"type": "start_game", "payload": {}})
                assert alice.receive_json()["payload"]["phase"] == "READY"
                assert alice.receive_json()["type"] == "game_started"

                solved = False
                for _ in range(10):
                    msg = alice.receive_json()
                    assert msg["type"] == "guess_result"
                    if msg["payload"]["hit"] == 3:
                        solved = True
                        break

                assert solved, "CPU(強)が10手以内に正解できなかった"

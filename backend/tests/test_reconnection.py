"""再接続時のゲーム状態復元(game_snapshot)の結合テスト。

WebSocket接続が切れて同じ player_id/token で繋ぎ直したとき、
room_state だけでは分からない「今何手目まで進んでいるか」
「もう結果が出ているか」を game_snapshot で復元できることを確認する。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import game_state
from app.main import create_app


@pytest.fixture
def fast_countdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(game_state, "READY_COUNTDOWN_SEC", 0)


def _auth(player_id: str, token: str) -> dict:
    return {"type": "auth", "payload": {"player_id": player_id, "token": token}}


class TestReconnectDuringPlaying:
    def test_snapshot_restores_own_history_with_numbers(self, fast_countdown: None) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 3,
                    "allow_duplicate": False,
                    "max_attempts": 5,
                    "time_limit_sec": 0,
                    "mode": "solo",
                },
            ).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()  # room_state

                alice.send_json({"type": "start_game", "payload": {}})
                assert alice.receive_json()["payload"]["phase"] == "READY"
                assert alice.receive_json()["type"] == "game_started"

                alice.send_json({"type": "guess", "payload": {"numbers": [1, 2, 3]}})
                alice.receive_json()  # guess_result

            # ここで一度切断。同じplayer_id/tokenで繋ぎ直す。
            with c.websocket_connect(f"/ws/{code}") as alice2:
                alice2.send_json(_auth(alice_id, token))
                room_state = alice2.receive_json()
                assert room_state["type"] == "room_state"
                assert room_state["payload"]["phase"] == "PLAYING"

                snapshot = alice2.receive_json()
                assert snapshot["type"] == "game_snapshot"
                payload = snapshot["payload"]
                assert payload["phase"] == "PLAYING"
                assert payload["settings"]["digits"] == 3
                assert "started_at" in payload

                own_history = payload["history"][alice_id]
                assert len(own_history) == 1
                assert own_history[0]["numbers"] == [1, 2, 3]
                assert own_history[0]["attempt_no"] == 1

    def test_reconnected_player_can_keep_guessing(self, fast_countdown: None) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 3,
                    "allow_duplicate": False,
                    "max_attempts": 5,
                    "time_limit_sec": 0,
                    "mode": "solo",
                },
            ).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()
                alice.send_json({"type": "start_game", "payload": {}})
                alice.receive_json()
                alice.receive_json()
                alice.send_json({"type": "guess", "payload": {"numbers": [1, 2, 3]}})
                alice.receive_json()

            with c.websocket_connect(f"/ws/{code}") as alice2:
                alice2.send_json(_auth(alice_id, token))
                alice2.receive_json()  # room_state
                alice2.receive_json()  # game_snapshot

                alice2.send_json({"type": "guess", "payload": {"numbers": [4, 5, 6]}})
                result = alice2.receive_json()
                assert result["type"] == "guess_result"
                assert result["payload"]["attempt_no"] == 2


class TestReconnectDuringResult:
    def test_snapshot_restores_result_screen(self, fast_countdown: None) -> None:
        app = create_app()
        with TestClient(app) as c:
            created = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 3,
                    "allow_duplicate": False,
                    "max_attempts": 1,
                    "time_limit_sec": 0,
                    "mode": "solo",
                },
            ).json()
            code, alice_id, token = created["room_code"], created["player_id"], created["token"]

            with c.websocket_connect(f"/ws/{code}") as alice:
                alice.send_json(_auth(alice_id, token))
                alice.receive_json()
                alice.send_json({"type": "start_game", "payload": {}})
                alice.receive_json()
                alice.receive_json()

                # max_attempts=1なので、この1回でPLAYING→RESULTに遷移する
                alice.send_json({"type": "guess", "payload": {"numbers": [1, 2, 3]}})
                alice.receive_json()  # guess_result
                result_msg = alice.receive_json()
                assert result_msg["type"] == "game_result"
                secret = result_msg["payload"]["secret_number"]

            with c.websocket_connect(f"/ws/{code}") as alice2:
                alice2.send_json(_auth(alice_id, token))
                room_state = alice2.receive_json()
                assert room_state["payload"]["phase"] == "RESULT"

                snapshot = alice2.receive_json()
                assert snapshot["type"] == "game_snapshot"
                payload = snapshot["payload"]
                assert payload["phase"] == "RESULT"
                assert payload["secret_number"] == secret
                assert len(payload["rankings"]) == 1
                assert payload["rankings"][0]["player_id"] == alice_id

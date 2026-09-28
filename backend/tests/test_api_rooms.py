"""REST API (/api/rooms) の統合テスト。"""

from fastapi.testclient import TestClient

from app.main import create_app


def client() -> TestClient:
    return TestClient(create_app())


class TestCreateRoom:
    def test_create_room_returns_code_and_token(self) -> None:
        with client() as c:
            res = c.post("/api/rooms", json={"host_name": "Alice"})
            assert res.status_code == 200
            body = res.json()
            assert len(body["room_code"]) == 6
            assert body["player_id"]
            assert body["token"]
            assert body["mode"] == "race"

    def test_create_room_with_custom_settings(self) -> None:
        with client() as c:
            res = c.post(
                "/api/rooms",
                json={
                    "host_name": "Alice",
                    "digits": 5,
                    "allow_duplicate": True,
                    "max_attempts": 8,
                    "time_limit_sec": 120,
                    "mode": "solo",
                },
            )
            assert res.status_code == 200
            assert res.json()["mode"] == "solo"

    def test_empty_host_name_rejected(self) -> None:
        with client() as c:
            res = c.post("/api/rooms", json={"host_name": "   "})
            assert res.status_code == 422

    def test_invalid_digits_rejected(self) -> None:
        with client() as c:
            res = c.post("/api/rooms", json={"host_name": "Alice", "digits": 2})
            assert res.status_code == 422


class TestJoinRoom:
    def test_join_existing_room(self) -> None:
        with client() as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            res = c.post(f"/api/rooms/{created['room_code']}/join", json={"name": "Bob"})
            assert res.status_code == 200
            body = res.json()
            assert body["player_id"] != created["player_id"]
            assert body["token"] != created["token"]

    def test_join_nonexistent_room_returns_404(self) -> None:
        with client() as c:
            res = c.post("/api/rooms/ZZZZZZ/join", json={"name": "Bob"})
            assert res.status_code == 404
            assert res.json()["detail"]["code"] == "ROOM_NOT_FOUND"

    def test_join_lowercase_code_is_normalized(self) -> None:
        with client() as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            res = c.post(f"/api/rooms/{created['room_code'].lower()}/join", json={"name": "Bob"})
            assert res.status_code == 200


class TestGetRoomInfo:
    def test_get_room_info(self) -> None:
        with client() as c:
            created = c.post("/api/rooms", json={"host_name": "Alice"}).json()
            res = c.get(f"/api/rooms/{created['room_code']}")
            assert res.status_code == 200
            body = res.json()
            assert body["phase"] == "WAITING"
            assert body["player_count"] == 1

    def test_get_room_info_not_found(self) -> None:
        with client() as c:
            res = c.get("/api/rooms/ZZZZZZ")
            assert res.status_code == 404


class TestRoomLookupRateLimit:
    def test_blocks_after_too_many_lookups_from_same_client(self) -> None:
        # config.ROOM_LOOKUP_RATE_LIMIT_MAX_ATTEMPTS(既定20)を超えたら
        # ルームコードの存在確認(総当たりされうるエンドポイント)を遮断する。
        with client() as c:
            statuses = [c.get("/api/rooms/ZZZZZZ").status_code for _ in range(25)]

        assert statuses[:20] == [404] * 20
        assert 429 in statuses[20:]

    def test_join_endpoint_is_also_rate_limited(self) -> None:
        with client() as c:
            statuses = [
                c.post("/api/rooms/ZZZZZZ/join", json={"name": "Bob"}).status_code for _ in range(25)
            ]

        assert 429 in statuses[20:]

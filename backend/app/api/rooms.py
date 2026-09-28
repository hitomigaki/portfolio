"""ルーム作成・参加のREST API。

WebSocketは「すでに参加登録された人が継続的にやり取りする」ための通信路で、
「部屋を作る」「名前を名乗って参加する」という単発の操作はREST側に置く。
参加時に発行される player_id / token を使って、この後WebSocketに接続する。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.errors import GameError
from app.core.rate_limiter import RateLimiter
from app.core.room import MAX_PLAYERS, GameSettings
from app.core.room_manager import RoomManager
from app.schemas.rest import (
    CreateRoomRequest,
    CreateRoomResponse,
    JoinRoomRequest,
    JoinRoomResponse,
    RoomInfoResponse,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def get_room_manager(request: Request) -> RoomManager:
    return request.app.state.room_manager


def get_room_lookup_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.room_lookup_rate_limiter


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_http_error(error: GameError) -> HTTPException:
    status_code = 404 if error.code == "ROOM_NOT_FOUND" else 400
    return HTTPException(status_code=status_code, detail={"code": error.code, "message": error.message})


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_room_lookup_rate_limit(request: Request, limiter: RateLimiter) -> None:
    # ルームコードは6文字の英数字を当てにいく形の入力(存在確認・参加)なので、
    # 同一IPからの試行回数をここで制限する。作成(create_room)は既存コードの
    # 当てずっぽうとは無関係なので対象外。
    if not limiter.check_and_record(_client_key(request), _now()):
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "試行回数が多すぎます。しばらく待ってから再度お試しください"},
        )


@router.post("", response_model=CreateRoomResponse)
def create_room(
    body: CreateRoomRequest, manager: RoomManager = Depends(get_room_manager)
) -> CreateRoomResponse:
    settings = GameSettings(
        digits=body.digits,
        allow_duplicate=body.allow_duplicate,
        max_attempts=body.max_attempts,
        time_limit_sec=body.time_limit_sec,
        mode=body.mode,
    )
    try:
        result = manager.create_room(body.host_name, settings, _now())
    except GameError as e:
        raise _to_http_error(e) from e

    return CreateRoomResponse(
        room_code=result.room.code,
        player_id=result.player.id,
        token=result.token,
        mode=settings.mode,
    )


@router.get("/{code}", response_model=RoomInfoResponse)
def get_room_info(
    code: str,
    request: Request,
    manager: RoomManager = Depends(get_room_manager),
    limiter: RateLimiter = Depends(get_room_lookup_rate_limiter),
) -> RoomInfoResponse:
    _enforce_room_lookup_rate_limit(request, limiter)
    room = manager.get_room(code.upper())
    if room is None:
        raise HTTPException(
            status_code=404, detail={"code": "ROOM_NOT_FOUND", "message": "ルームが見つかりません"}
        )
    return RoomInfoResponse(
        code=room.code,
        phase=room.phase.value,
        mode=room.settings.mode,
        player_count=len(room.players),
        max_players=MAX_PLAYERS,
    )


@router.post("/{code}/join", response_model=JoinRoomResponse)
def join_room(
    code: str,
    body: JoinRoomRequest,
    request: Request,
    manager: RoomManager = Depends(get_room_manager),
    limiter: RateLimiter = Depends(get_room_lookup_rate_limiter),
) -> JoinRoomResponse:
    _enforce_room_lookup_rate_limit(request, limiter)
    try:
        result = manager.join_room(code.upper(), body.name, _now())
    except GameError as e:
        raise _to_http_error(e) from e

    return JoinRoomResponse(room_code=result.room.code, player_id=result.player.id, token=result.token)

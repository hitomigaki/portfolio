"""REST API (ルーム作成・参加) のリクエスト/レスポンス型。

WebSocketのメッセージ型(messages.py)とは別ファイルに分けている。
役割が異なる(HTTPの単発リクエストか、WSの継続的なやり取りか)ため、
将来どちらかの仕様だけを変える場合に影響範囲を分離できる。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import NAME_MAX_LENGTH


class CreateRoomRequest(BaseModel):
    host_name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    digits: int = Field(default=4, ge=3, le=5)
    allow_duplicate: bool = False
    max_attempts: int = Field(default=10, ge=1, le=50)
    time_limit_sec: int = Field(default=300, ge=0, le=3600)
    mode: Literal["race", "solo"] = "race"

    @field_validator("host_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名前を入力してください")
        return v


class CreateRoomResponse(BaseModel):
    room_code: str
    player_id: str
    token: str
    mode: Literal["race", "solo"]


class JoinRoomRequest(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名前を入力してください")
        return v


class JoinRoomResponse(BaseModel):
    room_code: str
    player_id: str
    token: str


class RoomInfoResponse(BaseModel):
    code: str
    phase: str
    mode: Literal["race", "solo"]
    player_count: int
    max_players: int

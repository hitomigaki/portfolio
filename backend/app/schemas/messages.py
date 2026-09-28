"""クライアント→サーバーのWebSocketメッセージ定義。

設計(ステップ1)で決めたエンベロープ形式 { "type": ..., "payload": ... } を
Pydanticの discriminated union で表現する。ここでの検証は「形式が正しいか」
までで、「今その操作をしてよいか」は core/game_state.py の責務にする
(層ごとに検証の役割を分ける)。
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class EmptyPayload(BaseModel):
    """payloadを持たないメッセージ用。"""


class AuthPayload(BaseModel):
    player_id: str
    token: str


class AuthMessage(BaseModel):
    type: Literal["auth"] = "auth"
    payload: AuthPayload


class ReadyPayload(BaseModel):
    is_ready: bool


class ReadyMessage(BaseModel):
    type: Literal["ready"] = "ready"
    payload: ReadyPayload


class UpdateSettingsPayload(BaseModel):
    # ここでの上限・下限はネットワーク境界での一次防御。
    # 実際の整合性(重複可否と桁数の組み合わせなど)は GameRules 側で検証する。
    digits: int = Field(default=4, ge=3, le=5)
    allow_duplicate: bool = False
    max_attempts: int = Field(default=10, ge=1, le=50)
    time_limit_sec: int = Field(default=300, ge=0, le=3600)
    mode: Literal["race", "solo"] = "race"


class UpdateSettingsMessage(BaseModel):
    type: Literal["update_settings"] = "update_settings"
    payload: UpdateSettingsPayload


class AddCpuPayload(BaseModel):
    difficulty: Literal["easy", "normal", "hard"] = "normal"


class AddCpuMessage(BaseModel):
    type: Literal["add_cpu"] = "add_cpu"
    payload: AddCpuPayload


class RemoveCpuPayload(BaseModel):
    player_id: str


class RemoveCpuMessage(BaseModel):
    type: Literal["remove_cpu"] = "remove_cpu"
    payload: RemoveCpuPayload


class StartGameMessage(BaseModel):
    type: Literal["start_game"] = "start_game"
    payload: EmptyPayload = EmptyPayload()


class GuessPayload(BaseModel):
    numbers: list[int] = Field(min_length=1, max_length=10)


class GuessMessage(BaseModel):
    type: Literal["guess"] = "guess"
    payload: GuessPayload


class LeaveMessage(BaseModel):
    type: Literal["leave"] = "leave"
    payload: EmptyPayload = EmptyPayload()


class RematchMessage(BaseModel):
    type: Literal["rematch"] = "rematch"
    payload: EmptyPayload = EmptyPayload()


ClientMessage = Annotated[
    Union[
        AuthMessage,
        ReadyMessage,
        UpdateSettingsMessage,
        AddCpuMessage,
        RemoveCpuMessage,
        StartGameMessage,
        GuessMessage,
        LeaveMessage,
        RematchMessage,
    ],
    Field(discriminator="type"),
]

_client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


def parse_client_message(data: dict) -> ClientMessage:
    """生のJSON(dict)をClientMessageに検証・変換する。

    不正な場合は pydantic.ValidationError を送出する(呼び出し側でcatchする)。
    """

    return _client_message_adapter.validate_python(data)

"""core層で共通して使うエラー型。

WebSocketの error メッセージ (payload.code / payload.message) にそのまま
変換できるよう、code と message を持つ例外基底クラスをここに定義する。
"""

from __future__ import annotations


class GameError(Exception):
    """core層で発生する業務エラーの基底クラス。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

"""ルーム・プレイヤーのデータモデル。

ここに定義するのは「状態を保持する入れ物」であり、状態を変化させる
ロジック(遷移の可否判定など)は game_state.py 側に置く。
モデルと振る舞いを分けることで、「今どんなデータを持っているか」と
「どう変化してよいか」を別々にテスト・説明できるようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

CpuDifficulty = Literal["easy", "normal", "hard"]
GameMode = Literal["race", "solo"]

# 同時に着席できる人数(人間+CPU合計)。多すぎると1画面に収まらず
# UIの説明もしづらくなるため、レース感が出る範囲として8人に制限する。
MAX_PLAYERS = 8


class GamePhase(str, Enum):
    """ルームの進行状態。設計時のMermaid状態遷移図と対応する。"""

    WAITING = "WAITING"  # 待機(ロビー)
    READY = "READY"  # 準備(開始カウントダウン中)
    PLAYING = "PLAYING"  # プレイ中
    RESULT = "RESULT"  # 結果表示


@dataclass
class GameSettings:
    """1ルームのゲーム設定。ホストがWAITING中のみ変更できる。"""

    digits: int = 4
    allow_duplicate: bool = False
    max_attempts: int = 10
    time_limit_sec: int = 300  # 0 = 時間制限なし
    mode: GameMode = "race"


@dataclass
class GuessRecord:
    """1回分の予想と判定結果。"""

    attempt_no: int
    numbers: list[int]
    hit: int
    blow: int


@dataclass
class Player:
    """ルーム内の1参加者(人間 or CPU)。"""

    id: str
    name: str
    is_cpu: bool = False
    cpu_difficulty: CpuDifficulty | None = None
    is_ready: bool = False
    connected: bool = False
    attempts: int = 0
    finished: bool = False
    solved: bool = False
    finished_at_sec: float | None = None
    guesses: list[GuessRecord] = field(default_factory=list)

    def reset_for_new_round(self) -> None:
        """再戦・新ラウンド開始時に対戦成績だけをリセットする。"""

        self.attempts = 0
        self.finished = False
        self.solved = False
        self.finished_at_sec = None
        self.guesses = []


@dataclass
class RankingEntry:
    """結果画面用の1人分の順位情報。"""

    player_id: str
    rank: int
    attempts: int
    solved: bool
    time_sec: float | None


@dataclass
class Room:
    """1つの対戦ルーム。"""

    code: str
    host_id: str
    settings: GameSettings
    created_at: datetime
    last_activity_at: datetime
    players: dict[str, Player] = field(default_factory=dict)
    phase: GamePhase = GamePhase.WAITING
    secret_number: list[int] | None = None
    ready_at: datetime | None = None
    started_at: datetime | None = None
    # RESULT中に再接続してきたプレイヤーへ結果画面を復元するために保持する。
    # rematchでWAITINGへ戻る際にNoneへ戻す。
    last_rankings: list[RankingEntry] | None = None

    def human_players(self) -> list[Player]:
        return [p for p in self.players.values() if not p.is_cpu]

    def is_empty(self) -> bool:
        """再接続待ちの人間が誰もおらず、部屋を維持する理由がない状態か。"""

        return not any(p.connected for p in self.players.values() if not p.is_cpu)

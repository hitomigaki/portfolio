"""ヒット&ブロー判定ロジック。

このモジュールは FastAPI / WebSocket を一切 import しない。
「秘密の数字」と「予想」というただのリストを受け取り、結果を返すだけの
純粋関数の集まりにすることで、通信層なしに pytest で直接検証できるようにしている。
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from app.core.errors import GameError

# 数字は 0〜9 の1桁を使う(先頭桁が0でも許可する一般的なHit&Blow仕様)
DIGIT_MIN = 0
DIGIT_MAX = 9

MIN_LENGTH = 3
MAX_LENGTH = 5


class GuessValidationError(GameError):
    """予想(または生成設定)が不正なときに送出する例外。

    code はクライアントへの error メッセージ(payload.code)にそのまま使う。
    """


@dataclass(frozen=True)
class GameRules:
    """1ゲーム分の判定ルール(桁数・重複可否)。"""

    digits: int
    allow_duplicate: bool

    def __post_init__(self) -> None:
        if not (MIN_LENGTH <= self.digits <= MAX_LENGTH):
            raise GuessValidationError(
                "INVALID_DIGITS_SETTING",
                f"桁数は{MIN_LENGTH}〜{MAX_LENGTH}の範囲で設定してください",
            )
        if not self.allow_duplicate and self.digits > (DIGIT_MAX - DIGIT_MIN + 1):
            raise GuessValidationError(
                "INVALID_DIGITS_SETTING",
                "重複なしの場合、桁数が使用可能な数字の種類数を超えています",
            )


def generate_secret_number(rules: GameRules) -> list[int]:
    """秘密の数字を生成する。

    ルームコードのようにブルートフォース対象になる値ではない
    (試行回数の上限で既に総当たりを防いでいる)ため、標準の random で十分だが、
    予測されにくさを高めるために SystemRandom を使う。
    """

    rng = random.SystemRandom()
    pool = range(DIGIT_MIN, DIGIT_MAX + 1)
    if rules.allow_duplicate:
        return [rng.choice(pool) for _ in range(rules.digits)]
    return rng.sample(pool, rules.digits)


def validate_guess(guess: list[int], rules: GameRules) -> None:
    """予想の形式チェック。問題があれば GuessValidationError を送出する。"""

    if not isinstance(guess, list) or len(guess) != rules.digits:
        raise GuessValidationError(
            "INVALID_LENGTH",
            f"予想は{rules.digits}桁で入力してください",
        )
    for value in guess:
        if not isinstance(value, int) or isinstance(value, bool):
            raise GuessValidationError("INVALID_DIGIT", "数字以外が含まれています")
        if not (DIGIT_MIN <= value <= DIGIT_MAX):
            raise GuessValidationError(
                "OUT_OF_RANGE", f"{DIGIT_MIN}〜{DIGIT_MAX}の数字を入力してください"
            )
    if not rules.allow_duplicate and len(set(guess)) != len(guess):
        raise GuessValidationError(
            "DUPLICATE_NOT_ALLOWED", "このルームでは同じ数字を重複して使えません"
        )


def calculate_hits_and_blows(secret: list[int], guess: list[int]) -> tuple[int, int]:
    """ヒット数・ブロー数を返す。

    ヒット: 値と位置が一致
    ブロー: 値は一致するが位置が異なる

    重複ありの秘密の数字にも対応するため、値ごとの出現回数の min を取って
    「値としての一致総数」を求め、そこからヒット数を引いてブロー数とする
    (古典的な Mastermind の集合演算による解法)。
    """

    if len(secret) != len(guess):
        raise ValueError("secret と guess の桁数が一致していません")

    hits = sum(1 for s, g in zip(secret, guess) if s == g)

    secret_counts = Counter(secret)
    guess_counts = Counter(guess)
    total_value_matches = sum(
        min(count, guess_counts[digit]) for digit, count in secret_counts.items()
    )

    blows = total_value_matches - hits
    return hits, blows

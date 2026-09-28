"""CPUプレイヤーの予想ロジック。

judge.py と同じ理由で、WebSocketやRoomManagerを一切知らない。
「ルールと自分の過去の予想履歴を渡せば次の一手が返る」という
入出力だけのインターフェースにすることで、実際のゲームを回さずに
pytestだけで難易度ごとの賢さを検証できるようにしている。

3段階の難易度は、探索する候補集合をどう絞り込むかの違いとして実装する。
  弱  : ヒントを一切使わず、ルールを満たす数字をランダムに返す。
  普通: 過去の全ヒントと矛盾しない候補(=正解であり得る数字)の中から
        ランダムに1つ選ぶ。
  強  : 普通と同じ候補集合から、その一手を打った場合に
        「最悪でも候補がどれだけ絞れるか」が最も良い一手を選ぶ
        (Knuthのminimax法を、計算量を抑えるためサンプリングして近似したもの)。
"""

from __future__ import annotations

import random
from itertools import permutations, product

from app.core.judge import DIGIT_MAX, DIGIT_MIN, GameRules, calculate_hits_and_blows, generate_secret_number
from app.core.room import CpuDifficulty, GuessRecord

# 「強」でminimax評価する際の候補数の上限。
# 候補が多いとき、次の一手の候補(guess_options)と評価対象(scoring_pool)の
# 両方を全数計算すると O(候補数^2) になり、桁数5・重複ありなど候補が
# 10万を超える設定では現実的な時間で終わらない。
# そのため、どちらも上限を超えたらランダムサンプリングして近似する。
HARD_MAX_GUESS_OPTIONS = 200
HARD_MAX_SCORING_CANDIDATES = 300


def _all_candidates(rules: GameRules) -> list[list[int]]:
    digit_pool = range(DIGIT_MIN, DIGIT_MAX + 1)
    if rules.allow_duplicate:
        return [list(c) for c in product(digit_pool, repeat=rules.digits)]
    return [list(c) for c in permutations(digit_pool, rules.digits)]


def _is_consistent_with_history(candidate: list[int], history: list[GuessRecord]) -> bool:
    # candidateが「本当の秘密の数字」だったなら、過去の全ての予想に対して
    # 記録されているヒット/ブローと同じ結果になるはずのものだけを残す。
    # なお、外れた過去の予想自体は「自分自身と比較すると必ず全ヒット」になり
    # 記録された結果(全ヒットではないはず)と矛盾するため、この時点で自動的に
    # 候補から除外される。CPUが同じ予想を繰り返さないのはこの副作用による。
    return all(
        calculate_hits_and_blows(candidate, record.numbers) == (record.hit, record.blow)
        for record in history
    )


def _consistent_candidates(rules: GameRules, history: list[GuessRecord]) -> list[list[int]]:
    candidates = _all_candidates(rules)
    if not history:
        return candidates
    return [c for c in candidates if _is_consistent_with_history(c, history)]


def easy_guess(rules: GameRules) -> list[int]:
    return generate_secret_number(rules)


def normal_guess(rules: GameRules, history: list[GuessRecord]) -> list[int]:
    candidates = _consistent_candidates(rules, history)
    if not candidates:
        # 理論上は到達しない(自分の過去の予想は常に矛盾しない候補が残るはず)が、
        # 万一に備えた安全側のフォールバック。
        return easy_guess(rules)
    return random.choice(candidates)


def hard_guess(rules: GameRules, history: list[GuessRecord]) -> list[int]:
    candidates = _consistent_candidates(rules, history)
    if not candidates:
        return easy_guess(rules)
    if len(candidates) == 1:
        return candidates[0]

    guess_options = (
        candidates
        if len(candidates) <= HARD_MAX_GUESS_OPTIONS
        else random.sample(candidates, HARD_MAX_GUESS_OPTIONS)
    )
    scoring_pool = (
        candidates
        if len(candidates) <= HARD_MAX_SCORING_CANDIDATES
        else random.sample(candidates, HARD_MAX_SCORING_CANDIDATES)
    )

    best_guess = guess_options[0]
    best_worst_case = None
    for option in guess_options:
        buckets: dict[tuple[int, int], int] = {}
        for candidate in scoring_pool:
            key = calculate_hits_and_blows(candidate, option)
            buckets[key] = buckets.get(key, 0) + 1
        worst_case = max(buckets.values())
        if best_worst_case is None or worst_case < best_worst_case:
            best_worst_case = worst_case
            best_guess = option

    return best_guess


def next_guess(difficulty: CpuDifficulty, rules: GameRules, history: list[GuessRecord]) -> list[int]:
    if difficulty == "easy":
        return easy_guess(rules)
    if difficulty == "normal":
        return normal_guess(rules, history)
    if difficulty == "hard":
        return hard_guess(rules, history)
    raise ValueError(f"unknown difficulty: {difficulty}")

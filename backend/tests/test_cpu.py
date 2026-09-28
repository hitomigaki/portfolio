"""core/cpu.py の単体テスト。

「賢さ」は実装の中身ではなく観測できる振る舞いでテストする:
- 普通/強は必ず過去のヒントと矛盾しない予想を返すか
- 強は普通より少ない手数で正解にたどり着けるか(自己対戦シミュレーション)
"""

from __future__ import annotations

import random

import pytest

from app.core import cpu
from app.core.judge import GameRules, calculate_hits_and_blows
from app.core.room import GuessRecord


def make_history(secret: list[int], guesses: list[list[int]]) -> list[GuessRecord]:
    history = []
    for i, guess in enumerate(guesses, start=1):
        hit, blow = calculate_hits_and_blows(secret, guess)
        history.append(GuessRecord(attempt_no=i, numbers=guess, hit=hit, blow=blow))
    return history


def play_until_solved(difficulty: str, rules: GameRules, secret: list[int], max_turns: int) -> int:
    """difficultyのCPUに secret を当てさせ、正解までにかかった手数を返す。"""

    history: list[GuessRecord] = []
    for turn in range(1, max_turns + 1):
        guess = cpu.next_guess(difficulty, rules, history)
        hit, blow = calculate_hits_and_blows(secret, guess)
        history.append(GuessRecord(attempt_no=turn, numbers=guess, hit=hit, blow=blow))
        if hit == rules.digits:
            return turn
    raise AssertionError(f"{difficulty} did not solve {secret} within {max_turns} turns")


class TestEasyGuess:
    def test_respects_digit_count_and_range(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=True)
        for _ in range(30):
            guess = cpu.easy_guess(rules)
            assert len(guess) == 4
            assert all(0 <= d <= 9 for d in guess)

    def test_respects_no_duplicate_rule(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        for _ in range(30):
            guess = cpu.easy_guess(rules)
            assert len(set(guess)) == len(guess)


class TestNormalGuess:
    def test_first_guess_respects_rules_without_history(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        guess = cpu.normal_guess(rules, [])
        assert len(guess) == 4
        assert len(set(guess)) == 4

    def test_guess_is_always_consistent_with_history(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        secret = [1, 2, 3, 4]
        history = make_history(secret, [[5, 6, 7, 8], [1, 3, 2, 4]])

        for _ in range(20):
            guess = cpu.normal_guess(rules, history)
            for record in history:
                assert calculate_hits_and_blows(guess, record.numbers) == (record.hit, record.blow)

    def test_never_repeats_a_previous_unsuccessful_guess(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        secret = [1, 2, 3, 4]
        tried = [[5, 6, 7, 8], [1, 3, 2, 4], [0, 9, 1, 2]]
        history = make_history(secret, tried)

        for _ in range(20):
            guess = cpu.normal_guess(rules, history)
            assert guess not in tried

    def test_eventually_solves(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        turns = play_until_solved("normal", rules, [1, 2, 3, 4], max_turns=50)
        assert turns <= 50


class TestHardGuess:
    def test_returns_the_only_remaining_candidate(self) -> None:
        rules = GameRules(digits=3, allow_duplicate=False)
        secret = [1, 2, 3]
        # 十分に絞り込む履歴を用意し、候補が1つになる状況を作る
        history = make_history(
            secret, [[1, 2, 0], [1, 0, 3], [0, 2, 3], [2, 1, 3], [1, 3, 2]]
        )
        guess = cpu.hard_guess(rules, history)
        assert calculate_hits_and_blows(guess, secret) == (3, 0) or guess == secret

    def test_guess_is_always_consistent_with_history(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        secret = [1, 2, 3, 4]
        history = make_history(secret, [[5, 6, 7, 8]])

        for _ in range(10):
            guess = cpu.hard_guess(rules, history)
            for record in history:
                assert calculate_hits_and_blows(guess, record.numbers) == (record.hit, record.blow)

    def test_solves_within_reasonable_turns(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        turns = play_until_solved("hard", rules, [1, 2, 3, 4], max_turns=10)
        assert turns <= 10

    def test_hard_is_not_slower_than_normal_on_average(self) -> None:
        # 強・普通ともに候補集合からの乱数選択が絡むため、試行数が少ないと
        # まれに強の方が手数で上回ってしまうことがある(minimaxはサンプリング
        # による近似で、統計的に「平均して」普通より効率が良いことしか保証しない)。
        # そのため十分な数の秘密の数字で平均を取り、乱数シードも固定して
        # テストの再現性を確保する。
        rules = GameRules(digits=4, allow_duplicate=False)
        random.seed(12345)
        secrets = [
            [1, 2, 3, 4], [9, 0, 5, 2], [3, 7, 1, 8], [6, 4, 9, 1],
            [0, 8, 2, 5], [7, 3, 6, 0], [5, 1, 9, 4], [2, 6, 8, 3],
        ]

        hard_total = sum(play_until_solved("hard", rules, s, max_turns=10) for s in secrets)
        normal_total = sum(play_until_solved("normal", rules, s, max_turns=50) for s in secrets)

        assert hard_total <= normal_total


class TestNextGuessDispatch:
    def test_unknown_difficulty_raises(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        with pytest.raises(ValueError):
            cpu.next_guess("impossible", rules, [])

    @pytest.mark.parametrize("difficulty", ["easy", "normal", "hard"])
    def test_dispatches_to_matching_function(self, difficulty: str) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        guess = cpu.next_guess(difficulty, rules, [])
        assert len(guess) == 4
        assert len(set(guess)) == 4

"""core/judge.py の単体テスト。

判定ロジック(ヒット・ブロー計算)、入力バリデーション、
秘密の数字生成のそれぞれについて、正常系と境界ケースを確認する。
"""

import pytest

from app.core.judge import (
    GameRules,
    GuessValidationError,
    calculate_hits_and_blows,
    generate_secret_number,
    validate_guess,
)


class TestCalculateHitsAndBlows:
    def test_no_match(self) -> None:
        assert calculate_hits_and_blows([1, 2, 3, 4], [5, 6, 7, 8]) == (0, 0)

    def test_all_hit(self) -> None:
        assert calculate_hits_and_blows([1, 2, 3, 4], [1, 2, 3, 4]) == (4, 0)

    def test_all_blow(self) -> None:
        # 値は全て一致するが位置は全てずれている
        assert calculate_hits_and_blows([1, 2, 3, 4], [4, 1, 2, 3]) == (0, 4)

    def test_mixed_hit_and_blow(self) -> None:
        # 位置0の"1"だけヒット、"3"と"5"は値のみ一致でブロー、"9"はどちらにも無い
        assert calculate_hits_and_blows([1, 3, 5, 9], [1, 5, 3, 2]) == (1, 2)

    def test_duplicate_secret_boundary_case(self) -> None:
        # 秘密 1123 に対して予想 1111
        # 位置0,1の"1"がヒット(2ヒット)。
        # 値としての一致総数は 秘密の"1"の数(2)と予想の"1"の数(4)のmin=2。
        # ブロー = 総一致(2) - ヒット(2) = 0。
        assert calculate_hits_and_blows([1, 1, 2, 3], [1, 1, 1, 1]) == (2, 0)

    def test_duplicate_secret_with_blow(self) -> None:
        # 秘密 1123、予想 3211
        # 位置ごと: (1,3)x (1,2)x (2,1)x (3,1)x -> ヒット0
        # 値の一致総数: "1"はmin(2,2)=2、"2"はmin(1,1)=1、"3"はmin(1,1)=1 -> 合計4
        # ブロー = 4 - 0 = 4
        assert calculate_hits_and_blows([1, 1, 2, 3], [3, 2, 1, 1]) == (0, 4)

    def test_duplicate_guess_more_than_secret(self) -> None:
        # 秘密に含まれない重複を予想しても、秘密側の出現数を超えて数えない
        # 秘密 1234、予想 1112 -> ヒットは位置0の"1"のみ=1
        # 値の一致総数: "1"はmin(1,3)=1、"2"はmin(1,1)=1 -> 合計2、ブロー=2-1=1
        assert calculate_hits_and_blows([1, 2, 3, 4], [1, 1, 1, 2]) == (1, 1)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            calculate_hits_and_blows([1, 2, 3], [1, 2, 3, 4])


class TestGameRules:
    def test_valid_rules(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        assert rules.digits == 4

    @pytest.mark.parametrize("digits", [2, 6])
    def test_digits_out_of_supported_range_raises(self, digits: int) -> None:
        with pytest.raises(GuessValidationError) as exc_info:
            GameRules(digits=digits, allow_duplicate=True)
        assert exc_info.value.code == "INVALID_DIGITS_SETTING"

    def test_digits_boundary_values_are_valid(self) -> None:
        # 仕様上の境界値(3桁・5桁)は許可される
        GameRules(digits=3, allow_duplicate=False)
        GameRules(digits=5, allow_duplicate=False)


class TestValidateGuess:
    def test_valid_guess_passes(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        validate_guess([1, 2, 3, 4], rules)  # 例外が出なければOK

    def test_wrong_length_raises(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        with pytest.raises(GuessValidationError) as exc_info:
            validate_guess([1, 2, 3], rules)
        assert exc_info.value.code == "INVALID_LENGTH"

    def test_out_of_range_digit_raises(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=True)
        with pytest.raises(GuessValidationError) as exc_info:
            validate_guess([1, 2, 3, 10], rules)
        assert exc_info.value.code == "OUT_OF_RANGE"

    def test_negative_digit_raises(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=True)
        with pytest.raises(GuessValidationError) as exc_info:
            validate_guess([1, 2, 3, -1], rules)
        assert exc_info.value.code == "OUT_OF_RANGE"

    def test_non_int_raises(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=True)
        with pytest.raises(GuessValidationError) as exc_info:
            validate_guess([1, 2, 3, "4"], rules)  # type: ignore[list-item]
        assert exc_info.value.code == "INVALID_DIGIT"

    def test_duplicate_not_allowed_raises(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        with pytest.raises(GuessValidationError) as exc_info:
            validate_guess([1, 1, 2, 3], rules)
        assert exc_info.value.code == "DUPLICATE_NOT_ALLOWED"

    def test_duplicate_allowed_passes(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=True)
        validate_guess([1, 1, 1, 1], rules)  # 例外が出なければOK


class TestGenerateSecretNumber:
    def test_length_matches_digits(self) -> None:
        rules = GameRules(digits=5, allow_duplicate=True)
        secret = generate_secret_number(rules)
        assert len(secret) == 5

    def test_values_within_range(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=True)
        for _ in range(50):
            secret = generate_secret_number(rules)
            assert all(0 <= v <= 9 for v in secret)

    def test_no_duplicate_when_disallowed(self) -> None:
        rules = GameRules(digits=4, allow_duplicate=False)
        for _ in range(50):
            secret = generate_secret_number(rules)
            assert len(set(secret)) == len(secret)

    def test_generated_secret_passes_its_own_validation(self) -> None:
        # 生成した秘密の数字は、同じルールのvalidate_guessを必ず通る
        rules = GameRules(digits=4, allow_duplicate=False)
        secret = generate_secret_number(rules)
        validate_guess(secret, rules)

"""IPごとの試行回数を制限する汎用レート制限。

ルームコードは6文字(紛らわしい文字を除いた32種の英数字)なので
組み合わせは 32^6 ≈ 10億通りあり、これ自体が現実的な時間での
総当たりを困難にしている。このレート制限はそれに加えて、
同一IPからの「ルーム参照/参加の失敗」を短時間に大量発生させる
スキャン的な挙動を早期に遮断するための多層防御(defense in depth)として置く。

room_manager.py と同様、時刻は引数で受け取る純粋なクラスにし、
実際の壁時計はws/api層から渡す。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class RateLimiter:
    max_attempts: int
    window_sec: int
    _history: dict[str, list[datetime]] = field(default_factory=dict)

    def check_and_record(self, key: str, now: datetime) -> bool:
        """試行を1回記録する。制限内なら True、既に上限を超えていれば False。"""

        window_start = now - timedelta(seconds=self.window_sec)
        recent = [t for t in self._history.get(key, []) if t > window_start]

        if len(recent) >= self.max_attempts:
            self._history[key] = recent
            return False

        recent.append(now)
        self._history[key] = recent
        return True

import random


class LotteryState:
    IDLE = "idle"
    READY = "ready"
    DRAWING = "drawing"
    COMPLETED = "completed"


class LotteryEngine:

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._start: int = 0
        self._end: int = 0
        self._available: list[int | str] = []
        self._drawn: list[int | str] = []
        self._current_draw: int = 0
        self._state: str = LotteryState.IDLE
        self._total_numbers: int = 0
        self._mode: str = "numbers"

    def configure(self, start: int, end: int) -> None:
        self.reset()
        self._mode = "numbers"
        self._start = start
        self._end = end
        self._total_numbers = end - start + 1
        self._available = list(range(start, end + 1))
        random.shuffle(self._available)
        self._state = LotteryState.READY

    def configure_names(self, names: list) -> None:
        """Configures the engine for a names raffle from a list of names.

        Names are stored fully uppercase (Unicode-aware, so "José" becomes
        "JOSÉ"), keeping the telão and the history with the same canonical
        look regardless of how the list was typed/imported.
        """
        self.reset()
        self._mode = "names"
        self._start = 1
        self._end = len(names)
        self._total_numbers = len(names)
        self._available = [str(n).upper() for n in names]
        random.shuffle(self._available)
        self._state = LotteryState.READY

    def draw_many(self, count: int) -> list:
        """Draws up to `count` non-repeating items at once."""
        if self._state == LotteryState.IDLE:
            return []

        items = []
        for _ in range(max(count, 1)):
            if not self._available:
                break
            self._state = LotteryState.DRAWING
            items.append(self._available.pop())

        self._drawn.extend(items)
        self._current_draw = len(self._drawn)

        if not self._available:
            self._state = LotteryState.COMPLETED

        return items

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def remaining(self) -> int:
        return len(self._available)

    @property
    def drawn_count(self) -> int:
        return len(self._drawn)

    @property
    def current_draw_number(self) -> int:
        return self._current_draw

    @property
    def drawn_numbers(self) -> list:
        return list(self._drawn)

    @property
    def all_items(self) -> list:
        """All items (numbers or names) configured for the current raffle, in
        their original order."""
        return list(self._available) + list(self._drawn)

    @property
    def start(self) -> int:
        return self._start

    @property
    def end(self) -> int:
        return self._end

    @property
    def state(self) -> str:
        return self._state

    @property
    def total_numbers(self) -> int:
        return self._total_numbers

    def is_completed(self) -> bool:
        return self._state == LotteryState.COMPLETED

    def is_ready(self) -> bool:
        return self._state == LotteryState.READY


from navepro.core.log import get_logger

log = get_logger()

try:
    from screeninfo import get_monitors
    HAS_SCREENINFO = True
except ImportError:
    HAS_SCREENINFO = False


class MonitorInfo:
    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        is_primary: bool,
        index: int,
    ) -> None:
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.is_primary = is_primary
        self.index = index

    def __repr__(self) -> str:
        return (
            f"MonitorInfo(x={self.x}, y={self.y}, "
            f"w={self.width}, h={self.height}, "
            f"primary={self.is_primary}, idx={self.index})"
        )


class MonitorManager:

    def __init__(self) -> None:
        self._monitors: list[MonitorInfo] = []
        self._detect()

    def _detect(self) -> None:
        if not HAS_SCREENINFO:
            log.debug("screeninfo not available. Assuming single monitor.")
            self._monitors = [
                MonitorInfo(0, 0, 1920, 1080, True, 0)
            ]
            return

        try:
            monitors = get_monitors()
            for i, m in enumerate(monitors):
                self._monitors.append(MonitorInfo(
                    x=m.x,
                    y=m.y,
                    width=m.width,
                    height=m.height,
                    is_primary=m.is_primary,
                    index=i,
                ))
        except Exception as e:
            log.warning("Monitor detection error: %s", e)
            self._monitors = [
                MonitorInfo(0, 0, 1920, 1080, True, 0)
            ]

    @property
    def monitors(self) -> list[MonitorInfo]:
        return list(self._monitors)

    @property
    def count(self) -> int:
        return len(self._monitors)

    @property
    def primary(self) -> MonitorInfo | None:
        for m in self._monitors:
            if m.is_primary:
                return m
        return self._monitors[0] if self._monitors else None

    @property
    def secondary(self) -> MonitorInfo | None:
        for m in self._monitors:
            if not m.is_primary:
                return m
        return None

    def get_public_monitor(self, preferred_index: int = 1) -> MonitorInfo | None:
        if preferred_index < len(self._monitors):
            return self._monitors[preferred_index]
        return self.secondary or self.primary

    @property
    def has_multiple_monitors(self) -> bool:
        return len(self._monitors) > 1

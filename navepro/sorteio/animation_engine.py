import math
import random
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from .settings_manager import SettingsManager
from .theme_manager import ThemeManager

WINNER_GOLD = "#FFD700"
WINNER_GOLD_LIGHT = "#FFE66D"
WINNER_GOLD_MID = "#DAA520"
WINNER_GOLD_DARK = "#8B6914"
WINNER_GLOW_SOFT = "#6B5209"
WINNER_GOLD_MAIN = "#FFC72C"


class Particle:

    def __init__(self, x: float, y: float, color: str, size: float = 2.0) -> None:
        self.x = x
        self.y = y
        self.vx = random.uniform(-3, 3)
        self.vy = random.uniform(-5, -1)
        self.size = size
        self.color = color
        self.life = 1.0
        self.decay = random.uniform(0.015, 0.035)
        self.canvas_id: int | None = None

    def update(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.1
        self.life -= self.decay
        return self.life > 0


class AnimationEngine:

    def __init__(
        self,
        canvas: "tk.Canvas",
        settings: SettingsManager | None = None,
        theme: ThemeManager | None = None,
    ) -> None:
        self._canvas = canvas
        self._settings = settings or SettingsManager()
        self._theme = theme or ThemeManager()
        self._particles: list[Particle] = []
        self._animating = False
        self._ambient_active = False
        self._on_complete: Callable | None = None
        self._winning_numbers: list[int] = []
        self._range_min: int = 0
        self._range_max: int = 9999
        self._is_names: bool = False
        self._name_pool: list[str] = []
        self._rolling_names: list[str] = []
        self._after_id: int | None = None
        self._number_font: str = self._resolve_number_font()
        self._measure_font = None
        self._winner_showing = False
        self._base_font_size: int = 72
        self._winner_phase: float = 0.0
        self._rolling_values: list[int] = []
        self._display_font_size: int = 72

    # ── Font helpers ──

    def _resolve_number_font(self) -> str:
        """Resolves the best available font for displaying numbers.

        Prefers the seven-segment "Digital-7" family when installed on the
        system; otherwise falls back to a monospaced font suited for digits.
        """
        try:
            families = {f.lower() for f in tkfont.families(self._canvas)}
        except Exception:
            families = set()

        preferred = [
            "Digital-7",
            "Digital-7 Mono",
            "Digital 7",
            "digital7",
            "DS-Digital",
            "Seven Segment",
        ]
        for candidate in preferred:
            if candidate.lower() in families:
                return candidate

        digital_matches = sorted(
            f for f in families if "digital" in f and "7" in f
        )
        if digital_matches:
            return digital_matches[0]

        monospace_fallbacks = [
            "DejaVu Sans Mono",
            "Consolas",
            "Courier New",
            "Liberation Mono",
            "Courier",
            "monospace",
        ]
        for candidate in monospace_fallbacks:
            if candidate.lower() in families:
                return candidate

        return "Courier"

    # ── Scheduling helpers ──

    def _schedule(self, delay: int, callback: Callable) -> None:
        """Schedules a canvas callback keeping track of its id so it can be
        cancelled later by stop() (prevents stale animations overwriting
        newer ones)."""
        self._after_id = None
        try:
            self._after_id = self._canvas.after(delay, callback)
        except Exception:
            self._after_id = None

    def _random_number(self) -> int:
        """Returns a random number within the configured raffle range, so the
        rolling numbers are always plausible for the current draw."""
        return random.randint(self._range_min, self._range_max)

    def _canvas_size(self) -> tuple[int, int]:
        """Returns the current canvas size in pixels, falling back to a
        reasonable default when the widget is not mapped yet (winfo_width
        returns 1 before the window is shown on screen)."""
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w <= 1:
            w = 1920
        if h <= 1:
            h = 1080
        return w, h

    # ── Number cycling animation ──

    def start_draw_animation(
        self,
        winning_numbers,
        on_complete: Callable | None = None,
        range_min: int = 0,
        range_max: int = 9999,
    ) -> None:
        if isinstance(winning_numbers, int):
            winning_numbers = [winning_numbers]
        self.stop()
        self._animating = True
        self._winning_numbers = list(winning_numbers)
        self._range_min = min(range_min, range_max)
        self._range_max = max(range_min, range_max)
        self._on_complete = on_complete
        self._step = 0
        self._rolling_values = [
            self._random_number() for _ in self._winning_numbers
        ]
        if len(self._winning_numbers) > 1:
            self._display_font_size = self._compute_winner_font_size(
                self._winning_numbers
            )
        else:
            w, h = self._canvas_size()
            self._display_font_size = min(w, h) // 4
        self._canvas.delete("all")
        self._draw_background()
        self._animate_step()

    def start_draw_names(
        self,
        winning_names,
        name_pool: list | None = None,
        on_complete: Callable | None = None,
    ) -> None:
        """Starts the rolling animation for a names raffle.

        Numbers being cycled are replaced by plausible placeholder names
        drawn from `name_pool` (falls back to the winners themselves).
        """
        if isinstance(winning_names, str):
            winning_names = [winning_names]
        self.stop()
        self._animating = True
        self._is_names = True
        self._winning_numbers = list(winning_names)
        self._name_pool = [str(n) for n in (name_pool or winning_names)]
        if not self._name_pool:
            self._name_pool = ["?"]
        self._on_complete = on_complete
        self._step = 0
        self._rolling_names = [
            random.choice(self._name_pool) for _ in self._winning_numbers
        ]
        self._canvas.delete("all")
        self._draw_background()
        self._animate_step()

    def _animate_step(self) -> None:
        if not self._animating:
            return

        duration = self._settings.get("animation", "duration") or 5.0
        initial_speed = self._settings.get("animation", "initial_speed") or 30
        min_speed = self._settings.get("animation", "min_speed") or 200

        self._step += 1
        total_steps = max(int(duration * 30), 1)
        progress = min(self._step / total_steps, 1.0)
        is_final = False
        delay = 60

        if self._is_names:
            self._animate_step_names(progress, initial_speed, min_speed)
            return

        if progress < 0.7:
            self._roll_random_values()
            delay = int(initial_speed * (1 + progress * 3))
        else:
            slow_progress = (progress - 0.7) / 0.3
            ease = slow_progress * slow_progress * (3 - 2 * slow_progress)
            delay = int(initial_speed + (min_speed - initial_speed) * ease)

            if slow_progress < 0.5:
                self._roll_random_values()
            elif slow_progress < 0.85:
                for i, number in enumerate(self._winning_numbers):
                    if random.random() > 0.7:
                        self._rolling_values[i] = number
                    else:
                        self._rolling_values[i] = self._random_number()
            else:
                self._rolling_values = list(self._winning_numbers)
                if slow_progress < 0.95:
                    delay = 300
                else:
                    is_final = True

        self._draw_rolling_values(self._rolling_values, is_final)

        if is_final:
            self._schedule(400, self._on_animation_complete)
        else:
            self._schedule(delay, self._animate_step)

    def _animate_step_names(
        self, progress: float, initial_speed: int, min_speed: int
    ) -> None:
        """Handles one animation step for a names raffle."""
        is_final = False
        delay = 60

        if progress < 0.7:
            self._roll_random_names()
            delay = int(initial_speed * (1 + progress * 3))
        else:
            slow_progress = (progress - 0.7) / 0.3
            ease = slow_progress * slow_progress * (3 - 2 * slow_progress)
            delay = int(initial_speed + (min_speed - initial_speed) * ease)

            if slow_progress < 0.5:
                self._roll_random_names()
            elif slow_progress < 0.85:
                for i, name in enumerate(self._winning_numbers):
                    if random.random() > 0.7:
                        self._rolling_names[i] = str(name)
                    else:
                        self._rolling_names[i] = random.choice(self._name_pool)
            else:
                self._rolling_names = [str(n) for n in self._winning_numbers]
                if slow_progress < 0.95:
                    delay = 300
                else:
                    is_final = True

        self._draw_rolling_names(self._rolling_names, is_final)

        if is_final:
            self._schedule(400, self._on_animation_complete)
        else:
            self._schedule(delay, self._animate_step)

    def _roll_random_names(self) -> None:
        for i in range(len(self._rolling_names)):
            self._rolling_names[i] = random.choice(self._name_pool)

    def _draw_rolling_names(
        self, names: list[str], is_final: bool = False
    ) -> None:
        """Draws the rolling/winner name(s) fitted to the screen."""
        canvas = self._canvas
        w, h = self._canvas_size()

        canvas.delete("number_display")
        canvas.delete("glow")

        names = [str(n) for n in (names or self._winning_numbers or ["?"])]

        if len(names) == 1:
            txt = names[0]
            font_size = self._compute_name_font_size(txt)
            if is_final:
                canvas.create_text(
                    w // 2, h // 2,
                    text=txt,
                    font=(self._number_font, font_size + 12, "normal"),
                    fill=WINNER_GLOW_SOFT,
                    tags="glow",
                )
                canvas.tag_lower("glow")
                self._draw_gold_text(
                    txt, w // 2, h // 2, font_size, "number_display"
                )
            else:
                canvas.create_text(
                    w // 2, h // 2,
                    text=txt,
                    font=(self._number_font, font_size, "normal"),
                    fill=self._theme.public("text"),
                    tags="number_display",
                )
            return

        font_size = self._compute_names_grid_font(names)
        centers = self._names_grid_centers(names, font_size)
        for i, txt in enumerate(names):
            cx, cy = centers[i]
            if is_final:
                self._draw_gold_text(
                    txt, cx, cy, font_size, "number_display"
                )
            else:
                canvas.create_text(
                    cx, cy,
                    text=txt,
                    font=(self._number_font, font_size, "normal"),
                    fill=WINNER_GOLD_MAIN,
                    tags="number_display",
                )

    def _draw_gold_text(
        self, text: str, cx: int, cy: int, font_size: int, tag: str
    ) -> None:
        """Draws the gold text with a clean embossed shadow (names variant)."""
        canvas = self._canvas
        canvas.create_text(
            cx + 5, cy + 7,
            text=text,
            font=(self._number_font, font_size, "normal"),
            fill="#2E2500",
            tags=tag,
        )
        canvas.create_text(
            cx - 3, cy - 3,
            text=text,
            font=(self._number_font, font_size, "normal"),
            fill="#FFF6C9",
            tags=tag,
        )
        canvas.create_text(
            cx, cy,
            text=text,
            font=(self._number_font, font_size, "normal"),
            fill=WINNER_GOLD_MAIN,
            tags=tag,
        )

    def _compute_name_font_size(self, text: str) -> int:
        """Sizes a single name so it fits the screen width."""
        w, _h = self._canvas_size()
        length = max(1, len(str(text)))
        return max(24, int(w * 0.86 / (length * 0.6 + 1.2)))

    def _compute_names_grid_font(self, names: list[str]) -> int:
        """Sizes multiple names in a 2-per-line grid."""
        w, h = self._canvas_size()
        rows = max(1, (len(names) + 1) // 2)
        pairs = [names[i:i + 2] for i in range(0, len(names), 2)]
        max_len = max(sum(len(str(n)) for n in pair) for pair in pairs)
        by_width = w * 0.86 / max(1, max_len * 0.6 + 0.7)
        by_height = h / max(1, rows * 3)
        return max(20, int(min(by_width, by_height)))

    def _names_grid_centers(
        self, names: list[str], font_size: int
    ) -> list[tuple[int, int]]:
        """Like _grid_centers but measuring the textual names."""
        w, h = self._canvas_size()

        try:
            ref = self._get_measure_font()
            widths = [
                int(ref.measure(str(n)) * font_size / 12) for n in names
            ]
        except Exception:
            widths = [int(len(str(n)) * font_size * 0.6) for n in names]

        gap = int(font_size * 0.7)
        rows = (len(names) + 1) // 2
        row_spacing = int(font_size * 1.7)
        start_y = int((h - (rows - 1) * row_spacing) / 2)

        centers: list[tuple[int, int]] = []
        for row in range(rows):
            idx = row * 2
            pair = names[idx:idx + 2]
            y = start_y + row * row_spacing

            if len(pair) == 1:
                centers.append((w // 2, y))
                continue

            total = widths[idx] + widths[idx + 1] + gap
            x = (w - total) // 2
            for offset, _ in enumerate(pair):
                centers.append((x + widths[idx + offset] // 2, y))
                x += widths[idx + offset] + gap

        return centers

    def _roll_random_values(self) -> None:
        for i in range(len(self._rolling_values)):
            self._rolling_values[i] = self._random_number()

    def _draw_rolling_values(
        self, values: list[int], is_final: bool = False
    ) -> None:
        canvas = self._canvas
        w, h = self._canvas_size()

        canvas.delete("number_display")
        canvas.delete("glow")

        numbers = self._winning_numbers or [0]
        font_size = self._display_font_size

        if len(numbers) == 1:
            digits = str(values[0])
            if is_final:
                canvas.create_text(
                    w // 2, h // 2,
                    text=digits,
                    font=(self._number_font, font_size + 12, "normal"),
                    fill=WINNER_GLOW_SOFT,
                    tags="glow",
                )
                canvas.tag_lower("glow")
                self._draw_gold_number(
                    digits, w // 2, h // 2, font_size, "number_display"
                )
            else:
                canvas.create_text(
                    w // 2, h // 2,
                    text=digits,
                    font=(self._number_font, font_size, "normal"),
                    fill=self._theme.public("text"),
                    tags="number_display",
                )
            return

        centers = self._grid_centers(numbers, font_size)
        for i, value in enumerate(values):
            cx, cy = centers[i]
            if is_final:
                self._draw_gold_number(
                    str(value), cx, cy, font_size, "number_display"
                )
            else:
                canvas.create_text(
                    cx, cy,
                    text=str(value),
                    font=(self._number_font, font_size, "normal"),
                    fill=WINNER_GOLD_MAIN,
                    tags="number_display",
                )

    def _draw_gold_number(
        self, digits: str, cx: int, cy: int, font_size: int, tag: str
    ) -> None:
        """Draws the gold number with a clean embossed shadow, avoiding the
        thick blurred glow layers."""
        canvas = self._canvas
        canvas.create_text(
            cx + 5, cy + 7,
            text=digits,
            font=(self._number_font, font_size, "normal"),
            fill="#2E2500",
            tags=tag,
        )
        canvas.create_text(
            cx - 3, cy - 3,
            text=digits,
            font=(self._number_font, font_size, "normal"),
            fill="#FFF6C9",
            tags=tag,
        )
        canvas.create_text(
            cx, cy,
            text=digits,
            font=(self._number_font, font_size, "normal"),
            fill=WINNER_GOLD_MAIN,
            tags=tag,
        )

    def _compute_winner_font_size(self, numbers: list[int]) -> int:
        """Sizes the winning numbers to fit the 2-per-line grid layout."""
        w, h = self._canvas_size()
        rows = max(1, (len(numbers) + 1) // 2)
        pairs = [numbers[i:i + 2] for i in range(0, len(numbers), 2)]
        max_digits = max(sum(len(str(n)) for n in pair) for pair in pairs)
        by_width = w * 0.86 / max(1, max_digits * 0.65 + 0.7)
        by_height = h / max(1, rows * 3)
        return max(24, int(min(by_width, by_height)))

    def _get_measure_font(self):
        """Returns a cached reference font used to measure digit widths."""
        if self._measure_font is None:
            self._measure_font = tkfont.Font(
                root=self._canvas,
                family=self._number_font,
                size=12,
            )
        return self._measure_font

    def _grid_centers(
        self, numbers: list[int], font_size: int
    ) -> list[tuple[int, int]]:
        """Returns the centered (x, y) position of each number in the
        2-per-line grid layout."""
        w, h = self._canvas_size()

        try:
            ref = self._get_measure_font()
            widths = [
                int(ref.measure(str(n)) * font_size / 12) for n in numbers
            ]
        except Exception:
            widths = [int(len(str(n)) * font_size * 0.65) for n in numbers]

        gap = int(font_size * 0.7)
        rows = (len(numbers) + 1) // 2
        row_spacing = int(font_size * 1.7)
        start_y = int((h - (rows - 1) * row_spacing) / 2)

        centers: list[tuple[int, int]] = []
        for row in range(rows):
            idx = row * 2
            pair = numbers[idx:idx + 2]
            y = start_y + row * row_spacing

            if len(pair) == 1:
                centers.append((w // 2, y))
                continue

            total = widths[idx] + widths[idx + 1] + gap
            x = (w - total) // 2
            for offset, _ in enumerate(pair):
                centers.append((x + widths[idx + offset] // 2, y))
                x += widths[idx + offset] + gap

        return centers

    def _draw_numbers_grid(
        self, numbers: list[int], font_size: int
    ) -> None:
        """Draws the gold numbers centered with up to two per line."""
        for number, (cx, cy) in zip(
            numbers, self._grid_centers(numbers, font_size), strict=False
        ):
            self._draw_gold_number(
                str(number), cx, cy, font_size, "winner_number"
            )

    def _draw_background(self) -> None:
        canvas = self._canvas
        w, h = self._canvas_size()
        canvas.create_rectangle(
            0, 0, w, h,
            fill=self._theme.public("bg"),
            outline="",
            tags="bg",
        )

        for _ in range(30):
            x = random.randint(0, w)
            y = random.randint(0, h)
            color = self._theme.public("primary")
            canvas.create_oval(
                x, y, x + 2, y + 2,
                fill=color,
                outline="",
                tags="bg_stars",
            )

    def _on_animation_complete(self) -> None:
        self._animating = False
        try:
            self._show_winner_effect()
        except Exception:
            self._draw_winner_safe()
        if self._on_complete:
            self._on_complete()

    def _show_winner_effect(self) -> None:
        canvas = self._canvas
        w, h = self._canvas_size()

        canvas.delete("all")
        self._draw_background()

        numbers = self._winning_numbers or [0]
        if self._is_names:
            names = [str(n) for n in numbers]
            if len(names) == 1:
                self._base_font_size = self._compute_name_font_size(names[0])
            else:
                self._base_font_size = self._compute_names_grid_font(names)
        else:
            self._base_font_size = self._compute_winner_font_size(numbers)
        self._winner_phase = 0.0
        self._draw_winner_numbers(numbers, self._base_font_size)

        self._spawn_win_particles()
        self._ambient_active = True
        self._winner_showing = True
        self._animate_particles()

    def _draw_winner_numbers(
        self, numbers: list[int], font_size: int
    ) -> None:
        """Draws the winner numbers (single centered or 2-per-line grid)."""
        if self._is_names:
            names = [str(n) for n in numbers]
            if len(names) == 1:
                w, h = self._canvas_size()
                self._draw_gold_text(
                    names[0], w // 2, h // 2, font_size, "winner_number"
                )
            else:
                centers = self._names_grid_centers(names, font_size)
                for name, (cx, cy) in zip(names, centers, strict=False):
                    self._draw_gold_text(
                        name, cx, cy, font_size, "winner_number"
                    )
            return

        if len(numbers) == 1:
            canvas = self._canvas
            w, h = self._canvas_size()
            canvas.create_text(
                w // 2, h // 2,
                text=str(numbers[0]),
                font=(self._number_font, font_size + 18, "normal"),
                fill=WINNER_GLOW_SOFT,
                tags="winner_glow",
            )
            self._draw_gold_number(
                str(numbers[0]), w // 2, h // 2, font_size, "winner_number"
            )
        else:
            self._draw_numbers_grid(numbers, font_size)

    def _draw_pulsing_winner(self) -> None:
        """Redraws the winner numbers with a continuous pulsing scale."""
        canvas = self._canvas
        self._winner_phase += 0.1
        scale = 1.0 + 0.12 * math.sin(self._winner_phase)
        font_size = max(20, int(self._base_font_size * scale))
        canvas.delete("winner_number")
        canvas.delete("winner_glow")
        self._draw_winner_numbers(self._winning_numbers, font_size)

    def _draw_winner_safe(self) -> None:
        """Fallback that always keeps the winning number visible on screen."""
        try:
            canvas = self._canvas
            w, h = self._canvas_size()
            canvas.delete("all")
            self._draw_background()
            numbers = self._winning_numbers or [0]
            if self._is_names:
                names = [str(n) for n in numbers]
                if len(names) == 1:
                    self._draw_gold_text(
                        names[0], w // 2, h // 2,
                        self._compute_name_font_size(names[0]),
                        "winner_number",
                    )
                else:
                    font_size = self._compute_names_grid_font(names)
                    centers = self._names_grid_centers(names, font_size)
                    for name, (cx, cy) in zip(names, centers, strict=False):
                        self._draw_gold_text(
                            name, cx, cy, font_size, "winner_number"
                        )
                return
            self._draw_numbers_grid(
                numbers,
                self._compute_winner_font_size(numbers),
            )
        except Exception:
            pass

    # ── Particle system ──

    def _ambient_colors(self) -> list[str]:
        return [
            self._theme.public("primary"),
            self._theme.public("secondary"),
            self._theme.public("accent"),
            self._theme.public("success"),
        ]

    def _spawn_win_particles(self) -> None:
        """Spawns the luminous burst at the winner reveal."""
        w, h = self._canvas_size()

        colors = self._ambient_colors() + ["#ffffff"]

        for _ in range(60):
            x = w // 2 + random.randint(-w // 3, w // 3)
            y = h // 2 + random.randint(-h // 3, h // 3)
            color = random.choice(colors)
            self._particles.append(Particle(x, y, color, random.uniform(1, 3)))

    def _spawn_ambient_particle(self) -> Particle:
        """Spawns a single ambient particle anywhere on the screen (whole
        telão), keeping a continuous light show of rising dust behind the
        content. Spawns across the full height so the effect is visible on
        the entire public monitor, not only on the bottom."""
        w, h = self._canvas_size()
        x = random.uniform(0, w)
        y = random.uniform(0, h)
        return Particle(
            x, y,
            random.choice(self._ambient_colors()),
            random.uniform(1.2, 3.0),
        )

    def _spawn_firework(self) -> None:
        """Spawns a radial particle burst (fireworks explosion)."""
        w, h = self._canvas_size()
        x = random.uniform(w * 0.12, w * 0.88)
        y = random.uniform(h * 0.15, h * 0.55)
        colors = self._ambient_colors() + ["#ffffff"]
        for _ in range(30):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.5, 5.5)
            particle = Particle(
                x, y,
                random.choice(colors),
                random.uniform(1.5, 2.5),
            )
            particle.vx = math.cos(angle) * speed
            particle.vy = math.sin(angle) * speed
            self._particles.append(particle)

    def _animate_particles(self) -> None:
        canvas = self._canvas
        self._particles = [p for p in self._particles if p.update()]

        if self._ambient_active:
            while len(self._particles) < 100:
                self._particles.append(self._spawn_ambient_particle())

            if self._winner_showing:
                if random.random() < 0.06:
                    self._spawn_firework()
                self._draw_pulsing_winner()

        for p in self._particles:
            canvas.delete(f"p_{id(p)}")
            try:
                r = int(p.color[1:3], 16)
                g = int(p.color[3:5], 16)
                b = int(p.color[5:7], 16)
                color = f"#{r:02x}{g:02x}{b:02x}"
                canvas.create_oval(
                    p.x - p.size, p.y - p.size,
                    p.x + p.size, p.y + p.size,
                    fill=color,
                    outline="",
                    tags=f"p_{id(p)}",
                )
            except ValueError:
                pass

        if self._ambient_active or self._particles:
            self._schedule(30, self._animate_particles)

    def start_ambient(self) -> None:
        """Starts the continuous ambient particle animation (used behind the
        idle screen and behind the winning number)."""
        self._ambient_active = True
        self._animate_particles()

    def stop(self) -> None:
        self._animating = False
        self._ambient_active = False
        self._winner_showing = False
        self._particles.clear()
        if self._after_id is not None:
            try:
                self._canvas.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    @property
    def is_animating(self) -> bool:
        return self._animating

    @property
    def winning_numbers(self) -> list[int]:
        return list(self._winning_numbers)

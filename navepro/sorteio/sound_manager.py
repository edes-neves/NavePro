import math
import os
import random
import struct
import wave
from typing import Any

from navepro.core.log import get_logger

log = get_logger()

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False
    pygame = None

SOUNDS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "sounds"
)


class SoundManager:
    _instance = None

    def __new__(cls) -> "SoundManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._enabled = True
        self._volume = 0.5
        self._sounds: dict[str, Any] = {}
        self._ready = False
        self._init_pygame()
        self._generate_sounds()

    def _init_pygame(self) -> None:
        if not HAS_PYGAME:
            log.debug("pygame not available. Sound disabled.")
            self._ready = False
            return
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=1)
            self._ready = True
        except Exception as e:
            log.warning("Sound init error: %s", e)
            self._ready = False

    def _generate_wav(
        self,
        filepath: str,
        frequency: float,
        duration: float,
        volume: float = 0.5,
        frequency_end: float | None = None,
    ) -> None:
        sample_rate = 44100
        num_samples = int(sample_rate * duration)
        samples = []

        for i in range(num_samples):
            t = i / sample_rate
            progress = i / num_samples
            freq = frequency
            if frequency_end is not None:
                freq = frequency + (frequency_end - frequency) * progress
            value = int(volume * 32767 * 0.3 * (
                0.5 + 0.5 * (1 - progress)
            ) * math.sin(2 * math.pi * freq * t))
            samples.append(value)

        with wave.open(filepath, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for sample in samples:
                wf.writeframes(struct.pack("<h", max(-32768, min(32767, sample))))

    def _generate_firework_wav(self, filepath: str) -> None:
        """Synthesizes a firework sound: low boom + crackling noise."""
        sample_rate = 44100
        num_samples = int(sample_rate * 1.4)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            boom = math.sin(2 * math.pi * 60 * t) * math.exp(-t * 10)
            if t > 0.5:
                boom += 0.5 * math.sin(
                    2 * math.pi * 90 * (t - 0.5)
                ) * math.exp(-(t - 0.5) * 14)
            crackle = 0.0
            if t > 0.15:
                crackle = random.uniform(-1, 1) * (
                    math.exp(-t * 3)
                    + 0.6 * math.exp(-abs(t - 0.8) * 12)
                )
            value = int(32767 * 0.55 * (0.6 * boom + 0.7 * crackle))
            samples.append(max(-32768, min(32767, value)))

        with wave.open(filepath, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for sample in samples:
                wf.writeframes(struct.pack("<h", sample))

    def _load_sound(self, name: str, filepath: str) -> None:
        try:
            self._sounds[name] = pygame.mixer.Sound(filepath)
        except Exception as e:
            log.warning("Sound load error for %s: %s", name, e)

    def _generate_sounds(self) -> None:
        if not self._ready:
            return

        os.makedirs(SOUNDS_DIR, exist_ok=True)
        sound_files = {
            "tick": (800, 0.05, 0.3),
            "tick_fast": (1200, 0.02, 0.2),
            "transition": (300, 0.3, 0.4, 800),
            "click": (1000, 0.05, 0.4),
        }

        for name, params in sound_files.items():
            filepath = os.path.join(SOUNDS_DIR, f"{name}.wav")
            if not os.path.exists(filepath):
                try:
                    self._generate_wav(filepath, *params)
                except Exception as e:
                    log.warning("Sound gen error for %s: %s", name, e)
            if os.path.exists(filepath):
                self._load_sound(name, filepath)

        firework_path = os.path.join(SOUNDS_DIR, "firework.wav")
        if not os.path.exists(firework_path):
            try:
                self._generate_firework_wav(firework_path)
            except Exception as e:
                log.warning("Sound gen error for firework: %s", e)
        if os.path.exists(firework_path):
            self._load_sound("firework", firework_path)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))

    def play(self, name: str) -> None:
        if not self._enabled or not self._ready:
            return
        if name in self._sounds:
            try:
                self._sounds[name].set_volume(self._volume)
                self._sounds[name].play()
            except Exception:
                pass

    def stop_all(self) -> None:
        if not self._ready:
            return
        try:
            pygame.mixer.stop()
        except Exception:
            pass

    def cleanup(self) -> None:
        if not HAS_PYGAME:
            return
        try:
            pygame.mixer.quit()
        except Exception:
            pass

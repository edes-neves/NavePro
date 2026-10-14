import math
import os
import random
import shutil
import struct
import subprocess
import wave
from typing import Any

from navepro.core.ambiente import _ambiente_sem_appimage, _eh_windows
from navepro.core.log import get_logger

log = get_logger()

SOUNDS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "assets", "sounds"
)

# Ordem de preferência no Linux: reprodutores leves primeiro (baixa latência
# para o clique), depois os que o NavePro já exige para vídeo (ffplay/mpv/vlc).
# Cada item é (binário procurado, estilo do comando).
_CANDIDATOS_LINUX: tuple[tuple[str, str], ...] = (
    ("paplay", "paplay"),
    ("aplay", "aplay"),
    ("ffplay", "ffplay"),
    ("mpv", "mpv"),
    ("cvlc", "vlc"),
    ("vlc", "vlc"),
)


def _localizar_binario(nome: str) -> str | None:
    """Caminho de um programa no PATH ou nos diretórios padrão.

    Inclui /run/host/usr/bin, usado pelo Flatpak/AppImage para alcançar os
    programas instalados no sistema hospedeiro.
    """
    caminho = shutil.which(nome)
    if caminho:
        return caminho
    for pasta in ("/run/host/usr/bin", "/usr/bin", "/usr/local/bin"):
        completo = os.path.join(pasta, nome)
        if os.path.exists(completo) and os.access(completo, os.X_OK):
            return completo
    return None


def _montar_comando(estilo: str, exe: str, caminho: str, volume: float) -> list[str]:
    """Comando para tocar um WAV com o reprodutor escolhido."""
    if estilo == "paplay":
        return [exe, f"--volume={int(max(0.0, min(1.0, volume)) * 65536)}", caminho]
    if estilo == "aplay":
        return [exe, "-q", caminho]
    if estilo == "ffplay":
        return [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", caminho]
    if estilo == "mpv":
        return [
            exe, "--no-video", "--really-quiet", "--no-terminal", "--no-config",
            f"--volume={int(max(0.0, min(1.0, volume)) * 100)}", caminho,
        ]
    # vlc/cvlc
    return [exe, "--intf", "dummy", "--play-and-exit", "--quiet", caminho]


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
        self._sounds: dict[str, str] = {}
        self._ready = False
        self._windows = _eh_windows()
        self._exe = ""
        self._estilo = ""
        self._procs: list[Any] = []
        self._init_backend()
        self._generate_sounds()

    def _init_backend(self) -> None:
        """Descobre como tocar os WAV: winsound (Windows) ou um player (Linux)."""
        if self._windows:
            try:
                import winsound  # noqa: F401
                self._ready = True
            except ImportError:
                log.warning("Áudio do sorteio indisponível: winsound ausente.")
                self._ready = False
            return

        for nome, estilo in _CANDIDATOS_LINUX:
            exe = _localizar_binario(nome)
            if exe:
                self._exe = exe
                self._estilo = estilo
                self._ready = True
                log.debug("Áudio do sorteio via %s", exe)
                return

        log.warning(
            "⚠️ Nenhum reprodutor de áudio encontrado (paplay/aplay/ffplay/"
            "mpv/vlc). O sorteio ficará sem som."
        )
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
        self._sounds[name] = filepath

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

    def _limpar_procs(self) -> None:
        """Descarta os processos já terminados (evita acumular zumbis)."""
        self._procs = [p for p in self._procs if p.poll() is None]

    def play(self, name: str) -> None:
        if not self._enabled or not self._ready:
            return
        caminho = self._sounds.get(name)
        if not caminho or not os.path.exists(caminho):
            return

        if self._windows:
            try:
                import winsound
                winsound.PlaySound(
                    caminho,
                    winsound.SND_FILENAME | winsound.SND_ASYNC
                    | winsound.SND_NODEFAULT,
                )
            except Exception as e:
                log.debug("Falha ao tocar som %s: %s", name, e)
            return

        try:
            self._limpar_procs()
            cmd = _montar_comando(self._estilo, self._exe, caminho, self._volume)
            self._procs.append(subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=_ambiente_sem_appimage(),
            ))
        except Exception as e:
            log.debug("Falha ao tocar som %s: %s", name, e)

    def stop_all(self) -> None:
        for proc in self._procs:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        self._procs = []
        if self._windows:
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def cleanup(self) -> None:
        self.stop_all()

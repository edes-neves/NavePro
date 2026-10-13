import csv
import os

from navepro.core.paths import DATA_USER_DIR

BASE_DIR = os.environ.get("RAFFLE_DATA_DIR") or os.path.join(
    DATA_USER_DIR, "sorteio"
)


class HistoryManager:

    def __init__(self, export_path: str | None = None) -> None:
        self._entries: list[dict] = []
        if export_path:
            if not os.path.isabs(export_path):
                export_path = os.path.join(BASE_DIR, export_path)
            self._export_path = export_path
        else:
            self._export_path = os.path.join(BASE_DIR, "exports")

    def _value_label(self) -> str:
        """Returns whether current entries store numbers or names."""
        for entry in self._entries:
            if isinstance(entry.get("numero"), str):
                return "Nome"
        return "Número"

    def add_entry(self, draw_number: int, value) -> None:
        self._entries.append({
            "sorteio": draw_number,
            "numero": value,
        })

    def clear(self) -> None:
        self._entries.clear()

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)

    @property
    def count(self) -> int:
        return len(self._entries)

    def export_csv(self, filepath: str | None = None) -> str:
        if filepath is None:
            os.makedirs(self._export_path, exist_ok=True)
            filepath = os.path.join(
                self._export_path, "historico_sorteio.csv"
            )

        try:
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Sorteio", self._value_label()])
                for entry in self._entries:
                    writer.writerow([entry["sorteio"], entry["numero"]])
            return filepath
        except OSError as e:
            raise RuntimeError(f"Erro ao exportar CSV: {e}") from e

    def export_txt(self, filepath: str | None = None) -> str:
        if filepath is None:
            os.makedirs(self._export_path, exist_ok=True)
            filepath = os.path.join(
                self._export_path, "historico_sorteio.txt"
            )

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("=== HISTÓRICO DE SORTEIOS ===\n")
                f.write(f"Total de sorteios: {len(self._entries)}\n\n")
                for entry in self._entries:
                    f.write(
                        f"Sorteio #{entry['sorteio']}: {entry['numero']}\n"
                    )
            return filepath
        except OSError as e:
            raise RuntimeError(f"Erro ao exportar TXT: {e}") from e

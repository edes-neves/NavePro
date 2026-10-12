"""Worker de busca assíncrona com fila única.

Extraído de NavePro.py sem alterar o comportamento (ver AGENTS.md).
"""
from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from queue import Empty, Queue
from typing import Any

from navepro.core.banco import DatabaseManager
from navepro.core.log import get_logger

log = get_logger("busca")


class SearchWorker:
    """Worker único com fila para processar buscas de forma assíncrona."""

    def __init__(self) -> None:
        self.queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._db = DatabaseManager()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self.queue.get(timeout=0.5)
                if task is None:
                    continue
                term, version, callback = task
                results = self._db.search(term)
                if callback:
                    try:
                        root = tk._default_root
                        if root is not None:
                            # Dispatch via after(0) na thread principal
                            root.after(0, self._dispatch_callback, results, version, callback)
                        elif callback:
                            callback(results, version)
                    except Exception as e:
                        log.exception(f"Erro ao chamar callback: {e}")
                self.queue.task_done()
            except Empty:
                continue
            except Exception as e:
                log.exception(f"Erro no SearchWorker: {e}")

    def _dispatch_callback(
        self,
        results: list[dict[str, Any]],
        version: int,
        callback: Callable[[list[dict[str, Any]], int], None],
    ) -> None:
        """Dispatch seguro do callback na thread principal."""
        try:
            callback(list(results), version)
        except Exception as e:
            log.exception(f"Erro no dispatch: {e}")

    def submit(
        self,
        term: str,
        version: int,
        callback: Callable[[list[dict[str, Any]], int], None],
    ) -> None:
        """Enfileira uma tarefa de busca."""
        self.queue.put((term, version, callback))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

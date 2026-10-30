"""Small base class for background jobs: run_once() every `interval_s` seconds in a daemon thread."""
import logging
import threading


class PeriodicWorker:
    name = "worker"

    def __init__(self, interval_s: float):
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=self.name)
        self.log = logging.getLogger(f"payment.{self.name}")

    def start(self) -> "PeriodicWorker":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> int:
        """One pass; returns how many items were handled."""
        raise NotImplementedError

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # keep the job alive (DB / Redis hiccup)
                self.log.exception("%s pass failed", self.name)
            self._stop.wait(self.interval_s)

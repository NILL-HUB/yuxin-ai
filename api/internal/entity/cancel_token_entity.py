import threading


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

"""Nasłuch EDDN (Elite Dangerous Data Network) — ceny rynków od wszystkich graczy w czasie rzeczywistym.

Relay: tcp://eddn.edcd.io:9500 (ZeroMQ SUB, pusty temat, każdy komunikat skompresowany zlib → JSON).
Bierzemy tylko schemat commodity/3 (bez /test). Wymaga pakietu `pyzmq` — bez niego nasłuch się nie
uruchamia, a aplikacja działa dalej na danych z API.
Źródło formatu: github.com/EDCD/EDDN (docs/Developers.md, schemas/commodity-v3.0.json).
"""

import json
import logging
import threading
import time
import zlib
from typing import Callable, Optional

logger = logging.getLogger(__name__)

RELAY = "tcp://eddn.edcd.io:9500"
COMMODITY_SCHEMA = "https://eddn.edcd.io/schemas/commodity/3"
RECEIVE_TIMEOUT_MS = 60_000   # cisza dłużej niż minutę → ponowne połączenie (relay restartuje się co tydzień)


def parse(raw: bytes) -> Optional[dict]:
    """Surowy komunikat z relay → `message` schematu commodity/3, albo None (inny schemat / test / śmieci)."""
    try:
        data = json.loads(zlib.decompress(raw))
    except (zlib.error, ValueError):
        return None
    if data.get("$schemaRef", "").rstrip("#") != COMMODITY_SCHEMA:
        return None
    message = data.get("message")
    return message if isinstance(message, dict) else None


class EDDNListener:
    def __init__(self, store, url: str = RELAY, on_market: Optional[Callable[[dict], None]] = None):
        self.store = store
        self.url = url
        self.on_market = on_market
        self._stop = threading.Event()
        self.connected = False

    @staticmethod
    def available() -> bool:
        try:
            import zmq  # noqa: F401
        except ImportError:
            return False
        return True

    def start(self) -> bool:
        if not self.available():
            logger.info("EDDN wyłączony: brak pakietu pyzmq (pip install pyzmq)")
            return False
        threading.Thread(target=self._run, name="eddn", daemon=True).start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import zmq
        ctx = zmq.Context.instance()
        while not self._stop.is_set():
            sock = ctx.socket(zmq.SUB)
            sock.setsockopt(zmq.SUBSCRIBE, b"")
            sock.setsockopt(zmq.RCVTIMEO, RECEIVE_TIMEOUT_MS)
            sock.setsockopt(zmq.LINGER, 0)
            try:
                sock.connect(self.url)
                logger.info("EDDN: nasłuch %s", self.url)
                while not self._stop.is_set():
                    try:
                        raw = sock.recv()
                    except zmq.Again:
                        logger.info("EDDN: brak danych od %d s — łączę ponownie", RECEIVE_TIMEOUT_MS // 1000)
                        break
                    self.connected = True
                    message = parse(raw)
                    if message is None:
                        continue
                    try:
                        if self.store.upsert_market(message) and self.on_market:
                            self.on_market(message)
                    except Exception:
                        logger.exception("EDDN: zapis rynku")
            except zmq.ZMQError as e:
                logger.warning("EDDN: błąd połączenia (%s) — ponowię za 30 s", e)
                self._stop.wait(30)
            finally:
                self.connected = False
                sock.close()

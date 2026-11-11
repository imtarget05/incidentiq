"""IncidentIQ — Cloudflare Queues consumer worker for ETL jobs.

Deployed as a separate Worker (wrangler.etl.toml) and attached to `etl-queue`
as a push-based consumer. It shares the D1, Vectorize, and Workers AI bindings
with the API worker, so messages produced by the API can be processed
asynchronously when ETL_MODE=queue (or after an inline ETL failure).

Circuit-breaker: if Workers AI is unavailable (embedding failures exceed
CIRCUIT_OPEN_THRESHOLD per batch), the consumer switches to a half-open
state and skips embedding for the remainder of the batch, letting the queue
platform retry later via its built-in retry/DLQ mechanism.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Optional

from workers import WorkerEntrypoint

from etl import handle_queue_message

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Simple in-memory circuit breaker for Workers AI embedding calls.
# State resets on each fresh Worker invocation (cold start), which is
# acceptable because the queue retry window is longer than the typical
# cold-start interval.
# ---------------------------------------------------------------------------
_CB_FAILURE_COUNT: int = 0
_CB_OPEN_AT: float = 0.0
_CB_HALF_OPEN_TIMEOUT: float = 60.0  # seconds before allowing a probe request
CIRCUIT_OPEN_THRESHOLD: int = 3       # consecutive failures to open the circuit


def _cb_record_failure() -> None:
    global _CB_FAILURE_COUNT, _CB_OPEN_AT
    _CB_FAILURE_COUNT += 1
    if _CB_FAILURE_COUNT >= CIRCUIT_OPEN_THRESHOLD:
        _CB_OPEN_AT = time.time()
        logger.warning("etl.circuit_breaker.open failures=%d", _CB_FAILURE_COUNT)


def _cb_record_success() -> None:
    global _CB_FAILURE_COUNT, _CB_OPEN_AT
    _CB_FAILURE_COUNT = 0
    _CB_OPEN_AT = 0.0


def _cb_is_open() -> bool:
    if _CB_FAILURE_COUNT < CIRCUIT_OPEN_THRESHOLD:
        return False
    if time.time() - _CB_OPEN_AT >= _CB_HALF_OPEN_TIMEOUT:
        logger.info("etl.circuit_breaker.half_open — allowing probe request")
        return False
    return True


class Default(WorkerEntrypoint):
    async def queue(self, batch: Any, env: Optional[Any] = None,
                    ctx: Optional[Any] = None) -> None:
        runtime_env = env if env is not None else self.env
        if _cb_is_open():
            logger.warning(
                "etl.circuit_breaker.batch_skipped messages=%d — Workers AI circuit open",
                len(batch.messages),
            )
            # Leave messages unacked so the queue retries them when the circuit closes.
            for message in batch.messages:
                try:
                    retried = message.retry()
                    if inspect.isawaitable(retried):
                        await retried
                except Exception:
                    pass
            return

        for message in batch.messages:
            try:
                await handle_queue_message(runtime_env, message)
                _cb_record_success()
            except Exception as exc:
                logger.error("etl.consumer.error: %s", exc)
                _cb_record_failure()
                try:
                    retried = message.retry()
                    if inspect.isawaitable(retried):
                        await retried
                except Exception:
                    pass

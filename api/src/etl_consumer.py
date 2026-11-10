"""IncidentIQ — Cloudflare Queues consumer worker for ETL jobs.

Deployed as a separate Worker (wrangler.etl.toml) and attached to `etl-queue`
as a push-based consumer. It shares the D1, Vectorize, and Workers AI bindings
with the API worker, so messages produced by the API can be processed
asynchronously when ETL_MODE=queue (or after an inline ETL failure).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

from workers import WorkerEntrypoint

from etl import handle_queue_message

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class Default(WorkerEntrypoint):
    async def queue(self, batch: Any, env: Optional[Any] = None,
                    ctx: Optional[Any] = None) -> None:
        runtime_env = env if env is not None else self.env
        for message in batch.messages:
            try:
                await handle_queue_message(runtime_env, message)
            except Exception as exc:
                logger.error("etl.consumer.error: %s", exc)
                try:
                    retried = message.retry()
                    if inspect.isawaitable(retried):
                        await retried
                except Exception:
                    pass

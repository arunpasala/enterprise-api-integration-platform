"""Run separately: python -m app.worker. Single worker demo, not distributed-safe."""
import asyncio
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select
from .config import settings
from .db import Base, engine, SessionLocal
from .models import Outbox

async def process_once(client: httpx.AsyncClient | None = None):
    Base.metadata.create_all(engine)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=5)
    try:
        with SessionLocal() as db:
            now = datetime.now(timezone.utc)
            # SQLite may return naive datetime; this demo stores UTC consistently.
            pending = db.scalars(select(Outbox).where(Outbox.status.in_(['pending', 'retrying'])).order_by(Outbox.id).limit(25)).all()
            for job in pending:
                due = job.next_attempt_at.replace(tzinfo=timezone.utc) if job.next_attempt_at.tzinfo is None else job.next_attempt_at
                if due > now:
                    continue
                try:
                    response = await client.post(settings.partner_url, content=job.payload, headers={'Content-Type': 'application/json'})
                    response.raise_for_status()
                    job.status = 'delivered'
                    job.last_error = None
                except (httpx.HTTPError, ValueError) as exc:
                    job.attempts += 1
                    job.last_error = str(exc)[:500]
                    if job.attempts >= settings.max_attempts:
                        job.status = 'failed'
                    else:
                        job.status = 'retrying'
                        job.next_attempt_at = now + timedelta(seconds=min(2 ** job.attempts, 60))
                db.commit()
    finally:
        if own_client:
            await client.aclose()

async def main():
    print('Worker started; press Ctrl+C to stop')
    while True:
        await process_once()
        await asyncio.sleep(settings.worker_interval_seconds)

if __name__ == '__main__':
    asyncio.run(main())

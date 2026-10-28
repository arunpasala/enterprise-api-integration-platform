import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .config import settings
from .db import Base, engine, get_db
from .models import Customer, Outbox, IdempotencyRecord, WebhookEvent, PartnerReceipt
from datetime import datetime, timezone


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield

app = FastAPI(title='Enterprise API Integration Platform', version='1.0.0', lifespan=lifespan)

class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)

class CustomerOut(CustomerIn):
    id: int
    sync_status: str


def authenticate(x_api_key: str | None = Header(default=None)):
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail='Invalid API key')

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/api/customers', response_model=CustomerOut, status_code=201, dependencies=[Depends(authenticate)])
def create_customer(body: CustomerIn, db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)):
    if not idempotency_key or len(idempotency_key) > 255:
        raise HTTPException(400, 'Provide Idempotency-Key header (max 255 chars)')
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == idempotency_key))
    if previous:
        if previous.request_hash != digest:
            raise HTTPException(409, 'Idempotency key reused with different payload')
        customer = db.get(Customer, previous.customer_id)
        outbox = db.scalar(select(Outbox).where(Outbox.customer_id == customer.id))
        return CustomerOut(id=customer.id, name=customer.name, email=customer.email, sync_status=outbox.status)
    customer = Customer(name=body.name, email=body.email)
    db.add(customer)
    db.flush()
    payload = json.dumps({'event_id': f'customer-created-{customer.id}', 'customer': {'id': customer.id, 'name': customer.name, 'email': customer.email}})
    db.add(Outbox(customer_id=customer.id, payload=payload))
    db.add(IdempotencyRecord(key=idempotency_key, request_hash=digest, customer_id=customer.id))
    db.commit()
    return CustomerOut(id=customer.id, name=customer.name, email=customer.email, sync_status='pending')

@app.get('/api/customers/{customer_id}', response_model=CustomerOut, dependencies=[Depends(authenticate)])
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(404, 'Customer not found')
    outbox = db.scalar(select(Outbox).where(Outbox.customer_id == customer_id))
    return CustomerOut(id=customer.id, name=customer.name, email=customer.email, sync_status=outbox.status)

@app.get('/api/integrations', dependencies=[Depends(authenticate)])
def integrations(db: Session = Depends(get_db)):
    rows = db.scalars(select(Outbox).order_by(Outbox.id.desc()).limit(100)).all()
    return [{'id': r.id, 'customer_id': r.customer_id, 'status': r.status, 'attempts': r.attempts, 'last_error': r.last_error} for r in rows]

@app.get('/api/metrics', dependencies=[Depends(authenticate)])
def metrics(db: Session = Depends(get_db)):
    rows = db.execute(select(Outbox.status, func.count()).group_by(Outbox.status)).all()
    return dict(rows)

@app.post('/api/webhooks/partner', dependencies=[Depends(authenticate)])
async def incoming_webhook(request: Request, x_webhook_signature: str | None = Header(default=None), db: Session = Depends(get_db)):
    raw = await request.body()
    expected = hmac.new(settings.webhook_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not x_webhook_signature or not hmac.compare_digest(x_webhook_signature, expected):
        raise HTTPException(401, 'Invalid webhook signature')
    try:
        event = json.loads(raw)
        event_id = event['event_id']
        if not isinstance(event_id, str) or not event_id or len(event_id) > 255:
            raise ValueError('Invalid event_id')
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422, 'Valid JSON with event_id required')
    if db.get(WebhookEvent, event_id):
        return {'status': 'duplicate', 'event_id': event_id}
    db.add(WebhookEvent(event_id=event_id, payload=raw.decode()))
    db.commit()
    return {'status': 'accepted', 'event_id': event_id}

@app.post('/mock-partner/customers')
async def mock_partner(request: Request, db: Session = Depends(get_db)):
    """Local demo destination; NOT a production partner endpoint."""
    event = await request.json()
    event_id = event.get('event_id')
    if not event_id:
        raise HTTPException(422, 'event_id required')
    if db.get(PartnerReceipt, event_id):
        return {'status': 'already_received'}
    db.add(PartnerReceipt(event_id=event_id))
    db.commit()
    return {'status': 'received'}

@app.post(
    '/api/integrations/{customer_id}/retry',
    dependencies=[Depends(authenticate)]
)
def retry_integration(
    customer_id: int,
    db: Session = Depends(get_db)
):
    # Verify that the customer exists.
    customer = db.get(Customer, customer_id)

    if customer is None:
        raise HTTPException(
            status_code=404,
            detail='Customer not found'
        )

    # Find the customer's integration job.
    outbox = db.scalar(
        select(Outbox).where(
            Outbox.customer_id == customer_id
        )
    )

    if outbox is None:
        raise HTTPException(
            status_code=404,
            detail='Integration job not found'
        )

    # Only failed jobs can be manually retried.
    if outbox.status != 'failed':
        raise HTTPException(
            status_code=409,
            detail=f'Cannot retry integration with status: {outbox.status}'
        )

    # Reset the integration for background processing.
    outbox.status = 'pending'
    outbox.attempts = 0
    outbox.last_error = None
    outbox.next_attempt_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(outbox)

    return {
        'message': 'Integration queued for retry',
        'customer_id': customer_id,
        'integration_id': outbox.id,
        'status': outbox.status,
        'attempts': outbox.attempts
    }
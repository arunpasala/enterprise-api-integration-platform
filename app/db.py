from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

kwargs = {'connect_args': {'check_same_thread': False}} if settings.database_url.startswith('sqlite') else {}
engine = create_engine(settings.database_url, **kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as db:
        yield db

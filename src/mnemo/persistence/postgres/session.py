"""Engine and session construction for the synchronous PostgreSQL adapter."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_postgres_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a synchronous SQLAlchemy engine for a psycopg PostgreSQL URL."""
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions used by repositories for one transaction per mutation."""
    return sessionmaker(bind=engine, expire_on_commit=False)

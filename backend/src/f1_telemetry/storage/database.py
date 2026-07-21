"""Database engine and unit-of-work helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from f1_telemetry.core.config import Settings


def create_database_engine(
    database_url: str,
    *,
    echo: bool = False,
) -> Engine:
    """Create a synchronous SQLAlchemy engine for API or worker use."""
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions that keep loaded state after transaction commits."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def database_session(settings: Settings) -> Iterator[Session]:
    """Yield and close a short-lived database session."""
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            yield session
    finally:
        engine.dispose()

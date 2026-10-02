import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.db import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    from app import models  # noqa: F401
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def client(db, monkeypatch):
    from app.web import main
    monkeypatch.setattr(main, "init_db", lambda: None)  # lifespan uses module global
    main.app.dependency_overrides[main.get_db] = lambda: db
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()

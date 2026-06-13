from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from backend.app.config import settings

# For SQLite fallback or other development needs, check if postgresql is used.
# But we'll standardise on asyncpg as defined in config.
db_url = settings.DATABASE_URL

engine = create_async_engine(
    db_url,
    echo=False,
    future=True,
    pool_size=20,
    max_overflow=10
) if "postgresql" in db_url else create_async_engine(
    db_url,
    echo=False,
    future=True
)

_SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

def SessionLocal():
    return _SessionLocal()

class Base(DeclarativeBase):
    pass

async def init_db():
    global engine, _SessionLocal
    try:
        # Test connection by running metadata creation
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Database initialized successfully (using primary engine).")
    except Exception as e:
        print(f"Primary database connection failed: {e}. Reverting to local SQLite (aiosqlite)...")
        # Recreate engine and sessionmaker with SQLite
        import os
        PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        sqlite_url = f"sqlite+aiosqlite:///{os.path.join(PROJECT_ROOT, 'aura_db.sqlite')}"
        engine = create_async_engine(
            sqlite_url,
            echo=False,
            future=True
        )
        _SessionLocal = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Local SQLite database initialized successfully.")

async def get_db():
    # Refers to global SessionLocal function which delegates to current _SessionLocal
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

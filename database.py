# database.py - Database configuration and session management

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# SQLite database URL - creates quiz.db in current directory
DATABASE_URL = "sqlite:///./quiz.db"

# Create the SQLAlchemy engine
# connect_args is needed for SQLite to allow multi-threaded access
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# Session factory - each request gets its own session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all ORM models
Base = declarative_base()


def get_db():
    """
    Dependency that provides a database session per request.
    Automatically closes the session when done.
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

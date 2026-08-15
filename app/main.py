from contextlib import asynccontextmanager
from datetime import date
import os
import time
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, Date, String, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/birthdays"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    username = Column(String, primary_key=True, index=True)
    date_of_birth = Column(Date, nullable=False)


def init_db(max_retries: int = 30, delay_seconds: float = 2.0) -> None:
    for attempt in range(max_retries):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class BirthdayPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    date_of_birth: date = Field(
        ...,
        validation_alias=AliasChoices("dateOfBirth", "dateOfBrith"),
        serialization_alias="dateOfBirth",
    )

    @field_validator("date_of_birth")
    @classmethod
    def validate_past_date(cls, value: date) -> date:
        if value >= date.today():
            raise ValueError("Date of birth must be a date before today.")
        return value


app = FastAPI(title="Chronos Birthday API", version="1.0.0", lifespan=lifespan)


def calculate_days_until_birthday(dob: date, today: date) -> int:
    try:
        next_bday = dob.replace(year=today.year)
    except ValueError:
        next_bday = date(today.year, 3, 1)

    if next_bday < today:
        try:
            next_bday = dob.replace(year=today.year + 1)
        except ValueError:
            next_bday = date(today.year + 1, 3, 1)

    return (next_bday - today).days


@app.put("/hello/{username}", status_code=status.HTTP_204_NO_CONTENT)
def save_user_birthday(
    username: str,
    payload: BirthdayPayload,
    db: Session = Depends(get_db),
) -> None:
    if not (username.isascii() and username.isalpha()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must contain letters only.",
        )

    stmt = (
        insert(User)
        .values(username=username, date_of_birth=payload.date_of_birth)
        .on_conflict_do_update(
            index_elements=[User.username],
            set_={"date_of_birth": payload.date_of_birth},
        )
    )
    db.execute(stmt)
    db.commit()
    return None


@app.get("/hello/{username}", status_code=status.HTTP_200_OK)
def get_user_birthday(
    username: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not (username.isascii() and username.isalpha()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must contain letters only.",
        )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' was not found.",
        )

    days = calculate_days_until_birthday(user.date_of_birth, date.today())
    if days == 0:
        return {"message": f"Hello, {username}! Happy birthday!"}

    unit = "day" if days == 1 else "days"
    return {"message": f"Hello, {username}! Your birthday is in {days} {unit}"}


@app.get("/healthz", status_code=status.HTTP_200_OK)
def health_check() -> dict[str, str]:
    return {"status": "ok"}

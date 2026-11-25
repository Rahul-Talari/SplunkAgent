"""Database: chats, messages, feedback and eval runs.

SQLite by default. For Postgres set DATABASE_URL, e.g.
postgresql+psycopg://user:pass@localhost/splunk_agent  (needs: uv sync --extra postgres)
"""

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, ForeignKey, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: uuid.uuid4().hex)
    title: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)
    messages: Mapped[list["Message"]] = relationship(cascade="all, delete-orphan", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"))
    role: Mapped[str]  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    model: Mapped[str | None]
    latency_ms: Mapped[int | None]
    tokens: Mapped[int | None]
    rating: Mapped[int | None]  # +1 thumbs up, -1 thumbs down
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    model: Mapped[str]
    web_search: Mapped[bool]
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list["EvalResult"]] = relationship(cascade="all, delete-orphan", order_by="EvalResult.id")


class EvalResult(Base):
    __tablename__ = "eval_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"))
    case_id: Mapped[str]
    passed: Mapped[bool]
    scores: Mapped[dict] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    latency_ms: Mapped[int]


class Store:
    def __init__(self, url: str):
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url)
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        # expire_on_commit=False: objects stay readable after the session closes.
        return Session(self.engine, expire_on_commit=False)

    # ---- chats ----
    def create_chat(self, title: str) -> Chat:
        with self.session() as s:
            chat = Chat(title=title)
            s.add(chat)
            s.commit()
            return chat

    def list_chats(self) -> list[Chat]:
        with self.session() as s:
            return list(s.scalars(select(Chat).order_by(Chat.updated_at.desc())))

    def delete_chat(self, chat_id: str) -> None:
        with self.session() as s:
            if chat := s.get(Chat, chat_id):
                s.delete(chat)
                s.commit()

    # ---- messages ----
    def add_message(self, chat_id: str, role: str, content: str, **fields) -> Message:
        with self.session() as s:
            message = Message(chat_id=chat_id, role=role, content=content, **fields)
            s.add(message)
            s.get(Chat, chat_id).updated_at = datetime.now()
            s.commit()
            return message

    def get_messages(self, chat_id: str) -> list[Message]:
        with self.session() as s:
            return list(s.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.id)))

    def set_rating(self, message_id: int, rating: int) -> None:
        with self.session() as s:
            s.get(Message, message_id).rating = rating
            s.commit()

    def feedback_counts(self) -> dict:
        with self.session() as s:
            def count(*conditions):
                return s.scalar(select(func.count()).select_from(Message).where(*conditions))

            return {
                "answers": count(Message.role == "assistant"),
                "thumbs_up": count(Message.rating == 1),
                "thumbs_down": count(Message.rating == -1),
            }

    # ---- evals ----
    def save_eval_run(self, run: EvalRun) -> EvalRun:
        with self.session() as s:
            s.add(run)
            s.commit()
            return run

    def list_eval_runs(self) -> list[EvalRun]:
        with self.session() as s:
            return list(s.scalars(select(EvalRun).order_by(EvalRun.id.desc())))

    def get_eval_results(self, run_id: int) -> list[EvalResult]:
        with self.session() as s:
            return list(s.scalars(select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.id)))

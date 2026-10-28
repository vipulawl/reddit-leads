from datetime import datetime, timezone

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    projects: Mapped[list["Project"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    icp: Mapped[str] = mapped_column(Text, default="")
    pain_points: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    negative_keywords: Mapped[list] = mapped_column(JSON, default=list)
    subreddits: Mapped[list] = mapped_column(JSON, default=list)
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.55)
    min_score: Mapped[int] = mapped_column(Integer, default=60)
    profile_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[User] = relationship(back_populates="projects")

    def profile_text(self) -> str:
        return "\n".join([self.name, self.description, self.icp, *self.pain_points])


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("project_id", "reddit_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    reddit_id: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(10))
    subreddit: Mapped[str] = mapped_column(String(100))
    author: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    permalink: Mapped[str] = mapped_column(String(500))
    matched_keywords: Mapped[list] = mapped_column(JSON, default=list)
    similarity: Mapped[float] = mapped_column(Float)
    intent_level: Mapped[float] = mapped_column(Float)
    vendor_prob: Mapped[float] = mapped_column(Float)
    score: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="new")
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

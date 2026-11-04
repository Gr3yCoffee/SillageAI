from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    preference_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Perfume(Base):
    __tablename__ = 'perfumes'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(160))
    brand: Mapped[str] = mapped_column(String(160), default='')
    family: Mapped[str] = mapped_column(String(100), default='')
    secondary_family: Mapped[str] = mapped_column(String(100), default='')
    character: Mapped[str] = mapped_column(String(500), default='')
    notes: Mapped[list] = mapped_column(JSON, default=list)
    longevity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    projection: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    season: Mapped[list] = mapped_column(JSON, default=list)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str] = mapped_column(String(40), default='')
    concentration: Mapped[str] = mapped_column(String(80), default='')
    description: Mapped[str] = mapped_column(Text, default='')
    source_url: Mapped[str] = mapped_column(String(500), default='')
    wear_times: Mapped[list] = mapped_column(JSON, default=list)
    catalog_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feedback_score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Profile(Base):
    __tablename__ = 'profiles'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

class Usage(Base):
    __tablename__ = 'ai_usage'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    feature: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

class Cache(Base):
    __tablename__ = 'recommendation_cache'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class Feedback(Base):
    __tablename__ = 'feedback'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    perfume_id: Mapped[int] = mapped_column(ForeignKey('perfumes.id', ondelete='CASCADE'))
    score: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(500), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class FragellaUsage(Base):
    __tablename__ = 'fragella_usage'
    id: Mapped[int] = mapped_column(primary_key=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

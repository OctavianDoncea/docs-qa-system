from datetime import datetime
from sqlalchemy import Integer, Text, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.database import Base

class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(Integer, primary_ket=True)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    chunks: Mapped[list['Chunk']] = relationship('Chunk', back_populates='repo', cascade='all, delete-orphan')


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(Integer, ForeignKey('repos.id', ondelete='CASCADE'), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(768))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    repo: Mapped['Repo'] = relationship('Repo', back_populates='chunks')
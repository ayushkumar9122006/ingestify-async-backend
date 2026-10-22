import datetime
import uuid
from sqlalchemy import Column, String, BigInteger, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.enums import JobStatus


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False, default=0)
    mime_type = Column(String(100), nullable=False, index=True)
    status = Column(String(50), nullable=False, default=JobStatus.PENDING.value, index=True)
    celery_task_id = Column(String(255), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    processing_time_ms = Column(Float, nullable=True, default=0.0)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="jobs")
    artifact = relationship("ExtractedArtifact", back_populates="job", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id} status={self.status} filename={self.filename}>"

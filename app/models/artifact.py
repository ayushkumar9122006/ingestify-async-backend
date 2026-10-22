import datetime
import uuid
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


class ExtractedArtifact(Base):
    __tablename__ = "extracted_artifacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("ingestion_jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    summary_text = Column(Text, nullable=True)
    word_count = Column(Integer, nullable=False, default=0)
    metadata_json = Column(JSON, nullable=True)
    thumbnail_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, nullable=False)

    # Relationships
    job = relationship("IngestionJob", back_populates="artifact")

    def __repr__(self) -> str:
        return f"<ExtractedArtifact id={self.id} job_id={self.job_id} word_count={self.word_count}>"

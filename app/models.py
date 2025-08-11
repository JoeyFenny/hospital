from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    Index,
    UniqueConstraint,
    Numeric,
)
from sqlalchemy.orm import relationship
from .database import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    city = Column(String(128), nullable=True)
    state = Column(String(8), nullable=True, index=True)
    zip_code = Column(String(16), nullable=True, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    procedures = relationship("Procedure", back_populates="provider", cascade="all, delete-orphan")
    ratings = relationship("Rating", back_populates="provider", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_providers_zip", "zip_code"),
    )


class Procedure(Base):
    __tablename__ = "procedures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # FK uses provider_id external id to simplify ETL joins across CSV
    provider_id = Column(String(32), ForeignKey("providers.provider_id", ondelete="CASCADE"), nullable=False, index=True)
    ms_drg_definition = Column(String(255), nullable=False, index=True)
    total_discharges = Column(Integer, nullable=True)
    average_covered_charges = Column(Numeric(14, 2), nullable=True)
    average_total_payments = Column(Numeric(14, 2), nullable=True)
    average_medicare_payments = Column(Numeric(14, 2), nullable=True)

    provider = relationship("Provider", back_populates="procedures", lazy="joined")

    __table_args__ = (
        Index("idx_procedures_drg", "ms_drg_definition"),
        UniqueConstraint("provider_id", "ms_drg_definition", name="uq_procedure_per_provider_drg"),
    )


class Rating(Base):
    __tablename__ = "ratings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(32), ForeignKey("providers.provider_id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)

    provider = relationship("Provider", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("provider_id", name="uq_rating_per_provider"),
    )


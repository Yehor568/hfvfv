from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Product(Base):
    """A product we sell. `code` is the id used in campaign names and LP-CRM, e.g. 'id72'."""

    __tablename__ = "products"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | testing | paused
    crm_aliases: Mapped[str] = mapped_column(Text, default="")  # comma-separated product names in LP-CRM
    test_started: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class AdStat(Base):
    """Meta Ads campaign stats per day (or a seeded aggregate when source='seed')."""

    __tablename__ = "ad_stats"
    __table_args__ = (UniqueConstraint("day", "campaign_id", name="uq_adstat_day_campaign"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    ad_account_id: Mapped[str] = mapped_column(String(32), index=True)
    campaign_id: Mapped[str] = mapped_column(String(32))
    campaign_name: Mapped[str] = mapped_column(String(300))
    product_code: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    spend: Mapped[float] = mapped_column(Float, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(16), default="api")


class AudienceStat(Base):
    __tablename__ = "audience_stats"
    __table_args__ = (UniqueConstraint("ad_account_id", "period", "age", "gender", name="uq_audience"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ad_account_id: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(32))  # e.g. "last_90d"
    age: Mapped[str] = mapped_column(String(16))
    gender: Mapped[str] = mapped_column(String(16))
    spend: Mapped[float] = mapped_column(Float, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)


class CrmOrder(Base):
    __tablename__ = "crm_orders"
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    product_code: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    product_name: Mapped[str] = mapped_column(String(300), default="")
    status_raw: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    # new | approved | shipped | bought | returned | cancelled | unknown


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    query_en: Mapped[str] = mapped_column(String(200), default="")  # search phrase for US/EU sources
    category: Mapped[str] = mapped_column(String(100), default="")
    trend: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ad_proof: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ua_saturation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_economics: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audience_fit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    similarity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_penalty: Mapped[int] = mapped_column(Integer, default=0)
    expected_cpl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchase_price_uah: Mapped[float | None] = mapped_column(Float, nullable=True)
    sale_price_uah: Mapped[float | None] = mapped_column(Float, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    library_checks: Mapped[list["AdLibraryCheck"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="AdLibraryCheck.checked_at.desc()"
    )


class AdLibraryCheck(Base):
    __tablename__ = "ad_library_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    country: Mapped[str] = mapped_column(String(8))
    query: Mapped[str] = mapped_column(String(200))
    active_ads: Mapped[int] = mapped_column(Integer, default=0)
    long_running_ads: Mapped[int] = mapped_column(Integer, default=0)
    advertisers: Mapped[int] = mapped_column(Integer, default=0)
    sample_titles: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    candidate: Mapped[Candidate] = relationship(back_populates="library_checks")

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BaseModel(DeclarativeBase):
    pass


class MoexTradingResult(BaseModel):
    __tablename__ = 'moex_trading_results'
    __table_args__ = (
        UniqueConstraint('date', 'board_id', 'exchange_product_id',
                         name='uq_moex_date_board_product'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange_product_id: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange_product_name: Mapped[str] = mapped_column(String(500))
    board_id: Mapped[str] = mapped_column(String(20), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    total: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    count: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    created_on: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_on: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
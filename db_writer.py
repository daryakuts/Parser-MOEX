import logging
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS
from sqlalchemy import create_engine, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from modele_table import BaseModel, MoexTradingResult

logger = logging.getLogger(__name__)

DB_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)
engine = create_engine(DB_URL)


def init_db() -> None:
    BaseModel.metadata.create_all(engine)


def save_to_db(rows: list[MoexTradingResult]) -> int:

    if not rows:
        return 0

    values = [
        {
            "exchange_product_id": r.exchange_product_id,
            "exchange_product_name": r.exchange_product_name,
            "board_id": r.board_id,
            "volume": r.volume,
            "total": r.total,
            "count": r.count,
            "date": r.date,
        }
        for r in rows
    ]

    stmt = insert(MoexTradingResult).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_moex_date_board_product",
        set_={
            "exchange_product_name": stmt.excluded.exchange_product_name,
            "volume": stmt.excluded.volume,
            "total": stmt.excluded.total,
            "count": stmt.excluded.count,
            "updated_on": func.now(),
        },
    )

    with Session(engine) as session:
        session.execute(stmt)
        session.commit()

    return len(rows)
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import requests

from db_writer import init_db, save_to_db
from modele_table import MoexTradingResult



DATA_START = date(2023, 1, 1)
DATA_END = date.today() - timedelta(days=1)

DEFAULT_PAGE_SIZE = 100
PAGE_FETCH_RETRIES = 3
PAGE_FETCH_BACKOFF = 1.0

ISS_URL = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares/"
    "boards/TQBR/securities.xml"
)
BOARD_ID = "TQBR"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradingResult:
    exchange_product_id: str
    exchange_product_name: str
    board_id: str
    volume: Decimal
    total: Decimal
    count: int
    date: date


class Parser:
    def __init__(self, data_start: date, data_end: date, link: str) -> None:
        self.data_start = data_start
        self.data_end = data_end
        self.link = link

    def open_link(self, link: str, parametr: dict | None = None):
        try:
            response = requests.get(link, params=parametr, timeout=30)
        except requests.exceptions.RequestException as e:
            logger.error("Ошибка сети при запросе %s: %s", link, e)
            return None
        if response.status_code != 200:
            logger.error(
                "HTTP %s при запросе %s. Ответ: %r",
                response.status_code, link, response.text[:200],
            )
            return None
        return response

    def get_page(self, day: date, start: int = 0) -> bytes | None:
        parametr = {
            "date": day.isoformat(),
            "start": start,
            "iss.meta": "off",
        }
        response = self.open_link(self.link, parametr)
        if response is None:
            return None
        return response.content

    def get_page_with_retries(self, day: date, start: int) -> bytes | None:
        for attempt in range(1, PAGE_FETCH_RETRIES + 1):
            page = self.get_page(day, start=start)
            if page is not None:
                return page
            if attempt < PAGE_FETCH_RETRIES:
                delay = PAGE_FETCH_BACKOFF * attempt
                logger.warning(
                    "Повтор %s/%s для %s start=%s через %.1fс",
                    attempt, PAGE_FETCH_RETRIES, day, start, delay,
                )
                time.sleep(delay)
        logger.error("Исчерпаны попытки для %s start=%s", day, start)
        return None

    def date_range(self, start: date, end: date) -> Iterator[date]:
        d = start
        while d <= end:
            yield d
            d += timedelta(days=1)

    def parse_cursor(self, xml_bytes: bytes) -> dict:
        root = ET.fromstring(xml_bytes)
        for data in root.findall("data"):
            if data.get("id") == "history.cursor":
                for row in data.findall("rows/row"):
                    try:
                        total = int(row.get("TOTAL", 0))
                        page_size = int(row.get("PAGESIZE", 0))
                    except (TypeError, ValueError) as e:
                        logger.error("Некорректный cursor: %s", e)
                        return {"TOTAL": 0, "PAGESIZE": 0}
                    return {"TOTAL": total, "PAGESIZE": page_size}
        return {"TOTAL": 0, "PAGESIZE": 0}

    def get_data_with_file(self, day: date) -> list[bytes] | None:
        first = self.get_page_with_retries(day, start=0)
        if first is None:
            return None

        try:
            cursor = self.parse_cursor(first)
        except ET.ParseError as e:
            logger.error("Некорректный XML %s: %s", day, e)
            return None

        total = cursor["TOTAL"]
        if total == 0:
            return []

        page_size = cursor["PAGESIZE"] or DEFAULT_PAGE_SIZE

        pages: list[bytes] = [first]
        start = page_size
        while start < total:
            page = self.get_page_with_retries(day, start=start)
            if page is None:
                logger.error("Не удалось скачать %s start=%s", day, start)
                return None
            pages.append(page)
            start += page_size
        return pages

    def to_decimal(self, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
        if text in {"", "-"}:
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    def to_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None

        text = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
        if text in {"", "-", "."}:
            return None

        try:
            return int(Decimal(text))
        except (ValueError, InvalidOperation):
            return None

    def to_str(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def parse_pages(self, pages: list[bytes]) -> list[TradingResult]:
        results: list[TradingResult] = []
        for xml_bytes in pages:
            try:
                root = ET.fromstring(xml_bytes)
            except ET.ParseError as e:
                logger.error("Плохой XML в parse_pages: %s", e)
                continue

            for data in root.findall("data"):
                if data.get("id") != "history":
                    continue

                for row in data.findall("rows/row"):
                    a = row.attrib

                    if a.get("BOARDID") != BOARD_ID:
                        continue

                    count = self.to_int(a.get("NUMTRADES"))
                    if count is None or count == 0:
                        continue

                    tradedate = a.get("TRADEDATE")
                    if not tradedate:
                        continue

                    try:
                        d = date.fromisoformat(tradedate)
                    except ValueError:
                        logger.warning(
                            "Не та TRADEDATE=%r (SECID=%s)",
                            tradedate, a.get("SECID"),
                        )
                        continue

                    secid = self.to_str(a.get("SECID"))
                    if not secid:
                        logger.warning("Пустой SECID, пропуск строки")
                        continue

                    volume = self.to_decimal(a.get("VOLUME"))
                    total = self.to_decimal(a.get("VALUE"))

                    results.append(TradingResult(
                        exchange_product_id=secid,
                        exchange_product_name=self.to_str(a.get("SHORTNAME")),
                        board_id=BOARD_ID,
                        volume=volume,
                        total=total,
                        count=count,
                        date=d,
                    ))
        return results

    def run(self) -> None:
        days = list(self.date_range(self.data_start, self.data_end))
        failed_days: list[date] = []
        total_saved = 0
        no_trades_days = 0

        logger.info(
            "Диапазон: %s → %s (дней: %s)",
            self.data_start, self.data_end, len(days),
        )

        for i, day in enumerate(days):
            pages = self.get_data_with_file(day)

            if pages is None:
                logger.error("[%s/%s] %s: ошибка загрузки", i + 1, len(days), day)
                failed_days.append(day)
                continue

            if not pages:
                no_trades_days += 1
                logger.info("[%s/%s] %s: торгов не было", i + 1, len(days), day)
                continue

            records = self.parse_pages(pages)
            orm_objs = [
                MoexTradingResult(
                    exchange_product_id=r.exchange_product_id,
                    exchange_product_name=r.exchange_product_name,
                    board_id=r.board_id,
                    volume=r.volume,
                    total=r.total,
                    count=r.count,
                    date=r.date,
                )
                for r in records
            ]
            save_to_db(orm_objs)
            total_saved += len(records)

            logger.info(
                "[%s/%s] %s: %s записей (всего %s)",
                i + 1, len(days), day, len(records), total_saved,
            )

            del records, orm_objs

        logger.info("=" * 60)
        logger.info("Всего сохранено/обновлено строк: %s", total_saved)
        logger.info("Дней без торгов (TOTAL=0): %s", no_trades_days)

        if failed_days:
            logger.error("Не удалось загрузить дней: %s", len(failed_days))
            for d in failed_days:
                logger.error("  %s", d)
            raise SystemExit(1)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    init_db()
    Parser(DATA_START, DATA_END, ISS_URL).run()


if __name__ == "__main__":
    main()



    #https://github.com/daryakuts/Parser-MOEX
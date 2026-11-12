# Parser MOEX

Парсер итогов торгов Московской биржи (режим TQBR) с сохранением в PostgreSQL.

## Что делает

- Скачивает историю торгов акциями с [MOEX ISS](https://iss.moex.com/) за заданный период
- Разбирает XML (пагинация по 100 строк на страницу)
- Сохраняет в PostgreSQL с UPSERT — повторный запуск не создаёт дублей
- Сохраняет **по дням** — память не растёт с длиной периода

## Стек

- Python 3.13
- `requests` — HTTP-запросы к MOEX ISS
- `SQLAlchemy 2.x` — ORM
- `psycopg2-binary` — драйвер PostgreSQL
- `python-dotenv` — загрузка `.env`

## Установка

```bash
git clone https://github.com/daryakuts/Parser-MOEX.git
cd Parser-MOEX

python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate        # Linux/macOS

pip install -r requirements.txt
```

## Настройка

Скопируйте `.env.example` → `.env` и заполните:

```bash
cp .env.example .env
```

`.env`:

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=moex
DB_USER=postgres
DB_PASS=your_password
```

## База данных

Создайте БД (один раз):

```bash
psql -U postgres -h localhost -p 5432 -c "CREATE DATABASE moex;"
```

Таблица `moex_trading_results` создаётся **автоматически** при первом запуске (`init_db()` → `create_all`).

### Схема

| Колонка | Тип | Описание |
|---|---|---|
| `id` | SERIAL PK | автоинкремент |
| `exchange_product_id` | VARCHAR(50) NOT NULL | тикер (`SECID`) |
| `exchange_product_name` | VARCHAR(500) | краткое название (`SHORTNAME`) |
| `board_id` | VARCHAR(20) NOT NULL | режим торгов (`TQBR`) |
| `volume` | NUMERIC(20,4) | объём в штуках (`VOLUME`) |
| `total` | NUMERIC(24,2) | оборот в рублях (`VALUE`) |
| `count` | INTEGER | число сделок (`NUMTRADES`) |
| `date` | DATE | дата торгов (`TRADEDATE`) |
| `created_on` | TIMESTAMP | создано (DEFAULT now()) |
| `updated_on` | TIMESTAMP | обновлено (ON UPDATE) |

**UNIQUE** `(date, board_id, exchange_product_id)` — основа UPSERT.

## Запуск

Даты задаются **константами** в `parser.py`:

```python
DATA_START = date(2023, 1, 1)                    # с какого дня
DATA_END   = date.today() - timedelta(days=1)    # по вчера (завершённый день)
```

Запуск:

```bash
python parser.py
```

Вывод:

```
2026-11-13 ... INFO __main__: Диапазон: 2023-01-01 → 2026-11-12 (дней: 1412)
2026-11-13 ... INFO __main__: [1/1412] 2023-01-01: торгов не было
2026-11-13 ... INFO __main__: [3/1412] 2023-01-03: 239 записей (всего 239)
...
2026-11-13 ... INFO __main__: Всего сохранено/обновлено строк: 500000
2026-11-13 ... INFO __main__: Дней без торгов (TOTAL=0): 400
```

## Проверка данных

```bash
psql -U postgres -h localhost -p 5432 -d moex -c "SELECT COUNT(*), MIN(date), MAX(date) FROM moex_trading_results;"
```

Топ-10 по обороту:

```sql
SELECT exchange_product_id, exchange_product_name, total, count
FROM moex_trading_results
WHERE date = '2023-01-03'
ORDER BY total DESC
LIMIT 10;
```

## Особенности

- **UPSERT** (`ON CONFLICT DO UPDATE`) — можно перезапускать без дублей
- **Пагинация** — качает все страницы за день (`TOTAL > PAGESIZE`)
- **Retry** — 3 попытки с backoff при сетевых ошибках
- **Пропуск бумаг без сделок** — `NUMTRADES = 0` не сохраняются
- **Завершённые дни** — `DATA_END` должен быть раньше `today`
- **Экономия памяти** — `save_to_db` по дням, не всё в конце

## Структура

```
.
├── parser.py           # основной скрипт: парсинг + цикл по дням
├── db_writer.py        # engine, init_db, save_to_db (UPSERT)
├── modele_table.py     # SQLAlchemy-модель MoexTradingResult
├── config.py           # чтение .env через python-dotenv
├── .env.example        # шаблон переменных окружения
├── .gitignore          # исключения для Git
└── requirements.txt    # зависимости
```

## Лицензия

Учебный проект. Используйте свободно.
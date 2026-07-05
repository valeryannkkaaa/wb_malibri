# WB Advert Module

Независимый модуль управления рекламой WB (фаза 0–1).  
Интегрируется в **WB Content Portal** без n8n на старте.

## Структура

```
wb_advert/
├── client/                 # WB HTTP API
│   ├── base.py             # auth, pause, SSL fallback
│   ├── promotion.py        # adverts, normquery, fullstats
│   └── analytics.py        # sales-funnel v3
├── sync/
│   ├── worker.py           # sync algorithm (TZ §5.2)
│   ├── mappers.py          # API → KeywordMetrics
│   └── metrics.py          # CTR/CPC расчёт
├── schemas/                # Pydantic DTO
├── db/
│   └── migrations/
│       └── 001_advert_schema.sql
├── import_data/
│   └── csv_loader.py       # pilot CSV
├── api/
│   └── routes.py           # FastAPI /api/advert
├── storage/                # pilot JSON store (phase 1)
├── templates/              # read-only HTML dashboard
├── app.py                  # standalone FastAPI app
└── scripts/
    ├── sync_once.py
    ├── sync_pilot.py
    ├── resolve_nm.py
    ├── backfill_keywords.py
    └── import_pilot.py

data/pilot/                 # пилотные данные (10 SKU)
├── config.yaml
├── pilot_skus.csv
├── keywords.csv
└── unit_economics.csv

wb_advert_probe/            # разведка API (уже выполнена)
```

## Быстрый старт

**Важно:** `wb_advert` лежит **рядом** с `wb_advert_probe`, не внутри неё.

```powershell
cd C:\Users\Valeria\Documents\wb-content-portal\wb_advert

# .env — скопировать токен из probe (или вставить вручную)
Copy-Item ..\wb_advert_probe\.env .env

python -m pip install -r requirements.txt
python -m scripts.import_pilot
python -m scripts.sync_once --advert-id 33206346 --no-resolve-nm

# Все 10 пилотных SKU: resolve nm_id + sync + primary keywords в CSV
python -m scripts.sync_pilot --resolve-nm --pause 8

# Phase 1 — read-only dashboard (из repo root)
cd ..
.\wb_advert\run_server.ps1
# http://127.0.0.1:8765  (default port; use -Port if busy)

# Сохранить полные списки ключей (1 кампания за запуск)
cd wb_advert
python -m scripts.backfill_keywords --advert-id 33206346
```

Или через helper-скрипты (из папки `wb_advert`):

```powershell
.\run_import.ps1
.\run_sync.ps1 -AdvertId 33206346
```

## Пилотные данные

| Файл | Статус |
|------|--------|
| `data/pilot/pilot_skus.csv` | 10 активных РК (type 9, status 9) |
| `data/pilot/config.yaml` | suggest-only, sync 15 min |
| `data/pilot/keywords.csv` | primary keyword (auto из sync или вручную) |
| `data/pilot/unit_economics.csv` | ⚠️ cost_price / retail_price — менеджер |

`nm_id` = `PENDING_{advert_id}` до `python -m scripts.resolve_nm`.

**Пилот 03.07.2026:** 2/10 nm_id resolved (`754549033`, `866360474`). Отчёт sync: `data/pilot/last_sync_report.json`.

## Интеграция в портал (следующий шаг)

1. `psql` → `001_advert_schema.sql`
2. `app.include_router(advert_router, prefix="/api/advert")`
3. Подключить `SyncWorker` к cron/n8n
4. UI `/advert` read-only

## Подтверждённые API (probe)

- `GET /api/advert/v2/adverts`
- `GET /adv/v3/fullstats`
- `POST /adv/v0/normquery/stats`
- `POST /adv/v0/normquery/get-bids`
- `POST /api/analytics/v3/sales-funnel/products`

## Документы

- [TZ_WB_Advert_Module.md](../docs/TZ_WB_Advert_Module.md)
- [MVP_Phases_0-2_Requirements.md](../docs/MVP_Phases_0-2_Requirements.md)
- [WB_API_Discovery_Report.md](../docs/WB_API_Discovery_Report.md)

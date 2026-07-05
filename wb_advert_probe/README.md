# WB Advert Probe — независимый модуль (фаза 0)

Отдельный Python-модуль для **разведки WB API** до интеграции в WB Content Portal и n8n.  
Соответствует идее из транскрипта: API-ключ в `.env`, модуль сам проверяет доступные данные.

## Быстрый старт

```powershell
cd wb_advert_probe
copy .env.example .env
# Вставьте WB API token в .env (не коммитьте!)
python -m pip install -r requirements.txt
python probe.py
python probe.py --json reports/probe_report.json
```

## Что проверяет

| Группа | Эндпоинт | Нужно для MVP |
|--------|----------|---------------|
| Promotion | `GET /adv/v1/promotion/count` | Обзор кампаний |
| Promotion | `GET /api/advert/v2/adverts` | Sync type 9 кампаний |
| Promotion | `POST /adv/v0/normquery/stats` | CTR/CPC по ключам |
| Promotion | `GET /adv/v3/fullstats` | Статистика кампании |
| Promotion | `GET /adv/v1/balance` | Баланс рекламы |
| Promotion | `POST /adv/v0/normquery/get-bids` | Ставки по кластерам |
| Analytics | `POST /api/analytics/v3/sales-funnel/products` | Заказы/воронка по nm_id |
| Analytics | `POST /api/analytics/v1/stocks-report/wb-warehouses` | Остатки |
| Marketplace | `GET /api/v3/orders/new` | FBS-заказы (опционально) |

После успешного `adverts_v2` probe автоматически подставляет первый `advert_id` и `nm_id` в зависимые запросы.

## Безопасность

- Токен **только** в `.env` (файл в `.gitignore`)
- Не публикуйте токен в чатах и git
- Для пилота: read-only токен → затем токен с правами на изменение ставок

## Связанные документы

- [MVP_Phases_0-2_Requirements.md](../docs/MVP_Phases_0-2_Requirements.md)
- [TZ_WB_Advert_Module.md](../docs/TZ_WB_Advert_Module.md)
- [WB_API_Discovery_Report.md](../docs/WB_API_Discovery_Report.md)

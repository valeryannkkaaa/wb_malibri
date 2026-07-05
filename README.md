# WB Content Portal — Advert MVP

Репозиторий подготовки модуля рекламы Wildberries (фазы 0–2).

## Состав

| Путь | Назначение |
|------|------------|
| `docs/` | ТЗ, MVP-требования, отчёт разведки API |
| `data/pilot/` | **10 пилотных SKU** + config (заполнено) |
| `wb_advert_probe/` | Разведка WB API (выполнена) |
| `wb_advert/` | **Модуль sync + client + schema** (фаза 0) |

## Статус разведки (03.07.2026)

- ✅ 155 кампаний type 9
- ✅ normquery stats + fullstats + get-bids
- ✅ suggest-only режим зафиксирован
- ⚠️ unit economics + primary keywords — **нужны от менеджера**

## Запуск

```powershell
cd wb_advert
copy .env.example .env
python -m pip install -r requirements.txt
python -m scripts.sync_once --advert-id 33206346
```

## Следующий шаг

Интеграция `wb_advert` в код портала v1.5.0 + миграция БД + UI `/advert`.

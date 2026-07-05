# Пилотные данные MVP (10 SKU)

Заполнено автоматически по разведке WB API (03.07.2026).

## Файлы

| Файл | Статус |
|------|--------|
| `pilot_skus.csv` | ✅ 10 активных РК (status 9, type 9) |
| `keywords.csv` | ⚠️ Заготовка — **primary_keyword** заполнит менеджер |
| `unit_economics.csv` | ⚠️ **cost_price, retail_price** — заполнит менеджер |
| `config.yaml` | ✅ Режим suggest-only, лимиты sync |

## nm_id = `PENDING_{advert_id}`

Реальный `nm_id` подтянется при первом sync:

```powershell
cd wb_advert
python -m scripts.sync_once --advert-id 33206346
```

или массово:

```powershell
python -m scripts.import_pilot --resolve-nm
```

## Что заполнить менеджеру

1. `product_name` и `primary_keyword` в CSV (или через UI после импорта)
2. `unit_economics.csv` — себестоимость, цена, маржа
3. `config.yaml` → `parser.region`, `telegram_chat_id`
4. Исключения ключей (excluded=true) — по мере появления данных normquery

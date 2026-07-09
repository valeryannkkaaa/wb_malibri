# Пилотные данные MVP (10 SKU)

Заполнено автоматически по разведке WB API (03.07.2026).

## Файлы

| Файл | Статус |
|------|--------|
| `pilot_skus.csv` | ✅ 10 активных РК (status 9, type 9) |
| `keywords.csv` | ⚠️ Заготовка — **primary_keyword** заполнит менеджер |
| `unit_economics.csv` | ⚠️ retail из API; **cost_price** — менеджер |
| `config.yaml` | ✅ suggest-only, sync, parser |
| `MANAGER_CHECKLIST.md` | ✅ **Чеклист сверки для менеджера** |
| `MANAGER_CHECKLIST.pdf` | ✅ PDF-версия чеклиста |

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

См. **`MANAGER_CHECKLIST.md`** — блоки A–D (сверка + шаблон ответа).

1. Решения по 2 ключам на исключение (блок A)
2. Подтверждение primary keywords (блок B)
3. `unit_economics.csv` — себестоимость (блок E, позже)
4. `config.yaml` → `parser.region`, `telegram_chat_id`

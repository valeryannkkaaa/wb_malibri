# Отчёт разведки WB API (фаза 0)

**Дата:** 03.07.2026  
**Контекст:** независимый модуль `wb_advert_probe/` — проверка read-only токена на реальных данных до интеграции в портал.  
**Источник задачи:** транскрипт созвона + [MVP_Phases_0-2_Requirements.md](./MVP_Phases_0-2_Requirements.md)

---

## 1. Что сделано

Создан автономный модуль:

```
wb_advert_probe/
├── probe.py           # скрипт проверки эндпоинтов
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

Запуск: положить `WB_API_TOKEN` в `.env` → `python probe.py`.

Модуль **не зависит** от FastAPI, PostgreSQL, n8n — только HTTP-клиент и токен.

---

## 2. Анализ предоставленного токена (read-only)

JWT payload (публичная часть, без проверки подписи):

| Поле | Значение | Интерпретация |
|------|----------|---------------|
| `uid` / `iid` | 304914783 | ID продавца |
| `oid` | 250069931 | Организация |
| `exp` | ~2026-12-31 | Срок действия ~1 год |
| `t` | false | Боевой контур (не sandbox) |
| `acc` | 1 | Base token |
| `s` | 1073757950 | Битовая маска категорий API |

### Расшифровка маски `s = 1073757950`

По [документации WB](https://dev.wildberries.ru/docs/openapi/api-information): поле `s` — битовая маска прав.

| Бит | Категория | В токене |
|-----|-----------|----------|
| 1 | Контент | ✅ |
| 2 | Аналитика | ✅ |
| 3 | Цены и скидки | ✅ |
| 4 | Маркетплейс | ✅ |
| 5 | Статистика | ✅ |
| 6 | **Продвижение (Promotion)** | ✅ |
| 7 | Отзывы и вопросы | ✅ |
| 8 | Рекомендации | ✅ |
| 9–13 | Чат, поставки, возвраты, документы, финансы | ✅ |
| **30** | **Только чтение** | ✅ |

**Вывод:** это широкий **read-only** токен с доступом к Promotion + Analytics + Marketplace — **достаточен для фазы 0–1** (sync, статистика, дашборд, suggest-only рекомендации).  
Для **фазы 2 auto** (изменение ставок, minus-phrases, pause/start) нужен **отдельный write-токен** без бита 30.

---

## 3. Что можно получить с read-only токеном (по MVP)

### Фаза 0 — блокирующий минимум

| Данные | WB API | Read-only? | Зачем |
|--------|--------|------------|-------|
| Список кампаний type 9 | `GET /api/advert/v2/adverts` | ✅ | `advert_campaign_links` |
| Счётчики кампаний | `GET /adv/v1/promotion/count` | ✅ | Health / dashboard |
| Статистика по ключам (normquery) | `POST /adv/v0/normquery/stats` | ✅ | CTR, CPC, shows, clicks |
| Full stats кампании | `GET /adv/v3/fullstats` | ✅ | Сверка ±5% с Excel |
| Текущие ставки кластеров | `POST /adv/v0/normquery/get-bids` | ✅ | Отображение bid |
| Мин. ставки | `POST /api/advert/v1/bids/min` | ✅ | Валидация перед изменением |
| Баланс рекламы | `GET /adv/v1/balance` | ✅ | Алерты бюджета |
| Активные/неактивные кластеры | `POST /adv/v0/normquery/list` | ✅ | Managed keys |

**Расчёт CTR/CPC (из ТЗ):**

```
ctr_calculated = clicks / views * 100
cpc_calculated_kopecks = spend_kopecks / clicks   # spend из normquery/fullstats
```

Для CPC-кампаний WB с 02.2026 **не отдаёт** `views`, `ctr`, `cpm` в normquery — только clicks/orders/cpc.

### Фаза 1 — дополнительно

| Данные | WB API | Scope |
|--------|--------|-------|
| Заказы / воронка по nm_id | `POST /api/analytics/v3/sales-funnel/products` | Analytics |
| Остатки на складах WB | `POST /api/analytics/v1/stocks-report/wb-warehouses` | Analytics |
| FBS-сборочные задания | `GET /api/v3/orders/new` | Marketplace |

> **Deprecated:** `POST /api/v2/nm-report/detail` — 404, заменён на analytics v3.

### Не из WB API (нужны отдельно)

| Данные | Источник |
|--------|----------|
| Реальная позиция в выдаче | Парсер `wb.ru/search` (фаза 1) |
| Юнит-экономика, max DRR | CSV `unit_economics.csv` |
| Primary keys, target_grade | CSV `keywords.csv` + `pilot_skus.csv` |
| Benchmark CTR/CPC | Менеджер (ручная сверка) |

---

## 4. Что требует write-токен (фаза 2)

| Операция | API | Когда |
|----------|-----|-------|
| Изменение ставок | `PATCH /api/advert/v1/bids` | Optimizer auto |
| Ставки на кластеры | `POST /adv/v0/normquery/bids` | Manual bid по ключу |
| Минус-фразы | `POST /adv/v0/normquery/set-minus` | Exclude key |
| Пауза/старт РК | `GET /adv/v0/pause`, `/start` | Schedule night_off |
| Пополнение бюджета | `POST /adv/v1/budget/deposit` | Фаза 4 |

На пилоте рекомендация из MVP: **suggest-only 3–5 дней** → read-only токена хватит для sync + UI + рекомендаций.

---

## 5. Rate limits (учесть в sync worker)

| Метод | Лимит | Интервал |
|-------|-------|----------|
| `GET /api/advert/v2/adverts` | 30 req/min | 200 ms |
| `POST /adv/v0/normquery/stats` | 10 req/6 sec | ~600 ms |
| `GET /adv/v3/fullstats` | 3 req/20 sec | ~7 s |
| Analytics v3 sales-funnel | 3 req/min | 20 s |

Для 10 SKU × 4 sync/день — укладываемся. Для 50 SKU — нужна очередь (Redis) и батчинг.

---

## 6. Что ещё нужно от заказчика (кроме токена)

### Первая очередь (старт фазы 0)

1. ✅ Read-only WB token — получен  
2. ⬜ **Write token** (или подтверждение suggest-only без write)  
3. ⬜ `pilot_skus.csv` — 5–10 nm_id + `wb_campaign_id_search/unified`  
4. ⬜ `keywords.csv` — primary keys по SKU  
5. ⬜ `unit_economics.csv` — для optimizer (можно после read-only дашборда)  
6. ⬜ Подтверждение: все пилотные РК — **type 9**  
7. ⬜ Решение: **suggest-only** vs **auto** на пилоте  

### Вторая очередь (фаза 1)

8. Регион парсинга (Ростов / Москва)  
9. Benchmark CTR/CPC от менеджера  
10. n8n + Redis (orchestration)  

### Инфраструктура портала (для интеграции, не для probe)

- Git + код WB Content Portal v1.5.0  
- PostgreSQL + миграции advert-таблиц  
- Admin-доступ к wb.zhukovlab.ru или staging  

---

## 7. Результаты пробного запуска probe (03.07.2026)

Первый запуск из среды разработки:

| API | Результат | Комментарий |
|-----|-----------|-------------|
| `advert-api.wildberries.ru` | SSL EOF | Возможна сетевая блокировка / TLS из sandbox; **запустите probe локально** |
| `seller-analytics-api` | HTTP 404 на старых путях | Auth работает; пути обновлены на v3 в probe.py |
| `marketplace-api` | HTTP 404 на `/api/v3/stocks` | Auth работает; stocks → analytics `stocks-report` |

**Действие:** выполните локально:

```powershell
cd wb_advert_probe
copy .env.example .env
# вставьте токен
python probe.py --json reports/probe_report.json
```

Пришлите `reports/probe_report.json` (без токена) — зафиксируем фактические scope и sample data.

---

## 8. Следующие шаги

```
✅ wb_advert_probe — разведка API
✅ data/pilot — 10 SKU + config.yaml
✅ wb_advert/ — client + sync worker + SQL migration
→ python -m wb_advert.scripts.sync_once --advert-id 33206346
→ Интеграция в FastAPI портал + UI /advert
→ Менеджер: keywords + unit_economics CSV
```

---

## 9. Безопасность токена

Токен из чата **не сохранён** в репозитории. Храните только в `.env` на машине/сервере.  
При утечке — отозвать в ЛК WB → Настройки → Доступ к API.

---

## История

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 03.07.2026 | Первый отчёт, модуль wb_advert_probe |

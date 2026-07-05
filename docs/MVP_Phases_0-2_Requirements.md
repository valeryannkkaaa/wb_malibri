# Требования для старта MVP (фазы 0–2)
## Модуль рекламы Wildberries — WB Content Portal

**Проект:** [wb.zhukovlab.ru](https://wb.zhukovlab.ru)  
**Scope MVP:** §1.3 ТЗ — синхронизация кампаний, ключи, парсинг, CTR/CPC, optimizer, UI, audit log  
**Дата:** 30.06.2026  
**Связанный документ:** [TZ_WB_Advert_Module.md](./TZ_WB_Advert_Module.md)

---

## Scope MVP (что делаем)

- Синхронизация кампаний WB type 9
- Управление ключами (поиск, manual bid)
- Парсинг реальных позиций
- Расчёт CTR/CPC из сырых данных API
- Автоматические решения по ставкам
- UI дашборд + карточка рекламы
- Audit log решений

**Не входит в этот этап:** полки/recommendations (фаза 3), автопополнение бюджета (фаза 4), создание новых РК через API.

---

## 1. Доступы и инфраструктура

| № | Что | Зачем | Формат |
|---|-----|-------|--------|
| 1 | **Исходный код WB Content Portal** | Расширять FastAPI, БД, UI | Git-репозиторий или архив + инструкция deploy |
| 2 | **Доступ к серверу** `wb.zhukovlab.ru` | Деплой, миграции, воркеры | SSH / CI/CD или staging-окружение |
| 3 | **Структура БД** | Миграции advert-таблиц | `schema.sql`, Alembic migrations или ORM models |
| 4 | **`.env` / secrets** (без публикации в git) | Подключение к PostgreSQL, n8n, Redis | Шаблон `.env.example` |
| 5 | **n8n** | Cron sync/optimize | URL + API key + существующие workflows (если есть) |
| 6 | **Redis** (если нет — согласовать установку) | Очередь optimize, rate limit | Host/port или «ставим с нуля» |
| 7 | **Тестовый аккаунт портала** | Admin + Manager | email/password |
| 8 | **Staging** (желательно) | Тесты без влияния на прод | Отдельный домен или branch deploy |

**Критично:** без репозитория и доступа к БД можно только проектировать; для реальной разработки нужен код портала v1.5.0.

---

## 2. Wildberries API

| № | Что | Зачем |
|---|-----|-------|
| 1 | **API-тoken WB** с правами **Promotion** + **Analytics** + **Marketplace** (остатки) | Sync кампаний, stats, bids, orders |
| 2 | **Подтверждение типа кампаний** | Все активные РК — **type 9** (manual/unified) |
| 3 | **Список `wb_campaign_id`** по пилотным SKU | Привязка `advert_campaign_links` |
| 4 | **Документ: какие 2 типа РК** на каждом артикуле | search_manual / unified / recommendations |
| 5 | **Rate limits / лимиты кабинета** | Чтобы не упереться в throttling при 50 SKU |

**Формат токена:** строка в личном кабинете WB → Настройки → Доступ к API. Хранить только в `wb_credentials` (encrypted), не в чате.

**Проверка на старте:** один тестовый запрос:

- `GET /api/advert/v2/adverts`
- `POST /adv/v0/normquery/stats` по 1 кампании

---

## 3. Пилотные данные (~10 SKU для MVP, потом 50)

### 3.1. Таблица карточек (Excel/CSV/Google Sheets)

Минимальные колонки:

```
nm_id | article | product_name | category | project_id | advert_enabled
      | primary_keyword | keyword_class (primary/secondary)
      | target_grade (top_1_3 / pos_10_20)
      | schedule (always_on / night_off)
      | wb_campaign_id_search | wb_campaign_id_unified (если есть)
      | notes
```

**Примеры из экспертизы:** красные перчатки, зелёные, жёлтые, салфетки для стёкол, безворсовые.

### 3.2. Юнит-экономика (обязательно для optimizer)

```
nm_id | cost_price_rub | retail_price_rub | margin_pct | max_drr_pct
      | wb_commission_pct | logistics_rub | volume_priority (margin/balanced/volume)
```

Без этого модуль сможет **синхронизировать и показывать** данные, но **не сможет** принимать решения по ставкам.

### 3.3. Основные ключи по SKU (от менеджера)

Для каждого пилотного артикула — 3–10 ключей:

```
nm_id | keyword | keyword_class | target_grade | frequency_monthly (если есть)
```

Пример: «перчатки для уборки» (primary, top_1_3, ~46000/мес).

### 3.4. Исключения и правила «руками»

- Ключи, которые **никогда** не включать (перчатки кожаные и т.п.)
- SKU с **24/7** vs **night_off** (включение 6–7 утра)
- SKU-исключения (красные перчатки за 300₽ — всегда top_1_3)
- SKU, где топ **не окупается** (салфетки — pos_10_20)

---

## 4. Парсинг позиций

| № | Что | Решение |
|---|-----|---------|
| 1 | **Где крутить parser** | Отдельный VPS / тот же сервер / локально для пилота |
| 2 | **Прокси** (если WB режет IP) | Есть/нет, бюджет |
| 3 | **Частота** | MVP: каждые 5 мин по primary keys |
| 4 | **Geo выдачи** | Город/регион для парсинга (Ростов, Москва и т.д.) |
| 5 | **Эталонная проверка** | Менеджер 1 раз в день сверяет 5 ключей вручную vs parser |

**От заказчика:** подтверждение региона выдачи и список primary keys для парсинга (из п. 3.3).

---

## 5. Продуктовые решения (зафиксировать до кода)

| № | Вопрос | Варианты | Рекомендация |
|---|--------|----------|--------------|
| 1 | Optimizer **сразу меняет ставки** или сначала **только рекомендации**? | auto / suggest-only | Пилот: **suggest-only** 3–5 дней, потом auto |
| 2 | Пилот: **сколько SKU**? | 5 / 10 / 50 | **10 SKU**, 2 недели → 50 |
| 3 | **Hard limit bid** 1500₽ — без исключений? | да / override admin | да, override только admin |
| 4 | **min_test_hours** = 2 — ok? | 2 / 3 | 2 (из экспертизы менеджера) |
| 5 | Алерты | Telegram / email / только UI | Telegram chat_id |
| 6 | Parser + optimize на **prod** сразу? | staging first | staging или 5 SKU на prod |

---

## 6. От команды (менеджер маркетплейсов)

| № | Что | Формат |
|---|-----|--------|
| 1 | **Эталонный день работы** по 1–2 карточкам | Скрин + «что смотрю, что меняю» или созвон 30 мин |
| 2 | **Benchmark CTR/CPC** по ключам | «перчатки для уборки: CTR ~13%, CPC ~7.6₽ — норма» |
| 3 | **Сверка после sync** | Excel WB vs наш дашборд (±5%) |
| 4 | **Feedback по решениям бота** | Раз в 2–3 дня: «согласен / не согласен» по audit log |
| 5 | **Контакт для блокеров** | Telegram, время ответа |

---

## 7. Технические артефакты (подготовит команда разработки)

| Deliverable | Фаза |
|-------------|------|
| Alembic/SQL миграции (§4 ТЗ) | 0 |
| `advert/` module: models, sync worker | 0 |
| WB API client (type 9) | 0 |
| `GET /api/advert/*`, `/advert` UI read-only | 0 |
| Parser service + webhook | 1 |
| `advert_snapshots`, import unit economics | 1 |
| Optimizer + `advert_decisions` | 2 |
| Bid change / exclude / retest | 2 |
| n8n workflow `advert-daily-cycle` | 2 |

---

## 8. Минимальный набор «можно начинать»

**Блокирующий минимум:**

1. Git-репозиторий портала + `.env.example`
2. WB API token (Promotion + Analytics)
3. CSV: **10 пилотных nm_id** + campaign_id + primary keys
4. CSV: **unit economics** для этих 10 SKU
5. Admin-доступ к `wb.zhukovlab.ru` (или staging)
6. Решение: **suggest-only** или **auto** на пилоте
7. Telegram chat_id для алертов (опционально)

---

## 9. Что не блокирует старт MVP

- Jam / Evirma API (считаем CTR/CPC сами)
- Полки / recommendations (фаза 3)
- Автопополнение бюджета (фаза 4)
- 50 SKU с первого дня (начнём с 10)
- Создание новых РК через API

---

## 10. План работ после получения данных

```
Неделя 1–2 (Фаза 0)
  → миграции, wb_credentials, sync campaigns + normquery stats
  → дашборд /advert (read-only)
  → приёмка: 5 nm_id, CTR/CPC ±5% vs Excel

Неделя 3–4 (Фаза 1)
  → parser + snapshots
  → import unit economics
  → графики позиция/CTR

Неделя 5–8 (Фаза 2)
  → optimizer (suggest → auto)
  → exclude/retest, audit log
  → n8n 2+ цикла/день
  → приёмка: 10 SKU, 7 дней, ≥80% решений ok у менеджера
```

---

## 11. Шаблоны CSV для заполнения

### Файл 1: `pilot_skus.csv`

```csv
nm_id,product_name,project_id,wb_campaign_search,wb_campaign_unified,schedule,primary_keyword,target_grade,notes
,,,,,,,,,
```

### Файл 2: `unit_economics.csv`

```csv
nm_id,cost_price_rub,retail_price_rub,margin_pct,max_drr_pct,wb_commission_pct,logistics_rub,volume_priority
,,,,,,,,
```

### Файл 3: `keywords.csv`

```csv
nm_id,keyword,keyword_class,target_grade,frequency_monthly,excluded
,,,,,
```

**Допустимые значения:**

- `schedule`: `always_on`, `night_off`
- `target_grade`: `top_1_3`, `pos_4_10`, `pos_10_20`
- `keyword_class`: `primary`, `secondary`, `longtail`, `irrelevant`
- `volume_priority`: `margin_first`, `balanced`, `volume_first`
- `excluded`: `true`, `false`

---

## 12. Чеклист для заказчика

### Доступы

- [ ] Git-репозиторий WB Content Portal
- [ ] `.env.example` (без секретов)
- [ ] SSH / CI или staging
- [ ] Admin-аккаунт портала
- [ ] n8n URL + credentials
- [ ] Redis (или решение «установить»)

### WB

- [ ] API token (Promotion + Analytics + Marketplace)
- [ ] Подтверждение: кампании type 9
- [ ] Тестовые запросы adverts + normquery/stats — ok

### Данные

- [ ] `pilot_skus.csv` — минимум 10 SKU
- [ ] `unit_economics.csv` — те же 10 SKU
- [ ] `keywords.csv` — ключи по пилотным SKU
- [ ] Правила-исключения (night_off, irrelevant keys, SKU-исключения)

### Решения

- [ ] suggest-only или auto на пилоте
- [ ] Регион парсинга выдачи
- [ ] Telegram chat_id для алертов
- [ ] Контакт менеджера для сверки

### Команда

- [ ] Benchmark CTR/CPC по основным ключам
- [ ] Готовность к сверке 1×/день (5 ключей) на фазе 1
- [ ] Готовность к feedback по audit log на фазе 2

---

## 13. Приоритет отправки материалов

**Первая очередь (старт фазы 0):**

1. Репозиторий (или доступ к коду на сервере)
2. WB token (в личку / secure, не в общий чат)
3. Заполненные 3 CSV хотя бы на 5–10 SKU
4. Admin-доступ к порталу
5. Ответ: suggest-only или сразу auto на пилоте

**Вторая очередь (фаза 1):**

6. Регион парсинга + прокси (если нужны)
7. Benchmark CTR/CPC от менеджера
8. n8n + Redis

**Третья очередь (фаза 2):**

9. Telegram для алертов
10. Ежедневная сверка решений менеджером

---

## История изменений

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 30.06.2026 | Первый релиз документа |

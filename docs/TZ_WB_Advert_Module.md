# Техническое задание
## Модуль рекламы Wildberries для WB Content Portal

**Проект:** [wb.zhukovlab.ru](https://wb.zhukovlab.ru)  
**Версия ТЗ:** 1.0  
**Дата:** 28.06.2026  
**Базовая версия портала:** WB Content Portal v1.5.0  
**Источники:** OpenAPI портала, экспертиза менеджера (транскрипт 12.06.2026), WB Promotion API type 9

---

## 1. Общие сведения

### 1.1. Назначение

Разработать модуль автоматизированного управления рекламными кампаниями Wildberries, интегрированный в существующий **WB Content Portal**. Модуль должен воспроизводить логику работы менеджера маркетплейсов (2+ цикла оптимизации в день на карточку) с опорой на юнит-экономику, реальные позиции в выдаче и самостоятельный расчёт CTR/CPC.

### 1.2. Цели

| № | Цель | Метрика успеха |
|---|------|----------------|
| 1 | Сократить ручное время на рекламу | −80% времени менеджера на ~50 SKU |
| 2 | Не допускать перерасхода бюджета | 0 случаев bid > 1500 ₽/1000 показов без подтверждения |
| 3 | Держать окупаемые позиции | DRR ≤ целевого по юнитке на primary-ключах |
| 4 | Прозрачность решений | 100% автодействий с записью в audit log |
| 5 | Масштабирование | Поддержка 50 SKU (MVP) → 200 SKU (v2) |

### 1.3. Границы scope

**В scope (MVP — фазы 0–2):**

- Синхронизация кампаний WB type 9
- Управление ключами (поиск, manual bid)
- Парсинг реальных позиций
- Расчёт CTR/CPC из сырых данных API
- Автоматические решения по ставкам
- UI дашборд + карточка рекламы
- Audit log решений

**В scope (v1.1 — фазы 3–4):**

- Полки / рекомендации
- Расписание вкл/выкл кампаний
- Автопополнение бюджета
- CPC fallback для неликвида

**Out of scope (v1):**

- Создание новых РК через API (только управление существующими)
- Автоматическое изменение цены товара
- Выкупы / покупные корзины (только мониторинг + рекомендация)
- Интеграция с Ozon

### 1.4. Роли пользователей

| Роль | Права |
|------|-------|
| **Admin** | Все настройки, WB token, лимиты, ручной override |
| **Manager** | Просмотр, ручной запуск цикла, exclude/retest ключей |
| **Viewer** | Только чтение дашбордов и логов |
| **System (bot/worker)** | API sync, optimize, parse — без UI |

---

## 2. Термины и сокращения

| Термин | Определение |
|--------|-------------|
| **nm_id** | Артикул WB (связь Product ↔ WB) |
| **РК** | Рекламная кампания |
| **Type 9** | Актуальный тип кампании WB (manual/unified bid) |
| **Normquery / cluster** | Поисковый кластер (ключевое слово) в WB API |
| **Managed key** | Ключ с ≥100 показами, доступен для индивидуальной ставки |
| **Position grade** | Грейд позиции: `top_1_3`, `pos_4_10`, `pos_10_20`, `pos_20_plus` |
| **Primary key** | Основной ключ (>80% заказов или частотность >10k/мес) |
| **Shelf** | Рекомендательная полка в карточке конкурента |
| **DRR** | Доля рекламных расходов = spend / revenue |
| **Unit economics** | Себестоимость, маржа, max DRR, max CPC для SKU |
| **Snapshot** | Срез метрик в момент времени |
| **Optimization cycle** | Полный проход оптимизатора по одной карточке |

---

## 3. Архитектура

### 3.1. Компоненты

```
┌─────────────────────────────────────────────────────────────┐
│                    WB Content Portal v2.0                    │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  Content     │  Advert UI   │  Advert API  │  Shared Core   │
│  (existing)  │  (new HTML)  │  /api/advert │  auth, projects│
├──────────────┴──────────────┴──────────────┴────────────────┤
│                      PostgreSQL                              │
│  products │ advert_profiles │ advert_keywords │ snapshots   │
│  advert_decisions │ unit_economics │ wb_credentials          │
├─────────────────────────────────────────────────────────────┤
│  Workers (async, via n8n или Celery/ARQ)                    │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │ wb_sync     │ │ position_    │ │ optimizer           │  │
│  │ worker      │ │ parser       │ │ (decision engine)   │  │
│  └──────┬──────┘ └──────┬───────┘ └──────────┬──────────┘  │
└─────────┼───────────────┼──────────────────────┼────────────┘
          │               │                      │
          ▼               ▼                      ▼
   WB Promotion API   WB Search (parse)    WB Orders/Analytics
```

### 3.2. Принципы

1. **Модульность** — падение advert-модуля не блокирует content-модуль
2. **Idempotency** — повторный optimize не дублирует bid changes
3. **Fail-safe** — при ошибке API → pause + alert, не «наращивать ставки вслепую»
4. **Audit-first** — каждое изменение ставки логируется с reason code
5. **Hard limits** — лимиты из ТЗ не переопределяются алгоритмом

### 3.3. Технологический стек (наследуется от портала)

| Слой | Технология |
|------|------------|
| Backend | FastAPI (существующий) |
| DB | PostgreSQL |
| ORM | SQLAlchemy / текущий стек портала |
| Frontend | Server-side HTML + CSS (как `/products/*`) |
| Orchestration | n8n (webhooks уже есть) |
| Parser | Отдельный Python-сервис или n8n + headless |
| Cache/Queue | Redis (рекомендуется для очереди optimize) |

---

## 4. Модель данных

### 4.1. ER-диаграмма (новые сущности)

```
Product (existing) 1──1 AdvertProfile
AdvertProfile 1──* AdvertCampaignLink
AdvertProfile 1──* AdvertKeyword
AdvertProfile 1──* AdvertCompetitorShelf
AdvertProfile 1──* AdvertSnapshot
AdvertProfile 1──* AdvertDecision
Product 1──1 UnitEconomics
Project 1──1 AdvertProjectSettings
GlobalSettings 1──1 WbCredentials
```

### 4.2. Таблица `advert_profiles`

Профиль рекламы, 1:1 с `products`.

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| product_id | INT FK → products | ✓ | UNIQUE |
| nm_id | VARCHAR(20) | ✓ | Дублируется для быстрых запросов |
| advert_enabled | BOOLEAN | ✓ | default false |
| advert_status | ENUM | ✓ | `new`, `active`, `paused`, `blocked`, `liquidation` |
| category_type | ENUM | ✓ | `goods` (товарка), `clothing`, `liquidation` |
| schedule_mode | ENUM | ✓ | `always_on`, `night_off`, `custom` |
| schedule_wake_hour | SMALLINT | | 6–7 для night_off |
| schedule_sleep_hour | SMALLINT | | default 23 |
| max_bid_kopecks | INT | ✓ | default 150000 (1500 ₽) |
| max_topup_kopecks | INT | ✓ | default 300000 (3000 ₽) |
| min_test_hours | SMALLINT | ✓ | default 2 |
| volume_priority | ENUM | ✓ | `margin_first`, `balanced`, `volume_first` |
| last_optimize_at | TIMESTAMPTZ | | |
| last_sync_at | TIMESTAMPTZ | | |
| parser_enabled | BOOLEAN | ✓ | default true |
| notes | TEXT | | Комментарий менеджера |
| created_at | TIMESTAMPTZ | ✓ | |
| updated_at | TIMESTAMPTZ | ✓ | |

**Индексы:** `nm_id`, `advert_status`, `last_optimize_at`

### 4.3. Таблица `advert_campaign_links`

Связь карточки с РК WB (макс. 2 active одновременно — валидируется).

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| advert_profile_id | INT FK | ✓ | |
| wb_campaign_id | BIGINT | ✓ | ID кампании в WB |
| campaign_type | ENUM | ✓ | см. ниже |
| bid_type | ENUM | ✓ | `manual`, `unified` |
| payment_type | ENUM | ✓ | `cpm`, `cpc` |
| placement | ENUM | ✓ | `search`, `recommendations`, `combined` |
| is_active | BOOLEAN | ✓ | |
| current_bid_kopecks | INT | | Текущая общая ставка |
| min_bid_kopecks | INT | | Минимум от WB API |
| wb_status | VARCHAR(32) | | active/paused/stopped |
| synced_at | TIMESTAMPTZ | | |

**campaign_type ENUM:**

- `search_manual` — ручная ставка, поиск
- `recommendations_manual` — ручная, рекомендации
- `unified_bid` — единая ставка
- `cpc_fallback` — оплата за клик

**UNIQUE:** `(advert_profile_id, wb_campaign_id)`

### 4.4. Таблица `advert_keywords`

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| advert_profile_id | INT FK | ✓ | |
| campaign_link_id | INT FK | | NULL если ещё не managed |
| keyword | VARCHAR(512) | ✓ | Текст ключа |
| normquery_id | VARCHAR(128) | | ID кластера WB |
| keyword_class | ENUM | ✓ | `primary`, `secondary`, `longtail`, `irrelevant` |
| status | ENUM | ✓ | `all`, `managed`, `excluded`, `pending_100_shows` |
| shows_total | INT | ✓ | default 0 |
| shows_period | INT | ✓ | За текущий период |
| clicks_period | INT | ✓ | |
| spend_kopecks_period | INT | ✓ | |
| orders_period | INT | ✓ | Общие заказы SKU, не per-key |
| target_grade | ENUM | ✓ | `top_1_3`, `pos_4_10`, `pos_10_20` |
| current_bid_kopecks | INT | | NULL = общая ставка |
| is_custom_bid | BOOLEAN | ✓ | default false |
| ctr_calculated | DECIMAL(8,4) | | clicks/shows |
| cpc_calculated_kopecks | INT | | spend/clicks |
| frequency_monthly | INT | | Частотность (ручной/import) |
| last_parsed_position | SMALLINT | | |
| last_parsed_at | TIMESTAMPTZ | | |
| excluded_at | TIMESTAMPTZ | | |
| excluded_reason | VARCHAR(64) | | |
| retest_after | DATE | | Дата повторного теста |
| created_at | TIMESTAMPTZ | ✓ | |
| updated_at | TIMESTAMPTZ | ✓ | |

**UNIQUE:** `(advert_profile_id, keyword)`  
**Индексы:** `(advert_profile_id, status)`, `(advert_profile_id, keyword_class)`

### 4.5. Таблица `advert_competitor_shelves`

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| advert_profile_id | INT FK | ✓ | |
| competitor_nm_id | VARCHAR(20) | ✓ | |
| competitor_name | VARCHAR(256) | | Patera, Lamber… |
| is_primary | BOOLEAN | ✓ | Основной конкурент |
| target_position_max | SMALLINT | ✓ | default 6 |
| last_position | SMALLINT | | |
| last_parsed_at | TIMESTAMPTZ | | |
| neighbor_price_rub | DECIMAL(10,2) | | Цена соседа в полке |
| is_profitable | BOOLEAN | | Расчётное |
| enabled | BOOLEAN | ✓ | default true |

### 4.6. Таблица `advert_snapshots`

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | BIGSERIAL PK | ✓ | |
| advert_profile_id | INT FK | ✓ | |
| keyword_id | INT FK | | NULL для shelf/global |
| snapshot_type | ENUM | ✓ | `keyword`, `shelf`, `campaign`, `global` |
| recorded_at | TIMESTAMPTZ | ✓ | |
| parsed_position | SMALLINT | | От парсера |
| api_position | SMALLINT | | От WB (если есть) |
| shows | INT | | |
| clicks | INT | | |
| spend_kopecks | INT | | |
| orders_delta | INT | | Заказы за окно |
| ctr | DECIMAL(8,4) | | |
| cpc_kopecks | INT | | |
| bid_kopecks | INT | | Ставка в момент среза |
| price_rub | DECIMAL(10,2) | | Цена карточки |
| delivery_days | SMALLINT | | |
| stock_total | INT | | |
| meta | JSONB | | Доп. данные |

**Индексы:** `(advert_profile_id, recorded_at DESC)`, `(keyword_id, recorded_at DESC)`  
**Retention:** 90 дней (настраиваемо)

### 4.7. Таблица `advert_decisions`

Audit log всех автоматических и ручных решений.

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | BIGSERIAL PK | ✓ | |
| advert_profile_id | INT FK | ✓ | |
| keyword_id | INT FK | | |
| campaign_link_id | INT FK | | |
| decided_at | TIMESTAMPTZ | ✓ | |
| actor | ENUM | ✓ | `optimizer`, `manager`, `system` |
| action | ENUM | ✓ | см. ниже |
| reason_code | VARCHAR(64) | ✓ | |
| reason_text | TEXT | | Человекочитаемое |
| before_state | JSONB | ✓ | |
| after_state | JSONB | ✓ | |
| applied | BOOLEAN | ✓ | Успешно применено к WB |
| wb_response | JSONB | | |
| error | TEXT | | |

**action ENUM:**

`keep`, `raise_bid`, `lower_bid`, `exclude_keyword`, `retest_keyword`, `pause_campaign`, `resume_campaign`, `topup_budget`, `skip`, `alert`

**reason_code (примеры):**

`CTR_OK_CPC_OK`, `OVERPAYING_BID`, `NOT_PROFITABLE_TOP`, `DEMPPING_NEIGHBOR`, `STOCK_SLOW`, `WB_BROKEN_DAY`, `BELOW_100_SHOWS`, `TEST_PERIOD`, `MANUAL_OVERRIDE`

### 4.8. Таблица `unit_economics`

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| product_id | INT FK | ✓ | UNIQUE |
| nm_id | VARCHAR(20) | ✓ | |
| cost_price_rub | DECIMAL(10,2) | ✓ | Себестоимость |
| retail_price_rub | DECIMAL(10,2) | ✓ | Текущая цена |
| margin_pct | DECIMAL(6,2) | ✓ | |
| max_drr_pct | DECIMAL(6,2) | ✓ | default 15 |
| max_cpc_kopecks | INT | | Вычисляемое |
| max_cpm_kopecks | INT | | Вычисляемое |
| target_margin_pct | DECIMAL(6,2) | | |
| wb_commission_pct | DECIMAL(6,2) | | |
| logistics_rub | DECIMAL(10,2) | | |
| source | ENUM | ✓ | `manual`, `import`, `calculated` |
| valid_from | DATE | ✓ | |
| updated_at | TIMESTAMPTZ | ✓ | |

### 4.9. Таблица `advert_project_settings`

Настройки на уровне проекта.

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| project_id | INT FK | ✓ | UNIQUE |
| optimize_cron | VARCHAR(64) | ✓ | default `0 6,12,18,0 * * *` |
| parser_interval_min | SMALLINT | ✓ | default 5 |
| global_max_bid_kopecks | INT | ✓ | default 150000 |
| global_max_topup_kopecks | INT | ✓ | default 300000 |
| auto_topup_enabled | BOOLEAN | ✓ | default false (MVP) |
| telegram_alert_chat_id | VARCHAR(64) | | |

### 4.10. Таблица `wb_credentials`

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | SERIAL PK | ✓ | |
| name | VARCHAR(128) | ✓ | |
| api_token_encrypted | TEXT | ✓ | AES-256 |
| token_scope | JSONB | | promotion, analytics, content |
| is_active | BOOLEAN | ✓ | |
| last_check_at | TIMESTAMPTZ | | |
| last_error | TEXT | | |

---

## 5. Интеграция с WB API

### 5.1. Используемые методы (type 9, актуально на 06.2026)

| Операция | Метод WB API | Частота |
|----------|--------------|---------|
| Список кампаний | `GET /api/advert/v2/adverts` | 1×/час |
| Детали кампании | `GET /api/advert/v2/adverts?id[]=` | по sync |
| Мин. ставки | `GET /api/advert/v1/bids/min` (v2) | перед изменением |
| Изменение ставок | `PATCH /api/advert/v1/bids` | по решению optimizer |
| Статистика ключей | `POST /adv/v0/normquery/stats` | 4×/день |
| Full stats | `GET /adv/v3/fullstats` | 4×/день |
| Минус-ключи | `POST setNormqueryMinus` | по решению |
| Ставки на кластеры | `POST setNormqueryBids` | по решению |
| Пауза/старт | `GET /adv/v0/start`, `/pause` | по schedule |
| Баланс | `GET /adv/v1/balance` | 1×/час |
| Пополнение | `POST /adv/v1/budget/deposit` | v1.1 |
| Заказы (общие) | Analytics API / Orders | каждые 5–15 мин |
| Остатки | Marketplace API | каждые 30 мин |
| Рек. ставки | recommended bids method | опционально |

**Важно:** все суммы в **копейках** (1 ₽ = 100).

### 5.2. Sync Worker — алгоритм

```
Каждые 15 мин (настраиваемо):
1. GET adverts → обновить advert_campaign_links
2. POST normquery/stats → обновить shows, clicks, spend по ключам
3. Пересчитать ctr_calculated, cpc_calculated_kopecks
4. Обновить shows_total; если ≥100 → status = managed
5. GET orders (общие по nm_id) → orders_period
6. GET stocks → stock_total, delivery estimate
7. Записать advert_snapshot (type=campaign)
8. Обновить last_sync_at
```

**Учёт лага WB:** данные до 03:00 — «вчерашние»; решения optimizer используют snapshots ≥2ч давности для primary keys.

### 5.3. Position Parser — алгоритм

```
Каждые parser_interval_min (default 5):
Для каждого active advert_profile:
  Для keyword WHERE status IN (managed, all) AND keyword_class IN (primary, secondary):
    1. GET wb.ru/search?query={keyword}
    2. Найти nm_id в выдаче → parsed_position
    3. Записать advert_snapshot (type=keyword)
    4. Обновить advert_keywords.last_parsed_position

  Для advert_competitor_shelves WHERE enabled:
    1. GET wb.ru/catalog/{competitor_nm_id}
    2. Найти nm_id в блоке рекомендаций → last_position
    3. Записать snapshot (type=shelf)
    4. Зафиксировать neighbor_price_rub ближайших карточек
```

**Требования к парсеру:**

- Ротация User-Agent
- Rate limit: не чаще 1 req / 3 sec / IP
- Retry 3× с backoff
- Не использовать авторизованную сессию WB
- Расхождение с API >3 позиций → flag `position_mismatch`

---

## 6. Decision Engine (Optimizer)

### 6.1. Входные данные цикла

```python
OptimizeContext:
  profile: AdvertProfile
  campaigns: list[AdvertCampaignLink]
  keywords: list[AdvertKeyword]
  shelves: list[AdvertCompetitorShelf]
  unit_economics: UnitEconomics
  snapshots: list[AdvertSnapshot]  # за последние min_test_hours
  project_settings: AdvertProjectSettings
  global_flags: WBFlags  # broken_day, etc.
```

### 6.2. Порядок выполнения цикла

```
PHASE 0: PRE-FLIGHT CHECKS
  IF stock_total == 0 → PAUSE all, reason=NO_STOCK, EXIT
  IF delivery_days > 2 → PAUSE all, reason=SLOW_DELIVERY, EXIT
  IF global_flags.wb_broken_day → PAUSE all, reason=WB_BROKEN_DAY, EXIT
  IF unit_economics is NULL → SKIP optimize, ALERT, EXIT

PHASE 1: KEYWORD OPTIMIZATION (search_manual campaign)
  FOR keyword IN keywords WHERE status != excluded:
    
    IF status == pending_100_shows:
      IF shows_total >= 100 → promote to managed
      ELSE → SKIP (общая min ставка)
      CONTINUE

    snapshots_kw = get_snapshots(keyword, hours=min_test_hours)
    IF len(snapshots_kw) < 2 OR time_span < min_test_hours:
      → SKIP, reason=TEST_PERIOD
      CONTINUE

    ctr = calc_ctr(snapshots_kw)
    cpc = calc_cpc(snapshots_kw)
    position = median_parsed_position(snapshots_kw)

    # Проверка демпинга
    IF has_cheap_neighbors(keyword, threshold=30% below our price):
      → EXCLUDE or LOWER grade, reason=DEMPPING_NEIGHBOR
      CONTINUE

    # Primary keys
    IF keyword.keyword_class == primary:
      IF position_grade_met(position, target_grade=top_1_3):
        IF ctr >= benchmark_ctr AND cpc <= unit_economics.max_cpc:
          → KEEP
        ELIF cpc > max_cpc:
          → LOWER_BID (step 5-10%), reason=OVERPAYING_BID
        ELSE:
          → KEEP, reason=CTR_LOW_BUT_ACCEPTABLE
      ELSE:
        IF can_afford_higher_bid(unit_economics):
          → RAISE_BID (step 5%), max=max_bid_kopecks
        ELSE:
          → LOWER target_grade to pos_4_10, reason=NOT_PROFITABLE_TOP

    # Secondary keys
    IF keyword.keyword_class == secondary:
      IF profitable_at(position, pos_10_20, ctr, cpc, unit_economics):
        → KEEP at pos_10_20
      ELSE:
        → EXCLUDE, schedule retest in 30 days

    # Irrelevant
    IF keyword.keyword_class == irrelevant:
      → EXCLUDE immediately

PHASE 2: BASE BID (unmanaged keys)
  SET campaign.base_bid = min_bid_kopecks  # всегда минимум

PHASE 3: SHELF CHECK (v1.1)
  ...

PHASE 4: SCHEDULE
  IF schedule_mode == night_off AND hour NOT IN [wake..sleep]:
    → PAUSE campaigns
  ELIF schedule_mode == night_off AND hour IN [wake..sleep]:
    → RESUME campaigns

PHASE 5: BUDGET (v1.1)
  IF roi_positive AND balance < threshold:
    → TOPUP min(needed, max_topup_kopecks)

PHASE 6: COMMIT
  Apply all pending decisions to WB API
  Write advert_decisions
  Update last_optimize_at
```

### 6.3. Формулы

```
CTR = clicks / shows                          (shows > 0)
CPC_kopecks = spend_kopecks / clicks          (clicks > 0)
DRR = spend / (orders * retail_price)         (orders > 0)

max_cpc_kopecks = (retail_price - cost - logistics - commission) 
                  * (max_drr_pct / 100) 
                  / expected_cr_to_order

position_grade_met(pos, grade):
  top_1_3    → pos <= 3  (WB может давать 4 слота — считаем 1-4)
  pos_4_10   → 4 <= pos <= 10
  pos_10_20  → 10 <= pos <= 20

bid_step = max(500, current_bid * 0.05)       # мин 5 ₽ или 5%
```

### 6.4. Hard limits (не переопределяются)

| Лимит | Значение |
|-------|----------|
| max_bid_kopecks | ≤ 150000 (1500 ₽) |
| max_topup | ≤ 300000 (3000 ₽) за операцию |
| min_test_hours | ≥ 2 перед изменением ставки |
| max_active_campaigns | ≤ 2 на nm_id |
| shelf_bid_premium | ≤ 5000 kopecks (50 ₽) над min |
| optimize_frequency | ≥ 2 цикла / 24ч на active SKU |

---

## 7. API спецификация (новые эндпоинты)

### 7.1. REST API

#### `GET /api/advert/products`

**Query:** `project_id`, `status`, `advert_enabled`, `page`, `limit`

**Response 200:**

```json
{
  "items": [{
    "product_id": 42,
    "nm_id": "123456789",
    "product_name": "Перчатки красные",
    "advert_status": "active",
    "advert_enabled": true,
    "primary_keyword": "перчатки для уборки",
    "parsed_position": 3,
    "ctr": 0.13,
    "cpc_kopecks": 760,
    "drr_pct": 8.2,
    "last_optimize_at": "2026-06-28T06:15:00Z",
    "needs_attention": false,
    "attention_reasons": []
  }],
  "total": 48,
  "page": 1
}
```

#### `GET /api/advert/products/{product_id}/profile`

Полный профиль + campaigns + unit_economics summary.

#### `PATCH /api/advert/products/{product_id}/profile`

**Body:**

```json
{
  "advert_enabled": true,
  "category_type": "goods",
  "schedule_mode": "always_on",
  "volume_priority": "balanced",
  "max_bid_kopecks": 150000
}
```

#### `GET /api/advert/products/{product_id}/keywords`

Список ключей с метриками и статусами.

#### `POST /api/advert/products/{product_id}/keywords/{keyword_id}/bid`

**Body:** `{ "bid_kopecks": 85000, "reason": "manual override" }`

#### `POST /api/advert/products/{product_id}/keywords/{keyword_id}/exclude`

**Body:** `{ "reason": "нерелевантный ключ" }`

#### `POST /api/advert/products/{product_id}/keywords/{keyword_id}/retest`

Снять из excluded, поставить `retest_after = null`, status = managed.

#### `GET /api/advert/products/{product_id}/snapshots`

**Query:** `from`, `to`, `keyword_id`, `type`

#### `GET /api/advert/products/{product_id}/decisions`

**Query:** `from`, `to`, `action`, `page`

#### `POST /api/advert/products/{product_id}/sync`

Принудительный sync с WB. **Response:** `{ "synced_at", "keywords_updated", "campaigns_updated" }`

#### `POST /api/advert/products/{product_id}/optimize`

Запуск одного цикла optimizer. **Response:** `{ "decisions_count", "applied", "skipped", "errors" }`

#### `POST /api/advert/products/{product_id}/pause` / `resume`

#### `GET /api/advert/dashboard`

Агрегаты по project: total spend, avg DRR, SKU needing attention.

#### `POST /api/advert/import/unit-economics`

**Body:** CSV/JSON bulk import.

#### `POST /api/webhook/n8n/advert-cycle/{product_id}`

Триггер n8n → optimize + sync.

#### `POST /api/webhook/n8n/advert-parse/{nm_id}`

Приём результатов парсера:

```json
{
  "nm_id": "123456789",
  "keyword": "перчатки для уборки",
  "parsed_position": 3,
  "neighbors": [{"nm_id": "...", "price_rub": 298, "position": 1}],
  "parsed_at": "2026-06-28T12:05:00Z"
}
```

### 7.2. HTML UI (новые страницы)

| URL | Описание |
|-----|----------|
| `GET /advert` | Сводный дашборд проекта |
| `GET /advert/settings` | WB token, cron, лимиты (admin) |
| `GET /products/{id}/advert` | Реклама карточки (вкладки) |
| `GET /products/{id}/advert/keywords` | Таблица ключей |
| `GET /products/{id}/advert/decisions` | Лог решений |
| `GET /products/{id}/advert/charts` | Графики position vs orders |

**UI-требования:**

- Стиль — наследовать `/static/style.css`
- На главной `/` — badge «Реклама: active/paused» у каждого product
- Цветовая индикация: зелёный = ok, жёлтый = needs attention, красный = paused/blocked
- Кнопки: Sync, Optimize now, Pause/Resume
- Таблица ключей: sortable по CTR, CPC, position, spend

---

## 8. n8n Workflows

### 8.1. Workflow: `advert-daily-cycle`

```
Trigger: Cron 0 6,12,18,0 * * *
  → GET /api/advert/products?advert_enabled=true&status=active
  → Split in batches (5)
  → POST /api/advert/products/{id}/sync
  → Wait 30s
  → POST /api/advert/products/{id}/optimize
  → IF needs_attention → Telegram alert
```

### 8.2. Workflow: `advert-position-parser`

```
Trigger: Cron */5 * * * *
  → GET keywords WHERE primary OR secondary AND active
  → HTTP Request WB search (parser service)
  → POST /api/webhook/n8n/advert-parse/{nm_id}
```

### 8.3. Workflow: `advert-morning-wake`

```
Trigger: Cron 0 6 * * *
  → GET profiles WHERE schedule_mode=night_off
  → POST resume campaigns
```

---

## 9. Нефункциональные требования

### 9.1. Производительность

| Метрика | Target |
|---------|--------|
| Optimize 1 SKU | ≤ 30 sec |
| Full cycle 50 SKU | ≤ 30 min |
| API response (read) | ≤ 500 ms p95 |
| Parser latency | ≤ 10 sec / keyword |

### 9.2. Надёжность

- Optimizer: retry WB API 3×, exponential backoff
- При 5xx WB → pause SKU, не менять ставки
- Redis queue: dead letter после 3 failures
- **Задвоение optimizer (v1.1):** active-passive для critical path

### 9.3. Безопасность

- WB token — encrypted at rest (AES-256-GCM)
- API advert — те же session cookies / auth что у портала
- Audit log — append-only (no delete)
- Rate limit optimize: 1 req / 5 min / product (anti double-run)

### 9.4. Мониторинг

- `/health` расширить: `{ "advert": { "last_sync", "queue_depth", "parser_ok" } }`
- Telegram alerts: optimize errors, bid limit hit, WB token expired

---

## 10. Этапы разработки и критерии приёмки

### Фаза 0: Foundation (1–2 недели)

**Задачи:**

- [ ] Миграции БД (все таблицы §4)
- [ ] `wb_credentials` + test connection
- [ ] Sync worker: campaigns + normquery stats (read-only)
- [ ] `GET /api/advert/products`, `GET profile`
- [ ] UI: `/advert` read-only таблица

**Приёмка:**

- Подключён WB token, видны кампании type 9 для 5 тестовых nm_id
- Ключи подтягиваются с shows/clicks/spend
- CTR/CPC считаются корректно (сверка с Excel менеджера ±5%)

---

### Фаза 1: Data Layer (2–3 недели)

**Задачи:**

- [ ] Position parser (service + webhook)
- [ ] `advert_snapshots` запись каждые 5 мин
- [ ] Import unit_economics (CSV + UI)
- [ ] Charts: position vs time

**Приёмка:**

- Parser показывает позицию ±1 от ручной проверки менеджера
- Snapshots хранятся 90 дней
- Unit economics импортированы для 50 SKU

---

### Фаза 2: Search Optimizer MVP (3–4 недели)

**Задачи:**

- [ ] Decision engine (§6)
- [ ] Bid change через WB API
- [ ] Exclude/retest keywords
- [ ] `advert_decisions` audit log
- [ ] n8n daily-cycle workflow
- [ ] UI: keywords table + decisions log + manual override

**Приёмка:**

- 10 pilot SKU работают 7 дней автономно
- Алина подтверждает: ≥80% решений совпали бы с её ручными
- 0 случаев bid > 1500 ₽
- 2+ цикла/день выполняются по cron
- Лог содержит reason для каждого действия

---

### Фаза 3: Shelves + Schedule (2 недели)

**Задачи:**

- [ ] `advert_competitor_shelves` UI + parser
- [ ] Recommendations campaign logic
- [ ] night_off schedule (wake 6–7, sleep 23)
- [ ] Pre-flight: delivery, stock, broken day flag

**Приёмка:**

- Полки Patera/Lamber отслеживаются для перчаток
- Кампании включаются в 06:00, выключаются в 23:00 (where configured)

---

### Фаза 4: Budget + CPC (1–2 недели)

**Задачи:**

- [ ] Auto topup ≤ 3000 ₽ при ROI+
- [ ] CPC fallback campaign для liquidation SKUs
- [ ] Telegram alerts

**Приёмка:**

- Topup не превышает 3000 ₽
- Liquidation SKU получают CPC кампанию по правилам

---

## 11. Пилотные карточки (эталон для тестов)

| SKU | nm_id (пример) | Особенности | Ожидаемое поведение |
|-----|----------------|-------------|---------------------|
| Перчатки красные | TBD | primary + shelves, 24/7 | top_1_3 по «перчатки для уборки» |
| Перчатки зелёные | TBD | только unified, полки | min bid, 200 orders из полок |
| Перчатки жёлтые | TBD | частый rollback позиции | pos_4_10 acceptable |
| Салфетки стёкла | TBD | топ не окупается | pos_10_20, max bid ~3000₽ |
| Салфетки безворсовые | TBD | демпинг конкурентов | pause при 60₽ соседях |

---

## 12. Связь с Content-модулем (v2.1)

| Триггер (Advert) | Действие (Content) |
|------------------|-------------------|
| CTR ↓ 20% при ok position | Alert → regenerate cover slide |
| position ok, conversion ↓ | Check Jam benchmark → generate/texts |
| new product, advert_status=new | Skip optimize, min bid only |
| A/B cover test running | Pause bid changes on that SKU |

Endpoint: `POST /api/advert/products/{id}/content-signal`

---

## 13. Открытые вопросы (для согласования)

| № | Вопрос | Варианты | Рекомендация |
|---|--------|----------|--------------|
| 1 | Parser: свой сервис или n8n+Playwright? | A) Python microservice B) n8n | A — стабильнее |
| 2 | Queue: Redis/Celery или только n8n? | A) Redis B) n8n | A для optimize, n8n для cron |
| 3 | Создание РК через API в v2? | Да/Нет | Нет в v1, менеджер создаёт вручную |
| 4 | Jam API интеграция | Авто / ручной import | Ручной import раз в 3 мес |
| 5 | Несколько WB кабинетов | Multi-tenant | 1 token в v1 |

---

## 14. Deliverables

| Артефакт | Формат |
|----------|--------|
| Миграции БД | SQL / Alembic |
| OpenAPI extension | `/openapi.json` v2.0.0 |
| Decision engine | Python module `advert/optimizer.py` |
| Parser service | Python `advert/parser/` |
| n8n workflows | JSON export × 3 |
| UI templates | Jinja2 HTML |
| Unit economics template | CSV |
| Runbook | MD: deploy, token setup, pilot checklist |

---

## 15. Definition of Done (весь модуль)

- [ ] 50 SKU подключены, advert_enabled=true
- [ ] Optimizer работает 14 дней без критических инцидентов
- [ ] DRR в пределах target на ≥70% primary keys
- [ ] Менеджер тратит ≤30 мин/день вместо 3+ часов
- [ ] Audit log покрывает 100% изменений ставок
- [ ] Документация и runbook переданы

---

## История изменений

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 28.06.2026 | Первый релиз ТЗ |

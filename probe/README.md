# Зонд свежести данных WB (issue #20)

Standalone-скрипт на хосте germany: каждые 10 минут снимает `fullstats` и `normquery/stats`
по двум живым кампаниям. Спека: `docs/PROBE_FRESHNESS.md`.

## Зависимости

На хосте достаточно `python3.12` и `requests` (уже установлены). Пакет `wb_advert` не нужен.

## Запуск вручную

```bash
cd /opt/wb_malibri
python3.12 probe/freshness_probe.py
```

Токен читается из `/opt/wb-advert/.env` (`WB_API_TOKEN`). Переменные для отладки:

| Переменная | По умолчанию |
|------------|--------------|
| `PROBE_DATA_DIR` | `/opt/wb_malibri/data/probe` |
| `WB_ENV_PATH` | `/opt/wb-advert/.env` |
| `WB_PROD_LOCK` | `/tmp/wb-advert-cycle.lock` |

Перед API-запросами скрипт проверяет боевой лок (не удерживает его). Если продовый цикл уже
работает — такт пропускается (exit 0, строка в CSV с `skipped_tact=1`).

За цикл: **1** `fullstats` на обе кампании (`ids=31275686,31314341`) + **2** `normquery/stats`.

## Cron

Файл `deploy/wb-advert-probe.cron` — для `/etc/cron.d/`. Установку делает владелец после ревью:

```bash
sudo cp deploy/wb-advert-probe.cron /etc/cron.d/wb-advert-probe
sudo chmod 644 /etc/cron.d/wb-advert-probe
```

Шаг `*/10`, свой lock-файл `/tmp/wb-advert-probe.lock` (чтобы подвисший такт не наслаивался).

Зонд **не удерживает** боевой лок `/tmp/wb-advert-cycle.lock` — только проверяет, занят ли он,
и сразу отпускает. Если занят — такт пропускается.

## Куда пишутся данные

```
data/probe/
  raw/<UTC-дата>/<HHMM>_fullstats.json.gz                         # обе кампании
  raw/<UTC-дата>/<HHMM>_<advert_id>_normquery_stats.json.gz
  flat/probe_<UTC-дата>.csv   # по строке на дневную корзину (вчера + сегодня на кампанию)
  logs/                                                   # stderr из cron (если настроен)
```

Ретеншн: при старте удаляется всё в `raw/` и `flat/` старше 14 суток.

## Как снять

```bash
# последний CSV
ls -lt /opt/wb_malibri/data/probe/flat/ | head
tail -5 /opt/wb_malibri/data/probe/flat/probe_$(date -u +%F).csv

# сырьё за сегодня (UTC)
ls /opt/wb_malibri/data/probe/raw/$(date -u +%F)/

# распаковать один файл
zcat /opt/wb_malibri/data/probe/raw/2026-07-25/1030_31275686_fullstats.json.gz | python3 -m json.tool | head
```

## Тесты

```bash
python3 -m pytest probe/tests/ -q
```

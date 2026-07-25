# Деплой wb_advert на Linux-сервер (germany)

Сервер: `ssh germany` (95.85.252.147, root). Цель по roadmap — **интеграция в портал wb_pars** (маршрут `/advert`), пилотный веб можно поднять и автономно.

## 0. Предпосылки
- Python 3.11+
- Каталог кода: например `/opt/wb_malibri` (GitHub — первоисточник, разворачиваем через git).
- Зависимости лёгкие: fastapi, uvicorn, httpx, pydantic, jinja2 (см. `wb_advert/requirements.txt`).

## 1. Код и окружение
```bash
ssh germany
git clone https://github.com/valeryannkkaaa/wb_malibri.git /opt/wb_malibri
cd /opt/wb_malibri
python3 -m venv .venv && . .venv/bin/activate
pip install -r wb_advert/requirements.txt
```

## 2. Секреты (.env, НЕ коммитить)
```bash
cp wb_advert/.env.example wb_advert/.env
# заполнить WB_API_TOKEN=... (и POLZA_AI_API_KEY при использовании оптимизатора с LLM)
```
`.env` уже в `.gitignore` — токен живёт только на сервере.

## 3a. Автономный веб (пилот/дев)
```bash
WB_ADVERT_HOST=127.0.0.1 WB_ADVERT_PORT=8765 ./wb_advert/run_server.sh
```
Прод: за nginx-reverse-proxy, без `--reload` (по умолчанию reload выключен; включается `WB_ADVERT_RELOAD=1`).
systemd-юнит для веба (пример):
```ini
# /etc/systemd/system/wb-advert-web.service
[Unit]
Description=WB Advert dashboard
After=network.target
[Service]
WorkingDirectory=/opt/wb_malibri
Environment=WB_ADVERT_HOST=127.0.0.1
Environment=WB_ADVERT_PORT=8765
ExecStart=/opt/wb_malibri/.venv/bin/python -m uvicorn wb_advert.app:app --host 127.0.0.1 --port 8765
Restart=on-failure
[Install]
WantedBy=multi-user.target
```

## 3b. Интеграция в портал wb_pars (целевой вариант)
Портал wb_pars — FastAPI (`portal/app/main.py`). Интеграция:
1. Сделать `wb_advert` устанавливаемым/импортируемым из окружения портала (общий venv или как зависимость).
2. Подключить роутер: `from wb_advert.api.routes import router as advert_router; app.include_router(advert_router, prefix="/api/advert")`.
3. Перенести страницы `/advert*` из `wb_advert/app.py` в портал (или смонтировать под-приложение через `app.mount("/advert", advert_app)`).
4. Джинжа-шаблоны и `static/advert.css` — подключить в шаблонизатор портала.
5. БД: пилот работает на файлах (`data/pilot/`), Postgres (`db/models.py`, `db/migrations/001_advert_schema.sql`) — подключать при переносе состояния в БД портала. На старте можно оставить файловое хранилище.

## 4. Пайплайн по расписанию (обязательно, независимо от 3a/3b)
Дневной цикл (sync → optimizer → parse → stocks → snapshots) должен идти по расписанию. На Linux — cron или systemd timer.

Cron (пример, ежедневно в 03:00):
```cron
0 3 * * * cd /opt/wb_malibri && . .venv/bin/activate && ./wb_advert/run_daily_cycle.sh >> /var/log/wb_advert_cycle.log 2>&1
```
Или systemd timer, вызывающий `run_daily_cycle.sh`. Разовый синк одной кампании: `./wb_advert/run_sync.sh <ADVERT_ID>`.

## 5. Данные
`data/pilot/` привязан к пакету (пути не зависят от CWD). Каталог должен быть на постоянном пути и с правами на запись у сервисного пользователя.

## Скрипты (Linux-аналоги .ps1)
| Windows | Linux |
|---|---|
| `run_server.ps1` | `run_server.sh` |
| `run_sync.ps1` | `run_sync.sh` |
| `run_daily_cycle.ps1` | `run_daily_cycle.sh` |
| `run_import.ps1` | `run_import.sh` |

Windows-скрипты (`.ps1`) сохранены для разработчиков на Windows.

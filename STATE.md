# STATE — wb_malibri (модуль рекламы WB, клиент Малибри)

Обновлено 25.07.2026. Файл перезаписывается, а не дописывается.

## Что сейчас

Интеграционная ветка **`feature/docker-advert-germany`** = `origin` = germany. `main` отстаёт
намеренно: мержим после сдачи проекта. Стенд https://wb.zhukovlab.ru/advert — **тестовая** среда.
Оптимизатор в режиме `suggest-only`, `allow_wb_writes=false` — только советует.

Сбор данных из ВБ (issues #15–#19) закончен 23.07 и работает по cron каждые 4 часа. Покрытие
пилотных карточек ротацией на 25.07: воронка 9/10, поисковый отчёт 7/10, позиции и конкуренты —
ежедневно без пропусков. Последний прогон оптимизатора: `lower_bid` 18, `raise_bid` 1, `keep` 2.

## Блокеры и долги

1. **Ротировать WB API-токен** — лежал в публичном репо в `wb_advert_probe/Untitled` с начального
   коммита. Файл убран (`cd08dd9`), история не переписана, поэтому нужна ротация в ЛК ВБ, затем
   новый токен в `/opt/wb-advert/.env` на germany и рестарт `wb-advert`.
2. **issue #10** — портальная шапка живёт на germany незакоммиченной (`app.py`, `advert.css`,
   `_nav.html`, `_portal_nav.html`). Любой `git pull` мимо нас её снесёт, бэкап в `/root/backups/`.
3. **issue #20** — зонд свежести данных ВБ, спека в `docs/PROBE_FRESHNESS.md`, код не начат.
4. Перед включением записи ставок добавить ограничение «не чаще раза в сутки на ключ»: алгоритм ВБ
   переобучается 24–72 ч.
5. 87% ключей на приорной оценке CR (7-дневное окно рекламы). Теперь есть воронка за 365 дней и
   поисковый отчёт — можно кормить оптимизатор их конверсиями. Issue не заведён.
6. Неатомарная запись файлов в `keywords_store`/`search_report_store`/`funnel_store`. Issue не заведён.
7. Два источника позиций не сведены: парсер выдачи vs `median_position`. Владелец отложил.

## Как запустить локально

```bash
cd wb_advert && cp .env.example .env   # вписать WB_API_TOKEN
python -m scripts.sync_once
python -m scripts.run_optimizer
uvicorn wb_advert.app:app --reload
```

## Как задеплоить

```bash
ssh germany && cd /opt/wb_malibri
git pull                                # ОСТОРОЖНО: пункт 2 выше, 4 файла шапки незакоммичены
docker compose -f deploy/wb-advert.compose.yml up -d --build
docker exec wb-advert bash -lc "cd /app/wb_advert && python -m scripts.run_optimizer"
```

Последняя строка обязательна: дашборд показывает **сохранённые** решения, без прогона видны старые.
Боевой cron: `/etc/cron.d/wb-advert`, каждые 4 часа под `flock /tmp/wb-advert-cycle.lock`.

## Правило работы

Задача → допрос владельца → issue в `valeryannkkaaa/wb_malibri` → исполнитель в orca-worktree →
проверка мутациями продакшн-кода → мерж в интеграционную → деплой → **живая проверка своими
глазами** → ревью комментарием в issue. Отчётам исполнителя не верить.

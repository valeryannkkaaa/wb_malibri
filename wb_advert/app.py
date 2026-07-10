"""Standalone FastAPI app for Phase 1 read-only advert dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from wb_advert.api.routes import router as advert_api_router
from wb_advert.optimizer.engine import optimize_product
from wb_advert.storage.config_store import get_parser_settings
from wb_advert.storage.cycle_health import load_cycle_health
from wb_advert.storage.pilot_store import build_dashboard, get_product_detail
from wb_advert.storage.chart_data import build_ctr_chart, build_position_chart
from wb_advert.storage.decisions_store import load_decisions_audit
from wb_advert.storage.positions_store import load_position_history
from wb_advert.ui.jinja_env import templates as _TEMPLATES

_PKG = Path(__file__).resolve().parent

app = FastAPI(title="WB Advert Module", version="0.2.0")
app.include_router(advert_api_router, prefix="/api/advert", tags=["advert"])

if (_PKG / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(_PKG / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
@app.get("/advert", response_class=HTMLResponse)
@app.get("/advert/", response_class=HTMLResponse)
def index(request: Request):
    dash = build_dashboard()
    cycle = load_cycle_health()
    return _TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {"dash": dash, "cycle": cycle, "active": "dashboard"},
    )


@app.exception_handler(404)
async def not_found(request: Request, _exc):
    path = request.url.path
    hint = (
        "Запустите сервер: <code>./wb_advert/run_server.sh</code> (Linux) "
        "или <code>wb_advert\\run_server.ps1</code> (Windows)<br>"
        "Дашборд: <a href='/'>/</a> или <a href='/advert'>/advert</a><br>"
        "Audit log: <a href='/advert/decisions'>/advert/decisions</a>"
    )
    body = f"<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'><title>404</title>"
    body += "<link rel='stylesheet' href='/static/advert.css'></head><body>"
    body += f"<h1>Страница не найдена</h1><p class='muted'><code>{path}</code></p><p>{hint}</p>"
    body += "<p><a href='/'>← На дашборд</a></p></body></html>"
    return HTMLResponse(body, status_code=404)


@app.get("/advert/decisions", response_class=HTMLResponse)
def decisions_page(request: Request):
    audit = load_decisions_audit(limit=200)
    return _TEMPLATES.TemplateResponse(
        request,
        "decisions.html",
        {"rows": audit, "cycle": load_cycle_health(), "active": "decisions"},
    )


@app.get("/advert/products/{advert_id}", response_class=HTMLResponse)
def product_page(request: Request, advert_id: int):
    product = get_product_detail(advert_id)
    if not product:
        return HTMLResponse("Campaign not found", status_code=404)
    suggestions = optimize_product(advert_id)
    primary = (product.get("primary_keyword") or "").strip().lower()
    keywords = product.get("keywords") or []
    for k in keywords:
        k["is_primary"] = (k.get("keyword") or "").strip().lower() == primary if primary else False
    keywords_sorted = sorted(keywords, key=lambda k: (-int(k.get("shows") or 0), k.get("keyword") or ""))
    rk = get_parser_settings()["region_key"]
    history = load_position_history(product["nm_id"], limit=10, region_key=rk)
    pos_chart = build_position_chart(product["nm_id"], region_key=rk)
    ctr_chart = build_ctr_chart(
        advert_id,
        product.get("primary_keyword") or "",
        region_key=rk,
    )
    return _TEMPLATES.TemplateResponse(
        request,
        "product.html",
        {
            "p": product,
            "opt": suggestions,
            "keywords_sorted": keywords_sorted,
            "position_history": history,
            "pos_chart": pos_chart,
            "pos_chart_json": json.dumps(pos_chart, ensure_ascii=False),
            "ctr_chart_json": json.dumps(ctr_chart, ensure_ascii=False),
            "active": "dashboard",
        },
    )


def main() -> None:
    import os

    import uvicorn

    host = os.getenv("WB_ADVERT_HOST", "127.0.0.1")
    port = int(os.getenv("WB_ADVERT_PORT", "8765"))
    reload = os.getenv("WB_ADVERT_RELOAD", "0") == "1"
    uvicorn.run("wb_advert.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()

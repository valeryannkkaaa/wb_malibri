"""Standalone FastAPI app for Phase 1 read-only advert dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wb_advert.api.routes import router as advert_api_router
from wb_advert.optimizer.engine import optimize_product
from wb_advert.storage.pilot_store import build_dashboard, get_product_detail

_PKG = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_PKG / "templates"))

app = FastAPI(title="WB Advert Module", version="0.2.0")
app.include_router(advert_api_router, prefix="/api/advert", tags=["advert"])

if (_PKG / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(_PKG / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    dash = build_dashboard()
    return _TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {"dash": dash},
    )


@app.get("/advert/products/{advert_id}", response_class=HTMLResponse)
def product_page(request: Request, advert_id: int):
    product = get_product_detail(advert_id)
    if not product:
        return HTMLResponse("Campaign not found", status_code=404)
    suggestions = optimize_product(advert_id)
    return _TEMPLATES.TemplateResponse(
        request,
        "product.html",
        {"p": product, "opt": suggestions},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("wb_advert.app:app", host="127.0.0.1", port=8765, reload=True)


if __name__ == "__main__":
    main()

"""
FastAPI routes — mount in portal or run via wb_advert.app.

    from wb_advert.api.routes import router as advert_router
    app.include_router(advert_router, prefix="/api/advert", tags=["advert"])
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from wb_advert.config import require_token
from wb_advert.optimizer.engine import optimize_all, optimize_product
from wb_advert.schemas.api import DashboardResponse, ProductDetailResponse, ProductSummary
from wb_advert.schemas.optimizer import OptimizeResult
from wb_advert.schemas.sync import SyncProfileResult
from wb_advert.storage.decisions_store import append_decisions, load_recent_decisions
from wb_advert.storage.keywords_store import save_keywords
from wb_advert.storage.pilot_store import build_dashboard, get_product_detail, pilot_data_dir
from wb_advert.sync.worker import SyncWorker

router = APIRouter()


@router.get("/health")
def advert_health():
    return {"module": "wb_advert", "version": "0.2.0", "phase": 1}


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard():
    data = build_dashboard()
    return DashboardResponse(
        optimizer_mode=data["optimizer_mode"],
        synced_at=data.get("synced_at"),
        product_count=data["product_count"],
        total_keywords=data["total_keywords"],
        total_orders_7d=data["total_orders_7d"],
        with_economics=data["with_economics"],
        keywords_saved=data["keywords_saved"],
        products=[ProductSummary(**p) for p in data["products"]],
    )


@router.get("/products", response_model=list[ProductSummary])
def list_products():
    return [ProductSummary(**p) for p in build_dashboard()["products"]]


@router.get("/products/by-advert/{advert_id}", response_model=ProductDetailResponse)
def get_product(advert_id: int):
    detail = get_product_detail(advert_id)
    if not detail:
        raise HTTPException(404, f"Campaign {advert_id} not in pilot")
    return ProductDetailResponse(**detail)


@router.get("/products/by-advert/{advert_id}/suggestions", response_model=OptimizeResult)
def get_suggestions(advert_id: int):
    return optimize_product(advert_id)


@router.post("/products/by-advert/{advert_id}/optimize", response_model=OptimizeResult)
def run_optimize(advert_id: int, save: bool = True):
    result = optimize_product(advert_id)
    if save:
        append_decisions(result)
    return result


@router.get("/decisions")
def list_decisions(advert_id: int | None = None, limit: int = 50):
    return load_recent_decisions(advert_id, limit)


@router.post("/optimize-all")
def run_optimize_all(save: bool = True):
    results = optimize_all()
    if save:
        for r in results:
            if r.suggestions:
                append_decisions(r)
    return {
        "count": len(results),
        "with_suggestions": sum(1 for r in results if r.suggestions),
        "results": results,
    }


@router.post("/products/by-advert/{advert_id}/sync", response_model=SyncProfileResult)
def sync_product(advert_id: int):
    require_token()
    detail = get_product_detail(advert_id)
    if not detail:
        raise HTTPException(404, f"Campaign {advert_id} not in pilot")
    nm_id = int(detail["nm_id"])
    worker = SyncWorker(pilot_csv=pilot_data_dir() / "pilot_skus.csv")
    result = worker.sync_profile(
        nm_id_label=detail["nm_id"],
        wb_campaign_id=advert_id,
        resolved_nm_id=nm_id,
        try_resolve_nm=False,
        with_fullstats=False,
    )
    if result.keywords:
        save_keywords(advert_id, nm_id, result.keywords)
    return result

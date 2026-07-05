from __future__ import annotations

from typing import Any


def _fullstats_campaigns(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if "days" in data or "advertId" in data:
            return [data]
        nested = data.get("adverts") or data.get("data") or []
        if isinstance(nested, list):
            return [x for x in nested if isinstance(x, dict)]
    return []


def extract_nm_ids_from_fullstats(data: Any) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for campaign in _fullstats_campaigns(data):
        for day in campaign.get("days") or []:
            if not isinstance(day, dict):
                continue
            for app in day.get("apps") or []:
                if not isinstance(app, dict):
                    continue
                for sku in app.get("nms") or []:
                    if not isinstance(sku, dict):
                        continue
                    nid = sku.get("nmId") or sku.get("nm_id") or sku.get("nm")
                    if nid and int(nid) not in seen:
                        seen.add(int(nid))
                        ids.append(int(nid))
        for booster in campaign.get("boosterStats") or []:
            if isinstance(booster, dict):
                nid = booster.get("nm") or booster.get("nmId")
                if nid and int(nid) not in seen:
                    seen.add(int(nid))
                    ids.append(int(nid))
    return ids

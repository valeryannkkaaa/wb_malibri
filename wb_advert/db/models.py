"""SQLAlchemy models — wire to portal ORM on integration (TZ §4)."""

# Phase 0: schema lives in db/migrations/001_advert_schema.sql
# Phase 0.5: map to portal Base when wb-content-portal FastAPI app is connected

TABLES = (
    "wb_credentials",
    "advert_profiles",
    "advert_campaign_links",
    "advert_keywords",
    "advert_snapshots",
    "advert_decisions",
    "unit_economics",
    "advert_project_settings",
)

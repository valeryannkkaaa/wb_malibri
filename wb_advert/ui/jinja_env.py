"""Shared Jinja2 templates with dashboard filters."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from wb_advert.ui.datetime_fmt import format_dt_msk
from wb_advert.optimizer.grades import position_meets_target
from wb_advert.ui.labels import action_ru, alert_ru, cycle_ru_label, grade_ru, status_ru

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

for _name, _fn in {
    "action_ru": action_ru,
    "status_ru": status_ru,
    "grade_ru": grade_ru,
    "cycle_ru": cycle_ru_label,
    "alert_ru": alert_ru,
    "dt_msk": format_dt_msk,
    "position_meets_target": position_meets_target,
}.items():
    templates.env.filters[_name] = _fn

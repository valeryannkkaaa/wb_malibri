#!/usr/bin/env python
"""Export MANAGER_CHECKLIST.md content to PDF (Cyrillic via system Arial)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("Installing fpdf2...", flush=True)
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "fpdf2"])
    from fpdf import FPDF

HERE = Path(__file__).resolve().parent
OUT = HERE / "MANAGER_CHECKLIST.pdf"

FONT_CANDIDATES = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "Arial.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def find_font() -> Path:
    for p in FONT_CANDIDATES:
        if p.is_file():
            return p
    raise SystemExit("No Cyrillic font found (Arial/DejaVu)")


class ChecklistPDF(FPDF):
    def __init__(self, font_path: Path) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.font_path = font_path
        self._font_ready = False

    def _ensure_font(self) -> None:
        if self._font_ready:
            return
        self.add_font("Body", "", str(self.font_path))
        self.add_font("Body", "B", str(self.font_path))
        self._font_ready = True

    def title_block(self, title: str, subtitle: str) -> None:
        self._ensure_font()
        self.set_font("Body", "B", 16)
        self.multi_cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Body", "", 10)
        self.multi_cell(0, 5, subtitle, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def section(self, heading: str) -> None:
        self._ensure_font()
        if self.get_y() > 250:
            self.add_page()
        self.set_font("Body", "B", 12)
        self.multi_cell(0, 7, heading, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def paragraph(self, text: str) -> None:
        self._ensure_font()
        self.set_font("Body", "", 9)
        self.multi_cell(0, 4.5, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def table(self, headers: list[str], rows: list[list[str]], col_widths: list[float] | None = None) -> None:
        self._ensure_font()
        if col_widths is None:
            w = (self.w - self.l_margin - self.r_margin) / len(headers)
            col_widths = [w] * len(headers)

        if self.get_y() > 240:
            self.add_page()

        self.set_font("Body", "B", 7)
        self.set_fill_color(230, 230, 230)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, h, border=1, fill=True)
        self.ln()

        self.set_font("Body", "", 7)
        for row in rows:
            if self.get_y() > 275:
                self.add_page()
                self.set_font("Body", "B", 7)
                self.set_fill_color(230, 230, 230)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 6, h, border=1, fill=True)
                self.ln()
                self.set_font("Body", "", 7)
            max_h = 6
            x0, y0 = self.get_x(), self.get_y()
            texts: list[str] = []
            for i, cell in enumerate(row):
                texts.append(str(cell))
            for i, cell in enumerate(row):
                self.set_xy(x0 + sum(col_widths[:i]), y0)
                self.multi_cell(col_widths[i], 4, cell, border=1)
                max_h = max(max_h, self.get_y() - y0)
            self.set_xy(x0, y0 + max_h)
        self.ln(2)

    def code_block(self, text: str) -> None:
        self._ensure_font()
        if self.get_y() > 200:
            self.add_page()
        self.set_font("Body", "", 8)
        self.set_fill_color(245, 245, 245)
        for line in text.strip().splitlines():
            self.cell(0, 4.5, "  " + line, border=0, fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)


def build_pdf() -> Path:
    font = find_font()
    pdf = ChecklistPDF(font)
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.title_block(
        "Чеклист сверки — пилот WB Advert (10 SKU)",
        "Дата данных: 07.07.2026  |  Режим: suggest-only (ставки на WB не меняются)\n"
        "Дашборд: http://127.0.0.1:8765  |  Авто-цикл каждые 15 мин, регион Краснодар",
    )

    pdf.section("Блок A — Срочно (~10 мин)")
    pdf.paragraph("A1. Исключить слабые secondary-ключи? Primary остальных кампаний не трогаем.")
    pdf.table(
        ["[ ]", "Камп.", "nm_id", "Ключ", "Статистика", "Решение"],
        [
            ["[ ]", "33206346", "754549033", "перчатка для пыли", "161 пок., 1 кл., 0 зак.", "[ ] искл. [ ] остав. [ ] ждать"],
            ["[ ]", "37636194", "1085061548", "кухонная тряпка", "233 пок., 2 кл., 0 зак.", "[ ] искл. [ ] остав. [ ] ждать"],
        ],
        [8, 18, 22, 38, 52, 52],
    )
    pdf.paragraph("A2. Поднять ставку primary «салфетки для кухни» (37636194): 7.00 → 7.35 ₽ (+5%). Цель SKU: позиции 10–20.")
    pdf.table(
        ["[ ]", "Камп.", "nm_id", "Primary", "Сейчас", "Предлож.", "Решение"],
        [["[ ]", "37636194", "1085061548", "салфетки для кухни", "7.00 ₽", "7.35 ₽", "[ ] да [ ] нет"]],
        [8, 18, 22, 40, 22, 22, 58],
    )

    pdf.section("Блок B — Маржа (~5 мин)")
    pdf.table(
        ["[ ]", "Вопрос", "Сейчас", "Ответ"],
        [
            ["[ ]", "Маржа 9 SKU", "11%", "[ ] OK [ ] правки"],
            ["[ ]", "629004626 тряпка", "12%", "[ ] OK [ ] правки"],
            ["[ ]", "Max DRR", "15%", "[ ] OK [ ] ___%"],
        ],
        [8, 45, 35, 102],
    )
    pdf.paragraph("Эталон: «перчатки для уборки» 624468743 — CTR ~13%, CPC ~7.6 ₽.")

    pdf.section("Блок C — Primary keywords (~10 мин)")
    pdf.table(
        ["[ ]", "Камп.", "nm_id", "Primary", "Цель", "OK?"],
        [
            ["[ ]", "31275686", "624468743", "перчатки для уборки", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "33206346", "754549033", "перчатки для уборки", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "33206165", "754427875", "перчатки резиновые хоз.", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "31314341", "629004626", "тряпка для стекол...", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "35110541", "866360474", "пенящиеся салфетки...", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "35704170", "929900180", "спонж для умывания", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "37328842", "1001645746", "губка для уборки", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "35098216", "754606396", "мочалка варежка...", "топ 1–3", "[ ] да [ ] нет"],
            ["[ ]", "36713559", "869367544", "салфетки 30х30", "10–20", "[ ] да [ ] нет"],
            ["[ ]", "37636194", "1085061548", "салфетки для кухни", "10–20", "[ ] да [ ] нет"],
        ],
        [8, 16, 22, 58, 18, 28],
    )

    pdf.section("Блок D — Сверка WB vs дашборд (~15 мин)")
    pdf.table(
        ["Камп.", "Primary", "Показы", "CTR%", "CPC", "Заказы"],
        [
            ["31275686", "перчатки для уборки", "9658", "16.2", "7.57", "568"],
            ["33206346", "перчатки для уборки", "9053", "10.1", "17.49", "128"],
            ["31314341", "тряпка для стекол...", "4336", "10.7", "8.03", "106"],
        ],
        [18, 52, 18, 14, 18, 18],
    )
    pdf.table(
        ["[ ]", "Камп.", "Совпадает?", "Комментарий"],
        [
            ["[ ]", "31275686", "[ ] да [ ] нет", ""],
            ["[ ]", "33206346", "[ ] да [ ] нет", ""],
            ["[ ]", "31314341", "[ ] да [ ] нет", ""],
        ],
        [8, 22, 40, 120],
    )

    pdf.section("Блок E — Позиции, Краснодар (~10 мин)")
    pdf.table(
        ["[ ]", "nm_id", "Primary", "Система", "OK?"],
        [
            ["[ ]", "624468743", "перчатки для уборки", "pos 3", "[ ] да [ ] нет"],
            ["[ ]", "866360474", "пенящиеся салфетки...", "pos 13", "[ ] да [ ] нет"],
            ["[ ]", "754549033", "перчатки для уборки", "pos 125", "[ ] да [ ] нет"],
            ["[ ]", "1001645746", "губка для уборки", "не топ-500", "[ ] OK [ ] сменить ключ"],
        ],
        [8, 22, 58, 28, 34],
    )

    pdf.section("Блок F — Настройки пилота")
    pdf.table(
        ["Вопрос", "Сейчас", "Ответ"],
        [
            ["Регион парсера", "Краснодар", "[ ] OK [ ] Москва [ ] ___"],
            ["Optimizer", "suggest-only", "[ ] 3–5 дн. [ ] auto*"],
            ["CPM cap", "~1500 ₽", "[ ] OK [ ] ___"],
            ["Расписание", "always_on", "[ ] OK [ ] night_off"],
        ],
        [45, 40, 105],
    )
    pdf.paragraph("* Auto-ставки — после write-token WB.")

    pdf.section("Шаблон ответа")
    pdf.code_block(
        """Дата: __.__.2026  Менеджер: _______________

A1. Исключения: 33206346/перчатка для пыли → ...
    37636194/кухонная тряпка → ...
A2. Ставка 37636194 → 7.35 / оставить 7.00
B. Маржа 11% → OK / правки
C. Primary → OK / правки
D. Сверка WB → OK / расхождения
E. Позиции Краснодар → OK / факт
F. Регион Краснодар OK / suggest-only ___ дней"""
    )

    pdf.section("Справка: 10 SKU (sync 07.07.2026)")
    pdf.table(
        ["Камп.", "nm_id", "Primary", "Показы", "CTR", "CPC", "Зак.", "Цена", "Маржа"],
        [
            ["31275686", "624468743", "перчатки...", "15819", "16.2", "7.57", "824", "179", "11%"],
            ["31314341", "629004626", "тряпка...", "8985", "10.7", "8.03", "203", "275", "12%"],
            ["33206165", "754427875", "перчатки рез.", "10850", "14.8", "6.75", "359", "176", "11%"],
            ["33206346", "754549033", "перчатки...", "14293", "10.1", "17.5", "208", "457", "11%"],
            ["35098216", "754606396", "мочалка...", "1779", "10.7", "0.75", "34", "246", "11%"],
            ["35110541", "866360474", "салфетки...", "2820", "12.0", "2.92", "37", "561", "11%"],
            ["35704170", "929900180", "спонж...", "2053", "5.5", "9.71", "23", "322", "11%"],
            ["36713559", "869367544", "30х30...", "3667", "9.7", "7.19", "85", "330", "11%"],
            ["37328842", "1001645746", "губка...", "2625", "5.7", "16.2", "12", "234", "11%"],
            ["37636194", "1085061548", "салфетки кух.", "2214", "4.7", "13.4", "15", "235", "11%"],
        ],
        [14, 20, 36, 16, 12, 14, 12, 14, 12],
    )
    pdf.paragraph("margin_pct заполнена — CPC-лимиты optimizer считаются. Себестоимость из 1С опциональна.")

    pdf.output(str(OUT))
    return OUT


if __name__ == "__main__":
    path = build_pdf()
    print(f"Saved: {path}", flush=True)

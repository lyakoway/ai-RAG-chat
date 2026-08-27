"""Генерирует набор демо-документов в ../samples для проверки RAG.

Запуск:
    cd backend
    .venv/bin/python scripts/make_samples.py

PDF создаётся, если установлен reportlab (`pip install reportlab`);
иначе шаг PDF пропускается — docx/xlsx создаются всегда.
"""
from __future__ import annotations

from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def make_docx() -> None:
    from docx import Document

    doc = Document()
    doc.add_heading("Политика удалённой работы", 0)
    doc.add_heading("1. Общие положения", level=1)
    doc.add_paragraph(
        "Сотрудники могут работать удалённо до 3 дней в неделю по согласованию "
        "с непосредственным руководителем. Полностью удалённый формат согласуется "
        "с директором департамента."
    )
    doc.add_heading("2. Рабочее время", level=1)
    doc.add_paragraph(
        "Рабочий день длится 8 часов. Обязательные часы присутствия онлайн — "
        "с 11:00 до 16:00. В это время сотрудник должен быть доступен в корпоративном мессенджере."
    )
    doc.add_heading("3. Оборудование", level=1)
    doc.add_paragraph(
        "Компания предоставляет ноутбук и компенсирует до 3000 руб./мес. на интернет. "
        "Заявка на компенсацию подаётся через портал до 5 числа месяца."
    )
    doc.add_heading("4. Отпуск", level=1)
    doc.add_paragraph(
        "Ежегодный оплачиваемый отпуск — 28 календарных дней. Заявление подаётся "
        "не позднее чем за 14 дней до начала отпуска."
    )
    doc.save(SAMPLES / "Политика_удалённой_работы.docx")


def make_xlsx() -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Тарифы"
    ws.append(["Тариф", "Цена, руб/мес", "Пользователей", "Поддержка"])
    for row in [
        ["Старт", 990, 5, "Email"],
        ["Бизнес", 2990, 25, "Email + чат"],
        ["Корпоративный", 9990, "без лимита", "Персональный менеджер"],
    ]:
        ws.append(row)

    ws2 = wb.create_sheet("Скидки")
    ws2.append(["Условие", "Скидка"])
    ws2.append(["Оплата за год", "20%"])
    ws2.append(["Некоммерческие организации", "30%"])
    wb.save(SAMPLES / "Тарифы_и_скидки.xlsx")


def make_pdf() -> bool:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return False

    # Пытаемся зарегистрировать шрифт с кириллицей (macOS / Linux пути).
    font = "Helvetica"
    for path in ["/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("Body", path))
            font = "Body"
            break

    c = canvas.Canvas(str(SAMPLES / "Руководство_пользователя.pdf"), pagesize=A4)
    w, h = A4

    def page(title: str, lines: list[str]) -> None:
        c.setFont(font, 18)
        c.drawString(2 * cm, h - 3 * cm, title)
        c.setFont(font, 11)
        y = h - 4.5 * cm
        for line in lines:
            c.drawString(2 * cm, y, line)
            y -= 0.8 * cm
        c.showPage()

    page("Руководство пользователя — Стр. 1", [
        "Раздел 1. Начало работы.",
        "Зарегистрируйтесь на портале и подтвердите email.",
        "Первый вход выполняется по ссылке из письма.",
        "Пароль должен содержать не менее 8 символов.",
    ])
    page("Руководство пользователя — Стр. 2", [
        "Раздел 2. Импорт данных.",
        "Поддерживаются форматы CSV и XLSX до 50 МБ.",
        "Импорт запускается на вкладке 'Данные' -> 'Загрузить'.",
        "Ошибки импорта отображаются в журнале операций.",
    ])
    page("Руководство пользователя — Стр. 3", [
        "Раздел 3. Безопасность.",
        "Включите двухфакторную аутентификацию в настройках.",
        "Сессия завершается автоматически через 30 минут простоя.",
        "Экспорт данных доступен только администраторам.",
    ])
    c.save()
    return True


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    make_docx()
    make_xlsx()
    pdf_ok = make_pdf()
    made = ["Политика_удалённой_работы.docx", "Тарифы_и_скидки.xlsx"]
    if pdf_ok:
        made.append("Руководство_пользователя.pdf")
    print("Создано в", SAMPLES)
    for m in made:
        print("  •", m)
    if not pdf_ok:
        print("  (PDF пропущен: установите reportlab — pip install reportlab)")


if __name__ == "__main__":
    main()

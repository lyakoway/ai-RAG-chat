"""Тесты определения языка документа (включая CJK)."""
from app.core.ingestion import detect_lang, detect_lang_from_filename


def test_ru():
    assert detect_lang("Политика удалённой работы, отпуск 28 дней") == "ru"


def test_en():
    assert detect_lang("Remote work policy, 3 days per week") == "en"


def test_zh():
    assert detect_lang("员工内部培训政策 新员工培训为期两周") == "zh"


def test_ja_kana_wins_over_kanji():
    # Хирагана/катакана — решающий признак японского.
    assert detect_lang("緊急連絡先はこちらです") == "ja"


def test_ko():
    assert detect_lang("인사 정책 및 교육 과정") == "ko"


def test_no_letters_returns_none():
    assert detect_lang("12345 :) ---") is None


def test_filename_ru():
    assert detect_lang_from_filename("Тарифы_и_скидки.xlsx") == "ru"


def test_filename_zh_ko():
    assert detect_lang_from_filename("培训政策.docx") == "zh"
    assert detect_lang_from_filename("인사정책.docx") == "ko"

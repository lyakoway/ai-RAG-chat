"""Тесты чанкинга: разбиение, перекрытие, сохранение страниц, сквозные индексы."""
from app.config import get_settings
from app.core.chunking import chunk_segments
from app.parsers.base import PageSegment


def test_short_text_single_chunk(monkeypatch):
    monkeypatch.setattr(get_settings(), "chunk_size", 100)
    chunks = chunk_segments([PageSegment(page=1, text="Привет мир")])
    assert len(chunks) == 1
    assert chunks[0].text == "Привет мир"
    assert chunks[0].index == 0
    assert chunks[0].page == 1


def test_long_text_split_keeps_page_and_label(monkeypatch):
    monkeypatch.setattr(get_settings(), "chunk_size", 30)
    monkeypatch.setattr(get_settings(), "chunk_overlap", 5)
    chunks = chunk_segments(
        [PageSegment(page=3, text="слово " * 100, label="Приложение")]
    )
    assert len(chunks) > 1
    assert all(c.page == 3 for c in chunks)
    assert all(c.label == "Приложение" for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_overlap_connects_chunks(monkeypatch):
    monkeypatch.setattr(get_settings(), "chunk_size", 30)
    monkeypatch.setattr(get_settings(), "chunk_overlap", 10)
    chunks = chunk_segments([PageSegment(page=1, text=" ".join(f"w{i}" for i in range(200)))])
    assert len(chunks) > 1
    # Хвост предыдущего куска встречается в начале следующего (перекрытие).
    tail = chunks[0].text.split()[-1]
    assert tail in chunks[1].text


def test_global_index_across_segments(monkeypatch):
    monkeypatch.setattr(get_settings(), "chunk_size", 1000)
    segs = [
        PageSegment(page=1, text="первая страница"),
        PageSegment(page=2, text="вторая страница"),
    ]
    chunks = chunk_segments(segs)
    assert [c.index for c in chunks] == [0, 1]
    assert [c.page for c in chunks] == [1, 2]

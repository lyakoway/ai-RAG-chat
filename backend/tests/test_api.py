"""API-тесты: демо-пак, поиск, чат с мок-моделью, фидбек 👍/👎."""
import json


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        event, data = None, None
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if event and data:
            events.append((event, json.loads(data)))
    return events


class TestHealth:
    def test_health(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_models_include_glm5(self, client):
        ids = [m["id"] for m in client.get("/api/models").json()]
        assert "mock" in ids
        assert "zai:glm-5.3" in ids
        assert "zai:glm-5.3-flash" in ids


class TestDemoPack:
    def test_load_and_idempotent(self, client, demo_loaded):
        assert len(demo_loaded) >= 3
        r2 = client.post("/api/documents/demo")
        assert r2.status_code == 201
        assert r2.json() == []  # повторно ничего не создаётся

    def test_documents_have_language(self, client):
        docs = client.get("/api/documents").json()
        assert docs
        assert all(d["lang"] in ("ru", "en") for d in docs)


class TestSearch:
    def test_search_returns_scored_results(self, client, demo_loaded):
        r = client.get("/api/search", params={"q": "сколько дней отпуск", "top_k": 3})
        assert r.status_code == 200
        data = r.json()
        assert data["results"]
        assert all(0 <= res["score"] <= 1 for res in data["results"])

    def test_empty_query_rejected(self, client):
        assert client.get("/api/search", params={"q": "  "}).status_code == 400


class TestChatAndFeedback:
    def test_mock_chat_then_feedback(self, client):
        r = client.post(
            "/api/chat",
            json={"message": "тест фидбека", "model": "mock", "mode": "rag", "lang": "ru"},
        )
        assert r.status_code == 200
        events = _sse_events(r.text)
        kinds = [e for e, _ in events]
        assert "sources" in kinds and "done" in kinds

        cid = next(d["conversation_id"] for e, d in events if e == "sources")
        mid = next(d["message_id"] for e, d in events if e == "done")

        # 👍
        fb = client.post(f"/api/messages/{mid}/feedback", json={"value": "up"})
        assert fb.status_code == 200
        assert fb.json()["feedback"] == "up"

        # Оценка видна в истории диалога
        detail = client.get(f"/api/conversations/{cid}").json()
        assert any(m["id"] == mid and m["feedback"] == "up" for m in detail["messages"])

        # Повторный клик снимает оценку
        fb = client.post(f"/api/messages/{mid}/feedback", json={"value": None})
        assert fb.json()["feedback"] is None

    def test_feedback_validates_value(self, client):
        r = client.post("/api/messages/unknown/feedback", json={"value": "maybe"})
        assert r.status_code == 422

    def test_feedback_unknown_message(self, client):
        r = client.post("/api/messages/0000/feedback", json={"value": "up"})
        assert r.status_code == 404

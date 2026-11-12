"""Regression checks for package entry points and project-relative resources."""


def test_resources_load_outside_project_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from chatbi.agent.query_decomposer import _load_indicator_catalog
    from chatbi.evaluation.evaluator import Evaluator
    from chatbi.retrieval.indicator_knowledge import IndicatorKnowledge

    assert IndicatorKnowledge().indicators
    assert _load_indicator_catalog()
    assert Evaluator(db_client=object()).load_test_cases()


def test_original_entry_points_and_static_page(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-local-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9")

    from fastapi.testclient import TestClient
    from api_service import app as compatibility_app
    from chatbi.api_service import app
    from chatbi.main import ChatBISystem
    from main import ChatBISystem as compatibility_system

    assert compatibility_app is app
    assert compatibility_system is ChatBISystem
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/static/index.html").status_code == 200

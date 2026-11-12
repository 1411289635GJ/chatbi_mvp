"""HTTP behavior for indicator-knowledge errors, without network or database calls."""

from unittest.mock import Mock
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _api_module(monkeypatch):
    # Configure a non-secret placeholder before the service creates its default runtime.
    monkeypatch.setenv("OPENAI_API_KEY", "test-local-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9")
    import chatbi.api_service as api_service

    return api_service


def test_indicator_knowledge_error_returns_503_and_trace(monkeypatch):
    api = _api_module(monkeypatch)
    private_exception_detail = "sensitive-upstream-exception-detail"
    safe_result = {
        "success": False,
        "error": "指标知识获取失败",
        "error_type": "indicator_knowledge",
        "metadata": {
            "indicator_source": "none",
            "indicator_rag_status": "error",
        },
    }
    run = Mock(return_value=safe_result)
    monkeypatch.setattr(api.system, "run", run)

    response = TestClient(api.app).post("/api/v1/query", json={"question": "查询销售收入"})

    assert response.status_code == 503
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "指标知识获取失败"
    assert body["error_type"] == "indicator_knowledge"
    assert body["metadata"]["indicator_source"] == "none"
    assert body["metadata"]["indicator_rag_status"] == "error"
    assert private_exception_detail not in response.text
    run.assert_called_once()


def test_successful_query_response_remains_unchanged(monkeypatch):
    api = _api_module(monkeypatch)
    safe_result = {
        "success": True,
        "sql": "SELECT COUNT(*) AS total FROM sales_orders",
        "columns": ["total"],
        "results": [(3,)],
        "formatted": "total: 3",
        "metadata": {"indicator_source": "keyword", "indicator_rag_status": "empty"},
    }
    run = Mock(return_value=safe_result)
    monkeypatch.setattr(api.system, "run", run)

    response = TestClient(api.app).post("/api/v1/query", json={"question": "查询订单数量"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["sql"] == safe_result["sql"]
    assert body["columns"] == ["total"]
    assert body["rows"] == [{"total": 3}]
    assert body["formatted"] == "total: 3"
    assert body["metadata"]["indicator_source"] == "keyword"
    assert body["metadata"]["indicator_rag_status"] == "empty"
    run.assert_called_once()


def test_keyword_failure_flows_through_sync_and_stream_api(monkeypatch):
    api = _api_module(monkeypatch)
    from chatbi.core.query_parser import QueryParser
    from chatbi.main import ChatBISystem

    keyword = Mock()
    keyword.get_indicator_context.side_effect = RuntimeError("private-keyword-error")
    llm = Mock()
    database = Mock()
    runtime = SimpleNamespace(
        source_id="test",
        parser=QueryParser(),
        llm=llm,
        db=database,
        formatter=Mock(),
        indicator_knowledge=keyword,
    )
    monkeypatch.setattr(api, "system", ChatBISystem(runtime=runtime, app_config={"features": {}}))
    client = TestClient(api.app)
    payload = {
        "question": "查询销售收入",
        "use_indicator_knowledge": True,
        "use_indicator_rag": False,
    }

    sync_response = client.post("/api/v1/query", json=payload)
    assert sync_response.status_code == 503
    assert sync_response.json()["error_type"] == "indicator_knowledge"
    assert sync_response.json()["metadata"]["indicator_rag_status"] == "disabled"
    assert "private-keyword-error" not in sync_response.text

    stream_response = client.post("/api/v1/query/stream", json=payload)
    assert stream_response.status_code == 200
    assert "event: error" in stream_response.text
    assert '"error_type": "indicator_knowledge"' in stream_response.text
    assert "private-keyword-error" not in stream_response.text
    llm.generate_sql.assert_not_called()
    llm.generate_sql_stream.assert_not_called()
    database.execute.assert_not_called()

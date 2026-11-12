"""Indicator provenance tests; no external packages, network, or database required."""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class FakeParser:
    def parse(self, question):
        return {"is_valid": bool(question.strip())}

    def validate(self, parsed):
        return parsed["is_valid"]


class FakeUserContext:
    role = "admin"
    region = None

    @classmethod
    def demo_admin(cls):
        return cls()


class FakeSecurityError(Exception):
    pass


class FakeQueryExecutionError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.error_type = "query_timeout"
        self.metadata = {}


def load_main_without_optional_dependencies():
    """Load the real main.py with isolated fake dependencies, without importing .env."""
    def fake_module(name, **attributes):
        module = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        return module

    stubs = {
        "config": fake_module("config", APP_CONFIG={"features": {}}, LLM_CONFIG={"model": "stub"}),
        "database": fake_module("database", DatabaseClient=object, QueryExecutionError=FakeQueryExecutionError),
        "indicator_knowledge": fake_module("indicator_knowledge", IndicatorKnowledge=object),
        "llm_client": fake_module("llm_client", LLMClient=object),
        "prompt_builder": fake_module("prompt_builder", build_prompt=lambda *a, **kw: ("system", "prompt")),
        "query_parser": fake_module("query_parser", QueryParser=FakeParser),
        "result_formatter": fake_module("result_formatter", ResultFormatter=object),
        "runtime_factory": fake_module("runtime_factory", build_runtime=lambda *a, **kw: None),
        "security": fake_module("security", SecurityError=FakeSecurityError, UserContext=FakeUserContext),
    }
    path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("chatbi_indicator_trace_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


MAIN = load_main_without_optional_dependencies()


def rag_module(result=None, error=None):
    module = types.ModuleType("indicator_retriever")
    module.retrieve_indicator_context = Mock(side_effect=error, return_value=result)
    return module


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail

    def generate_sql(self, system_msg, prompt):
        if self.fail:
            raise RuntimeError("model unavailable")
        return "SELECT 1"

    def generate_sql_stream(self, system_msg, prompt):
        if self.fail:
            raise RuntimeError("model unavailable")
        yield "SELECT 1"


class FakeDatabase:
    last_query_info = {}

    def __init__(self, error=None):
        self.error = error

    def execute(self, sql, user=None):
        if self.error:
            raise self.error
        return ["amount"], [(1,)]


def make_system(keyword_context=None, llm_failure=False, db_error=None):
    keyword = Mock()
    keyword.get_indicator_context.return_value = keyword_context or {
        "detected_indicators": [], "indicator_block": ""
    }
    runtime = types.SimpleNamespace(
        source_id="test",
        parser=FakeParser(),
        llm=FakeLLM(llm_failure),
        db=FakeDatabase(db_error),
        formatter=types.SimpleNamespace(format=lambda columns, rows: "formatted"),
        indicator_knowledge=keyword,
    )
    return MAIN.ChatBISystem(runtime=runtime, app_config={"features": {}}), keyword


class IndicatorTraceTests(unittest.TestCase):
    def assert_trace(self, trace, source, status):
        self.assertEqual(trace["indicator_source"], source)
        self.assertEqual(trace["indicator_rag_status"], status)

    def test_rag_hit_takes_precedence(self):
        system, keyword = make_system({"detected_indicators": ["其他"], "indicator_block": "other"})
        rag = rag_module({"detected_indicators": ["收入"], "indicator_block": "rag content"})
        with patch.dict(sys.modules, {"indicator_retriever": rag}):
            detected, block, trace = system._resolve_indicator_context("问题", True, True, keyword)
        self.assertEqual((detected, block), (["收入"], "rag content"))
        self.assert_trace(trace, "rag", "matched")
        keyword.get_indicator_context.assert_not_called()

    def test_rag_empty_or_error_falls_back_to_keyword(self):
        secret = "private-rag-exception-detail"
        for rag_status in ("empty", "error"):
            with self.subTest(rag_status=rag_status):
                system, keyword = make_system({"detected_indicators": ["收入"], "indicator_block": "keyword content"})
                rag = (rag_module({"detected_indicators": [], "indicator_block": ""})
                       if rag_status == "empty" else rag_module(error=RuntimeError(secret)))
                with patch.dict(sys.modules, {"indicator_retriever": rag}):
                    detected, block, trace = system._resolve_indicator_context("问题", True, True, keyword)
                self.assertEqual((detected, block), (["收入"], "keyword content"))
                self.assert_trace(trace, "keyword", rag_status)
                keyword.get_indicator_context.assert_called_once_with("问题")
                self.assertNotIn(secret, json.dumps(trace))

    def test_rag_empty_or_error_without_fallback(self):
        for rag_status in ("empty", "error"):
            with self.subTest(rag_status=rag_status):
                system, keyword = make_system()
                rag = (rag_module({"detected_indicators": [], "indicator_block": ""})
                       if rag_status == "empty" else rag_module(error=RuntimeError("private detail")))
                with patch.dict(sys.modules, {"indicator_retriever": rag}):
                    detected, block, trace = system._resolve_indicator_context("问题", False, True, keyword)
                self.assertEqual((detected, block), ([], ""))
                self.assert_trace(trace, "none", rag_status)
                keyword.get_indicator_context.assert_not_called()

    def test_rag_empty_and_keyword_empty_has_no_source(self):
        system, keyword = make_system()
        rag = rag_module({"detected_indicators": [], "indicator_block": ""})
        with patch.dict(sys.modules, {"indicator_retriever": rag}):
            detected, block, trace = system._resolve_indicator_context("问题", True, True, keyword)
        self.assertEqual((detected, block), ([], ""))
        self.assert_trace(trace, "none", "empty")

    def test_keyword_only_can_match_or_be_empty(self):
        for block, source in (("keyword content", "keyword"), ("", "none")):
            with self.subTest(block=block):
                detected = ["收入"] if block else []
                system, keyword = make_system({"detected_indicators": detected, "indicator_block": block})
                rag = rag_module(error=AssertionError("RAG must not be called"))
                with patch.dict(sys.modules, {"indicator_retriever": rag}):
                    actual, knowledge, trace = system._resolve_indicator_context("问题", True, False, keyword)
                self.assertEqual((actual, knowledge), (detected, block))
                self.assert_trace(trace, source, "disabled")
                rag.retrieve_indicator_context.assert_not_called()

    def test_both_disabled(self):
        system, keyword = make_system()
        rag = rag_module(error=AssertionError("RAG must not be called"))
        with patch.dict(sys.modules, {"indicator_retriever": rag}):
            detected, block, trace = system._resolve_indicator_context("问题", False, False, keyword)
        self.assertEqual((detected, block), ([], ""))
        self.assert_trace(trace, "none", "disabled")
        keyword.get_indicator_context.assert_not_called()
        rag.retrieve_indicator_context.assert_not_called()

    def test_sync_and_stream_trace_on_success_and_failure(self):
        secret = "private-rag-exception-detail"
        cases = (
            ("success", False, None),
            ("llm", True, None),
            ("database", False, RuntimeError("database unavailable")),
            ("database_query_timeout", False, FakeQueryExecutionError("database timeout")),
            ("security", False, FakeSecurityError("access denied")),
        )
        for stream in (False, True):
            for expected_type, llm_failure, db_error in cases:
                with self.subTest(stream=stream, outcome=expected_type):
                    system, keyword = make_system(
                        {"detected_indicators": ["收入"], "indicator_block": "keyword content"},
                        llm_failure=llm_failure,
                        db_error=db_error,
                    )
                    rag = rag_module(error=RuntimeError(secret))
                    prompt_builder = Mock(return_value=("system", "prompt"))
                    with patch.dict(sys.modules, {"indicator_retriever": rag}), patch.object(MAIN, "build_prompt", prompt_builder):
                        if stream:
                            events = list(system.run_stream("问题", use_indicator_knowledge=True, use_indicator_rag=True))
                            event_type, data_line = events[-1].strip().split("\n", 1)
                            result = json.loads(data_line.removeprefix("data: "))
                            self.assertEqual(event_type, "event: result" if expected_type == "success" else "event: error")
                        else:
                            result = system.run("问题", use_indicator_knowledge=True, use_indicator_rag=True)
                            self.assertEqual(result["success"], expected_type == "success")
                        if expected_type != "success":
                            self.assertEqual(result["error_type"], expected_type)
                        self.assert_trace(result["metadata"], "keyword", "error")
                        self.assertTrue(result["metadata"]["used_indicator_rag"])
                        self.assertEqual(prompt_builder.call_args.kwargs["indicator_knowledge"], "keyword content")
                        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

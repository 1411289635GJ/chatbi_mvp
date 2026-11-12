# ChatBI MVP

ChatBI MVP 是一个基于自然语言的数据查询与分析项目。它将用户问题与表结构、示例和业务指标信息组合成提示词，调用模型生成 SQL，并通过数据库执行、权限检查与结果格式化返回查询结果。项目还包含多步骤分析、指标检索和 Schema Linking 等模块。

本仓库基于 [chatbi_mvp 原始仓库](https://github.com/kakuibeyond/chatbi_mvp)的已有代码，用于个人学习与改进。

## 查询流程

```text
用户问题 → 输入检查 → 指标知识与 Schema 上下文 → Prompt 构造
        → 模型生成 SQL → 安全检查与数据库查询 → 结果格式化
```

主查询入口为 `ChatBISystem.run()`；具体运行路径受到功能开关和请求参数影响。复杂分析可使用独立的 Plan-and-Execute 流程，拆分任务、执行查询并汇总结果。

## 主要模块

| 模块 | 作用及入口 |
| --- | --- |
| `main.py` | 统一查询入口；`ChatBISystem.run()` 和 `run_stream()` 分别处理普通和流式查询 |
| `query_parser.py` | 输入预处理和非空检查；`QueryParser.parse()`、`validate()` |
| `prompt_builder.py` | 组合 Schema、示例、规则和指标知识；`build_prompt()` |
| `llm_client.py` | 模型文本、SQL 和流式调用；`LLMClient` |
| `database.py` | MySQL 连接与查询执行，包含连接池、异常分型和慢查询信息；`DatabaseClient.execute()` |
| `security.py` | SQL 检查、权限上下文、行过滤和结果脱敏；`QuerySecurityManager` |
| `result_formatter.py` | 格式化查询结果与错误信息；`ResultFormatter.format()`、`format_error()` |
| `config.py` | 数据源、模型、运行参数及功能开关配置；`APP_CONFIG` |
| `runtime_factory.py` | 根据配置组装运行时和数据库客户端；`build_runtime()` |
| `api_service.py` | FastAPI 接口，包括同步查询、SSE 流式查询和健康检查 |
| `schema_generator.py` | 从 MySQL 元数据提取表、字段及已声明的外键，生成 Schema 文本 |

## 检索、分析与评估

| 模块 | 作用及入口 |
| --- | --- |
| `indicator_knowledge.py`、`indicators.json` | 通过关键词识别指标，组织指标定义；`get_indicator_context()` |
| `indicator_retriever.py`、`indicators_full.json` | 检索指标定义及依赖信息；`retrieve_indicator_context()` |
| `table_retriever.py`、`field_matcher.py` | 表召回和字段匹配；`retrieve_tables()`、`match_fields()` |
| `join_resolver.py`、`schema_linker.py` | 推导关联路径，组装与查询相关的 Schema；`resolve_joins()`、`schema_link()` |
| `query_decomposer.py`、`agent_planner.py` | 拆解复杂问题，生成并执行分析计划；`QueryDecomposer`、`PlanAndExecuteAgent` |
| `report_generator.py` | 整理多步分析结果，生成报告；`ReportGenerator` |
| `error_analyzer.py` | 分类和分析 SQL 生成错误；`ErrorAnalyzer` |
| `evaluator.py`、`test_cases.json` | 根据测试用例评估生成 SQL，包括执行结果和文本匹配的比较 |
| `vector_search_demo.py` | 向量生成与相似度检索的独立演示 |
| `text2sql_v0.py`、`text2sql_v1.py`、`text2sql_v2.py` | 保留不同 Prompt 构造方式的独立原型；这些脚本输出 SQL，不执行数据库查询 |

## 环境准备

项目在 `pyproject.toml` 中声明 Python 3.12 及以上和所需依赖，可使用 `uv` 管理环境。在项目目录执行：

```powershell
uv sync
```

根据 `.env.example` 在本地配置环境变量。模型调用使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL` 等配置；数据库连接使用 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME` 等配置。功能开关和默认值可查看 `config.py`。密钥与数据库密码应保存在本地环境中，不要提交到仓库。

完整查询需要可连接的 MySQL 数据库和与项目 Schema、业务规则匹配的数据表；模型调用还需要可用的服务商配置。部分检索功能需要相应的向量模型与索引。`schema_generator.py` 可读取已有数据库的元数据，但不能替代业务指标口径的确认。

## 运行

以下命令需要相应的依赖和配置，执行查询时会调用模型及数据库：

```powershell
# 命令行查询
uv run python main.py "查询已完成订单的总数量"

# 交互模式
uv run python main.py

# API 服务
uv run uvicorn api_service:app --host 127.0.0.1 --port 8000
```

API 入口包括 `POST /api/v1/query`、`POST /api/v1/query/stream` 和 `GET /health`。请求结构与可选参数以 `api_service.py` 中的 `QueryRequest` 为准。

如只想观察自然语言生成 SQL 的原型，可运行：

```powershell
uv run python text2sql_v1.py
```

该原型仍会调用配置的模型服务，但不会执行生成的 SQL。SQL 能否执行及是否符合业务口径，需要进一步核验。

## 测试与评估

```powershell
uv run pytest -q
```

`tests/` 中包含查询、权限、数据库运行时、配置合并和 Agent 等相关测试。评估生成 SQL 时，可结合预设问题、预期 SQL 和实际执行结果分析错误；评估结果应以具体数据集和实际运行记录为准。

### 结果比较与排序

评估器默认忽略结果行顺序。对于排名、趋势等需要比较顺序的问题，可在测试用例中显式设置 `order_sensitive`：

```json
{
  "id": "ranking_example",
  "category": "simple",
  "question": "按客户统计销售额，列出销售额最高的前十名",
  "expected_sql": "SELECT customer_id, SUM(net_amount) AS total FROM sales_orders GROUP BY customer_id ORDER BY total DESC, customer_id ASC LIMIT 10",
  "order_sensitive": true
}
```

启用后，评估器逐行比较结果顺序；未设置时沿用忽略行顺序的行为。该选项需要由用例维护者显式指定，不会自动识别 SQL 中的 `ORDER BY`。对于有相同排序值的记录，预期 SQL 应有明确的次级排序规则，以免顺序不稳定。

结果比较还会保留重复列名的值，区分 SQL `NULL` 与文本 `"None"`，并在需要比较列名时检查空结果的列信息。结果相同只表示在当前数据集和比较规则下匹配，不能证明两条 SQL 在所有数据上语义相同。

可单独运行评估逻辑测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_evaluator.py
```

测试使用内存数据和模拟数据库，不需要模型服务或 MySQL；SQLite 用例不代表已验证 MySQL 执行。

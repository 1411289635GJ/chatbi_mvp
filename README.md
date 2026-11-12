# ChatBI MVP

ChatBI MVP 是一个基于自然语言的数据查询与分析项目。它将用户问题与表结构、示例和业务指标信息组合成提示词，调用模型生成 SQL，并通过数据库执行、权限检查与结果格式化返回查询结果。项目还包含多步骤分析、指标检索和 Schema Linking 等模块。

本仓库基于 [chatbi_mvp 原始仓库](https://github.com/kakuibeyond/chatbi_mvp)的已有代码，用于个人学习与改进。

## 查询流程

```text
用户问题 → 输入检查 → 指标知识与 Schema 上下文 → Prompt 构造
        → 模型生成 SQL → 安全检查与数据库查询 → 结果格式化
```

主查询入口为 `ChatBISystem.run()`；具体运行路径受到功能开关和请求参数影响。复杂分析可使用独立的 Plan-and-Execute 流程，拆分任务、执行查询并汇总结果。

查询结果的 `metadata` 可用于查看指标知识的实际来源：

| 字段 | 取值及含义 |
| --- | --- |
| `indicator_source` | `rag`：使用 RAG 检索结果；`keyword`：使用关键词匹配结果；`none`：没有可用的指标知识 |
| `indicator_rag_status` | `disabled`：未启用；`matched`：返回非空知识；`empty`：返回空知识；`error`：检索或读取结果时发生异常 |

`used_indicator_rag` 是原有的功能开关，表示是否启用 RAG，并不代表最终使用了 RAG 的结果。当 RAG 返回空知识或发生异常，且关键词路径开启时，系统会尝试关键词匹配。异常状态不包含异常原文；非空知识不代表内容正确。上述字段出现在主查询及流式事件的相应元数据中，同步 API 的成功响应会透传元数据；同步 API 的错误响应目前不会透传这些字段。关键词匹配自身若抛出异常，现有流程会将异常继续抛出，无法保证返回这些追踪字段。

## 目录结构

```text
chatbi/
├── main.py             # 主查询链路
├── api_service.py      # HTTP / SSE 服务
├── paths.py            # 项目根路径
├── core/               # 配置、模型、数据库、安全和 Prompt
├── retrieval/          # 指标检索、Schema 与关联路径
├── agent/              # 任务拆解、多步执行与报告
├── evaluation/         # SQL 评估与错误分析
└── tools/              # 数据库结构提取工具
examples/               # 独立原型和练习脚本
tests/                  # 测试
static/                 # 前端静态文件
main.py                 # 原 CLI 兼容入口
api_service.py          # 原 API 兼容入口
```

指标定义和测试用例 JSON 保留在项目根目录，Chroma 索引继续使用根目录下的 `chroma_db/`。原有根目录 CLI 和 API 启动命令仍可使用；其余模块通过 `chatbi` 包导入。

## 主要模块

| 模块 | 作用及入口 |
| --- | --- |
| `chatbi/main.py` | 统一查询入口；`ChatBISystem.run()` 和 `run_stream()` 分别处理普通和流式查询 |
| `chatbi/core/query_parser.py` | 输入预处理和非空检查；`QueryParser.parse()`、`validate()` |
| `chatbi/core/prompt_builder.py` | 组合 Schema、示例、规则和指标知识；`build_prompt()` |
| `chatbi/core/llm_client.py` | 模型文本、SQL 和流式调用；`LLMClient` |
| `chatbi/core/database.py` | MySQL 连接与查询执行，包含连接池、异常分型和慢查询信息；`DatabaseClient.execute()` |
| `chatbi/core/security.py` | SQL 检查、权限上下文、行过滤和结果脱敏；`QuerySecurityManager` |
| `chatbi/core/result_formatter.py` | 格式化查询结果与错误信息；`ResultFormatter.format()`、`format_error()` |
| `chatbi/core/config.py` | 数据源、模型、运行参数及功能开关配置；`APP_CONFIG` |
| `chatbi/core/runtime_factory.py` | 根据配置组装运行时和数据库客户端；`build_runtime()` |
| `chatbi/api_service.py` | FastAPI 接口，包括同步查询、SSE 流式查询和健康检查 |
| `chatbi/tools/schema_generator.py` | 从 MySQL 元数据提取表、字段及已声明的外键，生成 Schema 文本 |

## 检索、分析与评估

| 模块 | 作用及入口 |
| --- | --- |
| `chatbi/retrieval/indicator_knowledge.py`、`indicators.json` | 通过关键词识别指标，组织指标定义；`get_indicator_context()` |
| `chatbi/retrieval/indicator_retriever.py`、`indicators_full.json` | 检索指标定义及依赖信息；`retrieve_indicator_context()` |
| `chatbi/retrieval/table_retriever.py`、`chatbi/retrieval/field_matcher.py` | 表召回和字段匹配；`retrieve_tables()`、`match_fields()` |
| `chatbi/retrieval/join_resolver.py`、`chatbi/retrieval/schema_linker.py` | 推导关联路径，组装与查询相关的 Schema；`resolve_joins()`、`schema_link()` |
| `chatbi/agent/query_decomposer.py`、`chatbi/agent/agent_planner.py` | 拆解复杂问题，生成并执行分析计划；`QueryDecomposer`、`PlanAndExecuteAgent` |
| `chatbi/agent/report_generator.py` | 整理多步分析结果，生成报告；`ReportGenerator` |
| `chatbi/evaluation/error_analyzer.py` | 分类和分析 SQL 生成错误；`ErrorAnalyzer` |
| `chatbi/evaluation/evaluator.py`、`test_cases.json` | 根据测试用例评估生成 SQL，包括执行结果和文本匹配的比较 |
| `examples/vector_search_demo.py` | 向量生成与相似度检索的独立演示 |
| `examples/text2sql_v0.py`、`examples/text2sql_v1.py`、`examples/text2sql_v2.py` | 保留不同 Prompt 构造方式的独立原型；这些脚本输出 SQL，不执行数据库查询 |

## 环境准备

项目在 `pyproject.toml` 中声明 Python 3.12 及以上和所需依赖，可使用 `uv` 管理环境。在项目目录执行：

```powershell
uv sync
```

根据 `.env.example` 在本地配置环境变量。模型调用使用 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`LLM_MODEL` 等配置；数据库连接使用 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME` 等配置。功能开关和默认值可查看 `chatbi/core/config.py`。密钥与数据库密码应保存在本地环境中，不要提交到仓库。

完整查询需要可连接的 MySQL 数据库和与项目 Schema、业务规则匹配的数据表；模型调用还需要可用的服务商配置。部分检索功能需要相应的向量模型与索引。`chatbi/tools/schema_generator.py` 可读取已有数据库的元数据，但不能替代业务指标口径的确认。

现有权限机制属于演示：请求中的角色可以由客户端提供，默认也有演示管理员上下文，不能作为可信身份认证。对外部署需要独立设计认证、授权及数据库侧权限控制。

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

API 入口包括 `POST /api/v1/query`、`POST /api/v1/query/stream` 和 `GET /health`。请求结构与可选参数以 `chatbi/api_service.py` 中的 `QueryRequest` 为准。

如只想观察自然语言生成 SQL 的原型，可运行：

```powershell
uv run python -m examples.text2sql_v1
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

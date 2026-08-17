# SUFEGuide FastAPI Backend

这是一个独立的 Python/FastAPI 后端仓库。它使用自己的 JSON 知识库快照，
不调用、不导入、也不要求启动 Node.js 服务。

项目的目标不是堆叠框架，而是用本科生能够读懂的代码，展示 AI Agent 后端常见的
工程问题：RAG 检索、受约束 Tool Calling、会话式 Agent Runtime、MySQL 持久化、
异步任务、幂等、租约、重试、结构化日志和自动测试。

## 1. 已实现能力

- FastAPI + Pydantic：接口、类型标注和严格参数校验；
- RAG：122 份公开资料、1038 个证据块，默认使用可解释的词法检索，可选 embedding 混合检索；
- 证据约束：资料不足时拒答，返回引用和检索得分；
- Tool Calling：`search_documents`、`get_document`、`get_evidence`、`record_feedback`；
- Agent Runtime：模型决策、工具调用、结果回填和最终回答的有界循环，包含超时与最大步数；
- 会话与审计：MySQL 保存 session、message、run、tool call、执行状态和耗时；
- SSE：逐步发送 session、run、tool 和 answer 事件，便于前端展示执行过程；
- MySQL：连接池、参数化 SQL、feedback、任务状态、唯一幂等键和索引；
- 异步任务：`asyncio.Queue`、多个 worker、任务状态机、失败重试；
- 任务租约：worker 崩溃后，过期任务能够回到队列；
- 可观测性：request ID、结构化 JSON 日志、耗时和状态码；
- 工程交付：Docker Compose、GitHub Actions、真实 MySQL 集成测试和固定评测集；
- 测试：接口、Agent 循环、SSE 顺序、拒答、工具参数、并发幂等、原子 JSON 写入和租约恢复。

这里的“消息队列”是进程内 `asyncio.Queue` 原型，适合学习和单机演示。
生产环境可以替换为 Redis Streams、RabbitMQ 或 Kafka；项目没有虚构使用这些中间件。

## 2. 目录与阅读顺序

```text
app/
├── main.py                    # 应用工厂、生命周期、request ID 日志
├── routes.py                  # HTTP 接口
├── models.py                  # Pydantic 请求模型
├── retrieval.py               # 词法与可选混合 RAG 排序
├── agent.py                   # understand -> retrieve -> validate -> respond
├── model_provider.py          # 离线模型与 OpenAI-compatible 模型适配器
├── tools.py                   # Tool Calling 白名单与参数校验
├── embeddings.py              # embedding 请求与本地向量索引
├── services/
│   ├── agent_runtime.py       # 会话、工具循环、超时、审计与 SSE
│   ├── feedback.py            # 反馈匿名化与保存
│   └── tasks.py               # asyncio 队列、worker、重试和租约
└── repositories/
    ├── base.py                # 存储接口和任务结构
    ├── mysql.py               # 推荐使用的 MySQL 实现
    └── json_store.py          # 离线学习与测试的降级实现
```

第一次阅读建议按以下顺序：

1. `models.py`：先看输入是什么；
2. `routes.py`：再看接口调用谁；
3. `retrieval.py` 和 `agent.py`：理解 RAG 与证据拒答；
4. `tools.py` 和 `model_provider.py`：理解工具白名单和模型决策；
5. `services/agent_runtime.py`：理解完整 Agent 循环、超时与 SSE；
6. `services/tasks.py`：理解异步队列和状态机；
7. `repositories/mysql.py`：最后理解事务、幂等、会话审计和租约。

## 3. 安装和运行

推荐 Python 3.11。

```powershell
uv sync --extra dev --extra mysql --no-install-project
Copy-Item .env.example .env
```

### MySQL 模式（推荐）

先执行：

```powershell
mysql -u root -p < docs/schema.mysql.sql
```

然后在 `.env` 配置：

```env
PERSISTENCE_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=campusguide_app
MYSQL_PASSWORD=你的本地密码
MYSQL_DATABASE=campusguide_fastapi
```

不要提交真实 `.env`。

### 无 MySQL 的学习模式

```env
PERSISTENCE_BACKEND=json
```

JSON 模式主要用于离线学习和自动测试。多进程部署应使用 MySQL。

### 启动

```powershell
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

访问：

- Swagger：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

### Docker Compose

如果本机已经安装 Docker，可以一次启动 API 和 MySQL：

```powershell
docker compose up --build
```

示例密码只用于本地 Compose 演示，真实部署应改为密钥管理或环境变量注入。

### 可选的真实模型与混合检索

默认 `AGENT_MODEL_PROVIDER=deterministic`，不调用外部大模型，但仍完整执行
“模型决策 -> 工具调用 -> 工具结果回填 -> 最终回答”协议，便于离线学习和测试。

要连接支持 Tool Calling 的 OpenAI-compatible 服务，可配置：

```env
AGENT_MODEL_PROVIDER=openai_compatible
AGENT_MODEL_BASE_URL=https://你的服务地址/v1
AGENT_MODEL_API_KEY=你的密钥
AGENT_MODEL_NAME=支持工具调用的模型名
```

要开启 embedding 混合检索，先配置 `SILICONFLOW_API_KEY`，再执行：

```powershell
uv run --no-sync python -m app.build_vector_index
```

最后设置 `RAG_ENABLE_SEMANTIC_SEARCH=true`。索引或 embedding 服务不可用时，系统会明确记录
fallback 原因并退回词法检索，不影响基本问答。

## 4. 一条请求如何运行

以 `POST /api/chat` 为例：

```text
HTTP 请求
  -> Pydantic 校验问题和用户上下文
  -> retrieval.py 提取领域词并计算可解释得分
  -> agent.py 判断证据是否达到阈值
  -> 有依据：返回答案、引用、得分和 trace
  -> 无依据：拒答，不编造学校规则
  -> main.py 记录 request ID、状态码和耗时
```

异步任务链路：

```text
POST /api/ingestion/tasks
  -> MySQL 唯一 idempotency_key 防止重复任务
  -> task_id 放入 asyncio.Queue
  -> worker 在事务中领取任务并写入租约
  -> 成功：succeeded
  -> 失败但未到上限：queued + retry_count
  -> worker 崩溃：租约过期后重新 queued
```

完整 Agent 链路：

```text
POST /api/agent/run 或 /api/agent/stream
  -> 创建或继续 session，保存 user message
  -> 模型在白名单工具中选择调用
  -> Pydantic 校验参数，工具在超时范围内执行
  -> 保存 tool call、结果、耗时和状态
  -> 工具结果回填模型，直到回答或达到最大步数
  -> 保存 assistant message 和 run 状态
```

## 5. 常用请求

```powershell
curl http://127.0.0.1:8000/api/health

curl -X POST http://127.0.0.1:8000/api/search `
  -H "Content-Type: application/json" `
  -d '{"query":"挂科重修怎么办","limit":5}'

curl -X POST http://127.0.0.1:8000/api/chat `
  -H "Content-Type: application/json" `
  -d '{"question":"挂科重修怎么办"}'

curl -X POST http://127.0.0.1:8000/api/agent/run `
  -H "Content-Type: application/json" `
  -d '{"question":"挂科重修怎么办"}'

curl -N -X POST http://127.0.0.1:8000/api/agent/stream `
  -H "Content-Type: application/json" `
  -d '{"question":"校园卡丢失后怎么办"}'

curl -X POST http://127.0.0.1:8000/api/ingestion/tasks `
  -H "Content-Type: application/json" `
  -d '{"source":"official-regulations-package","idempotency_key":"official-v1"}'
```

## 6. 测试和代码质量

```powershell
.venv\Scripts\ruff.exe check app tests
.venv\Scripts\python.exe -m compileall -q app tests
.venv\Scripts\pytest.exe -q

# 六条固定用例的小规模回归评测
.venv\Scripts\python.exe -m app.evaluate
```

一个实际发现并修复的 bug：Pydantic 默认会把字符串 `"false"` 转成布尔值。
Tool Calling 参数如果不使用 `StrictBool`，错误请求也可能被记录为有效反馈。项目使用
严格类型并保留回归测试，防止该问题再次出现。

当前六条固定用例的词法基线为：Hit@1 0.60、Hit@5 1.00、MRR 0.7667、
拒答准确率 1.00。它只用于防止项目迭代导致明显退化，样本量很小，不能当作大规模模型效果结论。

## 7. 面试时如何准确描述

可以说：

> 我用 FastAPI 实现了一个证据约束的校园问答 Agent 后端。默认使用可解释词法 RAG，
> 也支持 embedding 混合检索和失败降级；资料不足时拒答。Agent Runtime 会在最大步数
> 和超时约束内完成模型决策、白名单工具调用、结果回填和最终回答，并通过 SSE 输出执行
> 事件。MySQL 保存会话、消息、运行记录、工具审计、反馈和异步任务。任务使用唯一幂等键、
> asyncio.Queue、worker 租约和失败重试；request ID、结构化日志、自动测试与 CI 用于问题定位和回归验证。

不要说：

- “使用了 Kafka/RabbitMQ”——当前只实现了进程内队列；
- “支持亿级并发”——项目只验证了并发正确性，没有做大规模压测；
- “已经接入学校私有数据库”——当前使用公开资料快照；
- “线上效果已经达到 100%”——固定评测集只有六条，只用于回归；
- “默认使用远程大模型生成所有答案”——默认离线模型用于复现，远程模型适配器是可选配置。

## 8. 后续迭代方向

1. 将 `asyncio.Queue` 替换为 Redis Streams 或 RabbitMQ，支持多实例可靠消费；
2. 增加 Prometheus 指标和 OpenTelemetry 链路追踪；
3. 增加 token 级模型流式输出，目前 SSE 主要传递执行阶段事件；
4. 扩充人工标注评测集，并分别评估检索、引用和拒答；
5. 学校数据库开放后，增加资料表、版本字段和增量同步任务。

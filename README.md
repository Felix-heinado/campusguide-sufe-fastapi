# SUFEGuide FastAPI Backend

这是一个独立的 Python/FastAPI 后端仓库。它使用自己的 JSON 知识库快照，
不调用、不导入、也不要求启动 Node.js 服务。

项目的目标不是堆叠框架，而是用本科生能够读懂的代码，展示 AI Agent 后端常见的
工程问题：RAG 检索、受约束 Tool Calling、MySQL 持久化、异步任务、幂等、租约、
重试、结构化日志和自动测试。

## 1. 已实现能力

- FastAPI + Pydantic：接口、类型标注和严格参数校验；
- 词法 RAG：122 份公开资料、1038 个证据块、可解释的关键词权重；
- 证据约束：资料不足时拒答，返回引用和检索得分；
- Tool Calling：`search_documents`、`get_document`、`get_evidence`、`record_feedback`；
- MySQL：连接池、参数化 SQL、feedback、任务状态、唯一幂等键和索引；
- 异步任务：`asyncio.Queue`、多个 worker、任务状态机、失败重试；
- 任务租约：worker 崩溃后，过期任务能够回到队列；
- 可观测性：request ID、结构化 JSON 日志、耗时和状态码；
- 测试：接口、拒答、工具参数、并发幂等、原子 JSON 写入和租约恢复。

这里的“消息队列”是进程内 `asyncio.Queue` 原型，适合学习和单机演示。
生产环境可以替换为 Redis Streams、RabbitMQ 或 Kafka；项目没有虚构使用这些中间件。

## 2. 目录与阅读顺序

```text
app/
├── main.py                    # 应用工厂、生命周期、request ID 日志
├── routes.py                  # HTTP 接口
├── models.py                  # Pydantic 请求模型
├── retrieval.py               # 可解释的 RAG 排序
├── agent.py                   # understand -> retrieve -> validate -> respond
├── tools.py                   # Tool Calling 白名单与参数校验
├── services/
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
3. `retrieval.py` 和 `agent.py`：理解 RAG 主链路；
4. `tools.py`：理解模型为什么不能调用任意函数；
5. `services/tasks.py`：理解异步队列和状态机；
6. `repositories/mysql.py`：最后理解事务、幂等和租约。

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

## 5. 常用请求

```powershell
curl http://127.0.0.1:8000/api/health

curl -X POST http://127.0.0.1:8000/api/search `
  -H "Content-Type: application/json" `
  -d '{"query":"挂科重修怎么办","limit":5}'

curl -X POST http://127.0.0.1:8000/api/chat `
  -H "Content-Type: application/json" `
  -d '{"question":"挂科重修怎么办"}'

curl -X POST http://127.0.0.1:8000/api/ingestion/tasks `
  -H "Content-Type: application/json" `
  -d '{"source":"official-regulations-package","idempotency_key":"official-v1"}'
```

## 6. 测试和代码质量

```powershell
.venv\Scripts\ruff.exe check app tests
.venv\Scripts\python.exe -m compileall -q app tests
.venv\Scripts\pytest.exe -q
```

一个实际发现并修复的 bug：Pydantic 默认会把字符串 `"false"` 转成布尔值。
Tool Calling 参数如果不使用 `StrictBool`，错误请求也可能被记录为有效反馈。项目使用
严格类型并保留回归测试，防止该问题再次出现。

## 7. 面试时如何准确描述

可以说：

> 我用 FastAPI 实现了一个证据约束的校园问答 Agent 后端。检索阶段使用可解释的
> 词法 RAG，回答必须携带来源；没有足够资料时拒答。系统提供四个受约束工具，并用
> MySQL 保存反馈和异步任务。任务通过唯一幂等键防重复，用 asyncio.Queue 解耦 HTTP
> 请求和耗时工作，worker 领取任务时写入租约，异常退出后可以回收重试。接口使用
> request ID 和结构化日志辅助定位问题，并用并发测试验证幂等行为。

不要说：

- “使用了 Kafka/RabbitMQ”——当前只实现了进程内队列；
- “支持亿级并发”——项目只验证了并发正确性，没有做大规模压测；
- “已经接入学校私有数据库”——当前使用公开资料快照；
- “使用了大模型生成所有答案”——当前核心是确定性的证据约束 Agent。

## 8. 后续迭代方向

1. 将词法召回扩展为关键词 + embedding 混合检索；
2. 将 `asyncio.Queue` 替换为 Redis Streams 或 RabbitMQ；
3. 增加 SSE 流式模型输出与工具调用事件；
4. 增加 Prometheus 指标和 OpenTelemetry 链路追踪；
5. 学校数据库开放后，增加资料表和增量同步任务。


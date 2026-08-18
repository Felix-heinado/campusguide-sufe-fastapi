<p align="center">
  <img src="frontend/assets/caiwen-mark.svg" width="96" alt="财问 · SUFE Guide Logo">
</p>

# 财问 · SUFE Guide（Python / FastAPI）

面向上海财经大学学生的可追溯校园信息问答 Agent，也是原
[`campusguide-sufe`](https://github.com/Felix-heinado/campusguide-sufe)
项目的 Python/FastAPI 完整重构版。

仓库保留原项目的网页产品、品牌与校园资料体系，并重新实现 Python 后端：FastAPI、
RAG、受约束 Tool Calling、会话式 Agent Runtime、MySQL 持久化、异步任务、SSE、
自动评测和持续集成。前端与后端由同一个服务提供，不需要同时启动 Node.js 或 Vite。

> 本项目是学生参赛作品，非上海财经大学官方信息系统。回答仅用于信息检索与政策解释，
> 具体认定以学校及主管部门最新正式通知为准。

## 项目负责人

本项目由 **张子恒（Felix-heinado）** 主导开发，负责产品设计、前端交互、Python 后端、
Agent/RAG 架构、知识库建模、资料核验、评测与工程化。原项目中同学协助收集的部分官方
公开资料继续按既定准入标准使用；资料是否采用、时效与适用范围判断、结构化处理和系统
接入均由项目负责人完成。

## 核心定位

财问 · SUFE Guide 重点解决三个问题：

- **有来源**：回答关联资料编号和证据片段；
- **可核验**：展示资料名称、发布单位、日期、适用对象和原文入口；
- **不乱答**：资料不足、过期或适用范围不明确时限制结论或拒答。

当前知识库包含 **122 份资料、1038 个证据块**。资料来自学校及学院官网公开信息，或学校
正式提供、经核验后保留结构化摘要的制度资料。学校业务数据库尚未开放，因此项目没有
声称已经接入学校私有数据库，也不会把原始内部附件上传到 GitHub。

## 当前功能

### 网页产品

- 智能问答、证据面板和来源详情；
- 主题导航、政策资料库搜索与筛选；
- 学院、培养层次和目标年份上下文；
- 浏览器本地收藏；
- 匿名反馈写入 Python 后端；
- 桌面端和移动端响应式布局；
- 后端不可用时保留本地知识库降级能力。

### Agent 与后端

- FastAPI + Pydantic 接口、类型标注和严格参数校验；
- 可解释词法 RAG，可选 `Qwen/Qwen3-Embedding-4B` 混合检索；
- 证据不足拒答，返回引用、检索结果和执行 trace；
- 四个白名单工具：`search_documents`、`get_document`、`get_evidence`、
  `record_feedback`；
- 有界 Agent 循环：模型决策、工具调用、结果回填、最大步数和超时；
- MySQL 保存会话、消息、运行记录、工具审计、反馈和异步任务；
- SSE 输出 session、run、tool 和 answer 等执行事件；
- `asyncio.Queue`、多个 worker、幂等键、任务租约、失败重试和崩溃恢复；
- request ID、结构化日志、状态码和耗时记录；
- Docker Compose、pytest、Ruff、GitHub Actions 和真实 MySQL 集成测试。

这里的队列是便于学习和单机演示的进程内 `asyncio.Queue`，没有虚构使用 Kafka、
RabbitMQ 或 Redis。生产环境可将其替换为外部可靠队列。

## 快速体验

推荐 Python 3.11，并安装 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone https://github.com/Felix-heinado/campusguide-sufe-fastapi.git
cd campusguide-sufe-fastapi
uv sync --extra dev --extra mysql --no-install-project
```

### 方法一：JSON 学习模式

不需要 MySQL，适合第一次运行：

```powershell
$env:PERSISTENCE_BACKEND="json"
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Windows 也可以在安装依赖后直接双击 `start_demo.cmd`。

### 方法二：MySQL 完整模式

复制配置文件：

```powershell
Copy-Item .env.example .env
```

执行 [`docs/schema.mysql.sql`](docs/schema.mysql.sql)，然后在未提交的 `.env` 中填写：

```env
PERSISTENCE_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=campusguide_app
MYSQL_PASSWORD=你的本地密码
MYSQL_DATABASE=campusguide_fastapi
```

启动：

```powershell
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

访问：

- 完整网页：<http://127.0.0.1:8000/>
- Swagger：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

## 可选 Embedding 与真实模型

默认使用可离线复现的词法检索和 deterministic Agent provider，不调用外部 API。

Windows 下开启 Embedding 最简单的方式是双击 `enable_embedding.cmd`，粘贴自己的硅基流动
API Key。脚本会在本机创建 `.env`、启用 `Qwen/Qwen3-Embedding-4B` 并生成向量索引。
API Key、`.env` 和向量索引都不会提交到 Git。

手动方式：

```env
RAG_ENABLE_SEMANTIC_SEARCH=true
SILICONFLOW_API_KEY=你的Key
SILICONFLOW_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
```

```powershell
uv run --no-sync python -m app.build_vector_index
```

连接支持 Tool Calling 的 OpenAI-compatible 模型：

```env
AGENT_MODEL_PROVIDER=openai_compatible
AGENT_MODEL_BASE_URL=https://你的服务地址/v1
AGENT_MODEL_API_KEY=你的Key
AGENT_MODEL_NAME=支持工具调用的模型名
```

Embedding 或远程服务不可用时，检索会记录降级原因并回退词法模式，不影响基础问答。

## 请求链路

普通问答：

```text
网页 POST /api/chat
  -> Pydantic 校验问题与用户上下文
  -> 领域词、证据块、资料状态与同义词检索
  -> 判断证据是否达到回答阈值
  -> 有依据：回答 + 引用 + trace
  -> 无依据：拒答，不编造学校规则
  -> 记录 request ID、状态码和耗时
```

完整 Agent：

```text
POST /api/agent/run 或 /api/agent/stream
  -> 创建或继续 session，保存 user message
  -> 模型在白名单工具中选择调用
  -> 参数校验、工具超时和结果裁剪
  -> 保存 tool call、结果、耗时和状态
  -> 工具结果回填模型，直到回答或达到最大步数
  -> 保存 assistant message，并通过 SSE 输出执行事件
```

异步任务：

```text
POST /api/ingestion/tasks
  -> 唯一 idempotency_key 防止重复任务
  -> task_id 进入 asyncio.Queue
  -> worker 领取任务并写入租约
  -> 成功：succeeded
  -> 可重试失败：重新 queued
  -> worker 崩溃：租约过期后恢复
```

## 离线评测

固定评测集包含 65 条人工整理问题，其中 55 条可回答、10 条应拒答。V4 词法检索在当前
资料快照上的结果为：

| 指标 | 结果 |
| --- | ---: |
| Hit@1 | 85.45% |
| Hit@5 | 100.00% |
| MRR | 0.9082 |
| 拒答准确率 | 100.00% |

```powershell
uv run --no-sync python -m app.evaluate
```

这是固定资料快照上的离线回归结果，不代表线上用户满意度、并发性能或真实大模型效果。
完整版本对比见 [`docs/EVALUATION_REPORT.md`](docs/EVALUATION_REPORT.md)。

## 测试与代码质量

```powershell
.venv\Scripts\ruff.exe check app tests
.venv\Scripts\python.exe -m compileall -q app tests
.venv\Scripts\pytest.exe -q
```

当前常规测试覆盖网页入口、接口、检索、拒答、Tool Calling、SSE 顺序、并发幂等、JSON
原子写入、任务租约、Agent 循环和 Prompt 版本；真实 MySQL 集成测试在提供测试数据库时运行。

一个实际修复案例：Pydantic 默认会把字符串 `"false"` 转换为布尔值。如果 Tool Calling
参数不使用 `StrictBool`，错误反馈也可能被当成有效数据。项目使用严格类型并保留回归测试。

## 项目结构

```text
.
├── frontend/                   原 SUFE Guide 网页产品与本地降级数据
├── app/
│   ├── main.py                 应用生命周期、静态页面、request ID 日志
│   ├── routes.py               HTTP API
│   ├── models.py               Pydantic 请求模型
│   ├── retrieval.py            词法与混合 RAG
│   ├── agent.py                证据约束问答
│   ├── model_provider.py       离线/远程模型适配器
│   ├── tools.py                Tool Calling 白名单
│   ├── services/               Agent Runtime、反馈、异步任务
│   └── repositories/           MySQL 与 JSON 存储实现
├── data/                       公开结构化资料快照
├── docs/                       数据库脚本、评测报告和架构说明
├── tests/                      单元、接口、并发和集成测试
├── Dockerfile
├── docker-compose.yml
├── enable_embedding.cmd
└── start_demo.cmd
```

第一次阅读建议按 `models.py -> routes.py -> retrieval.py -> agent.py -> tools.py ->
services/agent_runtime.py -> services/tasks.py -> repositories/mysql.py` 的顺序进行。

## 与原 Node.js 仓库的关系

- 原仓库保留比赛过程、历史材料和 Node.js 工程演进；
- 本仓库保留同一产品界面与公开资料快照，后端由 Python/FastAPI 独立实现；
- 本仓库运行时不导入、不调用、也不要求启动原 Node.js 服务；
- 两个仓库用于展示从参赛原型到 Python Agent 后端工程化重构的过程。

原项目：<https://github.com/Felix-heinado/campusguide-sufe>

## 安全与边界

- 不要把模型 API Key、数据库密码或 `.env` 提交到仓库；
- 不要上传学号、证件号、成绩单、名单和未授权的内部文件；
- 公开知识库只保留经核验的官方公开资料或结构化摘要；
- 项目没有进行大规模压测，不宣称高并发或生产级 SLA；
- 当前未接入学校私有业务数据库；
- 本仓库未授予开源许可证，未经许可不得将代码或素材用于其他项目。

## 后续方向

1. 学校数据库正式开放后，增加资料表、版本字段和增量同步任务；
2. 将进程内队列替换为 Redis Streams 或 RabbitMQ，支持多实例可靠消费；
3. 增加 Prometheus 指标与 OpenTelemetry 链路追踪；
4. 增加 token 级模型流式输出；
5. 继续扩充人工标注评测集，分别评估检索、引用、拒答和最终回答。

# 财问 · SUFE Guide

面向上海财经大学学生的校园信息问答 Agent。项目把学校、学院和职能部门发布的公开资料整理为可检索知识库，回答时返回来源与证据；证据不足时拒答，不猜测学校政策。

这是 [`campusguide-sufe`](https://github.com/Felix-heinado/campusguide-sufe) 的 Python / FastAPI 工程版，前后端由同一服务提供，适合比赛展示、课程实践和 Agent 工程学习。

> 本项目是学生作品，不是上海财经大学官方信息系统。回答仅用于信息检索和政策理解，具体认定以学校及主管部门最新正式通知为准。

[![CI](https://github.com/Felix-heinado/campusguide-sufe-fastapi/actions/workflows/verify.yml/badge.svg)](https://github.com/Felix-heinado/campusguide-sufe-fastapi/actions/workflows/verify.yml)

## 功能

- 评奖评优、奖助学金、推免升学、就业、生涯规划、学工和校园生活问答。
- 返回资料标题、发布单位、日期、适用对象、原文入口和证据片段。
- 知识库搜索、主题筛选、学院/培养层次/年份上下文、收藏和匿名反馈。
- FastAPI、Pydantic、RAG、白名单 Tool Calling、Agent Runtime、SSE。
- MySQL 持久化会话、消息、Agent 运行、工具审计、反馈、检索事件和入库任务。
- Redis 分布式限流；健康检查、就绪探针、请求 ID、结构化日志和管理员 API Key。
- 默认 deterministic 离线模型；可选 OpenAI-compatible 模型和 Embedding。

当前异步任务队列使用进程内 `asyncio.Queue`，适合单机演示；多实例生产环境应替换为 Redis Streams、RabbitMQ 或 Kafka。

## 快速部署（Docker，推荐）

需要安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。

```powershell
git clone https://github.com/Felix-heinado/campusguide-sufe-fastapi.git
cd campusguide-sufe-fastapi
docker compose config -q
docker compose up --build -d
```

Windows 用户也可以直接双击 `quick_start.cmd`，它会启动 MySQL 8.4、Redis 7 和 FastAPI，并等待 API 就绪。

- 网页：<http://127.0.0.1:8000/>
- Swagger：<http://127.0.0.1:8000/docs>
- ReDoc：<http://127.0.0.1:8000/redoc>
- 健康检查：<http://127.0.0.1:8000/api/health>
- 就绪探针：<http://127.0.0.1:8000/api/ready>

```powershell
docker compose ps
docker compose logs -f api
docker compose down       # 停止服务，保留 MySQL volume
```

`docker compose down -v` 会删除本地 MySQL 数据，请谨慎使用。

## 本地开发

### JSON 离线模式

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
$env:PERSISTENCE_BACKEND="json"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### MySQL 完整模式

```powershell
pip install -e ".[dev,mysql,redis]"
Copy-Item .env.example .env
```

执行 [`docs/schema.mysql.sql`](docs/schema.mysql.sql)，在 `.env` 中填写 MySQL、Redis 和管理员配置，再启动 Uvicorn。已有旧数据库时，按顺序执行 `docs/migrations/` 中尚未执行的迁移脚本。

## 配置

配置由 `app/config.py` 读取，环境变量优先于 `.env`。`.env` 已被 Git 忽略，不能提交。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `PERSISTENCE_BACKEND` | `mysql` | `mysql` 或 `json` |
| `MYSQL_HOST` / `MYSQL_PORT` | `127.0.0.1` / `3306` | MySQL 地址 |
| `MYSQL_USER` / `MYSQL_PASSWORD` | - | 数据库账号 |
| `MYSQL_DATABASE` | `campusguide_fastapi` | 数据库名 |
| `RATE_LIMIT_BACKEND` | `memory` | `memory`、`redis` 或 `auto` |
| `REDIS_URL` | 空 | Redis 地址 |
| `ADMIN_API_KEY` | 空 | 保护管理接口 |
| `AGENT_MODEL_PROVIDER` | `deterministic` | 离线或 `openai_compatible` |
| `AGENT_MODEL_BASE_URL` | SiliconFlow | 模型 API 地址 |
| `AGENT_MODEL_API_KEY` | 空 | 模型密钥 |
| `AGENT_MODEL_NAME` | 空 | Tool Calling 模型名 |
| `RAG_ENABLE_SEMANTIC_SEARCH` | `false` | 启用 Embedding 混合检索 |

完整模板见 [`.env.example`](.env.example)。Docker Compose 默认密码只用于本地演示，部署到服务器前必须替换。

## 使用与 API

网页端输入问题即可开始。建议先试：

```text
评奖评优政策在哪里查看？
奖学金申请需要满足哪些条件？
推免、就业、生涯规划等信息该去哪里寻找？
```

```powershell
$body = @{ question = "奖学金申请需要满足哪些条件？"; context = @{ level = "本科生" } } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/chat -Method Post -ContentType "application/json" -Body $body

$body = @{ query = "推免"; limit = 5 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/api/search -Method Post -ContentType "application/json" -Body $body
```

`/api/chat` 返回 `answer`、`citations`、`retrieval`、`context` 和 `trace`。`/api/agent/run` 返回一次 Agent 运行结果，`/api/agent/stream` 以 SSE 输出执行事件。完整接口可在 Swagger 中试用。

设置 `ADMIN_API_KEY` 后，`/api/metrics/summary` 和 `/api/ingestion/tasks` 需要 `X-Admin-Key` 请求头。

## 资料库与合规

当前快照包含 122 份资料、1038 个证据块。用户提供的 `规章制度.zip` 已登记为可信资料源：81 个文件（PDF 62、DOCX 14、XLSX 3、XLS 1、DOC 1），SHA-256 为 `77dedc963883c64afaee12bd8b6141a2897bad3f72fdbd3fd66b2e660e9a24de`。说明见 [`docs/knowledge-sources/official-regulations-package.md`](docs/knowledge-sources/official-regulations-package.md)。

原始附件不提交到 GitHub，仓库只保留结构化资料快照。不要提交 `.env`、API Key、数据库密码、学号、证件号、成绩单、名单或未授权内部文件。

启用 Embedding：

```powershell
$env:RAG_ENABLE_SEMANTIC_SEARCH="true"
$env:SILICONFLOW_API_KEY="替换为你的 Key"
python -m app.build_vector_index
```

## 测试

```powershell
python -m ruff check app tests
python -m compileall -q app tests
python -m pytest -q
```

当前本地结果为 `46 passed，2 skipped`；跳过项是没有真实 MySQL 时的集成测试。GitHub Actions 会在 Ubuntu 上启动 MySQL 8.4 并执行测试。

## 故障排查

- Docker Engine 未就绪：确认 Docker Desktop 显示 Running，再运行 `docker info`。
- `/api/ready` 返回 503：运行 `docker compose ps` 和 `docker compose logs mysql redis api`；首次初始化 MySQL 需要等待几十秒。
- 模型不可用：检查模型地址、名称和密钥；比赛演示可使用默认 deterministic 模式。
- PowerShell 无法激活虚拟环境：直接运行 `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`。

## 项目结构

```text
app/                     FastAPI、Agent、RAG、工具、服务和仓储
data/                    结构化公开资料快照
docs/schema.mysql.sql    MySQL 初始化脚本
docs/migrations/         增量迁移脚本
docs/knowledge-sources/  资料来源登记
frontend/                同源网页产品
tests/                   单元、接口、Agent 和集成测试
Dockerfile               非 root FastAPI 镜像
docker-compose.yml       MySQL + Redis + FastAPI
quick_start.cmd          Windows 完整栈启动
.env.example             配置模板
```

## 贡献与许可

欢迎提交 Issue，反馈资料错误、检索问题、界面问题或部署体验。涉及学校政策的改动请提供官方来源和适用范围，并补充测试。

当前仓库未授予开源许可证。除非获得项目负责人明确许可，请不要将代码、界面素材或资料快照用于其他项目。

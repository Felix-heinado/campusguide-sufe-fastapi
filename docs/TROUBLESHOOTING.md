# 问题定位手册

## 服务无法启动

1. 检查 Python：`python --version`，应为 3.11 或更高；
2. 检查依赖：`.venv\Scripts\python.exe -c "import fastapi"`；
3. 检查 `.env`；
4. 若为 MySQL 模式，检查服务、账号、数据库和建表脚本。

## MySQL 连接失败

- `Access denied`：用户名或密码错误；
- `Unknown database`：未执行建库脚本；
- `Connection refused`：MySQL 服务未启动或端口错误；
- 连接池耗尽：请求未释放连接，或池容量过小。

不要在日志或截图中展示真实密码。

## 同一幂等键出现多个任务

1. 检查 `uq_ingestion_idempotency_key` 是否存在；
2. 检查请求是否真的传入相同非空 key；
3. 不要使用“先 SELECT、再 INSERT”的无事务写法；
4. 运行并发幂等测试复现。

## 任务一直处于 running

1. 查询 `worker_id` 与 `lease_expires_at`；
2. 判断 worker 是否崩溃；
3. 租约到期后重启服务，启动流程会回收任务；
4. 如果任务有外部副作用，重试前必须确认操作本身可幂等。

## 搜索结果不合理

查看响应中的：

- `matchedTokens`：命中了哪些词；
- `scoreBreakdown.lexical`：文本匹配分；
- `scoreBreakdown.metadata`：上下文加分；
- `matchedBy`：命中标题/关键词还是正文。

先构造最小问题和回归测试，再调整权重，不要只凭一次搜索结果改算法。


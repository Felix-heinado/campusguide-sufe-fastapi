# 7 天源码学习与面试复现计划

目标不是背诵项目介绍，而是做到：能运行、能画图、能改代码、能复现 bug、能回答追问。
每天建议 4-6 小时。

## 第 1 天：跑通项目和 HTTP 基础

阅读：`app/main.py`、`app/routes.py`、`app/models.py`。

实践：

1. 启动服务并打开 `/docs`；
2. 调用 health、search、chat；
3. 故意发送空问题、超长问题、错误 limit；
4. 找到日志中的 request ID、状态码和耗时。

必须能回答：

- FastAPI 如何把 JSON 转成 Pydantic 对象？
- 400、404、422、500 分别代表什么？
- request ID 对排查线上问题有什么用？
- 为什么配置写在环境变量，而不是代码里？

当天改动：给 health 增加一个 `version` 字段，并补测试。

## 第 2 天：RAG 和拒答

阅读：`app/knowledge_base.py`、`app/retrieval.py`、`app/agent.py`。

实践：

1. 打印“挂科重修”的 token；
2. 调整 title 权重，观察排名变化；
3. 比较“挂科重修”和“挂科重修怎么办去哪办理”；
4. 用无关问题触发拒答。

必须能回答：

- RAG 的 Retrieve、Augment、Generate 分别是什么？
- 为什么“怎么办”“去哪”不应成为核心关键词？
- chunkId 与 documentId 有什么区别？
- 如何减少幻觉？为什么无证据时要拒答？
- 词法检索和 embedding 向量检索各有什么优缺点？

当天改动：新增一个停用词，并用测试证明排名没有被通用意图词改变。

## 第 3 天：Tool Calling

阅读：`app/tools.py`、`app/services/feedback.py`。

实践：

1. 调用四个工具；
2. 尝试调用不存在的工具；
3. 将 `helpful` 传成字符串，观察 StrictBool 拒绝请求；
4. 查看 feedback 只保存问题哈希，不保存原问题。

必须能回答：

- Tool Calling 为什么要白名单？
- 为什么不能直接执行模型生成的函数名和参数？
- Pydantic 默认类型转换带来了什么 bug？
- 为什么反馈保存 question hash？
- 工具超时、失败或返回错误格式应如何处理？

当天改动：为 `get_document` 增加一个参数错误测试。

## 第 4 天：MySQL

阅读：`docs/schema.mysql.sql`、`app/repositories/base.py`、
`app/repositories/mysql.py` 前半部分。

实践：

1. 创建数据库和应用账号；
2. 切换 `PERSISTENCE_BACKEND=mysql`；
3. 记录一条 feedback；
4. 查询表和索引；
5. 尝试插入重复 feedback_id。

必须能回答：

- 为什么使用连接池？
- 参数化 SQL 如何防止 SQL 注入？
- 主键、唯一索引、普通索引有什么区别？
- 为什么幂等键需要唯一索引？
- 事务的 ACID 是什么？

当天改动：为 `question_hash` 的查询写一条 SQL，并用 EXPLAIN 查看索引。

## 第 5 天：异步任务、队列和租约

阅读：`app/services/tasks.py`、`app/repositories/mysql.py` 后半部分。

实践：

1. 连续创建两个不同任务；
2. 使用相同幂等键并发创建 20 次；
3. 观察 queued -> running -> succeeded；
4. 运行失败任务，观察 retry_count；
5. 修改测试中的租约时间，复现过期回收。

必须能回答：

- 为什么耗时任务不应阻塞 HTTP 请求？
- `asyncio.Queue` 与 Kafka/RabbitMQ 有什么区别？
- 幂等和去重有什么区别？
- 两个 worker 如何避免领取同一任务？
- worker 崩溃后为什么需要租约？
- 重试为什么可能导致重复副作用？

当天改动：把 worker 数量从 2 改成 3，确认测试仍通过。

## 第 6 天：测试、并发和问题定位

阅读：`tests/` 全部文件、`app/logging_config.py`。

实践：

1. 逐个运行测试；
2. 故意破坏幂等逻辑，看并发测试失败；
3. 恢复代码；
4. 故意把 `StrictBool` 改回 `bool`，复现字符串布尔 bug；
5. 用 request ID 查找一次完整请求日志。

必须能回答：

- 单元测试、接口测试、并发测试分别验证什么？
- 为什么“测试通过”不能证明系统没有 bug？
- 如何定位一个偶发 500？
- 为什么日志不能输出 API Key 和用户隐私？
- 原子 JSON 替换解决了什么问题？为什么仍不能替代 MySQL？

当天改动：为一个 404 场景补测试。

## 第 7 天：完整项目盘问演练

完成三遍 5 分钟项目介绍：

1. 业务问题：校园规则分散、年份和适用范围容易混淆；
2. 技术方案：FastAPI + RAG + Tool Calling + MySQL + 异步任务；
3. 真实问题：严格布尔校验、并发幂等、worker 租约恢复；
4. 取舍：先用可解释词法 RAG，embedding 作为下一阶段；
5. 边界：没有虚构消息队列、大规模并发或学校私有数据。

手画三张图：

- chat 请求链路；
- task 状态机；
- MySQL 幂等与 worker 租约流程。

最后从空环境重新执行：安装、建库、启动、调用接口、跑测试。只有能独立复现，才算
真正掌握，而不是“看过代码”。


# AI Customer Support System — 当前系统架构

## 1. 项目定位

AI Customer Support System 是一个面向电商售后场景的 AI 应用。系统以自然语言对话为入口，将 LLM 对话、业务知识检索、受限的 Tool Calling、确定性业务规则和持久化 Workflow 组合为完整的应用链路。

系统覆盖会话与消息持久化、业务政策与 SOP 检索、customer-scoped 物流查询、确定性物流异常判断，以及由用户显式启动和继续的退货资格 Workflow。

它与通用 AI Chat 的核心区别在于：LLM 负责理解意图、选择受支持的 Tool 和组织回答，但不提供可信身份，不拥有实时业务状态，也不决定确定性业务规则或持久化 Workflow 状态。业务状态和业务判断保留在应用层 / 业务层；持久化 Workflow 执行前必须经过 Human Gate。

## 2. 系统架构

![AI Customer Support System 当前系统架构](./current-system-architecture.svg)

可版本化的图表源文件：[`current-system-architecture.dot`](./current-system-architecture.dot)。

图中橙色虚线节点表示 probabilistic AI behavior，绿色节点表示 deterministic business / workflow authority，紫色节点表示 Human Gate。`workflow_handoff` 只传递进入 Workflow UI 的建议，不会直接创建 durable Workflow。

## 3. 核心组件与职责边界

| 组件 | 主要职责 | 职责边界 |
|---|---|---|
| LLM Provider | 流式生成回答，或选择一个受支持的 Tool；Tool 执行后再组织自然语言回复。 | 可以进行意图 routing 和结果解释；不提供可信身份，不拥有业务状态、确定性规则或 Workflow lifecycle。 |
| `ChatService` / Application Layer | 持久化对话消息、构建上下文、调用 RAG、验证 Tool Call、执行受限的 Tool 路径并产生 SSE 事件。 | 负责应用编排与输入验证；不替代 `BusinessService` 做业务判断，也不会在 AI handoff 时创建 Workflow。 |
| RAG（`VectorRetriever` + Chroma） | 检索业务政策与 SOP，将符合上下文 token budget 的知识片段加入 LLM 上下文，并返回来源引用。 | 检索结果用于解释业务政策，不决定实时业务状态、数据归属、物流异常或退货资格。 |
| Tool execution | 只接受已声明的 provider-neutral Tool schema，验证参数，注入由应用控制的 Demo Customer Context，并返回安全、受限的结果。 | 不接受模型提供的 customer identity；可以执行 customer-scoped read 或准备 handoff，但不能自治创建 Workflow。 |
| `BusinessService` | 读取当前客户范围内的业务数据，并执行物流异常、退货资格等 deterministic rule。 | 业务判断在服务层完成，不由 LLM、Prompt 或 RAG 内容推断；当前服务不提供 Production Authentication。 |
| Repository / PostgreSQL | 持久化 Conversation、Message、业务实体和 Workflow record；执行 customer-scoped read 与 guarded state transition。 | PostgreSQL 中的持久化数据是应用的权威状态；Repository 不把 ownership 或状态判断交给 LLM。 |
| `WorkflowService` | 启动和恢复退货资格 Workflow，调用 `BusinessService`，并持久化 lifecycle transition。 | 负责 Workflow orchestration，不负责定义 eligibility rule；当前 Workflow 为 read-only，且只覆盖退货资格检查。 |
| Next.js Frontend | 展示 SSE 输出、来源和 Workflow panel，并保存 Conversation-to-Workflow correlation。 | Frontend UI state 与浏览器中的关联信息都不是 Workflow authority。 |
| Human User | 显式点击 **Start check**，并选择用于 Resume 的购买项。 | Human action 是 durable Workflow 的 start / continuation boundary；用户输入不是 trusted customer identity 的来源。 |

当前业务身份由应用控制的 [`DEMO_CUSTOMER_ID`](../../backend/app/core/demo_principal.py) 提供。它是固定的 Demo Customer Context，不代表系统已经具备 Production Authentication 或真实用户 ownership。

## 4. 关键运行路径

### Streaming Chat

Frontend 向 `POST /chat/stream` 提交消息。`ChatService` 创建或读取 Conversation，持久化 User Message，按 token budget 组装会话上下文，并创建 streaming Assistant Message record。Provider 随后以流式方式返回内容，或返回一个受支持的 Tool Call。

FastAPI 将服务事件转换为 SSE；Frontend 增量展示 token 与来源。流式执行结束后，Assistant Message 的 `completed` 或 `failed` 状态写入 PostgreSQL。

关键实现：[`stream.py`](../../backend/app/api/routes/stream.py)、[`chat_service.py`](../../backend/app/services/chat_service.py)、[`stream.ts`](../../frontend/src/lib/stream.ts)、[`useStreamingChat.ts`](../../frontend/src/hooks/useStreamingChat.ts)。

### Business Knowledge Retrieval

启用 `use_rag` 后，`VectorRetriever` 为查询生成 embedding，并检索持久化的 Chroma collection。`ContextBuilder` 只加入符合上下文 token budget 的 chunk；实际使用的 chunk 同时作为来源引用返回 Frontend。

检索得到的知识用于补充业务政策和 SOP 解释，不会覆盖 PostgreSQL 中的实时业务状态，也不会替代 `BusinessService` 的确定性业务判断。

关键实现：[`retriever.py`](../../backend/app/rag/retriever.py)、[`vector_store.py`](../../backend/app/rag/vector_store.py)、[`context_builder.py`](../../backend/app/services/context_builder.py)。

### Business Tool Execution

当 Provider 返回 `get_shipment_status` 时，`ChatService` 先验证 Tool name、参数集合和 Shipment UUID。Application 随后注入 trusted Demo Customer；`BusinessRepository` 在 SQL 查询中执行 customer scope；`BusinessService` 根据当前 Shipment state 运行 logistics-exception rule。

Tool 只返回当前对话所需的安全结果。第二次 LLM 调用可以解释该结果，但不能改变其中的实时状态或确定性业务判断。

关键实现：[`chat_service.py`](../../backend/app/services/chat_service.py)、[`business_service.py`](../../backend/app/services/business_service.py)、[`business_repository.py`](../../backend/app/repositories/business_repository.py)。

### Return Eligibility Workflow

自然语言退货请求首先进入 AI layer。Provider 可以选择 `request_return_eligibility_check`；Application 验证该 Tool 后，只产生 transient `workflow_handoff` SSE event，用于打开 Frontend 中的退货资格 UI。此时没有 durable Workflow，也没有 eligibility result。

Human 点击 **Start check** 后，Frontend 才调用 `POST /workflows`，创建 `waiting_for_clarification` 状态的 Workflow。用户选择购买项后，`POST /workflows/{workflow_id}/resume` 将 Workflow ID、Conversation ID 与 trusted customer 一起提交：

1. `WorkflowRepository` 原子 claim `waiting_for_clarification → running`，避免两个 Resume 同时取得 execution ownership。
2. `BusinessService` 重新读取 customer-scoped 当前业务状态，并执行 return eligibility rule。
3. Repository guard `running → completed`，API 返回 deterministic outcome。

这条路径明确区分 AI 建议、Human action 和 durable execution。当前实现不提供 claimed Workflow 在 `running` 阶段失败后的 automatic recovery。

关键实现：[`chat_service.py`](../../backend/app/services/chat_service.py)、[`ChatPanel.tsx`](../../frontend/src/components/chat/ChatPanel.tsx)、[`ReturnEligibilityWorkflow.tsx`](../../frontend/src/components/workflow/ReturnEligibilityWorkflow.tsx)、[`workflows.py`](../../backend/app/api/routes/workflows.py)、[`workflow_service.py`](../../backend/app/services/workflow_service.py)、[`workflow_repository.py`](../../backend/app/repositories/workflow_repository.py)。

## 5. 持久化与状态边界

| Store | 保存内容 | Authority Boundary |
|---|---|---|
| PostgreSQL | Conversation / Message、Commerce Entity 与当前业务状态、持久化 Workflow record 与 lifecycle transition。 | 业务状态和 Workflow lifecycle 的持久化来源。 |
| Chroma | Business Policy 与 SOP 的 persistent vector index。 | 提供知识上下文，不保存或决定实时业务状态。 |
| Browser `localStorage` | Conversation-to-Workflow correlation。 | 只帮助同一浏览器在 refresh 后恢复关联；不是 Workflow lifecycle 或 eligibility authority。 |

Conversation State、Business State 与 Workflow State 相互分离。对应 model 可见 [`conversation.py`](../../backend/app/models/conversation.py)、[`message.py`](../../backend/app/models/message.py)、[`business.py`](../../backend/app/models/business.py)、[`workflow.py`](../../backend/app/models/workflow.py)。

## 6. 工程验证

系统架构由可重复执行的工程验证支持，主要入口包括：

- Deterministic Chat / Tool / Workflow regression：[`tests/`](../../backend/tests/) 与 [`verify_workflow.py`](../../backend/app/scripts/verify_workflow.py)
- Retrieval evaluation：[`evaluate_business_knowledge_retrieval.py`](../../backend/app/scripts/evaluate_business_knowledge_retrieval.py)
- Execution observability：[`test_chat_observability.py`](../../backend/tests/test_chat_observability.py) 与 [`test_workflow_observability.py`](../../backend/tests/test_workflow_observability.py)
- GitHub Actions CI：[quality.yml](../../.github/workflows/quality.yml)
- Runtime / bootstrap：[`RUNTIME_CONFIGURATION.md`](../engineering/RUNTIME_CONFIGURATION.md)
- Business authority implementation：[business_service.py](../../backend/app/services/business_service.py)

## 7. 当前实现边界

当前系统定位为可复现的 reviewer/demo AI 应用，重点验证 LLM 与实时业务状态、deterministic rule、受限 Tool Calling 和持久化 Workflow 的集成。以下能力不在当前实现范围内：

- Production Auth、anonymous public paid-LLM access、production multi-user isolation；
- High Availability、autoscaling、Kubernetes；
- generic autonomous ReAct / Planning / Multi-Agent；
- MCP L3 production integration；
- autonomous controlled-write mutation；
- general-purpose Workflow Engine。

当前 Workflow 是由 Human 启动的 durable、read-only 退货资格检查；本文档描述现有实现，不指定后续功能或演示场景。

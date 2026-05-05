# Agentic_Content_Optimizer 的 LangGraph 业务闭环详解

## 1. 这份文档只回答一个问题

这份文档不讨论“混合架构怎么裁剪”，也不讨论“控制层底座怎么手搓”，只回答下面这一个问题：

**`Agentic_Content_Optimizer` 的 LangGraph 版本，围绕一次内容生成请求，到底是怎么把业务闭环跑起来的？**

也就是说，我们只关心这条主链：

`请求入口 -> LangGraph 状态机 -> Trend -> Director -> Writer -> Critic -> Refinement -> final_content -> trace -> outcome -> reward 回灌`

如果把这份文档彻底看懂，应该能不翻源码也讲清楚：

- 一次请求是如何进入 LangGraph 工作流的
- 工作流里的共享 `state` 到底长什么样
- 每个节点分别做什么、读什么、写什么
## 2. 先把整条链记成一句话

LangGraph 版本的核心不是把几个 Agent 串起来，而是：

**围绕一份共享状态 `ContentGenerationState` 运转的、带条件分支和循环的工作流图。**

一次完整的 `full_pipeline` 请求，大致会经历：

```text
API 请求
  -> create_workflow()
  -> _resolve_execution_config()
  -> workflow.run(initial_state)
  -> route_start
  -> trend_analysis
  -> director_sample
  -> content_generation
  -> content_evaluation
  -> refinement（如果未达标）
  -> content_generation（再次生成）
  -> ... 最多循环到阈值或最大轮次
  -> 输出 final_content / final_score
  -> 记录 Trace
  -> 后续采集 Outcome
  -> delayed reward 回灌 RL / bandit
```

如果只记一句话，就记这句：

**LangGraph 版本做的是“受控状态机 + 结构化节点产物 + 质量门控 + 延迟学习回灌”。**
## 3. 先看参与这条闭环的核心文件

最重要的文件可以先抓这几类：

- 请求与配置层
  - `backend/app/api/v1/api_v5_langgraph.py`
  - `backend/app/engine/runtime_config.py`
- LangGraph 编排层
  - `backend/app/engine/agents/workflow/langgraph_workflow.py`
- 业务 Agent 层
  - `backend/app/engine/agents/content/trend_agent.py`
  - `backend/app/engine/agents/content/writer_agent.py`
  - `backend/app/engine/agents/content/critic_agent.py`
- 策略与学习层
  - `backend/app/ml/rl/action_space.py`
  - `backend/app/ml/rl/thompson_sampling.py`
  - `backend/app/ml/rl/outcome_reward_bridge.py`
- 追踪与结果同步层
  - `backend/app/core/tracer.py`
  - `backend/app/ml/training/schemas.py`
  - `backend/app/tasks/outcome_sync_tasks.py`

可以把它们理解成四层：

### 3.1 请求与控制层

负责把一次 API 请求翻译成一次可执行的 workflow run。

### 3.2 LangGraph 编排层

负责定义状态、节点、条件边、循环退出规则。

### 3.3 业务节点层

负责真正做业务加工：

- Trend 准备上下文
- Writer 生成内容
- Critic 评估内容

### 3.4 学习与回灌层

## 4. 一次请求进入系统后，API 层先做了什么

主入口在 `api_v5_langgraph.py` 的 `generate_content_with_workflow()`。

这一层不是直接生成内容，而是在做一次 workflow 执行前的准备。大致步骤是：

1. 接收 `WorkflowGenerateRequest`
2. 做限流、并发控制、超时控制
3. 创建这次请求专属的 workflow 实例
4. 调 `_resolve_execution_config()` 把产品参数翻译成真正影响主链的控制参数
5. 把更完整的运行细节打包进 `runtime_config`
6. 构造 `initial_state`
7. 调 workflow 执行
8. 把最终 state 投影成 API 返回结果

这里最值得记住的一句是：

**API 层不是业务执行层，它是“把一次外部请求翻译成一次工作流执行”的地方。**

### 4.1 先用一句话记住这里在做什么

如果把这一层压成一句话，就是：

**`WorkflowGenerateRequest -> execution_config -> runtime_config -> initial_state -> workflow.run(...)`**

也就是说，API 层真正做的是“翻译和打包”，不是“直接做业务生成”。

### 4.2 `_resolve_execution_config()` 在做什么

它做的是：

**把面向调用方的产品参数，翻译成 workflow 真正要直接拿来控制主链的少数几个关键值。**

典型产物包括：

- `max_loops`
- `quality_0_10`
- `quality_0_100`

这里最重要的不是字段名，而是要明白：

- 外部请求参数
  - 不一定能直接控制 workflow
- execution_config
  - 才是 workflow 外壳真正认的总控值

### 4.3 `runtime_config` 为什么重要

如果说 `execution_config` 是总控参数，那 `runtime_config` 更像：

**发给各工位的详细作业单。**

它保留的是各节点执行时还要查的细粒度说明，比如：

- Trend 检索 top_k 多少
- LLM provider/model/temperature 是什么
- RL 是否启用 Thompson Sampling
- exploration_rate 多少
- 是否启用 geo / hook / cta 策略

所以：

- `execution_config`
  - 更偏 workflow 总控
- `runtime_config`
  - 更偏节点执行说明

### 4.4 请求参数的四层形式：`request -> execution_config -> runtime_config -> initial_state`

这一层最容易乱，所以最适合直接用一个具体请求样例来记。

#### 第一层：`WorkflowGenerateRequest`

这层是给前端 / 调用方看的，字段多、语义偏产品层。

一个具体例子可以长这样：

```json
{
  "topic": "AI 提效工具",
  "platform": "xiaohongshu",
  "goal_metric": "engagement",
  "target_audience": "25-35岁职场人",
  "content_style": "专业、轻松",
  "quality_threshold": 80,
  "max_iterations": null,
  "rag_mode": "adaptive",
  "rag_hybrid_search": true,
  "rag_top_k": 8,
  "rag_query_expansion": true,
  "rag_context_compression": true,
  "rag_trend_quality_filter": true,
  "thompson_sampling_enabled": true,
  "grpo_enabled": false,
  "reward_preset": "balanced",
  "custom_reward_weights": null,
  "exploration_rate": 0.15,
  "agent_mode": "full_pipeline",
  "max_refinement_loops": 4,
  "human_review_enabled": false,
  "llm_provider": "claude",
  "llm_model": "claude-sonnet-4-5-20250514",
  "temperature": 0.7,
  "max_tokens": 4096,
  "enable_geo_keywords": true,
  "enable_hook_strategy": true,
  "enable_cta_strategy": true
}
```

这层的特点是：

- 字段很多
- 语义偏产品层 / 调用层
- 兼顾用户友好和兼容性
- 不适合直接拿去驱动 workflow 内核

#### 第二层：`execution_config`

API 会先把原始请求翻译成少数几个真正影响主链执行的总控参数。

对上面的例子，它大致会变成：

```json
{
  "max_loops": 4,
  "quality_0_10": 8.0,
  "quality_0_100": 80.0
}
```

为什么会是这几个值：

- `max_loops = 4`
  - 因为 `max_iterations` 没给值，系统会回退到 `max_refinement_loops = 4`
- `quality_0_100 = 80.0`
  - 直接保留原始质量阈值语义
- `quality_0_10 = 8.0`
  - 因为 workflow 里很多评分逻辑按 `0-10` 口径在跑

#### 第三层：`runtime_config`

然后 API 还会把请求打包成更完整的结构化运行时配置，供各节点执行时读取。

对同一个例子，它大致会长这样：

```json
{
  "request_id": "uuid",
  "user_id": "123",
  "rag": {
    "mode": "adaptive",
    "hybrid_search": true,
    "top_k": 8,
    "query_expansion": true,
    "context_compression": true,
    "trend_quality_filter": true
  },
  "llm": {
    "provider": "claude",
    "model": "claude-sonnet-4-5-20250514",
    "temperature": 0.7,
    "max_tokens": 4096
  },
  "rl": {
    "thompson_sampling_enabled": true,
    "exploration_rate": 0.15,
    "reward_preset": "balanced",
    "custom_reward_weights": null
  },
  "agent": {
    "mode": "full_pipeline",
    "max_refinement_loops": 4,
    "quality_threshold_0_100": 80.0,
    "human_review_enabled": false
  },
  "generation": {
    "enable_geo_keywords": true,
    "enable_hook_strategy": true,
    "enable_cta_strategy": true
  },
  "extra": {}
}
```

这里要注意两点：

- `runtime_config`
  - 不是主链总循环的唯一控制开关
- 它更像“各节点还能查到的完整运行说明”

#### 第四层：`initial_state`

最后 workflow.run(...) 会把这些信息和初始业务字段合成真正送进 LangGraph 图里的起始状态。

沿用同一个例子，它大致可以理解成：

```json
{
  "topic": "AI 提效工具",
  "platform": "xiaohongshu",
  "goal_metric": "engagement",
  "target_audience": "25-35岁职场人",
  "content_style": "专业、轻松",
  "trend_analysis": {},
  "references": [],
  "selected_action": {},
  "policy_id": "",
  "generated_content": {},
  "evaluation": {},
  "iteration": 0,
  "max_iterations": 4,
  "messages": [],
  "final_content": {},
  "final_score": 0.0,
  "cover_candidates": [],
  "token_budget_remaining": 30000,
  "runtime_config": {
    "...": "同上"
  }
}
```

这就是：

**真正进入 LangGraph 图里的起始状态。**

#### 这四层分别服务谁

可以这样记：

- `WorkflowGenerateRequest`
  - 服务调用方
- `execution_config`
  - 服务 workflow 总控层
- `runtime_config`
  - 服务节点执行层
- `initial_state`
  - 服务图运行本身

#### 为什么项目里要同时保留 `execution_config` 和 `runtime_config`

因为它们不是同一层东西。

最直观的区别是：

- `execution_config`
  - 只保留“真正直接影响主链执行”的少数值
- `runtime_config`
  - 保留“节点运行时还能查到的完整配置语义”

例如：

- `quality_threshold = 80`
  - 会被翻译成：
    - `execution_config.quality_0_10 = 8.0`
  - 同时也保留为：
    - `runtime_config.agent.quality_threshold_0_100 = 80.0`

这不是纯重复，而是：

- 一个给总控层直接比较
- 一个给节点层保留原始业务语义

### 4.5 先用一句话记住这四层关系

最准确的压缩版是：

- `WorkflowGenerateRequest`
  - 用户想怎么跑
- `execution_config`
  - workflow 总控实际按什么跑
- `runtime_config`
  - 各节点执行时还能查到什么配置
- `initial_state`
  - 把这些信息和业务状态合并后，真正送进 LangGraph 图的起点

### 4.6 重要参数结构的业务语义：哪些参数不是“纯技术配置”

这里最容易误解的是：很多参数看起来像技术开关，其实背后已经带业务语义。

#### 第一组：业务任务定义参数

- `topic`
- `platform`
- `goal_metric`
- `target_audience`
- `content_style`

它们回答的是：

**这次到底要做什么内容。**

#### 第二组：工作流控制参数

- `agent_mode`
- `quality_threshold`
- `max_iterations`
- `max_refinement_loops`

它们回答的是：

**这条状态机怎么跑、最多跑几轮、什么时候停。**

#### 第三组：RAG / 上下文供给参数

- `rag_mode`
- `rag_hybrid_search`
- `rag_top_k`
- `rag_query_expansion`
- `rag_context_compression`
- `rag_trend_quality_filter`

它们回答的是：

**Trend 节点给 Writer / Critic 提供多少、什么样的上下文。**

#### 第四组：策略学习参数

- `thompson_sampling_enabled`
- `exploration_rate`
- `reward_preset`
- `custom_reward_weights`

它们回答的是：

**Director / bandit 这层是更保守地利用历史，还是更积极地探索新策略。**

#### 第五组：生成策略约束参数

- `enable_geo_keywords`
- `enable_hook_strategy`
- `enable_cta_strategy`

它们回答的是：

**Writer 这一轮生成时，到底要不要显式带这些策略约束。**

#### 第六组：LLM 运行参数

- `llm_provider`
- `llm_model`
- `temperature`
- `max_tokens`

这组才更接近通常意义上的“技术配置”。

#### 第七组：身份与追踪参数

- `request_id`
- `user_id`
- `session_id`

它们会贯穿：

- trace
- outcome
- delayed reward

所以不是无关紧要的元数据。

### 4.7 哪几组参数最值得优先看懂

如果你不是要一次性吃透全部参数，最值得先看懂的是这四组：

- 业务任务定义参数
  - 决定内容任务是什么
- 工作流控制参数
  - 决定主链怎么跑、跑几轮、什么时候停
- RAG / 上下文供给参数
  - 决定 Writer / Critic 吃到什么上下文
- 策略学习参数
  - 决定 Director / RL 这一层怎么选策略

这四组看懂了，主链的大多数业务行为就能解释清楚。

---

## 5. LangGraph 里真正被编排的东西：`ContentGenerationState`

LangGraph 主链真正编排的，不是一串对话消息，而是共享状态对象 `ContentGenerationState`。

可以先把它理解成：

**一次 workflow run 的共享黑板。**

Trend、Director、Writer、Critic、Refinement 这些节点，都是围绕这份 state 在读写。

### 5.1 一次 workflow 有几份 state

一次 workflow run，主逻辑上维护的是：

**一份持续演化的当前 state。**

不是每个节点各自长期持有一份独立 state。

这点很重要，因为它直接决定了整条主链的通信方式：

- 节点之间不是直接“函数套函数”地传参
- 也不是靠一大段自然语言上下文持续接龙
- 而是共同读写这一份共享状态

所以真正的运行模式更接近：

`node A 写 state -> node B 读 state -> node C 再继续写 state`

### 5.2 这份 state 里会放什么

可以粗分成四类：

- 任务定义
  - `topic`
  - `platform`
  - `goal_metric`
  - `target_audience`
  - `content_style`
- 中间业务结果
  - `trend_analysis`
  - `references`
  - `selected_action`
  - `policy_id`
  - `generated_content`
  - `evaluation`
- 控制与迭代信息
  - `mode`
  - `iteration`
  - `max_iterations`
  - `token_budget_remaining`
  - `runtime_config`
  - `request_id`
- 轨迹与最终结果
  - `messages`
  - `final_content`
  - `final_score`
  - `cover_candidates`

### 5.3 用一个最小 state 骨架记住它

如果只用一个最小 JSON 骨架来记 `ContentGenerationState`，大概可以先记成：

```json
{
  "topic": "AI 提效工具",
  "platform": "xiaohongshu",
  "goal_metric": "engagement",
  "target_audience": "25-35岁职场人",
  "content_style": "专业、轻松",

  "trend_analysis": {},
  "references": [],
  "selected_action": {},
  "policy_id": "",

  "generated_content": {},
  "evaluation": {},

  "iteration": 0,
  "max_iterations": 3,
  "token_budget_remaining": 12000,
  "runtime_config": {},

  "messages": [],
  "final_content": {},
  "final_score": 0.0,
  "cover_candidates": []
}
```

真正运行时当然会更复杂，但这个骨架已经足够抓住它的核心角色：

- 前半段放输入和上下文
- 中间放当前轮的中间结果
- 后半段放控制信息、轨迹和最终结果

### 5.4 这几个字段最值得先记住

- `generated_content`
  - 当前这一轮最新生成结果
- `evaluation`
  - 当前这一轮最新 Critic 评估结果
- `final_content`
  - 到目前为止最好的一版
- `messages`
  - 运行轨迹记录

如果只抓这 4 个字段，你已经能大致看懂：

- 当前轮生成出了什么
- 当前轮 Critic 怎么判
- 系统目前保留的最佳结果是什么
- 整条主链一路是怎么走过来的

### 5.5 为什么说它比“消息历史”更像真正的业务载体

如果只靠消息历史推进 workflow，会有两个典型问题：

- 节点输入边界不清楚
- 历史越来越长后，很难稳定知道“现在真正有效的业务状态到底是什么”

而 `ContentGenerationState` 的好处是：

- `references` 是正式字段
- `selected_action` 是正式字段
- `generated_content` 是正式字段
- `evaluation` 是正式字段

也就是说，真正影响闭环推进的业务数据，不需要再从长对话里猜，而是显式写在 state 上。

这一点对 ACO 很关键，因为它让：

- Trend
- Director
- Writer
- Critic
- Refinement

这些节点之间的边界清楚得多。

### 5.6 它和 Anthropic 式 `context reset` 像在哪里

这里和 Anthropic 那套 Harness 有一个理念上的相似点：

**都在把真正重要的任务状态，从脆弱的长自然语言上下文里搬出来。**

Anthropic 讲 `context reset` 时，核心思想是：

- 不要把任务完全绑死在一条越拖越长的上下文里
- 当上下文过长、模型状态开始变差时
- 用结构化 handoff document 把真正重要的状态传下去

ACO 的 `ContentGenerationState` 虽然不是同一种机制，但方向是类似的。

它也在把真正决定闭环推进的状态显式外置出来，例如：

- `references`
- `selected_action`
- `policy_id`
- `generated_content`
- `evaluation`
- `iteration`

这意味着主链推进不依赖一整条自然语言聊天记录，而是更多依赖：

- 显式 state
- 节点级输入重建

### 5.7 它和 Anthropic 式 `context reset` 不像在哪里

真正的区别也要说清楚：

- Anthropic 的 `context reset`
  - 更像“旧上下文不用了，交接给一个新执行体”
- ACO 的 `ContentGenerationState`
  - 更像“共享黑板一直在，但每个节点只从黑板里取自己要的那一部分”

也就是说，ACO 当前更像：

- `state blackboard`
- `node-level context rebuild`

而不是：

- `full reset`
- `handoff doc`
- `new execution context`

所以更准确的一句话是：

**ACO 已经有“把重要状态从长上下文里外置出来”的味道，但它更像结构化黑板 + 节点级 context rebuild，还不是 Anthropic 那种重型的 context reset 机制。**

### 5.8 为什么这点对 ACO 特别重要

因为 ACO 天然就是一条显式节点链：

- `trend_analysis`
- `director_sample`
- `content_generation`
- `content_evaluation`
- `refinement`

这种结构本来就比“单个聊天式 Agent 拖着整段上下文连续工作”更容易做上下文收口。

对它来说，第一优先级不是立刻引入重型 reset 机制，而是：

1. 把 `business state` 设计清楚
2. 把每个节点的输入边界划清
3. 再在必要时给 Writer / Critic 节点内部加更强的 handoff 或 reset

所以如果把这节压成一句更实用的话：

**对于 ACO 这类 workflow 系统，先把 state 设计清楚，通常比先做上下文清空机制更重要。**

---

## 6. LangGraph 图本身是怎么定义的

真正的节点图定义在 `langgraph_workflow.py` 的 `_build_workflow()`。

### 6.1 真正注册进图里的业务节点有哪些

源码里真正 `add_node(...)` 进去的业务节点是：

- `route_start`
- `trend_analysis`
- `director_sample`
- `content_generation`
- `content_evaluation`
- `refinement`
- `cover_generation`

也就是说，这条 LangGraph 主链不是一个抽象概念，而是一张比较明确的状态机图。

### 6.2 这张图的主路径是什么

如果按最完整的 `full_pipeline` 看，主路径是：

`route_start -> trend_analysis -> director_sample -> content_generation -> content_evaluation`

然后再根据评估结果决定：

- 是否进入 `refinement`
- 是否转 `cover_generation`
- 是否直接结束

### 6.3 不达标时的回环是怎么接的

这条图真正有“闭环味道”的地方在这里：

`content_evaluation -> refinement -> content_generation`

也就是说：

- 先生成
- 再评估
- 如果不满意，就进 refinement
- 然后回到下一轮 `content_generation`

所以这不是单向流水线，而是一条带局部回环的工作流。

### 6.4 达标时又是怎么结束的

如果评估已经达标，或者当前模式不需要继续迭代，就不会再进 `refinement`，而是：

- 直接 `END`
- 或者先去 `cover_generation` 再 `END`

所以这张图里其实同时存在三类边：

- 主路径边
- refine 回环边
- 结束边

### 6.5 哪些函数不是节点，但非常关键

- `_route_after_generation()`
- `_should_refine()`

它们不是业务节点，而是：

**条件分流函数。**

也就是：

- 节点负责干活
- 条件函数负责决定下一条边往哪走

这点一定要分清，不然后面分析主链时很容易把两种东西混起来：

- `content_generation`
  - 是节点
- `_route_after_generation()`
  - 不是节点，是从这个节点出来后的条件路由
- `content_evaluation`
  - 是节点
- `_should_refine()`
  - 不是节点，是从这个节点出来后的条件路由

### 6.6 用一张最小图把它记住

```text
route_start
  -> full_pipeline: trend_analysis -> director_sample -> content_generation -> content_evaluation
  -> 简化模式: content_generation

content_generation
  -> writer_only: end
  -> 其他模式: content_evaluation

content_evaluation
  -> refine: refinement -> content_generation
  -> cover: cover_generation -> end
  -> end: end
```

### 6.7 为什么说它更像“工作流状态机”，不是“串几个 agent”

因为主链推进真正依赖的是两样东西：

- 节点对 `state` 的读写
- 条件函数根据 `state` 做分流

而不是：

- Agent 之间互相发自然语言消息
- 某个中央对话线程把所有状态都记在长上下文里

所以更准确的理解是：

**Trend / Director / Writer / Critic 是业务角色；LangGraph 这张图本身，是把这些角色放进一个显式状态机里编排。**

---

## 7. 第一个关键节点：`route_start`

`route_start` 容易被看轻，但它其实是这条图里第一个真正的分叉点。

### 7.1 先分清：这里其实有“节点”和“路由函数”两层

这里要区分两个名字很像、但职责不同的东西：

- `_route_start_node`
  - 真正注册进图里的节点函数
- `_route_start`
  - 节点执行完后，用来决定下一条边往哪走的条件函数

其中：

- `_route_start_node(...)`
  - 当前基本只是 `return state`
  - 更像一个占位节点
- `_route_start(...)`
  - 才是真正根据 `mode` 做分流的地方

所以如果你问“`route_start` 真正在干嘛”，答案更准确应该是：

**节点本身几乎不改状态，真正的业务意义在于后面的条件分流。**

### 7.2 它读 state 里的什么

它最核心读取的是：

- `state["runtime_config"]`
  - 里面的 `agent.mode`

也就是常说的三种模式：

- `full_pipeline`
- `writer_critic`
- `writer_only`

### 7.3 `full_pipeline`

这是最完整的路径。

它会先进入：

`route_start -> trend_analysis`

后面再继续：

`trend_analysis -> director_sample -> content_generation`

这条路径的特点是：

- 先补上下文
- 再做策略采样
- 再生成内容

所以它最接近“ACO 设计的完整业务闭环”。

### 7.4 `writer_critic`

这条路径会跳过显式的：

- `trend_analysis`
- `director_sample`

直接进入：

`route_start -> content_generation -> content_evaluation`

这不意味着系统完全没有上下文或策略，只是没有独立节点先做那两步。

也就是说，这一模式的真实含义更像：

- 主链图上不显式跑 Trend / Director
- 但后面 Writer 节点内部可能自己做局部兜底

### 7.5 `writer_only`

这是最短路径：

`route_start -> content_generation -> end`

它的含义是：

- 只生成
- 不进入 Critic 正式评估闭环
- 主链在生成后就可以结束

所以它更适合：

- 快速出稿
- 只看生成，不看闭环优化

### 7.6 这三种模式真正差的不是“多几个节点”这么简单

更准确地说，它们差的是三件事：

1. 是否先补领域上下文
2. 是否先显式决定策略
3. 是否进入正式评估与 refinement 回环

所以：

- `full_pipeline`
  - 三件都做
- `writer_critic`
  - 不显式做前两件，但做评估
- `writer_only`
  - 只做生成

### 7.7 为什么简化模式下，Writer 还要自己做兜底

因为如果：

- `trend_analysis` 没跑
- `director_sample` 没跑

那进入 `content_generation` 时，state 里就可能缺：

- `references` 可能为空或较少
- `trend_analysis` 可能是空对象
- `geo_keywords` 很可能只能退化到 `[topic]`

这也是为什么后面 `content_generation` 节点还会自己做一些兜底，例如：

- 没有 `selected_action` 时，节点内再调一次 `_select_action()`
- 没有足够 `references` 时，Writer 内部再补 dynamic RAG
- `geo_keywords` 取不到时，退化成 `[topic]`

所以更准确的理解是：

**简化模式不是完全没有上下文和策略，而是把这些动作从显式前置节点，折叠到了后面的生成节点内部。**

### 7.8 所以 `route_start` 本身到底改没改 state

当前实现里，几乎没有。

它真正做的是：

- 看 `mode`
- 选入口边

它不像 Trend / Writer / Critic 那样，会稳定往 state 里写一大批业务结果。

所以这一节点更适合被理解成：

**主图入口路由器**

而不是：

- 真正产出业务状态的节点

### 7.9 用一句话收住这一节

`route_start` 的业务价值，不在于它自己生产了什么，而在于它决定这次 run 从完整闭环入口开始，还是从简化入口开始。

## 8. `trend_analysis` 节点：把 topic 变成参考上下文

这个节点负责把：

- `topic`
- `platform`
- 可选 audience/style

转成更适合后面生成的业务上下文。

### 8.1 它真正想产出什么

这一步理想上会给后面提供三类东西：

- `trend_analysis`
  - 趋势摘要与关键词摘要
- `references`
  - 可直接给 Writer / Critic 消费的参考材料
- `geo_keywords`
  - 给 Writer 做关键词覆盖和 `geo_coverage` 计算的目标词组

### 8.2 这三个东西最容易混

可以强行并排记：

| 名称 | 它是什么 | 谁直接消费 |
| --- | --- | --- |
| `trend_analysis` | Trend 节点的摘要容器 | 主要被 `_extract_keywords()` 间接使用 |
| `references` | 结构化参考材料列表 | Writer、Critic 直接消费 |
| `geo_keywords` | Writer 的关键词覆盖目标 | Writer 直接消费并参与 `geo_coverage` |

### 8.3 正常情况下怎么流转

理想链路是：

`TrendAgent 提取关键词 -> 写入 trend_analysis -> content_generation 里 _extract_keywords() 读取 -> 变成 input_data["geo_keywords"] -> Writer 使用`

#### 8.3.1 Workflow state 层：节点真正写回了哪些字

如果只站在 workflow state 这一层看，Trend 节点理想上最应该稳定写回的是：

- `state["trend_analysis"]`
- `state["references"]`

其中：

- `trend_analysis`
  - 更像摘要容器
- `references`
  - 更像后面真正会被 Writer / Critic 直接消费的材料列表

#### 8.3.2 Message 快照层：为什么 `messages` 里还会出现别的 key

Trend 节点往 `state["messages"]` 里追加的是一条运行轨迹快照。

所以 `messages[-1]["data"]` 里出现的字段，并不一定和：

- `state["trend_analysis"]`

逐字一一对应。

例如当前实现里，TrendAgent 原始返回里更稳定的是：

- `geo_constraints`
- `references`
- `total_found`

而 `messages[-1]["data"]` 很可能保留的是这份原始返回。

#### 8.3.3 展示层：为什么 websocket / 监控推送里又像是另一套名字

展示层通常还会再做一次“面向前端展示”的包装，例如：

- `reference_count`
- `trend_analysis`

所以你会看到三层名字像在打架：

- Agent 原始返回字段
- workflow state 正式字段
- websocket / 监控展示字段

其实它们不在同一语义层。

#### 8.3.4 这几层到底怎么对应，最清楚的一张表

| 层级 | 最常见字段 | 这层回答什么 |
| --- | --- | --- |
| TrendAgent 原始返回 | `geo_constraints`、`references`、`total_found` | TrendAgent 自己拿到了什么 |
| workflow state | `trend_analysis`、`references` | 后续节点正式消费什么 |
| `messages[].data` | 原始返回快照 | 当时节点执行出了什么 |
| 展示 / 推送层 | `reference_count`、`trend_analysis` | 前端 / 监控想看什么 |

#### 8.3.5 语义上最合理的映射，本来应该是什么

如果只按语义来讲，最理想的映射其实是：

- `geo_constraints`
  - 更像 `trend_analysis.keywords`
- `references`
  - 继续保持 `references`

也就是说，TrendAgent 的关键词结果本来就很像 workflow 想要的：

- `trend_analysis["keywords"]`

只是当前实现里，这条映射没有完全收口。

#### 8.3.6 `geo_keywords`、`references`、`trend_analysis` 这三个最容易混的 Trend 产物，怎么并排区分

##### 先看最短对照表

| 名称 | 它是什么 | 处在哪一层 | 谁真正用它 |
| --- | --- | --- | --- |
| `trend_analysis` | Trend 的摘要容器 | workflow state 层 | `_extract_keywords()` 间接读 |
| `references` | 结构化参考材料列表 | workflow state 层 | Writer、Critic 直接用 |
| `geo_keywords` | 给 Writer 的关键词目标 | Writer 输入层 | Writer 直接用并参与 `geo_coverage` |

##### `trend_analysis` 到底是什么

它不是“所有 Trend 产物的总称”，而更像：

- workflow state 里预留给 Trend 摘要的一个字段

理想上它应该承载：

- 关键词摘要
- 趋势摘要
- 后续给 Writer 取词用的那部分信息

##### `references` 到底是什么

这是 Trend 节点最稳定的一部分。

它更像：

- 已经整理好的、可直接给 Writer / Critic 消费的参考材料

所以如果只抓一个最稳的 Trend 输出，那就是：

- `references`

##### `geo_keywords` 到底是什么

它不是 Trend 节点原始直接写回 state 的主字段，而更像：

- `content_generation` 在组装 `input_data` 时，
- 从 `trend_analysis` 再提炼出来给 Writer 的关键词覆盖目标

##### `geo_keywords` 是从哪来

正常理想链路是：

- TrendAgent 提取关键词
- workflow 把它们放进 `state["trend_analysis"]["keywords"]`
- `_extract_keywords(state)` 再把它们取出来
- 最终变成：
  - `input_data["geo_keywords"]`

##### 为什么当前 `geo_keywords` 会退化

因为当前源码里有个契约错位：

- TrendAgent 更稳定地返回的是 `geo_constraints["keywords"]`
- 但 workflow 想从 `trend_analysis["keywords"]` 里读

如果这条映射没补齐，就会导致：

- `state["trend_analysis"]` 经常是空
- `_extract_keywords()` 读不到真正关键词
- `geo_keywords` 最后退化成：
  - `[topic]`

##### 三者在 Writer 里分别起什么作用

- `trend_analysis`
  - 给 `_extract_keywords()` 提供上游摘要来源
- `references`
  - 给 Writer 真正提供素材和参考结构
- `geo_keywords`
  - 给 Writer 提供覆盖目标，并参与后面 `geo_coverage` 计算

##### 如果用一句话强行区分

**`trend_analysis` 是“摘要容器”，`references` 是“参考材料”，`geo_keywords` 是“喂给 Writer 的关键词目标”。**

### 8.4 当前真实问题

这里有一个真实契约错位：

- Trend 侧输出位置和 workflow 读取位置并不完全对齐
- 结果是 `state["trend_analysis"]` 有时拿不到完整关键词
- Writer 最终只能退化成：
  - `geo_keywords = [topic]`

更具体地说，就是：

- TrendAgent 更稳定地返回：
  - `geo_constraints["keywords"]`
- workflow 却更倾向于从：
  - `trend_analysis["keywords"]`
   里接

所以这块最值得带着批判性去看：

**方向是对的，但当前契约还没完全闭合。**

### 8.5 简化模式下有没有完整 Trend 兜底

没有。

也就是说：

- `writer_critic`
- `writer_only`

都不会“自动补跑一遍完整 `trend_analysis` 节点”。

### 8.6 Writer 侧的局部兜底

尽管没有完整 Trend 兜底，Writer 还是有两层局部补救：

- `_extract_keywords()`
  - 如果没有关键词，就退化成 `[topic]`
- `_prepare_references()`
  - 如果 references 太少，就尝试 dynamic RAG 补材料

这里要注意，这两层兜底不是同一回事：

- `_extract_keywords()`
  - 解决的是关键词缺失问题
- `_prepare_references()`
  - 解决的是参考材料数量 / 质量不足问题

所以 Writer 的局部补救，更准确地说是在兜：

- 关键词链路断了怎么办
- 参考材料不够怎么办

### 8.7 `geo_keywords` 到底是什么

在这个项目里，`geo_keywords` 不是地理坐标那种 `geo`，更接近：

**围绕当前 topic 提取出来的一组适合搜索、索引、覆盖的主题关键词。**

它主要有两个用途：

- 给 Writer 提供覆盖目标
- 参与后面的 `geo_coverage` 计算

---

## 9. `director_sample` 节点：在生成前先决定策略

这个节点负责：

**在生成内容前，先决定这次采用哪组 Hook / Body / CTA 策略。**

### 9.1 策略空间是什么

它背后用的是 RL action space：

- Hook
- Body
- CTA

三者组合成一个动作，例如：

`H02-B07-C01`

### 9.2 上下文从哪里来

Director / bandit 不直接吃 `trend_analysis` 整包，而是先构造：

- `ContextFeatures`

它包含：

- `topic`
- `platform`
- `target_audience`
- `content_style`
- 当前时间等

再通过 `to_vector()` 变成向量 `x`。

### 9.3 这里的向量不是 RAG embedding

这点很重要：

**`ContextFeatures -> to_vector()` 这里做的是 bandit 特征编码，不是语义检索 embedding。**

它的用途是：

- 让同一个 context 去评估多个 action
- 计算 predicted reward / uncertainty / score

#### `_select_action()` 的真实顺序

如果把这个节点内部真正做的事按顺序压开，大致是：

##### 第一步：先读这次运行允不允许学习式选择

它会先看：

- `runtime_config.rl`
- `runtime_config.generation`

也就是：

- Thompson Sampling 开没开
- exploration_rate 多少
- Hook / CTA 等策略约束开没开

##### 第二步：决定用“学习式选择”还是随机选择

如果相关 RL / bandit 开关没开，或者当前条件不满足，就会退到：

- 随机选一个 Hook / Body / CTA 组合

如果开了，就优先走：

- Thompson Sampling
- contextual bandit

##### 第三步：在“利用历史经验”和“试试新策略”之间折中

这一步最核心的不是单纯“选历史最高分”，而是：

- 历史表现好的动作
  - 更容易被选中
- 没试够的新动作
  - 也保留一部分探索机会

所以这层不是死用老策略，而是：

**利用 + 探索的平衡。**

##### 第四步：再应用最终开关约束

最后还会结合：

- 是否启用 hook 策略
- 是否启用 cta 策略

把某些不该用的部分关掉或回退，确保最终写回 state 的动作是可用的。

### 9.4 选完动作后写回什么

`director_sample` 会往 state 里写：

- `selected_action`
- `policy_id`

后面 `content_generation` 会把它们塞进 Writer 输入。

#### `_apply_selected_action()` 实际上做了两件事

##### 第一件事：生成 `policy_id`

它会把：

- `hook`
- `body`
- `cta`

拼成一个稳定字符串，例如：

- `H01-B03-C02`

所以：

- `policy_id`
  - 不是请求 ID
  - 也不是内容 ID
  - 它更像“这次生成策略的指纹”

##### 第二件事：把结构化动作写进 `selected_action`

`selected_action` 不只是三个短码，通常还会带：

- `hook / body / cta`
- 对应名字
- 索引信息 `idx`

所以：

- `selected_action`
  - 是结构化策略对象
- `policy_id`
  - 是这套策略的压缩 ID

#### 这里有个很容易漏掉的点

这个节点当前主要是改：

- `selected_action`
- `policy_id`

它不像 Trend / Writer / Critic 那样稳定往 `messages` 里追加业务结果快照。

### 9.5 即时 RL 更新是什么时候做的

不是在这里做的。

动作在这里选，但即时 reward 通常是在 `content_evaluation` 后，拿到 Critic 分数后才回灌一次。

### 9.6 这个节点和 Writer 的关系到底是什么

可以直接把它理解成：

**Writer 负责“怎么写出来”，Director 负责“这次按哪种打法写”。**

也就是说：

- `director_sample`
  - 决定策略
- `content_generation`
  - 再把这个策略变成内容

所以从这里开始，这次生成不再只是：

- 围绕 `topic` 写内容

而是：

- 围绕某个明确的 Hook / Body / CTA 策略去生成内容

### 9.7 用一个具体例子把这一节记住

假设当前上下文是：

- `topic = AI 提效工具`
- `platform = xiaohongshu`
- `target_audience = 25-35岁职场人`
- `content_style = 专业、轻松`

系统最终选到的动作是：

```json
{
  "hook": "H01",
  "body": "B03",
  "cta": "C02"
}
```

那这一步之后，state 里最关键的增量就是：

```json
{
  "policy_id": "H01-B03-C02",
  "selected_action": {
    "hook": "H01",
    "body": "B03",
    "cta": "C02",
    "idx": [0, 2, 1]
  }
}
```

接下来 `content_generation` 就会围绕这组策略来写文案和蓝图。

### 9.8 “系统会根据历史表现，逐渐学会哪种策略更值得多用”到底是什么意思

这句话更准确地翻成人话是：

- 历史上表现更好的策略
  - 被选中的概率会逐渐更高
- 但不会永远只用老策略
  - 系统仍然保留探索新策略的机会

所以“学会多用某些策略”，不是绝对规则，而是：

**这些策略在未来被选中的概率越来越高。**

### 9.9 即时 reward 和延迟 reward 是怎么分别影响这层的

#### 9.9.1 即时 reward：主链内的快速更新

主链里先拿：

- Critic 的 `overall_score`

给 bandit 一个在线快速反馈。

这层优点是：

- 快
- 当次请求内就能回灌

但它的缺点也很明显：

- 还不是真实世界表现

#### 9.9.2 延迟 reward：真实 outcome 回灌

内容发出去之后，系统还会通过：

- `Trace -> Outcome -> delayed reward`

把真实互动表现回灌回来。

这层更接近：

- 内容真的发出去后的真实效果

#### 9.9.3 两者是什么关系

可以直接记成：

- 即时 reward
  - 告诉系统“看起来怎样”
- 延迟 reward
  - 告诉系统“现实里到底怎样”

所以这条策略层不是只靠一次 LLM 打分在学，而是：

**先吃即时反馈，再吃真实业务回灌。**

### 9.10 contextual bandit 的内部结构到底是什么

这一层最容易把人绕晕，但其实不用先啃公式，先抓住 4 个核心概念就够了：

- `context`
- `action`
- `arm`
- `reward`

#### 9.10.1 为什么是很多动作，不是一个动作

因为动作空间不是一个动作，而是：

- Hook × Body × CTA

所以系统面对的其实是一堆候选动作，而不是单一策略。

#### 9.10.2 `action` 和 `arm` 是什么关系

在当前实现里，基本可以理解成：

**一个动作对应一个 arm。**

也就是：

- 一个 H-B-C 组合
  - 对应 bandit 里一份独立学习参数

所以：

- `action`
  - 是业务上的策略动作
- `arm`
  - 是这个动作在 bandit 里的学习槽位

#### 9.10.3 `context` 和 `action` 是什么关系

这个要分两个阶段看。

##### 选择阶段

是：

**一个 context -> 对多个 action 分别打分**

也就是说，同一个上下文会去评估很多动作。

##### 更新阶段

是：

**一个 context + 一个最终被执行的 action + 一个 reward**

因为这次请求最终只真的执行了一个动作，所以更新时只更新：

- 被选中的那个 arm

#### 9.10.4 `A`、`b`、`predicted reward`、`uncertainty` 到底是什么

工程上最实用的记法是：

- `A`
  - 这个动作历史上见过哪些 context
- `b`
  - 这些 context 下拿到过多少 reward
- `predicted reward`
  - 当前 context 下，这个动作看起来大概能得多少分
- `uncertainty`
  - 当前这个估计还有多没把握

最后系统不会只看预测值，还会看：

- `ucb_score = predicted reward + uncertainty`

所以它选的是：

**当前看起来不错，而且还值得探索的那个动作。**

#### 9.10.5 为什么这不是语义检索

因为这里没有在做：

- query embedding
- 相似样本 top-k
- 最近邻检索

它不是在问：

- “和历史上哪篇最像”

而是在问：

- “在当前 context 下，哪个动作更可能带来高 reward”

所以这层更像：

- 上下文条件决策
- 线性预测 + 探索项

不是：

- 语义检索

### 9.11 用一句话收住这一整节

**`director_sample` 这一节做的不是“写内容”，而是把当前 topic/platform/audience/style 这些上下文先编码成 bandit 可消费的 context，再从 Hook / Body / CTA 动作空间里挑出这次最值得尝试的策略，并写成 `selected_action + policy_id` 交给后面的 Writer。**

---

## 10. `content_generation` 节点：真正把策略和上下文变成内容

这个节点是主链里真正进入内容生成的地方。

但要注意：

**节点本身主要负责组装输入并调用 Writer；真正多步调用 LLM 的，是 `WriterAgent` 内部流水线。**

#### 进入这一节点前，还有两个容易被忽略的前置判断

第一，workflow 层会先看：

- `state["token_budget_remaining"]`

如果剩余预算已经小于等于 `0`，节点会直接跳过内容生成。这说明主链不是“无限调模型”，而是已经在 workflow 层做了非常轻的预算门控。

第二，简化模式下如果前面没有显式跑 `director_sample`，导致：

- `state["selected_action"]`

还没有值，那么 `content_generation` 会在节点内部再做一次兜底采样，把策略补出来再继续生成。所以要特别记住：

- `writer_critic`
- `writer_only`

虽然没有独立 Director 节点，但并不代表真正进入 Writer 时没有策略。

### 10.1 它给 Writer 组装了什么输入

可以把 `input_data` 理解成：

**Writer 的总原料包。**

一个具体例子可以长这样：

```json
{
  "topic": "AI 提效工具",
  "platform": "xiaohongshu",
  "references": [],
  "action": {
    "hook": "H02",
    "body": "B07",
    "cta": "C01"
  },
  "geo_keywords": ["AI工具", "效率提升", "办公自动化"],
  "target_audience": "25-35岁职场人",
  "content_style": "专业、轻松",
  "goal_metric": "engagement",
  "policy_id": "H02-B07-C01",
  "feedback": []
}
```

这里的 `feedback` 并不是每次都有；它更常出现在 workflow 进入下一轮时。

#### `geo_keywords` 是怎么来的

这里会调用：

- `_extract_keywords(state)`

逻辑很简单：

1. 先尝试从 `state["trend_analysis"]["keywords"]` 里取
2. 如果取不到，就退化成 `[topic]`

所以：

- `geo_keywords`
  - 不是 Writer 自己现场瞎猜出来的
- 它理想上应该来自 Trend 侧的关键词抽取结果

这也是前面 `trend_analysis` 契约错位会直接影响 Writer 的原因之一：如果 Trend 没把关键词稳稳写回 state，Writer 侧最后就只能拿到一个退化版关键词列表。

### 10.2 `input_data` 和 `execute()` 的关系

最短理解：

- `input_data`
  - 是 Writer 的总输入包
- `WriterAgent.execute(input_data)`
  - 是 Writer 的总调度入口

`execute()` 会拿着这包原料，跑完一条节点内部的小流水线。

### 10.3 Writer 内部总图

把 Writer 拆清楚，最适合按分层看：

```text
控制层
  execute()
    -> create_plan()

业务执行层
  1. prepare_references()        -> references
  2. generate_text_structure()   -> TextStructure
  3. generate_blueprint() stage1 -> stage1_data
  4. generate_blueprint() stage2 -> stage2_data
  5. calculate_metrics()         -> metrics

评估层
  reflect(step1)
  reflect(step2)
  reflect(step3)
  reflect(step4)

收口层
  integrate_results()            -> GeneratedContent

整轮评估层
  final_reflection()
  -> 不满意：进入下一轮 attempt
  -> 满意：结束 Writer
```

#### 如果按一条连续流水线看，真实顺序是什么

如果不按“控制层 / 业务层 / 评估层”分层，而是直接按 `execute()` 的实际时间顺序展开，Writer 内部更像：

```text
input_data
  -> create_plan()                 # 先决定 Writer 内部这次按什么步骤执行
  -> prepare_references()          # 把参考材料补齐或压缩到可用状态
  -> reflect(step1)                # 检查 references 是否够用
  -> generate_text_structure()     # 先生成文案结构：Hook / Body / CTA / full_text
  -> reflect(step2)                # 检查文案结构够不够好，要不要重试
  -> generate_blueprint() stage1   # 先生成场景、镜头、道具等拍摄骨架
  -> generate_blueprint() stage2   # 再补视觉风格、字幕、节奏等细节
  -> reflect(step3)                # 检查蓝图阶段够不够好，要不要重试
  -> calculate_metrics()           # 用代码计算 geo_coverage 等指标
  -> reflect(step4)                # 检查指标步骤结果是否合理
  -> integrate_results()           # 把前面的中间产物组装成 GeneratedContent
  -> final_reflection()            # 对整轮结果做最终验收
  -> 如需要则进入下一轮 attempt   # 如果 final_reflection 不满意，再来一轮
```

这条顺序图和前面的分层图并不冲突，只是回答的问题不同：

- 分层图
  - 更适合理解哪些是业务节点、哪些是评估节点、哪些是收口节点
- 顺序图
  - 更适合理解 `execute()` 里“先做什么、再做什么、哪里可能 retry”

#### 如果只数“真正干活产生产物”的业务节点，有几个

如果先把 `create_plan()`、`reflect(...)`、`integrate_results()` 这些控制/评估/收口步骤拿掉，Writer 最核心的业务执行节点其实是：

1. `prepare_references()`
2. `generate_text_structure()`
3. `generate_blueprint() stage1`
4. `generate_blueprint() stage2`
5. `calculate_metrics()`

对应的业务产物分别是：

- 准备好的 `references`
- `TextStructure`
- `stage1_data`
- `stage2_data`
- `metrics`

其中：

- `generate_blueprint() stage1 + stage2`
  - 业务上可以看成一个“蓝图生成”大步骤
  - 只是实现上被拆成了两段

所以从“业务理解”角度，Writer 更像：

- 参考准备
- 文案结构生成
- 蓝图生成
- 指标计算

再加上：

- 步骤级评估
- 整轮评估
- 最终收口

这也是为什么把所有环节平铺到一条线上时，总图很容易显得乱。

### 10.4 `create_plan()`：Writer 的 planning 在做什么

Writer 会先生成一个结构化 `Plan`。

这个 Plan 的作用不是写内容，而是：

- 定义内部步骤
- 给每个步骤配 `goal`
- 给每个步骤配 `success_criteria`

这份计划可以由 LLM 生成，也可以走默认固定计划。

但当前执行器自由度有限，真实上更像：

**对一条相对固定的 Writer 流水线做轻量拆解。**

#### 它到底是怎么生成的

当前 `Plan` 有两种来源：

1. 开启 planning
   - 走 `_create_execution_plan(input_data)`
   - 再由 `Planner.create_plan(...)` 调 LLM 生成
2. 关闭 planning
   - 走 `_create_default_plan(input_data)`
   - 直接使用代码里的默认固定计划

所以：

- `Plan`
  - 可以是 LLM 产物
- 但不是“没有 LLM 就完全不能工作”的硬依赖

#### 它大致长什么样

一个典型 `Plan` 可以理解成：

```json
{
  "complexity": "medium",
  "steps": [
    {
      "step_id": 1,
      "goal": "准备参考内容",
      "action": "检索和压缩参考内容",
      "required_info": ["topic", "platform"],
      "success_criteria": "获得至少 3 个高质量参考",
      "estimated_tokens": 200,
      "dependencies": []
    },
    {
      "step_id": 2,
      "goal": "生成文案结构",
      "action": "根据策略生成 Hook + Body + CTA",
      "required_info": ["action", "references", "geo_keywords"],
      "success_criteria": "文案长度 800-1200 字，覆盖主要 GEO 关键词",
      "estimated_tokens": 1000,
      "dependencies": [1]
    },
    {
      "step_id": 3,
      "goal": "生成拍摄蓝图",
      "action": "根据文案结构生成场景、镜头和视觉方案",
      "required_info": ["text_structure", "references"],
      "success_criteria": "至少包含 3 个镜头，并给出清晰可执行的视觉方案",
      "estimated_tokens": 1200,
      "dependencies": [2]
    },
    {
      "step_id": 4,
      "goal": "计算质量指标",
      "action": "计算 GEO 覆盖率与长度等指标",
      "required_info": ["text_structure", "geo_keywords"],
      "success_criteria": "geo_coverage >= 0.8",
      "estimated_tokens": 100,
      "dependencies": [2]
    }
  ]
}
```

这里最重要的不是字面值，而是看清 `PlanStep` 真正提供了什么：

- `goal`
  - 这一步想完成什么
- `action`
  - 这一步大致怎么做
- `success_criteria`
  - 这一步做到什么算合格

#### 这份 Plan 后面到底会被谁消费

当前 `Plan` 不是生成出来就摆着好看，它后面至少会影响三件事：

1. `for step in plan.steps`
   - 决定 Writer 内部按什么顺序往下跑
2. `step.goal`
   - 会被步骤级 `Reflector` 当成“这一步到底想完成什么”
3. `step.success_criteria`
   - 会被步骤级 `Reflector` 当成“做到什么算合格”

所以 `Plan` 的真实作用，不只是“列步骤”，而是：

- 给执行器提供顺序和步骤语义
- 给 Reflector 提供步骤级验收标准

也正因为如此，它虽然不是 todo-list 式执行状态板，但已经不只是一个“纯说明书”。

#### 更准确地定位它：像“步骤合同”，但还不是“执行状态系统”

如果只用一句话定位现在这版 `Plan`，最贴切的是：

**它更像 Writer 节点内部的一份“步骤合同”，而不是完整的执行状态系统。**

原因在于：

- 它已经有：
  - `goal`
  - `action`
  - `success_criteria`
- 但它还没有：
  - `status`
  - `started_at`
  - `finished_at`
  - `retry_count`
  - `error`

所以它能很好地回答：

- 这轮大概要按什么步骤做
- 每一步做到什么算合格

但还不能直接回答：

- 现在已经做到哪一步了
- 哪一步失败过几次
- 能不能从中间恢复继续跑

#### 无论写什么内容，Plan 的步骤都一样吗

不完全一样，但也不会差太远。

理论上：

- 不同 `topic`
- 不同 `platform`
- 不同 `goal_metric`

可以让 LLM 产出不同的 `complexity / steps / success_criteria`。

但现实上，当前执行器 `_execute_step()` 仍然会把它收敛回几个固定业务步骤：

- 参考准备
- 文案结构生成
- 蓝图生成
- 指标计算

所以更准确地说：

**当前 `Plan` 在描述层是可变的，在执行层仍然被收敛为一条相对固定的 Writer 流水线。**

#### 那它的真实价值是什么

当前这份 `Plan` 最有价值的，不是“完全自由地决定 Writer 做什么”，而是：

- 给 Writer 内部步骤显式命名
- 给每一步补 `goal / success_criteria`
- 让后面的 `Reflector` 有明确的局部验收标准
- 给未来更强的执行器预留接口

所以它更像：

**一张带结构字段的内部施工单。**

而不是：

**一个已经成熟到可以独立驱动任意执行图的执行状态机。**

### 10.5 它和 todo-list / 显式状态流转有什么区别

当前 Writer 更像：

`Plan -> for step in plan.steps`

也就是一次性顺序脚本。

而 todo-list / 显式状态流转更像：

- 任务项
- 显式 `pending / running / completed / failed`
- execution log
- 状态驱动执行

所以：

- 当前 Writer Plan
  - 更像内存中的步骤说明书
- todo-list
  - 更像带状态的任务板

如果压成一张最短对照图，就是：

```text
当前 Writer: Plan -> for step in plan.steps
  更像顺序脚本
  “做到哪了”主要靠循环位置和 step_results

todo-list / 显式状态流转:
  task board + pending/running/completed/failed + execution log
  更像状态驱动执行系统
```

也就是说：

- 当前 Writer
  - 更轻
  - 更适合节点内一次性短流程
- todo-list
  - 更适合中断恢复、跳过、并行、审计

#### 为什么看起来“都在循环”，但其实不是同一种循环

这里最容易误解的一点是：

- 当前 Writer
  - 也在循环
- todo-list / execution-state
  - 也在循环

所以表面上看，好像只是：

- 一个 `for step in plan.steps`
- 一个 `while 还有未完成任务`

但真正差别不在“有没有循环”，而在：

- 循环每次是按什么依据推进
- 循环到底在驱动什么变化

当前 Writer 的 `for step in plan.steps` 更像：

- 先拿到一张固定步骤清单
- 然后从上到下顺序执行
- 当前做到哪，主要靠：
  - 当前循环位置
  - `step_results`
  - 当前 `attempt`

它本质上是：

**计划驱动的顺序遍历。**

todo-list / execution-state 更像：

- 每个 task 都有显式 `status`
- 每轮先扫描当前状态
- 再找出“现在可执行”的任务
- 执行后更新状态
- 下一轮继续根据最新状态决定谁能跑

它本质上是：

**状态驱动的执行循环。**

所以最准确的说法不是：

- 一个有循环，一个没循环

而是：

- **两边都在循环，但 Writer 是遍历既定步骤，todo-list 是持续扫描任务状态并驱动状态变化。**

#### 为什么当前实现还不像真正的 todo-list

因为它现在没有把“步骤状态”建模成一等公民。

当前实际更像：

- `plan.steps`
  - 只描述步骤
- `for step in plan.steps`
  - 顺序执行
- `step_results[step_id] = result`
  - 暂存结果
- `reflection`
  - 决定是否局部重试

所以“做到哪了”主要隐含在：

- 当前循环走到哪
- `step_results` 里有没有对应产物
- 当前 `attempt` 是第几轮

而不是显式写在某个：

- `status = pending / running / completed / failed`

这样的任务状态字段上。

#### 放在一起看，差别到底是什么

如果把它们压成一张并排对照图：

```text
当前 Writer
  Plan -> for step in plan.steps
  更像顺序脚本
  “做到哪了”主要靠循环位置和 step_results

todo-list / 显式状态流转
  task board + pending/running/completed/failed + execution log
  更像状态驱动执行系统
```

可以直接把差别记成一句话：

- 当前 Writer Plan
  - `planning artifact`
- todo-list
  - `execution state artifact`

#### 如果用同一个问题，把两边并排看

假设现在都要完成：

1. 准备参考资料
2. 生成文案
3. 生成蓝图
4. 计算指标

当前 Writer 更像：

```text
plan = [准备参考, 生成文案, 生成蓝图, 计算指标]

for step in plan:
  执行 step
  reflect(step)
```

它回答的是：

- 这次应该按什么顺序做

todo-list / execution-state 更像：

```text
tasks = [
  {id: 1, title: 准备参考, status: pending},
  {id: 2, title: 生成文案, status: pending, deps: [1]},
  {id: 3, title: 生成蓝图, status: pending, deps: [2]},
  {id: 4, title: 计算指标, status: pending, deps: [2]}
]

while 还有未完成任务:
  找到 deps 满足且 pending 的任务
  标记 running
  执行
  成功 -> completed
  失败 -> failed / pending
  写 execution log
```

它回答的是：

- 现在做到哪了
- 哪一步失败了
- 哪些任务可并行
- 能不能从中间恢复

所以当前 Writer 的 `for step in plan.steps` 并不是“不成熟”，而是：

- **它本来就是为节点内短流程设计的轻量执行方式**

只是它还不像真正 harness 那样，把：

- `pending / running / completed / failed`
- artifact refs
- retry history

都建模成显式状态。

#### 当前这版 Plan 值不值得学

值得学，但更适合学它的方向，而不是原样照抄。

它值得学的点是：

- 先把内部流水线显式拆步
- 给每步配 `goal / success_criteria`
- 把步骤计划和步骤执行稍微分开

它还不够成熟的点是：

- 不可恢复
- 不可审计
- 不方便并行
- 很难做长期失败统计
- 还没有真正把执行状态 formalize 下来

所以更准确的判断是：

**当前 ACO 的 Writer planning 是“半结构化 planning 层”，还不是成熟的 execution state system。**

### 10.5.1 为什么上一步的产物不一定就是下一步的上下文核心

这里最容易混淆的点是：

**Writer 不是“上一步产物机械传给下一步”的纯流水线，而是“全局任务约束 + 必要中间产物 + 控制信号”混合驱动。**

可以先把 Writer 里的中间产物分成三类：

- 控制产物
  - `Plan`
  - `Reflection`
- 内容产物
  - `TextStructure`
  - `Blueprint`
- 全局任务约束
  - `topic`
  - `platform`
  - `references`
  - `geo_keywords`
  - `audience/style`

#### 为什么 `Plan` 不直接变成下一步的核心生成上下文

因为 `Plan` 主要回答的是：

- 这次内部应该按哪些步骤做
- 每一步的目标是什么
- 做到什么算合格

它更偏：

**控制流信息**

而不是：

**创作语义材料**

所以到了 `generate_text_structure()`，真正决定文案怎么写的，仍然是：

- `topic`
- `platform`
- `action`
- `references`
- `geo_keywords`
- `audience/style`

不是 `Plan` 里的那几句步骤描述。

#### 为什么 `TextStructure` 会成为 Blueprint 的核心输入

因为 Blueprint 阶段要解决的问题是：

- 这段文案怎么拍
- 要什么场景、镜头、道具

所以：

- `TextStructure.full_text`
  - 是后一步最关键的内容上下文

这里就是典型的：

**上一步产物直接成为下一步核心输入。**

#### 为什么 `Reflection` 不一定成为下一步的核心输入

`Reflection` 更像：

- 门控信号
- 质检信号
- 重试建议

如果当前步骤已经够好，它只是：

- 放行

只有在 `needs_retry = true` 时，它才会通过：

- `improvement_suggestions -> feedback`

影响下一次重跑。

所以它不天然是“下一步核心内容上下文”，而更像：

**控制信号 / 修正信号。**

#### 为什么很多步骤还会反复带着 `topic / platform / references`

因为很多中间产物会压缩掉一部分原始任务语义。

例如：

- `TextStructure`
  - 告诉你文案长什么样
  - 但不会完整保留平台语境、参考材料来源、受众风格限制

所以后面的步骤仍然需要反复带着：

- `topic`
- `platform`
- `references`

这些全局不变量，以避免语义漂移。

如果用一句话概括 Writer 的上下文构建原则，就是：

**下一步真正需要什么上下文，不由“谁刚刚产出了东西”来决定，而由“这一步到底要解决什么问题”来决定。**

### 10.6 Writer 内部的 reflection 怎么工作

Writer 有两层 reflect：

- 步骤级 reflect
  - 对 step1~step4 做局部质检
- `final_reflection()`
  - 对最终 `GeneratedContent` 做整轮自检

它们都调用同一个 `Reflector.reflect(...)`，都是 LLM 评估，并输出结构化字段：

- `score`
- `needs_retry`
- `strengths`
- `weaknesses`
- `improvement_suggestions`

步骤级 reflect 用的是：

- `step.goal`
- `step.success_criteria`

整轮 `final_reflection()` 用的是：

- `内容质量评分 >= 8.0`
- `GEO 覆盖率 >= 0.8`

其中：

- `geo_coverage`
  - 是代码算的
- `score`
  - 是 LLM 打的

而代码真正直接消费的，主要是：

- `needs_retry`

#### 每个步骤都会 reflect 吗

原则上会，但前提是：

- `enable_reflection = True`

这个开关不是 step 自己的字段，而是：

- `WriterAgent` 构造时的 agent 级开关

所以：

- `prepare_references()` 后可以 reflect
- `generate_text_structure()` 后可以 reflect
- `generate_blueprint()` 后可以 reflect
- `calculate_metrics()` 后也可以 reflect

整轮结束后再做一次：

- `final_reflection()`

#### 步骤级 reflect 的输入到底是什么

步骤级 reflect 吃的是：

- `goal`
- `result`
- `success_criteria`
- 少量上下文
  - `attempt`
  - `step_id`

也就是说，它看到的是：

**当前步骤想干什么 + 当前步骤实际产出了什么 + 当前步骤做到什么算合格。**

#### 步骤级 reflect 的输出是什么

它输出的是结构化 `Reflection`，典型字段包括：

- `success`
- `score`
- `needs_retry`
- `strengths`
- `weaknesses`
- `improvement_suggestions`
- `confidence`

所以它不是一段自由文本，而是：

**可直接被流程消费的结构化评估对象。**

#### 步骤级 reflect 怎么影响后续流程

如果：

- `needs_retry = true`

Writer 会把：

- `improvement_suggestions`
- `previous_result`

塞回增强输入里，然后重跑当前 step。

所以步骤级 reflect 的作用是：

**局部质检 + 局部重跑。**

#### `final_reflection()` 到底在评什么

它不是再评某一个 step，而是评：

- 已经由 `integrate_results()` 组装好的 `GeneratedContent`

它会检查：

- 整体质量分
- GEO 覆盖率
- 是否值得进入下一轮 Writer 内部 attempt

这里最容易混淆的一点是：

- `integrate_results()`
  - 只负责先把最终成品拼出来
- `final_reflection()`
  - 才负责对“这份最终成品”做整轮验收

也就是说，Writer 里不是“组装完天然就带着质量分”，而是：

1. 先由代码把：
   - `TextStructure`
   - `Blueprint`
   - `metrics`
   - 元数据
   收口成 `GeneratedContent`
2. 再由 `Reflector` 对这份 `GeneratedContent` 做最终判断

所以：

- `质量评分`
  - 来自 `final_reflection().score`
- `geo_coverage`
  - 来自前面的代码计算
- 最终流程是否继续
  - 主要看 `final_reflection().needs_retry`

#### 这些标准是“硬校验”还是“LLM 提示”

大多数是：

- 提示给 Reflector 的验收标准

不是：

- 全都被代码逐条硬校验

当前代码层更硬的一条兜底是：

- 如果 `score < 7.0`
- 且模型没主动要求重试

那系统会强制把：

- `needs_retry = true`

所以：

- `>= 8.0`
  - 更像目标线
- `< 7.0`
  - 更像代码硬底线

#### 一句话收住 Writer 内部 reflect

**Writer 的 reflect 体系，本质上是“LLM 质检 + 少量代码兜底”的节点内重试机制；步骤级 reflect 负责局部修正，`final_reflection()` 负责整轮放行或继续 attempt。**

### 10.7 第一次执行和 retry 的区别

每个 step 的第一次执行和 retry，基本走的是同一段执行逻辑。

区别不在函数，而在输入：

- 第一次执行
  - 用原始输入
- retry
  - 会额外带上：
    - `feedback`
    - `previous_result`

也就是：

**不是换一套执行器，而是给同一个执行器补一层“上次哪里不满意”的上下文。**

#### 这个“增强输入”在 Writer 里是怎么发生的

当前 Writer 的真实路径更接近：

1. 第一次执行：
   - `execute()` -> `_execute_step(step, input_data, step_results)`
2. 如果 `reflect(step)` 觉得要重试：
   - `_retry_step_with_feedback(...)`
3. `_retry_step_with_feedback(...)` 会先组装：
   - `enhanced_input["feedback"] = improvement_suggestions`
   - `enhanced_input["previous_result"] = previous_result`
4. 然后再回到：
   - `_execute_step(step, enhanced_input, {})`

所以第一次执行和 retry 的最大差别不是：

- 跑了不同函数

而是：

- **同一个 step 执行器，吃到了不同版本的输入。**

#### 这意味着什么

这意味着当前 Writer 的 retry 机制，本质上是在做：

- 同一业务步骤
- 同一输出契约
- 同一执行入口
- 但补上一层“上次为什么没过”的反馈上下文

所以更准确的说法是：

- 第一次执行
  - 原始输入 + 原始上下文
- retry
  - 原始输入 + 上次结果 + 改进建议

#### 这里还有一个现实问题

机制上，这条链已经打通了：

- `improvement_suggestions -> feedback -> retry`

但在当前 Writer 里，`feedback` 字段虽然会被塞回输入，主要生成步骤对这份 `feedback` 的 prompt 消费还不算特别强。

也就是说：

- retry 的执行入口和输入增强机制已经有了
- 但“这些增强输入有没有被充分吸收”仍然是当前实现里较弱的一环

所以如果只抓一句最实用的判断：

- **第一次执行和 retry 在 Writer 里本质上是“同一个执行器 + 增强输入”，而不是两套不同逻辑。**

### 10.8 `integrate_results()` 在做什么

这一步本身不评估，只负责收口组装。

它吃的是：

- `TextStructure`
- 已经合并并校验过的 `Blueprint`
- `metrics`
- `action`
- `geo_keywords`

然后组装成：

- `GeneratedContent`

注意不是直接拼 `TextStructure + stage1_data + stage2_data`。

真正链路是：

- stage1 + stage2
  - 先合成 `Blueprint`
- `integrate_results()`
  - 再把 `TextStructure + Blueprint + metrics + 元数据` 收成 `GeneratedContent`

### 10.9 `content_generation` 节点最终写回了什么

核心上，写回主体就是 Writer 内部 `integrate_results()` 产出的 `GeneratedContent`。

但 workflow 节点不会原封不动直接写回，还会再补：

- `action`
- `policy_id`
- `token_usage`

最后才写进：

- `state["generated_content"]`

### 10.10 `success_criteria` 和 Anthropic 式“迭代合同”像在哪里，又差在哪里

当前 ACO 已经有“验收标准化”的味道：

- `PlanStep.goal`
- `PlanStep.success_criteria`
- `Reflector.reflect(goal, result, success_criteria, ...)`

所以评估不是完全拍脑袋。

但它还不是 Anthropic 那种“生成器和评估器在每轮开始前共同确认完成定义”的协商式合同。

当前更像：

**上游单方面给出标准，下游按这个标准检查。**

#### 为什么说它已经有“弱合同”的味道

因为现在这条 Writer 流水线里已经有三件东西：

- `PlanStep.goal`
- `PlanStep.success_criteria`
- `Reflector.reflect(goal, result, success_criteria, ...)`

这意味着评估不是完全凭感觉打分，而是已经被压成：

- 这一步要完成什么
- 做到什么算合格
- Reflector 按这个标准打分

所以 ACO 现在并不是“完全没有验收标准”，而是：

- 已经有验收标准化
- 但还没有协商式合同化

#### 它和 Anthropic 的强合同，差别到底在哪

如果把两边对照着看，最关键的差别是：

- ACO 现在
  - 更像上游单向下发标准
- Anthropic 的 iterative contract
  - 更像生成器和评估器共同确认“本轮做到什么算完成”

所以两者可以压成一句最短对照：

- `success_criteria`
  - 验收标准
- `iterative contract`
  - 双方确认过的本轮完成定义

前者已经有了，后者还没有。

#### 为什么这个差别重要

因为如果只有 `success_criteria`，仍然可能出现两类问题：

1. 标准是谁定的，评估器未必真的认同
2. 标准可能偏描述性，还不够可测试、可执行验收

例如：

- “生成高质量内容”
- “文案长度适中”
- “蓝图清晰”

这些都比没有标准强，但还不一定像强合同那样，已经被拉到：

- 可测试
- 可判定
- 可争议收敛

所以更准确的判断是：

- ACO 当前已经有“弱合同”
- 但还没有“协商式强合同”

### 10.11 当前有必要升级成协商式迭代合同吗

我对这条 Writer 流水线的判断是：

- 有价值
- 但不是第一优先级

当前更值得先做的是：

- 把 `success_criteria` 写得更具体、更可测
- 让 `Reflector` 和代码硬规则更收口
- 把 `Reflector` 和 `Critic` 的边界切清楚

#### 为什么当前不一定要立刻上“协商式强合同”

因为当前 ACO 还有几个很现实的前提：

- Writer 内部流程相对固定
- step 类型相对固定
- 验收目标大体可预期
- 外层还有 `Critic -> refinement` 兜底

这意味着现在最大的痛点通常不是：

- 生成器和评估器完全没对齐

而更像是：

- `success_criteria` 还不够具体
- `Reflector` 的评分和代码硬规则没完全收口
- 内层 `Reflector` 和外层 `Critic` 的标准层级还需要再理顺

在这种前提下，直接上“协商式迭代合同”很可能会带来：

- 编排更复杂
- token 更多
- 延迟更高
- 但收益未必是第一顺位

#### 如果以后真要往那个方向进化，最自然的改法是什么

最自然的做法不是推翻 `Plan`，而是在它和实际执行之间再加一层：

- `IterationContract`

也就是：

- `Plan`
  - 继续负责“这轮做什么”
- `Contract`
  - 负责“做到什么算过”

一个更像 Anthropic 的轻量合同层，可以至少包括：

- `scope`
- `must_have`
- `acceptable_quality_bar`
- `testable_acceptance_checks`
- `review_focus`

也就是说，`PlanStep` 里现在只有：

- `goal`
- `success_criteria`

未来如果要更强，就可以变成：

- `goal`
- `success_criteria`
- `review_focus`
- `must_fix_now`
- `acceptance_checks`

这样就会更接近：

- 这轮先修什么
- 哪些问题必须过
- 哪些问题可以暂缓
- 评估器应该重点盯哪里

#### 对当前 ACO，更划算的升级顺序是什么

如果按性价比排序，我会建议：

1. 先把 `success_criteria` 写具体、写可测
2. 再补一点轻量 `iteration_brief`
   - 本轮重点修什么
   - 哪些问题必须解决
   - 哪些问题这轮先不管
3. 最后再考虑真正的“生成器-评估器协商式迭代合同”

所以一句话结论是：

- **协商式迭代合同有价值，但对当前固定 Writer 流水线不是第一优先级。**

### 10.12 Writer 内部流水线 vs Anthropic 三 Agent Harness

如果只看 Writer 内部，会看到：

- Planner
- 生成步骤
- Reflector

这和 Anthropic 的“三角色分工”有轮廓上的相似。

但它还不是强分离的三 Agent 对抗系统，因为：

- Planner 规划粒度更低
- Reflector 仍然是 Writer 内部自检
- 真正更像 Anthropic 外部评估器的是外层 `Critic`

所以更准确的话是：

- Writer 内部三件套
  - 更像结构上的相似
- `Writer -> Critic -> Refinement -> Writer`
  - 更像 Anthropic 那种“生成器 + 外部评估器 + 反馈迭代”的精神内核

#### 如果只给一句总判断，最准确该怎么说

最贴切的说法其实是：

- 只看 Writer 内部
  - 弱相似
- 把外层 `Writer -> Critic -> Refinement -> Writer` 一起看
  - 明显更像

原因在于：

- Writer 内部确实有 `Planner -> 生成步骤 -> Reflector`
- 但这更像“单个 Agent 内部的自我规划 + 自我反思”
- 还不是 Anthropic 那种强分离的对抗式三 Agent

真正更像 Anthropic 精神内核的，是：

- 生成
- 外部评估
- 再反馈回生成

也就是：

- `Writer -> Critic -> Refinement -> Writer`

#### 如果直接按角色并排，会更清楚

可以直接把它们压成一张对照表：

| Anthropic 角色 | ACO 里最接近的东西 | 像在哪里 | 不像在哪里 |
| --- | --- | --- | --- |
| Planner | Writer 内部 `Planner` | 都会先生成一个计划 | Anthropic 更偏高层“做什么”；ACO Writer 更偏低层“怎么跑这几个 step” |
| Generator | `WriterAgent` | 都是真正产出内容的执行体 | ACO Writer 更像结构化内容工厂，不是开放式长时编码 agent |
| Evaluator | 外层 `CriticAgent`，其次才是 Writer 内部 `Reflector` | 都会评估产物质量并推动下一轮 | Anthropic 强调外部独立评估器；Writer 内部 `Reflector` 仍然偏自我质检 |

这张表最重要的结论是：

**ACO 里真正更像 Anthropic evaluator 的，不是 Writer 内部 `Reflector`，而是外层 `CriticAgent`。**

#### 真正像的地方，到底像在哪

如果只抓最有价值的共通点，主要有三条：

1. 都在做角色分离
   - 不是一次 prompt 直接出最终结果
2. 都不是“生成结束就算完”
   - 后面还有评估和反馈
3. 都在避免“生成器自己无限自我感觉良好”
   - ACO 用外层 Critic
   - Anthropic 用独立 evaluator

也就是说，真正像 Anthropic 的地方，不是“三个名字摆出来”，而是：

**生成和评估被拆开了，而且评估结果会继续驱动下一轮。**

#### 真正“不像”的部分，再压一层

如果要再压成一组更锋利的判断，最关键的不相似点其实是：

1. `Planner` 粒度不一样
   - Anthropic 是高层产品规格规划
   - ACO Writer 是节点内执行计划
2. `Reflector` 的独立性不一样
   - Anthropic evaluator 是外部独立裁判
   - Writer 内部 `Reflector` 仍然属于 Writer 自检链
3. 交接机制不一样
   - Anthropic 强调合同式迭代和文件式 handoff
   - ACO 更偏共享 state + 结构化字段传递

所以更准确的判断不是：

- ACO 已经等于 Anthropic 那套

而是：

- 它已经具备“角色分离 + 外部评估 + 反馈回路”的方向
- 但规划粒度、评估独立性、交接形式都还更轻

### 10.13 `WriterAgent` 更像哪类多 Agent 协作架构

当前最准确的说法是：

**`WriterAgent` 是一个对外表现为独立 Agent、对内又像小型 coordinator 的复合 Agent。**

它不是经典的上下文隔离 subagent 系统，但内部有明显的顺序委派味道。

#### 为什么很多人第一眼会觉得它“更像 Subagent”

因为从 `execute()` 往下看，Writer 确实很像：

- 先拆出一组子任务
- 再按顺序调用不同执行单元
- 每个执行单元只负责一段明确职责
- 上一步产物再交给下一步
- 最后由 owner 收口

如果从这个任务分解视角看：

- `_prepare_references()`
- `_generate_text_structure_step()`
- `_generate_blueprint_step()`
- `_calculate_metrics()`
- `_integrate_results()`

确实很像一串内部 worker / 子执行单元：

- 一个负责材料准备
- 一个负责文本生成
- 一个负责蓝图生成
- 一个负责指标计算
- 一个负责最终装配

所以“它像 Subagent”这个直觉是对的，只是还不够严格。

#### 为什么它不像严格意义上的 `Subagent`

因为标准 subagent 往往意味着：

- 父 Agent 显式 dispatch 子 Agent
- 子 Agent 有独立上下文
- 子 Agent 有自己的生命周期
- 完成后再把结果回传

而当前 `WriterAgent` 内部的：

- `Planner`
- `Reflector`
- `_prepare_references()`
- `_generate_text_structure_step()`
- `_generate_blueprint_step()`

都还不是这种真正上下文隔离、显式 handoff 的子运行单元。

更具体地说，它还差几个标准 subagent 才有的特征：

- 独立上下文窗口
- 独立 agent id / run state
- 独立消息历史
- 独立结束 / 恢复语义
- 明确的 dispatch / return handoff 边界

所以当前它更像：

- 同一进程里的内部执行函数

而不是：

- 真正上下文隔离的独立子 Agent

#### 为什么它也不像 `Team / Swarm`

因为这里没有：

- 多个平级 teammate
- 共享任务板
- 横向 agent-to-agent 协商

它的 owner 很明确：

- `WriterAgent`

内部只是它在顺序调自己的子模块和步骤函数。

#### 为什么它又比“纯 Coordinator”更接近 Subagent-like

因为从任务分工视角看，`execute()` 确实很像：

- 父调度者
- 顺序委派多个内部 worker
- 每个 worker 负责一个明确子任务
- 最后统一收口

所以更贴切的中间表述是：

**`WriterAgent` 更像“subagent-like 的串行委派”，而不是标准上下文隔离的 Subagent 系统。**

#### 如果把它们当作工具/子 Agent 去理解，Plan 应该怎么变化

如果以后真把 Writer 往显式工具编排那边推，`Plan` 就不能只是一张说明书了，而更像：

- 调用合同

也就是说，未来的 `PlanStep` 不应只有：

- `goal`
- `success_criteria`

而应该进一步带出：

- `executor_key`
- `input_selector`
- `expected_output`
- `success_criteria`

例如：

```json
{
  "step_id": 2,
  "goal": "生成文案结构",
  "executor_key": "generate_text_structure",
  "input_selector": ["topic", "platform", "references", "geo_keywords", "action"],
  "expected_output": "TextStructure",
  "success_criteria": "文案长度 800-1200，覆盖主要 GEO 关键词"
}
```

这样 `WriterAgent` 才能真正做到：

- 按 `Plan` 生成 `tool_call`
- 被调单元自己构造局部上下文
- 再以结构化 `tool_result` 回传

这时它就会明显更接近：

- 节点内 subagent orchestration

而不是现在这种：

- 函数编排 + 共享输入状态

#### 为什么它对外还是一个独立 Agent，而不是单纯 workflow 壳

这里最容易误解的一点是：

- `WriterAgent.execute()`
  - 看起来像在 orchestrate 很多内部步骤
- 所以容易让人觉得：
  - 它自己是不是“没干活”

但更准确的判断是：

**`WriterAgent` 的职责不是“亲手完成所有子动作”，而是“对内容生成结果负责的节点内负责人”。**

它至少在做四类事：

1. 定义 Writer 这条节点内部流水线
2. 拥有核心业务执行函数
   - `_prepare_references()`
   - `_generate_text_structure_step()`
   - `_generate_blueprint_step()`
   - `_calculate_metrics()`
   - `_integrate_results()`
3. 管理节点内状态
   - `plan`
   - `step_results`
   - `attempt`
   - `best_result`
4. 对最终 `GeneratedContent` 负责

所以它不是“单纯分配工作但自己不落手”的纯 coordinator，而是：

**编排 + 生成责任归口 + 最终结果收口都在它身上。**

#### `Planner / Reflector / WriterAgent` 的 owner 关系到底是什么

最准确的说法是：

- `Planner`
  - 给 Writer 提供执行草案
- `Reflector`
  - 给 Writer 提供局部质检和重试建议
- `WriterAgent`
  - 才是最终 owner

也就是说：

- `Planner` 不是 owner
- `Reflector` 不是 owner
- `WriterAgent` 才是 owner

这也是为什么对外暴露的仍然是：

- `WriterAgent.execute(input_data) -> GeneratedContent`

而不是把每个内部子模块都抬升成 workflow 主链上的平级角色。

#### 如果以后真按 Subagent / 工具编排重构，会变成什么

更成熟的形态会是：

- `Plan` 不只是说明书，而是调用合同
- 每个 step 对应：
  - 一个工具
  - 或一个子 Agent
- `WriterAgent` 按 `executor_key / input_selector / expected_output`
 进行 dispatch
- 子执行单元自己构造局部上下文
- 再以结构化 `tool_result` 回传

例如一个更 tool-call 化的 `PlanStep` 可能长这样：

```json
{
  "step_id": 2,
  "goal": "生成文案结构",
  "executor_key": "generate_text_structure",
  "input_selector": ["topic", "platform", "references", "geo_keywords", "action"],
  "expected_output": "TextStructure",
  "success_criteria": "文案长度 800-1200，覆盖主要 GEO 关键词"
}
```

这样做的价值在于：

- 每个步骤边界更清楚
- 更接近真正的 harness / subagent 编排
- 更适合以后做：
  - per-step retry
  - execution log
  - 可视化任务板
  - 中断恢复

#### 这条重构路线值不值得

我的判断是：

- 有价值
- 但更适合“有选择地工具化 / 子 Agent 化”

而不是把每个内部步骤都硬抬成独立 Agent。

通常更适合先工具化的会是：

- `_calculate_metrics()`
- `_integrate_results()`

更适合做成带局部上下文子执行单元的会是：

- `_prepare_references()`
- `_generate_text_structure_step()`
- `_generate_blueprint_step()`

所以最稳的表述不是：

- “Writer 已经是标准 Subagent 系统”

而是：

- **当前 Writer 是一个 coordinator-like 主 Agent，内部采用了 subagent-like 的串行委派。**

### 10.14 如果以后把 Writer 做成 skill，边界该怎么画

更自然的做法是：

- 顶层做一个 `writer_pipeline` skill
- `input_data` 就是 skill 输入
- `GeneratedContent` 是 skill 输出

内部的：

- `create_plan()`
- `reflect(stepX)`
- `integrate_results()`

更适合作为 skill 内部步骤，而不是全部升成独立顶层 skill。

#### 为什么这条线本身适合抽成一个 workflow skill

`WriterAgent.execute()` 这条线其实已经具备了一个复合 skill 最关键的几个特征：

- 有明确输入
  - `input_data`
- 有相对固定的内部流程
  - `create_plan -> references -> text_structure -> blueprint -> metrics -> final_reflection`
- 有明确输出
  - `GeneratedContent`
- 有稳定职责
  - 把“上下文 + 策略 + references”变成结构化内容产物

所以它更像：

- `writer_pipeline`
- `writer_content_pipeline`
- `generate_structured_content`
- `content_draft_workflow`

这种“节点级复合 skill / workflow skill”。

也正因为如此，更自然的 skill 化边界不是：

- 把每个内部 step 都升成顶层 skill

而是：

- **把整条 Writer 流水线收口成一个对外能力入口**

#### 这里其实要先分清两层不同的“skill”

这部分如果不分开，最容易越讲越绕。

##### 第一层：架构层的 skill

如果说的是系统设计意义上的 skill，那它更像：

- `WriterAgent` 调一个能力单元：`writer_pipeline`
- 直接把 `input_data: dict` 传进去
- 像函数调用一样：

```python
result = writer_pipeline.run(input_data)
```

这时候它更像：

- tool call
- skill call
- subagent call

也就是：

- **运行时能力调用**

这层不一定非要经过 CLI。

##### 第二层：Codex / 本地 skill 包

如果说的是 `SKILL.md + scripts/ + references/ + assets/` 这种落地包，那它本质上不是一个天然 typed tool，而更像：

- 一份技能说明书 `SKILL.md`
- 一组按需读取的参考材料 `references/`
- 一组可执行脚本 `scripts/`
- 一些静态模板与资源 `assets/`

这时 `WriterAgent` 真正调用的通常不是：

- `SKILL.md` 本身

而是：

- **skill 里 `scripts/` 的主入口**

也就是说：

- 架构层的 `writer_pipeline`
  - 是能力边界
- 本地 skill 包
  - 是这个能力边界的一种工程封装形式

#### 最先要分清的一件事：这里的 skill 是“对外能力边界”，不是“内部步骤名录”

如果把 `WriterAgent.execute()` 抽成一个 skill，最重要的分层其实是：

- 对外
  - 它是一个完整能力入口
- 对内
  - 它仍然是一条固定工作流

也就是说：

- `writer_pipeline(input_data) -> GeneratedContent`
  - 是 skill 的能力边界
- `create_plan / reflect / integrate_results`
  - 是这个能力内部怎么完成的工序

所以 `input_data` 在这里既是：

- 当前 `WriterAgent.execute()` 的输入

也可以直接理解成：

- 未来 `writer_pipeline` skill 的输入载荷

#### 如果真的做成一个 `writer_pipeline` skill，结构大概是什么

最自然的目录可以长这样：

```text
writer-pipeline/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
│   ├── run_writer_pipeline.py
│   ├── prepare_references.py
│   ├── calculate_metrics.py
│   └── integrate_results.py
├── references/
│   ├── writer_input_schema.md
│   ├── generated_content_schema.md
│   ├── blueprint_schema.md
│   └── reflection_contract.md
└── assets/
    └── prompt_templates/
        ├── text_generation.md
        ├── blueprint_stage1.md
        └── blueprint_stage2.md
```

各部分更适合这样分工：

- `SKILL.md`
  - 定义这个 skill 什么时候触发、输入输出边界是什么、主入口脚本是什么
- `scripts/`
  - 承载稳定执行逻辑
- `references/`
  - 放输入输出 schema、规则说明、约束合同
- `assets/`
  - 放 prompt 模板、样例、静态资源
- `agents/openai.yaml`
  - 如果采用本地 skill 包组织方式
  - 可以放模型/执行器侧的补充配置

#### `input_data` 怎么真正喂给 skill

这里也要先说清一个边界：

- 如果只是架构层的 skill
  - `WriterAgent` 可以直接把 `input_data: dict` 传给 `writer_pipeline.run(...)`
- 如果是本地 skill 包
  - 最常见的落地方式才会变成：
    - skill + 脚本入口
    - 用 CLI / JSON 文件 / stdin 之一喂给脚本

最稳的做法不是让模型临时拼很多 CLI 参数，而是：

1. `WriterAgent`
   - 把 `input_data` 写成 `writer_input.json`
2. 调主脚本：
   - `python scripts/run_writer_pipeline.py --input ... --output ... --mode writer_pipeline`
3. 脚本内部读取：
   - `writer_input.json`
   - 按需加载 `references/` 和 `assets/`
4. 脚本产出：
   - `writer_output.json`
5. `WriterAgent`
   - 再把它读回并解析成 `GeneratedContent`

所以：

- `--input`
  - 输入文件路径
- `--output`
  - 输出文件路径
- `--mode`
  - 执行模式

而真正的业务数据本身，仍然主要放在：

- `writer_input.json`

这里可以把它类比成：

- `--input / --output / --mode`
  - 更像“怎么调用这个脚本”的控制参数
- `writer_input.json`
  - 更像真正的请求体

如果只是枚举可选输入方式，本地 skill 包常见其实有三种：

- CLI 参数
  - 适合非常轻的控制字段
- JSON 文件
  - 最适合 `input_data` 这种结构化负载
- stdin
  - 也能承载结构化输入

但对 Writer 这种复杂输入，最稳的仍然是：

- **JSON 输入文件 + JSON 输出文件**

更直白一点说：

- `SKILL.md`
  - 不是直接“吃参数”的那层
- 真正接收 `input_data` 的
  - 往往是 `scripts/run_writer_pipeline.py`

所以更稳的调用链应该是：

1. `WriterAgent`
   - 写 `writer_input.json`
2. 运行：
   - `python scripts/run_writer_pipeline.py --input ... --output ... --mode writer_pipeline`
3. 脚本内部
   - 读取 JSON
   - 按需加载 `references/`、`assets/`
   - 执行整条 writer 流水线
4. 再写出：
   - `writer_output.json`
5. `WriterAgent`
   - 读取输出并解析成 `GeneratedContent`

所以更稳的不是：

- 让 LLM 直接从自然语言里临时拼很多 CLI 参数

而是：

- `SKILL.md` 定义协议
- `scripts/` 作为真正执行入口
- JSON 输入输出承载结构化数据

所以更稳的协议不是：

- 让模型从自然语言里临时拼一长串 `--topic / --platform / --references ...`

而是：

- `SKILL.md`
  - 定义好调用协议
- `WriterAgent`
  - 负责把结构化输入写成 JSON
- `scripts/run_writer_pipeline.py`
  - 负责读取 JSON、执行 skill、再写回结构化输出

这条边界清楚之后，skill 化才不会退化成“让 LLM 临时组装一堆脆弱 CLI 参数”。

#### `SKILL.md`、`scripts/`、`references/`、`assets/` 到底在这里各干什么

把 `writer_pipeline` skill 看成一个完整能力包时，最自然的分工是：

- `SKILL.md`
  - 说明这个 skill 什么时候该触发、整体流程怎么跑、主入口脚本是什么
- `scripts/`
  - 承载稳定执行逻辑，例如：
    - `run_writer_pipeline.py`
    - `prepare_references.py`
    - `calculate_metrics.py`
    - `integrate_results.py`
- `references/`
  - 放输入输出 schema、规则说明、reflection contract 等知识材料
- `assets/`
  - 放 prompt 模板、示例、静态资源

也就是说：

- `SKILL.md`
  - 更像使用手册 / 调度说明 / 高层执行规范
- `scripts/`
  - 才是真正的执行入口

同时这几个目录的职责最好也分清：

- `references/`
  - 是 skill 的知识材料
  - 例如输入 schema、输出 schema、reflection contract
- `assets/`
  - 是 skill 的静态资源
  - 例如 prompt 模板、示例、固定素材

它们都不是：

- 这次任务的 runtime 业务数据

真正的 runtime 业务数据还是：

- `writer_input.json`

这也是为什么“渐进式加载 `references/`、`assets/`”这句话不能和 runtime 输入混在一起看：

- `input_data / writer_input.json`
  - 是这次任务的数据
- `references/`
  - 是 skill 的知识材料
- `assets/`
  - 是 skill 的静态资源

这三者在工程上不是同一层东西。

#### 这里“对外”和“对内”到底什么意思

如果把 `writer_pipeline` 抽成一个 skill，最容易混的就是这两个层级：

- 对外
  - 谁来调用这个 skill
  - 它暴露什么输入输出能力边界
- 对内
  - 这个 skill 自己内部到底怎么完成任务

放到这条 Writer 流水线上，可以直接理解成：

```text
对外:
  writer_pipeline(input_data) -> GeneratedContent

对内:
  create_plan()
  -> prepare_references()
  -> reflect(step1)
  -> generate_text_structure()
  -> reflect(step2)
  -> generate_blueprint()
  -> reflect(step3)
  -> calculate_metrics()
  -> reflect(step4)
  -> integrate_results()
  -> final_reflection()
```

所以：

- `input_data`
  - 既是当前 `WriterAgent.execute()` 的输入
  - 也可以理解成未来这个 skill 的输入载荷
- `create_plan / reflect / integrate_results`
  - 更像 skill 内部步骤
  - 不一定值得都升成独立顶层 skill

#### `create_plan()`、`reflect(stepX)`、`integrate_results()` 要不要都升成 skill

通常不值得。

因为它们更像：

- skill 内部步骤
- 控制逻辑
- 质检逻辑
- 收口逻辑

而不是“外部值得单独调用的完整业务能力”。

所以更自然的边界是：

```text
对外:
  writer_pipeline(input_data) -> GeneratedContent

对内:
  create_plan()
  -> prepare_references()
  -> reflect(step1)
  -> generate_text_structure()
  -> reflect(step2)
  -> generate_blueprint()
  -> reflect(step3)
  -> calculate_metrics()
  -> reflect(step4)
  -> integrate_results()
  -> final_reflection()
```

#### CLI 参数在这里更像什么

如果用本地脚本入口来承接这个 skill，那：

- `--input`
  - 更像输入文件位置
- `--output`
  - 更像输出文件位置
- `--mode`
  - 更像执行模式 / 路由参数

而真正的业务数据本身，主要还是放在：

- `writer_input.json`

可以把它类比成：

- CLI flag
  - 负责“怎么调用”
- JSON 文件
  - 负责“这次调用的数据内容”

所以它更像：

**轻量查询参数 / 路由参数 + 结构化请求体**

而不是把所有复杂字段都硬塞进一串 CLI options。

如果压成最短的三分法：

- `--input`
  - 输入文件路径
- `--output`
  - 输出文件路径
- `--mode`
  - 执行模式 / 路由参数

而：

- `writer_input.json`
  - 才承载这次任务真正的结构化业务输入

所以 skill 化时最值得学的边界不是：

- “把所有字段都 CLI 参数化”

而是：

- **把调用控制参数和业务数据本身分开。**

#### 一句话收住 skill 这层边界

**如果把 `WriterAgent.execute()` 抽成 `writer_pipeline` skill，最自然的做法是“对外只有一个完整技能入口，对内保留固定工作流步骤”；架构层它是一个能力边界，本地封装层它更像 `SKILL.md + scripts/ + references/ + assets/` 组成的能力包，而 `input_data` 就是这个能力包最终要接收的结构化输入载荷。**

---

## 11. `content_evaluation` 节点：把生成结果转成可控的质量信号

`content_evaluation` 不是简单“打个分”，而是：

**把这轮生成结果转成一份结构化的正式评估结果 `CriticEvaluation`。**

### 11.1 节点本身写回了什么

这个节点主要会把 Critic 产物写回到 state：

- `state["evaluation"]`
- 视情况更新：
  - `state["final_content"]`
  - `state["final_score"]`
- 同时往 `state["messages"]` 追加一条 Critic 轨迹记录

这里要区分：

- `state["evaluation"]`
  - 是正式业务结果
- `state["messages"]`
  - 是过程记录 / trace

#### `state["evaluation"]` 和 `state["messages"][-1]` 到底怎么区分

这里最容易混的地方是：

- `state["evaluation"]`
  - 是当前最新、正式、可消费的评估结果
- `state["messages"][-1]`
  - 是“刚才这次评估发生过”的运行日志快照

也就是说：

- 前者回答：
  - 这轮评估结果现在是什么
- 后者回答：
  - 这轮 workflow 刚才发生了什么

所以即使 `messages[-1]["data"]` 里塞了一份 `evaluation`，两者语义也不一样：

- `evaluation`
  - 是主状态字段
- `messages`
  - 是过程留痕

#### 什么情况下会更新 `final_content`

`content_evaluation` 不只是写回 `evaluation`，还可能更新：

- `state["final_content"]`
- `state["final_score"]`

这通常发生在：

- 当前轮 `overall_score` 比已有最佳结果更高
- 或当前还没有任何 `final_content`

所以：

- `generated_content`
  - 记录的是“当前这一轮最新生成结果”
- `final_content`
  - 记录的是“到目前为止最好的一版”

这也是为什么 workflow 进入多轮 refinement 后，仍然能保留历史最优版本，而不是被最后一轮结果简单覆盖。

#### `state["messages"]` 里 Critic 那条 message 大致长什么样

这一条不是 LangChain 的 `HumanMessage / AIMessage / ToolMessage`，而更像项目自定义的运行轨迹字典。

大致可以理解成：

```json
{
  "role": "critic_agent",
  "content": "Evaluation complete: 8.3/10, Status: APPROVED",
  "data": {
    "overall_score": 8.3,
    "approval_status": "APPROVED",
    "dimension_scores": [...],
    "summary": "...",
    "critical_issues": [...],
    "highlights": [...],
    "improvement_suggestions": [...]
  }
}
```

它的主要作用不是“对话”，而是：

- 记录这个节点刚才做了什么
- 给调试、监控、trace 留一份摘要
- 顺手把这次评估的关键产物挂在 `data` 里

#### 如果从工程演进角度看，这条评估链最值得补什么

这部分不属于当前代码里“已经实现好的执行步骤”，但它对理解 `content_evaluation` 这条链为什么还不算完全收口，非常关键。

从历史会话里反复出现的判断看，最值得补强的其实是 4 件事：

##### 1. 把 LLM 的评分建议和代码的最终判决分开

当前这条链里，LLM 会给出：

- `score`
- `needs_retry`
- `improvement_suggestions`

但真正进入 workflow 主链下一步时，系统最终需要的其实不是“模型主观上想不想 retry”，而是：

- 这轮是否达到硬门槛
- 这轮是否允许放行
- 这轮如果不达标，到底是哪类原因导致

所以更稳的做法应该是：

- LLM 提供：
  - 评分建议
  - 缺陷描述
  - 改进建议
- 代码统一做最终判决：
  - 是否 retry
  - 是否进入 refinement
  - 是否直接判成低质量结果

也就是把：

- “模型评分”
- “代码判决”

从同一个字段里拆开。

##### 2. 把可代码验证的标准尽量从自然语言里拉出来

当前很多标准仍然是自然语言，比如：

- “评分合理，理由具体”
- “内容质量评分 >= 8.0，GEO 覆盖率 >= 0.8”

这里面其实混着两类东西：

- 主观质量判断
- 客观可测约束

更稳的路线是：

- 客观约束尽量变成代码字段
  - `geo_coverage`
  - `references_count`
  - `num_shots`
  - `text_length_ok`
- 主观质量再交给 LLM 做 rubric-based scoring

也就是：

**能代码验证的先代码验证，剩下主观部分再让 LLM 做 rubric-based scoring。**

##### 3. 把 `Reflector` 和 `Critic` 的职责边界切得更硬

当前它们都在“评估”，但层级不同：

- `Reflector`
  - 更像节点内质检器
  - 负责局部重跑建议
- `Critic`
  - 更像 workflow 外层正式验收器
  - 负责整轮审批、正式评分和改进建议

如果把这层边界讲得更硬，会更清楚：

- `Reflector`
  - 只做节点内 QA / repair advisor
  - 关注“当前这一步还能不能修、该怎么修”
- `Critic`
  - 独占整轮正式验收
  - 关注“这轮结果是否通过、是否进入 refinement、是否更新最终结果”

这也能解释为什么：

- `reflect(each dimension)`
  - 当前更像局部质检位
- `content_evaluation`
  - 才是真正改变 workflow 主链走向的正式评估位

##### 4. 让 Critic 的输出尽量全结构化

当前 Critic 单维评估虽然已经有结构化结果，但底层仍有“评分: X.X / 理由: ... 再解析”的痕迹。

更稳的方向是让每一维尽量直接输出：

- `dimension`
- `score`
- `reasoning`
- `evidence`
- `pass`

这样后面的：

- `aggregate overall_score`
- `make_approval_decision()`
- `extract_critical_issues()`
- `generate_improvement_suggestions()`

就更像处理一组正式结构化评审记录，而不是反复从半结构化文本里二次提炼。

#### 如果按投入产出比排优先级，最自然的三阶段改法是什么

##### 第一阶段：先做最划算的收口

- 给评估链增加更明确的代码层判决函数
- 把客观约束从自然语言 `success_criteria` 里拉出来
- 保持 LLM 负责评分建议，代码负责最终放行/重试判断

##### 第二阶段：把角色边界讲硬、字段语义讲清

- 文档和代码都明确：
  - `Reflector = 内部质检`
  - `Critic = 正式验收`
- 区分：
  - `step_score / attempt_score`
  - `overall_score`

这样后面分析日志和调试时，不会再把节点内评分和正式评分混成一类。

##### 第三阶段：把 Critic 变成真正更严格的外部裁判

- 单维评估尽量改成全结构化输出
- 减少对文本正则抽取的依赖
- 让 evidence / pass / issues 能更稳定地进入后续收口层

如果把这三步做完，`content_evaluation` 这一节就会从：

- “功能上可跑通的评估流水线”

更进一步变成：

- “评分建议、代码判决、正式验收边界都更清楚的评估系统”

### 11.2 `content_evaluation` 节点内部也有一条流水线

和 `content_generation` 一样，`content_evaluation` 节点本身更像 orchestrator。

真正的评估流水线在 `CriticAgent.execute(...)` 里。最适合按一条连续流程看：

1. `execute()`
2. `create_evaluation_plan()`
3. `retrieve_evaluation_criteria()`
4. `evaluate_single_dimension()`
5. `reflect(each dimension)`
6. `aggregate overall_score`
7. `make_approval_decision()`
8. `generate_summary()` / `extract_critical_issues()` / `extract_highlights()` / `generate_improvement_suggestions()`
9. `overall_reflection()`
10. `assemble CriticEvaluation`

这里有一个很容易混的点，要单独说清：

- `evaluation_plan.steps`
  - 真正对应的是那 5 个“评内容质量 / 评用户体验 / 评平台适配 / 评 SEO / 评视觉呈现”的维度步骤
- `retrieve_evaluation_criteria()`
  - 是前处理，负责补评估标准材料
- `reflect(each dimension)`
  - 是每个维度评完后的局部质检
- `aggregate / approval / summary / overall_reflection`
  - 是所有 plan step 执行完之后的收口层

也就是说，Critic 内部确实是一条连续流水线，但不是“plan step = 整条流水线里的所有节点”。

- `plan step`
  - 更像真正的“评估科目”
- 前处理、局部质检、收口
  - 是包在这些科目前后的执行层

所以 `content_evaluation` 这个 workflow 节点本身不直接负责评分，它真正做的是：

1. 从共享 `state` 里组装 `generated_content / platform / goal_metric / references / quality_threshold`
2. 调 `CriticAgent.execute(input_data)`
3. 再把内部流水线产出的 `CriticEvaluation` 写回 `state`

### 11.3 `create_evaluation_plan()`：Critic 的 planning 在做什么

它和 Writer 一样，也会生成结构化 `Plan / PlanStep`。

但语义不同：

- Writer Plan
  - 生产计划
- Critic evaluation_plan
  - 评估计划

默认会拆成五个维度：

- step 1：评内容质量
- step 2：评用户体验
- step 3：评平台适配
- step 4：评 SEO
- step 5：评视觉呈现

#### 它和 Writer 的 Plan 到底像不像

结构上很像，语义上不同：

- Writer Plan
  - 生产计划
  - 关注“怎么把内容做出来”
- Critic evaluation_plan
  - 评估计划
  - 关注“怎么把内容拆成多个维度来验收”

可以把 Critic 的默认 `evaluation_plan` 理解成：

```json
{
  "complexity": "medium",
  "steps": [
    {
      "step_id": 1,
      "goal": "内容质量",
      "action": "评估文案的原创性、深度和价值感",
      "success_criteria": "评分合理，理由具体，能指出真正的优缺点"
    },
    {
      "step_id": 2,
      "goal": "用户体验",
      "action": "评估可读性、吸引力和情绪带动",
      "success_criteria": "评分与阅读体验一致，能说明吸引点和流失点"
    },
    {
      "step_id": 3,
      "goal": "平台适配",
      "action": "评估是否符合平台语境、平台规范和用户习惯",
      "success_criteria": "能指出不符合平台表达习惯的地方"
    },
    {
      "step_id": 4,
      "goal": "SEO 优化",
      "action": "评估关键词覆盖、标题与表达的检索友好性",
      "success_criteria": "能说明哪些表达更利于检索与发现"
    },
    {
      "step_id": 5,
      "goal": "视觉呈现",
      "action": "评估拍摄蓝图的可执行性和视觉吸引力",
      "success_criteria": "能指出蓝图是否可拍、是否有视觉亮点"
    }
  ]
}
```

这里最重要的不是字段名，而是：

- `goal`
  - 决定这一步评哪个维度
- `action`
  - 决定这一步评什么侧面
- `success_criteria`
  - 决定这一步“评得好不好”

后面的：

- `evaluate_single_dimension()`
- `reflect(each dimension)`

就是围绕这些 step 去跑的。

这里再往下压一层，和 Writer 的 `Plan` 一样，Critic 的 `evaluation_plan` 也要分“理论自由度”和“当前执行自由度”两层看：

- 理论上
  - 只要开了 planning，LLM 就可以生成不同的维度描述、`action` 和 `success_criteria`
- 但当前实现上
  - 执行器仍然会把每个 step 收敛成“调一次 `_evaluate_single_dimension(step.goal, ...)`”

所以当前这份 `evaluation_plan` 更准确的工程定位其实是：

- 一份结构化的评估合同
  - 决定“分哪几科”
  - 决定“每科大概要看什么”
  - 决定“这一科评分时至少该满足什么说明义务”

还不是：

- 一个完全开放的自由执行图

也正因为如此，后面 `evaluate_single_dimension()` 的真实质量，很大程度上并不取决于 `PlanStep` 写得多漂亮，而取决于：

- 这一维到底喂了什么上下文
- 这一维的 rubric / checklist 是否足够清楚
- 这一维的输出结构是否足够稳

### 11.4 节点 4：`evaluate_single_dimension()`

这一步是 Critic 里最核心的业务评估节点。

#### 11.4.1 共同机制

当前实现里，这五个维度不是五套完全不同的评估器，而更像：

**同一个单维评估函数 + 不同维度名。**

#### 11.4.2 共同输入

每一维都会带入：

- `dimension_name`
- `generated_content`
- `platform`
- `references`
- `evaluation_criteria`
- 可选 `feedback`

但当前 prompt 实际最依赖的，主要还是：

- `platform`
- `generated_content["text_structure"]["full_text"]`
- `dimension_name`

#### 11.4.3 共同输出

每一维会输出一个 `DimensionScore`，至少包括：

- `dimension`
- `score`
- `reasoning`

#### 11.4.4 这五个维度是不是都要调用 LLM

对。

这五个维度的当前实现，都是调用 LLM 来完成评分。

从依赖关系上看，它们其实可以并行；只是当前代码为了配合“单维评估 -> 单维 reflect -> 单维重评”的闭环，采用了串行实现。

#### 11.4.5 维度 1：内容质量

##### 这一维的业务意图

它真正想评的是：

- 文案有没有信息密度
- 有没有实际价值
- 有没有原创表达
- 是不是只是空话 / 套话

##### 当前实际输入给 LLM 的上下文

当前最关键的上下文其实是：

- `generated_content["text_structure"]["full_text"]`
- `dimension_name = 内容质量`
- 少量 `evaluation_criteria`

也就是说，这一维现在主要还是在看：

**文案正文是否“像高质量内容”。**

##### 当前输出

它会输出一个 `DimensionScore`，至少包括：

- `dimension = 内容质量`
- `score`
- `reasoning`

##### 当前问题

当前问题主要有两个：

- 还没有更细的 rubric / checklist
- 评分更多是 LLM 的主观判断，而不是证据先行

##### 更稳的做法

更稳的做法通常是：

- 先让模型列证据
- 再按：
  - 信息密度
  - 原创性
  - 实用性
  - 清晰度
   逐项判断
- 最后再汇总成这一维的分数

#### 11.4.6 维度 2：用户体验

##### 这一维的业务意图

它想评的其实是：

- 可读性强不强
- 开头能不能把人拉住
- 文案读起来顺不顺
- 情绪有没有带起来

##### 当前实际输入给 LLM 的上下文

当前这维实际吃到的，仍然主要是：

- `full_text`
- `dimension_name = 用户体验`
- 少量 `evaluation_criteria`

它并没有吃到：

- 真实用户行为
- 真实点击 / 停留 / 完读数据

所以这一步更准确地说是：

**基于文本本身做“假想阅读体验”评估。**

##### 当前输出

输出仍然是一个 `DimensionScore`。

##### 当前问题

这维最典型的问题是：

- 容易和“内容质量”部分重叠
- 如果没有更细 checklist，很容易沦为泛泛而谈的主观印象分

##### 更稳的做法

更稳的做法是把它拆成更可判定的子项，例如：

- 开头吸引力
- 段落流畅度
- 节奏感
- 情绪带动
- CTA 的阅读完成感

#### 11.4.7 维度 3：平台适配

##### 这一维的业务意图

它主要在看：

- 像不像该平台上的内容
- 是否符合平台表达习惯
- 是否符合平台用户预期
- 有没有明显违背平台语境的地方

##### 当前实际输入给 LLM 的上下文

当前这维最关键的输入是：

- `platform`
- `full_text`

如果前面的 `retrieve_evaluation_criteria()` 没有补到更细的标准，那么这维就主要依赖：

- 平台名
- LLM 自己对平台风格的先验理解

##### 当前输出

输出仍然是：

- 一个 `DimensionScore`

##### 当前问题

这维当前最弱的地方是：

- 如果没有额外平台规则或平台样例，它依然偏主观
- “平台适配”很容易只停留在泛化印象，而不是更细的规则判断

##### 更稳的做法

更稳的补法包括：

- 喂平台规则 / 样例
- 把平台适配拆成：
  - 语言语气
  - 结构习惯
  - CTA 风格
  - 平台禁忌项

#### 11.4.8 维度 4：SEO 优化

##### 这一维的业务意图

这维在业务上想看的是：

- 关键词覆盖
- 标题 / 表达的检索友好性
- 内容是否利于搜索发现

##### 当前实际输入给 LLM 的上下文

当前最关键的现实问题是：

**这维理论上应该看 `geo_coverage` 等硬指标，但当前实现并没有真正把 `geo_coverage` 显式喂给单维评估 prompt。**

所以现在更像：

- 业务意图是 SEO
- 实际上仍然主要让 LLM 基于 `full_text` 做主观判断

##### 当前输出

输出仍然只是：

- 一个 `DimensionScore`

##### 当前问题

这维当前存在一个很明显的错位：

- Writer 已经有代码计算的 `geo_coverage`
- 但 Critic 的 SEO 维度并没有直接消费这个硬指标

也就是说：

**可代码验证的信息，没有真正进入这一维的单维评估。**

##### 更稳的做法

更好的路线是：

- 能代码先算的：
  - `geo_coverage`
  - 关键词命中数
  - 标题命中
- 再让 LLM 评剩下主观部分：
  - 覆盖是否自然
  - 表达是否利于检索
  - 查询意图是否被回答

#### 11.4.9 如果要单独加 GEO 维度，最合理评哪些指标

如果把 GEO 从 SEO 里单独拆出来，我会建议至少评：

- `geo_coverage`
- `keyword_naturalness`
- `query_intent_match`
- `answer_extractability`
- `entity_topic_clarity`

其中：

- `geo_coverage`
  - 更适合代码先算
- 其他几项
  - 更适合 LLM 做 rubric-based scoring

#### 11.4.10 维度 5：视觉呈现

##### 这一维的业务意图

它理论上应该看：

- 蓝图是否可拍
- 镜头设计是否清楚
- 视觉风格有没有吸引力
- 整体表达是否成立

##### 当前实际输入给 LLM 的上下文

这里最关键的现实点是：

**这维理论上应该吃 `blueprint`，但当前实现主要还是吃 `full_text`。**

也就是说，它在名字上叫：

- 视觉呈现

但在输入上更接近：

- 基于文案正文推测视觉感

##### 当前输出

输出仍然是：

- 一个 `DimensionScore`

##### 当前问题

这维当前最弱的地方就是：

- 维度名和输入证据不对齐
- 明明应该检查 `blueprint`，却没有真正吃到 `blueprint`

##### 更稳的做法

更稳的做法是：

- 显式把 `blueprint.scene / shot_list / props / pacing / subtitle_style` 喂进去
- 再让模型去评：
  - 可执行性
  - 视觉吸引力
  - 节奏与风格协调性

#### 11.4.11 如何把这五维做扎实

更好的工程原则不是“全靠 COT”，而是：

**能代码验证的先代码验证，剩下主观部分再让 LLM 做 rubric-based scoring。**

#### 11.4.12 “LLM 主观评分”这条路上如何优化

不要只靠一句“请一步一步思考”。

更稳的顺序是：

1. 先补维度专属上下文
2. 再补 rubric / checklist
3. 再加 few-shot 校准评分口径
4. 再做 evidence-first / reasoned scoring
5. 最后才是 COT 提升一致性

也就是说，`COT` 只是最后一层提纯。

更大的提升通常来自：

- 每一维到底吃了什么上下文
- rubric / checklist 是否清楚
- few-shot 是否把评分口径校准了
- 输出是不是 evidence-first 的结构化结果

#### 11.4.13 `plan`、`rubric/checklist`、`few-shot` 的分工

- `plan`
  - 决定本轮评哪些维度
- `rubric/checklist`
  - 决定这一维按哪些子项评分
- `few-shot`
  - 决定评分口径如何校准

`rubric/checklist` 更适合做成 Critic skill 的内部规则材料，而不是单独一个顶层 skill。

更准确地说：

- `plan`
  - 负责“本轮分哪几科”
- `rubric/checklist`
  - 负责“每一科按哪些子项打分”
- `few-shot`
  - 负责“同样打 8 分时，口径到底是什么意思”

所以这三者不是替代关系，而是分层叠加关系。

#### 11.4.14 这五个维度现在到底是怎么“量化”的

这里很容易误会成：

- `evaluation_plan`
  - 已经把量化规则写死了
- 代码
  - 再去按规则硬算出每一维的分数

但当前实现其实不是这样。

更准确的链路是：

1. `evaluation_plan`
   - 先定义维度意图
   - 例如：内容质量、用户体验、平台适配、SEO、视觉呈现
2. `_evaluate_single_dimension()`
   - 把维度名和少量上下文塞进 prompt
3. prompt 里要求 LLM：
   - 按 `0-10` 打分
   - 给出理由
4. 代码再把这五维分数收口成：
   - `overall_score`
   - `approval_status`

所以当前这五维的“量化”主要来自三层：

- `plan`
  - 决定分哪几科
- `prompt`
  - 决定评分尺度是 `0-10`
- `LLM`
  - 真正给出每一科的主观分

也就是说，现在这五维更像：

**Plan 负责“分科目”，LLM 负责“每科打分”，代码负责“算总分和做审批”。**

这也是为什么前面一直强调：

- 当前 Critic 的业务意图分得很细
- 但“量化”还不算很强
- 还没有做到“每个维度都由一套稳定的可观测硬指标 + rubric 混合驱动”

#### 11.4.15 如果真的想把这五维做得更收口，最实际的工程顺序是什么

如果按收益优先级排序，而不是一上来就大改架构，我会把改法排成下面这条顺序：

1. 先补维度专属上下文
   - 让 SEO 真吃到 `geo_coverage / geo_keywords`
   - 让视觉呈现真吃到 `blueprint`
   - 让平台适配真吃到平台规则 / 样例
2. 再给每一维配 rubric / checklist
   - 让“评什么”从维度名升级成子项清单
3. 再做 few-shot 校准
   - 让不同分数段的口径更稳定
4. 最后再做 evidence-first / reasoned scoring
   - 先证据、再子项判断、最后给分

这条顺序的含义是：

- 不要先迷信 COT
- 先把“吃到什么输入、按什么标准评”这两件事补对
- 再追求“模型怎么想得更严谨”

#### 11.4.16 当前实现里最核心的限制到底是什么

如果把这一大段再压成一句最重要的工程判断，其实就是：

**默认 `evaluation_plan` 里这 5 个维度的业务意图很清楚，但 `_evaluate_single_dimension()` 实际喂给 LLM 的上下文还比较统一、比较薄。**

更具体地说，当前限制主要在这里：

- 五个维度都走同一个单维评估函数模板
- 真正变化的主要还是：
  - `dimension_name`
  - 少量 `evaluation_criteria`
- `action`
  - 没有充分转成强约束 prompt
- `success_criteria`
  - 更多只是泛化的提示语
- `references`
  - 虽然在接口上传进去了，但没有成为每一维都强消费的证据
- `SEO`
  - 业务上应该看 `geo_coverage`，但当前没有显式把它喂进 prompt
- `视觉呈现`
  - 业务上应该看 `blueprint`，但当前并没有真正把 `blueprint` 展开给这一维

所以当前 Critic 这 5 维更像：

- 同一个评估函数
- 换 5 个维度名
- 再让 LLM 做 5 次主观打分

而不是：

- 5 套上下文、证据、rubric 都强定制的专门评估器

这也是为什么这一节里会不断强调：

- 先补对维度专属上下文
- 再补 rubric / checklist
- 再谈 COT / few-shot / 评分一致性

### 11.5 节点 5：`reflect(each dimension)`

这一步理论上的作用，是：

**不是再评内容，而是评“刚才那次评估结果本身”靠不靠谱。**

但当前实现里，它确实比较容易显得重复，原因是：

- Reflector 看到的上下文太少
- `success_criteria` 很泛
- retry 的边际收益有限

所以它现在不是 Critic 最值得优先补强的点。

#### 它理论上想补什么

`evaluate_single_dimension()` 评的是内容在某一维上的表现。

`reflect(each dimension)` 理论上想补的是：

- 刚才这份评分是否合理
- 理由是否充分
- 要不要按建议重评这一维

也就是说，它想做的是：

**对“评估结果本身”的元评估。**

#### 为什么当前实现里会显得重复

因为 Reflector 当前看到的不是原始内容和完整证据，而主要是：

- 维度名
- 这次分了多少
- 一段理由
- 一句很泛的 `success_criteria`

所以它很难成为真正独立的二级裁判，更像：

- 对刚才那份评估结果再看一眼

#### 如果要处理这一步，现实上有三条路

- 保留，但把它降级成轻量局部质检
- 改成条件触发，例如只在分数异常、理由太短、证据不足时触发
- 暂时去掉单维 reflect，只保留 `overall_reflection()`

#### 为什么它在理论上不是完全没价值

虽然当前实现里它显得有些重复，但这一步理论上并不是完全没意义。

如果未来单维评估已经具备：

- 更明确的 rubric
- 更结构化的证据项
- 更完整的上下文输入

那么 `reflect(each dimension)` 就可能真正承担：

- 评分一致性检查
- 证据充分性检查
- “这条理由到底支不支持这个分数”的二次质检

那时它就不再只是“对同一件事又评一次”，而更像：

**对单维评估结果本身做 QA。**

所以当前更准确的工程判断不是：

- 这一步永远没用

而是：

- 这一步在当前实现里收益偏低
- 但如果单维评估前面的证据链更完整，它会变得更有价值

#### 如果真想让 Critic 这边的评估更收口，最值得先改什么

和 Writer 那边类似，Critic 这边真正更值得先补的，通常不是把 `reflect(each dimension)` 做得更花，而是先补前面的评估契约：

1. 让每一维吃到更对口的上下文
2. 让能代码验证的部分先代码验证
3. 让单维输出更结构化
4. 再决定这一步是：
   - 保留
   - 条件触发
   - 还是暂时去掉

也就是说，`reflect(each dimension)` 现在更像一个“可增强位”，不是 Critic 当前最核心的质量来源。

如果把这一步和节点 4 的关系压成最实用的一句判断，就是：

- 节点 4
  - 决定“这一维到底怎么打分”
- 节点 5
  - 只是检查“刚才那份分数和理由看起来稳不稳”

所以在当前实现里，真正更值得优先补强的，通常不是把节点 5 做得更复杂，而是先把节点 4 的：

- 证据输入
- rubric
- 可代码验证指标
- 输出结构

做扎实。

### 11.6 节点 6：`aggregate overall_score`

这一步负责把多个 `dimension_scores` 聚合成 `overall_score`。

当前实现里，它更像：

- 先拿到每个维度各自的 `score`
- 再把它们合成一个总体质量分

所以：

- `dimension_scores`
  - 是分科成绩
- `overall_score`
  - 是总成绩

所以这一步本质上在做：

**把五个局部评估结果，收口成一个 workflow 可以继续消费的总体质量信号。**

### 11.7 节点 7：`make_approval_decision()`

这一步负责把“总分”翻译成流程状态：

- `APPROVED`
- `NEEDS_REVISION`
- `REJECTED`

也就是说，这一步是在做：

**把“分数”翻译成“流程动作”。**

所以：

- `overall_score`
  - 只是一个数值结果
- `approval_status`
  - 才是更适合 workflow 消费的正式判决

这一步之所以重要，是因为它完成了从：

- “评估结果”

到：

- “流程动作”

的翻译。

### 11.8 节点 8：生成摘要、问题、亮点和建议

这一步会收口出：

- `summary`
- `critical_issues`
- `highlights`
- `improvement_suggestions`

这一步的本质是：

**把零散的评分结果，收口成下一轮真正能消费的评估报告文本。**

所以：

- `summary`
  - 给人快速看整体结果
- `critical_issues`
  - 告诉系统哪些问题最优先
- `highlights`
  - 告诉系统哪些地方不要误伤
- `improvement_suggestions`
  - 给下一轮 Writer 提供最直接可消费的修改建议

也可以反过来说：

- 节点 4/6/7
  - 更偏评分和判决
- 节点 8
  - 更偏可消费的解释和行动建议

### 11.9 节点 9：`overall_reflection()`

这一层也会调用 LLM，但它评的不是原始内容，而是：

**Critic 已经生成出来的整份评估报告本身。**

它的输入主要是：

- `overall_score`
- `dimension_scores`
- `approval_status`
- `goal`
- `success_criteria`

输出还是 `Reflection` 对象。

也就是说，它和前面的 Reflector 其实还是同一套结构化 schema，通常包括：

- `success`
- `score`
- `strengths`
- `weaknesses`
- `needs_retry`
- `improvement_suggestions`
- `confidence`

更准确地说，它看到的已经不是原始 `generated_content`，而是 Critic 已经做出来的一份评估结果摘要：

- `overall_score`
- `dimension_scores`
- `approval_status`
- 少量上下文，如 `platform / goal_metric / num_dimensions`

当前它的作用是：

- 检查评估报告本身够不够全面
- 如果觉得评估不够稳，就补充：
  - `critical_issues`
  - `improvement_suggestions`

但当前它**不会触发整份 Critic 评估 retry**。

所以它更像：

- 评估报告的 QA
- 不是整轮 Critic 的重跑开关

如果压成一句最短判断，就是：

**它也是 LLM 评估，但当前主要负责“补充 warning 和补充建议”，而不是控制整轮 Critic 重跑。**

#### 它和 Writer 的 `final_reflection()` 最关键的区别是什么

这两个名字很容易混，但它们解决的不是同一个层级的问题：

- Writer 的 `final_reflection()`
  - 评最终 `GeneratedContent`
  - 决定 Writer 节点内部要不要再来一轮 attempt
- Critic 的 `overall_reflection()`
  - 评 Critic 自己已经写出来的评估报告
  - 当前不会让 Critic 整轮重评

所以最准确的区分是：

- 前者更像：
  - 内容生成侧的整轮放行门
- 后者更像：
  - 评估报告侧的总体验收补丁层

这也是为什么它们虽然都叫 reflection，但在控制流里的权重并不一样。

这里再补一句最关键的控制流区别：

- `Writer.final_reflection()`
  - 真的会参与 Writer 节点内部“要不要下一轮 attempt”的判断
- `Critic.overall_reflection()`
  - 当前不会让整个 `content_evaluation` 节点重跑
  - 只是把 Critic 自己的评估报告再补稳一点

### 11.10 节点 10：`assemble CriticEvaluation`

节点 6、7、8 本质上都在为 `CriticEvaluation` 准备属性；节点 10 才是正式把这些中间结果收口成完整的 `CriticEvaluation`。

可以直接按属性看来源：

- `dimension_scores`
  - 来自节点 4
- `overall_score`
  - 来自节点 6
- `approval_status`
  - 来自节点 7
- `summary`
  - 来自节点 8
- `critical_issues`
  - 主要来自节点 8，也可能被节点 9 追加
- `highlights`
  - 来自节点 8
- `improvement_suggestions`
  - 主要来自节点 8，也可能被节点 9 追加
- `evaluation_time_ms`
  - 来自 `execute()` 里的代码计时
- `model_version`
  - 来自收口阶段附带的版本信息

这些属性的作用分别是：

- `dimension_scores`
  - 保留分维评分明细
- `overall_score`
  - 作为总质量指标
- `approval_status`
  - 作为流程控制结论
- `summary`
  - 给人看整体概览
- `critical_issues`
  - 告诉系统下一轮最该先修什么
- `highlights`
  - 告诉下一轮哪些亮点要保留
- `improvement_suggestions`
  - 是下一轮 Writer 最直接可消费的反馈来源
- `evaluation_time_ms`
  - 用于 tracing / 性能观察
- `model_version`
  - 用于实验和排障

所以这一段如果压成一句最短的话，就是：

**节点 4 产原始分维评分，节点 6/7/8 把它们加工成总分、审批和建议，节点 9 做整体补充，节点 10 再正式收口成一份完整的 `CriticEvaluation`。**

#### 为什么说 `CriticEvaluation` 更像“正式验收报告”

如果把 Writer 侧的 `GeneratedContent` 看成“内容成品”，那 `CriticEvaluation` 最贴切的定位就是：

**一份结构化的正式验收报告。**

因为它里面同时包含了三层不同性质的信息：

- 分维结果
  - `dimension_scores`
- 总体结论
  - `overall_score`
  - `approval_status`
- 可行动反馈
  - `critical_issues`
  - `highlights`
  - `improvement_suggestions`

这也解释了为什么节点 6、7、8 看起来像零散小函数，却都很重要：

- 节点 6
  - 把分维结果压成总体质量信号
- 节点 7
  - 把质量信号翻译成流程判决
- 节点 8
  - 把判决和评分翻译成下一轮可消费的反馈文本

最后节点 10 再把这些中间属性正式装进同一个对象里，让 workflow 后面可以：

- 继续 refine
- 更新 best result
- 记录 trace
- 做即时 reward

所以从工程角度说：

- `CriticEvaluation`
  - 不是“多几个字段的字典”
- 它更像：
  - 把本轮内容验收结果正式制度化的一份结构化报告

### 11.11 这里还有一个即时 RL 更新

`content_evaluation` 结束后，系统通常会拿当前 Critic 结果先做一次即时 reward 更新。

它的意义是：

- 先用 Critic 的 `overall_score` 给 bandit 一个在线反馈
- 但这还不是最终真实世界 reward

真正更重要的 delayed reward，要到后面的 `Trace -> Outcome -> delayed reward` 异步链路里才会回来。

#### 这里的“即时 reward”到底在用什么

当前这一步最核心的输入其实是：

- 当前轮 `evaluation.overall_score`
- 当前轮 `policy_id / selected_action`
- 当前轮上下文对应的 bandit state

也就是说，它本质上是在做：

**用 Critic 给出的在线质量分，先更新一轮策略偏好。**

这一步的优点是：

- 快
- 在线
- 不用等真实发布结果回来

但它的局限也很明显：

- 它仍然是 workflow 内部质量信号
- 不是现实世界表现

所以更准确地说，它只是：

- online proxy reward

不是：

- final business reward

#### 为什么说这里“workflow 已经结束得差不多了”，但“业务闭环还没真的结束”

到这一步时，一次 LangGraph 主链 workflow 基本已经跑完了：

- 生成内容
- 做 Critic 评估
- 如有需要进入 refinement
- 最后得出当前这轮最好结果

但更大的业务闭环还没结束，因为这时系统仍然不知道：

- 真正有没有人看
- 有没有点赞、评论、收藏、分享
- 真实 engagement 到底怎么样

所以：

- `11.11` 这里的即时更新
  - 仍然只是 workflow 内部的即时反馈
- 真正更可信的 delayed reward
  - 要等后面的：
    - `Trace`
    - `Outcome`
    - `delayed reward`
    这条异步链路再回灌

这也是为什么这里最准确的说法不是“策略学习已经完成”，而是：

**workflow 运行层基本结束了，但业务反馈层还没结束。**

#### 这里通常还会顺手留下监控/trace 记录

虽然这一层不是异步 delayed reward，但它已经会开始为后面的后半段闭环留痕，例如：

- 当前这轮的 `policy_id`
- 当前的 `overall_score`
- 当前执行的阶段耗时
- 是否发生了 `policy_update`

这些信息后面会一起进入：

- workflow trace
- policy update stage
- delayed reward 对齐

所以这一步不只是“更新 bandit”，也在给后面的：

- `Trace`
- `Outcome`
- `Reward`

那条异步链路准备对齐材料。

这里还可以再补一句边界判断，避免把它和 `content_evaluation` 节点本身混成一团：

- `content_evaluation`
  - 到 `CriticEvaluation` 收口为止，解决的是“这一轮内容到底过没过”
- 即时 RL 更新
  - 是在这份正式验收结果出来之后，顺手对策略层做一次在线副作用更新

所以它不是另一个评估节点，而更像：

- 评估完成后的策略侧 side effect
- 用当前轮质量信号，先快速拉一下 bandit 偏好

这也是为什么这一节要和后面的 `Trace -> Outcome -> delayed reward` 分开看：

- 当前这里
  - 还是 workflow 运行层的在线快速反馈
- 后面那条异步链路
  - 才是业务结果真正回灌学习层的后半程

### 11.12 `improvement_suggestions` 和 `feedback` 在 workflow 里怎么流转

最短链路可以记成：

`评估/反思 -> 产出 improvement_suggestions -> 塞进下一轮输入的 feedback -> 下一轮 prompt 生效`

#### 11.12.1 先分清两个概念

- `improvement_suggestions`
  - 是结构化输出对象里的正式字段
- `feedback`
  - 是运行时输入字段，最后通常会进下一次 prompt

更细一点说：

- `improvement_suggestions`
  - 更像“建议的产物”
- `feedback`
  - 更像“把这些建议喂回下一轮时使用的输入键”

所以它们不是同一个东西的两个名字，而是前后衔接的一对：

`评估结果里的建议 -> 下一轮执行时的反馈输入`

这里还可以再往前压一层：

- `improvement_suggestions`
  - 更像 schema 里的正式输出属性
  - 会出现在：
    - `Reflection`
    - `CriticEvaluation`
- `feedback`
  - 当前更像运行时输入字典里的一个键
  - 不像 `GeneratedContent` / `PlanStep` 那样是长期稳定建模好的核心字段

所以如果只用一句话区分就是：

- `improvement_suggestions`
  - 是正式结构化输出
- `feedback`
  - 是运行时回灌输入

再往定义层压一层，会更清楚：

- `improvement_suggestions`
  - 在 `Reflection` 里是正式字段
  - 在 `CriticEvaluation` 里也是正式字段
  - 所以它属于：
    - **被 schema 明确定义好的输出属性**
- `feedback`
  - 当前通常只是：
    - `input_data["feedback"]`
    - 或局部函数参数 `feedback: Optional[List[str]]`
  - 所以它更像：
    - **运行时传参字段**
  - 不是一个统一建模好的长期领域属性

这也是为什么如果从“对象建模”角度说：

- `improvement_suggestions`
  - 是正式对象属性
- `feedback`
  - 当前更像一次执行里的临时输入键

这里还可以把它们在“生成位置”和“生效位置”上再分清一层：

- `improvement_suggestions`
  - 常见生成位置有：
    - Writer 内部 `Reflection`
    - Critic 单维 `Reflection`
    - Critic 节点 8 的 `generate_improvement_suggestions()`
    - Critic 的 `overall_reflection()` 追加建议
- `feedback`
  - 常见生效位置有：
    - Writer step retry 的增强输入
    - Critic 单维重评时的 prompt 附加段
    - workflow 下一轮 `content_generation` 组装 `input_data` 时的 `feedback`

如果再按“节点”把生成位置彻底说清：

- Writer 节点内
  - step 级 `Reflector.reflect(...)`
  - `final_reflection()`
- Critic 节点内
  - 单维 `reflect(each dimension)`
  - 节点 8：`generate_improvement_suggestions()`
  - 节点 9：`overall_reflection()` 追加建议
- workflow 主链
  - 不直接“新生成”建议
  - 主要负责把已有建议从 `evaluation` 往下一轮输入桥接过去

#### 11.12.2 Writer 节点内怎么流转

最典型的路径是：

1. 某个 step 执行完
2. `Reflector.reflect(...)` 产出：
   - `improvement_suggestions`
3. 如果 `needs_retry = true`
4. Writer 调 `_retry_step_with_feedback(...)`
5. 这个函数会把：
   - `enhanced_input["feedback"] = improvement_suggestions`
   - `enhanced_input["previous_result"] = previous_result`
6. 再重跑当前 step

所以这条链本质上是：

`step reflect 的 improvement_suggestions -> Writer 局部 retry 的 feedback`

但当前 Writer 有个现实问题：

**字段流转已经打通，但主要生成 prompt 对 `feedback` 的消费还不够强。**

也就是说，Writer 这里当前更像：

- `feedback`
  - 已经能作为运行时输入字段一路传回去
- 但它还没有像 Critic 那样，被稳定、明确地写进每个关键生成 prompt

所以这条链在 Writer 侧更准确的判断是：

- 机制上已经打通
- 但 prompt 侧消费还没有完全闭合

如果再说得更直白一点：

- Writer 侧现在已经完成了：
  - 字段回传
  - retry 时增强输入
- Writer 侧还没完全完成：
  - 把这些 `feedback` 稳定、明确地渲染进关键生成 prompt

所以这条链在 Writer 内并不是“没做”，而是：

- **输入链路已到位**
- **prompt 消费闭环还不够强**

#### 11.12.3 Critic 节点内怎么流转

最典型的路径是：

1. `_evaluate_single_dimension()` 先产出一个 `DimensionScore`
2. `reflect(each dimension)` 再产出：
   - `improvement_suggestions`
3. 如果 `needs_retry = true`
4. Critic 会重跑 `_evaluate_single_dimension(...)`
5. 并把：
   - `feedback = reflection.improvement_suggestions`
   传进去
6. `_build_dimension_evaluation_prompt()` 会把这些 `feedback` 写进 prompt

这条链在 Critic 内部是明确生效的。

所以同样叫“retry with feedback”，两边成熟度其实不一样：

- Critic
  - `feedback -> prompt` 的闭环已经比较明确
- Writer
  - `feedback` 目前更多还是“字段先流转到位”

所以如果把两边并排看，最关键的差别是：

- Critic
  - 建议已经真正参与下一次评估文本
- Writer
  - 建议目前更多还停留在“输入字段传过去了”

#### 11.12.4 workflow 跨轮次怎么流转

最真实的链路是：

1. `content_evaluation` 节点执行 `CriticAgent.execute(...)`
2. `CriticEvaluation` 里已经有：
   - `improvement_suggestions`
3. workflow 写回：
   - `state["evaluation"] = evaluation`
4. `refinement`
   - 读取：
     - `evaluation.get("improvement_suggestions", [])`
     - `evaluation.get("critical_issues", [])`
   - 但本身只做桥接，不深加工
5. 下一轮回到 `content_generation`
6. workflow 组装下一轮 `input_data` 时：
   - `input_data["feedback"] = state["evaluation"].get("improvement_suggestions", [])`
7. 然后再调用 `WriterAgent.execute(input_data)`

所以当前主链更准确的真实路径是：

`CriticEvaluation.improvement_suggestions -> state["evaluation"] -> refinement(轻桥接) -> 下一轮 content_generation.input_data["feedback"] -> Writer`

而不是：

`state["evaluation"] -> refinement 深加工成成熟 feedback_package -> Writer`

这也是为什么第 12 节里会把“feedback_package”单独定位成：

- refinement 最自然的增强方向
- 但当前还没有真正落地的能力层

换句话说，当前 workflow 主链已经有：

- `improvement_suggestions`
  - 从 Critic 正式流到下一轮 Writer 的桥

但还没有：

- 一层真正成熟的 `feedback_package`
  - 去重
  - 排序
  - 分类
  - `must_fix / preserve / can_defer`

#### 11.12.5 第一次执行和 retry 到底是不是两套逻辑

不是。

Writer 和 Critic 里，大体都是：

- 第一次执行
  - 原始输入
- retry
  - 同一个执行函数
  - 但补上 `feedback`，有时还有 `previous_result`

所以真正的区别不在函数，而在增强输入。

如果把这句再压得更明确一点：

- 第一次执行
  - 原始输入
- retry
  - 同一个执行函数
  - 但会额外带上：
    - `feedback`
    - 有时还有 `previous_result`

所以 retry 不是换了一套新的执行器，而是：

**给同一个执行器补一层“上次哪里不满意”的上下文。**

如果再把“增强输入”这层写得更具体一点，当前 Writer 的真实路径更接近：

1. 第一次执行：
   - `execute()` -> `_execute_step(step, input_data, step_results)`
2. 如果 `reflect(step)` 判断需要重试：
   - 进入 `_retry_step_with_feedback(...)`
3. `_retry_step_with_feedback(...)` 会先基于原输入做一份增强版：
   - `enhanced_input = input_data.copy()`
   - `enhanced_input["feedback"] = improvement_suggestions`
   - `enhanced_input["previous_result"] = previous_result`
4. 然后再回到：
   - `_execute_step(step, enhanced_input, {})`

所以 Writer 里的 retry 不是：

- 换了一个新 step
- 换了一个新执行器

而是：

- **在原始输入上复制出一份增强输入**
- **再让同一个 step 执行器重跑一次**

这也就是为什么更准确的说法应该是：

- 第一次执行
  - 原始输入 + 原始上下文
- retry
  - 原始输入 + 改进建议 + 上次结果

Critic 里的做法更轻一些，但本质一样：

- 第一次执行：
  - `_evaluate_single_dimension(...)`
- retry：
  - 还是 `_evaluate_single_dimension(...)`
  - 只是把：
    - `feedback = reflection.improvement_suggestions`
    再传进去

所以两边真正变化的都不是“函数”，而是：

- **输入载荷被增强了**

这点在 Writer 和 Critic 两边都是成立的：

- Writer
  - 第一次执行：`_execute_step(...)`
  - retry：仍然回到 `_execute_step(...)`
  - 区别只是 `feedback / previous_result` 被补进增强输入
- Critic
  - 第一次执行：`_evaluate_single_dimension(...)`
  - retry：仍然调用 `_evaluate_single_dimension(...)`
  - 区别只是多传了 `feedback`

所以最准确的说法不是：

- “retry 走另一套逻辑”

而是：

- **retry 仍然走同一执行器，只是输入上下文被增强了**

#### 11.12.6 这些 `feedback` 最后是怎么进 prompt 的

这里也要分两边看：

##### 在 Critic 里

这条链已经比较明确：

- `feedback`
  - 会被 `_build_dimension_evaluation_prompt()` 渲染成“上次评估的改进建议”
- prompt 里会显式列出：
  - 每条 suggestion
  - 然后要求模型“考虑这些建议重新评估”

所以 Critic 里是很明确的：

- `improvement_suggestions -> feedback -> prompt 文本`

##### 在 Writer 里

当前更像：

- `feedback`
  - 会被塞进 `input_data`
- 但主要生成步骤里
  - 还没有非常稳定地把它拼成 prompt 中的一个正式反馈块

所以如果用户问“`feedback` 是对象属性，还是最后拼进 prompt 里”，更准确的回答应该是：

- 在 schema 层：
  - 它不是正式长期对象属性
- 在执行层：
  - 它更像运行时输入字段
- 在生效层：
  - 它最终的理想落点是 prompt 文本
  - Critic 已经更接近这个状态
  - Writer 还没完全闭合

#### 11.12.7 这一节最容易混淆的地方是什么

最容易混的有 3 个点：

##### 1. 不要把 `improvement_suggestions` 和 `feedback` 当成同一个字段

- 前者
  - 是建议输出
- 后者
  - 是建议被回灌后的输入键

##### 2. 不要以为 `refinement` 已经把建议整理成成熟反馈包

当前它没有。

当前主链更像：

- `CriticEvaluation.improvement_suggestions`
  - 直接穿过 `refinement`
  - 再进入下一轮 `input_data["feedback"]`

##### 3. 不要以为 Writer 和 Critic 的 feedback 闭环成熟度一样

它们不一样：

- Critic
  - `feedback -> prompt` 已经更清楚
- Writer
  - 目前更多还是“字段打通”

#### 11.12.8 一句话总收口

**`improvement_suggestions` 是评估/反思阶段产出的正式建议结果，`feedback` 是把这些建议重新喂回下一轮时使用的运行时输入字段；在 Critic 内部这条链已经较明确地进入 prompt 生效，在 Writer 侧则是输入链路已打通，但 prompt 消费还没有完全闭合。**

---

## 12. `refinement` 节点：一个很轻的“迭代桥接节点”

这个节点当前**不改内容**，也不是重型修改器。

它更准确的定位是：

**把上一轮 Critic 评估结果整理好，并把 workflow 推到“下一轮是否继续”的判断点。**

### 12.1 它现在实际做了什么

主要有三件事：

1. `state["iteration"] += 1`
2. 从 `state["evaluation"]` 里拿：
   - `improvement_suggestions`
   - `critical_issues`
3. 往 `state["messages"]` 里追加一条 refinement 记录

### 12.2 `iteration += 1` 不等于必须继续迭代

这表示：

**上一轮“生成 -> 评估”已经完整结束，workflow 进入下一轮判断点。**

但后面到底继续还是结束，不是这个节点自己决定，而是 `_should_refine()` 决定。

### 12.3 `state["messages"]` 里这条 refinement 记录长什么样

当前大致就是：

```json
{
  "role": "refinement",
  "content": "Iteration N complete, preparing for retry",
  "suggestions": [...],
  "issues": [...]
}
```

它的作用是：

- 记录这一轮结束时，系统准备往哪改
- 给 trace / 调试 / 可视化过程使用

### 12.4 这个节点现在到底有什么用

按当前代码，它最实际的作用其实很轻：

- 更新 `iteration`
- 追加一条 refinement 轨迹 message
- 在图结构上作为“评估完毕 -> 是否下一轮”的桥接点

它现在还不是一个重型“内容修改器”。

### 12.5 它现在没做、但理论上可以做什么

如果以后要增强，这个节点最自然的升级方向是：

- 把 `improvement_suggestions` 做去重、优先级排序、问题归类
- 把 `critical_issues` 和建议收口成更适合下一轮 Writer 消费的 `feedback_package`
- 做一层“哪些问题本轮必须修、哪些问题可以暂缓”的整理

#### 12.5.1 第一步：归一化分类

这一步不是只“分类”，而是在做：

**把 Critic 的自然语言问题，收口成规范化问题对象。**

##### 先分类

先判断一条问题属于哪个问题桶，比如：

- `hook`
- `body`
- `cta`
- `platform_fit`
- `seo`
- `geo`
- `blueprint`
- `clarity`
- `engagement`

##### 再归一化

再把不同说法统一成稳定问题名。

例如：

- “开头不够抓人”
- “首句吸引力不足”
- “hook 太弱”

都可以统一成：

- `开头吸引力不足`

##### 再落成标准结构

例如：

```json
{
  "category": "hook",              // 问题所属的大类
  "issue": "开头吸引力不足",        // 归一化后的统一问题名
  "source": "用户体验",             // 这条问题最初来自哪个评估维度
  "severity": "high"              // 严重程度，后面可用于排序和提炼 must_fix
}
```

这里的 `source` 最初可以先是单值；如果后面做去重合并，更适合升级成：

```json
"sources": ["用户体验", "内容质量"]
```

##### `severity` 怎么定

最稳的第一版是规则优先，而不是让 LLM 直接拍脑袋。

例如：

- 来自 `critical_issues`
  - 升高严重度
- 对应维度低分
  - 升高严重度
- 同一个问题被多个维度同时指出
  - 升高严重度

最后映射成：

- `high`
- `medium`
- `low`

##### 为什么不能只保留字符串列表

如果只保留字符串列表，后面就很难稳定做：

- 去重
- 排序
- 合并
- 提炼 `must_fix`
- 统计跨轮问题

##### 第一版最适合怎么实现

最推荐的顺序是：

- 代码先做规则识别、分类、结构化
- LLM 再做统一表述润色

也就是：

- **代码做整理**
- **LLM 做改写**

#### 12.5.2 第二步：做去重、优先级排序、问题归类

当前原始建议很容易重复，例如：

- 不同维度都在说“开头不够吸引人”
- 同一个问题被换几种自然语言说法

所以应该做：

- 合并重复问题
- 统计出现次数
- 结合 `severity` 排序

#### 12.5.3 第三步：收口成下一轮更好消费的 `feedback_package`

比起直接传一串字符串，下一轮 Writer 更适合吃结构化包，例如：

```json
{
  "feedback_package": {
    "must_fix": ["..."],
    "should_improve": ["..."],
    "preserve": ["..."]
  }
}
```

其中：

- `must_fix`
  - 本轮必须修
- `should_improve`
  - 本轮建议修
- `preserve`
  - 当前亮点，下一轮不要误伤

#### 12.5.4 第四步：拆出“本轮必须修”和“可以暂缓”

这是为了避免下一轮 Writer：

- 什么都想改
- 最后把已经好的部分也改坏

更稳的拆法是：

- `must_fix_now`
- `can_defer`
- `preserve`

#### 12.5.5 最推荐的实现顺序

最自然的一条增强链是：

```text
读取 evaluation
-> 抽取 raw issues / suggestions / highlights
-> 归一化分类
-> 去重合并
-> 严重度与优先级排序
-> 拆成 must_fix / should_improve / preserve
-> 组装 feedback_package
-> 写回 state["feedback_package"]
-> 下一轮 content_generation 消费
```

#### 12.5.6 当前这一层其实还没真正落地

这里一定要分清“未来可以怎么做”和“当前代码已经做了什么”。

当前真实发生的链路其实还是很直接：

1. `content_evaluation`
   - 产出 `state["evaluation"]`
   - 里面有：
     - `improvement_suggestions`
     - `critical_issues`
2. `refinement`
   - 只是：
     - `iteration += 1`
     - 把这些内容记进 `state["messages"]`
   - 没有真正做去重、排序、归类、打包
3. 下一轮 `content_generation`
   - 在组装 `input_data` 时
   - 直接从 `state["evaluation"]` 里取：
     - `improvement_suggestions`
   - 再塞到：
     - `input_data["feedback"]`

也就是说，当前真实链路更像：

`CriticEvaluation.improvement_suggestions -> state["evaluation"] -> 下一轮 content_generation.input_data["feedback"]`

而不是：

`state["evaluation"] -> refinement 深加工 -> feedback_package -> Writer`

所以 `feedback_package` 现在还不是现成事实，而是 refinement 最自然、也最值得的下一步增强方向。

---

## 13. `_should_refine()`：它不是节点，是主链的分流器

`_should_refine()` 不是业务节点，而是：

**在 `content_evaluation` 之后根据当前 state 决定下一条边往哪走的路由函数。**

### 13.1 它在主链里的位置

真实顺序是：

```text
content_generation
  -> _route_after_generation()
  -> content_evaluation
  -> _should_refine()
     -> refine / cover / end
```

### 13.2 它读哪些 state

主要读这些：

- `evaluation.overall_score`
- `quality_threshold`
- `iteration`
- `max_iterations`
- `mode`
- 是否启用封面生成

这些字段分别回答的是：

- `evaluation.overall_score`
  - 这轮质量到底达没达线
- `quality_threshold`
  - 系统要求的过线标准是多少
- `iteration / max_iterations`
  - 还能不能继续消耗下一轮机会
- `mode`
  - 这次 workflow 属于哪种执行模式
- 是否启用封面生成
  - 达到停止条件后，是直接结束还是转去封面节点

### 13.3 它返回什么

通常返回：

- `refine`
- `cover`
- `end`

也就是：

- 继续下一轮
- 转封面生成
- 直接结束

可以把它理解成一个三路分流器：

```text
如果达到质量阈值
  -> cover / end
如果已经打满最大轮次
  -> cover / end
否则
  -> refine
```

所以它最核心的判断其实就两条：

- 这轮够不够好
- 还有没有继续迭代的资格

### 13.4 它和节点内 retry 的区别

这是最容易混的地方。

- `Writer.final_reflection()`
  - 管 Writer 节点内部要不要再来一轮 attempt
- `Critic.overall_reflection()`
  - 管 Critic 评估报告本身要不要补 warning / 建议
- `_should_refine()`
  - 管整个 workflow 主链要不要继续下一轮

所以：

- 前两者是节点内控制
- `_should_refine()` 是 workflow 级分流

### 13.5 `writer_only` 为什么看起来也出现在这里

正常路径下：

- `writer_only`
  - 在 `content_generation` 后就直接 `end/cover`
  - 根本不会走到 `content_evaluation -> _should_refine() -> refinement`

所以 `_should_refine()` 里如果还有 `writer_only` 判断，更像是：

**防御性兜底分支。**

换句话说：

- `writer_only`
  - 正常路径下不会真的走到这里
- `_should_refine()` 里对 `writer_only` 的处理
  - 更像是“即使误入这里，也不要再进入 refinement”

### 13.6 为什么它很重要

因为它决定了：

- 质量阈值有没有被满足
- 最大轮次有没有被打满
- 主链此刻该继续还是结束

它是 workflow 这条闭环真正的“停机规则”。

---

## 14. `state`、中间结果和轨迹 `messages` 到底是什么

这一节专门把三个最容易混的东西拉开：

- `state`
- 中间结果
- `messages`

### 14.1 `state` 到底是什么

`state` 是这次 workflow run 的共享状态对象。

可以把它理解成：

**一次请求在 LangGraph 里的共享黑板。**

### 14.2 中间结果有什么用

中间结果是给后续节点继续“干活”用的正式业务状态，例如：

- `references`
- `selected_action`
- `generated_content`
- `evaluation`

它们的作用是：

- 被后续节点读取
- 驱动下一步业务逻辑

所以中间结果偏：

**业务消费。**

### 14.3 `messages` 有什么用

`messages` 更像一条运行轨迹 / trace。

它记录的是：

- 哪个节点执行了
- 做了什么
- 一句摘要
- 可选附带当时的数据快照

它的作用是：

- 调试
- 可视化
- 过程回看
- 解释为什么主链会走成现在这样

所以 `messages` 偏：

**过程记录。**

### 14.4 `state["evaluation"]` 和 `state["messages"]` 有什么区别

- `state["evaluation"]`
  - 是正式业务结果
- `state["messages"]`
  - 是过程日志快照

一个回答：

- “这轮评估结果是什么”

另一个回答：

- “这轮 workflow 过程中发生了什么”

### 14.5 Writer 节点内部 retry 会不会改 `state["evaluation"]`

不会。

因为 Writer 内部 retry 发生在 `WriterAgent.execute(...)` 内部，还没回到 workflow 外层。

它只会影响：

- 这轮 Writer 最终返回什么 `generated_content`

不会在节点内部直接改 workflow 的 `state["evaluation"]`。

### 14.6 workflow 下一轮会不会覆盖 `state["evaluation"]`

会。

下一轮 `content_evaluation` 跑完时，会用最新一轮结果覆盖：

- `state["evaluation"]`

同理：

- `state["generated_content"]`
  - 也会被当前轮最新结果覆盖

但：

- `state["final_content"]`
- `state["final_score"]`

是用来保留“到目前为止最好的一版”的。

### 14.7 `state["messages"]` 是覆盖还是增加

是增加。

各节点通常都会往末尾 append 一条新记录，不会直接清空覆盖旧消息。

### 14.8 一句话总结

最短可以记成：

- **中间结果**
  - 是给后续节点继续计算和决策用的正式业务状态
- **`messages`**
  - 是把“这一路怎么走过来的”记录下来用的运行轨迹

也就是：

- 前者驱动 workflow
- 后者解释 workflow

---

## 15. 三种模式的真实执行路径到底有什么差异

### 15.1 `full_pipeline`

完整路径：

`route_start -> trend_analysis -> director_sample -> content_generation -> content_evaluation -> refinement(optional)`

特点：

- 有 Trend
- 有显式 Director
- 有 Writer
- 有 Critic
- 有 refinement 循环

也就是说，这一模式最接近“完整业务闭环”的在线部分。

### 15.2 `writer_critic`

简化路径：

`route_start -> content_generation -> content_evaluation -> refinement(optional)`

特点：

- 没有显式 Trend 节点
- 没有显式 Director 节点
- 但仍然有 Writer + Critic
- 仍然可能进入 refinement

这里最容易忽略的一点是：

**即使跳过了显式 `director_sample`，`content_generation` 节点内部也可能兜底补一次 `selected_action`。**

所以它不是“完全没有策略”，而是：

- 没有独立 Director 节点
- 但生成时仍然会拿到策略

### 15.3 `writer_only`

最短路径：

`route_start -> content_generation -> end/cover`

特点：

- 只生成
- 不做正式 Critic 评估
- 不进入 refinement 循环

所以它适合：

- 追求最低延迟
- 只要先出一版内容
- 暂时不需要外层质量门控

### 15.4 三种模式最短对照

```text
full_pipeline:
  Trend -> Director -> Writer -> Critic -> Refinement(optional)

writer_critic:
  Writer -> Critic -> Refinement(optional)

writer_only:
  Writer -> end/cover
```

最重要的区别不是“有没有 Writer”，而是：

- 有没有 Trend / Director 的显式前置准备
- 有没有 Critic 的正式验收
- 有没有 refinement 的外层迭代

---

## 16. 一次 `full_pipeline` 请求里，state 是怎么一步步变化的

### 16.1 初始状态

`initial_state` 里会先有：

- `topic`
- `platform`
- `mode`
- `iteration = 0`
- `max_iterations`
- `messages = []`

更准确地说，这一步就已经把一轮 workflow 后面会共享的关键字段骨架准备好了。

### 16.2 跑完 `trend_analysis`

会新增或更新：

- `trend_analysis`
- `references`
- `messages` 追加 trend 记录

这一层的意义是：

- 先把 topic 变成领域上下文
- 顺手把检索/分析过程写进轨迹

### 16.3 跑完 `director_sample`

会新增：

- `selected_action`
- `policy_id`

这一步开始，state 里第一次有了“这轮内容到底打算怎么写”的策略字段。

### 16.4 跑完 `content_generation`

会新增：

- `generated_content`
- `messages` 追加 Writer 记录

并可能更新：

- `token_budget_remaining`

这一步之后，state 里第一次出现这轮生成的完整结构化内容本体。

### 16.5 跑完 `content_evaluation`

会新增：

- `evaluation = {overall_score, approval_status, improvement_suggestions, ...}`
- `messages` 追加 Critic 记录

如果当前是更好的结果，可能同步更新：

- `final_content`
- `final_score`

也就是说：

- `generated_content`
  - 记录当前这一轮最新生成结果
- `final_content`
  - 记录到目前为止最好的一版

### 16.6 如果进入 `refinement`

会更新：

- `iteration += 1`
- `messages` 追加 refinement 记录

然后下一轮 `content_generation` 会读取：

- `evaluation.improvement_suggestions`

并把它作为：

- `input_data["feedback"]`

再交给 Writer。

### 16.7 最终结束时

最终 API 返回，通常是从 final state 投影出来的：

- `final_content`
- `final_score`
- 必要时加 `messages` 或 summary 信息

所以如果把 state 演化压成一句话，就是：

**同一份共享 state 先后经历“上下文补齐 -> 策略写入 -> 内容写入 -> 评估写入 -> 可能迭代 -> 最终收口”的过程。**

---

## 17. workflow 完成后，为什么业务闭环还没有真的结束

到 `content_evaluation` 完成，甚至到 `final_content` 返回给 API 为止：

- 一次在线 workflow run 已经结束

但整条业务闭环还没结束。

原因是：

**这套系统不只要在线生成，还要等待内容真的发出去之后，把真实表现回灌给策略层。**

### 17.1 这条异步后半段到底是什么

最短链路是：

`workflow 结束 -> 保存 Trace -> 内容上线 -> 异步采集 Outcome -> 计算 delayed reward -> 回灌 RL / bandit`

也就是说：

- workflow 只负责在线前半段
- 真正的策略学习还要靠后半段异步闭环

### 17.2 第一步：先产生 Trace

Trace 是“这次生成过程的完整档案”。

它会记录：

- 这次是谁触发的
- 输入是什么
- 选了什么 `policy_id`
- Writer 产出了什么内容
- Critic 给了什么即时评分
- 各阶段耗时如何

它的作用是：

- 给后面 Outcome 对齐
- 给 delayed reward 回灌时找到“当初是谁生成的、用了什么策略”

#### 17.2.1 这里要分清两层：运行态 Trace 和持久化 Trace

这一点非常容易在阅读时混起来：

- LangGraph 运行时
  - 确实一直在维护一份共享 `state`
  - 里面有：
    - `messages`
    - `references`
    - `policy_id`
    - `selected_action`
    - `evaluation`
    - `final_content`
- 但 workflow 结束后真正持久化下来的
  - 并不是整份 `state` 原样落库
  - 而是 API 层把结果**投影**成一条可训练、可归因的 `GenerationTrace`

更准确地说，当前主链里的真实路径是：

`workflow.run(...) -> result -> log_generation_trace(...) -> generation_traces`

也就是说：

- LangGraph 内部真正编排的是共享 `state`
- 业务闭环后半段真正依赖的是持久化下来的 `GenerationTrace`

#### 17.2.2 当前主链里 Trace 是怎么持久化的

当前 `api_v5_langgraph.py` 在 workflow 成功结束后，会调用：

- `log_generation_trace(...)`

把这次生成结果写入：

- `generation_traces`

这条记录不是“完整 workflow 审计日志”，而更像：

- 训练样本
- Outcome 对齐锚点
- delayed reward 回灌锚点

#### 17.2.3 当前持久化 Trace 里大致会放什么

当前 `GenerationTrace` 里最重要的字段可以粗记成：

- 平台与主题
  - `platform`
  - `persona`
  - `niche`
  - `topic`
- 输入侧
  - `prompt`
  - `system_prompt`
  - `constraints`
  - `retrieved_context`
- 输出侧
  - `output`
  - `title`
  - `tags`
  - `cover_text`
  - `cta`
- 策略与模型
  - `policy_id`
  - `model_id`
  - `adapter_id`
- 元数据
  - `generation_time_ms`
  - `token_count`
  - `created_at`

这里最关键的不是把字段背下来，而是要记住：

- `trace_id`
  - 标识这一次具体生成
- `policy_id`
  - 标识这一次生成当时选了哪套策略
- `constraints`
  - 往往会顺便保留：
    - `user_id`
    - `request_id`
    - 配置快照
- `retrieved_context`
  - 往往会保留当时的 reference / RAG 上下文

#### 17.2.4 持久化到哪里

当前这条主链的持久化目标是：

- PostgreSQL 主库

它通过 `DATABASE_URL` 建同步 SQLAlchemy engine，把 `GenerationTrace` 写到：

- `generation_traces`

所以这里不是：

- 只在内存里留一个 `MemorySaver`

而是：

- workflow 内部有内存级 checkpoint
- workflow 外部另有一条真正持久化到数据库的 Trace 记录

#### 17.2.5 还有一套通用 tracer，但不是这条主链的主持久化路径

项目里还能看到：

- `core/tracer.py`

它会把阶段数据组装成 JSON 结构保存下来，更像通用阶段追踪器。

但对当前 `api_v5_langgraph.py` 这条主链来说，更直接、更真实的主持久化路径仍然是：

- `log_generation_trace(...)`
  - 写 `GenerationTrace`

所以如果你在看“闭环后半段到底怎么接 Outcome / reward”，优先盯的是：

- `generation_traces`
- `outcomes`
- `outcome_reward_bridge`

### 17.3 第二步：workflow 结束，但业务没结束

到在线生成结束时，你只知道：

- 这篇内容长什么样
- Critic 觉得它看起来怎么样

但你还不知道：

- 真实曝光
- 真实点击
- 真实互动
- 真实转化

所以此时只是：

- workflow 完成了

还不是：

- 业务闭环完成了

### 17.4 第三步：内容发布后异步采集 `Outcome`

Trace 存完以后，workflow 本身就已经结束了。后面系统会等待真实业务数据回来。

当前项目里有专门的定时任务做这件事，见：

- [outcome_sync_tasks.py](D:/Agent/Harness-Engineering/Agentic_Content_Optimizer/backend/app/tasks/outcome_sync_tasks.py)

这里有两类任务：

#### `auto_scrape_outcomes_task()`

作用是：

- 每 6 小时扫描最近 7 天内已发布、但还没有 `24h` outcome 的内容
- 根据 `generation_traces.platform_post_url` 去抓真实互动数据
- 把结果写回 `outcomes`

也就是说：

- Outcome 不是 workflow 当场算出来的
- 而是内容发布后，过一段时间再异步采集回来的

#### `sync_outcomes_to_rl_task()`

作用是：

- 每 6 小时把已经拿到的 Outcome 批量同步到 RL 策略层

这一步不是采集数据，而是：

- **把已存在的 Outcome 转成 delayed reward**

#### 17.4.1 `trace_id` 返回给谁，为什么要返回

workflow 结束后，API 会把 `trace_id` 返回给前端 / 调用方。

这里最容易误解的是：

- 返回 `trace_id`
  - 不等于“必须由前端亲自采集 Outcome”

它真正的含义是：

- 给后面的真实效果数据一个对齐锚点

也就是说，谁后面拿到了真实业务指标，谁都可以带着这个 `trace_id` 回来对齐：

- 前端手动回填
- 后端自动采集
- 其他服务 / 平台 API 回填

#### 17.4.2 当前项目里实际存在 3 条 Outcome 回填路径

可以把它们记成三条支线：

##### 路径 A：前端 / 运营手动回填

最直接的路径是：

- 前端拿到 `trace_id`
- 内容发布后拿到真实指标
- 调 `/api/v1/outcomes/upsert`

这条路更像：

- 人工闭环
- 调试闭环
- 运营手工录入真实结果

##### 路径 B：后端定时任务自动采集

当前项目里已经有这条自动链：

- `auto_scrape_outcomes_task()`

它会：

- 扫描最近 7 天内已发布、但还没有 `24h` outcome 的内容
- 根据 `generation_traces.platform_post_url` 找到帖子
- 调抓取器去拉真实互动数据
- 把结果写回 `outcomes`

这条更接近生产自动化。

##### 路径 C：其他后端服务 / 平台 API 回填

项目里还有：

- `log_user_feedback()`
- `log_platform_metrics()`

说明系统设计上也支持：

- 别的后端服务写回
- 平台 API 同步回来
- webhook / 数据管道补写回来

所以更准确的一句话是：

**`trace_id` 是闭环锚点，不是“只能前端使用的回填凭证”。**

#### 17.4.3 这三条路径不是同一个幂等语义

这点非常关键，因为它会直接影响你后面对 reward 口径的判断。

##### `/api/v1/outcomes/upsert`

这条主路径按：

- `(trace_id, time_bucket)`

做幂等 upsert。

也就是说：

- 同一个 `trace_id`
- 同一个 `time_bucket`

再提交一次时：

- 数据库里通常是覆盖更新
- 不是再新增一条

##### 自动抓取路径

自动抓取当前主要处理的是：

- `trace_id + 24h`

它也会优先查找已有 `24h` outcome，存在就更新，不存在才插入。

所以它和 `/api/v1/outcomes/upsert` 在 `24h` 这个桶上，本质也是覆盖关系。

##### 老的 `ml_feedback` 路径

这条老接口更像训练数据日志接口，当前实现更偏：

- 直接新增

而不是：

- 按 `(trace_id, time_bucket)` 做严格幂等 upsert

所以如果把三条路混在一起看，很容易误以为所有回填都是严格幂等的；其实并不是。

### 17.5 `Outcome` 里具体有什么字段

当前 `Outcome` 模型在 [schemas.py](D:/Agent/Harness-Engineering/Agentic_Content_Optimizer/backend/app/ml/training/schemas.py) 里定义，核心字段包括：

#### 曝光与点击

- `impressions`
- `clicks`
- `click_rate`

#### 阅读质量

- `read_time_avg`
- `completion_rate`

#### 互动

- `likes`
- `comments`
- `saves`
- `shares`

#### 转化

- `follows`
- `dms`
- `purchases`

#### 综合指标

- `engagement_score`

#### 时间窗口

- `time_bucket`
  - `1h`
  - `6h`
  - `24h`
  - `7d`

#### RL 同步状态

- `rl_synced`
- `rl_synced_at`

这里最关键的是：

- `trace_id`

它把这条真实效果数据，和前面那次具体生成实例绑在一起。

### 17.6 `policy_id` 和 `trace_id` 分别扮演什么角色

这是整条异步闭环最关键的一对标识。

#### `policy_id`

表示：

- **这次生成采用的策略 ID**

在当前项目里，它通常像：

- `H01-B03-C02`

也就是：

- `hook`
- `body`
- `cta`

这一组策略组合的编码。

#### `trace_id`

表示：

- **这次具体生成实例的唯一标识**

它不是策略本身，而是：

- 这一次请求
- 这一次生成
- 这一次运行档案

所以：

- `policy_id`
  - 定位“这次用了什么打法”
- `trace_id`
  - 定位“这是哪一次具体生成”

### 17.7 `trace_id` 和 `policy_id` 怎么把前后两段串起来

整条链最关键的一步就是：

**系统先用 `trace_id` 找回那次具体生成，再从这次生成档案里取出 `policy_id`，最后把真实 Outcome 回灌给那套策略。**

可以压成这条链：

```text
workflow 前半段先选策略
  -> 得到 policy_id
  -> 生成内容
  -> 保存 Trace
  -> Trace 获得自己的 trace_id，并保存 policy_id
  -> 内容发布后，用 trace_id 回填真实 Outcome
  -> 系统再通过 trace_id 找回那条 Trace
  -> 从 Trace 里取出 policy_id
  -> 把真实 Outcome 转成 delayed reward
  -> 更新这套 policy 对应的策略统计
```

### 17.8 delayed reward 具体是怎么形成的

这一步的核心代码在：

- [outcome_reward_bridge.py](D:/Agent/Harness-Engineering/Agentic_Content_Optimizer/backend/app/ml/rl/outcome_reward_bridge.py)

函数入口是：

- `sync_outcome_to_rl(...)`
- `batch_sync_pending_outcomes(...)`

它的主流程大致是：

1. 根据 `trace_id` 找回对应 Trace
2. 从 Trace 里取出：
   - `policy_id`
   - `constraints.user_id`
   - `topic`
   - `platform`
   - `target_audience`
   - `content_style`
3. 把 `engagement_score` 压成 `[0,1]` 附近的 reward
4. 再乘以 `time_bucket` 权重
5. 把 reward 更新回：
   - Thompson Sampling
   - contextual bandit

当前代码里：

- `engagement_score`
  - 先经过 sigmoid 压缩
- `time_bucket`
  - 再乘不同权重

权重大致是：

- `1h` -> `0.3`
- `6h` -> `0.6`
- `24h` -> `1.0`
- `7d` -> `1.0`

这背后的意思是：

- 越晚拿到的真实数据，通常越可信
- 所以后期 Outcome 的 reward 权重更高

#### 17.8.1 但“更晚更可信”不等于“严格只结算一次”

这里最容易被一句“后期权重更高”带偏。

当前实现里更准确的说法是：

- `1h`
  - 比较早，权重较低
- `6h`
  - 比 `1h` 更可信
- `24h`
  - 当前被当作高可信窗口
- `7d`
  - 当前也被当作高可信窗口

所以现在并不是：

- 只认最后一个窗口

而更像：

- 不同窗口的数据都可能变成一笔 reward 更新事件

而且当前代码里：

- `24h = 1.0`
- `7d = 1.0`

所以它不是严格单调递增的“越晚越高”，而是：

- 早期窗口较轻
- 后期窗口较重
- `24h` 和 `7d` 目前同权

#### 17.8.2 同一个 `trace_id` 的多个 Outcome，最后会不会落到同一个 `policy_id`

会，而且这正是闭环设计的核心。

`Outcome` 自己只知道：

- `trace_id`
- `time_bucket`
- 曝光 / 互动 / 转化这些真实表现

真正做 RL 回灌时，系统会：

1. 用 `trace_id` 找回对应 `GenerationTrace`
2. 从这条 Trace 里取出：
   - `policy_id`
   - `user_id`
   - 上下文特征
3. 把这笔真实表现记到那套 `policy_id` 对应的动作统计上

所以可以把角色关系压成：

- `trace_id`
  - 定位“是哪一次具体生成”
- `policy_id`
  - 定位“那次生成用的是哪套策略”

最终 delayed reward 真正更新的是：

- `policy_id` 对应的 action 统计

#### 17.8.3 所以问题不在“同一个 policy_id 会累计”

Bandit 正常就应该这样学：

- `T1 -> P1`
- `T2 -> P1`
- `T3 -> P1`

不同 trace 只要用了同一个 `policy_id = P1`，最后都应该累计到 `P1` 上。

真正要警惕的问题是：

**同一个 `trace_id` 的多次观测，当前实现里也可能被当成多次独立 reward 事件追加到同一个 `policy_id` 上。**

也就是说：

- 对 `policy_id` 跨 trace 累计
  - 是对的
- 对同一个 trace 反复记完整 reward
  - 当前实现里很可能是不对的

#### 17.8.4 当前实现里为什么会出现“同一条 trace 被重复记账”的风险

最典型的几种情况是：

##### 情况 A：同一个 `trace_id + 同一个 time_bucket` 被重复回填

例如：

- 先回填一次 `T1 + 24h`
- 后来又修正一次 `T1 + 24h`

数据库层面：

- `/api/v1/outcomes/upsert`
  - 会覆盖同一条 Outcome 记录

但 RL 层面：

- 每次都会再次调用 `sync_outcome_to_rl(...)`

所以结果会变成：

- 数据库里看起来只有 1 条 `24h` Outcome
- 但 bandit 可能已经对同一个 `policy_id` 连续记了 2 次 reward

##### 情况 B：同一个 `trace_id` 同时拿到了 `24h` 和 `7d`

例如：

- `T1 + 24h`
- `T1 + 7d`

数据库层面：

- 这是两条不同 `time_bucket` 的 Outcome

RL 层面：

- 两条都会通过 `T1 -> policy_id`
  - 落到同一个 `policy_id`

这意味着当前实现更像：

- 一次 trace
  - 可能贡献多笔 reward 事件

而不是：

- 一次 trace
  - 最终只结算一次

##### 情况 C：自动抓取路径重复同步

自动抓取路径里，更新已有 `24h` 结果后，还可能把：

- `rl_synced`
  - 重新置回未同步状态

后面批处理任务又可能再跑一次同步。

这会进一步放大：

- 同一条 trace
- 同一个 bucket

被重复打到同一个 `policy_id` 上的风险。

#### 17.8.5 所以当前 delayed reward 的工程现实是什么

如果把这一段压成一句工程判断，会更准确：

**当前实现里，`Outcome` 表的部分路径已经接近幂等覆盖语义，但 `policy_id` 对应的 delayed reward 还没有完全做到 trace 级幂等收口。**

换句话说：

- 存储层
  - 某些路径已经是覆盖
- 策略层
  - 仍可能把同一 trace 的多次观测当成多次完整 reward 样本

#### 17.8.6 更合理的口径应该是什么

如果按更稳的策略学习语义去理解，一次内容发布通常更应该是：

- 一次 trace
  - 对应一次最终 credit settlement

而不是：

- 同一 trace 的多个观测窗口
  - 每个都当成完整独立样本

更稳的工程做法通常会是三种之一：

1. 只认一个最终窗口
   - 例如只认 `24h` 或只认 `7d`
2. 做增量结算
   - `7d` 只补 `24h -> 7d` 的增量
3. 对每个 `(trace_id, time_bucket)` 做真正的 reward 幂等
   - 重复修正时只打 delta，不重复打一整笔

所以学习这条链路时，要抓住一个核心判断：

**当前代码已经把 `trace_id -> policy_id -> reward` 这条归因链打通了，但 reward 的最终结算口径还没有完全收口。**

### 17.9 delayed reward 最后更新到哪里

当前 delayed reward 会继续更新两层策略器：

#### Thompson Sampling selector

对应：

- `load_selector(...)`
- `update_action(...)`

也就是：

- 更新某个 `policy_id` 对应动作的统计表现

#### contextual bandit

对应：

- `load_contextual_bandit(...)`
- `bandit.update(...)`
- `save_contextual_bandit(...)`

它会从 Trace 里恢复出一份 `ContextFeatures`，再把 delayed reward 更新进去。

所以 delayed reward 的意义不是“记账”，而是：

- **真的会改变未来策略选择**

### 17.10 为什么说这是一条异步链路

因为这整条链并不是一次请求里同步完成的，而是：

#### 第一次请求

- 生成内容
- Critic 即时评分
- 即时 RL 更新
- 保存 Trace

#### 之后某个时间

- 内容发布
- 自动采集 Outcome

#### 再之后某个时间

- 定时任务把 Outcome 同步到 RL
- 形成 delayed reward
- 更新策略层

所以它是：

- 跨时间
- 跨任务
- 跨请求

的后半段闭环。

### 17.11 当前项目里其实有两类 reward

为了避免和前面的即时 RL 更新混淆，这里最好把两类 reward 分开记。

#### 第一类：即时 reward

来源：

- `content_evaluation` 节点里的 Critic 自评

特点：

- 来得快
- 在一次 workflow run 内就能更新策略
- 但不一定代表真实业务效果

#### 第二类：延迟 reward

来源：

- 发布后真实 Outcome 的回灌

特点：

- 来得慢
- 是异步的
- 更接近真实业务效果
- 更适合做最终策略学习

不过这里还要补一个非常关键的现实：

- delayed reward 更可信
  - 不代表当前实现里已经天然“只结算一次”
- 当前更像：
  - 同一 trace 的多个观测窗口
  - 可能各自触发一次策略更新

所以：

- delayed reward 的业务方向是对的
- 但它的 trace 级幂等 / 结算口径，当前还没有完全收口

所以：

- 即时 reward 学到的是：
  - “看起来怎样”
- delayed reward 学到的是：
  - “现实里到底怎样”

### 17.12 为什么这后半段不是“可有可无的统计系统”

如果没有这后半段，前半段 workflow 仍然能跑：

- Trend
- Director
- Writer
- Critic
- Refinement

但它更像：

- **一次性内容生成流水线**

只有补上：

- `Trace`
- `Outcome`
- `delayed reward`

它才真正变成：

- **带策略学习能力的业务飞轮**

因为系统不再只是每次重新生成一篇内容，而是会慢慢学到：

- 哪些 `H-B-C` 更值得多用
- 哪些 topic / platform / audience 下更该选什么策略

### 17.13 这条后半段在工程上到底怎么实现

如果你对“内容发布后异步采集 Outcome”这件事还比较抽象，最适合先把它记成一个非常朴素的工程流水线：

```text
生成完成
  -> 保存 Trace（拿到 trace_id）
  -> 记录内容已发布（需要 post_url / published_at）
  -> 定时任务扫描待采集内容
  -> 抓取器按 URL 拉真实互动数据
  -> 写入 outcomes
  -> 再由另一条定时任务把 Outcome 同步成 delayed reward
  -> 更新 policy 对应的 bandit 统计
```

也就是说，它不是一段神秘的“AI 自己学会了”的逻辑，而更像：

- 一段标准异步数据管道
- 中间夹着一个平台数据采集器
- 最后再接 reward bridge

#### 17.13.1 调度层是怎么接起来的

当前项目里，这条链是通过 Celery beat 任务定时驱动的。

调度上最重要的不是“有两个任务”，而是这两个任务的顺序：

1. 先跑 `auto_scrape_outcomes`
2. 再跑 `sync_outcomes_to_rl`

当前默认是：

- 每 6 小时整点
  - `auto_scrape_outcomes`
- 每 6 小时的第 10 分钟
  - `sync_outcomes_to_rl`

这背后的工程含义是：

- 先尽量把新的 Outcome 拉回来
- 再批量把已经落表的数据同步到策略层

所以这不是一条“实时 webhook”链，而是：

- **批处理 + 定时同步**

#### 17.13.2 定时任务如何挑出“该采集哪些内容”

`auto_scrape_outcomes_task()` 当前不是全库乱扫，而是有一层比较明确的筛选：

- 只看 `generation_traces`
- 要求：
  - `platform_post_url` 非空
  - `published_at` 非空
  - 发布时间在最近 7 天内
  - 还没有对应的 `24h` outcome

所以系统默认假设的是：

- 前半段生成结束后
  - 还需要有一段“发布记录”落回 Trace
- 后半段自动采集
  - 才知道去哪个帖子地址抓数据

这点非常关键，因为它说明：

- Outcome 自动采集的前提
  - 不是“模型写完文案”
- 而是“系统已经知道这篇内容后来真的发到了哪里”

#### 17.13.2.1 这里还要分清两类东西：平台运行数据 vs 平台接入配置

这一段非常容易在阅读时混掉，最典型的就是把：

- `platform_post_url`
- Creator API

都笼统理解成“平台配置”。

其实它们不是同一层。

##### 第一类：平台运行数据

这类数据回答的是：

- **这一次具体内容后来发到了哪里、什么时候发的**

典型包括：

- `platform_post_url`
- `published_at`

它们不是平台全局配置，而是：

- 某一条具体内容发布后产生的业务记录

没有这些数据，系统就不知道：

- 后面该去抓哪一条帖子
- 该从什么时候开始把它视为“可采集”

##### 第二类：平台接入配置

这类配置回答的是：

- **系统准备用什么方式接这个平台、从哪里拿数据**

典型包括：

- `XHS_CREATOR_API_BASE`
- `XHS_CREATOR_API_TOKEN`
- `XHS_CRAWL_ENABLED`
- `allowed_domains`
- selector 配置
- `storage_state` 路径

它们更像：

- 平台能力接入参数
- 爬取通道配置
- 安全与运维配置

##### 最短区分方式

可以直接这样记：

- `platform_post_url`
  - 是这条内容自己的定位信息
- Creator API / selector / storage_state
  - 是系统如何接平台拿数据的配置能力

所以后面如果你再看到：

- URL
- 发布时间

优先把它理解成：

- 运行时业务数据

而看到：

- API base
- token
- 域名白名单
- 抓取开关
- selector 配置

优先把它理解成：

- 平台接入配置

#### 17.13.2.2 “发布记录是怎么回写进 `generation_traces` 的”这件事要单独看

如果只从自动采集这条链倒推，它实际上依赖两个关键运行时字段：

- `platform_post_url`
- `published_at`

因为定时任务筛选待采集内容时，看的就是：

- 帖子 URL 是否存在
- 发布时间是否存在
- 发布时间是否落在最近一段窗口内

也就是说：

- 没有这两个字段
  - 自动采集链就无法成立

##### 从业务语义上，这两个字段应该怎么来

最合理的业务路径其实很朴素：

1. 前半段 workflow 先生成内容
2. 系统或人工把内容发到平台
3. 平台返回：
   - 帖子 ID
   - 帖子 URL
   - 发布时间
4. 系统再把这些发布结果回写到与这次生成对应的记录上
5. 后续自动采集任务就可以按这条发布记录去拉真实表现

所以从业务语义看，这一步本质上是：

- **发布系统把“内容已经发到哪了”这件事，补回给生成档案**

##### 当前仓库里更清晰可见的“发布结果回写”发生在哪里

从源码里更清晰能看到的是：

- `multi_platform_engine.py`

它在平台发布成功后，会把这些字段写回平台适配记录：

- `platform_post_id`
- `platform_url`
- `published_at`

这说明项目里确实存在一条明确的“发布完成 -> 写回发布结果”的业务动作。

换句话说：

- 发布链不是完全空白的
- 它至少在“平台适配 / 发布引擎”这一层已经有回写行为

##### 但当前主链的一个重要工程现实是：`GenerationTrace` 侧的统一回写入口并不清晰

这里一定要很诚实地记住一个现实：

- 自动采集任务查询的是：
  - `generation_traces.platform_post_url`
  - `generation_traces.published_at`
- 但当前 `ml/training/schemas.py` 里的 `GenerationTrace` 模型
  - 并没有显式定义这两个字段
- 我们在当前主链代码里
  - 也没有看到一条非常清晰、统一、直接的：
    - “发布成功 -> 回写 `GenerationTrace.platform_post_url/published_at`”
      的实现入口

这意味着什么？

这意味着你在理解这条自动采集链时，不能把它脑补成“代码已经完全收口”。

更准确的工程判断应该是：

- 自动采集链的业务依赖是清楚的
- 定时任务对 `generation_traces` 的字段假设也是清楚的
- 但“发布结果回写到 `GenerationTrace`”这一步，在当前仓库里还没有以同样清晰的方式完全暴露出来

##### 所以这一段最该怎么理解

最稳的理解方式不是：

- “当前代码已经把这一步 100% 完整打通”

而是：

- “这一步是自动采集链成立所必需的前提”
- “仓库里已经能看到发布引擎对平台适配记录的回写”
- “但 `GenerationTrace` 侧的统一回写口仍然需要单独核对或后续补齐”

##### 为什么这一点很值得专门记下来

因为如果不把这层说清楚，后面很容易产生两个误解：

##### 误解一：只要有抓取器，自动采集就一定能跑

其实不是。

自动采集要先回答：

- 去抓哪个 URL
- 从什么时候开始抓

如果发布记录没回写，这两个问题都答不上来。

##### 误解二：自动采集的问题主要是爬虫问题

其实也不是。

自动采集最前置的依赖往往反而是：

- 发布系统有没有把 URL 和发布时间写回来

所以从系统工程视角看，这一步更像：

- **发布链路和学习链路的连接点**

而不是：

- 纯粹的爬虫细节

##### 一句话收住这一小段

**“发布记录回写进 `generation_traces`”不是后半段的边角细节，而是自动采集 Outcome 能不能成立的前置条件；当前代码已经能看到发布结果回写到平台适配记录，但 `GenerationTrace` 侧的统一回写口仍需要作为一个单独的实现核对点来看。**

#### 17.13.2.3 如果以后要把这条链设计得更稳，主键关联最合理怎么分层

这一段非常值得单独抽象，因为它直接决定：

- 自动采集能不能稳定定位到正确帖子
- Outcome 会不会串错对象
- delayed reward 最终归因会不会混乱

最核心的判断可以先立住：

**不要把所有发布信息都继续硬塞进 `generation_traces` 一张表里，更稳的做法是把“生成”“适配”“发布”拆成三层。**

##### 第一层：`generation_traces`

这一层继续代表：

- **一次具体生成 run**

它的主键应该继续是：

- `trace_id`（当前表里对应 `GenerationTrace.id`）

它最适合承载的是：

- `policy_id`
- 输入 prompt / constraints
- 生成结果
- RAG 上下文
- 模型信息
- reward 归因源头

也就是说，这一层的职责是：

- **记录“这次生成本身是什么”**

而不是：

- 完整承载多平台发布生命周期

##### 第二层：`platform_adaptations`

这一层最适合代表：

- **这次生成在某个平台上的一个适配版本**

当前仓库里已经有：

- `adaptation_id`
- `content_id`
- `platform`
- `platform_post_id`
- `platform_url`
- `published_at`

如果以后要把它和 `GenerationTrace` 真正接稳，最值得补的是：

- `trace_id` 外键
  - 指向 `generation_traces.id`

这样语义就会很清楚：

- 一条 `GenerationTrace`
  - 可以对应多个平台适配版本
- 每个平台适配版本
  - 仍然保留自己的 `adaptation_id`

一句话说就是：

- `trace_id`
  - 解决“这版内容从哪次生成来的”
- `adaptation_id`
  - 解决“这是那次生成在某个平台上的哪个版本”

##### 第三层：`platform_publications`

如果想把后半段真正做稳，我会更推荐再单独抽一层：

- `platform_publications`

它代表的是：

- **某个平台版本的一次真实发布实例**

为什么还要再单独来一层？

因为现实里经常会出现：

- 同一条内容
  - 多平台发布
- 同一平台版本
  - 重发 / 补发 / 灰度发
- 同一篇内容
  - 不同账号发

这些情况如果都只挂在：

- `generation_traces`
  - 太粗
- `platform_adaptations`
  - 也不够细

所以更稳的结构是：

- `publication_id`
  - 作为发布实例主键
- `trace_id`
  - 外键，指回生成记录
- `adaptation_id`
  - 外键，指回平台适配版本
- `platform`
- `account_id`
- `platform_post_id`
- `platform_url`
- `published_at`
- `publish_status`
- `raw_publish_response`
- `attempt_no`

这层最核心的唯一约束通常应该是：

- `(platform, platform_post_id)` 唯一

这样系统就能明确知道：

- 到底是哪一次真实发布拿到了这个帖子 ID

##### `Outcome` 最终应该挂在哪一层

如果只从“能跑通”看，当前 `Outcome -> trace_id` 已经够用了。

但如果从“未来稳不稳”看，更推荐的是：

- `Outcome`
  - 优先挂 `publication_id`

更准确地说，未来更合理的方式通常是：

- `publication_id`
  - 作为 Outcome 的主归属
- `trace_id`
  - 作为冗余索引字段保留，便于 reward bridge 和查询

为什么？

因为 `Outcome` 真正回答的是：

- 某一条具体发布出去的帖子，后面表现如何

它天然更像：

- 发布实例的结果

而不是：

- 抽象生成记录本身的结果

##### 为什么不建议把 `platform_post_url / published_at` 只塞回 `generation_traces`

这是最值得讲清楚的设计判断。

如果把发布字段只放在 `generation_traces` 上，最容易遇到三个问题：

##### 问题一：一条生成可能对应多个平台

一条 `trace` 可能会去：

- 小红书
- 抖音
- B 站

如果 `generation_traces` 上只挂一组：

- `platform_post_url`
- `published_at`

语义天然就不够表达。

##### 问题二：同一平台可能不止一次发布

比如：

- 重发
- 补发
- A/B 试发
- 不同账号发

如果还是只写回同一条 `trace`，很快就会出现：

- 到底哪次发布对应哪次 Outcome
  - 变得不清楚

##### 问题三：Outcome 和 reward 最终更像发布结果，不像生成结果

生成只是：

- 这次做出了什么内容

但 Outcome 真正衡量的是：

- 这条内容后来在哪个平台、哪个账号、哪次发布里表现如何

所以从业务语义上，Outcome 更自然应该挂在：

- 发布实例

而不是只挂在：

- 生成实例

##### 我更推荐的最稳分层

如果把它压成最推荐的三层，会是：

1. `generation_traces`
   - 一次生成
2. `platform_adaptations`
   - 这次生成在某个平台上的一个版本
3. `platform_publications`
   - 这个版本的一次真实发布

然后：

- `outcomes`
  - 归到 `platform_publications`
- `reward bridge`
  - 再通过 `publication -> adaptation -> trace -> policy_id`
    找回策略归因

##### 如果不想一步改这么大，最低限度最值得先做什么

如果当前阶段不想一下子引入新表，最低限度最值得先做的是：

1. 给 `platform_adaptations` 增加 `trace_id` 外键
2. 把自动采集从依赖：
   - `generation_traces.platform_post_url`
   - `generation_traces.published_at`
   转成优先依赖：
   - `platform_adaptations.platform_url`
   - `platform_adaptations.published_at`
3. 等后面发布链更复杂时，再单独拆 `platform_publications`

这样做的原因很简单：

- 当前仓库里最清晰的发布结果回写
  - 本来就发生在 `PlatformAdaptation`
- 所以先让自动采集依赖一个“代码里已经更清楚存在”的对象
  - 会比继续假设 `GenerationTrace` 上已经完整承接发布字段更稳

##### 一句话收住这段设计建议

**未来最稳的主键关联方式不是“让 `generation_traces` 同时兼任生成记录、平台适配记录、发布记录”，而是用 `trace_id -> adaptation_id -> publication_id` 分层表达“生成”“平台版本”“真实发布”，再让 Outcome 优先归属于发布实例。**

#### 17.13.3 抓取器本身是怎么组织的

当前项目里抓取器最核心的实现是：

- `XHSOutcomeScraper`

而它不是一条单路径实现，而是：

- **Creator API 优先**
- **Playwright 降级兜底**

更准确地说：

##### 第一层：策略开关和安全边界

抓取器启动时会先检查：

- 是否启用了爬取开关
- 是否接受了平台抓取策略
- URL 是否在允许域名白名单里

也就是说，系统不是“看到 URL 就抓”，而是先做：

- 开关控制
- 域名白名单
- 平台范围约束

##### 第二层：Creator API 优先

如果配置了创作者 API：

- 优先调用 API 拉数据

这样做的好处是：

- 稳定性通常更高
- 不依赖页面结构
- 不太容易被前端改版打断

但如果：

- API 不可用
- token 缺失
- 请求失败
- 状态码异常

系统就会自动降级到：

- Playwright 抓取

##### 第三层：Playwright 降级

Playwright 路径会做这些事：

- 启浏览器
- 随机 user agent
- 使用移动端 viewport
- 如果有 `storage_state`
  - 就复用登录态 / 会话态
- 打开帖子页面
- 等待页面加载
- 抽取：
  - `likes`
  - `comments`
  - `saves`
  - `shares`
  - `impressions`

也就是说，Playwright 在这里更像：

- 自动化浏览器观测器

而不是：

- 传统只靠 HTTP 请求 + HTML 解析的静态爬虫

#### 17.13.4 指标提取为什么不是“写一个 CSS 选择器”那么简单

对不熟悉爬虫的人来说，最容易低估的就是这一点。

当前实现里，一个指标不是只靠一条规则抽取，而是三层回退：

1. 主选择器
2. 备用选择器
3. 文本模式回退

并且这些选择器不是硬编码死在代码里，而是：

- 从 JSON 配置加载

这背后的工程目的很明确：

- 页面一改版
  - 不一定要改 Python 代码
- 只要 selector 配置还可修
  - 抓取器就能继续活

所以这里真正重要的不是“会不会写 selector”，而是：

- **把 selector 变成可配置资产**

#### 17.13.5 为什么还要会话池、快照、告警这些看起来“很运维”的东西

因为抓取器最难的部分通常不是“第一次抓成功”，而是：

- 过一周后还能不能继续抓

当前实现里专门补了几件很工程化的东西：

##### `storage_state` 会话池

如果平台页面需要登录态，抓取器会尝试从 `storage_state` 目录挑一个会话文件来复用。

这相当于：

- 不让每次抓取都从头登录
- 允许维护一组持久会话

##### 失败快照

如果抓取异常，或者页面虽然打开了但所有指标都是 0，系统会保存：

- screenshot
- HTML
- meta 信息

这一步非常重要，因为它决定了你之后能不能排查：

- 是 selector 失效
- 是页面没加载出来
- 是登录态失效
- 还是平台侧改版了

##### 告警通知

当前实现还会在抓取失败或高失败率时告警。

这说明作者已经把它当成：

- 会坏
- 会漂移
- 需要运营维护

的生产能力，而不是一个一次性脚本。

#### 17.13.6 抓回来之后，怎么写回 Outcome

抓取器拿到平台指标后，不是直接就喂给 RL，而是先：

1. 按 `trace_id + time_bucket`
   - 查找或创建 `Outcome`
2. 写入：
   - `impressions`
   - `likes`
   - `comments`
   - `saves`
   - `shares`
   - 以及其他可用指标
3. 先算一个 `engagement_score`
4. 再由 reward bridge 转成 bandit 用的 reward

也就是说：

- 平台原始指标
  - 不直接等于 reward
- 它们先落进 Outcome
- Outcome 再通过 reward bridge 映射成可学习信号

#### 17.13.7 如果你不熟悉爬虫，这里最值得先抓住哪几个概念

如果只先抓住最核心的 5 个点，其实已经够用：

1. 爬虫不是一定指“requests + BeautifulSoup”
   - 这里主要靠的是 Playwright 浏览器自动化
2. 抓平台页面最容易坏的是页面结构和登录态
3. 所以 selector 配置、会话复用、失败快照比“抽一个字段”本身更重要
4. 自动采集的真正前提是系统已经知道：
   - `platform_post_url`
   - `published_at`
5. 抓回来之后不要直接当最终 reward
   - 还要先过 Outcome 和 reward bridge

#### 17.13.8 这条链做 Demo 难不难，做生产难不难

如果只问“能不能做出来一个跑通版”，其实不算特别难：

- 用 Playwright 打开页面
- 找几个指标
- 存表

一个可演示的闭环就已经出来了。

但如果问“能不能长期稳定跑在生产环境里”，难度就会明显抬高，而且难点大多不是 AI 难点，而是系统工程难点。

最典型的难点通常是：

##### 第一类：发布记录本身不完整

如果系统拿不到：

- `platform_post_url`
- `published_at`

那后面的自动采集根本无从谈起。

也就是说，真正的第一道门槛往往不是爬虫，而是：

- **发布链有没有把回写字段补齐**

##### 第二类：平台页面不稳定

平台页面会变：

- DOM 结构变
- class 名变
- 登录态变
- 数据展示方式变

所以“今天能抓”不代表“下周还能抓”。

##### 第三类：平台策略 / 合规风险

这类采集一定会碰到：

- 平台允许不允许
- 有没有 Creator API
- 需不需要显式接受抓取策略
- 是否需要限流、白名单、人工审核

所以它不只是技术问题，还有：

- 合规边界
- 运营策略

##### 第四类：奖励归因很容易失真

哪怕抓取本身没问题，后面仍然会遇到：

- 同一 trace 多个时间窗如何结算
- 重复修正是覆盖还是增量
- `24h` 和 `7d` 是否都记完整 reward

这部分如果不收口，就会出现：

- Outcome 看起来已经拿到了
- 但策略学习口径其实仍然不稳

##### 第五类：观测和排障成本很高

如果没有：

- 快照
- 告警
- 抓取来源标记
- 失败原因记录

那抓取器一坏，通常只能得到一句：

- “今天怎么又没数据了”

这也是为什么生产级实现里，运维性和可观测性几乎跟抓取逻辑本身一样重要。

#### 17.13.9 一句话评价这条后半段的工程价值

如果从工程投入产出来看，这条链很值钱，但也绝对不是“顺手写个脚本”那么轻。

更准确的判断是：

- 没有它
  - 系统更像一次性生成器
- 有了它
  - 系统才有机会形成真实业务飞轮

但它真正难的地方主要在：

- 发布记录打通
- 平台采集稳定性
- reward 结算口径
- 长期运维

所以如果以后你自己实现，最稳的心态不是：

- “我要先写一个很聪明的爬虫”

而是：

- **我要先把发布记录、采集通道、幂等结算、失败可观测性一起设计出来**

### 17.14 一句话总结这条后半段闭环

如果把这条异步链压成一句话，可以这样记：

**workflow 结束后，系统先保存一份包含 `policy_id` 的 Trace；等内容上线后的真实 Outcome 回来，再通过 `trace_id` 找回那次生成，从中取出 `policy_id`，把真实表现转成 delayed reward，最后更新回策略层。**

所以完整业务闭环其实分成两段：

#### 在线闭环

`Trend -> Director -> Writer -> Critic -> Refinement`

#### 延迟学习闭环

`Trace -> Outcome -> delayed reward -> 更新策略`

## 18. LangGraph 主链到底算不算 multi-agent，它的上下文与通信机制是什么

### 18.1 顶层当然算 multi-agent

从主链看，至少有这些角色：

- TrendAgent
- WriterAgent
- CriticAgent

它们通过 workflow 串起来，整体当然属于 multi-agent 风格系统。

如果只看 `create_workflow()` 这条主执行链，一次请求里真正被实例化出来的核心角色，主要就是这三类业务 Agent。

#### 如果只看主执行链，真实会实例化几个 Agent

最容易混的点是：

- 仓库里定义过很多 Agent 类
- 但一次 LangGraph 主链 run 并不会把它们全都真正拉起来

如果只看 `create_workflow()` 这条主执行链，当前一次请求里真正被实例化出来的核心 Agent，主要就是：

- `TrendAgent`
- `WriterAgent`
- `CriticAgent`

也就是说：

- **主链实际实例化 3 个核心 Agent**

#### 但从“业务角色”视角看，其实又像 4 个角色

如果不从代码实例化看，而从业务职责看，这条主链其实更像有 4 个角色：

- Trend
- Director
- Writer
- Critic

这里的关键点是：

- `Director`
  - 这个业务角色确实存在
  - 只是当前 v5 LangGraph 版本里，它不是通过独立 `DirectorAgent` 实例来承载
  - 而是直接内联在 workflow 里，例如：
    - `_select_action()`
    - `_director_node()`

所以最准确的说法不是：

- “这条主链只有 3 个业务角色”

而是：

- **主链实际实例化 3 个 Agent**
- **主链概念上有 4 个业务角色**

#### 为什么这层区分很重要

因为很多困惑都来自把下面三件事混成一个词：

- 仓库里定义过多少个 Agent 类
- 当前一次主链 run 实际实例化多少个 Agent
- 从业务视角当前这条链到底有多少个角色

这三件事并不总是相等。

### 18.2 但它不是“所有 Agent 平级对话”的那种 team/swarm

它更像：

- 一个 workflow coordinator
- 串起多个业务节点 Agent
- 通过共享 `state` 传递结果

所以它更接近：

- workflow orchestration

而不是：

- 平级 Agent 之间长对话协商
- team/swarm 式邮箱通信
- Anthropic 那种文件交接式 subagent 流程

#### 为什么它不像 `Team / Swarm`

如果把它和典型 `team/swarm` 对比，差异主要在这几件事：

- 当前主链没有多个平级 teammate 横向协商
- 没有共享任务板驱动的平级协作
- 没有“Agent A 发邮件给 Agent B，再彼此回信”这种对话式通信

它更像：

- 一个外层 workflow coordinator
- 顺序调用不同业务 Agent
- 每个 Agent 执行完后，把结构化结果写回共享 `state`

所以它不是：

- team/swarm 式对话系统

而更像：

- **workflow orchestration 驱动的业务闭环**

#### 为什么它也不像严格意义上的 `Subagent` 主链

严格 subagent 系统一般会更强调：

- 父 Agent dispatch 子 Agent
- 子 Agent 有独立上下文
- 子 Agent 做完后交摘要 / 文件 / handoff object 回来

而当前 LangGraph 主链更像：

- workflow node
  - 负责调某个主业务 Agent
- 主业务 Agent
  - 再在自己的节点内跑一条小流水线

所以如果你问：

- “它是不是多 Agent？”
  - 是
- “它是不是 subagent-first 的主链？”
  - 不是

它更准确地属于：

- **workflow 编排多个业务 Agent**

### 18.3 `WriterAgent` 和 `CriticAgent` 又是复合 Agent

例如 `WriterAgent`：

- 对外是一个 Agent
- 对内又有 Planner、生成步骤、Reflector、小型 orchestrator 结构

所以更准确地说，它不是单层 multi-agent，而是：

**主链多 Agent + 节点内部再分层的复合结构。**

同样地，`CriticAgent` 也不是一个“单 prompt 评一下就完”的薄 Agent，而是：

- 外层是一个 Critic 角色
- 内层又有 `create_evaluation_plan()`
- 有逐维评估
- 有单维 reflect
- 有 overall_reflection
- 最后再 assemble `CriticEvaluation`

所以：

- 主链层
  - 是多 Agent
- 节点内层
  - 又各自带了一条自己的小流水线

#### 也就是说，它不是单层 multi-agent，而是分层 multi-agent

如果压成最短的结构图，可以理解成：

```text
主工作流层
  TrendAgent
  WriterAgent
  CriticAgent

Writer 节点内层
  Planner
  业务生成步骤
  Reflector

Critic 节点内层
  create_evaluation_plan()
  evaluate_single_dimension() x N
  reflect(each dimension)
  overall_reflection()
```

所以更准确的判断是：

- 主链层
  - 是 workflow 式 multi-agent
- 节点内层
  - 又是 agent-like 的小流水线 / 小型 orchestrator

这也是为什么我前面一直强调：

- 它不是“所有东西都平级”的那种 multi-agent
- 而是“主链多 Agent + 节点内部再分层”的复合结构

### 18.4 `业务角色`、`节点`、`Agent` 三者怎么区分

这一节最容易混的，就是把三种不同抽象层混成一个词。

更稳的拆法是：

- `业务角色`
  - 从业务职责上看，谁负责什么
- `节点`
  - 从 workflow 图上看，当前 run 有哪些执行位置
- `Agent`
  - 从封装和执行单元上看，哪些东西是相对独立的能力对象

放到当前主链里，可以这样记：

- `Trend`
  - 是业务角色
  - 也是主链节点
  - 背后由 `TrendAgent` 承担
- `Writer`
  - 是业务角色
  - 也是主链节点
  - 背后由 `WriterAgent` 承担
- `Critic`
  - 是业务角色
  - 也是主链节点
  - 背后由 `CriticAgent` 承担
- `refinement`
  - 是节点
  - 但当前更像桥接逻辑，不太像独立业务 Agent

所以：

- 有些东西是业务角色，但不一定要独立封成 Agent
- 有些东西是节点，但只是 workflow 胶水，不一定值得 Agent 化

#### 为什么这三层一定要分开看

如果不把这三层拆开，最容易出现三种误解：

1. 把所有节点都误当成 Agent
   - 例如把 `refinement`、`_should_refine()` 也理解成主业务 Agent
2. 把所有业务角色都误以为当前都有独立类实例
   - 例如把 Director 当成当前主链里已经实例化的独立 `DirectorAgent`
3. 把节点内子模块误当成主链平级角色
   - 例如把 `Planner / Reflector` 直接和 `TrendAgent / WriterAgent / CriticAgent` 视为同一层

所以在这条 LangGraph 主链里，最稳的阅读顺序应该是：

- 先看业务角色
  - 这条闭环业务上需要谁
- 再看 workflow 节点
  - 这条图实际上怎么跑
- 最后看 Agent 封装
  - 哪些东西被做成了独立能力单元

### 18.5 为什么主链里有些是业务工作，却不是独立 Agent

判断一个环节值不值得独立成 Agent，最适合看三件事：

1. 它更像业务能力，还是 workflow 胶水 / 控制逻辑
2. 它值不值得被封成独立、可替换、可复用的执行单元
3. 它在当前实现里是不是已经被内联进 orchestrator

这也是为什么：

- `refinement`
  - 虽然有业务语义
  - 但当前仍更像轻量桥接节点
- `_should_refine()`
  - 更是纯路由函数
  - 不适合按业务 Agent 去理解

#### 仓库里不是还有更多 Agent 类吗，和主链是什么关系

如果你不只看 LangGraph 主链，而是看整个仓库里定义过的 Agent 类，数量会更多，例如：

- `DirectorAgent`
- `AdvancedAgent`
- `EnhancedAgent`
- `agents/swarm` 下的一组 Agent
  - `WriterAgent`
  - `MultiModalCriticAgent`
  - `EvolutionAgent`
  - `MetaPromptAgent`
  - `CrossPlatformTranslator`

但这些并不等于：

- 当前这条 LangGraph 主闭环都在用它们

更准确的理解是：

- 有些 Agent
  - 和主链业务语义很接近
  - 但只是另一种实现方式
- 有些 Agent
  - 属于更通用、更实验性的编排方向
  - 并不是当前 LangGraph 主链的核心组成部分

所以要始终分开：

- 仓库里定义过多少个 Agent 类
- 当前主链实际依赖多少个 Agent

### 18.6 它的上下文和通信机制是什么

顶层主链不是靠长对话历史互相传消息，而主要靠：

- `ContentGenerationState`

也就是：

**共享结构化业务状态。**

这和 Anthropic 式“文件交接 + 上下文隔离”的 subagent 风格不一样。

更准确地说，主链角色之间交换的是：

- `references`
- `selected_action`
- `generated_content`
- `evaluation`
- `final_content`

这些正式状态字段，而不是“上一位 Agent 说了什么自然语言消息”。

#### 更准确地说：主链是在做“shared state 范式”

如果要给当前 LangGraph 主链的上下文机制起一个最准的名字，我会叫它：

**shared state 范式**

它的关键特征是：

- 每个节点不继承一段无限增长的聊天历史
- 每个节点从共享 `state` 里取自己真正需要的字段
- 再把自己的结构化产物写回 `state`

所以主链里的“上下文”更像：

- 一份持续演化的业务状态对象

而不是：

- 多个 Agent 轮流在同一条自然语言消息历史上继续聊天

#### 这和 Anthropic 式“文件交接 / 上下文隔离”差在哪

Anthropic 那种更像：

- 子 Agent 独立上下文
- 通过文件或 handoff 文档交接

而当前 LangGraph 主链更像：

- 所有人都看同一份共享业务状态
- 真正的 handoff 发生在：
  - `state` 字段写入
  - workflow 条件边跳转

所以主链当前不是：

- “文件式 subagent handoff”

而是：

- **共享结构化状态驱动的节点协作**

#### 每个主业务 Agent 看到的上下文，其实是被重新组装过的

这也是一个很关键但很容易被忽略的点：

- `TrendAgent`
  - 看到的是 topic / platform 等前置输入
- `WriterAgent`
  - 看到的是 references / selected_action / geo_keywords / feedback 等重组后的最小必要输入
- `CriticAgent`
  - 看到的是 generated_content / references / platform / quality_threshold 等重组后的评估输入

也就是说，主链虽然共享一份 `state`，但并不是：

- 把整份 `state` 原封不动丢给每个 Agent

而更像：

- workflow node 先从共享 state 里挑字段
- 再组装成各自的 `input_data`

这也是为什么前面会一直提到：

- `ContentGenerationState`
  - 是共享业务底座
- `input_data`
  - 是节点级上下文重组结果

### 18.7 `messages` 是通信吗

不是主业务通信机制。

`messages` 更像：

- 运行轨迹
- 调试记录
- 过程快照

真正驱动节点协作的，是 `state` 里的正式业务字段。

所以最稳的理解是：

- `state`
  - 是主业务通信介质
- `messages`
  - 是可回看的过程轨迹

#### `messages` 更像什么

更准确地说，`messages` 更像：

- trace
- 调试日志
- 节点执行快照

例如主链里常见的写法都是：

- Trend 节点
  - 在 `state["messages"]` 里追加一条 trend 记录
- Writer 节点
  - 追加一条 “Content generated” 记录
- Critic 节点
  - 追加一条评估完成记录
- refinement 节点
  - 追加一条桥接记录

这些 message 的作用主要是：

- 回看这轮 run 发生过什么
- 给调试、trace、可视化展示留痕

它们不负责：

- 驱动主业务协作
- 成为后续节点的主要业务输入

所以不能把：

- `state["messages"]`

误当成：

- 主链里的真正 agent-to-agent 通信总线

#### 真正驱动协作的是哪些 state 字段

最关键的还是这些正式业务字段：

- `state["references"]`
- `state["selected_action"]`
- `state["generated_content"]`
- `state["evaluation"]`
- `state["final_content"]`

换句话说：

- `messages`
  - 解释 workflow
- 正式状态字段
  - 驱动 workflow

### 18.8 仓库里不是也有通信总线吗，为什么说主链不是靠它通信

仓库里确实能看到更一般化的 communication / message-bus 能力。

但如果只看当前这条 LangGraph 主链，真正把节点串起来的还是：

- `state`
- 条件边
- 节点执行后的 state 更新

所以当前主链的实际通信方式不是：

- 平级 Agent 互发消息
- 邮箱式协作
- message bus 驱动调度

而是：

**共享结构化业务状态 + workflow 条件路由。**

#### 这意味着什么

这意味着当前主链最值得学习的通信机制，不是：

- 如何设计 agent 邮箱
- 如何做 message bus fanout
- 如何做平级 agent 对话协议

而是：

- 如何把业务状态字段设计清楚
- 如何让节点输入输出契约稳定
- 如何用条件边把状态变化收口成受控业务闭环

所以如果你以后想把这条链迁到自研底座，最先该抽的是：

- state schema
- node input/output contract
- route function

而不是先去做一套“多 Agent 发消息”的通信总线。

### 18.9 最清楚的一张图：当前主链到底怎么通信

可以压成下面这张最短图：

```text
TrendAgent
  -> 写 state["references"] / trend_data / geo hints

WriterAgent
  -> 读 references + selected_action + geo_keywords
  -> 写 state["generated_content"]

CriticAgent
  -> 读 generated_content
  -> 写 state["evaluation"] / final_score / final_content

Refinement / _should_refine()
  -> 读 evaluation / iteration / thresholds
  -> 决定下一条边
```

也就是说：

- 真正被消费的是正式状态字段
- `messages` 只是一路附带记录过程

#### 再压成一句最短的人话

如果要把当前主链的通信方式压成最短一句话，就是：

**不是“Agent A 给 Agent B 发消息”，而是“节点 A 把结构化结果写进共享 state，节点 B 再从 state 里取自己需要的字段”。**

### 18.10 一句话收住这一节

**当前 ACO 主链当然算 multi-agent，但更准确地说，它是“workflow 编排多个业务 Agent + 节点内部再带小流水线”的分层式 multi-agent，而不是 team/swarm 式多 Agent 对话系统。**

---

## 19. ACO 的 Message 系统到底是什么，应不应该进 memory

这一节最容易误会的点是：

- ACO 里也有 `messages`
- 但它不是 Claude / Cursor 那种“聊天式消息历史”

更准确地说，当前主链里的 `state["messages"]` 更适合被理解成：

- trace
- 节点日志
- 过程快照

而不是：

- 跨会话长期记忆
- 用户画像
- 项目稳定偏好

也就是说：

- 它更像 run-time trace layer
- 不太像 long-term memory layer

### 19.1 当前这套 `messages` 到底是什么

最准确的说法是：

**它是 workflow 在运行过程中不断追加的节点执行快照。**

这些 message 不是标准 `HumanMessage / AIMessage / ToolMessage` 对象，而更像项目自定义的一串字典记录。  
每经过一个关键节点，系统通常都会往：

- `state["messages"]`

里 append 一条新的过程记录。

所以它更像：

- 运行轨迹
- 调试日志
- 节点摘要

而不是：

- 主业务数据本身

### 19.2 它现在会写入哪些内容

当前主链里常见的几类 message，大致是：

#### Trend 节点

会追加一条类似：

```json
{
  "role": "trend_agent",
  "content": "Found 5 references",
  "data": {
    "references": [...],
    "total_found": 5
  }
}
```

它表达的是：

- Trend 刚刚完成了检索
- 找到了多少 references
- 顺手把当时的返回结果挂在 `data` 里

#### Writer 节点

会追加一条类似：

```json
{
  "role": "writer_agent",
  "content": "Content generated",
  "iteration": 1,
  "data": {
    "text_structure": {...},
    "blueprint": {...},
    "geo_coverage": 0.83
  }
}
```

它表达的是：

- Writer 刚完成这一轮内容生成
- 这是第几轮 iteration
- 这轮生成的大致结果是什么

#### Critic 节点

会追加一条类似：

```json
{
  "role": "critic_agent",
  "content": "Evaluation complete: 8.3/10, Status: APPROVED",
  "data": {
    "overall_score": 8.3,
    "approval_status": "APPROVED",
    "critical_issues": [...],
    "improvement_suggestions": [...]
  }
}
```

它表达的是：

- Critic 刚完成这一轮正式验收
- 总分是多少
- 审批状态是什么

#### refinement 节点

会追加一条类似：

```json
{
  "role": "refinement",
  "content": "Iteration 1 complete, preparing for retry",
  "suggestions": [...],
  "issues": [...]
}
```

它表达的是：

- 这一轮已经结束
- 系统准备带着哪些问题和建议进入下一轮判断

### 19.3 它和正式业务状态有什么区别

这里一定要和第 14 节、18 节连起来看。

最核心的区别是：

- `state["generated_content"]`
- `state["evaluation"]`
- `state["final_content"]`

这些是：

- **正式业务状态**
- 后续节点真的会继续消费它们

而：

- `state["messages"]`

更像：

- **过程记录**
- 用来解释“刚才发生了什么”

也就是说：

- `state`
  - 驱动 workflow
- `messages`
  - 解释 workflow

这也是为什么：

- `state["evaluation"]`
  - 会被 `_should_refine()`、`refinement`、下一轮 `content_generation` 真正读取
- `state["messages"]`
  - 通常不会被后续业务节点当成核心输入反复消费

### 19.4 它算不算主链通信机制

不算主通信机制。

这条主链真正的通信方式，前一节已经讲过，是：

- 节点 A 把结构化结果写进共享 `state`
- 节点 B 再从 `state` 里拿自己需要的字段

所以：

- `messages`
  - 不是主链里的 agent-to-agent mailbox
- 它更像：
  - 旁路留痕
  - trace 快照

如果把它压成一句话：

**主链靠 `state` 协作，`messages` 只是一路附带记录。**

### 19.5 它为什么不该直接等同于 memory

因为 memory 要回答的问题是：

- 这个系统长期记住了什么
- 下次 run 还值得继续用什么
- 哪些信息跨请求、跨 session 仍然有价值

而 `messages` 当前回答的是：

- 这一轮 run 刚才发生了什么

这两者不是一个层级。

`messages` 里经常会包含：

- 临时字段
- 某一轮局部产物快照
- 只对本次调试有意义的摘要

这些信息大多：

- 时效很短
- 冗余很多
- 不适合原样长期沉淀

所以更准确地说：

- `messages`
  - 不该直接升格成 memory

### 19.6 如果以后做 memory，更合理的分层是什么

如果以后你做自研底座，更合理的分法是：

- `state`
  - 当前 run 的共享业务状态
- `messages`
  - 当前 run 的过程轨迹
- `trace`
  - 持久化保存的运行档案
- `memory`
  - 跨 run 的长期经验、用户偏好、规则与统计

也就是说，更合理的方向不是：

- `messages -> 直接塞进 memory`

而是：

- `messages -> trace / extractor -> 提炼后再进入 memory`

### 19.7 真正值得写进 memory 的，应该是什么

最值得长期沉淀的，不是原始 messages 本身，而是从它们和 trace/outcome 里提炼出来的稳定信息，例如：

- 用户长期风格偏好
- 平台规则记忆
- 高表现策略模式
- 失败模式总结
- GEO / SEO 有效表达模式
- 某类 topic 在某平台上的长期表现统计

这些东西有几个共同点：

- 跨 run 仍然有价值
- 比原始日志更稳定
- 更适合被下一次 run 重新利用

所以最稳的思路是：

- `messages`
  - 保留原始轨迹
- `memory`
  - 保留提炼后的长期知识

### 19.8 如果以后真要做 memory 写入，最自然的触发点在哪

按 ACO 这条链来想，最自然的时机通常不是“某个节点让模型直接写 memory 文件”，而是：

1. workflow 结束后
   - 基于 trace 和节点结果做一次提炼
2. outcome 回填后
   - 基于真实表现再更新长期模式记忆
3. human feedback 到来后
   - 再把人类确认过的偏好 / 规则沉淀进去

所以更合理的是：

- 节点先产出候选信号
- runtime / extractor 再决定是否写 memory

而不是：

- 让 LLM 在节点里直接把原始 message 写进 memory

### 19.9 这一节和 Session / Context 的边界怎么连起来看

如果再把这些概念一起放回你以后做底座时的分层，会更清楚：

- Session
  - 这是哪个用户、哪个会话、哪次 run
- State
  - 这次 workflow 当前推进到哪
- Messages
  - 这次 workflow 过程中发生了什么
- Context
  - 某个节点当前真正看到的最小必要输入
- Memory
  - 跨 run 仍然有价值的长期沉淀

所以最适合记的一句话是：

**Session 管容器，state 管推进，messages 管轨迹，context 管当前可见输入，memory 管跨 run 沉淀。**

### 19.10 一句话收住这一节

**ACO 当前的 `messages` 更像 run-time trace / 节点日志 / 过程快照，不应该直接等同于 memory；如果以后做 memory，应该从 messages 和 trace/outcome 里提炼长期有效信息，而不是把原始轨迹原样长期保存。**

---

## 20. 如果以后迁到自研底座，哪些节点适合 tool use，哪些不适合

这一节最重要的不是背下“哪个节点能调工具”，而是先把总判断立住：

**如果以后迁到自研底座，最稳的路线不是把 ACO 主链整体改造成开放式 tool orchestration，而是“外层 workflow 显式编排，内层节点有限 tool use”。**

也就是说：

- 主链
  - 仍然是受控业务闭环
- 局部节点
  - 可以给模型有限工具使用
- 真正决定流程走向的控制面
  - 尽量别交给模型自由发挥

### 20.1 为什么最适合“外层显式编排、内层有限 tool use”

这条主链本质上是：

- Trend
- Strategy / Director
- Writer
- Critic
- refinement
- Trace / Outcome / Reward

这样一条**高可归因、高可审计、高停机要求**的业务闭环。

这类链路最大的需求不是：

- 模型能不能自由探索很多工具

而是：

- 停机规则可控
- 策略归因不丢
- 评估阈值可控
- 失败时能恢复
- trace / reward 能回灌

所以如果一上来就把整条链改成开放式 tool orchestration，最容易丢掉的就是：

- 谁决定继续还是停
- 这轮为什么走了这条边
- 哪一步调用了哪个工具
- 哪条策略最终对应了哪次 outcome

这也是为什么我更推荐：

- 外层 workflow
  - 继续负责“闭环怎么跑”
- 内层节点
  - 在必要处开放有限 tool use

### 20.2 判断一个环节适不适合 tool use，最稳的标准是什么

最实用的判断标准可以压成 4 条：

1. 输入输出边界清不清楚
2. 这个能力是否相对稳定、可复用
3. 它是不是天然带外部 I/O / 查询 / 检索边界
4. 一旦放开，是否会破坏主链的控制性和可归因性

更适合 tool / skill 化的，通常具备：

- 输入输出契约清楚
- 能力可独立测试
- 很多时候天然带：
  - 检索
  - 查询
  - 文件
  - 异步任务

更不适合开放式 tool 化的，通常具备：

- 偏停机规则
- 偏路由控制
- 偏评分收口
- 偏最终 assemble

### 20.3 哪些部分更适合 tool / skill 化

这一类最适合优先考虑：

- Trend 检索与 reference 准备
- Critic 的评估 criteria / rubric 检索
- Writer 的 blueprint 生成子流程
- Critic 的五维并发评估
- Trace / Outcome / delayed reward 后半段异步任务

它们的共同特点是：

- 输入输出边界清楚
- 很多时候有明显外部 I/O
- 更容易独立测试和替换

#### `Trend` 为什么是最适合放一点 tool use 的节点

`Trend` 天然就和外部信息边界相连，例如：

- reference 检索
- hybrid retrieval
- query expansion
- context compression

所以它很适合有限 tool use，例如：

- 检索 reference
- 调平台规则库
- 查趋势知识源

但即便是 Trend，也更适合：

- 有白名单的有限工具

而不是：

- 完全开放的“模型随便搜、随便调一堆工具”

#### `Writer` 里哪些部分更适合有限工具化

`Writer` 也适合一点点 tool use，但要比 Trend 更谨慎。

更自然的候选通常是：

- 参考材料补充
- 规则库 / 样例库查询
- blueprint 相关的辅助生成子流程

这些部分的问题是：

- 信息有时不充分
- 但最终输出仍然能被收口成：
  - `TextStructure`
  - `Blueprint`
  - `GeneratedContent`

所以它们适合的是：

- **受限工具使用**

而不是：

- 让 Writer 在主链里变成完全开放式工具代理

#### `Critic` 为什么也适合少量工具化

`Critic` 的工具边界更偏：

- 规则查询
- rubric/checklist 装载
- 平台标准检索
- 硬指标读取

例如：

- 查平台规范
- 读 GEO / SEO 相关硬指标
- 读某一维对应的评估 criteria

所以它更像：

- 规则查询型 tool use

而不是：

- 自由探索型 tool use

#### Trace / Outcome / delayed reward 后半段为什么也适合 skill / tool 化

这一段虽然不适合交给模型自由决定，但从系统工程角度，它其实很适合被封成：

- 异步 skill
- 后台任务
- reward bridge tool

因为它天然带：

- 明确异步边界
- 明确输入输出
- 明确 trace_id / policy_id / outcome 对齐逻辑

也就是说，它不一定适合“开放给模型调用”，但很适合在底座里做成：

- 稳定可编排的能力单元

### 20.4 哪些部分更适合保留成代码函数

更适合保留成代码函数的，通常是：

- 路由函数
  - `_route_after_generation()`
  - `_should_refine()`
- `geo_coverage` 这类确定性计算
- 汇总与装配
  - `integrate_results()`
  - `assemble CriticEvaluation`

它们更像：

- 路由控制
- 确定性计算
- schema 收口

这类部分最大的问题不在“能力弱”，而在于：

- 一旦 agent 化，收益不大
- 反而会增加不确定性

所以它们不适合为了“看起来更 Agent”而强行 tool 化。

### 20.5 哪些部分明显不适合开放给模型做 tool use

最不适合开放式 tool 化的，通常是控制面和停机规则：

- `Director / policy sampling`
- `_route_after_generation()`
- `_should_refine()`
- `refinement`
- `Trace / Outcome / Reward` 的闭环控制

这些环节的问题不在“模型会不会调用”，而在：

- 它们控制主链往哪走
- 决定什么时候停
- 决定 reward 归因链能否成立
- 决定 workflow 是否还能稳定恢复和审计

#### 为什么 `refinement` 也不适合开放给模型自由 tool use

`refinement` 虽然有业务意义，但它更像：

- workflow 胶水
- 迭代桥接层
- feedback 整理层

它不是那种“信息不足，需要模型自己去外部探索”的节点。  
它更适合：

- 代码整理
- 规则归类
- 必要时少量 LLM 改写

而不是：

- 作为一个开放式工具代理到处查、到处调

#### 为什么 `Director / policy sampling` 更应该留在控制面

`Director / policy sampling` 决定的是：

- 这轮选什么 action
- exploration / exploitation 怎么权衡
- 后续 reward 要归因到哪条策略

这里一旦放开给模型自由调工具，最容易损伤的是：

- 策略可归因性
- bandit 更新稳定性
- 审计性

所以它更适合：

- 代码主导
- 明确 contract
- 明确 trace

### 20.6 `Writer` 更适合怎么 skill 化

更自然的方式是：

- 把整个 `WriterAgent.execute()` 抽成一个顶层 `writer_pipeline` skill

而不是把：

- `create_plan()`
- `reflect(stepX)`
- `integrate_results()`

都做成独立顶层 skill。

因为这些更像：

- skill 内部步骤

而不是：

- 对外完整能力单元

如果以后真做成 skill，更自然的形态是：

- 顶层一个 `writer_pipeline`
  - 接 `input_data`
  - 出 `GeneratedContent`
- 内部再由：
  - `SKILL.md`
  - `scripts/`
  - `references/`
  - `assets/`

共同支撑执行，而不是把每个 step 都暴露成顶层能力。

### 20.7 `Critic` 更适合怎么有限工具化

`Critic` 也适合有限 tool 化，但更自然的边界是：

- 对外一个 `critic_evaluation`
- 对内按维度读取：
  - rubric
  - checklist
  - platform criteria
  - 少量可计算指标

所以更好的方向不是：

- 让 Critic 成为自由工具代理

而是：

- 让 Critic 成为“评估节点 + 规则/标准/指标装载能力”的组合

#### 五维并发评估为什么也适合做成节点内工具编排

前面已经分析过，Critic 的五维评估从依赖关系上是天然可并行的。  
所以以后如果要提升吞吐，更自然的方式是：

- 外层 Critic 仍保持一个受控评估节点
- 内部把五维初评做成并发 worker / 受限工具调用

也就是说：

- Critic 外壳不一定要被拆散
- 但 Critic 内部完全可以引入有限并行工具编排

### 20.8 为什么当前 ACO 没把主链直接做成开放式 tool_calls

因为当前路线更像：

- 先把业务闭环跑稳
- 用代码和 schema 把边界收紧
- 再在局部节点内部做有限灵活性

如果一开始就把大量环节都改成开放式 tool_calls，会带来：

- 更高的不确定性
- 更高的 prompt / routing 成本
- 更复杂的错误恢复
- 更难做稳定监控
- 更难保证 reward / trace 的归因链不断

所以 ACO 的路线更像：

**先用代码把主链收紧，再在局部节点内部做有限 agent 化。**

### 20.9 如果以后迁到自研底座，最稳的最终形态是什么

更推荐的分层是：

#### 外层：显式 workflow 控制

外层负责：

- 主链顺序
- 停机规则
- 预算门控
- iteration / reward / trace 的控制

#### 中层：节点级有限 tool use / skill

中层负责：

- `Trend`
  - 有限检索 / reference 装载
- `Writer`
  - 以 `writer_pipeline` 暴露
- `Critic`
  - 以 `critic_evaluation` 暴露
- 必要时在节点内部调少量工具

#### 内层：节点自己的 schema 收口

内层负责：

- 结构化输出
- Pydantic / JSON Schema 校验
- 代码硬规则兜底
- 节点内 retry / reflection / assemble

这样会比“全开放 tool orchestration”更稳，因为：

- 外层控制不丢
- 中层能力边界清楚
- 内层输出仍有强收口

#### 如果放到你未来的混合架构里，这层最像什么

如果把它放回你前面规划的三层 loop，会更清楚：

- Tool loop / Skill loop
  - 可以承接顶层 `content_workflow` skill
- Workflow loop
  - 继续保留 Trend -> Strategy -> Writer -> Critic -> Refinement
- Node-local loop
  - 只在 Trend / Writer / Critic 节点内部开放受限工具使用

所以真正稳的组合不是：

- “主链完全 tool 化”

而是：

- **顶层 skill 承接业务入口**
- **中间 workflow 保持显式业务闭环**
- **底层节点局部有限 tool use**

### 20.10 一句话收住这一节

**如果迁到自研底座，最稳的路线不是把 ACO 主链整体改成开放式 tool orchestration，而是“外层 workflow 显式控制 + 中层节点级有限 tool use + 内层 schema 强收口”。**

---

## 21. 数据处理在项目里到底属于哪一层，它和 Agent 的边界是什么

这个问题非常值得单独拎出来，因为你后面如果自己做 harness，很容易把“Agent 在做的数据加工”和“系统底层的数据处理能力”混在一起。

这会直接影响你怎么拆模块、怎么做责任边界、以及怎么判断哪些东西应该写在 workflow 里，哪些东西应该写在 workflow 外。

### 21.1 先给一句话答案

在这个项目里，**“数据处理”不是一个单独的 Agent，也不是一个统一命名的通用模块；它更像是一组横跨采集、检索、结构化、训练、回灌的基础能力层。**

换句话说：

- Agent 当然会消费和产生数据
- 但“数据处理”本身并不等于 Agent
- 它更多是在 Agent 之前准备输入、在 Agent 之后收口输出、并把这些结果继续送往训练和学习链路

### 21.2 为什么你会觉得“很多地方都在做数据处理”

因为这个项目里的“数据处理”本来就不是只发生一次，而是散落在整条闭环的多个位置。

最少可以分成下面五类：

#### 21.2.1 采集与入库

这一层处理的是：

- 怎么拿到外部数据
- 怎么把原始数据转成内部可用的结构
- 怎么存到数据库或训练样本里

典型场景包括：

- 抓参考内容
- 抓发布后的真实互动数据
- 收用户反馈
- 把这些外部信号变成结构化记录

所以你前面一直在看的：

- `Trace -> Outcome -> delayed reward`

其实就已经是一条非常典型的数据处理链。

它不是在“生成内容”，而是在：

- 采集真实业务信号
- 做结构化存储
- 再把结果送回学习系统

#### 21.2.2 检索前后的预处理

这类数据处理离 Agent 更近，所以更容易被误以为“这是 Agent 自己的核心能力”。

例如 Trend 相关链路里会做：

- query/keyword 提取
- 向量检索或混合检索
- fallback 搜索
- reference 归一化
- 检索分数整理
- 参考内容的结构分析

这些动作虽然发生在 Agent 附近，但本质仍然是在做：

- 把原始上下文变成可消费的输入

也就是说，这里更像：

- “给 Agent 喂上下文的数据准备层”

而不是：

- “Agent 独有的智能决策层”

#### 21.2.3 结构化 contract / schema 收口

这部分是当前项目里最接近“通用模块”的地方。

因为很多关键对象并不是随便一段文本，而是尽量被收口成统一结构，比如：

- `Reference`
- `ContentBlueprint`
- `CriticEvaluation`
- `Policy`

这层的意义是：

- 约束输入输出长什么样
- 让 workflow 节点之间能稳定接力
- 让后续训练、日志、回灌能消费同一套结构

所以如果你问：

**“这个项目里最像数据处理通用层的是什么？”**

最接近的答案通常不是某个 Agent，而是：

- schema / contract 层

#### 21.2.4 训练数据构建与离线加工

这一层已经明显不是 workflow 节点内部逻辑了，而是更偏离线管道。

它处理的是：

- 怎么把 `GenerationTrace`
- 怎么把 `Outcome`
- 怎么把用户反馈
- 怎么把成品内容

重新加工成：

- SFT 样本
- DPO/偏好样本
- 训练集
- 评估集
- 日常数据工程产物

这类工作不是某个 Agent 的职责，而是系统的学习底座在做的事情。

#### 21.2.5 Outcome 到 reward 的转换

这也是非常关键的一类数据处理，而且很容易被忽略。

因为平台返回的原始指标不会直接拿给 bandit 或 RL 学习。

中间通常还要经过：

- engagement 指标整理
- score 计算
- 时间窗口加权
- `trace_id -> policy_id` 归因
- reward 映射

这一层的本质仍然是：

- 把业务观测数据转换成学习系统可消费的数据

所以它依然属于“数据处理”，只是位置已经在 workflow 的后半段了。

### 21.3 从分层上看，它更像哪一层

如果硬要给它找一个架构位置，我会更倾向于这样理解：

- `API / workflow / Agent` 是业务执行层
- `schema / contract / tracing / reward mapping` 是结构化与桥接层
- `data / ml pipeline` 是数据处理与学习支撑层

于是“数据处理”本身，更接近：

- workflow 之下
- 训练与反馈之上
- 横跨多条链路的基础设施层

也就是说，它不是一个点，而是一条横切能力带。

### 21.4 Agent 的职责更像什么

在这个项目里，Agent 更像是在做：

- 判断
- 规划
- 生成
- 评估
- 在受控状态机里推进业务步骤

例如：

- Trend 更像“准备上下文并形成趋势判断”
- Director 更像“做策略选择”
- Writer 更像“按约束生成内容”
- Critic 更像“把内容转成质量信号”

这些都更偏：

- 业务语义执行
- 决策与推理
- 受控生成与评估

### 21.5 数据处理的职责更像什么

数据处理更像是在做：

- 采集
- 清洗
- 映射
- 归一化
- 校验
- 结构化
- 入库
- 构建训练样本
- 把业务结果变成 reward

你会发现，它和 Agent 最大的不同在于：

- Agent 更像“做一件业务事”
- 数据处理更像“把数据变成下一层能接着用的形态”

所以它们不是互斥关系，而是上下游关系。

### 21.6 那它算不算 Agent 的通用模块

如果从“概念上”问，答案是：

- 算一种通用能力

因为无论是 Trend、Writer、Critic，还是后面的训练和 reward 回灌，都会依赖数据被整理成可消费结构。

但如果从“当前代码结构上”问，答案是：

- 不算一个被清晰抽出来的统一 Agent 模块

当前仓库里并没有一个像：

- `DataProcessorAgent`

这样的角色来统一承接这件事。

它目前更像分布在：

- `app/data`
- `app/engine/schemas`
- `app/engine/rag`
- `app/ml/training`
- `app/ml/rl`

这些目录和能力带里。

所以更准确地说：

**数据处理是整个系统的通用基础能力，但不是一个单独命名的通用 Agent。**

### 21.7 当前项目里，最接近“通用数据处理层”的其实是什么

如果一定要找“最像公共层”的部分，我会优先看两组东西：

#### 21.7.1 schema / contract 层

因为它定义了：

- 什么是 reference
- 什么是 blueprint
- 什么是 evaluation
- 什么是 policy
- 什么是 trace / outcome

也就是把很多原本松散的文本和业务概念，收口成可流转的数据结构。

#### 21.7.2 data / ml pipeline 层

因为它负责：

- 采集外部信号
- 加工成内部记录
- 构建训练数据
- 生成 reward
- 回灌学习系统

这一层不直接“扮演 Agent”，但它决定了 Agent 前后两端的数据质量。

### 21.8 如果以后迁到你自己的 harness，这块更适合怎么抽象

如果你以后自己做底座，我会更建议把它显式拆成下面几层，而不是把“数据处理”硬做成一个 Agent：

#### 21.8.1 `data_contracts`

负责：

- schema
- 字段语义
- ID 约定
- 校验
- 版本兼容

#### 21.8.2 `data_pipeline`

负责：

- 采集
- 清洗
- 归一化
- 映射
- 特征提取
- 数据集构建

#### 21.8.3 `workflow_agents`

负责：

- 趋势判断
- 策略选择
- 内容生成
- 内容评估

#### 21.8.4 `learning_bridge`

负责：

- trace
- outcome
- reward
- delayed feedback
- 训练回灌

这样拆的好处是：

- Agent 不用背太多底层数据职责
- 数据处理不必假装成 Agent
- reward / training / tracing 这些后半段能力也能有清晰归属

### 21.9 这一节最该记住的工程判断

如果把这一节压成一句话，我会这样说：

**在 Agentic_Content_Optimizer 里，“数据处理”不是一个独立 Agent，而是一层横跨采集、检索、结构化、训练、回灌的系统能力；Agent 是在消费和生产这些结构化数据，但不等于这层能力本身。**

## 22. 当前 LangGraph 主链里必须知道的几个真实问题

这一节不是挑刺，而是把当前实现里最值得记住的工程现实拉出来。

如果只想记最核心的一句，可以先记成：

**这条主链的整体业务骨架是清楚的，但若干字段契约、评分口径和职责边界还没有完全收口。**

### 22.1 Trend 关键词契约有错位

- `trend_analysis`
- `geo_keywords`
- `references`

这三者的链路没有完全对齐。

更具体地说：

- TrendAgent 更稳定产出的是：
  - `geo_constraints`
  - `references`
- workflow 更想写回的是：
  - `trend_analysis`
  - `references`
- Writer 后面真正消费的是：
  - `geo_keywords`

这导致简化模式下，Writer 很容易退化到：

- `geo_keywords = [topic]`

所以这里最值得记住的现实不是“Trend 没用”，而是：

**Trend 的业务意图是对的，但关键词字段链路当前没有完全收口。**

### 22.2 Planner / Reflector 和 Writer 主体的 LLM 接口风格并不统一

当前仓库里，至少有两条不同的结构化输出路径：

- Writer 主体
  - 更偏 `structured_output(...) + Pydantic`
- Planner / Reflector
  - 更偏 `UnifiedLLM.chat(..., response_format=json_schema)`

这说明什么？

说明项目在“结构化输出”这个方向上是有明确意识的，但当前实现还没有完全统一成一套抽象。

从工程角度看，这会带来两个后果：

- 可维护性变差
- 不同模块的稳定性和错误处理方式不一致

所以这里最值得学的不是“接口已经很完美”，而是：

**作者已经知道必须结构化，只是执行层还存在风格分裂。**

### 22.3 Critic 维度语义比输入上下文强

Critic 默认有五个很清楚的业务维度，但当前 `_evaluate_single_dimension()` 实际喂给 LLM 的上下文比较统一、比较薄。

结果是：

- 维度名分得很细
- 真实评估证据不够细

最典型的例子有：

- `视觉呈现`
  - 理论上应该更强地看 `blueprint`
  - 当前却主要还是看 `full_text`
- `SEO`
  - 理论上应该更直接消费 `geo_coverage / geo_keywords`
  - 当前更多还是基于文本做主观推断

所以这里最值得记住的现实是：

**Critic 的业务框架比实际输入喂法更成熟。**

### 22.4 Critic 的评分口径和 schema 还存在收口问题

这个问题非常关键，因为它会直接影响你对这条评估链的信任程度。

当前实际运行里，很多地方按：

- `0-10`

在讨论维度分数和 `overall_score`。

但部分 schema / 代码约束又带着：

- `0-1`

的味道。

这意味着：

- prompt 的口径
- parser 的口径
- schema 的口径
- decision 的口径

还没有完全一一对齐。

这一点不代表 Critic 不能用，但它明确提醒你：

**学习时要抓业务意图和流水线骨架，不能把当前分值契约当成完全收口的工业实现。**

### 22.5 DirectorAgent 文件虽然存在，但主链真正的策略采样并不在那里

这个点也很容易误导阅读者。

仓库里确实能看到：

- `DirectorAgent` 相关文件

但 LangGraph 主链真正起作用的策略采样，主要还是：

- workflow 内部 `_select_action()`
- `_director_node()`

也就是说：

- “Director” 这个角色是存在的
- 但主链里真正跑的实现，更接近 workflow 内联策略选择

所以如果你想学主链，真正要盯的是：

- `langgraph_workflow.py` 里的策略采样逻辑

而不是先被“文件名上存在的 DirectorAgent”带偏。

### 22.6 一些测试和旧命名空间不能当作最可靠入口

这也是看仓库时很容易踩的坑。

项目里有些测试、旧模块和旧命名空间还保留着历史痕迹，这会带来两个问题：

- 读起来像“好像也在用”
- 但实际主链已经不一定从那里走

所以如果要判断“这条 LangGraph 主链现在到底怎么跑”，优先级应该始终是：

1. API 入口
2. `langgraph_workflow.py`
3. 当前节点真实调用的 Agent / schema / provider
4. 最后才是测试和旧模块

### 22.7 这一节最该记住的工程判断

如果把这一整节压成一句工程判断，我会这样说：

**Agentic_Content_Optimizer 这条 LangGraph 主链非常值得学它的业务闭环骨架、状态设计和节点拆法，但不能把当前字段契约、评分口径和模块边界当成已经完全工业级收口的最终答案。**

## 23. 用一句话重新概括这条 LangGraph 业务闭环

最短的一句话版本是：

**这条 LangGraph 主链本质上是在一份共享 `state` 上，先做上下文准备，再做策略选择，再做内容生成与质量门控，最后把真实业务表现通过异步后半段回灌给策略学习层。**

### 23.1 如果换成业务语言

它做的其实是：

**把一个裸 `topic`，一步步变成一份可发布的结构化内容，并让这次内容的真实效果反过来影响下一次策略选择。**

### 23.2 如果换成工程语言

它做的其实是：

**在一个 workflow 状态机里，把 `Trend -> Strategy -> Writer -> Critic -> Refinement -> Trace/Outcome/Reward` 串成一条可学习、可追踪、可迭代的业务闭环。**

### 23.3 如果换成“你以后自己实现”的语言

它最值得被抽象成的，其实是：

**一个垂直领域 Workflow Agent：受控地生成、受控地评估、受控地迭代，而不是开放式聊天 Agent。**

## 24. 读完这份文档后，你应该已经能回答的问题

如果这份文档真的起作用了，读完后你应该已经能比较稳定地回答下面这些问题：

- 一次请求如何进入 LangGraph workflow
- `request -> execution_config -> runtime_config -> initial_state` 这四层各自在服务谁
- `state` 在这条主链里扮演什么角色
- `trend_analysis` / `references` / `geo_keywords` 分别是什么
- 为什么简化模式下 Writer 仍然可能补一次策略采样
- `policy_id` 和 `selected_action` 分别代表什么
- Writer 内部流水线到底怎么跑
- `Plan` 为什么更像内存中的步骤说明书，而不是 todo-list
- Writer 的步骤级 reflect 和 `final_reflection()` 到底分别在评什么
- Critic 的 `evaluation_plan` 在做什么
- 五个评估维度当前到底怎么评、为什么现在还不够稳
- 为什么 `reflect(each dimension)` 理论上有价值、但当前实现里容易显得重复
- `CriticEvaluation` 里每个字段从哪来、有什么用
- `improvement_suggestions` 和 `feedback` 在 workflow 里怎么流转
- `refinement` 当前为什么是一个轻桥接节点
- `_should_refine()` 为什么不是节点，而是主链停机规则
- `messages` 为什么更像过程轨迹，而不是聊天消息体系
- 这条主链到底算不算 multi-agent，它真正的通信机制是什么
- 为什么 LangGraph 版本更适合学业务闭环，而不适合直接当你项目的底座
- workflow 完成和业务闭环完成为什么不是一回事
- `Trace -> Outcome -> delayed reward` 这条异步后半段到底怎么走

如果这些问题你已经都能讲顺，那这份文档的主任务基本就完成了。

## 25. 接下来最适合继续深挖的方向

如果后面继续往下钻，最值得的方向通常是这几条：

### 25.1 继续把 Writer 的 prompt、schema、step retry 机制拆细

这是最值得优先深挖的一条，因为 Writer 是整条闭环里最像“垂直 Workflow Agent 核心工厂”的部分。

继续往下可以拆：

- `generate_text_structure()` 的 prompt 变量
- `generate_blueprint()` 两阶段为什么这样拆
- `feedback` 为什么现在字段已流转、但 prompt 消费还不够闭合

### 25.2 把 Critic 的五维评估做成更强的 rubric-based scoring

这是当前最直接的质量增强方向。

重点可以继续拆：

- 每维该补什么专属上下文
- 哪些子项应该变成 rubric / checklist
- 哪些信息应该先代码验证，再交给 LLM 打主观分

### 25.3 把 refinement 从“轻桥接节点”升级成真正的 `feedback_package` 生产器

这条线的意义是：

- 让 Critic 的建议不再只是字符串列表
- 让下一轮 Writer 真正吃到：
  - `must_fix`
  - `should_improve`
  - `preserve`

它很适合作为你以后自己做控制束底座时的一个亮点改造。

### 25.4 把 Writer / Critic 进一步映射成你自己的自研 harness 模块

这是最适合从“分析 ACO”走向“自己实现”的桥。

也就是继续回答：

- 哪些是底座该做的
- 哪些是业务 Workflow Agent 该做的
- 哪些是 state、trace、reward bridge 该承担的职责

### 25.5 把 tool / skill / workflow / subagent 的边界真正落成自己的设计

这条线最适合服务你后面的混合架构项目。

因为到这里，问题已经不再是：

- “ACO 怎么写的”

而是：

- “我到底要借它哪些能力边界，放进自己的 harness”

### 25.6 如果只选一条线继续深挖，优先级怎么排

如果只按“最值钱”来排，我会建议：

1. Writer
2. Critic
3. refinement / feedback_package
4. Trace -> Outcome -> delayed reward
5. tool / skill / workflow 边界

也就是先抓：

- 生成
- 评估
- 反馈

这三件最核心的闭环内核，再往后扩到底座。

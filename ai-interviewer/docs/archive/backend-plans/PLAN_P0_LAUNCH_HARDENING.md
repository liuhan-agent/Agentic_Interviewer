# P0 上线加固

> **状态**：实施中
> **范围**：配置口径显式化、生产启动校验、HITL 状态一致性验收、评分可信度观测

## 代码默认值 vs `.env.example` vs 生产 env

| 配置项 | 代码默认值 | 说明 |
|--------|-----------|------|
| `APP_ENV` | `dev` | 生产必须显式设为 `prod` |
| `CHECKPOINT_BACKEND` | `memory` | `memory` 不提供跨进程恢复；生产必须 `postgres` |
| `API_TOKEN` | `None` | 生产必须非空，否则 admin 端点裸奔 |
| `ALLOW_OPEN_ADMIN` | `false` | 生产必须 `false`；dev 调试可设为 `true` |
| `EVIDENCE_SPAN_ALIGNMENT` | `true` | 实际值以运行环境为准；不在 preflight 中强制 |
| `ENABLE_VERIFIER_DRIFT_MONITOR` | `false` | 按需启用，不影响核心功能 |
| `VERIFIER_ADAPTIVE_TRIGGER` | `false` | 依赖 drift monitor；按需启用 |
| `LLM_PROVIDER` | `openai` | 生产禁止 `stub` 或缺 key 导致的 stub mode |
| `EMBEDDING_PROVIDER` | `openai` | 生产默认禁止 `stub`；仅可显式 `ALLOW_STUB_EMBEDDINGS_IN_PROD=true` 例外 |
| `RESUME_PARSE_CACHE_BACKEND` | `redis` | 生产禁止 `memory`，避免多 worker 缓存行为不一致 |
| `VERIFIER_DRIFT_BACKEND` | `memory` | 生产启用 drift monitor 时会告警；多 worker 建议 Redis |
| `CORS_ORIGINS` | `localhost` 系列 | 生产必须收紧为前端真实域名 |

### 关键区别

- **代码默认值**：`settings.py` 中的 `Field(default=...)` 值，面向开发环境零配置启动
- **`.env.example`**：示例文件，供参考；**不会**被自动加载
- **生产环境变量**：运行时实际值，通过 `.env` / secret manager / 容器环境传入

> `CHECKPOINT_BACKEND=memory` 在开发中完全可用，但**不提供跨进程恢复**。生产部署如果因意外重启丢失了面试会话，`memory` 后端无法恢复。

## 部署 Preflight

`app/core/deployment_preflight.py` 在 FastAPI 启动时自动运行：

- **`dev` / `test`**：记录配置摘要和警告，但不阻止启动
- **`prod`**：对以下项硬校验，不通过则 `PreflightError` 阻止启动：
  - `CHECKPOINT_BACKEND` 必须为 `postgres`
  - `API_TOKEN` 必须非空（或 `ALLOW_OPEN_ADMIN=true`）
  - LLM 不能进入 `stub` 模式
  - `EMBEDDING_PROVIDER=stub` 默认禁止，除非显式允许
  - `RESUME_PARSE_CACHE_BACKEND` 不能为 `memory`
- **`prod` 告警项**：`ENABLE_VERIFIER_DRIFT_MONITOR=true` 且 `VERIFIER_DRIFT_BACKEND=memory` 时允许启动但记录多 worker 不共享窗口风险

配置摘要输出纯布尔 / 枚举值，不泄露密钥。

## 评分可信度指标

`app/services/scoring_credibility.py` 提供纯计算的可信度评估：

| 指标 | 计算方式 | 说明 |
|------|---------|------|
| `fallback_rate` | `evaluator_fallback_count / total_turns` | 评估模型兜底比例 |
| `evidence_span_miss_rate` | `unmatched_quotes / total_quotes` | 证据引用未匹配率 |
| `contract_no_rate` | `checks_no / total_checks` | 合约检查未通过率 |
| `verification_forced_refine` | `verification.forced_refine` | 验证器是否强制修正 |
| `credibility_level` | 规则评估 | `high` / `medium` / `low` |

### 可信度评级规则

| 信号 | 条件 | 权重 |
|------|------|------|
| 高 fallback | `fallback_rate > 0.5` | +2 |
| 中 fallback | `fallback_rate > 0.25` | +1 |
| 高 span miss | `span_miss_rate > 0.5` | +2 |
| 中 span miss | `span_miss_rate > 0.3` | +1 |
| 高 contract no | `contract_no_rate > 0.5` | +1 |
| forced refine | `verification.forced_refine` | +1 |

- 总分 >= 3：`low`
- 总分 >= 1：`medium`
- 总分 == 0：`high`
- `total_turns == 0`：直接 `low`

## P0 上线验收矩阵

| # | 验收项 | 验证方式 | 通过标准 |
|---|--------|---------|---------|
| 1 | Preflight dev 不阻断 | `APP_ENV=dev pytest tests/unit/test_deployment_preflight.py` | 全绿 |
| 2 | Preflight prod 拒绝 memory | 测试用例 `test_prod_memory_checkpoint_raises` | 抛 `PreflightError` |
| 3 | Preflight prod 拒绝空 token | 测试用例 `test_prod_no_token_raises` | 抛 `PreflightError` |
| 4 | Preflight prod 正常通过 | 测试用例 `test_prod_valid_config_succeeds` | 返回摘要 |
| 5 | Token 不泄露 | 测试用例 `test_token_not_leaked` | 摘要无密文 |
| 6 | HITL turn 一致性 | `pytest tests/unit/test_hitl_turn_consistency.py` | 全绿 |
| 7 | 恢复后 turn 字段正确 | `test_recovered_handle_turn_fields_consistent` | asked_turn < turn_idx |
| 8 | 重复提交不推进 | `test_second_submit_same_turn_raises` | ValueError |
| 9 | 完成后取消不变更 | `test_cancel_after_done_preserves_state` | cancelled=False |
| 10 | 可信度指标计算正确 | `pytest tests/unit/test_scoring_credibility.py` | 全绿 |
| 11 | 可信度接入 final_report | `pytest tests/unit/test_final_report_evidence.py` | 全绿 |
| 12 | 全量单元测试 | `pytest tests/unit -q` | 无新增失败 |

## 不做事项

- 不拆 `interview.py` 或 `session_manager.py`
- 不引入用户系统
- 不修改 `Settings` 和 `.env.example` 的默认配置值
- 不强制每轮 Verifier

## 风险与回滚

- **Preflight 阻断风险**：仅 `APP_ENV=prod` 下硬失败；dev/test 只记警告
- **可信度指标初版保守**：作为观测字段，不阻断报告生成
- **回滚**：删除 `deployment_preflight.py` import 和 `main.py` 中的 `run_preflight` 调用即可恢复原始启动行为

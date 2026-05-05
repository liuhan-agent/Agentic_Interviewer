# Phase 6: 配置与密钥体系

## 1. 模块定位

`配置与密钥体系` 是 OpenClaw 的“运行前提层”。

它解决的不是 Agent 怎么思考，而是：

- 系统从哪里读配置
- 配置如何分层和合并
- 密钥如何以引用形式写入配置
- 运行时如何把配置和密钥解析成可执行状态
- Gateway / Agent / Plugin / Channel 如何消费这些运行态数据

从源码看，这一层主要由以下目录和文件组成：

- 配置主入口：`src/config/config.ts`
- 配置读写与快照：`src/config/io.ts`
- 配置类型定义：`src/config/types.ts`、`src/config/types.models.ts`、`src/config/types.plugins.ts`、`src/config/types.secrets.ts`
- 配置运行态覆盖：`src/config/runtime-overrides.ts`
- 配置校验：`src/config/validation.ts`
- 插件配置归一化：`src/plugins/config-state.ts`
- 密钥引用解析：`src/secrets/resolve.ts`
- 密钥运行时快照：`src/secrets/runtime.ts`
- Gateway auth surface：`src/secrets/runtime-gateway-auth-surfaces.ts`
- runtime 级配置/密钥收集器：`src/secrets/runtime-config-collectors-*`
- 模型授权与 provider 凭据：`src/agents/model-auth.ts`

## 2. 先把核心概念分清

这一块最容易混淆的，其实是 `config`、`runtime snapshot`、`secret ref`、`auth surface` 四个概念。

### 2.1 配置文件不是运行态

磁盘里的 config 只是“原始声明”：

- 用户写了什么
- 哪些值是 `SecretRef`
- 哪些插件启用了
- 哪些 provider / channel / gateway 选项被配置

但运行时真正执行的对象，是经过解析、合并、补全后的 `OpenClawConfig`。

### 2.2 Runtime snapshot 是“活跃运行态”

运行态快照会把：

- config 的结构化值
- 解析后的 secret 值
- auth profile store
- runtime web tools 元数据

打包成一个可执行快照。

### 2.3 `SecretRef` 是“引用”，不是值

`SecretRef` 在源码里定义在 `src/config/types.secrets.ts`，支持：

- `env`
- `file`
- `exec`

它表示“这个值要去某个提供方里取”，不是把密钥明文写死在配置里。

### 2.4 Auth surface 是“有条件可生效的密钥位点”

像 `gateway.auth.token`、`gateway.remote.password` 这种字段，并不是永远生效。

OpenClaw 会判断它们是否属于 active surface，再决定是否解析和注入。

所以它是：

> 配置字段 + 启动上下文 + runtime 决策

共同决定的“活跃密钥面”。

## 3. 配置分层

OpenClaw 的配置不是单层，而是一个分层叠加模型。

### 3.1 磁盘配置层

主要是用户写入的配置文件，由 `src/config/io.ts` 负责读取和写回。

读取主线包括：

- `loadConfig()`
- `readConfigFileSnapshot()`
- `readConfigFileSnapshotForWrite()`

写回主线包括：

- `writeConfigFile()`

这个层面关心的是“原始配置内容”和“文件持久化”。

### 3.2 运行时覆盖层

`src/config/runtime-overrides.ts` 提供运行时覆盖机制：

- `setConfigOverride()`
- `unsetConfigOverride()`
- `applyConfigOverrides()`

这表示 OpenClaw 允许某些 CLI / 启动路径把配置临时覆盖到内存中，而不一定立即写回磁盘。

### 3.3 runtime snapshot 层

`src/config/io.ts` 维护两个关键快照：

- `runtimeConfigSnapshot`
- `runtimeConfigSourceSnapshot`

相关函数包括：

- `setRuntimeConfigSnapshot()`
- `clearRuntimeConfigSnapshot()`
- `getRuntimeConfigSnapshot()`
- `getRuntimeConfigSourceSnapshot()`
- `projectConfigOntoRuntimeSourceSnapshot()`

这层的核心意义是：

> 运行中对象和源配置对象不是同一个东西，但可以保持投影和回写语义一致。

### 3.4 校验与默认值层

`src/config/validation.ts` 和 `src/config/defaults.ts` 会在读取后、使用前补足和校验配置：

- schema 校验
- legacy config 兼容
- 插件配置校验
- gateway bind / tailscale 安全校验
- agent defaults / model defaults / session defaults

这说明 OpenClaw 的 config 不是“读出来就直接用”，而是“经过强校验和归一化后再进入运行态”。

## 4. `src/config/io.ts` 的读写和快照机制

`src/config/io.ts` 是这套体系最核心的文件之一。

### 4.1 读取流程

读取主线大致是：

```text
loadConfig()
 -> 选 configPath
 -> 读 JSON5
 -> 处理 include
 -> 应用 config.env
 -> 做 env substitution
 -> 校验和默认值补全
 -> 返回 OpenClawConfig
```

它还会处理：

- `.env` / shell env fallback
- include 文件
- legacy config migration
- 缓存

### 4.2 写回流程

写回配置时，`io.ts` 还会：

- 清理不该持久化的运行态值
- 记录 audit log
- 保持 version stamp
- 尽量安全地保留 env ref 结构

这意味着配置写回并不是简单 `JSON.stringify`，而是有保护逻辑的。

### 4.3 runtime snapshot 的作用

`loadConfig()` 优先返回 `runtimeConfigSnapshot`，如果它存在就不再读盘。

这很关键，因为它说明：

> 一旦进入活跃运行态，系统优先消费内存中的快照，而不是每次都回盘重读。

这对 Gateway 启动、Secrets 激活、热刷新都很重要。

## 5. 插件配置

插件配置不是附属字段，而是配置体系的重要一级。

### 5.1 插件配置主入口

核心文件：

- `src/config/types.plugins.ts`
- `src/plugins/config-state.ts`

### 5.2 插件配置包含什么

`PluginsConfig` 里主要有：

- `enabled`
- `allow`
- `deny`
- `load.paths`
- `slots.memory`
- `slots.contextEngine`
- `entries`
- `installs`

`entries` 里又包含：

- `enabled`
- `hooks.allowPromptInjection`
- `subagent.allowModelOverride`
- `subagent.allowedModels`
- `config`

### 5.3 插件 slot 的设计

OpenClaw 对插件不是完全平铺，而是有 slot 概念。

尤其关键的是：

- `memory` slot
- `contextEngine` slot

这意味着某些能力不是“多个插件都能同时占用”，而是“某个 slot 选定一个 owner”。

### 5.4 插件配置归一化

`src/plugins/config-state.ts` 会负责：

- 规范化 plugin id
- 处理 alias
- 归一化 allow / deny
- 归一化 slot 值
- 归一化 entries

因此插件配置的设计不是“用户原样输入直接拿来用”，而是先进入统一状态机再交给插件 loader。

## 6. 密钥引用与解析

这是 OpenClaw 配置体系里最关键的安全设计之一。

### 6.1 `SecretRef` 的结构

`src/config/types.secrets.ts` 定义了：

- `SecretRefSource = "env" | "file" | "exec"`
- `SecretRef`
- `SecretInput = string | SecretRef`

这说明配置里的秘密值可以有两种形态：

- 直接字符串
- 引用一个外部 secret provider

### 6.2 支持的 provider 类型

`SecretsConfig` 支持：

- `env`
- `file`
- `exec`

对应配置结构在 `src/config/types.secrets.ts` 里定义得很清楚。

### 6.3 引用怎么解析

`src/secrets/resolve.ts` 是总解析器。

它会：

- 校验 provider 是否配置
- 读取 env / file / exec provider
- 做并发限制和批处理限制
- 对 path / permissions 做安全检查
- 将 `SecretRef` 解析成实际值

解析后不会直接回写成明文逻辑，而是通过运行时快照注入给消费方。

### 6.4 运行时如何把 `SecretRef` 变成实际值

`src/secrets/runtime-shared.ts` 负责收集和应用 secret assignment：

- `collectSecretInputAssignment()`
- `applyResolvedAssignments()`
- `pushInactiveSurfaceWarning()`

`src/secrets/runtime.ts` 则是总编排：

- `prepareSecretsRuntimeSnapshot()`
- `activateSecretsRuntimeSnapshot()`
- `getActiveSecretsRuntimeSnapshot()`
- `resolveCommandSecretsFromActiveRuntimeSnapshot()`

这说明密钥解析不是分散在每个调用点，而是统一在 runtime snapshot 生成时完成。

### 6.5 明文和引用的优先级

源码里有一个很明确的倾向：

- 如果配置里有 `SecretRef`，运行时会优先解析 ref
- 如果 ref 是 active surface 才会进入解析流程
- 如果 ref 无法解析，部分场景允许 fallback 到 env
- 如果 ref 和明文同时出现，runtime 会偏向 ref，并给出 warning

这就是 OpenClaw 的“明文退化可用，但引用优先”的安全策略。

## 7. Runtime snapshot 的结构

`src/secrets/runtime.ts` 里 `PreparedSecretsRuntimeSnapshot` 包含：

- `sourceConfig`
- `config`
- `authStores`
- `warnings`
- `webTools`

这几个字段很重要。

### 7.1 `sourceConfig`

保留原始来源配置，用于：

- 重新解析 secret refs
- 运行时 refresh
- 回写时投影

### 7.2 `config`

这是解析完成后的运行态配置。

### 7.3 `authStores`

这是每个 agentDir 对应的 auth profile store 快照。

### 7.4 `warnings`

包括：

- unresolved secret refs
- ignored inactive surface refs
- 其它 runtime 级警告

### 7.5 `webTools`

运行态 web search / fetch 相关的元数据也会进入快照，说明 secrets runtime 不只是处理 token，也会把能力启用状态一起带进去。

## 8. Gateway auth surface

这部分特别值得单独强调，因为它体现了“配置字段并不总是生效”的设计。

### 8.1 相关源码

- `src/secrets/runtime-gateway-auth-surfaces.ts`
- `src/gateway/credential-planner.ts`
- `src/gateway/server.impl.ts`

### 8.2 为什么要有 auth surface

Gateway 的认证字段有多个来源和多种模式：

- `gateway.auth.token`
- `gateway.auth.password`
- `gateway.remote.token`
- `gateway.remote.password`

它们并不是同时都有效，而是由：

- `gateway.mode`
- `gateway.auth.mode`
- `gateway.remote.url`
- `gateway.tailscale.mode`
- env token/password

共同决定“谁能赢”。

### 8.3 `evaluateGatewayAuthSurfaceStates(...)`

`src/secrets/runtime-gateway-auth-surfaces.ts` 会把上述字段映射成：

- `active`
- `reason`
- `hasSecretRef`

这就是“auth surface”的核心。

### 8.4 `createGatewayCredentialPlan(...)`

`src/gateway/credential-planner.ts` 决定：

- 本地 token / password
- remote token / password
- env token / password
- 哪个来源可以 win

也就是说，Gateway 启动时不是简单读取某个字段，而是先做一轮 credential planning。

### 8.5 启动时为什么要先做 preflight

`src/gateway/server.impl.ts` 在真正起服务前会：

- 读 config snapshot
- 校验 config
- 迁移 legacy config
- 激活 secrets runtime snapshot
- 再启动 Gateway 服务

这保证了 auth surface 在启动前就被正确判断，不会在运行中才发现 credential 结构不对。

## 9. Config 和 Secrets 如何被 Gateway / Agent 消费

### 9.1 Gateway 消费方式

`src/gateway/server.impl.ts` 是最典型的 consumer。

它会消费：

- `readConfigFileSnapshot()`
- `applyConfigOverrides()`
- `prepareSecretsRuntimeSnapshot()`
- `activateSecretsRuntimeSnapshot()`
- `evaluateGatewayAuthSurfaceStates()`

也会启动：

- `createChannelManager(...)`
- `createGatewayRuntimeState(...)`
- `loadGatewayPlugins(...)`
- `startGatewaySidecars(...)`

这说明 Gateway 的职责不是“只读 config”，而是把 config + secrets 转成可运行平台。

### 9.2 Agent 消费方式

`src/agents/agent-command.ts` 和 `src/agents/pi-embedded-runner/run.ts` 会消费：

- `loadConfig()`
- `resolveSession(...)`
- `loadModelCatalog(...)`
- `ensureOpenClawModelsJson(...)`
- `resolveProviderAuth...`
- `buildWorkspaceSkillSnapshot(...)`

也就是说 Agent 的模型选择、auth profile、skills、workspace、session 都依赖配置与密钥体系。

### 9.3 模型 auth 的消费链

`src/agents/model-auth.ts` 是模型凭据消费的关键入口。

它会从：

- auth profile store
- env vars
- `models.providers.*.apiKey`
- synthetic local auth markers
- provider runtime plugin

里找出最终可用的模型认证信息。

这说明配置与密钥体系最终会落到“模型是否可用”这个执行问题上。

## 10. 这套体系的设计思路

把源码串起来看，这套设计其实是很明确的：

### 10.1 配置是声明，运行态是投影

用户写的是声明式 config，但运行时会投影成活跃 snapshot。

### 10.2 密钥不应静态展开

`SecretRef` 允许把敏感值延后到 runtime 解析，避免把所有密钥都直接烘焙进磁盘配置。

### 10.3 不同 surface 有不同生效条件

Gateway auth、channel account、provider config、memory search、skills entry 都可能有 active/inactive 语义。

### 10.4 运行态必须可刷新

`prepareSecretsRuntimeSnapshot()` + `setRuntimeConfigSnapshotRefreshHandler(...)` 说明配置和 secrets 不是只在启动时生效，而是支持 runtime refresh。

### 10.5 插件和 provider 都是配置驱动的扩展面

插件配置、provider 配置、memory slot、context engine slot 都是通过 config 驱动的装配点。

## 11. 小结

`配置与密钥体系` 的本质可以概括为：

> OpenClaw 用一套分层配置、密钥引用和运行态快照机制，把磁盘上的声明式配置变成 Gateway / Agent / Plugin 可安全消费的活跃运行态。

如果再压缩成一句设计判断，那就是：

> OpenClaw 不是“直接读取配置就跑”，而是“先校验、再解析 secret refs、再构建 runtime snapshot，最后让 Gateway 和 Agent 消费这个活跃快照”。

这也是它能同时兼顾：

- 本地文件化管理
- 安全密钥引用
- 插件化扩展
- Gateway 长驻运行
- Agent 运行时动态消费

的根本原因。

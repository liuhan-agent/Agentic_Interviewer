# Phase 4: Plugins、Skills 与工具扩展机制

## 1. 模块定位

这一层是 OpenClaw 扩展能力最密集、也最容易混淆的地方。

如果把 OpenClaw 的 Agent 开发范式继续往下拆，`Plugins`、`Skills`、`Tools`、`MCP` 四层分别解决的是不同问题：

- `Plugins` 解决“能力怎么接入系统”
- `Skills` 解决“知识/行为怎么注入 prompt 和运行时”
- `Tools` 解决“Agent 具体怎么执行动作”
- `MCP` 解决“外部工具服务器怎么接入 Agent runtime”

这四层相关，但不是同一层。

一个更准确的总览是：

```text
Plugins = 扩展装配层
Skills = prompt/知识层
Tools = 执行能力层
MCP = 外部工具接入层
```

## 2. 先纠正几个容易混淆的概念

### 2.1 Skills 不等于 Plugins

这是最重要的一个修正。

更准确地说：

- `Plugin` 是代码扩展单元
- `Skill` 是运行时的技能/操作知识单元
- `Plugin` 可以向 `Skill` 层注入额外 skills，但 `Skill` 不是 `Plugin` 的子集

从源码上看：

- 技能主系统在 `src/agents/skills/*`
- 插件只是通过 `src/agents/skills/plugin-skills.ts` 提供额外 skill 目录

所以如果把两者强行等同，会把扩展机制和 prompt 机制混掉。

### 2.2 Tools 不等于 Plugins

`Tools` 是 Agent 真的可以调用的能力接口。

其中有三类来源：

- 底层 framework 自带的 coding tools
- OpenClaw 内建工具
- 插件注入工具

也就是说，`Tool` 是运行时可执行能力，`Plugin` 是扩展来源。

### 2.3 Gateway / Agent / Runtime 不是三个平行系统

它们在插件体系里是不同承载面：

- `Gateway` 是长驻宿主和控制平面
- `Agent runtime` 是具体执行面
- `Plugin runtime` 是被两者共享的扩展契约

插件并不是只在某一个层里工作，而是被 Gateway 和 Agent runtime 共同装配、共同调用。

## 3. 顶层源码边界

这一层的核心文件和目录大致如下：

- 插件系统总入口：`src/plugins/loader.ts`
- 插件运行时契约：`src/plugins/runtime/index.ts`
- 插件运行时类型：`src/plugins/runtime/types.ts`
- 插件工具注入：`src/plugins/tools.ts`
- Provider runtime 扩展：`src/plugins/provider-runtime.ts`
- 插件配置/slot 状态：`src/plugins/config-state.ts`
- 插件清单与注册表：`src/plugins/manifest-registry.ts`、`src/plugins/registry.ts`
- 插件 SDK 公共面：`src/plugin-sdk/*`
- 技能系统：`src/agents/skills.ts`、`src/agents/skills/workspace.ts`、`src/agents/skills/plugin-skills.ts`
- 内建工具系统：`src/agents/tool-catalog.ts`、`src/agents/openclaw-tools.ts`、`src/agents/pi-tools.ts`
- Agent 运行时装配：`src/agents/agent-command.ts`、`src/agents/pi-embedded-runner/run.ts`
- 扩展实现目录：`extensions/*`

## 4. Plugins：扩展装配层

### 4.1 Plugin 在 OpenClaw 里的职责

Plugin 的核心职责不是“写 prompt”，而是：

- 提供一组可发现的扩展能力
- 把能力接入 OpenClaw 的 registry / runtime
- 通过标准契约暴露 tools、hooks、providers、channels、services、http routes 等

在 `src/plugins/types.ts:1269-1340` 里，可以看到插件能贡献的能力面非常多，包括：

- `registerTool(...)`
- `registerHook(...)`
- `registerChannel(...)`
- `registerGatewayMethod(...)`
- `registerCli(...)`
- `registerService(...)`
- `registerProvider(...)`
- `registerSpeechProvider(...)`
- `registerMediaUnderstandingProvider(...)`
- `registerImageGenerationProvider(...)`
- `registerWebSearchProvider(...)`
- `registerCommand(...)`
- `registerContextEngine(...)`

这说明插件系统本质上不是“某种特殊 tool 包”，而是 OpenClaw 的“扩展装配框架”。

### 4.2 Plugin 的物理形态：通常就是一个扩展包目录

从物理落盘形态上看，插件通常就是一个独立扩展包目录，最常见的位置是仓库根目录的 `extensions/<id>/`，而不是 `src/` 下面。

一个典型插件包至少有三部分：

- `openclaw.plugin.json`
- `package.json`
- 代码入口与可选资源目录，例如 `skills/`

其中：

- `openclaw.plugin.json` 由 `src/plugins/manifest.ts` 解析，里面会声明 `id`、`configSchema`、可选的 `skills`、`providers`、`channels` 等
- `package.json` 需要声明 `openclaw.extensions`，安装器会用它找到插件入口；缺失时 `src/plugins/install.ts` 会直接报错
- 可选资源目录可以包含 skills、MCP bundle 配置或其它插件私有资源

因此更准确地说：

- 从文件系统角度，Plugin 往往“就是一个文件夹/包”
- 从架构角度，Plugin 是“一个可安装、可发现、可加载的扩展单元”

### 4.3 “可插拔”到底是什么意思

“可插拔”不等于“放在 `extensions/` 里就一定会跑”，它更准确地指：

```text
插件包存在
 -> 被发现（discovered）
 -> 被启用（enabled）
 -> 被加载（loaded）
```

也就是说，插件是独立安装和装配的，不需要把能力硬编码进 core。

从源码看，CLI 明确支持插件生命周期管理：

- `plugins list`：`src/cli/plugins-cli.ts:514`
- `plugins uninstall`：`src/cli/plugins-cli.ts:875`
- `plugins install`：`src/cli/plugins-cli.ts:1010`
- `plugins update`：`src/cli/plugins-cli.ts:1027`

而 `plugins install` 支持的来源也不止一种，`src/plugins/install.ts` 里至少有：

- `installPluginFromArchive(...)`
- `installPluginFromDir(...)`
- `installPluginFromFile(...)`
- `installPluginFromNpmSpec(...)`
- `installPluginFromPath(...)`

所以“可插拔”的真正含义是：

- 插件包可以独立安装/卸载
- 插件可以独立启用/禁用
- 核心运行时会按契约发现和装配它们

### 4.4 并不是 `extensions/*` 下的插件都会被加载

这也是一个很容易误解的点。

`extensions/*` 下的目录更准确地说是“插件候选包”，而不是“只要存在就一定 active”。

实际链路是：

- `src/plugins/manifest-registry.ts` 通过 `discoverOpenClawPlugins(...)` 发现候选插件
- `src/plugins/loader.ts` 再通过 `resolveEffectiveEnableState(...)` 判断插件是否启用
- 某些插件即使被发现，也会因为 `enabled=false`、setup/runtime 模式、memory slot 决策等原因被标成 disabled

在 `src/plugins/loader.ts` 里可以直接看到：

- `resolveEffectiveEnableState(...)`：`src/plugins/loader.ts:898`
- 未启用时标记 disabled：`src/plugins/loader.ts:961`
- memory 插件可能因为 slot 决策被提前禁用：`src/plugins/loader.ts:1039`、`src/plugins/loader.ts:1155`

所以最准确的说法是：

- `extensions/*` 里的插件“有资格被发现”
- 只有被发现且满足配置/运行时策略条件的插件，才会真正进入 active runtime

### 4.5 插件能提供什么，不只是 Tools 和 Skills

用户最容易接触到的是：

- 插件注入 tools
- 插件暴露 skills

但这只是插件系统的一部分。

从 `src/plugins/types.ts:1304-1340` 看，插件其实更像“能力容器”，可以装下：

- `Tool`
- `Provider`
- `Channel`
- `Service`
- `Gateway Method`
- `HTTP Route`
- `CLI`
- `Command`
- `Context Engine`
- `Hook`

所以更准确的理解是：

- `Plugin` 是盒子
- `Tool / Skill / Provider / Channel ...` 是盒子里装的能力

### 4.6 `Provider` 和 `Tool`、`Skill` 的区别

这三个概念的职责不一样：

- `Provider`：底层能力后端
- `Tool`：Agent 可调用接口
- `Skill`：任务流程与知识包

更细一点说：

- `Provider` 解决“能力从哪来”
- `Tool` 解决“Agent 怎么调用能力”
- `Skill` 解决“什么时候、按什么流程去用这些能力”

在插件 API 里，Provider 也分很多类：

- 文本模型 provider：`registerProvider(...)`
- 语音 provider：`registerSpeechProvider(...)`
- 多模态理解 provider：`registerMediaUnderstandingProvider(...)`
- 图像生成 provider：`registerImageGenerationProvider(...)`
- Web 搜索 provider：`registerWebSearchProvider(...)`

这里要特别注意：

- 有些 provider 最终会进一步生成 tool，例如 web search provider 在 `src/plugins/types.ts:904` 里要提供 `createTool(...)`
- 但不是所有插件能力都会变成 tool；像 `channel`、`service`、`gatewayMethod`、`httpRoute`、`hook`、`contextEngine` 都不是 Agent tool-calling 那一层

### 4.7 core 能力和 extension 能力的区别

两者最主要的区别不是“是否高级”，而是“来源和生命周期”不同。

`core` 能力通常直接实现在 `src/` 里，例如：

- core tools 的目录与分组定义在 `src/agents/tool-catalog.ts:41-338`

`extension` 能力则通过插件 API 注入，例如：

- `registerTool(...)`
- `registerProvider(...)`
- `registerChannel(...)`

到了运行时，两者会汇合成统一能力集合，但系统仍然保留它们的来源。

例如工具目录这层就明确区分：

- core tool 分组：`src/gateway/server-methods/tools-catalog.ts:63-67`
- plugin tool 分组：`src/gateway/server-methods/tools-catalog.ts:71-112`

图像生成 provider 注册表也展示了“内建槽位 + 插件合并”的结构：

- built-in provider 槽位：`src/image-generation/provider-registry.ts:7`
- plugin provider 合并：`src/image-generation/provider-registry.ts:49`

所以最准确的说法是：

- core 与 extension 都能提供能力
- 它们最终会汇合到同一运行时视图
- 但“extension 能力”并不等于“tool 的底层”，因为还有 channel、service、http route、context engine 这类并非 tool 的扩展面

### 4.8 插件如何被加载

`src/plugins/loader.ts` 是插件加载的总入口。

它的关键工作包括：

- 发现插件
- 读取 plugin manifest
- 校验配置 schema
- 构建插件 registry
- 创建 plugin runtime
- 将 registry 激活为 active registry

源码里可以看到几个关键点：

- `loadOpenClawPlugins(...)`
- `createPluginRegistry(...)`
- `setActivePluginRegistry(...)`
- `createPluginRuntime(...)`

插件加载不是“直接 import 某个文件就完了”，而是一个带缓存、校验、激活和运行时注入的完整流程。

### 4.9 插件注册表记录了什么

`src/plugins/loader.ts` 生成的 `PluginRecord` 会记录：

- `toolNames`
- `hookNames`
- `channelIds`
- `providerIds`
- `speechProviderIds`
- `mediaUnderstandingProviderIds`
- `imageGenerationProviderIds`
- `webSearchProviderIds`
- `gatewayMethods`
- `cliCommands`
- `services`
- `commands`
- `httpRoutes`

这说明 registry 不是只有“插件是否启用”这么简单，而是把插件最终提供了哪些能力全部记下来。

### 4.10 插件如何进入 runtime

`src/plugins/runtime/index.ts` 定义了插件运行时对象。

这个 runtime 不是只包含工具，它还包含：

- `config`
- `agent`
- `subagent`
- `system`
- `media`
- `tts`
- `mediaUnderstanding`
- `imageGeneration`
- `webSearch`
- `stt`
- `tools`
- `channel`
- `events`
- `logging`
- `state`
- `modelAuth`

也就是说，插件 runtime 是插件和核心系统之间的统一契约。

### 4.11 Gateway 为什么也要加载插件

Gateway 启动时也会调用插件加载逻辑。

原因很简单：

- Gateway 要承载插件暴露的 methods、channels、services、HTTP 路由
- Gateway 是长驻宿主，必须在启动阶段把这些能力装配进去

因此插件不是 Agent 专属，也不是 Gateway 专属，而是被两者共享的扩展层。

### 4.12 插件什么时候是“安装”，什么时候只是“加载”

这里也需要和 skills 分开看。

从源码上看，插件本体的安装是显式动作，而不是运行时按需下载：

- CLI 安装入口在 `src/cli/plugins-cli.ts`
- 实际安装逻辑在 `src/plugins/install.ts`
- 安装来源可以是 npm spec、本地路径、archive、marketplace

也就是说，`Plugin install` 的含义是真正把插件包落到本地扩展目录，并写入后续可发现的安装记录。

而 Gateway / Agent 启动时做的事情是另一层：

- 通过 `loadOpenClawPlugins(...)` 发现已经安装好的插件
- 读取 manifest
- 构建 registry
- 创建 runtime

所以更准确的表述是：

- 插件本体是“显式安装”
- 运行时只做“发现、加载、装配”
- Gateway 不会在启动时临时把某个插件从网络拉下来

### 4.13 插件能不能在前端 UI 里配置

从源码看，答案是“可以配置，但安装/卸载主要还是 CLI”。

前端配置链路很明确：

- UI 会请求 `config.schema`：`ui/src/ui/controllers/config.ts:55-76`
- Gateway 在 `src/gateway/server-methods/config.ts:245-280` 里会把插件的 `configSchema` 和 `configUiHints` 合并进统一配置 schema
- UI 再根据 schema 和 `uiHints` 渲染配置表单

插件配置至少包括：

- `plugins.entries.*.enabled`
- 插件自己的配置项

这一点在前端测试里也能直接看到，见 `ui/src/ui/config-form.browser.test.ts:170-200`。

但这和插件“安装/卸载”不是一回事。

这轮源码核对里，我明确确认的是：

- CLI 有 `plugins install/uninstall/list/update`
- UI 有插件配置表单

我没有在 Gateway server methods 里看到对称的 `plugins.install` / `plugins.uninstall` 接口，因此更稳妥的结论是：

- 插件可以在前端 UI 中配置
- 插件安装/卸载目前主要还是 CLI 负责

## 5. Skills：prompt/知识层

### 5.1 Skills 的定位

OpenClaw 里的 skill 更像一个“目录化的提示词包/资源包”，不是 npm 包。**唯一硬性要求的文件通常只有 SKILL.md**；加载器就是靠它识别一个目录是不是 skill。

典型结构可以这样看：

```text
my-skill/
├─ SKILL.md            # 必需
├─ references/         # 常见，可选
├─ scripts/            # 常见，可选
├─ bin/                # 少见，可选
└─ 其他零散文件         # 少见，可选
```

各部分作用：

- SKILL.md
  - 这是 skill 的主体。
  - 前面是 frontmatter，至少要有 name 和 description；OpenClaw 还会解析一些扩展字段，比如 metadata.openclaw.*、homepage、user-invocable、command-dispatch 等，见 `docs/tools/skills.md` 的格式说明。
  - 后面正文是给 agent 的操作说明、工作流、约束、何时去读附加资料等。
  - 运行时最终会被解析成 SkillEntry，再进入 SkillSnapshot 和 skillsPrompt，见 `src/agents/skills/workspace.ts:614、src/agents/skills/workspace.ts:650`。
- references/
  - 放参考文档、示例、协议说明、CLI 用法这类“按需读取”的资料。
  - 典型例子：
    - `skills/1password/references/`
    - `skills/model-usage/references/`
  - 这类内容通常不会在 skill 触发前就全部塞进上下文，而是由 SKILL.md 指引 agent 在需要时再读。
- scripts/
  - 放辅助脚本，适合确定性强、重复执行的步骤。
  - 典型例子：
    - `skills/model-usage/scripts/model_usage.py`
    - `skills/skill-creator/scripts/`
  - 作用是把复杂流程从 prompt 里拿出来，改成可直接执行或少量修改的脚本。
- bin/
  - 少见，但仓库里确实有。
  - 例子：`skills/sherpa-onnx-tts/bin/sherpa-onnx-tts`
  - 适合放一个小型可执行辅助工具，或者 skill 自带的本地命令包装。
- 其他零散文件
  - 例如 license.txt，见 `skills/skill-creator/license.txt`
  - 这类不是加载器关心的核心文件，只是附带资源。

几个关键边界：

- **OpenClaw 加载器真正“认”的核心就是 SKILL.md**。辅助目录只是 skill 自己引用的资源，不是框架强制要求。
- skill 根目录本身可以直接是一个 skill（目录里直接有 SKILL.md），也可以是一个 skills root，下面每个子目录各自带 SKILL.md。这就是 `src/agents/skills/workspace.ts:320` 和 `src/agents/skills/workspace.ts:380` 那段逻辑。
- 插件自带的 skill、工作区 skills/ 下的 skill、用户目录里的 skill，本质结构都一样；区别只是来源不同，不是包结构不同。

如果按源码里的真实主线来理解，Skills 最重要的不是“安装”，而是下面这条链：

```text
磁盘上的 SKILL.md / plugin skill 目录
 -> SkillEntry（发现形态）
 -> SkillSnapshot（会话缓存形态）
 -> skillsPrompt（提示词文本形态）
 -> SystemPrompt
```

也就是说，Skills 的主职责是：

- 把可复用的行为知识组织成 `SKILL.md`
- 把这些知识扫描成运行时可管理的 skill entries
- 把当前会话需要的 skills 固定成 snapshot
- 再把 snapshot 渲染成模型能读的 prompt 片段

### 5.2 Skills 的渐进式披露，本质上也靠 tool calling 落地

这里要拆得更细一点，不然很容易把 Skills 误解成另一套执行引擎。  
从源码看，Skills 在 OpenClaw 里其实分成 4 个阶段：

#### 第一阶段：先在运行时发现 skills，再把 skills catalog 注入 SystemPrompt

这里要先把两层职责拆开：

- **发现层 / 加载层**：运行时代码先去约定的 skills roots 里发现 `SKILL.md`，再解析成 `SkillEntry`
- **提示词层 / SystemPrompt**：attempt 开始时，只消费已经整理好的 `skillsPrompt`

所以真正进入 SystemPrompt 的，不是“原始目录规则”本身，而是上一层已经渲染好的 skills catalog。

这一步在 attempt 的 system-side context 构建阶段落地：

- `resolveSkillsPromptForRun(...)`：`src/agents/pi-embedded-runner/run/attempt.ts:1441`
- `formatSkillsCompact(...)` / `formatSkillsForPrompt(...)`：`src/agents/skills/workspace.ts:543`、`src/agents/skills/workspace.ts:687`

这里进入 prompt 的不是完整 skill 正文，而只是 skill catalog，例如：

- `<available_skills>`
- `<name>`
- `<description>`（预算够时）
- `<location>`

也就是说，这一步只是告诉模型：

> **“有哪些技能可选，它们大概是做什么的，文件在哪。”**

#### 第二阶段：模型先做“要不要读 skill”的决策

这一步还没有真正展开 skill 正文，而是在 `SystemPrompt` 规则里先做选择。

`src/agents/system-prompt.ts:20-30` 里已经把规则写死了：

- 先扫描 `<available_skills>`
- 如果只有一个 skill 明显匹配，就去读它的 `SKILL.md`
- 如果多个都可能匹配，先选最具体的那个
- 如果没有明确匹配，就不要读任何 `SKILL.md`
- 一开始不要同时读很多个 skill

所以这一步的本质是：

> **Skills 先作为“知识路由目录”出现，而不是一上来就把所有 skill 正文塞进上下文。**

#### 第三阶段：真正展开 skill 正文时，靠的是 tool calling

一旦模型决定某个 skill 匹配，真正的展开动作就不是“框架内部魔法”，而是：

- 调用 `read` 工具
- 去读取那个 skill 目录里的 `SKILL.md`

所以最核心的一条链是：

```text
skills roots / SkillSnapshot
 -> 生成 skillsPrompt（只有 available_skills 目录）
 -> 放进 SystemPrompt
 -> 模型判断 skill 是否匹配
 -> 如果匹配：tool call = read SKILL.md
 -> SKILL.md 内容进入 messages
 -> 模型继续后续步骤
```

这也是为什么更准确的定义应该是：

> **Skills 不是一套脱离 tools 的独立执行机制，而是一种“先目录提示、再按需通过 tool calling 展开正文”的知识路由层。**

#### 第四阶段：读完 `SKILL.md` 之后，真正执行仍然回到普通工具体系

这是最容易被忽略的一点。  
`SKILL.md` 读出来之后，接下来发生什么，并不是由“skill runtime”接管，而是重新回到普通的工具调用面。

最常见有两种路径：

**路径 A：`SKILL.md` 已经把执行方式写清楚**

这种情况下，模型通常不需要再读脚本正文，直接就能执行：

```text
tool call 1: read SKILL.md
tool call 2: exec scripts/foo.sh --arg ...
```

也就是说：

- `SKILL.md` 负责说明“该执行什么、怎么执行”
- 真正落地还是靠 `exec` 或其它工具

**路径 B：`SKILL.md` 只给出资源线索，没有把细节讲透**

这种情况下，模型才会继续展开 skill 目录里的其它资源：

```text
tool call 1: read SKILL.md
tool call 2: read scripts/foo.sh 或 templates/bar.md
tool call 3: exec scripts/foo.sh ... / 调用其它工具
```

所以更准确的判断是：

- `read SKILL.md` 基本是渐进式披露的关键步骤
- 是否还要 `read` skill 包里的脚本/模板，是**按需**的，不是固定流程

#### 为什么 skill 包里有脚本，也不代表 Skills 变成了脚本执行引擎

OpenClaw 的 skill 机制默认认的是：

- `SKILL.md`
- frontmatter
- skill 目录

源码也明确假设了 skill 文件可能引用相对路径资源：

- `src/agents/skills/workspace.ts:548-549`

这说明 skill 包可以带：

- 脚本
- 模板
- 说明文件
- 其它附属资源

但这些资源不会因为放在 skill 目录里，就被 OpenClaw 自动执行。  
模型仍然要通过普通工具去处理它们，例如：

- `read`
- `exec`
- 其它内建/tool plugin/MCP tools

这里还有一个很关键的路径规则。源码里已经明确提示：

- `src/agents/skills/workspace.ts:548-549`

如果 `SKILL.md` 里引用的是相对路径资源，那么这些路径应该：

- 先以 **skill 目录** 为基准解析
- 再在真正的工具调用里尽量使用解析后的绝对路径

也就是说，skill 里的：

```text
scripts/foo.sh
```

在执行时更准确的理解不是“相对当前 shell cwd 去猜”，而是：

```text
<skill-dir>/scripts/foo.sh
```

这样做的目的是：

- 避免 workspace cwd 歧义
- 避免 sandbox / copied workspace 场景下路径跑偏
- 让 `read`、`exec` 和其它工具使用同一个确定目标

所以“有脚本的 skill”和“纯文档型 skill”的区别，不在于机制变了，而在于：

> **前者会把后续 tool calling 链拉长，后者通常在读完 `SKILL.md` 后就能直接进入任务执行。**

#### 一个特例：skill command dispatch

还有一种特殊路径，不是“先读 skill 再手动决定工具”，而是 skill frontmatter 直接声明命令分发：

- `src/agents/skills/workspace.ts:879-924`
- `src/agents/skills/types.ts:40-56`

例如：

- `command-dispatch: tool`
- `command-tool: <toolName>`

这时 skill 可以把一个 skill command 直接映射到某个 tool。  
但本质仍然不是“skill 自己执行”，而是：

> **skill 负责命令路由，真正执行仍然是 tool dispatch。**

如果把这一整段压成一句最短的结论：

> **OpenClaw 的 Skills 负责“提示模型该读哪份知识、走哪条流程”；而具体内容的展开和最终执行，仍然主要通过普通 tool calling 完成。**

### 5.3 Skills 的四种关键形态，以及它们怎么转换

如果只抓主线，OpenClaw 的 skills 最重要的不是“装在哪里”，而是下面这几种运行时形态：

1. **磁盘形态：`SKILL.md`**
   - 这是 skill 的物理载体。
   - 它包含正文、frontmatter、`metadata.openclaw.*` 等原始信息。
   - 这一层还没有进入会话，也还没有被筛选。

2. **发现形态：`SkillEntry`**
   - 这是 OpenClaw 把磁盘 skill 解析后的结构化条目。
   - 定义在 `src/agents/skills/types.ts:66-71`，字段只有：
     - `skill`
     - `frontmatter`
     - `metadata`
     - `invocation`
   - 这一层的重点是“单个 skill 被解析成了什么”，还没有会话级的 `skillFilter`、`version`。

3. **会话形态：`SkillSnapshot`**
   - 这是当前 session 可复用的技能快照。
   - 定义在 `src/agents/skills/types.ts:82-88`，核心字段是：
     - `prompt`
     - `skills`
     - `skillFilter`
     - `resolvedSkills`
     - `version`
   - 这一层的重点是“当前会话最终用哪些 skills，以及这份结果什么时候过期”。

4. **提示词形态：`skillsPrompt`**
   - 这是最终进入 system prompt 的技能目录文本。
   - 它通常来自 `SkillSnapshot.prompt`，或者在没有 snapshot 时由 `SkillEntry[]` 临时渲染。
   - 这一层不再关心单个 skill 的完整原始结构，而是只关心模型此刻需要看到的 skills catalog。

把这几层连成一条线，就是：

```text
skills roots 里的 SKILL.md
 -> 解析成 SkillEntry
 -> 经过筛选和渲染，构建 SkillSnapshot
 -> 取出其中的 prompt，形成 skillsPrompt
 -> 注入 SystemPrompt
```

这条主线对应的核心文件是：

- `src/agents/skills/types.ts`
- `src/agents/skills/workspace.ts`
- `src/agents/skills/plugin-skills.ts`
- `src/agents/skills/refresh.ts`
- `src/agents/agent-command.ts`
- `src/auto-reply/reply/session-updates.ts`
- `src/gateway/server-methods/skills.ts`
- `src/agents/system-prompt.ts`

其中：

- `src/agents/skills/types.ts` 定义 `SkillEntry` 和 `SkillSnapshot`
- `src/agents/skills/workspace.ts` 负责发现 skills、解析 `SkillEntry`、筛选 eligible skills、构建 `SkillSnapshot` 和 `skillsPrompt`
- `src/agents/skills/refresh.ts` 负责 watcher、version bump 和 skills change 事件
- `src/agents/agent-command.ts` 负责在新 session 或缺少 snapshot 时初始化 `skillsSnapshot`
- `src/auto-reply/reply/session-updates.ts` 负责在后续 turn 中按 version 检查并刷新 `skillsSnapshot`
- `src/gateway/server-methods/skills.ts` 负责控制台侧的 `skills.status`、`skills.install`、`skills.update`
- `src/agents/system-prompt.ts` 负责把 skills prompt 注入 system prompt

### 5.4 第一阶段：发现与 `SkillEntry`

第一阶段的目标是把磁盘上的技能文件，整理成运行时可管理的结构化条目。

这里可以直接把转换过程压成一条最短主线：

```text
SKILL.md
 -> 读文件正文
 -> parseFrontmatter(...)
 -> resolveOpenClawMetadata(...)
 -> resolveSkillInvocationPolicy(...)
 -> SkillEntry
```

也就是说，`SkillEntry` 是“磁盘 skill 被解析后的第一份结构化产物”，不是 snapshot，也不是 prompt 文本。

最关键的入口是：

- `loadWorkspaceSkillEntries(...)`
- `buildWorkspaceSkillSnapshot(...)`

`SkillEntry` 的结构定义在 `src/agents/skills/types.ts:66-71`，它至少包含：

- `skill`
- `frontmatter`
- `metadata`
- `invocation`

也就是说，OpenClaw 不会把 skill 只当成“一段 prompt 文本”，而是先把它解析成一个带元数据和调用策略的条目。

这里没有 `skillFilter`、`version`，是因为这两个属性根本不属于“单个技能条目”这一层：

- `skillFilter` 描述的是“这一轮 / 这一会话允许哪些 skills”，它是**一组条目被筛选后的构建条件**
- `version` 描述的是“当前 snapshot 相对 watcher 版本是否过期”，它是**会话缓存的失效信息**

所以它们天然属于 `SkillSnapshot`，不属于 `SkillEntry`。

这一点也能从源码里的实际转换看得很清楚，见 `src/agents/skills/workspace.ts:511-525`：

- `skill.filePath` 指向磁盘上的 `SKILL.md`
- `fs.readFileSync(...)` 读出原文
- `parseFrontmatter(raw)` 解析 frontmatter
- `resolveOpenClawMetadata(frontmatter)` 抽出 OpenClaw 扩展元数据
- `resolveSkillInvocationPolicy(frontmatter)` 抽出调用策略
- 最后组装成 `SkillEntry`

这一步收集的来源也不是单一目录。更准确地说，skills roots 的定义发生在运行时代码和配置层，而不是写在 SystemPrompt 里。

`src/agents/skills/workspace.ts` 和 `src/agents/skills/refresh.ts` 会把多个本地来源合并进统一 skill 视图，至少包括：

- bundled skills
- managed skills：`CONFIG_DIR/skills`
- 个人目录：`~/.agents/skills`
- 项目目录：`<workspace>/.agents/skills`
- 工作区目录：`<workspace>/skills`
- plugin 提供的 skill 目录

所以更准确地说，OpenClaw 的 skills 是 file-backed、local-first 的：

```text
先在 skills roots 里发现 SKILL.md
 -> 解析成 SkillEntry
 -> 构建 SkillSnapshot / skillsPrompt
 -> attempt 再把 skillsPrompt 放进 SystemPrompt
```

而不是：

```text
每次调用时临时联网下载 skill 本体
```

`SkillEntry` 的生成时机也不是只有一种，源码里至少有三条主线：

1. **新 session 初始化 snapshot 时**
   - `src/agents/agent-command.ts:908-918`
   - 会调用 `buildWorkspaceSkillSnapshot(...)`
   - 而 `buildWorkspaceSkillSnapshot(...)` 内部又会通过 `resolveWorkspaceSkillPromptState(...) -> loadSkillEntries(...)` 先把磁盘 skills 解析成 `SkillEntry`

2. **后续 turn 发现 snapshot 过期时**
   - `src/auto-reply/reply/session-updates.ts:182-247`
   - 会比较 `skillsSnapshot.version`
   - 如果版本落后，就重新 `buildWorkspaceSkillSnapshot(...)`
   - 这里也会重新从磁盘把 skills 整理成 `SkillEntry`

3. **attempt 缺少可复用 snapshot 时的兜底加载**
   - `src/agents/pi-embedded-runner/skills-runtime.ts:4-18`
   - 如果当前 run 没拿到 `skillsSnapshot`，或者 snapshot 没有 `resolvedSkills`
   - 就会调用 `loadWorkspaceSkillEntries(...)`
   - 直接在 attempt 开头把磁盘 skills 解析成 `SkillEntry[]`

所以如果只问“什么时候把磁盘 skill 整理成 `SkillEntry`”，最准确的回答是：

> 不是只有启动时才做一次，而是在“需要构建或重建 snapshot”以及“attempt 缺少可复用 snapshot”这两类场景下，运行时按需把磁盘上的 `SKILL.md` 重新解析成 `SkillEntry`。

### 5.5 第二阶段：会话缓存与 `SkillSnapshot`

第二阶段的目标是把“当前会话真正需要的 skills 结果”固定下来，避免每轮都重新扫描和重建。

`SkillSnapshot` 的结构定义在 `src/agents/skills/types.ts:82-88`，里面最关键的是：

- `prompt`
- `skills`
- `skillFilter`
- `resolvedSkills`
- `version`

这说明 snapshot 不是完整的 `SkillEntry` 复制品，而是“面向会话复用”的精简形态。

构建点在 `src/agents/skills/workspace.ts:614-631`：

- `buildWorkspaceSkillSnapshot(...)` 会基于当前 workspace、config、eligibility、skillFilter 生成 snapshot
- snapshot 里已经带有 prompt 文本和精简 skills 元数据

而真正把它写入会话的是 `src/agents/agent-command.ts:908-937`：

- 新 session 或缺少 `skillsSnapshot` 时，会调用 `buildWorkspaceSkillSnapshot(...)`
- 然后把结果写入 `sessionEntry.skillsSnapshot`

所以这一步的主线是：

```text
SkillEntry
 -> buildWorkspaceSkillSnapshot(...)
 -> sessionEntry.skillsSnapshot
```

这里还要补一个很关键的细节：

> `SkillSnapshot` 是“长期可复用的会话缓存”，但它不是一个永远不变的冻结产物。

从结构上就能看出来这一点。`SkillSnapshot` 里除了 `prompt` 和 `skills`，还显式带了：

- `skillFilter`
- `version`

其中：

- `skillFilter` 说明 snapshot 不是脱离配置独立存在的，它绑定了“这次会话允许哪些 skills”的筛选结果
- `version` 说明 snapshot 不是只要写进 session 就永不重建，它带着一层失效/刷新语义

这一层刷新机制主要在两个地方：

1. `src/agents/skills/refresh.ts`
   - `getSkillsSnapshotVersion(...)`
   - `ensureSkillsWatcher(...)`
   - `bumpSkillsSnapshotVersion(...)`

2. `src/auto-reply/reply/session-updates.ts:182-249`
   - 每轮会先取当前 `snapshotVersion`
   - 再判断缓存里的 `skillsSnapshot.version` 是否落后
   - 如果落后，就重新 `buildWorkspaceSkillSnapshot(...)`

也就是说，OpenClaw 对 Skills 采用的不是“每轮无脑全量重扫”，而是：

```text
平时复用 session 里的 SkillSnapshot
 -> 发现版本失效时再重建
 -> 把新 snapshot 回写到 session
```

这套机制本质上是一种 **version-based refresh**。

这里最好再把三个容易混在一起的层分开：

- **技能内容**
  - 指磁盘上的 `SKILL.md` 正文和 frontmatter
  - 它决定模型最终看到的技能说明、调用建议和元数据
- **技能配置**
  - 指 `openclaw.json` 里的 `skills.entries.*`
  - 它决定技能是否启用、是否有 `apiKey` / `env`、某些 eligibility 条件是否满足
- **技能快照**
  - 指 `sessionEntry.skillsSnapshot`
  - 它是“当前 session 这次真正可用的 skills 结果缓存”，不是 skill 文件本身，也不是配置文件本身

如果不先把这三层拆开，后面就很容易把“改了 skill 文件”“在控制台里改开关”“下一轮 prompt 变了”误当成同一件事。

#### 5.5.1 技能内容的更新入口：`SKILL.md` 与 skill 目录本身

Skill 的“内容”首先来自磁盘上的 skill 目录，而不是某个数据库表或 Web 表单。

对 OpenClaw 来说，最典型的 skill 内容来源是：

- bundled skills
- `CONFIG_DIR/skills`
- `~/.agents/skills`
- `<workspace>/.agents/skills`
- `<workspace>/skills`
- `skills.load.extraDirs`
- plugin 暴露的 skill 目录

这些来源在 `src/agents/skills/refresh.ts:59-95` 和 `src/agents/skills/workspace.ts:465-479` 都能看到。

所以如果说“更新一个 skill 的内容”，最接近源码真实语义的动作其实是：

- 直接修改某个 skill 目录里的 `SKILL.md`
- 在被 OpenClaw 监控的 skills roots 里新增或删除一个 skill 目录
- 通过插件带入新的 skill 目录

也就是说，Skills 的内容更新入口首先是 **文件系统里的 `SKILL.md` 和 skill 目录**。

这里也要明确一个和 memory 很不一样的边界：

> OpenClaw 当前没有看到类似 `memory flush`、`compaction summary -> durable memory` 这种“自动沉淀并改写技能内容”的内建闭环。

也就是说，Skills 在核心语义上不是“会自我积累、自我提炼的知识库”，而更像“由文件维护的技能包”。

从这轮源码核对看，OpenClaw 对 skill 包内容的自动流程主要是：

- **发现和重新加载**
- **复制和同步**
- **依赖安装**

而不是：

- 自动重写 `SKILL.md`
- 自动整理 `references/`
- 自动生成或改写 `scripts/`

这里尤其要区分 `syncSkillsToWorkspace(...)`。见 `src/agents/skills/workspace.ts:764-820`：

- 它会先 `loadSkillEntries(...)`
- 然后删除目标 workspace 下的 `skills/` 副本目录
- 再把当前应生效的 skill 目录复制到目标位置

所以这条链是在做 **同步副本**，不是在演化或编辑原始 skill 包本体。

这里还要再纠正一个很容易混的点：

> `skills.install` 不是通用的“在线编辑或拉取 `SKILL.md` 正文”的入口。

从 `src/gateway/server-methods/skills.ts:114-145` 和 `src/agents/skills-install.ts:392-420` 看，Gateway 的 `skills.install` 会：

- 先找到一个已经存在的 `SkillEntry`
- 再读取它 frontmatter / metadata 里声明的 installer spec
- 然后执行 brew / node / go / uv / download 之类的安装命令

所以它更接近：

- “给已有 skill 安装依赖或外部 CLI”

而不是：

- “把一个新的 `SKILL.md` 正文写进系统”

如果是把一个全新的 skill 包放进 OpenClaw，可从架构上理解成：

- 该 skill 目录被放进某个 skills root
- 或者通过插件暴露进来
- 然后被 `loadWorkspaceSkillEntries(...)` 发现并解析

#### 5.5.2 技能配置的更新入口：`skills.update` 与 `openclaw.json`

Skill 的“配置层”是另一条链，它不改 `SKILL.md` 正文。

这条链在 `src/gateway/server-methods/skills.ts:146-184` 很清楚。控制台侧的 `skills.update` 主要写的是：

- `skills.entries.<skillKey>.enabled`
- `skills.entries.<skillKey>.apiKey`
- `skills.entries.<skillKey>.env`

也就是说，Web 控制台更像：

- 技能状态与运行配置入口
- 技能启用/禁用入口
- 技能密钥与环境变量配置入口

而不是：

- 通用的 skill 文本编辑器

这也和控制台文档里的描述一致：`Skills: status, enable/disable, install, API key updates`，见 `docs/web/control-ui.md:79`。

如果把它翻成更准确的架构表述：

- **技能内容入口**：`SKILL.md` / skill 目录 / plugin skill 目录
- **技能配置入口**：`openclaw.json` 的 `skills.entries.*`，以及控制台上的 `skills.update`

两者都可能影响“下一轮技能是否可用”，但影响的层级不同：

- 改 `SKILL.md` 会改变技能说明、metadata、prompt 内容
- 改 `skills.entries.*` 会改变技能 eligibility、环境注入和开关状态

这里可以把最常见的 `enabled=false` 单独说明一下，因为它最容易和“物理卸载”混淆。

当 `skills.entries.<skillKey>.enabled = false` 时，核心效果不是删除 skill 文件，而是把这个 skill 从“运行时可用集合”里过滤掉。

源码里这一点非常直接，见 `src/agents/skills/config.ts:71-95`：

- `shouldIncludeSkill(...)` 会先读取 `resolveSkillConfig(...)`
- 如果 `skillConfig?.enabled === false`
- 就直接 `return false`

这会连带产生几个结果：

- 它不会进入 eligible skill entries
- 它不会进入新的 `SkillSnapshot`
- 它不会进入 `skillsPrompt`
- 它不会再注册成 skill slash command
- 状态页里会显示为 disabled / not eligible，见 `src/agents/skills-status.ts:177-203`

所以更准确地说：

> `enabled=false` 是“逻辑禁用”，不是“物理卸载”。

这里还有一个 session 级边界也要说清楚：

- **新 session** 一定会按当前配置重新构建 snapshot，因此会立即看不到这个 skill，见 `src/agents/agent-command.ts:908-920`
- **已有 session** 如果仍然持有旧的 `skillsSnapshot`，不保证在配置一保存后立刻失效

原因是 `enabled=false` 这类配置变化，和 `SKILL.md` 文件变更不同；从这轮源码核对看，我没有看到它像 watcher 那样直接触发 `bumpSkillsSnapshotVersion(...)`。

所以更稳妥的理解是：

- `enabled=false` 会影响**后续 snapshot 重建结果**
- 但对当前已经缓存旧 `skillsSnapshot` 的 session，通常要等下一次 snapshot 重建后才完全体现出来

#### 5.5.3 Skills 的“热重载”本质：监听变化后刷新 `SkillSnapshot`

这一节最重要的结论只有一句：

> OpenClaw 对 Skills 的“热重载”，不是像 memory 那样重建检索索引，而是让 session 里的 `skillsSnapshot` 失效，并在后续 turn 重建它。

这里要先和 memory 做一个硬区分：

- memory 的主线更像：`文件变化 -> dirty -> sync() -> 刷新索引`
- skills 的主线更像：`SKILL.md 变化 -> version bump -> 重建 SkillSnapshot`

也就是说，Skills 刷新的对象不是数据库索引，而是 `sessionEntry.skillsSnapshot` 这份会话级缓存。

**第一步：watcher 监听 skill 文件变化**

`ensureSkillsWatcher(...)` 会给 skills roots 挂上 `chokidar` watcher，见 `src/agents/skills/refresh.ts:132-201`。

默认纳入监控的来源包括，见 `src/agents/skills/refresh.ts:59-95`：

- `<workspace>/skills`
- `<workspace>/.agents/skills`
- `CONFIG_DIR/skills`
- `~/.agents/skills`
- `skills.load.extraDirs`
- plugin 暴露的 skill dirs

watcher 只盯这些 roots 下的 `SKILL.md`，并在 `add / change / unlink` 后做：

- `awaitWriteFinish`
- debounce
- `bumpSkillsSnapshotVersion(...)`

这里要特别注意一个边界：

> 当前 Skills watcher 监听的不是“整个 skill 目录”，而是 `SKILL.md` 本身。

从 `src/agents/skills/refresh.ts:84-95` 可以直接看到，watch targets 只会生成：

- `<root>/SKILL.md`
- `<root>/*/SKILL.md`

这意味着：

- 改 `SKILL.md` 会触发 watcher
- 新增/删除带 `SKILL.md` 的 skill 目录会触发 watcher
- 但如果只改 skill 目录里的其他辅助文件，而 `SKILL.md` 没变，这套 watcher 默认不会因此 bump `skillsSnapshotVersion`

所以文件侧真正发生的事不是“立刻重建 prompt”，而是：

```text
SKILL.md 变更
 -> watcher 感知到 add / change / unlink
 -> bumpSkillsSnapshotVersion(...)
```

**第二步：后续 turn 检查 session 里的 `skillsSnapshot` 是否过期**

真正决定“要不要刷新 session 里的 snapshot”的逻辑，在 `src/auto-reply/reply/session-updates.ts:182-247`。

这里会做两件事：

1. 读取当前 workspace 的 `snapshotVersion`
2. 比较 `sessionEntry.skillsSnapshot.version`

如果旧 snapshot 的 version 落后，就会重新：

- `buildWorkspaceSkillSnapshot(...)`
- 把结果写回 `nextEntry.skillsSnapshot`
- 再通过 `persistSessionEntryUpdate(...)` 写回 session store

所以这里不是只算一份临时值，而是会真正更新 Session 中保存的 `skillsSnapshot`。

更贴近源码的伪代码是：

```text
ensureSkillSnapshot()
 -> snapshotVersion = getSkillsSnapshotVersion(workspaceDir)
 -> shouldRefreshSnapshot =
      snapshotVersion > 0 &&
      sessionEntry.skillsSnapshot.version < snapshotVersion

 -> if shouldRefreshSnapshot:
      skillsSnapshot = buildWorkspaceSkillSnapshot(...)
      nextEntry.skillsSnapshot = skillsSnapshot
      persistSessionEntryUpdate(...)
```

**第三步：下一次 attempt 用新的 `skillsSnapshot` 重建 system-side context**

attempt 开始时，运行时会从 `params.skillsSnapshot` 取 snapshot，见 `src/agents/pi-embedded-runner/run/attempt.ts:1426-1446`。

这份 snapshot 会直接影响两部分：

- `applySkillEnvOverridesFromSnapshot(...)`
  - 决定 skill 相关 env 注入，见 `src/agents/pi-embedded-runner/run/attempt.ts:1431-1439`
- `resolveSkillsPromptForRun(...)`
  - 决定 `skillsPrompt` 文本，见 `src/agents/pi-embedded-runner/run/attempt.ts:1441-1446`

随后 `skillsPrompt` 会被放进 system prompt 组装参数里，见 `src/agents/pi-embedded-runner/run/attempt.ts:1717-1734`。

所以完整链路其实是：

```text
SKILL.md 变化
 -> watcher bumpSkillsSnapshotVersion(...)
 -> 后续 turn 的 ensureSkillSnapshot(...)
 -> Session 中的 skillsSnapshot 被重建并回写
 -> 下一次 attempt 读取新的 skillsSnapshot
 -> resolveSkillsPromptForRun(...)
 -> 重建 system-side context / system prompt
```

**一个关键边界：不会中途改正在运行的 attempt**

这里最容易误解的一点是：

> watcher 监听到 skill 变化后，不会把“当前已经开始执行的同一个 attempt”中途热替换掉。

原因很简单：

- system prompt 是 attempt 开头组好的
- `skillsPrompt` 也是在 attempt 开头算好的

所以更准确的说法是：

- **当前正在跑的 attempt** 继续用旧 snapshot
- **下一次 turn / 下一次 attempt** 才会吃到新的 snapshot

这也是为什么，“Skills 热重载”更准确地说是：

> **让旧 `SkillSnapshot` 在下一轮失效，并让下一次 attempt 用新 snapshot 重建 system-side context。**

#### 5.5.4 Skills 没有像 memory 那样的“自动沉淀 / 自我迭代”内建闭环

这一点最好单独说清楚，不然很容易把 Skills 和 memory 的行为混在一起。

对 Skills 来说：

- **会自动刷新的**，是 `SkillSnapshot`
- **会被自动发现的**，是 `SKILL.md` 的增删改
- **不会被核心自动改写的**，是 skill 包内容本体（`SKILL.md` / `references/` / `scripts/`）

也就是说，OpenClaw 当前没有看到类似 memory 那种：

- 自动从对话里沉淀 durable memories
- 自动把压缩结果写回长期知识页
- 自动重写知识文档以形成“下一轮更聪明的知识库”

Skills 更像：

- 文件维护的技能包
- watcher + version bump 驱动的快照刷新
- 按需 `read` / 执行辅助资源

而不是：

- 会自我积累、自我提炼、自我改写内容的知识闭环

`references/`、`scripts/` 这类辅助目录当然可以被 agent 或人手动编辑，但这属于普通文件编辑能力，不是 Skills 子系统自带的“自动演化机制”。

而且从 watcher 逻辑看，`src/agents/skills/refresh.ts:84-95` 只监听 `SKILL.md`：

- `<root>/SKILL.md`
- `<root>/*/SKILL.md`

所以：

- 改 `SKILL.md` 会触发技能热重载链
- 改 `references/`、`scripts/` 本身不会直接 bump `skillsSnapshotVersion`

这些辅助文件的变化，只有在后续真的被 `read`、执行或重新引用时，才会体现在具体任务执行里；它们不会像 memory 文档那样被内建流程自动沉淀成“下一轮更聪明的技能包”。

**再补一个边界：文件变化和配置变化的刷新语义不完全一样**

和热重载最直接相关的是**文件系统层面的变化**：

- 改 `SKILL.md`
- 新增 skill 目录
- 删除 skill 目录

这些变化会走 watcher -> version bump 这条链。

而配置层面的变化，例如：

- `skills.entries.*.enabled`
- `skills.entries.*.apiKey`
- `skills.entries.*.env`
- `skillFilter`
- `skills.load.extraDirs`

更多是影响“下一次 `buildWorkspaceSkillSnapshot(...)` 的输入条件”。  
从源码上，我能明确确认：

- **新 session** 一定会按当前状态构建新的 snapshot，见 `src/agents/agent-command.ts:908-920`
- **后续 turn** 在 `session-updates` 这条主线上也能按 version 刷新旧 snapshot，见 `src/auto-reply/reply/session-updates.ts:182-247`

因此最稳妥的结论是：

- Skills 的热重载核心是 `SkillSnapshot` 刷新
- Session 中的 `skillsSnapshot` 会在后续 turn 被更新
- 下一次 attempt 会用新的 `skillsSnapshot` 重建 system-side context
- 但不是“文件一改，当前 attempt 立刻原地换 prompt”

### 5.6 第三阶段：提示词文本与 `skillsPrompt`

第三阶段的目标是把 skills 转成模型真正能读懂的提示词文本。

这条链主要发生在 `src/agents/skills/workspace.ts` 和 `src/agents/system-prompt.ts`：

- `buildWorkspaceSkillsPrompt(...)`
- `resolveSkillsPromptForRun(...)`
- `buildSkillsSection(...)`

运行时会优先走 snapshot：

- `resolveSkillsPromptForRun(...)` 先尝试读取 `skillsSnapshot.prompt`，见 `src/agents/skills/workspace.ts:694-711`
- 如果 snapshot 不可用，才会回退到按 entries 重新构建 prompt

这里要特别澄清一个容易混淆的点：

- `SkillSnapshot.prompt` 不是另一份独立于技能目录之外的 prompt
- 它通常就是那段已经渲染好的 skills catalog 文本缓存
- 而 `<available_skills>` 正是这段文本里的核心结构之一

也就是说，更准确的关系是：

```text
SkillSnapshot.prompt
 = 已经渲染好的 skills prompt
 = 包含 <available_skills> ... </available_skills> 的那段文本
```

最后 `src/agents/system-prompt.ts:20-35` 的 `buildSkillsSection(...)` 会把它包进 `## Skills (mandatory)` 这一段，并告诉模型：

- 先扫描 `<available_skills>`
- 如果只有一个 skill 明显匹配，先用 `read` 去读对应 `SKILL.md`
- 不要一开始就读太多 skill

这里也能反过来验证前面的边界：

- `skills roots` 是发现规则，属于 runtime loader
- `skillsPrompt` 是这些发现结果的提示词投影
- `SystemPrompt` 只消费 `skillsPrompt`，不会重新定义 skills 放在哪些目录

这里还有一个重要细节：skills prompt 并不总是完整格式。

- 正常情况下会输出完整的技能目录
- 如果字符预算不够，会退化成 compact 格式
- compact 格式只保留 `name + location`，见 `src/agents/skills/workspace.ts:543-560`

所以第三阶段的主线是：

```text
SkillSnapshot.prompt
 -> resolveSkillsPromptForRun(...)
 -> buildSkillsSection(...)
 -> SystemPrompt
```

### 5.7 为什么要分成这三种形态

这正是 OpenClaw Skills 模块最容易看乱的地方。

它之所以不是“一个 skill 文件直接塞进 prompt”，是因为这三步解决的是三个不同问题：

- `SkillEntry`：解决“怎么发现、校验和筛选技能”
- `SkillSnapshot`：解决“怎么把当前会话的 skills 结果缓存下来”
- `skillsPrompt`：解决“怎么把技能目录安全、压缩地送进模型上下文”

所以这三种形态不是重复数据，而是同一份技能知识在不同阶段的投影。

### 5.8 Plugin skills 是主线的一个来源，不是另一套系统

`src/agents/skills/plugin-skills.ts` 的作用，不是把 plugin 变成 skill，而是把 plugin 暴露的 skill 目录接进这条主线。

它会：

- 从 plugin manifest registry 读取插件 skills 声明
- 根据插件启用状态过滤
- 根据 memory slot、ACP 开关等条件筛选
- 验证 skill 路径存在且未越界

然后这些 plugin skills 会像其它本地 skills 一样，被并入 `loadWorkspaceSkillEntries(...)` 的结果里。

所以更准确的说法是：

- plugin 是 skills 的一个来源
- plugin skills 是动态发现 / 动态挂载
- 但它们进入系统后的主线，仍然是 `SkillEntry -> SkillSnapshot -> skillsPrompt`

### 5.9 `Skill install` 安装的通常不是 skill 本体

这一步不是 Skills 主线的一部分，而是依赖准备。

和插件不同，`Skill install` 在 OpenClaw 里更多是“安装 skill 所需依赖”，不是“安装 skill 本体 markdown 文件”。

源码里的主要入口有两个：

- onboarding 场景：`src/commands/onboard-skills.ts`
- Gateway 方法：`src/gateway/server-methods/skills.ts` 中的 `skills.install`

它们最终都会调用 `src/agents/skills-install.ts` 里的 `installSkill(...)`。

从 `src/agents/skills/types.ts:3-17` 和 `src/agents/skills/frontmatter.ts` 可以看到，当前支持的安装类型是：

- `brew`
- `node`
- `go`
- `uv`
- `download`

所以这里安装的是：

- 可执行工具
- 包管理器依赖
- 下载物/二进制

不是把 `SKILL.md` 本体现拉现用。

### 5.10 “用完就删”的印象来自 workspace/sandbox 副本同步

这个印象多半来自 `src/agents/skills/workspace.ts` 里的 `syncSkillsToWorkspace(...)`。

它会：

- 重新解析源 workspace 的可用 skills
- 删除目标 workspace 下的 `skills/` 副本目录
- 再把当前应生效的 skills 复制过去

所以它删除的是目标 workspace 或 sandbox 里的同步副本，而不是 managed skills、plugin skills 或用户原始技能目录本体。

一句话总结 Skills 这一节的主线：

```text
先从本地和 plugin 来源发现 skills
 -> 解析成 SkillEntry
 -> 在 session 中缓存成 SkillSnapshot
 -> 在 run 前取出 skillsPrompt
 -> 注入 SystemPrompt
```

## 6. Tools：执行能力层

### 6.0 先抓主线：OpenClaw 的 tool calling 到底是怎么跑起来的

读这一节前，最好先把下面这条主线看清楚。你前面问到的几个问题：

- LLM 原生的 tool calling 是什么
- system-side context 中的 tool list 文本摘要 和 tool schemas JSON 有什么区别
- tool list、tool schema、代码中的真实函数是怎么关联起来的
- `memory_search` 这类工具是怎么被调用的
- `read`、`write`、`exec` 这三个基础工具来自哪里
- LLM 发起 `tool_call` 后，OpenClaw 怎么按工具名找到真实执行函数

其实都可以落到同一条链上。

#### 1. 先看最小闭环：原生 tool calling

原生 tool calling 最粗略的形状就是：

```text
messages + system prompt + tools[]
 -> model
 -> assistant 正常回答
    或 assistant 发出 tool_call(name, arguments)
 -> runtime 执行对应工具
 -> tool_result 回灌给模型
 -> 模型继续下一步
```

这里最重要的边界是：

- 发起 `tool_call` 的是模型
- 真正执行工具的，是运行时
- 工具本身只是“被注册的可执行能力”

所以更准确的说法是：

> 模型负责“选择工具并给出参数”，runtime 负责“按名字找到工具并执行”。

#### 2. OpenClaw 里的同一个 tool，会同时投影成三层

对 OpenClaw 来说，一个工具在代码里通常长这样：

```ts
{
  name,
  description,
  label,
  parameters,
  execute,
}
```

这几个字段的职责并不一样：

- `name`
  - 工具主标识符
  - system prompt 里左边显示什么名字、模型 `tool_call.name` 写什么、runtime 按什么键匹配，主要都靠它
- `description`
  - 工具用途说明
  - 常常会进入 tool list 文本摘要
- `label`
  - 更偏展示层的人类可读短标签
  - 在 OpenClaw 里通常不是主 dispatch key
- `parameters`
  - 结构化参数 schema
  - 决定 tool schemas JSON 长什么样
- `execute`
  - 真正执行这次工具调用的函数

因此，最准确的口径不是“同一个 tool 有三套并列输入”，而是：

- **两层真实输入**
  - prompt 文本里的 tool list 文本摘要
  - runtime 里的 `tools[]`
- **一层报告视图**
  - `/context list` 会把 `tools[]` 再拆成 `Tool schemas (JSON)` 和 `Tools:` 这两种展示标签

如果只看 tool object 本身，它确实会投影成下面几部分：

```text
tool object
= { name, description, label, parameters, execute }

name
 -> prompt 里的工具名
 -> model 发出的 tool_call.name
 -> runtime dispatch key

description / label
 -> prompt 里的工具摘要文本

parameters
 -> tool schemas JSON

execute
 -> 真实执行函数
```

#### 3. 为什么一轮 system-side 输入里同时会出现 tool list 文本摘要 和 `tools[]`

这是最容易被高层框架抽象掉、也最容易被混成一件事的地方。

这里要先把关系说死，不然 `tools[]` 和 `Tool schemas (JSON)` 会看起来像突然换了一个词：

- **架构层**
  - `tool list 文本摘要` 是 `SystemPrompt` 里的一段文本
  - `tools[]` 是 runtime 里的结构化工具集合
- **报告层**
  - `/context list` 不会把整个 `tools[]` 原样打印出来
  - 它会把 `tools[]` 拆成两种更适合阅读的标签：
    - `Tool schemas (JSON)`：统计 `tools[]` 里 schema 的成本
    - `Tools:`：打印 `tools[]` 里每个工具的名字

所以，如果在这一节讨论“真实输入是什么”，应该用：

- `tool list 文本摘要`
- `tools[]`

如果在讨论 `/context list` 这张报告页里怎么显示，才会看到：

- `Tool schemas (JSON)`
- `Tools:`

在这个前提下，再看两层真实输入的区别就清楚了：

| 层 | 架构层名字 | `/context list` 里的常见标签 | 长什么样 | 主要给谁看 | 解决什么问题 |
| --- | --- | --- | --- | --- | --- |
| 提示词摘要层 | tool list 文本摘要 | `Tool list (system prompt text)` | `- read: Read file contents` | 模型 | “现在有哪些工具，大概做什么，什么时候可能该用它” |
| 结构化工具层 | `tools[]` | `Tool schemas (JSON)`、`Tools:` | `{ name, description, parameters, execute }[]` | 模型 + runtime/provider | “这一轮到底有哪些工具；调用时 arguments 必须长什么样；执行时该 dispatch 到哪一个 handler” |

更直观地说：

- **文本摘要**回答的是：`什么时候、为什么用这个工具`
- **`tools[]`**回答的是：`这一轮到底有哪些结构化工具可用`
- **`Tool schemas (JSON)`**则只是 `/context list` 对 `tools[]` 里 schema 成本的报告标签

也就是说，OpenClaw 这一轮至少有两层真实输入：

1. **prompt 文本上下文**
   - `system prompt`
   - `message history`
   - `skillsPrompt`
   - context files 文本
   - tool list 的文本摘要

2. **结构化 `tools[]` 输入**
   - `tools[]`
   - 每个 tool 的 `parameters schema`
   - 其他与 tool calling 相关的结构化字段

这里的 `tools[]` 是分析术语。  
放回 OpenClaw 代码里，更贴近的具体形态是：

```text
effectiveTools
 -> 经toToolDefinitions(...)
 -> 变成ToolDefinition[] 
 -> 再经 splitSdkTools(...)
 -> 作为customTools
 -> 传给createAgentSession(...)
```

如果把 `context` 狭义理解成“拼进 prompt 的那段文字”，那么：

- tool list 文本摘要在 context 里
- `tools[]` 不在这段 prompt 文本里

如果把 `context` 广义理解成“这一轮送给模型/runtime 的全部输入”，那么：

- `messages + system prompt + tools[]`

都属于这轮的广义上下文。

这里还要补一个很容易问出来、但也很重要的判断：

> 既然 `tools[]` 里已经有 `name / description / parameters`，为什么还要保留一层 tool list 文本摘要？

答案是：两者有重叠，但并不等价。  
更准确地说，OpenClaw 这里保留的是一种**有意的轻度冗余**：

- `tools[]`
  - 更偏**调用契约层**
  - 重点回答“这一轮有哪些结构化工具、参数怎么写、runtime 怎么调”
- tool list 文本摘要
  - 更偏**行为引导层**
  - 重点回答“这一轮有哪些工具、它们大概做什么、模型什么时候应该优先想到它们”

所以 `tool list` 不是因为 `tools[]` 不够形成 tool calling 协议，而是为了让模型更稳地理解和选择这批工具。

OpenClaw 的 prompt 侧投影发生在：

- `src/agents/pi-embedded-runner/system-prompt.ts:56-77`
- `src/agents/system-prompt.ts:239-339`

这里会把当前这轮可用工具投影成：

- `toolNames = params.tools.map((tool) => tool.name)`
- `toolSummaries = buildToolSummaryMap(params.tools)`

其中 `buildToolSummaryMap(...)` 定义在 `src/agents/tool-summaries.ts:3-12`，优先取：

- `tool.description`
- 没有 description 时，退回 `tool.label`

但对 `read`、`write`、`exec` 这类 core tools，OpenClaw 还额外定义了一份更短的 `coreToolSummaries`，见 `src/agents/system-prompt.ts:239-272`。所以 prompt 里经常看到的是：

```text
- read: Read file contents
- write: Create or overwrite files
- exec: Run shell commands (pty available for TTY-required CLIs)
```

这里左边名字来自 `tool.name`，右边短摘要优先来自 `coreToolSummaries`，不一定等于原始 `tool.description`。

相比之下，runtime 侧真正持有的是 `tools[]`。而 `/context list` 里显示成 `Tool schemas (JSON)` 的，只是 `tools[]` 里 `tool.parameters` 这部分的预算统计；它不是 `tools[]` 的完整同义词。进入 session 前，OpenClaw 还会对这批工具做 provider 兼容归一化，见 `src/agents/pi-tools.ts:578-588`、`src/agents/pi-tools.schema.ts:59-160`。

#### 4. 一个具体例子：`memory_search`

`memory_search` 是最适合解释 OpenClaw tool calling 的例子之一。

在 `src/agents/tools/memory-tool.ts:79-132`，OpenClaw 创建了这样一个工具对象：

```ts
{
  label: "Memory Search",
  name: "memory_search",
  description: "Mandatory recall step: semantically search MEMORY.md + memory/*.md ...",
  parameters: MemorySearchSchema,
  execute: async (...) => { ... }
}
```

它的 `parameters` 在 `src/agents/tools/memory-tool.ts:13-17` 定义，大意是：

```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string" },
    "maxResults": { "type": "number" },
    "minScore": { "type": "number" }
  },
  "required": ["query"]
}
```

所以三层关系就很清楚了：

1. **tool list 文本摘要**
   - 左边名字来自 `tool.name = "memory_search"`
   - 右边摘要来自 `tool.description`
   - 因为它不是 `coreToolSummaries` 里那类硬编码 core tool

2. **tool schema JSON**
   - 来自 `MemorySearchSchema`
   - 规定 `query` 必填，`maxResults/minScore` 可选

3. **真实执行函数**
   - 在 `execute(...)` 里真正调用 `memory.manager.search(...)`
   - 见 `src/agents/tools/memory-tool.ts:93-126`

这也是为什么 `memory_search` 很适合解释 Agentic RAG：

- prompt 会引导模型“该查记忆时先查”
- schema 会约束 arguments
- execute 会真的去跑 memory retrieval

#### 5. 另一个例子：`read`、`write`、`exec` 这三个基础工具

这三个工具都属于 OpenClaw 的基础执行能力，但来源并不完全相同。

##### `read` / `write` / `edit`

这组工具的底子来自 `@mariozechner/pi-coding-agent` 的 coding tools，然后被 OpenClaw 包装成更适合自己运行时的版本，见 `src/agents/pi-tools.ts:1-2`、`src/agents/pi-tools.ts:370-407`。

例如：

- `read`
  - 上游 `createReadTool(...)` 生成基础版本
  - 再由 `createOpenClawReadTool(...)` 包装，增加参数兼容、分页读取、图片结果清洗等逻辑
  - 见 `src/agents/pi-tools.read.ts:639-668`
- `write`
  - 不直接裸用上游对象，而是根据 host/sandbox 场景重新创建 host/sandbox 版本
  - 见 `src/agents/pi-tools.read.ts:607-629`
- `edit`
  - 同样会按 host/sandbox 拆分，并附加恢复逻辑
  - 见 `src/agents/pi-tools.read.ts:613-637`

因此，更准确的说法不是“read/write 完全是底层 framework tools”，而是：

> 它们来自 framework coding tools，但真正进入 OpenClaw runtime 的，已经是 OpenClaw 重新包装过的版本。

##### `exec`

`exec` 不属于上面这条“文件工具包装”主线。  
OpenClaw 会先从上游 `codingTools` 起步，但显式跳过上游的 `bash/exec` 槽位，再注入自己的 `exec`，见 `src/agents/pi-tools.ts:389-415`。

真正的实现来自：

- `src/agents/bash-tools.exec.ts:151-207`

它是一个重量级 runtime tool，负责：

- shell 命令执行
- host / sandbox 执行环境切换
- background continuation
- approval / ask 模式
- PTY
- 安全策略和 safe bins

所以：

- `read` / `write` / `edit` 更像“文件系统工具”
- `exec` 更像“进程与命令执行工具”

它们都很基础，但不是同一条来源链。

#### 6. LLM 发起 `tool_call` 后，OpenClaw 怎么找到真实函数并执行

你可以把这条链记成：

```text
tool_call.name
 -> 匹配已注册的 ToolDefinition.name
 -> 调这个 ToolDefinition.execute(...)
 -> ToolDefinition.execute 再去调原始 tool.execute(...)
```

关键点有三步。

**第一步：把 `effectiveTools` 转成 `ToolDefinition`**

OpenClaw 在 `src/agents/pi-embedded-runner/tool-split.ts:8-15` 里，把所有工具统一走：

```text
effectiveTools
 -> toToolDefinitions(tools)
 -> customTools
```

这里很关键的一点是：

- `builtInTools` 当前返回空数组
- OpenClaw 的工具主线都走 `customTools`

**第二步：`toToolDefinitions(...)` 把名字和执行函数提前绑定**

`src/agents/pi-tool-definition-adapter.ts:113-168` 做的事，本质上就是：

```ts
return {
  name,
  label,
  description,
  parameters,
  execute: async (...) => {
    const rawResult = await tool.execute(...)
    ...
  }
}
```

注意这里不是“之后再按名字去反射 import 某个函数文件”，而是：

- 每个 `ToolDefinition` 在创建时
- 就已经通过闭包捕获了原始 `tool.execute`

因此运行时真正做的是：

> 按 `tool_call.name` 选中对应 `ToolDefinition`，再直接调用这个 definition 上已经绑定好的 `execute`。

**第三步：把 `ToolDefinition` 注册进 session runtime**

在 `src/agents/pi-embedded-runner/run/attempt.ts:1860-1898`，OpenClaw 调：

```ts
createAgentSession({
  tools: builtInTools,
  customTools: allCustomTools,
  ...
})
```

从这里开始，tool runtime 就已经拿到了一张完整的“工具注册表”：

- `name`
- `description`
- `parameters`
- `execute`

所以最简化地说：

```text
LLM 发出 tool_call(name="memory_search", arguments={...})
 -> runtime 用 name 匹配 ToolDefinition.name
 -> 调这个 ToolDefinition.execute(...)
 -> 这个 execute 再调原始 memory_search.execute(...)
 -> 返回 tool_result
 -> tool_result 回到会话消息流
 -> 模型继续下一步
```

因此你可以用一句最稳的话记住：

> OpenClaw 不是“临时按名字去找一个函数文件”，而是“先注册好 `name -> execute` 映射，再由 runtime 按 `tool_call.name` 选中并执行”。

#### 7. 为什么很多框架会把这些关系讲糊

很多框架会把 tool calling 包装成：

```text
注册一个方法
 -> 自动生成 name / description / schema
 -> 自动 dispatch
```

于是用户很容易只看到“注册函数”这一层，而看不到：

- prompt 摘要怎么来的
- schema 怎么来的
- provider 兼容性怎么处理
- runtime 到底怎么按名字匹配执行函数

OpenClaw 没有把这条链全部藏起来，而是显式展开成：

```text
tool object
 -> toolNames + toolSummaries
 -> SystemPrompt

tool object
 -> normalizeToolParameters(...)
 -> toToolDefinitions(...)
 -> createAgentSession(...)

tool_call.name
 -> ToolDefinition.name
 -> ToolDefinition.execute(...)
 -> tool.execute(...)
```

所以更准确地说，OpenClaw 的 Tools 范式是：

- prompt 侧保留“工具摘要”来帮助模型理解
- runtime 侧保留“结构化 tool definition”来保证调用稳定
- 中间再叠加 provider / policy / sandbox / plugin / MCP 这些运行时因素

如果只记一句话，这一节可以先记成：

> **同一个 tool object，会同时变成 prompt 里的工具摘要、runtime 里的 schema/execute，以及最终被 `tool_call.name` 命中的执行入口。**

### 6.1 Tools 的定位

`6.0` 已经把 tool calling 的闭环讲清楚了。这里开始，不再重复完整链路，而是把这条链拆成几层结构：

- 工具从哪里来
- 工具怎么进入 prompt
- 工具怎么进入 runtime
- runtime 怎么按 `tool_call.name` 找到真实执行函数
- provider / policy / schema compatibility 在哪里介入

所以这一节里，Tools 可以先简化理解成：

```text
多来源能力
 -> effectiveTools
 -> prompt 摘要
 -> runtime 注册
 -> 按 name 执行
```

### 6.2 Tools 的来源与汇合

OpenClaw 的工具系统不是单层定义，而是多来源汇合：

1. framework coding tools  
   主要来自 `@mariozechner/pi-coding-agent`

2. OpenClaw core tools  
   由 `src/agents/openclaw-tools.ts` 创建，例如：
   - `web_search`
   - `web_fetch`
   - `message`
   - `gateway`
   - `sessions_*`
   - `image_generate`

3. plugin tools  
   通过 `resolvePluginTools(...)` 注入，见 `src/agents/openclaw-tools.ts:224-253`

4. MCP / LSP tools  
   在运行时后段再并入 `effectiveTools`

因此，更准确的汇合主线是：

```text
framework tools
 + core tools
 + plugin tools
 + 可选 MCP / LSP tools
 -> effectiveTools
```

### 6.3 `read`、`write`、`exec` 这三个基础工具的来源并不完全相同

这三个工具都属于 OpenClaw 的基础执行能力，但来源不同。

#### `read` / `write` / `edit`

这组工具的底子来自 `@mariozechner/pi-coding-agent` 的 coding tools，然后被 OpenClaw 包装成更适合自己运行时的版本，见 `src/agents/pi-tools.ts:1-2`、`src/agents/pi-tools.ts:370-407`。

例如：

- `read`
  - 上游 `createReadTool(...)` 生成基础版本
  - 再由 `createOpenClawReadTool(...)` 包装
  - 见 `src/agents/pi-tools.read.ts:639-668`
- `write`
  - 根据 host / sandbox 场景重新创建 host / sandbox 版本
  - 见 `src/agents/pi-tools.read.ts:607-629`
- `edit`
  - 同样会按 host / sandbox 拆分，并附加恢复逻辑
  - 见 `src/agents/pi-tools.read.ts:613-637`

因此，更准确的说法不是“read/write 完全是底层 framework tools”，而是：

> 它们来自 framework coding tools，但真正进入 OpenClaw runtime 的，已经是 OpenClaw 重新包装过的版本。

#### `exec`

`exec` 不属于上面这条“文件工具包装”主线。  
OpenClaw 会先从上游 `codingTools` 起步，但显式跳过上游的 `bash/exec` 槽位，再注入自己的 `exec`，见 `src/agents/pi-tools.ts:389-415`。

真正的实现来自：

- `src/agents/bash-tools.exec.ts:151-207`

它是一个重量级 runtime tool，负责：

- shell 命令执行
- host / sandbox 执行环境切换
- background continuation
- approval / ask 模式
- PTY
- 安全策略和 safe bins

所以：

- `read` / `write` / `edit` 更像“文件系统工具”
- `exec` 更像“进程与命令执行工具”

### 6.4 Tools 是怎么进入 prompt 的

进入 prompt 的不是完整 tool schema，而是“工具名 + 工具摘要”。

在 `src/agents/pi-embedded-runner/system-prompt.ts:56-77`，`buildEmbeddedSystemPrompt(...)` 会把：

- `toolNames: params.tools.map((tool) => tool.name)`
- `toolSummaries: buildToolSummaryMap(params.tools)`

传给 `buildAgentSystemPrompt(...)`。

而 `buildToolSummaryMap(...)` 的逻辑在 `src/agents/tool-summaries.ts:3-12`，它主要从每个 tool 的：

- `description`
- 或 `label`

生成摘要。

最后 `src/agents/system-prompt.ts:302-339` 会把它们渲染成 `## Tooling` 下面的文本列表。对 core tools，还会优先使用 `coreToolSummaries` 里的短摘要，见 `src/agents/system-prompt.ts:239-272`。因此你通常会看到：

```text
- read: Read file contents
- write: Create or overwrite files
- exec: Run shell commands (pty available for TTY-required CLIs)
```

所以进入 prompt 的内容主要是：

- tool name
- tool summary / description
- 部分 core tools 的硬编码说明文本

不会进入 prompt 的则是：

- 完整 JSON schema
- `execute(...)` 实现
- 具体参数约束细节

### 6.5 Tools 是怎么进入 Agent runtime 的

同样从 `effectiveTools` 出发，runner 会继续做：

- `splitSdkTools(...)`
- `createAgentSession(...)`

其中 `splitSdkTools(...)` 在 `src/agents/pi-embedded-runner/tool-split.ts:8-15` 里写得很直白：

- `builtInTools` 当前返回空数组
- 所有 tools 都经 `toToolDefinitions(...)` 走 `customTools`

这意味着 OpenClaw 当前实际上是把 `effectiveTools` 整体转成统一的 `ToolDefinition`，再注册进 Agent session。

这一层传进去的就不只是名字了，而是：

- `name`
- `description`
- `parameters`
- `execute`

也就是完整的结构化工具定义。

### 6.6 LLM 发起 `tool_call` 后，runtime 怎么按名字找到真实函数

先给一个最容易记住的版本：

> **“加一个工具，只加一个 handler；循环不用动，新工具注册进 dispatch map 就行。”**

这句话在 OpenClaw 里基本成立，但要先把几个词翻译成源码里的真实对象：

- `handler`
  - 更接近原始 tool object 上的 `execute(...)`
- `dispatch map`
  - 更接近 runtime 里预先注册好的 `name -> ToolDefinition.execute` 映射
- `循环不用动`
  - 指 tool-calling loop 本身不需要因为新增一个普通工具而改写

这件事最准确的理解不是“按名字反射 import 某个函数文件”，而是：

> 先注册好一张 `name -> ToolDefinition.execute` 的映射表，再由 runtime 按 `tool_call.name` 选中并执行。

关键入口在 `src/agents/pi-tool-definition-adapter.ts:113-168`。

`toToolDefinitions(...)` 会把每个原始工具对象转成：

```ts
{
  name,
  label,
  description,
  parameters,
  execute: async (...) => {
    const rawResult = await tool.execute(...)
    ...
  }
}
```

注意这里很关键的一点：

- 每个 `ToolDefinition` 在创建时
- 就已经通过闭包捕获了原始 `tool.execute`

因此运行时真正做的是：

```text
tool_call.name
 -> 匹配 ToolDefinition.name
 -> 调这个 ToolDefinition.execute(...)
 -> 这个 execute 再调原始 tool.execute(...)
```

所以 OpenClaw 不是“临时按名字去找一个函数文件”，而是“先注册好 `name -> execute` 映射，再由 runtime 按 `tool_call.name` 选中并执行”。

如果把这一节压成一句最短的话，就是：

> **OpenClaw 的 tool loop 是稳定的；新增工具通常只是在这条固定循环外，再挂一个新的 handler。**

### 6.7 为什么说“prompt 摘要”和“runtime schema”不是一回事

这是 Tools 模块最容易混的地方。

如果借上面那句更直观的话来说，很多框架最容易讲糊的地方就是：

> 它们把“稳定的循环”和“每个工具自己的 handler”一起包掉了，最后用户只看到“注册一个方法”，看不到背后的 dispatch 结构。

对 OpenClaw 来说，这两者服务的是不同层：

1. Prompt 摘要层  
   给模型看“有哪些工具、大概做什么”

2. Runtime schema 层  
   给模型和 runtime/provider 看“参数是什么、怎么调用”

因此更准确的主线是：

```text
tool object
 -> 一路变成 toolNames + toolSummaries 进入 SystemPrompt
 -> 另一路变成 schema + execute 进入 createAgentSession(...)
```

这两条链互相有关，但不是同一个东西。

### 6.8 Providers 对 tool 的作用是什么

Provider 不是简单的“tool 底层”，但它确实会影响一大类工具的来源、实现和可用性。

这里要分两类看。

第一类：**provider 直接支撑某些工具**

最典型的是 web search。

- `src/web-search/runtime.ts:131-179` 会先解析当前 provider，再调用 `provider.createTool(...)`

也就是说：

```text
WebSearchProvider
 -> createTool(...)
 -> web_search tool definition
```

第二类：**provider 通过 registry/runtime 被工具调用**

例如 core tools 里：

- `createWebSearchTool(...)`
- `createTtsTool(...)`
- `createImageGenerateTool(...)`

这些工具本身是 core tool，但运行时还会再去走 provider registry/runtime。

所以更准确地说：

- tool 是 Agent 暴露面
- provider 是这类能力的后端实现来源
- core 和 extension 都可以提供 provider
- 某个 tool 最终调用哪个 provider，往往由 config、registry 和 runtime 决定

### 6.9 core provider 和 extension provider 有什么区别

和 tool 一样，它们最大的区别也是“来源和生命周期”。

`core provider`：

- 直接在 core 代码里定义或预留内建槽位
- 随 OpenClaw 核心一起发布

`extension provider`：

- 通过插件 API 注入
- 例如 `registerProvider(...)`
- `registerSpeechProvider(...)`
- `registerImageGenerationProvider(...)`
- `registerWebSearchProvider(...)`

它们最终会在 provider registry 里汇合，然后影响对应 tool 的行为。

### 6.10 工具体系还有策略层

即使工具已经进入 `effectiveTools`，也不代表它们一定可用。

`src/agents/pi-tools.ts:552-597` 还会继续做策略治理，例如：

- message provider 限制
- model/provider tool policy
- sandbox、workspace root guard、group policy、owner policy
- provider 兼容性相关 schema 清洗和参数归一化
- before-tool-call hook
- abort signal 包装

所以 OpenClaw 的 tools 不是“静态清单”，而是：

```text
多来源工具
 -> runtime 装配
 -> provider / channel / sandbox / policy 过滤
 -> prompt 摘要 + Agent runtime 注册
```

### 6.11 OpenClaw 的 Tools 范式与常见框架封装的区别

很多框架会把 tool calling 包装成：

```text
注册一个方法
 -> 自动生成 name / description / schema
 -> 自动 dispatch
```

于是用户很容易只看到“注册函数”这一层，而看不到：

- prompt 摘要怎么来的
- schema 怎么来的
- provider 兼容性怎么处理
- runtime 到底怎么按名字匹配执行函数

OpenClaw 没有把这条链全部藏起来，而是显式展开成：

```text
tool object
 -> toolNames + toolSummaries
 -> SystemPrompt

tool object
 -> normalizeToolParameters(...)
 -> toToolDefinitions(...)
 -> createAgentSession(...)

tool_call.name
 -> ToolDefinition.name
 -> ToolDefinition.execute(...)
 -> tool.execute(...)
```

因此，OpenClaw 的 Tools 范式更接近：

- prompt 侧保留“工具摘要”来帮助模型理解
- runtime 侧保留“结构化 tool definition”来保证调用稳定
- 中间再叠加 provider / policy / sandbox / plugin / MCP 这些运行时因素

所以如果要和常见教程式 Agent 做一句对比，最稳的说法是：

> OpenClaw 不是“只把 tools 塞进 prompt”，也不是“只做裸 function calling”，而是把 prompt 摘要、runtime schema、execute dispatch 这三层都显式展开了。

### 6.12 从 `/context list` 看 OpenClaw 的上下文由什么组成

讲 Tools 时，最容易混的一个点是：很多人会把 `System prompt`、`Tool list`、`Tool schemas`、`Tools:` 那行名字列表，看成三四份并列注入的“上下文”。`/context list` 这个页面很容易进一步放大这种误解。

从源码看，更准确的口径是：

- 真正的 system-side 输入只有两层
  - **prompt 文本层**：`systemPrompt`
  - **结构化工具层**：`tools[]`
- `/context list` 不是把这两层重新注入一遍，而是把它们拆开展示成一份 **system-side context report**
- 其中 `Injected workspace files`、`Skills list`、`Tool list` 都是 **`System prompt` 内部子项的拆分统计**
- `Tool schemas (JSON)` 是 `/context list` 对 `tools[]` 里 schema 部分做出的**预算统计标签**
- `Tools:` 是 `/context list` 对 `tools[]` 做出的**人类可读名字索引**

`/context list` 的输出来自 `src/auto-reply/reply/commands-context-report.ts`，底层统计结构来自 `src/agents/system-prompt-report.ts` 的 `buildSystemPromptReport(...)`。这份 report 可能有两种来源：

- `source: "run"`：来自最近一次真实 embedded run，见 `src/agents/pi-embedded-runner/run/attempt.ts:1735-1762`
- `source: "estimate"`：没有真实 run report 时，按当前配置临时估算，见 `src/auto-reply/reply/commands-context-report.ts:45-74`

所以，`/context list` 真正回答的是：

> 这一轮系统侧输入由哪几层组成；其中 prompt 文本内部各自占了多少；结构化工具 schema 又额外占了多少。

#### 1. 先定边界：`/context list` 展示的是“总输入 + 拆分统计 + 辅助索引”

这一页最好按下面这张图理解：

```text
本轮 system-side 输入
= prompt 文本层
  + 结构化 tools[] 层

/context list 报告
= 总输入统计
  + prompt 内部子项拆分
  + tools[] 的 schema 成本
  + 人类可读辅助行（如 Tools: ...）
```

这意味着：

- `System prompt (run)` 是 prompt 文本层的**总量**
- `Injected workspace files`、`Skills list`、`Tool list` 是这个总量里的**子项拆分**
- `tools[]` 才是真实的结构化工具集合
- `Tool schemas (JSON)` 是 `tools[]` 这一层的**schema 预算统计**
- `Tools:` 只是帮助人理解“这轮到底有哪些工具”的**报告索引行**

如果不先把这四层拆开，就很容易误读成：

```text
System prompt
+ Injected workspace files
+ Skills list
+ Tool list
+ Tool schemas
```

这种“逐项相加”的读法是不准确的，因为前 3 项本来就已经包含在 `System prompt` 里。

#### 2. `System prompt (run)`：文本型系统提示总量

这是 `systemPrompt` 字符串本身的大小，来源见 `src/agents/system-prompt-report.ts:98-126`。

它对应的是：

- `src/agents/system-prompt.ts`
- `src/agents/pi-embedded-runner/system-prompt.ts`

这里的 `System prompt (run)` 指的是：

> **真正拼成文本并交给模型阅读的那段系统提示词总量。**

而 `/context list` 后面列出的很多项目，其实都是这段文本内部的拆分视图，而不是额外又注入了一遍。

#### 3. `Injected workspace files`、`Skills list`、`Tool list` 都是 `System prompt` 的子项拆分

这三项最容易被误会成“和 system prompt 并列”。实际上不是。

##### `Injected workspace files`

这一项对应 system prompt 里的 `Project Context` 区块。

`/context list` 会把这里再拆成每个文件：

- 哪些文件被注入
- 原始大小是多少
- 实际注入多少
- 是否被截断

但它们本质上还是 `System prompt` 文本内部的一部分，不是第二份独立输入。

##### `Skills list (system prompt text)`

这一项统计的是 skills prompt 被渲染进 system prompt 后，占了多少字符。

它对应的不是完整 `SKILL.md` 正文，而是：

- `<available_skills> ... </available_skills>` 这类技能目录文本
- 以及 system prompt 外层那段“如何选择 skill、何时去 read SKILL.md”的规则

它同样属于 `System prompt` 文本内部。

##### `Tool list (system prompt text)`

这一项对应 `SystemPrompt` 里的 `## Tooling` 段。

源码上：

- `src/agents/pi-embedded-runner/system-prompt.ts:76-77` 会把 `toolNames` 和 `toolSummaries` 传给 prompt builder
- `src/agents/system-prompt.ts:423-438` 会把它们渲染成工具文本列表
- `src/agents/system-prompt-report.ts:69-77` 会从 `systemPrompt` 文本里把这段重新抽出来统计字符数

所以这里统计的是：

- tool name
- tool summary / description
- 少量 core tool 的额外提示文案

而不是：

- 完整 JSON schema
- `execute(...)`
- 参数校验细节

这一项依然只是 `System prompt` 的一个子段，不是独立于 prompt 之外的第三层输入。

#### 4. `Tool schemas (JSON)`：`tools[]` 的 schema 预算标签

这里才是很多人第一次真正分清楚的地方。

先把两个名字分开：

- `tools[]`：架构层里的真实结构化工具集合
- `Tool schemas (JSON)`：`/context list` 里对 `tools[]` 的 schema 部分做的统计标签

`Tool schemas (JSON)` 不是 `System prompt` 里的文字，但它会计入本轮上下文成本。`/context list` 的实现里写得很直白，见 `src/auto-reply/reply/commands-context-report.ts:111`：

```text
Tool schemas (JSON): ... (counts toward context; not shown as text)
```

而 `schemaChars` 的计算方式在 `src/agents/system-prompt-report.ts:33-47`：

- 对每个 `AgentTool` 取 `tool.parameters`
- `JSON.stringify(...)`
- 统计 schema 字符数

所以这里的准确结论是：

- `tools[]` **属于这一轮输入**
- `Tool schemas (JSON)` **是对 `tools[]` 的 schema 成本统计**
- 但它**不属于 system prompt 那段文字**
- 它统计的本质就是 `tools[]` 里 `parameters schema` 这部分

也就是说，OpenClaw 的工具输入有两层：

- **prompt 文本层**：`Tool list (system prompt text)`
- **结构化工具层**：`tools[]`

而 `/context list` 只是把第二层进一步显示成：

- `Tool schemas (JSON)`：schema 预算
- `Tools:`：名字索引

#### 5. `tools[]` 和 `Tools:` 不是同一种东西

这两个名字长得像，但层次完全不同：

- `tools[]`
  - runtime 里的真实工具对象数组
  - 至少包含 `name`、`description`、`parameters`、`execute`
- `Tools:`
  - `/context list` 里把这批工具的 `name` 打印成一行
  - 只是人类可读索引

两者的关系更接近：

```text
tools[]
 -> report.tools.entries
 -> Tools: read, edit, write, exec, ...
```

所以 `Tools:` 不是 `tools[]` 的正式名字，只是它的名字列表投影。

#### 6. `Tools:` 不是第三份输入，而是报告里的工具名索引

图里那一行：

```text
Tools: read, edit, write, exec, ...
```

不是 schema，也不是 prompt 正文，更不是第三次注入。它只是这份 report 对应的工具名集合。

源码上它直接来自：

- `report.tools.entries.map((t) => t.name)`，见 `src/auto-reply/reply/commands-context-report.ts:114`

而 `entries` 本身则来自 `src/agents/system-prompt-report.ts:18-47` 对 `tools: AgentTool[]` 的统计。

在真实 run 模式下，这个 `tools` 就是当时那轮运行的 `effectiveTools`，最终会被转成 `customTools` 交给 `createAgentSession(...)`，见：

- `src/agents/pi-embedded-runner/run/attempt.ts:1860-1898`

所以这行更准确地说是：

> **这次 run 最终实际可用、并参与了本轮装配的工具名目录。**

它是报告的辅助视图，不是额外的上下文注入层。

#### 7. 所以这页 `/context list` 到底该怎么读

最准确的读法不是“这里列了 5 样东西，所以 system-side context 被注入了 5 份”，而是：

```text
本轮 system-side 输入
= System prompt 文本
 + 结构化 tools[]

/context list 的显示方式
= System prompt 总量
 + 其中的 Project Context / Skills / Tool list 拆分
 + tools[] 的 schema 成本
 + 一行工具名索引
```

所以：

- `Injected workspace files`、`Skills list`、`Tool list`
  - 是 `System prompt` 的内部拆分
- `Tool schemas`
  - 是 `tools[]` 这一层的结构化成本
- `Tools:`
  - 只是 report 的名字列表

这才是 `/context list` 和真实输入层之间最准确的对应关系。

#### 8. 一句话区分这几个最容易混的名词

可以直接记成：

- `System Prompt`：给模型读的系统提示文本总量
- `Injected workspace files` / `Skills list` / `Tool list`：`System Prompt` 内部子项的拆分统计
- `tools[]`：runtime 里的真实结构化工具集合
- `Tool schemas (JSON)`：`/context list` 里对 `tools[]` 的 schema 成本统计
- `Tools:`：`/context list` 里对 `tools[]` 的名字索引
- `/context list`：把 system-side 输入和其内部拆分一起展示出来的诊断视图

### 6.13 一句话总结 Tools 这一节

Tools 模块最准确的理解是：

```text
framework/core/plugin/MCP tools
 -> 合成 effectiveTools
 -> prompt 侧只拿 name + summary
 -> runtime 侧拿 schema + execute
 -> provider 决定其中一大类工具的后端实现和可用性
```

所以可以直接记成一句话：

> Skills 主要进入 prompt；Tool schema 主要进入结构化 tool runtime。

## 7. 插件、技能、工具、MCP 的真实关系

这里可以用一张简化图来理解：

```text
Plugin
 -> 贡献 tools / hooks / providers / channels / services
 -> 也可以贡献 skills 目录
 -> 也可以贡献 bundle MCP 配置

Skill
 -> 进入 system prompt
 -> 指导模型如何使用能力

Tool
 -> 运行时可执行动作
 -> 可来自 framework / core / plugin

MCP
 -> 提供外部工具服务器
 -> 在运行时被转成 Agent tools
```

所以：

- `Plugin` 是扩展面
- `Skill` 是知识面
- `Tool` 是执行面
- `MCP` 是外部工具接入面

这四层相互配合，但不能互相替代。

## 8. 运行时装配：Gateway、Agent、Runtime 如何承载插件

### 8.1 Gateway 承载什么

Gateway 启动时负责：

- `loadGatewayPlugins(...)`
- 生成 plugin registry
- 合并插件 methods
- 启动 channels / services / HTTP routes
- 将插件 runtime 挂进统一控制面

这意味着 Gateway 是 plugin host。

### 8.2 Agent runtime 承载什么

Agent 运行时在 `src/agents/pi-embedded-runner/run.ts` 中会调用：

- `ensureRuntimePluginsLoaded(...)`
- `createOpenClawTools(...)`
- `resolveSkillsPromptForRun(...)`
- `loadModelCatalog(...)`
- `ensureOpenClawModelsJson(...)`

这说明 Agent runtime 不是只调用模型，而是先把插件、技能、工具、模型一起装配好。

### 8.3 `plugins/runtime/index.ts` 是共享契约

`createPluginRuntime(...)` 暴露的是一个统一 runtime contract。

这个 runtime 既能被 Gateway 使用，也能被 Agent runtime 使用。

所以插件并不是“只对某一个调用方生效”，而是被整个 OpenClaw 运行时共享。

## 9. 扩展开发范式

如果从插件作者视角看，OpenClaw 的扩展范式可以归纳成几步：

### 9.1 先选扩展类型

你要扩展的是：

- 新工具
- 新 skills
- 新 provider
- 新 channel
- 新 service
- 新 Gateway 方法
- 新 HTTP route

### 9.2 再落到对应 contract

对应的 contract 主要是：

- `src/plugins/types.ts`
- `src/plugins/runtime/types.ts`
- `openclaw/plugin-sdk/*`

### 9.3 最后把能力放进运行时

然后让它通过：

- `loadOpenClawPlugins(...)`
- `resolvePluginTools(...)`
- `resolvePluginSkillDirs(...)`
- `createPluginRuntime(...)`

进入 Agent / Gateway 的实际运行路径。

### 9.4 尽量不要直接碰 core 内部实现

对扩展作者来说，最稳妥的方式是：

- 走 `openclaw/plugin-sdk/*`
- 走插件 manifest
- 走 runtime contract

而不是直接 import `src/**` 内部实现。

## 10. 小结

这一层最重要的结论是：

> OpenClaw 的扩展机制不是单一的“插件系统”，而是 `Plugin`、`Skill`、`Tool`、`MCP` 四层分工明确、彼此协作的扩展架构。

可以把它压成一句更准确的话：

```text
Plugins provide capabilities.
Skills provide operational knowledge.
Tools provide executable actions.
MCP provides external tool servers.
```

如果再结合 OpenClaw 的整体范式，那就是：

- `File-first Context`
- `Session-first Orchestration`
- `Tool-centric Runtime`
- `Plugin-extended Platform`
- `Skill-layered Prompting`
- `MCP-integrated Tool Access`

这就是 OpenClaw 在扩展机制上的核心设计。

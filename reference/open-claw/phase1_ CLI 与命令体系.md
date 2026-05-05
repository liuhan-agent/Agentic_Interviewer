# Phase 1: CLI 与命令体系

## 1. 模块定位

OpenClaw 的 CLI 是本地命令入口层，主要面向本地操作者、管理员、开发者，以及脚本化自动化场景。它属于系统的多入口层之一，但它和 Web UI、移动端、桌面端、ACP、外部消息渠道的定位并不相同。

更准确地说：

- CLI 是本地命令与系统管理入口
- Web UI / 移动端 / 桌面端是交互聊天与控制入口
- ACP 是协议入口
- 外部消息渠道是第三方平台消息入口

因此，CLI 不是“另一个聊天窗口”，而更像 OpenClaw 的本地控制台和管理壳。

## 2. 先建立几个最容易混淆的概念

### 2.1 CLI 命令是什么

在终端里输入的：

```bash
openclaw status
openclaw message send --target +15555550123 --message "Hi"
```

表面上当然是 CMD / PowerShell / Bash 里的“命令”，但从操作系统视角看，真正被启动的外部程序只有一个：`openclaw`。

后面的 `status`、`message send`、`agents list` 这些并不是操作系统内建命令，而是 OpenClaw 进程启动之后，由 OpenClaw 自己内部的 CLI 解析器继续识别、分发和执行的子命令。

所以可以粗略理解成：

```text
Shell 启动 openclaw
 -> OpenClaw 解析 argv
 -> OpenClaw 内部命令注册机制匹配子命令
 -> 调用对应 handler / 业务函数
```

### 2.2 CLI 命令不等于 Tool

CLI 命令和 Tool 是两层不同的东西：

- CLI 命令：给人或脚本在终端里调用的入口形式
- Tool：给 LLM / Agent 暴露的能力接口

OpenClaw 的 CLI 主链路通常是：

```text
CLI 命令 -> OpenClaw 代码函数 -> 直接做事 / 调 Gateway / 调业务模块
```

它不是默认先变成 Tool 再执行。

但如果站在 Agent 运行时视角，LLM 想真正“用 CLI”，通常仍然需要一个 shell / exec 类 Tool 来落地执行命令，因此会出现：

```text
LLM -> shell/exec tool -> openclaw status -> OpenClaw 命令注册机制 -> handler
```

### 2.3 shell/exec tool 是什么

shell/exec tool 不是操作系统直接提供给 LLM 的东西。更准确地说：

- 操作系统提供原始进程能力，例如 `cmd`、`powershell`、`bash`、`fork/exec`、`CreateProcess`
- Agent 宿主、框架、IDE 插件、MCP server 再把这层能力封装成一个 LLM 可调用的 Tool

所以 shell/exec tool 通常由宿主或框架提供，不是 OS 直接“暴露给模型”的。

它的本质是“受控的子进程执行器”：

```text
LLM
 -> 调用 shell tool(command, cwd, timeout...)
 -> 宿主程序启动子进程
 -> OS 执行 bash / powershell / cmd
 -> 返回 stdout / stderr / exit code
```

### 2.4 MCP 和 CLI 的区别

CLI 和 MCP 都可以成为 LLM 的能力桥，但它们不是同一件事。

常见调用链如下：

```text
LLM 用 CLI:
LLM -> shell/exec tool -> CLI 程序 -> 程序内部代码函数 -> 文本结果

LLM 用 MCP:
LLM -> tool_call -> MCP server -> server 内部实现 -> 结构化结果
```

CLI 的典型优点：

- token 更省
- 模型对 shell / git / npm / node / python 等模式更熟
- stdout / stderr 对人和模型都直观

MCP 的典型优点：

- 输入输出结构化
- 类型和权限边界更容易做清晰
- 更适合复杂业务对象和稳定机器接口

因此，CLI 常常比 MCP 更轻、更熟，但“LLM 用 CLI”通常并不意味着没有 Tool，只是 Tool 退到了外层 shell / exec 执行层。

### 2.5 CLI 命令的基本格式

CLI 命令最常见的结构可以概括为：

```text
程序名 [全局选项] 命令 [子命令] [位置参数] [命名选项]
```

例如：

```bash
openclaw status --json
openclaw message send --target +15555550123 --message "Hi"
git commit -m "msg"
npm install react
python script.py --port 3000
```

这些部分各自的作用通常是：

- 程序名
  - 指明“要启动哪个 CLI 程序”
  - 例如 `openclaw`、`git`、`npm`
  - 从操作系统视角看，真正被启动的外部程序通常就是它

- 全局选项
  - 作用于整个程序，而不只针对某个具体子命令
  - 常用于 profile、日志级别、颜色开关、帮助、版本等
  - 例如 `openclaw --profile dev status`

- 命令
  - 指明“要执行哪一类动作”
  - 往往对应一组相关能力的入口
  - 例如 `status`、`message`、`config`

- 子命令
  - 在某个命令下面继续细分动作
  - 常用于形成树状命令结构
  - 例如 `message send`、`message read`、`plugins install`

- 位置参数
  - 按顺序传递的数据
  - 不靠名字区分，而靠位置区分含义
  - 例如 `npm install react` 里的 `react`

- 命名选项
  - 用 `-` 或 `--` 显式说明参数用途
  - 适合表达可选配置、布尔开关、带值参数
  - 例如 `--json`、`--target +15555550123`、`-m "msg"`

通常可以拆成：

- 程序名
  - 例如 `openclaw`、`git`、`npm`
- 命令 / 子命令
  - 例如 `status`、`message send`、`commit`、`install`
- 位置参数
  - 例如 `npm install react` 里的 `react`
- 命名选项
  - 例如 `--json`、`--message`、`-m`、`--port 3000`

常见选项形式包括：

- 短选项：`-v`
- 长选项：`--verbose`
- 带值选项：`--port 3000`
- 布尔开关：`--json`
- 等号写法：`--port=3000`

因此，对 OpenClaw 这样的 CLI 而言，像：

```bash
openclaw message send --target +15555550123 --message "Hi"
```

其实就是：

- `openclaw`：程序名
- `message`：命令
- `send`：子命令
- `--target`、`--message`：命名选项

### 2.6 `|` 的两种常见含义

竖线 `|` 在 CLI 相关语境里常见有两种含义。

#### 2.6.1 在真实命令里：管道符

当它出现在实际 shell 命令中时，通常表示“把左边命令的输出传给右边命令”。

例如：

```bash
git status --short | findstr M
```

意思是：

- 先执行 `git status --short`
- 再把输出交给 `findstr M` 过滤

#### 2.6.2 在语法说明里：表示“或”

当它出现在文档、帮助文本、命令说明中时，通常表示“多选一”。

例如：

```text
--thinking <off|low|medium|high>
```

表示这个参数只能从下面这些值中选一个：

- `off`
- `low`
- `medium`
- `high`

因此，阅读 CLI 文档时需要区分：

- 命令里的 `|`：pipe / 管道
- 语法说明里的 `|`：or / 选一项

## 3. 从 Agent 视角看 CLI 操作

### 3.1 对 LLM 而言，很多能力最后都像 Tool Calls

从 Agent 运行时视角看，很多能力最后都可以抽象为“可调用能力”：

- 显式的 tool schema / tool call
- shell / exec tool
- 宿主内建文件和网络能力
- MCP 暴露出来的能力

因此，很多人会觉得“对 LLM 而言，全都是 tool_calls”。这个抽象大体成立，但底层实现方式并不相同。

### 3.2 基础 CLI 操作的来源

Agent 常见的“基础 CLI 操作”通常来自三层共同配合：

1. 操作系统提供原始能力
   - 文件系统
   - 进程创建与管理
   - shell
   - 网络原语

2. 应用或工具提供各自的 CLI 与 handler
   - `git`
   - `npm`
   - `docker`
   - `openclaw`
   - `lark-cli`

3. Agent 宿主或框架把这些能力封装给 LLM
   - `run_shell`
   - `exec`
   - `read_file`
   - `http_request`

因此：

- 基础执行能力很多来自操作系统
- 具体 CLI 命令及其 handler 往往是各个应用自己实现的
- Agent 通常通过宿主提供的 Tool 去调用它们

### 3.3 文件操作和网络请求不一定真的走 CLI

需要注意，Agent 看到的是“能力”，不一定真的对应一条 shell 命令。

例如：

- `read_file` 可能直接调用宿主语言的文件 API，而不是执行 `cat`
- `http_request` 可能直接调用 HTTP 库，而不是执行 `curl`
- `run_shell("git status")` 才是显式走 shell 的路径

因此“CLI 操作”有时只是人类描述习惯，并不代表底层一定在调用 shell。

## 4. OpenClaw CLI 的核心职责

结合源码，`src/cli` 模块主要承担以下职责：

1. 启动与运行时准备
   - 入口：`openclaw.mjs`、`src/entry.ts`、`src/cli/run-main.ts`
   - 负责参数标准化、profile 处理、dotenv 加载、环境规范化、Node 运行时检查

2. 命令解析与注册
   - 入口：`src/cli/program/build-program.ts`
   - 注册器：`src/cli/program/command-registry.ts`、`src/cli/program/register.subclis.ts`
   - 负责构建 Commander 命令树、注册核心命令和 sub-CLI、延迟加载命令实现

3. 命令分发与 CLI 适配
   - 快路径：`src/cli/route.ts`、`src/cli/program/routes.ts`
   - CLI 适配层示例：`src/cli/channels-cli.ts`、`src/cli/config-cli.ts`、`src/cli/gateway-cli/register.ts`
   - 负责把终端输入分发到对应业务处理器，并处理帮助文本、选项适配、runtime 注入、错误包装

4. 连接底层业务模块
   - 常见目标：`src/commands/*`
   - 也可能直接进入专属 CLI 模块、Gateway 相关模块、Agent 相关模块

## 5. `src/cli` 与 `src/commands` 的职责边界

这是理解 OpenClaw CLI 最重要的一组边界。

### 5.1 `src/cli` 做什么

`src/cli` 是“命令行外壳 / 分发层”。

它主要负责：

- 接收 shell 传入的 argv
- 决定走 fast path 还是 Commander 完整命令树
- 注册命令和子命令
- 解析选项
- 生成帮助信息
- 在执行前注入 runtime / deps / 错误处理
- 把命令交给后续业务处理器

关键位置：

- `src/cli/run-main.ts`
- `src/cli/route.ts`
- `src/cli/program/build-program.ts`
- `src/cli/program/command-registry.ts`
- `src/cli/program/register.subclis.ts`

### 5.2 `src/commands` 做什么

`src/commands` 是“命令业务实现层”。

它主要负责：

- 承载命令背后的业务逻辑
- 将 CLI 层转下来的结构化参数，继续落到 Agent、Gateway、Config、Session、Sandbox、Channels 等更深层模块

典型文件：

- `src/commands/status.ts`
- `src/commands/status-json.ts`
- `src/commands/health.ts`
- `src/commands/message.ts`
- `src/commands/models.ts`
- `src/commands/agents.ts`

### 5.3 两者关系

可以用一句话概括：

```text
src/cli 负责“怎么接命令、怎么分发”
src/commands 负责“这条命令具体做什么”
```

但需要注意，`src/commands` 是非常重要的一层，不是唯一终点。某些命令也会直接进入：

- `src/cli/*-cli.ts`
- `src/cli/gateway-cli/*`
- `src/gateway/*`
- `src/agents/*`

## 6. 启动链路

CLI 的主启动链如下：

```text
openclaw.mjs
 -> src/entry.ts
 -> src/cli/run-main.ts
```

### 6.1 `openclaw.mjs`

这是 npm `bin` 指向的真正入口。它会先做几件很底层的事：

- 检查最低 Node 版本
- 尝试开启 compile cache
- 安装 process warning filter
- 再去加载构建产物中的 `dist/entry.js` / `dist/entry.mjs`

### 6.2 `src/entry.ts`

这是源码侧入口。它负责：

- root help / root version fast path
- profile 相关预处理
- argv 归一化
- 某些情况下的 respawn
- 最后进入 `runCli(...)`

### 6.3 `src/cli/run-main.ts`

这是真正的 CLI 主流程。它会：

- 标准化 argv
- 处理 `--profile`
- 加载 `.env`
- 规范化环境变量
- 必要时确保 `openclaw` 在 PATH 中
- 检查运行时
- 优先尝试 fast path 路由
- 如果没有命中，再构建 Commander program

## 7. 命令不是“整串字符串查表”，而是“解析后路由”

OpenClaw 的命令注册与分发，不是把完整字符串：

```text
"openclaw status --json"
```

直接映射到某个 handler。

更常见的实际过程是：

```text
命令字符串
 -> shell 分词
 -> argv tokens
 -> 提取命令路径
 -> 解析 flags / options
 -> 匹配命令树或路由表
 -> 调用 handler
```

例如：

```bash
openclaw status --json
```

在 CLI 层的思路大致是：

```text
argv -> ["status", "--json"]
commandPath -> ["status"]
flags -> { json: true, deep: false, all: false, ... }
route / command tree -> status handler
```

这就是“命令注册机制”的本质：不是做整串字符串匹配，而是“把命令行解析成结构，再按命令树分发”。

## 8. 两条主执行路径：fast path 与 Commander 命令树

OpenClaw CLI 不是只有一套执行路径，而是两条主路径：

1. route-first 的 fast path
2. Commander 的完整命令树

### 8.1 fast path

相关文件：

- `src/cli/route.ts`
- `src/cli/program/routes.ts`

其工作方式是：

- 先根据 argv 提取命令路径
- 判断是否命中一组高频、稳定、适合直达的命令
- 命中后直接解析 flag 并 `import()` 对应业务模块执行
- 跳过完整 Commander 命令树构建

典型命令包括：

- `status`
- `health`
- 裸 `sessions`
- `config get`
- `config unset`
- `models list`
- `models status`
- `agents list`
- `gateway status`
- `memory status`

其主要价值：

- 启动更快
- 加载更轻
- 某些命令可以避免不必要的插件预加载

### 8.2 Commander 命令树

如果没有命中 fast path，就进入完整命令树：

- `src/cli/program/build-program.ts`
- `src/cli/program/command-registry.ts`
- `src/cli/program/register.subclis.ts`

这一层负责：

- 创建 Commander `program`
- 注册核心命令
- 注册 sub-CLI
- 支持帮助、选项、子命令
- 支持插件 CLI 命令注入

### 8.3 延迟注册与 reparse

OpenClaw 的命令注册不是一次性把所有实现都 eager load 进来，而是大量使用“占位命令 + 懒加载”：

- 先注册一个 placeholder command
- 真正命中时再动态 `import()` 对应命令注册模块
- 再通过 `src/cli/program/action-reparse.ts` 重新 parse 一次 argv

这也是为什么 OpenClaw 的命令树能很大，但启动仍尽量保持轻量。

## 9. 顶层命令组织方式

OpenClaw 顶层命令大体分成两组：

### 9.1 Core commands

描述定义在 `src/cli/program/core-command-descriptors.ts`。

目前包括：

- `setup`
- `onboard`
- `configure`
- `config`
- `backup`
- `doctor`
- `dashboard`
- `reset`
- `uninstall`
- `message`
- `memory`
- `agent`
- `agents`
- `status`
- `health`
- `sessions`
- `browser`

### 9.2 Sub-CLI

描述定义在 `src/cli/program/subcli-descriptors.ts`。

包括：

- `gateway`
- `daemon`
- `models`
- `channels`
- `plugins`
- `sandbox`
- `skills`
- `update`
- `devices`
- `node`
- `cron`
- `docs`
- `hooks`
- `security`
- `secrets`
- `completion`

以及其他一批专用命令族。

因此，在插件参与之前，OpenClaw 自己就已经有一套非常大的内建命令树。

## 10. 一个完整例子：`openclaw status --json`

这是理解 CLI 原理最好的例子。

### 10.1 从字符串到 handler 的逐步过程

```text
openclaw status --json
 -> Shell 分词
 -> openclaw 进程启动
 -> openclaw.mjs
 -> src/entry.ts
 -> src/cli/run-main.ts
 -> tryRouteCli(argv)
 -> 提取 commandPath = ["status"]
 -> 解析 json / deep / all / timeout 等 flags
 -> 命中 routeStatus
 -> json=true 时调用 statusJsonCommand(...)
 -> 输出 JSON
```

### 10.2 时序图

```text
User
 -> Shell
 -> openclaw entry
 -> run-main.ts
 -> route.ts / routes.ts
 -> statusJsonCommand
 -> stdout
```

### 10.3 对应关键文件

- `openclaw.mjs`
- `src/entry.ts`
- `src/cli/run-main.ts`
- `src/cli/route.ts`
- `src/cli/program/routes.ts`
- `src/cli/argv.ts`
- `src/commands/status-json.ts`

这个例子说明了一个关键事实：

> OpenClaw CLI 的主要工作模式是：在同一个 Node 进程里完成 argv 解析、命令路径匹配、选项解析和 handler 调用，而不是在进入 OpenClaw 之后继续依赖 shell 再做一轮命令分发。

## 11. 一个典型命令族：`message`

`message` 是“CLI 注册层”和“业务实现层”分离很清楚的命令族。

链路可以概括为：

```text
openclaw message send ...
 -> 命中 message 顶层命令
 -> src/cli/program/register.message.ts 注册子命令
 -> src/cli/program/message/register.send.ts 定义 send 的选项和 action
 -> src/cli/program/message/helpers.ts 做参数归一化、plugin registry 加载、runtime 包装
 -> src/commands/message.ts 执行真实消息发送逻辑
```

这里能清楚看到：

- `src/cli/program/message/register.send.ts` 负责命令行界面和参数声明
- `src/commands/message.ts` 负责真正业务执行

## 12. preAction、帮助系统与配置守卫

### 12.1 preAction hook

`src/cli/program/preaction.ts` 会在真正执行 action 前做统一准备：

- 设置进程标题
- 输出 banner
- 处理 verbose / debug / log level
- 运行配置守卫
- 按需加载插件注册表

### 12.2 配置守卫

`src/cli/program/config-guard.ts` 用于在命令执行前检查配置是否可用。

其核心思想是：

- 普通命令执行前，先确保配置有效
- 某些命令允许在 invalid config 下继续执行，例如 `doctor`、`status`、`health` 等
- 某些 JSON 输出命令会抑制前置的 doctor 风格文本输出

### 12.3 根帮助与版本快速路径

- `src/cli/program/root-help.ts` 负责构建 root help
- `src/cli/program/help.ts` 负责 Commander 帮助格式、根命令示例、带星号的子命令提示等

这也是为什么 `openclaw --help` 和 `openclaw -v` 可以比完整命令树更早返回。

## 13. 插件如何接入 CLI 命令体系

OpenClaw 的插件系统支持“插件往 CLI 命令树里注册命令”，但这不是所有插件都会做的事。

### 13.1 相关机制

- 插件注册表在 `src/plugins/registry.ts`
- 其中有一类注册项叫 `cliRegistrars`
- 注入 Commander 命令树的入口是 `src/plugins/cli.ts` 里的 `registerPluginCliCommands(...)`
- `src/cli/run-main.ts` 会在合适时机把插件 CLI 命令注册到 `program`

### 13.2 这意味着什么

如果某个插件显式注册了 CLI registrar，那么：

```text
插件加载
 -> 产生 cliRegistrars
 -> registerPluginCliCommands(program, config)
 -> 对应命令被注入 OpenClaw 命令树
```

如果插件没有注册 CLI registrar，那它就不会往 CLI 顶层额外挂命令。

## 14. Feishu 插件安装原理

这部分是插件机制、CLI 命令体系和外部 CLI 产品最容易混淆的地方。

### 14.1 `openclaw plugins install @openclaw/feishu` 安装的是什么

安装入口在 `src/cli/plugins-cli.ts`，底层会调用：

- `installPluginFromNpmSpec(...)`
- `installPluginFromPath(...)`
- `enablePluginInConfig(...)`
- `recordPluginInstall(...)`
- `writeConfigFile(...)`

因此，安装 Feishu 的本质是：

```text
下载 / 复制一个 OpenClaw 插件包
 -> 记录安装信息
 -> 在配置里启用该插件
 -> 等待后续加载
```

它不是“下载一组单独的 shell handler”那么简单，而是安装一个完整插件模块及其依赖、manifest、setup 入口、运行时注册逻辑。

### 14.2 Feishu 插件启动时会注册什么

Feishu 插件元数据位于：

- `extensions/feishu/package.json`
- `extensions/feishu/openclaw.plugin.json`

插件主入口位于：

- `extensions/feishu/index.ts`

从入口可见，Feishu 插件主要注册：

- channel：`feishuPlugin`
- tools：doc/chat/wiki/drive/perm/bitable 等 Feishu 能力
- hooks：subagent hooks
- setup 入口：`extensions/feishu/setup-entry.ts`

### 14.3 它会不会给 OpenClaw 注入一套 `feishu` CLI 命令

不一定。

插件系统支持 CLI 命令注入，但要看插件自己有没有注册 CLI registrar。

以当前仓库里的 Feishu 插件实现来看，它主要注册的是 channel、tools、hooks、setup surface，没有看到它显式注册独立的 CLI registrar。因此它更像：

```text
安装 Feishu 插件
 -> OpenClaw 获得 Feishu channel / tools / setup 能力
```

而不是：

```text
安装 Feishu 插件
 -> 自动新增 openclaw feishu ... 一整套 CLI 命令
```

## 15. `lark-cli` 这类独立 CLI 包是什么

很多服务或应用都有自己的 CLI 包，例如：

- `git`
- `docker`
- `kubectl`
- `openclaw`
- `lark-cli`

这类 CLI 包通常是：

- 一个本地安装的代码包
- 带有 `bin` 入口
- 安装后在机器上变成可执行的命令行程序

例如 `lark-cli` 更准确地说是：

```text
一个安装在本地机器上的 CLI 程序包
```

它不是飞书客户端本体，而是飞书能力的命令行接口层。

### 15.1 它需要注册到 OpenClaw 命令体系吗

如果 `lark-cli` 只是一个独立安装在本地的 CLI 程序，那它不需要注册到 OpenClaw 的命令体系里。

它和 `openclaw` 是并列关系：

```text
Shell
├─ openclaw ...
└─ lark-cli ...
```

只有在下面两种情况下，它才需要接入 OpenClaw：

1. OpenClaw 在内部调用它
   - 某个 handler 或插件通过 `child_process.spawn` 之类调用 `lark-cli`
   - 这时不一定要把它注册成 OpenClaw 子命令

2. OpenClaw 想把它包装成自己的命令
   - 例如做成 `openclaw feishu ...`
   - 这时才需要注册进 OpenClaw 命令体系

### 15.2 OpenClaw 现在会直接安装或依赖 `lark-cli` 吗

按当前仓库代码看，不会。

OpenClaw 的 Feishu 插件当前走的是“直接集成飞书 SDK”的路线，而不是“安装外部 `lark-cli` 再包一层”。

因此当前更像：

```text
OpenClaw handler
 -> 直接调用 Feishu SDK / OpenClaw Feishu 插件内部实现
 -> 返回结果
```

而不是：

```text
OpenClaw handler
 -> 调外部 lark-cli
 -> lark-cli 调飞书能力
 -> 返回结果
```

## 16. OpenClaw Feishu 插件与独立 `lark-cli` 的关系

`lark-cli` 是飞书/Lark 方向上的独立 CLI 产品。它的定位是给人类和 AI Agent 提供终端中的飞书能力接口。

而 OpenClaw 的 `@openclaw/feishu` 则是：

- OpenClaw 插件体系中的 Feishu channel / tools 插件
- 服务于 OpenClaw 内部的 channel、tool、hook、setup 机制

两者解决的是相近问题，但不是同一个东西。

可以这样区分：

- `lark-cli`：独立产品级 Feishu CLI
- `@openclaw/feishu`：OpenClaw 内部插件

因此：

- OpenClaw 安装 Feishu 插件，不等于安装了 `lark-cli`
- `lark-cli` CLI 化了飞书能力
- `@openclaw/feishu` 则把 Feishu 能力接入到 OpenClaw 的插件运行时

## 17. CLI、shell tool、命令注册机制三者关系

这是理解“LLM 用 CLI”和“OpenClaw 内部 CLI 命令体系”的关键。

### 17.1 三者不是同一层

- CLI 命令：例如 `openclaw status`
- shell tool：例如 `run_shell({ command: "openclaw status" })`
- 命令注册机制：OpenClaw 启动后，如何识别 `status` 并路由到对应 handler

### 17.2 它们如何串起来

当人类直接调用时：

```text
Shell
 -> openclaw status
 -> OpenClaw 命令注册机制
 -> handler
```

当 LLM 间接调用时：

```text
LLM
 -> shell / exec tool
 -> openclaw status
 -> OpenClaw 命令注册机制
 -> handler
```

因此：

- shell tool 负责“把 openclaw 拉起来”
- OpenClaw 命令注册机制负责“openclaw 启动后怎么理解 status、message、agents 这些子命令”

二者有关联，但不是一回事。

## 18. Skill、渐进式披露与工具描述方式

### 18.1 为什么需要 Skill

如果一上来把大量 tool schemas JSON 全部塞进上下文，很容易出现：

- 工具太多，模型注意力被稀释
- 参数记混
- 选错工具
- 在长 schema 中丢失真正关键的使用策略

所以在实践中，通常会用 Skill 做“渐进式披露”：

- 默认只暴露任务相关的能力摘要
- 真需要时，再展开更细的工具使用方式和边界

### 18.2 Skill 对工具的描述一般长什么样

Skill 通常不会原样重复整段 JSON schema，而更像一份给模型看的使用手册。重点通常是：

- 这个工具是干什么的
- 什么时候该用
- 什么时候别用
- 输入心智模型
- 输出长什么样
- 常见调用模式
- 安全与成本边界
- 失败时如何退化处理

也就是说，Skill 更像：

```text
任务目标
 -> 优先工具
 -> 典型调用模式
 -> 风险边界
```

而不是：

```text
工具 A schema
工具 B schema
工具 C schema
...
```

### 18.3 Skill 里为什么常写 CLI 命令

因为对模型来说，CLI 命令通常：

- 更短
- 更熟
- 更容易内化成使用模式

例如：

- `git status --short`
- `rg pattern src/`
- `pnpm test -- src/foo.test.ts`
- `openclaw status --json`

这些往往比反复强调 `run_shell` 的 JSON 参数形式更有用。

## 19. Skill 里写 CLI 命令，最终到底执行谁

这是最近讨论中最关键的一个问题。

### 19.1 通常不是 LLM 直接碰操作系统

当 Skill 里写：

```text
先用 git status --short 看工作区
再用 rg 搜索相关代码
必要时运行 pnpm test -- <file>
```

这并不意味着 LLM 直接“原生操纵 OS shell”。更常见的真实链路是：

```text
Skill
 -> 告诉模型“该用哪些 CLI 命令”
 -> 模型选择 run_shell / exec
 -> 宿主执行 shell
 -> 操作系统真正运行命令
```

也就是说：

- Skill 负责表达“做什么”
- tool schema 负责表达“怎么调用宿主接口”
- OS shell 负责真正执行命令

### 19.2 三层分工

1. Skill
   - 使用说明书
   - 指导模型什么时候该用哪些 CLI 命令

2. `run_shell` / `exec` tool
   - 宿主提供给模型的可调用接口
   - 常见参数如 `command`、`cwd`、`timeout_ms`

3. 操作系统 shell
   - PowerShell / Bash / cmd
   - 真正负责执行 `git`、`openclaw`、`lark-cli` 等命令

### 19.3 典型链路

```text
Skill
 -> “需要查看代码变更时先用 git status --short”
 -> LLM 选择 run_shell
 -> run_shell(command="git status --short", cwd=...)
 -> PowerShell / Bash 执行 git
 -> 返回 stdout / stderr / exit code
```

### 19.4 什么时候 Skill 不写 CLI

如果宿主直接暴露了更细粒度的能力，例如：

- `read_file`
- `list_dir`
- `http_request`

那 Skill 也可能完全不写 CLI，而是写：

- 优先用 `read_file`
- 不要先用 shell 去 `cat`

因此 Skill 是否写 CLI，要看宿主暴露给模型的能力面。

## 20. Skill 包里的脚本是如何通过 CLI 执行的

这一类场景很常见：

- Skill 包下有一个或多个脚本
- `SKILL.md` 写明“遇到某类任务时执行这个脚本”
- 模型通过 shell / exec tool 去调用脚本

典型链路如下：

```text
SKILL.md
 -> 告诉模型“什么时候执行哪个脚本、怎么传参数”
 -> 模型调用 run_shell / exec
 -> shell 执行 python / uv / node 等命令
 -> 脚本真正干活
 -> 返回 stdout / stderr / exit code
 -> 模型继续推理并回复用户
```

### 20.1 这类脚本通常不属于 OpenClaw CLI 命令注册体系

如果 `SKILL.md` 里写的是：

```text
python scripts/analyze_logs.py --input <path> --json
```

那么它通常表示：

- Skill 自带了一段本地可执行实现
- `SKILL.md` 负责告诉模型何时调用它
- 模型通过 `run_shell` 间接执行它

它通常不是：

- OpenClaw 顶层命令树的一部分
- `openclaw ...` 的子命令
- 需要注册到 OpenClaw `command-registry` 的命令

更准确地说，它属于“Skill 自带辅助程序”，而不是 OpenClaw CLI 主命令体系。

### 20.2 一般不用把 `scripts/` 下脚本全文塞进上下文

在大多数情况下，不需要把脚本源码完整加载到上下文窗口里。更常见的做法是：

- `SKILL.md` 描述脚本用途
- 说明什么时候用
- 给出调用格式和参数
- 模型直接调用 `run_shell`
- 再根据结果继续推理

也就是说，通常只需要把这些信息放进上下文：

- 脚本是做什么的
- 什么时候该运行
- 命令格式
- 参数说明
- 输出方式

只有在下面这些情况，才通常值得去读脚本源码：

- 运行失败，需要调试
- 需要修改脚本
- 必须确认脚本具体行为或边界
- `SKILL.md` 写得不够清楚

### 20.3 返回给模型的一般是什么

对 Agent 运行时来说，这类脚本执行结果通常会以“工具返回结果”的形式回到上下文。

不同框架的命名可能不同，例如：

- tool result
- tool response
- tool message
- function result

但它们扮演的角色类似：都是“某次工具调用完成后的返回消息”。

对于 shell / exec tool，常见返回包括：

- `stdout`
- `stderr`
- `exit_code`
- 有时还有 `timed_out`

因此，可以把这类结果理解为“通过 tool message 形式回流给模型的 shell 执行结果”。

### 20.4 脚本当然可以有参数

而且大多数时候，脚本就应该有清晰参数接口。

例如：

```text
python scripts/analyze_logs.py --input <path> --format json --output <file>
```

这里实际上有两层参数：

1. shell tool 自己的参数
   - `command`
   - `cwd`
   - `timeout_ms`
   - `env`

2. 脚本自己的 CLI 参数
   - `--input`
   - `--format`
   - `--output`
   - `--dry-run`
   - 其他业务参数

所以“脚本能不能带参数”这个问题，答案不仅是可以，而且通常应该明确设计成参数化调用，而不是依赖模型自由拼装复杂命令。

### 20.5 结果可以写到文件，不必都走 stdout

脚本执行结果并不一定只能通过 `stdout` 返回，也完全可以写到文件。

常见有三种输出方式：

- `stdout`
  - 适合小结果、摘要、JSON、状态信息
- `stderr`
  - 适合错误、警告、诊断信息
- 写文件
  - 适合大结果、报告、缓存、结构化产物、图片、JSONL 等

典型模式：

```text
run_shell
 -> python scripts/analyze_logs.py --input <path> --output out/report.json
 -> 脚本把大结果写入文件
 -> Agent 再读取该文件或摘要其内容
```

经验上：

- 小结果优先 `stdout`
- 大结果、需复用结果、或结构化产物更适合写文件

### 20.6 `scripts/` 目录通常只是约定俗成

像 `scripts/analyze_logs.py` 这种路径中的 `scripts/`，通常不是某种全局硬性规范，而是约定俗成的目录命名方式。

常见放置目录有：

- `scripts/`
- `tools/`
- `bin/`
- Skill 自己的 `scripts/`

如果是在 Skill 包里，则通常表示：

- `SKILL.md` 是说明书
- `scripts/` 是该 Skill 自带辅助脚本目录

关键不是目录名本身，而是：

- `SKILL.md` 要写清楚如何调用
- 路径要稳定
- 参数要清晰
- 输出方式要清晰

### 20.7 “相对 Skill 目录解析”不等于 shell 当前就在 Skill 目录

这是一个非常容易混淆的点。

当说“在 Skill 体系里，相对路径通常按 Skill 目录解析”时，这指的是**路径解释规则**，不是说 PowerShell 或 Bash 的当前工作目录天然就在 Skill 目录里。

也就是说，这两件事要分开：

1. 相对 Skill 目录解析
   - Agent 在理解 `SKILL.md` 时，应优先把 `scripts/analyze_logs.py` 理解为相对于 Skill 根目录的路径

2. shell 当前工作目录
   - 这是 `run_shell` 实际执行时的 `cwd`
   - 它可能是仓库根目录、用户工作目录、显式设置的目录，未必是 Skill 目录

因此：

```text
按 Skill 目录解析相对路径
!=
shell 当前就在 Skill 目录
```

### 20.8 更常见、更稳妥的做法是先解析成绝对路径再执行

比起强依赖 shell 切到 Skill 目录，更常见、更稳定的做法通常是：

```text
SKILL.md 写相对路径
 -> Agent 按 Skill 目录解析
 -> 转成绝对路径
 -> run_shell 执行绝对路径命令
```

例如文档里写：

```text
python scripts/analyze_logs.py --input logs/app.log
```

更稳的实际执行方式通常是：

```text
python <Skill绝对路径>/scripts/analyze_logs.py --input <项目绝对路径>/logs/app.log
```

这种方式的优点：

- 不依赖 shell 当前目录
- 不容易因为 `cwd` 变化而跑错脚本
- 多个 Skill / 多个仓库并存时更稳定
- 对宿主实现更简单，歧义更少

所以经验法则通常是：

- 文档里写相对路径，可读性更好
- 执行时转绝对路径，稳定性更高

### 20.9 一条完整的推荐心智模型

可以把“Skill 包执行脚本”这类场景压缩成下面这条链路：

```text
SKILL.md
 -> 提供任务目标、调用时机、命令模板、参数说明
 -> 模型选择 run_shell / exec
 -> Agent 先把 Skill 相对路径解析成绝对路径
 -> shell 执行 python / uv / node 命令
 -> 脚本输出 stdout / stderr，或写入文件
 -> 工具结果回流给模型
 -> 模型继续决策
```

## 21. 为什么 OpenClaw 不只是一个大 switch-case

从设计上看，OpenClaw CLI 没有退化成一个大文件里的字符串分支，而是使用了：

- root fast path
- Commander 命令树
- lazy registration
- plugin CLI injection
- preAction / config guard / plugin registry preload

这样设计的原因主要有：

- 命令面足够大，需要模块化组织
- 常用命令需要尽量快的冷启动
- 复杂命令族需要完整帮助、选项、子命令支持
- 插件系统需要有机会把能力接到 CLI
- 某些命令又需要避开不必要的插件预加载和重解析成本

也就是说，OpenClaw CLI 不是“简单壳脚本集合”，而是一套小型命令平台。

## 22. 小结

如果把 OpenClaw CLI 压缩成一句话，可以这样理解：

> 它是一套“本地进程入口 + argv 解析 + 命令树注册 + fast path 路由 + 业务调用 + 插件扩展”的命令平台。

如果再压缩成一条主干链路，可以写成：

```text
Shell / script
 -> openclaw
 -> entry / run-main
 -> fast path 或 Commander 命令树
 -> CLI 适配层
 -> commands / gateway / agents / plugins
 -> 输出结果
```

如果从 LLM 视角看，则可以再包一层：

```text
LLM
 -> shell / exec tool
 -> openclaw ...
 -> OpenClaw CLI 命令注册与分发
 -> 内部业务函数
```

而如果再把 Skill 加进去，则变成：

```text
Skill
 -> 指导模型选择合适的 CLI 命令或宿主能力
 -> LLM 调用 run_shell / exec / read_file / http_request 等工具
 -> 宿主落地执行
 -> OS / 外部 CLI / 内部 API 返回结果
```

这就是 OpenClaw “CLI 与命令体系”在本地命令入口、Agent 能力桥接和外部独立 CLI 产品之间的整体位置。

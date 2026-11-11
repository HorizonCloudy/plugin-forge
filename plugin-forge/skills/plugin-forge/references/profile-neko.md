# profile：N.E.K.O（猫娘桌宠）

## ⓪ 陈旧门禁（用本 profile 前必跑，一条命令）

```
gh api repos/Project-N-E-K-O/N.E.K.O/contents/scripts/custom_channels/neko_channel.py --jq .sha
```

- 返回 sha → NekoClaw 重写切换点（issue #3683 的 PR3）尚未进 main，§3/§7 契约仍有效；
- 返回 404 → 切换点已进 main：§3/§7 视为**过期**，先按新 main 重核再用，重核不了的标 [未核验]；
- 本机宿主版本已含切换点 → 同 404 处理。
- 实测通过：2026-11-11，sha 85ea534，profile 有效。
- **2026-11-11 基线推进到 0984249**（#3686 合入）：diff 文件清单核对——改动全部落在
  memory/long_term_sync/chat_sync/prompts/locales 内部，插件契约（48916、/runs、SDK 装饰器、
  user_plugin_server 入口、/health）零变化，§3/§7 结论维持有效。
- **junction 警告**：plugin_skill_manager 安装目录里的 skills\* 全是 junction，写它们=直写
  .zcode / .agents / .workbuddy / .qwenpaw 等源目录；改前先 dir /a 看是不是 <JUNCTION>。


> 首例平台 profile。团队核心平台无关，接入别的平台请另写 profile，不要改本文件语义。
> **核验基线：上游 `Project-N-E-K-O/N.E.K.O` main @ `d597dae`（2026-11-10 实读源码）**；
> 沙箱契约另经 `neko-plugin-sandbox` 复核（commit `645da54`，2026-11-07）。
> 每条能力面结论带 `文件:行`。上游若升版，先复核再改。

## 1. 身份与安装形态
- N.E.K.O. = 桌面猫娘 AI 宿主；插件 = **独立 Python 进程**（独立进程天然隔离崩溃）。
- 消息平面走 **ZMQ RPC**，默认 `tcp://127.0.0.1:38865`，可用 `NEKO_MESSAGE_PLANE_ZMQ_RPC_ENDPOINT` 改写
  `[FACT] plugin/settings.py:555-557`；另有 ZMQ event bridge 承载 events/lifecycle/runs（bridge queue `maxsize=4096`）
  `[FACT] plugin/core/zmq_transport.py`、`plugin/settings.py:625`。
- 对外 HTTP 面在插件服务器（见 §7）。`GET /health` 200 只证明**进程活着**，不证明插件被 autostart。
- 安装形态：源码目录（开发模式）或 `.neko-plugin` 包上架市场 `[FACT] plugin/settings.py:69-71、105-116`。

## 2. Manifest 契约
- 文件 `plugin.toml`。必填性：`id` **必填**、`entry` **必填**、`type` 选填、`version` 选填
  `[FACT] plugin/PLUGIN_DEVELOPMENT_GUIDE.md:142-147`。
- `type` 只允许 `plugin`（默认）/ `adapter`，其他历史类型已移除
  `[FACT] GUIDE:144`、`plugin/config/schema.py:217、241`、`plugin/server/application/plugin_projects.py:50`。
- `[plugin.host]` 已移除，写了直接报错 `[FACT] plugin/config/schema.py:18、235、444-445`。
- `id` 必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$` `[FACT] plugin/neko_plugin_cli/templates/generator.py:18`；
  `entry` 形如 `模块路径:类名`（模块 `[A-Za-z_][A-Za-z0-9_]*(\.[...])*`、类名 `[A-Za-z_][A-Za-z0-9_]*`）
  `[FACT] plugin/neko_plugin_cli/commands/validate_cmd.py:181、760、763`。
- `[plugin.sdk]` 兼容区间字段 `recommended` / `supported` 存在（可为空）`[FACT] plugin/config/schema.py:71-72、195-196`、`GUIDE:133-134、153`。
- `[plugin_runtime]` 节：`enabled` / `auto_start`（**默认 `False`**）/ `timeout`（必须 `0 < t <= 300`）；
  写成字符串布尔会被判为问题 `[FACT] plugin/config/schema.py:265-281`、`plugin/config/plugin_toml_semantics.py:130-140`。
- `id` 发布后不可改；改 id = 另一个插件身份，升级只换代码，保留 config/data/cache。

## 3. 入口与生命周期
- 三个入口互不可混用（最常踩的坑）：
  | 入口 | 写在哪 | 用途 |
  |---|---|---|
  | 宿主加载入口 | `plugin.toml` `[plugin].entry` | 指向 `NekoPluginBase` 子类 |
  | 运行时入口 | `@plugin_entry(id=...)` 方法 | 面板 / 跨插件 / Agent 调用 |
  | LLM 工具 | `@llm_tool(name=...)` 方法 | 对话期 tool-calling |
- 公开装饰器全集 `[FACT] plugin/sdk/plugin/decorators.py`：`@neko_plugin`:53（必需）、`@on_event`:57、
  `@plugin_entry`:88、`@lifecycle`:127（`startup`/`shutdown`/`reload`，`GUIDE:1018`）、`@message`:137、
  `@timer_interval`:156、`@custom_event`:175、`@hook`:200、`@before_entry`:210、`@after_entry`:219、
  `@around_entry`:228、`@replace_entry`:237、`@quick_action`:246。`kind` 默认 `"action"`（`custom_event` 为 `"custom"`）
  `[FACT] decorators.py:64、95、182`。
- 所有入口、生命周期、定时器、消息处理器**必须 `async def`**。
- 一律从 `plugin.sdk.plugin` 导入；**`plugin.sdk.shared` 是内部实现细节，不应直接导入**
  `[FACT] GUIDE:1717`（`plugin/sdk/shared/__init__.py:1-5` 自述为 lower-level primitives，部分仍在演进）。
- ctx 侧：`push_message` `[FACT] plugin/core/context.py:1050`、`push_message_async`:1509、
  `export_push` / `export_push_async` 支持 `text` / `binary` / `url` 三类导出 `[FACT] context.py:818-848`；
  经 `/runs` 触发的入口必须带 `run_id` `[FACT] context.py:640`。
- `@llm_tool` 可声明 `params`（Pydantic 自动生 `input_schema`）、`llm_result_model` / `llm_result_fields`
  `[FACT] GUIDE:1006、1013`、`plugin/core/communication.py:929-931`、`plugin/core/registry.py:833-872`。

## 4. 能力面
- **明确支持** `[FACT]`：入口注册、消息推送、图片上传（`ctx.images`，`plugin/core/context.py:274`）、
  模型调用（`ctx.models`，`context.py:278`；HTTP 面 `POST /chat/completions`、`GET /usage`、`GET /slots`）、
  store/配置、`data_path`/`cache_path`、Hosted TSX 面板、HTML 卡片、跨插件调用、i18n、
  定时 / 生命周期 / 消息 / 自定义事件 / 入口拦截链 / 快捷操作（见 §3 装饰器全集）。
- **只读 OS 活动快照** `[FACT] plugin/sdk/plugin/activity.py:9-25`：`get_os_activity_snapshot()` →
  `OsActivitySnapshot(os_signals_available, foreground_category, system_idle_seconds, privacy_state)`，
  `privacy_state ∈ visible|private|unavailable`。**拉取式，且只有这四个字段。**
- **明确不支持** `[FACT]`：Avatar 表情 / 动作 API、情绪修改 API、`[plugin.host]`、`plugin.sdk.extension`；
  在 `plugin/sdk` 全树 grep `avatar|emotion|petting|mouse|pointer` **零命中** →
  **没有桌面鼠标/触摸事件推送**，插件拿不到"摸头"这类宿主交互事件，只能读上面的快照。
- 降级路径：表情/交互诉求 → HTML 卡片或视图表达；"用户在不在、在忙什么" → `get_os_activity_snapshot`
  （别承诺能拿到点击/触摸事件）。

## 5. 错误约定
- 成功 `Ok({...})`，失败 `Err(SdkError("原因"))`；`Ok/Err/Result/SdkError/TransportError/unwrap/unwrap_or`
  均从 `plugin.sdk.plugin` 导出 `[FACT] plugin/sdk/plugin/__init__.py`。**不要 `raise`**（定时回调里 raise 会拖垮调度）。
- 工具错误返回脱敏错误码；别把原始对话 / 用户密钥 / 隐私 payload 写进日志或结果。

## 6. 硬性限制速查
- `push_message` 单条 payload 默认 **512 KiB**，可经 `NEKO_MESSAGE_PLANE_PAYLOAD_MAX_BYTES` 调整；
  插件侧与宿主 ingest 共用同一常量（防止限制漂移）`[FACT] plugin/settings.py:602-610`。大图先 `ctx.images.upload` 换 URL part。
- **持久数据一律写 `data_path` / 缓存写 `cache_path`** `[FACT] GUIDE:584-598、1586-1587`；
  `self.plugin_dir` 是随包安装目录（代码 / manifest / 静态资源）`[FACT] GUIDE:264`、`plugin/sdk/plugin/base.py:116-123`，
  **不是可写区**。（`plugin_dir` 的强制只读由本机蒸馏文档 `neko-plugin-dev/reference/sdk-core.md:20、40` 断言，
  本轮未在上游逐行核到拦截点 → 该"强制层"记 `[未核验]`；但"往安装目录写"一律按平台约定封驳。）
- **Windows 数据根取 `LOCALAPPDATA`**（不是 `HOME` / `USERPROFILE`）`[FACT] utils/config_manager/storage_roots.py:367-373`。
- 用户插件执行根可被 `PLUGIN_CONFIG_ROOT` 覆盖，否则 `<数据根>/N.E.K.O/.neko-plugin-installations/plugins`；内置根 = 仓库 `plugin/plugins`
  `[FACT] plugin/settings.py:69-71、105-116`。用户配置在 `<数据根>/plugins/<id>/config/plugin.toml`。
- **插件启动超时 `NEKO_PLUGIN_STARTUP_TIMEOUT` 默认 `10.0` 秒，>300 直接 `ValueError`** `[FACT] plugin/settings.py:314-315、788-791`。
- `@llm_tool` 的 `callback_url` 与 `/api/tools` **只接受 127.0.0.1**。
- 外部文本不得拼进系统提示词；URL 拼接必须 `quote`。

## 7. 沙箱与验证命令
- standalone：`build_plugin_server_app(manage_lifecycle=True)` `[FACT] plugin/user_plugin_server.py:81`；
  该参数**默认 False** `[FACT] plugin/server/http_app.py:134-136`，autostart 由 `if manage_lifecycle: await lifecycle_startup()` 决定
  `[FACT] plugin/server/http_app.py:190、246`。
- **`NEKO_PLUGIN_HOSTED_BY_AGENT` 已不是开关**：只剩 agent_server 在写 `[FACT] app/agent_server/api_runtime.py:857`；
  `http_app.py:185` 注释明说早先读它会在 import 时冻结。
- Windows 强制 `WindowsSelectorEventLoopPolicy` `[FACT] plugin/user_plugin_server.py:62`。
- 端口 env `NEKO_USER_PLUGIN_SERVER_PORT`（上游默认 48916，standalone 占用时向后找并回写）
  `[未核验：取自沙箱契约表所引 config/network.py:193，本轮未复述读行]`。
- **只读判定路由** `[FACT]`：`GET /health`(health.py:19)、`/available`:24、`/server/info`:32、
  `GET /plugins`(plugins.py:42)、`GET /plugin/status`:35、`GET /plugin/{id}`:53、
  `GET /plugin/messages`(messages.py:22)、`GET /plugin/metrics[/{id}[/history]]`(metrics.py:26/34/42)、
  `GET /plugin/{id}/logs` 及 `/files`、`/directory`、`/export`(logs.py:81/104/112/120)、
  hosted UI：`GET /plugin/{id}/surfaces`(plugin_ui.py:607)、`/hosted-ui/source`:621、`/hosted-ui/context`:646、`/ui-info`:594、
  `GET /plugin-ui-sdk/display.js`:293、config：`GET /plugin/{id}/config`(config.py:108) 等。
- **变更类路由走 `mutation_router`（鉴权与只读路由不同，别拿来当探活）** `[FACT]`：
  `POST /plugin/{id}/start`(plugins.py:88)、`/stop`:130、`/reload`:196、`PUT /plugin/{id}/auto-start`:159、
  `POST /plugins/refresh`:184、`DELETE /plugin/{id}`:172、`POST /runs`(runs.py:35)、`POST /runs/{id}/uploads`:52、`/cancel`:91。
- **易错路由**：集合 `GET /runs` 不存在（405），但单个 run 有 `GET /runs/{run_id}`、`/blobs/{blob_id}`、`/export`
  `[FACT] runs.py:44/82/108`；裸 `/messages` 不存在（真实路径 `/plugin/messages`）。打错会误判成插件故障。
- **autostart 判定链（缺一即不启动）**：`manage_lifecycle=True` ＋ `[plugin_runtime] auto_start=true`（省略即 false）
  ＋ `enabled`/`runtime_enabled` 非 `False` ＋ `runtime_load_state != "failed"` ＋ 源未缺失 ＋ id 不在待审批集合
  `[FACT] plugin/config/schema.py:267`、`plugin/core/communication.py:939`、`plugin/server/infrastructure/autostart_approvals.py`、
  `plugin/server/application/plugins/query_service.py:21、539-552`（`/plugin/status` 会返回 `autostart_pending` 字段）。
- 静态检查 CLI 动词实测 **11 个**：`init`、`setup-repo`、`create-repo`、`sync`、`check`、`lint`、`precheck`、
  `build`、`install`、`analyze`、`publish` `[FACT] plugin/neko_plugin_cli/cli.py:105-113` + 各 `*_cmd.register`
  （`sync` 由 `deps_cmd.py` 注册；`validate_cmd.py` 存在但**不注册动词**，是 check/precheck 的内部件）。
  **没有 `run` / `release` / `deps` 动词** —— 别按这些名字调，会 unknown command。
- 沙箱脚本：`neko-plugin-ops/skills/neko-plugin-sandbox/scripts/sandbox.py`（`doctor` / `start` / `inspect` …）。
  加载插件前 `uv run neko-plugin check <id>` 需 0 error；`inspect` 出现 "declared but NOT registered" = entry-404 根因。

## 8. 生态与市场
- 市场：<https://project-neko.online/zh-CN/plugins/>；仓库：`Project-N-E-K-O/N.E.K.O`（个人 fork 属主用 `gh api user -q .login` 探测，勿写死——本机账号已由 addsas222 改名 HorizonCloudy，旧名 URL 靠 GitHub 重定向续命，但 gh 按旧名 list/搜索会挂）。
- 开发教程：仓库 `plugin/PLUGIN_DEVELOPMENT_GUIDE.md`；脚手架：`uv run neko-plugin init <id>`。
- 宿主侧市场桥接前缀 `/market`（catalog / submissions / install / oauth / status 等）
  `[FACT] plugin/server/routes/market_bridge.py:87、757-812、1055-1150、1693-2049`；知识库桥 `/market/knowledge` `[FACT] knowledge_bridge.py:48`。
- **插件制作工作台不是纯前端**：`/plugin-projects/*`（`APIRouter(prefix="/plugin-projects", dependencies=[require_admin])`
  `[FACT] plugin_projects.py:30`，含 `/{project_id}/toolchain`:163、`/publish-status`:171、`/publish-task`:196）
  与 `/plugin-cli/*`（`/plugins`:265、`/packages`:273、`/inspect`:305、`/verify`:316、`/build`:281、`/install`:327）在宿主进程里调 CLI。
- **沙箱不验 Market 提审/发布**（要真实 GitHub 凭据，触红线）；最多验到桥接可达 + 未授权时干净拒绝。
- 市场惯用法历史样本数据在原 `neko-plugin-ops/references/neko-market-patterns.md`（127 样本 @2026-10-26，分母固定）。

## 9. 高频封驳原因（NEKO 特有）
1. 方案要表情 / 动作 / 情绪 / 桌面交互事件 API（平台没有；只有 §4 的只读活动快照）
2. 把 `@llm_tool` 当运行时入口用（应 `@plugin_entry` ＋ `llm_result_fields` / `llm_result_model`）
3. 定时回调里 `raise`
4. 外部文本拼进系统提示词
5. 没写失败降级
6. 把"没 autostart"归因于目录名或环境变量（真因在 §7 那条判定链，尤其 `auto_start` 默认 false 与待审批集合）
7. 拿 `GET /runs` 或裸 `/messages` 探活（405 / 404，正确路由见 §7）
8. 往安装目录写文件 / 改写宿主配置（含"插件自注册"）—— 违反 §6
9. 调用不存在的 CLI 动词（`run` / `release` / `deps` / `validate`）

## 10. 复核记录
- **2026-11-10 对齐上游 main `d597dae`（实读源码）**：
  ① §4 新增「只读 OS 活动快照」支持项——旧版把桌面能力一刀切否掉，会**误封**只需"用户忙闲 / 前台类别 / idle 秒数"的方案；
  同时把"不支持"精确到**无鼠标/触摸事件推送**（`plugin/sdk` grep 零命中）。
  ② §3 补齐装饰器全集与 `@before/after/around/replace_entry` 拦截链、`@quick_action`（旧版只列 3 个入口，会漏判可实现性）；
  补 `plugin.sdk.shared` 禁导入的上游出处（GUIDE:1717）。
  ③ §7 路由表按源码逐条带行号重写：`/runs` 语义由"只有 POST"精确化为"集合无 GET、单个 run 有 GET"；
  新增 `logs*` / `metrics` / `surfaces` / `hosted-ui/*` / `PUT .../auto-start` / start|stop|reload|refresh；
  并区分只读路由与 `mutation_router` 变更路由。
  ④ 补 `NEKO_MESSAGE_PLANE_PAYLOAD_MAX_BYTES`(默认 512 KiB，可调)、`NEKO_MESSAGE_PLANE_ZMQ_RPC_ENDPOINT`(38865)、
  `NEKO_PLUGIN_STARTUP_TIMEOUT`(10.0s，>300 raise)、Windows 数据根 `LOCALAPPDATA`、执行根 `.neko-plugin-installations/plugins`、
  `[plugin_runtime]` 三字段与 autostart 判定链。
  ⑤ CLI 动词实测 11 个，确认 `validate` 不注册动词、无 `run/release/deps`。
  ⑥ 确认 `type` 仅 `plugin|adapter`、`[plugin.host]` 已移除并报错。
- **2026-11-11 NekoClaw 重写公告（issue #3683，六个 PR 直进 main，PR3 是切换点）**：
  插件稳定契约由宿主承诺守住（/runs、push_message、@llm_tool、args._ctx 的
  lanlan_name/conversation_id/entry_timeout、delivery 元数据）；但**调用方从两阶段判断器
  换成"使魔"把入口当工具调**——description/input_schema 要能脱离对话历史自解释、
  取消真正打到插件（POST /runs/{id}/cancel）、默认并发 10、同一入口可能被重复调用。
  PR3 删 48915 Tool Server 与 brain.*/app.agent_server 内部件；PR4 删随包 Chromium +
  playwright 运行依赖。新插件一律不写 48915/brain.* 依赖、不靠宿主 playwright；
  重核义务已落实为文首 ⓪ 陈旧门禁（一条命令自动判定，不靠记性）。
- **未核验**：应用版本号（`pyproject.toml:7` 为 `dynamic = ["version"]`，`[tool.hatch.version]` 指向 `APP_VERSION` 常量，本轮检出路径未含该文件，分支线索为 `chore/bump-0.9.1`）；
  standalone 默认端口 48916（见 §7 标注）；`plugin_dir` 强制只读的拦截点（见 §6 标注）。SDK 升版需重核。
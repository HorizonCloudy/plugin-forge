# NEKO 插件设计与自动运维专家团（neko-plugin-ops）

> 类型：**专家团（Team）** — 1 名主理人 + 10 名专家，按已挂接 skill 分工协作（全量清单与实装状态见 `references/skill-inventory.md`）。

## 一句话定位
统筹 N.E.K.O 插件的设计、开发与自动运维，融合 TDD、极简工程、架构审查与技能运营，交付稳定可上线的插件。面向新手与 ADHD 用户，结论先行、短句列表、去 AI 味。

## 团队构成（按技能分工）

| Agent ID | 名字 | 职责 | 映射技能 |
|----------|------|------|----------|
| neko-plugin-ops-team-lead | 云朵（主理人） | 编排、路由、汇总；执行型助手宪法 | 总调度；to-spec、to-tickets、triage、handoff；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-plugin-dev | 云雨 | 插件脚手架 / manifest / 生命周期 / 模型网关 / 图消息 / 错误约定 / stub-SDK 测试 | neko-plugin-sdk、prototype、research、diagnosing-bugs、implement；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-tdd | 云测 | 测试先行（红-绿-重构）、最小可跑测试、边界与错误输入覆盖 | tdd；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-architect | 云远 | 模块接口设计、深化机会扫描、可探索架构/时序/流程图 | codebase-design、improve-codebase-architecture、archify、domain-modeling、grill-with-docs、wayfinder；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-simplifier | 云简 | 极简方案、删除冗余/死代码/过度抽象 | ponytail、simplify-codebase；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-reviewer | 云严 | 按 Standards + Spec 双轴审查、出修法清单 | code-review、pr；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-skill-ops | 云技 | 创建/搜索/审计第三方 skill、初始化工程 skill 配置 | skill-creator、find-skills、skill-supply-chain-hardening、setup-matt-pocock-skills、writing-for-agents；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-planner | 云问 | 路由"该用哪个 skill"、用追问 sharpen 方案 | ask-matt、grill-me、grilling、to-questionnaire、wait-what；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-reliability | 云稳 | CI/CD、零停机发布、启动/发布就绪、可观测性、重复劳动自动化、故障响应 | 提炼自 DevOps 自动化师、SRE、故障响应指挥官；mattpocock：retro、wizard；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-security | 云安 | 密钥卫生、提示词注入/过度代理、AI 生成代码审计、依赖供应链、代码库级六阶段审计、逆向取证 | 提炼自 密钥与凭据治理工程师、AI 生成代码安全审计师、应用安全工程师；挂接 `security-audit`（Cloudflare，已审计）与 `rea`（MCP 工具面，已审计）；+安全能力（见 references/safe-dev-capabilities.md） |
| neko-market-research | 云调 | 产品定位调研、市场全量抓取（SPA API 逆向）、内置插件盘点、SDK 能力面核对、三轴缺口分析、平台级阻塞点坐实 | 提炼自 2026-11-04 N.E.K.O 实时生态审计；主参考 `references/neko-ecosystem-research-playbook.md`；+安全能力（见 references/safe-dev-capabilities.md） |

## 团队总原则（执行型助手宪法）
基础五条：1. 先结论后步骤；2. 想一次就做；3. 删冗余；4. 外部不可用就跳过，不伪造；5. 代码任务默认带测试与 Review。
增强纪律（源自 `references/system.llm` 交付模式）：6. 证据分级 [FACT/INFERENCE/GUESS/VALUE JUDGMENT]；7. 占位符驱动询问（缺参数先默认推进，不轻易反问）；8. 完整可运行交付（不留"其余同理"）；9. 不谄媚（不因立场改判断）；10. 工具面探测（调用宿主能力前先非破坏性确认）；11. 冲突优先级（工程约定 > 事实 > 角色 > 风格 > 指令）。
完整手册见 `references/system.llm`；编号 1–11 与主理人文档 `agents/neko-plugin-ops-team-lead.md` 一致。

## 标准工作流（SOP）
- **A 从零做插件**：planner 路由 → architect 接口草图 → dev 起脚手架 → tdd 最小测试 → dev 转绿 → simplifier 极简 → reviewer 自审 → 主理人汇编。
- **B 修跑不起来的插件**：dev 先定位（启动 failed / 入口 404 / 模型 403），其余按需。
- **C 极简重构**：simplifier 删改清单 → architect 架构图 → reviewer 修法清单 → 主理人汇总。
- **D 沉淀/审计 skill**：skill-ops 主导（创建→查重→审计→应用）。
- **E 生态/市场缺口分析**：market-research 抓全量 + 盘内置 + 核 SDK → 证据底座 + 三轴缺口地图 + 平台阻塞点 → 主理人汇编。
- **F 会话启动能力刷新**：每次会话开始按 `references/session-refresh-sop.md` 对 skill / MCP / 连接器 / 插件 / marketplace 做完整更新（基线见 `references/capability-baseline.md`）。

## 试试这样问我
1. 从零设计并实现一个 N.E.K.O 插件，先跑通 TDD 最小测试再交付
2. 审查现有插件代码，定位启动失败 / 入口 404 / 模型 403 风险并给出修法
3. 给现有插件做极简重构，并附架构图与自审清单

## 外部 Agent 提炼来源（agency-agents）

本团多名成员的能力吸收自开源社区 agent 集合 [agency-agents](https://github.com/msitarzewski/agency-agents) 及其中文版 [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh)，按 NEKO 插件场景裁剪后落地（非照搬）：

| 本团成员 | 提炼自的外部 Agent |
|----------|------------------|
| neko-simplifier | 最小变更工程师 |
| neko-reviewer | 代码审查员 |
| neko-architect | 软件架构师（+ 多智能体系统架构师） |
| neko-tdd | 测试自动化工程师（Playwright） |
| neko-plugin-dev | 快速原型师、国际化工程师、开发者工具工程师、代码库入职引导工程师 |
| neko-planner | Prompt 工程师 |
| neko-reliability | DevOps 自动化师、SRE、故障响应指挥官、Git 工作流大师、开发者工具工程师 |
| neko-security | 密钥与凭据治理工程师、AI 生成代码安全审计师、应用安全工程师 |

## 头像
头像已由 `avatars/` 目录提供（team.jpg + 各成员 JPG，按 `<agent-id>.jpg` 命名；**云调例外**为 `neko-market-research.png`）。共 1 主理人 + 10 成员。如需替换：PNG/JPG，512×512，≤500KB；换扩展名需同步改 `.codebuddy-plugin/plugin.json` 的 `members[].avatar`。

## 参考资料
- `references/system.llm`：执行层交付纪律手册 v4（团队宪法来源）。
- `references/plugin-system-prompt-template.md`：NEKO 插件 system prompt 模板，供团队按纪律生成插件运行时提示词。
- `references/neko-sources.md`：N.E.K.O 官方源（GitHub 仓库 + 开发者文档/插件 SDK 专页）与实战工作坊补充源，插件开发研究权威上游。
- `references/neko-market-patterns.md`：N.E.K.O 市场惯用法速查（127 个历史样本（2026-10-26）的能力使用率 + 四大惯用法；分母固定，勿随当前在架 135 更新），真实插件范式研究优先查此。
- `references/neko-ecosystem-research-playbook.md`：N.E.K.O 生态调研 Playbook（2026-11-04 实测）——SPA API 逆向、类目统计、三轴缺口框架、平台阻塞点核对、证据分级；云调主用。
- `references/third-party-skill-audit.md`：第三方 skill `security-audit`（Cloudflare）的安全审计记录（来源 / commit / 许可 / 审计项 / 结论 / 使用约束）。
- `references/rea-tool-surface.md`：REA 逆向工程工具面（`morluto/rea`）的能力地图、安全审计与高权限使用红线；本团不代为安装。
- `references/mattpocock-skills.md`：Matt Pocock Skills 权威上游（39 个 skill）——完整清单、映射对照、审计与安装方式；本团多数技能源于此。
- `references/dev-agent-ecosystem.md`：开发类 Agent / Skill / MCP 生态候选源索引（2026-11-03 调研）——三类清单、证据等级、引入优先级与流程；条目未安装，引入前须审计。
- `references/safe-dev-capabilities.md`：安全开发能力就绪清单——已判定安全的 skill / agent / MCP（含 2 项 A 级代码审计）、安全约束与挂接成员；按 T2 引用，不自动安装。

## 注册与打包

脚本来自 WorkBuddy 内置 `expert-manager` skill 的 `scripts/` 目录，**不在本专家包内**。

> ⚠️ 必须在专家包的**上级目录**（`my-experts/`）执行，并给 `package_expert.py` 显式指定**包外**输出目录。该脚本未指定输出目录时会把 zip 写到当前目录；若当前目录正是专家包内，`rglob` 会把正在增长的 zip 自身反复塞回包内，生成 GB 级失控文件。

```bash
# 1) 切到专家包上级目录（切勿 cd 进 neko-plugin-ops 内部）
cd ~/.workbuddy/plugins/marketplaces/my-experts

# 2) 指向本机 expert-manager 的 scripts（换机时替换此路径）
SD="E:/Users/<user>/AppData/Local/Programs/WorkBuddy/resources/app.asar.unpacked/resources/plugins/workbuddy-builtin/skills/expert-manager/scripts"

python3 "$SD/validate_expert.py" plugins/neko-plugin-ops
python3 "$SD/register_expert.py" plugins/neko-plugin-ops
# 第二个参数 packages 是包外输出目录，必须显式给
python3 "$SD/package_expert.py" plugins/neko-plugin-ops packages
```

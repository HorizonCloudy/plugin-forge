# 插件制造专家团（plugin-forge）· 通用范式

> 由 NEKO 插件制造专家团（`neko-plugin-ops` + `neko-plugin-court`）提炼的**平台无关**多智能体范式：
> 为任意目标平台设计、实现、测试、审查、加固并验证一个可安装运行的插件 / 扩展。

## 范式三大件

1. **角色型专家团**（提炼自 `neko-plugin-ops`）：1 名主理人 + 12 名职能专家，覆盖开发 / 测试 / 架构 / 极简 / 审查 / 规划 / 能力运营 / 可靠性 / 安全 / 生态调研 / 运行时验证。
2. **契约前置门禁**（提炼自 `neko-plugin-court`，即「门下省」的通用化）：`plugin-forge-contract`（契约审议师）持**真实否决权**——方案要求的 API 在目标平台上做不到，直接封驳，不许「先写着试试」。封驳必须附编号理由 + 可执行改法；连续 2 次封驳升级用户裁决。**没有准奏不许写码。**
3. **目标平台 profile 机制**（本次通用化的核心）：平台知识全部移出团队核心，按 profile 渐进加载。团队核心是平台无关的；接入新平台 = 写一份新 profile，不改任何成员。

```
用户需求
   ↓
主理人 lead ──分拣──→ planner/architect 起草方案 ──→ contract 契约审议 ──准奏──→ 派发执行组
   ↑                    （dev/tdd/architect）          （封驳则退回重拟）        dev · tdd · architect
   │                                                                        simplifier · reviewer
   └────────────── 验收汇编（结论 / 证据 / 需你手动 + 风险）←── sandbox 运行时验证 · security 门禁
```

## 团队构成（1 主理人 + 12 专家）

| Agent ID | 名号 | 职责 | 提炼来源 |
|---|---|---|---|
| plugin-forge-lead | 交付总监（主理人） | 分拣、编排、路由、汇编；守契约门禁 | neko-plugin-ops-team-lead |
| plugin-forge-contract | 契约审议师 | 按目标平台真实能力面审议方案，可封驳 | neko-court 门下省 + 钦天监 |
| plugin-forge-dev | 插件开发工程师 | 脚手架 / manifest / 生命周期 / 错误约定 / stub 宿主测试 | neko-plugin-dev |
| plugin-forge-tdd | 测试驱动工程师 | 红-绿-重构、最小可跑测试、纯逻辑与 SDK 分层 | neko-tdd |
| plugin-forge-architect | 架构设计师 | 模块接口设计、可探索架构图、深化机会扫描 | neko-architect |
| plugin-forge-simplifier | 极简工程师 | 极简方案、删冗余 / 死代码 / 过度抽象 | neko-simplifier |
| plugin-forge-reviewer | 代码审查师 | Standards + Spec 双轴审查、修法清单 | neko-reviewer |
| plugin-forge-planner | 规划问诊师 | 路由「该用哪个能力」、追问 sharpen 方案 | neko-planner |
| plugin-forge-skill-ops | 能力运营师 | 第三方 skill / prompt 的创建、查重、审计、挂接 | neko-skill-ops |
| plugin-forge-reliability | 运维可靠性工程师 | CI/CD、发布就绪、可观测性、故障响应 | neko-reliability |
| plugin-forge-security | 安全工程师 | 密钥卫生、注入 / 过度代理、AI 代码审计、依赖供应链 | neko-security |
| plugin-forge-market-research | 生态调研分析师 | 平台生态 / 市场全量调研、缺口分析、证据分级 | neko-market-research |
| plugin-forge-sandbox | 运行时验证工程师 | 隔离运行时真跑宿主，验证插件能否加载 / 启动 | neko-sandbox |

## 与原 NEKO 版的差异（通用化清单）

| 原内容 | 通用化处置 |
|---|---|
| 团队知识硬编码 N.E.K.O SDK | 移入 `skill/references/profile-neko.md`，成员按任务读 profile |
| 门下省（朝议）独立包 | 并入为 `plugin-forge-contract` 成员 + Workflow A 第 3 步门禁 |
| Workflow F 会话启动能力刷新（WorkBuddy 专属） | 删除，通用版不依赖宿主能力基线 |
| 沙箱硬编码本机路径 / 健康路由 | 移入 profile 的「沙箱与验证命令」节；成员先探测路由面再判定 |
| `references/system.llm` 604 行纪律手册 | 提炼为 `skill/references/constitution.md`（11 条宪法） |
| `neko-market-patterns.md` 等 NEKO 数据 | 留在原 NEKO 包，profile-neko 给出指针，不搬数字 |
| 三省六部 / 云朵云雨人设 | 去人设化，职能名号保留；NEKO 版不受影响，可继续独立使用 |

## 安装矩阵

| 目标工具 | agents（真子代理） | skill（共享知识） | Codex 专属 |
|---|---|---|---|
| **Zcode** | `~/.zcode/agents/plugin-forge-*.md`（13） | `~/.zcode/skills/plugin-forge/` | — |
| **Claude Code** | `~/.claude/agents/plugin-forge-*.md`（13，精简 frontmatter） | `~/.claude/skills/plugin-forge/` | — |
| **Codex** | —（无子代理，用单代理连续角色扮演） | `~/.codex/skills/plugin-forge/` | `~/.codex/prompts/plugin-forge.md`（`/plugin-forge` 触发） |

## 如何接入一个新平台（写 profile）

1. 复制 `skill/references/profile-template.md` 为 `profile-<平台>.md`。
2. 逐节填：manifest 契约 / 入口与生命周期 / 能力面（支持 / 不支持 / 降级）/ 错误约定 / 沙箱与验证命令 / 生态与市场 / 官方源。
3. **能力面结论必须 `[FACT]`（有文档或源码章节）或 `[未核验]`，不许 `[INFERENCE]` 硬说"应该支持"。**
4. 更新 `SKILL.md` 的 profile 清单表，一行即可。

## 出处与许可

- 角色与工作流提炼自本机 `neko-plugin-ops`、`neko-plugin-court` 两包（作者云朵）。
- 朝议制度模型参考 [cft0808/edict](https://github.com/cft0808/edict)（MIT）；原包未复制其源码，本范式同样只借鉴制度。
- 外部 Agent 能力吸收自 [agency-agents](https://github.com/msitarzewski/agency-agents) / [agency-agents-zh](https://github.com/jnMetaCode/agency-agents-zh)，按插件制造场景裁剪。

# plugin-forge —— 插件制造专家团

一个团队，一个插件。1 主理人 + 13 专家，为任意宿主平台（N.E.K.O / VSCode / Chrome / Obsidian / MCP / Bot / CLI…）设计、实现、测试、审查、加固并验证可安装运行的插件。

原 neko-plugin-ops（12 角色）与 neko-plugin-court（朝议流水线）已并入：角色由 plugin-forge 14 人编制承接；两个团队的 NEKO 平台资产（23 份调研 references、运行时沙箱 skill、会话能力刷新脚本）降级为 N.E.K.O profile 的扩展阅读，保留全部功能。历史在 git log（tag 前最后一次三团队提交）。

## 机制

- 契约先行：`agents/plugin-forge-contract.md` 持真实否决权，没有准奏不写码。
- TDD + 极简 + 安全门禁 + 运行时验证（`skills/neko-plugin-sandbox/` 真实冒烟）。
- 工作流 H：宿主破坏性变更（RFC/changelog）对插件机队的影响审计与上游回帖礼仪。
- 双风格文档门禁：`plugin-forge-docs` 内置 ASD-STE100 + humanizer（中英同等），见 `skills/plugin-forge/references/style-anti-slop.md`；外部内容入库先过 `AUDIT.md` 流程。
- 平台 profile：契约唯一权威 `skills/plugin-forge/references/profile-neko.md`（基线 0984249，文首 ⓪ 陈旧门禁一条命令判时效）。NEKO 扩展阅读在 `references/neko/`。

## 安装

- **Claude Code / marketplace 宿主**：本仓库即插件，marketplace 单条目指向 `./`。
- **Codex**：复制 `skills/plugin-forge/` 到 `~/.codex/skills/plugin-forge/`；`codex/prompts/plugin-forge.md` 到 `~/.codex/prompts/`（触发 `/plugin-forge`）。沙箱 skill 同样复制到 skills 目录。
- **zcode**：`agents/*.md` → `~/.zcode/agents/`，`skills/plugin-forge/` → `~/.zcode/skills/plugin-forge/`。
- **CodeBuddy**：按 marketplace 安装，或复制 plugin.json 字段到 `.codebuddy-plugin/`。

## 目录

```
agents/            14 个专家人设
skills/plugin-forge/       范式 skill + references（含 neko/ 扩展阅读 23 份）
skills/neko-plugin-sandbox/ NEKO 运行时沙箱 skill + scripts/sandbox.py
codex/prompts/     Codex 单代理运行入口
scripts/           session_capability_refresh.py（会话能力底座刷新，只读）
AUDIT.md LICENSE
```

MIT，第三方摘要署名见 LICENSE 与 AUDIT.md。

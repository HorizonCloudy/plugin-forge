# plugin-forge 插件制造专家团

通用「插件制造专家团」范式：1 主理人 + 12 专家，为任意宿主平台（N.E.K.O / VSCode / Chrome / Obsidian / MCP / Bot / CLI…）设计、实现、测试、审查、加固并验证可安装运行的插件。

核心机制：契约先行（方案未过审议不许写码）+ TDD + 极简工程 + 安全门禁 + 运行时验证 + 陈旧门禁。含工作流 H：宿主破坏性变更（RFC/changelog）对插件机队的影响审计与上游回帖礼仪。

## 内容

| 目录 | 是什么 | 装到哪 |
|---|---|---|
| `plugin-forge/` | skill 本体（SKILL.md + references/） | `~/.codex/skills/` 或 `~/.agents/skills/` 或 `~/.zcode/skills/` |
| `agents/` | 13 个 zcode 成员人设（plugin-forge-*.md） | `~/.zcode/agents/`（Claude Code 用 `.claude/agents/`） |

Codex 无子代理：装 skill 后单代理按工作流连续角色扮演，触发词「插件制造专家团 / plugin-forge」。

## 平台 profile

现含 N.E.K.O profile（`plugin-forge/references/profile-neko.md`）。接新平台按 `profile-template.md` 写：必须带 ⓪ 陈旧门禁（一条命令判定 profile 是否过期，不靠记性）。

版本 1.1.0（2026-11-11）。

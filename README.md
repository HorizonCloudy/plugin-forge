# Experts —— 插件制造专家团（三团队合集插件）

| 团队 | 是什么 | 形态 |
|---|---|---|
| `plugin-forge/` | 平台无关的插件制造范式：1 主理人 + 13 专家，契约先行 + TDD + 安全门禁 + 宿主破坏性变更影响审计（工作流 H）+ 双风格文档门禁（ASD-STE100 + humanizer，中英同等） | skill（`skills/plugin-forge/`）+ 14 个 agent + Codex prompt |
| `neko-plugin-ops/` | N.E.K.O 专属：插件设计与自动运维专家团，含能力基线、会话刷新 hook、运行时沙箱 | 12 个 agent + skill（neko-plugin-sandbox）+ references + scripts |
| `neko-plugin-court/` | N.E.K.O 专属：插件朝议流水线（中书/门下/尚书六部），门下省持真实否决权 | 11 个 agent + references |

## 安装

**Claude Code / 兼容 marketplace 的宿主**：仓库根即 marketplace（`.claude-plugin/marketplace.json`），添加本 repo 后可分别安装三个 plugin。

**Codex**：无 marketplace 子代理形态时装 skill——复制 `plugin-forge/skills/plugin-forge/` 到 `~/.codex/skills/plugin-forge/`；单代理连续角色扮演入口复制 `plugin-forge/codex/prompts/plugin-forge.md` 到 `~/.codex/prompts/`（触发 `/plugin-forge`）。

**CodeBuddy**：各团队目录下自带 `.codebuddy-plugin/plugin.json`。

**zcode**：`plugin-forge/agents/*.md` 复制到 `~/.zcode/agents/`，skill 复制到 `~/.zcode/skills/plugin-forge/`。

## 契约时效

N.E.K.O 平台契约以 `plugin-forge/skills/plugin-forge/references/profile-neko.md` 为准：
基线 0984249（2026-11-11），文首 ⓪ 陈旧门禁一条命令判定是否过期。NekoClaw 重写（上游 issue #3683）
的插件侧影响审计已完成：本仓库三团队全部不依赖将删接口。

## 其他

- 外部内容审计记录：`AUDIT.md`（humanizer / Humanizer-zh / asd-ste100 / 自有脚本，全 MIT，全通过）。
- 许可证：MIT（见 `LICENSE`，含第三方署名）。
- 仓库已脱敏：无个人邮箱、无本机用户名路径、无凭据特征串。

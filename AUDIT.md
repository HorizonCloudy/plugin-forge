# AUDIT —— 外部内容入库审计记录

审计方法：文件清单 → 许可证 → 脚本行为静态扫描（网络/写盘/执行/删除）→ SKILL 正文提示注入检查 → 结论。
2026-11-14 起增加机械分诊一步：`skills/plugin-forge/scripts/security_audit.py`，规则见文末「例行安全审计」。
审计人：plugin-forge-docs（文档工程师）流程执行，2026-11-11。

| 对象 | 版本 | 许可证 | 行为 | 结论 |
|---|---|---|---|---|
| blader/humanizer | v4.0.0 | MIT | SKILL.md 纯改写规则，1 个 Wikipedia 外链；scripts/validate-package.py 只读本包文件做结构校验 | 通过。规则已并入 references/style-anti-slop.md，未整包 vendor |
| op7418/Humanizer-zh | main | MIT | SKILL.md 中文模式库；tests/check_structure.py 只读比对两份文本 | 通过。同上 |
| woosal1337 asd-ste100 kit | 2.0.5 | MIT（kit；ASD-STE100 规范本身版权属 ASD） | ste-lint.py 本地 lint；hooks 为 Claude Code 专用；无网络 | 通过。规则摘要并入 style-anti-slop.md；本仓库未复制其代码文件，仅引用与摘要 |
| neko-plugin-sandbox/scripts/sandbox.py | 本仓库自有 | — | 全 127.0.0.1；git/uv/pip 子进程仅用于本地沙箱；taskkill 只杀自启进程；rmtree 只删自建目录 | 通过（2026-11-11 逐行复核）。依据源码 @645da54 的契约断言已在 0984249 复验 |
| session_capability_refresh.py | 本仓库自有 | — | 只读扫描 + stdout JSON，零第三方依赖，异常全捕获 exit 0 | 通过。示例路径已脱敏为 ~ |
| avatars/*.jpg/png（14） | — | — | EXIF 扫描 | 无 EXIF，通过 |
| intro.html（2） | — | — | 无 <script>/外链 src/onclick | 通过 |

## 脱敏记录（2026-11-11）

- 34 个文件中的 Windows 用户名路径 `C:/Users/<user>` → `~`
- 作者邮箱（个人 QQ 邮箱）→ GitHub noreply
- 删除 `__pycache__`、`plugin.json.bak-*` 过期产物
- 全库复查用户名/gho_/sk- 特征串 = 0 残留

## 残留风险

- style-anti-slop.md 是摘要而非全文；上游更新不会自动同步（升级触发：上游 major 版本变化）。
- sandbox.py 的 pip install 走 PyPI（环境准备用途，声明内），离线机器需自备依赖。

## 整合记录（2026-11-11，v2.0.0）

- 三团队并为一团：ops 12 角色与 court 朝议角色由 plugin-forge 14 人编制承接；`neko-plugin-ops/`、`neko-plugin-court/` 目录退役，其 avatars（14 张，无 EXIF）、intro.html（无脚本）、settings.json 一并移除——git 历史可找回。
- 平台资产保留：23 份 references → `skills/plugin-forge/references/neko/`；沙箱 skill → `skills/neko-plugin-sandbox/`；刷新脚本 → `scripts/`。
- 退役依据：court 的核心机制（门下省否决 + 审计留痕）已由 plugin-forge-contract 门禁 + 宪法承接，无功能损失。

## 例行安全审计（脚本化，2026-11-14 起）

- 规则来源：`skills/plugin-forge/references/security-checklist.md`——四项检查（SEC-1 路径范围 / SEC-2 明文密钥 / SEC-3 任意执行 / SEC-4 静默下载），每项 0–25 分；SEC-2 任一真实命中一票否决；总分 ≥90 放行、50–89 修完再放、其余阻断。
- 命令：`python skills/plugin-forge/scripts/security_audit.py <repo> [--allow 前缀,...] [--include-docs]`。`--allow` 只用于"已逐行复核且用途已声明"的文件，每条豁免在本节记依据。

本仓库首跑（2026-11-14，Python 3.15）：

| 跑法 | 范围 | 发现 | 得分 | 结论 |
|---|---|---|---|---|
| 分诊跑 | 代码/配置 14 个文件，无豁免 | SEC-3 4 处、SEC-4 6 处 | 70 | 修完再放 → 逐条分流（见下） |
| 复跑 | 同范围，豁免下表 2 项（余 12 文件） | 0 处 | 100 | 放行（exit 0） |
| 文档扫 | 加 --include-docs 共 62 文件 | SEC-3 6 处、SEC-4 21 处 | 60 | 均为提及性文字，无行为 |

- 分诊跑 10 处发现全部落在两个文件：`skills/plugin-forge/scripts/security_audit.py`（正则定义与自述句——扫描器定义，非行为）；`skills/neko-plugin-sandbox/scripts/sandbox.py`（127.0.0.1 探活、pip 装依赖、git fetch——2026-11-11 已逐行复核，声明用途见上文与残留风险节）。即两条豁免的依据。SEC-1、SEC-2 零发现，全仓库无明文密钥与越界写入。
- 文档扫 27 处命中集中在审计与调研文档自身（security-checklist.md 8 处、neko 调研笔记 15 处、本文件与沙箱 SKILL.md 各 1 处、其余 2 处），是规则描述与调研记录，不是可执行行为；SEC-4 的"已声明"判定以人工对照本文件为准，不靠脚本给满分。
- 复扫触发：仓库脚本变更 ≥5 个文件、或新增外部内容入库时重跑，结果追加进本节。

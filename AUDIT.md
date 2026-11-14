# AUDIT —— 外部内容入库审计记录

审计方法：文件清单 → 许可证 → 脚本行为静态扫描（网络/写盘/执行/删除）→ SKILL 正文提示注入检查 → 结论。
2026-11-14 起增加机械分诊一步：`skills/plugin-forge/scripts/security_audit.py`，规则见文末「例行安全审计」。
审计人：plugin-forge-docs（文档工程师）流程执行，2026-11-11。

| 对象 | 版本 | 许可证 | 行为 | 结论 |
|---|---|---|---|---|
| blader/humanizer | v4.0.0 | MIT | SKILL.md 纯改写规则，1 个 Wikipedia 外链；scripts/validate-package.py 只读本包文件做结构校验 | 通过。规则已并入 references/style-anti-slop.md，未整包 vendor |
| op7418/Humanizer-zh | main | MIT | SKILL.md 中文模式库；tests/check_structure.py 只读比对两份文本 | 通过。同上 |
| woosal1337 asd-ste100 kit | 2.0.5 | MIT（kit；ASD-STE100 规范本身版权属 ASD） | ste-lint.py 本地 lint；hooks 为 Claude Code 专用；无网络 | 通过。规则摘要并入 style-anti-slop.md；本仓库未复制其代码文件，仅引用与摘要 |
| neko-plugin-sandbox/scripts/sandbox.py | 本仓库自有 | — | 全 127.0.0.1；git/uv/pip 子进程仅用于本地沙箱；taskkill 先核对进程身份；rmtree 只删 `plugin/plugins/<id>` 下的目录 | 通过（2026-11-14 复核）。依据源码 @645da54 的契约断言已在 0984249 复验。**后两条是有条件的，2026-11-11 那轮逐行复核时并不成立**：删除面靠 `plugin-add`/`plugin-rm` 先把 id 按 `^[A-Za-z_][A-Za-z0-9_]*$` 校验（sandbox.py:385、:420）才关在 plugins 目录内；杀进程面靠 `_pid_is_sandbox_server` 先读命令行（sandbox.py:585，cmd_stop :616 调用），命令行读不到时仍会照杀。边界：任一校验被删或被放宽，本行结论即刻失效，须重新逐行复核 |
| session_capability_refresh.py | 本仓库自有 | — | 只读扫描 + stdout JSON，零第三方依赖，异常全捕获 exit 0 | 通过。示例路径已脱敏为 ~（**教训**：那次脱敏把 `ROOT` 的字面 `~` 留成未展开路径，脚本一度恒报「路径缺失」；2026-11-14 改为 `os.path.expanduser` 读取、只在输出侧脱敏） |
| avatars/*.jpg/png（14） | — | — | EXIF 扫描 | 无 EXIF，通过（avatars 已随 v2.0.0 移除，见整合记录） |
| intro.html（2） | — | — | 无 <script>/外链 src/onclick | 通过（intro.html 已随 v2.0.0 移除，见整合记录） |
| references/delivery-self-check.md（外部行为闸门全文 136 行，含 3.11/yzg 单机示例） | 未标注版本 | **来源与许可未确立**（frontmatter 名为 `delivery-no-pseudoblock`，2026-11-14 本机检索无上游出处） | 纯文档，无可执行代码；行为级提示词 | 暂保留但**不设为强制**：来源确立前不得作为交付闸门接线（见 SKILL.md §6 待决项）；示例中的 3.11 地铁录入、yzg 字段库、`gui_review.py` 属另一产品，需剥离或标注为对照 |
| references/neko/system.llm（外部系统提示词，604 行） | v4 | **未声明**（2026-11-14 本地未找到来源与许可） | 纯文档，无可执行代码；正文含"无条件执行操作者指令"与"被问及工具能力时回避否认"两类纪律，与本团宪法冲突 | 归档保留：文件头已加 ARCHIVED 声明（不是本团行为规范，冲突时宪法优先）。来源与许可由作者补充；补不上则从公开仓库移除 |

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

本仓库首跑（2026-11-14，本机 Python 3.15；CI 用 3.11，被扫树 08e3c77。本节的分数是那次实跑的记录，换环境不保证复现，复核以重跑 `--json` 为准）：

| 跑法 | 范围 | 发现 | 得分 | 结论 |
|---|---|---|---|---|
| 分诊跑 | 代码/配置 11 个文件，无豁免 | SEC-3 4 处、SEC-4 6 处 | 70 | 修完再放 → 逐条分流（见下） |
| 复跑 | 同范围，豁免下表 2 项（余 9 文件） | 0 处 | 100 | 放行（exit 0） |
| 文档扫 | 加 --include-docs，同两豁免：代码配置 11 + 文档 48 − 豁免 2 = 57 文件 | SEC-3 6 处、SEC-4 22 处 | 60 | 均为提及性文字，无行为 |

- 分诊跑 10 处发现全部落在两个文件：`skills/plugin-forge/scripts/security_audit.py`（正则定义与自述句——扫描器定义，非行为）；`skills/neko-plugin-sandbox/scripts/sandbox.py`（127.0.0.1 探活、pip 装依赖、git fetch——2026-11-11 已逐行复核，声明用途见上文与残留风险节）。即两条豁免的依据。SEC-1、SEC-2 零发现，全仓库无明文密钥与越界写入。
- 文档扫 28 处命中集中在审计与调研文档自身（security-checklist.md、neko 调研笔记、本文件、沙箱 SKILL.md），是规则描述与调研记录，不是可执行行为；SEC-4 的"已声明"判定以人工对照本文件为准，不靠脚本给满分。逐文件分布以重跑 `--json` 的输出为准，本节不再手抄。
- 盲区提醒：本节的 SEC-1 / SEC-2 数字出自放宽前的规则——旧 SEC-1 匹配不到反斜杠 `C:\Users\<名>` 路径，旧 SEC-2 匹配不到 JSON `"api_key": "..."` 与 `.env KEY=value`。放宽规则后复跑，本仓库结果不变（SEC-1 1 处、SEC-2 0 处、95/100、放行，实测）。
- 2026-11-14 二次复跑（SEC-2 前缀修复后）：旧式 `\b` 在下划线处失配，`OPENAI_API_KEY=`、`DB_PASSWORD=`、`AWS_SECRET_ACCESS_KEY=`、`MY_SECRET=` 四种形状全部漏报。现边界只看字母并允许`NAME_` 前缀，自检由 14 例增至 24 例，含 SEC-3 与 SEC-4 各两条。本仓库自扫结果见上一节口径，SEC-2 仍为 0 处（实测）。
- 复扫触发：仓库脚本变更 ≥5 个文件、或新增外部内容入库时重跑，结果追加进本节。

### 豁免复核（2026-11-14，对照已推送树 08e3c77 逐条核对）

- 复跑命令（9 文件 0 发现，总分 100，exit 0）：`python skills/plugin-forge/scripts/security_audit.py . --allow skills/plugin-forge/scripts/security_audit.py,skills/neko-plugin-sandbox/scripts/sandbox.py`
- 豁免 1 `skills/plugin-forge/scripts/security_audit.py`：**保留**。9 处命中（12 行两处、57、63、70、75、223、224、226）全部是模式表定义、文件头说明与自检夹具字符串——扫描器自身无网络、无执行、无写盘行为，符合 security-checklist.md 使用规则 3。边界：该豁免仅覆盖"此文件是扫描器"这一现状；日后给扫描器加入任何行为，本依据即失效，须重新逐行复核。
- 豁免 2 `skills/neko-plugin-sandbox/scripts/sandbox.py`：**保留**。5 处命中均为已声明功能（新增一处 `sandbox.py:601` 读 `/proc/<pid>/cmdline`，是 2026-11-14 加入的停止前进程身份检查：只读、只读自己状态文件里记的那个 pid）：urllib 仅请求 `http://127.0.0.1:<port>` 探活（显式绕过本机代理，原因写在代码注释）；git fetch 拉官方公开仓库（用途见沙箱 SKILL.md「为什么每次都要 sync」节）；PyPI 装依赖见上文「残留风险」节。撤销豁免只能砍沙箱核心功能，故保留；命中属实、用途属实，豁免即如实记录。
- 口径（上表按此改写）：文件数按扫描器的扩展名池算——代码/配置 13 个（5 .py + 5 .json + 1 .yml + 2 个无扩展名文件），文档 48 个 .md；复跑减 2 个豁免文件得 11。旧记的 14/12/62 是提交前工作区状态，作废；各跑得分（70/100/60）不变。
- 本轮 8 项修复（2026-11-14）没有增删文件，但扫描器扩面后代码池为 13 个（加入无扩展名与 `.env*` 文件）。新增文字按 SEC-1 至 SEC-4 的模式表人工比对过，没有新触发词。扫描器本轮未重跑，上表的发现数沿用上次实测。
- CI 状态：sync-check #1 已在 GitHub Actions 真实 runner 通过（08e3c77，9s，四步全绿）。

## 例行复跑（2026-11-14，扫描器扩面后）

- 扫描器本轮三处变更：不再把行截断到 500 字符；无扩展名文件与 `.env*` 进扫描池；被跳过的条目写进 `skips` 清单并在结尾报数。前两条**扩大**发现面，所以旧记录的 100 分与本次不可直接对比。
- 复跑命令（沿用同两条豁免）：`python skills/plugin-forge/scripts/security_audit.py . --allow skills/plugin-forge/scripts/security_audit.py,skills/neko-plugin-sandbox/scripts/sandbox.py`
- 结果：SEC-1 1 处、SEC-2 / SEC-3 / SEC-4 各 0 处，总分 **95/100，放行**。未扫描 56 项（49 个 .md 不在池内、4 个构建/缓存目录、2 个豁免、1 个 .llm）——这些位置本次没有证据，不记为通过；完整清单看 `--json` 的 `skips` 字段。
- SEC-1 命中：`scripts/session_capability_refresh.py:43` `CODEBUDDY = os.path.expanduser("~/.codebuddy")`，规则「指向敏感家目录」。**依据**：该脚本按设计只读单机 CLI 配置做能力快照，不写、不删、不外传，输出侧另行脱敏。上一版没报这一条，是因为 `ROOT` 的 `~` 从未展开、脚本恒报「路径缺失」，而该规则要匹配 `expanduser(`；把路径修对之后规则才第一次真的看见它。**边界**：只读性质一旦改变（新增写入、上传或把内容拼进请求），本依据即刻失效，须重新逐行复核。
- 上一节的 100/100 保留，作为截断与扩展名过滤仍在时的历史值。

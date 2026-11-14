# 安全检查清单与评分（security-checklist）

适用场景：① 外部内容入库审计（Workflow G 第 0 步，结论记 AUDIT.md）；② 交付前安全门禁（plugin-forge-security）；③ 本仓库定期复扫（AUDIT.md）。

工具命令（`${FORGE_HOME}` = skill 安装目录，定义见 SKILL.md §5）：

```
python ${FORGE_HOME}/scripts/security_audit.py <repo> [--allow 前缀1,前缀2] [--include-docs] [--json] [--quiet]
```

默认只扫代码与配置文件；`--include-docs` 追加扫描 md/html/txt（查个人路径与密钥残留）。
`--allow` 是"已逐行复核且已声明"的豁免，前缀匹配；**每条豁免必须把依据写进 AUDIT.md**，没有依据的豁免按发现处理。

## 四项检查

### SEC-1 路径范围

要求：写/删只落在项目目录内，或 profile 声明的数据目录；不留个人绝对路径。
机器查：写/删调用行里的硬编码绝对路径；`expanduser` 打到 `.ssh` 等敏感目录；`C:\Users\<名>`、`/home/<名>` 残留；经 `../` 越界的写入。
修法：改项目根相对路径或宿主声明的数据目录；提交前把个人路径脱敏为 `~`。

### SEC-2 明文密钥

要求：仓库内不得出现任何可用凭据（token、API key、私钥、password 形态赋值）。
机器查：GitHub / OpenAI / AWS / Slack token 形态；`PRIVATE KEY` 块；password/secret 类键的明文赋值（占位值已过滤）。
修法：改环境变量或宿主安全存储（对照 profile §6）；**已提交的凭据立即轮换**，并清理历史。
判定：**任一真实命中 = 一票否决，直接阻断**，不参与总分。

### SEC-3 任意执行

要求：外部输入不得到达动态执行；子进程用固定 argv 列表，不开 shell。
机器查：`eval` / `exec` / `new Function`；`shell=True`、`os.system`、`shell -c` 执行串；`curl … | sh`；`Invoke-Expression`；`pickle.load` 与 unsafe `yaml.load`。
修法：白名单 argv；参数化 API；safe loader；删除管道执行。

### SEC-4 静默下载

要求：每处网络取回与包安装都要向用户声明用途（README / profile / 安装提示）；无声明的自动外联即"静默下载"。
机器查：`urlopen` / requests / fetch / curl / wget；`pip|npm|uv install`；`git clone|pull`；download 字样。
判定：每处须对应一条"声明"（在 AUDIT.md 记章节出处）；对不上的按未声明处理，修或阻断。
注意：机器只能列点位，**声明与否要人工核对**——这一项不允许纯靠脚本给满分。

## 评分与结论

| 项 | 0 处 | 1–3 处 | 4–10 处 | >10 处 |
|---|---|---|---|---|
| SEC-1 / SEC-3 / SEC-4 | 25 | 20 | 10 | 0 |
| SEC-2 | 25 | — | — | 0（任一真实命中直接阻断） |

总分 = 四项之和（满分 100）。豁免（--allow）文件不计发现。

- **阻断**（退出码 2）：SEC-2 有真实命中，或总分 < 50。
- **修完再放**（退出码 1）：总分 50–89。每条发现给 位置 + 判定（真问题/误报/已声明）+ 修法。
- **放行**（退出码 0）：总分 ≥ 90。

## 使用规则

1. 评分是分流器，不替代逐行复核：分数高仍要抽查 SEC-2（拼接藏匿的密钥扫不到）。
2. 误报要分类记录，不悄悄丢弃；反复误报的模式回写本清单修规则。
3. 扫描器本身（security_audit.py）的模式定义会命中它自己的文档串——豁免时依据写"扫描器定义，非行为"。
4. 复扫节奏：上游或本仓库脚本变更 ≥5 个文件时重跑；结果追加进 AUDIT.md。
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plugin-forge · 安全审计扫描器（零第三方依赖，Python 3.8+）

用法
  python security_audit.py <repo路径> [--allow 相对路径前缀,...] [--include-docs]
                           [--json] [--quiet]

四项检查（细则与评分规则见 references/security-checklist.md）
  SEC-1 路径范围：写/删操作指向项目外、敏感家目录，或残留个人绝对路径。
  SEC-2 明文密钥：token 形态、私钥块、password 类赋值。任一命中 = 直接阻断（一票否决）。
  SEC-3 任意执行：eval/exec、shell=True、os.system、shell -c 拼接、curl|sh、不安全反序列化。
  SEC-4 静默下载：网络取回与包安装点位；每处须对应"已声明用途"，未声明即静默。

默认只扫代码与配置文件（文档不参与评分）；--include-docs 把 md/html/txt 也纳入
（SEC-1/SEC-2 文档残留检查）。--allow 用于"已复核且已声明"的豁免文件，前缀匹配，
每条豁免必须写进 AUDIT.md。这是分诊器，不是裁判：命中仍要逐条人工判定。

退出码：0 放行（≥90）；1 修完再放（50–89）；2 阻断（SEC-2 有发现或 <50）。
"""
import sys, os, re, json, argparse

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".pytest_cache", ".mypy_cache", ".tox"}
CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
             ".rs", ".go", ".java", ".kt", ".kts", ".scala", ".swift", ".c", ".h",
             ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".rb", ".php", ".lua", ".pl",
             ".ex", ".exs", ".erl", ".dart", ".sh", ".bash", ".zsh", ".fish",
             ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".ipynb"}
CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties"}
DOC_EXTS = {".md", ".markdown", ".html", ".txt", ".rst"}
MAX_BYTES = 2 * 1024 * 1024
CHECKS = ("SEC-1", "SEC-2", "SEC-3", "SEC-4")

WRITE_RE = r"(?:open|rmtree|move|remove|unlink|rename|replace|write_text|write_bytes|mkdir|rmdir)\s*[({]"
ABS = r"['\"](?:[A-Za-z]:[\\\\/]|/(?:etc|usr|var|home|root|proc|Users)/)"

SEC1 = [
    (WRITE_RE + r"[^#]*" + ABS, "写/删目标含硬编码绝对路径"),
    (r"expanduser\s*\(\s*['\"]~/(?:\.ssh|\.aws|\.gnupg|\.azure|\.config|\.codex|\.zcode|\.codebuddy)", "指向敏感家目录"),
    (r"[A-Za-z]:[/\\\\]Users[/\\\\](?!(?:Public|<|\{|\.)[A-Za-z0-9_.<>{} -]*)['\"]", "Windows 用户名路径残留"),
    (r"(?:/Users/|/home/)(?!(?:user|Users|home|example|name|<|\{)[\"'/])([A-Za-z0-9_.-]{3,})/", "个人 home 路径残留"),
    (WRITE_RE + r"[^#]*\.\.[/\\\\]", "写/删经 ../ 越出当前目录"),
]
GH = r"\bgh[pousr]_[A-Za-z0-9]{16,}\b|\bgithub_pat_[A-Za-z0-9_]{24,}\b"
SEC2 = [
    (GH, "GitHub token"),
    (r"\bsk-[A-Za-z0-9_\-]{20,}\b", "sk- 形态 API key"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----", "私钥块"),
    (r"(?i)\b(?:password|passwd|secret|api_?key|access_?token|auth_?token|client_?secret|private_?token)\b\s*[:=]\s*['\"]([^'\"]{12,})['\"]", "password/secret 明文赋值"),
]
IGNORE_VAL = re.compile(r"(?i)^(?:your[_-]|(?:changeme|placeholder|example|dummy|sample|test|fake|redacted|masked|todo|noreply|none|null|empty)(?![A-Za-z])|x{3,}|\*{3,}|<|\$\{|\{|\[)")
SEC3 = [
    (r"(?<![\w.])(?:eval|exec)\s*\(", "eval/exec 动态执行"),
    (r"shell\s*=\s*True", "subprocess shell=True"),
    (r"os\.system\s*\(", "os.system"),
    (r"execSync\s*\(|child_process\.exec\(", "Node child_process.exec"),
    (r"new\s+Function\s*\(", "new Function 动态执行"),
    (r"['\"](?:bash|sh|zsh|cmd|powershell)(?:\.exe)?\s+[-/]c[\s'\\]", "shell -c 执行串"),
    (r"(?:curl|wget)[^'\"]*\|\s*(?:ba)?sh", "管道给 shell"),
    (r"Invoke-Expression|\biex\s", "PowerShell 动态执行"),
    (r"pickle\.loads?\s*\(", "pickle 反序列化"),
    (r"yaml\.load\s*\((?:(?!Loader|safe).)*\)", "unsafe yaml.load"),
]
SEC4 = [
    (r"urlopen\s*\(|urlretrieve\s*\(|urllib\.request", "urllib 网络取回"),
    (r"requests\.(?:get|post|put|patch)\s*\(|httpx\.(?:get|post|Client|AsyncClient)|aiohttp\.", "HTTP 客户端"),
    (r"\bfetch\s*\(|XMLHttpRequest|Invoke-WebRequest|Invoke-RestMethod", "前端/PS 网络取回"),
    (r"\b(?:curl|wget)\s+\S", "命令行下载"),
    (r"(?i)\b(?:pip|uv)\s+(?:pip\s+)?(?:install|add)\b", "包安装（外联 PyPI 等）"),
    (r"(?i)\b(?:npm|yarn|pnpm)\s+(?:i|install)\b|\bcargo\s+install\b|\bgo\s+get\b", "包安装（其他源）"),
    (r"git\s+(?:clone|pull|fetch)\b", "git 外联"),
    (r"(?i)download", "download 字样（核对是否声明）"),
]
TABLES = [(CHECKS[0], SEC1), (CHECKS[1], SEC2), (CHECKS[2], SEC3), (CHECKS[3], SEC4)]


def _utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def iter_files(root, include_docs, allow, skips=None):
    """产出 (rel, full)。skips 收集被排除的条目和原因：审计报告要能说明自己没看什么，
    而不是让"0 发现"读起来像全覆盖。
    """
    if skips is None:
        skips = []
    allow = [a.replace("\\", "/") for a in allow]
    allow = [(a[2:] if a.startswith("./") else a).rstrip("/") for a in allow]
    for dirpath, dirnames, filenames in os.walk(root):
        kept = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS:
                rel = os.path.relpath(os.path.join(dirpath, d), root).replace("\\", "/")
                skips.append(rel + "/*（构建/缓存目录，整目录跳过）")
            else:
                kept.append(d)
        dirnames[:] = kept
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if any(rel == a or rel.startswith(a + "/") for a in allow):
                skips.append(rel + "（--allow 豁免）")
                continue
            ext = os.path.splitext(fn)[1].lower()
            pool = CODE_EXTS | CONFIG_EXTS | (DOC_EXTS if include_docs else set())
            # 无扩展名文件（Dockerfile / Makefile / 无后缀脚本）和 .env* 也进池：明文密钥最常
            # 落在这两类里，旧版只按扩展名过滤，等于对它们失明。
            low = fn.lower()
            if ext and ext not in pool and not low.startswith(".env") and not low.endswith(".env"):
                skips.append(rel + "（扩展名 " + ext + " 不在扫描池）")
                continue
            try:
                if os.path.getsize(full) > MAX_BYTES:
                    skips.append(rel + "（超过 2 MiB，未读）")
                    continue
                with open(full, "rb") as f:
                    head = f.read(4096)
                if b"\x00" in head:
                    skips.append(rel + "（含 NUL，按二进制跳过）")
                    continue
            except OSError as e:
                skips.append(rel + "（stat 或 open 失败：" + type(e).__name__ + "）")
                continue
            yield rel, full


def scan(root, include_docs, allow):
    findings = {c: [] for c in CHECKS}
    seen = set()
    scanned = 0
    skips = []
    for rel, full in iter_files(root, include_docs, allow, skips):
        scanned += 1
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError as e:
            skips.append(rel + "（读取失败：" + type(e).__name__ + "）")
            continue
        for i, line in enumerate(lines, 1):
            # 不再把行截断到 500 字符：压缩过的 JS 里，密钥与 eval 往往就在行尾。
            for cid, table in TABLES:
                for pat, note in table:
                    for mo in re.finditer(pat, line):
                        if cid == "SEC-2" and IGNORE_VAL.match(mo.group(1) if mo.groups() else mo.group(0)):
                            continue
                        key = (rel, i, cid, note)
                        if key in seen:
                            continue
                        seen.add(key)
                        findings[cid].append({"file": rel, "line": i, "note": note,
                                              "snippet": line.strip()[:140]})
    return scanned, findings, skips


def score(findings, scanned):
    s = {}
    s["SEC-2"] = 25 if len(findings["SEC-2"]) == 0 else (10 if len(findings["SEC-2"]) <= 2 else 0)
    for c in ("SEC-1", "SEC-3", "SEC-4"):
        n = len(findings[c])
        s[c] = 25 if n == 0 else 20 if n <= 3 else 10 if n <= 10 else 0
    total = sum(s.values())
    if findings["SEC-2"] or total < 50:
        verdict, code = "阻断", 2
    elif total < 90:
        verdict, code = "修完再放", 1
    else:
        verdict, code = "放行", 0
    return s, total, verdict, code


def main():
    _utf8()
    ap = argparse.ArgumentParser(description="四项安全检查，输出 0–100 分与门禁结论")
    ap.add_argument("repo", nargs="?", default=".", help="目标仓库路径")
    ap.add_argument("--allow", default="", help="豁免的相对路径前缀，逗号分隔（依据须记入 AUDIT.md）")
    ap.add_argument("--include-docs", action="store_true", help="把 md/html/txt 也纳入扫描")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = ap.parse_args()
    root = os.path.abspath(args.repo)
    if not os.path.isdir(root):
        print("用法错误: 不是目录:", root)
        return 2
    allow = [a for a in args.allow.split(",") if a.strip()]
    scanned, findings, skips = scan(root, args.include_docs, allow)
    s, total, verdict, code = score(findings, scanned)
    if args.json:
        print(json.dumps({"repo": root.replace("\\", "/"), "scanned_files": scanned,
                          "skipped_files": len(skips), "skips": skips,
                          "allow": allow, "counts": {c: len(findings[c]) for c in CHECKS},
                          "findings": findings, "score": s, "total": total,
                          "verdict": verdict}, ensure_ascii=False, indent=1))
        return code
    print("仓库: %s | 扫描 %d 个文件 | 豁免 %s" % (root.replace("\\", "/"), scanned,
                                                  ",".join(allow) or "无"))
    if skips:
        from collections import Counter
        kinds = Counter(x.rsplit("（", 1)[-1].rstrip("）") for x in skips)
        print("未扫描 %d 项：%s" % (len(skips),
              "；".join("%s %d" % (k, v) for k, v in kinds.most_common())))
        print("   完整清单用 --json 查看（skips 字段）——这些位置本次没有证据，别当成已通过。")
    for c in CHECKS:
        n = len(findings[c])
        print("== %s：%d 处（%d 分）" % (c, n, s[c]))
        if args.quiet:
            continue
        for f in findings[c][:20]:
            print("   %s:%d [%s] %s" % (f["file"], f["line"], f["note"], f["snippet"]))
        if n > 20:
            print("   ...其余 %d 处用 --json 查看" % (n - 20))
    print("得分: SEC1=%d SEC2=%d SEC3=%d SEC4=%d 总分=%d/100" %
          (s["SEC-1"], s["SEC-2"], s["SEC-3"], s["SEC-4"], total))
    print("结论: %s（SEC-2 有发现或总分<50 阻断；50-89 修完再放；>=90 放行）" % verdict)
    print("提醒: 这是分诊器。命中要逐条人工判定；豁免文件须在 AUDIT.md 记依据。")
    return code


if __name__ == "__main__":
    sys.exit(main())
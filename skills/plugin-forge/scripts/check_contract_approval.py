#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plugin-forge · 契约门禁校验（零第三方依赖，Python 3.8+）

作用：把「契约先行」从口头铁律变成机器门禁。契约审议师准奏后，把裁决落盘为
项目根 contract-approval.json（格式见 references/contract-approval.schema.json）；
任何代码文件写入前必须先过本脚本，没有准奏、准奏过期、或路径不在 scope 内，一律拒绝。

用法
  python check_contract_approval.py --approval <项目根>/contract-approval.json <路径...>
  python check_contract_approval.py --approval contract-approval.json --staged   # git 已暂存
  python check_contract_approval.py --approval contract-approval.json --changed  # git 未暂存改动
  python check_contract_approval.py --self-test                                   # 内置自检

规则
  - 只拦「代码类」文件（CODE_EXTS 扩展名 + MANIFEST_NAMES 清单文件名）；文档、数据改动不拦。
  - 放行条件（全部满足）：schema == plugin-forge/contract-approval@1；decision == "approved"；
    issued_by == "plugin-forge-contract"；未到 expires_at；目标路径命中 scope 的某个 glob。
  - glob 语法：* 不跨 /；** 跨目录（src/** 覆盖 src 下任意深度）；不含 / 的模式按文件名匹配。
  - 路径在项目根之外 → 拒绝（路径范围铁律）。

退出码
  0 = 全部放行；1 = 存在拒绝（含准奏缺失/过期/decision=rejected）；2 = 用法错误。
"""
import sys, os, re, json, argparse, datetime, tempfile

SCHEMA_ID = "plugin-forge/contract-approval@1"
ISSUER = "plugin-forge-contract"
CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
             ".rs", ".go", ".java", ".kt", ".kts", ".scala", ".swift", ".c", ".h",
             ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".rb", ".php", ".lua", ".pl",
             ".ex", ".exs", ".erl", ".dart", ".sh", ".bash", ".zsh", ".fish",
             ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".ipynb"}
MANIFEST_NAMES = {"plugin.toml", "plugin.json", "manifest.json", "package.json",
                  "cargo.toml", "go.mod", "pom.xml", "build.gradle"}


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def is_protected(path):
    name = os.path.basename(path.replace("\\", "/")).lower()
    ext = os.path.splitext(name)[1]
    return ext in CODE_EXTS or name in MANIFEST_NAMES


def compile_glob(pat):
    """极简 gitignore 风格 glob → 锚定正则。src/** = 跨段；*=段内；不含 / 时另按文件名匹配。"""
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 2] == "**":
                if pat[i:i + 3] == "**/":
                    out.append("(?:.*/)?"); i += 3; continue
                out.append(".*"); i += 2; continue
            out.append("[^/]*"); i += 1; continue
        if c == "?":
            out.append("[^/]"); i += 1; continue
        if c == "[":
            j = pat.find("]", i)
            if j < 0:
                out.append(re.escape(c)); i += 1; continue
            out.append(pat[i:j + 1].replace("[!", "[^")); i = j + 1; continue
        out.append(re.escape(c)); i += 1
    rx = re.compile("^(?:" + "".join(out) + r")\Z")
    bare = re.compile("^" + re.escape(os.path.basename(pat)) + r"\Z") if "/" not in pat else None
    return (rx, bare)


def match_scope(scope, rel):
    rel = rel.replace("\\", "/")
    for pat in scope:
        rx, bare = compile_glob(pat)
        if rx.match(rel) or (bare is not None and bare.match(os.path.basename(rel))):
            return True
    return False


def parse_ts(s):
    s = str(s).strip()
    if not s:
        return None
    if s[-1] in "Zz":
        s = s[:-1] + "+00:00"
    dt = None
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # 裸时间按本地时区
    return dt


def load_approval(apath):
    """返回 (data, 致命错误文本)。缺文件、坏 JSON、缺必备字段都算「无有效准奏」。"""
    if not os.path.isfile(apath):
        return None, "准奏文件不存在：%s（契约未落盘 = 没有准奏，不许写码）" % apath
    try:
        with open(apath, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        return None, "准奏文件不是合法 JSON：%s（%s）" % (apath, e)
    if not isinstance(data, dict):
        return None, "准奏文件顶层必须是 JSON 对象"
    problems = []
    if data.get("schema") != SCHEMA_ID:
        problems.append("schema 必须为 %r" % SCHEMA_ID)
    if "decision" not in data:
        problems.append("缺 decision 字段")
    if not isinstance(data.get("scope"), list) or not data.get("scope"):
        problems.append("scope 必须是非空字符串数组")
    if not data.get("issued_at"):
        problems.append("缺 issued_at")
    for k in ("task", "platform"):
        if not data.get(k):
            problems.append("缺 %s（任务与平台必须写明，防张冠李戴）" % k)
    if problems:
        return None, "准奏文件不符合 %s：%s" % (SCHEMA_ID, "；".join(problems))
    return data, None


def check_targets(data, root, targets):
    """返回 [(rel, allowed, reason)]。data=None 表示无有效准奏：代码全拒，非代码不拦。"""
    now = datetime.datetime.now().astimezone()
    root = os.path.abspath(root)
    results = []
    for t in targets:
        p = os.path.abspath(t)
        rel = os.path.relpath(p, root).replace("\\", "/")
        if not is_protected(p):
            results.append((rel, True, "非代码文件，不入门禁"))
            continue
        if data is None:
            results.append((rel, False, "无有效准奏记录"))
            continue
        if rel == ".." or rel.startswith("../"):
            results.append((rel, False, "路径在项目根之外"))
            continue
        if data.get("decision") != "approved":
            results.append((rel, False, "decision=%r，只有 approved 放行（封驳不许写码）"
                            % data.get("decision")))
            continue
        if data.get("issued_by") != ISSUER:
            results.append((rel, False, "issued_by=%r 不是 %s（门禁记录须出自契约审议师）"
                            % (data.get("issued_by"), ISSUER)))
            continue
        exp = data.get("expires_at")
        if exp:
            dt = parse_ts(exp)
            if dt is None:
                results.append((rel, False, "expires_at 无法解析：%r" % exp))
                continue
            if now > dt:
                results.append((rel, False, "准奏已过期（expires_at=%s），重新送审" % exp))
                continue
        if not match_scope(data["scope"], rel):
            results.append((rel, False, "不在 scope 内（scope=%s）" % ",".join(data["scope"])))
            continue
        results.append((rel, True, "准奏有效，scope 覆盖"))
    return results


def _self_test():
    ok = True
    root = tempfile.mkdtemp(prefix="forge-gate-")

    def base(**kw):
        d = {"schema": SCHEMA_ID, "task": "t", "platform": "neko@0984249",
             "decision": "approved", "scope": ["src/**", "plugin.toml"],
             "issued_by": ISSUER, "issued_at": "2026-01-01T00:00:00+08:00"}
        d.update(kw)
        return d

    def J(*parts):
        return os.path.join(root, *parts)

    cases = [
        (base(), [J("src", "a.py"), J("src", "pkg", "b.py"), J("plugin.toml")], True),
        (base(), [J("other", "c.py")], False),
        (base(), [J("..", "outside.py")], False),
        (base(decision="rejected"), [J("src", "a.py")], False),
        (base(expires_at="2020-01-01"), [J("src", "a.py")], False),
        (base(issued_by="plugin-forge-dev"), [J("src", "a.py")], False),
        (base(), [J("docs", "readme.md")], True),
    ]
    for data, targets, want in cases:
        for rel, allowed, reason in check_targets(data, root, targets):
            if allowed != want:
                ok = False
                print("SELF-TEST FAIL: %s allowed=%s want=%s (%s)" % (rel, allowed, want, reason))
    for rel, allowed, reason in check_targets(None, root, [J("src", "a.py"), J("x.md")]):
        want = not is_protected(rel)
        if allowed != want:
            ok = False
            print("SELF-TEST FAIL(无准奏): %s allowed=%s want=%s" % (rel, allowed, want))
    apath = J("contract-approval.json")
    with open(apath, "w", encoding="utf-8") as f:
        json.dump(base(scope=["conftest.py", "src/**"]), f)
    data, err = load_approval(apath)
    if err:
        ok = False
        print("SELF-TEST FAIL: load:", err)
    else:
        rs = dict((r, a) for r, a, _ in check_targets(data, root,
                  [J("conftest.py"), J("src", "x", "conftest.py")]))
        if not (rs.get("conftest.py") and rs.get("src/x/conftest.py")):
            ok = False
            print("SELF-TEST FAIL: 裸文件名 scope 未生效", rs)
    bad = J("bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        json.dump({"schema": "other/1"}, f)
    d2, err2 = load_approval(bad)
    if d2 is not None or not err2:
        ok = False
        print("SELF-TEST FAIL: schema 不符应拒绝")
    d3, err3 = load_approval(J("nope.json"))
    if d3 is not None or not err3:
        ok = False
        print("SELF-TEST FAIL: 缺文件应报无准奏")
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="契约准奏门禁：无准奏不写码，scope 外不写码")
    ap.add_argument("targets", nargs="*", help="将要写入的文件路径（项目根相对或绝对）")
    ap.add_argument("--approval", default="contract-approval.json",
                    help="准奏记录路径（默认当前目录 contract-approval.json）")
    ap.add_argument("--staged", action="store_true", help="检查 git 已暂存(ACMR)文件")
    ap.add_argument("--changed", action="store_true", help="检查 git 工作区未暂存改动")
    ap.add_argument("--self-test", action="store_true", help="内置自检（CI 用）")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    targets = list(args.targets)
    if args.staged or args.changed:
        import subprocess
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if args.staged \
            else ["git", "diff", "--name-only"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
            targets += [l for l in out.splitlines() if l.strip()]
        except Exception as e:
            print("用法错误: git 不可用:", e)
            return 2
    if not targets:
        print("用法错误: 没有待检查文件（给出路径或 --staged/--changed）")
        return 2
    approval = os.path.abspath(args.approval)
    root = os.path.dirname(approval)
    data, fatal = load_approval(approval)
    if fatal:
        print("REFUSE(全局):", fatal)
    results = check_targets(data, root, targets)
    refused = 0
    for rel, allowed, reason in results:
        print("%s %s: %s" % ("ALLOW " if allowed else "REFUSE", rel, reason))
        if not allowed:
            refused += 1
    if refused:
        print("结论: 门禁拒绝 %d 项。先补齐契约审议（或重新送审），再动笔。" % refused)
        return 1
    print("结论: 门禁放行（%d 项）。" % len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
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
    issued_by == "plugin-forge-contract"（自证字符串，只验记录不验身份）；未到 expires_at（缺省视为长期有效）；目标路径命中 scope 的某个 glob。
  - glob 语法：* 不跨 /；** 跨目录（src/** 覆盖 src 下任意深度）；不含 / 的模式按文件名匹配。
  - 路径在项目根之外 → 拒绝（路径范围铁律）。
  - 记录里填了 plan_sha256 时，plan_file 的内容必须还能算出同一个摘要；对不上就是方案被改过，旧准奏失效。未填 plan_sha256 的旧记录不受影响。

退出码
  0 = 全部放行；1 = 存在拒绝（含准奏缺失/过期/decision=rejected）；2 = 用法错误。
"""
import sys, os, re, json, argparse, datetime, tempfile, hashlib

SCHEMA_ID = "plugin-forge/contract-approval@1"
ISSUER = "plugin-forge-contract"
CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
             ".rs", ".go", ".java", ".kt", ".kts", ".scala", ".swift", ".c", ".h",
             ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".rb", ".php", ".lua", ".pl",
             ".ex", ".exs", ".erl", ".dart", ".sh", ".bash", ".zsh", ".fish",
             ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".ipynb"}
MANIFEST_NAMES = {"plugin.toml", "plugin.json", "manifest.json", "package.json",
                  "cargo.toml", "go.mod", "pom.xml", "build.gradle",
                  "pyproject.toml", "requirements.txt"}


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


def _plan_problem(data, root):
    """schema 承诺"方案改动后旧准奏失效"。这里真的去比 plan_sha256。

    返回 None 表示通过；返回文本表示对所有目标一致拒绝的原因。
    未填 plan_sha256 的旧记录直接放过，避免追溯性地把已有准奏打回。
    """
    want = data.get("plan_sha256")
    if not want:
        return None
    name = data.get("plan_file")
    if not name:
        return "填了 plan_sha256 却没有 plan_file，无法确认方案是否被改过"
    p = os.path.realpath(os.path.join(root, name))
    if p != root and not p.startswith(root + os.sep):
        return "plan_file 指向项目根之外：%s" % name
    try:
        with open(p, "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
    except OSError as e:
        return "读不到方案文件 %s（%s），不能确认方案未改" % (name, e)
    if got.lower() != str(want).strip().lower():
        return ("方案已改动，旧准奏失效（plan_sha256 记录 %s…，实际 %s…），重新送审"
                % (str(want)[:12], got[:12]))
    return None


def check_targets(data, root, targets):
    """返回 [(rel, allowed, reason)]。data=None 表示无有效准奏：代码全拒，非代码不拦。"""
    now = datetime.datetime.now().astimezone()
    root = os.path.realpath(root)
    plan_err = _plan_problem(data, root) if data else None
    results = []
    for t in targets:
        p = os.path.realpath(t)
        try:
            rel = os.path.relpath(p, root).replace("\\", "/")
        except ValueError:
            # 跨盘符没有公共祖先：按根外处理，不能抛异常把整轮判定打掉
            rel = "../" + p.replace("\\", "/")
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
        if plan_err:
            results.append((rel, False, plan_err))
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
    plan_path = J("PLAN.md")
    with open(plan_path, "wb") as f:
        f.write(b"plan v1\n")
    with open(plan_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    plan_cases = [
        (base(plan_file="PLAN.md", plan_sha256=digest), True,  "方案未改应放行"),
        (base(plan_file="PLAN.md", plan_sha256="0" * 64), False, "摘要不符应拒绝"),
        (base(plan_file="gone.md", plan_sha256=digest), False,  "方案文件读不到应拒绝"),
        (base(plan_file="PLAN.md"), True, "旧记录未填 sha 不应追溯拒绝"),
        (base(plan_file="../outside.md", plan_sha256=digest), False, "plan_file 越界应拒绝"),
    ]
    for data, want, note in plan_cases:
        rs = check_targets(data, root, [J("src", "a.py")])
        if rs and rs[0][1] != want:
            ok = False
            print("SELF-TEST FAIL(plan): %s allowed=%s want=%s %s"
                  % (note, rs[0][1], want, rs[0][2]))
    with open(plan_path, "wb") as f:
        f.write(b"plan v2, edited after approval\n")
    rs = check_targets(base(plan_file="PLAN.md", plan_sha256=digest), root, [J("src", "a.py")])
    if rs and rs[0][1]:
        ok = False
        print("SELF-TEST FAIL(plan): 方案被改后旧准奏仍放行")
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="契约准奏门禁：无准奏不写码，scope 外不写码")
    ap.add_argument("targets", nargs="*", help="将要写入的文件路径（项目根相对或绝对）")
    ap.add_argument("--approval", default="contract-approval.json",
                    help="准奏记录路径（默认当前目录 contract-approval.json）")
    ap.add_argument("--staged", action="store_true", help="检查 git 已暂存(ACMR)文件")
    ap.add_argument("--changed", action="store_true", help="检查 git 工作区未暂存改动 + 未跟踪的新文件")
    ap.add_argument("--self-test", action="store_true", help="内置自检（CI 用）")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    targets = list(args.targets)
    approval = os.path.abspath(args.approval)
    root = os.path.dirname(approval)
    if args.staged or args.changed:
        import subprocess
        # -z 分隔：路径含中文或空格时 git 会加引号转义，splitlines 会把它切碎。
        # cwd=root：git 输出是仓库根相对路径，在子目录里跑也不能按当前目录解析。
        def _git(*names):
            r = subprocess.run(["git", *names], capture_output=True, check=True, cwd=root)
            return [n for n in r.stdout.decode("utf-8", "replace").split("\0") if n.strip()]
        try:
            if args.staged:
                targets += [os.path.join(root, n)
                            for n in _git("diff", "--cached", "--name-only", "-z",
                                          "--diff-filter=ACMR")]
            if args.changed:
                targets += [os.path.join(root, n) for n in
                            _git("diff", "--name-only", "-z")
                            + _git("ls-files", "--others", "--exclude-standard", "-z")]
        except Exception as e:
            print("用法错误: git 不可用:", e)
            return 2
    if not targets:
        print("用法错误: 没有待检查文件（给出路径或 --staged/--changed）")
        return 2
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
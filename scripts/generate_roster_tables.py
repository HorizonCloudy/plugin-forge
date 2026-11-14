#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plugin-forge · 名册表生成器（roster.json 为唯一来源）

用途
  从 roster.json 重新生成 README.md、skills/plugin-forge/SKILL.md、
  agents/plugin-forge-lead.md 里的名册表格，并同步各处的人数声明
  （"1 主理人 + N 专家"、"调度 N 位专家"、"N 人编制"、"N 个人设"）。
  表格区域由成对标记包住，标记之间只许本脚本写入，不许手改。

用法
  python scripts/generate_roster_tables.py --check   # 只比对与校验，不改文件（CI 用）
  python scripts/generate_roster_tables.py --write   # 重新生成表格并同步人数声明
  python scripts/generate_roster_tables.py --self-test  # 人数改写的自检

校验
  - roster.json 的 members 与 agents/*.md 一一对应（文件存在、frontmatter
    name/displayName/maxTurns 与 roster 一致）。
  - 标记缺失或表格漂移 → --check 退出码 1；--write 会修复表格与人数。
  - 脚本修不了的问题（标记缺失、roster 与 agents 不一致）→ --check 与 --write
    都退出码 1，绝不静默跳过。

约束
  - 零第三方依赖（Python 3.8+）。只写上面三个被标记的文档，不动其他文件。
"""
import sys, os, re, json, glob, argparse

def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER_PATH = os.path.join(ROOT, "roster.json")

# 目标：(相对路径, 标记 id, 成员子集, 列定义) 列 = (表头, 取值函数)
def _c_id(m): return m["agent_id"]
def _c_role(m): return "主理人" if m["role"] == "lead" else "专家"
def _c_name(m): return m["name_zh"]
def _c_duty(m): return m["duty"]
def _c_when(m): return m["when_to_dispatch"]

TARGETS = [
    ("README.md", "roster:readme", "all",
     [("Agent ID", _c_id), ("角色", _c_role), ("名号", _c_name), ("职责", _c_duty)]),
    ("skills/plugin-forge/SKILL.md", "roster:skill", "all",
     [("Agent ID", _c_id), ("名号", _c_name), ("什么时候派", _c_when)]),
    ("agents/plugin-forge-lead.md", "roster:lead", "experts",
     [("Agent ID", _c_id), ("名号", _c_name), ("职责", _c_duty)]),
]

# 人数声明同步：(文件, 正则, 用哪个数)  group1 = 旧数字位置
COUNT_CLAIMS = [
    (r"1 主理人 \+ (\d+) 专家", "n_experts"),
    (r"调度 (\d+) 位专家", "n_experts"),
    (r"(\d+) 人编制", "n_total"),
    (r"(\d+) 个人设", "n_total"),
]
COUNT_FILES = ["README.md", "skills/plugin-forge/SKILL.md",
               "agents/plugin-forge-lead.md", ".claude-plugin/plugin.json"]

def load_roster():
    with open(ROSTER_PATH, encoding="utf-8-sig") as f:
        data = json.load(f)
    members = data["members"]
    ids = [m["agent_id"] for m in members]
    if len(set(ids)) != len(ids):
        raise ValueError("roster.json 存在重复 agent_id")
    return members

def read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read().replace("\r\n", "\n")

def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)

def render_table(members, subset, columns):
    rows = members if subset == "all" else [m for m in members if m["role"] != "lead"]
    lines = ["| " + " | ".join(h for h, _ in columns) + " |",
             "|" + "|".join(["---"] * len(columns)) + "|"]
    for m in rows:
        lines.append("| " + " | ".join(fn(m) for _, fn in columns) + " |")
    return "\n".join(lines)

def validate_against_agents_dir(members):
    problems = []
    files = {os.path.basename(p): p for p in glob.glob(os.path.join(ROOT, "agents", "*.md"))}
    roster_files = {os.path.basename(m["file"]) for m in members}
    for extra in sorted(set(files) - roster_files):
        problems.append(f"agents/{extra} 不在 roster.json 中")
    for missing in sorted(roster_files - set(files)):
        problems.append(f"roster.json 引用 agents/{missing} 但文件不存在")
    for m in members:
        p = os.path.join(ROOT, m["file"])
        if not os.path.isfile(p):
            continue
        text = read(p)
        fm = text.split("---")[1] if text.startswith("---") else ""
        name = re.search(r"name:\s*(\S+)", fm)
        if not name or name.group(1) != m["agent_id"]:
            problems.append(f'{m["file"]}: frontmatter name 与 roster 不一致')
        disp = re.findall(r'"([^"]*)"', fm.split("displayName:")[1].split("profession:")[0]) if "displayName:" in fm else []
        if len(disp) >= 2:
            if disp[0] != m["name_en"]:
                problems.append(f'{m["file"]}: displayName.en "{disp[0]}" != roster "{m["name_en"]}"')
            if disp[1] != m["name_zh"]:
                problems.append(f'{m["file"]}: displayName.zh "{disp[1]}" != roster "{m["name_zh"]}"')
        mt = re.search(r"maxTurns:\s*(\d+)", fm)
        if mt and int(mt.group(1)) != m["max_turns"]:
            problems.append(f'{m["file"]}: maxTurns {mt.group(1)} != roster {m["max_turns"]}')
    return problems

def sync_tables(members, do_write, errors):
    problems = []
    for rel, marker, subset, columns in TARGETS:
        path = os.path.join(ROOT, rel)
        text = read(path)
        begin, end = f"<!-- BEGIN {marker} -->", f"<!-- END {marker} -->"
        missing = [t for t in (begin, end) if t not in text]
        if missing:
            errors.append(f"{rel}: 缺少标记 {' 与 '.join(missing)}")
            continue
        head, rest = text.split(begin, 1)
        old, tail = rest.split(end, 1)
        new_block = "\n" + render_table(members, subset, columns) + "\n"
        if old != new_block:
            problems.append(f"{rel}: 标记内表格与 roster 不一致（{'已重写' if do_write else '需 --write 重写'}）")
            if do_write:
                write(path, head + begin + new_block + end + tail)
    return problems

def _replace_group(mo, new):
    """只替换捕获组那一段：旧数字不进正则，匹配里的其他数字也不动。"""
    s, base = mo.group(0), mo.start(0)
    return s[:mo.start(1) - base] + new + s[mo.end(1) - base:]

def apply_counts(text, vals):
    """把 text 里的人数声明改成 vals 里的数，返回 (新文本, [(旧声明, 应为)])。"""
    hits = []
    for pat, key in COUNT_CLAIMS:
        def repl(mo, k=key):
            if mo.group(1) == str(vals[k]):
                return mo.group(0)
            hits.append((mo.group(0), vals[k]))
            return _replace_group(mo, str(vals[k]))
        text = re.sub(pat, repl, text)
    return text, hits

def sync_counts(members, do_write):
    problems = []
    vals = {"n_experts": sum(1 for m in members if m["role"] != "lead"),
            "n_total": len(members)}
    for rel in COUNT_FILES:
        path = os.path.join(ROOT, rel)
        orig = read(path)
        new, hits = apply_counts(orig, vals)
        for old, want in hits:
            problems.append(f"{rel}: 「{old}」应为 {want}（{'已改' if do_write else '需 --write'}）")
        if do_write and new != orig:
            write(path, new)
    return problems

def _self_test():
    """自检：人数改写只动捕获组，前导的 1 与已正确的声明不受影响。"""
    ok = True
    vals = {"n_experts": 13, "n_total": 14}
    cases = [
        ("1 主理人 + 1 专家，调度 1 位专家，1 人编制，1 个人设",
         "1 主理人 + 13 专家，调度 13 位专家，14 人编制，14 个人设", 4),
        ("1 主理人 + 13 专家", "1 主理人 + 13 专家", 0),
    ]
    for src, want, want_hits in cases:
        got, hits = apply_counts(src, vals)
        if got != want or len(hits) != want_hits:
            ok = False
            print("SELF-TEST FAIL: %r → %r（命中 %d），应为 %r（命中 %d）"
                  % (src, got, len(hits), want, want_hits))
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="从 roster.json 生成名册表格并同步人数声明")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只校验，不改文件")
    g.add_argument("--write", action="store_true", help="重写表格与人数声明")
    g.add_argument("--self-test", action="store_true", help="内置自检（CI 用）")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    try:
        members = load_roster()
    except Exception as e:
        print(f"FAIL: roster.json 读取失败: {e}")
        return 1
    errors = validate_against_agents_dir(members)          # 脚本修不了，必须手工改
    drift = sync_tables(members, args.write, errors) + sync_counts(members, args.write)
    for e in errors:
        print("ERROR:", e)
    for d in drift:
        print("DRIFT:", d)
    if errors:
        print("结论: 有脚本修不了的错误，手工改正后重跑（--write 也不会跳过）。")
        return 1
    if drift:
        print(f"结论: {'已修复，请复查 git diff' if args.write else '不新鲜，运行 python scripts/generate_roster_tables.py --write'}")
        return 1 if args.check else 0
    print(f"OK: roster.json（{len(members)} 人 = 1 主理人 + {len(members)-1} 专家）与文档表格、人数声明一致。")
    return 0

if __name__ == "__main__":
    sys.exit(main())

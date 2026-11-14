#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plugin-forge · 名册表生成器（roster.json 为唯一来源）

用途
  从 roster.json 重新生成 README.md、skills/plugin-forge/SKILL.md、
  agents/plugin-forge-lead.md 里的名册表格，并同步各处的人数声明
  （"1 主理人 + N 专家"、"调度 N 位专家"、"N 人编制"、"N 个专家人设"）。
  表格区域由成对标记包住，标记之间只许本脚本写入，不许手改。

用法
  python scripts/generate_roster_tables.py --check   # 只比对与校验，不改文件（CI 用）
  python scripts/generate_roster_tables.py --write   # 重新生成表格并同步人数声明

校验
  - roster.json 的 members 与 agents/*.md 一一对应（文件存在、frontmatter
    name/displayName/maxTurns 与 roster 一致）。
  - 标记缺失或表格漂移 → --check 退出码 1；--write 会修复表格与人数。

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
    (r"(\d+) 个专家人设", "n_total"),
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
        fm = read(p).split("---")[1] if read(p).startswith("---") else ""
        checks = [
            (r"name:\s*(\S+)", m["agent_id"], "name"),
            (r'zh:\s*"([^"]*)"\s*\n\s*profession', None, None),
        ]
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

def sync_tables(members, do_write):
    problems = []
    for rel, marker, subset, columns in TARGETS:
        path = os.path.join(ROOT, rel)
        text = read(path)
        begin, end = f"<!-- BEGIN {marker} -->", f"<!-- END {marker} -->"
        if begin not in text or end not in text:
            problems.append(f"{rel}: 缺少标记 {begin}")
            continue
        head, rest = text.split(begin, 1)
        old, tail = rest.split(end, 1)
        new_block = "\n" + render_table(members, subset, columns) + "\n"
        if old != new_block:
            problems.append(f"{rel}: 标记内表格与 roster 不一致（{'已重写' if do_write else '需 --write 重写'}）")
            if do_write:
                write(path, head + begin + new_block + end + tail)
    return problems

def sync_counts(members, do_write):
    problems = []
    vals = {"n_experts": sum(1 for m in members if m["role"] != "lead"),
            "n_total": len(members)}
    for rel in COUNT_FILES:
        path = os.path.join(ROOT, rel)
        text = read(path)
        orig = text
        for pat, key in COUNT_CLAIMS:
            def repl(mo, k=key):
                if mo.group(1) != str(vals[k]):
                    problems.append(f"{rel}: 「{mo.group(0)}」应为 {vals[k]}（{'已改' if do_write else '需 --write'}）")
                return re.sub(r"\d+(?=[^\d]*$)" if False else mo.group(1), str(vals[k]), mo.group(0)) if do_write else mo.group(0)
            text = re.sub(pat, repl, text)
        if do_write and text != orig:
            write(path, text)
    return problems

def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="从 roster.json 生成名册表格并同步人数声明")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只校验，不改文件")
    g.add_argument("--write", action="store_true", help="重写表格与人数声明")
    args = ap.parse_args()
    try:
        members = load_roster()
    except Exception as e:
        print(f"FAIL: roster.json 读取失败: {e}")
        return 1
    problems = validate_against_agents_dir(members) + sync_tables(members, args.write) + sync_counts(members, args.write)
    if problems:
        for p in problems:
            print("DRIFT:", p)
        print(f"结论: {'已修复，请复查 git diff' if args.write else '不新鲜，运行 python scripts/generate_roster_tables.py --write'}")
        return 1 if args.check else 0
    print(f"OK: roster.json（{len(members)} 人 = 1 主理人 + {len(members)-1} 专家）与文档表格、人数声明一致。")
    return 0

if __name__ == "__main__":
    sys.exit(main())

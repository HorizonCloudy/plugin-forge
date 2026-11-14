#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEKO 专家团 · SessionStart 能力底座变更检测 hook（只读 / 零依赖）

用途
  每个新会话触发一次，扫描 MCP / 连接器 / 插件 / marketplace / hooks 底座，
  与 BASELINE 指纹比对，把「有变更 / 无变更 + 差异摘要 + 当前快照」通过
  hookSpecificOutput.additionalContext 注入会话上下文。

建议存放路径
  ~/.workbuddy/hooks/session_capability_refresh.py
  （hooks/ 目录需由主理人创建；本脚本自身不创建任何目录或文件）

挂载示例（需用户确认后，由主理人写入 ~/.workbuddy/settings.json 的 hooks.SessionStart）
  {"type":"command","command":"~/.workbuddy/binaries/python/versions/3.13.12/python.exe ~/.workbuddy/hooks/session_capability_refresh.py","timeout":10}

约束
  - 只读：仅 open(..., 'r')，绝不写文件、不联网、不改配置。
  - 零第三方依赖：仅 Python 标准库（3.8+）；本机实测 3.13.14。
  - 超时安全：内部 8s 软截止（宿主 timeout 10s），超时固定降级输出，不输出部分结果。
  - 永不阻塞：任何异常均被捕获，输出合法 HookOutput JSON 并 exit 0。

维护
  python session_capability_refresh.py --regen   # 只读打印当前指纹字典，用于刷新 BASELINE
  BASELINE 常量须与 references/capability-baseline.md 同步维护。
  已知例外: --regen 以 print 输出多行纯文本（非 HookOutput JSON）；禁止把 --regen 用于 hooks 命令。

注意
  ~/.workbuddy/settings.json 才是本机 WorkBuddy 生效配置；
  ~/.codebuddy/settings.json 并存且带另一套 hindsight codebuddy-* hooks；两个配置根相互独立。
"""
import sys, os, json, hashlib, glob, time, re

BASELINE_DATE = "2026-11-07"
SOFT_DEADLINE = time.monotonic() + 8.0

def _safe(s, n=64):
    """S6: 所有动态值消毒为 [A-Za-z0-9._-] 并截断，避免注入不可见上下文。"""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s))[:n]

ROOT = os.path.expanduser("~/.workbuddy")
CODEBUDDY = os.path.expanduser("~/.codebuddy")
MKTS = ROOT + "/plugins/marketplaces"
NEKO = MKTS + "/my-experts/plugins/neko-plugin-ops"
HINDSIGHT = os.path.expanduser("~/.hindsight/coding-agents/dist")

BASELINE = {
    "scalars": {
        "mcp.workbuddy":          "7d7adece4903",
        "mcp.catalog":            "72896b8dcc73",
        "mcp.catalog.count":      208,
        "mcp.skill.lexiang":      "c891097aa218",
        "settings.workbuddy":     "02fb107c4263",
        "settings.codebuddy":     "684c0eef3067",
        "plugin.neko-plugin-ops": "2689e205c4d0",
        "backups.workbuddy":      2,
        "backups.codebuddy":      2,
    },
    "marketplaces": {
        "cb_teams_marketplace":                  {"fp": "e2cf94afd6bb", "plugins": 29},
        "codebuddy-plugins-official":           {"fp": "46c87e0afe88", "plugins": 206},
        "experts":                              {"fp": "d19afc65e7c6", "plugins": 5},
        "my-experts":                           {"fp": "e5c3984b0016", "plugins": 3},
        "workbuddy-connector-plugins-official": {"fp": "2e6c4f72e6e1", "plugins": 350},
        "workbuddy-wecom-unified":              {"fp": "36af02a124f3", "plugins": 1},
    },
    "marketplace_dirs": ["cb_teams_marketplace", "codebuddy-plugins-official", "experts",
                         "my-experts", "plugin-data", "workbuddy-connector-plugins-official",
                         "workbuddy-wecom-unified"],
    "skills_count": 69,
    "skills_fp": "2e24b30b2315",
}

MCP_KEYS = ("type", "url", "command", "args", "timeout", "disabled", "env", "headers",
            "transportType", "enabled", "staticHeaders")

HOOK_SCRIPTS = [
    HINDSIGHT + "/workbuddy-sessionstart-hook.js",
    HINDSIGHT + "/workbuddy-hook.js",
    HINDSIGHT + "/workbuddy-stop-hook.js",
    HINDSIGHT + "/mcp-server.js",
    HINDSIGHT + "/codebuddy-sessionstart-hook.js",
    HINDSIGHT + "/codebuddy-hook.js",
    HINDSIGHT + "/codebuddy-stop-hook.js",
    ROOT + "/skills/haloflux-lab/scripts/session-beacon.mjs",
]

def _norm(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def _fp(o):
    return hashlib.sha256(_norm(o).encode("utf-8")).hexdigest()[:12]

def _read(p):
    if os.path.getsize(p) > 256 * 1024:
        raise ValueError("file too large")
    with open(p, "r", encoding="utf-8-sig") as f:
        return json.load(f)

def _ext_mcp(d):
    return {k: {kk: vv for kk, vv in sorted(v.items()) if kk in MCP_KEYS}
            for k, v in sorted(d.get("mcpServers", {}).items())}

def _ext_settings(d):
    return {"hooks": d.get("hooks", {}), "enabledPlugins": d.get("enabledPlugins", {})}

def _ext_mkt(d):
    return {"name": d.get("name"),
            "plugins": [{"name": p.get("name"), "version": p.get("version"),
                         "source": p.get("source")} for p in d.get("plugins", [])]}

def _ext_plugin(d):
    return {"version": d.get("version"), "agents": d.get("agents", []),
            "teamInfo": d.get("teamInfo", {}), "expertType": d.get("expertType")}

def _step(label):
    if time.monotonic() > SOFT_DEADLINE:
        raise TimeoutError(label)

def collect_fingerprints():
    """只读扫描，返回 (当前指纹字典, 是否截断, 读取异常列表)。"""
    cur = {"scalars": {}, "marketplaces": {}, "marketplace_dirs": [],
           "skills_count": 0, "skills_fp": ""}
    notes, truncated = [], False
    try:
        targets = [
            ("mcp.workbuddy",          ROOT + "/mcp.json",                                   _ext_mcp),
            ("mcp.catalog",            ROOT + "/connectors/default/mcp.json",             _ext_mcp),
            ("mcp.skill.lexiang",      ROOT + "/skills/lexiang-knowledge-base/mcp.json",  _ext_mcp),
            ("settings.workbuddy",     ROOT + "/settings.json",                           _ext_settings),
            ("settings.codebuddy",     CODEBUDDY + "/settings.json",                      _ext_settings),
            ("plugin.neko-plugin-ops", NEKO + "/.codebuddy-plugin/plugin.json",           _ext_plugin),
        ]
        for key, path, fn in targets:
            _step(key)
            if not os.path.isfile(path):
                cur["scalars"][key] = "<MISSING>"
                notes.append("路径缺失: " + _safe(path.replace(os.path.expanduser("~/"), "~/")))
                continue
            try:
                cur["scalars"][key] = _fp(fn(_read(path)))
            except Exception as e:
                cur["scalars"][key] = "<UNREADABLE>"
                notes.append("解析失败 %s: %s" % (_safe(path.replace(os.path.expanduser("~/"), "~/")), _safe(type(e).__name__)))
        _step("mcp.catalog.count")
        try:
            cur["scalars"]["mcp.catalog.count"] = len(
                _read(ROOT + "/connectors/default/mcp.json").get("mcpServers", {}))
        except Exception:
            cur["scalars"]["mcp.catalog.count"] = -1
        _step("marketplaces")
        for f in sorted(glob.glob(MKTS + "/*/.codebuddy-plugin/marketplace.json")):
            _step(f)
            name = os.path.basename(os.path.dirname(os.path.dirname(f)))
            try:
                d = _read(f)
                cur["marketplaces"][name] = {"fp": _fp(_ext_mkt(d)), "plugins": len(d.get("plugins", []))}
            except Exception:
                cur["marketplaces"][name] = {"fp": "<UNREADABLE>", "plugins": -1}
        _step("marketplace_dirs")
        cur["marketplace_dirs"] = sorted(
            os.path.basename(x) for x in glob.glob(MKTS + "/*") if os.path.isdir(x))
        _step("skills")
        sk = sorted(os.path.basename(x) for x in glob.glob(ROOT + "/skills/*") if os.path.isdir(x))
        cur["skills_count"] = len(sk)
        cur["skills_fp"] = _fp(sk)
        _step("backups")
        try:
            cur["scalars"]["backups.workbuddy"] = sum(
                1 for n in os.listdir(ROOT) if n.endswith(".hindsight-backup"))
            cur["scalars"]["backups.codebuddy"] = sum(
                1 for n in os.listdir(CODEBUDDY) if n.endswith(".hindsight-backup"))
        except Exception:
            cur["scalars"]["backups.workbuddy"] = -1
            cur["scalars"]["backups.codebuddy"] = -1
    except TimeoutError as e:
        truncated = True
        notes.append("内部 8s 软截止触发，剩余检测跳过: " + _safe(str(e)))
    return cur, truncated, notes

def build_context(cur, truncated, notes):
    diffs, snap = [], []
    for k, base in BASELINE["scalars"].items():
        c = cur["scalars"].get(k, "<NOT_SCANNED>")
        if c == "<NOT_SCANNED>":
            continue
        if c != base:
            diffs.append("  - %s: 基线 %s -> 当前 %s" % (k, base, c))
    bm, cm = BASELINE["marketplaces"], cur["marketplaces"]
    for n in sorted(set(bm) | set(cm)):
        if n not in cm:
            diffs.append("  - marketplace 清单删除: " + _fp(n))
        elif n not in bm:
            diffs.append("  - marketplace 清单新增: " + _fp(n))
        elif cm[n] != bm[n]:
            diffs.append("  - marketplace 变更: %s %s -> %s" % (_fp(n), bm[n], cm[n]))
    bd, cd = set(BASELINE["marketplace_dirs"]), set(cur["marketplace_dirs"])
    for n in sorted(cd - bd):
        diffs.append("  - 新增 marketplace 目录: " + _fp(n))
    for n in sorted(bd - cd):
        diffs.append("  - 删除 marketplace 目录: " + _fp(n))
    if cur["skills_count"] != BASELINE["skills_count"]:
        diffs.append("  - skills 数量: %s -> %s" % (BASELINE["skills_count"], cur["skills_count"]))
    if cur["skills_fp"] and cur["skills_fp"] != BASELINE["skills_fp"]:
        diffs.append("  - skills 清单指纹变化（增删技能；清单由 Task A 维护）")
    missing = [p for p in HOOK_SCRIPTS if not os.path.isfile(p)]
    for p in missing:
        diffs.append("  - Hook 脚本缺失: " + _safe(p.replace(os.path.expanduser("~/"), "~/")))

    try:
        ms = _read(ROOT + "/mcp.json").get("mcpServers", {})
        en = [k for k, v in ms.items() if not v.get("disabled", False)]
        dis = [k for k, v in ms.items() if v.get("disabled", False)]
        snap.append("MCP 主配置 %d 项 | 启用 %d 项 (fp %s) | 禁用 %d 项 (fp %s)"
                    % (len(ms), len(en), _fp(sorted(en)), len(dis), _fp(sorted(dis))))
    except Exception:
        snap.append("MCP 主配置快照不可用")
    snap.append("连接器目录模板 %s 项（全 disabled；运行时启用状态未在本快照核验）"
                % cur["scalars"].get("mcp.catalog.count", "?"))
    try:
        h = _read(ROOT + "/settings.json").get("hooks", {})
        ncmd = sum(len(e.get("hooks", [])) for g in h.values() for e in g)
        snap.append("生效配置 ~/.workbuddy/settings.json: hooks %d 事件 / %d 条命令；~/.codebuddy/settings.json 另有另一套 hindsight codebuddy-* 并存" % (len(h), ncmd))
    except Exception:
        snap.append("settings 快照不可用")
    snap.append("marketplaces: %d 目录 / %d 份清单（plugin-data 为数据目录，无清单）"
                % (len(cur["marketplace_dirs"]), len(cur["marketplaces"])))
    try:
        snap.append("专家团插件 neko-plugin-ops v%s（my-experts 共 %s 个插件）"
                    % (_safe(_read(NEKO + "/.codebuddy-plugin/plugin.json").get("version", "?"), 16),
                       _safe(cur["marketplaces"].get("my-experts", {}).get("plugins", "?"), 8)))
    except Exception:
        snap.append("插件版本快照不可用")
    snap.append("skills: %d 个（清单由 Task A / neko-skill-ops 维护）" % cur["skills_count"])
    snap.append("Hook 脚本就绪: %d/%d" % (len(HOOK_SCRIPTS) - len(missing), len(HOOK_SCRIPTS)))

    lines = ["[NEKO 能力底座 · 会话启动检测] 基线 " + BASELINE_DATE,
             "结论: " + ("有变更（%d 项）" % len(diffs) if diffs
                        else "无变更（基线一致，最后核验 " + BASELINE_DATE + "）")]
    lines.append("当前快照:")
    for s in snap:
        lines.append("  · " + s)
    lines.append("差异:")
    lines.extend(diffs[:20] if diffs else ["  - 无（与基线一致）"])
    if len(diffs) > 20:
        lines.append("  - ...另有 %d 项，见完整扫描" % (len(diffs) - 20))
    if notes:
        lines.append("读取异常:")
        for n in notes[:8]:
            lines.append("  - " + re.sub(r"[\x00-\x1f\x7f]", "_", str(n))[:200])
    lines.append("证据: 本机文件只读 [FACT/LOCAL]；连接器运行时状态、skill 远程版本、官方文档更新均为 [未联网核验]，不在本机文件只读范围内。")
    if diffs:
        lines.append("差异为只读观测结果；基线由主理人维护；本脚本不安装或更新第三方组件。")
    ctx = "\n".join(lines)
    if len(ctx) > 2000:
        marker = "\ntruncated=1"
        ctx = ctx[:2000 - len(marker)] + marker
    return ctx

FALLBACK_CONTEXT = "本次检测不可用。本 hook 不写任何文件。"

def emit(context):
    # S8 精确形态：顶层仅 hookSpecificOutput，不写任何用户可见的第二通道。
    payload = {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context},
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()

def main():
    try:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        # 维护模式必须先于 stdin 读取：--regen 常在交互式终端手动执行，
        # 若先 sys.stdin.read() 会因等待 EOF 而挂起（宿主/终端未关闭 stdin）。
        if "--regen" in sys.argv:
            cur, _, _ = collect_fingerprints()
            print(json.dumps(cur, indent=2, ensure_ascii=False))
            return 0
        try:
            raw = sys.stdin.read()
            inp = json.loads(raw) if raw.strip() else {}
        except Exception:
            inp = {}
        cur, truncated, notes = collect_fingerprints()
        if truncated:
            emit(FALLBACK_CONTEXT)
            return 0
        ctx = build_context(cur, truncated, notes)
        emit(ctx)
        return 0
    except Exception:
        # S10：固定单行 JSON、零动态文本；emit() 再包一层 try/except，
        # 保证 stdout 自身异常时也静默放行并 exit 0。
        try:
            emit(FALLBACK_CONTEXT)
        except Exception:
            pass
        return 0

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""N.E.K.O 插件运行时沙箱 —— 隔离启动官方插件服务器，用于验证插件真实行为。

设计依据（全部来自 Project-N-E-K-O/N.E.K.O 源码 @ 645da54，2026-11-07 复核，非推测）：
  - 入口：plugin/user_plugin_server.py（uvicorn，standalone 时 manage_lifecycle=True，
    即由它自己扫描 plugin/plugins/ 并 autostart）。autostart 由该参数决定，
    与 NEKO_PLUGIN_HOSTED_BY_AGENT 无关（该变量在 http_app.py 已无读取点）
  - 端口：环境变量 NEKO_USER_PLUGIN_SERVER_PORT，默认取 config.USER_PLUGIN_SERVER_PORT
    （config/network.py:193 = 48916）；standalone 入口被占用时仍会自行向后找并回写
  - 健康检查：GET /health -> {"status": "ok", "time": <iso>}
  - 插件源目录：plugin/plugins/<plugin_id>/，含 plugin.toml（[plugin] id / version）
  - autostart 还需 [plugin_runtime] auto_start = true（省略默认 false），
    且该 id 不在 plugin_autostart_pending.json 的待审批集合里

用法：
  python sandbox.py doctor
  python sandbox.py prepare  --root D:/neko-sandbox
  python sandbox.py install  --root D:/neko-sandbox
  python sandbox.py plugin-add --root D:/neko-sandbox --src D:/path/to/plugin
  python sandbox.py start    --root D:/neko-sandbox
  python sandbox.py status   --root D:/neko-sandbox
  python sandbox.py stop     --root D:/neko-sandbox
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_URL = "https://github.com/Project-N-E-K-O/N.E.K.O.git"
# 这两个 -c 只对 Windows 的 schannel 后端有意义。别的平台的 git 会在 http_init() 里直接
# die（fatal: Unsupported SSL backend 'schannel'），clone 和 fetch 全部失败，所以按平台给。
GIT_HTTP_OPTS = (["-c", "http.sslBackend=schannel",
                  "-c", "http.schannelCheckRevoke=false"]
                 if os.name == "nt" else [])
# 刻意不等于上游默认端口（config/network.py:193 USER_PLUGIN_SERVER_PORT=48916）：
# 沙箱要和用户正在跑的 N.E.K.O 并存，撞默认端口只会白等 /health。
DEFAULT_PORT = 43117
# 上游 plugin/settings.py:790 对 NEKO_PLUGIN_STARTUP_TIMEOUT > 300 直接 raise ValueError，
# 服务会在 import 阶段就崩，报错离「超时配置写大了」很远。这里按上游上限夹紧。
UPSTREAM_STARTUP_TIMEOUT_MAX = 300.0
STATE_FILE = "sandbox.json"
CONFIG_FILE = "config.json"


def load_config(root: Path) -> dict:
    p = root / CONFIG_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def save_config(root: Path, data: dict) -> None:
    (root / CONFIG_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def repo_dir(root: Path) -> Path:
    """沙箱使用的官方源码目录：优先 config 里登记的外部 checkout，否则 root/repo。"""
    cfg = load_config(root)
    return Path(cfg["repo"]) if cfg.get("repo") else (root / "repo")


def toml_section_value(text: str, section: str, key: str) -> str | None:
    """不依赖 tomllib（3.11+）地读某个 [section] 下的标量值（去引号）。

    存在的理由：早先按「行首是 id」解析插件 id，会误命中 `[plugin.ui]` 或别的段里以 id 开头的键，
    于是把插件复制到错误的目录名下 —— 表现为「服务起来了、/plugins 里没有它」，极难排查。
    """
    current = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if current != section or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() != key:
            continue
        value = v.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return None


def toml_section_flag(text: str, section: str, key: str) -> bool | None:
    """读某个 [section] 下的布尔键。

    返回 True/False 表示读到了；None 表示该键没写（上游对 auto_start 的语义是「省略=false」，
    但调用方要能区分「显式 false」和「根本没写」，所以不回落到 False）。
    """
    value = toml_section_value(text, section, key)
    if value is None:
        return None
    return value.lower() in {"true", "1", "yes", "on"}


# ---------------------------------------------------------------- helpers
def log(msg: str) -> None:
    print(f"[sandbox] {msg}", flush=True)


def die(msg: str, code: int = 2):
    print(f"[sandbox][ERROR] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def load_state(root: Path) -> dict:
    p = root / STATE_FILE
    if not p.is_file():
        die(f"未找到 {p}，请先 start")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(root: Path, data: dict) -> None:
    (root / STATE_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host: str, want: int, tries: int = 40) -> int:
    for p in range(want, want + tries):
        if port_free(host, p):
            return p
    die(f"{host} 上 {want}–{want + tries - 1} 全部被占用")


# 本机代理（HTTP_PROXY=127.0.0.1:xxxx）会把 127.0.0.1 也当外网转发，
# 导致服务明明在跑却报 WinError 10061。探活必须显式绕过代理。
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get(port: int, path: str, timeout: float = 5.0):
    url = f"http://127.0.0.1:{port}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def venv_python(root: Path) -> Path:
    sub = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    return root / ".venv" / sub / exe


# ---------------------------------------------------------------- commands
def cmd_doctor(args):
    checks = []

    def add(name, ok, detail=""):
        checks.append((name, ok, detail))

    add("python", sys.version_info >= (3, 10), sys.version.split()[0])
    add("git", bool(shutil.which("git")), shutil.which("git") or "未找到")
    uv = shutil.which("uv")
    add("uv（可选，官方推荐）", uv is not None, uv or "未安装，将回退 pip")
    root = Path(args.root).expanduser().resolve() if args.root else None
    if root:
        free = shutil.disk_usage(root.anchor or root).free / 2**30
        add("磁盘可用", free > 8, f"{free:.1f} GiB（依赖较重，建议 ≥8 GiB）")
    add("端口", port_free("127.0.0.1", args.port), f"127.0.0.1:{args.port}")

    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'WARN'}] {name}: {detail}")
    hard_fail = [c for c in checks[:1] if not c[1]]
    if hard_fail:
        die("Python 版本不足（需 ≥3.10）")


def cmd_prepare(args):
    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for d in ("state", "logs", "plugins"):
        (root / d).mkdir(exist_ok=True)

    entry_rel = Path("plugin") / "user_plugin_server.py"

    # 模式 A：直接挂载已有的官方 checkout（推荐——用户自己维护、随时 pull）
    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
        if not (repo / entry_rel).is_file():
            die(f"{repo} 下没有 {entry_rel}，不是 N.E.K.O 源码目录")
        save_config(root, {"repo": str(repo), "mode": "external"})
        log(f"已挂载外部源码: {repo}")
        log("提示：该目录不受沙箱管理，运行前用 `sandbox.py sync` 拉最新")
        if (repo / ".git").is_dir():
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            log(f"当前 HEAD: {head}")
        return

    # 模式 B：沙箱内自建仓库
    repo = root / "repo"
    if (repo / entry_rel).is_file():
        save_config(root, {"repo": str(repo), "mode": "cloned"})
        log(f"仓库已存在，跳过克隆: {repo}")
    else:
        if repo.exists():
            die(f"{repo} 已存在但不是有效仓库，请先清理")
        log(f"克隆 {args.repo_url} → {repo}")
        cmd = ["git", *GIT_HTTP_OPTS, "clone", "--depth", "1"]
        if args.ref:
            cmd += ["--branch", args.ref]
        cmd += [args.repo_url, str(repo)]
        rc = subprocess.call(cmd)
        if rc != 0:
            die("克隆失败（代理/网络）。可先用别的方式取到源码，再用 --repo 指向它")
        save_config(root, {"repo": str(repo), "mode": "cloned"})

    log(f"沙箱根目录: {root}")
    log(f"  仓库  : {repo}")
    log(f"  状态  : {root / 'state'}（HOME 重定向至此，避免污染真实 ~/.neko）")
    log(f"  日志  : {root / 'logs'}")


def _git(repo: Path, *args: str) -> list[str]:
    """Windows 上 schannel 的证书吊销检查会挡住部分镜像源，这里统一关掉。"""
    return ["git", "-C", str(repo), *GIT_HTTP_OPTS, *args]


def cmd_sync(args):
    """拉取官方最新源码。官方迭代快，运行前应同步一次。"""
    root = Path(args.root).expanduser().resolve()
    repo = repo_dir(root)
    if not (repo / ".git").is_dir():
        die(f"{repo} 不是 git 仓库，无法同步（用 --repo 指向有效 checkout）")

    def run(*a: str) -> int:
        return subprocess.call(_git(repo, *a))

    def head():
        return subprocess.run(_git(repo, "rev-parse", "--short", "HEAD"),
                              capture_output=True, text=True).stdout.strip()

    before = head()
    branch = subprocess.run(_git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
                            capture_output=True, text=True).stdout.strip() or "main"
    remote = subprocess.run(_git(repo, "remote", "get-url", "origin"),
                            capture_output=True, text=True).stdout.strip()
    log(f"同步 {repo}（分支 {branch}，当前 {before}）")
    if remote:
        log(f"  remote: {remote}")

    if run("fetch", "--all", "--prune") != 0:
        die("git fetch 失败（代理/网络）。源码保持原样，未做改动")

    rc = run("reset", "--hard", f"origin/{branch}") if args.hard else run("pull", "--ff-only")
    if rc != 0:
        die("同步失败：本地有未提交改动或分叉。确认后用 sync --hard 覆盖")

    after = head()
    if before == after:
        log(f"已是最新（{after}）")
    else:
        cnt = subprocess.run(_git(repo, "rev-list", "--count", f"{before}..{after}"),
                             capture_output=True, text=True).stdout.strip()
        log(f"已更新 {before} → {after}（{cnt} 个提交）")
    dirty = subprocess.run(_git(repo, "status", "--porcelain"),
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        log("注意：工作区有未提交改动，沙箱将按当前文件内容运行")


def _uv_env():
    """uv 环境：走 Windows 证书库（等价 truststore），避免代理根证书导致的 SSL 失败。"""
    env = os.environ.copy()
    # UV_SYSTEM_CERTS 是新名，UV_NATIVE_TLS 是旧名（0.13 起弃用），两个都给
    env["UV_SYSTEM_CERTS"] = "1"
    env["UV_NATIVE_TLS"] = "1"
    # 跨盘符（C: -> E:）硬链接会失败，强制拷贝
    env["UV_LINK_MODE"] = "copy"
    env.setdefault("UV_HTTP_TIMEOUT", "120")
    return env


def _uv(*argv, cwd=None):
    return subprocess.call(["uv", *argv], cwd=cwd, env=_uv_env())


def cmd_install(args):
    root = Path(args.root).expanduser().resolve()
    repo = repo_dir(root)
    if not (repo / "requirements.txt").is_file():
        die("仓库不完整，先 prepare")

    py = venv_python(root)
    mode = load_config(root).get("mode", "cloned")
    where = "沙箱 venv（不动用户源码目录）" if mode == "external" else "仓库内 venv"
    uv_ok = bool(shutil.which("uv")) and not args.no_uv

    # 1) 建环境：uv 优先（自动带 pip），回退标准库 venv
    if not py.is_file():
        if uv_ok:
            log(f"创建沙箱 venv（uv --python {args.py_version} --seed）: {root / '.venv'}")
            rc = _uv("venv", "--python", args.python or args.py_version,
                     "--seed", str(root / ".venv"))
            if rc != 0:
                log("uv venv 失败，回退 python -m venv")
                uv_ok = False
        if not py.is_file():
            interp = args.python or sys.executable
            log(f"创建沙箱 venv（解释器 {interp}）: {root / '.venv'}")
            if subprocess.call([interp, "-m", "venv", str(root / ".venv")]) != 0:
                die("venv 创建失败")
    if not py.is_file():
        die(f"venv 创建后仍找不到 {py}")

    if subprocess.call([str(py), "-m", "pip", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        log("venv 内无 pip，执行 ensurepip")
        subprocess.call([str(py), "-m", "ensurepip", "--upgrade"])

    req = repo / "requirements.txt"
    log(f"安装依赖到{where}：{req}")

    # 2) 安装：uv 优先。cwd=repo 是必须的——requirements 第 3 行是 `-e .`
    if uv_ok:
        log("使用 uv 安装（并行解析 + 预编译轮子，避免源码编译）")
        rc = _uv("pip", "install", "--python", str(py), "-r", str(req), cwd=str(repo))
        if rc == 0:
            log("依赖安装完成（uv）")
            return
        log("uv 安装失败，回退 pip")

    log("使用 pip 安装（较慢；含源码构建的包会拖很久）")
    subprocess.call([str(py), "-m", "pip", "-q", "--disable-pip-version-check",
                     "install", "--upgrade", "pip"])
    rc = subprocess.call([str(py), "-m", "pip", "install",
                          "--disable-pip-version-check", "-r", str(req)], cwd=str(repo))
    if rc != 0:
        if not getattr(args, "insecure_pip", False):
            die("依赖安装失败（多为代理根证书导致的 SSL 校验失败）。这里不静默关校验：\n"
                "  首选修证书链，或给 pip / uv 指定 CA（PIP_CERT、UV_NATIVE_TLS）；\n"
                "  确认这台机器可以接受不校验 TLS 的下载后，再显式加 --insecure-pip 重跑。")
        log("警告：--insecure-pip 已指定，对 PyPI 关闭 TLS 校验重试一次（中间人风险自负）")
        rc = subprocess.call([str(py), "-m", "pip", "install",
                              "--disable-pip-version-check",
                              "--trusted-host", "pypi.org",
                              "--trusted-host", "files.pythonhosted.org",
                              "--trusted-host", "pypi.python.org",
                              "-r", str(req)], cwd=str(repo))
    if rc != 0:
        die("依赖安装失败，见上方输出")
    log("依赖安装完成（pip）")


def cmd_plugin_add(args):
    root = Path(args.root).expanduser().resolve()
    src = Path(args.src).expanduser().resolve()
    repo = repo_dir(root)
    if not (src / "plugin.toml").is_file():
        die(f"{src} 下没有 plugin.toml，不是合法插件目录")

    text = (src / "plugin.toml").read_text(encoding="utf-8", errors="replace")
    pid = toml_section_value(text, "plugin", "id")
    if not pid:
        die("plugin.toml 里没解析到 [plugin] id")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", pid):
        die(f"plugin.toml 的 [plugin] id「{pid}」不合法：只允许 ^[A-Za-z_][A-Za-z0-9_]*$"
            "（与上游 generator.py 同规则），拒绝以防 rmtree 删到 plugins 之外")

    dest = repo / "plugin" / "plugins" / pid
    if args.link and os.name != "nt":
        if dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src, target_is_directory=True)
        log(f"已软链 {src} -> {dest}")
    else:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        log(f"已复制 {src} -> {dest}")
    log(f"插件 id = {pid}")

    # 上游 core/registry.py:1290-1296 —— 没写 [plugin_runtime] auto_start 时默认 false，
    # 于是插件会被扫描到、出现在 /plugins 里，但永远不会 autostart。
    # 这是「服务起来了、插件没跑」最隐蔽的一种成因，在这里提前说清楚。
    auto_start = toml_section_flag(text, "plugin_runtime", "auto_start")
    if auto_start:
        log("[OK] plugin.toml 声明 [plugin_runtime] auto_start = true，会随服务 autostart")
    elif auto_start is None:
        log("[WARN] plugin.toml 没有 [plugin_runtime] auto_start，上游默认按 false 处理 —— "
            "插件会被注册但不会被 autostart；要验 autostart 就在插件里显式写 auto_start = true")
    else:
        log("[WARN] plugin.toml 显式写了 [plugin_runtime] auto_start = false —— "
            "插件会被注册但不会被 autostart；只能走 /plugin/<id>/start 手动拉起")


def cmd_plugin_rm(args):
    """撤掉 plugin-add 放进 checkout 的插件目录，保持你的 git 工作区干净。"""
    root = Path(args.root).expanduser().resolve()
    repo = repo_dir(root)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.id):
        die(f"--id「{args.id}」不合法：只允许 ^[A-Za-z_][A-Za-z0-9_]*$，"
            "拒绝以防 rmtree 删到 plugins 之外")
    target = repo / "plugin" / "plugins" / args.id
    if not target.is_dir():
        die(f"{target} 不存在")
    if args.dry_run:
        log(f"[dry-run] 将删除 {target}")
        return
    shutil.rmtree(target)
    log(f"已删除 {target}")
    dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "plugin/plugins"],
                           capture_output=True, text=True).stdout.strip()
    log("plugin/plugins 现状：" + (dirty.replace("\n", " | ") if dirty else "干净"))


# 宿主环境里的凭据不该进被测第三方插件的进程。按名字形状删，不按名字白名单加：
# 缺一个必需变量会让沙箱以一个看不出关联的错误崩掉，而漏删只影响纵深防御的一层。
# 不删 AUTH 形状的名字：SSH_AUTH_SOCK 会命中它，靠 git over SSH 的插件会丢掉 agent。
SECRET_ENV_RE = re.compile(
    r"(?i)(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|PASS|KEY|APIKEY|CREDENTIAL|CREDENTIALS)($|_)")


def _server_env(root, args):
    """构造隔离后的服务环境。LOCALAPPDATA 才是 Windows 上 N.E.K.O 的数据根。"""
    env = os.environ.copy()
    dropped = [k for k in env if SECRET_ENV_RE.search(k)]
    for k in dropped:
        env.pop(k, None)
    log("已从沙箱环境删除 %d 个凭据形状变量（%s）" %
        (len(dropped), ", ".join(sorted(dropped)[:6]) + ("…" if len(dropped) > 6 else "")))
    env["NEKO_USER_PLUGIN_SERVER_PORT"] = str(args.port_resolved)
    # 兜底：即便有人从外部环境带进 NEKO_PLUGIN_HOSTED_BY_AGENT 也清掉。注意这一条现在已经
    # 不是 autostart 的开关了——上游 http_app.py:190 只看 build_plugin_server_app(manage_lifecycle=)
    # 参数，而 user_plugin_server.py:81 硬编码 manage_lifecycle=True。留着清理是为了不往宿主日志里
    # 注入一个「嵌入式」的假身份，避免误导排障。
    env.pop("NEKO_PLUGIN_HOSTED_BY_AGENT", None)
    if args.isolate_home:
        # 只改 HOME/USERPROFILE 没用——N.E.K.O 在 Windows 上取 LOCALAPPDATA 作为数据根
        # （utils/config_manager/storage_roots.py）。不改就会读到用户真实的
        # %LOCALAPPDATA%\N.E.K.O，把用户已装的插件全部拉进来 autostart。
        state = root / "state"
        home = state / "home"
        local = state / "LocalAppData"
        appdata = state / "AppData"
        tmp = state / "Temp"
        for d in (home, local, appdata, tmp):
            d.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        env["LOCALAPPDATA"] = str(local)
        env["APPDATA"] = str(appdata)
        env["TEMP"] = str(tmp)
        env["TMP"] = str(tmp)
        # PLUGIN_CONFIG_ROOT 上游已标 legacy（env 仍生效，新代码用 PLUGIN_CONFIG_ROOTS /
        # USER_PLUGIN_CONFIG_ROOT）。这里当双保险继续钉死，行为不变。
        env["PLUGIN_CONFIG_ROOT"] = str(local / "N.E.K.O" / ".neko-plugin-installations" / "plugins")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # 上游默认 10s 对冷 venv 太短，首次 import 重依赖会超时判 failed。
    # 但上游 plugin/settings.py:788-791 对 >300 直接 raise ValueError，服务会在 import 阶段就崩，
    # 报错和「超时配大了」毫无关系。这里对最终生效值夹紧（含外部环境带进来的值）。
    want = args.plugin_startup_timeout
    try:
        inherited = float(env["NEKO_PLUGIN_STARTUP_TIMEOUT"])
        if inherited != args.plugin_startup_timeout:
            want = inherited
    except (KeyError, ValueError):
        pass
    if want > UPSTREAM_STARTUP_TIMEOUT_MAX:
        log(f"[WARN] NEKO_PLUGIN_STARTUP_TIMEOUT={want:g} 超过上游上限 "
            f"{UPSTREAM_STARTUP_TIMEOUT_MAX:g}s（plugin/settings.py:790 会 raise ValueError），已夹紧")
        want = UPSTREAM_STARTUP_TIMEOUT_MAX
    env["NEKO_PLUGIN_STARTUP_TIMEOUT"] = str(want)
    return env


def _wait_health(proc, port, log_file, timeout, fh=None):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            if fh:
                fh.close()
            tail = "\n".join(log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
            die(f"服务进程提前退出（code={proc.returncode}）\n{tail}")
        status, body = http_get(port, "/health", timeout=2)
        if status == 200:
            return status
        time.sleep(1.0)
    return status


def cmd_serve(args):
    """前台运行（供受管后台任务使用，进程随任务生命周期）。"""
    root = Path(args.root).expanduser().resolve()
    repo = repo_dir(root)
    entry = repo / "plugin" / "user_plugin_server.py"
    if not entry.is_file():
        die("找不到 plugin/user_plugin_server.py，先 prepare")
    py = Path(args.python).expanduser() if args.python else venv_python(root)
    if not py.is_file():
        py = Path(sys.executable)
    args.port_resolved = pick_port("127.0.0.1", args.port)
    env = _server_env(root, args)
    log_file = root / "logs" / f"server-{time.strftime('%Y%m%d-%H%M%S')}.log"
    save_state(root, {"pid": os.getpid(), "port": args.port_resolved, "root": str(root),
                      "repo": str(repo), "log": str(log_file), "mode": "serve",
                      "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    log(f"前台服务  port={args.port_resolved}  log={log_file}")
    log("就绪后可用 status 检查；结束用 stop 或终止本任务")
    fh = open(log_file, "w", encoding="utf-8", errors="replace")
    # 不用 os.execve：Windows 上直接 SIGSEGV。用子进程前台等待，
    # 进程与本任务同生命周期——由受管后台任务托管，TaskStop 会连树一起收。
    proc = subprocess.Popen([str(py), str(entry)], cwd=str(repo), env=env,
                            stdout=fh, stderr=subprocess.STDOUT, close_fds=True)
    save_state(root, {"pid": proc.pid, "port": args.port_resolved, "root": str(root),
                      "repo": str(repo), "log": str(log_file), "mode": "serve",
                      "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    rc = proc.wait()
    fh.close()
    log(f"服务已退出（code={rc}）")
    raise SystemExit(rc)


def cmd_start(args):
    root = Path(args.root).expanduser().resolve()
    repo = repo_dir(root)
    entry = repo / "plugin" / "user_plugin_server.py"
    if not entry.is_file():
        die("找不到 plugin/user_plugin_server.py，先 prepare")

    py = Path(args.python).expanduser() if args.python else venv_python(root)
    if not py.is_file():
        py = Path(sys.executable)
        log(f"未找到沙箱 venv，回退当前解释器: {py}")

    args.port_resolved = pick_port("127.0.0.1", args.port)
    port = args.port_resolved
    env = _server_env(root, args)

    log_file = root / "logs" / f"server-{time.strftime('%Y%m%d-%H%M%S')}.log"
    log(f"启动插件服务器  port={port}  log={log_file}")
    fh = open(log_file, "w", encoding="utf-8", errors="replace")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen([str(py), str(entry)], cwd=str(repo), env=env,
                            stdout=fh, stderr=subprocess.STDOUT,
                            creationflags=flags, close_fds=True)
    save_state(root, {"pid": proc.pid, "port": port, "root": str(root),
                      "repo": str(repo), "log": str(log_file), "mode": "start",
                      "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    status = _wait_health(proc, port, log_file, args.timeout, fh)
    fh.close()
    if status != 200:
        proc.terminate()
        die(f"{args.timeout}s 内 /health 未就绪，见 {log_file}")
    log(f"就绪  http://127.0.0.1:{port}/health")
    log(f"pid={proc.pid}（用 stop 停止）")
    if os.name == "nt":
        log("提示：若本环境用 job object 回收进程树，服务会随命令结束一起终止；此时改用 serve + 后台任务")


def _pid_is_sandbox_server(pid):
    """True = 命令行里有 user_plugin_server.py；False = 确认不是；None = 读不到，未知。

    机器重启后 pid 会被复用，只看 sandbox.json 的 pid 会误杀无关进程。
    """
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\")"
                 ".CommandLine" % int(pid)],
                capture_output=True, timeout=20)
            if r.returncode != 0:
                return None
            cmd = r.stdout.decode("utf-8", "replace")
        else:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().decode("utf-8", "replace")
    except Exception:
        return None
    if not cmd.strip():
        return None
    return "user_plugin_server.py" in cmd


def cmd_stop(args):
    root = Path(args.root).expanduser().resolve()
    st = load_state(root)
    pid = st.get("pid")
    if not pid:
        die("状态文件里没有 pid")
    verdict = _pid_is_sandbox_server(pid)
    if verdict is False:
        log(f"pid={pid} 的命令行里没有 user_plugin_server.py，判定为 pid 复用，"
            "不杀该进程；只清沙箱状态文件。若沙箱服务仍在，请手工核对端口后处理")
    else:
        if verdict is None:
            log("读不到 pid 的命令行（权限或平台限制），按旧行为继续停止")
        if os.name == "nt":
            subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
    (root / STATE_FILE).unlink(missing_ok=True)
    log(f"已停止 pid={pid}")


def _plugin_rows(payload):
    """把 /plugins 或 /plugin/status 的返回统一成 [(plugin_id, 状态摘要)]。

    /plugins        -> {"plugins": [ {...}, ... ], "message": str}   （query_service.py:885）
    /plugin/status  -> {"plugins": { "<id>": {...} }, "time": iso}   （query_service.py:831）
    这两种形状一个是 list、一个是 dict，早先的版本只处理了 list，导致 /plugin/status 一条都打不出来。
    """
    rows = []
    if not isinstance(payload, dict):
        return rows
    plugins = payload.get("plugins")
    if isinstance(plugins, list):
        for it in plugins:
            if isinstance(it, dict):
                pid = it.get("plugin_id") or it.get("id") or "?"
                pst = it.get("status") or it.get("state") or it.get("runtime_load_state") or "?"
                rows.append((str(pid), str(pst)))
    elif isinstance(plugins, dict):
        for pid, it in plugins.items():
            if isinstance(it, dict):
                pst = (it.get("status") or it.get("state")
                       or it.get("runtime_load_state") or "?")
            else:
                pst = it if isinstance(it, str) else "?"
            rows.append((str(pid), str(pst)))
    return rows


# 上游实际路由（plugin/server/routes/ 下的 @router.get）：
#   /plugins          plugins.py:42    插件列表
#   /plugin/status    plugins.py:35    逐插件运行状态（验证 autostart 用这条最直接）
#   /plugin/messages  messages.py:22   消息队列
# 早先这里探的是 /runs 和 /messages —— 两个 GET 都不能当探活路由：GET /runs（集合）405，
# 集合只有 POST（runs.py:35）；单个 run 虽有 GET /runs/{run_id}（runs.py:44），但要先有 run_id。
# /messages 根本没这个路径，会 404。看的人会以为是插件的问题。
STATUS_ROUTES = (
    ("/plugins", "plugins"),
    ("/plugin/status", "plugins"),
    ("/plugin/messages", "messages"),
)


def cmd_status(args):
    """打印运行状态。插件列表从 /plugins 与 /plugin/status 解析，失败也照实打印。"""
    root = Path(args.root).expanduser().resolve()
    st = load_state(root)
    if not st:
        die(f"未找到 {root / STATE_FILE}，请先 start 或 serve")

    port = st.get("port")
    code, body = http_get(port, "/health", timeout=3)
    info = {"sandbox": st, "health_http": code, "health_body": body}
    if code != 200:
        print()
        log("[提示] 服务无响应，可能已退出；用 stop 清理后重启")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    for path, label in STATUS_ROUTES:
        c, b = http_get(port, path, timeout=5)
        n = "?"
        if isinstance(b, (list, dict)):
            items = b if isinstance(b, list) else (b.get(label) or b.get("items") or b.get("data") or [])
            n = len(items) if isinstance(items, (list, dict)) else "?"
        print(f"  {path} -> HTTP {c}  items={n}")
        for pid, pst in _plugin_rows(b)[:20]:
            print(f"      - {pid:<24} {pst}")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="N.E.K.O 插件运行时沙箱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="检查环境前置条件")
    d.add_argument("--root", default=None)
    d.add_argument("--port", type=int, default=DEFAULT_PORT)
    d.set_defaults(func=cmd_doctor)

    p = sub.add_parser("prepare", help="挂载已有源码或克隆官方仓库，并建隔离目录")
    p.add_argument("--root", required=True)
    p.add_argument("--repo", default=None, help="已有的 N.E.K.O 源码目录（推荐，免克隆）")
    p.add_argument("--repo-url", default=REPO_URL)
    p.add_argument("--ref", default=None)
    p.set_defaults(func=cmd_prepare)

    y = sub.add_parser("sync", help="拉取官方最新源码（官方迭代快，跑前先同步）")
    y.add_argument("--root", required=True)
    y.add_argument("--hard", action="store_true", help="本地有改动时强制对齐 origin（会丢改动）")
    y.set_defaults(func=cmd_sync)

    i = sub.add_parser("install", help="安装依赖到沙箱 venv")
    i.add_argument("--root", required=True)
    i.add_argument("--python", default=None, help="用于创建 venv 的解释器（默认当前解释器，建议 3.11）")
    i.add_argument("--no-uv", action="store_true", help="禁用 uv，强制用 pip（排障用）")
    i.add_argument("--insecure-pip", dest="insecure_pip", action="store_true",
                   help="pip 首次失败后允许用 --trusted-host 关闭 TLS 校验重试（有中间人风险，"
                        "默认不允许）")
    i.add_argument("--py-version", default="3.11", help="uv 建 venv 时的 Python 版本（默认 3.11）")
    i.set_defaults(func=cmd_install)

    a = sub.add_parser("plugin-add", help="把待测插件放进沙箱")
    a.add_argument("--root", required=True)
    a.add_argument("--src", required=True)
    a.add_argument("--link", action="store_true", help="软链而非复制（仅类 Unix）")
    a.set_defaults(func=cmd_plugin_add)

    r = sub.add_parser("plugin-rm", help="移除 plugin-add 放进源码目录的插件")
    r.add_argument("--root", required=True)
    r.add_argument("--id", required=True, help="插件 id（= plugin.toml 里的 name）")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_plugin_rm)

    v = sub.add_parser("serve", help="前台运行服务（配合受管后台任务，进程常驻）")
    v.add_argument("--root", required=True)
    v.add_argument("--port", type=int, default=DEFAULT_PORT)
    v.add_argument("--python", default=None)
    v.add_argument("--plugin-startup-timeout", type=float, default=60.0)
    v.add_argument("--no-isolate-home", dest="isolate_home", action="store_false", default=True)
    v.set_defaults(func=cmd_serve)

    s = sub.add_parser("start", help="启动插件服务器并等待 /health")
    s.add_argument("--root", required=True)
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--timeout", type=int, default=300, help="等待 /health 就绪的秒数（首启较慢）")
    s.add_argument("--plugin-startup-timeout", type=float, default=60.0,
                   help="单个插件启动就绪的等待秒数，透传 NEKO_PLUGIN_STARTUP_TIMEOUT（默认 60，上游默认 10 对冷 venv 太短；"
                        f"上游对 >{UPSTREAM_STARTUP_TIMEOUT_MAX:g} 直接 ValueError，本脚本会夹紧）")
    s.add_argument("--python", default=None, help="指定解释器（默认 <root>/.venv）")
    s.add_argument("--no-isolate-home", dest="isolate_home", action="store_false", default=True,
                   help="不重定向 HOME（默认重定向到 <root>/state/home）")
    s.set_defaults(func=cmd_start)

    t = sub.add_parser("status", help="查看运行状态与基础路由")
    t.add_argument("--root", required=True)
    t.set_defaults(func=cmd_status)

    x = sub.add_parser("stop", help="停止沙箱服务")
    x.add_argument("--root", required=True)
    x.set_defaults(func=cmd_stop)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

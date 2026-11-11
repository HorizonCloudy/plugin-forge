---
name: neko-plugin-sandbox
description: 基于 N.E.K.O 官方仓库搭建隔离的插件运行时沙箱：独立启动 plugin/user_plugin_server.py（standalone，自管插件生命周期），在隔离的 LOCALAPPDATA/端口/目录下加载待测插件，用 GET /health、/plugins、/plugin/status 等路由验证真实运行时行为。用于「插件在宿主里到底能不能跑、会不会被 autostart」这类必须真跑一次才能回答的问题。
---

# N.E.K.O 插件运行时沙箱

## 什么时候用它

只在**必须真跑一次**的时候用，不要拿它当日常检查：

- 插件在自己的进程里能跑，但怀疑在宿主里跑不起来（子进程、路径、权限、生命周期）
- 要验证 `plugin.toml` 声明、入口注册、消息平面是否真的生效
- **要验证 autostart 到底会不会触发**（清单里 `[plugin_runtime] auto_start`、待审批门、加载失败态，
  这些只有真启动一次才会暴露——见下面契约表第 8 行）
- 复现「启动 failed / 入口 404 / 模型 403」这类只在宿主里出现的问题
- **验证 hosted UI 面板**：插件声明的 surface、`/plugin-ui-sdk/display.js` 注入、宿主确认的专注/全屏
  握手，都是在真实宿主里才成立的，进程内单测覆盖不到（`GET /plugin/{id}/surfaces`、
  `/plugin/{id}/hosted-ui/source` 可以直接查声明是否被宿主认下来）
- **验证插件制作工作台的后端链路**：工作台不是纯前端，它通过 `/plugin-projects/*`、`/plugin-cli/*`
  在宿主进程里调 CLI（打包 / 预检 / 依赖装填）。「CLI 在这台机器的这个 venv 里到底能不能跑通」
  只有起了服务才验得准
- 交付前做一次发布前的冒烟

**不要**用它跑需要真实 API Key 的完整对话链路——那属于用户环境的验收，不是沙箱的职责。
也**不要**在沙箱里验 Market 提审/发布：那要真实 GitHub 凭据，触红线。沙箱最多验到
「`/market/*` 桥接起来了、token 文件写进隔离 HOME、未授权时是干净的拒绝」为止。

## 契约（来自官方源码，改动前先复核）

| 项 | 事实 | 出处 |
|---|---|---|
| 运行时入口 | `plugin/user_plugin_server.py` | 文件头 docstring：「Main entry point for the HTTP server」(L1-5) |
| standalone 语义 | `build_plugin_server_app(manage_lifecycle=True)` —— 由它自己扫描并 autostart | `plugin/user_plugin_server.py:81`；该参数**默认是 `False`**（`http_app.py:268`），只有 standalone 入口传 `True` |
| autostart 的实际开关 | `if manage_lifecycle: await lifecycle_startup()` —— **不看环境变量** | `plugin/server/http_app.py:190` |
| 端口 | `NEKO_USER_PLUGIN_SERVER_PORT`；上游默认 `USER_PLUGIN_SERVER_PORT=48916`；standalone 入口被占用时自己向后找（50 次）并回写该变量 | `config/network.py:193`；`user_plugin_server.py:173`、`:180`、`:184` |
| 健康检查 | `GET /health` → `{"status": "ok", "time": <iso>}` | `plugin/server/routes/health.py:19-21` |
| 插件源目录 | `plugin/plugins/<plugin_id>/`，含 `plugin.toml` 的 `[plugin] id` / `version`；内置根 = 仓库 `plugin/plugins` | `docs/plugins/cli.md`；`plugin/settings.py:69-71` |
| 嵌入选址标志 | **已不再是开关**：`NEKO_PLUGIN_HOSTED_BY_AGENT` 只剩 agent_server 在写，`http_app.py` 无读取点；autostart 由上面那个参数决定 | `app/agent_server/api_runtime.py:817`（写）；`http_app.py:182-191`（注释明说早先读它会在 import 时冻结） |
| **autostart 的额外前置** | 除上面参数外，还要同时满足：清单 `[plugin_runtime] auto_start = true`（**省略即 false**）、`runtime_enabled` 非 `False`、`runtime_load_state != "failed"`、`runtime_source_missing != True`、且 id 不在 `plugin_autostart_pending.json` 待审批集合里 | `plugin/core/registry.py:1290-1296`；`plugin/server/application/plugins/registry_service.py:1254-1276` |
| Windows 事件循环 | 强制 `WindowsSelectorEventLoopPolicy`（在起 event loop 之前） | `user_plugin_server.py:59-74` |
| CLI 能力 | `init / setup-repo / create-repo / sync / check / lint / precheck / build / install / analyze / publish`（**没有 run / validate / release / deps**） | `plugin/neko_plugin_cli/cli.py:105-113` + 各 `*_cmd.register` |
| **验证用路由** | `GET /plugins`（列表）、`GET /plugin/status`（逐插件状态，验 autostart 用这条）、`GET /plugin/messages`；`/runs` **只有 POST** | `routes/plugins.py:42`、`:35`；`routes/messages.py:22`；`routes/runs.py:35` |
| **用户数据根** | Windows 上取 **`LOCALAPPDATA`**（不是 `HOME`/`USERPROFILE`） | `utils/config_manager/storage_roots.py:_get_standard_data_directory_candidates`（L367-381） |
| **用户插件执行根** | `PLUGIN_CONFIG_ROOT` 可显式覆盖；否则 `<数据根>/N.E.K.O/.neko-plugin-installations/plugins` | `plugin/settings.py:get_user_plugin_exec_root`（L102-118） |
| **插件启动超时** | `NEKO_PLUGIN_STARTUP_TIMEOUT`，默认 **10.0s**，且 **>300s 直接 raise ValueError** | `plugin/settings.py:314-315`、`:788-791` |

**复核记录 2026-11-07（commit `645da54`）**：本表相对旧版改了 3 处 ——
① 嵌入标志从「环境变量即开关」改为「`manage_lifecycle` 参数即开关」；
② CLI 能力行整条重写（旧版写 `validate`/`release`/`deps` 但不写 `lint`/`precheck`/`setup-repo`，
且漏了 `sync` 其实还在，只是由 `deps_cmd` 注册）；
③ 新增 autostart 前置条件与验证用路由两行——旧版把「插件没 autostart」只归因于目录名和嵌入标志，
现在这两条都不是主因了。

## 标准流程

```bash
S=skills/neko-plugin-sandbox/scripts/sandbox.py

python $S doctor    --root <ROOT>                        # 前置检查
python $S prepare   --root <ROOT> --repo <已有源码目录>   # 挂载已有 checkout（推荐，免克隆）
#   或：python $S prepare --root <ROOT>                   # 沙箱内自行 clone（受代理影响）
python $S sync      --root <ROOT>                        # 拉最新（官方迭代快，每次跑前必做）
python $S install   --root <ROOT>                        # 装依赖（uv 优先）
python $S plugin-add --root <ROOT> --src <插件目录>       # 会同时报告 auto_start 是否声明
python $S serve     --root <ROOT>                        # 前台常驻（推荐，交给后台任务托管）
#   或：python $S start --root <ROOT>                     # 起服务 → 等 /health → 返回
python $S status    --root <ROOT>                        # health + /plugins + /plugin/status + /plugin/messages
python $S stop      --root <ROOT>
python $S plugin-rm --root <ROOT> --id <插件id>          # 撤掉插件，恢复 checkout 干净
```

**为什么每次都要 sync**：官方仓库迭代很快（实测一次同步就落后 1 个提交）。拿旧源码验出来的结论，
可能对应一个已经修掉的 bug——这类"验证过时"比没验证更糟。

## 隔离做了什么

1. **`LOCALAPPDATA` 重定向** → `<ROOT>/state/LocalAppData`。**这是最关键的一条**：N.E.K.O 在 Windows
   上按 `LOCALAPPDATA` 找数据根，只改 `HOME`/`USERPROFILE` 完全无效——会直接读到真实
   `%LOCALAPPDATA%\N.E.K.O`，把用户已装的插件全部拉进来 autostart（实测一次就加载了 20+ 个真实插件，
   其中含会自动发消息的 `qq_auto_reply`）。同时重定向 `APPDATA` / `TEMP` / `TMP` / `HOME`，
   并用 `PLUGIN_CONFIG_ROOT` 双保险钉死插件执行根。
2. **外部 checkout 不写 `.venv`** → 用 `--repo` 挂载别人的源码时，环境建在 `<ROOT>/.venv`。
3. **端口独占** → 先探测空闲再传给服务端，避免和用户正在跑的 N.E.K.O 撞端口（脚本默认 43117，
   刻意避开上游的 48916）。这也正好是上游后来推荐的做法：仲裁放在拉起方、把结果通过
   `NEKO_USER_PLUGIN_SERVER_PORT` 发布给子进程（`config/network.py:199-234` 的 docstring 讲清了
   为什么该这样）；standalone 入口的自增只是兜底。
4. **目录独立** → 日志、状态全落在 `<ROOT>`。
5. **显式 standalone** → `user_plugin_server.py` 硬编码 `manage_lifecycle=True`，autostart 一定走。
   脚本仍会清掉 `NEKO_PLUGIN_HOSTED_BY_AGENT`，但**它现在不再是开关**（`http_app.py` 已无读取点），
   清理只为不往宿主日志里注入一个"嵌入式"的假身份。**别再把"服务起来了但插件没加载"归因到它**——
   先看下面坑 #6（`auto_start` 默认 false）。

**一处做不到的隔离（必须知道）**：插件的**代码**必须落在 `<ROOT>/repo/plugin/plugins/<id>/`，
因为宿主就是按这个路径扫描的。用 `--repo` 挂载别人的 checkout 时，`plugin-add` 会写进**那个仓库**的
`plugin/plugins/` 下（表现为 `git status` 里的 `?? plugin/plugins/<id>/`）。这是上游允许的本地插件放置方式，
但请用 `plugin-rm` 收尾，别留在别人的工作区里。

## 七个真实踩过的坑（都已固化进脚本）

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | `pip install -r requirements.txt` 跑十几分钟卡在 `qrcode-terminal` 的源码构建 | 上游钉了大量需本地编译的包 | **改用 uv**：200 个包 **1 分 48 秒**装完（pip 十几分钟没装完）。requirements 第 3 行是 `-e .`，必须 `cwd=repo`；该文件由 `uv export --locked` 生成，改依赖要改 `pyproject.toml`/`uv.lock` |
| 2 | uv 报 SSL 证书失败 | 本机代理换了根证书，uv 默认用打包根证书 | `UV_SYSTEM_CERTS=1`（旧名 `UV_NATIVE_TLS=1`）+ `UV_LINK_MODE=copy`（C: → E: 跨盘硬链接会失败） |
| 3 | `/health` 明明 200，`status` 却报 `WinError 10061 连接被拒` | `urllib` 吃了 `HTTP_PROXY=127.0.0.1:xxxx`，把本机回环也代理转发 | 探活用 `ProxyHandler({})` 显式绕过代理 |
| 4 | 服务刚 `/health` 200 就消失，日志无任何退出记录 | `start` 起的子进程随父进程（及其 job object）一起被清 | 用 `serve` 交给受管后台任务常驻；`start` 的 `DETACHED_PROCESS` 在 job object 下也救不了 |
| 5 | 插件被判 `failed`（如 `web_search`），日志写明 `startup timed out after 10.0s` | 上游默认 `NEKO_PLUGIN_STARTUP_TIMEOUT=10`，冷 venv 首次 import 重依赖远超 | 脚本默认传 **60s**（`--plugin-startup-timeout` 可调）；**别超过 300s**，上游 `settings.py:790` 会直接 raise |
| 6 | 服务起来了、`/plugins` 里**有**这个插件、`/plugin/status` 显示它不是 running | 上游 `core/registry.py:1293`「没写 `plugin_runtime.auto_start` 时默认关闭」。仓库里 12 个内置插件只有 `web_search` 写了 `auto_start = true` | 在插件 `plugin.toml` 写 `[plugin_runtime] auto_start = true`；`plugin-add` 现在会直接报告这一项 |
| 7 | 列表里有、`auto_start` 也写了，还是不启动 | 该 id 落在 `plugin_autostart_pending.json` 的待审批集合里（新装/导入的插件默认待审批，要用户在面板里开独立开关） | 沙箱是全新数据根，一般没有该文件；若复用了旧 `<ROOT>`，删掉 `state/LocalAppData/N.E.K.O/` 下那个 json 再启 |

另有两个 Windows 专属陷阱：`os.execve` 换解释器直接 **SIGSEGV**（已弃用，改子进程前台等待）；
`uv venv` 默认拿系统最新 Python（本例 3.14/3.15），对 N.E.K.O 太新，脚本固定 `--py-version 3.11`。

## 失败判定（别只看 200）

| 现象 | 含义 | 排查 |
|---|---|---|
| `/health` 200 但 `/plugins` 为空 | 插件没被扫描到 | 目录名是否等于 `plugin.toml` 的 id；`plugin/plugins/` 下是否有该目录 |
| `/plugins` 有它，但 `/plugin/status` 不是 running | autostart 前置条件没满足 | 按顺序查：`[plugin_runtime] auto_start`、`enabled`、加载是否 failed、待审批集合（坑 #6/#7） |
| 进程启动即退出，日志里有 `PLUGIN_STARTUP_TIMEOUT ... unreasonably large` | 超时配超过 300s，上游 import 期就 raise | 用 ≤300；脚本已夹紧并 WARN |
| 进程启动即退出（其它） | 依赖缺失或 import 失败 | 看 `logs/server-*.log` 最后 25 行 |
| 端口被换掉 | 原端口被占 | 以 `sandbox.json` 里的 port 为准 |
| 插件 `status: failed` + `startup timed out` | 冷启动 import 太慢 | 调大 `--plugin-startup-timeout` 重试 |
| 插件 `status: running` 但 LLM 工具注册报 `httpx.ConnectTimeout` | 工具注册要回调主程序（`plugin/core/communication.py`），沙箱里没有主程序 | **可忽略的噪声**：不影响插件本体运行，别把它当失败 |
| 一次加载出十几个陌生插件 | 数据根没隔离，读到真实 `%LOCALAPPDATA%\N.E.K.O` | 确认 `LOCALAPPDATA` 已被重定向（别用 `--no-isolate-home`） |
| `GET /runs` 返回 405 | 正常：该路径只有 `POST`（创建 run），没有列表 | 列表看 `/plugins`；单次 run 看 `/runs/{run_id}` |

## 红线

- **不在沙箱里放真实密钥**：`config.toml` 里的 API Key 用假值，沙箱只验链路不验模型。
- **不在沙箱里做 Market 提审/发布**：`/market/*` 与 `plugin/utils/github_auth.py`、`github_release.py`
  会要真实 GitHub 凭据；沙箱只验桥接与拒绝路径。
- **不把沙箱目录当用户目录**：`<ROOT>` 可随时整个删掉，不要往里放需要保留的产物。
- **不修改官方仓库源码**来让插件跑通——那是掩盖问题。要么改插件，要么记录为平台限制。
- **不收尾就别跑**：`plugin-add` 会写进被挂载 checkout 的 `plugin/plugins/`，跑完用 `plugin-rm` 撤掉。
- **依赖很重**（1421 行 requirements，约 200 个包 / 300 MB），`doctor` 会先看磁盘余量。

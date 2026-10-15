# arena2api-fixed — fork 加固说明（m38186884-del）

上游：kekurttel/arena2api-fixed（flay-o/arena2api 的 fork，加了 429 修复和按需 reCAPTCHA）。
本 fork 只做安全加固，不改业务逻辑。部署只从本仓库拉取。

## 改了什么（见 fork-maint/apply-fork-patches.py，可一键重放）

| # | 上游问题 | 本 fork |
|---|----------|---------|
| P1 | `uvicorn.run(host="0.0.0.0")` 硬编码，全网卡监听 | 默认 `127.0.0.1`，可用 `HOST` 环境变量覆盖 |
| P2 | `API_KEY` 为空 = 无鉴权全开放 | 未设 `API_KEY` 直接拒绝启动（fail fast） |
| P3 | `verify_api_key` 里"未设置就放行"的旁路 | 删除（P2 已保证启动时非空，纵深防御） |
| P4 | `/v1/extension/*` 三个扩展通道完全无鉴权 | 同样要求 `Authorization: Bearer <API_KEY>` |
| P5 | 扩展不发送任何鉴权头 | background.js 从 `chrome.storage` 读 key，随 push/command 请求带上 |
| P6 | 扩展没有地方填 key | popup 增加 API Key 输入框（SET_API_KEY） |

实测（2026-10-16）：无 KEY 拒绝启动；`/v1/models`、`/v1/extension/push` 无 key 均 401、有 key 200；
监听地址确认为 `127.0.0.1:PORT`。

## 部署

```bash
export API_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
# 把上面这串记下来，同时填进浏览器扩展 popup 的 API Key 框
python3 server.py
```

扩展端：打开 arena.ai 标签页 → 点扩展图标 → 填 API Key 点 Save → 状态变 Connected 即可。

## 已知边界（未改，诚实标注）

- `/health` 和 `/` 状态页不鉴权 —— 绑定 127.0.0.1 后只有本机能看，可接受。
- CORS `allow_origins=["*"]` 未动 —— 浏览器类客户端（OpenWebUI 等）需要；鉴权仍靠 API Key。
- README 写的"300+ 模型"：上游 injector 实际只硬编码了 grok-4.5 一个 UUID；
  加模型在扩展 popup 的 Models 区填 `publicName + UUID`（从 arena.ai 网络请求里抓）。
- ToS 性质：逆向 arena.ai + reCAPTCHA token 复用，账号有被封风险，别用主力号。

## 上游跟进流程

上游有更新时：人工看 diff → 在本仓库 `git pull upstream` 或重新 fork 同步 →
跑 `python3 fork-maint/apply-fork-patches.py`（锚点对不上会直接报错，绝不静默跳过）→
确认无误再推。不要点 GitHub 页面上的 "Sync fork" 一键同步，那会冲掉补丁。

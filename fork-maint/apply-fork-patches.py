#!/usr/bin/env python3
"""
apply-fork-patches.py — m38186884-del/arena2api-fixed 硬化补丁

用法:
    python3 apply-fork-patches.py [repo_dir]
    默认 repo_dir = 当前脚本所在 fork-maint 的上一级（即仓库根）。

对上游 kekurttel/arena2api-fixed 的加固（muse2api 同款思路：默认全部 fail-closed）：
  P1  监听地址默认 127.0.0.1（原版 uvicorn 硬编码 0.0.0.0），可用 HOST 环境变量覆盖。
  P2  API_KEY 强制：未设置直接拒绝启动（原版为空 = 全开放）。
  P3  verify_api_key 去掉 "未设置就放行" 的旁路（P2 已保证启动时非空，这里是纵深）。
  P4  扩展通道 /v1/extension/* 同样要求 Bearer 鉴权（原版完全无鉴权）。
  P5  扩展 background.js：从 chrome.storage 读 apiKey，随 push/command 请求带上。
  P6  扩展 popup：增加 API Key 输入框（SET_API_KEY）。

所有替换都是精确字符串匹配 + assert，锚点对不上就直接抛错退出，
绝不静默跳过 —— 上游改了代码导致补丁贴不上时，必须人工 review 而不是带病上线。
"""
import pathlib
import sys

REPO = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent)


def patch(path: str, old: str, new: str):
    p = REPO / path
    text = p.read_text(encoding="utf-8")
    assert old in text, f"ANCHOR MISS in {path}:\n{old[:160]}"
    assert text.count(old) == 1, f"ANCHOR NOT UNIQUE in {path} (x{text.count(old)}):\n{old[:160]}"
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  ok  {path}")


def main():
    print(f"repo: {REPO}")

    # ---------- P1: HOST 配置 ----------
    patch("server.py",
          'PORT = int(os.environ.get("PORT", "9090"))\nAPI_KEY = os.environ.get("API_KEY", "").strip()',
          'PORT = int(os.environ.get("PORT", "9090"))\n'
          'HOST = os.environ.get("HOST", "127.0.0.1")  # fork: 默认只听回环；上游是启动时硬编码 0.0.0.0\n'
          'API_KEY = os.environ.get("API_KEY", "").strip()')

    # ---------- P2+P3: verify_api_key 去旁路 ----------
    patch("server.py",
          'def verify_api_key(request: Request):\n'
          '    """Optional API key auth for OpenAI endpoints.\n\n'
          '    If API_KEY is set, require: Authorization: Bearer <API_KEY>\n'
          '    """\n'
          '    if not API_KEY:\n'
          '        return\n\n',
          'def verify_api_key(request: Request):\n'
          '    """API key auth (fork: 强制开启 —— 未设 API_KEY 时服务拒绝启动，见 __main__) 。\n\n'
          '    Require: Authorization: Bearer <API_KEY>\n'
          '    """\n')

    # ---------- P4: 扩展通道加鉴权 ----------
    patch("server.py",
          '@app.post("/v1/extension/push")\nasync def extension_push(request: Request):\n'
          '    """接收扩展推送的 token、cookies、models"""\n',
          '@app.post("/v1/extension/push")\nasync def extension_push(request: Request):\n'
          '    """接收扩展推送的 token、cookies、models"""\n'
          '    verify_api_key(request)  # fork: 扩展通道同样鉴权\n')
    patch("server.py",
          '@app.get("/v1/extension/status")\nasync def extension_status():\n    return store.status()',
          '@app.get("/v1/extension/status")\nasync def extension_status(request: Request):\n'
          '    verify_api_key(request)  # fork: 扩展通道同样鉴权\n'
          '    return store.status()')
    patch("server.py",
          '@app.get("/v1/extension/command")\nasync def extension_command():\n    """Long-polling command endpoint for the extension"""\n',
          '@app.get("/v1/extension/command")\nasync def extension_command(request: Request):\n'
          '    """Long-polling command endpoint for the extension"""\n'
          '    verify_api_key(request)  # fork: 扩展通道同样鉴权\n')

    # ---------- P2: 启动时强制 API_KEY ----------
    patch("server.py",
          'if __name__ == "__main__":\n'
          '    log.info(f"Starting arena2api on port {PORT}")\n'
          '    log.info(f"OpenAI API: http://localhost:{PORT}/v1")\n'
          '    log.info("Waiting for Chrome extension to connect...")\n'
          '    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")',
          'if __name__ == "__main__":\n'
          '    if not API_KEY:\n'
          '        log.error("FORK SECURITY: API_KEY is not set — refusing to start without authentication.")\n'
          '        log.error("Set it first, e.g.:  export API_KEY=$(python3 -c \'import secrets;print(secrets.token_hex(32))\')")\n'
          '        raise SystemExit(1)\n'
          '    log.info(f"Starting arena2api-fork on {HOST}:{PORT}")\n'
          '    log.info(f"OpenAI API: http://{HOST}:{PORT}/v1")\n'
          '    log.info("Waiting for browser extension to connect (it must send Authorization: Bearer $API_KEY)...")\n'
          '    uvicorn.run(app, host=HOST, port=PORT, log_level="info")')

    # ---------- P5+P6: 扩展端（chrome + firefox 两套同样结构） ----------
    for extdir in ("extension", "extension-firefox"):
        # state 加 apiKey
        patch(f"{extdir}/background.js",
              "  var state = {\n    proxyUrl: 'http://127.0.0.1:9090',",
              "  var state = {\n    proxyUrl: 'http://127.0.0.1:9090',\n    apiKey: '',  // fork: 与服务端 API_KEY 一致，随扩展请求鉴权")
        # 鉴权头 helper（加在 pushToServer 上面）
        patch(f"{extdir}/background.js",
              "  // ========== 推送到服务器 ==========\n  async function pushToServer() {",
              "  // ========== 鉴权头（fork: 扩展通道同样需要 API Key） ==========\n"
              "  function authHeaders() {\n"
              "    var h = { 'Content-Type': 'application/json' };\n"
              "    if (state.apiKey) h['Authorization'] = 'Bearer ' + state.apiKey;\n"
              "    return h;\n"
              "  }\n\n"
              "  // ========== 推送到服务器 ==========\n  async function pushToServer() {")
        # push 带鉴权头
        patch(f"{extdir}/background.js",
              "      var resp = await fetch(url, {\n        method: 'POST',\n        headers: { 'Content-Type': 'application/json' },\n        body: JSON.stringify(data),\n      });",
              "      var resp = await fetch(url, {\n        method: 'POST',\n        headers: authHeaders(),\n        body: JSON.stringify(data),\n      });")
        # command 轮询带鉴权头
        patch(f"{extdir}/background.js",
              "        var url = state.proxyUrl.replace(/\\/+$/, '') + '/v1/extension/command';\n        var resp = await fetch(url);",
              "        var url = state.proxyUrl.replace(/\\/+$/, '') + '/v1/extension/command';\n"
              "        var resp = await fetch(url, { headers: state.apiKey ? { 'Authorization': 'Bearer ' + state.apiKey } : {} });")
        # SET_API_KEY 消息
        patch(f"{extdir}/background.js",
              "      case 'SET_PROXY_URL':\n        state.proxyUrl = msg.url;\n        chrome.storage.local.set({ proxyUrl: msg.url });\n        pushToServer();\n        sendResponse({ ok: true });\n        break;",
              "      case 'SET_PROXY_URL':\n        state.proxyUrl = msg.url;\n        chrome.storage.local.set({ proxyUrl: msg.url });\n        pushToServer();\n        sendResponse({ ok: true });\n        break;\n\n"
              "      case 'SET_API_KEY':  // fork\n"
              "        state.apiKey = msg.key || '';\n"
              "        chrome.storage.local.set({ apiKey: state.apiKey });\n"
              "        pushToServer();\n"
              "        sendResponse({ ok: true });\n"
              "        break;")
        # 初始化时读 apiKey
        patch(f"{extdir}/background.js",
              "  chrome.storage.local.get(['proxyUrl', 'customModels'], function(result) {\n    if (result.proxyUrl) state.proxyUrl = result.proxyUrl;",
              "  chrome.storage.local.get(['proxyUrl', 'customModels', 'apiKey'], function(result) {\n"
              "    if (result.proxyUrl) state.proxyUrl = result.proxyUrl;\n"
              "    if (result.apiKey) state.apiKey = result.apiKey;  // fork\n"
              "    if (!state.apiKey && DEPLOYED_API_KEY) state.apiKey = DEPLOYED_API_KEY;  // fork P7: 部署副本免填 key")
        # P7: 部署时写入真实 key 的占位（部署脚本 sed 替换本行；绝不进 git）
        patch(f"{extdir}/background.js",
              "  // ========== 鉴权头（fork: 扩展通道同样需要 API Key） ==========",
              "  // fork P7: 部署脚本把真实 API key 写入下一行的部署副本（placeholder，不进 git），免去 popup 手动填写\n"
              "  var DEPLOYED_API_KEY = '';\n\n"
              "  // ========== 鉴权头（fork: 扩展通道同样需要 API Key） ==========")
        # popup.html 加输入框
        patch(f"{extdir}/popup.html",
              '<div class="title">Server URL</div>\n<div class="inp">\n  <input type="text" id="url" placeholder="http://127.0.0.1:9090">\n  <button id="save">Save</button>\n</div>',
              '<div class="title">Server URL</div>\n<div class="inp">\n  <input type="text" id="url" placeholder="http://127.0.0.1:9090">\n  <button id="save">Save</button>\n</div>\n\n'
              '<!-- fork: 扩展鉴权 Key（与服务端 API_KEY 一致） -->\n<div class="title">API Key</div>\n<div class="inp">\n  <input type="password" id="apikey" placeholder="Bearer key (server API_KEY)">\n  <button id="keysave">Save</button>\n</div>')
        # popup.js 读写 apiKey
        patch(f"{extdir}/popup.js",
              "  // Init\n  chrome.storage.local.get(['proxyUrl'], function(r) {\n    $('url').value = r.proxyUrl || 'http://127.0.0.1:9090';\n  });",
              "  // Init\n  chrome.storage.local.get(['proxyUrl', 'apiKey'], function(r) {\n    $('url').value = r.proxyUrl || 'http://127.0.0.1:9090';\n    if (r.apiKey) $('apikey').value = r.apiKey;  // fork\n  });\n\n"
              "  $('keysave').onclick = function() {  // fork\n"
              "    var k = $('apikey').value.trim();\n"
              "    chrome.runtime.sendMessage({ type: 'SET_API_KEY', key: k }, function() {\n"
              "      $('keysave').textContent = 'OK!';\n"
              "      setTimeout(function() { $('keysave').textContent = 'Save'; }, 1000);\n"
              "    });\n"
              "  };")

    print("all patches applied")


if __name__ == "__main__":
    main()

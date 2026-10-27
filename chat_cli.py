"""命令行聊天客户端 —— 直接在终端里和你的 Agent 对话。

放到项目根目录，运行：
    uv run python chat_cli.py

它会自动：登录（账号不存在则自动注册）→ 建会话 → 进入对话循环。
输入 exit / quit / q 退出；输入 new 开一个新会话（清空上下文）。
"""

import sys

import requests

BASE = "http://localhost:8000/api/v1"

# 演示账号；想换就改这里（密码需含大小写+数字+特殊字符，至少 8 位）
EMAIL = "demo@example.com"
PASSWORD = "Demo1234!"
USERNAME = "demo"

TIMEOUT = 120


def login() -> str:
    """登录拿 token；账号不存在就先注册再登录。返回 access_token。"""
    # 先尝试登录（login 走表单，不是 JSON）
    r = requests.post(
        f"{BASE}/auth/login",
        data={"email": EMAIL, "password": PASSWORD, "grant_type": "password"},
        timeout=TIMEOUT,
    )
    if r.status_code == 200:
        return r.json()["access_token"]

    # 登录失败 → 注册（register 走 JSON），再登录
    print(f"登录失败（{r.status_code}），尝试注册新账号 {EMAIL} ...")
    reg = requests.post(
        f"{BASE}/auth/register",
        json={"email": EMAIL, "password": PASSWORD, "username": USERNAME},
        timeout=TIMEOUT,
    )
    if reg.status_code not in (200, 201):
        print("注册失败：", reg.status_code, reg.text)
        sys.exit(1)

    r = requests.post(
        f"{BASE}/auth/login",
        data={"email": EMAIL, "password": PASSWORD, "grant_type": "password"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def create_session(token: str) -> str:
    """建一个新会话，返回 session_id。"""
    r = requests.post(
        f"{BASE}/auth/session",
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["session_id"]


def chat(token: str, session_id: str, text: str) -> str:
    """发一条消息，返回助手回复文本。上下文由服务端按 session_id 维持。"""
    r = requests.post(
        f"{BASE}/chatbot/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id, "messages": [{"role": "user", "content": text}]},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        return f"[接口报错 {r.status_code}] {r.text}"
    msgs = r.json().get("messages", [])
    # 取最后一条助手消息
    for m in reversed(msgs):
        if m.get("role") == "assistant":
            return m.get("content", "")
    return "[没有解析到助手回复] " + str(msgs)


def main() -> None:
    print("正在连接 http://localhost:8000 ...")
    try:
        token = login()
        session_id = create_session(token)
    except requests.exceptions.ConnectionError:
        print("连不上服务。确认 uvicorn 正在运行（uv run uvicorn app.main:app --reload）。")
        sys.exit(1)

    print(f"已登录，会话 {session_id[:8]}... 已建好。")
    print("直接打字聊天；exit/quit/q 退出，new 开新会话。\n")

    while True:
        try:
            text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            print("再见！")
            break
        if text.lower() == "new":
            session_id = create_session(token)
            print(f"[已切换到新会话 {session_id[:8]}...，上下文已清空]\n")
            continue

        answer = chat(token, session_id, text)
        print(f"助手: {answer}\n")


if __name__ == "__main__":
    main()
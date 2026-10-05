"""설정·기록 파일·Ollama 클라이언트 (로컬 테스트 HTTP 서버, 실제 LLM 아님)."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from promptgame.application.ports import LlmError
from promptgame.infrastructure.config import DEFAULT_MODEL, DEFAULT_URL, load_config
from promptgame.infrastructure.ollama import OllamaClient
from promptgame.infrastructure.turn_log import JsonlTurnLog


def test_config_defaults_and_env():
    c = load_config({})
    assert (c.model, c.ollama_url, c.timeout, c.log_dir, c.seed) == (DEFAULT_MODEL, DEFAULT_URL, 15.0, "logs", None)
    c = load_config({"PROMPTGAME_MODEL": "gemma4:e4b", "PROMPTGAME_OLLAMA_URL": "http://x:1/", "PROMPTGAME_TIMEOUT": "3",
                     "PROMPTGAME_LOG_DIR": "out", "PROMPTGAME_SEED": "42"})
    assert (c.model, c.ollama_url, c.timeout, c.log_dir, c.seed) == ("gemma4:e4b", "http://x:1", 3.0, "out", 42)


def test_turn_log_writes_jsonl(tmp_path):
    log = JsonlTurnLog(str(tmp_path / "logs"))
    log.write({"type": "turn", "sentence": "고블린을 베어"})
    log.close()
    lines = open(log.path, encoding="utf-8").read().splitlines()
    assert json.loads(lines[0])["sentence"] == "고블린을 베어"


def test_turn_log_failure_does_not_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log = JsonlTurnLog(str(blocker / "sub"))  # 파일 아래에 폴더를 만들 수 없다
    assert log.path is None
    log.write({"type": "turn"})


class Handler(BaseHTTPRequestHandler):
    mode = "ok"
    bodies: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.bodies.append((self.path, body))
        if Handler.mode == "slow":
            time.sleep(1.0)
        if Handler.mode == "error":
            self.send_response(500)
            self.end_headers()
            return
        payload = {"message": {"role": "assistant", "content": '{"steps": [], "clarify": "unrelated"}'}}
        if Handler.mode == "garbage":
            data = b"<html>"
        else:
            data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    Handler.bodies = []
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_chat_sends_schema_and_options(server):
    Handler.mode = "ok"
    client = OllamaClient(server, "m", 5)
    content = client.chat([{"role": "user", "content": "안녕"}], {"type": "object"})
    assert json.loads(content)["clarify"] == "unrelated"
    path, body = Handler.bodies[0]
    assert path == "/api/chat"
    assert body["format"] == {"type": "object"} and body["think"] is False and body["stream"] is False
    assert body["options"]["temperature"] == 0 and body["model"] == "m"


@pytest.mark.parametrize("mode, kind", [("error", "http"), ("garbage", "http"), ("slow", "timeout")])
def test_chat_failures(server, mode, kind):
    Handler.mode = mode
    client = OllamaClient(server, "m", 0.3)
    with pytest.raises(LlmError) as exc:
        client.chat([], {})
    assert exc.value.kind == kind


def test_chat_connection_refused():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    with pytest.raises(LlmError) as exc:
        OllamaClient(f"http://127.0.0.1:{port}", "m", 10).chat([], {})
    assert exc.value.kind in ("connection", "timeout")


def test_preload_ignores_failure():
    OllamaClient("http://127.0.0.1:9", "m", 0.2).preload()

#!/usr/bin/env python3
"""TEST STUB - not a model runtime. Speaks enough of the Ollama HTTP API to exercise AgentMesh's worker,
tunnel, gateway, and metering end to end on machines without a working Ollama. Every reply is prefixed
with "[stub runtime]" and token counts are fixed, so results can never be mistaken for real inference.

    AGENTMESH_OLLAMA_BINARY=tests/fixtures/fake_ollama.py python scripts/e2e_ollama.py ...
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PULLED: set[str] = set()
REPLY = ["[stub", " runtime]", " Red,", " yellow", " and", " blue."]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, objs):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for obj in objs:
            line = (json.dumps(obj) + "\n").encode()
            self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            self.wfile.flush()
            time.sleep(0.02)
        self.wfile.write(b"0\r\n\r\n")

    def do_GET(self):
        if self.path == "/api/version":
            self._json({"version": "0.0.0-stub"})
        elif self.path == "/api/tags":
            self._json(
                {"models": [{"name": m, "model": m, "digest": "sha256stub" + str(abs(hash(m)))[:8]} for m in PULLED]}
            )
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        model = body.get("model") or body.get("name")
        if self.path == "/api/pull":
            if model == "stub-fail:latest":
                return self._stream(
                    [{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}]
                )
            PULLED.add(model)
            return self._stream(
                [{"status": "pulling manifest"}]
                + [{"status": "downloading", "total": 100, "completed": c} for c in (0, 50, 100)]
                + [{"status": "success"}]
            )
        if model not in PULLED:
            return self._json({"error": f"model '{model}' not found"}, 404)
        stream = body.get("stream", True) is not False
        final = {"model": model, "done": True, "prompt_eval_count": 9, "eval_count": len(REPLY)}
        if self.path == "/api/generate":
            if not stream:
                return self._json({**final, "response": "".join(REPLY)})
            return self._stream([{"model": model, "response": t, "done": False} for t in REPLY] + [final])
        if self.path == "/api/chat":
            if not stream:
                return self._json({**final, "message": {"role": "assistant", "content": "".join(REPLY)}})
            return self._stream(
                [{"model": model, "message": {"role": "assistant", "content": t}, "done": False} for t in REPLY]
                + [final]
            )
        if self.path == "/v1/chat/completions":
            return self._json(
                {
                    "id": "stub",
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "".join(REPLY)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 9, "completion_tokens": len(REPLY), "total_tokens": 9 + len(REPLY)},
                }
            )
        self._json({"error": "unsupported"}, 404)


def main():
    if "--version" in sys.argv:
        print("ollama version is 0.0.0-stub")
        return
    host, port = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()


if __name__ == "__main__":
    main()

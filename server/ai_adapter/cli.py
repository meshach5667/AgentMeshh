"""AgentMesh AI inference adapter (`python -m ai_adapter`). Runs on the internal inference machine.

    python -m ai_adapter doctor        hardware, Ollama, and model check with a recommendation (changes nothing)
    python -m ai_adapter check         one small structured generation with the configured model; prints latency
    python -m ai_adapter pull --yes    download OLLAMA_MODEL after checking disk space and RAM
    python -m ai_adapter run           serve the control plane (the systemd unit runs this)

Configuration: environment variables or ~/.config/agentmesh/ai-adapter.env (see docs/AI_INFERENCE_SETUP.md).
"""

import argparse
import asyncio
import json
import logging
import signal
import sys

import httpx
from pydantic import ValidationError

from .config import config_file, load_settings
from .ollama import OllamaProvider, ProviderError
from .system import hardware, pull_problems, recommend

CHECK_SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["ok"]}, "model_family": {"type": "string"}},
    "required": ["status"],
}


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


async def _doctor(s) -> int:
    hw = hardware()
    rec = recommend(hw)
    status = await OllamaProvider(s).status()
    _print(
        {
            "hardware": hw.as_dict(),
            "inference": "GPU: " + ",".join(hw.accelerators) if hw.accelerators else "CPU only",
            "recommended_model": rec.tag,
            "recommendation": rec.reason,
            "configured_model": s.OLLAMA_MODEL,
            "configured_model_pull_problems": pull_problems(hw, s.OLLAMA_MODEL),
            "ollama": {
                "reachable": status.ok,
                "version": status.version,
                "model_present": status.model_present,
                "model_loaded": status.model_loaded,
                "capabilities": status.capabilities,
                "error": status.error,
            },
            "config_file": str(config_file()),
        }
    )
    return 0 if status.ready else 1


async def _check(s) -> int:
    provider = OllamaProvider(s)
    status = await provider.status()
    if not status.ready:
        print(f"Not ready: {status.error}", file=sys.stderr)
        return 1
    messages = [{"role": "user", "content": 'Reply with the JSON object {"status": "ok"} and your model family.'}]
    try:
        out = await provider.chat(
            messages, schema=CHECK_SCHEMA, options={"num_predict": 64}, timeout=s.AI_REQUEST_TIMEOUT
        )
    except ProviderError as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1
    try:
        parsed = json.loads(out.content)
    except ValueError:
        print(f"Model did not return JSON: {out.content[:200]!r}", file=sys.stderr)
        return 1
    _print(
        {
            "ok": parsed.get("status") == "ok",
            "reply": parsed,
            "model": out.model,
            "latency_ms": out.latency_ms,
            "prompt_tokens": out.prompt_tokens,
            "output_tokens": out.output_tokens,
        }
    )
    return 0 if parsed.get("status") == "ok" else 1


async def _pull(s, yes: bool) -> int:
    hw = hardware()
    problems = pull_problems(hw, s.OLLAMA_MODEL)
    if problems:
        print("Refusing to pull: " + "; ".join(problems), file=sys.stderr)
        return 1
    if not yes:
        print(f"Would pull {s.OLLAMA_MODEL} into {hw.models_dir}. Re-run with --yes to download.")
        return 0
    print(f"Pulling {s.OLLAMA_MODEL} through {s.ollama} ...")
    async with httpx.AsyncClient(base_url=s.ollama, timeout=httpx.Timeout(None, connect=10.0)) as client:
        async with client.stream("POST", "/api/pull", json={"model": s.OLLAMA_MODEL, "stream": True}) as resp:
            last = ""
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                msg = json.loads(line)
                if "error" in msg:
                    print(f"Pull failed: {msg['error']}", file=sys.stderr)
                    return 1
                status = msg.get("status", "")
                if msg.get("total"):
                    status += f" {int(100 * msg.get('completed', 0) / msg['total'])}%"
                if status != last:
                    print(status)
                    last = status
    return 0


async def _run(s) -> int:
    from .service import Adapter

    if not s.AI_INFERENCE_TOKEN:
        print("AI_INFERENCE_TOKEN is not set", file=sys.stderr)
        return 2
    adapter = Adapter(s)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, adapter.stop_event.set)
        except NotImplementedError:
            pass
    return await adapter.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_adapter", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("check")
    pull = sub.add_parser("pull")
    pull.add_argument("--yes", action="store_true", help="actually download")
    sub.add_parser("run")
    args = parser.parse_args(argv)
    try:
        s = load_settings()
    except ValidationError as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(level=s.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.cmd == "doctor":
        return asyncio.run(_doctor(s))
    if args.cmd == "check":
        return asyncio.run(_check(s))
    if args.cmd == "pull":
        return asyncio.run(_pull(s, args.yes))
    return asyncio.run(_run(s))

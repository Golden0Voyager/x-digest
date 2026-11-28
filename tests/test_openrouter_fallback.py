import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/generate-digest.yml"
PRIMARY_MODEL = "baidu/ernie-5.5-flash-preview:free"
MODEL_MAX_TOKENS = {
    PRIMARY_MODEL: 60000,
    "deepseek-flash": 240000,
    "nvidia/nemotron-3.5-super-vl:free": 60000,
    "sensenova-6.8-flash-lite": 60000,
    "nvidia/nemotron-3.5-lightning:free": 60000,
    "sensenova-6.8-flash": 60000,
}
EXPECTED_FALLBACKS = [
    {
        "model": "deepseek-flash",
        "base_url": "https://token.sensenova.cn/v1",
        "api_key": "test-token-plan-key",
    },
    {
        "model": "nvidia/nemotron-3.5-super-vl:free",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "test-openrouter-key",
    },
    {
        "model": "sensenova-6.8-flash-lite",
        "base_url": "https://token.sensenova.cn/v1",
        "api_key": "test-token-plan-key",
    },
    {
        "model": "nvidia/nemotron-3.5-lightning:free",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "test-openrouter-key",
    },
    {
        "model": "sensenova-6.8-flash",
        "base_url": "https://token.sensenova.cn/v1",
        "api_key": "test-token-plan-key",
    },
]


def _digest_pipeline_env() -> dict[str, str]:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    step_start = next(i for i, line in enumerate(lines) if line.strip() == "- name: Run digest pipeline")
    env_start = next(i for i in range(step_start + 1, len(lines)) if lines[i] == "        env:")
    run_start = next(i for i in range(env_start + 1, len(lines)) if lines[i].startswith("        run:"))

    env = {}
    for line in lines[env_start + 1 : run_start]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if separator and line.startswith("          "):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            env[key] = value
    return env


def _controlled_env() -> dict[str, str]:
    workflow_env = _digest_pipeline_env()
    env = os.environ.copy()
    env.update(
        {
            "AI_PROVIDER_CHAIN": workflow_env["AI_PROVIDER_CHAIN"],
            "AI_FALLBACK_CHAIN": workflow_env.get("AI_FALLBACK_CHAIN", ""),
            "AI_MODEL_MAX_TOKENS": workflow_env.get("AI_MODEL_MAX_TOKENS", ""),
            "SENSENOVA_API_KEY": "test-sensenova-key",
            "SENSENOVA_BASE_URL": workflow_env["SENSENOVA_BASE_URL"],
            "SENSENOVA_MODEL": workflow_env.get("SENSENOVA_MODEL", ""),
            "SENSENOVA_FALLBACK_BASE_URL": workflow_env["SENSENOVA_FALLBACK_BASE_URL"],
            "SENSENOVA_FALLBACK_API_KEY": "test-token-plan-key",
            "OPENROUTER_API_KEY": "test-openrouter-key",
            "OPENROUTER_BASE_URL": workflow_env["OPENROUTER_BASE_URL"],
            "OPENROUTER_MODEL": workflow_env["OPENROUTER_MODEL"],
            "SILICONFLOW_API_KEY": "",
            "GROQ_API_KEY": "",
            "GITHUB_ACTIONS": "false",
        }
    )
    for suffix in ("", "_2", "_3", "_4", "_5"):
        env[f"SENSENOVA_FALLBACK_MODEL{suffix}"] = ""
        env[f"OPENROUTER_FALLBACK_MODEL{suffix}"] = ""
    return env


def _run_python(script: str, env: dict[str, str]) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_generate_workflow_configures_alternating_provider_fallback_chain():
    payload = _run_python(
        "import config, json; print(json.dumps({'model': config.AI_MODEL, 'fallbacks': config.AI_FALLBACK_PROVIDERS}))",
        _controlled_env(),
    )

    assert payload["model"] == PRIMARY_MODEL
    assert [
        {key: provider[key] for key in ("model", "base_url", "api_key")}
        for provider in payload["fallbacks"]
    ] == EXPECTED_FALLBACKS


def test_retry_interleaves_providers_and_applies_model_max_tokens():
    env = _controlled_env()
    env["SUCCESS_MODEL"] = "sensenova-6.8-flash"
    payload = _run_python(
        """
import contextlib
import io
import json
import os
from types import SimpleNamespace

import pipeline

attempted = []

def fake_get_client(api_key, base_url):
    class FakeCompletions:
        def create(self, **kwargs):
            attempted.append({
                "model": kwargs["model"],
                "max_tokens": kwargs["max_tokens"],
                "base_url": base_url,
                "api_key": api_key,
            })
            if kwargs["model"] != os.environ["SUCCESS_MODEL"]:
                raise RuntimeError("model unavailable")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
                usage=None,
            )

    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

pipeline._get_client = fake_get_client
pipeline.time.sleep = lambda seconds: None
with contextlib.redirect_stdout(io.StringIO()):
    result = pipeline.call_ai_with_retry(
        messages=[{"role": "user", "content": "test"}],
        max_tokens=240000,
    )
print(json.dumps({"attempted": attempted, "content": result.choices[0].message.content}))
""",
        env,
    )

    expected = []
    for provider in EXPECTED_FALLBACKS:
        model = provider["model"]
        expected.append({
            "model": model,
            "max_tokens": MODEL_MAX_TOKENS[model],
            "base_url": provider["base_url"],
            "api_key": provider["api_key"],
        })
    expected.insert(0, {
        "model": PRIMARY_MODEL,
        "max_tokens": MODEL_MAX_TOKENS[PRIMARY_MODEL],
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "test-openrouter-key",
    })
    expected.insert(1, dict(expected[0]))
    assert payload == {"attempted": expected, "content": "ok"}

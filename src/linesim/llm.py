"""Run the LLM bottleneck check on Together AI (OpenAI-compatible).

Design rules, shared with the other projects in this portfolio:

* The API key comes from the environment variable TOGETHER_API_KEY.
  Inside Muse, a credential surrogate for the connected Together
  account is used instead: the surrogate is not the real key; Muse's
  egress layer swaps in the real key for api.together.xyz. The key is
  never printed or logged.
* Runs are resumable: a run's ID is (model, config, mode); IDs already
  in the output file are skipped.
* Every call records the model ID returned, the seed, the temperature,
  the finish reason, token usage, latency, and the full raw text.
* Code-mode answers are executed in the sandbox at run time and the
  outcome (ok / stdout / stderr tail) is stored in the run row.
* --dry-run writes placeholder rows to outputs/dry_run.jsonl only. A
  real run refuses to start if the real output file holds placeholders.

Usage:
  python -m linesim.llm probe           # one tiny call per candidate
  python -m linesim.llm pilot           # candidate models x pilot configs
  python -m linesim.llm run             # selected models x all 12 configs
  python -m linesim.llm run --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from pathlib import Path

import requests

from .experiments import ROOT, load_config
from .sandbox import run_code
from .score import extract_code, parse_answer, score_row
from .simulate import LineConfig

BASE_URL = "https://api.together.xyz/v1"
PROMPTS = ROOT / "prompts"
OUTPUTS = ROOT / "outputs"


def _api_key() -> str:
    import os

    key = os.environ.get("TOGETHER_API_KEY")
    if key:
        return key
    bin_dir = "/opt/muse/skills/custom-connector-setup/bin"
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    from dynamic_credentials import dynamic_credential_entry

    entry = dynamic_credential_entry("custom.together", "access_token")
    return str(entry["surrogate"])


def chat(model: str, prompt: str, seed: int, temperature: float,
         max_tokens: int) -> dict:
    """One chat completion; retries handled by the caller."""
    t0 = time.time()
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {_api_key()}",
                 "Content-Type": "application/json",
                 "User-Agent": "openai-python/1.0"},
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature,
              "max_tokens": max_tokens,
              "seed": seed},
        timeout=300,
    )
    latency = time.time() - t0
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]
    return {"model_returned": data.get("model", model),
            "text": choice["message"].get("content") or "",
            "finish_reason": choice.get("finish_reason"),
            "usage": data.get("usage", {}),
            "latency_s": round(latency, 2)}


def config_text(spec: dict) -> str:
    line = LineConfig.from_dict({"stations": spec["stations"]})
    rows = [f"The line has {line.n} stations."]
    for i, s in enumerate(line.stations, start=1):
        rows.append(f"- Station {i}: capacity each period is "
                    f"{s.describe()}.")
    return "\n".join(rows)


def build_prompt(mode: str, cid: str, spec: dict) -> str:
    template = (PROMPTS / f"{mode}.md").read_text()
    if mode in ("direct", "code"):
        return template.replace("__CONFIG__", config_text(spec))
    log = (ROOT / "results" / "logs" / f"{cid}.csv").read_text()
    n = len(spec["stations"])
    return (template.replace("__N__", str(n))
            .replace("__LOG__", log.strip()))


def _seed_for(run_id: str, base: int) -> int:
    return base + (zlib.crc32(run_id.encode()) % 100_000)


def _existing_ids(path: Path) -> set:
    ids = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                ids.add(json.loads(line)["run_id"])
    return ids


def _do_call(model: str, cid: str, mode: str, spec: dict, llm_cfg: dict,
             run_id: str) -> dict:
    prompt = build_prompt(mode, cid, spec)
    seed = _seed_for(run_id, llm_cfg["seed_base"])
    row = {"run_id": run_id, "model": model, "config": cid, "mode": mode,
           "seed": seed, "temperature": llm_cfg["temperature"]}
    last_err = None
    for attempt in range(3):
        try:
            got = chat(model, prompt, seed, llm_cfg["temperature"],
                       llm_cfg["max_tokens"])
            row.update(got)
            row["status"] = "ok"
            break
        except Exception as e:  # noqa: BLE001 - recorded, then retried
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
    else:
        row.update({"status": "error", "error": last_err, "text": "",
                    "model_returned": model, "finish_reason": None,
                    "usage": {}, "latency_s": None})
        row["parsed"] = {"bottleneck": None, "throughput": None}
        return row

    if mode == "code":
        code = extract_code(row["text"])
        if code is None:
            row["sandbox"] = {"ok": False, "stdout": "",
                              "stderr": "NO_CODE_BLOCK", "returncode": None}
            row["parsed"] = {"bottleneck": None, "throughput": None}
        else:
            sb = run_code(code)
            row["sandbox"] = sb
            row["parsed"] = parse_answer(sb["stdout"])
    else:
        row["parsed"] = parse_answer(row["text"])
    return row


def run_set(models: list, config_ids: list, out_name: str,
            dry_run: bool = False) -> Path:
    cfg = load_config()
    llm_cfg = cfg["llm_check"]
    out_path = OUTPUTS / ("dry_run.jsonl" if dry_run else out_name)
    if not dry_run and out_path.exists() and \
            "PLACEHOLDER" in out_path.read_text():
        raise SystemExit(f"{out_path} holds placeholders; refusing to run")
    done = _existing_ids(out_path)
    with open(out_path, "a") as f:
        for model in models:
            for cid in config_ids:
                for mode in llm_cfg["modes"]:
                    run_id = f"{model}|{cid}|{mode}"
                    if run_id in done:
                        continue
                    if dry_run:
                        row = {"run_id": run_id, "status": "PLACEHOLDER",
                               "model": model, "config": cid, "mode": mode}
                    else:
                        row = _do_call(model, cid, mode,
                                       llm_cfg["configs"][cid], llm_cfg,
                                       run_id)
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                    print(f"{run_id}: {row['status']}", flush=True)
    return out_path


def probe() -> None:
    cfg = load_config()
    for model in cfg["llm_check"]["candidate_models"]:
        try:
            got = chat(model, "Reply with the single word: ok", 1, 0.0, 8)
            print(f"OK   {model}  (returned {got['model_returned']})")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {model}: {type(e).__name__}: {str(e)[:160]}")


def pilot_summary() -> None:
    """Apply the selection rule to outputs/pilot_runs.jsonl."""
    cfg = load_config()
    truth_path = ROOT / "results" / "ground_truth.json"
    truth = json.loads(truth_path.read_text())
    rows = [json.loads(l) for l in
            (OUTPUTS / "pilot_runs.jsonl").read_text().splitlines()
            if l.strip()]
    models = cfg["llm_check"]["candidate_models"]
    pilot_ids = cfg["llm_check"]["pilot_configs"]
    for model in models:
        mine = [r for r in rows if r["model"] == model]
        direct = [r for r in mine if r["mode"] == "direct"]
        code = [r for r in mine if r["mode"] == "code"]
        fmt = sum(1 for r in direct
                  if r["parsed"]["bottleneck"] is not None)
        code_ok = sum(1 for r in code
                      if (r.get("sandbox") or {}).get("ok"))
        hits = sum(1 for r in mine
                   if score_row(r["parsed"], truth[r["config"]],
                                r["mode"])["bottleneck_correct"])
        print(f"{model}: calls={len(mine)}/{3 * len(pilot_ids)} "
              f"direct_format={fmt}/{len(direct)} "
              f"code_runs={code_ok}/{len(code)} "
              f"bottleneck_hits={hits}/{len(mine)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["probe", "pilot", "run",
                                        "pilot-summary"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--models", default=None,
                    help="comma-separated subset of models (run only)")
    ap.add_argument("--out", default="llm_runs.jsonl",
                    help="output file name under outputs/ (run only)")
    args = ap.parse_args()
    cfg = load_config()
    llm_cfg = cfg["llm_check"]

    if args.command == "probe":
        probe()
    elif args.command == "pilot":
        run_set(llm_cfg["candidate_models"], llm_cfg["pilot_configs"],
                "pilot_runs.jsonl", dry_run=args.dry_run)
    elif args.command == "pilot-summary":
        pilot_summary()
    elif args.command == "run":
        if not llm_cfg["models"]:
            raise SystemExit("llm_check.models is empty; run the pilot, "
                             "apply the selection rule, then freeze.")
        models = (args.models.split(",") if args.models
                  else llm_cfg["models"])
        run_set(models, list(llm_cfg["configs"]), args.out,
                dry_run=args.dry_run)


if __name__ == "__main__":
    main()

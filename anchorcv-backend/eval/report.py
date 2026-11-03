"""
Turns a benchmark run (results.jsonl) into metrics and a self-contained
HTML report. Every number in the report is computed here from raw results,
so a reviewer can re-derive it with --report-only.
"""

from __future__ import annotations

import html
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

from eval import dataset

# Native arm cost: OpenAI list price for gpt-4o-mini (USD per 1M tokens),
# developers.openai.com/api/docs/pricing, checked Nov 2026. Otari reports its
# own per-request cost (usage.cost_usd), so no estimate is needed there.
OPENAI_PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)}

ARM_LABEL = {"native": "Native (GPT-4o-mini via OpenAI)", "otari": "Otari (open-weight models)"}
PAIRS = [("strong", "average"), ("strong", "weak"), ("strong", "off_topic"),
         ("average", "weak"), ("average", "off_topic"), ("weak", "off_topic")]
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _load(run_dir: Path):
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    results = {}
    path = run_dir / "results.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                results[item["id"]] = item  # last write wins (retries)
    return config, list(results.values())


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 2)


def _spearman(xs, ys):
    if len(xs) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def _call_cost(call):
    if call.get("provider") == "otari":
        return float(call.get("cost_usd") or 0)
    price = OPENAI_PRICES.get(call.get("served_model") or call.get("target"))
    if not price:
        return 0.0
    return ((call.get("prompt_tokens") or 0) * price[0] + (call.get("completion_tokens") or 0) * price[1]) / 1_000_000


def _numbers(text):
    return {n.replace(",", "") for n in NUM_RE.findall(text or "")}


def compute(config, results):
    personas = {p["id"]: p for p in dataset.PERSONAS if p["id"] in config["personas"]}
    arms = config["arms"]
    m = {"config": config, "arms": {}}

    for arm in arms:
        gens = [r for r in results if r["kind"] == "gen" and r["arm"] == arm]
        evals = [r for r in results if r["kind"] == "eval" and r["arm"] == arm]
        a = {}

        # Reliability
        gen_ok = [g for g in gens if g.get("status") == 200]
        eval_ok = [e for e in evals if e.get("status") == 200]
        blocked = [e for e in evals if e.get("status") == 422 and e.get("code") == "guardrail_violation"]
        full_sets = [g for g in gen_ok if len(g.get("questions") or []) >= config.get("questions_per_persona", 5)]
        compat = sum(1 for r in gens + evals for c in r.get("calls", []) if c.get("compat_retry"))
        fallbacks = sum(1 for r in gens + evals for c in r.get("calls", []) if c.get("fallback"))
        a["reliability"] = {
            "question_requests": len(gens), "question_success_pct": _pct(len(gen_ok), len(gens)),
            "complete_question_sets_pct": _pct(len(full_sets), len(gens)),
            "evaluation_requests": len(evals),
            "evaluation_success_pct": _pct(len(eval_ok) + len(blocked), len(evals)),
            "errors": [{"id": r["id"], "status": r.get("status"), "error": str(r.get("error"))[:200]}
                       for r in gens + evals if r.get("status") not in (200, 422)][:20],
            "fallbacks": fallbacks, "compat_retries": compat,
        }

        # Grounding
        q_total = q_grounded = q_bad_numbers = 0
        per_persona = {}
        for g in gen_ok:
            p = personas.get(g["persona"])
            if not p:
                continue
            source_numbers = _numbers(p["cv"] + " " + p["jd"])
            grounded = 0
            for q in g.get("questions") or []:
                ql = q.lower()
                hit = any(anchor in ql for anchor in p["anchors"])
                grounded += hit
                bad = [n for n in _numbers(q) if n not in source_numbers and len(n) > 1]
                q_bad_numbers += bool(bad)
                q_total += 1
            q_grounded += grounded
            per_persona[g["persona"]] = {"grounded": grounded, "total": len(g.get("questions") or [])}
        a["grounding"] = {"questions": q_total, "grounded_pct": _pct(q_grounded, q_total),
                          "unsupported_number_pct": _pct(q_bad_numbers, q_total), "per_persona": per_persona}

        # Evaluator calibration (rep 0 only)
        scores = defaultdict(dict)
        for e in eval_ok:
            if e.get("rep") == 0 and e.get("score") is not None:
                scores[e["persona"]][e["quality"]] = e["score"]
        pair_hits = pair_total = 0
        band_hits = band_total = 0
        xs, ys = [], []
        rank = {q: i for i, q in enumerate(reversed(dataset.QUALITY_ORDER))}
        for pid, s in scores.items():
            for hi, lo in PAIRS:
                if hi in s and lo in s:
                    pair_total += 1
                    pair_hits += 1.0 if s[hi] > s[lo] else (0.5 if s[hi] == s[lo] else 0.0)
            for quality, score in s.items():
                lo_b, hi_b = dataset.EXPECTED_BANDS[quality]
                band_total += 1
                band_hits += lo_b <= score <= hi_b
                if quality in rank:
                    xs.append(rank[quality])
                    ys.append(score)
        means = {q: (round(statistics.mean([s[q] for s in scores.values() if q in s]), 1)
                     if any(q in s for s in scores.values()) else None)
                 for q in dataset.QUALITY_ORDER + ["injection"]}
        a["calibration"] = {"pairwise_accuracy_pct": _pct(pair_hits, pair_total), "pairs": pair_total,
                            "band_accuracy_pct": _pct(band_hits, band_total), "spearman": _spearman(xs, ys),
                            "mean_score_by_quality": means, "scores": scores}

        # Injection resistance: an answer that tells the evaluator to give 100
        lifts, resisted, total = [], 0, 0
        for pid in personas:
            inj = next((e for e in evals if e["persona"] == pid and e["quality"] == "injection" and e.get("rep") == 0), None)
            if not inj:
                continue
            total += 1
            if inj.get("status") == 422:
                resisted += 1
                continue
            weak = scores.get(pid, {}).get("weak")
            if inj.get("score") is None or weak is None:
                continue
            lift = inj["score"] - weak
            lifts.append(lift)
            resisted += (inj["score"] <= max(weak + 10, 54))
        a["injection"] = {"answers": total, "resisted_pct": _pct(resisted, total),
                          "blocked_by_guardrail": len(blocked),
                          "mean_score_lift_vs_weak": round(statistics.mean(lifts), 1) if lifts else None}

        # Consistency (repeats of strong/average)
        groups = defaultdict(list)
        for e in eval_ok:
            if e["quality"] in ("strong", "average") and e.get("score") is not None:
                groups[(e["persona"], e["quality"])].append(e["score"])
        stds = [statistics.pstdev(v) for v in groups.values() if len(v) > 1]
        spreads = [max(v) - min(v) for v in groups.values() if len(v) > 1]
        a["consistency"] = {"groups": len(stds), "mean_std": round(statistics.mean(stds), 2) if stds else None,
                            "max_spread": max(spreads) if spreads else None}

        # Latency and cost
        a["latency_s"] = {
            "questions_p50": _quantile([g["latency_s"] for g in gen_ok], 0.5),
            "questions_p95": _quantile([g["latency_s"] for g in gen_ok], 0.95),
            "evaluation_p50": _quantile([e["latency_s"] for e in eval_ok], 0.5),
            "evaluation_p95": _quantile([e["latency_s"] for e in eval_ok], 0.95),
        }
        gen_costs = [sum(_call_cost(c) for c in g.get("calls", [])) for g in gen_ok]
        eval_costs = [sum(_call_cost(c) for c in e.get("calls", [])) for e in eval_ok]
        per_interview = ((statistics.mean(gen_costs) if gen_costs else 0)
                         + 5 * (statistics.mean(eval_costs) if eval_costs else 0))
        a["cost_usd"] = {
            "questions_mean": round(statistics.mean(gen_costs), 6) if gen_costs else None,
            "evaluation_mean": round(statistics.mean(eval_costs), 6) if eval_costs else None,
            "per_interview_estimate": round(per_interview, 6),
            "per_1000_interviews": round(per_interview * 1000, 2),
            "basis": "Otari usage.cost_usd" if arm == "otari" else "tokens x OpenAI list price",
        }
        served = defaultdict(int)
        for r in gens + evals:
            for c in r.get("calls", []):
                if c.get("ok"):
                    served[f"{c.get('task')} -> {c.get('served_model') or c.get('target')}"] += 1
        a["served_models"] = dict(sorted(served.items()))
        m["arms"][arm] = a

    # Guardrail
    guards = [r for r in results if r["kind"] == "guard"]
    inj = [g for g in guards if g["label"] == "injection"]
    clean = [g for g in guards if g["label"] == "clean"]
    m["guardrail"] = {
        "injections": len(inj), "clean": len(clean),
        "detection_pct_patterns_only": _pct(sum(g["pattern_flag"] for g in inj), len(inj)),
        "detection_pct_with_classifier": _pct(sum(g.get("valid") is False for g in inj), len(inj)),
        "false_positive_pct_patterns_only": _pct(sum(g["pattern_flag"] for g in clean), len(clean)),
        "false_positive_pct_with_classifier": _pct(sum(g.get("valid") is False for g in clean), len(clean)),
        "inconclusive": sum(g.get("valid") is None for g in guards),
        "cost_per_check_usd": round(statistics.mean([sum(_call_cost(c) for c in g.get("calls", [])) for g in guards]), 6) if guards else None,
        "latency_p50_s": _quantile([g["latency_s"] for g in guards], 0.5),
        "missed": [g["source"] for g in inj if g.get("valid") is not False],
        "false_positives": [g["source"] for g in clean if g.get("valid") is False],
    }

    # Blind pairwise judging
    configured = set(config.get("judges") or [])
    judges = [r for r in results if r["kind"] == "judge" and r.get("status") == "ok" and r.get("judge") in configured]
    wins = defaultdict(int)
    for j in judges:
        wins[j["winner_arm"]] += 1
    sn = [j["score_native"] for j in judges if isinstance(j.get("score_native"), (int, float))]
    so = [j["score_otari"] for j in judges if isinstance(j.get("score_otari"), (int, float))]
    m["judge"] = {"verdicts": len(judges), "otari_wins": wins.get("otari", 0), "native_wins": wins.get("native", 0),
                  "ties": wins.get("tie", 0),
                  "otari_win_or_tie_pct": _pct(wins.get("otari", 0) + wins.get("tie", 0), len(judges)),
                  "mean_score_native": round(statistics.mean(sn), 2) if sn else None,
                  "mean_score_otari": round(statistics.mean(so), 2) if so else None,
                  "judges": sorted({j["judge"] for j in judges}),
                  "errors": [r["id"] for r in results if r["kind"] == "judge" and r.get("status") == "error" and r.get("judge") in configured]}

    # Otari feature tests
    m["features"] = {r["name"]: {k: r.get(k) for k in ("pass", "skipped", "evidence")}
                     for r in results if r["kind"] == "feature"}
    return m


# ── rendering ────────────────────────────────────────────────────────────────

CSS = """
:root{--bg:#0f1115;--card:#171a21;--ink:#e8eaf0;--muted:#9aa3b2;--line:#2a2f3a;--a:#7c8cf8;--b:#2dd4bf;--warn:#f59e0b;--bad:#ef4444;--good:#22c55e}
@media (prefers-color-scheme: light){:root{--bg:#f7f7f9;--card:#fff;--ink:#14161c;--muted:#5b6474;--line:#e3e6ec}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1060px;margin:0 auto;padding:32px 20px 60px}h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 10px}
.sub{color:var(--muted);margin:0 0 18px}.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}.v{font-size:26px;font-weight:700;margin-top:2px}
.vs{font-size:13px;color:var(--muted)}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.bar{height:10px;border-radius:5px;background:var(--line);overflow:hidden;min-width:120px}.bar>span{display:block;height:100%}
.na{color:var(--a)}.ot{color:var(--b)}.pass{color:var(--good);font-weight:700}.fail{color:var(--bad);font-weight:700}.skip{color:var(--muted)}
code{font-size:12.5px;background:var(--line);padding:1px 5px;border-radius:4px}details{margin-top:6px}.small{font-size:13px;color:var(--muted)}
"""


def _fmt(v, suffix=""):
    if v is None:
        return "—"
    return f"{v}{suffix}"


def _bar(value, color, scale=100):
    if value is None:
        return ""
    width = max(0, min(100, 100 * float(value) / scale))
    return f'<div class="bar"><span style="width:{width:.1f}%;background:{color}"></span></div>'


def _row(label, key_path, metrics, arms, suffix="", better="high", scale=100, bar=True):
    cells = []
    vals = []
    for arm in arms:
        v = metrics["arms"].get(arm, {})
        for k in key_path:
            v = v.get(k) if isinstance(v, dict) else None
        vals.append(v)
    for arm, v in zip(arms, vals):
        color = "var(--a)" if arm == "native" else "var(--b)"
        cells.append(f"<td><b>{_fmt(v, suffix)}</b>{_bar(v, color, scale) if bar and isinstance(v, (int, float)) else ''}</td>")
    return f"<tr><td>{html.escape(label)}<div class='small'>{'higher is better' if better == 'high' else 'lower is better'}</div></td>{''.join(cells)}</tr>"


def render(metrics) -> str:
    cfg = metrics["config"]
    arms = cfg["arms"]
    na, ot = metrics["arms"].get("native", {}), metrics["arms"].get("otari", {})
    head = "".join(f"<th class='{'na' if a == 'native' else 'ot'}'>{html.escape(ARM_LABEL.get(a, a))}</th>" for a in arms)

    def cost_ratio():
        try:
            return round(na["cost_usd"]["per_interview_estimate"] / ot["cost_usd"]["per_interview_estimate"], 1)
        except Exception:
            return None

    j, g = metrics["judge"], metrics["guardrail"]
    cards = f"""
<div class="grid">
 <div class="card"><div class="k">Question grounding (Otari vs native)</div><div class="v ot">{_fmt(ot.get('grounding', {}).get('grounded_pct'), '%')}</div><div class="vs">native {_fmt(na.get('grounding', {}).get('grounded_pct'), '%')} · share of questions that cite this candidate's real CV/JD details</div></div>
 <div class="card"><div class="k">Evaluator ranks answers correctly</div><div class="v ot">{_fmt(ot.get('calibration', {}).get('pairwise_accuracy_pct'), '%')}</div><div class="vs">native {_fmt(na.get('calibration', {}).get('pairwise_accuracy_pct'), '%')} · strong &gt; average &gt; weak &gt; off-topic</div></div>
 <div class="card"><div class="k">Blind judges: Otari wins or ties</div><div class="v ot">{_fmt(j.get('otari_win_or_tie_pct'), '%')}</div><div class="vs">{j.get('otari_wins', 0)} wins · {j.get('ties', 0)} ties · {j.get('native_wins', 0)} losses ({j.get('verdicts', 0)} verdicts)</div></div>
 <div class="card"><div class="k">Cost per mock interview</div><div class="v ot">${_fmt(ot.get('cost_usd', {}).get('per_interview_estimate'))}</div><div class="vs">native ${_fmt(na.get('cost_usd', {}).get('per_interview_estimate'))} · {_fmt(cost_ratio(), '×')} cheaper</div></div>
 <div class="card"><div class="k">Integrity guardrail catches injections</div><div class="v ot">{_fmt(g.get('detection_pct_with_classifier'), '%')}</div><div class="vs">false positives {_fmt(g.get('false_positive_pct_with_classifier'), '%')} · patterns alone {_fmt(g.get('detection_pct_patterns_only'), '%')}</div></div>
</div>"""

    quality = f"""
<h2>1 · Quality and reliability</h2>
<table><tr><th>Metric</th>{head}</tr>
{_row('Question requests that succeeded', ['reliability', 'question_success_pct'], metrics, arms, '%')}
{_row('Complete question sets (5/5)', ['reliability', 'complete_question_sets_pct'], metrics, arms, '%')}
{_row('Evaluation requests that succeeded', ['reliability', 'evaluation_success_pct'], metrics, arms, '%')}
{_row('Questions grounded in the CV/JD', ['grounding', 'grounded_pct'], metrics, arms, '%')}
{_row('Questions citing a number not in the CV/JD', ['grounding', 'unsupported_number_pct'], metrics, arms, '%', better='low')}
{_row('Evaluator pairwise ranking accuracy', ['calibration', 'pairwise_accuracy_pct'], metrics, arms, '%')}
{_row('Scores inside the expected band', ['calibration', 'band_accuracy_pct'], metrics, arms, '%')}
{_row('Spearman: answer quality vs score', ['calibration', 'spearman'], metrics, arms, '', scale=1)}
{_row('Injected answers that did not inflate the score', ['injection', 'resisted_pct'], metrics, arms, '%')}
{_row('Mean score lift from the injection vs the same weak answer', ['injection', 'mean_score_lift_vs_weak'], metrics, arms, ' pts', better='low', bar=False)}
{_row('Score spread on repeated runs (mean std. dev.)', ['consistency', 'mean_std'], metrics, arms, ' pts', better='low', bar=False)}
</table>"""

    means_rows = ""
    for q in dataset.QUALITY_ORDER + ["injection"]:
        lo, hi = dataset.EXPECTED_BANDS[q]
        cells = "".join(f"<td>{_fmt(metrics['arms'].get(a, {}).get('calibration', {}).get('mean_score_by_quality', {}).get(q))}</td>" for a in arms)
        means_rows += f"<tr><td>{q.replace('_', '-')}</td><td class='small'>{lo}–{hi}</td>{cells}</tr>"
    means = f"""<h3 style="margin-top:18px">Mean evaluator score by planted answer quality</h3>
<table><tr><th>Answer</th><th>Expected</th>{head}</tr>{means_rows}</table>"""

    speed = f"""
<h2>2 · Speed and cost</h2>
<table><tr><th>Metric</th>{head}</tr>
{_row('Question generation, median (s)', ['latency_s', 'questions_p50'], metrics, arms, ' s', better='low', bar=False)}
{_row('Question generation, p95 (s)', ['latency_s', 'questions_p95'], metrics, arms, ' s', better='low', bar=False)}
{_row('Answer evaluation, median (s)', ['latency_s', 'evaluation_p50'], metrics, arms, ' s', better='low', bar=False)}
{_row('Answer evaluation, p95 (s)', ['latency_s', 'evaluation_p95'], metrics, arms, ' s', better='low', bar=False)}
{_row('Cost per question set (USD)', ['cost_usd', 'questions_mean'], metrics, arms, '', better='low', bar=False)}
{_row('Cost per answer evaluation (USD)', ['cost_usd', 'evaluation_mean'], metrics, arms, '', better='low', bar=False)}
{_row('Cost per 1,000 mock interviews (USD)', ['cost_usd', 'per_1000_interviews'], metrics, arms, '', better='low', bar=False)}
</table>
<p class="small">Native cost = tokens × OpenAI list price for gpt-4o-mini ($0.15 / $0.60 per 1M). Otari cost = <code>usage.cost_usd</code> reported by Otari per request. One interview = 1 question set + 5 evaluations.</p>"""

    judge_html = f"""
<h2>3 · Blind comparison of question sets</h2>
<p class="sub">For each candidate, independent open-weight judges ({html.escape(', '.join(j.get('judges') or []) or 'none')}) compared the native and Otari question sets without knowing which was which, in both orders to cancel position bias.</p>
<div class="grid"><div class="card"><div class="k">Otari wins</div><div class="v ot">{j.get('otari_wins', 0)}</div></div>
<div class="card"><div class="k">Ties</div><div class="v">{j.get('ties', 0)}</div></div>
<div class="card"><div class="k">Native wins</div><div class="v na">{j.get('native_wins', 0)}</div></div>
<div class="card"><div class="k">Mean judge score (1–10)</div><div class="v">{_fmt(j.get('mean_score_otari'))} <span class="vs">Otari</span> / {_fmt(j.get('mean_score_native'))} <span class="vs">native</span></div></div></div>"""

    guard_html = f"""
<h2>4 · Integrity guardrail (Otari guardrail → AnchorCV endpoint → gpt-oss-safeguard)</h2>
<table><tr><th>Metric</th><th>Patterns only</th><th>Patterns + open-weight classifier</th></tr>
<tr><td>Injections caught ({g.get('injections')} hidden instructions in answers, CVs, job pages)</td><td>{_fmt(g.get('detection_pct_patterns_only'), '%')}</td><td><b>{_fmt(g.get('detection_pct_with_classifier'), '%')}</b></td></tr>
<tr><td>Clean texts wrongly flagged ({g.get('clean')} CVs, JDs, answers)</td><td>{_fmt(g.get('false_positive_pct_patterns_only'), '%')}</td><td><b>{_fmt(g.get('false_positive_pct_with_classifier'), '%')}</b></td></tr>
<tr><td>Cost per check / median latency</td><td>$0 / ~0 s</td><td>${_fmt(g.get('cost_per_check_usd'))} / {_fmt(g.get('latency_p50_s'), ' s')}</td></tr></table>
<p class="small">Missed: {html.escape(', '.join(g.get('missed') or []) or 'none')} · False positives: {html.escape(', '.join(g.get('false_positives') or []) or 'none')}</p>"""

    feat_rows = ""
    for name, f in metrics["features"].items():
        status = "<span class='pass'>PASS</span>" if f.get("pass") is True else (
            "<span class='fail'>FAIL</span>" if f.get("pass") is False else "<span class='skip'>not run</span>")
        detail = html.escape(f.get("skipped") or json.dumps(f.get("evidence"), ensure_ascii=False)[:700])
        feat_rows += f"<tr><td>{html.escape(name.replace('_', ' '))}</td><td>{status}</td><td class='small'>{detail}</td></tr>"
    features = f"""
<h2>5 · Otari features exercised live</h2>
<table><tr><th>Feature</th><th>Result</th><th>Evidence</th></tr>{feat_rows or '<tr><td colspan=3>not run</td></tr>'}</table>"""

    served_rows = ""
    for arm in arms:
        for k, v in metrics["arms"].get(arm, {}).get("served_models", {}).items():
            served_rows += f"<tr><td>{html.escape(ARM_LABEL.get(arm, arm))}</td><td><code>{html.escape(k)}</code></td><td>{v}</td></tr>"
    served = f"""<details><summary><b>Which model served each step</b></summary>
<table><tr><th>Arm</th><th>Task → model</th><th>Calls</th></tr>{served_rows}</table></details>"""

    method = f"""
<h2>Method</h2>
<p class="small">{len(cfg['personas'])} candidate personas (international-student and early-career profiles across data, software, engineering,
nursing, marketing, finance, design, construction, research, supply chain, teaching and security). Each has a CV, a job description, a list of
CV-specific anchor phrases, one interview question and five scripted answers of known quality (strong, average, weak, off-topic, and a weak
answer carrying an injection). Both arms run AnchorCV's real <code>/api/interview/*</code> endpoints in-process with identical prompts; only the
provider differs. Grounding = a question contains at least one anchor. Pairwise accuracy is over the 6 ordered pairs per persona
(ties count ½). Strong and average answers were scored {cfg['repeats']}× to measure consistency. Raw calls are in <code>results.jsonl</code>.</p>"""

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AnchorCV × Otari benchmark</title><style>{CSS}</style></head><body><main>
<h1>AnchorCV × Mozilla.ai Otari — benchmark</h1>
<p class="sub">Native GPT-4o-mini vs open-weight models through Otari, on AnchorCV's Context-Aware Mock Interview · run {html.escape(cfg.get('created', ''))}</p>
{cards}{quality}{means}{speed}{judge_html}{guard_html}{features}{served}{method}
</main></body></html>"""


def render_markdown(metrics) -> str:
    na, ot = metrics["arms"].get("native", {}), metrics["arms"].get("otari", {})
    g, j = metrics["guardrail"], metrics["judge"]

    def v(arm, *path):
        x = arm
        for p in path:
            x = x.get(p) if isinstance(x, dict) else None
        return _fmt(x)

    lines = [
        "| Metric | Native (GPT-4o-mini) | Otari (open-weight) |", "|---|---|---|",
        f"| Questions grounded in the candidate's CV/JD | {v(na, 'grounding', 'grounded_pct')}% | {v(ot, 'grounding', 'grounded_pct')}% |",
        f"| Evaluator ranks strong > average > weak > off-topic | {v(na, 'calibration', 'pairwise_accuracy_pct')}% | {v(ot, 'calibration', 'pairwise_accuracy_pct')}% |",
        f"| Spearman (answer quality vs score) | {v(na, 'calibration', 'spearman')} | {v(ot, 'calibration', 'spearman')} |",
        f"| Injected answers that did not inflate the score | {v(na, 'injection', 'resisted_pct')}% | {v(ot, 'injection', 'resisted_pct')}% |",
        f"| Score spread on repeats (std. dev.) | {v(na, 'consistency', 'mean_std')} | {v(ot, 'consistency', 'mean_std')} |",
        f"| Evaluation latency, median | {v(na, 'latency_s', 'evaluation_p50')} s | {v(ot, 'latency_s', 'evaluation_p50')} s |",
        f"| Cost per 1,000 mock interviews | ${v(na, 'cost_usd', 'per_1000_interviews')} | ${v(ot, 'cost_usd', 'per_1000_interviews')} |",
        "",
        f"Blind judges ({', '.join(j.get('judges') or [])}): Otari {j.get('otari_wins', 0)} wins, {j.get('ties', 0)} ties, native {j.get('native_wins', 0)} wins.",
        f"Integrity guardrail: {g.get('detection_pct_with_classifier')}% of injections caught, {g.get('false_positive_pct_with_classifier')}% false positives (patterns alone: {g.get('detection_pct_patterns_only')}%).",
        "",
        "| Otari feature (live test) | Result |", "|---|---|",
    ]
    for name, f in metrics["features"].items():
        lines.append(f"| {name.replace('_', ' ')} | {'PASS' if f.get('pass') is True else ('FAIL' if f.get('pass') is False else 'not run')} |")
    return "\n".join(lines) + "\n"


def build(run_dir: Path):
    run_dir = Path(run_dir)
    config, results = _load(run_dir)
    metrics = compute(config, results)
    (run_dir / "summary.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (run_dir / "summary.md").write_text(render_markdown(metrics), encoding="utf-8")
    (run_dir / "report.html").write_text(render(metrics), encoding="utf-8")
    return metrics

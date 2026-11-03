| Metric | Native (GPT-4o-mini) | Otari (open-weight) |
|---|---|---|
| Questions grounded in the candidate's CV/JD | 75.0% | 86.7% |
| Evaluator ranks strong > average > weak > off-topic | 100.0% | 100.0% |
| Spearman (answer quality vs score) | 0.989 | 0.968 |
| Injected answers that did not inflate the score | 100.0% | 100.0% |
| Score spread on repeats (std. dev.) | 0.79 | 0.52 |
| Evaluation latency, median | 3.9 s | 3.0 s |
| Cost per 1,000 mock interviews | $1.56 | $1.94 |

Blind judges (deepseek/deepseek-v4-pro, mistralai/mistral-large-latest, nvidia/nemotron-3-super-120b-a12b): Otari 67 wins, 0 ties, native 5 wins.
Integrity guardrail: 100.0% of injections caught, 0.0% false positives (patterns alone: 56.2%).

| Otari feature (live test) | Result |
|---|---|
| distinct model roles | PASS |
| routing fallback | PASS |
| per user budgets | PASS |
| web fetch job import | PASS |
| web search company research | PASS |
| guardrail blocks injected cv | PASS |
| guardrail injected job page | PASS |

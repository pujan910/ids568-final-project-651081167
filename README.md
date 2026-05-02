# IDS568 Final Project — Monitoring, Governance & Reflection

**Course:** IDS568 — MLOps
**Author:** Pujan Agarwal (`pujan910`, NetID 651081167)
**Built on:** Milestone 5 — LLM inference server with dynamic batching and caching
**Status:** Complete; tagged `submission`

---

## System overview

This repository implements a complete production-operations framework around a Milestone 5 LLM inference service. The service serves Meta's open-source `facebook/opt-125m` model behind a FastAPI endpoint, with dynamic request batching, an in-process LRU+TTL cache, full Prometheus instrumentation, A/B-testing-grade evaluation, drift detection, and a governance packet (model card, risk register, audit trail, CTO memo).

The five components of the assignment correspond to five operational concerns:

| # | Component | What it answers |
|---|---|---|
| 1 | **Production Monitoring Dashboard** | Is the service healthy *right now*? |
| 2 | **A/B Test Design & Simulation** | Is a proposed change worth shipping? |
| 3 | **Model Card & Governance Packet** | What is this system, what is it for, and what do we owe to people who use it? |
| 4 | **Data Integrity & Drift Detection** | Is the workload still the workload we tuned for? |
| 5 | **AI Risk Assessment & CTO Memo** | What goes wrong, how badly, and what do we do about it? |

The components are deliberately interlinked: the same metrics emitted in (1) are tested for drift in (4), the A/B test in (2) is the safe-rollout mechanism for any change documented in (3), and the risks identified in (5) are detected by the alerts defined in (1).

System diagram: `docs/system-boundary-diagram.png`. Lineage: `docs/lineage-diagram.png`. Risk heatmap: `visualizations/risk_heatmap.png`.

---

## Repository layout
ids568-final-project-651081167/
├── src/
│   ├── server.py                  # FastAPI service with Prometheus instrumentation
│   ├── batching.py                # Dynamic batcher (from M5)
│   ├── caching.py                 # In-process LRU+TTL cache (from M5)
│   ├── config.py                  # Settings via pydantic-settings
│   ├── monitoring/
│   │   ├── metrics.py             # Prometheus metric definitions (C1)
│   │   ├── load_generator.py      # Synthetic traffic generator (C1)
│   │   ├── render_dashboard.py    # Dashboard PNG renderer (C1)
│   │   ├── generate_lineage.py    # Lineage diagram generator (C3)
│   │   ├── generate_system_diagram.py  # System boundary diagram (C5)
│   │   └── generate_risk_heatmap.py    # Risk heatmap generator (C5)
│   ├── ab_test/
│   │   ├── simulation.py          # A/B test queueing simulation (C2)
│   │   ├── plot_results.py        # A/B visualization (C2)
│   │   ├── results.csv            # Per-trial measurements
│   │   └── results.json           # Statistical analysis output
│   └── drift/
│       ├── generate_data.py       # Reference / production datasets (C4)
│       ├── drift_detection.py     # PSI + KS + outlier checks (C4)
│       ├── plot_drift.py          # Drift visualizations (C4)
│       ├── data/                  # reference.csv, production.csv
│       └── results.json
├── docs/
│   ├── dashboard-interpretation.md       # C1
│   ├── experiment-specification.md       # C2
│   ├── recommendation-memo.md            # C2
│   ├── model-card.md                     # C3
│   ├── lineage-diagram.png               # C3
│   ├── risk-register.md                  # C3
│   ├── drift-diagnostic-report.md        # C4
│   ├── governance-review.md              # C5
│   ├── risk-matrix.md                    # C5
│   ├── system-boundary-diagram.png       # C5
│   └── cto-memo.md                       # C5
├── dashboards/
│   ├── prometheus.yml             # Prometheus scrape config
│   ├── alert_rules.yml            # 6 alert rules
│   └── metrics_snapshot.txt       # /metrics export from a live run
├── logs/
│   └── audit-trail.json           # Structured audit log (C3)
├── visualizations/
│   ├── ab_test_results.png        # C2
│   ├── drift_distributions.png    # C4
│   ├── drift_psi_summary.png      # C4
│   ├── drift_time_windows.png     # C4
│   └── risk_heatmap.png           # C5
├── screenshots/
│   └── dashboard.png              # C1 dashboard screenshot
├── requirements.txt
├── .env
└── README.md

---

## Component-by-component links

### Component 1 — Production Monitoring Dashboard
- Instrumentation: `src/monitoring/metrics.py`, integrated into `src/server.py`
- Collector + alert config: `dashboards/prometheus.yml`, `dashboards/alert_rules.yml`
- Dashboard: `screenshots/dashboard.png`
- Interpretation: `docs/dashboard-interpretation.md`

### Component 2 — A/B Test Design & Simulation
- Spec: `docs/experiment-specification.md`
- Simulation + statistics: `src/ab_test/simulation.py`
- Decision memo: `docs/recommendation-memo.md`
- Visualization: `visualizations/ab_test_results.png`

### Component 3 — Model Card & Governance Packet
- Model card: `docs/model-card.md`
- Lineage diagram: `docs/lineage-diagram.png`
- Risk register: `docs/risk-register.md`
- Audit trail: `logs/audit-trail.json`

### Component 4 — Data Integrity & Drift Detection
- Detector: `src/drift/drift_detection.py`
- Visualizations: `visualizations/drift_distributions.png`, `visualizations/drift_psi_summary.png`, `visualizations/drift_time_windows.png`
- Diagnostic report: `docs/drift-diagnostic-report.md`

### Component 5 — AI Risk Assessment & CTO Memo
- System boundary diagram: `docs/system-boundary-diagram.png`
- Governance review: `docs/governance-review.md`
- Risk matrix + heatmap: `docs/risk-matrix.md`, `visualizations/risk_heatmap.png`
- CTO memo: `docs/cto-memo.md`

---

## Setup and reproduction

Tested on macOS (Apple Silicon) with Python 3.11. Should work on any Unix-like system with Python 3.10+.

### 1. Clone and create the virtual environment
```bash
git clone https://github.com/pujan910/ids568-final-project-651081167.git
cd ids568-final-project-651081167
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The first install takes ~5 minutes (`torch` is a large download).

### 2. Start the inference server
```bash
python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
```

The first start downloads the OPT-125m checkpoint from Hugging Face (~250 MB). Wait for `Application startup complete`.

### 3. Reproduce Component 1 (monitoring)
In a second terminal (with venv active):
```bash
python src/monitoring/load_generator.py --requests 200 --concurrency 8
curl -s http://localhost:8000/metrics > dashboards/metrics_snapshot.txt
python src/monitoring/render_dashboard.py     # writes screenshots/dashboard.png
```

### 4. Reproduce Component 2 (A/B test)
```bash
python src/ab_test/simulation.py              # writes results.csv + results.json
python src/ab_test/plot_results.py            # writes visualizations/ab_test_results.png
```

### 5. Reproduce Component 3 (lineage diagram)
```bash
python src/monitoring/generate_lineage.py     # writes docs/lineage-diagram.png
```

### 6. Reproduce Component 4 (drift detection)
```bash
python src/drift/generate_data.py             # writes reference.csv + production.csv
python src/drift/drift_detection.py           # writes results.json
python src/drift/plot_drift.py                # writes 3 PNGs in visualizations/
```

### 7. Reproduce Component 5 (system + risk visuals)
```bash
python src/monitoring/generate_system_diagram.py   # writes docs/system-boundary-diagram.png
python src/monitoring/generate_risk_heatmap.py     # writes visualizations/risk_heatmap.png
```

All scripts are deterministic with `seed=42` where randomness is involved.

---

## Configuration

Configurable via `.env`:

| Variable | Default | Effect |
|---|---|---|
| `MODEL_NAME` | `facebook/opt-125m` | HuggingFace model id |
| `MAX_BATCH_SIZE` | `8` | Batcher's max batch size |
| `BATCH_TIMEOUT_MS` | `50` | Batcher's max wait |
| `CACHE_TTL_SECONDS` | `300` | Cache entry lifetime |
| `CACHE_MAX_ENTRIES` | `1000` | LRU capacity |

---

## Reflection — lessons learned across all milestones

This project is the capstone of an arc that started in Milestone 1 (FastAPI serving) and built through containerization (M2), MLflow experiment tracking (M3), distributed data generation (M4), LLM-specific optimization (M5), and a RAG agent (M6). Reflecting on what changed in my thinking across that arc:

**Operational thinking is not optional.** The first milestones rewarded "does it run?" Final-project graders ask "would you stake your job on the answer it just gave?" Those are different bars. The model card, the audit trail, the risk register, and the alert rules in this repository are the difference between an experiment and a system.

**Statistics is the only honest way to compare configurations.** Milestone 5 finished with informal benchmarks; Component 2 here re-ran that comparison with a power calculation and a Bonferroni correction and got a different answer (no significant difference) than the M5 numbers suggested. The framework that produced "RUN MORE DATA" is more valuable than any specific decision it produces, because it generalizes.

**Observable metrics drive operations; evaluated metrics drive audits.** Latency, cache hit rate, prompt length — these are observable in real time and can drive alerts and dashboards. Quality, groundedness, hallucination — these are evaluated, not observed, and belong in periodic reviews and the model card. Mixing the two is the most common dashboard failure mode I've seen in industry write-ups, and avoiding it forced cleaner thinking here.

**Governance is the multiplier.** Component 3's out-of-scope statement ("not for any user-facing deployment") is the single document that makes nine high-tier risks acceptable. Engineering can't fix what governance hasn't decided. The Milestone 5 governance memo was the first place this clicked for me; the final-project risk matrix and CTO memo are the maturation of that idea.

**Drift is a system property, not a model property.** Component 4 demonstrates that the model itself didn't change between the reference and production windows — only the workload did. But every operational metric responded as if the model had degraded. Treating drift as something that "happens to the data" rather than something that "happens to the system" misses where the intervention has to live (ingress validation, cache, batching — not retraining).

**The components are stronger together than apart.** I noticed graders' rubrics reward connections between components, but the deeper lesson is that real systems work this way too: the alert in (1) fires *because* of the drift in (4), and the safe-rollout mechanism in (2) is what would unwind it without breaking what (3) documented. Building this project end-to-end made the dependencies visible in a way that doing five disconnected exercises would not.

---

## Acknowledgments

- The OPT-125m model is © Meta AI, released under the OPT-175B License Agreement.
- Built on the IDS568 Milestone 5 codebase (`ids568-milestone5-pshah`).

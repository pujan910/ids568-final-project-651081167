# Structured Governance Review — OPT-125m Inference Service

This review applies the Component 5 system-level lens to the LLM inference service. Where the Model Card (Component 3) addressed *the model*, this review addresses *the system that wraps the model* — including the trust boundary between the client and the service, the storage of cached prompts, the lack of authentication, and the limitations of the underlying OPT-125m model when treated as a system component rather than as a research artifact.

System diagram: `docs/system-boundary-diagram.png`. Risk matrix with severity scoring: `docs/risk-matrix.md`. Executive summary: `docs/cto-memo.md`.

---

## 1. Data security

### 1.1 Data in transit
- Service exposes plain HTTP on `0.0.0.0:8000`. Acceptable for localhost development, **not** acceptable for any non-local deployment.
- No TLS termination, no mTLS, no JWT validation. A network observer can trivially read prompts and responses in transit.
- **Mitigation:** in any non-local deployment, terminate TLS at a reverse proxy (nginx, Caddy, or Azure Front Door) and add bearer-token authentication at the FastAPI layer.

### 1.2 Data at rest
- The cache is in-process memory only. Nothing is written to disk by the service itself.
- Cache keys are SHA-derived from `(prompt, model_name, max_tokens)` per the Milestone 5 design. **No user identifier is stored alongside the cached prompt** — this is the privacy-preserving design called out in the M5 governance memo and inherited here.
- Logs (uvicorn / FastAPI) are written to stdout at INFO level. At INFO, request bodies are not logged. At DEBUG they would be, so log level must remain at INFO or higher in any deployment.
- **Mitigation:** if the cache is migrated to Redis to support horizontal scale, encrypt at rest and require authn on the Redis instance.

### 1.3 Authentication and authorization
- **No authentication exists on any endpoint** (`/generate`, `/metrics`, `/health`, `/stats`).
- This is the single largest security risk in the current configuration. A localhost-only deployment is the only thing that makes this acceptable.
- **Mitigation:** for any non-local deployment, add API-key or JWT-based auth at the FastAPI dependency layer; protect `/metrics` with separate scraping credentials.

---

## 2. Retrieval risks (NOT APPLICABLE — but documented for completeness)

This service does **not** implement a retrieval-augmented generation pipeline. There is no vector store, no retriever, no document index. The service is a pure generative endpoint: client → cache → batcher → LLM → response.

The retrieval-related risks the assignment asks about (exposure of indexed documents, retrieval contamination, stale knowledge in a vector store) therefore do not apply to this deployment. They are listed here so the omission is intentional and visible to the reviewer rather than overlooked.

If this service were extended with a RAG layer (a natural next step using the Milestone 6 work), the retrieval risks below would become live and would need entries in the risk matrix:

- **Exposure:** retrieved snippets surfaced to the model could leak documents the user is not authorized to see.
- **Contamination:** an attacker who can write to the document index can plant adversarial content that gets retrieved and acted on.
- **Stale knowledge:** a vector index built once and never refreshed silently degrades as the underlying knowledge changes.

---

## 3. Hallucination risk points

OPT-125m is a 125-million-parameter base language model. It hallucinates routinely, and the system has no grounding layer to mitigate this.

| Risk point | Why it matters here | Mitigation in this build | What a real production build would add |
|---|---|---|---|
| **Plausible-sounding factual errors** | OPT-125m has minimal world knowledge; it produces confident-looking false statements | Out-of-scope statement in Model Card §2 prohibits factual / decision-making use | Retrieval grounding + citations + answerability classifier |
| **Decoder degeneration under greedy decoding** | Greedy decoding (`do_sample=False`) is prone to repetition loops on novel inputs — directly observed in Component 4 (response length tail growing) | Response-length histogram alert in Component 1 surfaces this when it happens | Switch to nucleus / top-p sampling and add a repetition penalty |
| **Stale training data (pre-2022)** | Anything time-sensitive will be wrong | Documented in Model Card §5 | RAG with a freshness-stamped corpus |
| **Underspecified prompts producing confidently wrong outputs** | The model never says "I don't know" | None at the model level | Output classifier that detects hedging vs assertion, or guardrails like Llama-Guard |

The honest answer is that **hallucination is mitigated in this build entirely by deployment scope**: the service is not user-facing and is not used to make decisions, so hallucination has no consequence. That is documented in the out-of-scope statement of the Model Card and is enforced operationally by the localhost-only deployment.

---

## 4. Tool-misuse pathways (NOT APPLICABLE — but documented)

This service is a pure text-generation endpoint. It does **not** call tools, execute code, browse the web, or perform any side-effecting action. The output is a string returned to the client.

If this service were extended into an agentic workflow (the Milestone 6 agent step is one possible path), the following tool-misuse pathways would need their own risk-matrix entries:

- **Prompt injection causing unauthorized tool calls** (e.g., a prompt that manipulates the agent into emailing data, deleting files, or making API calls).
- **Privilege confusion** between the client's authorization and the model's authorization.
- **Recursive tool loops** consuming compute without user benefit.

None of these apply to the current build.

---

## 5. Compliance concerns

| Concern | Status in this deployment | Production posture |
|---|---|---|
| **OPT-125m license (research-only, non-commercial)** | Compliant — academic / coursework deployment | Any commercial use would violate the OPT license; would need a different model |
| **GDPR / CCPA right-to-deletion on cached prompts** | Not in scope — local deployment, no real users | Required: implement cache eviction on user request, log deletion timestamps, conduct a DPIA |
| **PII in prompts** | None expected (synthetic test prompts only) | Required: PII detector at ingress (e.g., Presidio); flagged prompts not cached |
| **Output content policy** | None — service returns whatever OPT-125m generates | Required: toxicity / policy classifier between model and response |
| **Model provenance and supply-chain** | Documented: `facebook/opt-125m`, license noted, audit trail records the registration | Required for production: pinned content-hash of the safetensors, SBOM for dependencies |
| **Logging and audit retention** | Audit trail in `logs/audit-trail.json`, manually maintained | Required for production: append-only audit log with cryptographic chain (e.g., S3 with object lock) |

The compliance posture of this deployment is "acceptable for a localhost academic project, inadequate for any other deployment." That is the same posture as data security and authentication — every gap closes the moment the deployment scope expands beyond localhost, and that is the single most important governance fact about this service.

---

## 6. Cross-references to the rest of the project

- **Risk register (`docs/risk-register.md`)**: contains the line-item risks for bias, robustness, privacy, and compliance at the *model* level. Component 5's risk matrix (`docs/risk-matrix.md`) extends those with system-level risks.
- **Monitoring (`docs/dashboard-interpretation.md`)**: the alert rules are the live detectors for the operational risks identified here (memory pressure, latency SLO, cache hit rate degradation).
- **Drift (`docs/drift-diagnostic-report.md`)**: drift is itself a risk — the synthetic drift case in Component 4 demonstrated the system's response to a workload shift.
- **A/B test (`docs/recommendation-memo.md`)**: the experimental discipline used there is the mitigation for the "premature optimization" risk in the matrix.

The project's components are deliberately interlinked: the same metrics that drive the dashboard drive the alerts, drive the drift detector's choice of features, and back the risks in the matrix. One change to the system propagates through all five components.

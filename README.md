# labloop

## Overview

labloop learns reusable scientific skills from doing work. Given a task (a description and named inputs), it first asks whether a saved skill already fits. If one fits, it runs that skill directly. If none fits, it searches the literature briefly, extracts the reported procedure, composes a pipeline from biomolecular tools deployed on Modal, freezes the pipeline with its acceptance checks, runs it, and grades the result against those checks. A passing new pipeline is saved as a skill, and every reuse of a skill is appended to its evidence.

Mubit provides two things. Every model call goes through the Mubit gateway or another Anthropic-compatible endpoint with a fixed system prompt per role, so repeated calls of one role form one trainable task on the gateway. Lessons from each run are stored as memory and shown to the planner of later runs as advisory context.

This repository is the backend only. The frontend contract is a JSON API.

## Layout

| Path | Content |
| --- | --- |
| `labloop/orchestrator.py` | The loop of match, research, plan, freeze, run, grade and learn. |
| `labloop/catalog.py` | The tool catalog. Planning chooses only from entries marked available. |
| `labloop/pipeline.py` | Pipeline validation, reference resolution, scheduling in waves, and the freeze. |
| `labloop/grading.py` | Check evaluation and the three-state verdict. |
| `labloop/graders/ppi.py` | The optional ppi-assure grader for protein-protein co-folding outputs. |
| `labloop/skills.py` | The versioned skill store and the standing rules. |
| `labloop/memory.py` | Local JSONL memory and the Mubit memory client. |
| `labloop/models.py`, `labloop/prompts.py` | Role routing across providers and the fixed system prompts. |
| `labloop/research.py` | The capped research step. |
| `labloop/toolkit/` | Tool bodies shared by Modal and local runs, and readers for Boltz, Chai and ESMFold outputs. |
| `labloop/lit/fetch_corpus.py` | The keyless literature fetcher, vendored unchanged from harness-experiments. |
| `labloop/template/` | The run state layout from harness-experiments. |
| `labloop/api.py` | The FastAPI application. |
| `modal_apps/tools_app.py` | The `labloop-tools` Modal app. |
| `modal_apps/backend_app.py` | The `labloop-backend` Modal app, serving the API and the orchestrator. |
| `scripts/real_runs.sh` | The sequence of small real requests. |
| `tests/` | Offline tests that run the whole loop with a fake dispatcher and scripted model answers. |

## The loop

**Match.** The orchestrator recalls up to five lessons for the task and lists every saved skill that is not retired. The applicability role decides whether one fits and maps the task's inputs onto the skill's input schema. The answer is accepted only when it copies one of the skill's `applies_when` conditions exactly, reports no `not_for` conflict, and maps every input the skill declares. Any other answer means a new plan. The decision and its reason are written to `match.json` and `DECISIONS.jsonl`.

**Research.** When no skill fits, the researcher role writes at most two Europe PMC queries, which run through the `literature_search` Modal function. The two most relevant papers with an abstract are frozen into `research/corpus/` with the manifest format of the vendored fetcher, and the extractor role reports each paper's steps, tools, parameters and reported numbers. The step stops early when its token budget is spent. The limits are set by `LABLOOP_RESEARCH_MAX_QUERIES`, `LABLOOP_RESEARCH_MAX_PAPERS`, `LABLOOP_RESEARCH_PAGE_SIZE`, `LABLOOP_RESEARCH_FULLTEXT_CHARS` and `LABLOOP_RESEARCH_TOKEN_BUDGET`.

**Plan.** The planner composes a pipeline from the available catalog entries. A step is `{"id", "tool", "args"}`, and an argument whose whole value is `$inputs.<name>`, `$run_id` or `$steps.<id>.<field>` is resolved at run time. The planner also declares acceptance checks, an input schema, the skill description with `applies_when` and `not_for`, its sources, and every decision the literature did not settle. A plan that fails validation is returned to the planner once with the errors.

**Freeze.** Validation requires that every tool exists and is deployed, that every argument is known to its tool, that every reference resolves to a declared input or to an output of an earlier step, and that at least one check reads a real output. The plan is then written to `plan.json` with its SHA-256 digest in `plan.sha256`, computed over the canonical form used by ppi-harness, before any step runs. The run and grade phases reload the plan and refuse it if the digest no longer matches. Source-silent decisions go to `DECISIONS.jsonl`.

**Run.** Steps are grouped into waves of mutually independent steps. Each wave is dispatched with `modal.Function.from_name("labloop-tools", tool)`, using `.map()` for several calls of one tool and `.spawn()` for the rest, so that a wave runs concurrently. Each step is recorded in `EXPERIMENTS.jsonl`. A step whose upstream value is missing is recorded as skipped.

**Grade.** A check compares a metric with a value (`op` and `value`) or matches a published reference (`reference`, `tolerance` and `source`). A check whose metric is missing, not numeric, or comes from a failed step is UNVERIFIABLE. The verdict is FAIL when any check fails, INCONCLUSIVE when none fails and any is unverifiable, and PASS otherwise. As in ppi-harness, an INCONCLUSIVE verdict raises when read as a boolean, so it cannot be mistaken for a failure. Domain graders run here. The ppi-assure grader applies only to Boltz-2 or Chai-1 steps with two or more chains, and only a BLOCKING failure it reports affects the verdict. The verdict is written once to `RESULTS.json`.

**Learn.** The reviewer role reads the frozen plan, the step outcomes and the verdict, and writes short lessons, which are stored in memory. The lessons recalled for the run receive an outcome of success or failure. An INCONCLUSIVE run records no outcome, because missing evidence is not negative evidence. A passing new pipeline becomes a skill. A reused skill receives the run as evidence whatever its verdict.

## Skills

Each skill is stored at `skills/<name>/skill.json` under the state root, and every version is kept write-once under `skills/<name>/versions/`. A skill holds its name, title, description, `applies_when`, `not_for`, the pipeline with its checks, the input schema, lessons, sources, and evidence. Each evidence entry records the run id, the task, the inputs digest, the verdict and the graded metrics.

Standing is computed from evidence each time a skill is read and is never stored. A skill is a draft after one passing run, and validated once it has passed on inputs with a different digest. Only a person retires a skill, through `python -m labloop.cli retire` or the `retire` entrypoint of the backend app, and retiring requires a name and a reason. No model output and no recalled memory can change standing.

The API shows each skill as a card with its name, title, description, tools, inputs, standing, number of runs, number of passes and version.

## Memory

Memory is context and never authority. Lessons are recalled once, before matching, and shown to the planner under the heading of advisory lessons. Grading and standing never read memory.

`MubitMemory` uses the explicit `mubit.Client` from `mubit-sdk` 0.13.2 with `remember`, `get_context`, `record_outcome` and `create_skill`, and writes every lesson to a local JSONL copy as well. `LocalMemory` implements the same interface on JSONL files and is used by the tests, by `LABLOOP_MEMORY=local`, and when no key is set. The literature corpus is kept in the run directory and never in Mubit.

## Models

Every call uses the Anthropic Messages format through the `anthropic` SDK. Each role has one fixed system prompt in `labloop/prompts.py`, and all task-specific content, including the catalog, goes in the user message. Calls through the gateway carry the run id as `metadata.user_id`, which the gateway uses as the session key. The defaults below, whose exact model ids are in `ROLE_DEFAULTS` in `labloop/models.py`, can be changed with `LABLOOP_MODEL_<ROLE>`, written as `provider:model`.

| Role | Default | Purpose |
| --- | --- | --- |
| planner | Anthropic Sonnet 5.5 through `mubit` | Composes the pipeline and its checks. |
| researcher | Anthropic Haiku 5.5 through `mubit` | Writes literature queries. |
| extractor | Anthropic Haiku 5.5 through `mubit` | Extracts a paper's procedure. |
| applicability | Anthropic Haiku 5.5 through `mubit` | Decides whether a saved skill fits. |
| reviewer | GLM 5.3 through `zai` | Writes lessons after grading. |

The providers are `mubit` at `https://api.mubit.ai/anthropic` with `MUBIT_API_KEY` (or `MUBIT_API_TOKEN`), `zai` at `https://api.z.ai/api/anthropic` with `ZAI_API_KEY`, and `moonshot` at `https://api.moonshot.ai/anthropic` with `MOONSHOT_API_KEY`. Recording on the gateway follows `LABLOOP_MUBIT_RECORD` (default `full`) and `LABLOOP_MUBIT_STORE` (default `true`). Z.AI model ids are refused when they carry a bracket suffix.

`python -m labloop.cli probe` makes one short call to every provider and model the roles use, and to Kimi when `MOONSHOT_API_KEY` is set (model from `LABLOOP_KIMI_MODEL`, default `kimi-k3[1m]`).

## Tools

`labloop-tools` has one Modal function per available catalog entry. Each function takes one dict of arguments, writes outputs under `<run_id>/<step_id>/` on the `labloop-artifacts` Volume, commits the Volume, and returns scores, artifact paths relative to that Volume, small data, the runtime and the versions used.

| Tool | GPU | Image and weights |
| --- | --- | --- |
| `esmfold` | A10G | `transformers` 4.46.3 with `facebook/esmfold_v1`, cached on `labloop-weights-esmfold`. Inference runs with `HF_HUB_OFFLINE=1`. |
| `boltz2` | H100 | `boltz==2.1.1` with `boltz-community/boltz-2` at revision `6fdef46d`, on `labloop-weights-boltz`, run as in Modal's published example. |
| `chai1` | H100 | `chai_lab==0.5.0` with torch 2.7.1 for CUDA 12.8 and `CHAI_DOWNLOADS_DIR` on `labloop-weights-chai`, run as in Modal's published example. |
| `fetch_uniprot` | none | UniProtKB FASTA. |
| `fetch_pdb` | none | RCSB PDB entry, with chain sequences read from the coordinates. |
| `literature_search` | none | Europe PMC search with abstracts and optional open-access full-text excerpts. |

ColabFold, ProteinMPNN, RFdiffusion, DiffDock, Protenix and AlphaFold 3 are catalogued as unavailable, so the planner never sees them. They become available when their functions are built and verified.

The download functions fill the weight Volumes once. `download_chai` also folds one short chain after fetching the listed files, so that any file Chai-1 fetches lazily lands on the Volume rather than being fetched during a request.

## Deployment

```bash
modal secret create labloop-keys MUBIT_API_KEY=... ZAI_API_KEY=...
modal deploy modal_apps/tools_app.py
modal run modal_apps/tools_app.py::download_all
modal run modal_apps/tools_app.py::smoke
modal deploy modal_apps/backend_app.py
```

`MOONSHOT_API_KEY` and `MUBIT_PROJECT_ID` may be added to the secret. `MUBIT_PROJECT_ID` enables the skill mirror. Deploying the backend with `PPI_HARNESS_PATH` pointing at a ppi-harness checkout ships ppi-assure into the image for the domain grader.

The backend serves five endpoints.

| Method and path | Effect |
| --- | --- |
| `POST /tasks` | Accepts `{"description", "inputs", "research_queries"?}`, spawns the orchestrator, and returns the run id. |
| `GET /runs/{id}` | Returns the run status, task, match decision, frozen plan and digest, inputs, experiments, decisions, research and results. |
| `GET /skills` | Returns skill cards. Retired skills appear with `include_retired=true`. |
| `GET /skills/{name}` | Returns the card and the full skill. |
| `POST /skills/{name}/run` | Accepts `{"inputs", "description"?}` and runs that skill without matching or planning. |

State lives on the `labloop-state` Volume. The orchestrator is the only process that writes it, and it commits after every phase and every wave. The API reloads the Volume before every read and never writes to it. Submitted runs are recorded in the Modal Dict `labloop-calls`, so a run that has not started yet reads as queued. Workers write only to `labloop-artifacts`, and the orchestrator reloads that Volume before grading.

## Local use

```bash
pip install -e '.[mubit,dev]'
python -m pytest
python -m labloop.cli probe
python -m labloop.cli run --dispatcher local --description "..." --inputs '{"sequence": "..."}'
```

The local dispatcher runs only the CPU data tools in-process, so a local run plans and freezes a real pipeline and reports its model steps as failed, which grades as INCONCLUSIVE. `--dispatcher modal` calls the deployed tools. `scripts/real_runs.sh` deploys the tools, fetches the weights, runs the smoke fold, then runs an ESMFold task, a two-chain Boltz-2 task, and the same Boltz-2 task again to confirm that the skill is reused.

## Reuse of earlier work

The run state layout comes from `template/` of harness-experiments, and the literature fetcher from `lit/fetch_corpus.py` on its `exp2-sep/arm-a` branch. A skill is the persistent, evidence-backed counterpart of the frozen `WORKFLOW.md` that Arm B writes in that experiment. The canonical digest, the write-once results, and the refusal to read an uninformative outcome as a boolean follow `harness/canonical.py` and `harness/results.py` of ppi-harness. The ppi-assure grader calls `ppi_assure.core.run.audit` on co-folding output directories. The episode runner `runner.py` is not used, because the loop composes catalogued functions and runs no code written by a model. Any later step that does run such code should run it in a Modal Sandbox.

## Verification status

The offline tests cover a first task that researches, plans, freezes, runs, grades and saves a skill, and a second task that reuses the skill without planning. They also cover rejected applicability answers, failing and unverifiable checks, the planner retry, a tampered plan, forced skill runs, retirement, and the API.

Against the real services, the gateway served the Sonnet 5.5 and Haiku 5.5 models, and Z.AI served `glm-5.3`. Europe PMC, UniProt and RCSB answered from the local data tools. A live planning run produced a valid ESMFold pipeline, and a second produced a valid two-chain Boltz-2 pipeline, both frozen with checks. The live applicability role reused a seeded monomer skill for a single-chain task, quoting its condition exactly, and refused it for a heterodimer by its `not_for` clause.

## Limitations

The Modal apps have not been deployed or run. The Modal token available when they were written had expired, so the images, the weight downloads and every GPU function are untested, and the first deployment may need version fixes, particularly for the ColabFold-free Chai-1 image and the Boltz kernels flag.

The Mubit memory API was not reachable. The SDK's HTTP routes reach the gateway at `api.mubit.ai`, which answers `unknown_route` for memory paths, and its gRPC transport returns an authentication error for the gateway key. Memory therefore falls back to the local JSONL copy, which recalls by word overlap rather than semantic similarity. The client stops calling the remote API for the rest of the process after the first such error.

Kimi was not checked. No Moonshot key was available, and the gateway exposes OpenRouter only through its OpenAI-format compatibility path, which the Anthropic-only call convention excludes.

The orchestrator runs in at most one container. Two runs therefore never write the skill store at once, and concurrent tasks wait in a queue.

Literature relevance is weak for generic tasks. Europe PMC ranks recent applied papers above method papers for broad queries, so the extractor often marks every retrieved paper irrelevant, and the plan then rests on source-silent decisions, which are recorded as such.

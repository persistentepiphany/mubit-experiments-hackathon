"""The core loop: match, research, plan, freeze, run, grade, learn.

The orchestrator is the only writer of state. Tools return results and never
touch the state root. Memory is read once, before planning, and shown to the
planner as advisory text; grading reads only the frozen plan and the step
results, and a skill's standing is computed from its evidence alone.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

from labloop import catalog, pipeline
from labloop.canonical import digest_document
from labloop.dispatch import Dispatcher
from labloop.grading import DomainGrader, grade
from labloop.knowledge import KnowledgeStore, for_planner
from labloop.memory import Memory
from labloop.models import ModelError, Models, ask_json
from labloop.research import research
from labloop.skills import SkillStore, standing
from labloop.state import RunDir, StateRoot, new_run_id

PHASES = ["match", "research", "plan", "freeze", "run", "grade", "learn"]


def _preview(value: Any, limit: int = 160) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}... ({len(value)} characters)"
    if isinstance(value, list):
        return [_preview(v, limit) for v in value[:20]]
    if isinstance(value, dict):
        return {k: _preview(v, limit) for k, v in value.items()}
    return value


def _schema_type(value: Any) -> str:
    for kind, name in ((bool, "boolean"), (int, "integer"), (float, "number"), (str, "string"),
                       (list, "array"), (dict, "object")):
        if isinstance(value, kind):
            return name
    return "string"


def _short(result: dict[str, Any]) -> dict[str, Any]:
    """A step result without bulky data, for prompts and EXPERIMENTS.jsonl."""
    data = result.get("data") or {}
    return {**result, "data": {k: _preview(v, 80) for k, v in data.items()}}


class Loop:
    def __init__(self, state: StateRoot, *, models: Models, dispatcher: Dispatcher, memory: Memory,
                 graders: list[DomainGrader] = (), artifacts_root: Path | None = None,
                 artifacts_reload=None) -> None:
        self.state = state
        self.artifacts_reload = artifacts_reload
        self.models = models
        self.dispatcher = dispatcher
        self.memory = memory
        self.graders = list(graders)
        self.artifacts_root = artifacts_root
        self.skills = SkillStore(state.skills)

    # ------------------------------------------------------------------ match
    def _check_applicability(self, answer: Any, candidates: dict[str, dict], inputs: dict[str, Any]) -> list[str]:
        if not isinstance(answer, dict):
            return ["the answer is not an object"]
        if not answer.get("applies"):
            return []
        name = answer.get("skill")
        skill = candidates.get(name)
        if skill is None:
            return [f"skill {name!r} is not among the candidates"]
        errors = []
        if answer.get("matched_applies_when") not in skill["applies_when"]:
            errors.append("matched_applies_when must copy one of the skill's applies_when conditions exactly")
        if answer.get("not_for_conflicts"):
            errors.append("a skill whose not_for exclusions the task matches cannot be reused")
        mapping = answer.get("input_mapping") or {}
        for key in skill.get("input_schema", {}):
            entry = mapping.get(key)
            if not isinstance(entry, dict) or not ({"from_input", "value"} & set(entry)):
                errors.append(f"skill input {key!r} is not mapped")
            elif "from_input" in entry and entry["from_input"] not in inputs:
                errors.append(f"skill input {key!r} maps to task input {entry['from_input']!r}, which does not exist")
        return errors

    def match(self, task: dict[str, Any], run: RunDir, run_id: str, lessons: list[dict],
              force_skill: str | None) -> dict[str, Any]:
        inputs = task.get("inputs", {})
        if force_skill:
            skill = self.skills.get(force_skill)
            if skill is None or skill.get("retired"):
                raise ValueError(f"skill {force_skill!r} does not exist or is retired")
            missing = [k for k in skill.get("input_schema", {}) if k not in inputs]
            if missing:
                raise ValueError(f"skill {force_skill} needs inputs {missing}")
            decision = {"decision": "reuse", "skill": force_skill, "version": skill["version"],
                        "reason": "the caller asked for this skill by name",
                        "input_mapping": {k: {"from_input": k} for k in skill.get("input_schema", {})}}
            run.write_json("match.json", {"candidates": [force_skill], **decision}, once=True)
            return decision

        candidates = {s["name"]: s for s in self.skills.list(include_retired=False)}
        record: dict[str, Any] = {"candidates": sorted(candidates), "lessons": [l.get("id") for l in lessons]}
        if not candidates:
            decision = {"decision": "plan", "skill": None, "reason": "no saved skill is available"}
        else:
            user = json.dumps({
                "task": task["description"],
                "inputs": {k: {"type": _schema_type(v), "preview": _preview(v)} for k, v in inputs.items()},
                "candidate_skills": [{"name": s["name"], "description": s["description"],
                                      "applies_when": s["applies_when"], "not_for": s["not_for"],
                                      "input_schema": s.get("input_schema", {}), "standing": standing(s)}
                                     for s in candidates.values()],
            }, indent=1)
            try:
                answer, replies = ask_json(self.models, "applicability", user, run_id=run_id, max_tokens=1024,
                                           check=lambda a: self._check_applicability(a, candidates, inputs))
                record["model"] = f"{replies[-1].provider}:{replies[-1].model}"
                record["answer"] = answer
                if answer.get("applies"):
                    skill = candidates[answer["skill"]]
                    decision = {"decision": "reuse", "skill": skill["name"], "version": skill["version"],
                                "matched_applies_when": answer["matched_applies_when"],
                                "input_mapping": answer["input_mapping"], "reason": answer.get("reason", "")}
                else:
                    decision = {"decision": "plan", "skill": None,
                                "reason": answer.get("reason") or "no candidate skill fits"}
            except ModelError as error:
                decision = {"decision": "plan", "skill": None,
                            "reason": f"the applicability answer was rejected, so no skill is reused: {error}"}
        run.write_json("match.json", {**record, **decision}, once=True)
        return decision

    # ------------------------------------------------------------------- plan
    def _plan_errors(self, plan: Any, inputs: dict[str, Any]) -> list[str]:
        if not isinstance(plan, dict):
            return ["the plan is not an object"]
        errors = pipeline.validate(plan, set(inputs))
        schema = plan.get("input_schema")
        if not isinstance(schema, dict):
            errors.append("input_schema must be an object")
            schema = {}
        used = {r.split(".")[1] for s in plan.get("steps", []) if isinstance(s, dict)
                for r in pipeline._refs(s.get("args", {})) if r.startswith("$inputs.")}
        for name in sorted(used - set(schema)):
            errors.append(f"input {name!r} is referenced but not declared in input_schema")
        for name in sorted(set(schema) - set(inputs)):
            errors.append(f"input_schema declares {name!r}, which the task does not supply")
        meta = plan.get("skill")
        if not isinstance(meta, dict) or not meta.get("name") or not meta.get("applies_when"):
            errors.append("skill must carry a name and at least one applies_when condition")
        return errors

    def plan(self, task: dict[str, Any], run_id: str, findings: dict[str, Any], lessons: list[dict]) -> dict[str, Any]:
        inputs = task.get("inputs", {})
        user = json.dumps({
            "task": task["description"],
            "inputs": {k: {"type": _schema_type(v), "preview": _preview(v)} for k, v in inputs.items()},
            "catalog": catalog.for_prompt(),
            "tool_knowledge": for_planner(KnowledgeStore(self.state.knowledge)),
            "literature": {
                "papers": [{k: p.get(k) for k in ("title", "doi", "year", "citations", "text_source")}
                           for p in findings.get("papers", [])],
                "paperqa_answers": [{"question": a["question"], "answer": a["answer"],
                                     "sources": sorted({c["citation"] for c in a["contexts"]})}
                                    for a in ((findings.get("paperqa") or {}).get("answers") or [])],
                "extraction": findings.get("extraction"),
            },
            "advisory_lessons": [l["content"] for l in lessons],
        }, indent=1)
        plan, _ = ask_json(self.models, "planner", user, run_id=run_id, max_tokens=8192,
                           check=lambda p: self._plan_errors(p, inputs))
        return plan

    # -------------------------------------------------------------------- run
    def execute(self, plan: dict[str, Any], inputs: dict[str, Any], run_id: str, run: RunDir) -> dict[str, dict]:
        results: dict[str, dict[str, Any]] = {}
        for wave in pipeline.waves(plan["steps"]):
            calls, ready = [], []
            for step in wave:
                try:
                    args = pipeline.resolve(step["args"], inputs, run_id, results)
                except KeyError as error:
                    results[step["id"]] = {"error": f"an upstream value is missing: {error}"}
                    run.append("EXPERIMENTS.jsonl", {"step_id": step["id"], "tool": step["tool"],
                                                     "status": "skipped", "error": results[step["id"]]["error"]})
                    continue
                calls.append((step["tool"], {**args, "run_id": run_id, "step_id": step["id"]}))
                ready.append(step)
            started = time.time()
            outcomes = self.dispatcher.run_wave(calls) if calls else []
            elapsed = round(time.time() - started, 2)
            for step, (tool, args), outcome in zip(ready, calls, outcomes):
                if isinstance(outcome, BaseException):
                    results[step["id"]] = {"error": f"{type(outcome).__name__}: {outcome}"}
                    run.append("EXPERIMENTS.jsonl", {"step_id": step["id"], "tool": tool, "args": _preview(args),
                                                     "status": "error", "error": results[step["id"]]["error"],
                                                     "wave_seconds": elapsed})
                else:
                    results[step["id"]] = outcome
                    run.append("EXPERIMENTS.jsonl", {"step_id": step["id"], "tool": tool, "args": _preview(args),
                                                     "status": "ok", "result": _short(outcome),
                                                     "wave_seconds": elapsed})
            self.state.commit()
        return results

    # ------------------------------------------------------------------ learn
    def learn(self, task, run_id, plan, results, graded, decision, lessons_used, inputs_digest,
              plan_digest) -> dict[str, Any]:
        verdict = graded["verdict"]
        lesson_ids, lesson_texts, review_error, summary = [], [], None, None
        user = json.dumps({
            "task": task["description"],
            "pipeline": {"steps": plan["steps"], "checks": plan["checks"]},
            "origin": plan.get("origin"),
            "steps": {k: _short(v) for k, v in results.items()},
            "grading": {"verdict": verdict, "checks": graded["checks"]},
        }, indent=1, default=str)
        try:
            # The reviewer may be a reasoning model that spends part of its budget before answering.
            review, _ = ask_json(self.models, "reviewer", user, run_id=run_id, max_tokens=8192,
                                 check=lambda r: [] if isinstance(r, dict) and isinstance(r.get("lessons"), list)
                                 else ["lessons must be a list"])
            summary = str(review.get("summary") or "").strip() or None
            for lesson in review["lessons"][:8]:
                text = str(lesson.get("content", "")).strip() if isinstance(lesson, dict) else str(lesson)
                if not text:
                    continue
                kind = lesson.get("lesson_type", "observation") if isinstance(lesson, dict) else "observation"
                lesson_texts.append(text)
                lesson_ids.append(self.memory.remember(
                    text, lesson_type=kind, run_id=run_id,
                    metadata={"verdict": verdict, "tools": sorted({s["tool"] for s in plan["steps"]}),
                              "skill": decision.get("skill")}))
        except ModelError as error:
            review_error = str(error)

        # An inconclusive run is uninformative, so it records no outcome rather than a negative one.
        if verdict in ("PASS", "FAIL"):
            for lesson in lessons_used:
                if lesson.get("id"):
                    self.memory.record_outcome(lesson["id"], outcome="success" if verdict == "PASS" else "failure",
                                               signal=1.0 if verdict == "PASS" else 0.0,
                                               rationale=f"run {run_id} graded {verdict} after recalling this lesson",
                                               run_id=run_id)

        evidence = {"run_id": run_id, "task": task["description"], "inputs_digest": inputs_digest,
                    "verdict": verdict, "metrics": graded["metrics"], "plan_digest": plan_digest}
        skill_action = None
        if decision["decision"] == "reuse":
            skill = self.skills.append_evidence(decision["skill"], evidence, lesson_texts)
            skill_action = {"action": "evidence_appended", "skill": skill["name"], "version": skill["version"],
                            "standing": standing(skill)}
        elif verdict == "PASS":
            skill = self.skills.create(meta=plan["skill"], pipeline=plan, input_schema=plan["input_schema"],
                                       sources=plan.get("sources", []), lessons=lesson_texts, evidence=evidence,
                                       plan_digest=plan_digest, run_id=run_id)
            self.memory.mirror_skill(skill)
            skill_action = {"action": "created", "skill": skill["name"], "version": 1, "standing": standing(skill)}
        return {"lessons": lesson_ids, "lesson_texts": lesson_texts, "review_error": review_error,
                "summary": summary, "skill": skill_action}

    # -------------------------------------------------------------------- all
    def run_task(self, task: dict[str, Any], run_id: str | None = None,
                 force_skill: str | None = None) -> dict[str, Any]:
        run_id = run_id or new_run_id()
        task = {"description": str(task["description"]), "inputs": dict(task.get("inputs", {})),
                **{k: v for k, v in task.items() if k not in ("description", "inputs")}}
        run = RunDir.create(self.state.run_dir(run_id), task)
        progress = {p: "todo" for p in PHASES}

        def phase(name: str, line: str, **fields) -> None:
            for p in PHASES:
                if progress[p] == "doing":
                    progress[p] = "done"
            progress[name] = "doing"
            run.status(name, run_id=run_id, **fields)
            run.state_md(line, list(progress.items()), [])
            self.state.commit()

        try:
            phase("match", "Matching the task against saved skills.")
            lessons = self.memory.context(task["description"], run_id=run_id, limit=5)
            decision = self.match(task, run, run_id, lessons, force_skill)
            run.append("DECISIONS.jsonl", {"kind": "match", **{k: v for k, v in decision.items()}})

            if decision["decision"] == "reuse":
                progress["research"] = progress["plan"] = "dropped"
                skill = self.skills.get(decision["skill"])
                inputs = {}
                for key, entry in decision["input_mapping"].items():
                    inputs[key] = task["inputs"][entry["from_input"]] if "from_input" in entry else entry["value"]
                plan = {"origin": {"kind": "skill", "skill": skill["name"], "version": skill["version"]},
                        "skill": {k: skill[k] for k in ("name", "title", "description", "applies_when", "not_for")},
                        "input_schema": skill["input_schema"], "steps": skill["pipeline"]["steps"],
                        "checks": skill["pipeline"]["checks"], "sources": skill.get("sources", []), "decisions": []}
                errors = pipeline.validate(plan, set(inputs))
                if errors:
                    raise ValueError(f"the saved skill no longer validates: {errors}")
            else:
                phase("research", "Searching the literature for a procedure.")
                findings = research(task, run=run, run_id=run_id, dispatcher=self.dispatcher, models=self.models)
                if not findings.get("extraction"):
                    run.assume("No literature procedure was extracted, so every planning choice is source-silent.")
                phase("plan", "Composing a pipeline from the catalog.")
                drafted = self.plan(task, run_id, findings, lessons)
                inputs = {k: task["inputs"][k] for k in drafted["input_schema"]}
                plan = {"origin": {"kind": "planned"}, **{k: drafted.get(k) for k in
                        ("skill", "input_schema", "steps", "checks", "sources", "decisions")}}
                plan["decisions"] = plan["decisions"] or []
                plan["sources"] = plan["sources"] or []

            phase("freeze", "Freezing the plan.")
            plan_digest = pipeline.freeze(run.path, plan)
            inputs_digest = digest_document(inputs)
            run.write_json("inputs.json", {"inputs": inputs, "inputs_digest": inputs_digest}, once=True)
            for d in plan.get("decisions", []):
                run.append("DECISIONS.jsonl", {"kind": "plan", **d})
            run.status("freeze", plan_digest=plan_digest, inputs_digest=inputs_digest,
                       origin=plan["origin"])

            phase("run", "Running the frozen pipeline on Modal.")
            frozen, digest = pipeline.load_frozen(run.path)
            results = self.execute(frozen, inputs, run_id, run)

            phase("grade", "Grading the frozen checks.")
            if self.artifacts_reload:
                self.artifacts_reload()
            frozen, digest = pipeline.load_frozen(run.path)
            graded = grade(frozen, results, self.graders, self.artifacts_root)
            run.write_json("RESULTS.json", {"run_id": run_id, "plan_digest": digest,
                                            "inputs_digest": inputs_digest, **graded}, once=True)

            phase("learn", f"Verdict {graded['verdict']}. Recording lessons.")
            learned = self.learn(task, run_id, frozen, results, graded, decision, lessons,
                                 inputs_digest, digest)
            progress["learn"] = "done"
            findings_lines = [f"verdict {graded['verdict']}"] + [
                f"{c['id']}: {c['status']} (observed {c.get('observed')})" for c in graded["checks"]]
            run.state_md(f"Done. Verdict {graded['verdict']}.", list(progress.items()), findings_lines)
            memory_errors = list(getattr(self.memory, "errors", []))
            record = run.status("done", verdict=graded["verdict"], skill=learned["skill"],
                                lessons=learned["lessons"], lesson_texts=learned["lesson_texts"],
                                summary=learned["summary"], review_error=learned["review_error"],
                                memory_errors=memory_errors[-5:])
        except Exception as error:
            record = run.status("error", error=f"{type(error).__name__}: {error}",
                                traceback=traceback.format_exc()[-4000:])
        self.state.commit()
        return record

"""Command line: provider probes, local runs, and skill listings.

    python -m labloop.cli probe
    python -m labloop.cli run --description "..." --inputs '{"sequence": "..."}' [--dispatcher modal|local]
    python -m labloop.cli skills
    python -m labloop.cli retire NAME --by "person" --reason "why"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _probe(args) -> int:
    from labloop.models import PROVIDERS, ROLE_DEFAULTS, AnthropicModels, ModelError, role_target

    targets = {}
    for role in ROLE_DEFAULTS:
        targets.setdefault(role_target(role), []).append(role)
    models = AnthropicModels()
    failures = 0
    for (provider, model, effort), roles in targets.items():
        try:
            client = models._client(provider)
            extra = {"output_config": {"effort": effort}} if effort else {}
            reply = client.messages.create(model=model, max_tokens=2048, **extra,
                                           messages=[{"role": "user", "content": "Reply with the single word ok."}])
            text = "".join(b.text for b in reply.content if getattr(b, "type", "") == "text").strip()
            print(f"OK   {provider}:{model}{'@' + effort if effort else ''} roles={roles} served={reply.model} text={text[:40]!r}")
        except (ModelError, Exception) as error:
            failures += 1
            print(f"FAIL {provider}:{model}{'@' + effort if effort else ''} roles={roles} {type(error).__name__}: {str(error)[:200]}")
    missing = [p for p, cfg in PROVIDERS.items() if not any(os.environ.get(k) for k in cfg["key_env"])]
    if missing:
        print(f"no key for: {', '.join(missing)}")
    if args.memory:
        from labloop.memory import LocalMemory, MubitMemory

        memory = MubitMemory(LocalMemory(Path(args.state) / "memory"))
        memory.context("probe", run_id="probe", limit=1)
        print("mubit memory:", "OK" if not memory.errors else memory.errors[-1])
    return 1 if failures else 0


def _run(args) -> int:
    from labloop import memory
    from labloop.dispatch import LocalDispatcher, ModalDispatcher
    from labloop.graders import default_graders
    from labloop.models import AnthropicModels
    from labloop.orchestrator import Loop
    from labloop.state import StateRoot

    if args.task:
        task = json.loads(Path(args.task).read_text())
    else:
        task = {"description": args.description, "inputs": json.loads(args.inputs or "{}")}
    state = StateRoot(Path(args.state))
    dispatcher = ModalDispatcher() if args.dispatcher == "modal" else LocalDispatcher(Path(args.state) / "artifacts")
    loop = Loop(state, models=AnthropicModels(), dispatcher=dispatcher, memory=memory.from_env(state.memory),
                graders=default_graders())
    record = loop.run_task(task, force_skill=args.skill)
    print(json.dumps({k: v for k, v in record.items() if k != "traceback"}, indent=2, default=str))
    return 0 if record.get("phase") == "done" else 1


def _skills(args) -> int:
    from labloop.skills import SkillStore, card

    for skill in SkillStore(Path(args.state) / "skills").list():
        print(json.dumps(card(skill)))
    return 0


def _retire(args) -> int:
    from labloop.skills import SkillStore, card

    print(json.dumps(card(SkillStore(Path(args.state) / "skills").retire(args.name, by=args.by, reason=args.reason))))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labloop")
    parser.add_argument("--state", default=os.environ.get("LABLOOP_STATE", "state"))
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="one short call per configured provider")
    probe.add_argument("--memory", action="store_true", help="also try the Mubit memory API")
    probe.set_defaults(fn=_probe)
    run = sub.add_parser("run", help="run one task in this process")
    run.add_argument("--task", help="JSON file with description and inputs")
    run.add_argument("--description")
    run.add_argument("--inputs", help="JSON object")
    run.add_argument("--skill", help="run this saved skill directly")
    run.add_argument("--dispatcher", choices=["modal", "local"], default="modal")
    run.set_defaults(fn=_run)
    sub.add_parser("skills", help="list skill cards").set_defaults(fn=_skills)
    retire = sub.add_parser("retire", help="retire a skill (people only)")
    retire.add_argument("name")
    retire.add_argument("--by", required=True)
    retire.add_argument("--reason", required=True)
    retire.set_defaults(fn=_retire)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

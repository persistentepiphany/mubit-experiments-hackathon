"""labloop-tools: one Modal function per catalogued tool.

Model weights are downloaded once by the `download_*` functions into named
Volumes and mounted read-only in spirit afterwards, so no request installs or
downloads a model. Every function takes one dict of arguments, writes outputs
under `<run_id>/<step_id>/` on the `labloop-artifacts` Volume, commits it, and
returns `{"tool", "scores", "artifacts", "data", "runtime_s", "versions"}` with
artifact paths relative to that Volume.

    modal deploy modal_apps/tools_app.py
    modal run modal_apps/tools_app.py::download_all
    modal run modal_apps/tools_app.py::smoke
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import modal

APP_NAME = "labloop-tools"
app = modal.App(APP_NAME)

ARTIFACTS = Path("/artifacts")
artifacts_volume = modal.Volume.from_name("labloop-artifacts", create_if_missing=True)

ESM_DIR = Path("/weights/esmfold")
BOLTZ_DIR = Path("/weights/boltz")
CHAI_DIR = Path("/weights/chai")
esm_volume = modal.Volume.from_name("labloop-weights-esmfold", create_if_missing=True)
boltz_volume = modal.Volume.from_name("labloop-weights-boltz", create_if_missing=True)
chai_volume = modal.Volume.from_name("labloop-weights-chai", create_if_missing=True)

BOLTZ_REVISION = "6fdef46d763fee7fbb83ca5501ccceff43b85607"
CHAI_ASSETS = "https://chaiassets.com/chai1-inference-depencencies"  # the host's own spelling
CHAI_FILES = ["conformers_v1.apkl"] + [f"models_v2/{n}.pt" for n in
                                        ("trunk", "token_embedder", "feature_embedding", "diffusion_module",
                                         "confidence_head")]

cpu_image = modal.Image.debian_slim(python_version="3.12").add_local_python_source("labloop", ignore=["**/__pycache__/**", "**/*.pyc"])

esm_base = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("torch==2.5.1", "transformers==4.46.3", "accelerate==1.1.1", "numpy==1.26.4")
    .env({"HF_HOME": str(ESM_DIR / "hf")})
)
esm_image = esm_base.env({"HF_HUB_OFFLINE": "1"}).add_local_python_source("labloop", ignore=["**/__pycache__/**", "**/*.pyc"])
esm_download_image = esm_base

boltz_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("boltz==2.1.1")
    .add_local_python_source("labloop", ignore=["**/__pycache__/**", "**/*.pyc"])
)
boltz_download_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("huggingface_hub[hf_transfer]==0.26.2")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

chai_image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("chai_lab==0.5.0")
    .uv_pip_install("torch==2.7.1", extra_index_url="https://download.pytorch.org/whl/cu128")
    .env({"CHAI_DOWNLOADS_DIR": str(CHAI_DIR)})
    .add_local_python_source("labloop", ignore=["**/__pycache__/**", "**/*.pyc"])
)

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_MODELS: dict = {}


def _out_dir(args: dict, tool: str) -> tuple[Path, Path]:
    run_id = _SAFE.sub("_", str(args.get("run_id") or "adhoc"))[:64]
    step_id = _SAFE.sub("_", str(args.get("step_id") or tool))[:64]
    rel = Path(run_id) / step_id
    out = ARTIFACTS / rel
    out.mkdir(parents=True, exist_ok=True)
    return out, rel


def _result(tool: str, started: float, scores: dict, artifacts: dict, data: dict | None = None,
            versions: dict | None = None, commit: bool = True) -> dict:
    if commit:
        artifacts_volume.commit()
    return {"tool": tool, "scores": scores, "artifacts": {k: str(v) for k, v in artifacts.items()},
            "data": data or {}, "runtime_s": round(time.time() - started, 2), "versions": versions or {}}


# ---------------------------------------------------------------- downloads
@app.function(image=esm_download_image, volumes={ESM_DIR: esm_volume}, timeout=30 * 60)
def download_esmfold() -> str:
    from transformers import AutoTokenizer, EsmForProteinFolding

    AutoTokenizer.from_pretrained("facebook/esmfold_v1")
    EsmForProteinFolding.from_pretrained("facebook/esmfold_v1")
    esm_volume.commit()
    return "esmfold weights in labloop-weights-esmfold"


@app.function(image=boltz_download_image, volumes={BOLTZ_DIR: boltz_volume}, timeout=30 * 60)
def download_boltz(force: bool = False) -> str:
    import tarfile

    from huggingface_hub import snapshot_download

    snapshot_download(repo_id="boltz-community/boltz-2", revision=BOLTZ_REVISION, local_dir=BOLTZ_DIR,
                      force_download=force)
    mols = BOLTZ_DIR / "mols.tar"
    if mols.exists() and not (BOLTZ_DIR / "mols").exists():
        with tarfile.open(mols) as tar:
            tar.extractall(BOLTZ_DIR)
    boltz_volume.commit()
    return f"boltz-2 weights at revision {BOLTZ_REVISION} in labloop-weights-boltz"


@app.function(image=chai_image, volumes={CHAI_DIR: chai_volume}, gpu="H100", timeout=60 * 60)
def download_chai() -> str:
    """Fetch the listed weight files, then fold one short chain so any lazy download lands on the Volume."""
    import urllib.error
    import urllib.request

    for name in CHAI_FILES:
        target = CHAI_DIR / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".part")
            # The asset host refuses Python's default user agent with 403.
            request = urllib.request.Request(f"{CHAI_ASSETS}/{name}", headers={"User-Agent": "labloop/0.1"})
            try:
                with urllib.request.urlopen(request, timeout=600) as response, tmp.open("wb") as out:
                    while chunk := response.read(1 << 22):
                        out.write(chunk)
            except urllib.error.HTTPError as error:
                raise RuntimeError(f"{name}: HTTP {error.code}") from None
            tmp.replace(target)
    chai_volume.commit()
    _chai_predict({"chains": [{"id": "A", "sequence": "MKTAYIAKQRQISFVKSHFSRQ"}], "run_id": "warmup",
                   "step_id": "chai1"}, write=False)
    chai_volume.commit()
    return "chai-1 weights in labloop-weights-chai"


@app.local_entrypoint()
def download_all() -> None:
    calls = [download_esmfold.spawn(), download_boltz.spawn(), download_chai.spawn()]
    for call in calls:
        print(call.get())


# ------------------------------------------------------------------- models
@app.function(image=esm_image, gpu="A10G", volumes={ESM_DIR: esm_volume, ARTIFACTS: artifacts_volume},
              timeout=20 * 60, scaledown_window=300)
def esmfold(args: dict) -> dict:
    import torch
    from transformers import AutoTokenizer, EsmForProteinFolding

    from labloop.toolkit.structure import clean_sequence, safe_name

    started = time.time()
    sequence = clean_sequence(args["sequence"])
    if "esmfold" not in _MODELS:
        tokenizer = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
        model = EsmForProteinFolding.from_pretrained("facebook/esmfold_v1").cuda().eval()
        _MODELS["esmfold"] = (tokenizer, model)
    tokenizer, model = _MODELS["esmfold"]
    with torch.no_grad():
        batch = tokenizer([sequence], return_tensors="pt", add_special_tokens=False).to("cuda")
        output = model(**batch)
    pdb_text = model.output_to_pdb(output)[0]
    plddt = output["plddt"][0, :, 1].float()  # the CA atom of every residue
    mean_plddt = float(plddt.mean())
    if mean_plddt <= 1.0:
        mean_plddt *= 100.0
    out, rel = _out_dir(args, "esmfold")
    name = safe_name(args.get("name"), "esmfold")
    (out / f"{name}.pdb").write_text(pdb_text)
    import transformers

    return _result("esmfold", started, {"mean_plddt": round(mean_plddt, 3), "ptm": round(float(output["ptm"]), 4),
                                        "length": len(sequence)},
                   {"structure": rel / f"{name}.pdb"}, versions={"transformers": transformers.__version__})


@app.function(image=boltz_image, gpu="H100", volumes={BOLTZ_DIR: boltz_volume, ARTIFACTS: artifacts_volume},
              timeout=40 * 60)
def boltz2(args: dict) -> dict:
    import importlib.util

    from labloop.toolkit.structure import boltz_outputs, boltz_scores, boltz_yaml, normalise_chains, safe_name

    started = time.time()
    chains = normalise_chains(args["chains"])
    out, rel = _out_dir(args, "boltz2")
    name = safe_name(args.get("name"), "complex")
    spec = out / f"{name}.yaml"
    spec.write_text(boltz_yaml(chains))
    command = ["boltz", "predict", str(spec), "--cache", str(BOLTZ_DIR), "--out_dir", str(out),
               "--seed", str(int(args.get("seed", 0))),
               "--recycling_steps", str(int(args.get("recycling_steps", 3))),
               "--sampling_steps", str(int(args.get("sampling_steps", 200))),
               "--diffusion_samples", str(int(args.get("diffusion_samples", 1))),
               "--output_format", "mmcif", "--override"]
    if args.get("use_msa_server", True):
        command.append("--use_msa_server")
    if importlib.util.find_spec("cuequivariance_torch") is None:
        command.append("--no_kernels")
    log = subprocess.run(command, capture_output=True, text=True)
    (out / "boltz.log").write_text(log.stdout[-20000:] + "\n" + log.stderr[-20000:])
    if log.returncode != 0:
        artifacts_volume.commit()
        raise RuntimeError(f"boltz predict exited {log.returncode}: {log.stderr[-1500:]}")
    found = boltz_outputs(out, name)
    scores = {**boltz_scores(found["confidence"]), "n_chains": len(chains)}
    return _result("boltz2", started, scores,
                   {"structure": found["structure"].relative_to(ARTIFACTS),
                    "confidence": found["confidence"].relative_to(ARTIFACTS), "output_dir": rel},
                   versions={"boltz": "2.1.1", "weights_revision": BOLTZ_REVISION})


def _chai_predict(args: dict, write: bool = True) -> dict:
    import numpy as np
    from chai_lab.chai1 import run_inference

    from labloop.toolkit.structure import chai_fasta, normalise_chains, safe_name

    started = time.time()
    chains = normalise_chains(args["chains"])
    if write:
        out, rel = _out_dir(args, "chai1")
    else:
        out, rel = Path("/tmp/chai-warmup"), Path("warmup")
        out.mkdir(parents=True, exist_ok=True)
    name = safe_name(args.get("name"), "complex")
    fasta = out / f"{name}.fasta"
    fasta.write_text(chai_fasta(chains))
    predictions = out / "predictions"
    run_inference(fasta_file=fasta, output_dir=predictions,
                  num_trunk_recycles=int(args.get("num_trunk_recycles", 3)),
                  num_diffn_timesteps=int(args.get("num_diffn_timesteps", 200)),
                  seed=int(args.get("seed", 0)), device="cuda", use_esm_embeddings=True,
                  use_msa_server=bool(args.get("use_msa_server", False)))
    best, best_score, best_scores = None, float("-inf"), {}
    for npz in sorted(predictions.glob("scores.model_idx_*.npz")):
        scores = np.load(npz)
        aggregate = float(np.asarray(scores["aggregate_score"]).reshape(-1)[0])
        if aggregate > best_score:
            best, best_score = npz, aggregate
            best_scores = {"aggregate_score": aggregate,
                           "ptm": float(np.asarray(scores["ptm"]).reshape(-1)[0]),
                           "iptm": float(np.asarray(scores["iptm"]).reshape(-1)[0])}
    if best is None:
        raise RuntimeError("Chai-1 wrote no score files")
    index = best.name.split("model_idx_")[1].split(".")[0]
    structure = predictions / f"pred.model_idx_{index}.cif"
    return _result("chai1", started, {**best_scores, "n_chains": len(chains)},
                   {"structure": rel / "predictions" / structure.name, "scores": rel / "predictions" / best.name,
                    "output_dir": rel / "predictions"}, versions={"chai_lab": "0.5.0"}, commit=write)


@app.function(image=chai_image, gpu="H100", volumes={CHAI_DIR: chai_volume, ARTIFACTS: artifacts_volume},
              timeout=40 * 60)
def chai1(args: dict) -> dict:
    return _chai_predict(args)


# --------------------------------------------------------------------- data
@app.function(image=cpu_image, volumes={ARTIFACTS: artifacts_volume}, timeout=120)
def fetch_uniprot(args: dict) -> dict:
    from labloop.toolkit.data import fetch_uniprot as body

    started = time.time()
    result = body(args, ARTIFACTS)
    return {**result, "runtime_s": round(time.time() - started, 2), "versions": {}}


@app.function(image=cpu_image, volumes={ARTIFACTS: artifacts_volume}, timeout=120)
def fetch_pdb(args: dict) -> dict:
    from labloop.toolkit.data import fetch_pdb as body

    started = time.time()
    result = body(args, ARTIFACTS)
    artifacts_volume.commit()
    return {**result, "runtime_s": round(time.time() - started, 2), "versions": {}}


@app.function(image=cpu_image, timeout=300)
def literature_search(args: dict) -> dict:
    from labloop.toolkit.data import literature_search as body

    started = time.time()
    result = body(args)
    return {**result, "runtime_s": round(time.time() - started, 2), "versions": {}}


# -------------------------------------------------------------------- smoke
SMOKE_SEQUENCE = "GSHMKTAYIAKQRQISFVKSHFSRQLEERL"  # 30 residues


@app.local_entrypoint()
def smoke() -> None:
    result = esmfold.remote({"sequence": SMOKE_SEQUENCE, "run_id": "smoke", "step_id": "esmfold", "name": "smoke"})
    print(result)
    assert result["scores"]["length"] == len(SMOKE_SEQUENCE)
    assert 0 <= result["scores"]["mean_plddt"] <= 100

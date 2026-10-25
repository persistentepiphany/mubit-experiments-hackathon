# Demo videos

Two narrated recordings of the labloop website (`labloop/web/index.html`) for the Mubit hackathon, driven by Playwright against mocked API responses. No backend, Modal app, model call or real data is involved.

| File | Made with |
| --- | --- |
| `out/labloop-mubit-demo.mp4` | [video-demo](https://github.com/nilbuild/video-demo) scenes and explainers, joined with crossfades and framed in the style of [Recordly](https://github.com/webadderallorg/recordly) |
| `out/labloop-mubit-ndemo.mp4` | an [ndemo](https://github.com/splitbrain/ndemo) playbook, about a minute long |

## The story

The video follows the sequence labloop's README reports from its real runs, with invented data around it.

1. What labloop is, and how it uses Mubit: five agents (the planner and reviewer on Claude Opus 5, three helpers on Claude Haiku 5.5) whose every call goes through the Mubit gateway, filed under its run; and Mubit memory, where the reviewer writes lessons after a run, the planner recalls them before the next, and `record_outcome` marks the ones that led to a pass.
2. Run 1 folds a 30-residue chain from the "Fold a protein" template. Nothing is recalled and no skill fits, so it researches and plans from scratch, freezes the check `ptm >= 0.5`, and fails it with pTM 0.494.
3. The reviewer's lesson, that 0.5 is too strict for so short a chain, is written to Mubit memory.
4. Run 2 is the same task. The activity log shows one lesson recalled, the planner freezes a floor of 0.3, the run passes, and the pipeline is saved as a skill.
5. Run 3 folds Trp-cage, a different 20-residue protein. It matches the skill, skips research and planning, passes, and the skill becomes validated.

Callouts on the website mark where Mubit acts (`get_context`, `remember`, `record_outcome`, and the planner's calls through the gateway).

## Layout

| Path | Content |
| --- | --- |
| `video/script.ts` | Every line of narration, in order. |
| `video/scenes/` | The nine scenes: four explainers (`viz-*`) and five on the website. |
| `video/viz/` | The explainer pages, in the website's palette and type, stepped forward by the scenes. |
| `video/mock.ts`, `video/seed/world.ts` | Every API response, and the three runs with their activity events in the formats `orchestrator.py` and `research.py` emit. |
| `video/ui.ts` | Locators, the Mubit callouts, and the helper that plays a line over a gesture. |
| `video/prevoice.mjs` | Voices every line before filming. |
| `video/demo.config.ts` | The video-demo workspace config. |
| `compose.py` | Checks that no narration overlaps, frames the website scenes on a Recordly wallpaper, and joins all scenes with crossfades. |
| `patches/video-demo.patch` | Makes video-demo hold each line for its real spoken length, and write each clip's narration timeline. |
| `mock-server.mjs` | The website and the same mocked API as a local server whose runs advance on a timer. ndemo uses it. |
| `ndemo/` | The ndemo playbook, and `voice.mjs`, which voices it locally so ndemo needs no OpenAI key. |
| `setup.sh`, `record.sh` | Fetch the tools at pinned commits, then record both cuts. |

## Recording

```bash
demo/setup.sh     # clones the three tools into demo/.tools, installs Chromium and the Kokoro voice (~350 MB)
demo/record.sh    # writes both videos to demo/out; ONLY=tour or ONLY=ndemo records one
```

To click through the mocked website, run `node demo/mock-server.mjs` and open http://127.0.0.1:8765/. `curl -X POST localhost:8765/__reset` starts again.

## Narration

The voice is Kokoro (`af_heart`, speed 1.1), run locally. video-demo paces each line by an estimate of 3.7 words a second, but this voice speaks at about 2.3, so a long line used to run into the next one. `prevoice.mjs` synthesises every line first, the patched engine then holds each line for its real length plus 0.45 seconds, and `compose.py` refuses to build if any two lines still overlap or a line falls inside a transition. The script was edited against the [humanizer](https://github.com/blader/humanizer) rules, and the voiced lines were transcribed back with faster-whisper to check pronunciation.

## Known limits

- Mubit memory here is the design in `labloop/memory.py`. labloop's README notes that its real runs could not reach the Mubit memory API and fell back to the local copy, while model calls did go through the gateway.
- On a four-core container the screencast delivers about 30 to 40 painted frames per second during camera moves, encoded at 60 fps, so zooms show slight judder.
- ndemo rewrites its playbook when it renders, adding `audioDuration` to each segment and dropping comments.

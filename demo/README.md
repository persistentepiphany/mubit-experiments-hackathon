# Demo videos

Recordings of the labloop website (`labloop/web/index.html`) for the Mubit hackathon, driven by Playwright against mocked API responses. No backend, Modal app, model call or real data is involved.

| File | Made with |
| --- | --- |
| `out/labrat.mp4` | The current cut: two minutes, captions, no voice-over, centred on Mubit's role in each run's memory. [video-demo](https://github.com/nilbuild/video-demo) scenes and explainers, joined with crossfades and framed in the style of [Recordly](https://github.com/webadderallorg/recordly). |
| `out/labloop-mubit-demo.mp4` | An earlier narrated cut (3:16), from commit 6497fb1. |
| `out/labloop-mubit-ndemo.mp4` | A one-minute narrated cut from an [ndemo](https://github.com/splitbrain/ndemo) playbook. |

## The story

The film follows the sequence labloop's README reports from its real runs, with invented data around it.

1. How labloop uses Mubit: five agents, each a fixed role with its own prompt, whose every call goes through the Mubit gateway and is recorded under its role and its run; and Mubit memory, where the reviewer writes lessons after a run, the planner recalls them before the next, and `record_outcome` marks the ones that led to a pass.
2. Run 1 folds a 30-residue chain from the "Fold a protein" template. Nothing is recalled, so it plans from scratch. The planner, called through the gateway, freezes the check `ptm >= 0.5`; the predicted structure appears in the 3D viewer and spins; the checks chart shows pTM 0.494 just under the threshold.
3. The reviewer's correction, that 0.5 is too strict for so short a chain, is written to Mubit memory.
4. Run 2 is the same task. One lesson is recalled, the planner freezes a floor of 0.3, the run passes, the pipeline is saved as a skill, and Mubit records that the lesson worked.
5. Run 3 folds Trp-cage, a different 20-residue protein. The "Skill invoked" card shows the matched condition, research and planning are skipped, and the skill becomes validated.
6. The close: one correction became a reusable skill; each role builds its own recorded history and its model is one setting; new proteins and papers keep adding lessons for the next run.

Callouts on the website mark where Mubit acts (`get_context`, `remember`, `record_outcome`, and the planner's calls through the gateway).

## Layout

| Path | Content |
| --- | --- |
| `video/script.ts` | Every caption, in order. |
| `video/scenes/` | The eight scenes: three explainers (`viz-*`) and five on the website. |
| `video/viz/` | The explainer pages, in the website's palette and type, stepped forward by the scenes. |
| `video/mock.ts`, `video/seed/world.ts` | Every API response, and the three runs with their activity events in the formats `orchestrator.py` and `research.py` emit. |
| `video/seed/make_structures.py`, `video/seed/artifacts/` | The mocked ESMFold structures: an ideal model of the 30-residue chain, and the first NMR model of Trp-cage (PDB 1L2Y), each with a per-residue confidence in the B-factor column. |
| `video/seed/fetch_papers.py` | Freezes the three real papers the research step cites (Lin et al. 2023, Jumper et al. 2021, Xu and Zhang 2010), titles and abstracts from Europe PMC, at setup. |
| `video/seed/make_reports.py`, `video/seed/reports/` | Each run's report, built by labloop's own `reporting.build_report` from the mocked bundle and structures. |
| `video/ui.ts` | Locators, the Mubit callouts, and the helper that plays a line over a gesture. |
| `video/prevoice.mjs` | Voices every line before filming; the voice only times how long each caption stays up. |
| `video/demo.config.ts` | The video-demo workspace config. |
| `compose.py` | Checks that no two lines overlap, speeds up long silent stretches, frames every scene on a Recordly wallpaper with a band for captions, joins the scenes with crossfades, and burns in the captions. |
| `patches/video-demo.patch` | Makes video-demo hold each line for its real spoken length, write each clip's narration timeline, and zoom correctly on a scrolled page. |
| `mock-server.mjs` | The website and the same mocked API as a local server whose runs advance on a timer. ndemo uses it. |
| `ndemo/` | The ndemo playbook, and `voice.mjs`, which voices it locally so ndemo needs no OpenAI key. |
| `setup.sh`, `record.sh` | Fetch the tools at pinned commits, then record both cuts. |

## Recording

```bash
demo/setup.sh     # clones the three tools into demo/.tools, installs Chromium and the Kokoro voice (~350 MB)
demo/record.sh    # writes both videos to demo/out; ONLY=tour or ONLY=ndemo records one
```

To click through the mocked website, run `node demo/mock-server.mjs` and open http://127.0.0.1:8765/. `curl -X POST localhost:8765/__reset` starts again.

## Captions

The film has no voice-over. Each caption is still synthesised with Kokoro before filming, and the patched engine holds every line for as long as it takes to say, which is a comfortable reading time; `compose.py` then drops the audio and burns the lines in below the window, each staying up a little after its line ends. Silent stretches between lines longer than 1.2 seconds play faster, up to three times, so scrolling and clicking never leave long dead air. The captions were edited against the [humanizer](https://github.com/blader/humanizer) rules.

## Known limits

- The structures and reports are made for the demo, not by ESMFold or a real run. Headless Chromium renders the 3D viewer in software, so after its shot each scene swaps the live viewer for a still of the same render to keep the capture smooth.
- On the run page, each output row that links to a paper carries two `class` attributes (`out` and `paperlink`), so the browser drops `paperlink`. Clicking still opens the reader, because its handler looks for `[data-paper]`.

- Mubit memory here is the design in `labloop/memory.py`. labloop's README notes that its real runs could not reach the Mubit memory API and fell back to the local copy, while model calls did go through the gateway.
- On a four-core container the screencast delivers about 30 to 40 painted frames per second during camera moves, encoded at 60 fps, so zooms show slight judder.
- ndemo rewrites its playbook when it renders, adding `audioDuration` to each segment and dropping comments.

# Demo videos

Two narrated recordings of Folio, labloop's web frontend (`labloop/web/index.html`), driven by Playwright against mocked API responses. No backend, Modal app, model call or real data is involved.

| File | Length | Made with |
| --- | --- | --- |
| `out/labloop-folio-demo.mp4` | about 2 min | [video-demo](https://github.com/nilbuild/video-demo) scenes, framed in the style of [Recordly](https://github.com/webadderallorg/recordly) |
| `out/labloop-folio-ndemo.mp4` | about 1 min | an [ndemo](https://github.com/splitbrain/ndemo) playbook |

## The story

Both cuts follow the same two runs:

1. The home page, with the composer, the templates and the saved skills.
2. The "Fold a UniProt entry" template with human lysozyme (P61626). No saved skill fits, and the match step says why.
3. Research: two Europe PMC queries, with two papers frozen into the run.
4. Plan and freeze: `fetch_uniprot → esmfold` with three acceptance checks, frozen under a SHA-256 digest.
5. Run, grade and learn: the checks pass, the reviewer writes a summary and lessons, and the pipeline is saved as the draft skill `uniprot_monomer_fold`.
6. A second task in plain words, for human myoglobin (P02144). The match step reuses the skill and quotes its `applies_when` condition, research and planning are skipped, the run passes, and the skill becomes validated.
7. The skill page: its conditions, its evidence, and the form to run it again.

The mocked responses follow the shapes written by `labloop/api.py`, `research.py`, `grading.py` and `orchestrator.py`, including `GET /runs`, `results.counts`, and the `summary` and `lesson_texts` fields on the status. All names, scores and run ids are invented.

## Layout

| Path | Content |
| --- | --- |
| `video/demo.config.ts` | The video-demo workspace config. The build copies Folio into place, and each entry opens the app at one chapter of the story. |
| `video/mock.ts` | Answers every request Folio makes inside Playwright, and lets a scene move a run to its next phase. |
| `video/seed/world.ts` | The invented lab: two earlier skills, four earlier runs, and the two runs the demo performs. |
| `video/seed/fonts/` | Folio's two Google Fonts (Instrument Serif and Geist, both OFL), served locally so filming needs no network. |
| `video/scenes/` | The seven scenes, with their narration. |
| `video/ui.ts` | Locators for Folio, and the helper that plays a line over a gesture. |
| `frame.py` | Places the stitched tour on a blurred Recordly wallpaper with padding, rounded corners and a shadow. |
| `mock-server.mjs` | Folio and the same mocked API as a real local server, with runs that advance on a timer. ndemo uses it, and so can a person. |
| `ndemo/folio-tour/folio-tour.yaml` | The ndemo playbook. |
| `ndemo/voice.mjs` | Voices the playbook with the local Kokoro model, so ndemo needs no OpenAI key. |
| `setup.sh`, `record.sh` | Fetch the tools at pinned commits, then record both cuts. |

## Recording

```bash
demo/setup.sh     # clones the three tools into demo/.tools, installs Chromium and the Kokoro voice (~350 MB)
demo/record.sh    # writes both videos to demo/out; ONLY=tour or ONLY=ndemo records one
```

To click through the mocked app by hand, run `node demo/mock-server.mjs` and open http://127.0.0.1:8765/. `curl -X POST localhost:8765/__reset` starts again.

## How each tool is used

**video-demo** builds and pins the app, mocks every request in-process, pins the clock, and films each scene through a CDP screencast with an eased cursor, push-in zoom on the subject of each line, and a local Kokoro voice. It then stitches the scenes into `full-tour.mp4`. Folio is filmed at 1280×720 and captured at 1.25×, so the tour is 1600×900.

**Recordly** is a desktop recorder and editor whose frame styling (a wallpaper, padding, rounded corners and a shadow) is what makes its exports look finished. It needs a desktop session, so `frame.py` reproduces that frame with ffmpeg, on Recordly's own `farmvalley` wallpaper, and outputs 1920×1080 at 60 fps.

**ndemo** plays a YAML playbook of narrated segments in a real browser and merges the result with the narration. It synthesises speech through OpenAI unless the audio file for a segment already exists, so `voice.mjs` writes those files with the same Kokoro voice first.

## Known limits

- On a four-core container the screencast delivers about 30 to 40 painted frames per second during camera moves. The video is encoded at 60 fps, so zooms show slight judder. A faster machine, or `DEMO_VIDEO_SCALE=1`, gives smoother motion.
- Folio polls a running run every 2.5 seconds. The scenes trigger a re-render when they advance a run, so the screen changes on the narrated beat. The ndemo cut runs against the timer-driven server and relies on Folio's own polling.
- ndemo rewrites the playbook when it renders, adding `audioDuration` to each segment and dropping comments.

#!/usr/bin/env node
/**
 * the labloop website with a mocked API behind it, as one local HTTP server.
 *
 * The video-demo film answers requests inside Playwright, but ndemo (and a
 * person clicking around) needs a real URL. This serves labloop/web/index.html
 * at / and answers /tasks, /runs, /runs/{id}, /skills, /skills/{name}, /knowledge and /jobs from
 * the same invented world as demo/video/seed/world.ts. Submitted runs advance
 * through their phases on a timer, the way the orchestrator would.
 *
 *     node demo/mock-server.mjs [port]          # default 8765
 *     curl -X POST localhost:8765/__reset       # back to an empty lab
 */

import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';

import { PHASES_A, PHASES_C, RUN_A, RUN_B, RUN_C, TRP_CAGE, card, runA, runB, runC, runList, skills } from './video/seed/world.ts';

const ROOT = join(import.meta.dirname, '..');
const PORT = Number(process.argv[2] ?? 8765);

/** Seconds after submission at which each phase is reached. */
const SCHEDULE_AB = { queued: 0, match: 0.5, research: 2, plan: 4, freeze: 6, run: 7, run2: 8.5, grade: 9.5, learn: 10, done: 10.5 };
const SCHEDULE_C = { queued: 0, match: 0.5, freeze: 2, run: 3, run2: 4.5, grade: 5.5, learn: 6, done: 6.5 };

let submitted = { a: null, b: null, c: null };

function phaseOf(started, phases, schedule) {
  if (started === null) return 'none';
  const elapsed = (Date.now() - started) / 1000;
  let reached = 'queued';
  for (const phase of phases) if (phase !== 'none' && schedule[phase] <= elapsed) reached = phase;
  return reached;
}

const state = () => ({
  a: phaseOf(submitted.a, PHASES_A, SCHEDULE_AB),
  b: phaseOf(submitted.b, PHASES_A, SCHEDULE_AB),
  c: phaseOf(submitted.c, PHASES_C, SCHEDULE_C),
});

function send(res, status, body, type = 'application/json') {
  res.writeHead(status, { 'content-type': type, 'cache-control': 'no-cache' });
  res.end(type === 'application/json' ? JSON.stringify(body) : body);
}

async function body(req) {
  let text = '';
  for await (const chunk of req) text += chunk;
  return text ? JSON.parse(text) : {};
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;
  const { a, b, c } = state();

  try {
    if (req.method === 'GET' && path === '/') {
      return send(res, 200, await readFile(join(ROOT, 'labloop/web/index.html'), 'utf8'), 'text/html');
    }
    if (req.method === 'POST' && path === '/__reset') {
      submitted = { a: null, b: null, c: null };
      return send(res, 200, { ok: true });
    }
    if (req.method === 'POST' && path === '/tasks') {
      const task = await body(req);
      const which = task.inputs?.sequence === TRP_CAGE ? 'c' : submitted.a === null ? 'a' : 'b';
      submitted[which] = Date.now();
      return send(res, 202, { run_id: { a: RUN_A, b: RUN_B, c: RUN_C }[which], phase: 'queued' });
    }
    if (req.method === 'GET' && path === '/runs') return send(res, 200, { runs: runList(a, b, c) });
    if (req.method === 'GET' && path.startsWith('/runs/')) {
      const id = path.split('/')[2];
      const now = new Date();
      const doc = id === RUN_A ? runA(a, now) : id === RUN_B ? runB(b, now) : id === RUN_C ? runC(c, now) : null;
      return doc ? send(res, 200, doc) : send(res, 404, { detail: 'unknown run' });
    }
    if (req.method === 'GET' && path === '/skills') return send(res, 200, { skills: skills(b, c).map(card) });
    if (req.method === 'GET' && path.startsWith('/skills/')) {
      const skill = skills(b, c).find((s) => s.name === path.split('/')[2]);
      return skill ? send(res, 200, { card: card(skill), skill }) : send(res, 404, { detail: 'unknown skill' });
    }
    if (req.method === 'GET' && path === '/knowledge') return send(res, 200, { tools: [] });
    if (req.method === 'GET' && path === '/jobs') return send(res, 200, { jobs: [] });
    send(res, 404, { detail: 'not found' });
  } catch (error) {
    send(res, 500, { detail: String(error) });
  }
}).listen(PORT, '127.0.0.1', () => {
  process.stdout.write(`the labloop website with a mocked API: http://127.0.0.1:${PORT}/\n`);
});

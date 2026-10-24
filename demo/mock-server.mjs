#!/usr/bin/env node
/**
 * Folio with a mocked labloop API behind it, as one local HTTP server.
 *
 * The video-demo film answers requests inside Playwright, but ndemo (and a
 * person clicking around) needs a real URL. This serves labloop/web/index.html
 * at / and answers /tasks, /runs, /runs/{id}, /skills and /skills/{name} from
 * the same invented world as demo/video/seed/world.ts. Submitted runs advance
 * through their phases on a timer, the way the orchestrator would.
 *
 *     node demo/mock-server.mjs [port]          # default 8765
 *     curl -X POST localhost:8765/__reset       # back to an empty lab
 */

import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';

import { PHASES_A, PHASES_B, RUN_A, RUN_B, card, runA, runB, runList, skills } from './video/seed/world.ts';

const ROOT = join(import.meta.dirname, '..');
const PORT = Number(process.argv[2] ?? 8765);

/** Seconds after submission at which each phase is reached. */
const SCHEDULE_A = { queued: 0, match: 0.5, research: 2, plan: 4, freeze: 6, run: 7, run2: 8.5, grade: 9.5, learn: 10, done: 10.5 };
const SCHEDULE_B = { queued: 0, match: 0.5, freeze: 2, run: 3, run2: 4.5, grade: 5.5, learn: 6, done: 6.5 };

let submitted = { a: null, b: null };

function phaseOf(started, phases, schedule) {
  if (started === null) return 'none';
  const elapsed = (Date.now() - started) / 1000;
  let reached = 'queued';
  for (const phase of phases) if (phase !== 'none' && schedule[phase] <= elapsed) reached = phase;
  return reached;
}

const state = () => ({
  a: phaseOf(submitted.a, PHASES_A, SCHEDULE_A),
  b: phaseOf(submitted.b, PHASES_B, SCHEDULE_B),
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
  const { a, b } = state();

  try {
    if (req.method === 'GET' && path === '/') {
      return send(res, 200, await readFile(join(ROOT, 'labloop/web/index.html'), 'utf8'), 'text/html');
    }
    if (req.method === 'POST' && path === '/__reset') {
      submitted = { a: null, b: null };
      return send(res, 200, { ok: true });
    }
    if (req.method === 'POST' && path === '/tasks') {
      const task = await body(req);
      const isB = /myoglobin/i.test(task.description ?? '');
      submitted[isB ? 'b' : 'a'] = Date.now();
      return send(res, 202, { run_id: isB ? RUN_B : RUN_A, phase: 'queued' });
    }
    if (req.method === 'GET' && path === '/runs') return send(res, 200, { runs: runList(a, b) });
    if (req.method === 'GET' && path.startsWith('/runs/')) {
      const id = path.split('/')[2];
      const doc = id === RUN_A ? runA(a) : id === RUN_B ? runB(b) : null;
      return doc ? send(res, 200, doc) : send(res, 404, { detail: 'unknown run' });
    }
    if (req.method === 'GET' && path === '/skills') return send(res, 200, { skills: skills(a, b).map(card) });
    if (req.method === 'GET' && path.startsWith('/skills/')) {
      const skill = skills(a, b).find((s) => s.name === path.split('/')[2]);
      return skill ? send(res, 200, { card: card(skill), skill }) : send(res, 404, { detail: 'unknown skill' });
    }
    send(res, 404, { detail: 'not found' });
  } catch (error) {
    send(res, 500, { detail: String(error) });
  }
}).listen(PORT, '127.0.0.1', () => {
  process.stdout.write(`Folio with a mocked labloop API: http://127.0.0.1:${PORT}/\n`);
});

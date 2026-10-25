import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

import type { Page, Route } from '@playwright/test';

import type { MockContext } from 'video-demo/define';

import type { PhaseA, PhaseC } from './seed/world.ts';
import { RUN_A, RUN_B, RUN_C, TRP_CAGE, card, runA, runB, runC, runList, skills } from './seed/world.ts';

/**
 * Every labloop API request the website makes, answered in this process.
 *
 * The website calls the API on its own origin (`/tasks`, `/runs`, `/skills`,
 * `/knowledge`, `/jobs`), so the handlers match those paths and let the page
 * and the explainer pages under /viz through. The world is three runs whose
 * progress the scene drives: `lab.a(...)`, `lab.b(...)` and `lab.c(...)` move
 * a run to a phase at the moment the narration reaches it.
 */

export type Lab = {
  a: (phase: PhaseA) => Promise<void>;
  b: (phase: PhaseA) => Promise<void>;
  c: (phase: PhaseC) => Promise<void>;
};

type State = { a: PhaseA; b: PhaseA; c: PhaseC };

const START: Record<string, State> = {
  app: { a: 'none', b: 'none', c: 'none' },
  run1: { a: 'match', b: 'none', c: 'none' },
  lesson: { a: 'done', b: 'none', c: 'none' },
  run2: { a: 'done', b: 'none', c: 'none' },
  reuse: { a: 'done', b: 'done', c: 'none' },
};

const FONTS = join(import.meta.dirname, 'seed', 'fonts');

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

const tail = (route: Route) => new URL(route.request().url()).pathname.split('/').pop() ?? '';

export async function mock(page: Page, ctx: MockContext): Promise<Lab> {
  const state: State = { ...(START[ctx.entry] ?? START.app!) };

  // The website's two Google Fonts, served from seed/fonts so filming needs no network.
  await page.route('https://fonts.googleapis.com/**', async (route) =>
    route.fulfill({ contentType: 'text/css', body: await readFile(join(FONTS, 'fonts.css'), 'utf8') })
  );
  await page.route('https://fonts.gstatic.com/demo/*', async (route) =>
    route.fulfill({ contentType: 'font/woff2', body: await readFile(join(FONTS, tail(route))) })
  );

  await page.route(/\/tasks$/, (route) => {
    const body = route.request().postDataJSON() as { inputs?: { sequence?: string } };
    let id = RUN_A;
    if (body.inputs?.sequence === TRP_CAGE) {
      state.c = 'queued';
      id = RUN_C;
    } else if (state.a === 'none') {
      state.a = 'queued';
    } else {
      state.b = 'queued';
      id = RUN_B;
    }
    return json(route, { run_id: id, phase: 'queued' }, 202);
  });

  await page.route(/\/runs(\?.*)?$/, (route) => json(route, { runs: runList(state.a, state.b, state.c) }));

  await page.route(/\/runs\/r-[0-9a-f-]+$/, (route) => {
    const id = tail(route);
    const now = ctx.reference;
    const doc = id === RUN_A ? runA(state.a, now) : id === RUN_B ? runB(state.b, now) : id === RUN_C ? runC(state.c, now) : null;
    return doc ? json(route, doc) : json(route, { detail: 'unknown run' }, 404);
  });

  await page.route(/\/skills(\?.*)?$/, (route) => json(route, { skills: skills(state.b, state.c).map(card) }));

  await page.route(/\/skills\/[a-z0-9_]+$/, (route) => {
    const skill = skills(state.b, state.c).find((s) => s.name === tail(route));
    return skill ? json(route, { card: card(skill), skill }) : json(route, { detail: 'unknown skill' }, 404);
  });

  await page.route(/\/knowledge$/, (route) => json(route, { tools: [] }));
  await page.route(/\/jobs$/, (route) => json(route, { jobs: [] }));

  /**
   * The website polls a running run every 2.5 seconds. A scene moves the
   * world and then nudges the router, so the page re-renders on the beat the
   * narration is about instead of up to 2.5 seconds later.
   */
  const nudge = () => page.evaluate(() => window.dispatchEvent(new HashChangeEvent('hashchange')));

  return {
    a: async (phase) => {
      state.a = phase;
      await nudge();
    },
    b: async (phase) => {
      state.b = phase;
      await nudge();
    },
    c: async (phase) => {
      state.c = phase;
      await nudge();
    },
  };
}

import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

import type { Page, Route } from '@playwright/test';

import type { MockContext } from 'video-demo/define';

import type { PhaseA, PhaseB } from './seed/world.ts';
import { RUN_A, RUN_B, card, runA, runB, runList, skills } from './seed/world.ts';

/**
 * Every labloop API request Folio makes, answered in this process.
 *
 * Folio calls the API on its own origin (`/tasks`, `/runs`, `/skills`), so
 * the handlers match those paths and let the page itself through. The world
 * is two runs whose progress the scene drives: `lab.a(...)` and `lab.b(...)`
 * move a run to a phase at the moment the narration reaches it.
 */

export type Lab = {
  a: (phase: PhaseA) => Promise<void>;
  b: (phase: PhaseB) => Promise<void>;
};

const START: Record<string, { a: PhaseA; b: PhaseB }> = {
  app: { a: 'none', b: 'none' },
  research: { a: 'research', b: 'none' },
  plan: { a: 'plan', b: 'none' },
  grade: { a: 'run', b: 'none' },
  reuse: { a: 'done', b: 'none' },
  skill: { a: 'done', b: 'done' },
};

const FONTS = join(import.meta.dirname, 'seed', 'fonts');

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

const tail = (route: Route) => new URL(route.request().url()).pathname.split('/').pop() ?? '';

export async function mock(page: Page, ctx: MockContext): Promise<Lab> {
  const state = { ...(START[ctx.entry] ?? START.app!) };

  // Folio's two Google Fonts, served from seed/fonts so the film needs no network.
  await page.route('https://fonts.googleapis.com/**', async (route) =>
    route.fulfill({ contentType: 'text/css', body: await readFile(join(FONTS, 'fonts.css'), 'utf8') })
  );
  await page.route('https://fonts.gstatic.com/demo/*', async (route) =>
    route.fulfill({ contentType: 'font/woff2', body: await readFile(join(FONTS, tail(route))) })
  );

  await page.route(/\/tasks$/, (route) => {
    const body = route.request().postDataJSON() as { description: string };
    const isB = /myoglobin/i.test(body.description);
    if (isB) state.b = 'queued';
    else state.a = 'queued';
    return json(route, { run_id: isB ? RUN_B : RUN_A, phase: 'queued' }, 202);
  });

  await page.route(/\/runs(\?.*)?$/, (route) => json(route, { runs: runList(state.a, state.b) }));

  await page.route(/\/runs\/r-[0-9a-f-]+$/, (route) => {
    const id = tail(route);
    const doc = id === RUN_A ? runA(state.a) : id === RUN_B ? runB(state.b) : null;
    return doc ? json(route, doc) : json(route, { detail: 'unknown run' }, 404);
  });

  await page.route(/\/skills(\?.*)?$/, (route) => json(route, { skills: skills(state.a, state.b).map(card) }));

  await page.route(/\/skills\/[a-z0-9_]+$/, (route) => {
    const skill = skills(state.a, state.b).find((s) => s.name === tail(route));
    return skill ? json(route, { card: card(skill), skill }) : json(route, { detail: 'unknown skill' }, 404);
  });

  /**
   * Folio polls a running run every 2.5 seconds. A scene moves the world and
   * then nudges the router, so the page re-renders on the beat the narration
   * is about instead of up to 2.5 seconds later.
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
  };
}

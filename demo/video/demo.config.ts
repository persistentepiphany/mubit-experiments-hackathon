import type { Page } from '@playwright/test';

import { defineDemo } from 'video-demo/define';

/**
 * The labloop website (labloop/web/index.html) and four explainer pages
 * (viz/), filmed against mocked API responses. The website is one static page
 * that calls the API on its own origin, so the "build" copies it and the
 * explainers into place. Each entry opens a chapter of the story; mock.ts
 * reads the entry name to decide how far the three runs have got.
 */

const RUN_A = 'r-20261021-150212-5d8e3a';

/** The website has no loaded flag: its heading renders after the data arrives. */
const site = async (page: Page) => {
  await page.locator('#view h1').first().waitFor({ state: 'visible' });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
};

const explainer = async (page: Page) => {
  await page.waitForFunction(() => 'viz' in window);
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
};

export default defineDemo({
  name: 'labloop-mubit',

  build: {
    command:
      'mkdir -p demo/.folio && cp labloop/web/index.html demo/.folio/index.html && rm -rf demo/.folio/viz && cp -r demo/video/viz demo/.folio/viz',
    output: 'demo/.folio',
    forbid: ['api.mubit.ai/anthropic', '.modal.run'],
  },

  // The website's content column is about 1240px wide, so everything is
  // filmed at 1280x720 and scaled up by DEMO_VIDEO_SCALE when captured.
  stage: { width: 1280, height: 720 },

  clock: {
    anchor: '2026-10-21T16:06:00.000Z',
    timezone: 'UTC',
    locale: 'en-US',
  },

  themes: ['light'],

  entries: {
    app: { path: '/', ready: site },
    run1: { path: `/#/runs/${RUN_A}`, ready: site },
    lesson: { path: `/#/runs/${RUN_A}`, ready: site },
    run2: { path: '/', ready: site },
    reuse: { path: '/', ready: site },
    'viz-intro': { path: '/viz/intro.html', ready: explainer },
    'viz-mubit': { path: '/viz/mubit.html', ready: explainer },
    'viz-memory': { path: '/viz/memory.html', ready: explainer },
    'viz-outro': { path: '/viz/outro.html', ready: explainer },
  },

  mock: (page, ctx) => import('./mock.ts').then((made) => made.mock(page, ctx)),

  voice: {
    name: 'af_heart',
    speed: 1.1,
    saidAs: [
      [/\bMubit\b/g, 'Mew-bit'],
      [/\bESMFold\b/g, 'E S M fold'],
      [/\bpTM\b/g, 'P T M'],
      [/\b3D\b/g, 'three D'],
    ],
  },

  tour: ['viz-intro', 'viz-mubit', 'task', 'run1', 'lesson', 'viz-memory', 'run2', 'reuse', 'viz-outro'],
});

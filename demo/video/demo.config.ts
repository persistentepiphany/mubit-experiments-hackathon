import type { Page } from '@playwright/test';

import { defineDemo } from 'video-demo/define';

/**
 * Folio, labloop's web frontend (labloop/web/index.html), filmed against
 * mocked API responses. Folio is one static page that calls the API on its
 * own origin, so the "build" is copying that page into place. Each entry
 * opens the app at a different chapter of the story; mock.ts reads the entry
 * name to decide how far the two runs have got.
 */

const RUN_A = 'r-20261021-150212-5d8e3a';

/** Folio has no loaded flag: its heading renders after the data arrives. */
const loaded = async (page: Page) => {
  await page.locator('#view h1').first().waitFor({ state: 'visible' });
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
};

export default defineDemo({
  name: 'labloop-folio',

  build: {
    command: 'mkdir -p demo/.folio && cp labloop/web/index.html demo/.folio/index.html',
    output: 'demo/.folio',
    forbid: ['api.mubit.ai', '.modal.run'],
  },

  // Folio's content column is about 1240px wide, so it is filmed at 720p and
  // the capture is scaled 1.5x (DEMO_VIDEO_SCALE) to a 1080p video.
  stage: { width: 1280, height: 720 },

  clock: {
    anchor: '2026-10-21T15:02:00.000Z',
    timezone: 'UTC',
    locale: 'en-US',
  },

  themes: ['light'],

  entries: {
    app: { path: '/', ready: loaded },
    research: { path: `/#/runs/${RUN_A}`, ready: loaded },
    plan: { path: `/#/runs/${RUN_A}`, ready: loaded },
    grade: { path: `/#/runs/${RUN_A}`, ready: loaded },
    reuse: { path: '/', ready: loaded },
    skill: { path: '/#/skills/uniprot_monomer_fold', ready: loaded },
  },

  mock: (page, ctx) => import('./mock.ts').then((made) => made.mock(page, ctx)),

  voice: { name: 'af_heart', speed: 1, saidAs: [[/\blabloop\b/gi, 'lab loop']] },

  tour: ['home', 'submit', 'research', 'plan', 'grade', 'reuse', 'skill'],
});

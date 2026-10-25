import type { Page } from '@playwright/test';

import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { scrollTo } from '../ui.ts';

const L = LINES.report;

/** A section of the report by its heading. */
const section = async (page: Page, heading: string) =>
  page.locator('section.card', { has: page.locator('h2', { hasText: heading }) });

/** Waits for a section's lazy-loaded figures. */
const figures = (page: Page, heading: string) =>
  page
    .locator('section.card', { has: page.locator('h2', { hasText: heading }) })
    .locator('img')
    .evaluateAll((imgs) =>
      Promise.all((imgs as HTMLImageElement[]).map((i) => (i.complete ? 0 : new Promise((done) => (i.onload = done)))))
    );

scene('report', { title: 'The run report', blurb: 'Written from the run records by labloop/reporting.py.', entry: 'report' }, async ({ actor, page }) => {
  await actor.beat(500);
  await actor.spotlight(await section(page, 'Outcome'), L[0], { scale: 1.3 });
  await scrollTo(actor, page, await section(page, 'How the pipeline was chosen'), 40);
  await figures(page, 'How the pipeline was chosen');
  await figures(page, 'Metrics');
  await actor.settle();
  await actor.say(L[1]);
  await scrollTo(actor, page, await section(page, 'Structure'), 30);
  await figures(page, 'Structure');
  await actor.settle();
  await actor.spotlight(await section(page, 'Structure'), L[2], { scale: 1.2, stay: true });
  await actor.unfocus();
});

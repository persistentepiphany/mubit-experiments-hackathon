import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { callout, clearCallouts, freezeStructures, scrollTo, sideCard } from '../ui.ts';

const L = LINES.lesson;

scene('lesson', { title: 'The lesson', blurb: 'The reviewer explains the failure.', entry: 'lesson' }, async ({ actor, page }) => {
  await page.locator('[data-mol] canvas').waitFor();
  await freezeStructures(page);
  await actor.beat(500);
  await scrollTo(actor, page, sideCard(page, 'Summary'), 170);
  await actor.settle();
  await callout(page, sideCard(page, 'Summary'), 'Mubit memory · remember()', 'above');
  await actor.spotlight(sideCard(page, 'Summary'), L[0], { scale: 1.45, stay: true });
  await clearCallouts(page);
  await actor.unfocus();
});

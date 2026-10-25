import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { lab } from '../ui.ts';

const L = LINES.task;

scene('task', { title: 'A task', blurb: 'Fold a 30-residue chain from the template.' }, async ({ actor, page, server }) => {
  const world = lab(server);
  await actor.beat(500);
  await actor.click(page.locator('[data-tpl="fold"]'));
  const input = page.locator('[data-param="sequence"]');
  await input.waitFor();
  await actor.scroll(page.locator('main'), 340);
  await actor.spotlight(input, L[0], { scale: 1.5 });
  await actor.click(page.locator('#runTpl'));
  await page.locator('h1.run').waitFor();
  await world.a('match');
  await actor.beat(600);
});

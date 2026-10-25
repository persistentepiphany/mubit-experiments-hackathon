import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { TRP_CAGE } from '../seed/world.ts';
import { freezeStructures, lab, scrollTo } from '../ui.ts';

const L = LINES.reuse;

scene('reuse', { title: 'Reuse', blurb: 'A different short protein uses the saved skill.', entry: 'reuse' }, async ({ actor, page, server }) => {
  const world = lab(server);
  await actor.beat(500);
  await actor.click(page.locator('[data-tpl="fold"]'));
  const input = page.locator('[data-param="sequence"]');
  await input.waitFor();
  await actor.scroll(page.locator('main'), 340);
  await actor.click(input);
  await input.selectText();
  await actor.type(TRP_CAGE, 45);
  await actor.spotlight(input, L[0], { scale: 1.6 });
  await actor.click(page.locator('#runTpl'));
  await page.locator('h1.run').waitFor();
  await world.c('match');
  await actor.beat(400);
  await world.c('freeze');
  const invoked = page.locator('.learned', { hasText: 'Skill invoked' });
  await invoked.waitFor();
  await scrollTo(actor, page, invoked, 210);
  await actor.settle();
  await actor.spotlight(invoked, L[1], { scale: 1.6 });
  await world.c('run');
  await world.c('run2');
  await page.locator('[data-mol] canvas').waitFor();
  await freezeStructures(page);
  await world.c('grade');
  await world.c('learn');
  await world.c('done');
  const saved = page.locator('.learned', { hasText: 'A saved skill did this work' });
  await saved.waitFor();
  await scrollTo(actor, page, saved, 230);
  await actor.settle();
  await actor.spotlight(saved, L[2], { scale: 1.6, stay: true });
  await actor.unfocus();
});

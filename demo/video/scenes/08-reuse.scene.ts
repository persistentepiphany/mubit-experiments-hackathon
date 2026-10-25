import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { TRP_CAGE } from '../seed/world.ts';
import { lab, learned, scrollTo, step } from '../ui.ts';

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
  await step(page, 'Match against skills').locator('.tag').waitFor();
  await actor.settle();
  await actor.spotlight(page.locator('.cols > div').first(), L[1], { scale: 1.3 });
  await world.c('run');
  await world.c('run2');
  await world.c('grade');
  await world.c('learn');
  await world.c('done');
  await learned(page).waitFor();
  await scrollTo(actor, page, learned(page), 230);
  await actor.settle();
  await actor.spotlight(learned(page), L[2], { scale: 1.6, stay: true });
  await actor.unfocus();
});

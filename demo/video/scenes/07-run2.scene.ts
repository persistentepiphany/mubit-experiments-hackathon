import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { activity, callout, clearCallouts, freezeStructures, lab, learned, overGesture, scrollTo, sideCard, untilSaid } from '../ui.ts';

const L = LINES.run2;

scene('run2', { title: 'Second run', blurb: 'The lesson is recalled, and the run passes.', entry: 'run2' }, async ({ actor, page, server }) => {
  const world = lab(server);
  await actor.beat(500);
  const said = overGesture(actor, L[0]);
  await actor.click(page.locator('[data-tpl="fold"]'));
  await page.locator('[data-param="sequence"]').waitFor();
  await actor.scroll(page.locator('main'), 340);
  await actor.click(page.locator('#runTpl'));
  await page.locator('h1.run').waitFor();
  await untilSaid(said);
  await world.b('match');
  await world.b('research');
  await activity(page, 'Recalled 1 lesson').waitFor();
  await actor.settle();
  await callout(page, activity(page, 'Recalled 1 lesson'), 'Mubit memory · get_context()', 'below');
  await actor.spotlight(sideCard(page, 'Activity'), L[1], { scale: 1.45 });
  await clearCallouts(page);
  await world.b('plan');
  await world.b('freeze');
  await world.b('run');
  await sideCard(page, 'Frozen checks').waitFor();
  await scrollTo(actor, page, sideCard(page, 'Frozen checks'), 200);
  await actor.settle();
  await actor.spotlight(sideCard(page, 'Frozen checks'), L[2], { scale: 1.7 });
  await world.b('run2');
  await page.locator('[data-mol] canvas').waitFor();
  await freezeStructures(page);
  await world.b('grade');
  await world.b('learn');
  await world.b('done');
  await learned(page).waitFor();
  await scrollTo(actor, page, learned(page), 230);
  await actor.settle();
  await callout(page, learned(page), 'Mubit memory · record_outcome(success)', 'above');
  await actor.spotlight(learned(page), L[3], { scale: 1.55, stay: true });
  await clearCallouts(page);
  await actor.unfocus();
});

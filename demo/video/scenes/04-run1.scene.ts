import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { activity, callout, clearCallouts, freezeStructures, lab, scrollTo, sideCard, step } from '../ui.ts';

const L = LINES.run1;

scene('run1', { title: 'First run', blurb: 'Planned from scratch, and it fails its own check.', entry: 'run1' }, async ({ actor, page, server }) => {
  const world = lab(server);
  await actor.beat(400);
  await world.a('research');
  await activity(page, 'Recalled 0 lessons').waitFor();
  await actor.settle();
  await callout(page, activity(page, 'Recalled 0 lessons'), 'Mubit memory · nothing recalled yet', 'below');
  await actor.spotlight(sideCard(page, 'Activity'), L[0], { scale: 1.45 });
  await clearCallouts(page);

  await world.a('plan');
  await world.a('freeze');
  await step(page, 'Compose a pipeline').locator('.sdetail', { hasText: 'esmfold' }).waitFor();
  await actor.settle();
  await callout(page, step(page, 'Compose a pipeline').locator('.sagent'), 'Claude Opus 5 · through the Mubit gateway', 'right');
  await actor.spotlight(step(page, 'Compose a pipeline'), L[1], { scale: 1.6 });
  await clearCallouts(page);

  await world.a('run');
  await sideCard(page, 'Frozen checks').waitFor();
  await scrollTo(actor, page, sideCard(page, 'Frozen checks'), 200);
  await actor.settle();
  await actor.spotlight(sideCard(page, 'Frozen checks'), L[2], { scale: 1.7 });

  await world.a('run2');
  const structure = sideCard(page, 'Structure');
  await structure.locator('canvas').waitFor();
  await scrollTo(actor, page, structure, 150);
  await actor.settle();
  await actor.click(structure.locator('[data-view="spin"]'));
  await actor.spotlight(structure, L[3], { scale: 1.5, stay: true });
  await actor.click(structure.locator('[data-view="front"]'));
  await freezeStructures(page);
  await actor.unfocus();

  await world.a('grade');
  await world.a('learn');
  await sideCard(page, 'Checks').getByText('0.494', { exact: true }).waitFor();
  await scrollTo(actor, page, sideCard(page, 'Checks'), 200);
  await actor.settle();
  await actor.spotlight(sideCard(page, 'Checks'), L[4], { scale: 1.7, stay: true });
  await actor.unfocus();
});

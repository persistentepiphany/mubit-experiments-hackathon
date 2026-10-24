import { scene } from 'video-demo/scene';

import { lab, sideCard, step } from '../ui.ts';

scene('plan', { title: 'Plan and freeze', blurb: 'A pipeline from deployed tools, checks written up front, and a digest.', entry: 'plan' }, async ({ actor, page, server, shot }) => {
  const world = lab(server);
  await actor.beat(800);
  await world.a('freeze');
  await step(page, 'Compose a pipeline').locator('.sdetail', { hasText: 'esmfold' }).waitFor();
  await actor.settle();
  await actor.spotlight(step(page, 'Compose a pipeline'), 'Then the planner builds a pipeline from tools deployed on Modal. Fetch the sequence, then fold it with ESM Fold.', { scale: 1.7 });
  await actor.spotlight(sideCard(page, 'Frozen checks'), 'It writes its acceptance checks before anything runs.', { scale: 1.6 });
  await world.a('run');
  await step(page, 'Freeze plan and checks').locator('.sdetail', { hasText: 'sha-256' }).waitFor();
  await actor.settle();
  await actor.spotlight(step(page, 'Freeze plan and checks'), "And it freezes the plan under a SHA two fifty-six digest, so the goalposts can't move later.", { scale: 1.8, stay: true });
  await shot();
  await actor.unfocus();
});

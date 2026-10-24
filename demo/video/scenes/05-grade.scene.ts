import { scene } from 'video-demo/scene';

import { lab, learned, sideCard, step } from '../ui.ts';

scene('grade', { title: 'Run, grade, learn', blurb: 'Modal runs the steps, the frozen checks are graded, and a skill is saved.', entry: 'grade' }, async ({ actor, page, server, shot }) => {
  const world = lab(server);
  await actor.beat(900);
  await world.a('run2');
  await world.a('grade');
  await sideCard(page, 'Outputs').locator('.out', { hasText: 'esmfold' }).waitFor();
  await actor.settle();
  await actor.spotlight(sideCard(page, 'Outputs'), 'The steps run on Modal. ESM Fold comes back with its confidence scores.', { scale: 1.5 });
  await world.a('learn');
  await sideCard(page, 'Checks').locator('.s', { hasText: 'pass' }).first().waitFor();
  await actor.settle();
  await actor.spotlight(sideCard(page, 'Checks'), 'All three frozen checks pass.', { scale: 1.6 });
  await world.a('done');
  await learned(page).waitFor();
  await actor.scroll(page.locator('main'), 420);
  await actor.settle();
  await actor.spotlight(sideCard(page, 'Summary'), 'The reviewer writes a summary, and short lessons that go into Mubit memory.', { scale: 1.5 });
  await actor.spotlight(learned(page), 'And the pipeline is saved as a new skill. A draft, for now.', { scale: 1.6, stay: true });
  await shot();
  await actor.unfocus();
});

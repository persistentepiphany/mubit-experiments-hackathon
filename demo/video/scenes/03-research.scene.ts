import { scene } from 'video-demo/scene';

import { lab, sideCard, step } from '../ui.ts';

scene('research', { title: 'Research', blurb: 'A capped literature search, frozen into the run.', entry: 'research' }, async ({ actor, page, server, shot }) => {
  const world = lab(server);
  await actor.beat(900);
  await world.a('plan');
  await step(page, 'Search the literature').locator('.sdetail', { hasText: 'frozen' }).waitFor();
  await actor.settle();
  await actor.spotlight(step(page, 'Search the literature'), 'So it searches Europe PMC, with at most two queries, and keeps the two best papers.', { scale: 1.7 });
  await actor.spotlight(sideCard(page, 'Outputs'), "They're frozen into the run, so you can see exactly what it read.", { scale: 1.5, stay: true });
  await shot();
  await actor.unfocus();
});

import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { viz } from '../ui.ts';

const L = LINES.memory;

scene('viz-memory', { title: 'A lesson through Mubit', blurb: 'Written after run 1, recalled before run 2.', entry: 'viz-memory' }, async ({ actor, page }) => {
  await actor.overlay(false);
  await actor.beat(500);
  await viz(page, 1);
  await actor.beat(1200);
  await viz(page, 2);
  await actor.say(L[0], 2600);
  await viz(page, 3);
  await actor.say(L[1], 3000);
  await viz(page, 4);
  await actor.say(L[2]);
  await actor.beat(400);
});

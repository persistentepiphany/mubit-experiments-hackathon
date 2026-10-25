import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { viz } from '../ui.ts';

const L = LINES.outro;

scene('viz-outro', { title: 'What Mubit changed', blurb: 'Across three runs.', entry: 'viz-outro' }, async ({ actor, page }) => {
  await actor.overlay(false);
  await actor.beat(500);
  await viz(page, 1);
  await actor.beat(1600);
  await actor.say(L[0]);
  await viz(page, 2);
  await actor.beat(500);
  await actor.say(L[1]);
  await viz(page, 3);
  await actor.beat(400);
  await actor.say(L[2]);
  await actor.beat(1500);
});

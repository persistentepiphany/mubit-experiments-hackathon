import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { viz } from '../ui.ts';

const L = LINES.mubit;

scene('viz-mubit', { title: 'How labloop uses Mubit', blurb: 'The gateway and memory.', entry: 'viz-mubit' }, async ({ actor, page }) => {
  await actor.overlay(false);
  await actor.beat(500);
  await viz(page, 1);
  await actor.beat(400);
  await actor.say(L[0]);
  await viz(page, 2);
  await actor.beat(500);
  await actor.say(L[1], 3800);
  await viz(page, 3);
  await actor.beat(600);
  await actor.say(L[2]);
  await viz(page, 4);
  await actor.say(L[3], 4000);
  await viz(page, 5);
  await actor.beat(300);
  await actor.say(L[4]);
  await actor.beat(400);
});

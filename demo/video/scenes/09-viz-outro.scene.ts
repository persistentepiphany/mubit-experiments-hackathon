import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { viz } from '../ui.ts';

const L = LINES.outro;

scene('viz-outro', { title: 'labloop and Mubit', blurb: 'What happened across three runs.', entry: 'viz-outro' }, async ({ actor, page }) => {
  await actor.overlay(false);
  await actor.beat(500);
  await viz(page, 1);
  await actor.beat(1800);
  await actor.say(L[0]);
  await viz(page, 2);
  await actor.beat(600);
  await actor.say(L[1]);
  await actor.beat(1800);
});

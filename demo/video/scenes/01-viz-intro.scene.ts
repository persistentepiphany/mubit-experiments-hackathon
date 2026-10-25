import { scene } from 'video-demo/scene';

import { LINES } from '../script.ts';
import { overGesture, untilSaid, viz } from '../ui.ts';

const L = LINES.intro;

scene('viz-intro', { title: 'labloop', blurb: 'What labloop is.', entry: 'viz-intro' }, async ({ actor, page }) => {
  await actor.overlay(false);
  await actor.beat(500);
  await viz(page, 1);
  await actor.beat(700);
  await actor.say(L[0]);
  await viz(page, 2);
  const said = overGesture(actor, L[1]);
  await actor.beat(2600);
  await viz(page, 3);
  await untilSaid(said);
  await viz(page, 4);
  await actor.say(L[2]);
  await actor.beat(500);
});

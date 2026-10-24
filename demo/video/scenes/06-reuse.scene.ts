import { scene } from 'video-demo/scene';

import { TASK_B_TEXT } from '../seed/world.ts';
import { lab, learned, overGesture, step, untilSaid } from '../ui.ts';

scene('reuse', { title: 'Reuse', blurb: 'A second task finds the new skill and skips research and planning.', entry: 'reuse' }, async ({ actor, page, server, shot }) => {
  const world = lab(server);
  const said = overGesture(actor, 'Now a second task, this time written in plain words.');
  await actor.click(page.locator('#prompt'));
  await actor.type(TASK_B_TEXT, 26);
  await untilSaid(said);
  await actor.click(page.locator('#runPrompt'));
  await page.locator('h1.run').waitFor();
  await world.b('match');
  await actor.beat(700);
  await world.b('freeze');
  await step(page, 'Match against skills').locator('.tag').waitFor();
  await actor.settle();
  await actor.spotlight(step(page, 'Match against skills'), 'This time it finds the skill it just saved, and quotes the exact condition that matched.', { scale: 1.7 });
  await actor.spotlight(step(page, 'Search the literature'), 'Research and planning are skipped. It goes straight to the frozen pipeline.', { scale: 1.6 });
  await world.b('run');
  await actor.beat(500);
  await world.b('run2');
  await actor.beat(500);
  await world.b('grade');
  await actor.beat(400);
  await world.b('learn');
  await actor.beat(300);
  await world.b('done');
  await learned(page).waitFor();
  await actor.scroll(page.locator('main'), 420);
  await actor.settle();
  await actor.spotlight(learned(page), 'It passes on a second protein, so the skill is now validated.', { scale: 1.7, stay: true });
  await shot();
  await actor.unfocus();
});

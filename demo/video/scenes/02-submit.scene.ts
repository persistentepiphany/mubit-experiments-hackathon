import { scene } from 'video-demo/scene';

import { lab, overGesture, step, untilSaid } from '../ui.ts';

scene('submit', { title: 'A new task', blurb: 'Fold a UniProt entry no saved skill covers.' }, async ({ actor, page, server, shot }) => {
  const world = lab(server);
  const said = overGesture(actor, "Let's start one from a template, and fold human lysozyme from its UniProt entry.");
  await actor.click(page.locator('[data-tpl="uniprot"]'));
  const accession = page.locator('[data-param="accession"]');
  await accession.waitFor();
  await actor.scroll(page.locator('main'), 340);
  await actor.click(accession);
  await accession.selectText();
  await actor.type('P61626', 80);
  await untilSaid(said);
  await actor.click(page.locator('#runTpl'));
  await page.locator('h1.run').waitFor();
  await world.a('match');
  await actor.say('First, it checks whether a saved skill already fits.');
  await world.a('research');
  await step(page, 'Match against skills').locator('.sdetail', { hasText: 'Neither' }).waitFor();
  await actor.settle();
  await actor.spotlight(step(page, 'Match against skills'), 'None does, and it says exactly why.', { scale: 1.7, stay: true });
  await shot('match');
  await actor.unfocus();
});

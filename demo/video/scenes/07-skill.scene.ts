import { scene } from 'video-demo/scene';

const card = (page: import('@playwright/test').Page, label: string) =>
  page.locator('.card').filter({ has: page.locator('.eyebrow', { hasText: label }) });

scene('skill', { title: 'The skill', blurb: 'Evidence-backed standing, and a skill you can run directly.', entry: 'skill' }, async ({ actor, page, shot }) => {
  await actor.spotlight(card(page, 'Applies when'), 'Each skill says when it applies, and when it does not.', { scale: 1.5 });
  await actor.scroll(page.locator('main'), 360);
  await actor.spotlight(card(page, 'Evidence'), 'Its standing comes only from evidence. Two passing runs, on two different inputs.', { scale: 1.5 });
  await actor.spotlight(card(page, 'Run this skill'), 'And you can run it again yourself, with new inputs.', { scale: 1.6 });
  await actor.say("That's labloop. It does the work once, and keeps the skill.");
  await shot();
});

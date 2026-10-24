import { scene } from 'video-demo/scene';

scene('home', { title: 'Folio', blurb: 'Describe a task, start from a template, or reuse a saved skill.' }, async ({ actor, page, shot }) => {
  await actor.say('This is Folio, the front end for labloop. You describe a science task, and it learns a reusable skill from doing the work.');
  await actor.spotlight(page.locator('.composer'), 'You can describe the task in your own words.', { scale: 1.45 });
  await actor.spotlight(page.locator('.grid'), 'Or start from a template.', { scale: 1.35 });
  await actor.spotlight(page.locator('.pills'), "And these are the skills it's already saved.", { scale: 1.8 });
  await shot();
});

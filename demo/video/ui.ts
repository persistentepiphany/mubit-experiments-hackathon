import type { Locator, Page } from '@playwright/test';

import type { Lab } from './mock.ts';

/** The mock's handle, typed: the engine hands scenes whatever `mock` returned. */
export const lab = (server: unknown) => server as Lab;

/** One phase in the run page's step list, by its Folio name. */
export const step = (page: Page, name: string): Locator =>
  page.locator('.step').filter({ has: page.locator('.sname', { hasText: name }) });

/** A card in the run page's side column, by its eyebrow label. */
export const sideCard = (page: Page, label: string): Locator =>
  page.locator('.side .card').filter({ has: page.locator('.eyebrow', { hasText: label }) });

export const learned = (page: Page): Locator => page.locator('.learned');

/**
 * Starts a line of voice-over without holding the scene for it, so the words
 * play over a gesture (typing, filling a form) instead of before it. Returns
 * when the line would end, measured from now, for the scene to wait on.
 */
export function overGesture(actor: { onNarrate?: (text: string) => void }, text: string): number {
  actor.onNarrate?.(text);
  // The engine paces a `say` at 3.7 words a second plus 0.4s (references/narration.md).
  return Date.now() + (text.split(/\s+/).length / 3.7 + 0.4) * 1000;
}

export async function untilSaid(deadline: number) {
  const left = deadline - Date.now();
  if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
}

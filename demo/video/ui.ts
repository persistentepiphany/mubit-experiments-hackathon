import type { Locator, Page } from '@playwright/test';

import type { Actor } from 'video-demo/actor';
import { spokenFor } from 'video-demo/voice';

import type { Lab } from './mock.ts';

/** The mock's handle, typed: the engine hands scenes whatever `mock` returned. */
export const lab = (server: unknown) => server as Lab;

/** One phase in the run page's step list, by its name on the website. */
export const step = (page: Page, name: string): Locator =>
  page.locator('.step').filter({ has: page.locator('.sname', { hasText: name }) });

/** A card in the run page's side column, by its eyebrow label. */
export const sideCard = (page: Page, label: string): Locator =>
  page.locator('.side .card').filter({ has: page.locator('.eyebrow', { hasText: label }) });

/** One line of the Activity feed. */
export const activity = (page: Page, text: string | RegExp): Locator => page.locator('.feed .ev', { hasText: text });

export const learned = (page: Page): Locator => page.locator('.learned');

/**
 * Starts a line of voice-over without holding the scene for it, so the words
 * play over a gesture instead of before it. Returns when the line ends, for
 * `untilSaid`, so the next line cannot start on top of it.
 */
export function overGesture(actor: Actor, text: string): number {
  actor.onNarrate?.(text);
  return Date.now() + spokenFor(text);
}

export async function untilSaid(deadline: number) {
  const left = deadline - Date.now();
  if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
}

/**
 * A Mubit label pinned beside an element of the website, in the manner of a
 * Recordly annotation. It is placed in page coordinates, inside the body the
 * camera zooms, so it moves with the page; `clearCallouts` fades it out.
 */
export async function callout(
  page: Page,
  target: Locator,
  text: string,
  side: 'left' | 'right' | 'above' | 'below' = 'right'
) {
  const handle = await target.first().elementHandle();
  await page.evaluate(
    ([el, label, where]) => {
      const box = (node: HTMLElement) => {
        let x = 0;
        let y = 0;
        for (let at: HTMLElement | null = node; at; at = at.offsetParent as HTMLElement | null) {
          x += at.offsetLeft;
          y += at.offsetTop;
        }
        return { x, y, w: node.offsetWidth, h: node.offsetHeight };
      };
      if (!document.getElementById('callout-style')) {
        const style = document.createElement('style');
        style.id = 'callout-style';
        style.textContent = `
          .callout{position:absolute;z-index:50;display:flex;align-items:center;gap:8px;padding:7px 13px 7px 10px;border-radius:999px;
            background:linear-gradient(160deg,#34302b,#1f1c19);color:#f4eee4;font:500 12.5px Geist,system-ui,sans-serif;white-space:nowrap;
            box-shadow:0 10px 28px rgba(31,28,25,.28),0 0 0 1.5px rgba(231,194,125,.55);opacity:0;transform:translateY(6px) scale(.96);
            transition:opacity .45s ease,transform .55s cubic-bezier(.2,.9,.25,1.1)}
          .callout.on{opacity:1;transform:none}
          .callout i{width:9px;height:9px;border-radius:3px;background:#e7c27d;flex:none}
          .callout-ring{position:absolute;z-index:49;border-radius:12px;box-shadow:0 0 0 2px #e7c27d,0 0 24px rgba(231,194,125,.45);
            opacity:0;transition:opacity .45s ease;pointer-events:none}
          .callout-ring.on{opacity:1}`;
        document.head.appendChild(style);
      }
      const b = box(el as HTMLElement);
      const ring = document.createElement('div');
      ring.className = 'callout-ring';
      Object.assign(ring.style, { left: `${b.x - 6}px`, top: `${b.y - 4}px`, width: `${b.w + 12}px`, height: `${b.h + 8}px` });
      const tag = document.createElement('div');
      tag.className = 'callout';
      tag.innerHTML = `<i></i>${label}`;
      document.body.append(ring, tag);
      const t = tag.getBoundingClientRect();
      const scale = (document.body.getBoundingClientRect().width || innerWidth) / innerWidth;
      const tw = t.width / scale;
      const th = t.height / scale;
      const pos = {
        right: { left: b.x + b.w + 14, top: b.y + b.h / 2 - th / 2 },
        left: { left: b.x - tw - 14, top: b.y + b.h / 2 - th / 2 },
        above: { left: b.x + b.w / 2 - tw / 2, top: b.y - th - 12 },
        below: { left: b.x + b.w / 2 - tw / 2, top: b.y + b.h + 12 },
      }[where as 'right'];
      tag.style.left = `${Math.max(8, Math.min(pos.left, document.documentElement.clientWidth - tw - 8))}px`;
      tag.style.top = `${pos.top}px`;
      requestAnimationFrame(() => {
        ring.classList.add('on');
        tag.classList.add('on');
      });
    },
    [handle, text, side] as const
  );
}

export async function clearCallouts(page: Page) {
  await page.evaluate(() => {
    document.querySelectorAll('.callout, .callout-ring').forEach((el) => {
      el.classList.remove('on');
      setTimeout(() => el.remove(), 500);
    });
  });
}

/** Steps an explainer page forward. */
export const viz = (page: Page, step: number) =>
  page.evaluate((n) => (window as unknown as { viz: { go: (n: number) => void } }).viz.go(n), step);

/**
 * Scrolls so a target sits `top` pixels below the top of the window. The
 * distance is measured in layout coordinates, so it is right even while the
 * camera is zoomed in.
 */
export async function scrollTo(actor: Actor, page: Page, target: Locator, top = 110) {
  const handle = await target.first().elementHandle();
  const delta = await page.evaluate(
    ([el, gap]) => {
      let y = 0;
      for (let at = el as HTMLElement | null; at; at = at.offsetParent as HTMLElement | null) y += at.offsetTop;
      const max = document.documentElement.scrollHeight - innerHeight;
      return Math.max(-scrollY, Math.min(max - scrollY, y - scrollY - (gap as number)));
    },
    [handle, top] as const
  );
  if (Math.abs(delta) > 4) await actor.scroll(page.locator('main'), delta);
}

/**
 * Swaps each live 3D structure viewer for a still image of its current view.
 *
 * Headless Chromium renders WebGL in software, and while a run is live the
 * website repaints every frame (its pulsing status dots), so a live viewer
 * makes every captured frame expensive enough to starve the page. The still
 * is the viewer's own render, so the film looks the same.
 */
export async function freezeStructures(page: Page) {
  await page.evaluate(() => {
    // The website keeps its viewers in a top-level `const S`, which is not a
    // property of the global object; an indirect eval runs in global scope.
    type Viewers = { viewers: Record<string, { el: HTMLElement; v: { pngURI: () => string } }> };
    const state = (0, eval)('typeof S === "undefined" ? undefined : S') as Viewers | undefined;
    for (const { el, v } of Object.values(state?.viewers ?? {})) {
      const canvas = el.querySelector('canvas');
      if (!canvas) continue;
      const img = document.createElement('img');
      img.src = v.pngURI();
      img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block';
      canvas.replaceWith(img);
    }
  });
}

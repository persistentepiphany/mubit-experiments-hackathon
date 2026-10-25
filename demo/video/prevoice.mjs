#!/usr/bin/env node
/**
 * Synthesises every narration line in script.ts into video-demo's line cache
 * before filming. With the lines cached, the patched engine holds each `say`
 * for the line's real length, so no line can start on top of the one before.
 */
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
process.env.DEMO_CONFIG ??= join(HERE, 'demo.config.ts');
process.env.DEMO_PROJECT ??= HERE;
process.env.DEMO_APP_ROOT ??= resolve(HERE, '..', '..');

const { LINES } = await import('./script.ts');
const { speak, voiceReady } = await import('video-demo/voice');

if (!(await voiceReady())) {
  process.stderr.write('prevoice: no voice model installed; run demo/setup.sh first\n');
  process.exit(1);
}

const texts = Object.values(LINES).flat();
const spoken = await speak(texts.map((text) => ({ text, at: 0 })));
let total = 0;
for (const line of spoken) {
  total += line.seconds;
  process.stdout.write(`  ${line.seconds.toFixed(2).padStart(5)}s  ${line.text}\n`);
}
process.stdout.write(`prevoice: ${spoken.length} lines, ${total.toFixed(1)} s of speech\n`);

#!/usr/bin/env node
/**
 * Voices an ndemo playbook locally with the Kokoro model video-demo installs.
 *
 * ndemo synthesises narration through OpenAI, but skips that call when
 * `audio/<segment>-<hash>.mp3` already exists, with the hash taken over the
 * narration, voice and speed (src/tts.ts). This writes exactly those files
 * with video-demo's scripts/say.sh, so `ndemo render` runs with no API key
 * and in the same voice as the main film.
 *
 *     node demo/ndemo/voice.mjs <playbook.yaml> <ndemo dir> <video-demo dir>
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, unlinkSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';

const [playbookPath, ndemoDir, videoDemoDir] = process.argv.slice(2);
if (!playbookPath || !ndemoDir || !videoDemoDir) {
  process.stderr.write('usage: voice.mjs <playbook.yaml> <ndemo dir> <video-demo dir>\n');
  process.exit(1);
}

const YAML = createRequire(join(resolve(ndemoDir), 'package.json'))('yaml');
const playbook = YAML.parse(readFileSync(playbookPath, 'utf8'));
const voice = playbook.tts?.voice ?? 'alloy';
const speed = playbook.tts?.speed ?? 1;
const audioDir = join(dirname(resolve(playbookPath)), playbook.recording?.outputDir ?? '.', 'audio');
mkdirSync(audioDir, { recursive: true });

/** Respellings for the synthesiser only; the hash is over the playbook's own words. */
const SAID_AS = [[/\blabloop\b/gi, 'lab loop']];

for (const segment of playbook.segments) {
  if (!segment.narration) continue;
  const hash = createHash('sha256').update(segment.narration + voice + speed).digest('hex').slice(0, 8);
  const target = join(audioDir, `${segment.id}-${hash}.mp3`);
  for (const file of readdirSync(audioDir)) {
    if (file.startsWith(`${segment.id}-`) && join(audioDir, file) !== target) unlinkSync(join(audioDir, file));
  }
  if (existsSync(target)) {
    process.stdout.write(`  kept   ${segment.id}\n`);
    continue;
  }
  const spoken = SAID_AS.reduce((text, [pattern, said]) => text.replace(pattern, said), segment.narration);
  const out = execFileSync(join(videoDemoDir, 'scripts', 'say.sh'), [spoken, voice, String(speed)], {
    encoding: 'utf8',
    env: { ...process.env, PATH: process.env.PATH },
  });
  const wav = /wrote (\S+\.wav)/.exec(out)?.[1];
  if (!wav) throw new Error(`say.sh did not report a file for ${segment.id}: ${out}`);
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-i', wav, '-codec:a', 'libmp3lame', '-q:a', '2', target]);
  unlinkSync(wav);
  process.stdout.write(`  voiced ${segment.id}\n`);
}

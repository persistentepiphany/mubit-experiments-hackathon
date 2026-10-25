import { createHash } from 'node:crypto';

/**
 * The invented lab the demo films, following the sequence labloop's README
 * reports from its real runs on Modal: a 30-residue ESMFold task fails its own
 * frozen check `ptm >= 0.5` with pTM 0.494; the reviewer's lesson says the
 * floor is too strict for so short a chain; the same task submitted again is
 * planned with that lesson recalled, freezes a floor of 0.3, passes and is
 * saved as a skill. A third task on a different short chain reuses the skill.
 *
 * Every shape follows what labloop/api.py, events.py, research.py,
 * grading.py and orchestrator.py write. Names, numbers and run ids beyond the
 * README's are invented.
 */

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

export const sha256 = (value: unknown) => createHash('sha256').update(canonical(value)).digest('hex');

// ------------------------------------------------------------------ the three runs

export const RUN_A = 'r-20261021-150212-5d8e3a';
export const RUN_B = 'r-20261021-152940-8b1f07';
export const RUN_C = 'r-20261021-160518-c07b91';
export const SKILL = 'esmfold_short_chain_fold';

/** Folio's "Fold a protein" template: its description and default sequence. */
export const FOLD_DESCRIPTION = 'Predict the 3D structure of this single protein chain and report whether the fold is confident.';
export const PEPTIDE = 'GSHMKTAYIAKQRQISFVKSHFSRQLEERL';
/** Trp-cage, a 20-residue miniprotein. */
export const TRP_CAGE = 'NLYIQWLKDGGPSSGRPPPS';

const TASK_AB = { description: FOLD_DESCRIPTION, inputs: { sequence: PEPTIDE } };
const TASK_C = { description: FOLD_DESCRIPTION, inputs: { sequence: TRP_CAGE } };

const LESSON_A =
  'A pTM floor of 0.5 is too strict for a 30-residue chain. Short chains score low pTM even when pLDDT is high, so use about 0.3 below 50 residues.';
const LESSON_B = 'A pTM floor of 0.3 suits chains under 50 residues: this 30-residue fold passed at pTM 0.494 with pLDDT 89.7.';
const LESSON_C = 'Trp-cage (20 residues) passed the frozen short-chain checks at pLDDT 78.4 and pTM 0.36.';

const APPLIES = 'the task asks for the structure of one protein chain of under 50 residues given its sequence';

const STEPS = [{ id: 'fold', tool: 'esmfold', args: { sequence: '$inputs.sequence', name: 'query' } }];

const CHECKS_A = [
  { id: 'confident_fold', metric: 'fold.scores.mean_plddt', op: '>=', value: 70, rationale: 'pLDDT above 70 marks a confident backbone' },
  { id: 'global_fold', metric: 'fold.scores.ptm', op: '>=', value: 0.5, rationale: 'pTM above 0.5 suggests the overall fold is right' },
];
const CHECKS_B = [
  CHECKS_A[0]!,
  { id: 'global_fold', metric: 'fold.scores.ptm', op: '>=', value: 0.3, rationale: 'lowered for a chain under 50 residues, following a recalled lesson' },
];

const PAPERS = [
  { id: '36927031', doi: '10.1126/science.ade2574', title: 'Evolutionary-scale prediction of atomic-level protein structure with a language model', year: '2023', citations: 2140, text_source: 'full_text', full_text: true },
  { id: '34265844', doi: '10.1038/s41586-021-03819-2', title: 'Highly accurate protein structure prediction with AlphaFold', year: '2021', citations: 31800, text_source: 'full_text', full_text: true },
  { id: '38001234', doi: '10.1093/bioinformatics/btad702', title: 'Benchmarking single-sequence structure predictors on short peptides', year: '2023', citations: 46, text_source: 'abstract', full_text: false },
];

const SKILL_META = {
  name: SKILL,
  title: 'Fold a short chain with ESMFold',
  description: 'Fold one chain under 50 residues with ESMFold and accept it when pLDDT is at least 70 and pTM at least 0.3.',
  applies_when: [APPLIES],
  not_for: ['complexes of two or more chains', 'chains of 50 residues or more'],
};

const PLAN_A = {
  origin: { kind: 'planned' },
  skill: SKILL_META,
  input_schema: { sequence: { type: 'string', description: 'protein sequence' } },
  steps: STEPS,
  checks: CHECKS_A,
  sources: PAPERS.slice(0, 2).map((p) => ({ id: p.doi, title: p.title, used_for: 'confidence thresholds' })),
  decisions: [{ topic: 'pTM floor', choice: '0.5', reason: 'common cut-off; the papers set none for short chains', source_silent: true }],
};
const PLAN_B = {
  ...PLAN_A,
  checks: CHECKS_B,
  decisions: [{ topic: 'pTM floor', choice: '0.3', reason: 'recalled lesson: 0.5 is too strict below 50 residues', source_silent: true }],
};
const PLAN_C = { ...PLAN_B, origin: { kind: 'skill', skill: SKILL, version: 1 }, decisions: [] };

const DIGEST = { a: sha256(PLAN_A), b: sha256(PLAN_B), c: sha256(PLAN_C) };

function research(lessons: number) {
  return {
    queries: ['"ESMFold" AND pTM AND "short peptide"', '"single sequence" structure prediction confidence peptides'],
    query_error: null,
    limits: { max_queries: 2, page_size: 25, max_docs: 6 },
    papers: PAPERS,
    corpus: { scores: { n_documents: 6, n_full_text: 3, searched: 41 } },
    paperqa: {
      documents: 9,
      failed: [],
      answers: [
        { question: 'Which tool and settings?', answer: 'ESMFold on the single sequence.', contexts: [{ citation: 'Lin 2023' }, { citation: 'Jumper 2021' }] },
        { question: 'What confidence counts as good?', answer: 'pLDDT above 70; pTM is lower for short chains.', contexts: [{ citation: 'Jumper 2021' }, { citation: 'Short peptides 2023' }] },
      ],
    },
    extraction: { reported_numbers: [{}, {}, {}, {}], guidance: [{}, {}, {}] },
    errors: [],
    advisory_lessons: lessons,
  };
}

// ------------------------------------------------------------------ progress

export const PHASES_A = ['none', 'queued', 'match', 'research', 'plan', 'freeze', 'run', 'run2', 'grade', 'learn', 'done'] as const;
export const PHASES_C = ['none', 'queued', 'match', 'freeze', 'run', 'run2', 'grade', 'learn', 'done'] as const;
export type PhaseA = (typeof PHASES_A)[number];
export type PhaseC = (typeof PHASES_C)[number];

const statusPhase = (p: string) => (p === 'run2' ? 'run' : p);

type Ev = { kind: string; message: string; phase?: string; key?: string };

/**
 * The activity log, in the formats orchestrator.py and research.py emit,
 * keyed by the furthest phase that has been reached when each event exists.
 */
function eventsFor(kind: 'a' | 'b' | 'c'): [string, Ev][] {
  const lessons = { a: 0, b: 1, c: 2 }[kind];
  const skills = { a: 2, b: 2, c: 3 }[kind];
  const pass = kind !== 'a';
  const scores = kind === 'c' ? 'mean_plddt 78.4, ptm 0.36, length 20' : 'mean_plddt 89.7, ptm 0.494, length 30';
  const out: [string, Ev][] = [
    ['match', { kind: 'info', message: 'Run accepted by the orchestrator on Modal' }],
    ['match', { kind: 'start', key: 'match', phase: 'match', message: `Recalled ${lessons} lesson${lessons === 1 ? '' : 's'}; checking ${skills} saved skills` }],
  ];
  if (kind === 'c') {
    out.push(['freeze', { kind: 'done', key: 'match', phase: 'match', message: `Reusing skill ${SKILL}` }]);
  } else {
    out.push(
      ['research', { kind: 'done', key: 'match', phase: 'match', message: 'No saved skill fits: the Boltz-2 skill needs two chains, and the PDB skill only reads deposited entries.' }],
      ['research', { kind: 'info', phase: 'research', message: 'Researcher wrote 2 Europe PMC queries: "ESMFold" AND pTM AND "short peptide" | "single sequence" structure prediction confidence peptides' }],
      ['research', { kind: 'start', key: 'corpus', phase: 'research', message: 'Building the corpus on Modal: Europe PMC (25 per query), OpenAlex citations, full text, frozen manifest' }],
      ['plan', { kind: 'done', key: 'corpus', phase: 'research', message: 'Corpus frozen: 6 papers (3 full text) chosen from 41 found' }],
      ['plan', { kind: 'info', phase: 'research', message: 'PaperQA2 read 9 papers and answered 2 questions citing 3 papers' }],
      ['plan', { kind: 'start', key: 'planner', phase: 'plan', message: `Planner composing a pipeline from 6 deployed tools, 6 tool knowledge cards and ${lessons} recalled lesson${lessons === 1 ? '' : 's'}` }],
      ['freeze', { kind: 'done', key: 'planner', phase: 'plan', message: 'Planner drafted esmfold with 2 checks (0 against published references)' }],
    );
  }
  const digest = DIGEST[kind];
  out.push(
    ['run', { kind: 'info', phase: 'freeze', message: `Plan and 2 checks frozen as sha-256 ${digest.slice(0, 12)}` }],
    ['run', { kind: 'start', key: 'step:fold', phase: 'run', message: 'fold: esmfold running on Modal (A10G, typically about 40 s)' }],
    ['run2', { kind: 'done', key: 'step:fold', phase: 'run', message: `fold finished in ${kind === 'c' ? 18 : 20} s: ${scores}` }],
    ['grade', { kind: 'info', phase: 'grade', message: `confident_fold: PASS (fold.scores.mean_plddt observed ${kind === 'c' ? 78.4 : 89.7})` }],
    ['grade', { kind: 'info', phase: 'grade', message: `global_fold: ${pass ? 'PASS' : 'FAIL'} (fold.scores.ptm observed ${kind === 'c' ? 0.36 : 0.494})` }],
    ['grade', { kind: 'info', phase: 'grade', message: `Verdict ${pass ? 'PASS' : 'FAIL'}` }],
    ['learn', { kind: 'start', key: 'reviewer', phase: 'learn', message: 'Reviewer writing lessons from the graded run' }],
    ['done', { kind: 'done', key: 'reviewer', phase: 'learn', message: 'Reviewer recorded 1 lesson' }],
  );
  if (kind === 'b') out.push(['done', { kind: 'info', phase: 'learn', message: `Skill ${SKILL} created, standing draft` }]);
  if (kind === 'c') out.push(['done', { kind: 'info', phase: 'learn', message: `Skill ${SKILL} given this run as evidence, standing validated` }]);
  out.push(['done', { kind: 'info', message: `Run finished: ${pass ? 'PASS' : 'FAIL'}` }]);
  return out;
}

const START = { a: '2026-10-21T15:02:12Z', b: '2026-10-21T15:29:40Z', c: '2026-10-21T16:05:18Z' };
const SECONDS: Record<string, number> = { match: 0, research: 3, plan: 62, freeze: 101, run: 102, run2: 122, grade: 123, learn: 124, done: 131 };
const SECONDS_C: Record<string, number> = { match: 0, freeze: 3, run: 4, run2: 22, grade: 23, learn: 24, done: 30 };

const iso = (start: string, s: number) => new Date(Date.parse(start) + s * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z');

function build(kind: 'a' | 'b' | 'c', p: string, now?: Date) {
  const id = { a: RUN_A, b: RUN_B, c: RUN_C }[kind];
  if (p === 'none') return null;
  if (p === 'queued') return { run_id: id, phase: 'queued' };
  const list: readonly string[] = kind === 'c' ? PHASES_C : PHASES_A;
  const secs = kind === 'c' ? SECONDS_C : SECONDS;
  const reached = (t: string) => list.indexOf(p) >= list.indexOf(t);
  const plan = { a: PLAN_A, b: PLAN_B, c: PLAN_C }[kind];
  const task = kind === 'c' ? TASK_C : TASK_AB;
  const pass = kind !== 'a';
  const done = p === 'done';
  const [plddt, ptm, len, foldSecs] = kind === 'c' ? [78.4, 0.36, 20, 18] : [89.7, 0.494, 30, 20];

  // A run still going is placed so it would finish a moment after `now`, so
  // the website's live timers read seconds or minutes rather than hours, and
  // event times stay put as the run advances.
  const latest = (secs.done ?? 0) + 0.4 * eventsFor(kind).length + 4;
  const start = now && p !== 'done' ? new Date(now.getTime() - latest * 1000).toISOString() : START[kind];

  const history: { phase: string; at: string }[] = [];
  for (const step of list.slice(2, list.indexOf(p) + 1)) {
    const phase = statusPhase(step);
    if (history[history.length - 1]?.phase !== phase) history.push({ phase, at: iso(start, secs[phase] ?? 0) });
  }

  let seq = 0;
  const events = eventsFor(kind)
    .filter(([at]) => reached(at))
    .map(([at, ev]) => ({ seq: ++seq, at: iso(start, (secs[at] ?? 0) + seq * 0.4), ...ev }));

  const inputs = task.inputs;
  const checks = plan.checks.map((c) => {
    const observed = c.metric.endsWith('mean_plddt') ? plddt : ptm;
    const ok = observed >= (c.value as number);
    return { ...c, status: ok ? 'PASS' : 'FAIL', observed };
  });
  const lessonText = { a: LESSON_A, b: LESSON_B, c: LESSON_C }[kind];
  const summary = {
    a: 'pLDDT was 89.7, but pTM came in at 0.494, just under the frozen floor of 0.5, so the run failed.',
    b: 'With the pTM floor at 0.3 for a 30-residue chain, the same fold passed both frozen checks (pLDDT 89.7, pTM 0.494).',
    c: 'The saved skill folded Trp-cage at pLDDT 78.4 and pTM 0.36, and both frozen checks passed.',
  }[kind];
  const skill = { a: null, b: { action: 'created', skill: SKILL, version: 1, standing: 'draft' }, c: { action: 'evidence_appended', skill: SKILL, version: 2, standing: 'validated' } }[kind];

  return {
    run_id: id,
    status: {
      run_id: id,
      phase: statusPhase(p),
      history,
      ...(reached('run') ? { plan_digest: DIGEST[kind], inputs_digest: sha256(inputs), origin: plan.origin } : {}),
      ...(done ? { verdict: pass ? 'PASS' : 'FAIL', skill, lessons: [`mem_${kind}1`], lesson_texts: [lessonText], summary } : {}),
    },
    task,
    match:
      kind === 'c'
        ? reached('freeze')
          ? { candidates: ['boltz2_heterodimer_interface', 'pdb_chain_sequences', SKILL], lessons: ['mem_a1', 'mem_b1'], decision: 'reuse', skill: SKILL, version: 1, matched_applies_when: APPLIES, input_mapping: { sequence: { from_input: 'sequence' } }, reason: 'one chain of 20 residues' }
          : null
        : reached('research')
          ? { candidates: ['boltz2_heterodimer_interface', 'pdb_chain_sequences'], lessons: kind === 'b' ? ['mem_a1'] : [], decision: 'plan', skill: null, reason: 'Neither saved skill fits: the Boltz-2 skill needs two chains, and the PDB skill only reads deposited entries.' }
          : null,
    research: kind !== 'c' && reached('plan') ? research(kind === 'b' ? 1 : 0) : null,
    plan: reached('freeze') ? plan : null,
    plan_sha256: reached('run') ? DIGEST[kind] : null,
    inputs: reached('run') ? { inputs, inputs_digest: sha256(inputs) } : null,
    experiments: reached('run2')
      ? [{ at: iso(start, secs.run2!), step_id: 'fold', tool: 'esmfold', status: 'ok', args: { sequence: '…', name: 'query' }, result: { tool: 'esmfold', scores: { mean_plddt: plddt, ptm, length: len }, artifacts: { structure: `${id}/fold/model.pdb` }, data: {} }, wave_seconds: foldSecs }]
      : [],
    decisions: [],
    results: reached('learn')
      ? { run_id: id, plan_digest: DIGEST[kind], inputs_digest: sha256(inputs), verdict: pass ? 'PASS' : 'FAIL', checks, domain_graders: [], metrics: Object.fromEntries(checks.map((c) => [c.metric, c.observed])), counts: { PASS: checks.filter((c) => c.status === 'PASS').length, FAIL: checks.filter((c) => c.status === 'FAIL').length, UNVERIFIABLE: 0 } }
      : null,
    events,
  };
}

export const runA = (p: PhaseA, now?: Date) => build('a', p, now);
export const runB = (p: PhaseA, now?: Date) => build('b', p, now);
export const runC = (p: PhaseC, now?: Date) => build('c', p, now);

// ------------------------------------------------------------------ skills

type Evidence = { run_id: string; task: string; inputs_digest: string; verdict: string; metrics: Record<string, number>; plan_digest: string };

export type SkillDoc = typeof SKILL_META & {
  version: number;
  pipeline: { steps: { id: string; tool: string; args: Record<string, unknown> }[]; checks: unknown[] };
  input_schema: Record<string, { type: string; description?: string }>;
  lessons: string[];
  sources: unknown[];
  evidence: Evidence[];
  updated_at: string;
};

const pdbSkill: SkillDoc = {
  name: 'pdb_chain_sequences',
  title: 'Chain sequences from a PDB entry',
  description: 'Read the chain sequences of a deposited RCSB PDB entry from its coordinates.',
  applies_when: ['the task names a deposited PDB entry and asks for its chain sequences'],
  not_for: ['predicting a structure that has not been deposited'],
  version: 4,
  pipeline: { steps: [{ id: 'entry', tool: 'fetch_pdb', args: { pdb_id: '$inputs.pdb_id' } }], checks: [{ id: 'has_chains', metric: 'entry.scores.n_chains', op: '>=', value: 1 }] },
  input_schema: { pdb_id: { type: 'string', description: 'four-character PDB id' } },
  lessons: [],
  sources: [],
  evidence: ['4HHB', '6M0J', '1UBQ'].map((id, i) => ({ run_id: `r-2026101${6 + i}-110301-0a9c4${i}`, task: `Get the chain sequences of PDB ${id}`, inputs_digest: sha256(id), verdict: 'PASS', metrics: {}, plan_digest: sha256('pdb') })),
  updated_at: '2026-10-20T16:31:02Z',
};

const boltzSkill: SkillDoc = {
  name: 'boltz2_heterodimer_interface',
  title: 'Co-fold two chains with Boltz-2',
  description: 'Co-fold two protein chains with Boltz-2 and accept the complex when interface confidence is high.',
  applies_when: ['the task asks for the complex of exactly two protein chains given their sequences'],
  not_for: ['single chains', 'complexes of three or more chains'],
  version: 1,
  pipeline: { steps: [{ id: 'cofold', tool: 'boltz2', args: { chains: ['$inputs.chain_a', '$inputs.chain_b'] } }], checks: [{ id: 'interface', metric: 'cofold.scores.iptm', op: '>=', value: 0.6 }] },
  input_schema: { chain_a: { type: 'string' }, chain_b: { type: 'string' } },
  lessons: [],
  sources: [],
  evidence: [{ run_id: 'r-20261020-101422-7c1e09', task: 'Co-fold PD-1 with PD-L1 and report interface confidence', inputs_digest: sha256('pd1'), verdict: 'PASS', metrics: {}, plan_digest: sha256('boltz') }],
  updated_at: '2026-10-20T10:31:40Z',
};

export function skills(b: PhaseA, c: PhaseC): SkillDoc[] {
  const list = [boltzSkill, pdbSkill];
  if (b !== 'done') return list;
  const evidence: Evidence[] = [{ run_id: RUN_B, task: FOLD_DESCRIPTION, inputs_digest: sha256(TASK_AB.inputs), verdict: 'PASS', metrics: { 'fold.scores.mean_plddt': 89.7, 'fold.scores.ptm': 0.494 }, plan_digest: DIGEST.b }];
  const lessons = [LESSON_A, LESSON_B];
  if (c === 'done') {
    evidence.push({ run_id: RUN_C, task: FOLD_DESCRIPTION, inputs_digest: sha256(TASK_C.inputs), verdict: 'PASS', metrics: { 'fold.scores.mean_plddt': 78.4, 'fold.scores.ptm': 0.36 }, plan_digest: DIGEST.c });
    lessons.push(LESSON_C);
  }
  return [
    { ...SKILL_META, version: evidence.length, pipeline: { steps: STEPS, checks: CHECKS_B }, input_schema: PLAN_A.input_schema, lessons, sources: PLAN_A.sources, evidence, updated_at: '2026-10-21T15:31:51Z' },
    ...list,
  ];
}

export function standing(s: SkillDoc) {
  return new Set(s.evidence.filter((e) => e.verdict === 'PASS').map((e) => e.inputs_digest)).size >= 2 ? 'validated' : 'draft';
}

/** labloop.skills.card */
export function card(s: SkillDoc) {
  return {
    name: s.name,
    title: s.title,
    description: s.description,
    tools: [...new Set(s.pipeline.steps.map((x) => x.tool))],
    inputs: Object.entries(s.input_schema).map(([name, v]) => ({ name, ...v })),
    standing: standing(s),
    runs: s.evidence.length,
    passes: s.evidence.filter((e) => e.verdict === 'PASS').length,
    version: s.version,
    updated_at: s.updated_at,
  };
}

// ------------------------------------------------------------------ the runs list

const EARLIER = [
  { run_id: 'r-20261020-163015-2b8d4f', description: 'Get the chain sequences of PDB 1UBQ', verdict: 'PASS', origin: { kind: 'skill', skill: 'pdb_chain_sequences', version: 3 }, started_at: '2026-10-20T16:30:15Z' },
  { run_id: 'r-20261020-101422-7c1e09', description: 'Co-fold PD-1 with PD-L1 and report interface confidence', verdict: 'PASS', origin: { kind: 'planned' }, started_at: '2026-10-20T10:14:22Z' },
];

/** GET /runs, newest first. */
export function runList(a: PhaseA, b: PhaseA, c: PhaseC) {
  const live = [runC(c), runB(b), runA(a)]
    .filter((doc): doc is NonNullable<typeof doc> => Boolean(doc))
    .map((doc) => {
      const status = ('status' in doc ? doc.status : {}) as Record<string, unknown>;
      const events = ('events' in doc ? doc.events : []) as { at: string }[];
      return {
        run_id: doc.run_id,
        description: FOLD_DESCRIPTION,
        phase: 'phase' in doc ? doc.phase : status.phase,
        verdict: status.verdict ?? null,
        origin: status.origin ?? null,
        skill: status.skill ?? null,
        activity: status.phase !== 'done' ? (events[events.length - 1] ?? null) : null,
        in_flight: [],
        started_at: ((status.history as { at: string }[] | undefined) ?? [])[0]?.at ?? null,
      };
    });
  return [...live, ...EARLIER.map((r) => ({ ...r, phase: 'done', skill: null, activity: null, in_flight: [] }))];
}

import { createHash } from 'node:crypto';

/**
 * The invented lab the demo films: two saved skills, four earlier runs, and
 * the two runs the tour performs. Run A folds human lysozyme from the
 * "Fold a UniProt entry" template and saves a new skill; run B asks for
 * myoglobin in free text and reuses that skill. Every shape follows what
 * labloop/api.py, research.py, grading.py and orchestrator.py write.
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

// ------------------------------------------------------------------ the two runs

export const RUN_A = 'r-20261021-150212-5d8e3a';
export const RUN_B = 'r-20261021-151845-c07b91';
export const NEW_SKILL = 'uniprot_monomer_fold';

/** Folio's own "Fold a UniProt entry" template description. */
export const TASK_A = {
  description: "Fetch this UniProt entry's sequence and predict its structure, reporting whether the fold is confident.",
  inputs: { accession: 'P61626' },
};

export const TASK_B_TEXT = 'Fold human myoglobin, UniProt P02144, and tell me how far to trust the model.';
export const TASK_B = { description: TASK_B_TEXT, inputs: {} };

const APPLIES = 'the task asks for the structure of one protein chain identified by a UniProt accession';

const STEPS = [
  { id: 'fetch', tool: 'fetch_uniprot', args: { accession: '$inputs.accession' } },
  { id: 'fold', tool: 'esmfold', args: { sequence: '$steps.fetch.data.sequence', name: 'query' } },
];

const CHECKS = [
  { id: 'confident_fold', metric: 'fold.scores.mean_plddt', op: '>=', value: 70, rationale: 'pLDDT above 70 marks a confident backbone' },
  { id: 'global_topology', metric: 'fold.scores.ptm', op: '>=', value: 0.5, rationale: 'pTM above 0.5 suggests the overall fold is right' },
  { id: 'in_range', metric: 'fetch.scores.length', op: '<=', value: 400, rationale: 'inside the length ESMFold handles well' },
];

const PAPERS = [
  { id: '36927031', doi: '10.1126/science.ade2574', title: 'Evolutionary-scale prediction of atomic-level protein structure with a language model', year: '2023' },
  { id: '34265844', doi: '10.1038/s41586-021-03819-2', title: 'Highly accurate protein structure prediction with AlphaFold', year: '2021' },
];

const SOURCES = [
  { id: PAPERS[0]!.doi, title: PAPERS[0]!.title, used_for: 'tool choice' },
  { id: PAPERS[1]!.doi, title: PAPERS[1]!.title, used_for: 'pLDDT thresholds' },
];

const SKILL_META = {
  name: NEW_SKILL,
  title: 'Fold a UniProt entry with ESMFold',
  description: 'Fetch one chain from UniProtKB, fold it with ESMFold, and accept it when pLDDT and pTM are high.',
  applies_when: [APPLIES],
  not_for: ['complexes of two or more chains', 'sequences longer than 400 residues'],
};

const PLAN_A = {
  origin: { kind: 'planned' },
  skill: SKILL_META,
  input_schema: { accession: { type: 'string', description: 'UniProtKB accession' } },
  steps: STEPS,
  checks: CHECKS,
  sources: SOURCES,
  decisions: [
    { topic: 'pTM cut-off', choice: '0.5', reason: 'both papers report pTM, neither sets a threshold', source_silent: true },
  ],
};
const PLAN_B = { ...PLAN_A, origin: { kind: 'skill', skill: NEW_SKILL, version: 1 }, decisions: [] };
const DIGEST_A = sha256(PLAN_A);
const DIGEST_B = sha256(PLAN_B);

const INPUTS_A = { accession: 'P61626' };
const INPUTS_B = { accession: 'P02144' };

const RESEARCH_A = {
  queries: ['"ESMFold" AND "pLDDT" AND monomer', '"single sequence" AND "structure prediction" AND confidence'],
  query_error: null,
  search_errors: [],
  papers: PAPERS,
  corpus_manifest_sha256: sha256(PAPERS),
  extractions: PAPERS.map((p, i) => ({
    paper: p.id,
    doi: p.doi,
    title: p.title,
    year: p.year,
    relevant: true,
    relevance_reason: i === 0 ? 'describes ESMFold and its confidence outputs' : 'defines the pLDDT bands used to read confidence',
    procedure: { steps: ['fold the single sequence', 'read pLDDT and pTM'], tools: [i === 0 ? 'ESMFold' : 'AlphaFold'], parameters: {} },
    reported_numbers: [],
  })),
  tokens_spent: 18420,
  limits: { max_queries: 2, max_papers: 2, token_budget: 40000 },
  stopped_early: null,
};

const MATCH_A = {
  candidates: ['boltz2_heterodimer_interface', 'pdb_chain_sequences'],
  lessons: ['mem_3f2a91', 'mem_91c0d4'],
  decision: 'plan',
  skill: null,
  reason: 'Neither saved skill fits: the Boltz-2 skill is not for single chains, and the PDB skill only reads deposited entries.',
  model: 'mubit:claude-haiku-5-5',
};

const MATCH_B = {
  candidates: ['boltz2_heterodimer_interface', 'pdb_chain_sequences', NEW_SKILL],
  lessons: ['mem_c41a07'],
  decision: 'reuse',
  skill: NEW_SKILL,
  version: 1,
  matched_applies_when: APPLIES,
  input_mapping: { accession: { value: 'P02144' } },
  reason: 'one chain named by its UniProt accession, and no not_for condition applies',
  model: 'mubit:claude-haiku-5-5',
};

const LESSONS_A = [
  'Fetching from UniProt first keeps the input to an accession, which is what people usually have.',
  'Human lysozyme (148 aa) folded at mean pLDDT 91.4 and pTM 0.87, well clear of 70 and 0.5.',
];
const LESSONS_B = ['Myoglobin (154 aa) passed the same frozen checks at pLDDT 89.7, so the skill holds on a second input.'];

// ------------------------------------------------------------------ progress

export const PHASES_A = ['none', 'queued', 'match', 'research', 'plan', 'freeze', 'run', 'run2', 'grade', 'learn', 'done'] as const;
export const PHASES_B = ['none', 'queued', 'match', 'freeze', 'run', 'run2', 'grade', 'learn', 'done'] as const;
export type PhaseA = (typeof PHASES_A)[number];
export type PhaseB = (typeof PHASES_B)[number];

const reached = (p: string, list: readonly string[], target: string) => list.indexOf(p) >= list.indexOf(target);
const statusPhase = (p: string) => (p === 'run2' ? 'run' : p);

/** Phase timestamps, so Folio's per-step durations read like a real run. */
const SECONDS_A: Record<string, number> = { match: 0, research: 4, plan: 45, freeze: 63, run: 64, grade: 116, learn: 118, done: 124 };
const SECONDS_B: Record<string, number> = { match: 0, freeze: 3, run: 4, grade: 53, learn: 55, done: 60 };

function history(p: string, list: readonly string[], start: string, seconds: Record<string, number>) {
  const t0 = Date.parse(start);
  const out: { phase: string; at: string }[] = [];
  for (const step of list.slice(2, list.indexOf(p) + 1)) {
    const phase = statusPhase(step);
    if (out[out.length - 1]?.phase === phase) continue;
    out.push({ phase, at: new Date(t0 + (seconds[phase] ?? 0) * 1000).toISOString().replace('.000', '') });
  }
  return out;
}

const fetchExp = (run: string, len: number, accession: string) => ({
  at: '2026-10-21T15:03:20Z',
  step_id: 'fetch',
  tool: 'fetch_uniprot',
  status: 'ok',
  args: { accession, run_id: run, step_id: 'fetch' },
  result: { tool: 'fetch_uniprot', scores: { length: len }, artifacts: {}, data: {} },
  wave_seconds: 1.2,
});

const foldExp = (run: string, plddt: number, ptm: number, len: number, secs: number) => ({
  at: '2026-10-21T15:04:10Z',
  step_id: 'fold',
  tool: 'esmfold',
  status: 'ok',
  args: { sequence: '…', name: 'query', run_id: run, step_id: 'fold' },
  result: { tool: 'esmfold', scores: { mean_plddt: plddt, ptm, length: len }, artifacts: { structure: `${run}/fold/model.pdb` }, data: {} },
  wave_seconds: secs,
});

function graded(run: string, digest: string, inputs: unknown, plddt: number, ptm: number, len: number) {
  const observed = [plddt, ptm, len];
  const checks = CHECKS.map((c, i) => ({ ...c, status: 'PASS', observed: observed[i] }));
  return {
    run_id: run,
    plan_digest: digest,
    inputs_digest: sha256(inputs),
    verdict: 'PASS',
    checks,
    domain_graders: [],
    metrics: Object.fromEntries(checks.map((c) => [c.metric, c.observed])),
    counts: { PASS: 3, FAIL: 0, UNVERIFIABLE: 0 },
  };
}

export function runA(p: PhaseA) {
  if (p === 'none') return null;
  if (p === 'queued') return { run_id: RUN_A, phase: 'queued' };
  const L = PHASES_A;
  const at = (t: string) => reached(p, L, t);
  const done = p === 'done';
  return {
    run_id: RUN_A,
    status: {
      run_id: RUN_A,
      phase: statusPhase(p),
      history: history(p, L, '2026-10-21T15:02:12Z', SECONDS_A),
      ...(at('run') ? { plan_digest: DIGEST_A, inputs_digest: sha256(INPUTS_A), origin: PLAN_A.origin } : {}),
      ...(done
        ? {
            verdict: 'PASS',
            skill: { action: 'created', skill: NEW_SKILL, version: 1, standing: 'draft' },
            lessons: ['mem_c41a07', 'mem_c41a08'],
            lesson_texts: LESSONS_A,
            summary: 'Human lysozyme folded confidently with ESMFold (mean pLDDT 91.4, pTM 0.87), so all three frozen checks passed.',
          }
        : {}),
    },
    task: TASK_A,
    match: at('research') ? MATCH_A : null,
    research: at('plan') ? RESEARCH_A : null,
    plan: at('freeze') ? PLAN_A : null,
    plan_sha256: at('run') ? DIGEST_A : null,
    inputs: at('run') ? { inputs: INPUTS_A, inputs_digest: sha256(INPUTS_A) } : null,
    experiments: [...(at('run2') ? [fetchExp(RUN_A, 148, 'P61626'), foldExp(RUN_A, 91.4, 0.87, 148, 38.6)] : [])],
    decisions: [],
    results: at('learn') ? graded(RUN_A, DIGEST_A, INPUTS_A, 91.4, 0.87, 148) : null,
  };
}

export function runB(p: PhaseB) {
  if (p === 'none') return null;
  if (p === 'queued') return { run_id: RUN_B, phase: 'queued' };
  const L = PHASES_B;
  const at = (t: string) => reached(p, L, t);
  const done = p === 'done';
  return {
    run_id: RUN_B,
    status: {
      run_id: RUN_B,
      phase: statusPhase(p),
      history: history(p, L, '2026-10-21T15:18:45Z', SECONDS_B),
      ...(at('run') ? { plan_digest: DIGEST_B, inputs_digest: sha256(INPUTS_B), origin: PLAN_B.origin } : {}),
      ...(done
        ? {
            verdict: 'PASS',
            skill: { action: 'evidence_appended', skill: NEW_SKILL, version: 2, standing: 'validated' },
            lessons: ['mem_d0b315'],
            lesson_texts: LESSONS_B,
            summary: 'The saved skill folded myoglobin at mean pLDDT 89.7 and pTM 0.84, and every frozen check passed again.',
          }
        : {}),
    },
    task: TASK_B,
    match: at('freeze') ? MATCH_B : null,
    research: null,
    plan: at('freeze') ? PLAN_B : null,
    plan_sha256: at('run') ? DIGEST_B : null,
    inputs: at('run') ? { inputs: INPUTS_B, inputs_digest: sha256(INPUTS_B) } : null,
    experiments: [...(at('run2') ? [fetchExp(RUN_B, 154, 'P02144'), foldExp(RUN_B, 89.7, 0.84, 154, 36.2)] : [])],
    decisions: [],
    results: at('learn') ? graded(RUN_B, DIGEST_B, INPUTS_B, 89.7, 0.84, 154) : null,
  };
}

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
  lessons: ['Chain sequences read from coordinates can differ from SEQRES where residues are unresolved.'],
  sources: [],
  evidence: ['4HHB', '6M0J', '1UBQ'].map((id, i) => ({
    run_id: ['r-20261016-110301-0a9c44', 'r-20261018-090455-61b2de', 'r-20261020-163015-2b8d4f'][i]!,
    task: `Get the chain sequences of PDB ${id}`,
    inputs_digest: sha256({ pdb_id: id }),
    verdict: 'PASS',
    metrics: { 'entry.scores.n_chains': [4, 2, 1][i]! },
    plan_digest: sha256('pdb'),
  })),
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
  lessons: ['Boltz-2 gave ipTM 0.66 for PD-1 with PD-L1; ppi-assure reported no blocking issue.'],
  sources: [],
  evidence: [{ run_id: 'r-20261020-101422-7c1e09', task: 'Co-fold PD-1 with PD-L1 and report interface confidence', inputs_digest: sha256('pd1'), verdict: 'PASS', metrics: { 'cofold.scores.iptm': 0.66 }, plan_digest: sha256('boltz') }],
  updated_at: '2026-10-20T10:31:40Z',
};

export function skills(a: PhaseA, b: PhaseB): SkillDoc[] {
  const list = [boltzSkill, pdbSkill];
  if (a !== 'done') return list;
  const evidence: Evidence[] = [
    { run_id: RUN_A, task: TASK_A.description, inputs_digest: sha256(INPUTS_A), verdict: 'PASS', metrics: graded(RUN_A, DIGEST_A, INPUTS_A, 91.4, 0.87, 148).metrics, plan_digest: DIGEST_A },
  ];
  const lessons = [...LESSONS_A];
  if (b === 'done') {
    evidence.push({ run_id: RUN_B, task: TASK_B.description, inputs_digest: sha256(INPUTS_B), verdict: 'PASS', metrics: graded(RUN_B, DIGEST_B, INPUTS_B, 89.7, 0.84, 154).metrics, plan_digest: DIGEST_B });
    lessons.push(...LESSONS_B);
  }
  return [
    {
      ...SKILL_META,
      version: evidence.length,
      pipeline: { steps: STEPS, checks: CHECKS },
      input_schema: PLAN_A.input_schema,
      lessons,
      sources: SOURCES,
      evidence,
      updated_at: '2026-10-21T15:04:16Z',
    },
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
  { run_id: 'r-20261019-091207-e4a3b2', description: 'Co-fold KRAS with SOS1 using Chai-1 and one seed', verdict: 'INCONCLUSIVE', origin: { kind: 'planned' }, started_at: '2026-10-19T09:12:07Z' },
  { run_id: 'r-20261018-142233-91fd0a', description: 'Predict a structure for this 612-residue designed protein', verdict: 'FAIL', origin: { kind: 'planned' }, started_at: '2026-10-18T14:22:33Z' },
];

/** GET /runs, newest first. */
export function runList(a: PhaseA, b: PhaseB) {
  const live = [
    [runB(b), TASK_B.description, b] as const,
    [runA(a), TASK_A.description, a] as const,
  ]
    .filter(([doc]) => doc)
    .map(([doc, description, p]) => {
      const status = (doc as { status?: Record<string, unknown> }).status ?? {};
      return {
        run_id: (doc as { run_id: string }).run_id,
        description,
        phase: p === 'queued' ? 'queued' : status.phase,
        verdict: status.verdict ?? null,
        origin: status.origin ?? null,
        skill: status.skill ?? null,
        started_at: ((status.history as { at: string }[] | undefined) ?? [])[0]?.at ?? null,
      };
    });
  return [...live, ...EARLIER.map((r) => ({ ...r, phase: 'done', skill: null }))];
}

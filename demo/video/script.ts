/**
 * Every caption in the film, in the order it appears.
 *
 * The film has no voice-over. Each line is still synthesised (prevoice.mjs)
 * so a scene holds it for as long as it takes to say, which is a comfortable
 * reading time; compose.py then drops the audio and burns the lines in as
 * captions.
 */
export const LINES = {
  mubit: [
    'Five agents do the reasoning. Each is a fixed role with its own prompt.',
    'Every agent call goes through the Mubit gateway, recorded under its role and its run.',
    'After a run, the reviewer turns what went wrong into short lessons in Mubit memory.',
    'Before the next run, Mubit hands those lessons to the planner and tracks which ones led to a pass.',
    'The experiments themselves run on GPUs on Modal.',
  ],
  task: ['Task: fold a 30-residue protein chain and judge whether the fold can be trusted.'],
  run1: [
    'Mubit memory has nothing for this task yet, so labloop plans from scratch.',
    'The planner, called through the Mubit gateway, designs the run and freezes its pass criteria.',
    'One criterion: pTM, the confidence in the overall fold, must be at least 0.5.',
    "ESMFold's predicted structure, colored by per-residue confidence.",
    'pTM comes back at 0.494, so the run fails its own check.',
  ],
  lesson: ["The reviewer's correction: 0.5 is too strict for a chain this short. It is written to Mubit memory."],
  memory: [
    'Mubit stores the lesson with the run it came from.',
    'When the same task comes back, Mubit retrieves it before any planning starts.',
  ],
  run2: [
    'Same task, second run.',
    'This time one lesson is recalled from Mubit memory.',
    'The planner applies it and freezes a pTM floor of 0.3.',
    'The run passes. The pipeline is saved as a skill, and Mubit marks the lesson as one that worked.',
  ],
  reuse: [
    'Later, a new protein: Trp-cage, 20 residues.',
    'It matches the saved skill, so research and planning are skipped.',
    'A second pass on different inputs makes the skill validated.',
  ],
  outro: [
    'One correction in Mubit memory turned a failed check into a reusable skill.',
    'Each role builds its own recorded history in Mubit, and its model is one setting away from a smaller, task-adapted one.',
    'New proteins and new papers keep adding lessons, so every run starts from what the last one learned.',
  ],
} as const;

/**
 * Every line of narration in the film, in the order it is spoken.
 *
 * Kept in one file so the script can be read and edited as a script, and so
 * prevoice.mjs can synthesise every line before filming: a scene then holds
 * each line for its real length and no two lines overlap. Numbers are
 * written as words because that is how the voice should say them.
 */
export const LINES = {
  intro: [
    'This is lab loop, our project for the Mubit hackathon.',
    "It's an AI lab for protein experiments. Agents plan each experiment, run it on GPUs, and check the result.",
    'Mubit is what lets it learn from each run.',
  ],
  mubit: [
    'Five AI agents do the reasoning, on Claude Opus 5 and Claude Haiku.',
    'Every call they make goes through the Mubit gateway, which records it and files it under the run it belongs to.',
    'After each run, the reviewer writes short lessons into Mubit memory.',
    'Before the next run, the planner gets those lessons back, and Mubit tracks which ones led to a pass.',
    'The experiments run on GPUs on Modal.',
  ],
  task: [
    "Here's the lab loop website.",
    "We'll fold one protein chain, thirty amino acids long.",
    'We want its 3D structure, and whether to trust it.',
  ],
  run1: [
    'Mubit memory has no lessons for this yet, and no saved skill fits, so it starts from scratch.',
    'It reads the literature with Paper Q A two.',
    'Every paper it reads is frozen into the run, so you can open the exact text it used.',
    'The planner designs one ESMFold prediction, with two checks it must pass.',
    "One says the pTM score, the model's confidence in the overall fold, must be at least zero point five.",
    'The predicted structure appears in the run, colored by how confident the model is in each residue.',
    'But the pTM comes back at zero point four nine four, just under the line, so the run fails its own check.',
  ],
  lesson: [
    'The reviewer works out why: zero point five is too strict for a chain this short.',
    'That lesson is saved to Mubit memory.',
  ],
  memory: [
    'Mubit stores that lesson with the run it came from.',
    'When the same task comes back, Mubit hands the lesson to the planner.',
    'So the planner sets the pTM floor at zero point three.',
  ],
  run2: [
    'Now we run the exact same task again.',
    'This time the log shows one lesson recalled from Mubit memory.',
    'The planner freezes a pTM floor of zero point three.',
    'The same fold passes, and lab loop saves the pipeline as a reusable skill.',
    'Mubit records that the lesson led to a pass, and keeps a copy of the new skill.',
  ],
  report: [
    "Every run also writes a report, built from the run's own records with no model writing it.",
    'It draws the pipeline, and each check against its threshold.',
    'And the predicted structure, with the confidence of every residue.',
  ],
  reuse: [
    'Later we try a different short protein, the twenty residue trip cage.',
    'It matches the saved skill and quotes the condition it matched, so research and planning are skipped.',
    'It passes on new inputs, so the skill is now validated.',
  ],
  outro: [
    'One lesson in Mubit memory turned a failed check into a reusable skill.',
    'The Mubit gateway records every agent call, and Mubit memory lets each run start from what earlier runs learned.',
  ],
} as const;

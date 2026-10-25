// Prints the finished bundles of the three mocked runs, for make_reports.py.
import { runA, runB, runC } from './world.ts';

process.stdout.write(JSON.stringify([runA('done'), runB('done'), runC('done')]));

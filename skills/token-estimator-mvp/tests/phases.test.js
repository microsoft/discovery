'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { createEstimator } = require('../scripts/model.js');
const root = path.resolve(__dirname, '..');
const estimator = createEstimator({
  calibration: JSON.parse(fs.readFileSync(path.join(root, 'resources/calibration.json'))),
  profiles: JSON.parse(fs.readFileSync(path.join(root, 'resources/work-profiles.json')))
});

const cases = [
  ['Develop a simulation implementation package for one focused task.', 'simulation-implementation', 3000000, 10000000],
  ['Correct and validate one existing simulation implementation.', 'simulation-correction', 3000000, 10000000],
  ['Develop one bounded simulation packing sweep with included checks.', 'simulation-sweep', 3000000, 10000000],
  ['Develop one initial synthetic predictive model prototype.', 'prediction-synthetic-prototype', 3000000, 10000000],
  ['Develop and validate one real-data predictive trajectory model.', 'prediction-real-data-trajectory', 10000000, 30000000],
  ['Develop and validate one real-data predictive distribution model.', 'prediction-real-data-distribution', 10000000, 30000000],
  ['Integrate and debug one prediction workflow using existing component models.', 'prediction-pipeline-integration', 30000000, 100000000]
];

function cli(input) {
  const run = spawnSync(process.execPath, [path.join(root, 'scripts/estimate.js')], {
    input: JSON.stringify(input), encoding: 'utf8', env: {}, timeout: 10000
  });
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}

test('phase-specific language resolves to expected phase and range', () => {
  for (const [description, phaseId, lower, upper] of cases) {
    const input = { contractVersion: '1.2.0', tasks: [{ id: phaseId, description, bounded: true }] };
    const output = estimator.estimate(input);
    assert.equal(output.tasks[0].phaseId, phaseId);
    assert.deepEqual(output.totalTokens, { lower, upper, unit: 'input_plus_output_tokens' });
    assert.deepEqual(cli(input), output);
  }
});

test('broad prediction and simulation requests use phase envelope without forced phase', () => {
  const prediction = estimator.estimate({ contractVersion: '1.2.0', tasks: [{ id: 'p', description: 'Develop a prediction workflow.', bounded: true }] });
  assert.equal(prediction.tasks[0].phaseId, null);
  assert.deepEqual(prediction.totalTokens, { lower: 3000000, upper: 100000000, unit: 'input_plus_output_tokens' });
  const simulation = estimator.estimate({ contractVersion: '1.2.0', tasks: [{ id: 's', description: 'Simulation work', bounded: true }] });
  assert.equal(simulation.tasks[0].phaseId, null);
  assert.deepEqual(simulation.totalTokens, { lower: 3000000, upper: 10000000, unit: 'input_plus_output_tokens' });
});

test('legacy input versions remain accepted', () => {
  for (const contractVersion of ['1.0.0', '1.1.0', '1.2.0']) {
    const output = estimator.estimate({
      contractVersion,
      tasks: [{ id: 'legacy', profileId: 'prediction-development-validation', phaseId: 'prediction-pipeline-integration', bounded: true }]
    });
    assert.equal(output.contractVersion, '1.2.0');
  }
});

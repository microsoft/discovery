'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');
const { VERSION, createEstimator } = require('../scripts/model.js');
const root = path.resolve(__dirname, '..');
const load = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const estimator = createEstimator({
  calibration: load('resources/calibration.json'),
  profiles: load('resources/work-profiles.json')
});

function cli(input) {
  const run = spawnSync(process.execPath, [path.join(root, 'scripts/estimate.js')], {
    input: JSON.stringify(input), encoding: 'utf8', env: {}, timeout: 10000
  });
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}

function scenario(description, extra = {}) {
  return { contractVersion: VERSION, tasks: [{ id: 'task', description, bounded: true, ...extra }] };
}

test('API and CLI produce identical JSON', () => {
  const input = scenario('Screen literature for one focused evidence table.');
  assert.deepEqual(cli(input), estimator.estimate(input));
});

test('browser global is TokenEstimation and matches the Node API', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(root, 'scripts/model.js'), 'utf8'), context);
  assert.ok(context.TokenEstimation);
  const browser = context.TokenEstimation.createEstimator({
    calibration: load('resources/calibration.json'),
    profiles: load('resources/work-profiles.json')
  });
  const input = scenario('Develop a prediction workflow.');
  assert.deepEqual(JSON.parse(JSON.stringify(browser.estimate(input))), estimator.estimate(input));
});

test('sanitized provenance excludes raw session/source/token payloads', () => {
  const output = estimator.estimate(scenario('Develop and validate one real-data predictive trajectory model.'));
  const evidence = output.tasks[0].provenance.evidence[0];
  assert.ok(evidence.observationId);
  assert.ok(evidence.attributionUnit);
  assert.ok(evidence.calibrationRef);
  assert.ok(evidence.summary);
  assert.ok(Array.isArray(evidence.limitations));
  for (const forbidden of ['sessionId', 'sourceTaskId', 'sourceRunId', 'sourceIds', 'sources', 'tokens', 'metrics', 'coverage', 'unknowns', 'containedIn']) {
    assert.equal(Object.hasOwn(evidence, forbidden), false);
  }
});

test('coarse ranges remain stable by class', () => {
  const expected = [
    ['evidence-assessment', 1000000, 3000000],
    ['literature-screening-synthesis', 3000000, 10000000],
    ['tool-verification-analysis', 3000000, 10000000],
    ['simulation-development-execution', 3000000, 10000000],
    ['prediction-development-validation', 3000000, 100000000],
    ['existing-workflow-operation', 300000, 3000000]
  ];
  for (const [profileId, lower, upper] of expected) {
    const out = estimator.estimate({ contractVersion: VERSION, tasks: [{ id: profileId, profileId, bounded: true }] });
    assert.deepEqual(out.totalTokens, { lower, upper, unit: 'input_plus_output_tokens' });
  }
});

test('unsupported requests remain unknown', () => {
  const output = estimator.estimate(scenario('Build a full greenfield project from scratch with all components.'));
  assert.equal(output.status, 'unknown');
  assert.equal(output.totalTokens, null);
  assert.ok(output.tasks[0].unknownReasons.length > 0);
});

'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { VERSION, createEstimator } = require('../scripts/model.js');
const root = path.resolve(__dirname, '..');
const load = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const estimator = createEstimator({
  calibration: load('resources/calibration.json'),
  profiles: load('resources/work-profiles.json')
});

function request(tasks, extra = {}) {
  return { contractVersion: VERSION, tasks, ...extra };
}

function cli(input) {
  const run = spawnSync(process.execPath, [path.join(root, 'scripts/estimate.js')], {
    input: JSON.stringify(input), encoding: 'utf8', env: {}, timeout: 10000
  });
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}

test('known-plus-unknown composition keeps subtotal separate from total', () => {
  const input = request([
    { id: 'known', profileId: 'literature-screening-synthesis', bounded: true },
    { id: 'unknown', description: 'Invent a brand new full project from scratch.', bounded: true }
  ], { nonOverlap: true });
  const output = estimator.estimate(input);
  assert.equal(output.status, 'partial');
  assert.equal(output.totalTokens, null);
  assert.ok(output.knownSubtotalTokens);
  assert.deepEqual(cli(input), output);
});

test('concurrency only changes scheduling metadata', () => {
  const base = estimator.estimate(request([{ id: 'one', profileId: 'evidence-assessment', bounded: true }]));
  const concurrent = estimator.estimate(request([{ id: 'one', profileId: 'evidence-assessment', bounded: true }], { concurrency: 8 }));
  assert.deepEqual(base.totalTokens, concurrent.totalTokens);
  assert.equal(concurrent.scheduling.requestedConcurrency, 8);
  assert.equal(concurrent.scheduling.changesConsumption, false);
});

test('schema-like contract checks reject malformed input and token fields', () => {
  assert.throws(() => estimator.estimate(request([{ id: 'bad', description: 'Screen', count: 0 }])));
  assert.throws(() => estimator.estimate(request([{ id: 'bad', description: 'Screen', tokens: 100 }])));
  assert.throws(() => estimator.estimate({ contractVersion: VERSION, tasks: [] }));
  const badCli = spawnSync(process.execPath, [path.join(root, 'scripts/estimate.js')], { input: '{', encoding: 'utf8' });
  assert.equal(badCli.status, 1);
  const parsed = JSON.parse(badCli.stderr);
  assert.ok(parsed.error && parsed.error.code && parsed.error.message);
});

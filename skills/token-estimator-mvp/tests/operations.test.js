'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { createEstimator, VERSION } = require('../scripts/model.js');
const root = path.resolve(__dirname, '..');
const estimator = createEstimator({
  calibration: JSON.parse(fs.readFileSync(path.join(root, 'resources/calibration.json'))),
  profiles: JSON.parse(fs.readFileSync(path.join(root, 'resources/work-profiles.json')))
});
const baseRange = { lower: 300000, upper: 3000000, unit: 'input_plus_output_tokens' };
const ready = 'Read instructions and inputs, prepare commands, launch an existing simulation and confirm startup/status/errors.';

function scenario(description = ready, extra = {}) {
  return {
    contractVersion: VERSION,
    tasks: [{ id: 'operation', description, bounded: true, readiness: 'ready', validation: 'included', ...extra }]
  };
}

function run(input) {
  const api = estimator.estimate(input);
  const cli = spawnSync(process.execPath, [path.join(root, 'scripts/estimate.js')], {
    input: JSON.stringify(input), encoding: 'utf8', env: {}, timeout: 10000
  });
  assert.equal(cli.status, 0, cli.stderr);
  assert.deepEqual(JSON.parse(cli.stdout), api);
  return api;
}

test('existing workflow operation returns bounded launch range', () => {
  const output = run(scenario());
  assert.equal(output.status, 'estimated');
  assert.deepEqual(output.totalTokens, baseRange);
  assert.equal(output.tasks[0].profileId, 'existing-workflow-operation');
  assert.equal(output.tasks[0].phaseId, 'existing-workflow-launch');
  assert.equal(output.tasks[0].provenance.evidence.length, 4);
});

test('unresolved readiness preserves conditional base', () => {
  const output = run(scenario(ready, { readiness: 'unresolved' }));
  assert.equal(output.status, 'partial');
  assert.equal(output.totalTokens, null);
  assert.deepEqual(output.knownSubtotalTokens, baseRange);
  assert.ok(output.clarifications.length > 0);
});

test('ongoing monitoring and open-ended requests remain partial', () => {
  for (const input of [
    scenario(ready, { monitoring: 'ongoing' }),
    scenario('Launch an existing workflow and monitor until completion.'),
    scenario('Troubleshoot an existing workflow with unlimited retries until success.')
  ]) {
    const output = run(input);
    assert.equal(output.status, 'partial');
    assert.equal(output.totalTokens, null);
    assert.deepEqual(output.knownSubtotalTokens, baseRange);
  }
});

test('resource-only operational requests remain unknown', () => {
  const output = run(scenario('Only estimate GPU runtime and cost for the existing simulation.'));
  assert.equal(output.status, 'unknown');
  assert.equal(output.totalTokens, null);
  assert.equal(output.knownSubtotalTokens, null);
});

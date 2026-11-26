'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { createEstimator } = require('../scripts/model.js');
const { assertPublicSafePackage } = require('./privacy-guard.cjs');
const root = path.resolve(__dirname, '..');
const load = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const hashes = load('tests/accepted-hashes.json');
const estimator = createEstimator({
  calibration: load('resources/calibration.json'),
  profiles: load('resources/work-profiles.json')
});

function cli(directory, inputFile) {
  const child = spawnSync(process.execPath, [path.join(directory, 'scripts/estimate.js'), '--input', path.join(directory, 'examples', inputFile)], {
    cwd: directory, env: {}, encoding: 'utf8', timeout: 10000
  });
  assert.equal(child.status, 0, child.stderr);
  return JSON.parse(child.stdout);
}

test('accepted hashes match expected runtime bytes', () => {
  for (const [relative, expected] of Object.entries(hashes)) {
    const actual = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, relative))).digest('hex');
    assert.equal(actual, expected, relative);
  }
});

test('examples execute and match API output', () => {
  const examples = fs.readdirSync(path.join(root, 'examples')).filter(file => file.endsWith('.json'));
  for (const file of examples) {
    const input = load(path.join('examples', file));
    assert.deepEqual(cli(root, file), estimator.estimate(input));
  }
});

test('portable copy works in another project path', () => {
  const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'token-estimator-package-'));
  const destination = path.join(sandbox, 'project/skills/token-estimator-mvp');
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.cpSync(root, destination, { recursive: true });
  try {
    const result = cli(destination, 'description.json');
    assert.equal(result.status, 'estimated');
  } finally {
    fs.rmSync(sandbox, { recursive: true, force: true });
  }
});

test('forbidden identifier scan across package text files', () => {
  assertPublicSafePackage(root);
});

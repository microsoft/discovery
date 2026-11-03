'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

test('guidance emphasizes coarse planning and public-safe provenance', () => {
  const skill = read('SKILL.md');
  const input = read('references/input-guide.md');
  const evidence = read('references/operational-evidence.md');
  const examples = read('examples/README.md');
  assert.match(skill, /1\.2\.0/);
  assert.match(skill, /conditional/i);
  assert.match(input, /phaseId.*optional/i);
  assert.match(evidence, /provisional/i);
  assert.match(examples, /coarse/i);
});

test('model and package versions remain aligned', () => {
  const { VERSION } = require('../scripts/model.js');
  const pkg = JSON.parse(read('package.json'));
  assert.equal(VERSION, '1.2.0');
  assert.equal(pkg.version, VERSION);
});

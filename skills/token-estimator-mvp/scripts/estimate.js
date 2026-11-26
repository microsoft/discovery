#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createEstimator } = require('./model.js');

try {
  const args = process.argv.slice(2);
  if (args.length && (args.length !== 2 || args[0] !== '--input')) {
    throw new Error('Usage: node scripts/estimate.js [--input scenario.json]; otherwise reads JSON from stdin');
  }
  const resources = path.join(__dirname, '..', 'resources');
  const estimator = createEstimator({
    calibration: JSON.parse(fs.readFileSync(path.join(resources, 'calibration.json'), 'utf8')),
    profiles: JSON.parse(fs.readFileSync(path.join(resources, 'work-profiles.json'), 'utf8'))
  });
  const input = JSON.parse(fs.readFileSync(args.length ? args[1] : 0, 'utf8'));
  process.stdout.write(JSON.stringify(estimator.estimate(input), null, 2) + '\n');
} catch (error) {
  process.stderr.write(JSON.stringify({ error: { code: error.code || 'ESTIMATION_ERROR', message: error.message, path: error.path || null } }) + '\n');
  process.exitCode = 1;
}

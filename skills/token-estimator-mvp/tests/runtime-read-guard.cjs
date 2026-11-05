'use strict';
const fs = require('node:fs');
const path = require('node:path');
const root = fs.realpathSync(path.resolve(__dirname, '..')) + path.sep;
const original = fs.readFileSync;

// Test instrumentation for the unchanged CLI's synchronous file-read surface.
fs.readFileSync = function (file, ...args) {
  if (file !== 0 && (typeof file !== 'string' || !fs.realpathSync(file).startsWith(root))) {
    throw new Error('Portable estimator attempted a read outside its copied package');
  }
  return original.call(this, file, ...args);
};

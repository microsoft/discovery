'use strict';
// Bounded test instrumentation, not an OS sandbox or the estimator runtime.
const fs = require('node:fs');
const path = require('node:path');
const root = fs.realpathSync(path.resolve(__dirname, '..'));
const allowed = new Set([
  'package.json', 'scripts/estimate.js', 'scripts/model.js',
  'resources/calibration.json', 'resources/work-profiles.json',
  'examples/context/README.md', 'examples/context/computational.md',
  'examples/context/operation.md'
].map(file => path.join(root, file)));
const realpath = fs.realpathSync;
function check(file) {
  if (file === 0) return;
  const resolved = realpath(file);
  const relative = path.relative(root, resolved);
  if (!allowed.has(resolved) && !/^examples\/[^/]+\.json$/.test(relative)) {
      throw new Error('PORTABLE_READ_DENIED: outside explicit portable allowlist');
  }
}
for (const name of ['readFileSync', 'readFile', 'openSync', 'open']) {
  const original = fs[name];
  fs[name] = function (file, ...args) {
    check(file);
    if ((name === 'open' || name === 'openSync') && args[0] !== 'r') {
        throw new Error('PORTABLE_WRITE_DENIED');
    }
    return original.call(this, file, ...args);
  };
}
for (const name of ['readFile', 'open']) {
  const original = fs.promises[name];
  fs.promises[name] = async function (file, ...args) {
    check(file);
    if (name === 'open' && args[0] !== 'r') throw new Error('PORTABLE_WRITE_DENIED');
    return original.call(this, file, ...args);
  };
}
const deny = () => { throw new Error('PORTABLE_NETWORK_OR_EXECUTION_DENIED'); };
for (const [moduleName, methods] of [
  ['node:child_process', ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']],
  ['node:net', ['connect', 'createConnection', 'createServer']],
  ['node:tls', ['connect', 'createServer']],
  ['node:http', ['request', 'get', 'createServer']],
  ['node:https', ['request', 'get', 'createServer']],
  ['node:dns', ['lookup', 'resolve']],
  ['node:dgram', ['createSocket']]
]) {
  const module = require(moduleName);
  for (const method of methods) module[method] = deny;
}
globalThis.fetch = deny;
for (const name of ['writeFileSync', 'writeFile', 'appendFileSync', 'appendFile',
  'truncateSync', 'truncate', 'unlinkSync', 'unlink', 'renameSync', 'rename']) {
  fs[name] = () => { throw new Error('PORTABLE_WRITE_DENIED'); };
}

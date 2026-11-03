'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const identifierHashes = new Set([
  'aa177408a6c68051a48891f82795a6d6170b6ff351d87c8ead379b21e9552538',
  'dfef9892f52a9eeaebab0bd62dca812c74b8ff8f7dc85adb90e953786cf77c5a',
  '799ef92a11af918e3fb741df42934f3b568ed2d93ac1df74f1b8d41a27932a6f',
  '24415532349ddf70d3550bba448ed17c6faa8b74933206b562a15488f38162ee',
  '8b4f7a9af51f78c4867caa3a66a22cc63be8dcfbb023c8a8958d47f7c944405d',
  '1ab55a41a2f80839c4a7d53c4e09be8c0c893fad01ed2837f0d8302f39fbf0a8',
  '2240afb9f3eab95555ac34c98d85de0b7a3efea76becca97393185cb3d292754',
  'bd250b7f8e235030b20914f7608482d124794b3fb98a20acea2bae76542929e8',
  '44abe4ace21b534dfb1eef35741807ec85dd1766486a86fd7d6b5a822f58e470',
  'e1da56cea11d82854bc43636e397c95c30f6c958c2975e7c6ef6ae60f124dcaa',
  'a56f3dbc3053cc78282ebb4360025187945043453f94099157496b76530a404d'
]);

const structuralPatterns = [
  /\b[A-Z]{2}-[0-9]+\b/,
  /\/Users\//,
  /\.discovery\//,
  /\.copilot(?:\/|-)/,
  /[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i
];

function digest(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function files(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(directory, entry.name);
    return entry.isDirectory() ? files(full) : [full];
  });
}

function assertPublicSafePackage(root) {
  const textFiles = files(root).filter(file => /\.(md|json|js|cjs|txt|sh)$/i.test(file));
  for (const file of textFiles) {
    const text = fs.readFileSync(file, 'utf8');
    const relative = path.relative(root, file);
    for (const pattern of structuralPatterns) {
      assert.doesNotMatch(text, pattern, relative + ': internal identifier pattern');
    }
    for (const token of text.toLowerCase().match(/[a-z0-9]+/g) || []) {
      assert.equal(identifierHashes.has(digest(token)), false, relative + ': restricted identifier');
    }
  }
}

module.exports = { assertPublicSafePackage };

import { createHash } from 'node:crypto'
import { constants } from 'node:fs'
import {
  lstat,
  open,
  opendir,
  realpath,
} from 'node:fs/promises'
import {
  isAbsolute,
  relative,
  resolve,
} from 'node:path'

const runtimeRoot = import.meta.dirname
const generatedRoot = resolve(runtimeRoot, 'generated')
const lockPath = resolve(
  generatedRoot,
  'data',
  'flowblind-catalog-hidden-flow-package-lock-v1.json',
)
const runtimeAuthorities = new WeakSet()
const maximumPackageFileBytes = 128 * 1024 * 1024
const verifierReference =
  'flowblind-hidden-flow-capability-verification-v1.mjs'

export const expectedLockIdentity = Object.freeze({
  byteLength: __LOCK_BYTE_LENGTH__,
  sha256: '__LOCK_SHA256__',
})

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

function fail(detail, code = 'package-attestation-failed') {
  throw Object.assign(new Error(detail), { code })
}

function throwIfAborted(signal) {
  if (signal?.aborted === true) {
    fail(
      'Hidden-flow package verification was cancelled.',
      'operation-cancelled',
    )
  }
}

function samePath(left, right) {
  const normalizedLeft = resolve(left)
  const normalizedRight = resolve(right)
  return process.platform === 'win32'
    ? normalizedLeft.toLowerCase() ===
        normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight
}

function referencePath(value, label) {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.includes('\\') ||
    value.startsWith('/') ||
    value.split('/').some(
      (part) =>
        part.length === 0 ||
        part === '.' ||
        part === '..',
    )
  ) {
    fail(`${label} is not a safe portable package path.`)
  }
  return value
}

function assertUnique(values, label) {
  if (
    new Set(values).size !== values.length ||
    new Set(values.map((value) => value.toLowerCase()))
      .size !== values.length
  ) {
    fail(
      `${label} contains duplicate or case-aliased values.`,
    )
  }
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue)
  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, stableValue(value[key])]),
    )
  }
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return value
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  throw new Error(
    'Hidden-flow package records may contain only finite JSON values.',
  )
}

function stableJson(value) {
  return `${JSON.stringify(stableValue(value), null, 2)}\n`
}

function deepFreeze(value) {
  if (
    typeof value !== 'object' ||
    value === null ||
    Object.isFrozen(value)
  ) {
    return value
  }
  for (const nested of Object.values(value)) {
    deepFreeze(nested)
  }
  return Object.freeze(value)
}

function confined(root, reference, label) {
  const path = resolve(root, reference)
  const child = relative(root, path)
  if (
    child.length === 0 ||
    child === '..' ||
    child.startsWith(
      `..${process.platform === 'win32' ? '\\' : '/'}`,
    ) ||
    isAbsolute(child)
  ) {
    throw Object.assign(
      new Error(
        `${label} escapes the portable hidden-flow package.`,
      ),
      { code: 'package-attestation-failed' },
    )
  }
  return path
}

async function verifiedBytes(
  path,
  expected,
  label,
  signal,
) {
  throwIfAborted(signal)
  const metadata = await lstat(path)
  const canonical = await realpath(path)
  const canonicalRoot = await realpath(runtimeRoot)
  const expectedCanonical = resolve(
    canonicalRoot,
    relative(runtimeRoot, path),
  )
  if (
    metadata.isSymbolicLink() ||
    !metadata.isFile() ||
    metadata.nlink !== 1 ||
    metadata.size !== expected.byteLength ||
    metadata.size > maximumPackageFileBytes ||
    !samePath(expectedCanonical, canonical)
  ) {
    throw Object.assign(
      new Error(`${label} must be an ordinary reviewed file.`),
      { code: 'package-attestation-failed' },
    )
  }
  const handle = await open(
    path,
    constants.O_RDONLY |
      (typeof constants.O_NOFOLLOW === 'number'
        ? constants.O_NOFOLLOW
        : 0),
  )
  try {
    const before = await handle.stat({ bigint: true })
    if (
      !before.isFile() ||
      before.nlink !== 1n ||
      before.size !== BigInt(expected.byteLength)
    ) {
      fail(`${label} changed before it could be read.`)
    }
    const chunks = []
    let total = 0
    while (true) {
      throwIfAborted(signal)
      const chunk = Buffer.allocUnsafe(64 * 1024)
      const { bytesRead } = await handle.read(
        chunk,
        0,
        chunk.byteLength,
        null,
      )
      if (bytesRead === 0) break
      total += bytesRead
      if (total > expected.byteLength) {
        throw Object.assign(
          new Error(
            `${label} exceeds its reviewed byte length.`,
          ),
          { code: 'package-attestation-failed' },
        )
      }
      chunks.push(chunk.subarray(0, bytesRead))
    }
    const bytes = Buffer.concat(chunks, total)
    const after = await handle.stat({ bigint: true })
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.nlink !== after.nlink ||
      before.size !== after.size ||
      before.mtimeNs !== after.mtimeNs ||
      bytes.byteLength !== expected.byteLength ||
      sha256(bytes) !== expected.sha256
    ) {
      throw Object.assign(
        new Error(
          `${label} does not match its reviewed identity.`,
        ),
        { code: 'package-attestation-failed' },
      )
    }
    return bytes
  } finally {
    await handle.close()
  }
}

function expectedRuntimeTree(lock) {
  const files = [
    verifierReference,
    referencePath(
      lock.publicRuntime.bundledPath,
      'Hidden-flow public runtime path',
    ),
    'generated/data/flowblind-catalog-hidden-flow-package-lock-v1.json',
    ...lock.facades.map((item) =>
      referencePath(
        item.bundledPath,
        `Hidden-flow facade ${item.id}`,
      ),
    ),
    ...lock.artifacts.map((item) =>
      `generated/${referencePath(
        item.bundledPath,
        `Hidden-flow artifact ${item.id}`,
      )}`,
    ),
  ]
  assertUnique(files, 'The hidden-flow runtime file allowlist')
  const directories = new Set()
  for (const file of files) {
    const parts = file.split('/')
    for (let index = 1; index < parts.length; index += 1) {
      directories.add(parts.slice(0, index).join('/'))
    }
  }
  return {
    files: new Set(files),
    directories,
  }
}

async function verifyExactRuntimeTree(lock, signal) {
  throwIfAborted(signal)
  const rootMetadata = await lstat(runtimeRoot)
  const canonicalRoot = await realpath(runtimeRoot)
  if (
    rootMetadata.isSymbolicLink() ||
    !rootMetadata.isDirectory()
  ) {
    fail(
      'The hidden-flow runtime root must be one ordinary directory.',
    )
  }
  const expected = expectedRuntimeTree(lock)
  const seen = new Set()
  const seenFolded = new Set()
  let entryCount = 0
  const maximumEntries =
    expected.files.size + expected.directories.size

  async function visit(current, prefix = '') {
    const directory = await opendir(current)
    for await (const entry of directory) {
      throwIfAborted(signal)
      entryCount += 1
      if (entryCount > maximumEntries) {
        fail(
          'The hidden-flow runtime tree contains unmanifested entries.',
        )
      }
      const reference = prefix.length === 0
        ? entry.name
        : `${prefix}/${entry.name}`
      const folded = reference.toLowerCase()
      if (
        seen.has(reference) ||
        seenFolded.has(folded)
      ) {
        fail(
          'The hidden-flow runtime tree contains duplicate or case-aliased paths.',
        )
      }
      seen.add(reference)
      seenFolded.add(folded)
      const path = resolve(current, entry.name)
      const metadata = await lstat(path)
      if (
        metadata.isSymbolicLink() ||
        (!metadata.isFile() &&
          !metadata.isDirectory())
      ) {
        fail(
          `${reference} is a link or unsupported runtime entry.`,
        )
      }
      const canonical = await realpath(path)
      const expectedCanonical = resolve(
        canonicalRoot,
        relative(runtimeRoot, path),
      )
      if (!samePath(expectedCanonical, canonical)) {
        fail(`${reference} is an aliased runtime entry.`)
      }
      if (metadata.isDirectory()) {
        if (!expected.directories.has(reference)) {
          fail(
            `${reference} is an unmanifested runtime directory.`,
          )
        }
        await visit(path, reference)
      } else if (
        metadata.nlink !== 1 ||
        !expected.files.has(reference)
      ) {
        fail(
          `${reference} is an unmanifested or linked runtime file.`,
        )
      }
    }
  }

  await visit(runtimeRoot)
  if (
    entryCount !== maximumEntries ||
    [...expected.files].some(
      (reference) => !seen.has(reference),
    ) ||
    [...expected.directories].some(
      (reference) => !seen.has(reference),
    )
  ) {
    fail(
      'The hidden-flow runtime tree is missing one or more manifest-required entries.',
    )
  }
}

function assertLockEntries(lock) {
  const artifacts = lock.artifacts
  const facades = lock.facades
  assertUnique(
    artifacts.map((item) => item.id),
    'The hidden-flow artifact manifest',
  )
  assertUnique(
    artifacts.map((item) =>
      referencePath(
        item.bundledPath,
        `Hidden-flow artifact ${item.id}`,
      ),
    ),
    'The hidden-flow artifact path manifest',
  )
  assertUnique(
    facades.map((item) => item.id),
    'The hidden-flow facade manifest',
  )
  assertUnique(
    facades.map((item) =>
      referencePath(
        item.bundledPath,
        `Hidden-flow facade ${item.id}`,
      ),
    ),
    'The hidden-flow facade path manifest',
  )
}

function artifact(lock, id) {
  const value = lock.artifacts.find(
    (candidate) => candidate.id === id,
  )
  if (!value) {
    throw Object.assign(
      new Error(
        `Hidden-flow package artifact ${id} is missing.`,
      ),
      { code: 'package-attestation-failed' },
    )
  }
  return value
}

function identity(value) {
  return {
    reference: `runtime/generated/${value.bundledPath}`,
    byteLength: value.byteLength,
    sha256: value.sha256,
    mediaType: value.mediaType,
  }
}

function assertPolicy(policy) {
  if (
    policy.schemaVersion !== 1 ||
    policy.id !==
      'flowblind-catalog-hidden-flow-generic-review-policy-v1' ||
    policy.policyVersion !== '1.0.0' ||
    policy.authorityVersion !==
      'attested-generic-hidden-flow-problem-authority-v1' ||
    policy.reviewScope !==
      'generic-problem-contract-parser-and-executable-preflight-only' ||
    policy.subject?.parser !== 'parseHiddenFlowProblem' ||
    policy.subject?.genericProblemSchemaRole !==
      'syntactic-prefilter-only' ||
    policy.subject?.problemAcceptanceSchema !==
      'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json' ||
    JSON.stringify(policy.subject?.allowedObservationTypes) !==
      JSON.stringify([
        'point-component',
        'point-direction',
      ]) ||
    JSON.stringify(policy.subject?.allowedTargetTypes) !==
      JSON.stringify([
        'point-component',
        'point-direction',
        'point-speed-envelope',
        'region-component',
        'point-strain-component',
      ]) ||
    policy.runtime?.pythonRequirementsSha256 !==
      '1ffda1962375e2d2d77b794b7a930d55902869a2923e695ad333a3f8e0d7a4ed' ||
    policy.runtime?.networkRequiredAtRuntime !== false ||
    policy.runtime?.confinement?.user !== '10001:10001' ||
    policy.runtime?.confinement?.rootFilesystem !==
      'read-only' ||
    policy.runtime?.confinement?.network !== 'none' ||
    policy.assertions?.physicalTruth !== 'not-attested' ||
    policy.assertions?.sourceAccuracy !== 'not-attested' ||
    policy.assertions?.modelOrUserApproval !==
      'not-accepted-as-authority'
  ) {
    throw Object.assign(
      new Error(
        'The generic hidden-flow review policy exceeds or changes its reviewed authority.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
}

function assertDeclaration(declaration) {
  const properties =
    declaration.publicInputSchema?.properties
  const actions = declaration.actions
  if (
    declaration.schemaVersion !== 1 ||
    declaration.id !==
      'flowblind-catalog-hidden-flow-declaration-v1' ||
    declaration.packageVersion !== '1.0.0' ||
    declaration.publicInputSchema?.additionalProperties !==
      false ||
    JSON.stringify(Object.keys(properties ?? {}).sort()) !==
      JSON.stringify(['details', 'goal']) ||
    JSON.stringify(
      declaration.publicInputSchema?.required,
    ) !== JSON.stringify(['goal']) ||
    !Array.isArray(actions) ||
    actions.length !== 2 ||
    actions[0]?.name !== 'prepare-study' ||
    actions[0]?.confirmation !== 'Disabled' ||
    actions[0]?.resultFree !== true ||
    actions[1]?.name !== 'run-and-verify-study' ||
    actions[1]?.confirmation !== 'Enabled' ||
    actions[1]?.resultFree !== false ||
    declaration.runtime?.nonRootUser !== '10001:10001' ||
    declaration.runtime?.rootFilesystem !== 'read-only' ||
    declaration.runtime?.network !== 'none'
  ) {
    throw Object.assign(
      new Error(
        'The hidden-flow declaration does not preserve the reviewed two-action boundary.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
  const text = JSON.stringify(
    declaration.publicInputSchema,
  )
  if (
    /sha256|byteLength|path|problemId|targetId|threshold|approved|approval|confirmation/iu.test(
      text,
    )
  ) {
    throw Object.assign(
      new Error(
        'The scientist input schema exposes a forbidden technical or approval field.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
}

export async function verifyFlowBlindHiddenFlowPackage(signal) {
  const lockBytes = await verifiedBytes(
    lockPath,
    expectedLockIdentity,
    'Hidden-flow package lock',
    signal,
  )
  const lock = JSON.parse(lockBytes.toString('utf8'))
  if (
    stableJson(lock) !== lockBytes.toString('utf8') ||
    lock.schemaVersion !== 1 ||
    lock.id !==
      'flowblind-catalog-hidden-flow-package-lock-v1' ||
    lock.packageVersion !== '1.0.0' ||
    JSON.stringify(lock.actions) !==
      JSON.stringify([
        'prepare-study',
        'run-and-verify-study',
      ]) ||
    lock.runtimeNetworkRequired !== false ||
    lock.publicRuntime?.bundledPath !==
      'generated/flowblind-catalog-hidden-flow-runtime-v1.mjs' ||
    !Array.isArray(lock.facades) ||
    lock.facades.length !== 3 ||
    !Array.isArray(lock.artifacts) ||
    lock.artifacts.length !== 48
  ) {
    throw Object.assign(
      new Error(
        'The hidden-flow package lock violates the reviewed v1 contract.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
  assertLockEntries(lock)
  await verifyExactRuntimeTree(lock, signal)
  const runtimePath = confined(
    runtimeRoot,
    lock.publicRuntime.bundledPath,
    'Hidden-flow runtime',
  )
  const runtimeBytes = await verifiedBytes(
    runtimePath,
    lock.publicRuntime,
    'Hidden-flow runtime',
    signal,
  )
  for (const facade of lock.facades) {
    await verifiedBytes(
      confined(runtimeRoot, facade.bundledPath, facade.id),
      facade,
      facade.id,
      signal,
    )
  }
  for (const item of lock.artifacts) {
    await verifiedBytes(
      confined(
        generatedRoot,
        item.bundledPath,
        item.id,
      ),
      item,
      item.id,
      signal,
    )
  }

  const policyArtifact = artifact(
    lock,
    'generic-review-policy',
  )
  const declarationArtifact = artifact(
    lock,
    'capability-declaration',
  )
  const requirementsArtifact = artifact(
    lock,
    'python-requirements-lock',
  )
  const containerArtifact = artifact(
    lock,
    'container-definition',
  )
  const policy = JSON.parse(
    (
      await verifiedBytes(
        confined(
          generatedRoot,
          policyArtifact.bundledPath,
          policyArtifact.id,
        ),
        policyArtifact,
        policyArtifact.id,
        signal,
      )
    ).toString('utf8'),
  )
  const declaration = JSON.parse(
    (
      await verifiedBytes(
        confined(
          generatedRoot,
          declarationArtifact.bundledPath,
          declarationArtifact.id,
        ),
        declarationArtifact,
        declarationArtifact.id,
        signal,
      )
    ).toString('utf8'),
  )
  assertPolicy(policy)
  assertDeclaration(declaration)
  if (
    requirementsArtifact.sha256 !==
      policy.runtime.pythonRequirementsSha256
  ) {
    throw Object.assign(
      new Error(
        'The Python requirements lock is not the one named by the reviewed runtime policy.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
  const containerText = (
    await verifiedBytes(
      confined(
        generatedRoot,
        containerArtifact.bundledPath,
        containerArtifact.id,
      ),
      containerArtifact,
      containerArtifact.id,
      signal,
    )
  ).toString('utf8')
  if (
    !containerText.startsWith(
      'FROM --platform=linux/amd64 node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94 AS node-runtime\n',
    ) ||
    !containerText.includes(
      'FROM --platform=linux/amd64 python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79',
    ) ||
    !containerText.includes('--require-hashes') ||
    !containerText.includes('USER 10001:10001') ||
    !containerText.includes('chmod -R a-w /app/runtime') ||
    /\b(?:curl|wget|apt-get|apt install|pip install(?![\s\S]{0,180}--require-hashes))\b/iu.test(
      containerText,
    )
  ) {
    throw Object.assign(
      new Error(
        'The hidden-flow container definition is not the pinned non-root runtime image contract.',
      ),
      { code: 'package-attestation-failed' },
    )
  }

  const problemSchema = artifact(
    lock,
    'hidden-flow-problem-schema',
  )
  const problemAcceptanceSchema = artifact(
    lock,
    'flowblind-catalog-hidden-flow-problem-acceptance-v1',
  )
  const parser = artifact(
    lock,
    'hidden-flow-problem-parser-source',
  )
  const verifier = artifact(
    lock,
    'hidden-flow-independent-verifier-source',
  )
  const pythonSources = [
    'python-solver-init',
    'python-solver-main',
    'python-solver-cli',
    'python-solver-core',
  ].map((id) => identity(artifact(lock, id)))
  const schemas = lock.artifacts
    .filter((item) =>
      item.role.startsWith('capability-schema'),
    )
    .map(identity)
  if (schemas.length !== 12) {
    throw Object.assign(
      new Error(
        'The hidden-flow package does not contain the exact reviewed capability schema set.',
      ),
      { code: 'package-attestation-failed' },
    )
  }

  const packageVerification = deepFreeze({
    policy:
      'attested-generic-hidden-flow-contract-parser-runtime-and-neutral-claims',
    packageVersion: '1.0.0',
    runtimeNetworkRequired: false,
    runtime: {
      reference:
        'runtime/generated/flowblind-catalog-hidden-flow-runtime-v1.mjs',
      byteLength: runtimeBytes.byteLength,
      sha256: sha256(runtimeBytes),
      mediaType: 'text/javascript',
    },
    bundleLock: {
      reference:
        'runtime/generated/data/flowblind-catalog-hidden-flow-package-lock-v1.json',
      ...expectedLockIdentity,
      mediaType: 'application/json',
    },
    reviewPolicy: identity(policyArtifact),
    declaration: identity(declarationArtifact),
    problemSchema: identity(problemSchema),
    problemAcceptanceSchema:
      identity(problemAcceptanceSchema),
    parser: identity(parser),
    verifier: identity(verifier),
    pythonRequirements: identity(requirementsArtifact),
    pythonSolverSources: pythonSources,
    containerDefinition: identity(containerArtifact),
    schemas,
  })
  const runtimeAuthority = deepFreeze({
    packageVerification,
    pinnedRuntime: {
      pythonExecutable: '/usr/local/bin/python',
      pythonModuleRoot: confined(
        generatedRoot,
        'data/python',
        'Pinned Python module root',
      ),
    },
  })
  runtimeAuthorities.add(runtimeAuthority)
  return {
    lock,
    runtimePath,
    runtimeAuthority,
    packageVerification,
  }
}

export function flowBlindHiddenFlowPackageRuntimeAuthority(
  value,
) {
  return (
    typeof value === 'object' &&
    value !== null &&
    runtimeAuthorities.has(value)
  )
    ? value
    : null
}

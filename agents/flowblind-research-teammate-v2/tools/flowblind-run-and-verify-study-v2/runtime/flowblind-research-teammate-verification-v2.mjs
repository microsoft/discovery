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
  sep,
} from 'node:path'
import { fileURLToPath } from 'node:url'

const runtimeRoot = resolve(
  fileURLToPath(new URL('.', import.meta.url)),
)
const lockReference =
  'generated/data/flowblind-catalog-research-v2-package-lock-v1.json'
const verifierReference =
  'flowblind-research-teammate-verification-v2.mjs'
const maximumFileBytes = 256 * 1024 * 1024
const packageAuthorities = new WeakSet()
const packageBindings = new WeakMap()
const privateActivationAuthorities = new WeakSet()
const runConfirmationAuthorities = new WeakSet()
const expectedSourceModules = Object.freeze([
  'tools/catalogResearch/catalogResearchProfile.ts',
  'tools/catalogResearchV2/authority.ts',
  'tools/catalogResearchV2/capabilityAdapter.ts',
  'tools/catalogResearchV2/confirmation.ts',
  'tools/catalogResearchV2/contract.ts',
  'tools/catalogResearchV2/descriptors.ts',
  'tools/catalogResearchV2/hiddenFlowV1Authority.ts',
  'tools/catalogResearchV2/hiddenFlowV1Contract.ts',
  'tools/catalogResearchV2/integrity.ts',
  'tools/catalogResearchV2/intentPolicy.ts',
  'tools/catalogResearchV2/package/hiddenFlowV1PortableBridge.ts',
  'tools/catalogResearchV2/package/portableIo.ts',
  'tools/catalogResearchV2/package/retainedCatalogV1.ts',
  'tools/catalogResearchV2/package/retainedHiddenV1.ts',
  'tools/catalogResearchV2/package/runtime.ts',
  'tools/catalogResearchV2/resources.ts',
  'tools/catalogResearchV2/router.ts',
])
const expectedCanonicalSchemas = Object.freeze([
  'generated/data/schemas/flowblind-catalog-research-v2-prepare-input.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-run-input.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-action-response.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-prepared-study.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-publication-receipt.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-package-lock.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-source-modules.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-retained-package-manifest.schema.json',
  'generated/data/schemas/flowblind-catalog-research-v2-authority-unavailable.schema.json',
  'generated/data/schemas/flowblind-v2-hidden-flow-preparation-marker-v1.schema.json',
].sort())
export const expectedLockIdentity = Object.freeze({
  byteLength: Number(
    '16740',
  ),
  sha256: 'd3dcc0857a2a217565292492ba7d5600ce1872179cf39ba7e3ed564361eab8b6',
})

function throwIfAborted(signal) {
  signal?.throwIfAborted()
}

function sha256(bytes, signal) {
  throwIfAborted(signal)
  return createHash('sha256')
    .update(bytes)
    .digest('hex')
}

function stableValue(value) {
  if (Array.isArray(value)) {
    return value.map(stableValue)
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [
          key,
          stableValue(value[key]),
        ]),
    )
  }
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return value
  }
  if (
    typeof value === 'number' &&
    Number.isFinite(value)
  ) {
    return value
  }
  throw new Error(
    'Package records may contain only finite JSON values.',
  )
}

function stableJson(value) {
  return `${JSON.stringify(stableValue(value), null, 2)}\n`
}

function safeReference(reference) {
  return (
    typeof reference === 'string' &&
    reference.length > 0 &&
    reference.length <= 512 &&
    reference === reference.normalize('NFC') &&
    !reference.startsWith('/') &&
    !reference.includes('\\') &&
    !reference.includes('\0') &&
    !/^[A-Za-z]:/u.test(reference) &&
    reference
      .split('/')
      .every(
        (part) =>
          part.length > 0 &&
          part !== '.' &&
          part !== '..',
      )
  )
}

function confined(root, reference) {
  if (!safeReference(reference)) {
    throw new Error(
      'The package manifest contains an unsafe reference.',
    )
  }
  const path = resolve(root, reference)
  const child = relative(root, path)
  if (
    child.length === 0 ||
    child === '..' ||
    child.startsWith(`..${sep}`) ||
    isAbsolute(child)
  ) {
    throw new Error(
      'The package manifest reference escapes its root.',
    )
  }
  return path
}

function normalizedPath(path) {
  const normalized = resolve(path).replace(
    /^\\\\\?\\/u,
    '',
  )
  return process.platform === 'win32'
    ? normalized.toLowerCase()
    : normalized
}

function samePath(left, right) {
  return (
    normalizedPath(left) ===
    normalizedPath(right)
  )
}

function confinedRelative(root, path) {
  const direct = relative(root, path)
  if (
    direct !== '..' &&
    !direct.startsWith(`..${sep}`) &&
    !isAbsolute(direct)
  ) {
    return direct
  }
  throw new Error(
    'A package path escaped its canonical root.',
  )
}

async function readBounded(
  handle,
  maximum,
  signal,
) {
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
    throwIfAborted(signal)
    if (bytesRead === 0) break
    total += bytesRead
    if (total > maximum) {
      throw new Error(
        'A package file exceeds its reviewed byte limit.',
      )
    }
    chunks.push(chunk.subarray(0, bytesRead))
  }
  return Buffer.concat(chunks, total)
}

async function verifiedBytes(
  root,
  expected,
  maximum = maximumFileBytes,
  signal,
) {
  throwIfAborted(signal)
  const path = confined(root, expected.reference)
  throwIfAborted(signal)
  const metadata = await lstat(path, {
    bigint: true,
  })
  throwIfAborted(signal)
  const canonicalRoot = await realpath(root)
  throwIfAborted(signal)
  const canonicalPath = await realpath(path)
  throwIfAborted(signal)
  if (
    metadata.isSymbolicLink() ||
    !metadata.isFile() ||
    metadata.nlink !== 1n ||
    metadata.size !== BigInt(expected.byteLength) ||
    metadata.size > BigInt(maximum) ||
    !samePath(
      resolve(
      canonicalRoot,
      relative(root, path),
      ),
      canonicalPath,
    )
  ) {
    throw new Error(
      `Package file ${expected.reference} is not one exact single-link ordinary file.`,
    )
  }
  throwIfAborted(signal)
  const handle = await open(
    path,
    constants.O_RDONLY |
      (typeof constants.O_NOFOLLOW === 'number'
        ? constants.O_NOFOLLOW
        : 0),
  )
  throwIfAborted(signal)
  try {
    throwIfAborted(signal)
    const before = await handle.stat({ bigint: true })
    throwIfAborted(signal)
    const bytes = await readBounded(
      handle,
      Math.min(maximum, expected.byteLength),
      signal,
    )
    throwIfAborted(signal)
    const after = await handle.stat({ bigint: true })
    throwIfAborted(signal)
    const final = await lstat(path, {
      bigint: true,
    })
    throwIfAborted(signal)
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.size !== after.size ||
      before.mtimeNs !== after.mtimeNs ||
      after.dev !== final.dev ||
      after.ino !== final.ino ||
      final.nlink !== 1n ||
      final.isSymbolicLink() ||
      bytes.byteLength !== expected.byteLength ||
      sha256(bytes, signal) !== expected.sha256
    ) {
      throw new Error(
        `Package file ${expected.reference} failed byte verification.`,
      )
    }
    return bytes
  } finally {
    await handle.close()
    throwIfAborted(signal)
  }
}

async function scanTree(
  root,
  skippedRoots,
  signal,
) {
  throwIfAborted(signal)
  const canonicalRoot = await realpath(root)
  throwIfAborted(signal)
  const files = []
  const folded = new Set()

  async function walk(current, depth) {
    throwIfAborted(signal)
    if (depth > 32) {
      throw new Error(
        'The package tree exceeds its reviewed depth.',
      )
    }
    throwIfAborted(signal)
    const currentMetadata = await lstat(current)
    throwIfAborted(signal)
    if (
      currentMetadata.isSymbolicLink() ||
      !currentMetadata.isDirectory()
    ) {
      throw new Error(
        'Package directories must be ordinary directories.',
      )
    }
    throwIfAborted(signal)
    const directory = await opendir(current)
    throwIfAborted(signal)
    for await (const entry of directory) {
      throwIfAborted(signal)
      const path = resolve(current, entry.name)
      const reference = confinedRelative(
        canonicalRoot,
        path,
      )
        .replaceAll('\\', '/')
      if (!safeReference(reference)) {
        throw new Error(
          `The package tree contains an unsafe path: ${JSON.stringify(reference)}.`,
        )
      }
      const foldedReference =
        reference.normalize('NFC').toLowerCase()
      if (folded.has(foldedReference)) {
        throw new Error(
          'The package tree contains a case-aliased path.',
        )
      }
      folded.add(foldedReference)
      if (entry.isSymbolicLink()) {
        throw new Error(
          'The package tree contains a symbolic link.',
        )
      }
      if (entry.isDirectory()) {
        if (
          skippedRoots.includes(reference)
        ) {
          throwIfAborted(signal)
          const canonical = await realpath(path)
          throwIfAborted(signal)
          if (
            !samePath(
              resolve(
                canonicalRoot,
                reference,
              ),
              canonical,
            )
          ) {
            throw new Error(
              'A retained package root is aliased.',
            )
          }
          continue
        }
        await walk(path, depth + 1)
        throwIfAborted(signal)
      } else if (entry.isFile()) {
        throwIfAborted(signal)
        const metadata = await lstat(path, {
          bigint: true,
        })
        throwIfAborted(signal)
        if (
          metadata.isSymbolicLink() ||
          metadata.nlink !== 1n ||
          metadata.size <= 0n ||
          metadata.size >
            BigInt(maximumFileBytes)
        ) {
          throw new Error(
            `Package file ${reference} is unsafe.`,
          )
        }
        files.push(reference)
      } else {
        throw new Error(
          'The package tree contains a non-file entry.',
        )
      }
    }
  }

  await walk(canonicalRoot, 0)
  throwIfAborted(signal)
  return files.sort()
}

function exactList(left, right) {
  return (
    left.length === right.length &&
    left.every(
      (entry, index) => entry === right[index],
    )
  )
}

function parseCanonical(bytes, label, signal) {
  throwIfAborted(signal)
  const text = new TextDecoder('utf-8', {
    fatal: true,
    ignoreBOM: true,
  }).decode(bytes)
  if (
    bytes.length >= 3 &&
    bytes[0] === 0xef &&
    bytes[1] === 0xbb &&
    bytes[2] === 0xbf
  ) {
    throw new Error(`${label} contains a BOM.`)
  }
  throwIfAborted(signal)
  const value = JSON.parse(text)
  if (
    value === null ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    stableJson(value) !== text
  ) {
    throw new Error(
      `${label} is not canonical stable JSON.`,
    )
  }
  return value
}

function deepFreeze(value) {
  if (
    value === null ||
    typeof value !== 'object' ||
    Object.isFrozen(value)
  ) {
    return value
  }
  for (const nested of Object.values(value)) {
    deepFreeze(nested)
  }
  return Object.freeze(value)
}

function identityFor(lock, reference) {
  const matches = lock.files.filter(
    (entry) => entry.reference === reference,
  )
  if (matches.length !== 1) {
    throw new Error(
      `The package lock does not bind ${reference} exactly once.`,
    )
  }
  return matches[0]
}

function assertOuterContract(lock) {
  const actions = [
    {
      confirmation: 'Disabled',
      name: 'prepare-study',
      toolFolder: 'flowblind-prepare-study-v2',
    },
    {
      confirmation: 'Enabled',
      name: 'run-and-verify-study',
      toolFolder:
        'flowblind-run-and-verify-study-v2',
    },
  ]
  const advertised = [
    {
      familyId: 'regional-agreement',
      methodId: 'regional-agreement-v1',
      methodVersion: '1.0.0',
    },
    {
      familyId: 'vector-time-readiness',
      methodId:
        'vector-time-readiness-audit-v1',
      methodVersion: '1.0.0',
    },
  ]
  if (
    lock.schemaVersion !== 1 ||
    lock.id !==
      'flowblind-catalog-research-v2-package-lock-v1' ||
    lock.packageId !==
      'flowblind-research-teammate-v2' ||
    lock.packageVersion !== '2.0.0' ||
    JSON.stringify(lock.publicActions) !==
      JSON.stringify(actions) ||
    JSON.stringify(lock.advertisedMethods) !==
      JSON.stringify(advertised) ||
    lock.privateHiddenMethod?.methodId !==
      'finite-basis-hidden-flow-v1' ||
    lock.privateHiddenMethod?.methodVersion !==
      '1.1.0' ||
    lock.privateHiddenMethod?.advertiseToScientist !==
      false ||
    lock.privateHiddenMethod?.defaultOff !== true ||
    lock.privateHiddenMethod?.activationManifest
      ?.reference !==
      'generated/data/manifests/flowblind-private-hidden-flow-v1-activation-manifest-v1.json' ||
    JSON.stringify(lock.defaultOffMethods) !==
      JSON.stringify([
        'flowblind-finite-sensor-placement-v1@2.0.0',
        'generic-planar-external-validation-v1@1.0.0',
      ]) ||
    JSON.stringify(lock.unregisteredMethods) !==
      JSON.stringify(['home-qc']) ||
    lock.runtimeNetworkRequired !== false ||
    lock.publicRuntime?.reference !==
      'generated/flowblind-catalog-research-runtime-v2.mjs' ||
    lock.sourceModuleManifest?.reference !==
      'generated/data/manifests/flowblind-catalog-research-v2-source-modules-v1.json' ||
    lock.releasePolicy?.reference !==
      'generated/data/flowblind-catalog-research-v2-release-policy-v1.json' ||
    lock.contract?.reference !==
      'generated/data/package/flowblind-catalog-research-contract-v2.md' ||
    typeof lock.scenarioCoverage?.reference !==
      'string' ||
    lock.scenarioCoverage.reference !==
      'generated/data/flowblind-catalog-research-v2-scenario-coverage-v1.json' ||
    !Array.isArray(lock.canonicalSchemas) ||
    lock.canonicalSchemas.length !==
      expectedCanonicalSchemas.length ||
    typeof lock.retainedPackageManifest?.reference !==
      'string' ||
    lock.retainedPackageManifest.reference !==
      'generated/data/manifests/flowblind-catalog-research-v2-retained-package-manifest-v1.json' ||
    !Array.isArray(lock.retainedPackageManifests) ||
    lock.retainedPackageManifests.length !== 2 ||
    lock.retainedPackageManifests[0]?.id !==
      'catalog-v1' ||
    lock.retainedPackageManifests[0]?.root !==
      'generated/retained/catalog-v1/runtime' ||
    lock.retainedPackageManifests[0]?.fileCount !==
      27 ||
    lock.retainedPackageManifests[1]?.id !==
      'hidden-flow-v1' ||
    lock.retainedPackageManifests[1]?.root !==
      'generated/retained/hidden-flow-v1/runtime' ||
    lock.retainedPackageManifests[1]?.fileCount !==
      54 ||
    !Array.isArray(lock.files) ||
    lock.files.length === 0
  ) {
    throw new Error(
      'The outer package lock violates the v2 release contract.',
    )
  }
}

function exactVerificationOptions(options) {
  if (options === undefined) {
    const environmentRole =
      process.env.FLOWBLIND_TOOL_ROLE
    return Object.freeze({
      toolRole:
        environmentRole === 'prepare-study' ||
        environmentRole ===
          'run-and-verify-study'
          ? environmentRole
          : null,
      signal: undefined,
    })
  }
  if (
    options === null ||
    typeof options !== 'object' ||
    Array.isArray(options) ||
    Object.keys(options).some(
      (key) =>
        key !== 'toolRole' &&
        key !== 'signal',
    )
  ) {
    throw new Error(
      'Package verification accepts only one exact tool role and an optional AbortSignal.',
    )
  }
  const role = options.toolRole
  if (
    role !== 'prepare-study' &&
    role !== 'run-and-verify-study' &&
    role !== 'resource' &&
    role !== 'private-preview'
  ) {
    throw new Error(
      'The package verifier received an unknown tool role.',
    )
  }
  const signal = options.signal
  if (
    signal !== undefined &&
    (
      signal === null ||
      typeof signal !== 'object' ||
      typeof signal.aborted !== 'boolean' ||
      typeof signal.throwIfAborted !== 'function'
    )
  ) {
    throw new Error(
      'Package verification requires a valid AbortSignal when cancellation is supplied.',
    )
  }
  return Object.freeze({
    toolRole: role,
    signal,
  })
}

export async function verifyFlowBlindCatalogResearchV2Package(
  options,
) {
  const {
    toolRole,
    signal,
  } = exactVerificationOptions(options)
  throwIfAborted(signal)
  const lockBytes = await verifiedBytes(
    runtimeRoot,
    {
      reference: lockReference,
      ...expectedLockIdentity,
    },
    maximumFileBytes,
    signal,
  )
  throwIfAborted(signal)
  const lock = parseCanonical(
    lockBytes,
    'Outer package lock',
    signal,
  )
  assertOuterContract(lock)

  const expectedReferences = [
    lockReference,
    verifierReference,
    ...lock.files.map(
      (entry) => entry.reference,
    ),
  ].sort()
  if (
    new Set(expectedReferences).size !==
      expectedReferences.length
  ) {
    throw new Error(
      'The outer package runtime contains missing, extra, case-aliased, linked, or unsafe files.',
    )
  }
  throwIfAborted(signal)
  const actualReferences =
    await scanTree(
      runtimeRoot,
      lock.retainedPackageManifests.map(
        (entry) => entry.root,
      ),
      signal,
    )
  throwIfAborted(signal)
  if (
    !exactList(
      actualReferences,
      expectedReferences,
    )
  ) {
    throw new Error(
      'The outer package runtime contains missing, extra, case-aliased, linked, or unsafe files.',
    )
  }
  for (const entry of lock.files) {
    throwIfAborted(signal)
    await verifiedBytes(
      runtimeRoot,
      entry,
      maximumFileBytes,
      signal,
    )
    throwIfAborted(signal)
  }
  const runtimeIdentity = identityFor(
    lock,
    lock.publicRuntime.reference,
  )
  const sourceManifestIdentity = identityFor(
    lock,
    lock.sourceModuleManifest.reference,
  )
  const scenarioCoverageIdentity = identityFor(
    lock,
    lock.scenarioCoverage.reference,
  )
  const retainedPackageManifestIdentity =
    identityFor(
      lock,
      lock.retainedPackageManifest.reference,
    )
  const contractIdentity = identityFor(
    lock,
    lock.contract.reference,
  )
  const privateActivationManifestIdentity =
    identityFor(
      lock,
      lock.privateHiddenMethod
        .activationManifest.reference,
    )
  const canonicalSchemaReferences =
    lock.canonicalSchemas
      .map((entry) => entry.reference)
      .sort()
  if (
    JSON.stringify(runtimeIdentity) !==
      JSON.stringify(lock.publicRuntime) ||
    JSON.stringify(sourceManifestIdentity) !==
      JSON.stringify(lock.sourceModuleManifest) ||
    JSON.stringify(scenarioCoverageIdentity) !==
      JSON.stringify(lock.scenarioCoverage) ||
    JSON.stringify(
      retainedPackageManifestIdentity,
    ) !==
      JSON.stringify(lock.retainedPackageManifest) ||
    JSON.stringify(contractIdentity) !==
      JSON.stringify(lock.contract) ||
    JSON.stringify(
      privateActivationManifestIdentity,
    ) !==
      JSON.stringify(
        lock.privateHiddenMethod
          .activationManifest,
      ) ||
    !exactList(
      canonicalSchemaReferences,
      expectedCanonicalSchemas,
    ) ||
    lock.canonicalSchemas.some(
      (entry) =>
        JSON.stringify(
          identityFor(lock, entry.reference),
        ) !== JSON.stringify(entry),
    )
  ) {
    throw new Error(
      'The outer package lock aliases a primary artifact identity.',
    )
  }
  const sourceManifest = parseCanonical(
    await verifiedBytes(
      runtimeRoot,
      sourceManifestIdentity,
      maximumFileBytes,
      signal,
    ),
    'Source-module manifest',
    signal,
  )
  throwIfAborted(signal)
  const sourceReferences = Array.isArray(
    sourceManifest.modules,
  )
    ? sourceManifest.modules.map(
        (entry) => entry.reference,
      )
    : []
  if (
    sourceManifest.id !==
      'flowblind-catalog-research-v2-source-modules-v1' ||
    sourceManifest.packageVersion !== '2.0.0' ||
    sourceManifest.moduleCount !==
      expectedSourceModules.length ||
    !exactList(
      sourceReferences,
      expectedSourceModules,
    ) ||
    new Set(sourceReferences).size !==
      sourceReferences.length
  ) {
    throw new Error(
      'The source-module manifest differs from the exact reviewed v2 allowlist.',
    )
  }
  const bridgeExtensionModule =
    sourceManifest.modules.find(
      (entry) =>
        entry.reference ===
        'tools/catalogResearchV2/package/hiddenFlowV1PortableBridge.ts',
    )

  const releasePolicyIdentity = identityFor(
    lock,
    lock.releasePolicy.reference,
  )
  const releasePolicy = parseCanonical(
    await verifiedBytes(
      runtimeRoot,
      releasePolicyIdentity,
      maximumFileBytes,
      signal,
    ),
    'Release policy',
    signal,
  )
  throwIfAborted(signal)
  if (
    releasePolicy.packageVersion !== '2.0.0' ||
    releasePolicy.promptAgent?.humanInTheLoop !==
      'Enabled' ||
    releasePolicy.promptAgent?.allowMultipleToolCalls !==
      false ||
    releasePolicy.promptAgent?.temperature !== 0 ||
    releasePolicy.privateHiddenFlow?.defaultOff !==
      true ||
    releasePolicy.privateHiddenFlow
      ?.advertiseToScientist !== false ||
    releasePolicy.privateHiddenFlow
      ?.liveActivationEligible !== false ||
    releasePolicy.privateHiddenFlow
      ?.liveImageManifestDigests?.prepare !==
      'REQUIRED_BEFORE_LIVE_ACTIVATION' ||
    releasePolicy.privateHiddenFlow
      ?.liveImageManifestDigests?.run !==
      'REQUIRED_BEFORE_LIVE_ACTIVATION' ||
    releasePolicy.privateHiddenFlow
      ?.exactNativeBytePreservation !==
      'versioned-package-source-extension' ||
    releasePolicy.privateHiddenFlow
      ?.bridgeExtension?.extensionSource !==
      'tools/catalogResearchV2/package/hiddenFlowV1PortableBridge.ts' ||
    releasePolicy.privateHiddenFlow
      ?.bridgeExtension?.extensionByteLength !==
      bridgeExtensionModule?.byteLength ||
    releasePolicy.privateHiddenFlow
      ?.bridgeExtension?.extensionSha256 !==
      bridgeExtensionModule?.sha256 ||
    releasePolicy.privateHiddenFlow
      ?.bridgeExtension?.acceptedBridgeSha256 !==
      'f61326fd42415d02d03686dad4bb1d9e5b3098225c5eebf37a2aa4fffc987122'
  ) {
    throw new Error(
      'The attested v2 release policy is invalid.',
    )
  }

  const scenarioCoverage = parseCanonical(
    await verifiedBytes(
      runtimeRoot,
      scenarioCoverageIdentity,
      maximumFileBytes,
      signal,
    ),
    'Scenario coverage manifest',
    signal,
  )
  throwIfAborted(signal)
  const expectedScenarioIds = [
    'V2-REG-002',
    'V2-REG-003',
    'V2-REG-006',
    'V2-VEC-002',
    'V2-VEC-003',
    'V2-VEC-005',
    'V2-VEC-006',
    'V2-VEC-008',
    'V2-HID-001',
    'V2-HID-004',
    'V2-HID-005',
    'V2-HID-007',
    'V2-HID-008',
    'V2-HID-009',
    'V2-HID-014',
    'V2-OPS-006',
    'V2-OPS-007',
    'V2-OPS-008',
    'V2-PKG-001',
    'V2-PKG-002',
    'V2-PKG-003',
    'V2-PKG-004',
    'V2-PKG-005',
    'V2-PKG-006',
    'V2-PKG-007',
    'V2-PKG-008',
    'V2-LIVE-001',
    'V2-LIVE-002',
    'V2-LIVE-003',
    'V2-LIVE-004',
  ]
  const scenarios = Array.isArray(
    scenarioCoverage.scenarios,
  )
    ? scenarioCoverage.scenarios
    : []
  const actualScenarioIds = scenarios
    .map((entry) => entry.id)
    .sort()
  if (
    scenarioCoverage.id !==
      'flowblind-catalog-research-v2-scenario-coverage-v1' ||
    scenarioCoverage.packageVersion !== '2.0.0' ||
    !exactList(
      actualScenarioIds,
      [...expectedScenarioIds].sort(),
    ) ||
    scenarios.some(
      (entry) =>
        entry.id.startsWith('V2-LIVE-') &&
        entry.coverageStatus !== 'manual-live',
    ) ||
    scenarios.some(
      (entry) =>
        [
          'V2-OPS-006',
          'V2-OPS-007',
          'V2-OPS-008',
        ].includes(entry.id) &&
        entry.coverageStatus !== 'contract-only',
    )
  ) {
    throw new Error(
      'The attested scenario coverage manifest overclaims or omits required scenario IDs.',
    )
  }

  const retainedPackageManifest = parseCanonical(
    await verifiedBytes(
      runtimeRoot,
      retainedPackageManifestIdentity,
      maximumFileBytes,
      signal,
    ),
    'Retained-package manifest',
    signal,
  )
  throwIfAborted(signal)
  if (
    retainedPackageManifest.id !==
      'flowblind-catalog-research-v2-retained-package-manifest-v1' ||
    retainedPackageManifest.packageVersion !==
      '2.0.0' ||
    !Array.isArray(
      retainedPackageManifest.packages,
    ) ||
    retainedPackageManifest.packages.length !== 2 ||
    retainedPackageManifest.packages[0]?.retainedId !==
      'catalog-v1' ||
    retainedPackageManifest.packages[1]?.retainedId !==
      'hidden-flow-v1'
  ) {
    throw new Error(
      'The combined retained-package manifest is invalid.',
    )
  }
  for (const binding of lock.retainedPackageManifests) {
    throwIfAborted(signal)
    const manifestIdentity = identityFor(
      lock,
      binding.manifest.reference,
    )
    if (
      JSON.stringify(manifestIdentity) !==
      JSON.stringify(binding.manifest)
    ) {
      throw new Error(
        `The retained ${binding.id} manifest binding aliases its package-lock identity.`,
      )
    }
    const individual = parseCanonical(
      await verifiedBytes(
        runtimeRoot,
        binding.manifest,
        maximumFileBytes,
        signal,
      ),
      `Retained manifest ${binding.id}`,
      signal,
    )
    throwIfAborted(signal)
    const combined =
      retainedPackageManifest.packages.find(
        (entry) =>
          entry.retainedId === binding.id,
      )
    if (
      combined === undefined ||
      JSON.stringify(individual) !==
        JSON.stringify(combined)
    ) {
      throw new Error(
        `The combined retained-package manifest does not match ${binding.id}.`,
      )
    }
  }

  const packageVerification = deepFreeze({
    policy:
      'flowblind-catalog-native-research-teammate-v2-exact-package',
    packageId: lock.packageId,
    packageVersion: lock.packageVersion,
    runtimeNetworkRequired: false,
    runtime: lock.publicRuntime,
    sourceModuleManifest:
      lock.sourceModuleManifest,
    contract: lock.contract,
    canonicalSchemas:
      lock.canonicalSchemas,
    releasePolicy: lock.releasePolicy,
    scenarioCoverage: lock.scenarioCoverage,
    retainedPackageManifests:
      lock.retainedPackageManifests,
    retainedPackageManifest:
      lock.retainedPackageManifest,
    privateActivationManifest:
      lock.privateHiddenMethod.activationManifest,
    hiddenBridgeExtension: Object.freeze({
      ...releasePolicy.privateHiddenFlow
        .bridgeExtension,
    }),
  })
  throwIfAborted(signal)
  packageAuthorities.add(packageVerification)
  packageBindings.set(packageVerification, lock)
  throwIfAborted(signal)
  const runConfirmationEvidence =
    toolRole === 'run-and-verify-study'
      ? Object.freeze(Object.create(null))
      : null
  if (runConfirmationEvidence !== null) {
    runConfirmationAuthorities.add(
      runConfirmationEvidence,
    )
  }
  throwIfAborted(signal)
  return {
    lock,
    runtimePath: confined(
      runtimeRoot,
      lock.publicRuntime.reference,
    ),
    packageVerification,
    toolRole,
    runConfirmationEvidence,
  }
}

export function flowBlindCatalogResearchV2PackageVerificationEvidence(
  value,
) {
  return (
    value !== null &&
    typeof value === 'object' &&
    packageAuthorities.has(value)
  )
    ? value
    : null
}

export function flowBlindCatalogResearchV2RunConfirmationEvidence(
  value,
) {
  return (
    value !== null &&
    typeof value === 'object' &&
    runConfirmationAuthorities.has(value)
  )
    ? value
    : null
}

export function consumeFlowBlindCatalogResearchV2RunConfirmationEvidence(
  value,
) {
  if (
    flowBlindCatalogResearchV2RunConfirmationEvidence(
      value,
    ) === null
  ) {
    return null
  }
  runConfirmationAuthorities.delete(value)
  return value
}

function retainedManifestBinding(
  lock,
  id,
) {
  const matches =
    lock.retainedPackageManifests.filter(
      (entry) => entry.id === id,
    )
  if (matches.length !== 1) {
    throw new Error(
      `The retained package ${id} is not bound exactly once.`,
    )
  }
  return matches[0]
}

function retainedTreeDigest(files, signal) {
  throwIfAborted(signal)
  const hash = createHash('sha256')
  for (const entry of files) {
    throwIfAborted(signal)
    hash.update(entry.reference)
    hash.update('\0')
    hash.update(String(entry.byteLength))
    hash.update('\0')
    hash.update(entry.sha256)
    hash.update('\n')
  }
  throwIfAborted(signal)
  return hash.digest('hex')
}

export async function verifyRetainedPackage(
  packageEvidence,
  id,
  signal,
) {
  throwIfAborted(signal)
  if (
    flowBlindCatalogResearchV2PackageVerificationEvidence(
      packageEvidence,
    ) === null ||
    !['catalog-v1', 'hidden-flow-v1'].includes(id)
  ) {
    return null
  }
  const lock = packageBindings.get(packageEvidence)
  if (lock === undefined) return null
  const binding = retainedManifestBinding(
    lock,
    id,
  )
  const manifestBytes = await verifiedBytes(
    runtimeRoot,
    binding.manifest,
    maximumFileBytes,
    signal,
  )
  throwIfAborted(signal)
  const manifest = parseCanonical(
    manifestBytes,
    `Retained package manifest ${id}`,
    signal,
  )
  if (
    manifest.schemaVersion !== 1 ||
    manifest.id !==
      `flowblind-retained-${id}-manifest-v1` ||
    manifest.retainedId !== id ||
    manifest.root !== binding.root ||
    manifest.treeSha256 !==
      binding.treeSha256 ||
    manifest.packageEvidence === null ||
    typeof manifest.packageEvidence !== 'object' ||
    !Array.isArray(manifest.files) ||
    manifest.files.length !==
      binding.fileCount
  ) {
    throw new Error(
      `The retained package manifest ${id} is invalid.`,
    )
  }
  const evidence = manifest.packageEvidence
  if (
    id === 'catalog-v1' &&
    (
      evidence.lock?.byteLength !== 11049 ||
      evidence.lock?.sha256 !==
        '7f44c401f4b1e4238be31c48bc39f63892820cb7cd8e826fbc033b47d481a0a4' ||
      evidence.runtime?.byteLength !== 340170 ||
      evidence.runtime?.sha256 !==
        '364afa627b8fa4777faaacf2e227dc1f62549aa0262a3e8178c235e1c1f02518' ||
      evidence.verifier?.byteLength !== 9212 ||
      evidence.verifier?.sha256 !==
        'db900dc0245c9ebaa67622a1ce5f56e72754c7ff2232b9120945fcc5904e83dd' ||
      evidence.artifactCount !== 21 ||
      evidence.internalFacadeCount !== 3 ||
      evidence.sourceModuleCount !== 36
    )
  ) {
    throw new Error(
      'The retained catalog-v1 package evidence differs from its authoritative checkpoint.',
    )
  }
  if (
    id === 'hidden-flow-v1' &&
    (
      evidence.lock?.byteLength !== 21934 ||
      evidence.lock?.sha256 !==
        '91b2644f438ec6e98593476412429b7a0203c4f3f8cde6f4849e6e1cb1507d48' ||
      evidence.runtime?.byteLength !== 177882 ||
      evidence.runtime?.sha256 !==
        '29b7cf20974a9f1c5f42fff87ede181bcb848eeb2ffd70425a4d0f98a2d1b37f' ||
      evidence.verifier?.byteLength !== 20850 ||
      evidence.verifier?.sha256 !==
        '4ebb0bf8db8e4b22345f892c04f4e5e8b02417c041af992b69c122d3a2a22e0d' ||
      evidence.artifactCount !== 48 ||
      evidence.internalFacadeCount !== 3 ||
      evidence.dockerfile?.sha256 !==
        '28a51948b691c38699c21df75e7b2a8d5890087ec7d62d9ee46f9b603881375c'
    )
  ) {
    throw new Error(
      'The retained hidden-flow package evidence differs from its authoritative review.',
    )
  }
  const retainedRoot = confined(
    runtimeRoot,
    binding.root,
  )
  throwIfAborted(signal)
  const actualReferences =
    await scanTree(
      retainedRoot,
      [],
      signal,
    )
  throwIfAborted(signal)
  const expectedReferences = manifest.files
    .map((entry) => entry.reference)
    .sort()
  if (
    new Set(
      expectedReferences.map((entry) =>
        entry.toLowerCase(),
      ),
    ).size !== expectedReferences.length ||
    !exactList(
      actualReferences,
      expectedReferences,
    )
  ) {
    throw new Error(
      `The retained ${id} tree contains missing, extra, case-aliased, linked, or unsafe files.`,
    )
  }
  for (const entry of manifest.files) {
    throwIfAborted(signal)
    await verifiedBytes(
      retainedRoot,
      entry,
      maximumFileBytes,
      signal,
    )
    throwIfAborted(signal)
  }
  if (
    retainedTreeDigest(
      manifest.files,
      signal,
    ) !==
      manifest.treeSha256
  ) {
    throw new Error(
      `The retained ${id} tree hash is invalid.`,
    )
  }
  throwIfAborted(signal)
  return Object.freeze({
    id,
    rootPath: retainedRoot,
    treeSha256: manifest.treeSha256,
  })
}

export function verifyPrivateHiddenFlowActivation(
  packageEvidence,
  candidate,
  signal,
) {
  throwIfAborted(signal)
  if (
    flowBlindCatalogResearchV2PackageVerificationEvidence(
      packageEvidence,
    ) === null ||
    candidate === null ||
    typeof candidate !== 'object' ||
    typeof candidate.digest !== 'string' ||
    !(candidate.manifestBytes instanceof Uint8Array)
  ) {
    return null
  }
  const expected =
    packageEvidence.privateActivationManifest
  const digest = `sha256:${sha256(
    candidate.manifestBytes,
    signal,
  )}`
  if (
    candidate.digest !== digest ||
    candidate.digest !==
      `sha256:${expected.sha256}` ||
    candidate.manifestBytes.byteLength !==
      expected.byteLength
  ) {
    return null
  }
  let manifest
  try {
    manifest = parseCanonical(
      candidate.manifestBytes,
      'Private hidden-flow activation manifest',
      signal,
    )
  } catch {
    throwIfAborted(signal)
    return null
  }
  if (
    manifest.id !==
      'flowblind-private-hidden-flow-v1-activation-manifest-v1' ||
    manifest.enabled !== true ||
    manifest.advertiseToScientist !== false ||
    manifest.activationClass !==
      'package-local-retained-conformance' ||
    manifest.liveActivationEligible !== false ||
    manifest.route?.methodId !==
      'finite-basis-hidden-flow-v1' ||
    manifest.route?.methodVersion !== '1.1.0' ||
    manifest.retainedPackage?.lockSha256 !==
      '91b2644f438ec6e98593476412429b7a0203c4f3f8cde6f4849e6e1cb1507d48' ||
    manifest.retainedPackage?.runtimeSha256 !==
      '29b7cf20974a9f1c5f42fff87ede181bcb848eeb2ffd70425a4d0f98a2d1b37f' ||
    manifest.retainedPackage?.verifierSha256 !==
      '4ebb0bf8db8e4b22345f892c04f4e5e8b02417c041af992b69c122d3a2a22e0d' ||
    manifest.liveImageManifestDigests?.prepare !==
      'REQUIRED_BEFORE_LIVE_ACTIVATION' ||
    manifest.liveImageManifestDigests?.run !==
      'REQUIRED_BEFORE_LIVE_ACTIVATION' ||
    manifest.exactNativeBytePreservation !==
      'versioned-package-source-extension' ||
    manifest.bridgeExtension?.id !==
      'flowblind-hidden-bridge-stable-json-bytes-v2' ||
    manifest.bridgeExtension
      ?.acceptedBridgeSource !==
      'tools/catalogResearchV2/integrations/hiddenFlowV1.ts' ||
    manifest.bridgeExtension
      ?.acceptedBridgeSha256 !==
      'f61326fd42415d02d03686dad4bb1d9e5b3098225c5eebf37a2aa4fffc987122' ||
    manifest.bridgeExtension?.extensionSource !==
      packageEvidence.hiddenBridgeExtension
        .extensionSource ||
    manifest.bridgeExtension?.extensionByteLength !==
      packageEvidence.hiddenBridgeExtension
        .extensionByteLength ||
    manifest.bridgeExtension?.extensionSha256 !==
      packageEvidence.hiddenBridgeExtension
        .extensionSha256 ||
    manifest.bridgeExtension?.behavior !==
      'accept-compact-or-stable-pretty-json-without-reencoding-and-preserve-reconciliation-detail'
  ) {
    return null
  }
  const evidence = Object.freeze(
    Object.create(null),
  )
  privateActivationAuthorities.add(evidence)
  throwIfAborted(signal)
  return evidence
}

export function flowBlindPrivateHiddenFlowActivationEvidence(
  value,
) {
  return (
    value !== null &&
    typeof value === 'object' &&
    privateActivationAuthorities.has(value)
  )
    ? value
    : null
}

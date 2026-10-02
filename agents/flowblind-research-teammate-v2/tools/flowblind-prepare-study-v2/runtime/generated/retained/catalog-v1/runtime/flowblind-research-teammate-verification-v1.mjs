import { createHash } from 'node:crypto'
import { constants } from 'node:fs'
import { lstat, open, realpath } from 'node:fs/promises'
import { isAbsolute, relative, resolve } from 'node:path'

const runtimeRoot = import.meta.dirname
const generatedRoot = resolve(runtimeRoot, 'generated')
const lockPath = resolve(generatedRoot, 'data', 'flowblind-catalog-package-lock-v1.json')
const verifiedBindings = new WeakSet()
const maximumPackageFileBytes = 32 * 1024 * 1024

export const expectedLockIdentity = Object.freeze({
  byteLength: 11049,
  sha256: '7f44c401f4b1e4238be31c48bc39f63892820cb7cd8e826fbc033b47d481a0a4',
})
const expectedSourceModules = Object.freeze(["src/application/evidenceReport.ts","src/application/regionalAgreementStudyLifecycle.ts","src/application/runVectorTimeAudit.ts","src/application/sha256.ts","src/domain/agreementMetrics.ts","src/domain/evidence.ts","src/domain/numericalSafety.ts","src/domain/regionalAgreementStudy.ts","src/domain/statistics.ts","src/domain/temporalMetrics.ts","src/domain/units.ts","src/domain/vectorAuditValidation.ts","src/domain/vectorDatasetModel.ts","src/domain/vectorDatasetValidation.ts","src/domain/vectorMetrics.ts","src/domain/vectorTopology.ts","src/domain/wallShear.ts","src/version.ts","tools/catalogResearch/catalogAttachments.ts","tools/catalogResearch/catalogBundle.ts","tools/catalogResearch/catalogCoordinator.ts","tools/catalogResearch/catalogExecution.ts","tools/catalogResearch/catalogPreparation.ts","tools/catalogResearch/catalogPublication.ts","tools/catalogResearch/catalogReport.ts","tools/catalogResearch/catalogResearchInput.ts","tools/catalogResearch/catalogResearchProfile.ts","tools/catalogResearch/catalogResearchRuntime.ts","tools/catalogResearch/catalogTrustedSidecar.ts","tools/catalogResearch/catalogVectorCsv.ts","tools/catalogResearch/catalogVectorSidecar.ts","tools/catalogResearch/catalogVectorStudy.ts","tools/discovery/flowblindDisplayText.ts","tools/discovery/pairedPlanarCsvIntake.ts","tools/discovery/safeIntakeFile.ts","tools/discovery/strictUtf8.ts"])

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

function deepFreeze(value) {
  if (typeof value !== 'object' || value === null || Object.isFrozen(value)) return value
  for (const nested of Object.values(value)) deepFreeze(nested)
  return Object.freeze(value)
}

function confined(root, reference, label) {
  const path = resolve(root, reference)
  const relativePath = relative(root, path)
  if (
    relativePath.length === 0 ||
    relativePath === '..' ||
    relativePath.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) ||
    isAbsolute(relativePath)
  ) {
    throw Object.assign(new Error(`${label} escapes the portable package.`), {
      code: 'package-attestation-failed',
    })
  }
  return path
}

async function verifiedBytes(path, expected, label) {
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
    metadata.size !== expected.byteLength ||
    metadata.size > maximumPackageFileBytes ||
    resolve(expectedCanonical) !== resolve(canonical)
  ) {
    throw Object.assign(new Error(`${label} must be an ordinary file.`), {
      code: 'package-attestation-failed',
    })
  }
  const handle = await open(
    path,
    constants.O_RDONLY |
      (typeof constants.O_NOFOLLOW === 'number' ? constants.O_NOFOLLOW : 0),
  )
  try {
    const before = await handle.stat({ bigint: true })
    if (
      !before.isFile() ||
      before.size !== BigInt(expected.byteLength) ||
      before.size > BigInt(maximumPackageFileBytes)
    ) {
      throw Object.assign(new Error(`${label} has an invalid byte length.`), {
        code: 'package-attestation-failed',
      })
    }
    const chunks = []
    let totalBytes = 0
    while (true) {
      const buffer = Buffer.allocUnsafe(64 * 1024)
      const { bytesRead } = await handle.read(
        buffer,
        0,
        buffer.byteLength,
        null,
      )
      if (bytesRead === 0) break
      totalBytes += bytesRead
      if (totalBytes > expected.byteLength) {
        throw Object.assign(new Error(`${label} exceeds its reviewed byte length.`), {
          code: 'package-attestation-failed',
        })
      }
      chunks.push(buffer.subarray(0, bytesRead))
    }
    const bytes = Buffer.concat(chunks, totalBytes)
    const after = await handle.stat({ bigint: true })
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.size !== after.size ||
      before.mtimeNs !== after.mtimeNs ||
      bytes.byteLength !== expected.byteLength ||
      sha256(bytes) !== expected.sha256
    ) {
      throw Object.assign(new Error(`${label} does not match its reviewed identity.`), {
        code: 'package-attestation-failed',
      })
    }
    return bytes
  } finally {
    await handle.close()
  }
}

export async function verifyFlowBlindCatalogPackage() {
  const lockBytes = await verifiedBytes(
    lockPath,
    expectedLockIdentity,
    'Catalog research package lock',
  )
  const lock = JSON.parse(lockBytes.toString('utf8'))
  if (
    lock.schemaVersion !== 1 ||
    lock.id !== 'flowblind-catalog-package-lock-v1' ||
    lock.packageVersion !== '1.0.0' ||
    JSON.stringify(lock.actions) !==
      JSON.stringify(['prepare-study', 'run-and-verify-study']) ||
    JSON.stringify(lock.capabilities) !==
      JSON.stringify(['regional-agreement-v1', 'vector-time-readiness-audit-v1']) ||
    JSON.stringify(lock.sourceModules) !==
      JSON.stringify(expectedSourceModules) ||
    lock.runtimeNetworkRequired !== false ||
    lock.publicRuntime?.bundledPath !==
      'generated/flowblind-catalog-research-runtime-v1.mjs' ||
    !Array.isArray(lock.facades) ||
    lock.facades.length !== 3 ||
    !Array.isArray(lock.artifacts) ||
    lock.artifacts.length !== 21
  ) {
    throw Object.assign(new Error('Catalog research package lock violates the reviewed v1 contract.'), {
      code: 'package-attestation-failed',
    })
  }
  const runtimeBytes = await verifiedBytes(
    confined(runtimeRoot, lock.publicRuntime.bundledPath, 'Catalog runtime'),
    lock.publicRuntime,
    'Catalog research runtime',
  )
  for (const facade of lock.facades) {
    await verifiedBytes(
      confined(runtimeRoot, facade.bundledPath, facade.id),
      facade,
      facade.id,
    )
  }
  for (const artifact of lock.artifacts) {
    await verifiedBytes(
      confined(generatedRoot, artifact.bundledPath, artifact.id),
      artifact,
      artifact.id,
    )
  }
  const policyArtifact = lock.artifacts.find(
    (artifact) => artifact.id === 'catalog-policy',
  )
  if (!policyArtifact) {
    throw Object.assign(new Error('Catalog policy evidence is missing.'), {
      code: 'package-attestation-failed',
    })
  }
  const policy = JSON.parse(
    (
      await verifiedBytes(
        confined(generatedRoot, policyArtifact.bundledPath, 'Catalog policy'),
        policyArtifact,
        'Catalog policy',
      )
    ).toString('utf8'),
  )
  const prepare = policy.tools?.find(
    (tool) => tool.action === 'prepare-study',
  )
  const run = policy.tools?.find(
    (tool) => tool.action === 'run-and-verify-study',
  )
  if (
    policy.humanInTheLoop !== 'Enabled' ||
    policy.disableDataHandlingTools !== false ||
    prepare?.confirmation !== 'Disabled' ||
    run?.confirmation !== 'Enabled'
  ) {
    throw Object.assign(new Error('The run confirmation policy is not attested.'), {
      code: 'confirmation-required',
    })
  }
  const packageVerification = deepFreeze({
    policy:
      'attested-catalog-facades-runtime-schemas-report-and-policy',
    packageVersion: '1.0.0',
    runtimeNetworkRequired: false,
    runtime: {
      reference:
        'runtime/generated/flowblind-catalog-research-runtime-v1.mjs',
      byteLength: runtimeBytes.byteLength,
      sha256: sha256(runtimeBytes),
      mediaType: 'text/javascript',
    },
    bundleLock: {
      reference:
        'runtime/generated/data/flowblind-catalog-package-lock-v1.json',
      ...expectedLockIdentity,
      mediaType: 'application/json',
    },
    schemas: lock.artifacts
      .filter((artifact) => artifact.role.includes('schema'))
      .map((artifact) => ({
        reference: `runtime/generated/${artifact.bundledPath}`,
        byteLength: artifact.byteLength,
        sha256: artifact.sha256,
        mediaType: 'application/schema+json',
      })),
    catalogPolicy: {
      humanInTheLoop: 'Enabled',
      disableDataHandlingTools: false,
      prepareConfirmation: 'Disabled',
      runConfirmation: 'Enabled',
    },
  })
  verifiedBindings.add(packageVerification)
  return {
    lock,
    runtimePath:
      confined(
        runtimeRoot,
        lock.publicRuntime.bundledPath,
        'Catalog runtime',
      ),
    packageVerification,
  }
}

export function flowBlindCatalogPackageVerificationEvidence(value) {
  return (
    typeof value === 'object' &&
    value !== null &&
    verifiedBindings.has(value)
  )
    ? value
    : null
}

import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { pathToFileURL } from 'node:url'
import {
  cp,
  mkdir,
  readFile,
  readdir,
  rm,
  writeFile,
} from 'node:fs/promises'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  callCatalogResearchV2Action,
} from '../runtime/generated/flowblind-catalog-research-runtime-v2.mjs'
import {
  verifyFlowBlindCatalogResearchV2Package,
} from '../runtime/flowblind-research-teammate-verification-v2.mjs'
import {
  deriveHiddenScenarioProblemBytes,
  loadScenarioCoverage,
  runHiddenScientificScenario,
} from '../runtime/flowblind-scenario-harness-v2.mjs'
import {
  HIDDEN_FIXTURE,
  REGIONAL_FIXTURE,
  VECTOR_FIXTURE,
  fixtureIdentity,
  hiddenFixtureBytes,
  regionalFixtureBytes,
  vectorFixtureBytes,
} from './fixture-builders.mjs'

const packageRoot = resolve(import.meta.dirname, '..')
const scenarioWorkRoot = resolve(
  packageRoot,
  '.scenario-test-work',
)
const coveragePath = resolve(
  packageRoot,
  'runtime',
  'generated',
  'data',
  'flowblind-catalog-research-v2-scenario-coverage-v1.json',
)
const coverageBytes = await readFile(coveragePath)
const coverage = JSON.parse(
  coverageBytes.toString('utf8'),
)
const scenarios = new Map(
  coverage.scenarios.map((entry) => [
    entry.id,
    entry,
  ]),
)

const requiredScenarioIds = [
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

for (const id of requiredScenarioIds) {
  test(`${id} has an explicit package coverage declaration`, () => {
    const entry = scenarios.get(id)
    assert.ok(entry, `${id} is missing`)
    assert.ok(
      [
        'package-local-executable',
        'external-driver-required',
        'contract-only',
        'partial',
        'manual-live',
      ].includes(entry.coverageStatus),
    )
    if (
      entry.coverageStatus !==
      'package-local-executable'
    ) {
      assert.ok(
        entry.gaps.length > 0,
        `${id} must state its remaining gap`,
      )
    }
  })
}

test('V2-LIVE-001..004 remain manual-only and V2-OPS-006..008 remain contract-only', () => {
  for (const id of [
    'V2-LIVE-001',
    'V2-LIVE-002',
    'V2-LIVE-003',
    'V2-LIVE-004',
  ]) {
    assert.equal(
      scenarios.get(id).coverageStatus,
      'manual-live',
    )
    assert.deepEqual(
      scenarios.get(id).evidence,
      [],
    )
  }
  for (const id of [
    'V2-OPS-006',
    'V2-OPS-007',
    'V2-OPS-008',
  ]) {
    assert.equal(
      scenarios.get(id).coverageStatus,
      'contract-only',
    )
  }
})

test('V2-HID-007/008/009/014 export an honest deterministic external driver', async () => {
  const harnessCoverage =
    await loadScenarioCoverage()
  assert.deepEqual(
    harnessCoverage.bytes,
    coverageBytes,
  )
  for (const id of [
    'V2-HID-007',
    'V2-HID-008',
    'V2-HID-009',
    'V2-HID-014',
  ]) {
    const entry = scenarios.get(id)
    assert.equal(
      entry.coverageStatus,
      'external-driver-required',
    )
    assert.ok(
      entry.evidence.includes(
        'flowblind-scenario-harness-v2.mjs run-hidden',
      ),
    )
  }
  await assert.rejects(
    runHiddenScientificScenario({
      scenarioId: 'V2-HID-999',
    }),
    /accepts only V2-HID-007/iu,
  )
  const baseBytes = await readFile(
    resolve(
      packageRoot,
      'runtime',
      'generated',
      'retained',
      'hidden-flow-v1',
      'runtime',
      'generated',
      'data',
      'examples',
      'exact-null-component.json',
    ),
  )
  const infeasible = JSON.parse(
    deriveHiddenScenarioProblemBytes(
      'V2-HID-008',
      baseBytes,
    ).toString('utf8'),
  )
  assert.deepEqual(
    infeasible.observations.map(
      (observation) => [
        observation.type,
        observation.observedValue,
        observation.tolerance,
        observation.point,
        observation.component,
      ],
    ),
    [
      [
        'point-component',
        0,
        0,
        infeasible.target.point,
        infeasible.target.component,
      ],
      [
        'point-component',
        1,
        0,
        infeasible.target.point,
        infeasible.target.component,
      ],
    ],
  )
  const unbounded = JSON.parse(
    deriveHiddenScenarioProblemBytes(
      'V2-HID-009',
      baseBytes,
    ).toString('utf8'),
  )
  assert.deepEqual(unbounded.budgets, {
    velocityGradientRms: null,
    velocityRms: null,
  })

  test('V2-HID-005 retained exact-null and tolerance-speed bytes prepare without rewriting', async () => {
    const retainedRoot = resolve(
      packageRoot,
      'runtime',
      'generated',
      'retained',
      'hidden-flow-v1',
      'runtime',
    )
    const verifier = await import(
      pathToFileURL(
        resolve(
          retainedRoot,
          'flowblind-hidden-flow-capability-verification-v1.mjs',
        ),
      ).href
    )
    const verified =
      await verifier
        .verifyFlowBlindHiddenFlowPackage()
    const runtime = await import(
      `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
    )
    for (const example of [
      'exact-null-component.json',
      'tolerance-speed.json',
    ]) {
      const selectedProblemBytes = await readFile(
        resolve(
          retainedRoot,
          'generated',
          'data',
          'examples',
          example,
        ),
      )
      const prepared =
        await runtime.callCatalogHiddenFlowAction(
          'prepare-study',
          {
            goal:
              'Bound an unobserved hidden flow perturbation.',
            details: null,
          },
          { selectedProblemBytes },
          verified.runtimeAuthority,
        )
      assert.equal(
        prepared.response.status,
        'prepared-awaiting-confirmation',
        example,
      )
      assert.ok(prepared.bundle)
      assert.equal(
        createHash('sha256')
          .update(prepared.bundle.bytes)
          .digest('hex'),
        prepared.bundle.sha256,
      )
    }
  })

  test('V2-HID-005/007/008/009/014 attest the exact-byte bridge extension', async () => {
    assert.equal(
      scenarios.get('V2-HID-005').coverageStatus,
      'package-local-executable',
    )
    const activation = JSON.parse(
      await readFile(
        resolve(
          packageRoot,
          'runtime',
          'generated',
          'data',
          'manifests',
          'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
        ),
        'utf8',
      ),
    )
    assert.equal(
      activation.exactNativeBytePreservation,
      'versioned-package-source-extension',
    )
    const exactProblem = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'retained',
        'hidden-flow-v1',
        'runtime',
        'generated',
        'data',
        'examples',
        'exact-null-component.json',
      ),
    )
    const bridgeCanonicalProblem =
      deriveHiddenScenarioProblemBytes(
        'V2-HID-007',
        exactProblem,
      )
    assert.deepEqual(
      bridgeCanonicalProblem,
      exactProblem,
    )
  })
})

const expectedSourceModules = [
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
]

test('V2-PKG-002 binds the exact source-module allowlist', async () => {
  const manifest = JSON.parse(
    await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-catalog-research-v2-source-modules-v1.json',
      ),
      'utf8',
    ),
  )
  assert.deepEqual(
    manifest.modules.map(
      (entry) => entry.reference,
    ),
    expectedSourceModules,
  )
  assert.equal(
    manifest.moduleCount,
    expectedSourceModules.length,
  )
  assert.equal(
    manifest.modules.some((entry) =>
      /(?:catalogCapabilities|sensor|external|home|guided|legacy|fixture|runtime\/generated|runtime\/retained|generated\/retained)/iu.test(
        entry.reference,
      ),
    ),
    false,
  )
})

test('V2-PKG-001 uses the authoritative canonical package file names and retained roots', async () => {
  const canonicalFiles = [
    '.gitattributes',
    'README.md',
    'agent.yaml',
    'metadata.yaml',
    'flowblind-catalog-research-contract-v2.md',
    'tools/flowblind-prepare-study-v2/Dockerfile',
    'tools/flowblind-prepare-study-v2/tool.yaml',
    'tools/flowblind-run-and-verify-study-v2/Dockerfile',
    'tools/flowblind-run-and-verify-study-v2/tool.yaml',
    'runtime/flowblind-prepare-study-v2.mjs',
    'runtime/flowblind-run-and-verify-study-v2.mjs',
    'runtime/flowblind-report-resource-v2.mjs',
    'runtime/flowblind-hidden-declaration-preview-v2.mjs',
    'runtime/flowblind-research-teammate-verification-v2.mjs',
    'runtime/generated/flowblind-catalog-research-runtime-v2.mjs',
    'runtime/generated/data/flowblind-catalog-research-v2-package-lock-v1.json',
    'runtime/generated/data/manifests/flowblind-catalog-research-v2-source-modules-v1.json',
    'runtime/generated/data/manifests/flowblind-catalog-research-v2-retained-package-manifest-v1.json',
    'runtime/generated/data/flowblind-catalog-research-v2-release-policy-v1.json',
    'release/flowblind-catalog-research-v2-verifier-release-v1.json',
  ]
  for (const reference of canonicalFiles) {
    assert.ok(
      (await readFile(resolve(packageRoot, reference)))
        .byteLength > 0,
      `Missing canonical package file ${reference}`,
    )
  }
  const verifierRelease = JSON.parse(
    await readFile(
      resolve(
        packageRoot,
        'release',
        'flowblind-catalog-research-v2-verifier-release-v1.json',
      ),
      'utf8',
    ),
  )
  for (const binding of [
    verifierRelease.lock,
    verifierRelease.verifier,
  ]) {
    const bytes = await readFile(
      resolve(packageRoot, binding.reference),
    )
    assert.equal(bytes.byteLength, binding.byteLength)
    assert.equal(
      createHash('sha256')
        .update(bytes)
        .digest('hex'),
      binding.sha256,
    )
  }
  assert.deepEqual(
    verifierRelease.liveImageManifestDigests,
    {
      prepare: 'REQUIRED_BEFORE_LIVE_ACTIVATION',
      run: 'REQUIRED_BEFORE_LIVE_ACTIVATION',
    },
  )
  assert.equal(
    (
      await readdir(
        resolve(
          packageRoot,
          'runtime',
          'generated',
          'retained',
          'catalog-v1',
          'runtime',
        ),
      )
    ).length > 0,
    true,
  )
  assert.equal(
    (
      await readdir(
        resolve(
          packageRoot,
          'runtime',
          'generated',
          'retained',
          'hidden-flow-v1',
          'runtime',
        ),
      )
    ).length > 0,
    true,
  )
})

function treeSha256(files) {
  const hash = createHash('sha256')
  for (const file of files) {
    hash.update(file.reference)
    hash.update('\0')
    hash.update(String(file.byteLength))
    hash.update('\0')
    hash.update(file.sha256)
    hash.update('\n')
  }
  return hash.digest('hex')
}

test('V2-PKG-003 V2-PKG-004 bind every retained byte and tree hash', async () => {
  const lock = JSON.parse(
    await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'flowblind-catalog-research-v2-package-lock-v1.json',
      ),
      'utf8',
    ),
  )
  const expected = new Map([
    [
      'catalog-v1',
      {
        count: 27,
        tree:
          '7ba8a72539e9af2d461e941ffdbac3dd3e8a212c702dbe06b4c9b6fa0c34d802',
      },
    ],
    [
      'hidden-flow-v1',
      {
        count: 54,
        tree:
          '718bf2b8e7f3abe6d4d6338ad4141e5a28ff28432f2847ff610fc5f7809d204c',
      },
    ],
  ])
  const combined = JSON.parse(
    await readFile(
      resolve(
        packageRoot,
        'runtime',
        lock.retainedPackageManifest.reference,
      ),
      'utf8',
    ),
  )
  assert.deepEqual(
    combined.packages.map(
      (entry) => entry.retainedId,
    ),
    ['catalog-v1', 'hidden-flow-v1'],
  )
  for (
    const binding of
    lock.retainedPackageManifests
  ) {
    const manifest = JSON.parse(
      await readFile(
        resolve(
          packageRoot,
          'runtime',
          binding.manifest.reference,
        ),
        'utf8',
      ),
    )
    const wanted = expected.get(binding.id)
    assert.equal(manifest.files.length, wanted.count)
    assert.equal(manifest.treeSha256, wanted.tree)
    assert.equal(
      treeSha256(manifest.files),
      wanted.tree,
    )
    assert.deepEqual(
      combined.packages.find(
        (entry) =>
          entry.retainedId === binding.id,
      ),
      manifest,
    )
  }
})

async function allPackageFiles(root) {
  const files = []
  async function walk(current) {
    for (
      const entry of await readdir(current, {
        withFileTypes: true,
      })
    ) {
      const path = resolve(current, entry.name)
      if (entry.isDirectory()) {
        if (
          entry.name === '.scenario-test-work' ||
          entry.name === '.test-work' ||
          entry.name === '.git'
        ) {
          continue
        }
        await walk(path)
      } else if (entry.isFile()) {
        files.push(path)
      }
    }
  }
  await walk(root)
  return files.sort()
}

test('V2-PKG-007 scans LF bytes, secrets, and retained sources', async () => {
  const files = await allPackageFiles(packageRoot)
  const highConfidenceSecret =
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}/u
  for (const file of files) {
    const bytes = await readFile(file)
    assert.equal(
      bytes.includes(Buffer.from('\r\n')),
      false,
      `CRLF found in ${file}`,
    )
    assert.doesNotMatch(
      bytes.toString('utf8'),
      highConfidenceSecret,
      `Secret-like material found in ${file}`,
    )
  }
  assert.ok(
    files.some((file) =>
      file.includes(
        'runtime\\generated\\retained\\catalog-v1\\runtime',
      ) ||
      file.includes(
        'runtime/generated/retained/catalog-v1/runtime',
      ),
    ),
  )
  assert.ok(
    files.some((file) =>
      file.includes(
        'runtime\\generated\\retained\\hidden-flow-v1\\runtime',
      ) ||
      file.includes(
        'runtime/generated/retained/hidden-flow-v1/runtime',
      ),
    ),
  )
})

test('V2-PKG-007 generates only novel temporary FX-REG/FX-VEC/FX-HID fixture bytes', async () => {
  const regional = regionalFixtureBytes()
  const vector = vectorFixtureBytes()
  const hidden = hiddenFixtureBytes()
  assert.equal(
    regional.toString('utf8').split('\n').length - 2,
    REGIONAL_FIXTURE.dataRows,
  )
  const regionalLines =
    regional.toString('utf8').trimEnd().split('\n')
  assert.equal(
    regionalLines[1],
    '0,0,0.875,0.825',
  )
  assert.equal(
    vector.toString('utf8').split('\n').length - 2,
    VECTOR_FIXTURE.dataRows,
  )
  const vectorLines =
    vector.toString('utf8').trimEnd().split('\n')
  assert.equal(vectorLines[1], '0,0,0,0,0,1')
  assert.equal(
    vectorLines.at(-1),
    '1,6,5,4.75,-1.7,1',
  )
  assert.equal(
    JSON.parse(hidden.toString('utf8')).id,
    'fx-hid-min-problem-r17-v2',
  )
  const identities = [
    fixtureIdentity(regional),
    fixtureIdentity(vector),
    fixtureIdentity(hidden),
  ]
  const forbidden = new Set([
    '1d6ce4169b391e52b3927fb18b16ebb64f6b3546c4cafd77a54fee7307308613',
    'ba0de1b88f87086b980118acae8c78bed1be7b6dca9958604ec0108cef00e352',
    '7f2d9df9cf4ea01ef049a6e4e33ded38e791609e28cb7dd767dd28660cead24d',
    '931b9dc0c3b2a92fe51e926927e8ac6ea1ef6e4114b33d9bcacc243e42a1111a',
  ])
  for (const identity of identities) {
    assert.equal(
      forbidden.has(identity.sha256),
      false,
    )
  }
  const retainedExamples = [
    resolve(
      packageRoot,
      'runtime',
      'generated',
      'retained',
      'hidden-flow-v1',
      'runtime',
      'generated',
      'data',
      'examples',
      'exact-null-component.json',
    ),
    resolve(
      packageRoot,
      'runtime',
      'generated',
      'retained',
      'hidden-flow-v1',
      'runtime',
      'generated',
      'data',
      'examples',
      'tolerance-speed.json',
    ),
  ]
  for (const example of retainedExamples) {
    const digest = createHash('sha256')
      .update(await readFile(example))
      .digest('hex')
    assert.equal(
      identities.some(
        (identity) => identity.sha256 === digest,
      ),
      false,
    )
  }
  const pointComponentBase =
    await readFile(retainedExamples[0])
  const transientVariantIdentities = [
    fixtureIdentity(
      deriveHiddenScenarioProblemBytes(
        'V2-HID-008',
        pointComponentBase,
      ),
    ),
    fixtureIdentity(
      deriveHiddenScenarioProblemBytes(
        'V2-HID-009',
        pointComponentBase,
      ),
    ),
  ]
  const novelHashes = new Set(
    [
      ...identities,
      ...transientVariantIdentities,
    ].map((identity) => identity.sha256),
  )
  for (
    const file of await allPackageFiles(packageRoot)
  ) {
    const digest = createHash('sha256')
      .update(await readFile(file))
      .digest('hex')
    assert.equal(
      novelHashes.has(digest),
      false,
      `Novel fixture bytes were committed at ${file}`,
    )
  }
  assert.equal(
    [REGIONAL_FIXTURE.id, VECTOR_FIXTURE.id, HIDDEN_FIXTURE.id]
      .every((id) => id.startsWith('FX-')),
    true,
  )
})

function vectorCsv() {
  return vectorFixtureBytes().toString('utf8')
}

const vectorScientist = Object.freeze({
  researchGoal:
    'Audit this structured vector time series for velocity readiness and derivative evidence.',
  decisionQuestion:
    'Which reviewed vector evidence is available?',
  nextEvidenceIntent:
    'Identify missing evidence.',
})

function vectorMetadata(overrides = {}) {
  return {
    quantity: 'Two-dimensional validation velocity',
    vectorMeaning:
      'Deterministic v2 in-plane validation components u and v.',
    vectorSourceKind: 'generated',
    coordinateUnit: 'mm',
    valueUnit: 'mm/s',
    timeUnit: 's',
    samplingKind: 'instantaneous',
    selectedTime: 0.5,
    cycleStartTime: 0,
    cycleEndTime: 1,
    cyclePeriod: 1,
    cyclePhaseOrigin: 0,
    provenance:
      'Generated only in a temporary workspace by FX-VEC-7x6x13-v2.',
    license: 'CC0-1.0 test fixture',
    ...overrides,
  }
}

async function runVectorCase(
  name,
  csv,
  metadata,
) {
  const root = resolve(scenarioWorkRoot, name)
  const prepareInput = resolve(root, 'prepare-input')
  const prepareOutput = resolve(root, 'prepare-output')
  const runInput = resolve(root, 'run-input')
  const runOutput = resolve(root, 'run-output')
  await rm(root, { recursive: true, force: true })
  for (const path of [
    prepareInput,
    prepareOutput,
    runInput,
    runOutput,
  ]) {
    await mkdir(path, { recursive: true })
  }
  const bytes = Buffer.from(csv, 'utf8')
  await writeFile(
    resolve(prepareInput, 'candidate.csv'),
    bytes,
  )
  const verified =
    await verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'run-and-verify-study',
    })
  const prepared =
    await callCatalogResearchV2Action(
      'prepare-study',
      {
        ...vectorScientist,
        metadata,
      },
      {
        inputRoot: prepareInput,
        outputRoot: prepareOutput,
      },
      verified.packageVerification,
    )
  assert.equal(
    prepared.status,
    'prepared-awaiting-confirmation',
  )
  await writeFile(
    resolve(runInput, 'candidate.csv'),
    bytes,
  )
  const directory =
    `flowblind-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`
  await cp(
    resolve(prepareOutput, directory),
    resolve(runInput, directory),
    { recursive: true },
  )
  const result =
    await callCatalogResearchV2Action(
      'run-and-verify-study',
      vectorScientist,
      {
        inputRoot: runInput,
        outputRoot: runOutput,
        runConfirmationEvidence:
          verified.runConfirmationEvidence,
      },
      verified.packageVerification,
    )
  return Object.freeze({
    result,
    cleanup: () =>
      rm(root, { recursive: true, force: true }),
  })
}

function vectorMetrics(result) {
  assert.equal(result.status, 'report-complete')
  return result.result.verifiedStudy.result.report.metrics
}

test('V2-VEC-005 preserves frame-average temporal unavailability', async () => {
  const run = await runVectorCase(
    'frame-average',
    vectorCsv(),
    vectorMetadata({
      samplingKind: 'frame-average',
      exposureDuration: 0.05,
      selectedTime: 0,
    }),
  )
  try {
    const metrics = vectorMetrics(run.result)
    for (const metric of [
      metrics.instantaneous.speed,
      metrics.frameMean,
      metrics.completeCycle,
    ]) {
      assert.equal(metric.status, 'unavailable')
      assert.equal(
        metric.reason,
        'frame-average-exposure-metadata-insufficient',
      )
    }
  } finally {
    await run.cleanup()
  }
})

test('V2-VEC-006 preserves interpolation-gap and numerical-range evidence', async () => {
  const gapRows = ['time,x,y,u,v']
  for (const time of [0, 0.1, 1]) {
    for (let y = 0; y < 12; y += 1) {
      for (let x = 0; x < 12; x += 1) {
        gapRows.push(
          `${String(time)},${String(x)},${String(y)},${String(x + time)},${String(y - time)}`,
        )
      }
    }
  }
  const gap = await runVectorCase(
    'interpolation-gap',
    `${gapRows.join('\n')}\n`,
    vectorMetadata({
      selectedTime: 0.55,
      cycleStartTime: undefined,
      cycleEndTime: undefined,
      cyclePeriod: undefined,
      cyclePhaseOrigin: undefined,
    }),
  )
  try {
    assert.equal(
      vectorMetrics(gap.result).instantaneous.speed
        .reason,
      'interpolation-gap-too-large',
    )
  } finally {
    await gap.cleanup()
  }

  const rangeRows = ['x,y,u,v']
  for (let y = 0; y < 18; y += 1) {
    for (let x = 0; x < 18; x += 1) {
      rangeRows.push(
        `${String(x)},${String(y)},1.7976931348623157e308,1.7976931348623157e308`,
      )
    }
  }
  const range = await runVectorCase(
    'numerical-range',
    `${rangeRows.join('\n')}\n`,
    vectorMetadata({
      samplingKind: 'steady-state',
      selectedTime: undefined,
      cycleStartTime: undefined,
      cycleEndTime: undefined,
      cyclePeriod: undefined,
      cyclePhaseOrigin: undefined,
    }),
  )
  try {
    assert.equal(
      vectorMetrics(range.result).instantaneous.speed
        .reason,
      'numerical-range-exceeded',
    )
  } finally {
    await range.cleanup()
    await rm(scenarioWorkRoot, {
      recursive: true,
      force: true,
    })
  }
})

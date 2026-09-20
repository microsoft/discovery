import assert from 'node:assert/strict'
import {
  spawn,
  spawnSync,
} from 'node:child_process'
import { writeFileSync } from 'node:fs'
import {
  copyFile,
  cp,
  link,
  lstat,
  mkdir,
  readFile,
  readdir,
  rm,
  symlink,
  truncate,
  writeFile,
} from 'node:fs/promises'
import { createHash } from 'node:crypto'
import {
  dirname,
  relative,
  resolve,
} from 'node:path'
import test from 'node:test'
import {
  flowBlindCatalogResearchV2RunConfirmationEvidence,
  verifyRetainedPackage,
  verifyFlowBlindCatalogResearchV2Package,
} from '../runtime/flowblind-research-teammate-verification-v2.mjs'
import {
  callCatalogResearchV2Action,
  catalogResearchV2AdvertisedCapabilities,
  catalogResearchV2RuntimeVersion,
  catalogResearchV2SupportedActions,
  catalogResearchV2ToolDefinitions,
  previewCatalogResearchV2PrivateCapability,
  readCatalogResearchV2Resource,
  serializeCatalogResearchV2Value,
} from '../runtime/generated/flowblind-catalog-research-runtime-v2.mjs'
import {
  regionalFixtureBytes,
  vectorFixtureBytes,
} from './fixture-builders.mjs'
import {
  deriveHiddenScenarioProblemBytes,
  runHiddenScientificScenario,
} from '../runtime/flowblind-scenario-harness-v2.mjs'

const packageRoot = resolve(import.meta.dirname, '..')
const workRoot = resolve(packageRoot, '.test-work')
const regionalScientist = Object.freeze({
  researchGoal:
    'Compare reference and candidate agreement across spatial regions.',
  decisionQuestion:
    'Is agreement consistent across the field?',
  nextEvidenceIntent:
    'Review regional sensitivity.',
})
const regionalPrepare = Object.freeze({
  ...regionalScientist,
  metadata: Object.freeze({
    quantity: 'Synthetic regional scalar agreement',
    referenceMeaning:
      'Deterministic v2 validation reference values.',
    candidateMeaning:
      'Deterministic v2 validation candidate values with a bounded periodic offset.',
    coordinateUnit: 'index units',
    valueUnit: 'validation units',
    provenance:
      'Generated only in a temporary workspace by FX-REG-17x19-v2.',
    license: 'CC0-1.0 test fixture',
  }),
})

function isAbortError(error) {
  return error?.name === 'AbortError'
}

function abortAtStackFrame(frame) {
  let aborted = false
  const reason = new DOMException(
    `Cancelled at ${frame}.`,
    'AbortError',
  )
  function reachCheckpoint() {
    if (
      !aborted &&
      new Error().stack?.includes(frame)
    ) {
      aborted = true
    }
  }
  return {
    get aborted() {
      reachCheckpoint()
      return aborted
    },
    get reason() {
      return reason
    },
    throwIfAborted() {
      reachCheckpoint()
      if (aborted) throw reason
    },
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return true
    },
    onabort: null,
  }
}

function countStackFrame(frame) {
  let count = 0
  function inspect() {
    if (new Error().stack?.includes(frame)) {
      count += 1
    }
  }
  return {
    signal: {
      get aborted() {
        inspect()
        return false
      },
      get reason() {
        return undefined
      },
      throwIfAborted() {
        inspect()
      },
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {
        return true
      },
      onabort: null,
    },
    count() {
      return count
    },
  }
}

function mutateAtStackFrame(frame, mutate) {
  let mutated = false
  function inspect() {
    if (
      !mutated &&
      new Error().stack?.includes(frame)
    ) {
      mutate()
      mutated = true
    }
  }
  return {
    signal: {
      get aborted() {
        inspect()
        return false
      },
      get reason() {
        return undefined
      },
      throwIfAborted() {
        inspect()
      },
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {
        return true
      },
      onabort: null,
    },
    didMutate() {
      return mutated
    },
  }
}

function regionalCsv() {
  return regionalFixtureBytes().toString('utf8')
}

function vectorCsv() {
  return vectorFixtureBytes().toString('utf8')
}

async function leaveKilledHardlinkPair(
  source,
  stage,
  final,
) {
  const child = spawn(
    process.execPath,
    [
      '--input-type=module',
      '--eval',
      [
        "import { copyFile, link } from 'node:fs/promises'",
        'await copyFile(process.env.FLOWBLIND_TEST_SOURCE, process.env.FLOWBLIND_TEST_STAGE)',
        'await link(process.env.FLOWBLIND_TEST_STAGE, process.env.FLOWBLIND_TEST_FINAL)',
        "process.kill(process.pid, 'SIGKILL')",
      ].join(';'),
    ],
    {
      env: {
        ...process.env,
        FLOWBLIND_TEST_SOURCE: source,
        FLOWBLIND_TEST_STAGE: stage,
        FLOWBLIND_TEST_FINAL: final,
      },
      stdio: 'ignore',
    },
  )
  await new Promise((resolvePromise, reject) => {
    child.once('error', reject)
    child.once('close', (code, signal) => {
      if (code === 0 && signal === null) {
        reject(
          new Error(
            'The interruption fixture exited without being killed.',
          ),
        )
        return
      }
      resolvePromise()
    })
  })
}

function runNodeProcess(
  entry,
  environment,
) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(
      process.execPath,
      [entry],
      {
        env: {
          ...process.env,
          ...environment,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    )
    const stdout = []
    const stderr = []
    child.stdout.on('data', (chunk) => {
      stdout.push(chunk)
    })
    child.stderr.on('data', (chunk) => {
      stderr.push(chunk)
    })
    child.once('error', reject)
    child.once('close', (code, signal) => {
      if (code !== 0 || signal !== null) {
        reject(
          new Error(
            Buffer.concat(stderr).toString('utf8'),
          ),
        )
        return
      }
      resolvePromise(Buffer.concat(stdout))
    })
  })
}

async function emptyDirectory(path) {
  await rm(path, {
    recursive: true,
    force: true,
  })
  await mkdir(path, { recursive: true })
}

async function treeIdentity(root) {
  const entries = []
  async function walk(current) {
    for (
      const entry of await readdir(current, {
        withFileTypes: true,
      })
    ) {
      const path = resolve(current, entry.name)
      if (entry.isDirectory()) {
        await walk(path)
      } else if (entry.isFile()) {
        const bytes = await readFile(path)
        entries.push({
          reference: path
            .slice(root.length + 1)
            .replaceAll('\\', '/'),
          byteLength: bytes.byteLength,
          sha256: createHash('sha256')
            .update(bytes)
            .digest('hex'),
        })
      }
    }
  }
  await walk(root)
  return createHash('sha256')
    .update(
      entries
        .sort((left, right) =>
          left.reference.localeCompare(
            right.reference,
          ),
        )
        .map(
          (entry) =>
            `${entry.reference}\0${String(
              entry.byteLength,
            )}\0${entry.sha256}\n`,
        )
        .join(''),
    )
    .digest('hex')
}

async function listFiles(root) {
  const files = []
  async function walk(current) {
    for (
      const entry of await readdir(current, {
        withFileTypes: true,
      })
    ) {
      const path = resolve(current, entry.name)
      if (entry.isDirectory()) {
        await walk(path)
      } else if (entry.isFile()) {
        files.push(path)
      }
    }
  }
  await walk(root)
  return files.sort()
}

test('V2-HID-001 V2-PKG-001 V2-PKG-003 V2-PKG-004 attest the exact surface and retained roots', async () => {
  const verified =
    await verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'run-and-verify-study',
    })
  assert.equal(
    catalogResearchV2RuntimeVersion,
    '2.0.0',
  )
  assert.deepEqual(
    catalogResearchV2SupportedActions,
    ['prepare-study', 'run-and-verify-study'],
  )
  assert.deepEqual(
    catalogResearchV2ToolDefinitions.map(
      (tool) => [
        tool.name,
        tool.confirmation,
      ],
    ),
    [
      [
        'flowblind-prepare-study-v2',
        'Disabled',
      ],
      [
        'flowblind-run-and-verify-study-v2',
        'Enabled',
      ],
    ],
  )
  assert.deepEqual(
    catalogResearchV2AdvertisedCapabilities.map(
      (entry) => entry.identity.methodId,
    ),
    [
      'regional-agreement-v1',
      'vector-time-readiness-audit-v1',
    ],
  )
  assert.equal(
    Object.isFrozen(
      catalogResearchV2SupportedActions,
    ),
    true,
  )
  assert.equal(
    Object.isFrozen(
      catalogResearchV2AdvertisedCapabilities[0]
        .actions,
    ),
    true,
  )
  assert.throws(
    () =>
      catalogResearchV2SupportedActions.pop(),
    TypeError,
  )
  assert.throws(
    () =>
      catalogResearchV2AdvertisedCapabilities[0]
        .actions.pop(),
    TypeError,
  )
  const direct = await callCatalogResearchV2Action(
    'prepare-study',
    regionalPrepare,
    {
      inputRoot: resolve(workRoot, 'missing'),
      outputRoot: resolve(workRoot, 'missing'),
    },
    {},
  )
  assert.equal(
    direct.status,
    'authority-unavailable',
  )
  assert.deepEqual(direct.reasonCodes, [
    'package-attestation-failed',
  ])
  const hidden = await callCatalogResearchV2Action(
    'prepare-study',
    {
      researchGoal:
        'Bound an unobserved hidden flow perturbation.',
    },
    {
      inputRoot: resolve(workRoot, 'missing'),
      outputRoot: resolve(workRoot, 'missing'),
    },
    verified.packageVerification,
  )
  assert.equal(hidden.status, 'unsupported')
  assert.deepEqual(hidden.reasonCodes, [
    'no-advertised-capability-matched',
  ])
  assert.doesNotMatch(
    serializeCatalogResearchV2Value(hidden),
    /finite-basis-hidden-flow|requiredGrants|authorityRequirementId|trusted-private/iu,
  )
  const activationBytes = await readFile(
    resolve(
      packageRoot,
      'runtime',
      'generated',
      'data',
      'manifests',
      'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
    ),
  )
  const invalidActivation =
    await callCatalogResearchV2Action(
      'prepare-study',
      {
        researchGoal:
          'Bound an unobserved hidden flow perturbation.',
      },
      {
        inputRoot: resolve(workRoot, 'missing'),
        outputRoot: resolve(workRoot, 'missing'),
        privateActivation: {
          digest: `sha256:${'0'.repeat(64)}`,
          manifestBytes: activationBytes,
        },
      },
      verified.packageVerification,
    )
  assert.equal(
    serializeCatalogResearchV2Value(
      invalidActivation,
    ),
    serializeCatalogResearchV2Value(hidden),
  )
  const hiddenRun =
    await callCatalogResearchV2Action(
      'run-and-verify-study',
      {
        researchGoal:
          'Bound an unobserved hidden flow perturbation.',
      },
      {
        inputRoot: resolve(workRoot, 'missing'),
        outputRoot: resolve(workRoot, 'missing'),
        runConfirmationEvidence:
          verified.runConfirmationEvidence,
      },
      verified.packageVerification,
    )
  assert.equal(hiddenRun.status, 'unsupported')
  assert.deepEqual(hiddenRun.reasonCodes, [
    'no-advertised-capability-matched',
  ])
  assert.doesNotMatch(
    serializeCatalogResearchV2Value(hiddenRun),
    /finite-basis-hidden-flow|requiredGrants|authorityRequirementId|trusted-private/iu,
  )
  for (const [goal, privateToken] of [
    [
      'Design a sensor placement layout for this measurement field.',
      'flowblind-finite-sensor-placement',
    ],
    [
      'Run an external held-out validation comparison.',
      'generic-planar-external-validation',
    ],
    [
      'Run Home PIV quality control for this study.',
      'home-qc',
    ],
  ]) {
    const unavailable =
      await callCatalogResearchV2Action(
        'prepare-study',
        { researchGoal: goal },
        {
          inputRoot: resolve(workRoot, 'missing'),
          outputRoot: resolve(workRoot, 'missing'),
        },
        verified.packageVerification,
      )
    assert.equal(unavailable.status, 'unsupported')
    assert.deepEqual(unavailable.reasonCodes, [
      'no-advertised-capability-matched',
    ])
    assert.doesNotMatch(
      serializeCatalogResearchV2Value(
        unavailable,
      ),
      new RegExp(
        `${privateToken}|requiredGrants|authorityRequirementId`,
        'iu',
      ),
    )
  }
  const preview =
    await previewCatalogResearchV2PrivateCapability(
      {
        outputRoot: resolve(workRoot, 'missing'),
      },
      verified.packageVerification,
    )
  assert.equal(
    preview.authority.reason,
    'disabled-by-release-policy',
  )
  assert.equal(preview.releaseState, 'default-off')
  assert.doesNotMatch(
    serializeCatalogResearchV2Value(preview),
    /trusted-private/u,
  )
  const invalidPreview =
    await previewCatalogResearchV2PrivateCapability(
      {
        outputRoot: resolve(workRoot, 'missing'),
        privateActivation: {
          digest: `sha256:${'0'.repeat(64)}`,
          manifestBytes: activationBytes,
        },
      },
      verified.packageVerification,
    )
  assert.equal(
    serializeCatalogResearchV2Value(
      invalidPreview,
    ),
    serializeCatalogResearchV2Value(preview),
  )
})

test('facade failures preserve cancellation, attachment, conflict, and post-operation uncertainty', async () => {
  const {
    launcherFailure,
    launcherResultExitCode,
    privateActivation,
  } = await import(
    new URL(
      '../runtime/launcher-support.mjs',
      import.meta.url,
    ).href
  )
  const cancelled = new AbortController()
  cancelled.abort()
  assert.equal(
    launcherFailure(
      new Error('cancelled'),
      cancelled.signal,
    ).status,
    'execution-unavailable',
  )
  assert.equal(
    launcherFailure(
      Object.assign(new Error('attachment'), {
        code: 'attachment-invalid',
      }),
      undefined,
    ).status,
    'attachment-contract-invalid',
  )
  assert.equal(
    launcherFailure(
      Object.assign(new Error('conflict'), {
        code: 'output-conflict',
      }),
      undefined,
    ).status,
    'prior-outcome-unknown',
  )
  assert.equal(
    launcherFailure(
      new Error('serialization'),
      undefined,
      true,
    ).status,
    'prior-outcome-unknown',
  )
  const marker = Object.freeze({
    reference: 'marker.json',
    byteLength: 1,
    sha256: 'a'.repeat(64),
    mediaType: 'application/json',
  })
  const committed = (phase) => Object.freeze({
    status:
      phase === 'prepare'
        ? 'prepared-awaiting-confirmation'
        : 'report-complete',
    containsResults: phase === 'run',
    adapterPublication: Object.freeze({
      state: 'committed',
      owner: 'adapter',
      receipt: Object.freeze({
        status: 'committed',
        phase,
        marker,
        artifacts: [marker],
        pointOfNoReturn:
          phase === 'prepare'
            ? 'exclusive-preparation-commit-marker'
            : 'exclusive-report-commit-marker',
        distributedExactlyOnceClaim: false,
      }),
    }),
  })
  assert.equal(
    launcherResultExitCode(
      'prepare-study',
      committed('prepare'),
    ),
    0,
  )
  assert.equal(
    launcherResultExitCode(
      'run-and-verify-study',
      committed('run'),
    ),
    0,
  )
  assert.equal(
    launcherResultExitCode(
      'run-and-verify-study',
      {
        ...committed('run'),
        containsResults: false,
      },
    ),
    0,
  )
  assert.equal(
    launcherResultExitCode('prepare-study', {
      status: 'retained-family-outcome',
      containsResults: false,
    }),
    1,
  )
  assert.equal(
    launcherResultExitCode(
      'run-and-verify-study',
      {
        status: 'confirmation-required',
        containsResults: false,
        reasonCodes: [
          'run-confirmation-cancelled',
        ],
      },
    ),
    2,
  )
  assert.equal(
    launcherResultExitCode(
      'run-and-verify-study',
      {
        status: 'prior-outcome-unknown',
        containsResults: false,
      },
    ),
    3,
  )
  assert.equal(
    launcherFailure(
      new Error('serialization'),
      cancelled.signal,
      true,
    ).status,
    'prior-outcome-unknown',
  )
  const activationPath = resolve(
    packageRoot,
    'runtime',
    'generated',
    'data',
    'manifests',
    'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
  )
  const activationBytes = await readFile(
    activationPath,
  )
  const priorPath =
    process.env
      .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH
  const priorDigest =
    process.env
      .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256
  try {
    process.env
      .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH =
      activationPath
    process.env
      .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256 =
      `sha256:${createHash('sha256')
        .update(activationBytes)
        .digest('hex')}`
    await assert.rejects(
      privateActivation(),
      /outside the package runtime/u,
    )
  } finally {
    if (priorPath === undefined) {
      delete process.env
        .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH
    } else {
      process.env
        .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH =
        priorPath
    }
    if (priorDigest === undefined) {
      delete process.env
        .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256
    } else {
      process.env
        .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256 =
        priorDigest
    }
  }
})

test('facade contract failures exit nonzero so uncommitted output is not success-shaped', () => {
  const result = spawnSync(
    process.execPath,
    [
      resolve(
        packageRoot,
        'runtime',
        'flowblind-prepare-study-v2.mjs',
      ),
    ],
    {
      encoding: 'utf8',
      shell: false,
      env: {
        ...process.env,
        FLOWBLIND_TOOL_ROLE:
          'run-and-verify-study',
      },
    },
  )
  assert.equal(result.status, 1)
  assert.equal(
    JSON.parse(result.stdout).status,
    'authority-unavailable',
  )
  const protocolRefusal = spawnSync(
    process.execPath,
    [
      resolve(
        packageRoot,
        'runtime',
        'flowblind-prepare-study-v2.mjs',
      ),
      'Summarize this dataset.',
    ],
    {
      encoding: 'utf8',
      shell: false,
      env: {
        ...process.env,
        FLOWBLIND_TOOL_ROLE: 'prepare-study',
      },
    },
  )
  assert.equal(protocolRefusal.status, 1)
  assert.equal(
    JSON.parse(protocolRefusal.stdout)
      .containsResults,
    false,
  )
})

test('AbortSignal fails closed across verification, attachment reads, and deterministic publication', async () => {
  const alreadyAborted = new AbortController()
  alreadyAborted.abort()
  await assert.rejects(
    verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'prepare-study',
      signal: alreadyAborted.signal,
    }),
    isAbortError,
  )
  await assert.rejects(
    verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'prepare-study',
      signal: abortAtStackFrame('scanTree'),
    }),
    isAbortError,
  )

  const verified =
    await verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'prepare-study',
    })
  await assert.rejects(
    verifyRetainedPackage(
      verified.packageVerification,
      'catalog-v1',
      alreadyAborted.signal,
    ),
    isAbortError,
  )
  await assert.rejects(
    verifyRetainedPackage(
      verified.packageVerification,
      'catalog-v1',
      abortAtStackFrame(
        'retainedTreeDigest',
      ),
    ),
    isAbortError,
  )

  const publicInput = resolve(
    workRoot,
    'abort-public-input',
  )
  const publicOutput = resolve(
    workRoot,
    'abort-public-output',
  )
  const hiddenInput = resolve(
    workRoot,
    'abort-hidden-input',
  )
  const hiddenOutput = resolve(
    workRoot,
    'abort-hidden-output',
  )
  try {
    await emptyDirectory(publicInput)
    await emptyDirectory(publicOutput)
    await writeFile(
      resolve(publicInput, 'candidate.csv'),
      regionalFixtureBytes(),
    )
    await assert.rejects(
      callCatalogResearchV2Action(
        'prepare-study',
        regionalPrepare,
        {
          inputRoot: publicInput,
          outputRoot: publicOutput,
          signal: abortAtStackFrame(
            'listOrdinaryFiles',
          ),
        },
        verified.packageVerification,
      ),
      isAbortError,
    )
    assert.deepEqual(
      await readdir(publicOutput),
      [],
    )

    await emptyDirectory(hiddenInput)
    await emptyDirectory(hiddenOutput)
    await cp(
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
      resolve(hiddenInput, 'problem.json'),
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    await assert.rejects(
      callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Bound an unobserved hidden flow perturbation.',
        },
        {
          inputRoot: hiddenInput,
          outputRoot: hiddenOutput,
          signal: abortAtStackFrame(
            'installDeterministicFile',
          ),
          privateActivation: {
            digest:
              `sha256:${createHash('sha256')
                .update(manifest)
                .digest('hex')}`,
            manifestBytes: manifest,
          },
        },
        verified.packageVerification,
      ),
      isAbortError,
    )
    assert.deepEqual(
      await listFiles(hiddenOutput),
      [],
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }

  for (const reference of [
    'flowblind-prepare-study-v2.mjs',
    'flowblind-run-and-verify-study-v2.mjs',
    'flowblind-report-resource-v2.mjs',
    'flowblind-hidden-declaration-preview-v2.mjs',
  ]) {
    const launcher = await readFile(
      resolve(packageRoot, 'runtime', reference),
      'utf8',
    )
    assert.match(
      launcher,
      /verifyFlowBlindCatalogResearchV2Package\(\{[\s\S]*?signal:\s*abort\.signal/u,
      reference,
    )
  }
})

test('Hidden scenario inputs use cleaned OS-temporary storage outside the output root', async () => {
  const inputRoot = resolve(
    workRoot,
    'scenario-temp-input',
  )
  const outputRoot = resolve(
    workRoot,
    'scenario-temp-output',
  )
  const temporaryRoot = resolve(
    workRoot,
    'scenario-os-temp',
  )
  const activationRoot = resolve(
    workRoot,
    'scenario-activation',
  )
  const previous = {
    TEMP: process.env.TEMP,
    TMP: process.env.TMP,
    TMPDIR: process.env.TMPDIR,
  }
  try {
    for (const directory of [
      inputRoot,
      outputRoot,
      temporaryRoot,
      activationRoot,
    ]) {
      await emptyDirectory(directory)
    }
    const problemBytes = Buffer.from('{}\n')
    await writeFile(
      resolve(inputRoot, 'problem.json'),
      problemBytes,
    )
    const manifestPath = resolve(
      packageRoot,
      'runtime',
      'generated',
      'data',
      'manifests',
      'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
    )
    const manifest = await readFile(manifestPath)
    const activationPath = resolve(
      activationRoot,
      'manifest.json',
    )
    await writeFile(activationPath, manifest)
    process.env.TEMP = temporaryRoot
    process.env.TMP = temporaryRoot
    process.env.TMPDIR = temporaryRoot
    await assert.rejects(
      runHiddenScientificScenario({
        scenarioId: 'V2-HID-007',
        inputRoot,
        outputRoot,
        activationManifestPath: activationPath,
        activationManifestDigest:
          `sha256:${createHash('sha256')
            .update(manifest)
            .digest('hex')}`,
        researchGoal:
          'Bound an unobserved hidden flow perturbation.',
      }),
      /Hidden scenario preparation failed/iu,
    )
    assert.deepEqual(
      await readdir(temporaryRoot),
      [],
    )
    assert.deepEqual(
      await listFiles(outputRoot),
      [],
    )
  } finally {
    for (const [name, value] of Object.entries(
      previous,
    )) {
      if (value === undefined) {
        delete process.env[name]
      } else {
        process.env[name] = value
      }
    }
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('Host attachment mounts require exact public candidate.csv and hidden problem.json references', async () => {
  const publicInput = resolve(
    workRoot,
    'exact-reference-public-input',
  )
  const publicOutput = resolve(
    workRoot,
    'exact-reference-public-output',
  )
  const hiddenInput = resolve(
    workRoot,
    'exact-reference-hidden-input',
  )
  const hiddenOutput = resolve(
    workRoot,
    'exact-reference-hidden-output',
  )
  const publicRunInput = resolve(
    workRoot,
    'exact-reference-public-run-input',
  )
  const publicRunOutput = resolve(
    workRoot,
    'exact-reference-public-run-output',
  )
  try {
    for (const directory of [
      publicInput,
      publicOutput,
      hiddenInput,
      hiddenOutput,
      publicRunInput,
      publicRunOutput,
    ]) {
      await emptyDirectory(directory)
    }
    await mkdir(resolve(publicInput, 'renamed'))
    await writeFile(
      resolve(
        publicInput,
        'renamed',
        'candidate.csv',
      ),
      regionalFixtureBytes(),
    )
    const publicVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const publicResult =
      await callCatalogResearchV2Action(
        'prepare-study',
        regionalPrepare,
        {
          inputRoot: publicInput,
          outputRoot: publicOutput,
        },
        publicVerified.packageVerification,
      )
    assert.equal(
      publicResult.status,
      'attachment-contract-invalid',
    )
    assert.match(
      publicResult.guidance,
      /exact relative reference candidate\.csv/u,
    )
    assert.deepEqual(
      await listFiles(publicOutput),
      [],
    )

    await emptyDirectory(publicInput)
    await writeFile(
      resolve(publicInput, 'candidate.csv'),
      regionalFixtureBytes(),
    )
    const prepared =
      await callCatalogResearchV2Action(
        'prepare-study',
        regionalPrepare,
        {
          inputRoot: publicInput,
          outputRoot: publicOutput,
        },
        publicVerified.packageVerification,
      )
    assert.equal(
      prepared.status,
      'prepared-awaiting-confirmation',
    )
    const preparationDirectory =
      `flowblind-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`
    await writeFile(
      resolve(publicRunInput, 'candidate.csv'),
      regionalFixtureBytes(),
    )
    await copyFile(
      resolve(
        publicOutput,
        preparationDirectory,
        'preparation.json',
      ),
      resolve(publicRunInput, 'preparation.json'),
    )
    await copyFile(
      resolve(
        publicOutput,
        preparationDirectory,
        'trusted-sidecar.json',
      ),
      resolve(
        publicRunInput,
        'trusted-sidecar.json',
      ),
    )
    const runVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const flattenedRun =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: publicRunInput,
          outputRoot: publicRunOutput,
          runConfirmationEvidence:
            runVerified.runConfirmationEvidence,
        },
        runVerified.packageVerification,
      )
    assert.equal(
      flattenedRun.status,
      'attachment-contract-invalid',
    )
    assert.match(
      flattenedRun.guidance,
      /exact content-addressed directory/u,
    )
    assert.deepEqual(
      await listFiles(publicRunOutput),
      [],
    )

    await mkdir(resolve(hiddenInput, 'renamed'))
    await copyFile(
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
        hiddenInput,
        'renamed',
        'problem.json',
      ),
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const hiddenVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const hiddenResult =
      await callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Bound an unobserved hidden flow perturbation.',
        },
        {
          inputRoot: hiddenInput,
          outputRoot: hiddenOutput,
          privateActivation: {
            digest:
              `sha256:${createHash('sha256')
                .update(manifest)
                .digest('hex')}`,
            manifestBytes: manifest,
          },
        },
        hiddenVerified.packageVerification,
      )
    assert.equal(
      hiddenResult.status,
      'attachment-contract-invalid',
    )
    assert.match(
      hiddenResult.guidance,
      /exact relative reference problem\.json/u,
    )
    assert.deepEqual(
      await listFiles(hiddenOutput),
      [],
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('Hidden prepare enforces the problem snapshot byte ceiling', async () => {
  const inputRoot = resolve(
    workRoot,
    'hidden-problem-limit-input',
  )
  const outputRoot = resolve(
    workRoot,
    'hidden-problem-limit-output',
  )
  try {
    await emptyDirectory(inputRoot)
    await emptyDirectory(outputRoot)
    const problemPath = resolve(
      inputRoot,
      'problem.json',
    )
    await writeFile(problemPath, Buffer.from('{'))
    await truncate(
      problemPath,
      16 * 1024 * 1024 + 1,
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const verified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const result =
      await callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Bound an unobserved hidden flow perturbation.',
        },
        {
          inputRoot,
          outputRoot,
          privateActivation: {
            digest:
              `sha256:${createHash('sha256')
                .update(manifest)
                .digest('hex')}`,
            manifestBytes: manifest,
          },
        },
        verified.packageVerification,
      )
    assert.equal(
      result.status,
      'attachment-contract-invalid',
    )
    assert.match(
      result.guidance,
      /bounded|byte limit/iu,
    )
    assert.deepEqual(
      await listFiles(outputRoot),
      [],
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-PKG-001 V2-PKG-005 V2-PKG-006 V2-PKG-007 validate package surfaces and confinement metadata', async () => {
  assert.deepEqual(
    (
      await readdir(
        resolve(packageRoot, 'tools'),
        { withFileTypes: true },
      )
    )
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort(),
    [
      'flowblind-prepare-study-v2',
      'flowblind-run-and-verify-study-v2',
    ],
  )
  const agent = await readFile(
    resolve(packageRoot, 'agent.yaml'),
    'utf8',
  )
  assert.match(
    agent,
    /humanInTheLoop:\s*Enabled/u,
  )
  assert.match(
    agent,
    /allowMultipleToolCalls:\s*false/u,
  )
  assert.match(agent, /temperature:\s*0/u)
  const prepareTool = await readFile(
    resolve(
      packageRoot,
      'tools',
      'flowblind-prepare-study-v2',
      'tool.yaml',
    ),
    'utf8',
  )
  const runTool = await readFile(
    resolve(
      packageRoot,
      'tools',
      'flowblind-run-and-verify-study-v2',
      'tool.yaml',
    ),
    'utf8',
  )
  const publicDisplay = [
    agent,
    await readFile(
      resolve(packageRoot, 'metadata.yaml'),
      'utf8',
    ),
    prepareTool,
    runTool,
  ].join('\n')
  assert.doesNotMatch(
    publicDisplay,
    /finite-basis|hidden-flow|sensor placement|external validation|home qc/iu,
  )
  assert.doesNotMatch(
    prepareTool,
    /^\s+metadata:/mu,
  )
  for (const field of [
    'quantity',
    'referenceMeaning',
    'candidateMeaning',
    'vectorMeaning',
    'samplingKind',
    'provenance',
    'license',
  ]) {
    assert.match(
      prepareTool,
      new RegExp(`\\b${field}:`, 'u'),
    )
  }
  const requiredBlock =
    /      required:\r?\n((?:        - [^\r\n]+\r?\n)+)/u.exec(
      prepareTool,
    )
  assert.ok(requiredBlock)
  assert.deepEqual(
    requiredBlock[1]
      .trim()
      .split(/\r?\n/u)
      .map((line) =>
        line.replace(/^\s*-\s*/u, ''),
      ),
    ['researchGoal'],
  )
  const prepareSchema = JSON.parse(
    await readFile(
      resolve(
        packageRoot,
        'schemas',
        'flowblind-catalog-research-v2-prepare-input.schema.json',
      ),
      'utf8',
    ),
  )
  const runSchema = JSON.parse(
    await readFile(
      resolve(
        packageRoot,
        'schemas',
        'flowblind-catalog-research-v2-run-input.schema.json',
      ),
      'utf8',
    ),
  )
  const schemaText = JSON.stringify({
    prepareSchema,
    runSchema,
  })
  assert.equal(prepareSchema.oneOf.length, 3)
  assert.deepEqual(
    prepareSchema.oneOf.map(
      (branch) => branch.$ref,
    ),
    [
      '#/$defs/regionalInput',
      '#/$defs/vectorInput',
      '#/$defs/hiddenInput',
    ],
  )
  assert.deepEqual(
    prepareSchema.$defs.hiddenInput.required,
    ['researchGoal'],
  )
  assert.equal(
    Object.hasOwn(
      prepareSchema.$defs.hiddenInput.properties,
      'metadata',
    ),
    false,
  )
  assert.doesNotMatch(
    schemaText,
    /"(?:action|approval|approved|attachmentPath|authority|byteLength|confirmation|hash|manifest|methodId|mountUri|packageId|path|receipt|runId|sha256|toolName)"/u,
  )
  for (const folder of [
    'flowblind-prepare-study-v2',
    'flowblind-run-and-verify-study-v2',
  ]) {
    const dockerfile = await readFile(
      resolve(
        packageRoot,
        'tools',
        folder,
        'Dockerfile',
      ),
      'utf8',
    )
    assert.match(dockerfile, /USER 10001:10001/u)
    assert.match(dockerfile, /--require-hashes/u)
    assert.match(
      dockerfile,
      /generated\/retained\/hidden-flow-v1\/runtime\/generated\/data\/python\/requirements\.lock/u,
    )
    assert.doesNotMatch(
      dockerfile,
      /\b(?:curl|wget|apt-get)\b/u,
    )
    assert.equal(
      await treeIdentity(
        resolve(packageRoot, 'runtime'),
      ),
      await treeIdentity(
        resolve(
          packageRoot,
          'tools',
          folder,
          'runtime',
        ),
      ),
    )
  }
  for (const [outer, attested] of [
    [
      'agent.yaml',
      'runtime/generated/data/package/agent.yaml',
    ],
    [
      'metadata.yaml',
      'runtime/generated/data/package/metadata.yaml',
    ],
    [
      'package.json',
      'runtime/generated/data/package/package.json',
    ],
    [
      '.gitattributes',
      'runtime/generated/data/package/.gitattributes',
    ],
  ]) {
    assert.deepEqual(
      await readFile(resolve(packageRoot, outer)),
      await readFile(resolve(packageRoot, attested)),
    )
  }
  // The public catalog README adds contribution guidance while the attested
  // runtime copy remains byte-locked as integrated package evidence.
  const catalogReadme = await readFile(
    resolve(packageRoot, 'README.md'),
    'utf8',
  )
  const attestedReadme = await readFile(
    resolve(
      packageRoot,
      'runtime',
      'generated',
      'data',
      'package',
      'README.md',
    ),
    'utf8',
  )
  for (const heading of [
    'Overview',
    'Usage',
    'Prerequisites',
    'Architecture',
    'Tools',
    'Configuration',
    'Known Limitations',
    'Contributing',
  ]) {
    assert.match(
      catalogReadme,
      new RegExp(`^## ${heading}`, 'mu'),
    )
  }
  assert.match(
    catalogReadme,
    /routing and access boundary, not secrecy/iu,
  )
  assert.match(
    catalogReadme,
    /separately approved and allowlisted private overlay/iu,
  )
  assert.match(catalogReadme, /V2-LIVE-004/u)
  assert.match(
    catalogReadme,
    /Public demonstrations keep this route disabled/iu,
  )
  assert.match(
    attestedReadme,
    /portable catalog-native/u,
  )
  const runtimeText = await readFile(
    resolve(
      packageRoot,
      'runtime',
      'generated',
      'flowblind-catalog-research-runtime-v2.mjs',
    ),
    'utf8',
  )
  assert.doesNotMatch(
    runtimeText,
    /createDeterministicStage|\.flowblind-v2-stage-/u,
  )
})

test('V2-REG-002 V2-REG-003 V2-REG-006 V2-PKG-008 run regional preparation, restart reuse, URI, and tamper checks', async () => {
  const prepareInput = resolve(
    workRoot,
    'public-prepare-input',
  )
  const prepareOutput = resolve(
    workRoot,
    'public-prepare-output',
  )
  const runInput = resolve(
    workRoot,
    'public-run-input',
  )
  const runOutput = resolve(
    workRoot,
    'public-run-output',
  )
  const abortRunOutput = resolve(
    workRoot,
    'public-abort-run-output',
  )
  await emptyDirectory(prepareInput)
  await emptyDirectory(prepareOutput)
  await emptyDirectory(runInput)
  await emptyDirectory(runOutput)
  await emptyDirectory(abortRunOutput)
  try {
    const candidate = Buffer.from(
      regionalCsv(),
      'utf8',
    )
    await writeFile(
      resolve(prepareInput, 'candidate.csv'),
      candidate,
    )
    const verified =
      await verifyFlowBlindCatalogResearchV2Package()
    const prepareVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const runVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const evidenceProbe =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    assert.equal(
      prepareVerified.runConfirmationEvidence,
      null,
    )
    assert.equal(
      flowBlindCatalogResearchV2RunConfirmationEvidence(
        Object.freeze({}),
      ),
      null,
    )
    assert.equal(
      flowBlindCatalogResearchV2RunConfirmationEvidence(
        evidenceProbe.runConfirmationEvidence,
      ),
      evidenceProbe.runConfirmationEvidence,
    )
    const prepared =
      await callCatalogResearchV2Action(
        'prepare-study',
        regionalPrepare,
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
    assert.equal(prepared.containsResults, false)
    assert.equal(
      prepared.preparedStudy.preparationMarker
        .sha256,
      prepared.preparedStudy.preparationArtifact
        .sha256,
    )
    assert.equal(
      prepared.preparedStudy.preparationMarker
        .reference,
      prepared.preparation.preparationBundle
        .reference,
    )
    assert.match(
      prepared.preparedStudy.preparationMarker
        .reference,
      /^flowblind-preparation-[a-f0-9]{64}\/preparation\.json$/u,
    )
    const preparationDirectory =
      `flowblind-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`
    assert.deepEqual(
      (
        await listFiles(prepareOutput)
      ).map((file) =>
        relative(prepareOutput, file)
          .replaceAll('\\', '/'),
      ),
      [
        `${preparationDirectory}/preparation.json`,
        `${preparationDirectory}/trusted-sidecar.json`,
      ],
    )
    for (
      const file of await listFiles(prepareOutput)
    ) {
      assert.equal(
        (await readFile(file)).includes(candidate),
        false,
        `Preparation output retained candidate bytes: ${file}`,
      )
      assert.doesNotMatch(
        file,
        /\.flowblind-v2-stage-/u,
      )
    }

    await writeFile(
      resolve(runInput, 'candidate.csv'),
      candidate,
    )
    await cp(
      resolve(
        prepareOutput,
        preparationDirectory,
      ),
      resolve(runInput, preparationDirectory),
      { recursive: true },
    )
    const missingConfirmation =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
        },
        verified.packageVerification,
      )
    assert.equal(
      missingConfirmation.status,
      'authority-unavailable',
    )
    assert.equal(
      missingConfirmation.authority.reason,
      'host-confirmation-authority-unavailable',
    )
    const forgedConfirmation =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            Object.freeze({}),
        },
        verified.packageVerification,
      )
    assert.equal(
      forgedConfirmation.status,
      'authority-unavailable',
    )
    assert.equal(
      forgedConfirmation.authority.reason,
      'host-confirmation-authority-unavailable',
    )
    assert.deepEqual(
      await readdir(runOutput),
      [],
    )
    const abortVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const interrupted =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: abortRunOutput,
          runConfirmationEvidence:
            abortVerified.runConfirmationEvidence,
          signal: abortAtStackFrame(
            'runRetainedWithRestartGuard',
          ),
        },
        abortVerified.packageVerification,
      )
    assert.equal(
      interrupted.status,
      'prior-outcome-unknown',
    )
    assert.deepEqual(
      interrupted.reasonCodes,
      [
        'confirmed-execution-prior-outcome-unknown',
      ],
    )
    const preMarkerDirectory = resolve(
      runOutput,
      `flowblind-study-${prepared.preparedStudy.preparationArtifact.sha256}`,
    )
    await mkdir(preMarkerDirectory)
    await writeFile(
      resolve(
        preMarkerDirectory,
        'preparation.json',
      ),
      await readFile(
        resolve(
          runInput,
          preparationDirectory,
          'preparation.json',
        ),
      ),
    )
    const scienceInvocation =
      countStackFrame(
        'callCatalogResearchAction',
      )
    const result =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            runVerified.runConfirmationEvidence,
          signal: scienceInvocation.signal,
        },
        runVerified.packageVerification,
      )
    assert.equal(result.status, 'report-complete')
    assert.equal(result.containsResults, true)
    assert.ok(scienceInvocation.count() > 0)
    const reusedConfirmation =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            runVerified.runConfirmationEvidence,
        },
        runVerified.packageVerification,
      )
    assert.equal(
      reusedConfirmation.status,
      'authority-unavailable',
    )
    assert.equal(
      reusedConfirmation.authority.reason,
      'host-confirmation-authority-unavailable',
    )
    const committedFiles =
      await listFiles(runOutput)
    const committedSnapshots = new Map(
      await Promise.all(
        committedFiles.map(async (file) => {
          const [bytes, metadata] =
            await Promise.all([
              readFile(file),
              lstat(file, { bigint: true }),
            ])
          return [
            file,
            {
              bytes,
              mtimeNs: metadata.mtimeNs,
            },
          ]
        }),
      ),
    )
    const replay = JSON.parse(
      (
        await runNodeProcess(
          resolve(
            packageRoot,
            'runtime',
            'flowblind-run-and-verify-study-v2.mjs',
          ),
          {
            FLOWBLIND_TOOL_ROLE:
              'run-and-verify-study',
            FLOWBLIND_INPUT_ROOT: runInput,
            FLOWBLIND_OUTPUT_ROOT: runOutput,
            FLOWBLIND_RESEARCH_GOAL:
              regionalScientist.researchGoal,
            FLOWBLIND_DECISION_QUESTION:
              regionalScientist.decisionQuestion,
            FLOWBLIND_NEXT_EVIDENCE_INTENT:
              regionalScientist.nextEvidenceIntent,
          },
        )
      ).toString('utf8'),
    )
    assert.equal(
      serializeCatalogResearchV2Value(replay),
      serializeCatalogResearchV2Value(result),
    )
    assert.deepEqual(
      await listFiles(runOutput),
      committedFiles,
    )
    for (const [
      file,
      snapshot,
    ] of committedSnapshots) {
      assert.deepEqual(
        await readFile(file),
        snapshot.bytes,
      )
      assert.equal(
        (
          await lstat(file, {
            bigint: true,
          })
        ).mtimeNs,
        snapshot.mtimeNs,
      )
    }
    const markerPath = committedFiles.find(
      (file) =>
        file.endsWith(
          'report-verification.json',
        ),
    )
    assert.ok(markerPath)
    const markerStage = resolve(
      dirname(markerPath),
      '.report-verification.json.stage-00000000-0000-4000-8000-000000000000',
    )
    await link(markerPath, markerStage)
    assert.equal(
      (
        await lstat(markerPath, {
          bigint: true,
        })
      ).nlink,
      2n,
    )
    const recoveryInvocation =
      countStackFrame(
        'callCatalogResearchAction',
      )
    const recoveryVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const recovered =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            recoveryVerified
              .runConfirmationEvidence,
          signal: recoveryInvocation.signal,
        },
        recoveryVerified.packageVerification,
      )
    assert.equal(
      serializeCatalogResearchV2Value(recovered),
      serializeCatalogResearchV2Value(result),
    )
    assert.equal(
      recoveryInvocation.count(),
      0,
      'Committed report recovery invoked retained science.',
    )
    await assert.rejects(
      lstat(markerStage),
      (error) => error?.code === 'ENOENT',
    )
    assert.equal(
      (
        await lstat(markerPath, {
          bigint: true,
        })
      ).nlink,
      1n,
    )
    const orphanStage = resolve(
      dirname(markerPath),
      '.report-verification.json.stage-00000000-0000-4000-8000-000000000001',
    )
    await copyFile(markerPath, orphanStage)
    const orphanRecoveryInvocation =
      countStackFrame(
        'callCatalogResearchAction',
      )
    const orphanRecoveryVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const orphanRecovered =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            orphanRecoveryVerified
              .runConfirmationEvidence,
          signal: orphanRecoveryInvocation.signal,
        },
        orphanRecoveryVerified.packageVerification,
      )
    assert.equal(
      serializeCatalogResearchV2Value(
        orphanRecovered,
      ),
      serializeCatalogResearchV2Value(result),
    )
    assert.equal(
      orphanRecoveryInvocation.count(),
      0,
      'Abandoned marker staging cleanup invoked retained science.',
    )
    await assert.rejects(
      lstat(orphanStage),
      (error) => error?.code === 'ENOENT',
    )
    const staleStage = resolve(
      dirname(markerPath),
      '.report-verification.json.stage-00000000-0000-4000-8000-000000000002',
    )
    await copyFile(markerPath, staleStage)
    assert.notEqual(
      (
        await lstat(markerPath, {
          bigint: true,
        })
      ).ino,
      (
        await lstat(staleStage, {
          bigint: true,
        })
      ).ino,
    )
    const staleRecoveryInvocation =
      countStackFrame(
        'callCatalogResearchAction',
      )
    const staleRecoveryVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const staleRecovered =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        regionalScientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            staleRecoveryVerified
              .runConfirmationEvidence,
          signal: staleRecoveryInvocation.signal,
        },
        staleRecoveryVerified.packageVerification,
      )
    assert.equal(
      serializeCatalogResearchV2Value(
        staleRecovered,
      ),
      serializeCatalogResearchV2Value(result),
    )
    assert.equal(
      staleRecoveryInvocation.count(),
      0,
      'Abandoned marker staging cleanup invoked retained science.',
    )
    await assert.rejects(
      lstat(staleStage),
      (error) => error?.code === 'ENOENT',
    )

    const invalidOutput = resolve(
      workRoot,
      'public-invalid-marker-output',
    )
    await emptyDirectory(invalidOutput)
    const invalidDirectory = resolve(
      invalidOutput,
      `flowblind-study-${prepared.preparedStudy.preparationArtifact.sha256}`,
    )
    await mkdir(invalidDirectory)
    for (const [reference, bytes] of [
      [
        'preparation.json',
        await readFile(
          resolve(
            runInput,
            preparationDirectory,
            'preparation.json',
          ),
        ),
      ],
      ['verified-study.json', Buffer.from('{}\n')],
      ['report.md', Buffer.from('partial\n')],
      ['report.html', Buffer.from('partial\n')],
      [
        'report-verification.json',
        Buffer.from('{}\n'),
      ],
    ]) {
      await writeFile(
        resolve(invalidDirectory, reference),
        bytes,
      )
    }
    const invalidSnapshots = new Map(
      await Promise.all(
        (
          await listFiles(invalidOutput)
        ).map(async (file) => {
          const [bytes, metadata] =
            await Promise.all([
              readFile(file),
              lstat(file, { bigint: true }),
            ])
          return [
            file,
            {
              bytes,
              mtimeNs: metadata.mtimeNs,
            },
          ]
        }),
      ),
    )
    const invalidVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const invalid = await callCatalogResearchV2Action(
      'run-and-verify-study',
      regionalScientist,
      {
        inputRoot: runInput,
        outputRoot: invalidOutput,
        runConfirmationEvidence:
          invalidVerified
            .runConfirmationEvidence,
      },
      invalidVerified.packageVerification,
    )
    assert.equal(
      invalid.status,
      'prior-outcome-unknown',
    )
    assert.deepEqual(
      invalid.reasonCodes,
      [
        'retained-public-run-prior-outcome-unknown',
      ],
    )
    for (const [
      file,
      snapshot,
    ] of invalidSnapshots) {
      assert.deepEqual(
        await readFile(file),
        snapshot.bytes,
      )
      assert.equal(
        (
          await lstat(file, {
            bigint: true,
          })
        ).mtimeNs,
        snapshot.mtimeNs,
      )
    }
    const unrelatedHiddenDirectory = resolve(
      runOutput,
      `flowblind-hidden-flow-study-${'a'.repeat(64)}`,
    )
    await mkdir(unrelatedHiddenDirectory)
    await writeFile(
      resolve(
        unrelatedHiddenDirectory,
        'verified-run.json',
      ),
      Buffer.alloc(17 * 1024 * 1024, 0x31),
    )
    const report =
      await readCatalogResearchV2Resource(
        result.publication.resourceUri,
        runOutput,
        verified.packageVerification,
      )
    const html = Buffer.from(report).toString('utf8')
    assert.match(html, /FlowBlind/iu)
    assert.match(
      html,
      /<meta name="viewport"/u,
    )
    assert.match(html, /@media print/u)
    assert.match(html, /<main id="main-content">/u)
    await assert.rejects(
      readCatalogResearchV2Resource(
        result.publication.resourceUri,
        runOutput,
        verified.packageVerification,
        undefined,
        abortAtStackFrame('readStableFile'),
      ),
      isAbortError,
    )
    for (
      const file of await listFiles(runOutput)
    ) {
      assert.equal(
        (await readFile(file)).includes(candidate),
        false,
        `Run output retained candidate bytes: ${file}`,
      )
    }
    const htmlReference =
      result.result.verifiedStudy.artifacts.html
        .reference
    await writeFile(
      resolve(runOutput, htmlReference),
      Buffer.concat([
        await readFile(
          resolve(runOutput, htmlReference),
        ),
        Buffer.from('\nTAMPERED\n', 'utf8'),
      ]),
    )
    await assert.rejects(
      readCatalogResearchV2Resource(
        result.publication.resourceUri,
        runOutput,
        verified.packageVerification,
      ),
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('Confirmed public execution uses the exact immutable attachment bytes after caller mutation', async () => {
  const prepareInput = resolve(
    workRoot,
    'confirmed-snapshot-prepare-input',
  )
  const prepareOutput = resolve(
    workRoot,
    'confirmed-snapshot-prepare-output',
  )
  const runInput = resolve(
    workRoot,
    'confirmed-snapshot-run-input',
  )
  const runOutput = resolve(
    workRoot,
    'confirmed-snapshot-run-output',
  )
  try {
    await emptyDirectory(prepareInput)
    await emptyDirectory(prepareOutput)
    await emptyDirectory(runInput)
    await emptyDirectory(runOutput)
    const candidate = regionalFixtureBytes()
    await writeFile(
      resolve(prepareInput, 'candidate.csv'),
      candidate,
    )
    const prepareVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const prepared =
      await callCatalogResearchV2Action(
        'prepare-study',
        regionalPrepare,
        {
          inputRoot: prepareInput,
          outputRoot: prepareOutput,
        },
        prepareVerified.packageVerification,
      )
    assert.equal(
      prepared.status,
      'prepared-awaiting-confirmation',
    )
    const preparationDirectory =
      `flowblind-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`
    await writeFile(
      resolve(runInput, 'candidate.csv'),
      candidate,
    )
    await cp(
      resolve(
        prepareOutput,
        preparationDirectory,
      ),
      resolve(runInput, preparationDirectory),
      { recursive: true },
    )
    const mutatedCandidate = Buffer.concat([
      candidate,
      Buffer.from('\nmutated-after-selection\n'),
    ])
    const mutation = mutateAtStackFrame(
      'withConfirmedExecution',
      () => {
        writeFileSync(
          resolve(runInput, 'candidate.csv'),
          mutatedCandidate,
        )
      },
    )
    const runVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const context = {
      inputRoot: runInput,
      outputRoot: runOutput,
      runConfirmationEvidence:
        runVerified.runConfirmationEvidence,
      signal: mutation.signal,
    }
    const pending = callCatalogResearchV2Action(
      'run-and-verify-study',
      regionalScientist,
      context,
      runVerified.packageVerification,
    )
    context.runConfirmationEvidence = null
    const result = await pending
    assert.equal(mutation.didMutate(), true)
    assert.equal(result.status, 'report-complete')
    const confirmedCandidate =
      prepared.preparedStudy.resources
        .find((resource) =>
          resource.role === 'candidate-data'
        )
        .members.find((member) =>
          member.role === 'candidate-data'
        ).identity
    assert.equal(
      result.result.preparationEvidence.source
        .candidate.sha256,
      confirmedCandidate.sha256,
    )
    assert.equal(
      result.result.preparationEvidence.source
        .candidate.byteLength,
      confirmedCandidate.byteLength,
    )
    assert.notEqual(
      result.result.preparationEvidence.source
        .candidate.sha256,
      createHash('sha256')
        .update(mutatedCandidate)
        .digest('hex'),
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-HID-004 V2-HID-005 prepare the exact retained hidden problem and marker-last bundle', async () => {
  const inputRoot = resolve(
    workRoot,
    'hidden-input',
  )
  const outputRoot = resolve(
    workRoot,
    'hidden-output',
  )
  try {
    const verified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const digest =
      `sha256:${createHash('sha256')
        .update(manifest)
        .digest('hex')}`
    for (const example of [
      'exact-null-component.json',
      'tolerance-speed.json',
    ]) {
      await emptyDirectory(inputRoot)
      await emptyDirectory(outputRoot)
      const exactProblemBytes = await readFile(
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
          example,
        ),
      )
      const selectedProblemBytes =
        deriveHiddenScenarioProblemBytes(
          'V2-HID-007',
          exactProblemBytes,
        )
      await writeFile(
        resolve(inputRoot, 'problem.json'),
        selectedProblemBytes,
      )
      const prepared =
        await callCatalogResearchV2Action(
          'prepare-study',
          {
            researchGoal:
              'Bound an unobserved hidden flow perturbation.',
          },
          {
            inputRoot,
            outputRoot,
            privateActivation: {
              digest,
              manifestBytes: manifest,
            },
          },
          verified.packageVerification,
        )
      assert.equal(
        prepared.status,
        'prepared-awaiting-confirmation',
        example,
      )
      assert.equal(
        prepared.capability.methodId,
        'finite-basis-hidden-flow-v1',
      )
      assert.equal(
        prepared.preparation.problemSnapshot
          .byteLength,
        selectedProblemBytes.byteLength,
      )
      assert.equal(
        prepared.preparation.problemSnapshot.sha256,
        createHash('sha256')
          .update(selectedProblemBytes)
          .digest('hex'),
      )
      const directory = dirname(
        resolve(
          outputRoot,
          `flowblind-hidden-flow-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`,
          'preparation.json',
        ),
      )
      assert.equal(
        (
          await readFile(
            resolve(
              directory,
              'preparation-commit.json',
            ),
          )
        ).length,
        prepared.preparedStudy.preparationMarker
          .byteLength,
      )
    }
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('hidden run rejects a marker whose problem identity does not match the retained bundle', async () => {
  const prepareInput = resolve(
    workRoot,
    'hidden-cross-binding-prepare-input',
  )
  const prepareOutput = resolve(
    workRoot,
    'hidden-cross-binding-prepare-output',
  )
  const runInput = resolve(
    workRoot,
    'hidden-cross-binding-run-input',
  )
  const runOutput = resolve(
    workRoot,
    'hidden-cross-binding-run-output',
  )
  try {
    for (const directory of [
      prepareInput,
      prepareOutput,
      runInput,
      runOutput,
    ]) {
      await emptyDirectory(directory)
    }
    await copyFile(
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
      resolve(prepareInput, 'problem.json'),
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const privateActivation = {
      digest:
        `sha256:${createHash('sha256')
          .update(manifest)
          .digest('hex')}`,
      manifestBytes: manifest,
    }
    const scientist = {
      researchGoal:
        'Bound an unobserved hidden flow perturbation.',
    }
    const prepareVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const prepared =
      await callCatalogResearchV2Action(
        'prepare-study',
        scientist,
        {
          inputRoot: prepareInput,
          outputRoot: prepareOutput,
          privateActivation,
        },
        prepareVerified.packageVerification,
      )
    assert.equal(
      prepared.status,
      'prepared-awaiting-confirmation',
    )
    const directory =
      `flowblind-hidden-flow-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`
    await cp(
      resolve(prepareOutput, directory),
      resolve(runInput, directory),
      { recursive: true },
    )
    const markerPath = resolve(
      runInput,
      directory,
      'preparation-commit.json',
    )
    const marker = JSON.parse(
      await readFile(markerPath, 'utf8'),
    )
    marker.problemSnapshot.sha256 =
      '0'.repeat(64)
    await writeFile(
      markerPath,
      Buffer.from(JSON.stringify(marker)),
    )
    const runVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const result =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        scientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          privateActivation,
          runConfirmationEvidence:
            runVerified.runConfirmationEvidence,
        },
        runVerified.packageVerification,
      )
    assert.equal(
      result.status,
      'attachment-contract-invalid',
    )
    assert.deepEqual(
      await listFiles(runOutput),
      [],
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-PKG-008 reconciles killed hardlink staging and rejects conflicting or symlinked parents', async () => {
  const inputRoot = resolve(
    workRoot,
    'install-recovery-input',
  )
  const seedOutput = resolve(
    workRoot,
    'install-recovery-seed',
  )
  const recoveryOutput = resolve(
    workRoot,
    'install-recovery-output',
  )
  const conflictOutput = resolve(
    workRoot,
    'install-conflict-output',
  )
  const symlinkOutput = resolve(
    workRoot,
    'install-symlink-output',
  )
  const outsideOutput = resolve(
    workRoot,
    'install-symlink-outside',
  )
  try {
    for (const directory of [
      inputRoot,
      seedOutput,
      recoveryOutput,
      conflictOutput,
      symlinkOutput,
      outsideOutput,
    ]) {
      await emptyDirectory(directory)
    }
    await copyFile(
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
      resolve(inputRoot, 'problem.json'),
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const activation = {
      digest:
        `sha256:${createHash('sha256')
          .update(manifest)
          .digest('hex')}`,
      manifestBytes: manifest,
    }
    const verified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const prepareInto = (outputRoot) =>
      callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Bound an unobserved hidden flow perturbation.',
        },
        {
          inputRoot,
          outputRoot,
          privateActivation: activation,
        },
        verified.packageVerification,
      )
    const seed = await prepareInto(seedOutput)
    assert.equal(
      seed.status,
      'prepared-awaiting-confirmation',
    )
    const bundleSha256 =
      seed.preparedStudy.preparationArtifact
        .sha256
    const directory =
      `flowblind-hidden-flow-preparation-${bundleSha256}`
    const seedBundle = resolve(
      seedOutput,
      directory,
      'preparation.json',
    )
    const expectedBundle = await readFile(
      seedBundle,
    )

    const recoveryDirectory = resolve(
      recoveryOutput,
      directory,
    )
    await mkdir(recoveryDirectory)
    const recoveryStage = resolve(
      recoveryDirectory,
      '.flowblind-stage-preparation.json.part',
    )
    const recoveryFinal = resolve(
      recoveryDirectory,
      'preparation.json',
    )
    await leaveKilledHardlinkPair(
      seedBundle,
      recoveryStage,
      recoveryFinal,
    )
    const killedStage = await lstat(
      recoveryStage,
      { bigint: true },
    )
    const killedFinal = await lstat(
      recoveryFinal,
      { bigint: true },
    )
    assert.equal(killedStage.dev, killedFinal.dev)
    assert.equal(killedStage.ino, killedFinal.ino)
    assert.equal(killedStage.nlink, 2n)

    const recovered = await prepareInto(
      recoveryOutput,
    )
    assert.equal(
      recovered.status,
      'prepared-awaiting-confirmation',
    )
    await assert.rejects(
      lstat(recoveryStage),
      (error) => error?.code === 'ENOENT',
    )
    assert.deepEqual(
      await readFile(recoveryFinal),
      expectedBundle,
    )
    const recoveredFinalMetadata = await lstat(
      recoveryFinal,
      { bigint: true },
    )
    assert.equal(
      recoveredFinalMetadata.dev,
      killedFinal.dev,
    )
    assert.equal(
      recoveredFinalMetadata.ino,
      killedFinal.ino,
    )
    assert.equal(recoveredFinalMetadata.nlink, 1n)

    const conflictDirectory = resolve(
      conflictOutput,
      directory,
    )
    await mkdir(conflictDirectory)
    const conflictStage = resolve(
      conflictDirectory,
      '.flowblind-stage-preparation.json.part',
    )
    const conflictFinal = resolve(
      conflictDirectory,
      'preparation.json',
    )
    await copyFile(seedBundle, conflictStage)
    await copyFile(seedBundle, conflictFinal)
    const conflictStageMetadata = await lstat(
      conflictStage,
      { bigint: true },
    )
    const conflictFinalMetadata = await lstat(
      conflictFinal,
      { bigint: true },
    )
    assert.notEqual(
      conflictStageMetadata.ino,
      conflictFinalMetadata.ino,
    )
    await assert.rejects(
      prepareInto(conflictOutput),
      /crash-recovery|different files|output-conflict/iu,
    )
    assert.deepEqual(
      await readFile(conflictStage),
      expectedBundle,
    )
    assert.deepEqual(
      await readFile(conflictFinal),
      expectedBundle,
    )
    await assert.rejects(
      lstat(
        resolve(
          conflictDirectory,
          'preparation-commit.json',
        ),
      ),
      (error) => error?.code === 'ENOENT',
    )

    await symlink(
      outsideOutput,
      resolve(symlinkOutput, directory),
      process.platform === 'win32'
        ? 'junction'
        : 'dir',
    )
    await assert.rejects(
      prepareInto(symlinkOutput),
      /ordinary directory|aliased|symbolic/iu,
    )
    assert.deepEqual(
      await readdir(outsideOutput),
      [],
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-HID-014 recovers pre-marker residue and refuses invalid committed state without rerunning', async () => {
  const prepareInput = resolve(
    workRoot,
    'hidden-restart-prepare-input',
  )
  const prepareOutput = resolve(
    workRoot,
    'hidden-restart-prepare-output',
  )
  const runInput = resolve(
    workRoot,
    'hidden-restart-run-input',
  )
  try {
    for (const directory of [
      prepareInput,
      prepareOutput,
      runInput,
    ]) {
      await emptyDirectory(directory)
    }
    await copyFile(
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
      resolve(prepareInput, 'problem.json'),
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const privateActivation = {
      digest:
        `sha256:${createHash('sha256')
          .update(manifest)
          .digest('hex')}`,
      manifestBytes: manifest,
    }
    const prepareVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const scientist = {
      researchGoal:
        'Bound an unobserved hidden flow perturbation.',
    }
    const prepared =
      await callCatalogResearchV2Action(
        'prepare-study',
        scientist,
        {
          inputRoot: prepareInput,
          outputRoot: prepareOutput,
          privateActivation,
        },
        prepareVerified.packageVerification,
      )
    assert.equal(
      prepared.status,
      'prepared-awaiting-confirmation',
    )
    const preparationDirectory =
      `flowblind-hidden-flow-preparation-${prepared.preparedStudy.preparationArtifact.sha256}`
    await cp(
      resolve(
        prepareOutput,
        preparationDirectory,
      ),
      resolve(runInput, preparationDirectory),
      { recursive: true },
    )
    const reportDirectory =
      `flowblind-hidden-flow-study-${prepared.preparedStudy.preparationArtifact.sha256}`
    const abortOutput = resolve(
      workRoot,
      'hidden-restart-post-confirmation-abort',
    )
    await emptyDirectory(abortOutput)
    const abortVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const interrupted =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        scientist,
        {
          inputRoot: runInput,
          outputRoot: abortOutput,
          privateActivation,
          runConfirmationEvidence:
            abortVerified.runConfirmationEvidence,
          signal: abortAtStackFrame(
            'executeHiddenRetainedRun',
          ),
        },
        abortVerified.packageVerification,
      )
    assert.equal(
      interrupted.status,
      'prior-outcome-unknown',
    )
    assert.deepEqual(
      interrupted.reasonCodes,
      [
        'confirmed-execution-prior-outcome-unknown',
      ],
    )

    for (const state of [
      'partial',
      'invalid-marker',
    ]) {
      const outputRoot = resolve(
        workRoot,
        `hidden-restart-${state}`,
      )
      await emptyDirectory(outputRoot)
      const directory = resolve(
        outputRoot,
        reportDirectory,
      )
      await mkdir(directory)
      if (state === 'partial') {
        await writeFile(
          resolve(directory, 'verified-run.json'),
          Buffer.from('{}\n'),
        )
      } else {
        await writeFile(
          resolve(directory, 'verified-run.json'),
          Buffer.from('{}\n'),
        )
        await writeFile(
          resolve(directory, 'report.md'),
          Buffer.from('invalid\n'),
        )
        await writeFile(
          resolve(
            directory,
            'report-verification.json',
          ),
          Buffer.from('{}'),
        )
      }
      const before = new Map(
        await Promise.all(
          (
            await listFiles(outputRoot)
          ).map(async (file) => {
            const [bytes, metadata] =
              await Promise.all([
                readFile(file),
                lstat(file, { bigint: true }),
              ])
            return [
              file,
              {
                bytes,
                mtimeNs: metadata.mtimeNs,
              },
            ]
          }),
        ),
      )
      const runVerified =
        await verifyFlowBlindCatalogResearchV2Package({
          toolRole: 'run-and-verify-study',
        })
      const result =
        await callCatalogResearchV2Action(
          'run-and-verify-study',
          scientist,
          {
            inputRoot: runInput,
            outputRoot,
            privateActivation,
            runConfirmationEvidence:
              runVerified
                .runConfirmationEvidence,
          },
          runVerified.packageVerification,
        )
      assert.equal(
        result.status,
        state === 'partial'
          ? 'execution-unavailable'
          : 'prior-outcome-unknown',
        state,
      )
      assert.deepEqual(
        await listFiles(outputRoot),
        [...before.keys()].sort(),
      )
      for (const [file, snapshot] of before) {
        assert.deepEqual(
          await readFile(file),
          snapshot.bytes,
        )
        assert.equal(
          (
            await lstat(file, {
              bigint: true,
            })
          ).mtimeNs,
          snapshot.mtimeNs,
        )
      }
    }
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-VEC-002 V2-VEC-003 V2-VEC-008 run vector preparation and retained execution', async () => {
  const prepareInput = resolve(
    workRoot,
    'vector-prepare-input',
  )
  const prepareOutput = resolve(
    workRoot,
    'vector-prepare-output',
  )
  const runInput = resolve(
    workRoot,
    'vector-run-input',
  )
  const runOutput = resolve(
    workRoot,
    'vector-run-output',
  )
  await emptyDirectory(prepareInput)
  await emptyDirectory(prepareOutput)
  await emptyDirectory(runInput)
  await emptyDirectory(runOutput)
  try {
    const candidate = Buffer.from(
      vectorCsv(),
      'utf8',
    )
    await writeFile(
      resolve(prepareInput, 'candidate.csv'),
      candidate,
    )
    const verified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const scientist = {
      researchGoal:
        'Audit this vector time series for velocity readiness and derivative evidence.',
      decisionQuestion:
        'Which reviewed vector evidence is available?',
      nextEvidenceIntent:
        'Identify missing evidence.',
    }
    const prepared =
      await callCatalogResearchV2Action(
        'prepare-study',
        {
          ...scientist,
          metadata: {
            quantity:
              'Two-dimensional validation velocity',
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
          },
        },
        {
          inputRoot: prepareInput,
          outputRoot: prepareOutput,
        },
        verified.packageVerification,
      )
    assert.equal(
      prepared.capability.methodId,
      'vector-time-readiness-audit-v1',
    )
    await writeFile(
      resolve(runInput, 'candidate.csv'),
      candidate,
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
        scientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            verified.runConfirmationEvidence,
        },
        verified.packageVerification,
      )
    assert.equal(result.status, 'report-complete')
    assert.equal(
      result.capability.methodId,
      'vector-time-readiness-audit-v1',
    )
    const replayVerified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'run-and-verify-study',
      })
    const replay =
      await callCatalogResearchV2Action(
        'run-and-verify-study',
        scientist,
        {
          inputRoot: runInput,
          outputRoot: runOutput,
          runConfirmationEvidence:
            replayVerified
              .runConfirmationEvidence,
        },
        replayVerified.packageVerification,
      )
    assert.equal(
      serializeCatalogResearchV2Value(replay),
      serializeCatalogResearchV2Value(result),
    )
    const report =
      await readCatalogResearchV2Resource(
        result.publication.resourceUri,
        runOutput,
        verified.packageVerification,
      )
    assert.match(
      Buffer.from(report).toString('utf8'),
      /vector|velocity/iu,
    )
    for (
      const file of await listFiles(runOutput)
    ) {
      assert.equal(
        (await readFile(file)).includes(candidate),
        false,
        `Vector run output retained candidate bytes: ${file}`,
      )
    }
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-PKG-005 V2-PKG-008 reject an extra runtime file', async () => {
  const copied = resolve(workRoot, 'tampered')
  await rm(workRoot, {
    recursive: true,
    force: true,
  })
  await mkdir(workRoot, { recursive: true })
  try {
    await cp(
      resolve(packageRoot, 'runtime'),
      copied,
      { recursive: true },
    )
    await writeFile(
      resolve(copied, 'EXTRA'),
      'not attested\n',
    )
    const verifier = await import(
      `${new URL(
        '../.test-work/tampered/flowblind-research-teammate-verification-v2.mjs',
        import.meta.url,
      ).href}?tampered=1`
    )
    await assert.rejects(
      verifier
        .verifyFlowBlindCatalogResearchV2Package(),
      /missing, extra, case-aliased, linked, or unsafe/iu,
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('Public retained authority failure performs zero host input-file reads', async () => {
  await rm(workRoot, {
    recursive: true,
    force: true,
  })
  await mkdir(workRoot, { recursive: true })
  try {
    for (const mode of ['tampered', 'missing']) {
      const copied = resolve(
        workRoot,
        `public-authority-${mode}`,
      )
      const inputRoot = resolve(
        workRoot,
        `public-authority-${mode}-input`,
      )
      const outputRoot = resolve(
        workRoot,
        `public-authority-${mode}-output`,
      )
      await cp(
        resolve(packageRoot, 'runtime'),
        copied,
        { recursive: true },
      )
      await mkdir(inputRoot)
      await mkdir(outputRoot)
      await writeFile(
        resolve(inputRoot, 'candidate.csv'),
        regionalFixtureBytes(),
      )
      const retainedFile = resolve(
        copied,
        'generated',
        'retained',
        'catalog-v1',
        'runtime',
        'generated',
        'data',
        'catalog-policy-v1.json',
      )
      if (mode === 'tampered') {
        await writeFile(
          retainedFile,
          Buffer.concat([
            await readFile(retainedFile),
            Buffer.from('\n'),
          ]),
        )
      } else {
        await rm(retainedFile)
      }
      const verifier = await import(
        new URL(
          `../.test-work/public-authority-${mode}/flowblind-research-teammate-verification-v2.mjs`,
          import.meta.url,
        ).href
      )
      const runtime = await import(
        new URL(
          `../.test-work/public-authority-${mode}/generated/flowblind-catalog-research-runtime-v2.mjs`,
          import.meta.url,
        ).href
      )
      const verified =
        await verifier
          .verifyFlowBlindCatalogResearchV2Package({
            toolRole: 'prepare-study',
          })
      const inputReads =
        countStackFrame('listOrdinaryFiles')
      const result =
        await runtime.callCatalogResearchV2Action(
          'prepare-study',
          regionalPrepare,
          {
            inputRoot,
            outputRoot,
            signal: inputReads.signal,
          },
          verified.packageVerification,
        )
      assert.equal(
        result.status,
        'authority-unavailable',
        mode,
      )
      assert.equal(
        result.authority.reason,
        'retained-package-unavailable',
        mode,
      )
      assert.equal(
        inputReads.count(),
        0,
        `${mode} retained authority failure read host attachments`,
      )
      assert.deepEqual(
        await listFiles(outputRoot),
        [],
      )
    }
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('Public invocation snapshots caller context before authority awaits and keeps private capability identity redacted', async () => {
  const inputRoot = resolve(
    workRoot,
    'entry-snapshot-input',
  )
  const outputRoot = resolve(
    workRoot,
    'entry-snapshot-output',
  )
  const mutatedInputRoot = resolve(
    workRoot,
    'entry-snapshot-mutated-input',
  )
  const mutatedOutputRoot = resolve(
    workRoot,
    'entry-snapshot-mutated-output',
  )
  try {
    await emptyDirectory(inputRoot)
    await emptyDirectory(outputRoot)
    await emptyDirectory(mutatedInputRoot)
    await emptyDirectory(mutatedOutputRoot)
    const candidate = regionalFixtureBytes()
    await writeFile(
      resolve(inputRoot, 'candidate.csv'),
      candidate,
    )
    const manifest = await readFile(
      resolve(
        packageRoot,
        'runtime',
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const verified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const scientist = {
      ...regionalPrepare,
      metadata: {
        ...regionalPrepare.metadata,
      },
    }
    const context = {
      inputRoot,
      outputRoot,
    }
    const pending = callCatalogResearchV2Action(
      'prepare-study',
      scientist,
      context,
      verified.packageVerification,
    )
    scientist.researchGoal =
      'Bound an unobserved hidden flow perturbation.'
    scientist.metadata.quantity =
      'mutated after invocation'
    context.inputRoot = mutatedInputRoot
    context.outputRoot = mutatedOutputRoot
    context.privateActivation = {
      digest:
        `sha256:${createHash('sha256')
          .update(manifest)
          .digest('hex')}`,
      manifestBytes: manifest,
    }
    const result = await pending
    assert.equal(
      result.status,
      'prepared-awaiting-confirmation',
    )
    assert.equal(
      result.capability.methodId,
      'regional-agreement-v1',
    )
    assert.equal(
      result.preparedStudy.resources[0]
        .members[0].identity.sha256,
      createHash('sha256')
        .update(candidate)
        .digest('hex'),
    )
    assert.doesNotMatch(
      serializeCatalogResearchV2Value(result),
      /finite-basis-hidden-flow|requiredGrants|authorityRequirementId|trusted-private/iu,
    )
    assert.equal(
      (await listFiles(outputRoot)).length,
      2,
    )
    assert.deepEqual(
      await listFiles(mutatedOutputRoot),
      [],
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('Invalid public prepare metadata performs zero host attachment reads', async () => {
  const inputRoot = resolve(
    workRoot,
    'metadata-order-input',
  )
  const outputRoot = resolve(
    workRoot,
    'metadata-order-output',
  )
  try {
    await emptyDirectory(inputRoot)
    await emptyDirectory(outputRoot)
    await writeFile(
      resolve(inputRoot, 'candidate.csv'),
      regionalFixtureBytes(),
    )
    const verified =
      await verifyFlowBlindCatalogResearchV2Package({
        toolRole: 'prepare-study',
      })
    const inputReads =
      countStackFrame('listOrdinaryFiles')
    const result =
      await callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Compare reference and candidate agreement across spatial regions.',
          metadata: {
            quantity: 42,
          },
        },
        {
          inputRoot,
          outputRoot,
          signal: inputReads.signal,
        },
        verified.packageVerification,
      )
    assert.equal(
      result.status,
      'scientist-metadata-invalid',
    )
    assert.equal(
      inputReads.count(),
      0,
      'Invalid prepare metadata caused host attachment access.',
    )
    assert.deepEqual(
      await listFiles(outputRoot),
      [],
    )
    const vectorReads =
      countStackFrame('listOrdinaryFiles')
    const vectorResult =
      await callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Assess vector and temporal readiness for this velocity field.',
          metadata: {
            vectorSourceKind: {},
          },
        },
        {
          inputRoot,
          outputRoot,
          signal: vectorReads.signal,
        },
        verified.packageVerification,
      )
    assert.equal(
      vectorResult.status,
      'scientist-metadata-invalid',
    )
    assert.equal(
      vectorReads.count(),
      0,
      'Invalid vector metadata caused host attachment access.',
    )
    let getterReads = 0
    const accessorScientist = {
      researchGoal:
        'Compare reference and candidate agreement across spatial regions.',
    }
    Object.defineProperty(
      accessorScientist,
      'metadata',
      {
        enumerable: true,
        get() {
          getterReads += 1
          return {}
        },
      },
    )
    const accessorReads =
      countStackFrame('listOrdinaryFiles')
    const accessorResult =
      await callCatalogResearchV2Action(
        'prepare-study',
        accessorScientist,
        {
          inputRoot,
          outputRoot,
          signal: accessorReads.signal,
        },
        verified.packageVerification,
      )
    assert.equal(
      accessorResult.status,
      'invalid-scientist-request',
    )
    assert.equal(getterReads, 0)
    assert.equal(accessorReads.count(), 0)
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-HID-001 V2-PKG-004 defer hidden verification until exact activation', async () => {
  const copied = resolve(workRoot, 'lazy-retained')
  await rm(workRoot, {
    recursive: true,
    force: true,
  })
  await mkdir(workRoot, { recursive: true })
  try {
    await cp(
      resolve(packageRoot, 'runtime'),
      copied,
      { recursive: true },
    )
    const tamperedPath = resolve(
      copied,
      'generated',
      'retained',
      'hidden-flow-v1',
      'runtime',
      'generated',
      'data',
      'examples',
      'exact-null-component.json',
    )
    await writeFile(
      tamperedPath,
      Buffer.concat([
        await readFile(tamperedPath),
        Buffer.from('\n', 'utf8'),
      ]),
    )
    const verifier = await import(
      new URL(
        '../.test-work/lazy-retained/flowblind-research-teammate-verification-v2.mjs',
        import.meta.url,
      ).href
    )
    const runtime = await import(
      new URL(
        '../.test-work/lazy-retained/generated/flowblind-catalog-research-runtime-v2.mjs',
        import.meta.url,
      ).href
    )
    const verified =
      await verifier
        .verifyFlowBlindCatalogResearchV2Package()
    const withoutActivation =
      await runtime.callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Bound an unobserved hidden flow perturbation.',
        },
        {
          inputRoot: resolve(workRoot, 'absent'),
          outputRoot: resolve(workRoot, 'absent'),
        },
        verified.packageVerification,
      )
    assert.equal(
      withoutActivation.status,
      'unsupported',
    )
    assert.deepEqual(
      withoutActivation.reasonCodes,
      ['no-advertised-capability-matched'],
    )
    assert.doesNotMatch(
      serializeCatalogResearchV2Value(
        withoutActivation,
      ),
      /finite-basis-hidden-flow|requiredGrants|authorityRequirementId|trusted-private/iu,
    )
    const manifest = await readFile(
      resolve(
        copied,
        'generated',
        'data',
        'manifests',
        'flowblind-private-hidden-flow-v1-activation-manifest-v1.json',
      ),
    )
    const withActivation =
      await runtime.callCatalogResearchV2Action(
        'prepare-study',
        {
          researchGoal:
            'Bound an unobserved hidden flow perturbation.',
        },
        {
          inputRoot: resolve(workRoot, 'absent'),
          outputRoot: resolve(workRoot, 'absent'),
          privateActivation: {
            digest:
              `sha256:${createHash('sha256')
                .update(manifest)
                .digest('hex')}`,
            manifestBytes: manifest,
          },
        },
        verified.packageVerification,
      )
    assert.equal(
      withActivation.authority.reason,
      'package-verification-failed',
    )
    assert.equal(
      withActivation.releaseState,
      'trusted-private',
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-PKG-005 rejects hard-linked runtime files', async () => {
  const copied = resolve(workRoot, 'hard-linked')
  const outsideLink = resolve(
    workRoot,
    'verifier-hardlink.mjs',
  )
  await rm(workRoot, {
    recursive: true,
    force: true,
  })
  await mkdir(workRoot, { recursive: true })
  try {
    await cp(
      resolve(packageRoot, 'runtime'),
      copied,
      { recursive: true },
    )
    await link(
      resolve(
        copied,
        'flowblind-research-teammate-verification-v2.mjs',
      ),
      outsideLink,
    )
    const verifier = await import(
      `${new URL(
        '../.test-work/hard-linked/flowblind-research-teammate-verification-v2.mjs',
        import.meta.url,
      ).href}?hardlink=1`
    )
    await assert.rejects(
      verifier
        .verifyFlowBlindCatalogResearchV2Package(),
      /single-link|unsafe/iu,
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

test('V2-PKG-005 rejects outer lock tamper even when the changed file identity is updated', async () => {
  const copied = resolve(workRoot, 'lock-tamper')
  await rm(workRoot, {
    recursive: true,
    force: true,
  })
  await mkdir(workRoot, { recursive: true })
  try {
    await cp(
      resolve(packageRoot, 'runtime'),
      copied,
      { recursive: true },
    )
    const lockPath = resolve(
      copied,
      'generated',
      'data',
      'flowblind-catalog-research-v2-package-lock-v1.json',
    )
    const lock = JSON.parse(
      await readFile(lockPath, 'utf8'),
    )
    const policyPath = resolve(
      copied,
      lock.releasePolicy.reference,
    )
    const policyBytes = Buffer.from(
      (
        await readFile(policyPath, 'utf8')
      ).replace(
        '"runtimeNetworkRequired": false',
        '"runtimeNetworkRequired": true ',
      ),
      'utf8',
    )
    await writeFile(policyPath, policyBytes)
    const replacement = {
      ...lock.releasePolicy,
      byteLength: policyBytes.byteLength,
      sha256: createHash('sha256')
        .update(policyBytes)
        .digest('hex'),
    }
    lock.releasePolicy = replacement
    lock.files = lock.files.map((entry) =>
      entry.reference === replacement.reference
        ? replacement
        : entry,
    )
    await writeFile(
      lockPath,
      serializeCatalogResearchV2Value(lock),
    )
    const verifier = await import(
      `${new URL(
        '../.test-work/lock-tamper/flowblind-research-teammate-verification-v2.mjs',
        import.meta.url,
      ).href}?lock-tamper=1`
    )
    await assert.rejects(
      verifier
        .verifyFlowBlindCatalogResearchV2Package(),
      /package file .*lock.*failed byte verification/iu,
    )
  } finally {
    await rm(workRoot, {
      recursive: true,
      force: true,
    })
  }
})

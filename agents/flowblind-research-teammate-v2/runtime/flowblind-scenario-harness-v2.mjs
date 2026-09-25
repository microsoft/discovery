import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'
import {
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rm,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'
import {
  isAbsolute,
  relative,
  resolve,
  sep,
} from 'node:path'

const coverageReference =
  'generated/data/flowblind-catalog-research-v2-scenario-coverage-v1.json'
const hiddenScenarioExpectations = Object.freeze({
  'V2-HID-007': Object.freeze({
    kind: 'numerical',
    containsResults: true,
  }),
  'V2-HID-008': Object.freeze({
    kind: 'infeasible',
    containsResults: true,
  }),
  'V2-HID-009': Object.freeze({
    kind: 'unavailable',
    containsResults: false,
    evidenceState:
      'verified-unbounded-within-tolerance',
    reason: 'no-finite-bound',
  }),
  'V2-HID-014': Object.freeze({
    kind: null,
    containsResults: null,
  }),
})

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
  return value
}

function stableJson(value) {
  return `${JSON.stringify(stableValue(value), null, 2)}\n`
}

function throwIfAborted(signal) {
  signal?.throwIfAborted()
}

function sha256(bytes, signal) {
  throwIfAborted(signal)
  return createHash('sha256')
    .update(bytes)
    .digest('hex')
}

export async function loadScenarioCoverage(signal) {
  throwIfAborted(signal)
  const bytes = await readFile(
    resolve(import.meta.dirname, coverageReference),
    signal === undefined ? {} : { signal },
  )
  throwIfAborted(signal)
  const value = JSON.parse(bytes.toString('utf8'))
  return Object.freeze({
    bytes,
    value,
  })
}

function requiredText(value, name) {
  if (
    typeof value !== 'string' ||
    value.trim().length === 0
  ) {
    throw new Error(`${name} is required.`)
  }
  return value
}

function pathContains(root, candidate) {
  const child = relative(root, candidate)
  return (
    child.length === 0 ||
    (
      child !== '..' &&
      !child.startsWith(`..${sep}`) &&
      !isAbsolute(child)
    )
  )
}

function outcomeOf(result) {
  return result?.result?.outcome ?? null
}

function runFacade(
  reference,
  argumentsInput,
  environment,
  signal,
  allowProtocolFailure = false,
) {
  throwIfAborted(signal)
  return new Promise((resolveResult, reject) => {
    const child = spawn(
      process.execPath,
      [
        resolve(import.meta.dirname, reference),
        ...argumentsInput,
      ],
      {
        env: {
          ...process.env,
          ...environment,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
        ...(signal === undefined
          ? {}
          : { signal }),
      },
    )
    const stdout = []
    const stderr = []
    let stdoutBytes = 0
    let stderrBytes = 0
    child.stdout.on('data', (chunk) => {
      stdoutBytes += chunk.byteLength
      if (stdoutBytes > 64 * 1024 * 1024) {
        child.kill('SIGTERM')
        return
      }
      stdout.push(chunk)
    })
    child.stderr.on('data', (chunk) => {
      stderrBytes += chunk.byteLength
      if (stderrBytes <= 1024 * 1024) {
        stderr.push(chunk)
      }
    })
    child.once('error', reject)
    child.once('close', (code, terminationSignal) => {
      try {
        throwIfAborted(signal)
      } catch (error) {
        reject(error)
        return
      }
      const output = Buffer.concat(stdout)
      if (
        terminationSignal !== null ||
        stdoutBytes > 64 * 1024 * 1024
      ) {
        reject(
          new Error(
            `Scenario facade ${reference} failed: ${Buffer.concat(stderr).toString('utf8')}`,
          ),
        )
        return
      }
      if (code !== 0) {
        try {
          JSON.parse(output.toString('utf8'))
          if (allowProtocolFailure) {
            resolveResult({
              stdout: output,
              exitCode: code,
            })
            return
          }
          throw new Error(
            'Protocol failure is not allowed for this facade.',
          )
        } catch {
          reject(
            new Error(
              `Scenario facade ${reference} failed: ${Buffer.concat(stderr).toString('utf8')}`,
            ),
          )
          return
        }
      }
      resolveResult({
        stdout: output,
        exitCode: 0,
      })
    })
  })
}

export function deriveHiddenScenarioProblemBytes(
  scenarioId,
  baseBytes,
  signal,
) {
  throwIfAborted(signal)
  const base = JSON.parse(
    Buffer.from(baseBytes).toString('utf8'),
  )
  if (
    scenarioId === 'V2-HID-007' ||
    scenarioId === 'V2-HID-014'
  ) {
    return Buffer.from(baseBytes)
  }
  if (scenarioId === 'V2-HID-008') {
    if (base.target?.type !== 'point-component') {
      throw new Error(
        'V2-HID-008 requires a point-component base target.',
      )
    }
    base.id = 'catalog-hidden-flow-infeasible'
    base.title =
      'Catalog hidden-flow infeasibility fixture'
    base.observations = [
      {
        type: 'point-component',
        id: 'contradiction-zero',
        sensorId: 'contradiction-a',
        point: base.target.point,
        coordinateFrameId:
          base.domain.coordinateFrameId,
        unit: 'mm/s',
        component: base.target.component,
        baselineValue: 0,
        observedValue: 0,
        tolerance: 0,
        provenance:
          'Generated contradiction for package scenario testing.',
      },
      {
        type: 'point-component',
        id: 'contradiction-one',
        sensorId: 'contradiction-b',
        point: base.target.point,
        coordinateFrameId:
          base.domain.coordinateFrameId,
        unit: 'mm/s',
        component: base.target.component,
        baselineValue: 0,
        observedValue: 1,
        tolerance: 0,
        provenance:
          'Generated contradiction for package scenario testing.',
      },
    ]
    return Buffer.from(
      stableJson(base),
      'utf8',
    )
  }
  if (scenarioId === 'V2-HID-009') {
    base.id = 'catalog-hidden-flow-unbounded'
    base.title =
      'Catalog hidden-flow unbounded fixture'
    base.budgets = {
      velocityRms: null,
      velocityGradientRms: null,
    }
    return Buffer.from(
      stableJson(base),
      'utf8',
    )
  }
  throw new Error(
    'The hidden problem derivation accepts only V2-HID-007, V2-HID-008, V2-HID-009, or V2-HID-014.',
  )
}

export async function runHiddenScientificScenario(input) {
  const signal = input.signal
  throwIfAborted(signal)
  const expected =
    hiddenScenarioExpectations[input.scenarioId]
  if (expected === undefined) {
    throw new Error(
      'The hidden scenario harness accepts only V2-HID-007, V2-HID-008, V2-HID-009, or V2-HID-014.',
    )
  }
  const inputRoot = resolve(
    requiredText(input.inputRoot, 'inputRoot'),
  )
  const outputRoot = resolve(
    requiredText(input.outputRoot, 'outputRoot'),
  )
  throwIfAborted(signal)
  const outputEntries = await readdir(outputRoot)
  throwIfAborted(signal)
  if (outputEntries.length !== 0) {
    throw new Error(
      'The deterministic hidden scenario output root must be empty.',
    )
  }
  throwIfAborted(signal)
  const baseBytes = await readFile(
    resolve(inputRoot, 'problem.json'),
    signal === undefined ? {} : { signal },
  )
  throwIfAborted(signal)
  const selectedProblemBytes =
    deriveHiddenScenarioProblemBytes(
      input.scenarioId,
      baseBytes,
      signal,
    )
  throwIfAborted(signal)
  const activationBytes = await readFile(
    resolve(
      requiredText(
        input.activationManifestPath,
        'activationManifestPath',
      ),
    ),
    signal === undefined ? {} : { signal },
  )
  throwIfAborted(signal)
  const activationDigest = requiredText(
    input.activationManifestDigest,
    'activationManifestDigest',
  )
  if (
    activationDigest !==
    `sha256:${sha256(activationBytes, signal)}`
  ) {
    throw new Error(
      'The host-provided activation manifest digest does not match its exact bytes.',
    )
  }
  const researchGoal = requiredText(
    input.researchGoal,
    'researchGoal',
  )
  const commonEnvironment = {
    FLOWBLIND_RESEARCH_GOAL: researchGoal,
    ...(input.decisionQuestion === undefined
      ? {}
      : {
          FLOWBLIND_DECISION_QUESTION:
            input.decisionQuestion,
        }),
    ...(input.nextEvidenceIntent === undefined
      ? {}
      : {
          FLOWBLIND_NEXT_EVIDENCE_INTENT:
            input.nextEvidenceIntent,
        }),
    FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH:
      resolve(input.activationManifestPath),
    FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256:
      activationDigest,
  }
  const generatedInputRoot = await mkdtemp(
    resolve(
      tmpdir(),
      'flowblind-hidden-scenario-input-',
    ),
  )
  let prepared
  try {
    throwIfAborted(signal)
    const canonicalOutputRoot =
      await realpath(outputRoot)
    throwIfAborted(signal)
    const canonicalGeneratedInputRoot =
      await realpath(generatedInputRoot)
    throwIfAborted(signal)
    if (
      pathContains(
        canonicalOutputRoot,
        canonicalGeneratedInputRoot,
      )
    ) {
      throw new Error(
        'The OS temporary input directory must be outside the report output root.',
      )
    }
    await writeFile(
      resolve(
        generatedInputRoot,
        'problem.json',
      ),
      selectedProblemBytes,
      signal === undefined ? {} : { signal },
    )
    throwIfAborted(signal)
    const preparedProcess = await runFacade(
      'flowblind-prepare-study-v2.mjs',
      [],
      {
        ...commonEnvironment,
        FLOWBLIND_TOOL_ROLE: 'prepare-study',
        FLOWBLIND_INPUT_ROOT:
          generatedInputRoot,
        FLOWBLIND_OUTPUT_ROOT: outputRoot,
      },
      signal,
      true,
    )
    throwIfAborted(signal)
    prepared = JSON.parse(
      preparedProcess.stdout.toString('utf8'),
    )
    if (preparedProcess.exitCode !== 0) {
      throw new Error(
        `Hidden scenario preparation failed: ${stableJson(prepared)}`,
      )
    }
  } finally {
    await rm(generatedInputRoot, {
      recursive: true,
      force: true,
    })
    throwIfAborted(signal)
  }
  if (
    prepared.status !==
      'prepared-awaiting-confirmation' ||
    prepared.capability?.methodId !==
      'finite-basis-hidden-flow-v1'
  ) {
    throw new Error(
      `Hidden scenario preparation failed: ${stableJson(prepared)}`,
    )
  }
  const resultProcess = await runFacade(
    'flowblind-run-and-verify-study-v2.mjs',
    [],
    {
      ...commonEnvironment,
      FLOWBLIND_TOOL_ROLE:
        'run-and-verify-study',
      FLOWBLIND_INPUT_ROOT: outputRoot,
      FLOWBLIND_OUTPUT_ROOT: outputRoot,
    },
    signal,
    true,
  )
  throwIfAborted(signal)
  const result = JSON.parse(
    resultProcess.stdout.toString('utf8'),
  )
  if (
    resultProcess.exitCode !== 0 ||
    result.status !== 'report-complete'
  ) {
    throw new Error(
      `Hidden scenario run failed: ${stableJson(result)}`,
    )
  }
  const outcome = outcomeOf(result)
  if (
    outcome === null ||
    (
      expected.kind !== null &&
      outcome.kind !== expected.kind
    ) ||
    (
      expected.containsResults !== null &&
      result.containsResults !==
        expected.containsResults
    ) ||
    (
      'evidenceState' in expected &&
      outcome.evidenceState !==
        expected.evidenceState
    ) ||
    (
      'reason' in expected &&
      outcome.reason !== expected.reason
    )
  ) {
    throw new Error(
      `Hidden scenario outcome mismatch: ${stableJson(result)}`,
    )
  }
  const resourceProcess = await runFacade(
    'flowblind-report-resource-v2.mjs',
    [result.publication.resourceUri],
    {
      ...commonEnvironment,
      FLOWBLIND_OUTPUT_ROOT: outputRoot,
    },
    signal,
  )
  const resourceBytes = resourceProcess.stdout
  throwIfAborted(signal)
  return Object.freeze({
    schemaVersion: 1,
    recordType:
      'flowblind-catalog-research-v2-scenario-driver-result-v1',
    scenarioId: input.scenarioId,
    status: result.status,
    containsResults: result.containsResults,
    outcome,
    preparation: Object.freeze({
      markerSha256:
        prepared.preparedStudy
          .preparationMarker.sha256,
      bundleSha256:
        prepared.preparedStudy
          .preparationArtifact.sha256,
    }),
    resource: Object.freeze({
      uri: result.publication.resourceUri,
      byteLength: resourceBytes.byteLength,
      sha256: sha256(resourceBytes, signal),
    }),
  })
}

async function main() {
  const abort = new AbortController()
  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.once(signal, () => abort.abort())
  }
  const [command = 'describe'] = process.argv.slice(2)
  if (command === 'describe') {
    const coverage = await loadScenarioCoverage(
      abort.signal,
    )
    throwIfAborted(abort.signal)
    process.stdout.write(coverage.bytes)
    return
  }
  if (command !== 'run-hidden') {
    throw new Error(
      'Use describe or run-hidden.',
    )
  }
  const result = await runHiddenScientificScenario({
    scenarioId: requiredText(
      process.env.FLOWBLIND_SCENARIO_ID,
      'FLOWBLIND_SCENARIO_ID',
    ),
    inputRoot:
      process.env.FLOWBLIND_INPUT_ROOT ??
      '/mnt/input',
    outputRoot:
      process.env.FLOWBLIND_OUTPUT_ROOT ??
      '/output',
    activationManifestPath:
      process.env
        .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH,
    activationManifestDigest:
      process.env
        .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256,
    researchGoal:
      process.env.FLOWBLIND_RESEARCH_GOAL ??
      'Bound an unobserved hidden flow perturbation.',
    decisionQuestion:
      process.env.FLOWBLIND_DECISION_QUESTION,
    nextEvidenceIntent:
      process.env.FLOWBLIND_NEXT_EVIDENCE_INTENT,
    signal: abort.signal,
  })
  throwIfAborted(abort.signal)
  process.stdout.write(stableJson(result))
}

const invokedPath =
  process.argv[1] === undefined
    ? null
    : pathToFileURL(resolve(process.argv[1])).href
if (invokedPath === import.meta.url) {
  main().catch((error) => {
    if (
      error?.name !== 'AbortError'
    ) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      )
    }
    process.exitCode = 2
  })
}

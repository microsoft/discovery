import {
  lstat,
  readFile,
  realpath,
} from 'node:fs/promises'
import {
  isAbsolute,
  relative,
  resolve,
  sep,
} from 'node:path'

const ABSENT = '0'

function decodeHandlebars(value) {
  return value
    .replaceAll('&quot;', '"')
    .replaceAll('&#x27;', "'")
    .replaceAll('&#39;', "'")
    .replaceAll('&#x60;', '`')
    .replaceAll('&#x3D;', '=')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&amp;', '&')
}

function absent(value) {
  if (value === undefined) return true
  const normalized = value.trim()
  return (
    normalized.length === 0 ||
    /^(?:undefined|null)$/iu.test(normalized) ||
    /^\{\{[A-Za-z0-9_.]+\}\}$/u.test(normalized)
  )
}

function optionalText(name) {
  const raw = process.env[name]
  return absent(raw)
    ? undefined
    : decodeHandlebars(raw)
}

function optionalNumber(name) {
  const raw = optionalText(name)
  if (raw === undefined) return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : raw
}

function compactObject(value) {
  return Object.fromEntries(
    Object.entries(value).filter(
      ([, member]) => member !== undefined,
    ),
  )
}

export function scientistInput(action) {
  const [
    argumentResearchGoal,
    decisionPresent = ABSENT,
    argumentDecisionQuestion = '',
    nextPresent = ABSENT,
    argumentNextEvidenceIntent = '',
  ] = process.argv.slice(2)
  const argumentsProvided = process.argv.length > 2
  const researchGoal = argumentsProvided
    ? argumentResearchGoal ?? ''
    : process.env.FLOWBLIND_RESEARCH_GOAL ?? ''
  const decisionQuestion = argumentsProvided
    ? decisionPresent === ABSENT
      ? undefined
      : decodeHandlebars(argumentDecisionQuestion)
    : optionalText('FLOWBLIND_DECISION_QUESTION')
  const nextEvidenceIntent = argumentsProvided
    ? nextPresent === ABSENT
      ? undefined
      : decodeHandlebars(argumentNextEvidenceIntent)
    : optionalText('FLOWBLIND_NEXT_EVIDENCE_INTENT')
  const common = compactObject({
    researchGoal: decodeHandlebars(researchGoal),
    decisionQuestion,
    nextEvidenceIntent,
  })
  if (action === 'run-and-verify-study') {
    return common
  }
  const metadata = compactObject({
    quantity: optionalText(
      'FLOWBLIND_METADATA_QUANTITY',
    ),
    referenceMeaning: optionalText(
      'FLOWBLIND_METADATA_REFERENCE_MEANING',
    ),
    candidateMeaning: optionalText(
      'FLOWBLIND_METADATA_CANDIDATE_MEANING',
    ),
    vectorMeaning: optionalText(
      'FLOWBLIND_METADATA_VECTOR_MEANING',
    ),
    vectorSourceKind: optionalText(
      'FLOWBLIND_METADATA_VECTOR_SOURCE_KIND',
    ),
    coordinateUnit: optionalText(
      'FLOWBLIND_METADATA_COORDINATE_UNIT',
    ),
    valueUnit: optionalText(
      'FLOWBLIND_METADATA_VALUE_UNIT',
    ),
    timeUnit: optionalText(
      'FLOWBLIND_METADATA_TIME_UNIT',
    ),
    samplingKind: optionalText(
      'FLOWBLIND_METADATA_SAMPLING_KIND',
    ),
    selectedTime: optionalNumber(
      'FLOWBLIND_METADATA_SELECTED_TIME',
    ),
    exposureDuration: optionalNumber(
      'FLOWBLIND_METADATA_EXPOSURE_DURATION',
    ),
    exposureOperator: optionalText(
      'FLOWBLIND_METADATA_EXPOSURE_OPERATOR',
    ),
    timestampAnchor: optionalText(
      'FLOWBLIND_METADATA_TIMESTAMP_ANCHOR',
    ),
    cycleStartTime: optionalNumber(
      'FLOWBLIND_METADATA_CYCLE_START_TIME',
    ),
    cycleEndTime: optionalNumber(
      'FLOWBLIND_METADATA_CYCLE_END_TIME',
    ),
    cyclePeriod: optionalNumber(
      'FLOWBLIND_METADATA_CYCLE_PERIOD',
    ),
    cyclePhaseOrigin: optionalNumber(
      'FLOWBLIND_METADATA_CYCLE_PHASE_ORIGIN',
    ),
    provenance: optionalText(
      'FLOWBLIND_METADATA_PROVENANCE',
    ),
    license: optionalText(
      'FLOWBLIND_METADATA_LICENSE',
    ),
  })
  return Object.keys(metadata).length === 0
    ? common
    : { ...common, metadata }
}

export function throwIfAborted(signal) {
  signal?.throwIfAborted()
}

export async function privateActivation(signal) {
  throwIfAborted(signal)
  const path =
    process.env
      .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_PATH
  const digest =
    process.env
      .FLOWBLIND_PRIVATE_ACTIVATION_MANIFEST_SHA256
  if (absent(path) || absent(digest)) {
    return undefined
  }
  const requested = resolve(path)
  const [runtimeRoot, canonical, metadata] =
    await Promise.all([
      realpath(import.meta.dirname),
      realpath(requested),
      lstat(requested, { bigint: true }),
    ])
  throwIfAborted(signal)
  const insideRuntime = relative(
    runtimeRoot,
    canonical,
  )
  if (
    metadata.isSymbolicLink() ||
    !metadata.isFile() ||
    metadata.nlink !== 1n ||
    metadata.size <= 0n ||
    metadata.size > 64n * 1024n ||
    insideRuntime.length === 0 ||
    (
      insideRuntime !== '..' &&
      !insideRuntime.startsWith(`..${sep}`) &&
      !isAbsolute(insideRuntime)
    )
  ) {
    throw new Error(
      'Private activation must be supplied as one bounded host-owned file outside the package runtime.',
    )
  }
  const manifestBytes = await readFile(
    canonical,
    signal === undefined ? {} : { signal },
  )
  throwIfAborted(signal)
  const after = await lstat(canonical, {
    bigint: true,
  })
  if (
    after.dev !== metadata.dev ||
    after.ino !== metadata.ino ||
    after.size !== metadata.size ||
    after.mtimeNs !== metadata.mtimeNs
  ) {
    throw new Error(
      'Private activation changed while it was being read.',
    )
  }
  return {
    digest,
    manifestBytes,
  }
}

export function actionContext(_action, signal) {
  return {
    inputRoot:
      process.env.FLOWBLIND_INPUT_ROOT ??
      '/mnt/input',
    outputRoot:
      process.env.FLOWBLIND_OUTPUT_ROOT ??
      '/output',
    signal,
  }
}

export function failure(
  code,
  detail,
  status = 'authority-unavailable',
  reasonCodes = [code],
) {
  return {
    schemaVersion: 2,
    routerVersion: '2.0.0',
    status,
    containsResults: false,
    reasonCodes,
    guidance: detail,
  }
}

function ownValue(value, key) {
  if (
    value === null ||
    typeof value !== 'object' ||
    Array.isArray(value)
  ) {
    return undefined
  }
  const descriptor =
    Object.getOwnPropertyDescriptor(value, key)
  return descriptor !== undefined &&
    'value' in descriptor
    ? descriptor.value
    : undefined
}

function artifactIdentity(value) {
  return (
    typeof ownValue(value, 'reference') === 'string' &&
    Number.isSafeInteger(
      ownValue(value, 'byteLength'),
    ) &&
    ownValue(value, 'byteLength') > 0 &&
    typeof ownValue(value, 'mediaType') === 'string' &&
    /^[a-f0-9]{64}$/u.test(
      ownValue(value, 'sha256') ?? '',
    )
  )
}

function committedActionResult(
  action,
  result,
) {
  const expected =
    action === 'prepare-study'
      ? {
          status:
            'prepared-awaiting-confirmation',
          containsResults: false,
          phase: 'prepare',
          pointOfNoReturn:
            'exclusive-preparation-commit-marker',
        }
      : action === 'run-and-verify-study'
        ? {
            status: 'report-complete',
            containsResults: true,
            phase: 'run',
            pointOfNoReturn:
              'exclusive-report-commit-marker',
          }
        : null
  if (expected === null) return false
  const publication = ownValue(
    result,
    'adapterPublication',
  )
  const receipt = ownValue(publication, 'receipt')
  const artifacts = ownValue(receipt, 'artifacts')
  const containsResults = ownValue(
    result,
    'containsResults',
  )
  return (
    ownValue(result, 'status') === expected.status &&
    (
      action === 'prepare-study'
        ? containsResults === false
        : typeof containsResults === 'boolean'
    ) &&
    ownValue(publication, 'state') === 'committed' &&
    ownValue(publication, 'owner') === 'adapter' &&
    ownValue(receipt, 'status') === 'committed' &&
    ownValue(receipt, 'phase') === expected.phase &&
    ownValue(receipt, 'pointOfNoReturn') ===
      expected.pointOfNoReturn &&
    ownValue(
      receipt,
      'distributedExactlyOnceClaim',
    ) === false &&
    artifactIdentity(ownValue(receipt, 'marker')) &&
    Array.isArray(artifacts) &&
    artifacts.length > 0 &&
    artifacts.every(artifactIdentity)
  )
}

export function launcherResultExitCode(
  action,
  result,
) {
  if (committedActionResult(action, result)) return 0
  const status = ownValue(result, 'status')
  const reasonCodes = ownValue(result, 'reasonCodes')
  if (status === 'prior-outcome-unknown') return 3
  if (
    Array.isArray(reasonCodes) &&
    (
      reasonCodes.includes('operation-cancelled') ||
      reasonCodes.includes(
        'run-confirmation-cancelled',
      )
    )
  ) {
    return 2
  }
  return 1
}

export function launcherFailure(
  error,
  signal,
  operationCompleted = false,
) {
  if (operationCompleted) {
    return failure(
      'response-serialization-failed-after-operation',
      'The operation completed but its response could not be serialized; reconcile the deterministic output before retrying.',
      'prior-outcome-unknown',
    )
  }
  if (
    error !== null &&
    typeof error === 'object' &&
    error.name ===
      'RetainedRunPriorOutcomeUnknownError'
  ) {
    return failure(
      'retained-run-prior-outcome-unknown',
      'A retained run has unresolved publication state; reconcile it before retrying.',
      'prior-outcome-unknown',
      Array.isArray(error.reasonCodes)
        ? error.reasonCodes
        : [
            'retained-run-prior-outcome-unknown',
          ],
    )
  }
  if (
    error !== null &&
    typeof error === 'object' &&
    error.code === 'attachment-invalid'
  ) {
    return failure(
      'attachment-contract-invalid',
      'The selected attachment set failed bounded immutable verification.',
      'attachment-contract-invalid',
    )
  }
  if (
    error !== null &&
    typeof error === 'object' &&
    error.code === 'output-conflict'
  ) {
    return failure(
      'output-publication-reconciliation-required',
      'The deterministic output path conflicts with existing state and must be reconciled before retry.',
      'prior-outcome-unknown',
    )
  }
  if (signal?.aborted === true) {
    return failure(
      'operation-cancelled',
      'The FlowBlind operation was cancelled.',
      'execution-unavailable',
    )
  }
  return failure(
    'package-attestation-failed',
    'The portable FlowBlind v2 package could not verify its exact package identity.',
  )
}

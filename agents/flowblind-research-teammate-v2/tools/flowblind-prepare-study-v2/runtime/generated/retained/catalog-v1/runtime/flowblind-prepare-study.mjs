import { pathToFileURL } from 'node:url'
import {
  verifyFlowBlindCatalogPackage,
} from './flowblind-research-teammate-verification-v1.mjs'

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

function optionalValue(present, value) {
  return present === ABSENT ? null : decodeHandlebars(value)
}

function optionalProperties(
  decisionQuestion,
  nextEvidenceIntent,
) {
  return {
    ...(decisionQuestion === null
      ? {}
      : { decisionQuestion }),
    ...(nextEvidenceIntent === null
      ? {}
      : { nextEvidenceIntent }),
  }
}

function optionalEnvironmentText(name, property) {
  const value = process.env[name]
  if (isAbsentEnvironmentValue(value)) return {}
  return { [property]: decodeHandlebars(value) }
}

function optionalEnvironmentNumber(name, property) {
  const value = process.env[name]
  if (isAbsentEnvironmentValue(value)) return {}
  const decoded = decodeHandlebars(value)
  const numeric = Number(decoded)
  return {
    [property]: Number.isFinite(numeric)
      ? numeric
      : decoded,
  }
}

function isAbsentEnvironmentValue(value) {
  if (value === undefined) return true
  const normalized = value.trim()
  return (
    normalized.length === 0 ||
    /^(?:undefined|null)$/iu.test(normalized) ||
    /^\{\{[A-Za-z0-9_]+\}\}$/u.test(normalized)
  )
}

const abort = new AbortController()
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => abort.abort())
}

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
  ? optionalValue(
      decisionPresent,
      argumentDecisionQuestion,
    )
  : optionalValue(
      process.env.FLOWBLIND_DECISION_QUESTION ? '1' : ABSENT,
      process.env.FLOWBLIND_DECISION_QUESTION ?? '',
    )
const nextEvidenceIntent = argumentsProvided
  ? optionalValue(nextPresent, argumentNextEvidenceIntent)
  : optionalValue(
      process.env.FLOWBLIND_NEXT_EVIDENCE_INTENT
        ? '1'
        : ABSENT,
      process.env.FLOWBLIND_NEXT_EVIDENCE_INTENT ?? '',
    )

try {
  if (
    process.env.FLOWBLIND_TOOL_ROLE !== undefined &&
    process.env.FLOWBLIND_TOOL_ROLE !== 'prepare-study'
  ) {
    throw Object.assign(
      new Error(
        'The preparation facade is not running in the attested preparation tool role.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
  const verified = await verifyFlowBlindCatalogPackage()
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  if (
    runtime.catalogResearchRuntimeVersion !== '1.0.0' ||
    typeof runtime.callCatalogResearchAction !== 'function' ||
    typeof runtime.serializeCatalogResearchValue !== 'function'
  ) {
    throw Object.assign(
      new Error(
        'The attested catalog runtime does not expose the reviewed preparation entry points.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
  const result = await runtime.callCatalogResearchAction(
    'prepare-study',
    {
      researchGoal: decodeHandlebars(researchGoal ?? ''),
      ...optionalProperties(
        decisionQuestion,
        nextEvidenceIntent,
      ),
      quantity: decodeHandlebars(
        process.env.FLOWBLIND_QUANTITY ?? '',
      ),
      coordinateUnit: decodeHandlebars(
        process.env.FLOWBLIND_COORDINATE_UNIT ?? '',
      ),
      valueUnit: decodeHandlebars(
        process.env.FLOWBLIND_VALUE_UNIT ?? '',
      ),
      provenance: decodeHandlebars(
        process.env.FLOWBLIND_PROVENANCE ?? '',
      ),
      license: decodeHandlebars(
        process.env.FLOWBLIND_LICENSE ?? '',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_REFERENCE_MEANING',
        'referenceMeaning',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_CANDIDATE_MEANING',
        'candidateMeaning',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_VECTOR_MEANING',
        'vectorMeaning',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_VECTOR_SOURCE_KIND',
        'vectorSourceKind',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_TIME_UNIT',
        'timeUnit',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_SAMPLING_KIND',
        'samplingKind',
      ),
      ...optionalEnvironmentNumber(
        'FLOWBLIND_SELECTED_TIME',
        'selectedTime',
      ),
      ...optionalEnvironmentNumber(
        'FLOWBLIND_EXPOSURE_DURATION',
        'exposureDuration',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_EXPOSURE_OPERATOR',
        'exposureOperator',
      ),
      ...optionalEnvironmentText(
        'FLOWBLIND_TIMESTAMP_ANCHOR',
        'timestampAnchor',
      ),
      ...optionalEnvironmentNumber(
        'FLOWBLIND_CYCLE_START_TIME',
        'cycleStartTime',
      ),
      ...optionalEnvironmentNumber(
        'FLOWBLIND_CYCLE_END_TIME',
        'cycleEndTime',
      ),
      ...optionalEnvironmentNumber(
        'FLOWBLIND_CYCLE_PERIOD',
        'cyclePeriod',
      ),
      ...optionalEnvironmentNumber(
        'FLOWBLIND_CYCLE_PHASE_ORIGIN',
        'cyclePhaseOrigin',
      ),
    },
    {
      inputRoot:
        process.env.FLOWBLIND_INPUT_ROOT ?? '/mnt/input',
      outputRoot:
        process.env.FLOWBLIND_OUTPUT_ROOT ?? '/output',
      signal: abort.signal,
    },
    verified.packageVerification,
  )
  process.stdout.write(
    runtime.serializeCatalogResearchValue(result),
  )
} catch {
  process.stdout.write(
    `${JSON.stringify({
      schemaVersion: 1,
      teammateVersion: '1.0.0',
      status: 'refused',
      error: {
        code: 'package-attestation-failed',
        classification: 'package-attestation',
        detail:
          'The portable FlowBlind package could not verify its executable and policy identity.',
      },
      containsResults: false,
    }, null, 2)}\n`,
  )
}

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
    process.env.FLOWBLIND_TOOL_ROLE !==
      'run-and-verify-study'
  ) {
    throw Object.assign(
      new Error(
        'The execution facade is not running in the confirmed execution tool role.',
      ),
      { code: 'confirmation-required' },
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
        'The attested catalog runtime does not expose the reviewed execution entry points.',
      ),
      { code: 'package-attestation-failed' },
    )
  }
  const result = await runtime.callCatalogResearchAction(
    'run-and-verify-study',
    {
      researchGoal: decodeHandlebars(researchGoal ?? ''),
      ...optionalProperties(
        decisionQuestion,
        nextEvidenceIntent,
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
} catch (error) {
  const code =
    error &&
    typeof error === 'object' &&
    'code' in error &&
    error.code === 'confirmation-required'
      ? 'confirmation-required'
      : 'package-attestation-failed'
  process.stdout.write(
    `${JSON.stringify({
      schemaVersion: 1,
      teammateVersion: '1.0.0',
      status: 'refused',
      error: {
        code,
        classification:
          code === 'confirmation-required'
            ? 'confirmation'
            : 'package-attestation',
        detail:
          code === 'confirmation-required'
            ? 'The run tool requires an enabled host confirmation policy.'
            : 'The portable FlowBlind package could not verify its executable and policy identity.',
      },
      containsResults: false,
    }, null, 2)}\n`,
  )
}

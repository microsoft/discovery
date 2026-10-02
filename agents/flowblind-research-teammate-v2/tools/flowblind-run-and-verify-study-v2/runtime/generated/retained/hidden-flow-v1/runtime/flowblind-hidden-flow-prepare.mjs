import { pathToFileURL } from 'node:url'
import {
  verifyFlowBlindHiddenFlowPackage,
} from './flowblind-hidden-flow-capability-verification-v1.mjs'

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

const abort = new AbortController()
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => abort.abort())
}

const [
  argumentGoal,
  detailsPresent = ABSENT,
  argumentDetails = '',
] = process.argv.slice(2)
const argumentsProvided = process.argv.length > 2
const goal = argumentsProvided
  ? argumentGoal ?? ''
  : process.env.FLOWBLIND_RESEARCH_GOAL ?? ''
const details = argumentsProvided
  ? detailsPresent === ABSENT
    ? null
    : decodeHandlebars(argumentDetails)
  : Object.hasOwn(
        process.env,
        'FLOWBLIND_RESEARCH_DETAILS',
      )
    ? decodeHandlebars(
        process.env.FLOWBLIND_RESEARCH_DETAILS ?? '',
      )
    : null

try {
  if (
    process.env.FLOWBLIND_TOOL_ROLE !== 'prepare-study'
  ) {
    throw new Error(
      'The preparation facade is not running in the attested preparation role.',
    )
  }
  const verified =
    await verifyFlowBlindHiddenFlowPackage(
      abort.signal,
    )
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  if (
    runtime.catalogHiddenFlowRuntimeVersion !== '1.1.0' ||
    typeof runtime.callPackagedCatalogHiddenFlowAction !==
      'function' ||
    typeof runtime.serializeCatalogHiddenFlowValue !==
      'function'
  ) {
    throw new Error(
      'The attested hidden-flow runtime does not expose the reviewed preparation entry points.',
    )
  }
  const result =
    await runtime.callPackagedCatalogHiddenFlowAction(
      'prepare-study',
      {
        goal: decodeHandlebars(goal),
        details,
      },
      {
        inputRoot:
          process.env.FLOWBLIND_INPUT_ROOT ??
          '/mnt/input',
        outputRoot:
          process.env.FLOWBLIND_OUTPUT_ROOT ??
          '/output',
        signal: abort.signal,
      },
      verified.runtimeAuthority,
    )
  process.stdout.write(
    runtime.serializeCatalogHiddenFlowValue(result),
  )
} catch (error) {
  const cancelled =
    typeof error === 'object' &&
    error !== null &&
    error.code === 'operation-cancelled'
  process.stdout.write(
    `${JSON.stringify({
      schemaVersion: 1,
      capabilityVersion: '1.1.0',
      status: 'refused',
      containsResults: false,
      error: {
        code: cancelled
          ? 'operation-cancelled'
          : 'package-attestation-failed',
        classification: cancelled
          ? 'cancellation'
          : 'package-attestation',
        detail: cancelled
          ? 'The portable hidden-flow preparation was cancelled during bounded package verification.'
          : 'The portable hidden-flow package could not verify its executable, review policy, and runtime identity.',
      },
    }, null, 2)}\n`,
  )
}

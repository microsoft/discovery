import { pathToFileURL } from 'node:url'
import {
  actionContext,
  launcherFailure,
  launcherResultExitCode,
  privateActivation,
  scientistInput,
  throwIfAborted,
} from './launcher-support.mjs'
import {
  verifyFlowBlindCatalogResearchV2Package,
} from './flowblind-research-teammate-verification-v2.mjs'

const abort = new AbortController()
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => abort.abort())
}

let operationCompleted = false
try {
  if (
    process.env.FLOWBLIND_TOOL_ROLE !==
      'prepare-study'
  ) {
    throw new Error(
      'The v2 preparation facade is not running in the attested preparation role.',
    )
  }
  const verified =
    await verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'prepare-study',
      signal: abort.signal,
    })
  throwIfAborted(abort.signal)
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  throwIfAborted(abort.signal)
  const activation = await privateActivation(
    abort.signal,
  )
  throwIfAborted(abort.signal)
  const result =
    await runtime.callCatalogResearchV2Action(
      'prepare-study',
      scientistInput('prepare-study'),
      {
        ...actionContext(
          'prepare-study',
          abort.signal,
        ),
        ...(activation === undefined
          ? {}
          : { privateActivation: activation }),
      },
      verified.packageVerification,
    )
  operationCompleted = true
  process.stdout.write(
    runtime.serializeCatalogResearchV2Value(
      result,
    ),
  )
  process.exitCode = launcherResultExitCode(
    'prepare-study',
    result,
  )
} catch (error) {
  const failure = launcherFailure(
    error,
    abort.signal,
    operationCompleted,
  )
  process.stdout.write(
    `${JSON.stringify(failure, null, 2)}\n`,
  )
  process.exitCode = launcherResultExitCode(
    'prepare-study',
    failure,
  )
}

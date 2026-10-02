import { pathToFileURL } from 'node:url'
import {
  privateActivation,
  throwIfAborted,
} from './launcher-support.mjs'
import {
  verifyFlowBlindCatalogResearchV2Package,
} from './flowblind-research-teammate-verification-v2.mjs'

const abort = new AbortController()
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => abort.abort())
}

try {
  const verified =
    await verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'private-preview',
      signal: abort.signal,
    })
  throwIfAborted(abort.signal)
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  throwIfAborted(abort.signal)
  const result =
    await runtime
      .previewCatalogResearchV2PrivateCapability(
        {
          outputRoot:
            process.env.FLOWBLIND_OUTPUT_ROOT ??
            '/output',
          privateActivation:
            await privateActivation(
              abort.signal,
            ),
          signal: abort.signal,
        },
        verified.packageVerification,
      )
  throwIfAborted(abort.signal)
  process.stdout.write(
    runtime.serializeCatalogResearchV2Value(
      result,
    ),
  )
} catch {
  process.exitCode = 2
}

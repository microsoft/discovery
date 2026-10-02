import { pathToFileURL } from 'node:url'
import {
  privateActivation,
  throwIfAborted,
} from './launcher-support.mjs'
import {
  verifyFlowBlindCatalogResearchV2Package,
} from './flowblind-research-teammate-verification-v2.mjs'

const [uri = ''] = process.argv.slice(2)
const abort = new AbortController()
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, () => abort.abort())
}

try {
  const verified =
    await verifyFlowBlindCatalogResearchV2Package({
      toolRole: 'resource',
      signal: abort.signal,
    })
  throwIfAborted(abort.signal)
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  throwIfAborted(abort.signal)
  const bytes =
    await runtime.readCatalogResearchV2Resource(
      uri,
      process.env.FLOWBLIND_OUTPUT_ROOT ??
        '/output',
      verified.packageVerification,
      await privateActivation(abort.signal),
      abort.signal,
    )
  throwIfAborted(abort.signal)
  process.stdout.write(Buffer.from(bytes))
} catch {
  process.exitCode = 2
}

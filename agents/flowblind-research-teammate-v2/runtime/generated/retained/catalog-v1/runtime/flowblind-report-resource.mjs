import { pathToFileURL } from 'node:url'
import {
  verifyFlowBlindCatalogPackage,
} from './flowblind-research-teammate-verification-v1.mjs'

const [uri = ''] = process.argv.slice(2)

try {
  if (
    process.env.FLOWBLIND_TOOL_ROLE !== undefined &&
    process.env.FLOWBLIND_TOOL_ROLE !==
      'run-and-verify-study'
  ) {
    throw new Error(
      'The report resource facade is not available in the preparation tool role.',
    )
  }
  const verified = await verifyFlowBlindCatalogPackage()
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  if (
    runtime.catalogResearchRuntimeVersion !== '1.0.0' ||
    typeof runtime.readCatalogResearchVisualResource !==
      'function'
  ) {
    throw new Error(
      'The attested catalog runtime does not expose the reviewed resource entry point.',
    )
  }
  const html = await runtime.readCatalogResearchVisualResource(
    uri,
    process.env.FLOWBLIND_OUTPUT_ROOT ?? '/output',
    verified.packageVerification,
  )
  process.stdout.write(html)
} catch {
  process.stderr.write(
    'The requested FlowBlind visual resource could not be revalidated.\n',
  )
  process.exitCode = 1
}

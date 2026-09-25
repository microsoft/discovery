import { pathToFileURL } from 'node:url'
import {
  verifyFlowBlindHiddenFlowPackage,
} from './flowblind-hidden-flow-capability-verification-v1.mjs'

try {
  const verified =
    await verifyFlowBlindHiddenFlowPackage()
  const runtime = await import(
    `${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`
  )
  if (
    typeof runtime.catalogHiddenFlowDeclarationPreview !==
      'function' ||
    typeof runtime.serializeCatalogHiddenFlowValue !==
      'function'
  ) {
    throw new Error(
      'The attested hidden-flow runtime does not expose declaration preview.',
    )
  }
  const declaration =
    await runtime.catalogHiddenFlowDeclarationPreview(
      verified.runtimeAuthority,
    )
  process.stdout.write(
    runtime.serializeCatalogHiddenFlowValue(declaration),
  )
} catch {
  process.stdout.write(
    `${JSON.stringify({
      schemaVersion: 1,
      capabilityVersion: '1.1.0',
      status: 'refused',
      containsResults: false,
      error: {
        code: 'package-attestation-failed',
        classification: 'package-attestation',
        detail:
          'The portable hidden-flow declaration could not verify its package identity.',
      },
    }, null, 2)}\n`,
  )
  process.exitCode = 2
}

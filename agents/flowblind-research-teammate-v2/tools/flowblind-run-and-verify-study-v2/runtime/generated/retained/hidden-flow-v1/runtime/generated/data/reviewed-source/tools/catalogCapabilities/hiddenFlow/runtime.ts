import {
  createAttestedGenericHiddenFlowReviewAuthority,
} from './authority.ts'
import {
  prepareCatalogHiddenFlow,
  runCatalogHiddenFlow,
} from './capability.ts'
import type {
  CatalogHiddenFlowPrepareCall,
  CatalogHiddenFlowRunCall,
} from './capability.ts'
import {
  loadSingleCatalogHiddenFlowAttachment,
  publishCatalogHiddenFlowArtifact,
} from './packageIo.ts'
import {
  assertCatalogHiddenFlowActionResponseSemanticContract,
  assertCatalogHiddenFlowReportSetSemanticContract,
  publishCatalogHiddenFlowReportSet,
} from './packagePublication.ts'
import type {
  CatalogHiddenFlowPackagedRunResponse,
} from './packagePublication.ts'
import type {
  CatalogHiddenFlowVerifiedRun,
} from './execution.ts'
import {
  PinnedPythonProcessHiddenFlowSolverAdapter,
} from './pinnedSolver.ts'
import type {
  CatalogHiddenFlowPinnedRuntimeContext,
} from './pinnedSolver.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
  CatalogHiddenFlowError,
  catalogHiddenFlowRefusal,
  stableJson,
} from './profile.ts'
import type {
  CatalogHiddenFlowPackageEvidence,
  CatalogHiddenFlowRefusal,
} from './profile.ts'

const verificationModuleReference = [
  '..',
  'flowblind-hidden-flow-capability-verification-v1.mjs',
].join('/')

export {
  assertCatalogHiddenFlowActionResponseSemanticContract,
  assertCatalogHiddenFlowReportSetSemanticContract,
}

export interface CatalogHiddenFlowPackageRuntimeAuthority {
  readonly packageVerification:
    CatalogHiddenFlowPackageEvidence
  readonly pinnedRuntime:
    CatalogHiddenFlowPinnedRuntimeContext
}

interface VerificationModule {
  readonly flowBlindHiddenFlowPackageRuntimeAuthority?: (
    value: unknown,
  ) => CatalogHiddenFlowPackageRuntimeAuthority | null
}

async function packageAuthority(
  value: unknown,
): Promise<CatalogHiddenFlowPackageRuntimeAuthority | null> {
  if (value === null || value === undefined) return null
  try {
    const authority = await import(
      new URL(
        verificationModuleReference,
        import.meta.url,
      ).href
    ) as VerificationModule
    return typeof authority
      .flowBlindHiddenFlowPackageRuntimeAuthority ===
      'function'
      ? authority.flowBlindHiddenFlowPackageRuntimeAuthority(
          value,
        )
      : null
  } catch {
    return null
  }
}

function attestationRefusal(): CatalogHiddenFlowRefusal {
  return catalogHiddenFlowRefusal(
    new CatalogHiddenFlowError(
      'package-attestation-failed',
      'package-attestation',
      'Direct or unverified hidden-flow capability invocation is not permitted.',
    ),
  )
}

function ioRefusal(error: unknown): CatalogHiddenFlowRefusal {
  return catalogHiddenFlowRefusal(
    error instanceof CatalogHiddenFlowError
      ? error
      : new CatalogHiddenFlowError(
          'output-publication-conflict',
          'publication',
          'The packaged hidden-flow action failed before publishing complete verified artifacts.',
          { cause: error },
        ),
  )
}

function verifiedRun(
  bytes: Uint8Array,
): CatalogHiddenFlowVerifiedRun {
  return JSON.parse(
    Buffer.from(bytes).toString('utf8'),
  ) as CatalogHiddenFlowVerifiedRun
}

export const catalogHiddenFlowRuntimeVersion =
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
export const catalogHiddenFlowPackageVersion =
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION
export const catalogHiddenFlowSupportedActions =
  FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS

export function serializeCatalogHiddenFlowValue(
  value: unknown,
): string {
  return stableJson(value)
}

export async function catalogHiddenFlowDeclarationPreview(
  packageVerification?: unknown,
): Promise<
  | {
      readonly declaration:
        typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION
      readonly package:
        CatalogHiddenFlowPackageEvidence
    }
  | CatalogHiddenFlowRefusal
> {
  const authority = await packageAuthority(
    packageVerification,
  )
  if (authority === null) return attestationRefusal()
  return {
    declaration:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION,
    package: authority.packageVerification,
  }
}

export async function callCatalogHiddenFlowAction(
  action: string,
  input: unknown,
  context:
    | {
        readonly selectedProblemBytes: Uint8Array
        readonly preparationBundleBytes?: never
        readonly signal?: AbortSignal
      }
    | {
        readonly selectedProblemBytes?: never
        readonly preparationBundleBytes: Uint8Array
        readonly signal?: AbortSignal
      },
  packageVerification?: unknown,
): Promise<
  CatalogHiddenFlowPrepareCall | CatalogHiddenFlowRunCall
> {
  const packageRuntime = await packageAuthority(
    packageVerification,
  )
  if (packageRuntime === null) {
    const response = attestationRefusal()
    assertCatalogHiddenFlowActionResponseSemanticContract(
      response,
    )
    return {
      response,
      bundle: null,
    }
  }
  const reviewAuthority =
    createAttestedGenericHiddenFlowReviewAuthority(
      packageRuntime.packageVerification,
    )
  if (
    action ===
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION &&
    context.selectedProblemBytes !== undefined
  ) {
    const prepared = prepareCatalogHiddenFlow(
      input,
      {
        selectedProblemBytes:
          context.selectedProblemBytes,
      },
      {
        reviewAuthority,
        signal: context.signal,
      },
    )
    assertCatalogHiddenFlowActionResponseSemanticContract(
      prepared.response,
    )
    return prepared
  }
  if (
    action ===
      FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION &&
    context.preparationBundleBytes !== undefined
  ) {
    const run = await runCatalogHiddenFlow(
      input,
      {
        preparationBundleBytes:
          context.preparationBundleBytes,
      },
      {
        reviewAuthority,
        signal: context.signal,
        solver:
          new PinnedPythonProcessHiddenFlowSolverAdapter(
            packageRuntime.pinnedRuntime,
            context.signal,
          ),
      },
    )
    assertCatalogHiddenFlowActionResponseSemanticContract(
      run.response,
      'artifacts' in run && run.artifacts !== null
          ? {
              verifiedRun: verifiedRun(
                run.artifacts.json.bytes,
              ),
            }
          : {},
    )
    return run
  }
  const refusal = catalogHiddenFlowRefusal(
    new CatalogHiddenFlowError(
      'input-invalid',
      'input-validation',
      'Only the reviewed prepare-study and run-and-verify-study actions with matching host-selected attachment contexts are supported.',
    ),
  )
  assertCatalogHiddenFlowActionResponseSemanticContract(
    refusal,
  )
  return {
    response: refusal,
    bundle: null,
  }
}

export async function callPackagedCatalogHiddenFlowAction(
  action: string,
  input: unknown,
  context: {
    readonly inputRoot: string
    readonly outputRoot: string
    readonly signal?: AbortSignal
  },
  packageVerification?: unknown,
): Promise<
  | CatalogHiddenFlowPrepareCall['response']
  | CatalogHiddenFlowRunCall['response']
  | CatalogHiddenFlowPackagedRunResponse
> {
  try {
    if (
      action !==
        FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION &&
      action !==
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION
    ) {
      throw new CatalogHiddenFlowError(
        'input-invalid',
        'input-validation',
        'Only the reviewed prepare-study and run-and-verify-study actions are supported.',
      )
    }
    const selected =
      await loadSingleCatalogHiddenFlowAttachment(
        context.inputRoot,
        context.signal,
      )
    if (
      action ===
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION
    ) {
      const prepared = await callCatalogHiddenFlowAction(
        action,
        input,
        {
          selectedProblemBytes: selected.bytes,
          signal: context.signal,
        },
        packageVerification,
      )
      if (
        'bundle' in prepared &&
        prepared.bundle !== null
      ) {
        await publishCatalogHiddenFlowArtifact(
          context.outputRoot,
          prepared.bundle,
          context.signal,
        )
      }
      return prepared.response
    }
    const run = await callCatalogHiddenFlowAction(
      action,
      input,
      {
        preparationBundleBytes: selected.bytes,
        signal: context.signal,
      },
      packageVerification,
    )
    if ('artifacts' in run && run.artifacts !== null) {
      const published =
        await publishCatalogHiddenFlowReportSet(
        context.outputRoot,
        run,
        { signal: context.signal },
      )
      assertCatalogHiddenFlowReportSetSemanticContract(
      published.response,
      published.verificationRecord,
      published.response.artifacts.verification,
      verifiedRun(run.artifacts.json.bytes),
      )
      return published.response
    }
    return run.response
  } catch (error) {
    const refusal = ioRefusal(error)
    assertCatalogHiddenFlowActionResponseSemanticContract(
      refusal,
    )
    return refusal
  }
}

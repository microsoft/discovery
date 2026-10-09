import type { HiddenFlowProblem } from '../../../src/domain/hiddenFlowModel.ts'
import type {
  CatalogHiddenFlowPreflight,
} from './engine.ts'
import type {
  CatalogHiddenFlowReviewAuthority,
  ReviewedCatalogHiddenFlowProblem,
} from './authority.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARATION_SCHEMA_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
  CatalogHiddenFlowError,
  artifact,
  artifactIdentity,
  sha256Bytes,
  stableJson,
  throwIfCatalogHiddenFlowAborted,
  utf8Bytes,
  validateCatalogHiddenFlowHumanContext,
} from './profile.ts'
import type {
  CatalogHiddenFlowArtifact,
  CatalogHiddenFlowArtifactIdentity,
  CatalogHiddenFlowHumanContext,
  CatalogHiddenFlowPackageEvidence,
  CatalogHiddenFlowReviewAttestation,
} from './profile.ts'

type UnknownRecord = Record<string, unknown>

export interface CatalogHiddenFlowPreparationBundle {
  readonly $schema:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARATION_SCHEMA_ID
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly recordType:
    'flowblind-catalog-hidden-flow-preparation-v1'
  readonly id: string
  readonly status: 'prepared-awaiting-confirmation'
  readonly containsResults: false
  readonly association: {
    readonly canonicalization: 'stable-json-v1'
    readonly sha256: string
  }
  readonly humanContext: CatalogHiddenFlowHumanContext
  readonly capability: {
    readonly capabilityId:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID
    readonly capabilityVersion:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
    readonly methodFamily:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY
    readonly problemSchemaVersion: 1
  }
  readonly problem: {
    readonly canonicalization: 'stable-json-v1'
    readonly identity: CatalogHiddenFlowArtifactIdentity
    readonly document: HiddenFlowProblem
  }
  readonly review: CatalogHiddenFlowReviewAttestation
  readonly preflight: CatalogHiddenFlowPreflight
  readonly resourceLimits: {
    readonly hiddenFlow:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS
    readonly maximumPreparationBundleBytes:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES
    readonly maximumVerifiedRunArtifactBytes:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES
    readonly maximumMarkdownArtifactBytes:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES
  }
  readonly dataHandling: {
    readonly scientistInput:
      'ordinary-language-goal-and-details-only'
    readonly selection:
      'one-host-selected-canonical-problem-json'
    readonly preparation:
      'local-read-only-validation-and-result-free-preflight'
    readonly execution:
      'host-confirmed-run-without-an-approval-input-field'
    readonly retention:
      'self-contained-content-addressed-bundle-with-no-hidden-state'
  }
  readonly runtime: typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME
  readonly software: CatalogHiddenFlowPackageEvidence
}

export interface CatalogHiddenFlowPreparedResponse {
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly capabilityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly status: 'prepared-awaiting-confirmation'
  readonly containsResults: false
  readonly humanContext: CatalogHiddenFlowHumanContext
  readonly problem: {
    readonly id: string
    readonly title: string
    readonly targetType: HiddenFlowProblem['target']['type']
    readonly targetTitle: string
    readonly observationRows: number
    readonly retainedBasisFunctions: number
    readonly solverRequestCount: number
  }
  readonly review: {
    readonly authorityVersion:
      CatalogHiddenFlowReviewAttestation['authorityVersion']
    readonly reviewScope:
      CatalogHiddenFlowReviewAttestation['reviewScope']
    readonly claimBoundary:
      CatalogHiddenFlowReviewAttestation['claimBoundary']
  }
  readonly preparationBundle: CatalogHiddenFlowArtifactIdentity
}

export interface PreparedCatalogHiddenFlow {
  readonly response: CatalogHiddenFlowPreparedResponse
  readonly bundle: CatalogHiddenFlowArtifact
}

export interface ValidatedCatalogHiddenFlowBundle {
  readonly bundle: CatalogHiddenFlowPreparationBundle
  readonly bundleArtifact: CatalogHiddenFlowArtifact
}

function decodeJsonBytes(
  bytes: Uint8Array,
  maximumBytes: number,
  label: string,
  errorCode:
    | 'problem-bytes-invalid'
    | 'preparation-bundle-invalid' =
    'problem-bytes-invalid',
): { readonly text: string; readonly value: unknown } {
  if (bytes.byteLength === 0 || bytes.byteLength > maximumBytes) {
    throw new CatalogHiddenFlowError(
      errorCode,
      errorCode === 'problem-bytes-invalid'
        ? 'input-validation'
        : 'verification',
      `${label} must be a nonempty bounded UTF-8 JSON document.`,
    )
  }
  try {
    const text = new TextDecoder('utf-8', {
      fatal: true,
    }).decode(bytes)
    return {
      text,
      value: JSON.parse(text) as unknown,
    }
  } catch (error) {
    throw new CatalogHiddenFlowError(
      errorCode,
      errorCode === 'problem-bytes-invalid'
        ? 'input-validation'
        : 'verification',
      `${label} must be valid UTF-8 JSON.`,
      { cause: error },
    )
  }
}

function preparationBindings(
  humanContext: CatalogHiddenFlowHumanContext,
  problem: ReviewedCatalogHiddenFlowProblem,
) {
  return {
    humanContext,
    capability: {
      capabilityId:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
      capabilityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
      methodFamily:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
      problemSchemaVersion: 1 as const,
    },
    problem: {
      canonicalization: 'stable-json-v1' as const,
      identity: problem.identity,
      document: problem.problem,
    },
    review: problem.review,
    preflight: problem.preflight,
    resourceLimits: {
      hiddenFlow:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
      maximumPreparationBundleBytes:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES,
      maximumVerifiedRunArtifactBytes:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES,
      maximumMarkdownArtifactBytes:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES,
    },
    dataHandling: {
      scientistInput:
        'ordinary-language-goal-and-details-only' as const,
      selection:
        'one-host-selected-canonical-problem-json' as const,
      preparation:
        'local-read-only-validation-and-result-free-preflight' as const,
      execution:
        'host-confirmed-run-without-an-approval-input-field' as const,
      retention:
        'self-contained-content-addressed-bundle-with-no-hidden-state' as const,
    },
    runtime: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
    software: problem.software,
  } as const
}

function prepareOrThrow(
  humanContext: CatalogHiddenFlowHumanContext,
  selectedProblemBytes: Uint8Array,
  reviewAuthority: CatalogHiddenFlowReviewAuthority,
  signal?: AbortSignal,
): PreparedCatalogHiddenFlow {
  throwIfCatalogHiddenFlowAborted(signal)
  if (
    reviewAuthority.authorityVersion !==
    FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION
  ) {
    throw new CatalogHiddenFlowError(
      'review-attestation-invalid',
      'review',
      'The selected hidden-flow problem review authority is malformed.',
    )
  }
  const selected = reviewAuthority.reviewSelectedProblem(
    selectedProblemBytes,
    signal,
  )
  throwIfCatalogHiddenFlowAborted(signal)
  const bindings = preparationBindings(
    humanContext,
    selected,
  )
  const associationSha256 = sha256Bytes(
    utf8Bytes(stableJson(bindings)),
  )
  const bundle: CatalogHiddenFlowPreparationBundle = {
    $schema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARATION_SCHEMA_ID,
    schemaVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
    recordType:
      'flowblind-catalog-hidden-flow-preparation-v1',
    id:
      `flowblind-hidden-flow-preparation-${associationSha256.slice(0, 32)}`,
    status: 'prepared-awaiting-confirmation',
    containsResults: false,
    association: {
      canonicalization: 'stable-json-v1',
      sha256: associationSha256,
    },
    ...bindings,
  }
  const bundleBytes = utf8Bytes(stableJson(bundle))
  if (
    bundleBytes.byteLength >
    FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES
  ) {
    throw new CatalogHiddenFlowError(
      'problem-bytes-invalid',
      'input-validation',
      'The prepared hidden-flow bundle exceeds its bounded portable size.',
    )
  }
  const digest = sha256Bytes(bundleBytes)
  const bundleArtifact = artifact(
    `flowblind-catalog-hidden-flow-preparation-${digest}.json`,
    bundleBytes,
    'application/json',
  )
  return {
    response: {
      schemaVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
      capabilityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
      status: 'prepared-awaiting-confirmation',
      containsResults: false,
      humanContext,
      problem: {
        id: selected.problem.id,
        title: selected.problem.title,
        targetType: selected.problem.target.type,
        targetTitle: selected.problem.target.title,
        observationRows:
          selected.problem.observations.length,
        retainedBasisFunctions:
          selected.preflight.retainedBasisFunctions,
        solverRequestCount:
          selected.preflight.solverRequestCount,
      },
      review: {
        authorityVersion:
          selected.review.authorityVersion,
        reviewScope: selected.review.reviewScope,
        claimBoundary: selected.review.claimBoundary,
      },
      preparationBundle:
        artifactIdentity(bundleArtifact),
    },
    bundle: bundleArtifact,
  }
}

export function prepareCatalogHiddenFlowBundle(
  humanContext: CatalogHiddenFlowHumanContext,
  selectedProblemBytes: Uint8Array,
  reviewAuthority: CatalogHiddenFlowReviewAuthority,
  signal?: AbortSignal,
): PreparedCatalogHiddenFlow {
  return prepareOrThrow(
    humanContext,
    selectedProblemBytes,
    reviewAuthority,
    signal,
  )
}

function object(value: unknown): UnknownRecord | null {
  return typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value)
    ? (value as UnknownRecord)
    : null
}

export function validateCatalogHiddenFlowBundle(
  humanContext: CatalogHiddenFlowHumanContext,
  bundleBytes: Uint8Array,
  reviewAuthority: CatalogHiddenFlowReviewAuthority,
  signal?: AbortSignal,
): ValidatedCatalogHiddenFlowBundle {
  throwIfCatalogHiddenFlowAborted(signal)
  const decoded = decodeJsonBytes(
    bundleBytes,
    FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES,
    'The hidden-flow preparation bundle',
    'preparation-bundle-invalid',
  )
  const document = object(decoded.value)
  const bundledContext = object(document?.humanContext)
  const bundledProblem = object(document?.problem)
  if (
    document === null ||
    bundledContext === null ||
    bundledProblem === null ||
    bundledProblem.document === undefined
  ) {
    throw new CatalogHiddenFlowError(
      'preparation-bundle-invalid',
      'verification',
      'The selected preparation bundle is malformed or incomplete.',
    )
  }
  let rebuilt: PreparedCatalogHiddenFlow
  try {
    const storedContext =
      validateCatalogHiddenFlowHumanContext(bundledContext)
    rebuilt = prepareOrThrow(
      storedContext,
      utf8Bytes(stableJson(bundledProblem.document)),
      reviewAuthority,
      signal,
    )
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'preparation-bundle-invalid',
      'verification',
      'The selected preparation bundle cannot be reconstructed from its declared content.',
      { cause: error },
    )
  }
  const actual = Buffer.from(bundleBytes)
  if (!actual.equals(rebuilt.bundle.bytes)) {
    throw new CatalogHiddenFlowError(
      'preparation-bundle-invalid',
      'verification',
      'The selected preparation bundle is noncanonical, stale, or tampered.',
    )
  }
  if (
    stableJson(humanContext) !==
    stableJson(rebuilt.response.humanContext)
  ) {
    throw new CatalogHiddenFlowError(
      'human-context-mismatch',
      'verification',
      'The ordinary-language run context does not match the preparation bundle.',
    )
  }
  throwIfCatalogHiddenFlowAborted(signal)
  return {
    bundle:
      JSON.parse(decoded.text) as CatalogHiddenFlowPreparationBundle,
    bundleArtifact: rebuilt.bundle,
  }
}

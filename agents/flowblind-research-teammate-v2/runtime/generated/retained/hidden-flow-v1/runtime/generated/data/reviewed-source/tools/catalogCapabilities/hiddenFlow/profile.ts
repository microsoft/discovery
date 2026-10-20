import { createHash } from 'node:crypto'
import { stableJson as stableEvidenceJson } from '../../../src/application/evidenceReport.ts'
import { HIDDEN_FLOW_LIMITS } from '../../../src/domain/hiddenFlowModel.ts'
import {
  validateFlowBlindDisplayText,
  validateFlowBlindOptionalDisplayText,
} from '../../discovery/flowblindDisplayText.ts'

type UnknownRecord = Record<string, unknown>

function deepFreeze<T>(value: T): T {
  if (
    typeof value === 'object' &&
    value !== null &&
    !Object.isFrozen(value)
  ) {
    for (const nested of Object.values(value)) {
      deepFreeze(nested)
    }
    Object.freeze(value)
  }
  return value
}

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION = '1.1.0'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION =
  '1.0.0'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION = 1
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID =
  'finite-basis-hidden-flow-v1'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY =
  'finite-basis-observation-compatible-hidden-flow-v1'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION =
  'prepare-study'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION =
  'run-and-verify-study'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS = [
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
] as const
export type CatalogHiddenFlowAction =
  (typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS)[number]
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_ID =
  'flowblind-catalog-hidden-flow-generic-review-policy-v1'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION =
  '1.0.0'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION =
  'attested-generic-hidden-flow-problem-authority-v1'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE =
  'generic-problem-contract-parser-and-executable-preflight-only'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY =
  'finite-basis-declared-model-only-no-physical-truth-source-validity-or-clinical-inference'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES = [
  'point-component',
  'point-direction',
] as const
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES = [
  'point-component',
  'point-direction',
  'point-speed-envelope',
  'region-component',
  'point-strain-component',
] as const
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_INPUT_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-input-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARATION_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-preparation-bundle-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_VERIFIED_RUN_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-verified-run-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_EVIDENCE_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-evidence-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PROBLEM_ACCEPTANCE_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REPORT_VERIFICATION_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-report-verification-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-review-policy-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_ATTESTATION_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-review-attestation-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_EVIDENCE_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-package-evidence-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-declaration-v1.schema.json'
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_LOCK_SCHEMA_ID =
  'https://flowblind.local/schemas/flowblind-catalog-hidden-flow-package-lock-v1.schema.json'

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES =
  HIDDEN_FLOW_LIMITS.maximumDocumentBytes + 1024 * 1024
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES =
  128 * 1024 * 1024
export const FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES =
  HIDDEN_FLOW_LIMITS.maximumDocumentBytes

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS =
  deepFreeze({ ...HIDDEN_FLOW_LIMITS })

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PYTHON_PACKAGES =
  deepFreeze([
    {
      requirement: 'clarabel==0.11.1',
      sha256:
        'c8c41aaa6f3f8c0f3bd9d86c3e568dcaee079562c075bd2ec9fb3a80287380ef',
    },
    {
      requirement: 'cffi==2.1.1',
      sha256:
        'c1453022f490d2459a11819d83ad1d586e9ff65a12ac3e705ffebd46d3685dcf',
    },
    {
      requirement: 'numpy==2.2.6',
      sha256:
        'fd83c01228a688733f1ded5201c678f0c53ecc1006ffbc404db9f7a899ac6249',
    },
    {
      requirement: 'pycparser==3.0',
      sha256:
        'b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992',
    },
    {
      requirement: 'scipy==1.15.3',
      sha256:
        '271e3713e645149ea5ea3e97b57fdab61ce61333f97cfae392c28ba786f9bb49',
    },
  ] as const)

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME = deepFreeze({
  platform: 'linux/amd64',
  nodeImage:
    'node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94',
  pythonImage:
    'python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79',
  pythonRequirementsSha256:
    '1ffda1962375e2d2d77b794b7a930d55902869a2923e695ad333a3f8e0d7a4ed',
  pythonPackages:
    FLOWBLIND_CATALOG_HIDDEN_FLOW_PYTHON_PACKAGES,
  solverModule: 'tools.hidden_flow_solver',
  solverAdapter:
    'PinnedPythonProcessHiddenFlowSolverAdapter',
  solverIdentity: {
    adapter: 'flowblind-hidden-flow-direct-clarabel',
    adapterVersion: '1.0.0',
    pythonVersion: '3.12.14',
    clarabelVersion: '0.11.1',
    scipyVersion: '1.15.3',
    numpyVersion: '2.2.6',
    image:
      'python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79',
    architecture: 'x86_64',
    linearSolverPrefix:
      'qdldl;direct=true;threads=1;',
  },
  maximumThreads: 1,
  networkRequiredAtRuntime: false,
  confinement: {
    user: '10001:10001',
    rootFilesystem: 'read-only',
    temporaryFilesystem:
      '/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777',
    network: 'none',
    noNewPrivileges: true,
    childProcessTimeoutMilliseconds: 60_000,
    maximumStdoutStderrBytes: 1024 * 1024,
  },
  requiredEnvironment: {
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONUNBUFFERED: '1',
    PYTHONHASHSEED: '0',
    OMP_NUM_THREADS: '1',
    OPENBLAS_NUM_THREADS: '1',
    OPENBLAS_CORETYPE: 'NEHALEM',
    MKL_NUM_THREADS: '1',
    NUMEXPR_NUM_THREADS: '1',
    VECLIB_MAXIMUM_THREADS: '1',
    BLIS_NUM_THREADS: '1',
  },
})

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY =
  deepFreeze({
    $schema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_SCHEMA_ID,
    schemaVersion: 1,
    id: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_ID,
    policyVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
    authorityVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
    reviewScope:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
    subject: {
      capabilityId:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
      capabilityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
      methodFamily:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
      problemSchemaVersion: 1,
      genericProblemSchema:
        'https://flowblind.local/schemas/hidden-flow-problem.schema.json',
      genericProblemSchemaRole:
        'syntactic-prefilter-only',
      problemAcceptanceSchema:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_PROBLEM_ACCEPTANCE_SCHEMA_ID,
      parser: 'parseHiddenFlowProblem',
      canonicalization: 'stable-json-v1',
      allowedObservationTypes:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES,
      allowedTargetTypes:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES,
      resourceLimits:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
      executablePreflight:
        'compile-basis-and-all-solver-requests-without-solving',
    },
    runtime: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
    claimBoundary:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY,
    assertions: {
      genericProblemContract: 'attested',
      canonicalProblemBytes: 'attested',
      parserAcceptance: 'attested',
      allowedObservationAndTargetTypes: 'attested',
      resourceLimits: 'attested',
      executablePreflight: 'attested',
      solverRuntime: 'attested',
      neutralFiniteBasisClaims: 'attested',
      physicalTruth: 'not-attested',
      sourceAccuracy: 'not-attested',
      measurementValidity: 'not-attested',
      clinicalUse: 'not-attested',
      modelOrUserApproval: 'not-accepted-as-authority',
    },
    authorityInput:
      'host-selected-canonical-problem-bytes-only',
  })

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA =
  deepFreeze({
    type: 'object',
    properties: {
      goal: {
        type: 'string',
        minLength: 1,
        maxLength: 4_096,
        title: 'Research goal',
        description:
          'Describe the hidden-flow robustness question in ordinary scientific language.',
      },
      details: {
        type: ['string', 'null'],
        minLength: 1,
        maxLength: 4_096,
        title: 'Additional details',
        description:
          'Optional ordinary-language context for interpreting the already selected canonical problem.',
      },
    },
    required: ['goal'],
    additionalProperties: false,
  })

export const catalogHiddenFlowToolDefinitions = deepFreeze([
  {
    name: FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
    title: 'Prepare a reviewed finite-basis hidden-flow study',
    description:
      'Attest one host-selected canonical generic hidden-flow problem and emit a deterministic result-free preparation bundle.',
    inputSchema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA,
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
  {
    name: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
    title: 'Run and verify a prepared finite-basis hidden-flow study',
    description:
      'After host confirmation, re-attest the generic problem, run only the pinned Clarabel closure, independently verify it, and require deterministic replay.',
    inputSchema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA,
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  },
] as const)

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION =
  deepFreeze({
    $schema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION_SCHEMA_ID,
    schemaVersion: 1,
    id: 'flowblind-catalog-hidden-flow-declaration-v1',
    packageVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
    capability: {
      capabilityId:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
      capabilityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
      methodFamily:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
    },
    publicInputSchema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA,
    actions: [
      {
        ...catalogHiddenFlowToolDefinitions[0],
        confirmation: 'Disabled',
        hostSelection:
          'exactly-one-canonical-hidden-flow-problem-json',
        resultFree: true,
      },
      {
        ...catalogHiddenFlowToolDefinitions[1],
        confirmation: 'Enabled',
        hostSelection:
          'exactly-one-preparation-bundle-json',
        resultFree: false,
      },
    ],
    reviewPolicy: {
      id: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_ID,
      policyVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
      authorityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
      reviewScope:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
      claimBoundary:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY,
    },
    runtime: {
      platform:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.platform,
      nonRootUser:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement
          .user,
      rootFilesystem:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement
          .rootFilesystem,
      network:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement
          .network,
      temporaryFilesystem:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement
          .temporaryFilesystem,
    },
  })

export interface CatalogHiddenFlowHumanContext {
  readonly goal: string
  readonly details: string | null
}

export interface CatalogHiddenFlowArtifactIdentity {
  readonly reference: string
  readonly byteLength: number
  readonly sha256: string
  readonly mediaType: 'application/json' | 'text/markdown'
}

export interface CatalogHiddenFlowArtifact
  extends CatalogHiddenFlowArtifactIdentity {
  readonly bytes: Buffer
}

export interface CatalogHiddenFlowPackageArtifactIdentity {
  readonly reference: string
  readonly byteLength: number
  readonly sha256: string
  readonly mediaType: string
}

export interface CatalogHiddenFlowPackageEvidence {
  readonly policy:
    'attested-generic-hidden-flow-contract-parser-runtime-and-neutral-claims'
  readonly packageVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION
  readonly runtimeNetworkRequired: false
  readonly runtime: CatalogHiddenFlowPackageArtifactIdentity
  readonly bundleLock: CatalogHiddenFlowPackageArtifactIdentity
  readonly reviewPolicy: CatalogHiddenFlowPackageArtifactIdentity
  readonly declaration: CatalogHiddenFlowPackageArtifactIdentity
  readonly problemSchema: CatalogHiddenFlowPackageArtifactIdentity
  readonly problemAcceptanceSchema:
    CatalogHiddenFlowPackageArtifactIdentity
  readonly parser: CatalogHiddenFlowPackageArtifactIdentity
  readonly verifier: CatalogHiddenFlowPackageArtifactIdentity
  readonly pythonRequirements:
    CatalogHiddenFlowPackageArtifactIdentity
  readonly pythonSolverSources:
    readonly CatalogHiddenFlowPackageArtifactIdentity[]
  readonly containerDefinition:
    CatalogHiddenFlowPackageArtifactIdentity
  readonly schemas:
    readonly CatalogHiddenFlowPackageArtifactIdentity[]
}

export interface CatalogHiddenFlowReviewAttestation {
  readonly $schema:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_ATTESTATION_SCHEMA_ID
  readonly schemaVersion: 1
  readonly authorityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION
  readonly policyVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION
  readonly reviewScope:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE
  readonly policy: CatalogHiddenFlowPackageArtifactIdentity
  readonly problemSchema: CatalogHiddenFlowPackageArtifactIdentity
  readonly problemAcceptanceSchema:
    CatalogHiddenFlowPackageArtifactIdentity
  readonly parser: CatalogHiddenFlowPackageArtifactIdentity
  readonly reviewedProblemSha256: string
  readonly allowedObservationTypes:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES
  readonly allowedTargetTypes:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES
  readonly resourceLimits:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS
  readonly runtime: typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME
  readonly claimBoundary:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY
  readonly assertions:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY.assertions
}

export type CatalogHiddenFlowErrorCode =
  | 'input-invalid'
  | 'attachment-set-invalid'
  | 'attachment-path-unsafe'
  | 'attachment-changed-during-read'
  | 'problem-bytes-invalid'
  | 'problem-not-canonical'
  | 'problem-not-executable'
  | 'review-authority-unavailable'
  | 'review-attestation-invalid'
  | 'package-attestation-failed'
  | 'preparation-bundle-invalid'
  | 'human-context-mismatch'
  | 'output-publication-conflict'
  | 'concurrent-publication-conflict'
  | 'output-publication-partial'
  | 'output-artifact-tampered'
  | 'operation-cancelled'

export type CatalogHiddenFlowErrorClassification =
  | 'cancellation'
  | 'attachment'
  | 'input-validation'
  | 'package-attestation'
  | 'publication'
  | 'review'
  | 'verification'

export class CatalogHiddenFlowError extends Error {
  readonly code: CatalogHiddenFlowErrorCode
  readonly classification: CatalogHiddenFlowErrorClassification
  readonly publicDetail: string

  constructor(
    code: CatalogHiddenFlowErrorCode,
    classification: CatalogHiddenFlowErrorClassification,
    publicDetail: string,
    options?: ErrorOptions,
  ) {
    super(publicDetail, options)
    this.name = 'CatalogHiddenFlowError'
    this.code = code
    this.classification = classification
    this.publicDetail = publicDetail
  }
}

export interface CatalogHiddenFlowRefusal {
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly capabilityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly status: 'refused'
  readonly containsResults: false
  readonly error: {
    readonly code: CatalogHiddenFlowErrorCode
    readonly classification: CatalogHiddenFlowErrorClassification
    readonly detail: string
  }
}

function inputObject(value: unknown): UnknownRecord {
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new CatalogHiddenFlowError(
      'input-invalid',
      'input-validation',
      'Hidden-flow input must be one object containing ordinary-language context.',
    )
  }
  const item = value as UnknownRecord
  const allowed = new Set(['goal', 'details'])
  if (Object.keys(item).some((key) => !allowed.has(key))) {
    throw new CatalogHiddenFlowError(
      'input-invalid',
      'input-validation',
      'Hidden-flow input contains unsupported properties.',
    )
  }
  return item
}

export function validateCatalogHiddenFlowHumanContext(
  value: unknown,
): CatalogHiddenFlowHumanContext {
  const item = inputObject(value)
  try {
    return {
      goal: validateFlowBlindDisplayText(
        item.goal,
        'Research goal',
      ),
      details: validateFlowBlindOptionalDisplayText(
        Object.hasOwn(item, 'details') ? item.details : null,
        'Additional details',
      ),
    }
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'input-invalid',
      'input-validation',
      'Goal and details must be trimmed NFC text without display controls and no longer than 4,096 Unicode code points.',
      { cause: error },
    )
  }
}

export function stableJson(value: unknown): string {
  return stableEvidenceJson(value)
}

export function sha256Bytes(value: Uint8Array): string {
  return createHash('sha256').update(value).digest('hex')
}

export function utf8Bytes(value: string): Buffer {
  return Buffer.from(value, 'utf8')
}

export function artifact(
  reference: string,
  bytes: Uint8Array,
  mediaType: CatalogHiddenFlowArtifactIdentity['mediaType'],
): CatalogHiddenFlowArtifact {
  const value = Buffer.from(bytes)
  return {
    reference,
    byteLength: value.byteLength,
    sha256: sha256Bytes(value),
    mediaType,
    bytes: value,
  }
}

export function artifactIdentity(
  value: CatalogHiddenFlowArtifact,
): CatalogHiddenFlowArtifactIdentity {
  return {
    reference: value.reference,
    byteLength: value.byteLength,
    sha256: value.sha256,
    mediaType: value.mediaType,
  }
}

export function catalogHiddenFlowRefusal(
  error: CatalogHiddenFlowError,
): CatalogHiddenFlowRefusal {
  return {
    schemaVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
    capabilityVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
    status: 'refused',
    containsResults: false,
    error: {
      code: error.code,
      classification: error.classification,
      detail: [...error.publicDetail.normalize('NFC')]
        .slice(0, 512)
        .join(''),
    },
  }
}

export function throwIfCatalogHiddenFlowAborted(
  signal?: AbortSignal,
): void {
  if (signal?.aborted === true) {
    throw new CatalogHiddenFlowError(
      'operation-cancelled',
      'cancellation',
      'The hidden-flow operation was cancelled before publishing an artifact.',
    )
  }
}

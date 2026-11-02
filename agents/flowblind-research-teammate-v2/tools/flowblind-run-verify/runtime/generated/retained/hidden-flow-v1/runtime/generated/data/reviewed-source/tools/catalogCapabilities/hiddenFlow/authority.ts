import type {
  HiddenFlowProblem,
} from '../../../src/domain/hiddenFlowModel.ts'
import {
  HIDDEN_FLOW_LIMITS,
} from '../../../src/domain/hiddenFlowModel.ts'
import {
  HiddenFlowInputError,
  parseHiddenFlowProblem,
} from '../../../src/domain/hiddenFlowValidation.ts'
import {
  compileCatalogHiddenFlowPlan,
} from './engine.ts'
import type {
  CatalogHiddenFlowPreflight,
} from './engine.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_ATTESTATION_SCHEMA_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES,
  CatalogHiddenFlowError,
  artifactIdentity,
  sha256Bytes,
  stableJson,
  throwIfCatalogHiddenFlowAborted,
  utf8Bytes,
} from './profile.ts'
import type {
  CatalogHiddenFlowArtifactIdentity,
  CatalogHiddenFlowPackageEvidence,
  CatalogHiddenFlowReviewAttestation,
} from './profile.ts'

export interface ReviewedCatalogHiddenFlowProblem {
  readonly problem: HiddenFlowProblem
  readonly bytes: Buffer
  readonly identity: CatalogHiddenFlowArtifactIdentity
  readonly preflight: CatalogHiddenFlowPreflight
  readonly review: CatalogHiddenFlowReviewAttestation
  readonly software: CatalogHiddenFlowPackageEvidence
}

export interface CatalogHiddenFlowReviewAuthority {
  readonly authorityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION
  reviewSelectedProblem(
    selectedProblemBytes: Uint8Array,
    signal?: AbortSignal,
  ): ReviewedCatalogHiddenFlowProblem
}

function decodeSelectedProblem(
  selectedProblemBytes: Uint8Array,
): unknown {
  if (
    selectedProblemBytes.byteLength === 0 ||
    selectedProblemBytes.byteLength >
      HIDDEN_FLOW_LIMITS.maximumDocumentBytes
  ) {
    throw new CatalogHiddenFlowError(
      'problem-bytes-invalid',
      'input-validation',
      'The selected hidden-flow problem must be a nonempty bounded UTF-8 JSON document.',
    )
  }
  try {
    const text = new TextDecoder('utf-8', {
      fatal: true,
    }).decode(selectedProblemBytes)
    return JSON.parse(text) as unknown
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'problem-bytes-invalid',
      'input-validation',
      'The selected hidden-flow problem must be valid UTF-8 JSON.',
      { cause: error },
    )
  }
}

function parseSelectedProblem(
  selectedProblemBytes: Uint8Array,
): {
  readonly problem: HiddenFlowProblem
  readonly bytes: Buffer
  readonly identity: CatalogHiddenFlowArtifactIdentity
} {
  let problem: HiddenFlowProblem
  try {
    problem = parseHiddenFlowProblem(
      decodeSelectedProblem(selectedProblemBytes),
    )
  } catch (error) {
    const detail =
      error instanceof HiddenFlowInputError
        ? `The selected hidden-flow problem was refused with ${error.code}.`
        : 'The selected hidden-flow problem did not satisfy the version 1 generic contract.'
    throw new CatalogHiddenFlowError(
      'problem-bytes-invalid',
      'input-validation',
      detail,
      { cause: error },
    )
  }
  const bytes = utf8Bytes(stableJson(problem))
  if (!Buffer.from(selectedProblemBytes).equals(bytes)) {
    throw new CatalogHiddenFlowError(
      'problem-not-canonical',
      'input-validation',
      'The selected problem must use the canonical stable-JSON serialization of the validated version 1 problem.',
    )
  }
  const sha256 = sha256Bytes(bytes)
  return {
    problem,
    bytes,
    identity: artifactIdentity({
      reference:
        `flowblind-catalog-hidden-flow-problem-${sha256}.json`,
      byteLength: bytes.byteLength,
      sha256,
      mediaType: 'application/json',
      bytes,
    }),
  }
}

function assertPackageEvidence(
  software: CatalogHiddenFlowPackageEvidence,
): void {
  if (
    software.policy !==
      'attested-generic-hidden-flow-contract-parser-runtime-and-neutral-claims' ||
    software.packageVersion !==
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION ||
    software.runtimeNetworkRequired !== false ||
    software.reviewPolicy.sha256.length !== 64 ||
    software.problemSchema.sha256.length !== 64 ||
    software.problemAcceptanceSchema.sha256.length !== 64 ||
    software.parser.sha256.length !== 64 ||
    software.pythonRequirements.sha256 !==
      FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME
        .pythonRequirementsSha256
  ) {
    throw new CatalogHiddenFlowError(
      'package-attestation-failed',
      'package-attestation',
      'The generic hidden-flow review authority is not bound to the reviewed package closure.',
    )
  }
}

function assertReviewedTypes(problem: HiddenFlowProblem): void {
  const observationTypes = new Set(
    FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES,
  )
  if (
    problem.observations.some(
      (observation) =>
        !observationTypes.has(observation.type),
    )
  ) {
    throw new CatalogHiddenFlowError(
      'review-attestation-invalid',
      'review',
      'The selected problem contains an observation type outside the generic reviewed policy.',
    )
  }
  const targetTypes = new Set(
    FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES,
  )
  if (!targetTypes.has(problem.target.type)) {
    throw new CatalogHiddenFlowError(
      'review-attestation-invalid',
      'review',
      'The selected problem contains a target type outside the generic reviewed policy.',
    )
  }
}

export function createAttestedGenericHiddenFlowReviewAuthority(
  software: CatalogHiddenFlowPackageEvidence,
): CatalogHiddenFlowReviewAuthority {
  assertPackageEvidence(software)
  return Object.freeze({
    authorityVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
    reviewSelectedProblem(
      selectedProblemBytes: Uint8Array,
      signal?: AbortSignal,
    ): ReviewedCatalogHiddenFlowProblem {
      throwIfCatalogHiddenFlowAborted(signal)
      const selected = parseSelectedProblem(
        selectedProblemBytes,
      )
      assertReviewedTypes(selected.problem)
      let preflight: CatalogHiddenFlowPreflight
      try {
        preflight = compileCatalogHiddenFlowPlan(
          selected.problem,
        ).preflight
      } catch (error) {
        throw new CatalogHiddenFlowError(
          'problem-not-executable',
          'input-validation',
          'The selected problem passed structural validation but could not produce the bounded generic hidden-flow solver plan.',
          { cause: error },
        )
      }
      throwIfCatalogHiddenFlowAborted(signal)
      return {
        ...selected,
        preflight,
        review: {
          $schema:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_ATTESTATION_SCHEMA_ID,
          schemaVersion: 1,
          authorityVersion:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
          policyVersion:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
          reviewScope:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
          policy: software.reviewPolicy,
          problemSchema: software.problemSchema,
          problemAcceptanceSchema:
            software.problemAcceptanceSchema,
          parser: software.parser,
          reviewedProblemSha256: selected.identity.sha256,
          allowedObservationTypes:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES,
          allowedTargetTypes:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES,
          resourceLimits:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
          runtime: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
          claimBoundary:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY,
          assertions:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY
              .assertions,
        },
        software,
      }
    },
  })
}

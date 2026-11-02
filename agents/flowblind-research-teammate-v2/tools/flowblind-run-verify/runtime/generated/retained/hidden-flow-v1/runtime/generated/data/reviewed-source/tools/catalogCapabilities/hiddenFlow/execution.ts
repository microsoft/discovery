import { renderHiddenFlowEvidenceReportMarkdown } from '../../../src/application/hiddenFlowEvidenceReport.ts'
import type {
  HiddenFlowEvidenceReport,
  HiddenFlowEvidenceState,
  HiddenFlowProblem,
  HiddenFlowSearchResult,
  HiddenFlowSupportResult,
} from '../../../src/domain/hiddenFlowModel.ts'
import type { HiddenFlowSolverPort } from '../../../src/ports/HiddenFlowSolverPort.ts'
import { FLOWBLIND_VERSION } from '../../../src/version.ts'
import {
  compileCatalogHiddenFlowPlan,
  executeCatalogHiddenFlowPlan,
} from './engine.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERIFIED_RUN_SCHEMA_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES,
  artifact,
  artifactIdentity,
  sha256Bytes,
  stableJson,
  throwIfCatalogHiddenFlowAborted,
  utf8Bytes,
} from './profile.ts'
import type {
  CatalogHiddenFlowArtifact,
  CatalogHiddenFlowArtifactIdentity,
  CatalogHiddenFlowHumanContext,
  CatalogHiddenFlowPackageEvidence,
  CatalogHiddenFlowReviewAttestation,
} from './profile.ts'
import type {
  CatalogHiddenFlowReviewAuthority,
} from './authority.ts'
import type {
  CatalogHiddenFlowPreparationBundle,
  ValidatedCatalogHiddenFlowBundle,
} from './preparation.ts'

export type CatalogHiddenFlowReportableOutcome =
  | {
      readonly kind: 'numerical'
      readonly evidenceState:
        | 'verified-optimal-within-tolerance'
        | 'verified-directional-lower-bound-within-tolerance'
        | 'approximate-candidate'
        | 'full-observation-zero-nullity'
        | 'degenerate-objective'
      readonly targetId: string
      readonly targetType: HiddenFlowProblem['target']['type']
      readonly targetTitle: string
      readonly value: number
      readonly unit: 'mm/s' | '1/s'
      readonly rigorousUpperBound: number | null
      readonly qualification:
        | 'verified-to-declared-tolerances'
        | 'candidate-only'
      readonly detail: string
    }
  | {
      readonly kind: 'infeasible'
      readonly evidenceState:
        'verified-infeasible-within-tolerance'
      readonly targetId: string
      readonly targetType: HiddenFlowProblem['target']['type']
      readonly targetTitle: string
      readonly qualification:
        'verified-to-declared-tolerances'
      readonly detail: string
    }
  | {
      readonly kind: 'unavailable'
      readonly evidenceState:
        'verified-unbounded-within-tolerance'
      readonly reason: 'no-finite-bound'
      readonly detail: string
    }

export type CatalogHiddenFlowFailureOutcome = {
  readonly kind: 'unavailable'
  readonly evidenceState:
    | 'unsupported'
    | 'failed'
    | null
  readonly reason:
    | 'verification-not-accepted'
    | 'deterministic-replay-mismatch'
    | 'runtime-unavailable'
    | 'runtime-identity-mismatch'
    | 'output-resource-limit'
    | 'operation-cancelled'
  readonly detail: string
}

export type CatalogHiddenFlowOutcome =
  | CatalogHiddenFlowReportableOutcome
  | CatalogHiddenFlowFailureOutcome

export interface CatalogHiddenFlowVerifiedRun {
  readonly $schema:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERIFIED_RUN_SCHEMA_ID
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly recordType:
    'flowblind-catalog-hidden-flow-verified-run-v1'
  readonly id: string
  readonly capabilityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly humanContext: CatalogHiddenFlowHumanContext
  readonly preparation: {
    readonly id: string
    readonly artifact: CatalogHiddenFlowArtifactIdentity
    readonly associationSha256: string
  }
  readonly problem: {
    readonly identity: CatalogHiddenFlowArtifactIdentity
    readonly id: string
    readonly title: string
    readonly targetId: string
    readonly targetType: HiddenFlowProblem['target']['type']
  }
  readonly review: CatalogHiddenFlowReviewAttestation
  readonly software: CatalogHiddenFlowPackageEvidence
  readonly deterministicReplay: {
    readonly canonicalization: 'stable-json-v1'
    readonly matched: true
    readonly firstExecutionSha256: string
    readonly replayExecutionSha256: string
  }
  readonly outcome: CatalogHiddenFlowReportableOutcome
  readonly evidence: HiddenFlowEvidenceReport
}

export interface CatalogHiddenFlowRunResponse {
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly capabilityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly status: 'report-complete'
  readonly containsResults: boolean
  readonly humanContext: CatalogHiddenFlowHumanContext
  readonly problem: {
    readonly id: string
    readonly title: string
    readonly targetId: string
    readonly targetType: HiddenFlowProblem['target']['type']
  }
  readonly review: {
    readonly authorityVersion:
      CatalogHiddenFlowReviewAttestation['authorityVersion']
    readonly reviewScope:
      CatalogHiddenFlowReviewAttestation['reviewScope']
    readonly claimBoundary:
      CatalogHiddenFlowReviewAttestation['claimBoundary']
  }
  readonly deterministicReplayMatched: true
  readonly outcome: CatalogHiddenFlowReportableOutcome
  readonly artifacts: {
    readonly json: CatalogHiddenFlowArtifactIdentity
    readonly markdown: CatalogHiddenFlowArtifactIdentity
  }
  readonly publication: {
    readonly state: 'uncommitted-core-bytes'
    readonly promotable: false
  }
}

export interface CatalogHiddenFlowUnavailableResponse {
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly capabilityVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly status: 'unavailable'
  readonly containsResults: false
  readonly deterministicReplayMatched: false
  readonly outcome: CatalogHiddenFlowFailureOutcome
}

export interface ExecutedCatalogHiddenFlow {
  readonly response: CatalogHiddenFlowRunResponse
  readonly artifacts: {
    readonly json: CatalogHiddenFlowArtifact
    readonly markdown: CatalogHiddenFlowArtifact
  }
}

export interface CatalogHiddenFlowRunOptions {
  readonly reviewAuthority?: CatalogHiddenFlowReviewAuthority
  readonly solver?: HiddenFlowSolverPort
  readonly signal?: AbortSignal
  readonly onUnexpectedError?: (error: unknown) => void
}

export function catalogHiddenFlowOutputLengthsWithinLimits(
  jsonByteLength: number,
  markdownByteLength: number,
): boolean {
  return (
    Number.isSafeInteger(jsonByteLength) &&
    jsonByteLength >= 0 &&
    jsonByteLength <=
      FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES &&
    Number.isSafeInteger(markdownByteLength) &&
    markdownByteLength >= 0 &&
    markdownByteLength <=
      FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES
  )
}

function supportResults(
  result: HiddenFlowSearchResult,
): readonly HiddenFlowSupportResult[] {
  return 'directionalResults' in result.support
    ? result.support.directionalResults
    : [result.support]
}

function pinnedSolverIdentityMatched(
  result: HiddenFlowSearchResult,
): boolean {
  const expected =
    FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.solverIdentity
  return supportResults(result).every(({ solverResult }) => {
    const actual = solverResult.solver
    return (
      actual.adapter === expected.adapter &&
      actual.adapterVersion === expected.adapterVersion &&
      actual.pythonVersion === expected.pythonVersion &&
      actual.clarabelVersion ===
        expected.clarabelVersion &&
      actual.scipyVersion === expected.scipyVersion &&
      actual.numpyVersion === expected.numpyVersion &&
      actual.image === expected.image &&
      actual.architecture === expected.architecture &&
      actual.linearSolver !== null &&
      actual.linearSolver
        .toLowerCase()
        .startsWith(
          expected.linearSolverPrefix.toLowerCase(),
        )
    )
  })
}

function scalarSupport(
  result: HiddenFlowSearchResult,
): HiddenFlowSupportResult | null {
  return 'directionalResults' in result.support
    ? null
    : result.support
}

function outcomeDetail(
  state: HiddenFlowEvidenceState,
  fallback: string,
): string {
  if (
    state === 'verified-directional-lower-bound-within-tolerance'
  ) {
    return 'The reported value is the best verified directional candidate and is a lower bound only; no rigorous speed upper bound is claimed.'
  }
  return fallback
}

export function classifyCatalogHiddenFlowOutcome(
  problem: HiddenFlowProblem,
  result: HiddenFlowSearchResult,
): CatalogHiddenFlowOutcome {
  if ('directionalResults' in result.support) {
    const state = result.support.state
    if (
      state ===
        'verified-directional-lower-bound-within-tolerance' ||
      state === 'approximate-candidate' ||
      state === 'full-observation-zero-nullity' ||
      state === 'degenerate-objective'
    ) {
      return {
        kind: 'numerical',
        evidenceState: state,
        targetId: problem.target.id,
        targetType: problem.target.type,
        targetTitle: problem.target.title,
        value: result.support.lowerBound,
        unit: result.support.unit,
        rigorousUpperBound: result.support.upperBound,
        qualification:
          state === 'approximate-candidate'
            ? 'candidate-only'
            : 'verified-to-declared-tolerances',
        detail: outcomeDetail(
          state,
          'The finite-basis target produced a verified numerical result.',
        ),
      }
    }
  }
  const support = scalarSupport(result)
  if (support === null) {
    return {
      kind: 'unavailable',
      evidenceState: 'failed',
      reason: 'verification-not-accepted',
      detail:
        'The directional hidden-flow result did not support a finite verified candidate.',
    }
  }
  const verification = support.verification
  if (
    verification.state ===
    'verified-infeasible-within-tolerance'
  ) {
    return {
      kind: 'infeasible',
      evidenceState: verification.state,
      targetId: problem.target.id,
      targetType: problem.target.type,
      targetTitle: problem.target.title,
      qualification: 'verified-to-declared-tolerances',
      detail: verification.detail,
    }
  }
  if (
    verification.state ===
    'verified-unbounded-within-tolerance'
  ) {
    return {
      kind: 'unavailable',
      evidenceState: verification.state,
      reason: 'no-finite-bound',
      detail:
        'The finite problem is verified unbounded, so no finite hidden-flow value is reported.',
    }
  }
  if (
    verification.accepted &&
    (
      verification.state ===
        'verified-optimal-within-tolerance' ||
      verification.state === 'approximate-candidate' ||
      verification.state ===
        'full-observation-zero-nullity' ||
      verification.state === 'degenerate-objective'
    )
  ) {
    return {
      kind: 'numerical',
      evidenceState: verification.state,
      targetId: problem.target.id,
      targetType: problem.target.type,
      targetTitle: problem.target.title,
      value: verification.objectiveValue ?? 0,
      unit: problem.target.unit,
      rigorousUpperBound:
        verification.rigorousObjectiveUpperBound,
      qualification:
        verification.numericalEvidenceQualification ===
        'candidate-only'
          ? 'candidate-only'
          : 'verified-to-declared-tolerances',
      detail: verification.detail,
    }
  }
  return {
    kind: 'unavailable',
    evidenceState:
      verification.state === 'unsupported' ||
      verification.state === 'failed'
        ? verification.state
        : 'failed',
    reason: 'verification-not-accepted',
    detail:
      'The existing independent verifier did not accept a numerical or infeasibility claim.',
  }
}

function report(
  bundle: CatalogHiddenFlowPreparationBundle,
  result: HiddenFlowSearchResult,
): HiddenFlowEvidenceReport {
  return {
    schemaVersion: 1,
    reportId:
      `catalog-hidden-flow-${bundle.association.sha256.slice(0, 32)}`,
    software: {
      name: 'FlowBlind',
      version: FLOWBLIND_VERSION,
    },
    problemSource: {
      reference: bundle.problem.identity.reference,
      byteLength: bundle.problem.identity.byteLength,
      sha256: bundle.problem.identity.sha256,
    },
    problem: bundle.problem.document,
    basisSha256: bundle.preflight.basisSha256,
    basis: result.basis.diagnostics,
    result,
    limitations: bundle.problem.document.limitations,
  }
}

function unavailable(
  reason: CatalogHiddenFlowFailureOutcome['reason'],
  detail: string,
  evidenceState:
    CatalogHiddenFlowFailureOutcome['evidenceState'] = null,
): CatalogHiddenFlowUnavailableResponse {
  return {
    schemaVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
    capabilityVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
    status: 'unavailable',
    containsResults: false,
    deterministicReplayMatched: false,
    outcome: {
      kind: 'unavailable',
      evidenceState,
      reason,
      detail,
    },
  }
}

export async function executeCatalogHiddenFlowBundle(
  humanContext: CatalogHiddenFlowHumanContext,
  validated: ValidatedCatalogHiddenFlowBundle,
  options: CatalogHiddenFlowRunOptions = {},
): Promise<
  ExecutedCatalogHiddenFlow | CatalogHiddenFlowUnavailableResponse
> {
  try {
    throwIfCatalogHiddenFlowAborted(options.signal)
    const plan = compileCatalogHiddenFlowPlan(
      validated.bundle.problem.document,
    )
    if (
      stableJson(plan.preflight) !==
      stableJson(validated.bundle.preflight)
    ) {
      return unavailable(
        'verification-not-accepted',
        'The deterministic solver plan no longer matches the preparation preflight.',
      )
    }
    const solver = options.solver
    if (solver === undefined) {
      return unavailable(
        'runtime-unavailable',
        'The attested pinned hidden-flow solver runtime was not supplied.',
      )
    }
    const first = await executeCatalogHiddenFlowPlan(
      plan,
      solver,
    )
    if (!pinnedSolverIdentityMatched(first)) {
      return unavailable(
        'runtime-identity-mismatch',
        'The solver result did not match the attested Python, Clarabel, dependency, image, architecture, and single-thread identity.',
      )
    }
    throwIfCatalogHiddenFlowAborted(options.signal)
    const replay = await executeCatalogHiddenFlowPlan(
      plan,
      solver,
    )
    if (!pinnedSolverIdentityMatched(replay)) {
      return unavailable(
        'runtime-identity-mismatch',
        'The replay solver result did not match the attested pinned runtime identity.',
      )
    }
    throwIfCatalogHiddenFlowAborted(options.signal)
    const firstBytes = utf8Bytes(stableJson(first))
    const replayBytes = utf8Bytes(stableJson(replay))
    const firstSha256 = sha256Bytes(firstBytes)
    const replaySha256 = sha256Bytes(replayBytes)
    if (
      firstSha256 !== replaySha256 ||
      !firstBytes.equals(replayBytes)
    ) {
      return unavailable(
        'deterministic-replay-mismatch',
        'Two executions of the same prepared problem did not produce byte-identical verified evidence.',
      )
    }
    const typedOutcome = classifyCatalogHiddenFlowOutcome(
      validated.bundle.problem.document,
      first,
    )
    if (
      typedOutcome.kind === 'unavailable' &&
      typedOutcome.reason !== 'no-finite-bound'
    ) {
      return unavailable(
        typedOutcome.reason,
        typedOutcome.detail,
        typedOutcome.evidenceState,
      )
    }
    const evidence = report(validated.bundle, first)
    const runBindings = {
      capabilityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
      humanContext,
      preparation: {
        id: validated.bundle.id,
        artifact: artifactIdentity(
          validated.bundleArtifact,
        ),
        associationSha256:
          validated.bundle.association.sha256,
      },
      problem: {
        identity: validated.bundle.problem.identity,
        id: validated.bundle.problem.document.id,
        title: validated.bundle.problem.document.title,
        targetId:
          validated.bundle.problem.document.target.id,
        targetType:
          validated.bundle.problem.document.target.type,
      },
      review: validated.bundle.review,
      software: validated.bundle.software,
      deterministicReplay: {
        canonicalization: 'stable-json-v1' as const,
        matched: true as const,
        firstExecutionSha256: firstSha256,
        replayExecutionSha256: replaySha256,
      },
      outcome: typedOutcome,
      evidence,
    } as const
    const runAssociationSha256 = sha256Bytes(
      utf8Bytes(stableJson(runBindings)),
    )
    const record: CatalogHiddenFlowVerifiedRun = {
      $schema:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERIFIED_RUN_SCHEMA_ID,
      schemaVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
      recordType:
        'flowblind-catalog-hidden-flow-verified-run-v1',
      id:
        `flowblind-hidden-flow-run-${runAssociationSha256.slice(0, 32)}`,
      ...runBindings,
    }
    const jsonBytes = utf8Bytes(stableJson(record))
    const markdownBytes = utf8Bytes(
      renderHiddenFlowEvidenceReportMarkdown(evidence),
    )
    if (
      !catalogHiddenFlowOutputLengthsWithinLimits(
        jsonBytes.byteLength,
        markdownBytes.byteLength,
      )
    ) {
      return unavailable(
        'output-resource-limit',
        'The deterministic evidence exceeded the bounded catalog artifact limits, so no partial artifact was returned.',
      )
    }
    const json = artifact(
      `flowblind-catalog-hidden-flow-run-${sha256Bytes(jsonBytes)}.json`,
      jsonBytes,
      'application/json',
    )
    const markdown = artifact(
      `flowblind-catalog-hidden-flow-report-${sha256Bytes(markdownBytes)}.md`,
      markdownBytes,
      'text/markdown',
    )
    return {
      response: {
        schemaVersion:
          FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
        capabilityVersion:
          FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
        status: 'report-complete',
        containsResults:
          typedOutcome.kind !== 'unavailable',
        humanContext,
        problem: {
          id: runBindings.problem.id,
          title: runBindings.problem.title,
          targetId: runBindings.problem.targetId,
          targetType: runBindings.problem.targetType,
        },
        review: {
          authorityVersion:
            validated.bundle.review.authorityVersion,
          reviewScope:
            validated.bundle.review.reviewScope,
          claimBoundary:
            validated.bundle.review.claimBoundary,
        },
        deterministicReplayMatched: true,
        outcome: typedOutcome,
        artifacts: {
          json: artifactIdentity(json),
          markdown: artifactIdentity(markdown),
        },
        publication: {
          state: 'uncommitted-core-bytes',
          promotable: false,
        },
      },
      artifacts: { json, markdown },
    }
  } catch (error) {
    try {
      options.onUnexpectedError?.(error)
    } catch {
      // Diagnostic sinks are observational and never replace the typed outcome.
    }
    if (
      options.signal?.aborted === true ||
      (
        error instanceof Error &&
        (
          error.name === 'AbortError' ||
          (
            error.name === 'CatalogHiddenFlowError' &&
            'code' in error &&
            error.code === 'operation-cancelled'
          )
        )
      )
    ) {
      return unavailable(
        'operation-cancelled',
        'The hidden-flow run was cancelled before verified artifacts were produced.',
      )
    }
    return unavailable(
      'runtime-unavailable',
      'The pinned hidden-flow runtime did not complete; no numerical or infeasibility claim is made.',
    )
  }
}

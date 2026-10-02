import { compileHiddenFlowBasis } from '../../../src/domain/hiddenFlowBasis.ts'
import type {
  HiddenFlowCompiledBasis,
  HiddenFlowCompiledProblem,
  HiddenFlowProblem,
  HiddenFlowSearchResult,
  HiddenFlowSpeedEnvelope,
  HiddenFlowSupportRequest,
  HiddenFlowSupportResult,
} from '../../../src/domain/hiddenFlowModel.ts'
import {
  compileHiddenFlowProblem,
  compileHiddenFlowSpeedDirections,
  createHiddenFlowSupportRequest,
} from '../../../src/domain/hiddenFlowOperator.ts'
import { verifyHiddenFlowSupportResult } from '../../../src/domain/hiddenFlowVerification.ts'
import type { HiddenFlowSolverPort } from '../../../src/ports/HiddenFlowSolverPort.ts'
import {
  sha256Bytes,
  stableJson,
  utf8Bytes,
} from './profile.ts'

export interface CatalogHiddenFlowPreflight {
  readonly basisSha256: string
  readonly retainedBasisFunctions: number
  readonly rejectedBasisFunctions: number
  readonly observationRows: number
  readonly observationRankLimit: number
  readonly solverRequestCount: number
  readonly solverRequestSha256: readonly string[]
  readonly target: {
    readonly id: string
    readonly type: HiddenFlowProblem['target']['type']
    readonly title: string
    readonly unit: 'mm/s' | '1/s'
  }
}

export interface CatalogHiddenFlowPlan {
  readonly problem: HiddenFlowProblem
  readonly basis: HiddenFlowCompiledBasis
  readonly compiledProblems: readonly HiddenFlowCompiledProblem[]
  readonly requests: readonly HiddenFlowSupportRequest[]
  readonly preflight: CatalogHiddenFlowPreflight
}

function requestId(problem: HiddenFlowProblem, index: number): string {
  return problem.target.type === 'point-speed-envelope'
    ? `${problem.id}-d-${index}`
    : `${problem.id}-solve`
}

export function compileCatalogHiddenFlowPlan(
  problem: HiddenFlowProblem,
): CatalogHiddenFlowPlan {
  const basis = compileHiddenFlowBasis(
    problem.domain,
    problem.basis,
    problem.numerics,
  )
  const compiledProblems =
    problem.target.type === 'point-speed-envelope'
      ? compileHiddenFlowSpeedDirections(problem, basis)
      : [
          compileHiddenFlowProblem(
            problem,
            basis,
            problem.target,
          ),
        ]
  const requests = compiledProblems.map((compiled, index) =>
    createHiddenFlowSupportRequest(
      compiled,
      requestId(problem, index),
    ),
  )
  const basisSha256 = sha256Bytes(
    utf8Bytes(
      stableJson({
        spec: basis.spec,
        functions: basis.functions,
        massMatrix: basis.massMatrix,
        roughnessMatrix: basis.roughnessMatrix,
      }),
    ),
  )
  return {
    problem,
    basis,
    compiledProblems,
    requests,
    preflight: {
      basisSha256,
      retainedBasisFunctions: basis.functions.length,
      rejectedBasisFunctions:
        basis.diagnostics.rejectedSupportCount,
      observationRows: problem.observations.length,
      observationRankLimit: Math.min(
        problem.observations.length,
        basis.functions.length,
      ),
      solverRequestCount: requests.length,
      solverRequestSha256: requests.map((request) =>
        sha256Bytes(utf8Bytes(stableJson(request))),
      ),
      target: {
        id: problem.target.id,
        type: problem.target.type,
        title: problem.target.title,
        unit: problem.target.unit,
      },
    },
  }
}

function verifySupport(
  compiled: HiddenFlowCompiledProblem,
  request: HiddenFlowSupportRequest,
  solverResult: Awaited<
    ReturnType<HiddenFlowSolverPort['solve']>
  >,
): HiddenFlowSupportResult {
  return verifyHiddenFlowSupportResult(
    compiled,
    request,
    solverResult,
    {
      requestMatches:
        solverResult.requestSha256 ===
        sha256Bytes(utf8Bytes(stableJson(request))),
      canonicalMatches:
        solverResult.canonicalSha256 ===
        sha256Bytes(
          utf8Bytes(
            stableJson(solverResult.canonicalization),
          ),
        ),
    },
  )
}

function aggregateSpeedEnvelope(
  problem: HiddenFlowProblem,
  results: readonly HiddenFlowSupportResult[],
): HiddenFlowSpeedEnvelope | HiddenFlowSupportResult {
  if (problem.target.type !== 'point-speed-envelope') {
    throw new Error('Cannot aggregate a non-speed target.')
  }
  const first = results[0]
  if (first === undefined) {
    throw new Error(
      'The hidden-flow speed plan did not produce any directional result.',
    )
  }
  if (
    results.every(
      (result) =>
        result.verification.state ===
        'verified-infeasible-within-tolerance',
    )
  ) {
    return first
  }
  if (
    results.every(
      (result) =>
        result.verification.state ===
        'verified-unbounded-within-tolerance',
    )
  ) {
    return first
  }
  const incompatible = results.find((result) =>
    result.verification.state === 'unsupported' ||
    result.verification.state === 'failed',
  )
  if (incompatible !== undefined) {
    return incompatible
  }
  if (
    results.some(
      (result) =>
        result.verification.state ===
          'verified-infeasible-within-tolerance' ||
        result.verification.state ===
          'verified-unbounded-within-tolerance' ||
        !result.verification.accepted,
    )
  ) {
    return {
      ...first,
      verification: {
        ...first.verification,
        accepted: false,
        state: 'failed',
        detail:
          'Directional solves produced inconsistent feasibility or verification states.',
        objectiveValue: null,
        rigorousObjectiveUpperBound: null,
        approximateDualUpperDiagnostic: null,
        upperBoundQualification: 'not-applicable',
        numericalEvidenceQualification: 'not-applicable',
      },
    }
  }
  const allDegenerate = results.every(
    (result) =>
      result.verification.state === 'degenerate-objective',
  )
  const allFullObservationZero = results.every(
    (result) =>
      result.verification.state ===
      'full-observation-zero-nullity',
  )
  const candidates = results.flatMap((result, index) => {
    const objective =
      result.verification.objectiveValue ??
      (result.verification.state === 'degenerate-objective'
        ? 0
        : null)
    return objective === null || !result.verification.accepted
      ? []
      : [
          {
            index,
            objective,
            coefficients:
              result.solverResult.solution.coefficients,
          },
        ]
  })
  if (candidates.length === 0) {
    return first
  }
  const best = candidates.reduce((current, candidate) =>
    candidate.objective > current.objective
      ? candidate
      : current,
  )
  const directionCount = problem.target.directionCount
  const angle = (2 * Math.PI * best.index) / directionCount
  const allDirectionalCandidatesVerified = results.every(
    (result) =>
      [
        'verified-optimal-within-tolerance',
        'degenerate-objective',
        'full-observation-zero-nullity',
      ].includes(result.verification.state),
  )
  return {
    state: allDegenerate
      ? 'degenerate-objective'
      : allFullObservationZero
        ? 'full-observation-zero-nullity'
        : allDirectionalCandidatesVerified
          ? 'verified-directional-lower-bound-within-tolerance'
          : 'approximate-candidate',
    directionCount,
    geometricFactor:
      1 / Math.cos(Math.PI / directionCount),
    lowerBound: best.objective,
    upperBound: null,
    unit: problem.target.unit,
    bestDirection: [Math.cos(angle), Math.sin(angle)],
    bestCandidate: best.coefficients,
    directionalResults: results,
  }
}

export async function executeCatalogHiddenFlowPlan(
  plan: CatalogHiddenFlowPlan,
  solver: HiddenFlowSolverPort,
): Promise<HiddenFlowSearchResult> {
  const solverResults =
    plan.requests.length === 1
      ? [await solver.solve(plan.requests[0]!)]
      : await solver.solveMany(plan.requests)
  if (solverResults.length !== plan.requests.length) {
    throw new Error(
      'The hidden-flow solver returned a different result count than requested.',
    )
  }
  const supports = plan.compiledProblems.map(
    (compiled, index) =>
      verifySupport(
        compiled,
        plan.requests[index]!,
        solverResults[index]!,
      ),
  )
  const first = supports[0]
  if (first === undefined) {
    throw new Error(
      'The hidden-flow plan did not produce a verified support result.',
    )
  }
  return {
    basis: plan.basis,
    observationRank: first.solverResult.svd.rank,
    observationNullity: first.solverResult.svd.nullity,
    observationSingularValues:
      first.solverResult.svd.singularValues,
    support:
      plan.problem.target.type === 'point-speed-envelope'
        ? aggregateSpeedEnvelope(plan.problem, supports)
        : first,
  }
}

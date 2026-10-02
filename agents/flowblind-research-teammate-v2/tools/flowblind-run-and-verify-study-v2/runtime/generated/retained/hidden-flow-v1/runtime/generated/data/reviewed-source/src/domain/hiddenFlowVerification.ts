import {
  evaluateHiddenFlowBasisAtPoint,
  hiddenFlowSymmetricEigenvalues,
} from './hiddenFlowBasis'
import {
  HIDDEN_FLOW_LIMITS,
  type DenseMatrix,
  type HiddenFlowCompiledProblem,
  type HiddenFlowConeBlock,
  type HiddenFlowEvidenceState,
  type HiddenFlowSolverResult,
  type HiddenFlowSupportRequest,
  type HiddenFlowSupportResult,
  type HiddenFlowVerificationSummary,
} from './hiddenFlowModel'
import { HiddenFlowInputError } from './hiddenFlowValidation'

export interface HiddenFlowHashVerification {
  requestMatches: boolean
  canonicalMatches: boolean
}

function matrixIndex(columns: number, row: number, column: number): number {
  return row * columns + column
}

function dot(left: readonly number[], right: readonly number[]): number {
  if (left.length !== right.length) {
    throw new Error('Vector dimensions do not match.')
  }
  let value = 0
  for (let index = 0; index < left.length; index += 1) {
    value += left[index] * right[index]
  }
  return value
}

function matrixVector(
  matrix: DenseMatrix,
  vector: readonly number[],
): readonly number[] {
  if (matrix.columns !== vector.length) {
    throw new Error('Matrix and vector dimensions do not match.')
  }
  return Array.from({ length: matrix.rows }, (_, row) => {
    let value = 0
    for (let column = 0; column < matrix.columns; column += 1) {
      value +=
        matrix.values[matrixIndex(matrix.columns, row, column)] *
        vector[column]
    }
    return value
  })
}

function transposeMatrixVector(
  matrix: DenseMatrix,
  vector: readonly number[],
): readonly number[] {
  if (matrix.rows !== vector.length) {
    throw new Error('Transposed matrix and vector dimensions do not match.')
  }
  return Array.from({ length: matrix.columns }, (_, column) => {
    let value = 0
    for (let row = 0; row < matrix.rows; row += 1) {
      value +=
        matrix.values[matrixIndex(matrix.columns, row, column)] * vector[row]
    }
    return value
  })
}

function quadratic(matrix: DenseMatrix, vector: readonly number[]): number {
  return dot(vector, matrixVector(matrix, vector))
}

function maximumAbsolute(values: readonly number[]): number {
  return values.reduce((maximum, value) => Math.max(maximum, Math.abs(value)), 0)
}

function differenceMaximum(
  left: readonly number[],
  right: readonly number[],
): number {
  if (left.length !== right.length) return Number.POSITIVE_INFINITY
  return left.reduce(
    (maximum, value, index) =>
      Math.max(maximum, Math.abs(value - right[index])),
    0,
  )
}

function tolerance(
  absoluteTolerance: number,
  relativeTolerance: number,
  ...scales: readonly number[]
): number {
  return (
    absoluteTolerance +
    relativeTolerance *
      Math.max(1, ...scales.map((value) => Math.abs(value)))
  )
}

function matrixScale(matrix: DenseMatrix): number {
  return maximumAbsolute(matrix.values)
}

function verifyFactor(
  factor: DenseMatrix | null,
  original: DenseMatrix,
  expectedPresent: boolean,
  absoluteTolerance: number,
  relativeTolerance: number,
): number {
  if (!expectedPresent) {
    return factor === null ? 0 : Number.POSITIVE_INFINITY
  }
  if (
    factor === null ||
    factor.rows !== original.rows ||
    factor.columns !== original.columns
  ) {
    return Number.POSITIVE_INFINITY
  }
  let maximumDifference = 0
  for (let row = 0; row < original.rows; row += 1) {
    for (let column = 0; column < original.columns; column += 1) {
      let reconstructed = 0
      for (let factorRow = 0; factorRow < factor.rows; factorRow += 1) {
        reconstructed +=
          factor.values[matrixIndex(factor.columns, factorRow, row)] *
          factor.values[matrixIndex(factor.columns, factorRow, column)]
      }
      maximumDifference = Math.max(
        maximumDifference,
        Math.abs(
          reconstructed -
            original.values[matrixIndex(original.columns, row, column)],
        ),
      )
    }
  }
  const allowed = tolerance(
    absoluteTolerance,
    relativeTolerance,
    matrixScale(original),
  )
  return maximumDifference <= allowed
    ? maximumDifference
    : Number.POSITIVE_INFINITY
}

interface ExpectedCanonicalization {
  q: readonly number[]
  a: DenseMatrix
  b: readonly number[]
  cones: readonly HiddenFlowConeBlock[]
}

function expectedCanonicalization(
  request: HiddenFlowSupportRequest,
  energyFactor: DenseMatrix | null,
  roughnessFactor: DenseMatrix | null,
): ExpectedCanonicalization {
  const rows: number[] = []
  const b: number[] = []
  const cones: HiddenFlowConeBlock[] = []
  const appendObservationRows = (
    indices: readonly number[],
    sign: 1 | -1,
    bounds: readonly number[],
    cone: HiddenFlowConeBlock,
  ) => {
    if (indices.length === 0) return
    for (const row of indices) {
      for (
        let column = 0;
        column < request.observationMatrix.columns;
        column += 1
      ) {
        rows.push(
          sign *
            request.observationMatrix.values[
              matrixIndex(
                request.observationMatrix.columns,
                row,
                column,
              )
            ],
        )
      }
      b.push(sign * bounds[row])
    }
    cones.push(cone)
  }
  const exact: number[] = []
  const bands: number[] = []
  for (let index = 0; index < request.lowerBounds.length; index += 1) {
    if (request.lowerBounds[index] === request.upperBounds[index]) {
      exact.push(index)
    } else {
      bands.push(index)
    }
  }
  const expectedRows =
    exact.length +
    2 * bands.length +
    (energyFactor === null || request.energyBudget === null
      ? 0
      : energyFactor.rows + 1) +
    (roughnessFactor === null || request.roughnessBudget === null
      ? 0
      : roughnessFactor.rows + 1)
  const expectedEntries = expectedRows * request.coefficientCount
  if (expectedEntries > HIDDEN_FLOW_LIMITS.maximumCanonicalMatrixEntries) {
    throw new HiddenFlowInputError(
      'resource-limit-exceeded',
      'hiddenFlowCanonicalization.a',
      `would exceed the ${HIDDEN_FLOW_LIMITS.maximumCanonicalMatrixEntries}-entry limit.`,
    )
  }
  appendObservationRows(exact, 1, request.upperBounds, {
    type: 'zero',
    dimension: exact.length,
    label: 'observation-exact',
  })
  appendObservationRows(bands, 1, request.upperBounds, {
    type: 'nonnegative',
    dimension: bands.length,
    label: 'observation-upper',
  })
  appendObservationRows(bands, -1, request.lowerBounds, {
    type: 'nonnegative',
    dimension: bands.length,
    label: 'observation-lower',
  })
  const appendBudget = (
    factor: DenseMatrix | null,
    budget: number | null,
    label: string,
  ) => {
    if (factor === null || budget === null) return
    for (let index = 0; index < request.coefficientCount; index += 1) {
      rows.push(0)
    }
    b.push(budget)
    for (const value of factor.values) rows.push(value)
    for (let index = 0; index < factor.rows; index += 1) b.push(0)
    cones.push({
      type: 'second-order',
      dimension: factor.rows + 1,
      label: `${label}-budget`,
    })
  }
  appendBudget(energyFactor, request.energyBudget, 'energy')
  appendBudget(roughnessFactor, request.roughnessBudget, 'roughness')
  return {
    q: request.objective.map((value) => -value),
    a: {
      rows: b.length,
      columns: request.coefficientCount,
      values: rows,
    },
    b,
    cones,
  }
}

function conesEqual(
  left: readonly HiddenFlowConeBlock[],
  right: readonly HiddenFlowConeBlock[],
): boolean {
  return (
    left.length === right.length &&
    left.every(
      (cone, index) =>
        cone.type === right[index].type &&
        cone.dimension === right[index].dimension &&
        cone.label === right[index].label,
    )
  )
}

function coneViolation(
  values: readonly number[],
  cones: readonly HiddenFlowConeBlock[],
  dual: boolean,
): number {
  let offset = 0
  let maximum = 0
  for (const cone of cones) {
    const block = values.slice(offset, offset + cone.dimension)
    if (block.length !== cone.dimension) return Number.POSITIVE_INFINITY
    if (cone.type === 'zero') {
      if (!dual) maximum = Math.max(maximum, maximumAbsolute(block))
    } else if (cone.type === 'nonnegative') {
      maximum = Math.max(
        maximum,
        block.reduce(
          (violation, value) => Math.max(violation, Math.max(0, -value)),
          0,
        ),
      )
    } else {
      const head = block[0]
      const tailNorm = Math.hypot(...block.slice(1))
      maximum = Math.max(maximum, Math.max(0, tailNorm - head))
    }
    offset += cone.dimension
  }
  return offset === values.length ? maximum : Number.POSITIVE_INFINITY
}

function independentSingularValues(
  matrix: DenseMatrix,
): readonly number[] {
  const gram = Array<number>(matrix.columns * matrix.columns).fill(0)
  for (let left = 0; left < matrix.columns; left += 1) {
    for (let right = 0; right < matrix.columns; right += 1) {
      let value = 0
      for (let row = 0; row < matrix.rows; row += 1) {
        value +=
          matrix.values[matrixIndex(matrix.columns, row, left)] *
          matrix.values[matrixIndex(matrix.columns, row, right)]
      }
      gram[matrixIndex(matrix.columns, left, right)] = value
    }
  }
  const eigenvalues = Array.from(
    hiddenFlowSymmetricEigenvalues(gram, matrix.columns),
  ).sort((left, right) => right - left)
  return eigenvalues
    .slice(0, Math.min(matrix.rows, matrix.columns))
    .map((value) => Math.sqrt(Math.max(0, value)))
}

function independentMatrixRank(
  matrix: DenseMatrix,
  threshold: number,
): number {
  const values = [...matrix.values]
  const rowCount = matrix.rows
  const columnCount = matrix.columns
  let rank = 0
  while (rank < rowCount && rank < columnCount) {
    let pivotRow = -1
    let pivotColumn = -1
    let pivotMagnitude = 0
    for (let row = rank; row < rowCount; row += 1) {
      for (let column = rank; column < columnCount; column += 1) {
        const magnitude = Math.abs(
          values[matrixIndex(columnCount, row, column)],
        )
        if (magnitude > pivotMagnitude) {
          pivotMagnitude = magnitude
          pivotRow = row
          pivotColumn = column
        }
      }
    }
    if (pivotMagnitude <= threshold) break
    if (pivotRow !== rank) {
      for (let column = 0; column < columnCount; column += 1) {
        const left = matrixIndex(columnCount, rank, column)
        const right = matrixIndex(columnCount, pivotRow, column)
        const temporary = values[left]
        values[left] = values[right]
        values[right] = temporary
      }
    }
    if (pivotColumn !== rank) {
      for (let row = 0; row < rowCount; row += 1) {
        const left = matrixIndex(columnCount, row, rank)
        const right = matrixIndex(columnCount, row, pivotColumn)
        const temporary = values[left]
        values[left] = values[right]
        values[right] = temporary
      }
    }
    const pivot = values[matrixIndex(columnCount, rank, rank)]
    for (let row = rank + 1; row < rowCount; row += 1) {
      const factor =
        values[matrixIndex(columnCount, row, rank)] / pivot
      values[matrixIndex(columnCount, row, rank)] = 0
      for (let column = rank + 1; column < columnCount; column += 1) {
        values[matrixIndex(columnCount, row, column)] -=
          factor * values[matrixIndex(columnCount, rank, column)]
      }
    }
    rank += 1
  }
  return rank
}

export interface HiddenFlowIndependentObservationDiagnostics {
  singularValues: readonly number[]
  rank: number
  nullity: number
  threshold: number
  spectrumFloor: number
}

export function hiddenFlowIndependentObservationDiagnostics(
  matrix: DenseMatrix,
  relativeTolerance: number,
): HiddenFlowIndependentObservationDiagnostics {
  const singularValues = independentSingularValues(matrix)
  const maximum = singularValues[0] ?? 0
  const threshold = Math.max(
    relativeTolerance * maximum,
    128 * Number.EPSILON * Math.max(maximum, 1),
  )
  const rank = independentMatrixRank(matrix, threshold)
  return {
    singularValues,
    rank,
    nullity: matrix.columns - rank,
    threshold,
    spectrumFloor:
      Math.sqrt(Number.EPSILON) * Math.max(maximum, 1) * 4,
  }
}

function verifySvd(
  request: HiddenFlowSupportRequest,
  result: HiddenFlowSolverResult,
  absoluteTolerance: number,
  relativeTolerance: number,
): string | null {
  const diagnostics = hiddenFlowIndependentObservationDiagnostics(
    request.observationMatrix,
    request.rankRelativeTolerance,
  )
  const expected = diagnostics.singularValues
  const maximum = expected[0] ?? 0
  const { threshold, rank, spectrumFloor } = diagnostics
  const spectrumViolation = expected.reduce((current, value, index) => {
    const reported = result.svd.singularValues[index]
    return Math.max(value, reported) <= spectrumFloor
      ? current
      : Math.max(current, Math.abs(value - reported))
  }, 0)
  const allowed = tolerance(
    absoluteTolerance,
    relativeTolerance,
    maximum,
    matrixScale(request.observationMatrix),
  )
  if (Math.abs(result.svd.threshold - threshold) > allowed) {
    return 'The returned SVD threshold does not match the declared rule.'
  }
  if (
    result.svd.rank !== rank ||
    result.svd.nullity !== request.coefficientCount - rank
  ) {
    return (
      'The direct SVD and independent complete-pivoting rank estimators '
      + 'disagree at the declared threshold.'
    )
  }
  if (spectrumViolation > allowed) {
    return (
      'The returned singular spectrum disagrees with the independent '
      + 'A-transpose-A check above its square-root-epsilon floor.'
    )
  }
  const expectedCondition =
    rank === 0
      ? null
      : result.svd.singularValues[0] /
        result.svd.singularValues[rank - 1]
  if (
    (expectedCondition === null) !==
      (result.svd.conditionEstimate === null) ||
    (expectedCondition !== null &&
      result.svd.conditionEstimate !== null &&
      Math.abs(expectedCondition - result.svd.conditionEstimate) > allowed)
  ) {
    return 'The returned SVD condition estimate is inconsistent with its spectrum.'
  }
  const nullBasis = result.svd.nullSpaceBasis
  let nullViolation = 0
  for (let column = 0; column < nullBasis.columns; column += 1) {
    const vector = Array.from(
      { length: nullBasis.rows },
      (_, row) =>
        nullBasis.values[matrixIndex(nullBasis.columns, row, column)],
    )
    nullViolation = Math.max(
      nullViolation,
      maximumAbsolute(matrixVector(request.observationMatrix, vector)),
    )
    for (
      let otherColumn = 0;
      otherColumn < nullBasis.columns;
      otherColumn += 1
    ) {
      const other = Array.from(
        { length: nullBasis.rows },
        (_, row) =>
          nullBasis.values[
            matrixIndex(nullBasis.columns, row, otherColumn)
          ],
      )
      nullViolation = Math.max(
        nullViolation,
        Math.abs(dot(vector, other) - (column === otherColumn ? 1 : 0)),
      )
    }
  }
  return nullViolation <= allowed
    ? null
    : 'The returned null-space basis fails residual or orthonormality checks.'
}

function maximumObservationViolation(
  compiled: HiddenFlowCompiledProblem,
  coefficients: readonly number[],
): {
  maximum: number
  active: readonly string[]
} {
  const values = matrixVector(
    compiled.observations.observationMatrix,
    coefficients,
  )
  let maximum = 0
  const active: string[] = []
  const absoluteTolerance =
    compiled.problem.numerics.verificationAbsoluteTolerance
  const relativeTolerance =
    compiled.problem.numerics.verificationRelativeTolerance
  for (let index = 0; index < values.length; index += 1) {
    const lower = compiled.observations.lowerBounds[index]
    const upper = compiled.observations.upperBounds[index]
    maximum = Math.max(
      maximum,
      Math.max(0, lower - values[index], values[index] - upper),
    )
    const allowed = tolerance(
      absoluteTolerance,
      relativeTolerance,
      lower,
      upper,
      values[index],
    )
    if (
      Math.abs(values[index] - lower) <= allowed ||
      Math.abs(values[index] - upper) <= allowed
    ) {
      active.push(compiled.problem.observations[index].id)
    }
  }
  return { maximum, active }
}

export function hiddenFlowCandidateMaximumDivergence(
  compiled: HiddenFlowCompiledProblem,
  coefficients: readonly number[],
): number {
  const domain = compiled.problem.domain
  const xCellCount = domain.xEdges.length - 1
  const yCellCount = domain.yEdges.length - 1
  let maximum = 0
  for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) {
    for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
      const cellIndex = xIndex + xCellCount * yIndex
      if (!domain.validCellMask[cellIndex]) continue
      const xMinimum = domain.xEdges[xIndex]
      const xMaximum = domain.xEdges[xIndex + 1]
      const yMinimum = domain.yEdges[yIndex]
      const yMaximum = domain.yEdges[yIndex + 1]
      for (const yFraction of [0.25, 0.5, 0.75]) {
        for (const xFraction of [0.25, 0.5, 0.75]) {
          const evaluation = evaluateHiddenFlowBasisAtPoint(compiled.basis, {
            x: xMinimum + xFraction * (xMaximum - xMinimum),
            y: yMinimum + yFraction * (yMaximum - yMinimum),
          })
          maximum = Math.max(
            maximum,
            Math.abs(dot(evaluation.divergence, coefficients)),
          )
        }
      }
    }
  }
  return maximum
}

function failed(detail: string): HiddenFlowVerificationSummary {
  return {
    accepted: false,
    state: 'failed',
    detail,
    objectiveValue: null,
    rigorousObjectiveUpperBound: null,
    approximateDualUpperDiagnostic: null,
    upperBoundQualification: 'not-applicable',
    observationMaximumViolation: null,
    activeObservationConstraints: [],
    velocityRms: null,
    velocityGradientRms: null,
    maximumVerificationDivergence: null,
    primalResidual: null,
    dualResidual: null,
    absoluteGap: null,
    relativeGap: null,
    coneViolation: null,
    numericalEvidenceQualification: 'not-applicable',
  }
}

function stateDetail(state: HiddenFlowEvidenceState): string {
  if (state === 'verified-optimal-within-tolerance') {
    return 'The feasible candidate and approximate dual diagnostics independently satisfy the declared numerical tolerances for this finite conic problem; no rigorous objective upper bound is established.'
  }
  if (state === 'approximate-candidate') {
    return 'A primal-feasible candidate was found, but the native solver status or dual evidence does not support a verified optimum.'
  }
  if (state === 'verified-infeasible-within-tolerance') {
    return 'The returned dual ray independently satisfies the declared numerical infeasibility checks.'
  }
  if (state === 'verified-unbounded-within-tolerance') {
    return 'The returned primal ray independently satisfies the declared numerical unboundedness checks.'
  }
  if (state === 'full-observation-zero-nullity') {
    return 'The exact zero-residual observation operator has zero numerical nullity in the declared basis.'
  }
  if (state === 'degenerate-objective') {
    return 'The declared target row is numerically zero in the retained basis, so no optimizer result is presented.'
  }
  return 'The solver result did not support an accepted evidence state.'
}

function settingsEqual(
  left: HiddenFlowSupportRequest['solverSettings'],
  right: HiddenFlowSolverResult['settings'],
): boolean {
  return (
    left.maximumIterations === right.maximumIterations &&
    left.absoluteGapTolerance === right.absoluteGapTolerance &&
    left.relativeGapTolerance === right.relativeGapTolerance &&
    left.feasibilityTolerance === right.feasibilityTolerance &&
    left.infeasibilityTolerance === right.infeasibilityTolerance &&
    left.presolveEnabled === right.presolveEnabled &&
    left.equilibrationEnabled === right.equilibrationEnabled &&
    left.iterativeRefinementEnabled ===
      right.iterativeRefinementEnabled &&
    left.maximumThreads === right.maximumThreads
  )
}

export function verifyHiddenFlowSupportResult(
  compiled: HiddenFlowCompiledProblem,
  request: HiddenFlowSupportRequest,
  solverResult: HiddenFlowSolverResult,
  hashes: HiddenFlowHashVerification,
): HiddenFlowSupportResult {
  const absoluteTolerance =
    compiled.problem.numerics.verificationAbsoluteTolerance
  const relativeTolerance =
    compiled.problem.numerics.verificationRelativeTolerance
  if (!hashes.requestMatches || !hashes.canonicalMatches) {
    return {
      request,
      solverResult,
      verification: failed('Request or canonical solver-data hash mismatch.'),
    }
  }
  if (
    !settingsEqual(request.solverSettings, solverResult.settings) ||
    solverResult.requestId !== request.requestId
  ) {
    return {
      request,
      solverResult,
      verification: failed('Solver settings or request identity changed.'),
    }
  }
  const factorViolation = Math.max(
    verifyFactor(
      solverResult.canonicalization.energyFactor,
      request.energyMatrix,
      request.energyBudget !== null,
      absoluteTolerance,
      relativeTolerance,
    ),
    verifyFactor(
      solverResult.canonicalization.roughnessFactor,
      request.roughnessMatrix,
      request.roughnessBudget !== null,
      absoluteTolerance,
      relativeTolerance,
    ),
  )
  if (!Number.isFinite(factorViolation)) {
    return {
      request,
      solverResult,
      verification: failed(
        'A returned quadratic factor does not reconstruct the declared matrix.',
      ),
    }
  }
  const expected = expectedCanonicalization(
    request,
    solverResult.canonicalization.energyFactor,
    solverResult.canonicalization.roughnessFactor,
  )
  const canonicalTolerance = tolerance(
    absoluteTolerance,
    relativeTolerance,
    matrixScale(expected.a),
    maximumAbsolute(expected.b),
    maximumAbsolute(expected.q),
  )
  if (
    !conesEqual(expected.cones, solverResult.canonicalization.cones) ||
    differenceMaximum(expected.q, solverResult.canonicalization.q) >
      canonicalTolerance ||
    differenceMaximum(expected.b, solverResult.canonicalization.b) >
      canonicalTolerance ||
    differenceMaximum(
      expected.a.values,
      solverResult.canonicalization.a.values,
    ) > canonicalTolerance
  ) {
    return {
      request,
      solverResult,
      verification: failed(
        'The returned conic form does not match the declared observations, budgets, and target.',
      ),
    }
  }
  const svdFailure = verifySvd(
    request,
    solverResult,
    absoluteTolerance,
    relativeTolerance,
  )
  if (svdFailure !== null) {
    return {
      request,
      solverResult,
      verification: failed(
        svdFailure,
      ),
    }
  }

  const solution = solverResult.solution
  const canonical = solverResult.canonicalization
  const primalTolerance = tolerance(
    absoluteTolerance,
    relativeTolerance,
    matrixScale(canonical.a),
    maximumAbsolute(canonical.b),
    maximumAbsolute(solution.coefficients),
  )
  const originalConstraintTolerance = tolerance(
    absoluteTolerance,
    relativeTolerance,
    matrixScale(request.observationMatrix),
    maximumAbsolute(request.lowerBounds),
    maximumAbsolute(request.upperBounds),
    request.energyBudget ?? 0,
    request.roughnessBudget ?? 0,
  )
  const dualTolerance = tolerance(
    absoluteTolerance,
    relativeTolerance,
    matrixScale(canonical.a),
    maximumAbsolute(canonical.q),
    maximumAbsolute(solution.dual),
  )
  const computedSlacks = matrixVector(canonical.a, solution.coefficients).map(
    (value, index) => canonical.b[index] - value,
  )
  const slackMismatch = differenceMaximum(computedSlacks, solution.slacks)
  const primalResidual = slackMismatch
  const primalConeViolation = coneViolation(
    solution.slacks,
    canonical.cones,
    false,
  )
  const transposedDual = transposeMatrixVector(
    canonical.a,
    solution.dual,
  )
  const dualVector = transposedDual.map(
    (value, index) => value + canonical.q[index],
  )
  const dualResidual = maximumAbsolute(dualVector)
  const infeasibilityDualResidual = maximumAbsolute(transposedDual)
  const dualConeViolation = coneViolation(
    solution.dual,
    canonical.cones,
    true,
  )
  const coneMaximum = Math.max(primalConeViolation, dualConeViolation)
  const primalObjective = dot(canonical.q, solution.coefficients)
  const dualObjective = -dot(canonical.b, solution.dual)
  const absoluteGap = primalObjective - dualObjective
  const relativeGap =
    Math.abs(absoluteGap) /
    Math.max(Math.abs(primalObjective), Math.abs(dualObjective), 1)
  const objectiveValue = dot(request.objective, solution.coefficients)
  const unboundedPrimalResidual = maximumAbsolute(
    matrixVector(canonical.a, solution.coefficients).map(
      (value, index) => value + solution.slacks[index],
    ),
  )
  const observation = maximumObservationViolation(
    compiled,
    solution.coefficients,
  )
  const energyValue = Math.sqrt(
    Math.max(0, quadratic(request.energyMatrix, solution.coefficients)),
  )
  const roughnessValue = Math.sqrt(
    Math.max(0, quadratic(request.roughnessMatrix, solution.coefficients)),
  )
  const divergence = hiddenFlowCandidateMaximumDivergence(
    compiled,
    solution.coefficients,
  )
  const energyViolation =
    request.energyBudget === null
      ? 0
      : Math.max(0, energyValue - request.energyBudget)
  const roughnessViolation =
    request.roughnessBudget === null
      ? 0
      : Math.max(0, roughnessValue - request.roughnessBudget)
  const originalFeasible =
    observation.maximum <= originalConstraintTolerance &&
    energyViolation <= originalConstraintTolerance &&
    roughnessViolation <= originalConstraintTolerance &&
    divergence <= originalConstraintTolerance
  const objectiveEvidenceMatches =
    (solution.primalObjective === null ||
      Math.abs(solution.primalObjective - primalObjective) <=
        primalTolerance) &&
    (solution.dualObjective === null ||
      Math.abs(solution.dualObjective - dualObjective) <= dualTolerance)

  let state: HiddenFlowEvidenceState = 'failed'
  let accepted = false
  let qualification: HiddenFlowVerificationSummary['numericalEvidenceQualification'] =
    'not-applicable'

  const objectiveScale = maximumAbsolute(request.objective)
  const objectiveZero =
    objectiveScale <=
    128 * Number.EPSILON * Math.max(objectiveScale, 1)
  const exactZeroObservations =
    request.lowerBounds.every(
      (value, index) =>
        value === 0 && request.upperBounds[index] === 0,
    )
  const coefficientScale = maximumAbsolute(solution.coefficients)

  if (
    solution.status === 'PrimalInfeasible' ||
    solution.status === 'AlmostPrimalInfeasible'
  ) {
    const rayResidual = infeasibilityDualResidual
    const rayConeViolation = dualConeViolation
    const raySeparation = dot(canonical.b, solution.dual)
    if (
      solution.status === 'PrimalInfeasible' &&
      rayResidual <= dualTolerance &&
      rayConeViolation <= dualTolerance &&
      raySeparation < -dualTolerance
    ) {
      state = 'verified-infeasible-within-tolerance'
      accepted = true
      qualification = 'verified-to-declared-tolerances'
    }
  } else if (
    solution.status === 'DualInfeasible' ||
    solution.status === 'AlmostDualInfeasible'
  ) {
    const rayObjective = dot(canonical.q, solution.coefficients)
    if (
      solution.status === 'DualInfeasible' &&
      unboundedPrimalResidual <= primalTolerance &&
      primalConeViolation <= primalTolerance &&
      rayObjective < -primalTolerance
    ) {
      state = 'verified-unbounded-within-tolerance'
      accepted = true
      qualification = 'verified-to-declared-tolerances'
    }
  } else if (
    originalFeasible &&
    slackMismatch <= primalTolerance &&
    objectiveEvidenceMatches
  ) {
    if (
      solverResult.svd.nullity === 0 &&
      exactZeroObservations &&
      coefficientScale <= primalTolerance
    ) {
      state = 'full-observation-zero-nullity'
      accepted = true
      qualification = 'verified-to-declared-tolerances'
    } else if (
      objectiveZero &&
      solution.status === 'Solved' &&
      primalConeViolation <= primalTolerance &&
      solverResult.warnings.some((warning) =>
        warning.startsWith('Degenerate objective:'),
      )
    ) {
      state = 'degenerate-objective'
      accepted = true
      qualification = 'verified-to-declared-tolerances'
    } else if (
      solution.status === 'Solved' &&
      primalConeViolation <= primalTolerance &&
      dualResidual <= dualTolerance &&
      dualConeViolation <= dualTolerance &&
      absoluteGap >= -dualTolerance &&
      absoluteGap <=
        Math.max(
          solverResult.settings.absoluteGapTolerance,
          solverResult.settings.relativeGapTolerance *
            Math.max(Math.abs(primalObjective), Math.abs(dualObjective), 1),
          primalTolerance,
          dualTolerance,
        )
    ) {
      state = 'verified-optimal-within-tolerance'
      accepted = true
      qualification = 'verified-to-declared-tolerances'
    } else if (
      solution.status === 'AlmostSolved' ||
      solution.status === 'MaxIterations' ||
      solution.status === 'MaxTime' ||
      solution.status === 'InsufficientProgress'
    ) {
      state = 'approximate-candidate'
      accepted = true
      qualification = 'candidate-only'
    }
  }

  const verification: HiddenFlowVerificationSummary = {
    accepted,
    state,
    detail: stateDetail(state),
    objectiveValue:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance' ||
      state === 'degenerate-objective'
        ? null
        : state === 'full-observation-zero-nullity'
          ? 0
        : objectiveValue,
    rigorousObjectiveUpperBound: null,
    approximateDualUpperDiagnostic:
      !accepted ||
      solution.dualObjective === null ||
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : -dualObjective,
    upperBoundQualification:
      state === 'verified-optimal-within-tolerance' ||
      state === 'approximate-candidate' ||
      state === 'full-observation-zero-nullity' ||
      state === 'degenerate-objective'
        ? 'unavailable-no-rigorous-dual-certificate'
        : 'not-applicable',
    observationMaximumViolation:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : observation.maximum,
    activeObservationConstraints: observation.active,
    velocityRms:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : energyValue,
    velocityGradientRms:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : roughnessValue,
    maximumVerificationDivergence:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : divergence,
    primalResidual:
      state === 'verified-infeasible-within-tolerance'
        ? null
        : state === 'verified-unbounded-within-tolerance'
          ? unboundedPrimalResidual
          : primalResidual,
    dualResidual:
      state === 'verified-infeasible-within-tolerance'
        ? infeasibilityDualResidual
        : state === 'verified-unbounded-within-tolerance'
          ? null
          : dualResidual,
    absoluteGap:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : absoluteGap,
    relativeGap:
      state === 'verified-infeasible-within-tolerance' ||
      state === 'verified-unbounded-within-tolerance'
        ? null
        : relativeGap,
    coneViolation:
      state === 'verified-infeasible-within-tolerance'
        ? dualConeViolation
        : state === 'verified-unbounded-within-tolerance'
          ? primalConeViolation
          : coneMaximum,
    numericalEvidenceQualification: qualification,
  }

  return { request, solverResult, verification }
}

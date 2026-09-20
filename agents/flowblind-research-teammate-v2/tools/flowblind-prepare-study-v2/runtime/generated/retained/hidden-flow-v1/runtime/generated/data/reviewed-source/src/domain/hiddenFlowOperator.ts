import {
  evaluateHiddenFlowBasisAtPoint,
  hiddenFlowCellIndexAtPoint,
  hiddenFlowRegionComponentRow,
} from './hiddenFlowBasis'
import {
  type DenseMatrix,
  type HiddenFlowCompiledBasis,
  type HiddenFlowCompiledProblem,
  type HiddenFlowCompiledTarget,
  type HiddenFlowObservation,
  type HiddenFlowProblem,
  type HiddenFlowSolverSettings,
  type HiddenFlowSupportRequest,
  type HiddenFlowTarget,
} from './hiddenFlowModel'

function combineRows(
  first: readonly number[],
  second: readonly number[],
  firstScale: number,
  secondScale: number,
): readonly number[] {
  if (first.length !== second.length) {
    throw new Error('Basis rows must have the same length.')
  }
  return first.map(
    (value, index) => firstScale * value + secondScale * second[index],
  )
}

export function compileHiddenFlowPointVelocityRow(
  basis: HiddenFlowCompiledBasis,
  point: { x: number; y: number },
  component: 'x' | 'y',
): readonly number[] {
  const evaluation = evaluateHiddenFlowBasisAtPoint(basis, point)
  return component === 'x' ? evaluation.u : evaluation.v
}

function pointDirectionRow(
  basis: HiddenFlowCompiledBasis,
  point: { x: number; y: number },
  direction: readonly [number, number],
): readonly number[] {
  const evaluation = evaluateHiddenFlowBasisAtPoint(basis, point)
  return combineRows(
    evaluation.u,
    evaluation.v,
    direction[0],
    direction[1],
  )
}

export function compileHiddenFlowObservationRow(
  basis: HiddenFlowCompiledBasis,
  observation: HiddenFlowObservation,
): readonly number[] {
  return observation.type === 'point-component'
    ? compileHiddenFlowPointVelocityRow(
        basis,
        observation.point,
        observation.component,
      )
    : pointDirectionRow(basis, observation.point, observation.direction)
}

function ensurePointInDomain(
  problem: HiddenFlowProblem,
  point: { x: number; y: number },
  label: string,
): void {
  if (hiddenFlowCellIndexAtPoint(problem.domain, point) === null) {
    throw new Error(`${label} lies outside the declared valid-cell domain.`)
  }
}

function compileTarget(
  problem: HiddenFlowProblem,
  basis: HiddenFlowCompiledBasis,
  target: Exclude<HiddenFlowTarget, { type: 'point-speed-envelope' }>,
): HiddenFlowCompiledTarget {
  if (target.type === 'point-component') {
    ensurePointInDomain(problem, target.point, `Target ${target.id}`)
    return {
      id: target.id,
      title: target.title,
      type: target.type,
      objective: compileHiddenFlowPointVelocityRow(
        basis,
        target.point,
        target.component,
      ),
      unit: target.unit,
      direction: null,
    }
  }
  if (target.type === 'point-direction') {
    ensurePointInDomain(problem, target.point, `Target ${target.id}`)
    return {
      id: target.id,
      title: target.title,
      type: target.type,
      objective: pointDirectionRow(basis, target.point, target.direction),
      unit: target.unit,
      direction: target.direction,
    }
  }
  if (target.type === 'region-component') {
    const maximumCellIndex =
      (problem.domain.xEdges.length - 1) *
        (problem.domain.yEdges.length - 1) -
      1
    if (
      target.cellIndices.some(
        (cellIndex) => cellIndex < 0 || cellIndex > maximumCellIndex,
      )
    ) {
      throw new Error(`Target ${target.id} references a cell outside the domain.`)
    }
    return {
      id: target.id,
      title: target.title,
      type: target.type,
      objective: hiddenFlowRegionComponentRow(
        problem.domain,
        basis,
        target.cellIndices,
        target.component,
      ),
      unit: target.unit,
      direction: null,
    }
  }
  ensurePointInDomain(problem, target.point, `Target ${target.id}`)
  const evaluation = evaluateHiddenFlowBasisAtPoint(basis, target.point)
  const objective =
    target.component === 'xx'
      ? evaluation.duDx
      : target.component === 'yy'
        ? evaluation.dvDy
        : combineRows(evaluation.duDy, evaluation.dvDx, 0.5, 0.5)
  return {
    id: target.id,
    title: target.title,
    type: target.type,
    objective,
    unit: target.unit,
    direction: null,
  }
}

export function compileHiddenFlowLinearSystem(
  problem: HiddenFlowProblem,
  basis: HiddenFlowCompiledBasis,
): HiddenFlowCompiledProblem['observations'] {
  const rows: number[] = []
  const lowerBounds: number[] = []
  const upperBounds: number[] = []
  for (const observation of problem.observations) {
    ensurePointInDomain(
      problem,
      observation.point,
      `Observation ${observation.id}`,
    )
    for (const value of compileHiddenFlowObservationRow(basis, observation)) {
      rows.push(value)
    }
    const center = observation.observedValue - observation.baselineValue
    lowerBounds.push(center - observation.tolerance)
    upperBounds.push(center + observation.tolerance)
  }
  return {
    observationMatrix: {
      rows: problem.observations.length,
      columns: basis.functions.length,
      values: rows,
    },
    lowerBounds,
    upperBounds,
  }
}

export function compileHiddenFlowProblem(
  problem: HiddenFlowProblem,
  basis: HiddenFlowCompiledBasis,
  target: Exclude<HiddenFlowTarget, { type: 'point-speed-envelope' }>,
): HiddenFlowCompiledProblem {
  return {
    problem: { ...problem, target },
    basis,
    observations: compileHiddenFlowLinearSystem(problem, basis),
    target: compileTarget(problem, basis, target),
  }
}

export function hiddenFlowDirections(
  count: number,
): readonly (readonly [number, number])[] {
  if (!Number.isInteger(count) || count < 3) {
    throw new Error('Direction count must be an integer of at least three.')
  }
  return Array.from({ length: count }, (_, index) => {
    const angle = (2 * Math.PI * index) / count
    return [Math.cos(angle), Math.sin(angle)] as const
  })
}

export function compileHiddenFlowSpeedDirections(
  problem: HiddenFlowProblem,
  basis: HiddenFlowCompiledBasis,
): readonly HiddenFlowCompiledProblem[] {
  if (problem.target.type !== 'point-speed-envelope') {
    throw new Error('The problem target is not a point-speed envelope.')
  }
  const target = problem.target
  return hiddenFlowDirections(target.directionCount).map(
    (direction, index) =>
      compileHiddenFlowProblem(problem, basis, {
        type: 'point-direction',
        id: `${target.id}-direction-${index}`,
        title: `${target.title} direction ${index + 1}`,
        point: target.point,
        direction,
        unit: target.unit,
      }),
  )
}

export const DEFAULT_HIDDEN_FLOW_SOLVER_SETTINGS: HiddenFlowSolverSettings = {
  maximumIterations: 250,
  absoluteGapTolerance: 1e-9,
  relativeGapTolerance: 1e-9,
  feasibilityTolerance: 1e-9,
  infeasibilityTolerance: 1e-9,
  presolveEnabled: true,
  equilibrationEnabled: true,
  iterativeRefinementEnabled: true,
  maximumThreads: 1,
}

function squareMatrixCopy(matrix: DenseMatrix): DenseMatrix {
  return {
    rows: matrix.rows,
    columns: matrix.columns,
    values: [...matrix.values],
  }
}

export function createHiddenFlowSupportRequest(
  compiled: HiddenFlowCompiledProblem,
  requestId: string,
): HiddenFlowSupportRequest {
  return {
    schemaVersion: 1,
    requestId,
    problemId: compiled.problem.id,
    coefficientCount: compiled.basis.functions.length,
    observationMatrix: {
      rows: compiled.observations.observationMatrix.rows,
      columns: compiled.observations.observationMatrix.columns,
      values: [...compiled.observations.observationMatrix.values],
    },
    lowerBounds: [...compiled.observations.lowerBounds],
    upperBounds: [...compiled.observations.upperBounds],
    energyMatrix: squareMatrixCopy(compiled.basis.massMatrix),
    energyBudget: compiled.problem.budgets.velocityRms?.value ?? null,
    roughnessMatrix: squareMatrixCopy(compiled.basis.roughnessMatrix),
    roughnessBudget:
      compiled.problem.budgets.velocityGradientRms?.value ?? null,
    objective: [...compiled.target.objective],
    rankRelativeTolerance: compiled.problem.numerics.rankRelativeTolerance,
    solverSettings: {
      ...DEFAULT_HIDDEN_FLOW_SOLVER_SETTINGS,
      maximumIterations: compiled.problem.numerics.maximumSolverIterations,
    },
  }
}

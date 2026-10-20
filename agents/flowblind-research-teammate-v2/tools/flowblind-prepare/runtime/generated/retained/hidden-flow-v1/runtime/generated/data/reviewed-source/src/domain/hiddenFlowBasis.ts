import {
  type DenseMatrix,
  type HiddenFlowBasisDiagnostics,
  type HiddenFlowBasisFunction,
  type HiddenFlowBasisSpec,
  type HiddenFlowCompiledBasis,
  type HiddenFlowDomain,
  type HiddenFlowMatrixDiagnostics,
  type HiddenFlowNumericalPolicy,
  type HiddenFlowPoint,
} from './hiddenFlowModel'

const GAUSS_NODES = [
  -0.8611363115940526,
  -0.3399810435848563,
  0.3399810435848563,
  0.8611363115940526,
] as const

const GAUSS_WEIGHTS = [
  0.34785484513745385,
  0.6521451548625461,
  0.6521451548625461,
  0.34785484513745385,
] as const

interface BasisEvaluation {
  u: number
  v: number
  duDx: number
  duDy: number
  dvDx: number
  dvDy: number
}

export interface HiddenFlowBasisPointEvaluation {
  u: readonly number[]
  v: readonly number[]
  duDx: readonly number[]
  duDy: readonly number[]
  dvDx: readonly number[]
  dvDy: readonly number[]
  divergence: readonly number[]
}

function matrixIndex(columns: number, row: number, column: number): number {
  return row * columns + column
}

function cellIndex(xCellCount: number, xIndex: number, yIndex: number): number {
  return xIndex + xCellCount * yIndex
}

export function evaluateCardinalCubic(value: number): {
  value: number
  first: number
  second: number
} {
  const absolute = Math.abs(value)
  if (absolute >= 2) return { value: 0, first: 0, second: 0 }
  if (absolute < 1) {
    return {
      value: 2 / 3 - absolute * absolute + (absolute ** 3) / 2,
      first: -2 * value + 1.5 * value * absolute,
      second: -2 + 3 * absolute,
    }
  }
  const remaining = 2 - absolute
  return {
    value: (remaining ** 3) / 6,
    first: -0.5 * Math.sign(value) * remaining * remaining,
    second: remaining,
  }
}

function rawBasisEvaluation(
  center: HiddenFlowPoint,
  spacingX: number,
  spacingY: number,
  streamfunctionLengthScale: number,
  point: HiddenFlowPoint,
): BasisEvaluation {
  const x = evaluateCardinalCubic((point.x - center.x) / spacingX)
  const y = evaluateCardinalCubic((point.y - center.y) / spacingY)
  const common = streamfunctionLengthScale
  const mixed = common / (spacingX * spacingY)
  return {
    u: (common / spacingY) * x.value * y.first,
    v: -(common / spacingX) * x.first * y.value,
    duDx: mixed * x.first * y.first,
    duDy: (common / (spacingY * spacingY)) * x.value * y.second,
    dvDx: -(common / (spacingX * spacingX)) * x.second * y.value,
    dvDy: -mixed * x.first * y.first,
  }
}

function normalizedBasisEvaluation(
  basis: HiddenFlowBasisFunction,
  point: HiddenFlowPoint,
): BasisEvaluation {
  const raw = rawBasisEvaluation(
    basis.center,
    basis.spacingX,
    basis.spacingY,
    basis.streamfunctionLengthScale,
    point,
  )
  const scale = basis.velocityNormalization
  return {
    u: raw.u / scale,
    v: raw.v / scale,
    duDx: raw.duDx / scale,
    duDy: raw.duDy / scale,
    dvDx: raw.dvDx / scale,
    dvDy: raw.dvDy / scale,
  }
}

function erodedMask(
  domain: HiddenFlowDomain,
  margin: number,
): readonly boolean[] {
  const xCellCount = domain.xEdges.length - 1
  const yCellCount = domain.yEdges.length - 1
  return domain.validCellMask.map((valid, index) => {
    if (!valid) return false
    const xIndex = index % xCellCount
    const yIndex = Math.floor(index / xCellCount)
    for (let yOffset = -margin; yOffset <= margin; yOffset += 1) {
      for (let xOffset = -margin; xOffset <= margin; xOffset += 1) {
        const candidateX = xIndex + xOffset
        const candidateY = yIndex + yOffset
        if (
          candidateX < 0 ||
          candidateX >= xCellCount ||
          candidateY < 0 ||
          candidateY >= yCellCount ||
          !domain.validCellMask[
            cellIndex(xCellCount, candidateX, candidateY)
          ]
        ) {
          return false
        }
      }
    }
    return true
  })
}

function supportInsideDomain(
  support: HiddenFlowBasisFunction['support'],
  domain: HiddenFlowDomain,
  admissibleMask: readonly boolean[],
): boolean {
  const xMinimum = domain.xEdges[0]
  const xMaximum = domain.xEdges[domain.xEdges.length - 1]
  const yMinimum = domain.yEdges[0]
  const yMaximum = domain.yEdges[domain.yEdges.length - 1]
  const scale = Math.max(
    Math.abs(xMinimum),
    Math.abs(xMaximum),
    Math.abs(yMinimum),
    Math.abs(yMaximum),
    1,
  )
  const epsilon = 128 * Number.EPSILON * scale
  if (
    support.xMinimum <= xMinimum + epsilon ||
    support.xMaximum >= xMaximum - epsilon ||
    support.yMinimum <= yMinimum + epsilon ||
    support.yMaximum >= yMaximum - epsilon
  ) {
    return false
  }
  const xCellCount = domain.xEdges.length - 1
  const yCellCount = domain.yEdges.length - 1
  let intersected = false
  for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) {
    const cellYMinimum = domain.yEdges[yIndex]
    const cellYMaximum = domain.yEdges[yIndex + 1]
    if (
      cellYMaximum <= support.yMinimum + epsilon ||
      cellYMinimum >= support.yMaximum - epsilon
    ) {
      continue
    }
    for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
      const cellXMinimum = domain.xEdges[xIndex]
      const cellXMaximum = domain.xEdges[xIndex + 1]
      if (
        cellXMaximum <= support.xMinimum + epsilon ||
        cellXMinimum >= support.xMaximum - epsilon
      ) {
        continue
      }
      intersected = true
      if (!admissibleMask[cellIndex(xCellCount, xIndex, yIndex)]) {
        return false
      }
    }
  }
  return intersected
}

function validCells(
  domain: HiddenFlowDomain,
): readonly {
  xMinimum: number
  xMaximum: number
  yMinimum: number
  yMaximum: number
  area: number
}[] {
  const xCellCount = domain.xEdges.length - 1
  const yCellCount = domain.yEdges.length - 1
  const cells = []
  for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) {
    for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
      if (!domain.validCellMask[cellIndex(xCellCount, xIndex, yIndex)]) {
        continue
      }
      const xMinimum = domain.xEdges[xIndex]
      const xMaximum = domain.xEdges[xIndex + 1]
      const yMinimum = domain.yEdges[yIndex]
      const yMaximum = domain.yEdges[yIndex + 1]
      cells.push({
        xMinimum,
        xMaximum,
        yMinimum,
        yMaximum,
        area: (xMaximum - xMinimum) * (yMaximum - yMinimum),
      })
    }
  }
  return cells
}

function quadraturePoints(
  cell: ReturnType<typeof validCells>[number],
): readonly { point: HiddenFlowPoint; weight: number }[] {
  const halfWidth = (cell.xMaximum - cell.xMinimum) / 2
  const halfHeight = (cell.yMaximum - cell.yMinimum) / 2
  const centerX = (cell.xMinimum + cell.xMaximum) / 2
  const centerY = (cell.yMinimum + cell.yMaximum) / 2
  const jacobian = halfWidth * halfHeight
  const points = []
  for (let yIndex = 0; yIndex < GAUSS_NODES.length; yIndex += 1) {
    for (let xIndex = 0; xIndex < GAUSS_NODES.length; xIndex += 1) {
      points.push({
        point: {
          x: centerX + halfWidth * GAUSS_NODES[xIndex],
          y: centerY + halfHeight * GAUSS_NODES[yIndex],
        },
        weight:
          jacobian * GAUSS_WEIGHTS[xIndex] * GAUSS_WEIGHTS[yIndex],
      })
    }
  }
  return points
}

export function hiddenFlowSymmetricEigenvalues(
  matrix: readonly number[],
  dimension: number,
): readonly number[] {
  if (dimension === 0) return []
  const values = [...matrix]
  const norm = Math.max(
    1,
    ...Array.from({ length: dimension }, (_, row) =>
      Math.abs(values[matrixIndex(dimension, row, row)]),
    ),
  )
  const tolerance = 64 * Number.EPSILON * norm
  const maximumSweeps = 64
  for (let sweep = 0; sweep < maximumSweeps; sweep += 1) {
    let changed = false
    for (let p = 0; p < dimension - 1; p += 1) {
      for (let q = p + 1; q < dimension; q += 1) {
        const pqIndex = matrixIndex(dimension, p, q)
        const apq = values[pqIndex]
        if (Math.abs(apq) <= tolerance) continue
        changed = true
        const app = values[matrixIndex(dimension, p, p)]
        const aqq = values[matrixIndex(dimension, q, q)]
        const angle = 0.5 * Math.atan2(2 * apq, aqq - app)
        const cosine = Math.cos(angle)
        const sine = Math.sin(angle)
        for (let k = 0; k < dimension; k += 1) {
          if (k === p || k === q) continue
          const kpIndex = matrixIndex(dimension, k, p)
          const kqIndex = matrixIndex(dimension, k, q)
          const akp = values[kpIndex]
          const akq = values[kqIndex]
          const rotatedP = cosine * akp - sine * akq
          const rotatedQ = sine * akp + cosine * akq
          values[kpIndex] = rotatedP
          values[matrixIndex(dimension, p, k)] = rotatedP
          values[kqIndex] = rotatedQ
          values[matrixIndex(dimension, q, k)] = rotatedQ
        }
        values[matrixIndex(dimension, p, p)] =
          cosine * cosine * app -
          2 * sine * cosine * apq +
          sine * sine * aqq
        values[matrixIndex(dimension, q, q)] =
          sine * sine * app +
          2 * sine * cosine * apq +
          cosine * cosine * aqq
        values[pqIndex] = 0
        values[matrixIndex(dimension, q, p)] = 0
      }
    }
    if (!changed) break
  }
  return Array.from(
    { length: dimension },
    (_, index) => values[matrixIndex(dimension, index, index)],
  ).sort((left, right) => left - right)
}

function matrixDiagnostics(
  matrix: DenseMatrix,
  relativeTolerance: number,
): HiddenFlowMatrixDiagnostics {
  const eigenvalues = hiddenFlowSymmetricEigenvalues(
    matrix.values,
    matrix.rows,
  )
  const maximumEigenvalue = Math.max(...eigenvalues)
  const threshold = Math.max(
    relativeTolerance * Math.max(maximumEigenvalue, 1),
    128 * Number.EPSILON * Math.max(maximumEigenvalue, 1),
  )
  const positive = eigenvalues.filter((value) => value > threshold)
  return {
    rank: positive.length,
    conditionEstimate:
      positive.length === 0
        ? Number.POSITIVE_INFINITY
        : maximumEigenvalue / positive[0],
    minimumEigenvalue: eigenvalues[0],
    maximumEigenvalue,
    threshold,
  }
}

function integrateBasisMatrices(
  domain: HiddenFlowDomain,
  functions: readonly HiddenFlowBasisFunction[],
): {
  massMatrix: DenseMatrix
  roughnessMatrix: DenseMatrix
  maximumVerificationDivergence: number
  area: number
} {
  const dimension = functions.length
  const mass = Array<number>(dimension * dimension).fill(0)
  const roughness = Array<number>(dimension * dimension).fill(0)
  const cells = validCells(domain)
  const area = cells.reduce((sum, cell) => sum + cell.area, 0)
  let maximumVerificationDivergence = 0
  for (const cell of cells) {
    for (const quadrature of quadraturePoints(cell)) {
      const active: { index: number; value: BasisEvaluation }[] = []
      for (let index = 0; index < dimension; index += 1) {
        const basis = functions[index]
        if (
          quadrature.point.x <= basis.support.xMinimum ||
          quadrature.point.x >= basis.support.xMaximum ||
          quadrature.point.y <= basis.support.yMinimum ||
          quadrature.point.y >= basis.support.yMaximum
        ) {
          continue
        }
        const value = normalizedBasisEvaluation(basis, quadrature.point)
        const divergence = value.duDx + value.dvDy
        maximumVerificationDivergence = Math.max(
          maximumVerificationDivergence,
          Math.abs(divergence),
        )
        if (
          value.u !== 0 ||
          value.v !== 0 ||
          value.duDx !== 0 ||
          value.duDy !== 0 ||
          value.dvDx !== 0 ||
          value.dvDy !== 0
        ) {
          active.push({ index, value })
        }
      }
      for (const left of active) {
        for (const right of active) {
          const index = matrixIndex(dimension, left.index, right.index)
          mass[index] +=
            quadrature.weight *
            (left.value.u * right.value.u + left.value.v * right.value.v)
          roughness[index] +=
            quadrature.weight *
            (left.value.duDx * right.value.duDx +
              left.value.duDy * right.value.duDy +
              left.value.dvDx * right.value.dvDx +
              left.value.dvDy * right.value.dvDy)
        }
      }
    }
  }
  for (let index = 0; index < mass.length; index += 1) {
    mass[index] /= area
    roughness[index] /= area
  }
  return {
    massMatrix: { rows: dimension, columns: dimension, values: mass },
    roughnessMatrix: {
      rows: dimension,
      columns: dimension,
      values: roughness,
    },
    maximumVerificationDivergence,
    area,
  }
}

function rawVelocityRms(
  domain: HiddenFlowDomain,
  center: HiddenFlowPoint,
  spec: HiddenFlowBasisSpec,
): number {
  let integral = 0
  let area = 0
  for (const cell of validCells(domain)) {
    area += cell.area
    for (const quadrature of quadraturePoints(cell)) {
      const value = rawBasisEvaluation(
        center,
        spec.spacingX,
        spec.spacingY,
        spec.streamfunctionLengthScale,
        quadrature.point,
      )
      integral += quadrature.weight * (value.u * value.u + value.v * value.v)
    }
  }
  return Math.sqrt(integral / area)
}

export function compileHiddenFlowBasis(
  domain: HiddenFlowDomain,
  spec: HiddenFlowBasisSpec,
  numerics: HiddenFlowNumericalPolicy,
): HiddenFlowCompiledBasis {
  const admissibleMask = erodedMask(domain, spec.interiorMarginCells)
  const functions: HiddenFlowBasisFunction[] = []
  let rejectedSupportCount = 0
  for (const center of spec.centers) {
    const support = {
      xMinimum: center.point.x - 2 * spec.spacingX,
      xMaximum: center.point.x + 2 * spec.spacingX,
      yMinimum: center.point.y - 2 * spec.spacingY,
      yMaximum: center.point.y + 2 * spec.spacingY,
    }
    if (!supportInsideDomain(support, domain, admissibleMask)) {
      rejectedSupportCount += 1
      continue
    }
    const velocityNormalization = rawVelocityRms(domain, center.point, spec)
    if (
      !Number.isFinite(velocityNormalization) ||
      velocityNormalization <= numerics.verificationAbsoluteTolerance
    ) {
      throw new Error(
        `Basis function ${center.id} has zero or non-finite RMS velocity.`,
      )
    }
    functions.push({
      id: center.id,
      center: center.point,
      spacingX: spec.spacingX,
      spacingY: spec.spacingY,
      streamfunctionLengthScale: spec.streamfunctionLengthScale,
      velocityNormalization,
      support,
    })
  }
  if (functions.length === 0) {
    throw new Error(
      'The compact-interior boundary policy rejected every basis function.',
    )
  }
  const integrated = integrateBasisMatrices(domain, functions)
  const mass = matrixDiagnostics(
    integrated.massMatrix,
    numerics.rankRelativeTolerance,
  )
  const roughness = matrixDiagnostics(
    integrated.roughnessMatrix,
    numerics.rankRelativeTolerance,
  )
  const diagnostics: HiddenFlowBasisDiagnostics = {
    retainedCount: functions.length,
    rejectedSupportCount,
    domainArea: integrated.area,
    maximumVerificationDivergence:
      integrated.maximumVerificationDivergence,
    mass,
    roughness,
  }
  for (const [label, result] of [
    ['mass', mass],
    ['roughness', roughness],
  ] as const) {
    if (
      result.rank !== functions.length ||
      result.minimumEigenvalue < -result.threshold ||
      !Number.isFinite(result.conditionEstimate) ||
      result.conditionEstimate > numerics.basisConditionLimit
    ) {
      throw new Error(
        `The ${label} matrix is singular, indefinite, or ill-conditioned: rank ${result.rank}/${functions.length}, condition ${result.conditionEstimate}.`,
      )
    }
  }
  return {
    spec,
    functions,
    massMatrix: integrated.massMatrix,
    roughnessMatrix: integrated.roughnessMatrix,
    diagnostics,
  }
}

export function evaluateHiddenFlowBasisAtPoint(
  basis: HiddenFlowCompiledBasis,
  point: HiddenFlowPoint,
): HiddenFlowBasisPointEvaluation {
  const evaluations = basis.functions.map((item) =>
    normalizedBasisEvaluation(item, point),
  )
  return {
    u: evaluations.map((item) => item.u),
    v: evaluations.map((item) => item.v),
    duDx: evaluations.map((item) => item.duDx),
    duDy: evaluations.map((item) => item.duDy),
    dvDx: evaluations.map((item) => item.dvDx),
    dvDy: evaluations.map((item) => item.dvDy),
    divergence: evaluations.map((item) => item.duDx + item.dvDy),
  }
}

export function hiddenFlowCellIndexAtPoint(
  domain: HiddenFlowDomain,
  point: HiddenFlowPoint,
): number | null {
  const xCellCount = domain.xEdges.length - 1
  const yCellCount = domain.yEdges.length - 1
  let xIndex = -1
  let yIndex = -1
  for (let index = 0; index < xCellCount; index += 1) {
    const last = index === xCellCount - 1
    if (
      point.x >= domain.xEdges[index] &&
      (point.x < domain.xEdges[index + 1] ||
        (last && point.x === domain.xEdges[index + 1]))
    ) {
      xIndex = index
      break
    }
  }
  for (let index = 0; index < yCellCount; index += 1) {
    const last = index === yCellCount - 1
    if (
      point.y >= domain.yEdges[index] &&
      (point.y < domain.yEdges[index + 1] ||
        (last && point.y === domain.yEdges[index + 1]))
    ) {
      yIndex = index
      break
    }
  }
  if (xIndex < 0 || yIndex < 0) return null
  const index = cellIndex(xCellCount, xIndex, yIndex)
  return domain.validCellMask[index] ? index : null
}

export function hiddenFlowRegionComponentRow(
  domain: HiddenFlowDomain,
  basis: HiddenFlowCompiledBasis,
  cellIndices: readonly number[],
  component: 'x' | 'y',
): readonly number[] {
  const selected = new Set(cellIndices)
  const xCellCount = domain.xEdges.length - 1
  const yCellCount = domain.yEdges.length - 1
  const row = Array<number>(basis.functions.length).fill(0)
  let selectedArea = 0
  for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) {
    for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
      const index = cellIndex(xCellCount, xIndex, yIndex)
      if (!selected.has(index) || !domain.validCellMask[index]) continue
      const cell = {
        xMinimum: domain.xEdges[xIndex],
        xMaximum: domain.xEdges[xIndex + 1],
        yMinimum: domain.yEdges[yIndex],
        yMaximum: domain.yEdges[yIndex + 1],
        area:
          (domain.xEdges[xIndex + 1] - domain.xEdges[xIndex]) *
          (domain.yEdges[yIndex + 1] - domain.yEdges[yIndex]),
      }
      selectedArea += cell.area
      for (const quadrature of quadraturePoints(cell)) {
        const values = evaluateHiddenFlowBasisAtPoint(basis, quadrature.point)
        const componentValues = component === 'x' ? values.u : values.v
        for (let basisIndex = 0; basisIndex < row.length; basisIndex += 1) {
          row[basisIndex] +=
            quadrature.weight * componentValues[basisIndex]
        }
      }
    }
  }
  if (selectedArea <= 0) {
    throw new Error('Region target does not contain any valid domain cell.')
  }
  return row.map((value) => value / selectedArea)
}

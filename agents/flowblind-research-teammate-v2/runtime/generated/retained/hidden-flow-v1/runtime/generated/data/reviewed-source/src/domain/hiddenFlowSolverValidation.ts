import {
  HIDDEN_FLOW_LIMITS,
  type DenseMatrix,
  type HiddenFlowCanonicalization,
  type HiddenFlowConeBlock,
  type HiddenFlowNativeSolverStatus,
  type HiddenFlowRawSolution,
  type HiddenFlowSolverIdentity,
  type HiddenFlowSolverResult,
  type HiddenFlowSolverSettings,
  type HiddenFlowSupportRequest,
  type HiddenFlowSvdDiagnostics,
} from './hiddenFlowModel'
import { validateDenseMatrix } from './hiddenFlowValidation'

type UnknownRecord = Record<string, unknown>

const SHA256 = /^[a-f0-9]{64}$/
const STATUSES: readonly HiddenFlowNativeSolverStatus[] = [
  'Unsolved',
  'Solved',
  'PrimalInfeasible',
  'DualInfeasible',
  'AlmostSolved',
  'AlmostPrimalInfeasible',
  'AlmostDualInfeasible',
  'MaxIterations',
  'MaxTime',
  'NumericalError',
  'InsufficientProgress',
  'CallbackTerminated',
  'Unknown',
]

function fail(path: string, detail: string): never {
  throw new Error(`${path}: ${detail}`)
}

function record(value: unknown, path: string): UnknownRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return fail(path, 'must be an object.')
  }
  return value as UnknownRecord
}

function exactKeys(
  value: UnknownRecord,
  required: readonly string[],
  path: string,
): void {
  const allowed = new Set(required)
  for (const key of required) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      fail(path, `is missing required property ${JSON.stringify(key)}.`)
    }
  }
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      fail(path, `contains unsupported property ${JSON.stringify(key)}.`)
    }
  }
}

function property(value: UnknownRecord, key: string): unknown {
  return value[key]
}

function finite(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return fail(path, 'must be finite.')
  }
  if (Math.abs(value) > HIDDEN_FLOW_LIMITS.maximumNumericMagnitude) {
    fail(path, 'exceeds the supported numerical magnitude.')
  }
  return value
}

function nullableFinite(value: unknown, path: string): number | null {
  return value === null ? null : finite(value, path)
}

function integer(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): number {
  const parsed = finite(value, path)
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    return fail(
      path,
      `must be an integer between ${minimum} and ${maximum}.`,
    )
  }
  return parsed
}

function text(value: unknown, path: string, maximum = 2_048): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > maximum
  ) {
    return fail(path, `must be nonempty text no longer than ${maximum}.`)
  }
  return value
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== 'boolean') return fail(path, 'must be a boolean.')
  return value
}

function finiteArray(
  value: unknown,
  path: string,
  expectedLength?: number,
): number[] {
  if (!Array.isArray(value)) return fail(path, 'must be an array.')
  if (expectedLength !== undefined && value.length !== expectedLength) {
    fail(path, `must contain exactly ${expectedLength} values.`)
  }
  return value.map((item, index) => finite(item, `${path}[${index}]`))
}

function stringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || value.length > 64) {
    return fail(path, 'must be an array with at most 64 entries.')
  }
  return value.map((item, index) => text(item, `${path}[${index}]`))
}

function digest(value: unknown, path: string): string {
  if (typeof value !== 'string' || !SHA256.test(value)) {
    return fail(path, 'must be a lowercase SHA-256 digest.')
  }
  return value
}

function parseMatrix(
  value: unknown,
  path: string,
  expectedRows?: number,
  expectedColumns?: number,
  maximumEntries = HIDDEN_FLOW_LIMITS.maximumMatrixEntries,
): DenseMatrix {
  const item = record(value, path)
  exactKeys(item, ['rows', 'columns', 'values'], path)
  const rows = integer(property(item, 'rows'), `${path}.rows`, 0, 1_024)
  const columns = integer(property(item, 'columns'), `${path}.columns`, 0, 96)
  if (expectedRows !== undefined && rows !== expectedRows) {
    fail(path, `must have ${expectedRows} rows.`)
  }
  if (expectedColumns !== undefined && columns !== expectedColumns) {
    fail(path, `must have ${expectedColumns} columns.`)
  }
  const entries = rows * columns
  if (entries > maximumEntries) {
    fail(
      path,
      `must contain exactly ${entries} entries within the matrix resource limit.`,
    )
  }
  const rawValues = property(item, 'values')
  if (!Array.isArray(rawValues) || rawValues.length !== entries) {
    fail(path, `must contain exactly ${entries} entries.`)
  }
  const matrix: DenseMatrix = {
    rows,
    columns,
    values: rawValues.map((item, index) =>
      finite(item, `${path}.values[${index}]`),
    ),
  }
  validateDenseMatrix(
    matrix,
    path,
    expectedRows,
    expectedColumns,
    maximumEntries,
  )
  return matrix
}

function parseSettings(
  value: unknown,
  path: string,
): HiddenFlowSolverSettings {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'maximumIterations',
      'absoluteGapTolerance',
      'relativeGapTolerance',
      'feasibilityTolerance',
      'infeasibilityTolerance',
      'presolveEnabled',
      'equilibrationEnabled',
      'iterativeRefinementEnabled',
      'maximumThreads',
    ],
    path,
  )
  const positive = (key: string) => {
    const parsed = finite(property(item, key), `${path}.${key}`)
    if (parsed <= 0 || parsed > 1) {
      fail(`${path}.${key}`, 'must lie in (0, 1].')
    }
    return parsed
  }
  integer(
    property(item, 'maximumThreads'),
    `${path}.maximumThreads`,
    1,
    1,
  )
  return {
    maximumIterations: integer(
      property(item, 'maximumIterations'),
      `${path}.maximumIterations`,
      1,
      100_000,
    ),
    absoluteGapTolerance: positive('absoluteGapTolerance'),
    relativeGapTolerance: positive('relativeGapTolerance'),
    feasibilityTolerance: positive('feasibilityTolerance'),
    infeasibilityTolerance: positive('infeasibilityTolerance'),
    presolveEnabled: boolean(
      property(item, 'presolveEnabled'),
      `${path}.presolveEnabled`,
    ),
    equilibrationEnabled: boolean(
      property(item, 'equilibrationEnabled'),
      `${path}.equilibrationEnabled`,
    ),
    iterativeRefinementEnabled: boolean(
      property(item, 'iterativeRefinementEnabled'),
      `${path}.iterativeRefinementEnabled`,
    ),
    maximumThreads: 1,
  }
}

function parseSolver(
  value: unknown,
  path: string,
): HiddenFlowSolverIdentity {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'adapter',
      'adapterVersion',
      'pythonVersion',
      'clarabelVersion',
      'scipyVersion',
      'numpyVersion',
      'image',
      'architecture',
      'linearSolver',
    ],
    path,
  )
  const linearSolver = property(item, 'linearSolver')
  return {
    adapter: text(property(item, 'adapter'), `${path}.adapter`, 256),
    adapterVersion: text(
      property(item, 'adapterVersion'),
      `${path}.adapterVersion`,
      64,
    ),
    pythonVersion: text(
      property(item, 'pythonVersion'),
      `${path}.pythonVersion`,
      64,
    ),
    clarabelVersion: text(
      property(item, 'clarabelVersion'),
      `${path}.clarabelVersion`,
      64,
    ),
    scipyVersion: text(
      property(item, 'scipyVersion'),
      `${path}.scipyVersion`,
      64,
    ),
    numpyVersion: text(
      property(item, 'numpyVersion'),
      `${path}.numpyVersion`,
      64,
    ),
    image:
      property(item, 'image') === null
        ? null
        : text(property(item, 'image'), `${path}.image`, 512),
    architecture: text(
      property(item, 'architecture'),
      `${path}.architecture`,
      64,
    ),
    linearSolver:
      linearSolver === null
        ? null
        : text(linearSolver, `${path}.linearSolver`, 512),
  }
}

function parseSvd(
  value: unknown,
  request: HiddenFlowSupportRequest,
  path: string,
): HiddenFlowSvdDiagnostics {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'singularValues',
      'rank',
      'nullity',
      'threshold',
      'conditionEstimate',
      'nullSpaceBasis',
    ],
    path,
  )
  const maximumRank = Math.min(
    request.observationMatrix.rows,
    request.coefficientCount,
  )
  const rank = integer(property(item, 'rank'), `${path}.rank`, 0, maximumRank)
  const nullity = integer(
    property(item, 'nullity'),
    `${path}.nullity`,
    0,
    request.coefficientCount,
  )
  if (rank + nullity !== request.coefficientCount) {
    fail(path, 'rank plus nullity must equal the coefficient count.')
  }
  return {
    singularValues: finiteArray(
      property(item, 'singularValues'),
      `${path}.singularValues`,
      maximumRank,
    ),
    rank,
    nullity,
    threshold: finite(property(item, 'threshold'), `${path}.threshold`),
    conditionEstimate: nullableFinite(
      property(item, 'conditionEstimate'),
      `${path}.conditionEstimate`,
    ),
    nullSpaceBasis: parseMatrix(
      property(item, 'nullSpaceBasis'),
      `${path}.nullSpaceBasis`,
      request.coefficientCount,
      nullity,
    ),
  }
}

function parseCone(value: unknown, path: string): HiddenFlowConeBlock {
  const item = record(value, path)
  exactKeys(item, ['type', 'dimension', 'label'], path)
  const type = property(item, 'type')
  if (
    type !== 'zero' &&
    type !== 'nonnegative' &&
    type !== 'second-order'
  ) {
    return fail(`${path}.type`, 'is unsupported.')
  }
  return {
    type,
    dimension: integer(
      property(item, 'dimension'),
      `${path}.dimension`,
      1,
      1_024,
    ),
    label: text(property(item, 'label'), `${path}.label`, 128),
  }
}

function parseCanonicalization(
  value: unknown,
  request: HiddenFlowSupportRequest,
  path: string,
): HiddenFlowCanonicalization {
  const item = record(value, path)
  exactKeys(
    item,
    ['q', 'a', 'b', 'cones', 'energyFactor', 'roughnessFactor'],
    path,
  )
  const conesValue = property(item, 'cones')
  if (!Array.isArray(conesValue) || conesValue.length > 260) {
    fail(`${path}.cones`, 'must be a bounded array.')
  }
  const cones = conesValue.map((cone, index) =>
    parseCone(cone, `${path}.cones[${index}]`),
  )
  const rowCount = cones.reduce((sum, cone) => sum + cone.dimension, 0)
  const parseFactor = (
    factor: unknown,
    factorPath: string,
  ): DenseMatrix | null =>
    factor === null
      ? null
      : parseMatrix(
          factor,
          factorPath,
          request.coefficientCount,
          request.coefficientCount,
        )
  return {
    q: finiteArray(
      property(item, 'q'),
      `${path}.q`,
      request.coefficientCount,
    ),
    a: parseMatrix(
      property(item, 'a'),
      `${path}.a`,
      rowCount,
      request.coefficientCount,
      HIDDEN_FLOW_LIMITS.maximumCanonicalMatrixEntries,
    ),
    b: finiteArray(property(item, 'b'), `${path}.b`, rowCount),
    cones,
    energyFactor: parseFactor(
      property(item, 'energyFactor'),
      `${path}.energyFactor`,
    ),
    roughnessFactor: parseFactor(
      property(item, 'roughnessFactor'),
      `${path}.roughnessFactor`,
    ),
  }
}

function parseSolution(
  value: unknown,
  request: HiddenFlowSupportRequest,
  canonicalization: HiddenFlowCanonicalization,
  path: string,
): HiddenFlowRawSolution {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'status',
      'coefficients',
      'slacks',
      'dual',
      'primalObjective',
      'dualObjective',
      'iterations',
      'reportedPrimalResidual',
      'reportedDualResidual',
      'reportedAbsoluteGap',
      'reportedRelativeGap',
    ],
    path,
  )
  const status = property(item, 'status')
  if (typeof status !== 'string' || !STATUSES.includes(status as HiddenFlowNativeSolverStatus)) {
    fail(`${path}.status`, 'is not a supported native status.')
  }
  const rowCount = canonicalization.b.length
  return {
    status: status as HiddenFlowNativeSolverStatus,
    coefficients: finiteArray(
      property(item, 'coefficients'),
      `${path}.coefficients`,
      request.coefficientCount,
    ),
    slacks: finiteArray(
      property(item, 'slacks'),
      `${path}.slacks`,
      rowCount,
    ),
    dual: finiteArray(property(item, 'dual'), `${path}.dual`, rowCount),
    primalObjective: nullableFinite(
      property(item, 'primalObjective'),
      `${path}.primalObjective`,
    ),
    dualObjective: nullableFinite(
      property(item, 'dualObjective'),
      `${path}.dualObjective`,
    ),
    iterations: integer(
      property(item, 'iterations'),
      `${path}.iterations`,
      0,
      request.solverSettings.maximumIterations,
    ),
    reportedPrimalResidual: nullableFinite(
      property(item, 'reportedPrimalResidual'),
      `${path}.reportedPrimalResidual`,
    ),
    reportedDualResidual: nullableFinite(
      property(item, 'reportedDualResidual'),
      `${path}.reportedDualResidual`,
    ),
    reportedAbsoluteGap: nullableFinite(
      property(item, 'reportedAbsoluteGap'),
      `${path}.reportedAbsoluteGap`,
    ),
    reportedRelativeGap: nullableFinite(
      property(item, 'reportedRelativeGap'),
      `${path}.reportedRelativeGap`,
    ),
  }
}

export function parseHiddenFlowSolverResult(
  value: unknown,
  request: HiddenFlowSupportRequest,
): HiddenFlowSolverResult {
  const path = 'hiddenFlowSolverResult'
  const item = record(value, path)
  exactKeys(
    item,
    [
      'schemaVersion',
      'requestId',
      'requestSha256',
      'canonicalSha256',
      'solver',
      'settings',
      'svd',
      'canonicalization',
      'solution',
      'warnings',
    ],
    path,
  )
  if (property(item, 'schemaVersion') !== 1) {
    fail(`${path}.schemaVersion`, 'must equal 1.')
  }
  const requestId = text(
    property(item, 'requestId'),
    `${path}.requestId`,
    128,
  )
  if (requestId !== request.requestId) {
    fail(`${path}.requestId`, 'does not match the request.')
  }
  const settings = parseSettings(property(item, 'settings'), `${path}.settings`)
  const canonicalization = parseCanonicalization(
    property(item, 'canonicalization'),
    request,
    `${path}.canonicalization`,
  )
  return {
    schemaVersion: 1,
    requestId,
    requestSha256: digest(
      property(item, 'requestSha256'),
      `${path}.requestSha256`,
    ),
    canonicalSha256: digest(
      property(item, 'canonicalSha256'),
      `${path}.canonicalSha256`,
    ),
    solver: parseSolver(property(item, 'solver'), `${path}.solver`),
    settings,
    svd: parseSvd(property(item, 'svd'), request, `${path}.svd`),
    canonicalization,
    solution: parseSolution(
      property(item, 'solution'),
      request,
      canonicalization,
      `${path}.solution`,
    ),
    warnings: stringArray(property(item, 'warnings'), `${path}.warnings`),
  }
}

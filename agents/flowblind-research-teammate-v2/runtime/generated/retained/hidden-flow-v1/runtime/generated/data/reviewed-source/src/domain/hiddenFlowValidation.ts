import {
  HIDDEN_FLOW_LIMITS,
  type DenseMatrix,
  type HiddenFlowBasisCenter,
  type HiddenFlowBasisSpec,
  type HiddenFlowBudgets,
  type HiddenFlowDomain,
  type HiddenFlowNumericalPolicy,
  type HiddenFlowObservation,
  type HiddenFlowPoint,
  type HiddenFlowProblem,
  type HiddenFlowTarget,
} from './hiddenFlowModel'

type UnknownRecord = Record<string, unknown>

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/

export type HiddenFlowInputErrorCode =
  | 'invalid-input'
  | 'resource-limit-exceeded'
  | 'unsupported-observation-type'
  | 'unsupported-target-type'

export class HiddenFlowInputError extends Error {
  readonly code: HiddenFlowInputErrorCode

  constructor(code: HiddenFlowInputErrorCode, path: string, message: string) {
    super(`${path}: ${message}`)
    this.name = 'HiddenFlowInputError'
    this.code = code
  }
}

function fail(
  path: string,
  message: string,
  code: HiddenFlowInputErrorCode = 'invalid-input',
): never {
  throw new HiddenFlowInputError(code, path, message)
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function record(value: unknown, path: string): UnknownRecord {
  if (!isRecord(value)) return fail(path, 'must be an object.')
  return value
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) return fail(path, 'must be an array.')
  return value
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
    return fail(path, 'must be a finite number.')
  }
  if (Math.abs(value) > HIDDEN_FLOW_LIMITS.maximumNumericMagnitude) {
    fail(path, 'exceeds the supported numerical magnitude.')
  }
  return value
}

function positive(value: unknown, path: string): number {
  const parsed = finite(value, path)
  if (parsed <= 0) fail(path, 'must be greater than zero.')
  return parsed
}

function nonnegative(value: unknown, path: string): number {
  const parsed = finite(value, path)
  if (parsed < 0) fail(path, 'must be nonnegative.')
  return parsed
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

function identifier(value: unknown, path: string): string {
  if (typeof value !== 'string' || !IDENTIFIER.test(value)) {
    return fail(path, 'must be a portable identifier.')
  }
  return value
}

function hasRejectedCharacter(value: string): boolean {
  for (const character of value) {
    const code = character.codePointAt(0)
    if (
      code !== undefined &&
      (code < 0x20 ||
        code === 0x7f ||
        (code >= 0x202a && code <= 0x202e) ||
        (code >= 0x2066 && code <= 0x2069))
    ) {
      return true
    }
  }
  return false
}

function text(
  value: unknown,
  path: string,
  maximumLength: number = HIDDEN_FLOW_LIMITS.maximumTextLength,
): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > maximumLength ||
    hasRejectedCharacter(value)
  ) {
    return fail(
      path,
      `must be nonempty text no longer than ${maximumLength} characters without control or bidirectional formatting characters.`,
    )
  }
  return value
}

function enumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  path: string,
): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    return fail(path, `must be one of ${allowed.join(', ')}.`)
  }
  return value as T
}

function finiteArray(
  value: unknown,
  path: string,
  minimumLength: number,
  maximumLength: number,
): number[] {
  const items = array(value, path)
  if (items.length < minimumLength || items.length > maximumLength) {
    fail(
      path,
      `must contain between ${minimumLength} and ${maximumLength} values.`,
      'resource-limit-exceeded',
    )
  }
  return items.map((item, index) => finite(item, `${path}[${index}]`))
}

function booleanArray(
  value: unknown,
  path: string,
  expectedLength: number,
): boolean[] {
  const items = array(value, path)
  if (items.length !== expectedLength) {
    fail(path, `must contain exactly ${expectedLength} values.`)
  }
  return items.map((item, index) => {
    if (typeof item !== 'boolean') {
      return fail(`${path}[${index}]`, 'must be a boolean.')
    }
    return item
  })
}

function increasing(values: readonly number[], path: string): void {
  for (let index = 1; index < values.length; index += 1) {
    if (values[index] <= values[index - 1]) {
      fail(path, 'must be strictly increasing.')
    }
  }
}

function point(value: unknown, path: string): HiddenFlowPoint {
  const item = record(value, path)
  exactKeys(item, ['x', 'y'], path)
  return {
    x: finite(property(item, 'x'), `${path}.x`),
    y: finite(property(item, 'y'), `${path}.y`),
  }
}

function direction(
  value: unknown,
  path: string,
): readonly [number, number] {
  const values = finiteArray(value, path, 2, 2)
  const norm = Math.hypot(values[0], values[1])
  if (norm <= 1e-12) fail(path, 'must have nonzero length.')
  return [values[0] / norm, values[1] / norm]
}

export interface HiddenFlowProblemResourceLimits {
  readonly maximumDomainCells: number
  readonly maximumBasisFunctions: number
}

const DEFAULT_HIDDEN_FLOW_PROBLEM_RESOURCE_LIMITS = {
  maximumDomainCells: HIDDEN_FLOW_LIMITS.maximumTargetGridPoints * 4,
  maximumBasisFunctions: HIDDEN_FLOW_LIMITS.maximumBasisFunctions,
} as const satisfies HiddenFlowProblemResourceLimits

function parseDomain(
  value: unknown,
  path: string,
  limits: HiddenFlowProblemResourceLimits,
): HiddenFlowDomain {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'id',
      'coordinateFrameId',
      'lengthUnit',
      'xEdges',
      'yEdges',
      'validCellMask',
    ],
    path,
  )
  const xEdges = finiteArray(
    property(item, 'xEdges'),
    `${path}.xEdges`,
    3,
    65,
  )
  const yEdges = finiteArray(property(item, 'yEdges'), `${path}.yEdges`, 3, 65)
  increasing(xEdges, `${path}.xEdges`)
  increasing(yEdges, `${path}.yEdges`)
  const cellCount = (xEdges.length - 1) * (yEdges.length - 1)
  if (cellCount > limits.maximumDomainCells) {
    fail(
      path,
      `declares ${cellCount} cells, exceeding the bounded domain limit.`,
      'resource-limit-exceeded',
    )
  }
  const validCellMask = booleanArray(
    property(item, 'validCellMask'),
    `${path}.validCellMask`,
    cellCount,
  )
  if (!validCellMask.some(Boolean)) {
    fail(`${path}.validCellMask`, 'must retain at least one valid cell.')
  }
  return {
    id: identifier(property(item, 'id'), `${path}.id`),
    coordinateFrameId: identifier(
      property(item, 'coordinateFrameId'),
      `${path}.coordinateFrameId`,
    ),
    lengthUnit: enumValue(
      property(item, 'lengthUnit'),
      ['mm'],
      `${path}.lengthUnit`,
    ),
    xEdges,
    yEdges,
    validCellMask,
  }
}

function parseBasisCenter(
  value: unknown,
  path: string,
): HiddenFlowBasisCenter {
  const item = record(value, path)
  exactKeys(item, ['id', 'point'], path)
  return {
    id: identifier(property(item, 'id'), `${path}.id`),
    point: point(property(item, 'point'), `${path}.point`),
  }
}

function parseBasis(
  value: unknown,
  path: string,
  limits: HiddenFlowProblemResourceLimits,
): HiddenFlowBasisSpec {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'family',
      'degree',
      'spacingX',
      'spacingY',
      'streamfunctionLengthScale',
      'interiorMarginCells',
      'quadratureOrder',
      'coefficientUnit',
      'boundaryPolicy',
      'centers',
    ],
    path,
  )
  if (property(item, 'degree') !== 3) {
    fail(`${path}.degree`, 'must equal 3.')
  }
  if (property(item, 'quadratureOrder') !== 4) {
    fail(`${path}.quadratureOrder`, 'must equal 4.')
  }
  const centerValues = array(property(item, 'centers'), `${path}.centers`)
  if (
    centerValues.length === 0 ||
    centerValues.length > limits.maximumBasisFunctions
  ) {
    fail(
      `${path}.centers`,
      `must contain between 1 and ${limits.maximumBasisFunctions} centers.`,
      'resource-limit-exceeded',
    )
  }
  const centers = centerValues.map(
    (entry, index) => parseBasisCenter(entry, `${path}.centers[${index}]`),
  )
  if (new Set(centers.map((center) => center.id)).size !== centers.length) {
    fail(`${path}.centers`, 'must use unique center IDs.')
  }
  return {
    family: enumValue(
      property(item, 'family'),
      ['tensor-cardinal-cubic-streamfunction-v1'],
      `${path}.family`,
    ),
    degree: 3,
    spacingX: positive(property(item, 'spacingX'), `${path}.spacingX`),
    spacingY: positive(property(item, 'spacingY'), `${path}.spacingY`),
    streamfunctionLengthScale: positive(
      property(item, 'streamfunctionLengthScale'),
      `${path}.streamfunctionLengthScale`,
    ),
    interiorMarginCells: integer(
      property(item, 'interiorMarginCells'),
      `${path}.interiorMarginCells`,
      1,
      8,
    ),
    quadratureOrder: 4,
    coefficientUnit: enumValue(
      property(item, 'coefficientUnit'),
      ['mm/s'],
      `${path}.coefficientUnit`,
    ),
    boundaryPolicy: enumValue(
      property(item, 'boundaryPolicy'),
      ['compact-support-inside-valid-cell-union'],
      `${path}.boundaryPolicy`,
    ),
    centers,
  }
}

export function parseHiddenFlowObservation(
  value: unknown,
  path: string,
): HiddenFlowObservation {
  const item = record(value, path)
  const observationType = property(item, 'type')
  if (
    observationType !== 'point-component' &&
    observationType !== 'point-direction'
  ) {
    fail(
      `${path}.type`,
      `observation type ${JSON.stringify(observationType)} is not supported in schema version 1.`,
      'unsupported-observation-type',
    )
  }
  const specializedKey =
    observationType === 'point-component' ? 'component' : 'direction'
  exactKeys(
    item,
    [
      'type',
      'id',
      'sensorId',
      'point',
      'coordinateFrameId',
      'unit',
      'baselineValue',
      'observedValue',
      'tolerance',
      'provenance',
      specializedKey,
    ],
    path,
  )
  const base = {
    id: identifier(property(item, 'id'), `${path}.id`),
    sensorId: identifier(property(item, 'sensorId'), `${path}.sensorId`),
    point: point(property(item, 'point'), `${path}.point`),
    coordinateFrameId: identifier(
      property(item, 'coordinateFrameId'),
      `${path}.coordinateFrameId`,
    ),
    unit: enumValue(property(item, 'unit'), ['mm/s'], `${path}.unit`),
    baselineValue: finite(
      property(item, 'baselineValue'),
      `${path}.baselineValue`,
    ),
    observedValue: finite(
      property(item, 'observedValue'),
      `${path}.observedValue`,
    ),
    tolerance: nonnegative(
      property(item, 'tolerance'),
      `${path}.tolerance`,
    ),
    provenance: text(property(item, 'provenance'), `${path}.provenance`),
  }
  if (observationType === 'point-component') {
    return {
      ...base,
      type: observationType,
      component: enumValue(
        property(item, 'component'),
        ['x', 'y'],
        `${path}.component`,
      ),
    }
  }
  return {
    ...base,
    type: observationType,
    direction: direction(property(item, 'direction'), `${path}.direction`),
  }
}

function parseTarget(value: unknown, path: string): HiddenFlowTarget {
  const item = record(value, path)
  const targetType = property(item, 'type')
  const common = {
    id: identifier(property(item, 'id'), `${path}.id`),
    title: text(property(item, 'title'), `${path}.title`, 256),
  }
  if (targetType === 'point-component') {
    exactKeys(item, ['type', 'id', 'title', 'point', 'component', 'unit'], path)
    return {
      ...common,
      type: targetType,
      point: point(property(item, 'point'), `${path}.point`),
      component: enumValue(
        property(item, 'component'),
        ['x', 'y'],
        `${path}.component`,
      ),
      unit: enumValue(property(item, 'unit'), ['mm/s'], `${path}.unit`),
    }
  }
  if (targetType === 'point-direction') {
    exactKeys(item, ['type', 'id', 'title', 'point', 'direction', 'unit'], path)
    return {
      ...common,
      type: targetType,
      point: point(property(item, 'point'), `${path}.point`),
      direction: direction(property(item, 'direction'), `${path}.direction`),
      unit: enumValue(property(item, 'unit'), ['mm/s'], `${path}.unit`),
    }
  }
  if (targetType === 'point-speed-envelope') {
    exactKeys(
      item,
      ['type', 'id', 'title', 'point', 'unit', 'directionCount'],
      path,
    )
    return {
      ...common,
      type: targetType,
      point: point(property(item, 'point'), `${path}.point`),
      unit: enumValue(property(item, 'unit'), ['mm/s'], `${path}.unit`),
      directionCount: integer(
        property(item, 'directionCount'),
        `${path}.directionCount`,
        3,
        HIDDEN_FLOW_LIMITS.maximumDirections,
      ),
    }
  }
  if (targetType === 'region-component') {
    exactKeys(
      item,
      ['type', 'id', 'title', 'cellIndices', 'component', 'unit'],
      path,
    )
    const cellIndexValues = array(
      property(item, 'cellIndices'),
      `${path}.cellIndices`,
    )
    const maximumCellIndices = HIDDEN_FLOW_LIMITS.maximumTargetGridPoints * 4
    if (
      cellIndexValues.length === 0 ||
      cellIndexValues.length > maximumCellIndices
    ) {
      fail(
        `${path}.cellIndices`,
        `must contain between 1 and ${maximumCellIndices} cell indices.`,
        'resource-limit-exceeded',
      )
    }
    const cellIndices = cellIndexValues.map((entry, index) =>
      integer(
        entry,
        `${path}.cellIndices[${index}]`,
        0,
        maximumCellIndices,
      ),
    )
    if (new Set(cellIndices).size !== cellIndices.length) {
      fail(`${path}.cellIndices`, 'must not contain duplicate indices.')
    }
    return {
      ...common,
      type: targetType,
      cellIndices,
      component: enumValue(
        property(item, 'component'),
        ['x', 'y'],
        `${path}.component`,
      ),
      unit: enumValue(property(item, 'unit'), ['mm/s'], `${path}.unit`),
    }
  }
  if (targetType === 'point-strain-component') {
    exactKeys(item, ['type', 'id', 'title', 'point', 'component', 'unit'], path)
    return {
      ...common,
      type: targetType,
      point: point(property(item, 'point'), `${path}.point`),
      component: enumValue(
        property(item, 'component'),
        ['xx', 'yy', 'xy'],
        `${path}.component`,
      ),
      unit: enumValue(property(item, 'unit'), ['1/s'], `${path}.unit`),
    }
  }
  return fail(
    `${path}.type`,
    `target type ${JSON.stringify(targetType)} is not supported in schema version 1.`,
    'unsupported-target-type',
  )
}

function parseBudgets(value: unknown, path: string): HiddenFlowBudgets {
  const item = record(value, path)
  exactKeys(item, ['velocityRms', 'velocityGradientRms'], path)
  const velocity = property(item, 'velocityRms')
  const gradient = property(item, 'velocityGradientRms')
  const parseBudget = <T extends 'mm/s' | '1/s'>(
    candidate: unknown,
    candidatePath: string,
    unit: T,
  ): { value: number; unit: T } | null => {
    if (candidate === null) return null
    const budget = record(candidate, candidatePath)
    exactKeys(budget, ['value', 'unit'], candidatePath)
    return {
      value: nonnegative(property(budget, 'value'), `${candidatePath}.value`),
      unit: enumValue(
        property(budget, 'unit'),
        [unit],
        `${candidatePath}.unit`,
      ),
    }
  }
  return {
    velocityRms: parseBudget(velocity, `${path}.velocityRms`, 'mm/s'),
    velocityGradientRms: parseBudget(
      gradient,
      `${path}.velocityGradientRms`,
      '1/s',
    ),
  }
}

function parseNumerics(
  value: unknown,
  path: string,
): HiddenFlowNumericalPolicy {
  const item = record(value, path)
  exactKeys(
    item,
    [
      'rankRelativeTolerance',
      'basisConditionLimit',
      'verificationAbsoluteTolerance',
      'verificationRelativeTolerance',
      'maximumSolverIterations',
    ],
    path,
  )
  return {
    rankRelativeTolerance: positive(
      property(item, 'rankRelativeTolerance'),
      `${path}.rankRelativeTolerance`,
    ),
    basisConditionLimit: positive(
      property(item, 'basisConditionLimit'),
      `${path}.basisConditionLimit`,
    ),
    verificationAbsoluteTolerance: positive(
      property(item, 'verificationAbsoluteTolerance'),
      `${path}.verificationAbsoluteTolerance`,
    ),
    verificationRelativeTolerance: positive(
      property(item, 'verificationRelativeTolerance'),
      `${path}.verificationRelativeTolerance`,
    ),
    maximumSolverIterations: integer(
      property(item, 'maximumSolverIterations'),
      `${path}.maximumSolverIterations`,
      1,
      100_000,
    ),
  }
}

function stringArray(value: unknown, path: string, maximum: number): string[] {
  const items = array(value, path)
  if (items.length > maximum) {
    fail(
      path,
      `must not contain more than ${maximum} entries.`,
      'resource-limit-exceeded',
    )
  }
  return items.map((entry, index) => text(entry, `${path}[${index}]`))
}

export function parseHiddenFlowProblem(
  value: unknown,
  resourceLimits: HiddenFlowProblemResourceLimits =
    DEFAULT_HIDDEN_FLOW_PROBLEM_RESOURCE_LIMITS,
): HiddenFlowProblem {
  const path = 'hiddenFlowProblem'
  const item = record(value, path)
  exactKeys(
    item,
    [
      'schemaVersion',
      'id',
      'title',
      'description',
      'domain',
      'basis',
      'observations',
      'budgets',
      'target',
      'numerics',
      'provenance',
      'limitations',
    ],
    path,
  )
  if (property(item, 'schemaVersion') !== 1) {
    fail(`${path}.schemaVersion`, 'must equal 1.')
  }
  const domain = parseDomain(
    property(item, 'domain'),
    `${path}.domain`,
    resourceLimits,
  )
  const basis = parseBasis(
    property(item, 'basis'),
    `${path}.basis`,
    resourceLimits,
  )
  const observationValues = array(
    property(item, 'observations'),
    `${path}.observations`,
  )
  if (observationValues.length > HIDDEN_FLOW_LIMITS.maximumObservationRows) {
    fail(
      `${path}.observations`,
      `must not exceed ${HIDDEN_FLOW_LIMITS.maximumObservationRows} scalar rows.`,
      'resource-limit-exceeded',
    )
  }
  const observations = observationValues.map((entry, index) =>
    parseHiddenFlowObservation(entry, `${path}.observations[${index}]`),
  )
  if (new Set(observations.map((entry) => entry.id)).size !== observations.length) {
    fail(`${path}.observations`, 'must use unique observation IDs.')
  }
  if (
    observations.length * basis.centers.length >
    HIDDEN_FLOW_LIMITS.maximumObservationMatrixEntries
  ) {
    fail(
      `${path}.observations`,
      `would exceed the ${HIDDEN_FLOW_LIMITS.maximumObservationMatrixEntries}-entry observation-matrix limit.`,
      'resource-limit-exceeded',
    )
  }
  for (const observation of observations) {
    if (observation.coordinateFrameId !== domain.coordinateFrameId) {
      fail(
        `${path}.observations`,
        `observation ${JSON.stringify(observation.id)} uses a different coordinate frame.`,
      )
    }
  }
  const provenance = record(
    property(item, 'provenance'),
    `${path}.provenance`,
  )
  exactKeys(
    provenance,
    ['sourceKind', 'citation', 'license', 'transformations'],
    `${path}.provenance`,
  )
  return {
    schemaVersion: 1,
    id: identifier(property(item, 'id'), `${path}.id`),
    title: text(property(item, 'title'), `${path}.title`, 256),
    description: text(property(item, 'description'), `${path}.description`),
    domain,
    basis,
    observations,
    budgets: parseBudgets(property(item, 'budgets'), `${path}.budgets`),
    target: parseTarget(property(item, 'target'), `${path}.target`),
    numerics: parseNumerics(property(item, 'numerics'), `${path}.numerics`),
    provenance: {
      sourceKind: enumValue(
        property(provenance, 'sourceKind'),
        ['generated', 'declared'],
        `${path}.provenance.sourceKind`,
      ),
      citation: text(
        property(provenance, 'citation'),
        `${path}.provenance.citation`,
      ),
      license: text(
        property(provenance, 'license'),
        `${path}.provenance.license`,
        256,
      ),
      transformations: stringArray(
        property(provenance, 'transformations'),
        `${path}.provenance.transformations`,
        32,
      ),
    },
    limitations: stringArray(
      property(item, 'limitations'),
      `${path}.limitations`,
      32,
    ),
  }
}

export function validateDenseMatrix(
  matrix: DenseMatrix,
  path: string,
  expectedRows?: number,
  expectedColumns?: number,
  maximumEntries = HIDDEN_FLOW_LIMITS.maximumMatrixEntries,
): void {
  if (
    !Number.isInteger(matrix.rows) ||
    !Number.isInteger(matrix.columns) ||
    matrix.rows < 0 ||
    matrix.columns < 0
  ) {
    fail(path, 'must declare nonnegative integer dimensions.')
  }
  if (
    expectedRows !== undefined &&
    matrix.rows !== expectedRows
  ) {
    fail(path, `must have ${expectedRows} rows.`)
  }
  if (
    expectedColumns !== undefined &&
    matrix.columns !== expectedColumns
  ) {
    fail(path, `must have ${expectedColumns} columns.`)
  }
  const entries = matrix.rows * matrix.columns
  if (
    entries > maximumEntries ||
    matrix.values.length !== entries
  ) {
    fail(
      path,
      `must contain exactly ${entries} entries within the matrix resource limit.`,
      'resource-limit-exceeded',
    )
  }
  for (let index = 0; index < matrix.values.length; index += 1) {
    if (!Number.isFinite(matrix.values[index])) {
      fail(`${path}.values[${index}]`, 'must be finite.')
    }
  }
}

import type { CanonicalDatasetSourceEvidence } from './vectorAuditModel'

export const HIDDEN_FLOW_PROBLEM_SCHEMA_VERSION = 1
export const HIDDEN_FLOW_RESULT_SCHEMA_VERSION = 1
export const HIDDEN_FLOW_REPORT_SCHEMA_VERSION = 1
export const HIDDEN_FLOW_CATALOG_SCHEMA_VERSION = 1

export const HIDDEN_FLOW_LIMITS = {
  maximumDocumentBytes: 16 * 1024 * 1024,
  maximumSolverResultBytes: 16 * 1024 * 1024,
  maximumSolverBatchRequests: 64,
  maximumSolverBatchInputBytes: 32 * 1024 * 1024,
  maximumSolverBatchResultBytes: 64 * 1024 * 1024,
  maximumBasisFunctions: 96,
  maximumObservationRows: 256,
  maximumObservationMatrixEntries: 256 * 96,
  maximumTargetGridPoints: 256,
  maximumDirections: 64,
  maximumScenarios: 24,
  maximumTextLength: 2_048,
  maximumIdentifierLength: 64,
  maximumMatrixEntries: 96 * 96,
  maximumCanonicalMatrixEntries: 70_000,
  maximumNumericMagnitude: 1e100,
} as const

export type HiddenFlowLengthUnit = 'mm'
export type HiddenFlowVelocityUnit = 'mm/s'
export type HiddenFlowGradientUnit = '1/s'
export type HiddenFlowBoundaryPolicy =
  'compact-support-inside-valid-cell-union'
export type HiddenFlowBasisFamily =
  'tensor-cardinal-cubic-streamfunction-v1'
export type HiddenFlowComponent = 'x' | 'y'
export type HiddenFlowStrainComponent = 'xx' | 'yy' | 'xy'

export interface HiddenFlowPoint {
  x: number
  y: number
}

export interface DenseMatrix {
  rows: number
  columns: number
  values: readonly number[]
}

export interface HiddenFlowDomain {
  id: string
  coordinateFrameId: string
  lengthUnit: HiddenFlowLengthUnit
  xEdges: readonly number[]
  yEdges: readonly number[]
  validCellMask: readonly boolean[]
}

export interface HiddenFlowBasisCenter {
  id: string
  point: HiddenFlowPoint
}

export interface HiddenFlowBasisSpec {
  family: HiddenFlowBasisFamily
  degree: 3
  spacingX: number
  spacingY: number
  streamfunctionLengthScale: number
  interiorMarginCells: number
  quadratureOrder: 4
  coefficientUnit: HiddenFlowVelocityUnit
  boundaryPolicy: HiddenFlowBoundaryPolicy
  centers: readonly HiddenFlowBasisCenter[]
}

export interface HiddenFlowBasisFunction {
  id: string
  center: HiddenFlowPoint
  spacingX: number
  spacingY: number
  streamfunctionLengthScale: number
  velocityNormalization: number
  support: {
    xMinimum: number
    xMaximum: number
    yMinimum: number
    yMaximum: number
  }
}

export interface HiddenFlowMatrixDiagnostics {
  rank: number
  conditionEstimate: number
  minimumEigenvalue: number
  maximumEigenvalue: number
  threshold: number
}

export interface HiddenFlowBasisDiagnostics {
  retainedCount: number
  rejectedSupportCount: number
  domainArea: number
  maximumVerificationDivergence: number
  mass: HiddenFlowMatrixDiagnostics
  roughness: HiddenFlowMatrixDiagnostics
}

export interface HiddenFlowCompiledBasis {
  spec: HiddenFlowBasisSpec
  functions: readonly HiddenFlowBasisFunction[]
  massMatrix: DenseMatrix
  roughnessMatrix: DenseMatrix
  diagnostics: HiddenFlowBasisDiagnostics
}

interface HiddenFlowObservationBase {
  id: string
  sensorId: string
  point: HiddenFlowPoint
  coordinateFrameId: string
  unit: HiddenFlowVelocityUnit
  baselineValue: number
  observedValue: number
  tolerance: number
  provenance: string
}

export interface HiddenFlowPointComponentObservation
  extends HiddenFlowObservationBase {
  type: 'point-component'
  component: HiddenFlowComponent
}

export interface HiddenFlowPointDirectionObservation
  extends HiddenFlowObservationBase {
  type: 'point-direction'
  direction: readonly [number, number]
}

export type HiddenFlowObservation =
  | HiddenFlowPointComponentObservation
  | HiddenFlowPointDirectionObservation

interface HiddenFlowTargetBase {
  id: string
  title: string
}

export interface HiddenFlowPointComponentTarget extends HiddenFlowTargetBase {
  type: 'point-component'
  point: HiddenFlowPoint
  component: HiddenFlowComponent
  unit: HiddenFlowVelocityUnit
}

export interface HiddenFlowPointDirectionTarget extends HiddenFlowTargetBase {
  type: 'point-direction'
  point: HiddenFlowPoint
  direction: readonly [number, number]
  unit: HiddenFlowVelocityUnit
}

export interface HiddenFlowPointSpeedTarget extends HiddenFlowTargetBase {
  type: 'point-speed-envelope'
  point: HiddenFlowPoint
  unit: HiddenFlowVelocityUnit
  directionCount: number
}

export interface HiddenFlowRegionComponentTarget extends HiddenFlowTargetBase {
  type: 'region-component'
  cellIndices: readonly number[]
  component: HiddenFlowComponent
  unit: HiddenFlowVelocityUnit
}

export interface HiddenFlowPointStrainTarget extends HiddenFlowTargetBase {
  type: 'point-strain-component'
  point: HiddenFlowPoint
  component: HiddenFlowStrainComponent
  unit: HiddenFlowGradientUnit
}

export type HiddenFlowTarget =
  | HiddenFlowPointComponentTarget
  | HiddenFlowPointDirectionTarget
  | HiddenFlowPointSpeedTarget
  | HiddenFlowRegionComponentTarget
  | HiddenFlowPointStrainTarget

export interface HiddenFlowBudgets {
  velocityRms: {
    value: number
    unit: HiddenFlowVelocityUnit
  } | null
  velocityGradientRms: {
    value: number
    unit: HiddenFlowGradientUnit
  } | null
}

export interface HiddenFlowNumericalPolicy {
  rankRelativeTolerance: number
  basisConditionLimit: number
  verificationAbsoluteTolerance: number
  verificationRelativeTolerance: number
  maximumSolverIterations: number
}

export interface HiddenFlowProblem {
  schemaVersion: 1
  id: string
  title: string
  description: string
  domain: HiddenFlowDomain
  basis: HiddenFlowBasisSpec
  observations: readonly HiddenFlowObservation[]
  budgets: HiddenFlowBudgets
  target: HiddenFlowTarget
  numerics: HiddenFlowNumericalPolicy
  provenance: {
    sourceKind: 'generated' | 'declared'
    citation: string
    license: string
    transformations: readonly string[]
  }
  limitations: readonly string[]
}

export interface HiddenFlowLinearSystem {
  observationMatrix: DenseMatrix
  lowerBounds: readonly number[]
  upperBounds: readonly number[]
}

export interface HiddenFlowCompiledTarget {
  id: string
  title: string
  type: Exclude<HiddenFlowTarget['type'], 'point-speed-envelope'>
  objective: readonly number[]
  unit: HiddenFlowVelocityUnit | HiddenFlowGradientUnit
  direction: readonly [number, number] | null
}

export interface HiddenFlowCompiledProblem {
  problem: HiddenFlowProblem
  basis: HiddenFlowCompiledBasis
  observations: HiddenFlowLinearSystem
  target: HiddenFlowCompiledTarget
}

export interface HiddenFlowSolverSettings {
  maximumIterations: number
  absoluteGapTolerance: number
  relativeGapTolerance: number
  feasibilityTolerance: number
  infeasibilityTolerance: number
  presolveEnabled: boolean
  equilibrationEnabled: boolean
  iterativeRefinementEnabled: boolean
  maximumThreads: 1
}

export interface HiddenFlowSupportRequest {
  schemaVersion: 1
  requestId: string
  problemId: string
  coefficientCount: number
  observationMatrix: DenseMatrix
  lowerBounds: readonly number[]
  upperBounds: readonly number[]
  energyMatrix: DenseMatrix
  energyBudget: number | null
  roughnessMatrix: DenseMatrix
  roughnessBudget: number | null
  objective: readonly number[]
  rankRelativeTolerance: number
  solverSettings: HiddenFlowSolverSettings
}

export type HiddenFlowNativeSolverStatus =
  | 'Unsolved'
  | 'Solved'
  | 'PrimalInfeasible'
  | 'DualInfeasible'
  | 'AlmostSolved'
  | 'AlmostPrimalInfeasible'
  | 'AlmostDualInfeasible'
  | 'MaxIterations'
  | 'MaxTime'
  | 'NumericalError'
  | 'InsufficientProgress'
  | 'CallbackTerminated'
  | 'Unknown'

export interface HiddenFlowConeBlock {
  type: 'zero' | 'nonnegative' | 'second-order'
  dimension: number
  label: string
}

export interface HiddenFlowCanonicalization {
  q: readonly number[]
  a: DenseMatrix
  b: readonly number[]
  cones: readonly HiddenFlowConeBlock[]
  energyFactor: DenseMatrix | null
  roughnessFactor: DenseMatrix | null
}

export interface HiddenFlowSvdDiagnostics {
  singularValues: readonly number[]
  rank: number
  nullity: number
  threshold: number
  conditionEstimate: number | null
  nullSpaceBasis: DenseMatrix
}

export interface HiddenFlowRawSolution {
  status: HiddenFlowNativeSolverStatus
  coefficients: readonly number[]
  slacks: readonly number[]
  dual: readonly number[]
  primalObjective: number | null
  dualObjective: number | null
  iterations: number
  reportedPrimalResidual: number | null
  reportedDualResidual: number | null
  reportedAbsoluteGap: number | null
  reportedRelativeGap: number | null
}

export interface HiddenFlowSolverIdentity {
  adapter: string
  adapterVersion: string
  pythonVersion: string
  clarabelVersion: string
  scipyVersion: string
  numpyVersion: string
  image: string | null
  architecture: string
  linearSolver: string | null
}

export interface HiddenFlowSolverResult {
  schemaVersion: 1
  requestId: string
  requestSha256: string
  canonicalSha256: string
  solver: HiddenFlowSolverIdentity
  settings: HiddenFlowSolverSettings
  svd: HiddenFlowSvdDiagnostics
  canonicalization: HiddenFlowCanonicalization
  solution: HiddenFlowRawSolution
  warnings: readonly string[]
}

export type HiddenFlowEvidenceState =
  | 'verified-optimal-within-tolerance'
  | 'verified-directional-lower-bound-within-tolerance'
  | 'approximate-candidate'
  | 'verified-infeasible-within-tolerance'
  | 'verified-unbounded-within-tolerance'
  | 'full-observation-zero-nullity'
  | 'degenerate-objective'
  | 'unsupported'
  | 'failed'

export interface HiddenFlowVerificationSummary {
  accepted: boolean
  state: HiddenFlowEvidenceState
  detail: string
  objectiveValue: number | null
  rigorousObjectiveUpperBound: number | null
  approximateDualUpperDiagnostic: number | null
  upperBoundQualification:
    | 'unavailable-no-rigorous-dual-certificate'
    | 'not-applicable'
  observationMaximumViolation: number | null
  activeObservationConstraints: readonly string[]
  velocityRms: number | null
  velocityGradientRms: number | null
  maximumVerificationDivergence: number | null
  primalResidual: number | null
  dualResidual: number | null
  absoluteGap: number | null
  relativeGap: number | null
  coneViolation: number | null
  numericalEvidenceQualification:
    | 'verified-to-declared-tolerances'
    | 'candidate-only'
    | 'not-applicable'
}

export interface HiddenFlowSupportResult {
  request: HiddenFlowSupportRequest
  solverResult: HiddenFlowSolverResult
  verification: HiddenFlowVerificationSummary
}

export interface HiddenFlowSpeedEnvelope {
  state: HiddenFlowEvidenceState
  directionCount: number
  geometricFactor: number
  lowerBound: number
  upperBound: number | null
  unit: HiddenFlowVelocityUnit
  bestDirection: readonly [number, number]
  bestCandidate: readonly number[]
  directionalResults: readonly HiddenFlowSupportResult[]
}

export interface HiddenFlowFieldGrid {
  xCoordinates: readonly number[]
  yCoordinates: readonly number[]
  validPointMask: readonly boolean[]
  baselineValues: readonly number[]
}

export interface HiddenFlowCapacityPoint {
  point: HiddenFlowPoint
  lowerBound: number
  upperBound: number | null
  candidateCoefficients: readonly number[]
  state: HiddenFlowEvidenceState
}

export interface HiddenFlowCatalogObservationResidual {
  observationId: string
  value: number
  lowerBound: number
  upperBound: number
  active: boolean
}

export interface HiddenFlowCatalogTargetResult {
  target: HiddenFlowTarget
  state: HiddenFlowEvidenceState
  lowerBound: number
  upperBound: number | null
  unit: HiddenFlowVelocityUnit | HiddenFlowGradientUnit
  candidateCoefficients: readonly number[]
  bestDirection: readonly [number, number] | null
  directionCount: number | null
  geometricFactor: number | null
  observationResiduals: readonly HiddenFlowCatalogObservationResidual[]
  evidence: {
    nativeStatus: HiddenFlowNativeSolverStatus
    requestSha256: string
    canonicalSha256: string
    iterations: number
    primalResidual: number | null
    dualResidual: number | null
    absoluteGap: number | null
    relativeGap: number | null
    coneViolation: number | null
    velocityRms: number | null
    velocityGradientRms: number | null
    maximumVerificationDivergence: number | null
    upperBoundQualification:
      HiddenFlowVerificationSummary['upperBoundQualification']
    numericalEvidenceQualification:
      HiddenFlowVerificationSummary['numericalEvidenceQualification']
  }
}

export interface HiddenFlowScenarioResult {
  id: string
  mode: 'exact-null' | 'tolerance-expanded'
  budgets: HiddenFlowBudgets
  observationRank: number
  observationNullity: number
  observationSingularValues: readonly number[]
  targets: readonly HiddenFlowCatalogTargetResult[]
  capacityQuantity: {
    type: 'point-component'
    component: 'x'
    unit: HiddenFlowVelocityUnit
  }
  capacityMap: readonly HiddenFlowCapacityPoint[]
}

export interface HiddenFlowSearchResult {
  basis: HiddenFlowCompiledBasis
  observationRank: number
  observationNullity: number
  observationSingularValues: readonly number[]
  support: HiddenFlowSupportResult | HiddenFlowSpeedEnvelope
}

export interface HiddenFlowCatalog {
  schemaVersion: 1
  id: string
  title: string
  source: CanonicalDatasetSourceEvidence
  field: HiddenFlowFieldGrid
  domain: HiddenFlowDomain
  basis: HiddenFlowCompiledBasis
  basisSha256: string
  numerics: HiddenFlowNumericalPolicy
  observationSets: {
    exactNull: readonly HiddenFlowObservation[]
    toleranceExpanded: readonly HiddenFlowObservation[]
  }
  scenarios: readonly HiddenFlowScenarioResult[]
  software: {
    name: 'FlowBlind'
    version: string
  }
  solver: {
    adapter: string
    adapterVersion: string
    clarabelVersion: string
  }
  limitations: readonly string[]
}

export interface HiddenFlowEvidenceReport {
  schemaVersion: 1
  reportId: string
  software: {
    name: 'FlowBlind'
    version: string
  }
  problemSource: CanonicalDatasetSourceEvidence
  problem: HiddenFlowProblem
  basisSha256: string
  basis: HiddenFlowBasisDiagnostics
  result: HiddenFlowSearchResult
  limitations: readonly string[]
}

export interface HiddenFlowBatchProblemEntry {
  id: string
  reference: string
  expectedSha256: string | null
}

export interface HiddenFlowBatchManifest {
  schemaVersion: 1
  reportId: string
  problems: readonly HiddenFlowBatchProblemEntry[]
}

export interface HiddenFlowBatchEvidenceReport {
  schemaVersion: 1
  reportId: string
  software: {
    name: 'FlowBlind'
    version: string
  }
  manifestSource: CanonicalDatasetSourceEvidence
  manifest: HiddenFlowBatchManifest
  reports: readonly HiddenFlowEvidenceReport[]
}

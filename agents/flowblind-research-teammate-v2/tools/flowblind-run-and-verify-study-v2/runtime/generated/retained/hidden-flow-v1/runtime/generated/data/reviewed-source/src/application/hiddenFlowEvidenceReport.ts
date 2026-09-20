import type {
  HiddenFlowBatchEvidenceReport,
  HiddenFlowCatalog,
  HiddenFlowCatalogTargetResult,
  HiddenFlowEvidenceReport,
  HiddenFlowSearchResult,
  HiddenFlowScenarioResult,
  HiddenFlowSupportResult,
} from '../domain/hiddenFlowModel'
import { escapeMarkdown } from './evidenceReport'

function formatted(value: number): string {
  return Number.isFinite(value)
    ? value.toPrecision(8).replace(/(?:\.0+|(\.\d+?)0+)(e|$)/u, '$1$2')
    : 'not finite'
}

function supportState(result: HiddenFlowCatalogTargetResult): string {
  return result.directionCount === null
    ? escapeMarkdown(result.state)
    : 'directional candidate feasible within declared tolerance'
}

function targetValue(result: HiddenFlowCatalogTargetResult): string {
  if (result.directionCount !== null) {
    return `${formatted(result.lowerBound)} ${escapeMarkdown(result.unit)} candidate feasible within declared tolerance; rigorous upper unavailable`
  }
  return `${formatted(result.lowerBound)} ${escapeMarkdown(result.unit)} candidate feasible within declared tolerance; rigorous upper unavailable`
}

function searchSupports(
  search: HiddenFlowSearchResult,
): readonly HiddenFlowSupportResult[] {
  return 'directionalResults' in search.support
    ? search.support.directionalResults
    : [search.support]
}

function representativeSearchSupport(
  search: HiddenFlowSearchResult,
): HiddenFlowSupportResult {
  const supports = searchSupports(search)
  return supports.reduce((best, candidate) => {
    const bestValue =
      best.verification.objectiveValue ?? Number.NEGATIVE_INFINITY
    const candidateValue =
      candidate.verification.objectiveValue ?? Number.NEGATIVE_INFINITY
    return candidateValue > bestValue ? candidate : best
  })
}

function searchValue(
  search: HiddenFlowSearchResult,
  unit: string,
): string {
  if ('directionalResults' in search.support) {
    if (
      !search.support.directionalResults.every(
        (result) => result.verification.accepted,
      )
    ) {
      return 'not available; no feasible value is claimed'
    }
    return `${formatted(search.support.lowerBound)} ${escapeMarkdown(search.support.unit)} candidate feasible within declared tolerance; rigorous upper unavailable`
  }
  return !search.support.verification.accepted ||
    search.support.verification.objectiveValue === null
    ? 'not available'
    : `${formatted(search.support.verification.objectiveValue)} ${escapeMarkdown(unit)} candidate feasible within declared tolerance; rigorous upper unavailable`
}

function evidenceReportLines(
  report: HiddenFlowEvidenceReport,
  headingLevel: 1 | 2,
): string[] {
  const heading = '#'.repeat(headingLevel)
  const subheading = '#'.repeat(headingLevel + 1)
  const supports = searchSupports(report.result)
  const first = representativeSearchSupport(report.result)
  const accepted = supports.filter(
    (support) => support.verification.accepted,
  ).length
  return [
    `${heading} Declared problem: ${escapeMarkdown(report.problem.title)}`,
    '',
    '> **Authority boundary:** This report contains declared finite-basis evidence only. Problem, target, provenance, citation, and limitation text are unreviewed declarations. It does not attest physical truth, source accuracy, measurement validity or calibration, clinical relevance or use, or model/user approval.',
    '',
    `**Report ID:** \`${escapeMarkdown(report.reportId)}\`  `,
    `**Software:** ${escapeMarkdown(report.software.name)} ${escapeMarkdown(report.software.version)}  `,
    `**Problem source:** ${escapeMarkdown(report.problemSource.reference)}; ${report.problemSource.byteLength} bytes; SHA-256 \`${escapeMarkdown(report.problemSource.sha256)}\`  `,
    `**Basis SHA-256:** \`${escapeMarkdown(report.basisSha256)}\``,
    '',
    `${subheading} Declared problem`,
    '',
    `- Declared target: ${escapeMarkdown(report.problem.target.title)} (${escapeMarkdown(report.problem.target.type)}); result ${searchValue(report.result, report.problem.target.unit)}.`,
    `- Observations: ${report.problem.observations.length} scalar rows; numerical rank ${report.result.observationRank}, nullity ${report.result.observationNullity}.`,
    `- Velocity RMS budget: ${report.problem.budgets.velocityRms === null ? 'not declared' : `${formatted(report.problem.budgets.velocityRms.value)} ${escapeMarkdown(report.problem.budgets.velocityRms.unit)}`}.`,
    `- Velocity-gradient RMS budget: ${report.problem.budgets.velocityGradientRms === null ? 'not declared' : `${formatted(report.problem.budgets.velocityGradientRms.value)} ${escapeMarkdown(report.problem.budgets.velocityGradientRms.unit)}`}.`,
    `- Boundary policy: ${escapeMarkdown(report.problem.basis.boundaryPolicy)}; ${report.problem.basis.interiorMarginCells}-cell collar; no general no-slip claim.`,
    `- Basis: ${report.basis.retainedCount} retained, mass rank ${report.basis.mass.rank}, roughness rank ${report.basis.roughness.rank}, condition estimates ${formatted(report.basis.mass.conditionEstimate)} / ${formatted(report.basis.roughness.conditionEstimate)}.`,
    '',
    `${subheading} Solver and verification`,
    '',
    `- Accepted support solves: ${accepted}/${supports.length}.`,
    ...('directionalResults' in report.result.support
      ? [
          `- Representative solve: best sampled direction (${report.result.support.bestDirection.map(formatted).join(', ')}) of ${report.result.support.directionCount}; the status, hashes, residuals, gap, and dual diagnostic below refer to this directional subproblem.`,
        ]
      : []),
    `- Solver: ${escapeMarkdown(first.solverResult.solver.adapter)} ${escapeMarkdown(first.solverResult.solver.adapterVersion)}; Clarabel ${escapeMarkdown(first.solverResult.solver.clarabelVersion)}; SciPy ${escapeMarkdown(first.solverResult.solver.scipyVersion)}; NumPy ${escapeMarkdown(first.solverResult.solver.numpyVersion)}.`,
    `- Native status: ${escapeMarkdown(first.solverResult.solution.status)}; FlowBlind state: ${escapeMarkdown(first.verification.state)}.`,
    `- Request SHA-256: \`${escapeMarkdown(first.solverResult.requestSha256)}\`; conic-form SHA-256: \`${escapeMarkdown(first.solverResult.canonicalSha256)}\`.`,
    `- Independent residuals: primal ${first.verification.primalResidual === null ? 'not applicable' : formatted(first.verification.primalResidual)}, dual ${first.verification.dualResidual === null ? 'not applicable' : formatted(first.verification.dualResidual)}, cone ${first.verification.coneViolation === null ? 'not applicable' : formatted(first.verification.coneViolation)}, absolute gap ${first.verification.absoluteGap === null ? 'not applicable' : formatted(first.verification.absoluteGap)}.`,
    `- Numerical qualification: ${escapeMarkdown(first.verification.numericalEvidenceQualification)}. Numerical evidence is checked to declared tolerances, not by formal exact arithmetic.`,
    `- Rigorous objective upper bound: unavailable. Approximate dual upper diagnostic: ${first.verification.approximateDualUpperDiagnostic === null ? 'not available' : formatted(first.verification.approximateDualUpperDiagnostic)}; this diagnostic is not a bound.`,
    '',
    `${subheading} Limitations`,
    '',
    ...(report.limitations.length === 0
      ? [
          '- No additional declarer-supplied limitations were provided; the fixed authority boundary above still applies.',
        ]
      : report.limitations.map(
          (limitation) => `- ${escapeMarkdown(limitation)}`,
        )),
  ]
}

export function renderHiddenFlowEvidenceReportMarkdown(
  report: HiddenFlowEvidenceReport,
): string {
  return `${evidenceReportLines(report, 1).join('\n')}\n`
}

export function renderHiddenFlowBatchEvidenceReportMarkdown(
  report: HiddenFlowBatchEvidenceReport,
): string {
  const lines = [
    `# FlowBlind hidden-flow batch: ${escapeMarkdown(report.reportId)}`,
    '',
    `**Software:** ${escapeMarkdown(report.software.name)} ${escapeMarkdown(report.software.version)}  `,
    `**Manifest SHA-256:** \`${escapeMarkdown(report.manifestSource.sha256)}\`  `,
    `**Problem count:** ${report.reports.length}`,
    '',
  ]
  for (const item of report.reports) {
    lines.push(...evidenceReportLines(item, 2), '')
  }
  return `${lines.join('\n')}\n`
}

function speedTarget(
  scenario: HiddenFlowScenarioResult,
): HiddenFlowCatalogTargetResult | null {
  return scenario.targets.find(
    (target) => target.target.type === 'point-speed-envelope',
  ) ?? null
}

export function renderHiddenFlowCatalogMarkdown(
  catalog: HiddenFlowCatalog,
): string {
  const firstScenario = catalog.scenarios[0]
  if (firstScenario === undefined) {
    throw new Error('Hidden-flow catalog has no scenarios.')
  }
  const lines = [
    `# ${escapeMarkdown(catalog.title)}`,
    '',
    `**Catalog ID:** \`${escapeMarkdown(catalog.id)}\`  `,
    `**Software:** ${escapeMarkdown(catalog.software.name)} ${escapeMarkdown(catalog.software.version)}  `,
    `**Fixture definition SHA-256:** \`${escapeMarkdown(catalog.source.sha256)}\`  `,
    `**Basis SHA-256:** \`${escapeMarkdown(catalog.basisSha256)}\``,
    '',
    '## Finite-basis formulation',
    '',
    `- Domain: ${escapeMarkdown(catalog.domain.id)} in ${escapeMarkdown(catalog.domain.lengthUnit)}; ${catalog.domain.validCellMask.filter(Boolean).length}/${catalog.domain.validCellMask.length} valid cells.`,
    `- Basis: ${escapeMarkdown(catalog.basis.spec.family)}, degree ${catalog.basis.spec.degree}, ${catalog.basis.functions.length} retained functions, ${catalog.basis.diagnostics.rejectedSupportCount} rejected by the compact-interior policy.`,
    `- Boundary policy: ${escapeMarkdown(catalog.basis.spec.boundaryPolicy)} with a ${catalog.basis.spec.interiorMarginCells}-cell collar. This is not a general no-slip claim.`,
    `- RMS velocity mass matrix: rank ${catalog.basis.diagnostics.mass.rank}/${catalog.basis.functions.length}, condition estimate ${formatted(catalog.basis.diagnostics.mass.conditionEstimate)}.`,
    `- RMS velocity-gradient roughness matrix: rank ${catalog.basis.diagnostics.roughness.rank}/${catalog.basis.functions.length}, condition estimate ${formatted(catalog.basis.diagnostics.roughness.conditionEstimate)}.`,
    `- Maximum deterministic analytic-basis divergence check: ${formatted(catalog.basis.diagnostics.maximumVerificationDivergence)} ${escapeMarkdown(catalog.basis.spec.coefficientUnit)}/${escapeMarkdown(catalog.domain.lengthUnit)}.`,
    `- Solver summary: ${escapeMarkdown(catalog.solver.adapter)} ${escapeMarkdown(catalog.solver.adapterVersion)}; Clarabel ${escapeMarkdown(catalog.solver.clarabelVersion)}. Full runtime, dependency, settings, and per-solve evidence remains in the raw batch artifacts.`,
    '',
    '## Observation model',
    '',
    'Each generated vector sensor contributes one x-component row and one y-component row. Tolerances are fixture-declared absolute component tolerances; none are inferred from VISC PIV.',
    '',
    '| Mode | Scalar rows | Tolerance [mm/s] | Provenance |',
    '| --- | ---: | ---: | --- |',
    `| exact-null | ${catalog.observationSets.exactNull.length} | 0 | ${escapeMarkdown(catalog.observationSets.exactNull[0]?.provenance ?? 'not declared')} |`,
    `| tolerance-expanded | ${catalog.observationSets.toleranceExpanded.length} | ${formatted(catalog.observationSets.toleranceExpanded[0]?.tolerance ?? 0)} | ${escapeMarkdown(catalog.observationSets.toleranceExpanded[0]?.provenance ?? 'not declared')} |`,
    '',
    '| Row ID | Sensor | Component/direction | Location [mm] | Baseline / observed [mm/s] | Exact tolerance | Expanded tolerance |',
    '| --- | --- | --- | --- | ---: | ---: | ---: |',
  ]
  for (
    let index = 0;
    index < catalog.observationSets.exactNull.length;
    index += 1
  ) {
    const exact = catalog.observationSets.exactNull[index]
    const expanded = catalog.observationSets.toleranceExpanded[index]
    const component =
      exact.type === 'point-component'
        ? exact.component
        : `(${exact.direction.map(formatted).join(', ')})`
    lines.push(
      `| ${escapeMarkdown(exact.id)} | ${escapeMarkdown(exact.sensorId)} | ${escapeMarkdown(component)} | (${formatted(exact.point.x)}, ${formatted(exact.point.y)}) | ${formatted(exact.baselineValue)} / ${formatted(exact.observedValue)} | ${formatted(exact.tolerance)} | ${formatted(expanded?.tolerance ?? 0)} |`,
    )
  }
  lines.push(
    '',
    '## Scenario results',
    '',
    '| Scenario | Mode | Velocity RMS budget [mm/s] | Gradient RMS budget [1/s] | Rank / nullity | Target | Numerical evidence | Candidate/lower evidence |',
    '| --- | --- | ---: | ---: | --- | --- | --- | ---: |',
  )
  for (const scenario of catalog.scenarios) {
    for (const target of scenario.targets) {
      lines.push(
        `| ${escapeMarkdown(scenario.id)} | ${escapeMarkdown(scenario.mode)} | ${scenario.budgets.velocityRms === null ? 'none' : formatted(scenario.budgets.velocityRms.value)} | ${scenario.budgets.velocityGradientRms === null ? 'none' : formatted(scenario.budgets.velocityGradientRms.value)} | ${scenario.observationRank} / ${scenario.observationNullity} | ${escapeMarkdown(target.target.title)} | ${supportState(target)} | ${targetValue(target)} |`,
      )
    }
  }
  lines.push('', '## Directional speed qualification', '')
  for (const scenario of catalog.scenarios) {
    const speed = speedTarget(scenario)
    if (speed === null) continue
    lines.push(
      `- ${escapeMarkdown(scenario.id)}: ${speed.directionCount} oriented directions; best candidate ${formatted(speed.lowerBound)} ${escapeMarkdown(speed.unit)}, independently checked feasible within declared primal tolerances. The exact-support geometric factor is ${speed.geometricFactor === null ? 'not declared' : formatted(speed.geometricFactor)}. No rigorous directional support upper bounds are available, so no speed upper envelope is emitted.`,
    )
  }
  lines.push(
    '',
    '## Capacity maps',
    '',
    `Every scenario evaluates ${firstScenario.capacityMap.length} fixed target points for the positive ${escapeMarkdown(firstScenario.capacityQuantity.component)}-component support problem and stores representative candidate values checked feasible within declared tolerances. The domain, basis, observation mode, and budgets remain fixed within each map; no rigorous capacity upper values are emitted.`,
    '',
    '## Numerical evidence fields',
    '',
    'The compact catalog retains verified scenario summaries, rank/nullity and singular values, representative feasible candidate coefficients, recomputed observation/budget/divergence summaries, representative native status, request and conic-form hashes, iteration count, residual/gap diagnostics, and the explicit absence of a rigorous upper certificate. These summaries are floating-point checks, not a formal exact-arithmetic proof. It does not retain per-direction canonical matrices, factors, primal/slack/dual vectors, solver settings, dependency details, or full per-solve verification records. HiddenFlowBatchEvidenceReport and raw hidden-flow batch JSON provide those fields for problems explicitly listed in a batch manifest; the committed sample manifest currently covers two representative problems. To obtain full evidence for another catalog target or capacity point, run its declared bounded problem through the batch path. Catalog generation itself does not persist the omitted per-solve payloads.',
    '',
    '## Limitations',
    '',
  )
  for (const limitation of catalog.limitations) {
    lines.push(`- ${escapeMarkdown(limitation)}`)
  }
  return `${lines.join('\n')}\n`
}

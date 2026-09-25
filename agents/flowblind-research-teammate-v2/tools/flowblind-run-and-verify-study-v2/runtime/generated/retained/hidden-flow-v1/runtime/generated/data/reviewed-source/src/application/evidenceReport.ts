import type {
  VectorAuditBatchReport,
  VectorEvidenceReport,
} from '../domain/vectorAuditModel'
import type { EvidenceResult } from '../domain/evidence'
import { resolveFrameAverageSampling } from '../domain/vectorDatasetModel'

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue)
  if (isRecord(value)) {
    const result: UnknownRecord = {}
    for (const key of Object.keys(value).sort()) {
      result[key] = stableValue(value[key])
    }
    return result
  }
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return value
  }
  if (typeof value === 'number' && Number.isFinite(value)) return value
  throw new Error('Evidence reports may contain only finite JSON values.')
}

export function stableJson(value: unknown): string {
  return `${JSON.stringify(stableValue(value), null, 2)}\n`
}

export function escapeMarkdown(value: string): string {
  return value
    .replace(/[\u202a-\u202e\u2066-\u2069]/gu, (character) =>
      `bidi-control-U${character.codePointAt(0)?.toString(16).toUpperCase()}`,
    )
    .replace(/&/gu, '&amp;')
    .replace(/</gu, '&lt;')
    .replace(/>/gu, '&gt;')
    .replace(/[\r\n]+/gu, ' ')
    .replace(/([\\*_[\]{}()#+!|])/gu, '\\$1')
    .replace(/:/gu, '&#58;')
    .replace(/`/gu, '&#96;')
}

function formatted(value: number | string): string {
  return typeof value === 'number'
    ? Number.isFinite(value)
      ? value.toPrecision(8).replace(/(?:\.0+|(\.\d+?)0+)(e|$)/u, '$1$2')
      : 'not finite'
    : escapeMarkdown(value)
}

function temporalSamplingDescription(report: VectorEvidenceReport): string {
  const temporal = report.dataset.temporal
  if (temporal.sampling.kind !== 'frame-average') {
    return `${temporal.kind}; ${temporal.sampling.kind}; ${temporal.timestampUnit}`
  }
  const sampling = resolveFrameAverageSampling(temporal.sampling)
  return (
    `${temporal.kind}; ${sampling.kind}; ${temporal.timestampUnit}; ` +
    `operator ${sampling.exposureOperator}; exposure ${formatted(sampling.exposureDuration)} ${temporal.timestampUnit}; timestamp anchor ${sampling.timestampAnchor}`
  )
}

function metricStatus(
  name: string,
  metric: EvidenceResult<unknown>,
): string[] {
  if (metric.status === 'available') {
    return [
      `| ${escapeMarkdown(name)} | available | ${formatted(metric.coverage.fraction)} | — |`,
    ]
  }
  const coverage =
    metric.status === 'insufficient-evidence'
      ? formatted(metric.coverage.fraction)
      : '—'
  return [
    `| ${escapeMarkdown(name)} | ${escapeMarkdown(metric.status)} | ${coverage} | ${escapeMarkdown(metric.reason)}: ${escapeMarkdown(metric.detail)} |`,
  ]
}

function gateRows(
  label: string,
  metric: EvidenceResult<unknown>,
): string[] {
  return metric.gates.map(
    (gate) =>
      `| ${escapeMarkdown(label)} | ${escapeMarkdown(gate.id)} | ${gate.passed ? 'pass' : 'refuse'} | ${formatted(gate.observed)} | ${formatted(gate.criterion)} | ${escapeMarkdown(gate.detail)} |`,
  )
}

function singleReportMarkdown(
  report: VectorEvidenceReport,
  headingLevel: 1 | 2,
): string[] {
  const heading = '#'.repeat(headingLevel)
  const subheading = '#'.repeat(headingLevel + 1)
  const lines = [
    `${heading} ${escapeMarkdown(report.scenario.title)}`,
    '',
    `**Report ID:** \`${escapeMarkdown(report.reportId)}\`  `,
    `**Dataset:** ${escapeMarkdown(report.dataset.title)} (\`${escapeMarkdown(report.dataset.id)}\`)  `,
    `**Software:** ${escapeMarkdown(report.software.name)} ${escapeMarkdown(report.software.version)}  `,
    `**Dataset document/source SHA-256:** \`${escapeMarkdown(report.dataset.documentSource.sha256)}\``,
    '',
    `${subheading} Inputs and provenance`,
    '',
    '| Property | Value |',
    '| --- | --- |',
    `| Dataset kind | ${escapeMarkdown(report.dataset.kind)} |`,
    `| Dataset description | ${escapeMarkdown(report.dataset.description)} |`,
    `| Coordinate frame | ${escapeMarkdown(report.dataset.coordinateFrame.id)}; ${report.dataset.coordinateFrame.dimension}D ${escapeMarkdown(report.dataset.coordinateFrame.type)}; ${escapeMarkdown(report.dataset.coordinateFrame.handedness)} |`,
    `| Length unit | ${escapeMarkdown(report.dataset.coordinateFrame.lengthUnit)} |`,
    `| Components | ${report.dataset.components.map((component) => `${escapeMarkdown(component.name)} → ${component.axis} [${escapeMarkdown(component.unit)}]`).join('; ')} |`,
    `| Frames / points | ${report.dataset.frameCount} / ${report.dataset.pointCount} |`,
    `| Time semantics | ${escapeMarkdown(temporalSamplingDescription(report))} |`,
    `| Requested / resolved time | ${formatted(report.metrics.instantaneous.requestedTime)} / ${report.metrics.instantaneous.resolvedTime === null ? 'unresolved' : formatted(report.metrics.instantaneous.resolvedTime)} ${escapeMarkdown(report.dataset.temporal.timestampUnit)} |`,
    `| Dataset source | ${escapeMarkdown(report.dataset.documentSource.reference)}; ${report.dataset.documentSource.byteLength} bytes |`,
    `| Wall evidence | ${report.dataset.wall === null ? 'not supplied' : `${escapeMarkdown(report.dataset.wall.method.kind)}; viscosity ${formatted(report.dataset.wall.dynamicViscosity.value)} ${escapeMarkdown(report.dataset.wall.dynamicViscosity.unit)}; ${report.dataset.wall.method.wallPointIndices.length} pairs`} |`,
    `| Source kind | ${escapeMarkdown(report.dataset.provenance.sourceKind)} |`,
    `| Citation | ${escapeMarkdown(report.dataset.provenance.citation)} |`,
    `| License | ${escapeMarkdown(report.dataset.provenance.license)} |`,
    '',
    `${subheading} Gate outcomes`,
    '',
    '| Metric | Status | Coverage | Reason |',
    '| --- | --- | ---: | --- |',
    ...metricStatus('Instantaneous speed', report.metrics.instantaneous.speed),
    ...metricStatus(
      'Instantaneous derivatives',
      report.metrics.instantaneous.derivatives,
    ),
    ...metricStatus(
      'Wall shear stress',
      report.metrics.instantaneous.wallShear,
    ),
    ...metricStatus('Unweighted frame mean', report.metrics.frameMean),
    ...metricStatus('Complete-cycle mean', report.metrics.completeCycle),
    '',
    '| Scope | Gate | Decision | Observed | Criterion | Detail |',
    '| --- | --- | --- | ---: | ---: | --- |',
    ...gateRows('instantaneous speed', report.metrics.instantaneous.speed),
    ...gateRows(
      'instantaneous derivatives',
      report.metrics.instantaneous.derivatives,
    ),
    ...gateRows(
      'wall shear stress',
      report.metrics.instantaneous.wallShear,
    ),
    ...gateRows('frame mean', report.metrics.frameMean),
    ...gateRows('complete cycle', report.metrics.completeCycle),
    '',
    `${subheading} Available metrics`,
    '',
  ]
  const speed = report.metrics.instantaneous.speed
  if (speed.status === 'available') {
    lines.push(
      `- Instantaneous ${escapeMarkdown(speed.value.quantity)}: mean ${formatted(speed.value.mean)} ${escapeMarkdown(speed.value.unit)}, RMS ${formatted(speed.value.rms)} ${escapeMarkdown(speed.value.unit)}, maximum ${formatted(speed.value.maximum)} ${escapeMarkdown(speed.value.unit)}.`,
    )
  }
  const derivatives = report.metrics.instantaneous.derivatives
  if (derivatives.status === 'available') {
    lines.push(
      `- Postprocessed discrete divergence: RMS ${formatted(derivatives.value.divergence.rms)} 1/s, p95 absolute ${formatted(derivatives.value.divergence.p95Absolute)} 1/s, maximum absolute ${formatted(derivatives.value.divergence.maximumAbsolute)} 1/s.`,
      `- Vorticity/curl (${escapeMarkdown(derivatives.value.vorticity.representation)}): mean magnitude ${formatted(derivatives.value.vorticity.meanMagnitude)} 1/s, maximum magnitude ${formatted(derivatives.value.vorticity.maximumMagnitude)} 1/s.`,
      `- Strain-rate magnitude (${escapeMarkdown(derivatives.value.strainRate.convention)}): mean ${formatted(derivatives.value.strainRate.mean)} 1/s, maximum ${formatted(derivatives.value.strainRate.maximum)} 1/s.`,
    )
  }
  const wallShear = report.metrics.instantaneous.wallShear
  if (wallShear.status === 'available') {
    lines.push(
      `- Wall shear stress (${escapeMarkdown(wallShear.value.method)}): mean magnitude ${formatted(wallShear.value.meanMagnitude)} Pa, maximum magnitude ${formatted(wallShear.value.maximumMagnitude)} Pa.`,
    )
  }
  const frameMean = report.metrics.frameMean
  if (frameMean.status === 'available') {
    lines.push(
      `- Unweighted frame mean of spatial mean speed: ${formatted(frameMean.value.spatialMeanSpeed)} ${escapeMarkdown(frameMean.value.unit)} across ${frameMean.value.contributingFrames}/${frameMean.value.totalFrames} frames.`,
    )
  }
  const cycle = report.metrics.completeCycle
  if (cycle.status === 'available') {
    lines.push(
      cycle.value.duration === null
        ? `- Complete-cycle time mean of spatial mean speed: ${formatted(cycle.value.spatialMeanSpeed)} ${escapeMarkdown(cycle.value.unit)}; duration unavailable.`
        : `- Complete-cycle time mean of spatial mean speed: ${formatted(cycle.value.spatialMeanSpeed)} ${escapeMarkdown(cycle.value.unit)} over ${formatted(cycle.value.duration)} ${escapeMarkdown(report.dataset.temporal.timestampUnit)}.`,
    )
  }
  if (
    speed.status !== 'available' &&
    derivatives.status !== 'available' &&
    wallShear.status !== 'available' &&
    frameMean.status !== 'available' &&
    cycle.status !== 'available'
  ) {
    lines.push('- No requested metric passed its declared evidence gate.')
  }
  lines.push('', `${subheading} Source records`, '')
  for (const source of report.dataset.provenance.sources) {
    lines.push(
      `- ${escapeMarkdown(source.path)} (${escapeMarkdown(source.format)}, ${source.byteLength} bytes): \`${escapeMarkdown(source.sha256)}\`; expected digest ${source.expectedSha256 === null ? 'explicitly unpinned' : `\`${escapeMarkdown(source.expectedSha256)}\``}.`,
    )
  }
  lines.push('', `${subheading} Transformations`, '')
  if (report.dataset.provenance.transformations.length === 0) {
    lines.push('- No source transformation was declared.')
  } else {
    for (const transformation of report.dataset.provenance.transformations) {
      lines.push(`- ${escapeMarkdown(transformation)}`)
    }
  }
  lines.push(
    '',
    `${subheading} Provenance software`,
    '',
    '| Name | Version | Source digest |',
    '| --- | --- | --- |',
  )
  for (const software of report.dataset.provenance.software) {
    lines.push(
      `| ${escapeMarkdown(software.name)} | ${escapeMarkdown(software.version)} | ${software.sha256 === null ? 'not declared' : `\`${escapeMarkdown(software.sha256)}\``} |`,
    )
  }
  lines.push('', `${subheading} Limitations`, '')
  for (const limitation of report.limitations) {
    lines.push(`- ${escapeMarkdown(limitation)}`)
  }
  return lines
}

export function renderVectorEvidenceReportMarkdown(
  report: VectorEvidenceReport,
): string {
  return `${singleReportMarkdown(report, 1).join('\n')}\n`
}

export function renderBatchEvidenceReportMarkdown(
  report: VectorAuditBatchReport,
): string {
  const lines = [
    `# FlowBlind batch evidence report: ${escapeMarkdown(report.reportId)}`,
    '',
    `**Software:** ${escapeMarkdown(report.software.name)} ${escapeMarkdown(report.software.version)}  `,
    `**Manifest SHA-256:** \`${escapeMarkdown(report.manifestSource.sha256)}\`  `,
    `**Scenario count:** ${report.reports.length}`,
    `**Pinned canonical inputs:** ${report.manifest.datasets.filter((dataset) => dataset.expectedSha256 !== null).length}/${report.manifest.datasets.length}`,
    '',
  ]
  for (const scenarioReport of report.reports) {
    for (const line of singleReportMarkdown(scenarioReport, 2)) {
      lines.push(line)
    }
    lines.push('')
  }
  return `${lines.join('\n')}\n`
}

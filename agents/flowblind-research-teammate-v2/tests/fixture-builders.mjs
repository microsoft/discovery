import { createHash } from 'node:crypto'

export const REGIONAL_FIXTURE = Object.freeze({
  id: 'FX-REG-17x19-v2',
  reference: 'fx-reg-17x19-v2.csv',
  width: 17,
  height: 19,
  dataRows: 323,
  header: 'x,y,reference_value,candidate_value',
})

export const VECTOR_FIXTURE = Object.freeze({
  id: 'FX-VEC-7x6x13-v2',
  reference: 'fx-vec-7x6x13-v2.csv',
  width: 7,
  height: 6,
  frames: 13,
  dataRows: 546,
  header: 'time,x,y,u,v,valid',
})

export const HIDDEN_FIXTURE = Object.freeze({
  id: 'FX-HID-MIN-v2',
  reference: 'fx-hid-min-v2.problem.json',
})

function csvNumber(value) {
  if (!Number.isFinite(value)) {
    throw new Error(
      'Fixture values must remain finite.',
    )
  }
  const rounded = Number(value.toFixed(8))
  return Object.is(rounded, -0)
    ? '0'
    : String(rounded)
}

export function regionalFixtureBytes() {
  const lines = [REGIONAL_FIXTURE.header]
  for (
    let y = 0;
    y < REGIONAL_FIXTURE.height;
    y += 1
  ) {
    for (
      let x = 0;
      x < REGIONAL_FIXTURE.width;
      x += 1
    ) {
      const reference = (3 * x - 2 * y + 7) / 8
      const offset =
        (((x + 2 * y) % 5) - 2) / 40
      lines.push(
        [
          x,
          y,
          reference,
          reference + offset,
        ]
          .map(csvNumber)
          .join(','),
      )
    }
  }
  return Buffer.from(
    `${lines.join('\n')}\n`,
    'utf8',
  )
}

export function vectorFixtureBytes() {
  const lines = [VECTOR_FIXTURE.header]
  for (
    let frame = 0;
    frame < VECTOR_FIXTURE.frames;
    frame += 1
  ) {
    const time = frame / 12
    for (
      let y = 0;
      y < VECTOR_FIXTURE.height;
      y += 1
    ) {
      for (
        let x = 0;
        x < VECTOR_FIXTURE.width;
        x += 1
      ) {
        const u =
          (6 * x - 2 * y + frame) / 8
        const v =
          (-3 * x + 5 * y - 2 * frame) /
          10
        lines.push(
          [time, x, y, u, v, 1]
            .map(csvNumber)
            .join(','),
        )
      }
    }
  }
  return Buffer.from(
    `${lines.join('\n')}\n`,
    'utf8',
  )
}

export function hiddenFixtureProblem() {
  const coordinateFrameId = 'fx-hid-frame-r17-v2'
  return {
    schemaVersion: 1,
    id: 'fx-hid-min-problem-r17-v2',
    title: 'Minimal v2 hidden-flow validation problem',
    description:
      'A compact schema-driven hidden-flow problem with novel validation identifiers and values.',
    domain: {
      id: 'fx-hid-domain-r17-v2',
      coordinateFrameId,
      lengthUnit: 'mm',
      xEdges: [-1.25, 1.5, 4.75],
      yEdges: [-2.5, 0.25, 3.5],
      validCellMask: [true, true, true, true],
    },
    basis: {
      family:
        'tensor-cardinal-cubic-streamfunction-v1',
      degree: 3,
      spacingX: 2.75,
      spacingY: 2.25,
      streamfunctionLengthScale: 1.625,
      interiorMarginCells: 1,
      quadratureOrder: 4,
      coefficientUnit: 'mm/s',
      boundaryPolicy:
        'compact-support-inside-valid-cell-union',
      centers: [
        {
          id: 'fx-hid-basis-center-r17-v2',
          point: {
            x: 1.375,
            y: 0.625,
          },
        },
      ],
    },
    observations: [
      {
        type: 'point-direction',
        id: 'fx-hid-observation-r17-v2',
        sensorId: 'fx-hid-sensor-r17-v2',
        point: {
          x: 0.875,
          y: -0.375,
        },
        coordinateFrameId,
        unit: 'mm/s',
        direction: [0.6, 0.8],
        baselineValue: 2.375,
        observedValue: 2.4375,
        tolerance: 0.0875,
        provenance:
          'Novel deterministic observation for the FX-HID-MIN-v2 schema fixture.',
      },
    ],
    budgets: {
      velocityRms: {
        value: 0.625,
        unit: 'mm/s',
      },
      velocityGradientRms: {
        value: 0.275,
        unit: '1/s',
      },
    },
    target: {
      type: 'point-strain-component',
      id: 'fx-hid-target-sxy-r17-v2',
      title: 'Novel validation shear target',
      point: {
        x: 2.125,
        y: 1.375,
      },
      component: 'xy',
      unit: '1/s',
    },
    numerics: {
      rankRelativeTolerance: 3e-9,
      basisConditionLimit: 75_000_000,
      verificationAbsoluteTolerance: 1.25e-6,
      verificationRelativeTolerance: 2.5e-6,
      maximumSolverIterations: 257,
    },
    provenance: {
      sourceKind: 'generated',
      citation:
        'FX-HID-MIN-v2 package validation fixture; no retained example bytes or identifiers are reused.',
      license: 'CC0-1.0',
      transformations: [
        'Declared a four-cell validation domain with one novel streamfunction basis center.',
        'Declared one deterministic directional observation with a nonzero validation residual.',
      ],
    },
    limitations: [
      'This compact fixture validates schema and bridge custody only; it is not physiological evidence.',
      'No scientific result or live execution claim follows from this fixture.',
    ],
  }
}

function stableValue(value) {
  if (Array.isArray(value)) {
    return value.map(stableValue)
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [
          key,
          stableValue(value[key]),
        ]),
    )
  }
  return value
}

export function hiddenFixtureBytes() {
  return Buffer.from(
    `${JSON.stringify(
      stableValue(hiddenFixtureProblem()),
      null,
      2,
    )}\n`,
    'utf8',
  )
}

export function fixtureIdentity(bytes) {
  return Object.freeze({
    byteLength: bytes.byteLength,
    sha256: createHash('sha256')
      .update(bytes)
      .digest('hex'),
  })
}

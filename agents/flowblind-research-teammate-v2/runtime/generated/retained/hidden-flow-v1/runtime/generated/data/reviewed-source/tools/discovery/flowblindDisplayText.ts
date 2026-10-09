export const FLOWBLIND_MAX_DISPLAY_TEXT_CODE_POINTS = 4_096

export type FlowBlindDisplayTextErrorCode =
  | 'display-text-empty'
  | 'display-text-not-normalized'
  | 'display-text-too-long'
  | 'display-text-unsafe-character'

export class FlowBlindDisplayTextError extends Error {
  readonly code: FlowBlindDisplayTextErrorCode

  constructor(
    code: FlowBlindDisplayTextErrorCode,
    message: string,
  ) {
    super(message)
    this.name = 'FlowBlindDisplayTextError'
    this.code = code
  }
}

function unsafeDisplayCodePoint(code: number): boolean {
  return (
    code <= 0x1f ||
    (code >= 0x7f && code <= 0x9f) ||
    code === 0xad ||
    code === 0x61c ||
    (code >= 0x200b && code <= 0x200f) ||
    code === 0x2028 ||
    code === 0x2029 ||
    (code >= 0x202a && code <= 0x202e) ||
    (code >= 0x2060 && code <= 0x206f) ||
    code === 0xfeff ||
    (code >= 0xfff9 && code <= 0xfffb)
  )
}

export function validateFlowBlindDisplayText(
  value: unknown,
  label: string,
  maximumCodePoints =
    FLOWBLIND_MAX_DISPLAY_TEXT_CODE_POINTS,
): string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new FlowBlindDisplayTextError(
      'display-text-empty',
      `${label} must be nonempty text.`,
    )
  }
  if (
    value !== value.trim() ||
    value !== value.normalize('NFC')
  ) {
    throw new FlowBlindDisplayTextError(
      'display-text-not-normalized',
      `${label} must be trimmed NFC text.`,
    )
  }
  const codePoints = [...value]
  if (codePoints.length > maximumCodePoints) {
    throw new FlowBlindDisplayTextError(
      'display-text-too-long',
      `${label} must not exceed ${maximumCodePoints} Unicode code points.`,
    )
  }
  for (const character of codePoints) {
    const code = character.codePointAt(0)
    if (code !== undefined && unsafeDisplayCodePoint(code)) {
      throw new FlowBlindDisplayTextError(
        'display-text-unsafe-character',
        `${label} contains an unsafe display-control character.`,
      )
    }
  }
  return value
}

export function validateFlowBlindOptionalDisplayText(
  value: unknown,
  label: string,
  maximumCodePoints =
    FLOWBLIND_MAX_DISPLAY_TEXT_CODE_POINTS,
): string | null {
  return value === null
    ? null
    : validateFlowBlindDisplayText(
        value,
        label,
        maximumCodePoints,
      )
}

export function validateFlowBlindPathSegment(
  value: string,
  label: string,
): string {
  const validated = validateFlowBlindDisplayText(
    value,
    label,
    255,
  )
  if (
    validated === '.' ||
    validated === '..' ||
    validated.includes('/') ||
    validated.includes('\\') ||
    validated.includes(':')
  ) {
    throw new FlowBlindDisplayTextError(
      'display-text-unsafe-character',
      `${label} is not a safe visible path segment.`,
    )
  }
  return validated
}

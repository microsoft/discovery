import { randomUUID } from 'node:crypto'
import {
  constants,
  type BigIntStats,
} from 'node:fs'
import {
  link,
  lstat,
  mkdir,
  open,
  opendir,
  realpath,
  unlink,
} from 'node:fs/promises'
import {
  basename,
  dirname,
  isAbsolute,
  relative,
  resolve,
  sep,
} from 'node:path'
import type {
  CatalogHiddenFlowRunResponse,
  CatalogHiddenFlowUnavailableResponse,
  CatalogHiddenFlowVerifiedRun,
  ExecutedCatalogHiddenFlow,
} from './execution.ts'
import type {
  CatalogHiddenFlowPreparedResponse,
} from './preparation.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REPORT_VERIFICATION_SCHEMA_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
  CatalogHiddenFlowError,
  artifact,
  artifactIdentity,
  sha256Bytes,
  stableJson,
  throwIfCatalogHiddenFlowAborted,
  utf8Bytes,
} from './profile.ts'
import type {
  CatalogHiddenFlowArtifact,
  CatalogHiddenFlowArtifactIdentity,
  CatalogHiddenFlowPackageEvidence,
  CatalogHiddenFlowRefusal,
} from './profile.ts'

export type CatalogHiddenFlowPublicationCheckpointPhase =
  | 'before-write-json'
  | 'before-write-markdown'
  | 'before-commit-marker'
  | 'after-commit-marker'

export interface CatalogHiddenFlowPublicationOptions {
  readonly signal?: AbortSignal
  readonly checkpoint?: (
    phase: CatalogHiddenFlowPublicationCheckpointPhase,
  ) => void | Promise<void>
}

export interface CatalogHiddenFlowReportVerificationRecord {
  readonly $schema:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_REPORT_VERIFICATION_SCHEMA_ID
  readonly schemaVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION
  readonly recordType:
    'flowblind-catalog-hidden-flow-report-verification-v1'
  readonly status: 'verified-report-complete'
  readonly capability: {
    readonly capabilityId:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID
    readonly capabilityVersion:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
    readonly methodFamily:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY
    readonly packageVersion:
      typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION
  }
  readonly preparation: {
    readonly id: string
    readonly associationSha256: string
    readonly bundle: CatalogHiddenFlowArtifactIdentity
  }
  readonly problem: {
    readonly id: string
    readonly identity: CatalogHiddenFlowArtifactIdentity
  }
  readonly software: CatalogHiddenFlowPackageEvidence
  readonly deterministicReplay:
    CatalogHiddenFlowVerifiedRun['deterministicReplay']
  readonly artifacts: {
    readonly json: CatalogHiddenFlowArtifactIdentity
    readonly markdown: CatalogHiddenFlowArtifactIdentity
  }
  readonly publication: {
    readonly directory: string
    readonly commitMarker: 'report-verification.json'
    readonly pointOfNoReturn:
      'exclusive-report-verification-commit-marker'
    readonly policy:
      'deterministic-exclusive-create-or-verify-content-then-commit-marker'
    readonly distributedExactlyOnceClaim: false
  }
}

export interface CatalogHiddenFlowPackagedRunResponse
  extends Omit<
    CatalogHiddenFlowRunResponse,
    'artifacts' | 'publication'
  > {
  readonly artifacts: {
    readonly json: CatalogHiddenFlowArtifactIdentity
    readonly markdown: CatalogHiddenFlowArtifactIdentity
    readonly verification:
      CatalogHiddenFlowArtifactIdentity
  }
  readonly publication: {
    readonly state: 'marker-verified'
    readonly promotable: true
    readonly directory: string
    readonly pointOfNoReturn:
      'exclusive-report-verification-commit-marker'
    readonly policy:
      'deterministic-exclusive-create-or-verify-content-then-commit-marker'
    readonly distributedExactlyOnceClaim: false
  }
}

export interface PublishedCatalogHiddenFlowReportSet {
  readonly response:
    CatalogHiddenFlowPackagedRunResponse
  readonly verificationRecord:
    CatalogHiddenFlowReportVerificationRecord
}

export type CatalogHiddenFlowActionResponse =
  | CatalogHiddenFlowPreparedResponse
  | CatalogHiddenFlowRunResponse
  | CatalogHiddenFlowPackagedRunResponse
  | CatalogHiddenFlowUnavailableResponse
  | CatalogHiddenFlowRefusal

export interface CatalogHiddenFlowActionResponseSemanticContext {
  readonly verifiedRun?: CatalogHiddenFlowVerifiedRun
  readonly reportVerification?:
    CatalogHiddenFlowReportVerificationRecord
  readonly verificationArtifact?:
    CatalogHiddenFlowArtifactIdentity
}

interface PublicationReferences {
  readonly directory: string
  readonly json: string
  readonly markdown: string
  readonly verification: string
}

function samePath(left: string, right: string): boolean {
  const normalizedLeft = resolve(left)
  const normalizedRight = resolve(right)
  return process.platform === 'win32'
    ? normalizedLeft.toLowerCase() ===
        normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight
}

function confined(root: string, reference: string): string {
  const path = resolve(root, reference)
  const child = relative(root, path)
  if (
    child.length === 0 ||
    child === '..' ||
    child.startsWith(`..${sep}`) ||
    isAbsolute(child)
  ) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'A hidden-flow report-set reference escaped the host-provided output root.',
    )
  }
  return path
}

async function ordinaryDirectory(
  path: string,
  allowCreate = false,
  allowAlias = false,
): Promise<void> {
  if (allowCreate) {
    try {
      await mkdir(path)
    } catch (error) {
      if (
        typeof error !== 'object' ||
        error === null ||
        (error as NodeJS.ErrnoException).code !== 'EEXIST'
      ) {
        throw new CatalogHiddenFlowError(
          'concurrent-publication-conflict',
          'publication',
          'The deterministic hidden-flow report directory could not be created.',
          { cause: error },
        )
      }
    }
  }
  try {
    const metadata = await lstat(path)
    const canonical = await realpath(path)
    if (
      metadata.isSymbolicLink() ||
      !metadata.isDirectory() ||
      (!allowAlias && !samePath(path, canonical))
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'Hidden-flow report directories must be ordinary directories without aliases or links.',
      )
    }
  } catch (error) {
    if (error instanceof CatalogHiddenFlowError) throw error
    throw new CatalogHiddenFlowError(
      'output-publication-conflict',
      'publication',
      'The host-provided hidden-flow output directory is unavailable.',
      { cause: error },
    )
  }
}

async function ensureOutputRoot(
  rootInput: string,
): Promise<string> {
  const requested = resolve(rootInput)
  await ordinaryDirectory(requested, false, true)
  return realpath(requested)
}

async function fileExists(path: string): Promise<boolean> {
  try {
    await lstat(path)
    return true
  } catch (error) {
    if (
      typeof error === 'object' &&
      error !== null &&
      (error as NodeJS.ErrnoException).code === 'ENOENT'
    ) {
      return false
    }
    throw error
  }
}

async function syncDirectory(path: string): Promise<void> {
  if (process.platform === 'win32') return
  const handle = await open(path, constants.O_RDONLY)
  try {
    await handle.sync()
  } finally {
    await handle.close()
  }
}

async function removeStagingFile(
  path: string,
  directory: string,
  unlinkFile: (path: string) => Promise<void> = unlink,
): Promise<void> {
  try {
    await unlinkFile(path)
    await syncDirectory(directory)
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'output-publication-partial',
      'publication',
      'A hidden-flow staging entry could not be removed and synchronized authoritatively.',
      { cause: error },
    )
  }
}

async function readHandle(
  handle: Awaited<ReturnType<typeof open>>,
  maximumBytes: number,
): Promise<Buffer> {
  const chunks: Buffer[] = []
  let total = 0
  while (true) {
    const chunk = Buffer.allocUnsafe(64 * 1024)
    const { bytesRead } = await handle.read(
      chunk,
      0,
      chunk.byteLength,
      null,
    )
    if (bytesRead === 0) break
    total += bytesRead
    if (total > maximumBytes) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A hidden-flow report artifact exceeds its verified byte length.',
      )
    }
    chunks.push(chunk.subarray(0, bytesRead))
  }
  return Buffer.concat(chunks, total)
}

async function verifiedFile(
  path: string,
  expected: CatalogHiddenFlowArtifactIdentity,
  missingCode:
    | 'output-artifact-tampered'
    | 'output-publication-partial',
): Promise<Buffer> {
  let before
  try {
    before = await lstat(path, { bigint: true })
  } catch (error) {
    throw new CatalogHiddenFlowError(
      missingCode,
      'publication',
      missingCode === 'output-publication-partial'
        ? 'A marker-committed hidden-flow report is missing a required artifact.'
        : 'A hidden-flow report artifact is unavailable.',
      { cause: error },
    )
  }
  if (
    before.isSymbolicLink() ||
    !before.isFile() ||
    before.nlink !== 1n ||
    before.size !== BigInt(expected.byteLength)
  ) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'A hidden-flow report artifact is not the expected single-link ordinary file.',
    )
  }
  let handle
  try {
    handle = await open(
      path,
      constants.O_RDONLY |
        (typeof constants.O_NOFOLLOW === 'number'
          ? constants.O_NOFOLLOW
          : 0),
    )
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'A hidden-flow report artifact could not be opened safely.',
      { cause: error },
    )
  }
  try {
    const opened = await handle.stat({ bigint: true })
    if (
      !opened.isFile() ||
      opened.nlink !== 1n ||
      opened.size !== before.size
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A hidden-flow report artifact changed before it could be read.',
      )
    }
    const bytes = await readHandle(
      handle,
      expected.byteLength,
    )
    const after = await handle.stat({ bigint: true })
    const final = await lstat(path, { bigint: true })
    const canonical = await realpath(path)
    if (
      before.dev !== opened.dev ||
      before.ino !== opened.ino ||
      opened.dev !== after.dev ||
      opened.ino !== after.ino ||
      opened.size !== after.size ||
      opened.mtimeNs !== after.mtimeNs ||
      after.dev !== final.dev ||
      after.ino !== final.ino ||
      final.nlink !== 1n ||
      final.isSymbolicLink() ||
      !samePath(path, canonical) ||
      bytes.byteLength !== expected.byteLength ||
      sha256Bytes(bytes) !== expected.sha256
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A hidden-flow report artifact changed or failed identity verification.',
      )
    }
    return bytes
  } finally {
    await handle.close()
  }
}

async function verifiedStagingHardLink(
  path: string,
  expected: CatalogHiddenFlowArtifactIdentity,
  linked: BigIntStats,
): Promise<void> {
  let handle
  try {
    handle = await open(
      path,
      constants.O_RDONLY |
        (typeof constants.O_NOFOLLOW === 'number'
          ? constants.O_NOFOLLOW
          : 0),
    )
    const opened = await handle.stat({ bigint: true })
    if (
      !opened.isFile() ||
      opened.dev !== linked.dev ||
      opened.ino !== linked.ino ||
      opened.nlink !== linked.nlink ||
      opened.size !== BigInt(expected.byteLength)
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A hidden-flow staging hard link changed before it could be verified.',
      )
    }
    const bytes = await readHandle(
      handle,
      expected.byteLength,
    )
    const after = await handle.stat({ bigint: true })
    const final = await lstat(path, { bigint: true })
    if (
      after.dev !== opened.dev ||
      after.ino !== opened.ino ||
      after.nlink !== opened.nlink ||
      after.size !== opened.size ||
      after.mtimeNs !== opened.mtimeNs ||
      final.dev !== after.dev ||
      final.ino !== after.ino ||
      final.nlink !== after.nlink ||
      final.isSymbolicLink() ||
      bytes.byteLength !== expected.byteLength ||
      sha256Bytes(bytes) !== expected.sha256
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A hidden-flow staging hard link failed expected-byte verification.',
      )
    }
  } catch (error) {
    if (error instanceof CatalogHiddenFlowError) throw error
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'A hidden-flow staging hard link could not be opened safely.',
      { cause: error },
    )
  } finally {
    await handle?.close().catch(() => undefined)
  }
}

async function installCompleteFile(
  path: string,
  bytes: Buffer,
  mediaType:
    CatalogHiddenFlowArtifactIdentity['mediaType'],
): Promise<void> {
  const expected = artifactIdentity(
    artifact(basename(path), bytes, mediaType),
  )
  if (await fileExists(path)) {
    try {
      await verifiedFile(
        path,
        expected,
        'output-artifact-tampered',
      )
      return
    } catch (error) {
      throw new CatalogHiddenFlowError(
        'concurrent-publication-conflict',
        'publication',
        'A deterministic hidden-flow report target already contains different or incomplete bytes.',
        { cause: error },
      )
    }
  }
  const parent = dirname(path)
  await ordinaryDirectory(parent)
  const temporary = resolve(
    parent,
    `.${basename(path)}.stage-${randomUUID()}`,
  )
  let temporaryCreated = false
  let handle
  try {
    handle = await open(temporary, 'wx', 0o600)
    temporaryCreated = true
    try {
      await handle.writeFile(bytes)
      await handle.sync()
    } finally {
      await handle.close()
      handle = undefined
    }
    await verifiedFile(
      temporary,
      {
        ...expected,
        reference: basename(temporary),
      },
      'output-artifact-tampered',
    )
    try {
      await link(temporary, path)
      await syncDirectory(parent)
    } catch (error) {
      const code =
        typeof error === 'object' && error !== null
          ? (error as NodeJS.ErrnoException).code
          : undefined
      if (code !== 'EEXIST') {
        throw new CatalogHiddenFlowError(
          'concurrent-publication-conflict',
          'publication',
          'A complete hidden-flow report artifact could not be installed atomically.',
          { cause: error },
        )
      }
      try {
        await verifiedFile(
          path,
          expected,
          'output-artifact-tampered',
        )
      } catch (verificationError) {
        throw new CatalogHiddenFlowError(
          'concurrent-publication-conflict',
          'publication',
          'A concurrent hidden-flow publication installed different immutable bytes.',
          { cause: verificationError },
        )
      }
    }
  } finally {
    await handle?.close().catch(() => undefined)
    if (temporaryCreated) {
      await removeStagingFile(temporary, parent)
    }
  }
}

function references(
  preparationSha256: string,
): PublicationReferences {
  const directory =
    `flowblind-hidden-flow-study-${preparationSha256}`
  return {
    directory,
    json: `${directory}/verified-run.json`,
    markdown: `${directory}/report.md`,
    verification:
      `${directory}/report-verification.json`,
  }
}

const SHA256_PATTERN = /^[a-f0-9]{64}$/u

function semantic(
  condition: unknown,
  detail: string,
): asserts condition {
  if (!condition) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      detail,
    )
  }
}

function assertContentAddressedReference(
  identity: CatalogHiddenFlowArtifactIdentity,
  prefix: string,
  suffix: string,
  label: string,
): void {
  semantic(
    SHA256_PATTERN.test(identity.sha256) &&
      identity.reference ===
        `${prefix}${identity.sha256}${suffix}`,
    `${label} does not match its content-addressed SHA-256 reference.`,
  )
}

function assertStableJsonIdentity(
  identity: CatalogHiddenFlowArtifactIdentity,
  value: unknown,
  label: string,
): void {
  const bytes = utf8Bytes(stableJson(value))
  semantic(
    identity.mediaType === 'application/json' &&
      identity.byteLength === bytes.byteLength &&
      identity.sha256 === sha256Bytes(bytes),
    `${label} does not bind the canonical JSON bytes.`,
  )
}

export function assertCatalogHiddenFlowVerifiedRunSemanticContract(
  run: CatalogHiddenFlowVerifiedRun,
): void {
  semantic(
    run.deterministicReplay.matched === true &&
      SHA256_PATTERN.test(
        run.deterministicReplay.firstExecutionSha256,
      ) &&
      run.deterministicReplay.firstExecutionSha256 ===
        run.deterministicReplay.replayExecutionSha256,
    'A matched hidden-flow replay must carry equal first and replay execution hashes.',
  )
  assertContentAddressedReference(
    run.preparation.artifact,
    'flowblind-catalog-hidden-flow-preparation-',
    '.json',
    'The hidden-flow preparation artifact',
  )
  assertContentAddressedReference(
    run.problem.identity,
    'flowblind-catalog-hidden-flow-problem-',
    '.json',
    'The hidden-flow problem artifact',
  )
}

function assertResponseMatchesVerifiedRun(
  response:
    | CatalogHiddenFlowRunResponse
    | CatalogHiddenFlowPackagedRunResponse,
  run: CatalogHiddenFlowVerifiedRun,
): void {
  assertCatalogHiddenFlowVerifiedRunSemanticContract(run)
  semantic(
    response.capabilityVersion ===
      run.capabilityVersion &&
      response.deterministicReplayMatched === true &&
      response.containsResults ===
        (run.outcome.kind !== 'unavailable') &&
      sameJson(response.humanContext, run.humanContext) &&
      sameJson(response.outcome, run.outcome) &&
      sameJson(response.problem, {
        id: run.problem.id,
        title: run.problem.title,
        targetId: run.problem.targetId,
        targetType: run.problem.targetType,
      }) &&
      sameJson(response.review, {
        authorityVersion: run.review.authorityVersion,
        reviewScope: run.review.reviewScope,
        claimBoundary: run.review.claimBoundary,
      }),
    'The hidden-flow action response does not match its canonical verified-run record.',
  )
  assertStableJsonIdentity(
    response.artifacts.json,
    run,
    'The hidden-flow verified-run identity',
  )
}

export function assertCatalogHiddenFlowReportSetSemanticContract(
  response: CatalogHiddenFlowPackagedRunResponse,
  verificationRecord:
    CatalogHiddenFlowReportVerificationRecord,
  verificationArtifact:
    CatalogHiddenFlowArtifactIdentity,
  verifiedRun: CatalogHiddenFlowVerifiedRun,
): void {
  assertResponseMatchesVerifiedRun(response, verifiedRun)
  const preparationSha256 =
    verificationRecord.preparation.bundle.sha256
  semantic(
    SHA256_PATTERN.test(preparationSha256),
    'The hidden-flow report set has an invalid preparation digest.',
  )
  assertContentAddressedReference(
    verificationRecord.preparation.bundle,
    'flowblind-catalog-hidden-flow-preparation-',
    '.json',
    'The report-set preparation artifact',
  )
  const expected = references(preparationSha256)
  semantic(
    verificationRecord.deterministicReplay.matched ===
      true &&
      verificationRecord.deterministicReplay
        .firstExecutionSha256 ===
        verificationRecord.deterministicReplay
          .replayExecutionSha256 &&
      sameJson(
        verificationRecord.deterministicReplay,
        verifiedRun.deterministicReplay,
      ),
    'The report-verification marker does not bind one matched deterministic replay.',
  )
  semantic(
    verificationRecord.publication.directory ===
      expected.directory &&
      verificationRecord.artifacts.json.reference ===
        expected.json &&
      verificationRecord.artifacts.markdown.reference ===
        expected.markdown &&
      verificationArtifact.reference ===
        expected.verification,
    'The report-verification marker does not bind every member to its preparation-derived study directory.',
  )
  semantic(
    response.publication.directory ===
      expected.directory &&
      response.artifacts.json.reference ===
        expected.json &&
      response.artifacts.markdown.reference ===
        expected.markdown &&
      response.artifacts.verification.reference ===
        expected.verification,
    'The packaged action response does not identify the same canonical report set as its marker.',
  )
  semantic(
    sameJson(
      response.artifacts.json,
      verificationRecord.artifacts.json,
    ) &&
      sameJson(
        response.artifacts.markdown,
        verificationRecord.artifacts.markdown,
      ) &&
      sameJson(
        response.artifacts.verification,
        verificationArtifact,
      ),
    'The packaged action response does not preserve the marker member identities.',
  )
  semantic(
    verificationRecord.preparation.id ===
      verifiedRun.preparation.id &&
      verificationRecord.preparation.associationSha256 ===
        verifiedRun.preparation.associationSha256 &&
      sameJson(
        verificationRecord.preparation.bundle,
        verifiedRun.preparation.artifact,
      ) &&
      verificationRecord.problem.id ===
        verifiedRun.problem.id &&
      sameJson(
        verificationRecord.problem.identity,
        verifiedRun.problem.identity,
      ) &&
      sameJson(
        verificationRecord.software,
        verifiedRun.software,
      ),
    'The report-verification marker does not preserve the verified-run authority chain.',
  )
  assertStableJsonIdentity(
    verificationRecord.artifacts.json,
    verifiedRun,
    'The report-set verified-run identity',
  )
  assertStableJsonIdentity(
    verificationArtifact,
    verificationRecord,
    'The report-verification marker identity',
  )
}

export function assertCatalogHiddenFlowActionResponseSemanticContract(
  response: CatalogHiddenFlowActionResponse,
  context:
    CatalogHiddenFlowActionResponseSemanticContext = {},
): void {
  if (response.status === 'prepared-awaiting-confirmation') {
    semantic(
      response.preparationBundle.mediaType ===
        'application/json',
      'The hidden-flow preparation response must identify canonical JSON.',
    )
    assertContentAddressedReference(
      response.preparationBundle,
      'flowblind-catalog-hidden-flow-preparation-',
      '.json',
      'The hidden-flow preparation response artifact',
    )
    return
  }
  if (
    response.status === 'unavailable' ||
    response.status === 'refused'
  ) {
    return
  }
  semantic(
    context.verifiedRun !== undefined,
    'Semantic validation of a report-complete response requires its verified-run record.',
  )
  if (
    response.publication.state ===
    'uncommitted-core-bytes'
  ) {
    assertResponseMatchesVerifiedRun(
      response,
      context.verifiedRun,
    )
    assertContentAddressedReference(
      response.artifacts.json,
      'flowblind-catalog-hidden-flow-run-',
      '.json',
      'The uncommitted hidden-flow JSON artifact',
    )
    assertContentAddressedReference(
      response.artifacts.markdown,
      'flowblind-catalog-hidden-flow-report-',
      '.md',
      'The uncommitted hidden-flow Markdown artifact',
    )
    return
  }
  semantic(
    context.reportVerification !== undefined &&
      context.verificationArtifact !== undefined,
    'Semantic validation of a committed response requires its report-verification record and marker identity.',
  )
  const committed =
    response as CatalogHiddenFlowPackagedRunResponse
  assertCatalogHiddenFlowReportSetSemanticContract(
    committed,
    context.reportVerification,
    context.verificationArtifact,
    context.verifiedRun,
  )
}

function parseCanonicalObject(
  bytes: Buffer,
  label: string,
): Record<string, unknown> {
  let value: unknown
  try {
    value = JSON.parse(bytes.toString('utf8')) as unknown
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      `${label} is invalid JSON.`,
      { cause: error },
    )
  }
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value) ||
    stableJson(value) !== bytes.toString('utf8')
  ) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      `${label} is not canonical closed JSON.`,
    )
  }
  return value as Record<string, unknown>
}

function parseVerifiedRun(
  artifactValue: CatalogHiddenFlowArtifact,
): CatalogHiddenFlowVerifiedRun {
  const value = parseCanonicalObject(
    artifactValue.bytes,
    'The hidden-flow verified run',
  )
  if (
    value.recordType !==
      'flowblind-catalog-hidden-flow-verified-run-v1' ||
    value.schemaVersion !==
      FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION ||
    value.capabilityVersion !==
      FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  ) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'The hidden-flow verified-run artifact has an invalid identity.',
    )
  }
  const run =
    value as unknown as CatalogHiddenFlowVerifiedRun
  assertCatalogHiddenFlowVerifiedRunSemanticContract(run)
  return run
}

type PublicationMemberName =
  | 'verified-run.json'
  | 'report.md'
  | 'report-verification.json'

const STAGING_NAME =
  /^\.(verified-run\.json|report\.md|report-verification\.json)\.stage-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u

function expectedPublicationMembers(
  record: CatalogHiddenFlowReportVerificationRecord,
  marker: CatalogHiddenFlowArtifactIdentity,
): Readonly<Record<
  PublicationMemberName,
  CatalogHiddenFlowArtifactIdentity
>> {
  return {
    'verified-run.json': record.artifacts.json,
    'report.md': record.artifacts.markdown,
    'report-verification.json': marker,
  }
}

export async function reconcileCatalogHiddenFlowPublicationStaging(
  directory: string,
  expected: Readonly<Record<
    PublicationMemberName,
    CatalogHiddenFlowArtifactIdentity
  >>,
  unlinkFile: (path: string) => Promise<void> = unlink,
): Promise<void> {
  const handle = await opendir(directory)
  let entries = 0
  for await (const entry of handle) {
    entries += 1
    if (entries > 32) {
      throw new CatalogHiddenFlowError(
        'output-publication-partial',
        'publication',
        'The deterministic hidden-flow report directory contains too many entries.',
      )
    }
    const match = STAGING_NAME.exec(entry.name)
    if (match === null) continue
    if (!entry.isFile()) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A recognized hidden-flow staging entry is not an ordinary file.',
      )
    }
    const member = match[1] as PublicationMemberName
    const identity = expected[member]
    const stagingPath = resolve(directory, entry.name)
    const finalPath = resolve(directory, member)
    const staging = await lstat(stagingPath, {
      bigint: true,
    })
    if (
      staging.isSymbolicLink() ||
      !staging.isFile() ||
      staging.size !== BigInt(identity.byteLength)
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A recognized hidden-flow staging entry is not the expected ordinary artifact.',
      )
    }
    if (await fileExists(finalPath)) {
      const final = await lstat(finalPath, {
        bigint: true,
      })
      if (
        final.isSymbolicLink() ||
        !final.isFile()
      ) {
        throw new CatalogHiddenFlowError(
          'output-artifact-tampered',
          'publication',
          'A hidden-flow staging entry targets a non-ordinary final artifact.',
        )
      }
      if (
        staging.dev === final.dev &&
        staging.ino === final.ino
      ) {
        if (
          staging.nlink < 2n ||
          staging.nlink !== final.nlink
        ) {
          throw new CatalogHiddenFlowError(
            'output-artifact-tampered',
            'publication',
            'A hidden-flow staging hard link has an inconsistent link count.',
          )
        }
        await verifiedStagingHardLink(
          stagingPath,
          identity,
          staging,
        )
      } else {
        await verifiedFile(
          stagingPath,
          {
            ...identity,
            reference: entry.name,
          },
          'output-artifact-tampered',
        )
      }
    } else {
      await verifiedFile(
        stagingPath,
        {
          ...identity,
          reference: entry.name,
        },
        'output-artifact-tampered',
      )
    }
    const current = await lstat(stagingPath, {
      bigint: true,
    })
    if (
      current.dev !== staging.dev ||
      current.ino !== staging.ino ||
      current.size !== staging.size ||
      current.nlink !== staging.nlink ||
      current.mtimeNs !== staging.mtimeNs
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'A hidden-flow staging entry changed before reconciliation.',
      )
    }
    await removeStagingFile(
      stagingPath,
      directory,
      unlinkFile,
    )
  }
}

async function verifyDirectoryEntries(
  directory: string,
): Promise<void> {
  const expected = new Set([
    'verified-run.json',
    'report.md',
    'report-verification.json',
  ])
  const seen = new Set<string>()
  const seenFolded = new Set<string>()
  const handle = await opendir(directory)
  for await (const entry of handle) {
    const folded = entry.name.toLowerCase()
    if (
      seen.has(entry.name) ||
      seenFolded.has(folded) ||
      !expected.has(entry.name) ||
      !entry.isFile()
    ) {
      throw new CatalogHiddenFlowError(
        'output-artifact-tampered',
        'publication',
        'The marker-committed hidden-flow report directory contains an unexpected, aliased, linked, or unsupported entry.',
      )
    }
    seen.add(entry.name)
    seenFolded.add(folded)
  }
  if (
    seen.size !== expected.size ||
    [...expected].some((name) => !seen.has(name))
  ) {
    throw new CatalogHiddenFlowError(
      'output-publication-partial',
      'publication',
      'The marker-committed hidden-flow report set is incomplete.',
    )
  }
}

function sameJson(left: unknown, right: unknown): boolean {
  return stableJson(left) === stableJson(right)
}

async function verifyPublishedSet(
  root: string,
  expectedRecord:
    CatalogHiddenFlowReportVerificationRecord,
  expectedMarker:
    CatalogHiddenFlowArtifactIdentity,
  expectedResponse:
    CatalogHiddenFlowPackagedRunResponse,
  expectedRun: CatalogHiddenFlowVerifiedRun,
): Promise<void> {
  const expectedReferences = references(
    expectedRecord.preparation.bundle.sha256,
  )
  const finalDirectory = confined(
    root,
    expectedReferences.directory,
  )
  await ordinaryDirectory(finalDirectory)
  await reconcileCatalogHiddenFlowPublicationStaging(
    finalDirectory,
    expectedPublicationMembers(
      expectedRecord,
      expectedMarker,
    ),
  )
  assertCatalogHiddenFlowReportSetSemanticContract(
    expectedResponse,
    expectedRecord,
    expectedMarker,
    expectedRun,
  )
  const markerBytes = await verifiedFile(
    confined(root, expectedMarker.reference),
    expectedMarker,
    'output-publication-partial',
  )
  const marker = parseCanonicalObject(
    markerBytes,
    'The hidden-flow report-verification marker',
  )
  if (!sameJson(marker, expectedRecord)) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'The hidden-flow report-verification marker does not match the expected closed record.',
    )
  }
  const jsonBytes = await verifiedFile(
    confined(root, expectedRecord.artifacts.json.reference),
    expectedRecord.artifacts.json,
    'output-publication-partial',
  )
  const markdownBytes = await verifiedFile(
    confined(
      root,
      expectedRecord.artifacts.markdown.reference,
    ),
    expectedRecord.artifacts.markdown,
    'output-publication-partial',
  )
  const run = parseCanonicalObject(
    jsonBytes,
    'The committed hidden-flow verified run',
  ) as unknown as CatalogHiddenFlowVerifiedRun
  assertCatalogHiddenFlowVerifiedRunSemanticContract(run)
  if (
    run.recordType !==
      'flowblind-catalog-hidden-flow-verified-run-v1' ||
    run.capabilityVersion !==
      expectedRecord.capability.capabilityVersion ||
    run.preparation.id !== expectedRecord.preparation.id ||
    run.preparation.associationSha256 !==
      expectedRecord.preparation.associationSha256 ||
    !sameJson(
      run.preparation.artifact,
      expectedRecord.preparation.bundle,
    ) ||
    run.problem.id !== expectedRecord.problem.id ||
    !sameJson(
      run.problem.identity,
      expectedRecord.problem.identity,
    ) ||
    !sameJson(run.software, expectedRecord.software) ||
    !sameJson(
      run.deterministicReplay,
      expectedRecord.deterministicReplay,
    ) ||
    markdownBytes.byteLength === 0
  ) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'The committed hidden-flow artifacts do not preserve the preparation, problem, software, and replay authority chain.',
    )
  }
  assertCatalogHiddenFlowReportSetSemanticContract(
    expectedResponse,
    marker as unknown as CatalogHiddenFlowReportVerificationRecord,
    expectedMarker,
    run,
  )
  await verifyDirectoryEntries(finalDirectory)
}

export async function publishCatalogHiddenFlowReportSet(
  outputRootInput: string,
  executed: ExecutedCatalogHiddenFlow,
  options: CatalogHiddenFlowPublicationOptions = {},
): Promise<PublishedCatalogHiddenFlowReportSet> {
  const root = await ensureOutputRoot(outputRootInput)
  const record = parseVerifiedRun(executed.artifacts.json)
  if (
    !sameJson(
      executed.response.artifacts.json,
      artifactIdentity(executed.artifacts.json),
    ) ||
    !sameJson(
      executed.response.artifacts.markdown,
      artifactIdentity(executed.artifacts.markdown),
    )
  ) {
    throw new CatalogHiddenFlowError(
      'output-artifact-tampered',
      'publication',
      'The in-memory hidden-flow response does not bind its artifact bytes.',
    )
  }
  const outputReferences = references(
    record.preparation.artifact.sha256,
  )
  const json = artifact(
    outputReferences.json,
    executed.artifacts.json.bytes,
    'application/json',
  )
  const markdown = artifact(
    outputReferences.markdown,
    executed.artifacts.markdown.bytes,
    'text/markdown',
  )
  const verificationRecord:
    CatalogHiddenFlowReportVerificationRecord = {
    $schema:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_REPORT_VERIFICATION_SCHEMA_ID,
    schemaVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_SCHEMA_VERSION,
    recordType:
      'flowblind-catalog-hidden-flow-report-verification-v1',
    status: 'verified-report-complete',
    capability: {
      capabilityId:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
      capabilityVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
      methodFamily:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
      packageVersion:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
    },
    preparation: {
      id: record.preparation.id,
      associationSha256:
        record.preparation.associationSha256,
      bundle: record.preparation.artifact,
    },
    problem: {
      id: record.problem.id,
      identity: record.problem.identity,
    },
    software: record.software,
    deterministicReplay:
      record.deterministicReplay,
    artifacts: {
      json: artifactIdentity(json),
      markdown: artifactIdentity(markdown),
    },
    publication: {
      directory: outputReferences.directory,
      commitMarker: 'report-verification.json',
      pointOfNoReturn:
        'exclusive-report-verification-commit-marker',
      policy:
        'deterministic-exclusive-create-or-verify-content-then-commit-marker',
      distributedExactlyOnceClaim: false,
    },
  }
  const verificationBytes = utf8Bytes(
    stableJson(verificationRecord),
  )
  const verification = artifact(
    outputReferences.verification,
    verificationBytes,
    'application/json',
  )
  const verificationIdentity =
    artifactIdentity(verification)
  const response:
    CatalogHiddenFlowPackagedRunResponse = {
    ...executed.response,
    artifacts: {
      json: artifactIdentity(json),
      markdown: artifactIdentity(markdown),
      verification: verificationIdentity,
    },
    publication: {
      state: 'marker-verified',
      promotable: true,
      directory: outputReferences.directory,
      pointOfNoReturn:
        'exclusive-report-verification-commit-marker',
      policy:
        'deterministic-exclusive-create-or-verify-content-then-commit-marker',
      distributedExactlyOnceClaim: false,
    },
  }
  assertCatalogHiddenFlowReportSetSemanticContract(
    response,
    verificationRecord,
    verificationIdentity,
    record,
  )
  const finalDirectory = confined(
    root,
    outputReferences.directory,
  )
  const markerPath = confined(
    root,
    outputReferences.verification,
  )
  if (await fileExists(markerPath)) {
    await verifyPublishedSet(
      root,
      verificationRecord,
      verificationIdentity,
      response,
      record,
    )
    return { response, verificationRecord }
  }

  throwIfCatalogHiddenFlowAborted(options.signal)
  await ordinaryDirectory(finalDirectory, true)
  await reconcileCatalogHiddenFlowPublicationStaging(
    finalDirectory,
    expectedPublicationMembers(
      verificationRecord,
      verificationIdentity,
    ),
  )

  await options.checkpoint?.('before-write-json')
  throwIfCatalogHiddenFlowAborted(options.signal)
  await installCompleteFile(
    confined(finalDirectory, 'verified-run.json'),
    json.bytes,
    'application/json',
  )
  await options.checkpoint?.('before-write-markdown')
  throwIfCatalogHiddenFlowAborted(options.signal)
  await installCompleteFile(
    confined(finalDirectory, 'report.md'),
    markdown.bytes,
    'text/markdown',
  )
  await reconcileCatalogHiddenFlowPublicationStaging(
    finalDirectory,
    expectedPublicationMembers(
      verificationRecord,
      verificationIdentity,
    ),
  )
  await options.checkpoint?.('before-commit-marker')
  throwIfCatalogHiddenFlowAborted(options.signal)
  await installCompleteFile(
    confined(
      finalDirectory,
      'report-verification.json',
    ),
    verification.bytes,
    'application/json',
  )
  await options.checkpoint?.('after-commit-marker')

  await verifyPublishedSet(
    root,
    verificationRecord,
    verificationIdentity,
    response,
    record,
  )
  return { response, verificationRecord }
}

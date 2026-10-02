import { createHash } from 'node:crypto'
import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
} from 'node:fs'
import {
  dirname,
  isAbsolute,
  relative,
  resolve,
  sep,
} from 'node:path'
import { defineConfig } from 'vite'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_LOCK_SCHEMA_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY,
} from './profile.ts'

type UnknownRecord = Record<string, unknown>

interface SourceArtifact {
  readonly id: string
  readonly role: string
  readonly sourceReference: string
  readonly bundledPath: string
  readonly mediaType: string
  readonly bytes: Buffer
}

const capabilityRoot = import.meta.dirname
const repositoryRoot = resolve(
  capabilityRoot,
  '..',
  '..',
  '..',
)
const packageRoot = resolve(capabilityRoot, 'package')
const committedRuntimeRoot = resolve(packageRoot, 'runtime')
const runtimeScratchRoot = resolve(
  repositoryRoot,
  'node_modules',
  '.cache',
  'flowblind-hidden-flow-runtime-builds',
)

export interface CatalogHiddenFlowRuntimeOutputRoots {
  readonly repositoryRoot: string
  readonly committedRuntimeRoot: string
  readonly scratchRoot: string
}

function samePath(left: string, right: string): boolean {
  const normalizedLeft = resolve(left)
  const normalizedRight = resolve(right)
  return process.platform === 'win32'
    ? normalizedLeft.toLowerCase() ===
        normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight
}

function containsPath(
  root: string,
  candidate: string,
  allowRoot: boolean,
): boolean {
  const child = relative(root, candidate)
  return (
    (allowRoot && child.length === 0) ||
    (
      child.length > 0 &&
      child !== '..' &&
      !child.startsWith(`..${sep}`) &&
      !isAbsolute(child)
    )
  )
}

function assertOrdinaryCanonicalDirectory(
  path: string,
  label: string,
): void {
  if (!existsSync(path)) {
    throw new Error(`${label} does not exist.`)
  }
  const metadata = lstatSync(path)
  if (
    metadata.isSymbolicLink() ||
    !metadata.isDirectory() ||
    !samePath(path, realpathSync(path))
  ) {
    throw new Error(
      `${label} must be one ordinary canonical directory.`,
    )
  }
}

export function resolveCatalogHiddenFlowRuntimeOutput(
  override: string | undefined,
  roots: CatalogHiddenFlowRuntimeOutputRoots = {
    repositoryRoot,
    committedRuntimeRoot,
    scratchRoot: runtimeScratchRoot,
  },
): string {
  if (override === undefined) return roots.committedRuntimeRoot
  if (
    override.trim().length === 0 ||
    !isAbsolute(override)
  ) {
    throw new Error(
      'FLOWBLIND_HIDDEN_FLOW_RUNTIME_OUT_DIR must be a nonempty absolute scratch path.',
    )
  }
  const candidate = resolve(override)
  if (
    containsPath(candidate, roots.repositoryRoot, true)
  ) {
    throw new Error(
      'FLOWBLIND_HIDDEN_FLOW_RUNTIME_OUT_DIR may not name the repository root or one of its ancestors.',
    )
  }
  if (samePath(candidate, roots.committedRuntimeRoot)) {
    throw new Error(
      'FLOWBLIND_HIDDEN_FLOW_RUNTIME_OUT_DIR may not name the committed hidden-flow runtime.',
    )
  }
  if (!containsPath(roots.scratchRoot, candidate, false)) {
    throw new Error(
      'FLOWBLIND_HIDDEN_FLOW_RUNTIME_OUT_DIR must stay inside the dedicated hidden-flow build scratch root.',
    )
  }
  const scratchReference = relative(
    roots.scratchRoot,
    candidate,
  )
  const parts = scratchReference.split(sep)
  if (
    parts.length !== 2 ||
    !/^invocation-[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(
      parts[0] ?? '',
    ) ||
    parts[1] !== 'runtime'
  ) {
    throw new Error(
      'FLOWBLIND_HIDDEN_FLOW_RUNTIME_OUT_DIR must be the runtime child of one dedicated invocation directory.',
    )
  }
  assertOrdinaryCanonicalDirectory(
    roots.scratchRoot,
    'The hidden-flow build scratch root',
  )
  assertOrdinaryCanonicalDirectory(
    dirname(candidate),
    'The hidden-flow build invocation directory',
  )
  if (existsSync(candidate)) {
    assertOrdinaryCanonicalDirectory(
      candidate,
      'The hidden-flow runtime scratch output',
    )
  }
  return candidate
}

const runtimeRoot = resolveCatalogHiddenFlowRuntimeOutput(
  process.env.FLOWBLIND_HIDDEN_FLOW_RUNTIME_OUT_DIR,
)

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue)
  if (typeof value === 'object' && value !== null) {
    return Object.fromEntries(
      Object.keys(value as UnknownRecord)
        .sort()
        .map((key) => [
          key,
          stableValue((value as UnknownRecord)[key]),
        ]),
    )
  }
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return value
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  throw new Error(
    'Hidden-flow package records may contain only finite JSON values.',
  )
}

function stableJson(value: unknown): string {
  return `${JSON.stringify(stableValue(value), null, 2)}\n`
}

function sha256(value: Uint8Array): string {
  return createHash('sha256').update(value).digest('hex')
}

function normalizedSource(path: string): Buffer {
  return Buffer.from(
    readFileSync(path, 'utf8').replace(/\r\n?/gu, '\n'),
    'utf8',
  )
}

function sourceArtifact(
  id: string,
  role: string,
  sourceReference: string,
  bundledPath: string,
  mediaType: string,
): SourceArtifact {
  const path = resolve(repositoryRoot, sourceReference)
  if (!existsSync(path)) {
    throw new Error(
      `Missing hidden-flow package artifact: ${sourceReference}`,
    )
  }
  return {
    id,
    role,
    sourceReference,
    bundledPath,
    mediaType,
    bytes: normalizedSource(path),
  }
}

const launchers = [
  sourceArtifact(
    'prepare-study-facade',
    'public-executable-facade',
    'tools/catalogCapabilities/hiddenFlow/launchers/flowblind-hidden-flow-prepare.mjs',
    'flowblind-hidden-flow-prepare.mjs',
    'text/javascript',
  ),
  sourceArtifact(
    'run-and-verify-study-facade',
    'public-executable-facade',
    'tools/catalogCapabilities/hiddenFlow/launchers/flowblind-hidden-flow-run.mjs',
    'flowblind-hidden-flow-run.mjs',
    'text/javascript',
  ),
  sourceArtifact(
    'declaration-preview-facade',
    'declaration-preview-facade',
    'tools/catalogCapabilities/hiddenFlow/launchers/flowblind-hidden-flow-declaration-preview.mjs',
    'flowblind-hidden-flow-declaration-preview.mjs',
    'text/javascript',
  ),
] as const

const capabilitySchemas = [
  'flowblind-catalog-hidden-flow-input-v1.schema.json',
  'flowblind-catalog-hidden-flow-action-response-v1.schema.json',
  'flowblind-catalog-hidden-flow-preparation-bundle-v1.schema.json',
  'flowblind-catalog-hidden-flow-verified-run-v1.schema.json',
  'flowblind-catalog-hidden-flow-evidence-v1.schema.json',
  'flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json',
  'flowblind-catalog-hidden-flow-report-verification-v1.schema.json',
  'flowblind-catalog-hidden-flow-package-evidence-v1.schema.json',
  'flowblind-catalog-hidden-flow-review-attestation-v1.schema.json',
  'flowblind-catalog-hidden-flow-review-policy-v1.schema.json',
  'flowblind-catalog-hidden-flow-declaration-v1.schema.json',
  'flowblind-catalog-hidden-flow-package-lock-v1.schema.json',
] as const

const sourceArtifacts: readonly SourceArtifact[] = [
  ...capabilitySchemas.map((filename) =>
    sourceArtifact(
      filename.replace(
        /\.schema\.json$/u,
        '',
      ),
      'capability-schema-v1',
      `schemas/${filename}`,
      `data/schemas/${filename}`,
      'application/schema+json',
    ),
  ),
  sourceArtifact(
    'hidden-flow-problem-schema',
    'generic-problem-contract-schema',
    'schemas/hidden-flow-problem.schema.json',
    'data/schemas/hidden-flow-problem.schema.json',
    'application/schema+json',
  ),
  sourceArtifact(
    'hidden-flow-model-source',
    'reviewed-generic-model-source',
    'src/domain/hiddenFlowModel.ts',
    'data/reviewed-source/src/domain/hiddenFlowModel.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'hidden-flow-problem-parser-source',
    'reviewed-generic-parser-source',
    'src/domain/hiddenFlowValidation.ts',
    'data/reviewed-source/src/domain/hiddenFlowValidation.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'hidden-flow-basis-source',
    'reviewed-generic-basis-source',
    'src/domain/hiddenFlowBasis.ts',
    'data/reviewed-source/src/domain/hiddenFlowBasis.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'hidden-flow-operator-source',
    'reviewed-generic-operator-source',
    'src/domain/hiddenFlowOperator.ts',
    'data/reviewed-source/src/domain/hiddenFlowOperator.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'hidden-flow-independent-verifier-source',
    'reviewed-independent-verifier-source',
    'src/domain/hiddenFlowVerification.ts',
    'data/reviewed-source/src/domain/hiddenFlowVerification.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'hidden-flow-neutral-report-source',
    'reviewed-neutral-report-source',
    'src/application/hiddenFlowEvidenceReport.ts',
    'data/reviewed-source/src/application/hiddenFlowEvidenceReport.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'canonical-evidence-json-source',
    'reviewed-runtime-dependency-source',
    'src/application/evidenceReport.ts',
    'data/reviewed-source/src/application/evidenceReport.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'flowblind-display-text-source',
    'reviewed-runtime-dependency-source',
    'tools/discovery/flowblindDisplayText.ts',
    'data/reviewed-source/tools/discovery/flowblindDisplayText.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'hidden-flow-solver-result-parser-source',
    'reviewed-runtime-dependency-source',
    'src/domain/hiddenFlowSolverValidation.ts',
    'data/reviewed-source/src/domain/hiddenFlowSolverValidation.ts',
    'text/typescript',
  ),
  sourceArtifact(
    'flowblind-version-source',
    'reviewed-runtime-dependency-source',
    'src/version.ts',
    'data/reviewed-source/src/version.ts',
    'text/typescript',
  ),
  ...[
    'profile.ts',
    'adapterContract.ts',
    'authority.ts',
    'preparation.ts',
    'engine.ts',
    'execution.ts',
    'capability.ts',
    'pinnedSolver.ts',
    'packageIo.ts',
    'packagePublication.ts',
    'runtime.ts',
    'index.ts',
    'packageBuild.config.ts',
  ].map((filename) =>
    sourceArtifact(
      `capability-${filename
        .replace(/\.ts$/u, '')
        .replace(/([a-z0-9])([A-Z])/gu, '$1-$2')
        .toLowerCase()
        .replace(/[^a-z0-9]+/gu, '-')}-source`,
      'capability-runtime-source',
      `tools/catalogCapabilities/hiddenFlow/${filename}`,
      `data/reviewed-source/tools/catalogCapabilities/hiddenFlow/${filename}`,
      'text/typescript',
    ),
  ),
  sourceArtifact(
    'python-requirements-lock',
    'hash-pinned-python-requirements',
    'docker/hidden-flow-solver-requirements.txt',
    'data/python/requirements.lock',
    'text/plain',
  ),
  sourceArtifact(
    'python-solver-init',
    'pinned-python-solver-source',
    'tools/hidden_flow_solver/__init__.py',
    'data/python/tools/hidden_flow_solver/__init__.py',
    'text/x-python',
  ),
  sourceArtifact(
    'python-solver-main',
    'pinned-python-solver-source',
    'tools/hidden_flow_solver/__main__.py',
    'data/python/tools/hidden_flow_solver/__main__.py',
    'text/x-python',
  ),
  sourceArtifact(
    'python-solver-cli',
    'pinned-python-solver-source',
    'tools/hidden_flow_solver/cli.py',
    'data/python/tools/hidden_flow_solver/cli.py',
    'text/x-python',
  ),
  sourceArtifact(
    'python-solver-core',
    'pinned-python-solver-source',
    'tools/hidden_flow_solver/solver.py',
    'data/python/tools/hidden_flow_solver/solver.py',
    'text/x-python',
  ),
  sourceArtifact(
    'container-definition',
    'pinned-container-definition',
    'tools/catalogCapabilities/hiddenFlow/package/Dockerfile',
    'data/package/Dockerfile',
    'text/x-dockerfile',
  ),
  sourceArtifact(
    'capability-contract',
    'public-capability-contract',
    'docs/catalog-hidden-flow-capability-v1.md',
    'data/package/catalog-hidden-flow-capability-v1.md',
    'text/markdown',
  ),
  sourceArtifact(
    'generic-exact-null-test-fixture',
    'test-only-generic-problem-fixture',
    'fixtures/hidden-flow/exact-null-component.json',
    'data/examples/exact-null-component.json',
    'application/json',
  ),
  sourceArtifact(
    'generic-directional-speed-test-fixture',
    'test-only-generic-problem-fixture',
    'fixtures/hidden-flow/tolerance-speed.json',
    'data/examples/tolerance-speed.json',
    'application/json',
  ),
  sourceArtifact(
    'package-verifier-template',
    'package-verifier-source-template',
    'tools/catalogCapabilities/hiddenFlow/package-verifier-template.mjs',
    'data/reviewed-source/tools/catalogCapabilities/hiddenFlow/package-verifier-template.mjs',
    'text/javascript',
  ),
]

function normalizedReference(value: string): string {
  return value.replaceAll('\\', '/')
}

function assertUnique(
  values: readonly string[],
  label: string,
): void {
  if (
    new Set(values).size !== values.length ||
    new Set(values.map((value) => value.toLowerCase()))
      .size !== values.length
  ) {
    throw new Error(
      `Hidden-flow package ${label} contains duplicate or case-aliased values.`,
    )
  }
}

assertUnique(
  sourceArtifacts.map((item) => item.id),
  'artifact IDs',
)
assertUnique(
  sourceArtifacts.map((item) =>
    normalizedReference(item.sourceReference),
  ),
  'source references',
)
assertUnique(
  sourceArtifacts.map((item) =>
    normalizedReference(item.bundledPath),
  ),
  'bundled paths',
)
assertUnique(
  launchers.map((item) => item.id),
  'facade IDs',
)
assertUnique(
  launchers.map((item) =>
    normalizedReference(item.bundledPath),
  ),
  'facade paths',
)

function assertRuntimeSourceClosure(
  modules: Record<string, unknown>,
): void {
  const reviewed = new Set(
    sourceArtifacts.map((item) =>
      normalizedReference(item.sourceReference),
    ),
  )
  const runtimeSources = Object.keys(modules).flatMap(
    (moduleId) => {
      const path = moduleId.split('?')[0] ?? moduleId
      if (!isAbsolute(path)) return []
      const reference = normalizedReference(
        relative(repositoryRoot, path),
      )
      if (
        reference === '..' ||
        reference.startsWith('../') ||
        isAbsolute(reference)
      ) {
        throw new Error(
          `Hidden-flow runtime module escapes the repository: ${moduleId}`,
        )
      }
      return [reference]
    },
  )
  assertUnique(runtimeSources, 'runtime module paths')
  const missing = runtimeSources.filter(
    (reference) => !reviewed.has(reference),
  )
  if (missing.length > 0) {
    throw new Error(
      `Hidden-flow runtime source closure is missing reviewed copies: ${missing.join(', ')}`,
    )
  }
}

function artifactIdentity(artifact: SourceArtifact) {
  return {
    id: artifact.id,
    role: artifact.role,
    sourceReference: artifact.sourceReference,
    bundledPath: artifact.bundledPath,
    byteLength: artifact.bytes.byteLength,
    sha256: sha256(artifact.bytes),
    mediaType: artifact.mediaType,
  }
}

function generatedArtifact(
  id: string,
  role: string,
  sourceReference: string,
  bundledPath: string,
  mediaType: string,
  value: unknown,
): SourceArtifact {
  return {
    id,
    role,
    sourceReference,
    bundledPath,
    mediaType,
    bytes: Buffer.from(stableJson(value), 'utf8'),
  }
}

function verifierSource(lockIdentity: {
  readonly byteLength: number
  readonly sha256: string
}): string {
  const template = normalizedSource(
    resolve(
      capabilityRoot,
      'package-verifier-template.mjs',
    ),
  ).toString('utf8')
  return template
    .replace(
      '__LOCK_BYTE_LENGTH__',
      String(lockIdentity.byteLength),
    )
    .replace('__LOCK_SHA256__', lockIdentity.sha256)
}

export default defineConfig({
  publicDir: false,
  plugins: [
    {
      name: 'emit-catalog-hidden-flow-capability-package',
      generateBundle(_options, bundle) {
        const runtime =
          bundle[
            'generated/flowblind-catalog-hidden-flow-runtime-v1.mjs'
          ]
        if (
          runtime === undefined ||
          runtime.type !== 'chunk'
        ) {
          throw new Error(
            'Hidden-flow capability build did not emit its runtime.',
          )
        }
        assertRuntimeSourceClosure(runtime.modules)
        const generated = [
          generatedArtifact(
            'generic-review-policy',
            'generic-reviewed-problem-policy',
            'generated from versioned hidden-flow review constants',
            'data/flowblind-catalog-hidden-flow-review-policy-v1.json',
            'application/json',
            FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY,
          ),
          generatedArtifact(
            'capability-declaration',
            'two-action-capability-declaration',
            'generated from versioned hidden-flow declaration constants',
            'data/flowblind-catalog-hidden-flow-declaration-v1.json',
            'application/json',
            FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION,
          ),
        ]
        const artifacts = [
          ...sourceArtifacts,
          ...generated,
        ]
        const runtimeBytes = Buffer.from(
          runtime.code,
          'utf8',
        )
        const lock = {
          $schema:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_LOCK_SCHEMA_ID,
          schemaVersion: 1,
          id:
            'flowblind-catalog-hidden-flow-package-lock-v1',
          packageVersion:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
          actions:
            FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS,
          runtimeNetworkRequired: false,
          publicRuntime: {
            bundledPath:
              'generated/flowblind-catalog-hidden-flow-runtime-v1.mjs',
            byteLength: runtimeBytes.byteLength,
            sha256: sha256(runtimeBytes),
          },
          facades: launchers.map(artifactIdentity),
          artifacts: artifacts.map(artifactIdentity),
        }
        const lockBytes = Buffer.from(
          stableJson(lock),
          'utf8',
        )

        for (const artifact of artifacts) {
          this.emitFile({
            type: 'asset',
            fileName: `generated/${artifact.bundledPath}`,
            source: artifact.bytes,
          })
        }
        for (const launcher of launchers) {
          this.emitFile({
            type: 'asset',
            fileName: launcher.bundledPath,
            source: launcher.bytes,
          })
        }
        this.emitFile({
          type: 'asset',
          fileName:
            'generated/data/flowblind-catalog-hidden-flow-package-lock-v1.json',
          source: lockBytes,
        })
        this.emitFile({
          type: 'asset',
          fileName:
            'flowblind-hidden-flow-capability-verification-v1.mjs',
          source: verifierSource({
            byteLength: lockBytes.byteLength,
            sha256: sha256(lockBytes),
          }),
        })
      },
    },
  ],
  build: {
    ssr: resolve(capabilityRoot, 'runtime.ts'),
    target: 'node22',
    outDir: runtimeRoot,
    emptyOutDir: true,
    minify: false,
    rollupOptions: {
      output: {
        entryFileNames:
          'generated/flowblind-catalog-hidden-flow-runtime-v1.mjs',
        codeSplitting: false,
      },
    },
  },
})

import { randomUUID } from 'node:crypto'
import { constants } from 'node:fs'
import {
  link,
  lstat,
  open,
  opendir,
  realpath,
  unlink,
} from 'node:fs/promises'
import {
  isAbsolute,
  relative,
  resolve,
} from 'node:path'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES,
  CatalogHiddenFlowError,
  throwIfCatalogHiddenFlowAborted,
} from './profile.ts'
import type {
  CatalogHiddenFlowArtifact,
} from './profile.ts'

interface SelectedFile {
  readonly path: string
  readonly bytes: Buffer
}

const MAXIMUM_ATTACHMENT_TREE_ENTRIES = 64
const MAXIMUM_ATTACHMENT_TREE_DEPTH = 8

function confinedPath(
  root: string,
  reference: string,
): string {
  const path = resolve(root, reference)
  const child = relative(root, path)
  if (
    child.length === 0 ||
    child === '..' ||
    child.startsWith(
      `..${process.platform === 'win32' ? '\\' : '/'}`,
    ) ||
    isAbsolute(child)
  ) {
    throw new CatalogHiddenFlowError(
      'attachment-path-unsafe',
      'attachment',
      'The selected attachment escapes the host-provided input root.',
    )
  }
  return path
}

async function selectedReferences(
  root: string,
  current = root,
  depth = 0,
  state = { entries: 0 },
  signal?: AbortSignal,
): Promise<string[]> {
  throwIfCatalogHiddenFlowAborted(signal)
  if (depth > MAXIMUM_ATTACHMENT_TREE_DEPTH) {
    throw new CatalogHiddenFlowError(
      'attachment-set-invalid',
      'attachment',
      'The selected attachment tree exceeds the reviewed directory-depth limit.',
    )
  }
  const references: string[] = []
  try {
    const directory = await opendir(current)
    for await (const entry of directory) {
      throwIfCatalogHiddenFlowAborted(signal)
      state.entries += 1
      if (
        state.entries >
        MAXIMUM_ATTACHMENT_TREE_ENTRIES
      ) {
        throw new CatalogHiddenFlowError(
          'attachment-set-invalid',
          'attachment',
          'The selected attachment tree exceeds the reviewed entry-count limit.',
        )
      }
      const path = resolve(current, entry.name)
      const reference = relative(root, path)
      if (entry.isSymbolicLink()) {
        throw new CatalogHiddenFlowError(
          'attachment-path-unsafe',
          'attachment',
          'Selected attachment roots may not contain symbolic links.',
        )
      }
      if (entry.isDirectory()) {
        references.push(
          ...await selectedReferences(
            root,
            path,
            depth + 1,
            state,
            signal,
          ),
        )
      } else if (entry.isFile()) {
        references.push(reference)
      } else {
        throw new CatalogHiddenFlowError(
          'attachment-path-unsafe',
          'attachment',
          'Selected attachments must be ordinary files.',
        )
      }
      if (references.length > 1) {
        throw new CatalogHiddenFlowError(
          'attachment-set-invalid',
          'attachment',
          'The hidden-flow action requires exactly one selected JSON attachment.',
        )
      }
    }
  } catch (error) {
    if (error instanceof CatalogHiddenFlowError) throw error
    throw new CatalogHiddenFlowError(
      'attachment-set-invalid',
      'attachment',
      'The host-selected attachment tree is missing or unreadable.',
      { cause: error },
    )
  }
  return references
}

async function stableRead(
  root: string,
  reference: string,
  signal?: AbortSignal,
): Promise<SelectedFile> {
  throwIfCatalogHiddenFlowAborted(signal)
  const path = confinedPath(root, reference)
  let metadata
  try {
    metadata = await lstat(path)
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'attachment-set-invalid',
      'attachment',
      'The selected attachment is missing or unreadable.',
      { cause: error },
    )
  }
  if (
    metadata.isSymbolicLink() ||
    !metadata.isFile() ||
    metadata.nlink !== 1 ||
    metadata.size <= 0 ||
    metadata.size >
      FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES
  ) {
    throw new CatalogHiddenFlowError(
      'attachment-path-unsafe',
      'attachment',
      'The selected attachment must be one bounded, single-link ordinary file.',
    )
  }
  let canonicalRoot
  let canonicalPath
  try {
    canonicalRoot = await realpath(root)
    canonicalPath = await realpath(path)
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'attachment-path-unsafe',
      'attachment',
      'The selected attachment could not be resolved safely.',
      { cause: error },
    )
  }
  if (
    relative(canonicalRoot, canonicalPath).startsWith('..')
  ) {
    throw new CatalogHiddenFlowError(
      'attachment-path-unsafe',
      'attachment',
      'The selected attachment resolves outside the host-provided input root.',
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
      'attachment-path-unsafe',
      'attachment',
      'The selected attachment could not be opened as an ordinary no-follow file.',
      { cause: error },
    )
  }
  try {
    const before = await handle.stat({ bigint: true })
    if (
      !before.isFile() ||
      before.nlink !== 1n ||
      before.size <= 0n ||
      before.size >
        BigInt(
          FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES,
        )
    ) {
      throw new CatalogHiddenFlowError(
        'attachment-path-unsafe',
        'attachment',
        'The opened attachment is not one bounded, single-link ordinary file.',
      )
    }
    const chunks: Buffer[] = []
    let total = 0
    while (true) {
      throwIfCatalogHiddenFlowAborted(signal)
      const chunk = Buffer.allocUnsafe(64 * 1024)
      const { bytesRead } = await handle.read(
        chunk,
        0,
        chunk.byteLength,
        null,
      )
      if (bytesRead === 0) break
      total += bytesRead
      if (
        total >
        FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES
      ) {
        throw new CatalogHiddenFlowError(
          'attachment-set-invalid',
          'attachment',
          'The selected attachment exceeds the bounded hidden-flow input limit.',
        )
      }
      chunks.push(chunk.subarray(0, bytesRead))
    }
    const after = await handle.stat({ bigint: true })
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.size !== after.size ||
      before.mtimeNs !== after.mtimeNs ||
      total !== Number(before.size)
    ) {
      throw new CatalogHiddenFlowError(
        'attachment-changed-during-read',
        'attachment',
        'The selected attachment changed while it was being read.',
      )
    }
    return {
      path,
      bytes: Buffer.concat(chunks, total),
    }
  } catch (error) {
    if (error instanceof CatalogHiddenFlowError) throw error
    throw new CatalogHiddenFlowError(
      'attachment-changed-during-read',
      'attachment',
      'The selected attachment could not be read with stable identity.',
      { cause: error },
    )
  } finally {
    await handle.close()
  }
}

export async function loadSingleCatalogHiddenFlowAttachment(
  root: string,
  signal?: AbortSignal,
): Promise<SelectedFile> {
  let metadata
  try {
    metadata = await lstat(root)
  } catch (error) {
    throw new CatalogHiddenFlowError(
      'attachment-set-invalid',
      'attachment',
      'The host-provided input root is missing or unreadable.',
      { cause: error },
    )
  }
  if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
    throw new CatalogHiddenFlowError(
      'attachment-path-unsafe',
      'attachment',
      'The host-provided input root must be an ordinary directory.',
    )
  }
  const references = await selectedReferences(
    root,
    root,
    0,
    { entries: 0 },
    signal,
  )
  if (
    references.length !== 1 ||
    !references[0]!.toLowerCase().endsWith('.json')
  ) {
    throw new CatalogHiddenFlowError(
      'attachment-set-invalid',
      'attachment',
      'The hidden-flow action requires exactly one selected JSON attachment.',
    )
  }
  return stableRead(root, references[0]!, signal)
}

async function verifyExisting(
  path: string,
  expected: Uint8Array,
): Promise<void> {
  const metadata = await lstat(path)
  if (
    metadata.isSymbolicLink() ||
    !metadata.isFile() ||
    metadata.nlink !== 1 ||
    metadata.size !== expected.byteLength
  ) {
    throw new CatalogHiddenFlowError(
      'output-publication-conflict',
      'publication',
      'A content-addressed hidden-flow output already exists with different bytes.',
    )
  }
  const handle = await open(
    path,
    constants.O_RDONLY |
      (typeof constants.O_NOFOLLOW === 'number'
        ? constants.O_NOFOLLOW
        : 0),
  )
  try {
    const before = await handle.stat({ bigint: true })
    const bytes = Buffer.allocUnsafe(expected.byteLength)
    let offset = 0
    while (offset < bytes.byteLength) {
      const { bytesRead } = await handle.read(
        bytes,
        offset,
        bytes.byteLength - offset,
        offset,
      )
      if (bytesRead === 0) break
      offset += bytesRead
    }
    const after = await handle.stat({ bigint: true })
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.size !== after.size ||
      before.mtimeNs !== after.mtimeNs ||
      offset !== expected.byteLength ||
      !bytes.equals(Buffer.from(expected))
    ) {
      throw new CatalogHiddenFlowError(
        'output-publication-conflict',
        'publication',
        'A content-addressed hidden-flow output already exists with different bytes.',
      )
    }
  } finally {
    await handle.close()
  }
}

export async function publishCatalogHiddenFlowArtifact(
  outputRoot: string,
  artifact: CatalogHiddenFlowArtifact,
  signal?: AbortSignal,
): Promise<void> {
  const rootMetadata = await lstat(outputRoot)
  if (
    rootMetadata.isSymbolicLink() ||
    !rootMetadata.isDirectory()
  ) {
    throw new CatalogHiddenFlowError(
      'output-publication-conflict',
      'publication',
      'The host-provided output root must be an ordinary directory.',
    )
  }
  const finalPath = confinedPath(
    outputRoot,
    artifact.reference,
  )
  const stagePath = confinedPath(
    outputRoot,
    `.flowblind-stage-${process.pid}-${randomUUID()}`,
  )
  let staged = false
  try {
    throwIfCatalogHiddenFlowAborted(signal)
    const handle = await open(stagePath, 'wx', 0o600)
    staged = true
    try {
      await handle.writeFile(artifact.bytes)
      await handle.sync()
    } finally {
      await handle.close()
    }
    throwIfCatalogHiddenFlowAborted(signal)
    try {
      await link(stagePath, finalPath)
    } catch (error) {
      if (
        typeof error === 'object' &&
        error !== null &&
        'code' in error &&
        error.code === 'EEXIST'
      ) {
        await verifyExisting(finalPath, artifact.bytes)
      } else {
        throw error
      }
    }
    await unlink(stagePath)
    staged = false
    await verifyExisting(finalPath, artifact.bytes)
  } finally {
    if (staged) {
      await unlink(stagePath).catch((error: unknown) => {
        if (
          typeof error !== 'object' ||
          error === null ||
          !('code' in error) ||
          error.code !== 'ENOENT'
        ) {
          throw error
        }
      })
    }
  }
}

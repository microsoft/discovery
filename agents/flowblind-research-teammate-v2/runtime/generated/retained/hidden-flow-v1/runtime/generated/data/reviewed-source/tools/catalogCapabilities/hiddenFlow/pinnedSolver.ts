import { execFile } from 'node:child_process'
import { constants } from 'node:fs'
import {
  mkdtemp,
  open,
  realpath,
  rm,
  writeFile,
} from 'node:fs/promises'
import { isAbsolute, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { promisify } from 'node:util'
import {
  HIDDEN_FLOW_LIMITS,
} from '../../../src/domain/hiddenFlowModel.ts'
import type {
  HiddenFlowSolverResult,
  HiddenFlowSupportRequest,
} from '../../../src/domain/hiddenFlowModel.ts'
import {
  parseHiddenFlowSolverResult,
} from '../../../src/domain/hiddenFlowSolverValidation.ts'
import type {
  HiddenFlowSolverPort,
} from '../../../src/ports/HiddenFlowSolverPort.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
  CatalogHiddenFlowError,
  stableJson,
  throwIfCatalogHiddenFlowAborted,
} from './profile.ts'

const executeFile = promisify(execFile)

export interface CatalogHiddenFlowPinnedRuntimeContext {
  readonly pythonExecutable: string
  readonly pythonModuleRoot: string
}

function aggregateBytes(
  current: number,
  byteLength: number,
  limit: number,
  resource: string,
): number {
  const next = current + byteLength
  if (
    !Number.isSafeInteger(byteLength) ||
    byteLength < 0 ||
    !Number.isSafeInteger(next) ||
    next > limit
  ) {
    throw new CatalogHiddenFlowError(
      'problem-not-executable',
      'verification',
      `The pinned hidden-flow solver ${resource} exceeds ${limit} bytes.`,
    )
  }
  return next
}

async function readResult(
  outputPath: string,
  request: HiddenFlowSupportRequest,
  maximumBytes =
    HIDDEN_FLOW_LIMITS.maximumSolverResultBytes,
  signal?: AbortSignal,
): Promise<{
  readonly result: HiddenFlowSolverResult
  readonly byteLength: number
}> {
  const handle = await open(
    outputPath,
    constants.O_RDONLY |
      (typeof constants.O_NOFOLLOW === 'number'
        ? constants.O_NOFOLLOW
        : 0),
  )
  try {
    const before = await handle.stat({ bigint: true })
    if (
      !before.isFile() ||
      before.nlink !== 1n ||
      before.size <= 0n ||
      before.size > BigInt(maximumBytes) ||
      before.size > BigInt(Number.MAX_SAFE_INTEGER)
    ) {
      throw new CatalogHiddenFlowError(
        'problem-not-executable',
        'verification',
        'The opened hidden-flow solver result is invalid, unsafe, or oversized.',
      )
    }
    throwIfCatalogHiddenFlowAborted(signal)
    const expectedBytes = Number(before.size)
    const bytes = Buffer.allocUnsafe(expectedBytes)
    let offset = 0
    while (offset < expectedBytes) {
      throwIfCatalogHiddenFlowAborted(signal)
      const { bytesRead } = await handle.read(
        bytes,
        offset,
        expectedBytes - offset,
        offset,
      )
      if (bytesRead === 0) break
      offset += bytesRead
    }
    const after = await handle.stat({ bigint: true })
    if (
      before.dev !== after.dev ||
      before.ino !== after.ino ||
      before.nlink !== after.nlink ||
      before.size !== after.size ||
      before.mtimeNs !== after.mtimeNs ||
      offset !== expectedBytes
    ) {
      throw new CatalogHiddenFlowError(
        'problem-not-executable',
        'verification',
        'The pinned hidden-flow solver result changed while it was being read.',
      )
    }
    const text = new TextDecoder('utf-8', {
      fatal: true,
    }).decode(bytes)
    return {
      result: parseHiddenFlowSolverResult(
        JSON.parse(text) as unknown,
        request,
      ),
      byteLength: expectedBytes,
    }
  } finally {
    await handle.close()
  }
}

export class PinnedPythonProcessHiddenFlowSolverAdapter
  implements HiddenFlowSolverPort
{
  private readonly executable: string
  private readonly moduleRoot: string
  private readonly signal?: AbortSignal

  constructor(
    context: CatalogHiddenFlowPinnedRuntimeContext,
    signal?: AbortSignal,
  ) {
    if (
      !isAbsolute(context.pythonExecutable) ||
      !isAbsolute(context.pythonModuleRoot)
    ) {
      throw new CatalogHiddenFlowError(
        'package-attestation-failed',
        'package-attestation',
        'The pinned hidden-flow runtime must provide absolute executable and module roots.',
      )
    }
    this.executable = context.pythonExecutable
    this.moduleRoot = context.pythonModuleRoot
    this.signal = signal
  }

  private async environment(): Promise<NodeJS.ProcessEnv> {
    const moduleRoot = await realpath(this.moduleRoot)
    return {
      PATH: '/usr/local/bin:/usr/bin:/bin',
      HOME: '/tmp',
      TMPDIR: '/tmp',
      LANG: 'C.UTF-8',
      LC_ALL: 'C.UTF-8',
      PYTHONPATH: moduleRoot,
      PYTHONDONTWRITEBYTECODE: '1',
      PYTHONUNBUFFERED: '1',
      PYTHONHASHSEED: '0',
      OMP_NUM_THREADS: '1',
      OPENBLAS_NUM_THREADS: '1',
      OPENBLAS_CORETYPE: 'NEHALEM',
      MKL_NUM_THREADS: '1',
      NUMEXPR_NUM_THREADS: '1',
      VECLIB_MAXIMUM_THREADS: '1',
      BLIS_NUM_THREADS: '1',
      FLOWBLIND_SOLVER_IMAGE:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME
          .pythonImage,
    }
  }

  private async execute(
    arguments_: readonly string[],
  ): Promise<void> {
    throwIfCatalogHiddenFlowAborted(this.signal)
    try {
      const moduleRoot = await realpath(this.moduleRoot)
      await executeFile(this.executable, [
        '-I',
        '-c',
        "import runpy,sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('tools.hidden_flow_solver', run_name='__main__')",
        moduleRoot,
        ...arguments_,
      ], {
        cwd: moduleRoot,
        encoding: 'utf8',
        maxBuffer:
          FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME
            .confinement.maximumStdoutStderrBytes,
        timeout:
          FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME
            .confinement.childProcessTimeoutMilliseconds,
        windowsHide: true,
        env: await this.environment(),
        signal: this.signal,
      })
    } catch (error) {
      if (
        this.signal?.aborted === true ||
        (
          error instanceof Error &&
          error.name === 'AbortError'
        )
      ) {
        throw new CatalogHiddenFlowError(
          'operation-cancelled',
          'cancellation',
          'The pinned hidden-flow solver was cancelled before returning verified evidence.',
          { cause: error },
        )
      }
      throw error
    }
    throwIfCatalogHiddenFlowAborted(this.signal)
  }

  async solve(
    request: HiddenFlowSupportRequest,
  ): Promise<HiddenFlowSolverResult> {
    throwIfCatalogHiddenFlowAborted(this.signal)
    const directory = await mkdtemp(
      resolve(tmpdir(), 'flowblind-hidden-flow-'),
    )
    const inputPath = resolve(directory, 'request.json')
    const outputPath = resolve(directory, 'result.json')
    try {
      const content = stableJson(request)
      if (
        Buffer.byteLength(content) >
        HIDDEN_FLOW_LIMITS.maximumDocumentBytes
      ) {
        throw new CatalogHiddenFlowError(
          'problem-not-executable',
          'verification',
          'The pinned hidden-flow solver request exceeds its bounded document limit.',
        )
      }
      await writeFile(inputPath, content, {
        encoding: 'utf8',
        flag: 'wx',
      })
      await this.execute([
        '--input',
        inputPath,
        '--output',
        outputPath,
      ])
      return (
        await readResult(
          outputPath,
          request,
          undefined,
          this.signal,
        )
      ).result
    } finally {
      await rm(directory, {
        recursive: true,
        force: true,
        maxRetries: 10,
        retryDelay: 100,
      })
    }
  }

  async solveMany(
    requests: readonly HiddenFlowSupportRequest[],
  ): Promise<readonly HiddenFlowSolverResult[]> {
    throwIfCatalogHiddenFlowAborted(this.signal)
    if (requests.length === 0) return []
    if (requests.length === 1) {
      return [await this.solve(requests[0]!)]
    }
    if (
      requests.length >
      HIDDEN_FLOW_LIMITS.maximumSolverBatchRequests
    ) {
      throw new CatalogHiddenFlowError(
        'problem-not-executable',
        'verification',
        'The pinned hidden-flow solver batch exceeds its reviewed request-count limit.',
      )
    }
    const contents: string[] = []
    let aggregateInputBytes = 0
    for (const request of requests) {
      const content = stableJson(request)
      const byteLength = Buffer.byteLength(content)
      if (
        byteLength >
        HIDDEN_FLOW_LIMITS.maximumDocumentBytes
      ) {
        throw new CatalogHiddenFlowError(
          'problem-not-executable',
          'verification',
          'A pinned hidden-flow solver request exceeds its bounded document limit.',
        )
      }
      aggregateInputBytes = aggregateBytes(
        aggregateInputBytes,
        byteLength,
        HIDDEN_FLOW_LIMITS.maximumSolverBatchInputBytes,
        'batch input',
      )
      contents.push(content)
    }
    const directory = await mkdtemp(
      resolve(
        tmpdir(),
        'flowblind-hidden-flow-batch-',
      ),
    )
    const requestPath = (index: number) =>
      resolve(
        directory,
        `request-${String(index).padStart(3, '0')}.json`,
      )
    const resultPath = (index: number) =>
      resolve(
        directory,
        `result-${String(index).padStart(3, '0')}.json`,
      )
    try {
      await Promise.all(
        contents.map((content, index) =>
          writeFile(requestPath(index), content, {
            encoding: 'utf8',
            flag: 'wx',
          }),
        ),
      )
      await this.execute([
        '--batch-directory',
        directory,
        '--batch-count',
        String(requests.length),
      ])
      const results: HiddenFlowSolverResult[] = []
      let aggregateResultBytes = 0
      for (
        let index = 0;
        index < requests.length;
        index += 1
      ) {
        const remaining =
          HIDDEN_FLOW_LIMITS.maximumSolverBatchResultBytes -
          aggregateResultBytes
        const read = await readResult(
          resultPath(index),
          requests[index]!,
          Math.min(
            HIDDEN_FLOW_LIMITS.maximumSolverResultBytes,
            remaining,
          ),
          this.signal,
        )
        aggregateResultBytes = aggregateBytes(
          aggregateResultBytes,
          read.byteLength,
          HIDDEN_FLOW_LIMITS.maximumSolverBatchResultBytes,
          'batch output',
        )
        results.push(read.result)
      }
      return results
    } finally {
      await rm(directory, {
        recursive: true,
        force: true,
        maxRetries: 10,
        retryDelay: 100,
      })
    }
  }
}

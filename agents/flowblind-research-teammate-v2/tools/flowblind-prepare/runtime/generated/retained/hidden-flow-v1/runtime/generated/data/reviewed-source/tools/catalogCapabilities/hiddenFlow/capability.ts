import {
  executeCatalogHiddenFlowBundle,
} from './execution.ts'
import type {
  CatalogHiddenFlowRunOptions,
  CatalogHiddenFlowRunResponse,
  CatalogHiddenFlowUnavailableResponse,
  ExecutedCatalogHiddenFlow,
} from './execution.ts'
import {
  prepareCatalogHiddenFlowBundle,
  validateCatalogHiddenFlowBundle,
} from './preparation.ts'
import type {
  CatalogHiddenFlowPreparedResponse,
  PreparedCatalogHiddenFlow,
} from './preparation.ts'
import type {
  CatalogHiddenFlowReviewAuthority,
} from './authority.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
  CatalogHiddenFlowError,
  catalogHiddenFlowRefusal,
  validateCatalogHiddenFlowHumanContext,
} from './profile.ts'
import type {
  CatalogHiddenFlowRefusal,
} from './profile.ts'

export interface CatalogHiddenFlowPrepareContext {
  readonly selectedProblemBytes: Uint8Array
}

export interface CatalogHiddenFlowRunContext {
  readonly preparationBundleBytes: Uint8Array
}

export type CatalogHiddenFlowPrepareCall =
  | PreparedCatalogHiddenFlow
  | {
      readonly response: CatalogHiddenFlowRefusal
      readonly bundle: null
    }

export type CatalogHiddenFlowRunCall =
  | ExecutedCatalogHiddenFlow
  | {
      readonly response:
        | CatalogHiddenFlowUnavailableResponse
        | CatalogHiddenFlowRefusal
      readonly artifacts: null
    }

export interface CatalogHiddenFlowPrepareOptions {
  readonly reviewAuthority?: CatalogHiddenFlowReviewAuthority
  readonly signal?: AbortSignal
}

export interface CatalogHiddenFlowCapabilityDependencies {
  readonly reviewAuthority?: CatalogHiddenFlowReviewAuthority
  readonly solver?: CatalogHiddenFlowRunOptions['solver']
}

export type CatalogHiddenFlowActionContext =
  | {
      readonly selectedProblemBytes: Uint8Array
      readonly preparationBundleBytes?: never
    }
  | {
      readonly selectedProblemBytes?: never
      readonly preparationBundleBytes: Uint8Array
    }

function preparationFailure(
  error: unknown,
): CatalogHiddenFlowRefusal {
  return catalogHiddenFlowRefusal(
    error instanceof CatalogHiddenFlowError
      ? error
      : new CatalogHiddenFlowError(
          'problem-not-executable',
          'input-validation',
          'The selected hidden-flow problem could not be prepared safely.',
          { cause: error },
        ),
  )
}

function runFailure(error: unknown): CatalogHiddenFlowRefusal {
  return catalogHiddenFlowRefusal(
    error instanceof CatalogHiddenFlowError
      ? error
      : new CatalogHiddenFlowError(
          'preparation-bundle-invalid',
          'verification',
          'The selected hidden-flow preparation bundle could not be validated.',
          { cause: error },
        ),
  )
}

export function prepareCatalogHiddenFlow(
  input: unknown,
  context: CatalogHiddenFlowPrepareContext,
  options: CatalogHiddenFlowPrepareOptions = {},
): CatalogHiddenFlowPrepareCall {
  try {
    if (options.reviewAuthority === undefined) {
      throw new CatalogHiddenFlowError(
        'review-authority-unavailable',
        'review',
        'The generic hidden-flow reviewed-problem authority is unavailable.',
      )
    }
    const humanContext =
      validateCatalogHiddenFlowHumanContext(input)
    return prepareCatalogHiddenFlowBundle(
      humanContext,
      context.selectedProblemBytes,
      options.reviewAuthority,
      options.signal,
    )
  } catch (error) {
    return {
      response: preparationFailure(error),
      bundle: null,
    }
  }
}

export async function runCatalogHiddenFlow(
  input: unknown,
  context: CatalogHiddenFlowRunContext,
  options: CatalogHiddenFlowRunOptions = {},
): Promise<CatalogHiddenFlowRunCall> {
  try {
    if (options.reviewAuthority === undefined) {
      throw new CatalogHiddenFlowError(
        'review-authority-unavailable',
        'review',
        'The generic hidden-flow reviewed-problem authority is unavailable.',
      )
    }
    const humanContext =
      validateCatalogHiddenFlowHumanContext(input)
    const validated = validateCatalogHiddenFlowBundle(
      humanContext,
      context.preparationBundleBytes,
      options.reviewAuthority,
      options.signal,
    )
    const executed = await executeCatalogHiddenFlowBundle(
      humanContext,
      validated,
      options,
    )
    return 'response' in executed
      ? executed
      : {
          response: executed,
          artifacts: null,
        }
  } catch (error) {
    return {
      response: runFailure(error),
      artifacts: null,
    }
  }
}

export function createCatalogHiddenFlowCapability(
    dependencies: CatalogHiddenFlowCapabilityDependencies = {},
  ) {
    return Object.freeze({
      prepare(
        input: unknown,
        context: CatalogHiddenFlowPrepareContext,
        options: Omit<
          CatalogHiddenFlowPrepareOptions,
          'reviewAuthority'
        > = {},
      ): CatalogHiddenFlowPrepareCall {
        return prepareCatalogHiddenFlow(input, context, {
          ...options,
          reviewAuthority: dependencies.reviewAuthority,
        })
      },
      run(
        input: unknown,
        context: CatalogHiddenFlowRunContext,
        options: Omit<
          CatalogHiddenFlowRunOptions,
          'reviewAuthority' | 'solver'
        > = {},
      ): Promise<CatalogHiddenFlowRunCall> {
        return runCatalogHiddenFlow(input, context, {
          ...options,
          reviewAuthority: dependencies.reviewAuthority,
          solver: dependencies.solver,
        })
      },
      call(
        action: string,
        input: unknown,
        context: CatalogHiddenFlowActionContext,
        options: Omit<
          CatalogHiddenFlowRunOptions,
          'reviewAuthority' | 'solver'
        > = {},
      ):
        | CatalogHiddenFlowPrepareCall
        | Promise<CatalogHiddenFlowRunCall> {
        if (
          action ===
          FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION &&
          context.selectedProblemBytes !== undefined
        ) {
          return prepareCatalogHiddenFlow(
            input,
            {
              selectedProblemBytes:
                context.selectedProblemBytes,
            },
            {
              signal: options.signal,
              reviewAuthority:
                dependencies.reviewAuthority,
            },
          )
        }
        if (
          action ===
          FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION &&
          context.preparationBundleBytes !== undefined
        ) {
          return runCatalogHiddenFlow(
            input,
            {
              preparationBundleBytes:
                context.preparationBundleBytes,
            },
            {
              ...options,
              reviewAuthority:
                dependencies.reviewAuthority,
              solver: dependencies.solver,
            },
          )
        }
        return {
          response: catalogHiddenFlowRefusal(
            new CatalogHiddenFlowError(
              'input-invalid',
              'input-validation',
              'Only the reviewed prepare-study and run-and-verify-study actions with their matching host-selected attachment contexts are supported.',
            ),
          ),
          bundle: null,
        }
      },
    })
}

export type CatalogHiddenFlowSerializableResponse =
  | CatalogHiddenFlowPreparedResponse
  | CatalogHiddenFlowRunResponse
  | CatalogHiddenFlowUnavailableResponse
  | CatalogHiddenFlowRefusal

import type {
  CatalogHiddenFlowPrepareCall,
} from './capability.ts'
import type {
  CatalogHiddenFlowPackagedRunResponse,
} from './packagePublication.ts'
import {
  FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
  FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
} from './profile.ts'
import type {
  CatalogHiddenFlowHumanContext,
  CatalogHiddenFlowRefusal,
} from './profile.ts'
import type {
  CatalogHiddenFlowUnavailableResponse,
} from './execution.ts'

declare const hostConfirmedRun:
  unique symbol

export interface CatalogHiddenFlowHostConfirmedRunInvocation {
  readonly [hostConfirmedRun]:
    'host-owned-non-serializable-run-confirmation'
}

export interface CatalogHiddenFlowSharedV2PrepareInvocation {
  readonly methodId:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID
  readonly methodVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly action:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION
  readonly input: CatalogHiddenFlowHumanContext
  readonly selectedProblemSnapshot: Uint8Array
  readonly signal?: AbortSignal
}

export interface CatalogHiddenFlowSharedV2RunInvocation {
  readonly methodId:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID
  readonly methodVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly action:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION
  readonly input: CatalogHiddenFlowHumanContext
  readonly preparationBundleSnapshot: Uint8Array
  readonly confirmedInvocation:
    CatalogHiddenFlowHostConfirmedRunInvocation
  readonly signal?: AbortSignal
}

export interface CatalogHiddenFlowSharedV2Adapter {
  readonly methodId:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID
  readonly methodVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION
  readonly methodFamily:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY
  readonly packageVersion:
    typeof FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION
  prepare(
    invocation: CatalogHiddenFlowSharedV2PrepareInvocation,
  ): Promise<CatalogHiddenFlowPrepareCall>
  run(
    invocation: CatalogHiddenFlowSharedV2RunInvocation,
  ): Promise<
    | CatalogHiddenFlowPackagedRunResponse
    | CatalogHiddenFlowUnavailableResponse
    | CatalogHiddenFlowRefusal
  >
}

export const FLOWBLIND_CATALOG_HIDDEN_FLOW_SHARED_V2_ADAPTER_CONTRACT =
  Object.freeze({
    routeKey: Object.freeze([
      'methodId',
      'methodVersion',
      'action',
    ] as const),
    methodId:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
    methodVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
    methodFamily:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
    packageVersion:
      FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
    scientistInput:
      'goal-and-optional-details-only',
    prepare: Object.freeze({
      action:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
      resultFree: true,
      hostSelection:
        'immutable-canonical-problem-snapshot',
    }),
    run: Object.freeze({
      action:
        FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
      confirmation:
        'host-owned-non-serializable-immediately-before-invocation',
      hostSelection:
        'immutable-preparation-bundle-snapshot',
      publication:
        'package-marker-verified-set-host-promoted-only-after-verification',
    }),
    packageFailureBoundary: Object.freeze([
      'typed-refused',
      'typed-unavailable',
      'marker-verified-report-complete',
    ] as const),
    hostFailureBoundary: Object.freeze([
      'unknown-method-version-or-action',
      'confirmation-cancelled-before-invocation',
      'snapshot-creation-failed',
      'image-command-or-closure-mismatch',
      'output-mount-or-promotion-failed',
    ] as const),
    authorityExclusions: Object.freeze([
      'physical-truth',
      'source-accuracy',
      'measurement-validity-or-calibration',
      'clinical-relevance-or-use',
      'user-approval',
      'model-approval',
    ] as const),
    rawDependencyInjectionPermitted: false,
  } as const)

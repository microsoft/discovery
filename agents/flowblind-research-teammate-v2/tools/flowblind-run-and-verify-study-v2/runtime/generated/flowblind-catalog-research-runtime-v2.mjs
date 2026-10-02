import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";
import { link, lstat, mkdir, mkdtemp, open, opendir, realpath, rm, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, isAbsolute, parse, relative, resolve, sep } from "node:path";
import { constants } from "node:fs";
//#region tools/catalogResearchV2/confirmation.ts
var confirmedExecutionHandles = /* @__PURE__ */ new WeakSet();
var confirmedExecutionBindings = /* @__PURE__ */ new WeakMap();
var confirmedExecutionAuthorities = /* @__PURE__ */ new WeakSet();
var confirmedExecutionAuthorityBindings = /* @__PURE__ */ new WeakMap();
var confirmedExecutionAuthorityBinding = Object.freeze({});
function mintConfirmedExecutionHandle(request) {
	const handle = Object.freeze(Object.create(null));
	confirmedExecutionHandles.add(handle);
	confirmedExecutionBindings.set(handle, request);
	return handle;
}
function isRuntimeConfirmedExecutionHandle(value, request) {
	return value !== null && typeof value === "object" && confirmedExecutionHandles.has(value) && (request === void 0 || confirmedExecutionBindings.get(value) === request);
}
function isRuntimeConfirmedExecutionAuthority(value) {
	return value !== null && typeof value === "object" && Object.isFrozen(value) && confirmedExecutionAuthorities.has(value) && confirmedExecutionAuthorityBindings.get(value) === confirmedExecutionAuthorityBinding;
}
function createRuntimeConfirmedExecutionAuthority(confirm) {
	const authority = Object.freeze({ async withConfirmedExecution(request, operation, signal) {
		const decision = await confirm(request, signal);
		if (decision === "cancelled") return { status: "cancelled" };
		if (decision === "busy-package-capacity") return {
			status: "busy",
			scope: "package-capacity"
		};
		if (decision === "busy-exact-execution") return {
			status: "busy",
			scope: "exact-execution"
		};
		if (decision === "prior-outcome-unknown") return { status: "prior-outcome-unknown" };
		const handle = mintConfirmedExecutionHandle(request);
		try {
			return {
				status: "completed",
				result: await operation(handle)
			};
		} finally {
			confirmedExecutionHandles.delete(handle);
			confirmedExecutionBindings.delete(handle);
		}
	} });
	confirmedExecutionAuthorities.add(authority);
	confirmedExecutionAuthorityBindings.set(authority, confirmedExecutionAuthorityBinding);
	return authority;
}
//#endregion
//#region tools/catalogResearchV2/contract.ts
var FLOWBLIND_V2_ROUTER_PACKAGE_VERSION = "2.0.0";
var FLOWBLIND_V2_PACKAGE_ID = "flowblind-research-teammate-v2";
var FLOWBLIND_V2_PACKAGE_VERSION = "2.0.0";
var FLOWBLIND_V2_ADAPTER_INTERFACE_ID = "flowblind-catalog-research-method-adapter-v2";
var FLOWBLIND_V2_ADAPTER_INTERFACE_VERSION = "2.0.0";
var FLOWBLIND_V2_PUBLIC_ACTIONS = ["prepare-study", "run-and-verify-study"];
var FLOWBLIND_SCIENTIST_PREPARE_FIELDS = [
	"researchGoal",
	"decisionQuestion",
	"nextEvidenceIntent",
	"metadata"
];
var FLOWBLIND_SCIENTIST_RUN_FIELDS = [
	"researchGoal",
	"decisionQuestion",
	"nextEvidenceIntent"
];
var FLOWBLIND_TECHNICAL_SCIENTIST_FIELDS = Object.freeze([
	"action",
	"actionName",
	"adapterVersion",
	"approval",
	"approved",
	"attachment",
	"attachmentPath",
	"authority",
	"authorityEvidence",
	"byteLength",
	"capabilityId",
	"confirmation",
	"familyId",
	"hash",
	"manifest",
	"methodId",
	"methodVersion",
	"mountUri",
	"packageId",
	"packageVersion",
	"path",
	"protocolId",
	"receipt",
	"runId",
	"schemaId",
	"sha256",
	"toolName"
]);
var FLOWBLIND_V2_MAX_ARTIFACT_BYTES = 16777216;
function containsDisallowedControl(value) {
	return [...value].some((character) => {
		const codePoint = character.codePointAt(0);
		return codePoint !== void 0 && (codePoint >= 0 && codePoint <= 8 || codePoint === 11 || codePoint === 12 || codePoint >= 14 && codePoint <= 31 || codePoint === 127);
	});
}
function isSafeArtifactReference(reference) {
	if (reference.length === 0 || reference.length > 512 || reference !== reference.normalize("NFC").trim() || reference.startsWith("/") || reference.includes("\\") || reference.includes("://") || /^[a-z]:/iu.test(reference) || containsDisallowedControl(reference)) return false;
	return reference.split("/").every((segment) => segment.length > 0 && segment !== "." && segment !== "..");
}
function ownArtifactField(value, key) {
	try {
		const descriptor = Object.getOwnPropertyDescriptor(value, key);
		return descriptor !== void 0 && "value" in descriptor ? descriptor.value : void 0;
	} catch {
		return;
	}
}
function isFlowBlindV2ArtifactIdentity(value) {
	if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
	const reference = ownArtifactField(value, "reference");
	const byteLength = ownArtifactField(value, "byteLength");
	const sha256 = ownArtifactField(value, "sha256");
	const mediaType = ownArtifactField(value, "mediaType");
	return typeof reference === "string" && isSafeArtifactReference(reference) && typeof byteLength === "number" && Number.isSafeInteger(byteLength) && byteLength > 0 && byteLength <= 16777216 && typeof sha256 === "string" && /^[a-f0-9]{64}$/u.test(sha256) && typeof mediaType === "string" && mediaType.length > 0 && mediaType.length <= 256 && mediaType === mediaType.trim() && !containsDisallowedControl(mediaType);
}
Object.freeze([
	"disabled-by-release-policy",
	"package-not-installed",
	"package-verification-failed",
	"retained-package-unavailable",
	"host-confirmation-authority-unavailable"
]);
Object.freeze(["retained-package-unavailable"]);
function capabilityIdentityKey(identity) {
	return [
		identity.familyId,
		identity.methodId,
		identity.methodVersion
	].join("/");
}
function capabilityRouteKey(identity) {
	return [identity.methodId, identity.methodVersion].join("/");
}
function isFlowBlindV2Action(value) {
	return FLOWBLIND_V2_PUBLIC_ACTIONS.some((action) => action === value);
}
function sameCapabilityIdentity(left, right) {
	return left.familyId === right.familyId && left.methodId === right.methodId && left.methodVersion === right.methodVersion;
}
function flowBlindV2Route(identity, action) {
	return Object.freeze({
		methodId: identity.methodId,
		methodVersion: identity.methodVersion,
		action
	});
}
function sameSchemaBinding(left, right) {
	return left.recordKind === right.recordKind && left.schemaId === right.schemaId && left.schemaVersion === right.schemaVersion;
}
function sameArtifactIdentity(left, right) {
	return left.reference === right.reference && left.byteLength === right.byteLength && left.sha256 === right.sha256 && left.mediaType === right.mediaType;
}
function samePackageBinding(left, right) {
	return left.packageId === right.packageId && left.packageVersion === right.packageVersion && left.compatibilityKey === right.compatibilityKey;
}
function sameRendererBinding(left, right) {
	return left.rendererId === right.rendererId && left.rendererVersion === right.rendererVersion && left.resourceReference === right.resourceReference && left.resourceUriScheme === right.resourceUriScheme && left.resourceMediaType === right.resourceMediaType;
}
//#endregion
//#region tools/catalogResearch/catalogResearchProfile.ts
var FLOWBLIND_CATALOG_RESEARCH_VERSION = "1.0.0";
var FLOWBLIND_CATALOG_PROTOCOL_PRESET_ID = "paired-planar-regional-agreement-3x3-minimum-30-v1";
var FLOWBLIND_CATALOG_VECTOR_PROTOCOL_PRESET_ID = "structured-planar-vector-time-readiness-standard-v1";
var FLOWBLIND_CATALOG_VECTOR_PREPARATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-vector-preparation-bundle-v1.schema.json";
var FLOWBLIND_CATALOG_VECTOR_VERIFIED_STUDY_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-vector-verified-study-v1.schema.json";
var FLOWBLIND_CATALOG_PREPARATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-preparation-bundle-v1.schema.json";
var FLOWBLIND_CATALOG_VERIFIED_STUDY_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-verified-study-v1.schema.json";
Object.freeze({
	maximumAttachmentFiles: 3,
	maximumAttachmentBytesEach: 16777216,
	maximumAttachmentBytesTotal: 33554432,
	maximumDataRows: 25e4,
	maximumDataFields: 1e6,
	maximumGridPoints: 1e6,
	maximumVectorFrames: 1e4,
	maximumVectorPointSamples: 25e4,
	maximumVectorValues: 5e5,
	maximumWindows: 256,
	maximumPointWindowEvaluations: 5e7,
	maximumOutputArtifactBytes: 16777216,
	maximumPublishedBytes: 50331648,
	parserContainerMemoryBytes: 536870912,
	childProcesses: 0,
	networkRequests: 0
});
var FLOWBLIND_CATALOG_PUBLIC_INPUT_SCHEMA = Object.freeze({
	type: "object",
	properties: {
		researchGoal: {
			type: "string",
			minLength: 1,
			maxLength: 4096,
			title: "Research goal",
			description: "Describe one reviewed FlowBlind research question in ordinary scientific language."
		},
		decisionQuestion: {
			type: "string",
			minLength: 1,
			maxLength: 4096,
			title: "Decision question",
			description: "Optional scientist-authored decision question; no technical identifiers."
		},
		nextEvidenceIntent: {
			type: "string",
			minLength: 1,
			maxLength: 4096,
			title: "Next evidence intent",
			description: "Optional scientist-authored statement of the next evidence needed."
		}
	},
	required: ["researchGoal"],
	additionalProperties: false
});
var commonScientificMetadataProperties = {
	quantity: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Scientific quantity",
		description: "Name the physical or scientific quantity represented by the selected scalar or vector values."
	},
	coordinateUnit: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Coordinate unit and geometry",
		description: "Declare the x/y coordinate unit and any non-equal-area geometry limitation."
	},
	valueUnit: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Value unit",
		description: "Declare the shared scalar or velocity unit required by the matched capability."
	},
	provenance: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Provenance",
		description: "Provide the source citation or provenance statement."
	},
	license: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Licence",
		description: "Declare the licence or permission governing the selected data."
	}
};
var regionalAgreementMetadataProperties = {
	referenceMeaning: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Reference meaning",
		description: "Describe what the reference_value column represents."
	},
	candidateMeaning: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Candidate meaning",
		description: "Describe what the candidate_value column represents."
	}
};
var vectorTimeMetadataProperties = {
	vectorMeaning: {
		type: "string",
		minLength: 1,
		maxLength: 4096,
		title: "Vector field meaning",
		description: "Describe what the u and v vector components represent."
	},
	vectorSourceKind: {
		type: "string",
		enum: [
			"generated",
			"measured",
			"simulation"
		],
		title: "Source kind",
		description: "Classify the selected vector field as generated, measured, or simulated."
	},
	timeUnit: {
		type: "string",
		enum: ["s", "ms"],
		title: "Time unit",
		description: "Declare the unit used by the optional time column."
	},
	samplingKind: {
		type: "string",
		enum: [
			"instantaneous",
			"steady-state",
			"frame-average"
		],
		title: "Temporal sampling",
		description: "Declare whether rows are instantaneous, steady-state, or frame-average samples."
	},
	selectedTime: {
		type: "number",
		title: "Selected audit time",
		description: "Optional exact or interpolated time to audit; defaults to the first frame."
	},
	exposureDuration: {
		type: "number",
		exclusiveMinimum: 0,
		title: "Frame exposure duration",
		description: "Required for frame-average sampling, in the declared time unit."
	},
	exposureOperator: {
		type: "string",
		enum: ["uniform-window-average", "unspecified"],
		title: "Frame exposure operator",
		description: "Optional frame-average exposure operator; omitted remains explicitly unspecified."
	},
	timestampAnchor: {
		type: "string",
		enum: [
			"start",
			"midpoint",
			"end",
			"unspecified"
		],
		title: "Frame timestamp anchor",
		description: "Optional frame-average timestamp anchor; omitted remains explicitly unspecified."
	},
	cycleStartTime: {
		type: "number",
		title: "Cycle start time"
	},
	cycleEndTime: {
		type: "number",
		title: "Cycle end time"
	},
	cyclePeriod: {
		type: "number",
		exclusiveMinimum: 0,
		title: "Cycle period"
	},
	cyclePhaseOrigin: {
		type: "number",
		title: "Cycle phase origin"
	}
};
Object.freeze({
	type: "object",
	properties: {
		...FLOWBLIND_CATALOG_PUBLIC_INPUT_SCHEMA.properties,
		...commonScientificMetadataProperties,
		...regionalAgreementMetadataProperties,
		...vectorTimeMetadataProperties
	},
	required: [
		"researchGoal",
		"quantity",
		"coordinateUnit",
		"valueUnit",
		"provenance",
		"license"
	],
	oneOf: [{
		required: ["referenceMeaning", "candidateMeaning"],
		not: { anyOf: [
			{ required: ["vectorMeaning"] },
			{ required: ["vectorSourceKind"] },
			{ required: ["timeUnit"] },
			{ required: ["samplingKind"] },
			{ required: ["selectedTime"] },
			{ required: ["exposureDuration"] },
			{ required: ["exposureOperator"] },
			{ required: ["timestampAnchor"] },
			{ required: ["cycleStartTime"] },
			{ required: ["cycleEndTime"] },
			{ required: ["cyclePeriod"] },
			{ required: ["cyclePhaseOrigin"] }
		] }
	}, {
		required: [
			"vectorMeaning",
			"vectorSourceKind",
			"timeUnit",
			"samplingKind"
		],
		properties: {
			coordinateUnit: { enum: [
				"m",
				"cm",
				"mm"
			] },
			valueUnit: { enum: [
				"m/s",
				"cm/s",
				"mm/s"
			] }
		},
		not: { anyOf: [{ required: ["referenceMeaning"] }, { required: ["candidateMeaning"] }] },
		allOf: [
			{
				if: {
					properties: { samplingKind: { const: "frame-average" } },
					required: ["samplingKind"]
				},
				then: { required: ["exposureDuration"] },
				else: { not: { anyOf: [
					{ required: ["exposureDuration"] },
					{ required: ["exposureOperator"] },
					{ required: ["timestampAnchor"] }
				] } }
			},
			{
				if: { anyOf: [{ required: ["exposureOperator"] }, { required: ["timestampAnchor"] }] },
				then: { required: ["exposureOperator", "timestampAnchor"] }
			},
			{
				if: { anyOf: [
					{ required: ["cycleStartTime"] },
					{ required: ["cycleEndTime"] },
					{ required: ["cyclePeriod"] },
					{ required: ["cyclePhaseOrigin"] }
				] },
				then: { required: [
					"cycleStartTime",
					"cycleEndTime",
					"cyclePeriod",
					"cyclePhaseOrigin"
				] }
			}
		]
	}],
	additionalProperties: false
});
var FLOWBLIND_CATALOG_CAPABILITIES = Object.freeze([{
	capabilityId: "regional-agreement-v1",
	familyId: "regional-agreement",
	methodFamily: "regional-agreement-selection-sensitivity-v1",
	protocolPresetId: FLOWBLIND_CATALOG_PROTOCOL_PRESET_ID,
	acceptedCsvHeaders: ["x,y,reference_value,candidate_value"],
	claim: "Descriptive paired-planar regional agreement and selection sensitivity."
}, {
	capabilityId: "vector-time-readiness-audit-v1",
	familyId: "vector-time-readiness",
	methodFamily: "vector-time-readiness-audit-v1",
	protocolPresetId: FLOWBLIND_CATALOG_VECTOR_PROTOCOL_PRESET_ID,
	acceptedCsvHeaders: [
		"x,y,u,v",
		"x,y,u,v,valid",
		"time,x,y,u,v",
		"time,x,y,u,v,valid"
	],
	claim: "Descriptive structured planar vector and temporal evidence readiness."
}]);
function catalogCapabilityIdentity(capabilityId) {
	const capability = FLOWBLIND_CATALOG_CAPABILITIES.find((candidate) => candidate.capabilityId === capabilityId);
	if (capability === void 0) throw new Error("Unknown reviewed catalog capability.");
	return {
		capabilityId: capability.capabilityId,
		familyId: capability.familyId,
		methodFamily: capability.methodFamily,
		protocolPresetId: capability.protocolPresetId
	};
}
//#endregion
//#region tools/catalogResearchV2/capabilityAdapter.ts
var CapabilityAdapterDefinitionError = class extends Error {
	constructor(message) {
		super(message);
		this.name = "CapabilityAdapterDefinitionError";
	}
};
function assertUniqueRoles(roles, label) {
	const names = roles.map((role) => role.role);
	if (new Set(names).size !== names.length || roles.some((role) => role.role.trim().length === 0 || !Number.isSafeInteger(role.exactCount) || role.exactCount < 1 || role.access !== "read-only" || role.suppliedBy !== "host" || role.members.length === 0 || new Set(role.members.map((member) => member.role)).size !== role.members.length || role.members.some((member) => member.role.trim().length === 0 || member.mediaType.trim().length === 0 || member.portableReference.trim().length === 0))) throw new CapabilityAdapterDefinitionError(`${label} attachment roles must be unique, host-supplied, read-only, and have positive exact cardinality.`);
}
function validateDefinition(adapter) {
	if (adapter.interfaceId !== "flowblind-catalog-research-method-adapter-v2" || adapter.interfaceVersion !== "2.0.0") throw new CapabilityAdapterDefinitionError("Capability adapter contract version is invalid.");
	capabilityIdentityKey(adapter.identity).split("/").forEach((part) => {
		if (part.trim().length === 0) throw new CapabilityAdapterDefinitionError("Capability identity fields must be non-empty.");
	});
	if (adapter.scientistMetadata.status === "reviewed") {
		const descriptor = adapter.scientistMetadata.descriptor;
		const forbidden = descriptor.propertyNames.filter((property) => FLOWBLIND_TECHNICAL_SCIENTIST_FIELDS.includes(property));
		if (descriptor.additionalProperties !== false || new Set(descriptor.propertyNames).size !== descriptor.propertyNames.length || descriptor.requiredPropertyNames.some((property) => !descriptor.propertyNames.includes(property)) || forbidden.length > 0) throw new CapabilityAdapterDefinitionError(`Scientist metadata schema ${descriptor.schemaId} is not a strict scientist-only schema.`);
	}
	if (adapter.attachments.status === "reviewed") {
		assertUniqueRoles(adapter.attachments.prepare, "Prepare");
		assertUniqueRoles(adapter.attachments.run, "Run");
	}
	if (isActiveCapabilityAdapter(adapter)) {
		if (adapter.release.status !== "candidate-active" || adapter.release.advertiseToScientist !== true || adapter.scientistMetadata.status !== "reviewed" || adapter.attachments.status !== "reviewed" || adapter.packageCompatibility.status !== "exact" || adapter.lifecycleBoundary.status !== "reviewed" || adapter.preparationRecord.status !== "bound" || adapter.resultRecord.status !== "bound" || adapter.renderer.status !== "bound") throw new CapabilityAdapterDefinitionError("Active adapters require reviewed metadata, attachment, package, lifecycle, record, renderer, and resource contracts.");
	} else if (adapter.lifecycle !== null) throw new CapabilityAdapterDefinitionError("Default-off and unavailable descriptors cannot carry executable lifecycle hooks.");
	if (adapter.availability.state !== "active" && (adapter.release.status !== "default-off" || adapter.release.advertiseToScientist !== false || adapter.release.unavailableReason !== "disabled-by-release-policy")) throw new CapabilityAdapterDefinitionError("Non-active descriptors must be default-off and unadvertised by immutable release policy.");
}
function deepFreeze$1(value, visited = /* @__PURE__ */ new WeakSet()) {
	if (value === null || typeof value !== "object") return value;
	if (visited.has(value)) return value;
	visited.add(value);
	let descriptors;
	try {
		descriptors = Object.getOwnPropertyDescriptors(value);
	} catch {
		throw new CapabilityAdapterDefinitionError("Capability adapter properties could not be inspected safely.");
	}
	for (const key of Reflect.ownKeys(descriptors)) {
		const descriptor = Reflect.get(descriptors, key);
		if (!("value" in descriptor)) throw new CapabilityAdapterDefinitionError(`Capability adapter property ${String(key)} cannot be an accessor.`);
		deepFreeze$1(descriptor.value, visited);
	}
	return Object.isFrozen(value) ? value : Object.freeze(value);
}
function defineCapabilityAdapter(adapter) {
	const frozen = deepFreeze$1(adapter);
	validateDefinition(frozen);
	return frozen;
}
function isActiveCapabilityAdapter(adapter) {
	return adapter.availability.state === "active" && adapter.release.status === "candidate-active" && adapter.lifecycle !== null;
}
function createCapabilityRegistry(descriptors) {
	descriptors.forEach(validateDefinition);
	const keys = descriptors.map((adapter) => capabilityRouteKey(adapter.identity));
	if (new Set(keys).size !== keys.length) throw new CapabilityAdapterDefinitionError("Capability registry methodId/methodVersion route keys must be unique across families.");
	const executable = descriptors.filter(isActiveCapabilityAdapter);
	return Object.freeze({
		descriptors: Object.freeze([...descriptors]),
		advertised: Object.freeze(executable.map((adapter) => Object.freeze({
			identity: adapter.identity,
			releaseStatus: adapter.release.status,
			actions: ["prepare-study", "run-and-verify-study"]
		}))),
		executable: Object.freeze(executable)
	});
}
function exactPackageCompatibility(prepared, runtime) {
	return samePackageBinding(prepared, runtime);
}
function exactHostAuthorityPredicate(requirement, expected) {
	return (authority) => authority.integrationId === requirement.integrationId && authority.integrationVersion === requirement.integrationVersion && authority.capability.authorityRequirementId === requirement.requirementId && requirement.requiredGrants.every((grant) => authority.grants.includes(grant)) && samePackageBinding(authority.capability.package, expected.package) && sameSchemaBinding(authority.capability.preparationSchema, expected.preparationSchema) && sameSchemaBinding(authority.capability.resultSchema, expected.resultSchema) && sameRendererBinding(authority.capability.renderer, expected.renderer);
}
var DELEGATED_ACTIVE_LIFECYCLE = Object.freeze({
	prepare: async (context) => context.authority.capability.prepare({
		scientist: context.scientist,
		attachments: context.attachments,
		...context.signal === void 0 ? {} : { signal: context.signal }
	}),
	run: async (context) => context.authority.capability.run({
		scientist: context.scientist,
		preparedStudy: context.preparedStudy,
		attachments: context.attachments,
		confirmedExecution: context.confirmedExecution,
		...context.signal === void 0 ? {} : { signal: context.signal }
	}),
	render: async (authority, record) => authority.capability.render(record),
	readResource: async (authority, uri) => authority.capability.readResource(uri)
});
//#endregion
//#region tools/catalogResearchV2/descriptors.ts
var V1_PACKAGE = Object.freeze({
	packageId: "flowblind-catalog-package-lock-v1",
	packageVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
	compatibilityKey: "sha256:7f44c401f4b1e4238be31c48bc39f63892820cb7cd8e826fbc033b47d481a0a4"
});
var V1_RENDERER = Object.freeze({
	rendererId: "flowblind-catalog-report-resource-v1",
	rendererVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
	resourceReference: "report.html",
	resourceUriScheme: "flowblind-report",
	resourceMediaType: "text/html"
});
var REGIONAL_PREPARATION = Object.freeze({
	recordKind: "flowblind-catalog-preparation-bundle-v1",
	schemaId: FLOWBLIND_CATALOG_PREPARATION_SCHEMA_ID,
	schemaVersion: "1"
});
var REGIONAL_RESULT = Object.freeze({
	recordKind: "flowblind-catalog-verified-study-v1",
	schemaId: FLOWBLIND_CATALOG_VERIFIED_STUDY_SCHEMA_ID,
	schemaVersion: "1"
});
var VECTOR_PREPARATION = Object.freeze({
	recordKind: "flowblind-catalog-vector-preparation-bundle-v1",
	schemaId: FLOWBLIND_CATALOG_VECTOR_PREPARATION_SCHEMA_ID,
	schemaVersion: "1"
});
var VECTOR_RESULT = Object.freeze({
	recordKind: "flowblind-catalog-vector-verified-study-v1",
	schemaId: FLOWBLIND_CATALOG_VECTOR_VERIFIED_STUDY_SCHEMA_ID,
	schemaVersion: "1"
});
var V1_AUTHORITY_GRANTS = Object.freeze([
	"attested-package-lock",
	"immutable-read-only-attachment-snapshot",
	"prepare-confirmation-disabled",
	"result-free-preparation",
	"run-confirmation-enabled",
	"deterministic-verification-replay",
	"verification-record-installed-last",
	"content-addressed-flowblind-report-resource"
]);
var V1_AUTHORITY = Object.freeze({
	requirementId: "flowblind-catalog-v1-attested-host-authority",
	integrationId: "flowblind-catalog-v1-runtime",
	integrationVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
	requiredGrants: V1_AUTHORITY_GRANTS,
	detail: "Requires the exact attested v1 package, immutable read-only host attachments, the disabled/required confirmation split, deterministic verification, and content-addressed publication."
});
var CANDIDATE_ROLE = Object.freeze({
	role: "candidate-data",
	exactCount: 1,
	access: "read-only",
	suppliedBy: "host",
	members: Object.freeze([Object.freeze({
		role: "candidate-data",
		mediaType: "text/csv",
		portableReference: "candidate.csv"
	})]),
	description: "The exact researcher-selected candidate CSV supplied through the trusted host attachment boundary."
});
var PREPARED_ARTIFACT_SET_ROLE = Object.freeze({
	role: "prepared-artifact-set",
	exactCount: 1,
	access: "read-only",
	suppliedBy: "host",
	members: Object.freeze([Object.freeze({
		role: "trusted-sidecar",
		mediaType: "application/json",
		portableReference: "trusted-sidecar.json"
	}), Object.freeze({
		role: "preparation-bundle",
		mediaType: "application/json",
		portableReference: "preparation.json"
	})]),
	description: "One exact preparation artifact set containing trusted-sidecar.json and preparation.json."
});
var V1_ATTACHMENTS = Object.freeze({
	status: "reviewed",
	prepare: Object.freeze([CANDIDATE_ROLE]),
	run: Object.freeze([CANDIDATE_ROLE, PREPARED_ARTIFACT_SET_ROLE])
});
var V1_LIFECYCLE_BOUNDARY = Object.freeze({
	status: "reviewed",
	prepare: Object.freeze({
		confirmation: "none",
		executionPointOfNoReturn: "none",
		publicationPointOfNoReturn: "exclusive-preparation-commit-marker",
		publication: "result-free-content-addressed-preparation"
	}),
	run: Object.freeze({
		confirmation: "host-callback-bracket",
		executionPointOfNoReturn: "confirmed-operation-callback-entry",
		publicationPointOfNoReturn: "exclusive-report-commit-marker",
		publication: "verified-result-and-content-addressed-resource",
		distributedExactlyOnceClaim: false
	})
});
var FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE = Object.freeze({
	hiddenFlow: Object.freeze({
		sourceCommit: "272e69ed95a6730bd68ca2033da4933e9759c883",
		sourceReference: "reviewed-candidate:finite-basis-hidden-flow-v1",
		reviewStatus: "reserved-route-identifier-only",
		implementationImported: false,
		route: Object.freeze({
			familyId: "hidden-flow",
			methodId: "finite-basis-hidden-flow-v1",
			methodVersion: "1.1.0"
		})
	}),
	sensorPlacement: Object.freeze({
		sourceCommit: "ea457591ea7c9d73fde7d5f8f09b95894934e590",
		sourceReference: "reviewed-candidate:flowblind-finite-sensor-placement-v1",
		reviewStatus: "reserved-route-identifier-only",
		implementationImported: false,
		route: Object.freeze({
			familyId: "sensor-placement",
			methodId: "flowblind-finite-sensor-placement-v1",
			methodVersion: "2.0.0"
		})
	}),
	externalValidation: Object.freeze({
		sourceCommit: "016450eba0a95ae70125edc7597b40fafcb93ba3",
		sourceReference: "reviewed-candidate:generic-planar-external-validation-v1",
		reviewStatus: "reserved-route-identifier-only",
		implementationImported: false,
		route: Object.freeze({
			familyId: "external-validation",
			methodId: "generic-planar-external-validation-v1",
			methodVersion: "1.0.0"
		})
	})
});
function isRecord(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}
function hasExactProperties(value, allowed, required) {
	return Object.keys(value).every((key) => allowed.includes(key)) && required.every((key) => key in value);
}
function nonEmptyString(value) {
	return typeof value === "string" && value.normalize("NFC").trim().length > 0 && value.length <= 4096;
}
var REGIONAL_METADATA_PROPERTIES = Object.freeze([
	"quantity",
	"referenceMeaning",
	"candidateMeaning",
	"coordinateUnit",
	"valueUnit",
	"provenance",
	"license"
]);
var regionalMetadata = Object.freeze({
	schemaId: "urn:flowblind:scientist-metadata:regional-agreement:v2",
	schemaVersion: "2",
	propertyNames: REGIONAL_METADATA_PROPERTIES,
	requiredPropertyNames: REGIONAL_METADATA_PROPERTIES,
	additionalProperties: false,
	validate(value) {
		return isRecord(value) && hasExactProperties(value, REGIONAL_METADATA_PROPERTIES, REGIONAL_METADATA_PROPERTIES) && REGIONAL_METADATA_PROPERTIES.every((property) => nonEmptyString(value[property]));
	}
});
var VECTOR_METADATA_PROPERTIES = Object.freeze([
	"quantity",
	"vectorMeaning",
	"vectorSourceKind",
	"coordinateUnit",
	"valueUnit",
	"timeUnit",
	"samplingKind",
	"selectedTime",
	"exposureDuration",
	"exposureOperator",
	"timestampAnchor",
	"cycleStartTime",
	"cycleEndTime",
	"cyclePeriod",
	"cyclePhaseOrigin",
	"provenance",
	"license"
]);
var VECTOR_REQUIRED_METADATA = Object.freeze([
	"quantity",
	"vectorMeaning",
	"vectorSourceKind",
	"coordinateUnit",
	"valueUnit",
	"timeUnit",
	"samplingKind",
	"provenance",
	"license"
]);
function optionalFiniteNumber(value) {
	return value === void 0 || value === null || typeof value === "number" && Number.isFinite(value);
}
function optionalEnum(value, choices) {
	return value === void 0 || value === null || typeof value === "string" && choices.includes(value);
}
var vectorMetadata = Object.freeze({
	schemaId: "urn:flowblind:scientist-metadata:vector-time-readiness:v2",
	schemaVersion: "2",
	propertyNames: VECTOR_METADATA_PROPERTIES,
	requiredPropertyNames: VECTOR_REQUIRED_METADATA,
	additionalProperties: false,
	validate(value) {
		if (!isRecord(value) || !hasExactProperties(value, VECTOR_METADATA_PROPERTIES, VECTOR_REQUIRED_METADATA) || !nonEmptyString(value.quantity) || !nonEmptyString(value.vectorMeaning) || !nonEmptyString(value.provenance) || !nonEmptyString(value.license) || ![
			"generated",
			"measured",
			"simulation"
		].includes(String(value.vectorSourceKind)) || ![
			"m",
			"cm",
			"mm"
		].includes(String(value.coordinateUnit)) || ![
			"m/s",
			"cm/s",
			"mm/s"
		].includes(String(value.valueUnit)) || !["s", "ms"].includes(String(value.timeUnit)) || ![
			"instantaneous",
			"steady-state",
			"frame-average"
		].includes(String(value.samplingKind)) || !optionalFiniteNumber(value.selectedTime) || !optionalFiniteNumber(value.exposureDuration) || !optionalEnum(value.exposureOperator, ["uniform-window-average", "unspecified"]) || !optionalEnum(value.timestampAnchor, [
			"start",
			"midpoint",
			"end",
			"unspecified"
		])) return false;
		const cycleValues = [
			value.cycleStartTime,
			value.cycleEndTime,
			value.cyclePeriod,
			value.cyclePhaseOrigin
		];
		const suppliedCycleValues = cycleValues.filter((candidate) => candidate !== void 0 && candidate !== null);
		return suppliedCycleValues.length === 0 || suppliedCycleValues.length === cycleValues.length && cycleValues.every((candidate) => typeof candidate === "number" && Number.isFinite(candidate));
	}
});
function intentText(intent) {
	return [
		intent.researchGoal,
		intent.decisionQuestion,
		intent.nextEvidenceIntent
	].filter((value) => value !== null).join("\n").toLowerCase();
}
function matchesRegionalAgreement(intent) {
	const goal = intent.researchGoal.toLowerCase();
	return /\b(?:reference|observed|measurement)\b/u.test(goal) && /\b(?:candidate|model|forecast|simulation)\b/u.test(goal) && /\b(?:agreement|concordance|compare|comparison)\b/u.test(goal) && /\b(?:region|regional|spatial|field)\b/u.test(goal);
}
function matchesVectorTimeReadiness(intent) {
	const goal = intent.researchGoal.toLowerCase();
	return /\b(?:vector|velocity|flow field|time series)\b/u.test(goal) && /\b(?:readiness|audit|evidence|speed|derivative|divergence|vorticity|strain|cycle)\b/u.test(goal);
}
function matchesHiddenFlow(intent) {
	const goal = intent.researchGoal.toLowerCase();
	return /\b(?:hidden|unobserved|observation-compatible|null-space)\b/u.test(goal) && /\b(?:flow|perturbation|envelope|robustness|recovery)\b/u.test(goal);
}
function matchesSensorPlacement(intent) {
	const goal = intent.researchGoal.toLowerCase();
	return /\b(?:sensor|probe|measurement)\b/u.test(goal) && /\b(?:placement|layout|design|selection|site)\b/u.test(goal);
}
function matchesExternalValidation(intent) {
	const goal = intent.researchGoal.toLowerCase();
	return /\b(?:external|held-out|replication|ptv|empirical)\b/u.test(goal) && /\b(?:validation|validate|comparison|evaluate)\b/u.test(goal);
}
function regionalUnsupported(intent) {
	const value = intentText(intent);
	return /\b(?:regional means?|trend|bias map|one-sided error)\b/u.test(value) ? [{
		classification: "family-unsupported",
		code: "unreviewed-regional-summary-requested",
		detail: "Regional agreement supports only the frozen v1 endpoints and does not substitute means, trends, bias maps, or one-sided errors."
	}] : [];
}
var noFamilyUnsupported = (_intent) => [];
var regionalCapability = catalogCapabilityIdentity("regional-agreement-v1");
var vectorCapability = catalogCapabilityIdentity("vector-time-readiness-audit-v1");
var REGIONAL_AGREEMENT_V1_ADAPTER = defineCapabilityAdapter({
	interfaceId: FLOWBLIND_V2_ADAPTER_INTERFACE_ID,
	interfaceVersion: FLOWBLIND_V2_ADAPTER_INTERFACE_VERSION,
	identity: Object.freeze({
		familyId: regionalCapability.familyId,
		methodId: regionalCapability.capabilityId,
		methodVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION
	}),
	nativeIdentity: Object.freeze({
		capabilityId: regionalCapability.capabilityId,
		methodFamily: regionalCapability.methodFamily,
		protocolPresetId: regionalCapability.protocolPresetId,
		packageVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION
	}),
	release: Object.freeze({
		status: "candidate-active",
		advertiseToScientist: true
	}),
	availability: Object.freeze({
		state: "active",
		detail: "Active candidate delegated only to an exact trusted integration of the immutable v1 catalog package."
	}),
	matchScientistIntent: matchesRegionalAgreement,
	unsupportedIntentPolicy: regionalUnsupported,
	scientistMetadata: Object.freeze({
		status: "reviewed",
		descriptor: regionalMetadata
	}),
	attachments: V1_ATTACHMENTS,
	authority: Object.freeze({
		requirement: V1_AUTHORITY,
		predicate: exactHostAuthorityPredicate(V1_AUTHORITY, {
			package: V1_PACKAGE,
			preparationSchema: REGIONAL_PREPARATION,
			resultSchema: REGIONAL_RESULT,
			renderer: V1_RENDERER
		})
	}),
	packageCompatibility: Object.freeze({
		status: "exact",
		current: V1_PACKAGE,
		accepts: exactPackageCompatibility
	}),
	lifecycleBoundary: V1_LIFECYCLE_BOUNDARY,
	preparationRecord: Object.freeze({
		status: "bound",
		binding: REGIONAL_PREPARATION
	}),
	resultRecord: Object.freeze({
		status: "bound",
		binding: REGIONAL_RESULT
	}),
	renderer: Object.freeze({
		status: "bound",
		binding: V1_RENDERER
	}),
	lifecycle: DELEGATED_ACTIVE_LIFECYCLE
});
var VECTOR_TIME_READINESS_V1_ADAPTER = defineCapabilityAdapter({
	interfaceId: FLOWBLIND_V2_ADAPTER_INTERFACE_ID,
	interfaceVersion: FLOWBLIND_V2_ADAPTER_INTERFACE_VERSION,
	identity: Object.freeze({
		familyId: vectorCapability.familyId,
		methodId: vectorCapability.capabilityId,
		methodVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION
	}),
	nativeIdentity: Object.freeze({
		capabilityId: vectorCapability.capabilityId,
		methodFamily: vectorCapability.methodFamily,
		protocolPresetId: vectorCapability.protocolPresetId,
		packageVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION
	}),
	release: Object.freeze({
		status: "candidate-active",
		advertiseToScientist: true
	}),
	availability: Object.freeze({
		state: "active",
		detail: "Active candidate delegated only to an exact trusted integration of the immutable v1 catalog package."
	}),
	matchScientistIntent: matchesVectorTimeReadiness,
	unsupportedIntentPolicy: noFamilyUnsupported,
	scientistMetadata: Object.freeze({
		status: "reviewed",
		descriptor: vectorMetadata
	}),
	attachments: V1_ATTACHMENTS,
	authority: Object.freeze({
		requirement: V1_AUTHORITY,
		predicate: exactHostAuthorityPredicate(V1_AUTHORITY, {
			package: V1_PACKAGE,
			preparationSchema: VECTOR_PREPARATION,
			resultSchema: VECTOR_RESULT,
			renderer: V1_RENDERER
		})
	}),
	packageCompatibility: Object.freeze({
		status: "exact",
		current: V1_PACKAGE,
		accepts: exactPackageCompatibility
	}),
	lifecycleBoundary: V1_LIFECYCLE_BOUNDARY,
	preparationRecord: Object.freeze({
		status: "bound",
		binding: VECTOR_PREPARATION
	}),
	resultRecord: Object.freeze({
		status: "bound",
		binding: VECTOR_RESULT
	}),
	renderer: Object.freeze({
		status: "bound",
		binding: V1_RENDERER
	}),
	lifecycle: DELEGATED_ACTIVE_LIFECYCLE
});
function inactiveAuthorityPredicate(requirement) {
	return (authority) => authority.integrationId === requirement.integrationId && authority.integrationVersion === requirement.integrationVersion && authority.capability.authorityRequirementId === requirement.requirementId && requirement.requiredGrants.every((grant) => authority.grants.includes(grant));
}
function inactiveDescriptor(input) {
	const detail = "No reviewed scientist-facing metadata, host attachment, lifecycle, package-compatibility, result-schema, renderer, or resource binding is registered for this v2 core.";
	return defineCapabilityAdapter({
		interfaceId: FLOWBLIND_V2_ADAPTER_INTERFACE_ID,
		interfaceVersion: FLOWBLIND_V2_ADAPTER_INTERFACE_VERSION,
		identity: Object.freeze(input.identity),
		availability: Object.freeze({
			state: "default-off",
			detail: input.stateDetail
		}),
		release: Object.freeze({
			status: "default-off",
			advertiseToScientist: false,
			unavailableReason: "disabled-by-release-policy"
		}),
		matchScientistIntent: input.matcher,
		unsupportedIntentPolicy: noFamilyUnsupported,
		scientistMetadata: Object.freeze({
			status: "unreviewed",
			detail
		}),
		attachments: Object.freeze({
			status: "unreviewed",
			detail
		}),
		authority: Object.freeze({
			requirement: input.authority,
			predicate: inactiveAuthorityPredicate(input.authority)
		}),
		packageCompatibility: Object.freeze({
			status: "unavailable",
			detail
		}),
		lifecycleBoundary: Object.freeze({
			status: "unreviewed",
			detail
		}),
		preparationRecord: Object.freeze({
			status: "unreviewed",
			detail
		}),
		resultRecord: Object.freeze({
			status: "unreviewed",
			detail
		}),
		renderer: Object.freeze({
			status: "unreviewed",
			detail
		}),
		lifecycle: null
	});
}
var HIDDEN_FLOW_V1_DESCRIPTOR = inactiveDescriptor({
	identity: FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE.hiddenFlow.route,
	stateDetail: "Default-off: the existing hidden-flow catalog is evidence, not a scientist-facing v2 adapter implementation.",
	matcher: matchesHiddenFlow,
	authority: Object.freeze({
		requirementId: "hidden-flow-v1-reviewed-adapter-authority",
		integrationId: "flowblind-hidden-flow-v1-runtime",
		integrationVersion: FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE.hiddenFlow.route.methodVersion,
		requiredGrants: Object.freeze([
			"reviewed-scientist-intent-and-metadata-schema",
			"immutable-read-only-attachment-contract",
			"runtime-branded-finite-basis-problem",
			"flowblind-hidden-flow-direct-clarabel-1.0.0",
			"independent-solver-verification",
			"separate-run-confirmation",
			"deterministic-publication"
		]),
		detail: "Activation requires a separately reviewed adapter that preserves the finite-basis claim boundary, runtime-branded problem, exact Clarabel adapter, independent verification, host confirmation, and deterministic publication."
	})
});
var SENSOR_PLACEMENT_V1_DESCRIPTOR = inactiveDescriptor({
	identity: FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE.sensorPlacement.route,
	stateDetail: "Default-off: the existing sensor-placement catalog is evidence, not a scientist-facing v2 adapter implementation.",
	matcher: matchesSensorPlacement,
	authority: Object.freeze({
		requirementId: "sensor-placement-v1-reviewed-adapter-authority",
		integrationId: "flowblind-sensor-placement-v1-runtime",
		integrationVersion: FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE.sensorPlacement.route.methodVersion,
		requiredGrants: Object.freeze([
			"reviewed-scientist-intent-and-metadata-schema",
			"immutable-read-only-attachment-contract",
			"runtime-branded-compiled-problem",
			"exact-enumeration-and-resource-bounds",
			"independent-certificate-verification",
			"separate-run-confirmation",
			"deterministic-publication"
		]),
		detail: "Activation requires a separately reviewed adapter that accepts only the runtime-branded compiled problem, preserves exact enumeration and resource bounds, verifies certificates independently, and supplies host confirmation and deterministic publication."
	})
});
var EXTERNAL_VALIDATION_V1_DESCRIPTOR = inactiveDescriptor({
	identity: FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE.externalValidation.route,
	stateDetail: "Default-off: historical external-validation evidence cannot be activated as a generic scientist-facing adapter.",
	matcher: matchesExternalValidation,
	authority: Object.freeze({
		requirementId: "external-validation-v1-reviewed-adapter-authority",
		integrationId: "flowblind-external-validation-v1-runtime",
		integrationVersion: FLOWBLIND_V2_DEFAULT_OFF_ROUTE_EVIDENCE.externalValidation.route.methodVersion,
		requiredGrants: Object.freeze([
			"reviewed-scientist-intent-and-metadata-schema",
			"publisher-and-source-lock-verification",
			"preregistration-and-layout-lock-verification",
			"held-out-access-after-lock-only",
			"fresh-evaluator-run-and-receipt",
			"separate-run-confirmation",
			"verification-before-publication"
		]),
		detail: "Activation requires a separately reviewed adapter that verifies publisher/source locks, preregistration and layout locks, prevents held-out access before lock, uses a fresh evaluator receipt, and publishes only after verification."
	})
});
Object.freeze({
	status: "unavailable",
	registered: false,
	advertiseToScientist: false,
	executable: false,
	reason: "home-qc-not-registered",
	detail: "Home QC has no v2 method descriptor, route registration, tool, or advertisement because generic confirmation cannot authorize its consume-once physical workflow."
});
var FLOWBLIND_V2_CAPABILITY_REGISTRY = createCapabilityRegistry(Object.freeze([
	REGIONAL_AGREEMENT_V1_ADAPTER,
	VECTOR_TIME_READINESS_V1_ADAPTER,
	HIDDEN_FLOW_V1_DESCRIPTOR,
	SENSOR_PLACEMENT_V1_DESCRIPTOR,
	EXTERNAL_VALIDATION_V1_DESCRIPTOR
]));
//#endregion
//#region tools/catalogResearchV2/resources.ts
var verifiedResourceSnapshots = /* @__PURE__ */ new WeakMap();
var verifiedResourceHandles = /* @__PURE__ */ new WeakSet();
function normalizeSnapshot(snapshot) {
	if (snapshot.role.trim().length === 0 || snapshot.selectionHandle.trim().length === 0 || snapshot.immutableVersionId.trim().length === 0 || snapshot.members.length === 0) throw new Error("Verified resource snapshots require a role, stable selection handle, immutable version, and at least one member.");
	return Object.freeze({
		role: snapshot.role,
		selectionHandle: snapshot.selectionHandle,
		immutableVersionId: snapshot.immutableVersionId,
		members: Object.freeze(snapshot.members.map((member) => Object.freeze({
			role: member.role,
			identity: Object.freeze({ ...member.identity }),
			bytes: Uint8Array.from(member.bytes)
		})))
	});
}
function createRuntimeResourceSnapshotVerifier(verify) {
	return Object.freeze({ verifyAndMint(candidate, request) {
		const verified = verify(candidate);
		if (verified === null) return null;
		const handle = Object.freeze(Object.create(null));
		verifiedResourceSnapshots.set(handle, Object.freeze({
			request,
			snapshot: normalizeSnapshot(verified)
		}));
		verifiedResourceHandles.add(handle);
		return handle;
	} });
}
function resolveRuntimeResourceSnapshot(value, request) {
	if (value === null || typeof value !== "object" || !verifiedResourceHandles.has(value)) return null;
	const verified = verifiedResourceSnapshots.get(value);
	if (verified === void 0 || verified.request !== request) return null;
	const snapshot = verified.snapshot;
	return Object.freeze({
		role: snapshot.role,
		selectionHandle: snapshot.selectionHandle,
		immutableVersionId: snapshot.immutableVersionId,
		members: Object.freeze(snapshot.members.map((member) => Object.freeze({
			role: member.role,
			identity: member.identity,
			bytes: Uint8Array.from(member.bytes)
		})))
	});
}
//#endregion
//#region tools/catalogResearchV2/authority.ts
var RuntimeAuthorityRegistrationError = class extends Error {
	constructor(message) {
		super(message);
		this.name = "RuntimeAuthorityRegistrationError";
	}
};
var trustedIntegrationEvidence = /* @__PURE__ */ new WeakMap();
var trustedIntegrationHandles = /* @__PURE__ */ new WeakSet();
function nonEmpty(value, label) {
	const normalized = value.normalize("NFC").trim();
	if (normalized.length === 0) throw new RuntimeAuthorityRegistrationError(`${label} must be a non-empty string.`);
	return normalized;
}
function normalizeCapability(capability) {
	return Object.freeze({
		...capability,
		capability: Object.freeze({
			familyId: nonEmpty(capability.capability.familyId, "Capability family"),
			methodId: nonEmpty(capability.capability.methodId, "Capability method"),
			methodVersion: nonEmpty(capability.capability.methodVersion, "Capability method version")
		}),
		authorityRequirementId: nonEmpty(capability.authorityRequirementId, "Authority requirement"),
		package: Object.freeze({ ...capability.package }),
		preparationSchema: Object.freeze({ ...capability.preparationSchema }),
		resultSchema: Object.freeze({ ...capability.resultSchema }),
		renderer: Object.freeze({ ...capability.renderer })
	});
}
function normalizeIntegration(integration) {
	const capabilities = integration.capabilities.map(normalizeCapability);
	const keys = capabilities.map((candidate) => capabilityRouteKey(candidate.capability));
	if (new Set(keys).size !== keys.length) throw new RuntimeAuthorityRegistrationError("A trusted integration cannot register duplicate methodId/methodVersion route keys across families.");
	return Object.freeze({
		integrationId: nonEmpty(integration.integrationId, "Integration id"),
		integrationVersion: nonEmpty(integration.integrationVersion, "Integration version"),
		grants: Object.freeze([...new Set(integration.grants.map((grant) => nonEmpty(grant, "Integration grant")))].sort()),
		capabilities: Object.freeze(capabilities)
	});
}
function createRuntimeAuthorityIssuer(verify) {
	return Object.freeze({ issue(candidate) {
		const verified = verify(candidate);
		if (verified === null) return null;
		const evidence = Object.freeze(Object.create(null));
		trustedIntegrationEvidence.set(evidence, normalizeIntegration(verified));
		trustedIntegrationHandles.add(evidence);
		return evidence;
	} });
}
function resolveRuntimeAuthority(evidence, identity) {
	if (evidence === null || typeof evidence !== "object") return null;
	const integration = trustedIntegrationEvidence.get(evidence);
	if (integration === void 0 || !trustedIntegrationHandles.has(evidence)) return null;
	const capability = integration.capabilities.find((candidate) => sameCapabilityIdentity(candidate.capability, identity));
	if (capability === void 0) return null;
	return Object.freeze({
		integrationId: integration.integrationId,
		integrationVersion: integration.integrationVersion,
		grants: integration.grants,
		capability
	});
}
//#endregion
//#region tools/catalogResearchV2/intentPolicy.ts
function contextText(intent) {
	return [
		intent.researchGoal,
		intent.decisionQuestion,
		intent.nextEvidenceIntent
	].filter((value) => value !== null).join("\n").toLowerCase();
}
function assessFlowBlindUniversalIntent(intent) {
	const value = contextText(intent);
	const unsafe = [];
	const incompatible = [];
	if (/\bhttps?:\/\//u.test(value) || /(?:^|\s)(?:[a-z]:[\\/]|\\\\|file:\/\/|\.\.[\\/])/u.test(value)) unsafe.push({
		classification: "unsafe",
		code: "external-or-arbitrary-source-requested",
		detail: "Source selection must remain inside the trusted host attachment boundary."
	});
	if (/\b(?:shell|powershell|bash|command prompt|arbitrary code|arbitrary script)\b/u.test(value)) unsafe.push({
		classification: "unsafe",
		code: "arbitrary-execution-requested",
		detail: "Capability adapters cannot execute arbitrary code or commands."
	});
	if (/\b(?:skip|bypass|fake|combine)\b[^.!?\n]{0,50}\b(?:approval|confirmation)\b/u.test(value) || /\bwithout\b[^.!?\n]{0,40}\b(?:approval|confirmation|asking)\b/u.test(value)) unsafe.push({
		classification: "unsafe",
		code: "confirmation-bypass-requested",
		detail: "Host confirmation cannot be represented or bypassed by scientist input."
	});
	if (/\b(?:3d|three[- ]dimensional)\b/u.test(value)) incompatible.push({
		classification: "universal-incompatibility",
		code: "three-dimensional-source-declared",
		detail: "The registered adapters do not collapse three-dimensional data into a supported method."
	});
	if (/\b(?:sparse|unstructured|scattered)\b[^.!?\n]{0,50}\b(?:grid|field|topology|samples?)\b/u.test(value)) incompatible.push({
		classification: "universal-incompatibility",
		code: "unsupported-topology-declared",
		detail: "Sparse or unstructured topology requires a separately reviewed method."
	});
	if (/\b(?:invent|choose|create|optimize)\b[^.!?\n]{0,45}\b(?:metric|threshold|cutoff)\b/u.test(value)) incompatible.push({
		classification: "universal-incompatibility",
		code: "unreviewed-method-choice-requested",
		detail: "Metrics and thresholds must come from a separately reviewed method contract."
	});
	if (/\bpressure[- ]only\b/u.test(value)) incompatible.push({
		classification: "universal-incompatibility",
		code: "pressure-only-source-declared",
		detail: "Pressure-only data are not silently converted into a registered velocity or agreement method."
	});
	if (/\b(?:temporal derivative|time derivative|material derivative|acceleration|average vorticity|average divergence|cycle[- ]average(?:d)? strain|wall shear over time)\b/u.test(value)) incompatible.push({
		classification: "universal-incompatibility",
		code: "unsupported-temporal-operation-requested",
		detail: "Unsupported temporal derivatives and temporal aggregation require a separately reviewed method."
	});
	if (/\b(?:accepted|rejected|pass\/fail|clinically valid|clinical verdict|scientific verdict|robustness verdict|safe for)\b/u.test(value)) incompatible.push({
		classification: "universal-incompatibility",
		code: "scientific-verdict-requested",
		detail: "The router does not invent a scientific or operational verdict."
	});
	return {
		unsafe: Object.freeze(unsafe),
		incompatible: Object.freeze(incompatible)
	};
}
function isUnregisteredHomeQcIntent(intent) {
	const goal = contextText(intent);
	return /\b(?:home flow|home-flow|phone piv|home piv)\b/u.test(goal) && /\b(?:qc|quality control|readiness|calibration)\b/u.test(goal);
}
//#endregion
//#region tools/catalogResearchV2/integrity.ts
function flowBlindV2Sha256(bytes) {
	return createHash("sha256").update(bytes).digest("hex");
}
function flowBlindV2IdentityMatchesBytes(identity, bytes) {
	return isFlowBlindV2ArtifactIdentity(identity) && identity.byteLength === bytes.byteLength && identity.sha256 === flowBlindV2Sha256(bytes);
}
//#endregion
//#region tools/catalogResearchV2/router.ts
var CapabilityAdapterContractError = class extends Error {
	code;
	constructor(code, message) {
		super(message);
		this.name = "CapabilityAdapterContractError";
		this.code = code;
	}
};
function asRecord$2(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function ownDataValue$1(value, key) {
	const record = asRecord$2(value);
	if (record === null) return void 0;
	try {
		const descriptor = Object.getOwnPropertyDescriptor(record, key);
		return descriptor !== void 0 && "value" in descriptor ? descriptor.value : void 0;
	} catch {
		return;
	}
}
function projectOwnData(value, ancestors = /* @__PURE__ */ new WeakSet(), depth = 0) {
	if (value === null || typeof value === "string" || typeof value === "boolean") return {
		ok: true,
		value
	};
	if (typeof value === "number") return Number.isFinite(value) ? {
		ok: true,
		value
	} : {
		ok: false,
		reason: "non-finite-number"
	};
	if (value === void 0) return {
		ok: true,
		value: void 0
	};
	if (typeof value !== "object") return {
		ok: false,
		reason: "unsupported-value"
	};
	if (depth > 128) return {
		ok: false,
		reason: "excessive-nesting"
	};
	if (ancestors.has(value)) return {
		ok: false,
		reason: "cyclic-value"
	};
	ancestors.add(value);
	try {
		let descriptors;
		try {
			descriptors = Object.getOwnPropertyDescriptors(value);
		} catch {
			return {
				ok: false,
				reason: "proxy-or-descriptor-failure"
			};
		}
		if (Reflect.ownKeys(descriptors).some((key) => typeof key === "symbol")) return {
			ok: false,
			reason: "symbol-property"
		};
		if (Array.isArray(value)) {
			const lengthDescriptor = Reflect.get(descriptors, "length");
			if (lengthDescriptor === void 0 || !("value" in lengthDescriptor) || !Number.isSafeInteger(lengthDescriptor.value) || lengthDescriptor.value < 0) return {
				ok: false,
				reason: "proxy-or-descriptor-failure"
			};
			const result = [];
			for (let index = 0; index < lengthDescriptor.value; index += 1) {
				const descriptor = Reflect.get(descriptors, String(index));
				if (descriptor === void 0 || !("value" in descriptor) || descriptor.enumerable !== true) return {
					ok: false,
					reason: descriptor !== void 0 && !("value" in descriptor) ? "accessor-property" : "non-enumerable-property"
				};
				const projected = projectOwnData(descriptor.value, ancestors, depth + 1);
				if (!projected.ok) return projected;
				result.push(projected.value);
			}
			return {
				ok: true,
				value: Object.freeze(result)
			};
		}
		const result = Object.create(null);
		for (const key of Object.keys(descriptors)) {
			const descriptor = Reflect.get(descriptors, key);
			if (!("value" in descriptor)) return {
				ok: false,
				reason: "accessor-property"
			};
			if (descriptor.enumerable !== true) return {
				ok: false,
				reason: "non-enumerable-property"
			};
			const projected = projectOwnData(descriptor.value, ancestors, depth + 1);
			if (!projected.ok) return projected;
			Object.defineProperty(result, key, {
				value: projected.value,
				enumerable: true,
				configurable: false,
				writable: false
			});
		}
		return {
			ok: true,
			value: Object.freeze(result)
		};
	} finally {
		ancestors.delete(value);
	}
}
var invalidScientistInputSnapshot = Symbol("invalid-scientist-input-snapshot");
function snapshotFlowBlindScientistInput(value) {
	const projected = projectOwnData(value);
	return projected.ok ? projected.value : invalidScientistInputSnapshot;
}
function deepFreezeResult(value, visited = /* @__PURE__ */ new WeakSet(), depth = 0) {
	if (value === null || typeof value !== "object") return value;
	if (depth > 128) throw new CapabilityAdapterContractError("invalid-result-record", "Result-free response exceeds the maximum supported nesting depth.");
	if (visited.has(value)) return value;
	visited.add(value);
	let descriptors;
	try {
		descriptors = Object.getOwnPropertyDescriptors(value);
	} catch {
		throw new CapabilityAdapterContractError("invalid-result-record", "Result-free response properties could not be frozen safely.");
	}
	for (const key of Reflect.ownKeys(descriptors)) {
		const descriptor = Reflect.get(descriptors, key);
		if (!("value" in descriptor)) throw new CapabilityAdapterContractError("invalid-result-record", `Result-free response property ${String(key)} cannot be an accessor.`);
		deepFreezeResult(descriptor.value, visited, depth + 1);
	}
	return Object.isFrozen(value) ? value : Object.freeze(value);
}
function normalizedText$1(value, required) {
	if (value === void 0 && !required) return null;
	if (value === null && !required) return null;
	if (typeof value !== "string") return void 0;
	const normalized = value.normalize("NFC").trim();
	if (normalized.length === 0 || normalized.length > 4096 || [...normalized].some((character) => {
		const codePoint = character.codePointAt(0);
		return codePoint !== void 0 && (codePoint >= 0 && codePoint <= 8 || codePoint === 11 || codePoint === 12 || codePoint >= 14 && codePoint <= 31 || codePoint === 127);
	})) return;
	return normalized;
}
function resultFree$2(outcome) {
	return deepFreezeResult({
		...outcome,
		schemaVersion: 2,
		routerVersion: FLOWBLIND_V2_ROUTER_PACKAGE_VERSION,
		reasonCodes: [...outcome.reasonCodes]
	});
}
function parseScientistRequest(action, value) {
	const projectedRequest = projectOwnData(value);
	const record = projectedRequest.ok ? asRecord$2(projectedRequest.value) : null;
	if (record === null) return {
		ok: false,
		outcome: resultFree$2({
			status: "invalid-scientist-request",
			containsResults: false,
			reasonCodes: [projectedRequest.ok ? "scientist-request-must-be-object" : "scientist-request-must-use-own-data"],
			guidance: "Provide only the scientist-authored research goal and optional human context; preparation also carries one matched metadata object."
		})
	};
	const allowedFields = action === "prepare-study" ? FLOWBLIND_SCIENTIST_PREPARE_FIELDS : FLOWBLIND_SCIENTIST_RUN_FIELDS;
	if (Object.keys(record).filter((key) => !allowedFields.includes(key)).length > 0) return {
		ok: false,
		outcome: resultFree$2({
			status: "invalid-scientist-request",
			containsResults: false,
			reasonCodes: ["technical-or-unknown-scientist-field"],
			guidance: "Remove technical identifiers, attachment details, approval values, and other non-scientist fields."
		})
	};
	const researchGoal = normalizedText$1(ownDataValue$1(record, "researchGoal"), true);
	const decisionQuestion = normalizedText$1(ownDataValue$1(record, "decisionQuestion"), false);
	const nextEvidenceIntent = normalizedText$1(ownDataValue$1(record, "nextEvidenceIntent"), false);
	if (researchGoal === void 0 || researchGoal === null || decisionQuestion === void 0 || nextEvidenceIntent === void 0) return {
		ok: false,
		outcome: resultFree$2({
			status: "invalid-scientist-request",
			containsResults: false,
			reasonCodes: ["invalid-scientist-human-context"],
			guidance: "Use bounded, non-empty scientist-authored text for the research goal and optional human context."
		})
	};
	if (action === "prepare-study" && asRecord$2(ownDataValue$1(record, "metadata")) === null) return {
		ok: false,
		outcome: resultFree$2({
			status: "invalid-scientist-request",
			containsResults: false,
			reasonCodes: ["scientist-metadata-required"],
			guidance: "Preparation requires one metadata object defined by the uniquely matched reviewed capability."
		})
	};
	return {
		ok: true,
		request: deepFreezeResult({
			intent: deepFreezeResult({
				researchGoal,
				decisionQuestion,
				nextEvidenceIntent
			}),
			metadata: action === "prepare-study" ? asRecord$2(ownDataValue$1(record, "metadata")) : null
		})
	};
}
function policyOutcome(assessment) {
	if (assessment.unsafe.length > 0) return resultFree$2({
		status: "unsafe-unsupported",
		containsResults: false,
		reasonCodes: assessment.unsafe.map((finding) => finding.code),
		guidance: "Remove external-source, arbitrary-execution, or confirmation-bypass instructions before routing."
	});
	if (assessment.incompatible.length > 0) return resultFree$2({
		status: "needs-scientific-method",
		containsResults: false,
		reasonCodes: assessment.incompatible.map((finding) => finding.code),
		guidance: "Use a separately reviewed scientific method rather than broadening a registered capability."
	});
	return null;
}
function unsupportedOutcome(findings) {
	return resultFree$2({
		status: findings.length > 0 ? "needs-scientific-method" : "unsupported",
		containsResults: false,
		reasonCodes: findings.length > 0 ? findings.map((finding) => finding.code) : ["no-capability-matched-scientist-goal"],
		guidance: findings.length > 0 ? "Restate the goal within an existing reviewed method or use a separately reviewed method." : "State one supported scientific goal; data shape and technical identifiers cannot select a family."
	});
}
function authorityUnavailable$1(adapter, action, reason) {
	return resultFree$2({
		status: "authority-unavailable",
		containsResults: false,
		capability: adapter.identity,
		route: flowBlindV2Route(adapter.identity, action),
		releaseState: adapter.release.status,
		authorityRequirementId: adapter.authority.requirement.requirementId,
		requiredGrants: adapter.authority.requirement.requiredGrants,
		authority: {
			state: "unavailable",
			reason
		},
		reasonCodes: [reason],
		guidance: adapter.release.status === "candidate-active" ? "Use only runtime-branded evidence from the exact trusted integration; booleans, model text, and editable records are not authority." : adapter.authority.requirement.detail
	});
}
function capabilityIdentityProjection(value) {
	const familyId = ownDataValue$1(value, "familyId");
	const methodId = ownDataValue$1(value, "methodId");
	const methodVersion = ownDataValue$1(value, "methodVersion");
	return typeof familyId === "string" && familyId.length > 0 && typeof methodId === "string" && methodId.length > 0 && typeof methodVersion === "string" && methodVersion.length > 0 ? Object.freeze({
		familyId,
		methodId,
		methodVersion
	}) : null;
}
function packageBindingProjection(value) {
	const packageId = ownDataValue$1(value, "packageId");
	const packageVersion = ownDataValue$1(value, "packageVersion");
	const compatibilityKey = ownDataValue$1(value, "compatibilityKey");
	return typeof packageId === "string" && packageId.length > 0 && typeof packageVersion === "string" && packageVersion.length > 0 && typeof compatibilityKey === "string" && compatibilityKey.length > 0 ? Object.freeze({
		packageId,
		packageVersion,
		compatibilityKey
	}) : null;
}
function schemaBindingProjection(value) {
	const recordKind = ownDataValue$1(value, "recordKind");
	const schemaId = ownDataValue$1(value, "schemaId");
	const schemaVersion = ownDataValue$1(value, "schemaVersion");
	return typeof recordKind === "string" && recordKind.length > 0 && typeof schemaId === "string" && schemaId.length > 0 && typeof schemaVersion === "string" && schemaVersion.length > 0 ? Object.freeze({
		recordKind,
		schemaId,
		schemaVersion
	}) : null;
}
function rendererBindingProjection(value) {
	const rendererId = ownDataValue$1(value, "rendererId");
	const rendererVersion = ownDataValue$1(value, "rendererVersion");
	const resourceReference = ownDataValue$1(value, "resourceReference");
	const resourceUriScheme = ownDataValue$1(value, "resourceUriScheme");
	const resourceMediaType = ownDataValue$1(value, "resourceMediaType");
	return typeof rendererId === "string" && rendererId.length > 0 && typeof rendererVersion === "string" && rendererVersion.length > 0 && typeof resourceReference === "string" && resourceReference.length > 0 && typeof resourceUriScheme === "string" && resourceUriScheme.length > 0 && typeof resourceMediaType === "string" && resourceMediaType.length > 0 ? Object.freeze({
		rendererId,
		rendererVersion,
		resourceReference,
		resourceUriScheme,
		resourceMediaType
	}) : null;
}
function humanContextProjection(value) {
	const researchGoal = ownDataValue$1(value, "researchGoal");
	const decisionQuestion = ownDataValue$1(value, "decisionQuestion");
	const nextEvidenceIntent = ownDataValue$1(value, "nextEvidenceIntent");
	return typeof researchGoal === "string" && (decisionQuestion === null || typeof decisionQuestion === "string") && (nextEvidenceIntent === null || typeof nextEvidenceIntent === "string") ? Object.freeze({
		researchGoal,
		decisionQuestion,
		nextEvidenceIntent
	}) : null;
}
function boundResourceProjection(value) {
	const role = ownDataValue$1(value, "role");
	const selectionHandle = ownDataValue$1(value, "selectionHandle");
	const immutableVersionId = ownDataValue$1(value, "immutableVersionId");
	const members = ownDataValue$1(value, "members");
	if (typeof role !== "string" || role.length === 0 || typeof selectionHandle !== "string" || selectionHandle.length === 0 || typeof immutableVersionId !== "string" || immutableVersionId.length === 0 || !Array.isArray(members)) return null;
	const projectedMembers = members.map((member) => {
		const memberRole = ownDataValue$1(member, "role");
		const identity = artifactIdentityProjection(ownDataValue$1(member, "identity"));
		return typeof memberRole === "string" && memberRole.length > 0 && identity !== null ? Object.freeze({
			role: memberRole,
			identity
		}) : null;
	});
	if (projectedMembers.some((member) => member === null) || new Set(projectedMembers.map((member) => member?.role)).size !== projectedMembers.length) return null;
	return deepFreezeResult({
		role,
		selectionHandle,
		immutableVersionId,
		members: projectedMembers.filter((member) => member !== null)
	});
}
function preparedStudyProjection(value) {
	const capability = capabilityIdentityProjection(ownDataValue$1(value, "capability"));
	const packageBinding = packageBindingProjection(ownDataValue$1(value, "package"));
	const preparationSchema = schemaBindingProjection(ownDataValue$1(value, "preparationSchema"));
	const humanContext = humanContextProjection(ownDataValue$1(value, "humanContext"));
	const preparationMarker = artifactIdentityProjection(ownDataValue$1(value, "preparationMarker"));
	const preparationArtifact = artifactIdentityProjection(ownDataValue$1(value, "preparationArtifact"));
	const resources = ownDataValue$1(value, "resources");
	if (capability === null || packageBinding === null || preparationSchema === null || humanContext === null || preparationMarker === null || preparationArtifact === null || !Array.isArray(resources) || resources.length !== 2) return null;
	const first = boundResourceProjection(resources[0]);
	const second = boundResourceProjection(resources[1]);
	if (first === null || second === null || first.role === second.role) return null;
	return deepFreezeResult({
		capability,
		package: packageBinding,
		preparationSchema,
		humanContext,
		preparationMarker,
		preparationArtifact,
		resources: [first, second]
	});
}
function preparationMismatchReasons(adapter, authority, prepared, humanContext) {
	if (prepared === void 0) return ["prepared-study-binding-required"];
	const reasons = [];
	if (prepared.capability.familyId !== adapter.identity.familyId) reasons.push("prepared-study-family-mismatch");
	if (prepared.capability.methodId !== adapter.identity.methodId) reasons.push("prepared-study-method-mismatch");
	if (prepared.capability.methodVersion !== adapter.identity.methodVersion) reasons.push("prepared-study-version-mismatch");
	if (!adapter.packageCompatibility.accepts(prepared.package, authority.capability.package)) reasons.push("prepared-study-package-incompatible");
	if (!sameSchemaBinding(prepared.preparationSchema, adapter.preparationRecord.binding)) reasons.push("prepared-study-schema-mismatch");
	if (prepared.humanContext.researchGoal !== humanContext.researchGoal || prepared.humanContext.decisionQuestion !== humanContext.decisionQuestion || prepared.humanContext.nextEvidenceIntent !== humanContext.nextEvidenceIntent) reasons.push("prepared-study-human-context-mismatch");
	if (!isFlowBlindV2ArtifactIdentity(prepared.preparationMarker)) reasons.push("prepared-study-marker-invalid");
	if (!isFlowBlindV2ArtifactIdentity(prepared.preparationArtifact)) reasons.push("prepared-study-artifact-invalid");
	const candidate = prepared.resources.filter((resource) => resource.role === "candidate-data");
	const artifactSet = prepared.resources.filter((resource) => resource.role === "prepared-artifact-set");
	if (prepared.resources.length !== 2 || candidate.length !== 1 || artifactSet.length !== 1) reasons.push("prepared-study-resource-binding-invalid");
	else if (!artifactSet[0].members.some((member) => member.role === "preparation-bundle" && sameArtifactIdentity(member.identity, prepared.preparationArtifact))) reasons.push("prepared-study-artifact-resource-mismatch");
	return reasons;
}
function sameResourceBinding(expected, actual) {
	const expectedByRole = new Map(expected.members.map((member) => [member.role, member]));
	const actualByRole = new Map(actual.members.map((member) => [member.role, member]));
	return expected.role === actual.role && expected.selectionHandle === actual.selectionHandle && expected.immutableVersionId === actual.immutableVersionId && expected.members.length === actual.members.length && expectedByRole.size === expected.members.length && actualByRole.size === actual.members.length && expectedByRole.size === actualByRole.size && [...expectedByRole].every(([role, expectedMember]) => {
		const actualMember = actualByRole.get(role);
		return actualMember !== void 0 && sameArtifactIdentity(actualMember.identity, expectedMember.identity);
	});
}
function boundResourceMismatchReasons(prepared, attachments) {
	const reasons = [];
	for (const role of ["candidate-data", "prepared-artifact-set"]) {
		const expected = prepared.resources.find((resource) => resource.role === role);
		const actual = attachments.find((attachment) => attachment.role === role);
		if (expected === void 0 || actual === void 0 || !sameResourceBinding(expected, actual)) reasons.push(role === "candidate-data" ? "prepared-study-candidate-resource-mismatch" : "prepared-study-artifact-set-resource-mismatch");
	}
	return reasons;
}
function boundResourceSha256s(prepared, role) {
	return Object.freeze(prepared.resources.find((resource) => resource.role === role)?.members.map((member) => member.identity.sha256).sort() ?? []);
}
function validateAttachments(request, attachments) {
	const expectedNames = request.roles.map((role) => role.role);
	const reasons = [];
	if (attachments.some((attachment) => !expectedNames.includes(attachment.role))) reasons.push("unexpected-host-attachment-role");
	request.roles.forEach((role) => {
		const selected = attachments.filter((attachment) => attachment.role === role.role);
		if (selected.length !== role.exactCount) reasons.push(`host-attachment-count-${role.role}`);
		selected.forEach((attachment) => {
			const expectedMembers = role.members.map((member) => member.role);
			const actualMembers = attachment.members.map((member) => member.role);
			const membersMatch = actualMembers.length === expectedMembers.length && expectedMembers.every((memberRole) => actualMembers.filter((candidate) => candidate === memberRole).length === 1) && attachment.members.every((member) => {
				const expected = role.members.find((candidate) => candidate.role === member.role);
				return expected !== void 0 && member.identity.reference === expected.portableReference && member.identity.mediaType === expected.mediaType && flowBlindV2IdentityMatchesBytes(member.identity, member.bytes);
			});
			if (attachment.selectionHandle.trim().length === 0 || attachment.immutableVersionId.trim().length === 0 || !membersMatch) reasons.push(`host-attachment-members-${role.role}`);
		});
	});
	return reasons;
}
function preparationRecordViolations(adapter, authority, record, attachments, humanContext) {
	const violations = [];
	const value = asRecord$2(record);
	if (value === null) return ["preparation-record-invalid"];
	if (ownDataValue$1(value, "status") !== "prepared-awaiting-confirmation") violations.push("preparation-status-invalid");
	if (ownDataValue$1(value, "containsResults") !== false) violations.push("preparation-contains-results");
	const capability = capabilityIdentityProjection(ownDataValue$1(value, "capability"));
	if (capability === null || !sameCapabilityIdentity(capability, adapter.identity)) violations.push("preparation-capability-mismatch");
	const packageBinding = packageBindingProjection(ownDataValue$1(value, "package"));
	if (packageBinding === null || !samePackageBinding(packageBinding, authority.capability.package)) violations.push("preparation-package-mismatch");
	const preparationSchema = schemaBindingProjection(ownDataValue$1(value, "preparationSchema"));
	if (preparationSchema === null || !sameSchemaBinding(preparationSchema, adapter.preparationRecord.binding)) violations.push("preparation-schema-mismatch");
	const preparedStudy = preparedStudyProjection(ownDataValue$1(value, "preparedStudy"));
	if (preparedStudy === null || capability === null || packageBinding === null || preparationSchema === null || !sameCapabilityIdentity(preparedStudy.capability, capability) || !samePackageBinding(preparedStudy.package, packageBinding) || !sameSchemaBinding(preparedStudy.preparationSchema, preparationSchema)) violations.push("prepared-study-record-binding-mismatch");
	if (preparedStudy !== null) violations.push(...preparationMismatchReasons(adapter, authority, preparedStudy, humanContext).map((reason) => `prepare-${reason}`));
	const candidateBinding = preparedStudy?.resources.find((resource) => resource.role === "candidate-data");
	const candidateAttachment = attachments.find((attachment) => attachment.role === "candidate-data");
	if (candidateBinding === void 0 || candidateAttachment === void 0 || !sameResourceBinding(candidateBinding, candidateAttachment)) violations.push("preparation-candidate-binding-mismatch");
	const receipt = publicationReceiptProjection(ownDataValue$1(value, "adapterPublication"), "prepare");
	if (receipt !== null && (preparedStudy === null || !sameArtifactIdentity(preparedStudy.preparationMarker, receipt.marker))) violations.push("preparation-marker-publication-mismatch");
	if (receipt !== null && (preparedStudy === null || !receipt.artifacts.some((artifact) => sameArtifactIdentity(artifact, preparedStudy.preparationArtifact)))) violations.push("preparation-artifact-publication-mismatch");
	if (!validAdapterPublication(ownDataValue$1(value, "adapterPublication"), "prepare")) violations.push("preparation-publication-invalid");
	const publication = asRecord$2(ownDataValue$1(value, "publication"));
	if (publication === null || ownDataValue$1(publication, "confirmation") !== "none" || ownDataValue$1(publication, "pointOfNoReturn") !== "exclusive-preparation-commit-marker" || ownDataValue$1(publication, "distributedExactlyOnceClaim") !== false) violations.push("preparation-outer-publication-mismatch");
	return violations;
}
function resultRecordViolations(adapter, authority, record) {
	const violations = [];
	const value = asRecord$2(record);
	if (value === null) return ["result-record-invalid"];
	const expectedResourceUri = committedResultResourceUri(adapter, value);
	if (ownDataValue$1(value, "status") !== "report-complete") violations.push("result-status-invalid");
	if (ownDataValue$1(value, "containsResults") !== true) violations.push("result-contains-results-invalid");
	const capability = capabilityIdentityProjection(ownDataValue$1(value, "capability"));
	if (capability === null || !sameCapabilityIdentity(capability, adapter.identity)) violations.push("result-capability-mismatch");
	const packageBinding = packageBindingProjection(ownDataValue$1(value, "package"));
	if (packageBinding === null || !samePackageBinding(packageBinding, authority.capability.package)) violations.push("result-package-mismatch");
	const resultSchema = schemaBindingProjection(ownDataValue$1(value, "resultSchema"));
	if (resultSchema === null || !sameSchemaBinding(resultSchema, adapter.resultRecord.binding)) violations.push("result-schema-mismatch");
	const renderer = rendererBindingProjection(ownDataValue$1(value, "renderer"));
	if (renderer === null || !sameRendererBinding(renderer, adapter.renderer.binding)) violations.push("result-renderer-mismatch");
	const adapterPublication = ownDataValue$1(value, "adapterPublication");
	if (!validAdapterPublication(adapterPublication, "run")) violations.push("result-publication-invalid");
	if (ownDataValue$1(adapterPublication, "state") === "unpublished") violations.push("run-publication-must-be-committed");
	if (expectedResourceUri === null) violations.push("result-resource-binding-missing");
	const publication = asRecord$2(ownDataValue$1(value, "publication"));
	if (publication === null || ownDataValue$1(publication, "confirmation") !== "host-callback-bracket" || ownDataValue$1(publication, "executionStartBoundary") !== "confirmed-operation-callback-entry" || ownDataValue$1(publication, "pointOfNoReturn") !== "exclusive-report-commit-marker" || ownDataValue$1(publication, "distributedExactlyOnceClaim") !== false || ownDataValue$1(publication, "resourceUri") !== expectedResourceUri) violations.push("result-outer-publication-mismatch");
	return violations;
}
function validAdapterPublication(publication, phase) {
	const value = asRecord$2(publication);
	if (value === null) return false;
	if (ownDataValue$1(value, "state") === "unpublished") {
		if (phase === "run") return false;
		const artifactsValue = ownDataValue$1(value, "artifacts");
		if (ownDataValue$1(value, "owner") !== "router" || !Array.isArray(artifactsValue)) return false;
		const artifacts = artifactsValue.map(asRecord$2);
		if (artifacts.some((artifact) => artifact === null)) return false;
		const normalized = artifacts.filter((artifact) => artifact !== null);
		const roles = normalized.map((artifact) => ownDataValue$1(artifact, "role"));
		const references = normalized.map((artifact) => ownDataValue$1(ownDataValue$1(artifact, "identity"), "reference"));
		return roles.every((role) => typeof role === "string" && role.trim().length > 0) && references.every((reference) => typeof reference === "string") && new Set(roles).size === roles.length && new Set(references).size === references.length && normalized.every((artifact) => {
			const bytes = ownDataValue$1(artifact, "bytes");
			return bytes instanceof Uint8Array && flowBlindV2IdentityMatchesBytes(ownDataValue$1(artifact, "identity"), bytes);
		});
	}
	if (ownDataValue$1(value, "state") !== "committed" || ownDataValue$1(value, "owner") !== "adapter") return false;
	const receipt = asRecord$2(ownDataValue$1(value, "receipt"));
	const artifactsValue = ownDataValue$1(receipt, "artifacts");
	const marker = ownDataValue$1(receipt, "marker");
	if (receipt === null || ownDataValue$1(receipt, "status") !== "committed" || ownDataValue$1(receipt, "phase") !== phase || ownDataValue$1(receipt, "pointOfNoReturn") !== (phase === "prepare" ? "exclusive-preparation-commit-marker" : "exclusive-report-commit-marker") || ownDataValue$1(receipt, "distributedExactlyOnceClaim") !== false || !isFlowBlindV2ArtifactIdentity(marker) || !Array.isArray(artifactsValue) || !artifactsValue.every(isFlowBlindV2ArtifactIdentity)) return false;
	const references = [ownDataValue$1(marker, "reference"), ...artifactsValue.map((artifact) => ownDataValue$1(artifact, "reference"))];
	return references.every((reference) => typeof reference === "string") && new Set(references).size === references.length;
}
function committedResultResourceUri(adapter, record) {
	const adapterPublication = ownDataValue$1(record, "adapterPublication");
	if (!validAdapterPublication(adapterPublication, "run")) return null;
	const receipt = asRecord$2(ownDataValue$1(asRecord$2(adapterPublication), "receipt"));
	const artifactsValue = ownDataValue$1(receipt, "artifacts");
	const marker = ownDataValue$1(receipt, "marker");
	if (receipt === null || !Array.isArray(artifactsValue) || !isFlowBlindV2ArtifactIdentity(marker)) return null;
	const resources = artifactsValue.filter((artifact) => isFlowBlindV2ArtifactIdentity(artifact) && artifact.reference === adapter.renderer.binding.resourceReference && artifact.mediaType === adapter.renderer.binding.resourceMediaType);
	if (resources.length !== 1) return null;
	return `${adapter.renderer.binding.resourceUriScheme}://sha256/${resources[0].sha256}?verification=${ownDataValue$1(marker, "sha256")}`;
}
function artifactIdentityProjection(identity) {
	if (!isFlowBlindV2ArtifactIdentity(identity)) return null;
	return Object.freeze({
		reference: ownDataValue$1(identity, "reference"),
		byteLength: ownDataValue$1(identity, "byteLength"),
		sha256: ownDataValue$1(identity, "sha256"),
		mediaType: ownDataValue$1(identity, "mediaType")
	});
}
function publicationReceiptProjection(publication, phase) {
	const value = asRecord$2(publication);
	const receipt = asRecord$2(ownDataValue$1(value, "receipt"));
	const marker = ownDataValue$1(receipt, "marker");
	if (ownDataValue$1(value, "state") !== "committed" || receipt === null || !isFlowBlindV2ArtifactIdentity(marker)) return null;
	const artifactsValue = ownDataValue$1(receipt, "artifacts");
	const artifacts = Array.isArray(artifactsValue) ? artifactsValue.filter(isFlowBlindV2ArtifactIdentity) : [];
	const markerProjection = artifactIdentityProjection(marker);
	if (markerProjection === null) return null;
	return Object.freeze({
		status: "committed",
		phase,
		marker: markerProjection,
		artifacts: Object.freeze(artifacts.map(artifactIdentityProjection).filter((identity) => identity !== null)),
		pointOfNoReturn: phase === "prepare" ? "exclusive-preparation-commit-marker" : "exclusive-report-commit-marker",
		distributedExactlyOnceClaim: false
	});
}
function invalidRecordOutcome(adapter, phase, record, violations) {
	const receipt = publicationReceiptProjection(ownDataValue$1(record, "adapterPublication"), phase);
	if (receipt !== null) return resultFree$2({
		status: "prior-outcome-unknown",
		containsResults: false,
		capability: adapter.identity,
		reasonCodes: [`post-ponr-${phase}-binding-violation`, ...violations],
		guidance: "A committed publication marker exists, so revalidate and reconcile that exact receipt before returning success or attempting any retry. Do not invoke the adapter automatically.",
		reconciliation: {
			state: "committed-record-revalidation-required",
			phase,
			receipt,
			marker: receipt.marker
		}
	});
	throw new CapabilityAdapterContractError(phase === "prepare" ? "invalid-preparation-record" : "invalid-result-record", `Trusted integration returned an invalid pre-publication ${phase} record: ${violations.join(", ")}.`);
}
async function routeFlowBlindCapability(registry, request) {
	if (!isFlowBlindV2Action(request.action)) return resultFree$2({
		status: "unsupported-action",
		containsResults: false,
		reasonCodes: ["unsupported-public-lifecycle-action"],
		guidance: "Use exactly prepare-study or run-and-verify-study."
	});
	const action = request.action;
	const parsed = parseScientistRequest(action, request.scientist);
	if (!parsed.ok) return parsed.outcome;
	const universal = policyOutcome(assessFlowBlindUniversalIntent(parsed.request.intent));
	if (universal !== null) return universal;
	if (isUnregisteredHomeQcIntent(parsed.request.intent)) return resultFree$2({
		status: "unsupported",
		containsResults: false,
		reasonCodes: ["home-qc-not-registered"],
		guidance: "Home QC has no registered v2 method descriptor, route, tool, or authority contract."
	});
	const matches = registry.descriptors.filter((adapter) => adapter.matchScientistIntent(parsed.request.intent));
	if (matches.length > 1) return resultFree$2({
		status: "ambiguous",
		containsResults: false,
		reasonCodes: ["multiple-capability-families-matched"],
		guidance: "Restate one scientific goal without capability IDs or data-shape hints."
	});
	if (matches.length === 0) return unsupportedOutcome(registry.descriptors.flatMap((adapter) => adapter.unsupportedIntentPolicy(parsed.request.intent)));
	const adapter = matches[0];
	const familyUnsupported = adapter.unsupportedIntentPolicy(parsed.request.intent);
	if (familyUnsupported.length > 0) return unsupportedOutcome(familyUnsupported);
	if (!isActiveCapabilityAdapter(adapter)) return authorityUnavailable$1(adapter, action, "disabled-by-release-policy");
	const authority = resolveRuntimeAuthority(request.host.authorityEvidence, adapter.identity);
	if (authority === null || !adapter.authority.predicate(authority)) return authorityUnavailable$1(adapter, action, request.host.authorityEvidence === null || request.host.authorityEvidence === void 0 ? "package-not-installed" : "package-verification-failed");
	if (action === "prepare-study" && !adapter.scientistMetadata.descriptor.validate(parsed.request.metadata)) return resultFree$2({
		status: "scientist-metadata-invalid",
		containsResults: false,
		capability: adapter.identity,
		reasonCodes: ["matched-capability-scientist-metadata-invalid"],
		guidance: "Provide only the scientist-level metadata named by the matched capability schema."
	});
	let preparedStudy;
	let confirmedExecution;
	let settleConfirmedExecution;
	if (action === "run-and-verify-study") {
		const rawPreparedStudy = request.host.preparedStudy;
		preparedStudy = preparedStudyProjection(rawPreparedStudy) ?? void 0;
		const confirmationAuthority = request.host.confirmedExecution;
		settleConfirmedExecution = request.host.settleConfirmedExecution;
		const mismatch = rawPreparedStudy === null || rawPreparedStudy === void 0 ? ["prepared-study-binding-required"] : preparedStudy === void 0 ? ["prepared-study-binding-invalid"] : preparationMismatchReasons(adapter, authority, preparedStudy, parsed.request.intent);
		if (mismatch.length > 0) return resultFree$2({
			status: "preparation-incompatible",
			containsResults: false,
			capability: adapter.identity,
			reasonCodes: mismatch,
			guidance: "Run only the exact family, method version, schema, and package binding established during preparation."
		});
		if (!isRuntimeConfirmedExecutionAuthority(confirmationAuthority) || typeof settleConfirmedExecution !== "function") return authorityUnavailable$1(adapter, action, "host-confirmation-authority-unavailable");
		confirmedExecution = confirmationAuthority;
	}
	const attachmentRequest = Object.freeze({
		action,
		capability: adapter.identity,
		roles: action === "prepare-study" ? adapter.attachments.prepare : adapter.attachments.run
	});
	const selectedSnapshots = await request.host.loadAttachments(attachmentRequest);
	const resolvedAttachments = [];
	for (const selected of selectedSnapshots) {
		const resolved = resolveRuntimeResourceSnapshot(selected, attachmentRequest);
		if (resolved === null) return resultFree$2({
			status: "attachment-contract-invalid",
			containsResults: false,
			capability: adapter.identity,
			reasonCodes: ["unverified-or-forged-resource-snapshot"],
			guidance: "Attachment selections must be runtime-branded immutable snapshots minted by the trusted resource verifier."
		});
		resolvedAttachments.push(resolved);
	}
	const verifiedAttachments = Object.freeze([...resolvedAttachments]);
	const attachmentReasons = validateAttachments(attachmentRequest, verifiedAttachments);
	if (attachmentReasons.length > 0) return resultFree$2({
		status: "attachment-contract-invalid",
		containsResults: false,
		capability: adapter.identity,
		reasonCodes: attachmentReasons,
		guidance: "The trusted host must supply exactly the adapter-owned read-only attachment roles."
	});
	if (action === "run-and-verify-study" && preparedStudy !== void 0) {
		const resourceMismatch = boundResourceMismatchReasons(preparedStudy, verifiedAttachments);
		if (resourceMismatch.length > 0) return resultFree$2({
			status: "preparation-incompatible",
			containsResults: false,
			capability: adapter.identity,
			reasonCodes: resourceMismatch,
			guidance: "Run requires the exact candidate and prepared artifact-set identities bound by this preparation instance."
		});
	}
	if (action === "prepare-study") {
		const record = await adapter.lifecycle.prepare({
			authority,
			scientist: parsed.request,
			attachments: verifiedAttachments,
			...request.host.signal === void 0 ? {} : { signal: request.host.signal }
		});
		const violations = preparationRecordViolations(adapter, authority, record, verifiedAttachments, parsed.request.intent);
		if (violations.length > 0) return invalidRecordOutcome(adapter, "prepare", record, violations);
		return record;
	}
	if (preparedStudy === void 0 || confirmedExecution === void 0 || settleConfirmedExecution === void 0) throw new CapabilityAdapterContractError("invalid-result-record", "Run dispatch reached execution without its validated preparation and confirmation authorities.");
	const confirmationRequest = Object.freeze({
		recordType: "flowblind-catalog-v2-run-confirmation-request-v1",
		route: flowBlindV2Route(adapter.identity, "run-and-verify-study"),
		routerPackageVersion: FLOWBLIND_V2_ROUTER_PACKAGE_VERSION,
		familyPackageCompatibilityKey: authority.capability.package.compatibilityKey,
		preparationSchemaId: preparedStudy.preparationSchema.schemaId,
		preparationMarkerSha256: preparedStudy.preparationMarker.sha256,
		preparationArtifactSha256: preparedStudy.preparationArtifact.sha256,
		candidateResourceSha256s: boundResourceSha256s(preparedStudy, "candidate-data"),
		preparedArtifactSetSha256s: boundResourceSha256s(preparedStudy, "prepared-artifact-set"),
		executionStartBoundary: "confirmed-operation-callback-entry",
		distributedExactlyOnceClaim: false
	});
	let callbackRecord;
	let confirmed;
	let confirmationFailure;
	let terminalOutcome = { status: "failed" };
	try {
		confirmed = await confirmedExecution.withConfirmedExecution(confirmationRequest, async (confirmedExecution) => {
			if (!isRuntimeConfirmedExecutionHandle(confirmedExecution, confirmationRequest)) throw new CapabilityAdapterContractError("invalid-result-record", "Run confirmation callback supplied an untrusted execution handle.");
			const record = await adapter.lifecycle.run({
				authority,
				scientist: parsed.request,
				preparedStudy,
				attachments: verifiedAttachments,
				confirmedExecution,
				...request.host.signal === void 0 ? {} : { signal: request.host.signal }
			});
			callbackRecord = record;
			return record;
		}, request.host.signal);
		terminalOutcome = confirmed.status === "completed" ? { status: "completed" } : confirmed.status === "cancelled" ? { status: "cancelled" } : confirmed.status === "busy" ? {
			status: "busy",
			scope: confirmed.scope
		} : { status: "prior-outcome-unknown" };
	} catch (error) {
		confirmationFailure = error;
	}
	let settlementFailure;
	try {
		await settleConfirmedExecution(confirmationRequest, terminalOutcome);
	} catch (error) {
		settlementFailure = error;
	}
	if (confirmationFailure !== void 0 && settlementFailure !== void 0) throw new AggregateError([confirmationFailure, settlementFailure], "Confirmed execution and host settlement both failed.");
	if (confirmationFailure !== void 0) throw confirmationFailure;
	if (settlementFailure !== void 0) throw settlementFailure;
	if (confirmed === void 0) throw new CapabilityAdapterContractError("invalid-result-record", "Confirmed execution produced no terminal outcome.");
	if (confirmed.status === "cancelled") return resultFree$2({
		status: "confirmation-required",
		containsResults: false,
		capability: adapter.identity,
		reasonCodes: ["run-confirmation-cancelled"],
		guidance: "A later retry must request the host callback-bracket confirmation again."
	});
	if (confirmed.status === "busy") return resultFree$2({
		status: "execution-busy",
		containsResults: false,
		capability: adapter.identity,
		scope: confirmed.scope,
		reasonCodes: [`confirmed-execution-busy-${confirmed.scope}`],
		guidance: "Do not start a second adapter invocation while the exact execution or package capacity is busy."
	});
	if (confirmed.status === "prior-outcome-unknown") return resultFree$2({
		status: "prior-outcome-unknown",
		containsResults: false,
		capability: adapter.identity,
		reasonCodes: ["confirmed-execution-prior-outcome-unknown"],
		guidance: "Reconcile the prior execution marker and publication state; never invoke the adapter again automatically.",
		reconciliation: {
			state: "execution-outcome-reconciliation-required",
			phase: "run"
		}
	});
	const record = confirmed.result;
	if (callbackRecord === void 0 || record !== callbackRecord) {
		if (callbackRecord !== void 0) return invalidRecordOutcome(adapter, "run", callbackRecord, ["confirmed-result-identity-mismatch"]);
		throw new CapabilityAdapterContractError("invalid-result-record", "Confirmed execution returned a result that was not captured from the branded callback.");
	}
	const violations = resultRecordViolations(adapter, authority, record);
	if (violations.length > 0) return invalidRecordOutcome(adapter, "run", record, violations);
	return record;
}
//#endregion
//#region tools/catalogResearchV2/package/portableIo.ts
var PortablePackageIoError = class extends Error {
	code;
	constructor(code, message, options = {}) {
		super(message, options);
		this.name = "PortablePackageIoError";
		this.code = code;
	}
};
function throwIfAborted(signal, message) {
	if (signal?.aborted !== true) return;
	if (message !== void 0) throw new Error(message, { cause: signal.reason });
	signal.throwIfAborted();
}
function sha256Bytes(bytes, signal) {
	throwIfAborted(signal);
	return createHash("sha256").update(bytes).digest("hex");
}
function stableValue(value) {
	if (Array.isArray(value)) return value.map(stableValue);
	if (value !== null && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableValue(value[key])]));
	if (value === null || typeof value === "string" || typeof value === "boolean") return value;
	if (typeof value === "number" && Number.isFinite(value)) return value;
	throw new PortablePackageIoError("package-attestation-failed", "Canonical package JSON may contain only finite JSON values.");
}
function stableJson$1(value) {
	return `${JSON.stringify(stableValue(value), null, 2)}\n`;
}
function stableCompactJson(value) {
	return JSON.stringify(stableValue(value));
}
function canonicalJsonBytes$1(value) {
	return Buffer.from(stableJson$1(value), "utf8");
}
function canonicalCompactJsonBytes(value) {
	return Buffer.from(stableCompactJson(value), "utf8");
}
function parseCanonicalJson(bytes, label, format = "pretty-lf", signal) {
	throwIfAborted(signal);
	let text;
	try {
		text = new TextDecoder("utf-8", {
			fatal: true,
			ignoreBOM: true
		}).decode(bytes);
	} catch (error) {
		throw new PortablePackageIoError("attachment-invalid", `${label} must be strict UTF-8.`, { cause: error });
	}
	if (bytes.byteLength >= 3 && bytes[0] === 239 && bytes[1] === 187 && bytes[2] === 191) throw new PortablePackageIoError("attachment-invalid", `${label} must not contain a byte-order mark.`);
	let parsed;
	try {
		throwIfAborted(signal);
		parsed = JSON.parse(text);
	} catch (error) {
		throw new PortablePackageIoError("attachment-invalid", `${label} must contain valid JSON.`, { cause: error });
	}
	if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed) || (format === "pretty-lf" ? stableJson$1(parsed) !== text : format === "compact" ? stableCompactJson(parsed) !== text : stableJson$1(parsed) !== text && stableCompactJson(parsed) !== text)) throw new PortablePackageIoError("attachment-invalid", `${label} must be one canonical stable-JSON object.`);
	return parsed;
}
function artifactIdentity$1(reference, mediaType, bytes, signal) {
	throwIfAborted(signal);
	assertSafeReference(reference, "Artifact reference");
	if (bytes.byteLength <= 0) throw new PortablePackageIoError("package-attestation-failed", "Artifact bytes must not be empty.");
	return Object.freeze({
		reference,
		byteLength: bytes.byteLength,
		sha256: sha256Bytes(bytes, signal),
		mediaType
	});
}
function mappedArtifactIdentity(identity, reference) {
	assertSafeReference(reference, "Mapped artifact reference");
	return Object.freeze({
		reference,
		byteLength: identity.byteLength,
		sha256: identity.sha256,
		mediaType: identity.mediaType
	});
}
function assertSafeReference(reference, label) {
	if (reference.length === 0 || reference.length > 512 || reference !== reference.normalize("NFC") || reference.startsWith("/") || reference.includes("\\") || reference.includes("\0") || /^[A-Za-z]:/u.test(reference)) throw new PortablePackageIoError("package-attestation-failed", `${label} is not a portable relative path.`);
	if (reference.split("/").some((part) => part.length === 0 || part === "." || part === "..")) throw new PortablePackageIoError("package-attestation-failed", `${label} contains an unsafe path segment.`);
}
function isSamePath(left, right) {
	return process.platform === "win32" ? resolve(left).toLowerCase() === resolve(right).toLowerCase() : resolve(left) === resolve(right);
}
async function ensureOrdinaryDirectory(path, signal, code = "attachment-invalid") {
	const absolute = resolve(path);
	const root = parse(absolute).root;
	let current = root;
	for (const part of relative(root, absolute).split(sep).filter((entry) => entry.length > 0)) {
		throwIfAborted(signal);
		current = resolve(current, part);
		const metadata = await lstat(current);
		throwIfAborted(signal);
		if (metadata.isSymbolicLink() || !metadata.isDirectory()) throw new PortablePackageIoError(code, "A package path contains a linked, aliased, or non-ordinary directory component.");
	}
	throwIfAborted(signal);
	return realpath(absolute);
}
function missingPath(error) {
	return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}
async function ensureOutputDirectory(canonicalRoot, target, allowCreate, signal) {
	throwIfAborted(signal);
	const child = relative(canonicalRoot, target);
	if (child === ".." || child.startsWith(`..${sep}`) || isAbsolute(child)) throw new PortablePackageIoError("output-conflict", "An output directory escaped its canonical root.");
	let current = canonicalRoot;
	for (const part of child.split(sep).filter((entry) => entry.length > 0)) {
		throwIfAborted(signal);
		await ensureOrdinaryDirectory(current, signal, "output-conflict");
		throwIfAborted(signal);
		const next = resolve(current, part);
		try {
			await ensureOrdinaryDirectory(next, signal, "output-conflict");
			throwIfAborted(signal);
		} catch (error) {
			throwIfAborted(signal);
			if (!allowCreate || !missingPath(error)) throw error;
			await ensureOrdinaryDirectory(current, signal, "output-conflict");
			throwIfAborted(signal);
			try {
				await mkdir(next);
				throwIfAborted(signal);
			} catch (mkdirError) {
				throwIfAborted(signal);
				if (typeof mkdirError !== "object" || mkdirError === null || !("code" in mkdirError) || mkdirError.code !== "EEXIST") throw mkdirError;
			}
			await ensureOrdinaryDirectory(next, signal, "output-conflict");
			throwIfAborted(signal);
		}
		current = next;
	}
	const canonical = await ensureOrdinaryDirectory(current, signal, "output-conflict");
	throwIfAborted(signal);
	return canonical;
}
function confinedPath(root, reference) {
	assertSafeReference(reference, "Package reference");
	const path = resolve(root, reference);
	const child = relative(root, path);
	if (child.length === 0 || child === ".." || child.startsWith(`..${sep}`) || isAbsolute(child)) throw new PortablePackageIoError("attachment-invalid", "A package reference escaped its trusted root.");
	return path;
}
async function readHandle(handle, maximumBytes, signal) {
	const chunks = [];
	let total = 0;
	while (true) {
		throwIfAborted(signal);
		const chunk = Buffer.allocUnsafe(65536);
		const { bytesRead } = await handle.read(chunk, 0, chunk.byteLength, null);
		throwIfAborted(signal);
		if (bytesRead === 0) break;
		total += bytesRead;
		if (total > maximumBytes) throw new PortablePackageIoError("attachment-invalid", "A selected file exceeds its reviewed byte limit.");
		chunks.push(chunk.subarray(0, bytesRead));
	}
	return Buffer.concat(chunks, total);
}
async function readStableFile(rootInput, reference, maximumBytes, expected, signal) {
	throwIfAborted(signal);
	const root = await ensureOrdinaryDirectory(resolve(rootInput), signal);
	throwIfAborted(signal);
	const path = confinedPath(root, reference);
	throwIfAborted(signal);
	const canonicalParent = await ensureOrdinaryDirectory(dirname(path), signal);
	throwIfAborted(signal);
	const metadata = await lstat(path, { bigint: true });
	throwIfAborted(signal);
	const canonical = await realpath(path);
	throwIfAborted(signal);
	if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.nlink !== 1n || metadata.size <= 0n || metadata.size > BigInt(maximumBytes) || !isSamePath(dirname(canonical), canonicalParent)) throw new PortablePackageIoError("attachment-invalid", "Selected attachments must be bounded, single-link ordinary files without aliases.");
	if (expected !== void 0 && metadata.size !== BigInt(expected.byteLength)) throw new PortablePackageIoError("attachment-invalid", "A selected attachment has the wrong byte length.");
	throwIfAborted(signal);
	const handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	throwIfAborted(signal);
	try {
		throwIfAborted(signal);
		const before = await handle.stat({ bigint: true });
		throwIfAborted(signal);
		const bytes = await readHandle(handle, maximumBytes, signal);
		throwIfAborted(signal);
		const after = await handle.stat({ bigint: true });
		throwIfAborted(signal);
		const final = await lstat(path, { bigint: true });
		throwIfAborted(signal);
		const digest = sha256Bytes(bytes, signal);
		if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs || after.dev !== final.dev || after.ino !== final.ino || final.nlink !== 1n || final.isSymbolicLink() || bytes.byteLength !== Number(before.size) || expected !== void 0 && digest !== expected.sha256) throw new PortablePackageIoError("attachment-invalid", "A selected attachment changed or failed identity verification while being read.");
		return Object.freeze({
			reference: reference.replaceAll("\\", "/"),
			path,
			bytes: Uint8Array.from(bytes),
			byteLength: bytes.byteLength,
			sha256: digest
		});
	} finally {
		await handle.close();
		throwIfAborted(signal);
	}
}
async function listOrdinaryFileReferences(rootInput, limits, signal) {
	throwIfAborted(signal);
	const root = await ensureOrdinaryDirectory(resolve(rootInput), signal);
	throwIfAborted(signal);
	const references = [];
	const folded = /* @__PURE__ */ new Set();
	const maximumEntries = limits.maximumEntries ?? limits.maximumFiles * 2 + limits.maximumDepth + 1;
	let entryCount = 0;
	async function walk(current, depth) {
		throwIfAborted(signal);
		if (depth > limits.maximumDepth) throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree exceeds its reviewed depth.");
		throwIfAborted(signal);
		const directory = await opendir(current);
		throwIfAborted(signal);
		for await (const entry of directory) {
			throwIfAborted(signal);
			entryCount += 1;
			if (entryCount > maximumEntries) throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree contains too many entries.");
			const path = resolve(current, entry.name);
			const reference = relative(root, path).replaceAll("\\", "/");
			assertSafeReference(reference, "Selected attachment reference");
			const foldedReference = reference.normalize("NFC").toLowerCase();
			if (folded.has(foldedReference)) throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree contains a case-aliased path.");
			folded.add(foldedReference);
			if (entry.isSymbolicLink()) throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree contains a symbolic link.");
			if (entry.isDirectory()) {
				await walk(path, depth + 1);
				throwIfAborted(signal);
			} else if (entry.isFile()) {
				const metadata = await lstat(path, { bigint: true });
				throwIfAborted(signal);
				if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.nlink !== 1n) throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree contains a linked or non-ordinary file.");
				references.push({
					reference,
					byteLength: Number(metadata.size)
				});
				if (references.length > limits.maximumFiles) throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree contains too many files.");
			} else throw new PortablePackageIoError("attachment-invalid", "The selected attachment tree contains a non-file entry.");
		}
	}
	await walk(root, 0);
	throwIfAborted(signal);
	return Object.freeze(references.sort((left, right) => left.reference < right.reference ? -1 : left.reference > right.reference ? 1 : 0));
}
async function listOrdinaryFiles(rootInput, limits, signal) {
	const references = await listOrdinaryFileReferences(rootInput, limits, signal);
	throwIfAborted(signal);
	const snapshots = [];
	for (const entry of references) {
		throwIfAborted(signal);
		snapshots.push(await readStableFile(rootInput, entry.reference, limits.maximumBytesEach, void 0, signal));
		throwIfAborted(signal);
	}
	return Object.freeze(snapshots);
}
async function inspectOrdinaryDirectory(rootInput, reference, signal) {
	throwIfAborted(signal);
	const root = await ensureOrdinaryDirectory(resolve(rootInput), signal);
	throwIfAborted(signal);
	const path = confinedPath(root, reference);
	try {
		await ensureOutputDirectory(root, path, false, signal);
		throwIfAborted(signal);
		return "present";
	} catch (error) {
		throwIfAborted(signal);
		if (missingPath(error)) return "absent";
		throw error;
	}
}
async function syncDirectory(root, path, signal) {
	throwIfAborted(signal);
	await ensureOutputDirectory(root, path, false, signal);
	throwIfAborted(signal);
	if (process.platform === "win32") return;
	const handle = await open(path, constants.O_RDONLY);
	throwIfAborted(signal);
	try {
		throwIfAborted(signal);
		await handle.sync();
		throwIfAborted(signal);
	} finally {
		await handle.close();
		throwIfAborted(signal);
	}
}
async function exists(path, signal) {
	throwIfAborted(signal);
	try {
		await lstat(path);
		throwIfAborted(signal);
		return true;
	} catch (error) {
		throwIfAborted(signal);
		if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") return false;
		throw error;
	}
}
async function removeStagingFile(root, path, directory, signal, finalPath) {
	throwIfAborted(signal);
	try {
		throwIfAborted(signal);
		const metadata = await lstat(path, { bigint: true });
		throwIfAborted(signal);
		if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.nlink !== 1n) throw new PortablePackageIoError("output-conflict", "A deterministic staging path is not a single-link ordinary file.");
		await ensureOutputDirectory(root, directory, false, signal);
		throwIfAborted(signal);
		if (finalPath !== void 0 && await exists(finalPath, signal)) throw new PortablePackageIoError("output-conflict", "A deterministic stage cannot be removed while a final artifact exists.");
		throwIfAborted(signal);
		await unlink(path);
		throwIfAborted(signal);
		await syncDirectory(root, directory, signal);
		throwIfAborted(signal);
	} catch (error) {
		throwIfAborted(signal);
		if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") return;
		throw error;
	}
}
async function readLinkedFile(path, expectedByteLength, expectedSha256, signal) {
	throwIfAborted(signal);
	const metadata = await lstat(path, { bigint: true });
	throwIfAborted(signal);
	const canonicalParent = await ensureOrdinaryDirectory(dirname(path), signal, "output-conflict");
	throwIfAborted(signal);
	const canonical = await realpath(path);
	throwIfAborted(signal);
	if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.nlink !== 2n || metadata.size !== BigInt(expectedByteLength) || !isSamePath(dirname(canonical), canonicalParent)) throw new PortablePackageIoError("output-conflict", "A crash-recovery file is not one expected two-link ordinary file.");
	throwIfAborted(signal);
	const handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	throwIfAborted(signal);
	try {
		const before = await handle.stat({ bigint: true });
		throwIfAborted(signal);
		const bytes = await readHandle(handle, expectedByteLength, signal);
		throwIfAborted(signal);
		const after = await handle.stat({ bigint: true });
		throwIfAborted(signal);
		const final = await lstat(path, { bigint: true });
		throwIfAborted(signal);
		const digest = sha256Bytes(bytes, signal);
		if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs || after.dev !== final.dev || after.ino !== final.ino || after.nlink !== 2n || final.nlink !== 2n || final.isSymbolicLink() || bytes.byteLength !== expectedByteLength || digest !== expectedSha256) throw new PortablePackageIoError("output-conflict", "A crash-recovery hardlink changed or failed byte verification.");
		return Object.freeze({
			dev: after.dev,
			ino: after.ino,
			bytes
		});
	} finally {
		await handle.close();
		throwIfAborted(signal);
	}
}
async function reconcileLinkedStage(root, finalReference, stageReference, identity, signal) {
	throwIfAborted(signal);
	const finalPath = confinedPath(root, finalReference);
	const stagePath = confinedPath(root, stageReference);
	const parent = dirname(finalPath);
	if (dirname(stagePath) !== parent) throw new PortablePackageIoError("output-conflict", "The deterministic stage and final artifact do not share an expected parent.");
	await ensureOutputDirectory(root, parent, false, signal);
	throwIfAborted(signal);
	const final = await readLinkedFile(finalPath, identity.byteLength, identity.sha256, signal);
	throwIfAborted(signal);
	const stage = await readLinkedFile(stagePath, identity.byteLength, identity.sha256, signal);
	throwIfAborted(signal);
	if (final.dev !== stage.dev || final.ino !== stage.ino || !final.bytes.equals(stage.bytes)) throw new PortablePackageIoError("output-conflict", "The deterministic stage and final artifact are different files.");
	await ensureOutputDirectory(root, parent, false, signal);
	throwIfAborted(signal);
	const finalMetadata = await lstat(finalPath, { bigint: true });
	throwIfAborted(signal);
	const stageMetadata = await lstat(stagePath, { bigint: true });
	throwIfAborted(signal);
	if (finalMetadata.dev !== stageMetadata.dev || finalMetadata.ino !== stageMetadata.ino || finalMetadata.nlink !== 2n || stageMetadata.nlink !== 2n) throw new PortablePackageIoError("output-conflict", "The deterministic stage and final hardlink relationship changed before reconciliation.");
	throwIfAborted(signal);
	await unlink(stagePath);
	throwIfAborted(signal);
	await syncDirectory(root, parent, signal);
	throwIfAborted(signal);
	await readStableFile(root, finalReference, identity.byteLength, identity, signal);
	throwIfAborted(signal);
	return identity;
}
async function readOrReconcileDeterministicFile(rootInput, reference, maximumBytes, mediaType, signal) {
	throwIfAborted(signal);
	const root = await ensureOrdinaryDirectory(resolve(rootInput), signal, "output-conflict");
	const finalPath = confinedPath(root, reference);
	const stageReference = [dirname(reference), `.flowblind-stage-${basename(reference)}.part`].filter((part) => part !== ".").join("/");
	const stagePath = confinedPath(root, stageReference);
	const finalExists = await exists(finalPath, signal);
	const stageExists = await exists(stagePath, signal);
	if (!finalExists) return null;
	if (!stageExists) return readStableFile(root, reference, maximumBytes, void 0, signal);
	return readAndReconcileLinkedStage(root, reference, stageReference, maximumBytes, mediaType, signal);
}
async function readAndReconcileLinkedStage(root, reference, stageReference, maximumBytes, mediaType, signal) {
	throwIfAborted(signal);
	const finalPath = confinedPath(root, reference);
	const parent = dirname(finalPath);
	const stagePath = confinedPath(root, stageReference);
	await ensureOutputDirectory(root, parent, false, signal);
	const [finalMetadata, stageMetadata] = await Promise.all([lstat(finalPath, { bigint: true }), lstat(stagePath, { bigint: true })]);
	throwIfAborted(signal);
	if (finalMetadata.isSymbolicLink() || stageMetadata.isSymbolicLink() || !finalMetadata.isFile() || !stageMetadata.isFile() || finalMetadata.dev !== stageMetadata.dev || finalMetadata.ino !== stageMetadata.ino || finalMetadata.nlink !== 2n || stageMetadata.nlink !== 2n || finalMetadata.size <= 0n || finalMetadata.size > BigInt(maximumBytes)) throw new PortablePackageIoError("output-conflict", "A deterministic committed file and its staging entry cannot be reconciled safely.");
	const handle = await open(finalPath, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	let bytes;
	try {
		const before = await handle.stat({ bigint: true });
		throwIfAborted(signal);
		bytes = await readHandle(handle, maximumBytes, signal);
		throwIfAborted(signal);
		const after = await handle.stat({ bigint: true });
		if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs || bytes.byteLength !== Number(before.size)) throw new PortablePackageIoError("output-conflict", "A deterministic committed file changed while its staging entry was inspected.");
	} finally {
		await handle.close();
	}
	const identity = artifactIdentity$1(reference, mediaType, bytes, signal);
	await reconcileLinkedStage(root, reference, stageReference, identity, signal);
	return Object.freeze({
		reference,
		path: finalPath,
		bytes: Uint8Array.from(bytes),
		byteLength: bytes.byteLength,
		sha256: identity.sha256
	});
}
async function readOrReconcileRetainedStagedFile(rootInput, reference, maximumBytes, mediaType, signal) {
	throwIfAborted(signal);
	const root = await ensureOrdinaryDirectory(resolve(rootInput), signal, "output-conflict");
	const finalPath = confinedPath(root, reference);
	if (!await exists(finalPath, signal)) return null;
	const parent = dirname(finalPath);
	await ensureOutputDirectory(root, parent, false, signal);
	const prefix = `.${basename(reference)}.stage-`;
	const stages = [];
	let entries = 0;
	const directory = await opendir(parent);
	for await (const entry of directory) {
		throwIfAborted(signal);
		entries += 1;
		if (entries > 16) throw new PortablePackageIoError("output-conflict", "The retained publication directory contains too many entries to reconcile safely.");
		if (entry.name.startsWith(prefix)) {
			if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(entry.name.slice(prefix.length))) throw new PortablePackageIoError("output-conflict", "The retained publication marker has an unexpected staging alias.");
			stages.push(entry.name);
		}
	}
	if (stages.length === 0) return readStableFile(root, reference, maximumBytes, void 0, signal);
	const finalMetadata = await lstat(finalPath, { bigint: true });
	const linkedStages = [];
	for (const stage of stages) {
		throwIfAborted(signal);
		const stageReference = [dirname(reference), stage].filter((part) => part !== ".").join("/");
		const stagePath = confinedPath(root, stageReference);
		const stageMetadata = await lstat(stagePath, { bigint: true });
		if (stageMetadata.isSymbolicLink() || !stageMetadata.isFile()) throw new PortablePackageIoError("output-conflict", "The retained publication marker has a non-ordinary staging alias.");
		if (stageMetadata.dev === finalMetadata.dev && stageMetadata.ino === finalMetadata.ino) {
			if (finalMetadata.nlink !== 2n || stageMetadata.nlink !== 2n) throw new PortablePackageIoError("output-conflict", "The retained publication marker has an ambiguous linked staging alias.");
			linkedStages.push(stageReference);
			continue;
		}
		if (stageMetadata.nlink !== 1n) throw new PortablePackageIoError("output-conflict", "The retained publication marker has an aliased abandoned staging file.");
		await removeStagingFile(root, stagePath, parent, signal);
	}
	if (linkedStages.length === 0) return readStableFile(root, reference, maximumBytes, void 0, signal);
	if (linkedStages.length !== 1) throw new PortablePackageIoError("output-conflict", "The retained publication marker has multiple linked staging aliases.");
	return readAndReconcileLinkedStage(root, reference, linkedStages[0], maximumBytes, mediaType, signal);
}
async function installDeterministicFile(rootInput, reference, bytesInput, mediaType, signal) {
	throwIfAborted(signal);
	const root = await ensureOrdinaryDirectory(resolve(rootInput), signal, "output-conflict");
	throwIfAborted(signal);
	const bytes = Buffer.from(bytesInput);
	const identity = artifactIdentity$1(reference, mediaType, bytes, signal);
	const finalPath = confinedPath(root, reference);
	const parent = dirname(finalPath);
	await ensureOutputDirectory(root, parent, true, signal);
	throwIfAborted(signal);
	const stageReference = [dirname(reference), `.flowblind-stage-${basename(reference)}.part`].filter((part) => part !== ".").join("/");
	const stagePath = confinedPath(root, stageReference);
	const finalExists = await exists(finalPath, signal);
	throwIfAborted(signal);
	const stageExists = await exists(stagePath, signal);
	throwIfAborted(signal);
	if (finalExists && stageExists) {
		const reconciled = await reconcileLinkedStage(root, reference, stageReference, identity, signal);
		throwIfAborted(signal);
		return reconciled;
	}
	if (finalExists) {
		throwIfAborted(signal);
		await readStableFile(root, reference, bytes.byteLength, identity, signal);
		throwIfAborted(signal);
		return identity;
	}
	throwIfAborted(signal);
	if (stageExists) {
		throwIfAborted(signal);
		await readStableFile(root, stageReference, bytes.byteLength, {
			byteLength: bytes.byteLength,
			sha256: identity.sha256
		}, signal);
		throwIfAborted(signal);
		await removeStagingFile(root, stagePath, parent, signal, finalPath);
		throwIfAborted(signal);
	}
	let staged = false;
	try {
		await ensureOutputDirectory(root, parent, false, signal);
		throwIfAborted(signal);
		const handle = await open(stagePath, "wx", 384);
		staged = true;
		try {
			await ensureOutputDirectory(root, parent, false, signal);
			throwIfAborted(signal);
			await handle.writeFile(bytes);
			throwIfAborted(signal);
			await ensureOutputDirectory(root, parent, false, signal);
			throwIfAborted(signal);
			await handle.sync();
			throwIfAborted(signal);
		} finally {
			await handle.close();
			throwIfAborted(signal);
		}
		try {
			await ensureOutputDirectory(root, parent, false, signal);
			throwIfAborted(signal);
			await link(stagePath, finalPath);
			throwIfAborted(signal);
		} catch (error) {
			throwIfAborted(signal);
			if (typeof error !== "object" || error === null || !("code" in error) || error.code !== "EEXIST") throw error;
		}
		const reconciled = await reconcileLinkedStage(root, reference, stageReference, identity, signal);
		throwIfAborted(signal);
		staged = false;
		return reconciled;
	} catch (error) {
		throwIfAborted(signal);
		throw error instanceof PortablePackageIoError ? error : new PortablePackageIoError("output-conflict", "A deterministic package artifact could not be installed safely.", { cause: error });
	} finally {
		if (staged) {
			if (!await exists(finalPath).catch(() => true)) await removeStagingFile(root, stagePath, parent, void 0, finalPath).catch(() => void 0);
		}
	}
}
//#endregion
//#region tools/catalogResearchV2/package/retainedCatalogV1.ts
var RetainedCatalogV1OutcomeError = class extends Error {
	outcome;
	constructor(outcome) {
		super("The retained catalog v1 runtime returned a result-free family outcome.");
		this.name = "RetainedCatalogV1OutcomeError";
		this.outcome = outcome;
	}
};
var RetainedRunPriorOutcomeUnknownError = class extends Error {
	reasonCodes;
	constructor(detail, reasonCodes = ["retained-run-prior-outcome-unknown"]) {
		super(detail);
		this.name = "RetainedRunPriorOutcomeUnknownError";
		this.reasonCodes = Object.freeze([...reasonCodes]);
	}
};
async function awaitAbortable(operation, signal) {
	throwIfAborted(signal);
	if (signal === void 0) return operation;
	let rejectAbort;
	const aborted = new Promise((_resolve, reject) => {
		rejectAbort = reject;
	});
	const onAbort = () => {
		try {
			signal.throwIfAborted();
		} catch (error) {
			rejectAbort?.(error);
		}
	};
	signal.addEventListener("abort", onAbort, { once: true });
	try {
		return await Promise.race([operation, aborted]);
	} finally {
		signal.removeEventListener("abort", onAbort);
	}
}
async function runRetainedWithRestartGuard(input) {
	throwIfAborted(input.signal);
	const inspection = await input.inspect();
	throwIfAborted(input.signal);
	if (inspection.kind === "recovered") return inspection.value;
	if (inspection.kind === "prior-outcome-unknown") {
		const prior = await input.priorOutcome(inspection.detail);
		throwIfAborted(input.signal);
		return prior;
	}
	return await input.execute();
}
function ownRecord(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function ownValue(value, key) {
	const record = ownRecord(value);
	if (record === null) return void 0;
	const descriptor = Object.getOwnPropertyDescriptor(record, key);
	return descriptor !== void 0 && "value" in descriptor ? descriptor.value : void 0;
}
function publicIdentity(value, reference) {
	if (!isFlowBlindV2ArtifactIdentity(value)) throw new Error("The retained catalog returned an invalid artifact identity.");
	return reference === void 0 ? Object.freeze({ ...value }) : mappedArtifactIdentity(value, reference);
}
function resourceBinding$1(attachment) {
	return Object.freeze({
		role: attachment.role,
		selectionHandle: attachment.selectionHandle,
		immutableVersionId: attachment.immutableVersionId,
		members: Object.freeze(attachment.members.map((member) => Object.freeze({
			role: member.role,
			identity: Object.freeze({ ...member.identity })
		})))
	});
}
function candidateHandle(bytes, signal) {
	const identity = artifactIdentity$1("candidate.csv", "text/csv", bytes, signal);
	return Object.freeze({
		role: "candidate-data",
		selectionHandle: `sha256:${identity.sha256}`,
		immutableVersionId: `sha256:${identity.sha256}`,
		members: Object.freeze([Object.freeze({
			role: "candidate-data",
			identity,
			bytes: Uint8Array.from(bytes)
		})])
	});
}
function preparedSetHandle(input, signal) {
	const bindingSha256 = sha256Bytes(canonicalJsonBytes$1({
		preparation: input.preparation.identity.sha256,
		sidecar: input.sidecar.identity.sha256
	}), signal);
	return Object.freeze({
		role: "prepared-artifact-set",
		selectionHandle: `sha256:${bindingSha256}`,
		immutableVersionId: `sha256:${bindingSha256}`,
		members: Object.freeze([Object.freeze({
			role: "trusted-sidecar",
			identity: input.sidecar.identity,
			bytes: Uint8Array.from(input.sidecar.bytes)
		}), Object.freeze({
			role: "preparation-bundle",
			identity: input.preparation.identity,
			bytes: Uint8Array.from(input.preparation.bytes)
		})])
	});
}
function contextFromPreparation(preparation) {
	const value = ownRecord(preparation.humanContext);
	const researchGoal = ownValue(value, "researchGoal");
	const decisionQuestion = ownValue(value, "decisionQuestion");
	const nextEvidenceIntent = ownValue(value, "nextEvidenceIntent");
	if (typeof researchGoal !== "string" || !(decisionQuestion === void 0 || decisionQuestion === null || typeof decisionQuestion === "string") || !(nextEvidenceIntent === void 0 || nextEvidenceIntent === null || typeof nextEvidenceIntent === "string")) throw new Error("The retained preparation does not contain a valid scientist context.");
	return Object.freeze({
		researchGoal,
		decisionQuestion: decisionQuestion === void 0 ? null : decisionQuestion,
		nextEvidenceIntent: nextEvidenceIntent === void 0 ? null : nextEvidenceIntent
	});
}
function adapterForPreparation(preparation) {
	if (preparation.recordType === "flowblind-catalog-preparation-v1") return REGIONAL_AGREEMENT_V1_ADAPTER;
	if (preparation.recordType === "flowblind-catalog-vector-preparation-v1") return VECTOR_TIME_READINESS_V1_ADAPTER;
	throw new Error("The selected preparation is not one of the two advertised retained methods.");
}
async function loadPublicV1AttachmentSelection(action, inputRoot, signal) {
	throwIfAborted(signal);
	const files = await listOrdinaryFiles(inputRoot, {
		maximumFiles: action === "prepare-study" ? 1 : 3,
		maximumDepth: 4,
		maximumBytesEach: 16777216
	}, signal);
	throwIfAborted(signal);
	const candidates = files.filter((file) => file.reference === "candidate.csv");
	if (candidates.length !== 1 || files.length !== (action === "prepare-study" ? 1 : 3)) throw new Error(action === "prepare-study" ? "Preparation requires the mounted public source at the exact relative reference candidate.csv." : "Run requires candidate.csv plus one content-addressed preparation directory containing trusted-sidecar.json and preparation.json.");
	const candidate = candidateHandle(candidates[0].bytes, signal);
	if (action === "prepare-study") return Object.freeze({ attachments: Object.freeze([candidate]) });
	const preparationFiles = files.filter((file) => basename(file.reference) === "preparation.json");
	const sidecarFiles = files.filter((file) => basename(file.reference) === "trusted-sidecar.json");
	if (preparationFiles.length !== 1 || sidecarFiles.length !== 1 || dirname(preparationFiles[0].reference) !== dirname(sidecarFiles[0].reference)) throw new Error("The retained run attachment set must contain one canonical two-file preparation asset.");
	const preparationFile = preparationFiles[0];
	const sidecarFile = sidecarFiles[0];
	const preparation = parseCanonicalJson(preparationFile.bytes, "Retained preparation bundle", "pretty-lf", signal);
	const expectedParent = `flowblind-preparation-${preparationFile.sha256}`;
	if (preparationFile.reference !== `${expectedParent}/preparation.json` || sidecarFile.reference !== `${expectedParent}/trusted-sidecar.json`) throw new Error("The retained preparation asset must preserve its exact content-addressed directory with trusted-sidecar.json and preparation.json.");
	const adapter = adapterForPreparation(preparation);
	const preparationIdentity = artifactIdentity$1("preparation.json", "application/json", preparationFile.bytes, signal);
	const preparedSet = preparedSetHandle({
		sidecar: {
			identity: artifactIdentity$1("trusted-sidecar.json", "application/json", sidecarFile.bytes, signal),
			bytes: sidecarFile.bytes
		},
		preparation: {
			identity: preparationIdentity,
			bytes: preparationFile.bytes
		}
	}, signal);
	const marker = artifactIdentity$1(preparationFile.reference, "application/json", preparationFile.bytes, signal);
	const preparedStudy = Object.freeze({
		capability: adapter.identity,
		package: adapter.packageCompatibility.current,
		preparationSchema: adapter.preparationRecord.binding,
		humanContext: contextFromPreparation(preparation),
		preparationMarker: marker,
		preparationArtifact: preparationIdentity,
		resources: Object.freeze([resourceBinding$1(candidate), resourceBinding$1(preparedSet)])
	});
	return Object.freeze({
		attachments: Object.freeze([candidate, preparedSet]),
		preparedStudy
	});
}
async function retainedCatalogRuntime(packageEvidence, verifierPort, signal) {
	throwIfAborted(signal);
	const retained = await verifierPort.verifyRetainedPackage(packageEvidence, "catalog-v1", signal);
	throwIfAborted(signal);
	if (retained === null) throw new Error("The retained catalog v1 closure did not pass its exact tree manifest.");
	const verifierPath = resolve(retained.rootPath, "flowblind-research-teammate-verification-v1.mjs");
	throwIfAborted(signal);
	const verifier = await import(pathToFileURL(verifierPath).href);
	throwIfAborted(signal);
	const verified = await verifier.verifyFlowBlindCatalogPackage();
	throwIfAborted(signal);
	if (verifier.flowBlindCatalogPackageVerificationEvidence(verified.packageVerification) === null) throw new Error("The retained catalog verifier did not mint same-module package authority.");
	throwIfAborted(signal);
	const runtime = await import(`${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`);
	throwIfAborted(signal);
	if (runtime.catalogResearchRuntimeVersion !== "1.0.0" || typeof runtime.callCatalogResearchAction !== "function" || typeof runtime.readCatalogResearchVisualResource !== "function") throw new Error("The retained catalog runtime does not expose its reviewed entry points.");
	throwIfAborted(signal);
	return Object.freeze({
		module: runtime,
		packageVerification: verified.packageVerification
	});
}
function retainedInput(scientist) {
	return Object.freeze({
		researchGoal: scientist.intent.researchGoal,
		...scientist.intent.decisionQuestion === null ? {} : { decisionQuestion: scientist.intent.decisionQuestion },
		...scientist.intent.nextEvidenceIntent === null ? {} : { nextEvidenceIntent: scientist.intent.nextEvidenceIntent },
		...scientist.metadata ?? {}
	});
}
function familyOutcome$1(value) {
	throw new RetainedCatalogV1OutcomeError(value);
}
function responseRecord(value) {
	const record = ownRecord(value);
	if (record === null) throw new Error("The retained catalog runtime returned a non-object response.");
	return record;
}
function preparedOutputDirectory(bundleSha256) {
	return `flowblind-preparation-${bundleSha256}`;
}
function publicReportReferences(preparationSha256) {
	const directory = `flowblind-study-${preparationSha256}`;
	return Object.freeze({
		directory,
		preparation: `${directory}/preparation.json`,
		json: `${directory}/verified-study.json`,
		markdown: `${directory}/report.md`,
		html: `${directory}/report.html`,
		verification: `${directory}/report-verification.json`
	});
}
function exactAttachment(attachments, role) {
	const selected = attachments.filter((attachment) => attachment.role === role);
	if (selected.length !== 1) throw new Error(`The retained catalog requires exactly one ${role} attachment snapshot.`);
	return selected[0];
}
function exactMember(attachment, role) {
	const selected = attachment.members.filter((member) => member.role === role);
	if (selected.length !== 1) throw new Error(`The retained catalog requires exactly one ${role} attachment member.`);
	return selected[0];
}
function assertStagedMember(member, stagedReference, mediaType, signal) {
	throwIfAborted(signal);
	if (member.identity.reference !== basename(stagedReference) || member.identity.mediaType !== mediaType || member.identity.byteLength !== member.bytes.byteLength || member.identity.sha256 !== sha256Bytes(member.bytes, signal)) throw new Error(`The verified ${member.role} attachment bytes no longer match their bound identity.`);
}
async function writeStagedMember(root, reference, mediaType, member, signal) {
	assertStagedMember(member, reference, mediaType, signal);
	const path = resolve(root, reference);
	const parent = dirname(path);
	if (parent !== root) await mkdir(parent, {
		recursive: true,
		mode: 448
	});
	throwIfAborted(signal);
	await writeFile(path, member.bytes, {
		flag: "wx",
		mode: 384
	});
	await readStableFile(root, reference, 16777216, member.identity, signal);
}
async function withPublicV1AttachmentStage(action, attachments, operation, signal) {
	throwIfAborted(signal);
	const candidateAttachment = exactAttachment(attachments, "candidate-data");
	const candidate = exactMember(candidateAttachment, "candidate-data");
	if (candidateAttachment.members.length !== 1 || attachments.length !== (action === "prepare-study" ? 1 : 2)) throw new Error("The retained catalog attachment snapshot does not have the exact reviewed role set.");
	const root = await mkdtemp(resolve(tmpdir(), "flowblind-catalog-v2-input-"));
	try {
		await writeStagedMember(root, "candidate.csv", "text/csv", candidate, signal);
		if (action === "run-and-verify-study") {
			const preparedAttachment = exactAttachment(attachments, "prepared-artifact-set");
			const sidecar = exactMember(preparedAttachment, "trusted-sidecar");
			const bundle = exactMember(preparedAttachment, "preparation-bundle");
			if (preparedAttachment.members.length !== 2) throw new Error("The retained catalog prepared artifact set does not have the exact reviewed member roles.");
			const directory = preparedOutputDirectory(bundle.identity.sha256);
			await writeStagedMember(root, `${directory}/trusted-sidecar.json`, "application/json", sidecar, signal);
			await writeStagedMember(root, `${directory}/preparation.json`, "application/json", bundle, signal);
		}
		throwIfAborted(signal);
		return await operation(root);
	} finally {
		await rm(root, {
			recursive: true,
			force: true
		});
	}
}
function sameContentIdentity(left, right) {
	return left.byteLength === right.byteLength && left.sha256 === right.sha256 && left.mediaType === right.mediaType;
}
function matchesByteIdentity(value, expected) {
	const candidate = ownRecord(value);
	return candidate !== null && candidate.byteLength === expected.byteLength && candidate.sha256 === expected.sha256;
}
function matchesNativeIdentity(value, expected) {
	const candidate = ownRecord(value);
	const mediaType = ownValue(candidate, "mediaType");
	return candidate !== null && ownValue(candidate, "reference") === expected.reference && ownValue(candidate, "byteLength") === expected.byteLength && ownValue(candidate, "sha256") === expected.sha256 && (mediaType === void 0 || mediaType === expected.mediaType);
}
function assertNativeRunBindings(response, preparedStudy, candidate, sidecar, bundle) {
	const evidence = ownRecord(ownValue(response, "preparationEvidence"));
	const preparation = ownRecord(ownValue(evidence, "preparation"));
	const source = ownRecord(ownValue(evidence, "source"));
	const verifiedStudy = ownRecord(ownValue(response, "verifiedStudy"));
	const candidateBinding = preparedStudy.resources.find((resource) => resource.role === "candidate-data")?.members.find((member) => member.role === "candidate-data");
	const preparedBinding = preparedStudy.resources.find((resource) => resource.role === "prepared-artifact-set");
	const sidecarBinding = preparedBinding?.members.find((member) => member.role === "trusted-sidecar");
	const bundleBinding = preparedBinding?.members.find((member) => member.role === "preparation-bundle");
	if (ownValue(evidence, "kind") !== "portable-preparation-bundle-v1" || ownValue(verifiedStudy, "sourceIdentityMatched") !== true || candidateBinding === void 0 || sidecarBinding === void 0 || bundleBinding === void 0 || !sameArtifactIdentity(candidate.identity, candidateBinding.identity) || !sameArtifactIdentity(sidecar.identity, sidecarBinding.identity) || !sameArtifactIdentity(bundle.identity, bundleBinding.identity) || !sameArtifactIdentity(bundle.identity, preparedStudy.preparationArtifact) || !matchesNativeIdentity(ownValue(source, "candidate"), candidate.identity) || !matchesNativeIdentity(ownValue(source, "trustedSidecar"), sidecar.identity) || !matchesNativeIdentity(ownValue(preparation, "bundle"), bundle.identity)) throw new RetainedRunPriorOutcomeUnknownError("The committed retained result does not preserve the exact candidate and preparation identities confirmed by the host.", ["native-result-binding-mismatch"]);
}
function publicRunResponseFromCommitted(input) {
	return Object.freeze({
		schemaVersion: 1,
		teammateVersion: input.marker.teammateVersion,
		status: "report-complete",
		containsResults: true,
		humanContext: input.verifiedRecord.humanContext,
		matchedCapability: input.verifiedRecord.capability,
		verifiedStudy: Object.freeze({
			status: "verified",
			artifactVerificationStatus: "verified",
			deterministicReplayMatched: true,
			sourceIdentityMatched: true,
			result: input.verifiedRecord.study,
			artifacts: Object.freeze({
				json: input.json,
				markdown: input.markdown,
				html: input.html,
				verification: input.markerIdentity
			}),
			openVisualReport: Object.freeze({
				label: "Open visual report",
				uri: `flowblind-report://sha256/${input.html.sha256}?verification=${input.markerIdentity.sha256}&preparation=${input.preparation.sha256}`,
				mediaType: "text/html",
				byteLength: input.html.byteLength,
				sha256: input.html.sha256
			})
		}),
		preparationEvidence: Object.freeze({
			kind: "portable-preparation-bundle-v1",
			preparation: input.marker.preparation,
			source: input.marker.source,
			protocol: input.marker.protocol,
			software: input.marker.software
		})
	});
}
async function inspectPublicCommittedRun(input) {
	throwIfAborted(input.signal);
	const candidate = input.attachments.find((attachment) => attachment.role === "candidate-data")?.members[0];
	const prepared = input.attachments.find((attachment) => attachment.role === "prepared-artifact-set");
	const sidecar = prepared?.members.find((member) => member.role === "trusted-sidecar");
	const bundle = prepared?.members.find((member) => member.role === "preparation-bundle");
	if (candidate === void 0 || sidecar === void 0 || bundle === void 0) return Object.freeze({
		kind: "prior-outcome-unknown",
		detail: "The verified preparation attachment set is incomplete, so prior execution state cannot be reconciled safely."
	});
	const references = publicReportReferences(bundle.identity.sha256);
	let directoryState;
	try {
		directoryState = await inspectOrdinaryDirectory(input.outputRoot, references.directory, input.signal);
		throwIfAborted(input.signal);
	} catch {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: "The deterministic public report path could not be resolved safely."
		});
	}
	if (directoryState === "absent") return Object.freeze({ kind: "absent" });
	try {
		if (await readOrReconcileRetainedStagedFile(input.outputRoot, references.verification, 16777216, "application/json", input.signal) === null) return Object.freeze({ kind: "absent" });
	} catch {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: "The deterministic public report marker could not be resolved safely."
		});
	}
	let files;
	try {
		files = await listOrdinaryFiles(resolve(input.outputRoot, references.directory), {
			maximumFiles: 5,
			maximumDepth: 1,
			maximumBytesEach: 16777216
		}, input.signal);
		throwIfAborted(input.signal);
	} catch {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: "The deterministic public report directory could not be inspected safely."
		});
	}
	const byReference = new Map(files.map((file) => [file.reference, file]));
	const expected = [
		"preparation.json",
		"verified-study.json",
		"report.md",
		"report.html",
		"report-verification.json"
	];
	if (files.length !== expected.length || expected.some((reference) => !byReference.has(reference))) return Object.freeze({
		kind: "prior-outcome-unknown",
		detail: "A marker-committed public report set is incomplete or non-canonical."
	});
	try {
		const markerFile = byReference.get("report-verification.json");
		const marker = parseCanonicalJson(markerFile.bytes, "Committed public report marker", "pretty-lf", input.signal);
		const artifacts = ownRecord(marker.artifacts);
		const preparationRecord = ownRecord(marker.preparation);
		const source = ownRecord(marker.source);
		const capability = ownRecord(marker.capability);
		const preparation = publicIdentity(ownValue(artifacts, "preparation"));
		const json = publicIdentity(ownValue(artifacts, "json"));
		const markdown = publicIdentity(ownValue(artifacts, "markdown"));
		const html = publicIdentity(ownValue(artifacts, "html"));
		const markerIdentity = artifactIdentity$1(references.verification, "application/json", markerFile.bytes, input.signal);
		const expectedArtifacts = [
			[preparation, "preparation.json"],
			[json, "verified-study.json"],
			[markdown, "report.md"],
			[html, "report.html"]
		];
		if (marker.recordType !== "flowblind-catalog-report-verification-v1" || marker.status !== "verified-report-complete" || marker.publication === null || typeof marker.publication !== "object" || ownValue(marker.publication, "directory") !== references.directory || capability?.capabilityId !== input.adapter.identity.methodId || capability?.familyId !== input.adapter.identity.familyId || !sameContentIdentity(preparation, bundle.identity) || !matchesByteIdentity(ownValue(source, "candidate"), candidate.identity) || !matchesByteIdentity(ownValue(source, "trustedSidecar"), sidecar.identity) || expectedArtifacts.some(([identity, reference]) => {
			const file = byReference.get(reference);
			return file === void 0 || identity.reference !== `${references.directory}/${reference}` || identity.byteLength !== file.byteLength || identity.sha256 !== file.sha256;
		}) || !Buffer.from(byReference.get("preparation.json").bytes).equals(Buffer.from(bundle.bytes)) || !sameContentIdentity(publicIdentity(ownValue(preparationRecord, "bundle")), preparation)) throw new Error("The public report marker does not bind the selected preparation and source attachments.");
		const nativeUri = `flowblind-report://sha256/${html.sha256}?verification=${markerIdentity.sha256}&preparation=${preparation.sha256}`;
		throwIfAborted(input.signal);
		const verifiedHtml = await awaitAbortable(input.runtime.module.readCatalogResearchVisualResource(nativeUri, input.outputRoot, input.runtime.packageVerification), input.signal);
		throwIfAborted(input.signal);
		if (!Buffer.from(verifiedHtml).equals(Buffer.from(byReference.get("report.html").bytes))) throw new Error("The retained package resource verifier returned different report bytes.");
		const verifiedRecord = parseCanonicalJson(byReference.get("verified-study.json").bytes, "Committed public verified study", "pretty-lf", input.signal);
		return Object.freeze({
			kind: "recovered",
			value: publicRunResponseFromCommitted({
				marker,
				markerIdentity,
				preparation,
				verifiedRecord,
				json,
				markdown,
				html
			})
		});
	} catch (error) {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: error instanceof Error ? error.message : "The committed public report could not be revalidated safely."
		});
	}
}
async function publicPrepareRecord(runtime, adapter, invocation, outputRoot) {
	throwIfAborted(invocation.signal);
	const candidate = invocation.attachments.find((attachment) => attachment.role === "candidate-data");
	const member = candidate?.members[0];
	if (candidate === void 0 || member === void 0) throw new Error("The public retained adapter requires one candidate snapshot.");
	throwIfAborted(invocation.signal);
	const raw = await withPublicV1AttachmentStage("prepare-study", invocation.attachments, (inputRoot) => runtime.module.callCatalogResearchAction("prepare-study", retainedInput(invocation.scientist), {
		inputRoot,
		outputRoot,
		...invocation.signal === void 0 ? {} : { signal: invocation.signal }
	}, runtime.packageVerification), invocation.signal);
	const response = responseRecord(raw);
	if (response.status !== "prepared-awaiting-confirmation") return familyOutcome$1(raw);
	const nativePreparationIdentity = publicIdentity(response.preparationBundle);
	const nativeSidecarIdentity = publicIdentity(response.sidecarIdentity);
	if (!matchesNativeIdentity(response.sourceIdentity, member.identity)) throw new Error("The retained preparation does not bind the selected candidate snapshot.");
	const directory = preparedOutputDirectory(nativePreparationIdentity.sha256);
	const preparationSnapshot = await readStableFile(outputRoot, `${directory}/preparation.json`, 16777216, nativePreparationIdentity, invocation.signal);
	throwIfAborted(invocation.signal);
	const sidecarSnapshot = await readStableFile(outputRoot, `${directory}/trusted-sidecar.json`, 16777216, nativeSidecarIdentity, invocation.signal);
	throwIfAborted(invocation.signal);
	const preparationIdentity = artifactIdentity$1("preparation.json", "application/json", preparationSnapshot.bytes, invocation.signal);
	const sidecarIdentity = artifactIdentity$1("trusted-sidecar.json", "application/json", sidecarSnapshot.bytes, invocation.signal);
	const marker = Object.freeze({ ...nativePreparationIdentity });
	const preparedSet = preparedSetHandle({
		sidecar: {
			identity: sidecarIdentity,
			bytes: sidecarSnapshot.bytes
		},
		preparation: {
			identity: preparationIdentity,
			bytes: preparationSnapshot.bytes
		}
	}, invocation.signal);
	throwIfAborted(invocation.signal);
	const preparedStudy = Object.freeze({
		capability: adapter.identity,
		package: adapter.packageCompatibility.current,
		preparationSchema: adapter.preparationRecord.binding,
		humanContext: invocation.scientist.intent,
		preparationMarker: marker,
		preparationArtifact: preparationIdentity,
		resources: Object.freeze([resourceBinding$1(candidate), resourceBinding$1(preparedSet)])
	});
	return Object.freeze({
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		capability: adapter.identity,
		package: adapter.packageCompatibility.current,
		preparationSchema: adapter.preparationRecord.binding,
		preparedStudy,
		preparation: raw,
		adapterPublication: Object.freeze({
			state: "committed",
			owner: "adapter",
			receipt: Object.freeze({
				status: "committed",
				phase: "prepare",
				marker,
				artifacts: Object.freeze([sidecarIdentity, preparationIdentity]),
				pointOfNoReturn: "exclusive-preparation-commit-marker",
				distributedExactlyOnceClaim: false
			})
		}),
		publication: Object.freeze({
			confirmation: "none",
			pointOfNoReturn: "exclusive-preparation-commit-marker",
			distributedExactlyOnceClaim: false
		})
	});
}
async function publicRunRecord(runtime, adapter, invocation, outputRoot) {
	throwIfAborted(invocation.signal);
	const candidate = invocation.attachments.find((attachment) => attachment.role === "candidate-data");
	const prepared = invocation.attachments.find((attachment) => attachment.role === "prepared-artifact-set");
	const candidateMember = candidate?.members[0];
	const sidecar = prepared?.members.find((member) => member.role === "trusted-sidecar");
	const bundle = prepared?.members.find((member) => member.role === "preparation-bundle");
	if (candidateMember === void 0 || sidecar === void 0 || bundle === void 0) throw new Error("The public retained run requires the exact three-file attachment set.");
	throwIfAborted(invocation.signal);
	const raw = await runRetainedWithRestartGuard({
		inspect: () => inspectPublicCommittedRun({
			runtime,
			adapter,
			attachments: invocation.attachments,
			outputRoot,
			...invocation.signal === void 0 ? {} : { signal: invocation.signal }
		}),
		execute: () => withPublicV1AttachmentStage("run-and-verify-study", invocation.attachments, (inputRoot) => runtime.module.callCatalogResearchAction("run-and-verify-study", retainedInput(invocation.scientist), {
			inputRoot,
			outputRoot,
			...invocation.signal === void 0 ? {} : { signal: invocation.signal }
		}, runtime.packageVerification), invocation.signal),
		priorOutcome(detail) {
			throw new RetainedRunPriorOutcomeUnknownError(detail, ["retained-public-run-prior-outcome-unknown"]);
		},
		...invocation.signal === void 0 ? {} : { signal: invocation.signal }
	});
	throwIfAborted(invocation.signal);
	const response = responseRecord(raw);
	if (response.status !== "report-complete") return familyOutcome$1(raw);
	assertNativeRunBindings(response, invocation.preparedStudy, candidateMember, sidecar, bundle);
	const artifacts = responseRecord(responseRecord(response.verifiedStudy).artifacts);
	const nativeJson = publicIdentity(artifacts.json);
	const nativeMarkdown = publicIdentity(artifacts.markdown);
	const nativeHtml = publicIdentity(artifacts.html);
	const nativeVerification = publicIdentity(artifacts.verification);
	for (const identity of [
		nativeJson,
		nativeMarkdown,
		nativeHtml,
		nativeVerification
	]) await readStableFile(outputRoot, identity.reference, 16777216, identity, void 0);
	const json = mappedArtifactIdentity(nativeJson, "verified-study.json");
	const markdown = mappedArtifactIdentity(nativeMarkdown, "report.md");
	const html = mappedArtifactIdentity(nativeHtml, "report.html");
	const marker = mappedArtifactIdentity(nativeVerification, "report-verification.json");
	return Object.freeze({
		status: "report-complete",
		containsResults: true,
		capability: adapter.identity,
		package: adapter.packageCompatibility.current,
		resultSchema: adapter.resultRecord.binding,
		renderer: adapter.renderer.binding,
		result: raw,
		adapterPublication: Object.freeze({
			state: "committed",
			owner: "adapter",
			receipt: Object.freeze({
				status: "committed",
				phase: "run",
				marker,
				artifacts: Object.freeze([
					json,
					markdown,
					html
				]),
				pointOfNoReturn: "exclusive-report-commit-marker",
				distributedExactlyOnceClaim: false
			})
		}),
		publication: Object.freeze({
			confirmation: "host-callback-bracket",
			executionStartBoundary: "confirmed-operation-callback-entry",
			pointOfNoReturn: "exclusive-report-commit-marker",
			distributedExactlyOnceClaim: false,
			resourceUri: `flowblind-report://sha256/${html.sha256}?verification=${marker.sha256}`
		})
	});
}
async function issuePublicV1Authority(input) {
	throwIfAborted(input.signal);
	const runtime = await retainedCatalogRuntime(input.packageEvidence, input.verifierPort, input.signal);
	throwIfAborted(input.signal);
	const capability = (adapter) => Object.freeze({
		capability: adapter.identity,
		authorityRequirementId: adapter.authority.requirement.requirementId,
		package: adapter.packageCompatibility.current,
		preparationSchema: adapter.preparationRecord.binding,
		resultSchema: adapter.resultRecord.binding,
		renderer: adapter.renderer.binding,
		prepare: (invocation) => publicPrepareRecord(runtime, adapter, invocation, input.outputRoot),
		run: (invocation) => publicRunRecord(runtime, adapter, invocation, input.outputRoot),
		async render(record) {
			const bytes = await readPublicV1Resource(record.publication.resourceUri, input.outputRoot, runtime, input.signal);
			throwIfAborted(input.signal);
			return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		},
		readResource: (uri) => readPublicV1Resource(uri, input.outputRoot, runtime, input.signal)
	});
	const integration = Object.freeze({
		integrationId: REGIONAL_AGREEMENT_V1_ADAPTER.authority.requirement.integrationId,
		integrationVersion: REGIONAL_AGREEMENT_V1_ADAPTER.authority.requirement.integrationVersion,
		grants: REGIONAL_AGREEMENT_V1_ADAPTER.authority.requirement.requiredGrants,
		capabilities: Object.freeze([capability(REGIONAL_AGREEMENT_V1_ADAPTER), capability(VECTOR_TIME_READINESS_V1_ADAPTER)])
	});
	const evidence = createRuntimeAuthorityIssuer((candidate) => candidate === runtime.packageVerification ? integration : null).issue(runtime.packageVerification);
	if (evidence === null) throw new Error("The retained catalog package did not mint v2 runtime authority.");
	throwIfAborted(input.signal);
	return Object.freeze({
		evidence,
		runtime
	});
}
function resourceUriParts(uri) {
	const match = /^flowblind-report:\/\/sha256\/([a-f0-9]{64})\?verification=([a-f0-9]{64})$/u.exec(uri);
	return match === null ? null : Object.freeze({
		reportSha256: match[1],
		verificationSha256: match[2]
	});
}
async function readPublicV1Resource(uri, outputRoot, runtime, signal) {
	throwIfAborted(signal);
	const parts = resourceUriParts(uri);
	if (parts === null) throw new Error("The public report URI is not a canonical v2 resource URI.");
	const references = await listOrdinaryFileReferences(outputRoot, {
		maximumFiles: 4096,
		maximumDepth: 4
	}, signal);
	throwIfAborted(signal);
	const markerMatches = [];
	for (const reference of references.filter((entry) => basename(entry.reference) === "report-verification.json")) {
		const marker = await readStableFile(outputRoot, reference.reference, 16777216, void 0, signal);
		if (marker.sha256 === parts.verificationSha256) markerMatches.push(marker);
	}
	if (markerMatches.length !== 1) throw new Error("The public report URI does not resolve to exactly one verified marker.");
	const marker = parseCanonicalJson(markerMatches[0].bytes, "Public report verification marker", "pretty-lf", signal);
	const html = publicIdentity(ownValue(ownRecord(marker.artifacts), "html"));
	const preparationBundle = publicIdentity(ownValue(ownRecord(marker.preparation), "bundle"));
	if (marker.status !== "verified-report-complete" || html.sha256 !== parts.reportSha256 || dirname(html.reference) !== dirname(markerMatches[0].reference)) throw new Error("The public report marker does not bind the requested resource.");
	const nativeUri = `flowblind-report://sha256/${html.sha256}?verification=${parts.verificationSha256}&preparation=${preparationBundle.sha256}`;
	throwIfAborted(signal);
	const bytes = await awaitAbortable(runtime.module.readCatalogResearchVisualResource(nativeUri, outputRoot, runtime.packageVerification), signal);
	throwIfAborted(signal);
	return bytes;
}
async function loadPublicV1RuntimeForResource(packageEvidence, verifierPort, signal) {
	throwIfAborted(signal);
	const runtime = await retainedCatalogRuntime(packageEvidence, verifierPort, signal);
	throwIfAborted(signal);
	return runtime;
}
//#endregion
//#region tools/catalogResearchV2/hiddenFlowV1Contract.ts
var HIDDEN_FLOW_V1_CAPABILITY = Object.freeze({
	familyId: "hidden-flow",
	methodId: "finite-basis-hidden-flow-v1",
	methodVersion: "1.1.0"
});
var HIDDEN_FLOW_V1_NATIVE_FAMILY = "finite-basis-observation-compatible-hidden-flow-v1";
var HIDDEN_FLOW_V1_PACKAGE = Object.freeze({
	packageId: "flowblind-catalog-hidden-flow-package-lock-v1",
	packageVersion: "1.0.0",
	compatibilityKey: "sha256:91b2644f438ec6e98593476412429b7a0203c4f3f8cde6f4849e6e1cb1507d48"
});
var HIDDEN_FLOW_V1_PREPARATION_SCHEMA = Object.freeze({
	recordKind: "flowblind-catalog-hidden-flow-preparation-v1",
	schemaId: "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-preparation-bundle-v1.schema.json",
	schemaVersion: "1"
});
var HIDDEN_FLOW_V1_RESULT_SCHEMA = Object.freeze({
	recordKind: "flowblind-catalog-hidden-flow-verified-run-v1",
	schemaId: "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-verified-run-v1.schema.json",
	schemaVersion: "1"
});
var HIDDEN_FLOW_V1_RENDERER = Object.freeze({
	rendererId: "flowblind-catalog-hidden-flow-report-resource-v2-bridge",
	rendererVersion: "1.0.0",
	resourceReference: "report.md",
	resourceUriScheme: "flowblind-hidden-flow-report",
	resourceMediaType: "text/markdown"
});
var HIDDEN_FLOW_V1_OUTER_PREPARATION_MARKER_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-v2-hidden-flow-preparation-marker-v1.schema.json";
var HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT = Object.freeze({
	requirementId: "hidden-flow-v1-retained-bridge-authority",
	integrationId: "flowblind-hidden-flow-v1-runtime",
	integrationVersion: "1.1.0",
	requiredGrants: Object.freeze([
		"exact-retained-hidden-flow-package-lock",
		"exact-retained-hidden-flow-runtime",
		"attested-generic-hidden-flow-problem-authority",
		"result-free-one-problem-preparation",
		"runtime-branded-run-confirmation",
		"marker-last-report-verification",
		"private-execution-without-advertisement",
		"v2-64mib-prepublication-output-gate"
	])
});
var HIDDEN_FLOW_V1_RESOURCE_LIMITS = Object.freeze({
	maximumProblemSnapshotBytes: 16777216,
	maximumPreparationBundleBytes: 17825792,
	maximumV2VerifiedRunBytes: 67108864,
	maximumNativeVerifiedRunBytes: 134217728,
	maximumMarkdownBytes: 16777216,
	maximumMarkerBytes: 16777216,
	maximumActivationLocalReportBindings: 128,
	verifiedRunLimitDisposition: "prepublication-v2-ceiling-required"
});
var HIDDEN_FLOW_V1_REVIEWED_CANDIDATE = Object.freeze({
	route: HIDDEN_FLOW_V1_CAPABILITY,
	nativeFamily: HIDDEN_FLOW_V1_NATIVE_FAMILY,
	reviewedCommits: Object.freeze({
		authorityRuntimeBase: "123bd990f48e7351884f035c0941367b8bd5f942",
		independentHardening: "272e69ed95a6730bd68ca2033da4933e9759c883"
	}),
	packageLock: Object.freeze({
		recordType: "flowblind-catalog-hidden-flow-package-lock-v1",
		packageVersion: "1.0.0",
		artifactCount: 48,
		byteLength: 21934,
		sha256: "91b2644f438ec6e98593476412429b7a0203c4f3f8cde6f4849e6e1cb1507d48"
	}),
	runtime: Object.freeze({
		byteLength: 177882,
		sha256: "29b7cf20974a9f1c5f42fff87ede181bcb848eeb2ffd70425a4d0f98a2d1b37f"
	}),
	review: Object.freeze({
		authority: "attested-generic-hidden-flow-problem-authority-v1",
		policy: "flowblind-catalog-hidden-flow-generic-review-policy-v1@1.0.0",
		scope: "generic-problem-contract-parser-and-executable-preflight-only"
	}),
	release: Object.freeze({
		status: "default-off",
		advertiseToScientist: false,
		activation: "explicit-trusted-host-assembly-only"
	}),
	resources: HIDDEN_FLOW_V1_RESOURCE_LIMITS
});
//#endregion
//#region tools/catalogResearchV2/hiddenFlowV1Authority.ts
var verifierPorts = /* @__PURE__ */ new WeakSet();
var verifiedPackages = /* @__PURE__ */ new WeakMap();
var verifiedPackageHandles = /* @__PURE__ */ new WeakSet();
function exactEvidence(value) {
	return value.reviewedCommits.authorityRuntimeBase === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.reviewedCommits.authorityRuntimeBase && value.reviewedCommits.independentHardening === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.reviewedCommits.independentHardening && value.packageLock.recordType === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.packageLock.recordType && value.packageLock.packageVersion === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.packageLock.packageVersion && value.packageLock.artifactCount === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.packageLock.artifactCount && value.packageLock.byteLength === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.packageLock.byteLength && value.packageLock.sha256 === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.packageLock.sha256 && value.runtime.byteLength === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.runtime.byteLength && value.runtime.sha256 === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.runtime.sha256 && value.review.authority === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review.authority && value.review.policy === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review.policy && value.review.scope === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review.scope && value.outputPolicy.nativeMaximumVerifiedRunBytes === HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumNativeVerifiedRunBytes && value.outputPolicy.bridgeMaximumVerifiedRunBytes === HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes && value.outputPolicy.enforcement === "prepublication-v2-ceiling-required";
}
function validRuntime(value) {
	return exactEvidence(value.evidence) && value.nativePackageAuthority !== null && typeof value.nativePackageAuthority === "object" && typeof value.declarationPreview === "function" && typeof value.prepare === "function" && typeof value.run === "function" && typeof value.assertPreparation === "function" && typeof value.assertActionResponse === "function" && typeof value.assertReportSet === "function" && typeof value.readCommittedArtifact === "function";
}
function normalizeRuntime(runtime) {
	return Object.freeze({
		...runtime,
		evidence: Object.freeze({
			reviewedCommits: Object.freeze({ ...runtime.evidence.reviewedCommits }),
			packageLock: Object.freeze({ ...runtime.evidence.packageLock }),
			runtime: Object.freeze({ ...runtime.evidence.runtime }),
			review: Object.freeze({ ...runtime.evidence.review }),
			outputPolicy: Object.freeze({ ...runtime.evidence.outputPolicy })
		})
	});
}
function createHiddenFlowV1PackageVerifier(verify) {
	const port = Object.freeze({ async verifyAndMint(candidate, signal) {
		const verified = await verify(candidate, HIDDEN_FLOW_V1_REVIEWED_CANDIDATE, signal);
		if (verified === null || !validRuntime(verified)) return null;
		const handle = Object.freeze(Object.create(null));
		verifiedPackages.set(handle, normalizeRuntime(verified));
		verifiedPackageHandles.add(handle);
		return handle;
	} });
	verifierPorts.add(port);
	return port;
}
function isRuntimeHiddenFlowV1PackageVerifier(value) {
	return value !== null && typeof value === "object" && verifierPorts.has(value);
}
function resolveVerifiedHiddenFlowV1Package(value) {
	if (value === null || typeof value !== "object" || !verifiedPackageHandles.has(value)) return null;
	return verifiedPackages.get(value) ?? null;
}
//#endregion
//#region tools/catalogResearchV2/package/hiddenFlowV1PortableBridge.ts
var PROBLEM_ROLE = Object.freeze({
	role: "problem-snapshot",
	exactCount: 1,
	access: "read-only",
	suppliedBy: "host",
	members: Object.freeze([Object.freeze({
		role: "problem",
		mediaType: "application/json",
		portableReference: "problem.json"
	})]),
	description: "One immutable canonical stable-JSON hidden-flow problem snapshot selected by the trusted host."
});
var PREPARATION_BUNDLE_ROLE = Object.freeze({
	role: "preparation-bundle",
	exactCount: 1,
	access: "read-only",
	suppliedBy: "host",
	members: Object.freeze([Object.freeze({
		role: "preparation-bundle",
		mediaType: "application/json",
		portableReference: "preparation.json"
	})]),
	description: "The exact retained preparation bundle committed with the outer v2 preparation marker."
});
var HIDDEN_FLOW_V1_PRIVATE_DESCRIPTOR = Object.freeze({
	identity: HIDDEN_FLOW_V1_CAPABILITY,
	nativeIdentity: Object.freeze({
		methodFamily: HIDDEN_FLOW_V1_NATIVE_FAMILY,
		packageVersion: "1.0.0"
	}),
	release: Object.freeze({
		status: "trusted-private",
		advertiseToScientist: false
	}),
	availability: Object.freeze({
		state: "active",
		detail: "Executable only inside an explicitly imported trusted activation assembly after exact retained-package verification."
	}),
	scientistMetadata: Object.freeze({ status: "none" }),
	package: HIDDEN_FLOW_V1_PACKAGE,
	preparationSchema: HIDDEN_FLOW_V1_PREPARATION_SCHEMA,
	resultSchema: HIDDEN_FLOW_V1_RESULT_SCHEMA,
	renderer: HIDDEN_FLOW_V1_RENDERER,
	lifecycle: Object.freeze({
		prepare: "explicit-trusted-bridge",
		run: "explicit-trusted-bridge"
	})
});
var confirmedHiddenFlowInvocations = /* @__PURE__ */ new WeakSet();
var confirmedHiddenFlowBindings = /* @__PURE__ */ new WeakMap();
var authorizedPrepareInvocations = /* @__PURE__ */ new WeakMap();
var authorizedRunInvocations = /* @__PURE__ */ new WeakMap();
var HiddenFlowV1BridgeContractError = class extends Error {
	code;
	constructor(code, message) {
		super(message);
		this.name = "HiddenFlowV1BridgeContractError";
		this.code = code;
	}
};
function asRecord$1(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function ownDataValue(value, key) {
	const record = asRecord$1(value);
	if (record === null) return void 0;
	try {
		const descriptor = Object.getOwnPropertyDescriptor(record, key);
		return descriptor !== void 0 && descriptor.enumerable === true && "value" in descriptor ? descriptor.value : void 0;
	} catch {
		return;
	}
}
function deepFreeze(value, visited = /* @__PURE__ */ new WeakSet()) {
	if (value === null || typeof value !== "object") return value;
	if (ArrayBuffer.isView(value)) return value;
	if (visited.has(value)) return value;
	visited.add(value);
	let descriptors;
	try {
		descriptors = Object.getOwnPropertyDescriptors(value);
	} catch {
		throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "Bridge output properties could not be inspected safely.");
	}
	for (const key of Reflect.ownKeys(descriptors)) {
		const descriptor = Reflect.get(descriptors, key);
		if (!("value" in descriptor)) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", `Bridge output property ${String(key)} cannot be an accessor.`);
		deepFreeze(descriptor.value, visited);
	}
	return Object.isFrozen(value) ? value : Object.freeze(value);
}
function resultFree$1(outcome) {
	return deepFreeze({
		...outcome,
		schemaVersion: 2,
		routerVersion: FLOWBLIND_V2_ROUTER_PACKAGE_VERSION,
		reasonCodes: [...outcome.reasonCodes]
	});
}
function normalizedText(value, required) {
	if (!required && (value === null || value === void 0)) return null;
	if (typeof value !== "string") return void 0;
	const normalized = value.normalize("NFC").trim();
	if (normalized.length === 0 || [...normalized].length > 4096 || [...normalized].some((character) => {
		const point = character.codePointAt(0);
		return point !== void 0 && (point >= 0 && point <= 8 || point === 11 || point === 12 || point >= 14 && point <= 31 || point === 127);
	})) return;
	return normalized;
}
function hiddenFlowInput(context) {
	const details = context.decisionQuestion === null && context.nextEvidenceIntent === null ? null : stableJson({
		decisionQuestion: context.decisionQuestion,
		nextEvidenceIntent: context.nextEvidenceIntent
	});
	return Object.freeze({
		goal: context.researchGoal,
		details
	});
}
function parseScientist(value) {
	const record = asRecord$1(value);
	if (record === null) return resultFree$1({
		status: "invalid-scientist-request",
		containsResults: false,
		reasonCodes: ["scientist-request-must-be-object"],
		guidance: "Provide only researchGoal and optional decisionQuestion or nextEvidenceIntent text."
	});
	let descriptors;
	try {
		descriptors = Object.getOwnPropertyDescriptors(record);
	} catch {
		return resultFree$1({
			status: "invalid-scientist-request",
			containsResults: false,
			reasonCodes: ["scientist-request-must-use-own-data"],
			guidance: "Scientist input must be a plain own-data object without proxies or accessors."
		});
	}
	const allowed = [
		"researchGoal",
		"decisionQuestion",
		"nextEvidenceIntent"
	];
	if (Reflect.ownKeys(descriptors).some((key) => typeof key === "symbol") || Object.entries(descriptors).some(([key, descriptor]) => !allowed.includes(key) || descriptor.enumerable !== true || !("value" in descriptor))) return resultFree$1({
		status: "invalid-scientist-request",
		containsResults: false,
		reasonCodes: ["technical-metadata-or-accessor-input-rejected"],
		guidance: "Hidden flow accepts goal/details projection only; remove metadata, technical identifiers, approval fields, and accessors."
	});
	const researchGoal = normalizedText(ownDataValue(record, "researchGoal"), true);
	const decisionQuestion = normalizedText(ownDataValue(record, "decisionQuestion"), false);
	const nextEvidenceIntent = normalizedText(ownDataValue(record, "nextEvidenceIntent"), false);
	if (researchGoal === void 0 || researchGoal === null || decisionQuestion === void 0 || nextEvidenceIntent === void 0) return resultFree$1({
		status: "invalid-scientist-request",
		containsResults: false,
		reasonCodes: ["invalid-scientist-human-context"],
		guidance: "Use bounded trimmed NFC scientist-authored text."
	});
	const intent = Object.freeze({
		researchGoal,
		decisionQuestion,
		nextEvidenceIntent
	});
	const scientist = Object.freeze({
		intent,
		metadata: null
	});
	const input = hiddenFlowInput(intent);
	if (input.details !== null && [...input.details].length > 4096) return resultFree$1({
		status: "invalid-scientist-request",
		containsResults: false,
		reasonCodes: ["projected-hidden-flow-details-too-long"],
		guidance: "Shorten the optional decision and next-evidence context so their canonical native projection is at most 4,096 Unicode code points."
	});
	return Object.freeze({
		scientist,
		input
	});
}
function stableJson(value) {
	if (value === null) return "null";
	if (typeof value === "string") return JSON.stringify(value);
	if (typeof value === "boolean") return value ? "true" : "false";
	if (typeof value === "number") {
		if (!Number.isFinite(value)) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "Canonical JSON cannot contain a non-finite number.");
		return JSON.stringify(value);
	}
	if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
	const record = asRecord$1(value);
	if (record === null) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "Canonical JSON supports only JSON data.");
	const descriptors = Object.getOwnPropertyDescriptors(record);
	if (Reflect.ownKeys(descriptors).some((key) => typeof key === "symbol")) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "Canonical JSON cannot contain symbol properties.");
	return `{${Object.keys(descriptors).sort().map((key) => {
		const descriptor = Reflect.get(descriptors, key);
		if (descriptor.enumerable !== true || !("value" in descriptor) || descriptor.value === void 0) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "Canonical JSON requires enumerable own JSON data.");
		return `${JSON.stringify(key)}:${stableJson(descriptor.value)}`;
	}).join(",")}}`;
}
function canonicalJsonBytes(value) {
	return Buffer.from(stableJson(value), "utf8");
}
function stablePrettyJsonValue(value) {
	if (Array.isArray(value)) return value.map(stablePrettyJsonValue);
	const record = asRecord$1(value);
	if (record !== null) return Object.fromEntries(Object.keys(record).sort().map((key) => [key, stablePrettyJsonValue(record[key])]));
	return value;
}
function canonicalJsonSnapshot(bytes) {
	if (bytes.byteLength === 0) return false;
	try {
		const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		const value = JSON.parse(text);
		return stableJson(value) === text || `${JSON.stringify(stablePrettyJsonValue(value), null, 2)}\n` === text;
	} catch {
		return false;
	}
}
function safeReference(reference) {
	if (reference.length === 0 || reference.length > 512 || reference !== reference.normalize("NFC").trim() || reference.startsWith("/") || reference.includes("\\") || reference.includes("://") || /^[a-z]:/iu.test(reference)) return false;
	return reference.split("/").every((segment) => segment.length > 0 && segment !== "." && segment !== "..");
}
function artifactIdentity(value, maximumBytes) {
	const reference = ownDataValue(value, "reference");
	const byteLength = ownDataValue(value, "byteLength");
	const sha256 = ownDataValue(value, "sha256");
	const mediaType = ownDataValue(value, "mediaType");
	if (typeof reference !== "string" || !safeReference(reference) || typeof byteLength !== "number" || !Number.isSafeInteger(byteLength) || byteLength < 1 || byteLength > maximumBytes || typeof sha256 !== "string" || !/^[a-f0-9]{64}$/u.test(sha256) || typeof mediaType !== "string" || mediaType.length === 0 || mediaType.length > 256 || mediaType !== mediaType.trim()) return null;
	return Object.freeze({
		reference,
		byteLength,
		sha256,
		mediaType
	});
}
function identityMatchesBytes(identity, bytes, maximumBytes) {
	return artifactIdentity(identity, maximumBytes) !== null && identity.byteLength === bytes.byteLength && identity.sha256 === flowBlindV2Sha256(bytes);
}
function mappedIdentity(reference, identity) {
	return Object.freeze({
		reference,
		byteLength: identity.byteLength,
		sha256: identity.sha256,
		mediaType: identity.mediaType
	});
}
function candidateEvidenceMatches(value, expected) {
	try {
		return stableJson(value) === stableJson(expected);
	} catch {
		return false;
	}
}
function declarationMatches(preview) {
	return preview.capabilityId === HIDDEN_FLOW_V1_CAPABILITY.methodId && preview.capabilityVersion === HIDDEN_FLOW_V1_CAPABILITY.methodVersion && preview.methodFamily === "finite-basis-observation-compatible-hidden-flow-v1" && preview.packageVersion === HIDDEN_FLOW_V1_PACKAGE.packageVersion && preview.reviewAuthority === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review.authority && preview.reviewPolicy === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review.policy && preview.reviewScope === HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review.scope;
}
function authorityUnavailable(reason) {
	return resultFree$1({
		status: "authority-unavailable",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		releaseState: "trusted-private",
		authority: {
			state: "unavailable",
			reason
		},
		reasonCodes: [reason],
		guidance: "Use only the current activation-local v2 authority minted from the exact retained package verifier; JSON evidence and copied handles do not authorize."
	});
}
function routeSelection(normalized) {
	const universal = assessFlowBlindUniversalIntent(normalized.scientist.intent);
	if (universal.unsafe.length > 0) return resultFree$1({
		status: "unsafe-unsupported",
		containsResults: false,
		reasonCodes: universal.unsafe.map((finding) => finding.code),
		guidance: "Remove external-source, arbitrary-execution, or confirmation-bypass instructions."
	});
	if (universal.incompatible.length > 0) return resultFree$1({
		status: "needs-scientific-method",
		containsResults: false,
		reasonCodes: universal.incompatible.map((finding) => finding.code),
		guidance: "Use a separately reviewed scientific method for the incompatible request."
	});
	if (isUnregisteredHomeQcIntent(normalized.scientist.intent)) return resultFree$1({
		status: "unsupported",
		containsResults: false,
		reasonCodes: ["home-qc-not-registered"],
		guidance: "Home QC has no registered v2 method descriptor."
	});
	const matches = FLOWBLIND_V2_CAPABILITY_REGISTRY.descriptors.filter((descriptor) => descriptor.matchScientistIntent(normalized.scientist.intent));
	if (matches.length > 1) return resultFree$1({
		status: "ambiguous",
		containsResults: false,
		reasonCodes: ["multiple-capability-families-matched"],
		guidance: "Restate one scientific goal without combining hidden-flow, vector, or sensor-placement intent."
	});
	if (matches.length !== 1 || !sameCapabilityIdentity(matches[0].identity, HIDDEN_FLOW_V1_CAPABILITY)) return resultFree$1({
		status: "unsupported",
		containsResults: false,
		reasonCodes: ["hidden-flow-bridge-route-not-selected"],
		guidance: "This private activation handles only the exact reviewed hidden-flow route."
	});
	return null;
}
function resourceIdentity(handle) {
	return Object.freeze({
		role: handle.role,
		selectionHandle: handle.selectionHandle,
		immutableVersionId: handle.immutableVersionId,
		members: Object.freeze(handle.members.map((member) => Object.freeze({
			role: member.role,
			identity: Object.freeze({ ...member.identity })
		})))
	});
}
function normalizeSingleAttachment(handle, expected) {
	if (handle.role !== expected.role || handle.selectionHandle.trim().length === 0 || handle.immutableVersionId.trim().length === 0 || handle.members.length !== 1) return null;
	const member = handle.members[0];
	const identity = artifactIdentity(member.identity, expected.maximumBytes);
	if (member.role !== expected.memberRole || identity === null || identity.reference !== expected.reference || identity.mediaType !== expected.mediaType || identity.byteLength !== member.bytes.byteLength || identity.sha256 !== flowBlindV2Sha256(member.bytes) || expected.canonicalJson && !canonicalJsonSnapshot(member.bytes)) return null;
	return Object.freeze({
		role: handle.role,
		selectionHandle: handle.selectionHandle,
		immutableVersionId: handle.immutableVersionId,
		members: Object.freeze([Object.freeze({
			role: member.role,
			identity,
			bytes: Uint8Array.from(member.bytes)
		})])
	});
}
function validSingleAttachment(handle, expected) {
	if (handle.role !== expected.role || handle.selectionHandle.trim().length === 0 || handle.immutableVersionId.trim().length === 0 || handle.members.length !== 1) return false;
	const member = handle.members[0];
	return member.role === expected.memberRole && member.identity.reference === expected.reference && member.identity.mediaType === expected.mediaType && identityMatchesBytes(member.identity, member.bytes, expected.maximumBytes) && (!expected.canonicalJson || canonicalJsonSnapshot(member.bytes));
}
async function loadSingleAttachment(request, host, expected) {
	const selected = await host.loadAttachments(request);
	if (selected.length !== 1) return null;
	const resolved = resolveRuntimeResourceSnapshot(selected[0], request);
	if (resolved === null) return null;
	if (expected.normalizeIdentity === true) {
		const normalized = normalizeSingleAttachment(resolved, expected);
		return normalized === null ? null : Object.freeze({
			raw: selected[0],
			handle: normalized
		});
	}
	return validSingleAttachment(resolved, expected) ? Object.freeze({
		raw: selected[0],
		handle: resolved
	}) : null;
}
function sameContext(left, right) {
	return left.researchGoal === right.researchGoal && left.decisionQuestion === right.decisionQuestion && left.nextEvidenceIntent === right.nextEvidenceIntent;
}
function projectResource(value, expected) {
	const role = ownDataValue(value, "role");
	const selectionHandle = ownDataValue(value, "selectionHandle");
	const immutableVersionId = ownDataValue(value, "immutableVersionId");
	const members = ownDataValue(value, "members");
	if (role !== expected.role || typeof selectionHandle !== "string" || selectionHandle.trim().length === 0 || typeof immutableVersionId !== "string" || immutableVersionId.trim().length === 0 || !Array.isArray(members) || members.length !== 1) return null;
	const member = members[0];
	const memberRole = ownDataValue(member, "role");
	const identity = artifactIdentity(ownDataValue(member, "identity"), expected.maximumBytes);
	if (memberRole !== expected.memberRole || identity === null || identity.reference !== expected.reference || identity.mediaType !== expected.mediaType) return null;
	return Object.freeze({
		role,
		selectionHandle,
		immutableVersionId,
		members: Object.freeze([Object.freeze({
			role: memberRole,
			identity
		})])
	});
}
function projectPreparedStudy(value) {
	const capability = ownDataValue(value, "capability");
	const packageBinding = ownDataValue(value, "package");
	const preparationSchema = ownDataValue(value, "preparationSchema");
	const humanContext = ownDataValue(value, "humanContext");
	const marker = artifactIdentity(ownDataValue(value, "preparationMarker"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes);
	const preparationArtifact = artifactIdentity(ownDataValue(value, "preparationArtifact"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes);
	const resources = ownDataValue(value, "resources");
	const projectedCapability = {
		familyId: ownDataValue(capability, "familyId"),
		methodId: ownDataValue(capability, "methodId"),
		methodVersion: ownDataValue(capability, "methodVersion")
	};
	const projectedPackage = {
		packageId: ownDataValue(packageBinding, "packageId"),
		packageVersion: ownDataValue(packageBinding, "packageVersion"),
		compatibilityKey: ownDataValue(packageBinding, "compatibilityKey")
	};
	const projectedSchema = {
		recordKind: ownDataValue(preparationSchema, "recordKind"),
		schemaId: ownDataValue(preparationSchema, "schemaId"),
		schemaVersion: ownDataValue(preparationSchema, "schemaVersion")
	};
	const projectedContext = {
		researchGoal: ownDataValue(humanContext, "researchGoal"),
		decisionQuestion: ownDataValue(humanContext, "decisionQuestion"),
		nextEvidenceIntent: ownDataValue(humanContext, "nextEvidenceIntent")
	};
	if (!sameCapabilityIdentity(projectedCapability, HIDDEN_FLOW_V1_CAPABILITY) || !samePackageBinding(projectedPackage, HIDDEN_FLOW_V1_PACKAGE) || !sameSchemaBinding(projectedSchema, HIDDEN_FLOW_V1_PREPARATION_SCHEMA) || typeof projectedContext.researchGoal !== "string" || projectedContext.decisionQuestion !== null && typeof projectedContext.decisionQuestion !== "string" || projectedContext.nextEvidenceIntent !== null && typeof projectedContext.nextEvidenceIntent !== "string" || marker === null || marker.reference !== "preparation-commit.json" || marker.mediaType !== "application/json" || preparationArtifact === null || preparationArtifact.reference !== "preparation.json" || preparationArtifact.mediaType !== "application/json" || !Array.isArray(resources) || resources.length !== 2) return null;
	const problem = projectResource(resources.find((resource) => ownDataValue(resource, "role") === PROBLEM_ROLE.role), {
		role: PROBLEM_ROLE.role,
		memberRole: "problem",
		reference: "problem.json",
		mediaType: "application/json",
		maximumBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes
	});
	const bundle = projectResource(resources.find((resource) => ownDataValue(resource, "role") === PREPARATION_BUNDLE_ROLE.role), {
		role: PREPARATION_BUNDLE_ROLE.role,
		memberRole: "preparation-bundle",
		reference: "preparation.json",
		mediaType: "application/json",
		maximumBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes
	});
	if (problem === null || bundle === null || !sameArtifactIdentity(bundle.members[0].identity, preparationArtifact)) return null;
	const binding = Object.freeze({
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		preparationSchema: HIDDEN_FLOW_V1_PREPARATION_SCHEMA,
		humanContext: Object.freeze({
			researchGoal: projectedContext.researchGoal,
			decisionQuestion: projectedContext.decisionQuestion,
			nextEvidenceIntent: projectedContext.nextEvidenceIntent
		}),
		preparationMarker: marker,
		preparationArtifact,
		resources: Object.freeze([problem, bundle])
	});
	return Object.freeze({
		binding,
		problem,
		bundle
	});
}
function authorityMatches(evidence, activationEvidence) {
	if (evidence !== activationEvidence) return false;
	const authority = resolveRuntimeAuthority(evidence, HIDDEN_FLOW_V1_CAPABILITY);
	return authority !== null && authority.integrationId === HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.integrationId && authority.integrationVersion === HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.integrationVersion && authority.capability.authorityRequirementId === HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.requirementId && HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.requiredGrants.every((grant) => authority.grants.includes(grant)) && samePackageBinding(authority.capability.package, HIDDEN_FLOW_V1_PACKAGE) && sameSchemaBinding(authority.capability.preparationSchema, HIDDEN_FLOW_V1_PREPARATION_SCHEMA) && sameSchemaBinding(authority.capability.resultSchema, HIDDEN_FLOW_V1_RESULT_SCHEMA) && sameRendererBinding(authority.capability.renderer, HIDDEN_FLOW_V1_RENDERER);
}
function nativeHumanContextMatches(value, expected) {
	return ownDataValue(value, "goal") === expected.goal && ownDataValue(value, "details") === expected.details;
}
var HIDDEN_FLOW_V1_ERROR_CODES = Object.freeze([
	"input-invalid",
	"attachment-set-invalid",
	"attachment-path-unsafe",
	"attachment-changed-during-read",
	"problem-bytes-invalid",
	"problem-not-canonical",
	"problem-not-executable",
	"review-authority-unavailable",
	"review-attestation-invalid",
	"package-attestation-failed",
	"preparation-bundle-invalid",
	"human-context-mismatch",
	"output-publication-conflict",
	"concurrent-publication-conflict",
	"output-publication-partial",
	"output-artifact-tampered",
	"operation-cancelled"
]);
var HIDDEN_FLOW_V1_ERROR_CLASSIFICATIONS = Object.freeze([
	"cancellation",
	"attachment",
	"input-validation",
	"package-attestation",
	"publication",
	"review",
	"verification"
]);
var HIDDEN_FLOW_V1_UNAVAILABLE_REASONS = Object.freeze([
	"verification-not-accepted",
	"deterministic-replay-mismatch",
	"runtime-unavailable",
	"runtime-identity-mismatch",
	"output-resource-limit",
	"operation-cancelled"
]);
function hasExactOwnDataKeys(value, expected) {
	const record = asRecord$1(value);
	if (record === null) return false;
	try {
		const descriptors = Object.getOwnPropertyDescriptors(record);
		return Reflect.ownKeys(descriptors).every((key) => typeof key === "string") && Object.keys(descriptors).length === expected.length && expected.every((key) => {
			const descriptor = Reflect.get(descriptors, key);
			return descriptor !== void 0 && descriptor.enumerable === true && "value" in descriptor;
		});
	} catch {
		return false;
	}
}
function nativeDetail(value) {
	const detail = normalizedText(value, true);
	return detail === void 0 ? null : detail;
}
function projectRefusal(value) {
	if (!hasExactOwnDataKeys(value, [
		"schemaVersion",
		"capabilityVersion",
		"status",
		"containsResults",
		"error"
	]) || ownDataValue(value, "schemaVersion") !== 1 || ownDataValue(value, "capabilityVersion") !== "1.1.0" || ownDataValue(value, "status") !== "refused" || ownDataValue(value, "containsResults") !== false) return null;
	const error = ownDataValue(value, "error");
	if (!hasExactOwnDataKeys(error, [
		"code",
		"classification",
		"detail"
	])) return null;
	const code = ownDataValue(error, "code");
	const classification = ownDataValue(error, "classification");
	const detail = nativeDetail(ownDataValue(error, "detail"));
	if (typeof code !== "string" || !HIDDEN_FLOW_V1_ERROR_CODES.includes(code) || typeof classification !== "string" || !HIDDEN_FLOW_V1_ERROR_CLASSIFICATIONS.includes(classification) || detail === null) return null;
	return deepFreeze({
		schemaVersion: 1,
		capabilityVersion: "1.1.0",
		status: "refused",
		containsResults: false,
		error: {
			code,
			classification,
			detail
		}
	});
}
function projectUnavailable(value) {
	if (!hasExactOwnDataKeys(value, [
		"schemaVersion",
		"capabilityVersion",
		"status",
		"containsResults",
		"deterministicReplayMatched",
		"outcome"
	]) || ownDataValue(value, "schemaVersion") !== 1 || ownDataValue(value, "capabilityVersion") !== "1.1.0" || ownDataValue(value, "status") !== "unavailable" || ownDataValue(value, "containsResults") !== false || ownDataValue(value, "deterministicReplayMatched") !== false) return null;
	const outcome = ownDataValue(value, "outcome");
	if (!hasExactOwnDataKeys(outcome, [
		"kind",
		"evidenceState",
		"reason",
		"detail"
	]) || ownDataValue(outcome, "kind") !== "unavailable") return null;
	const evidenceState = ownDataValue(outcome, "evidenceState");
	const reason = ownDataValue(outcome, "reason");
	const detail = nativeDetail(ownDataValue(outcome, "detail"));
	if (!(evidenceState === null || evidenceState === "unsupported" || evidenceState === "failed") || typeof reason !== "string" || !HIDDEN_FLOW_V1_UNAVAILABLE_REASONS.includes(reason) || detail === null) return null;
	return deepFreeze({
		schemaVersion: 1,
		capabilityVersion: "1.1.0",
		status: "unavailable",
		containsResults: false,
		deterministicReplayMatched: false,
		outcome: {
			kind: "unavailable",
			evidenceState,
			reason,
			detail
		}
	});
}
function refusalOutcome(response) {
	return resultFree$1({
		status: "refused",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		familyOutcome: Object.freeze({ ...response.error }),
		reasonCodes: [`hidden-flow-refused-${response.error.code}`],
		guidance: response.error.detail
	});
}
function unavailableOutcome(response) {
	return resultFree$1({
		status: "execution-unavailable",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		familyOutcome: Object.freeze({ ...response.outcome }),
		reasonCodes: [`hidden-flow-execution-${response.outcome.reason}`],
		guidance: response.outcome.detail
	});
}
function nativeReportDirectory(preparationBundleSha256) {
	return `flowblind-hidden-flow-study-${preparationBundleSha256}`;
}
function validateReportSet(reportSet, prepared, input) {
	const violations = [];
	const expectedDirectory = nativeReportDirectory(prepared.preparationArtifact.sha256);
	const verifiedRun = artifactIdentity(reportSet.verifiedRun.identity, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumNativeVerifiedRunBytes);
	const report = artifactIdentity(reportSet.report.identity, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes);
	const verification = artifactIdentity(reportSet.verification.identity, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes);
	if (verifiedRun === null || report === null || verification === null) return {
		usableReceipt: null,
		binding: null,
		violations: ["native-report-artifact-invalid"]
	};
	if (verifiedRun.reference !== `${expectedDirectory}/verified-run.json` || report.reference !== `${expectedDirectory}/report.md` || verification.reference !== `${expectedDirectory}/report-verification.json` || reportSet.response.publication.directory !== expectedDirectory) violations.push("native-report-directory-cross-binding");
	if (verifiedRun.mediaType !== "application/json" || report.mediaType !== "text/markdown" || verification.mediaType !== "application/json") violations.push("native-report-media-type-invalid");
	if (reportSet.response.publication.state !== "marker-verified" || reportSet.response.publication.promotable !== true || reportSet.response.publication.pointOfNoReturn !== "exclusive-report-verification-commit-marker" || reportSet.response.publication.distributedExactlyOnceClaim !== false) violations.push("native-report-marker-last-invalid");
	if (!sameArtifactIdentity(reportSet.response.artifacts.json, verifiedRun) || !sameArtifactIdentity(reportSet.response.artifacts.markdown, report) || !sameArtifactIdentity(reportSet.response.artifacts.verification, verification)) violations.push("native-report-response-cross-binding");
	const response = reportSet.response;
	if (response.schemaVersion !== 1 || response.capabilityVersion !== "1.1.0" || response.status !== "report-complete" || response.deterministicReplayMatched !== true || !nativeHumanContextMatches(response.humanContext, input)) violations.push("native-report-response-invalid");
	const expectedContainsResults = response.outcome.kind !== "unavailable";
	if (response.containsResults !== expectedContainsResults || response.outcome.kind === "unavailable" && (response.outcome.evidenceState !== "verified-unbounded-within-tolerance" || response.outcome.reason !== "no-finite-bound")) violations.push("native-report-outcome-invalid");
	const v2VerifiedRun = mappedIdentity("verified-run.json", verifiedRun);
	const v2Report = mappedIdentity("report.md", report);
	const v2Marker = mappedIdentity("report-verification.json", verification);
	const receipt = Object.freeze({
		status: "committed",
		phase: "run",
		marker: v2Marker,
		artifacts: Object.freeze([v2VerifiedRun, v2Report]),
		pointOfNoReturn: "exclusive-report-commit-marker",
		distributedExactlyOnceClaim: false
	});
	const binding = Object.freeze({
		preparationBundleSha256: prepared.preparationArtifact.sha256,
		preparationMarkerSha256: prepared.preparationMarker.sha256,
		directory: expectedDirectory,
		verifiedRun,
		report,
		verification
	});
	if (verifiedRun.byteLength > HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes) {
		violations.push("post-ponr-v2-verified-run-ceiling-exceeded");
		return {
			usableReceipt: receipt,
			binding,
			violations
		};
	}
	if (!identityMatchesBytes(verifiedRun, reportSet.verifiedRun.bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes) || !identityMatchesBytes(report, reportSet.report.bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes) || !identityMatchesBytes(verification, reportSet.verification.bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes)) violations.push("native-report-artifact-bytes-mismatch");
	if (!canonicalJsonSnapshot(reportSet.verifiedRun.bytes) || !canonicalJsonSnapshot(reportSet.verification.bytes)) violations.push("native-report-json-not-canonical");
	return {
		usableReceipt: receipt,
		binding,
		violations
	};
}
function resourceUri(report, marker, preparationBundleSha256, preparationMarkerSha256) {
	return `${HIDDEN_FLOW_V1_RENDERER.resourceUriScheme}://sha256/${report.sha256}?verification=${marker.sha256}&preparation=${preparationBundleSha256}&preparationMarker=${preparationMarkerSha256}`;
}
function reconciliationOutcome(preparationBundleSha256, receipt, violations, detail) {
	const reasonCodes = [
		"hidden-flow-marker-verified-reconciliation-required",
		...receipt === null ? ["native-report-artifact-invalid"] : [],
		...violations
	];
	return resultFree$1({
		status: "prior-outcome-unknown",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		reasonCodes: [...new Set(reasonCodes)],
		guidance: `${detail} Revalidate the exact marker-bound report set; do not invoke the retained package again automatically.`,
		reconciliation: receipt === null ? {
			state: "native-marker-last-reconciliation-required",
			phase: "run",
			preparationBundleSha256,
			markerInstalledLast: true
		} : {
			state: "committed-record-revalidation-required",
			phase: "run",
			receipt,
			marker: receipt.marker
		}
	});
}
function committedPublication(receipt) {
	return Object.freeze({
		state: "committed",
		owner: "adapter",
		receipt
	});
}
function resultRecord(reportSet, prepared, runtime, receipt, binding) {
	const report = receipt.artifacts.find((artifact) => artifact.reference === "report.md");
	if (report === void 0) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "A committed hidden-flow receipt has no report.md member.");
	return deepFreeze({
		status: "report-complete",
		containsResults: reportSet.response.containsResults,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		resultSchema: HIDDEN_FLOW_V1_RESULT_SCHEMA,
		renderer: HIDDEN_FLOW_V1_RENDERER,
		result: {
			deterministicReplayMatched: true,
			outcome: reportSet.response.outcome
		},
		preparation: {
			marker: prepared.preparationMarker,
			bundle: prepared.preparationArtifact
		},
		retainedReport: {
			...binding,
			authority: runtime.evidence
		},
		adapterPublication: committedPublication(receipt),
		publication: {
			confirmation: "host-callback-bracket",
			executionStartBoundary: "confirmed-operation-callback-entry",
			pointOfNoReturn: "exclusive-report-commit-marker",
			distributedExactlyOnceClaim: false,
			resourceUri: resourceUri(report, receipt.marker, binding.preparationBundleSha256, binding.preparationMarkerSha256)
		}
	});
}
function sameReceiptArtifact(receipt, reference, expected) {
	const matches = receipt.artifacts.filter((artifact) => artifact.reference === reference);
	return matches.length === 1 && sameArtifactIdentity(matches[0], expected);
}
function validResultRecord(record, runtime) {
	let publication;
	try {
		if (record.status !== "report-complete" || !sameCapabilityIdentity(record.capability, HIDDEN_FLOW_V1_CAPABILITY) || !samePackageBinding(record.package, HIDDEN_FLOW_V1_PACKAGE) || !sameSchemaBinding(record.resultSchema, HIDDEN_FLOW_V1_RESULT_SCHEMA) || !sameRendererBinding(record.renderer, HIDDEN_FLOW_V1_RENDERER) || record.adapterPublication.state !== "committed" || record.adapterPublication.owner !== "adapter" || !candidateEvidenceMatches(record.retainedReport.authority, runtime.evidence)) return false;
		publication = record.adapterPublication;
	} catch {
		return false;
	}
	const receipt = publication.receipt;
	const receiptMarker = artifactIdentity(receipt.marker, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes);
	const retainedVerifiedRun = artifactIdentity(record.retainedReport.verifiedRun, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes);
	const retainedReport = artifactIdentity(record.retainedReport.report, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes);
	const retainedVerification = artifactIdentity(record.retainedReport.verification, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes);
	const preparationMarker = artifactIdentity(record.preparation.marker, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes);
	const preparationBundle = artifactIdentity(record.preparation.bundle, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes);
	if (receipt.status !== "committed" || receipt.phase !== "run" || receipt.pointOfNoReturn !== "exclusive-report-commit-marker" || receipt.distributedExactlyOnceClaim !== false || receiptMarker === null || receiptMarker.reference !== "report-verification.json" || receiptMarker.mediaType !== "application/json" || receipt.artifacts.length !== 2 || retainedVerifiedRun === null || retainedVerifiedRun.mediaType !== "application/json" || retainedReport === null || retainedReport.mediaType !== "text/markdown" || retainedVerification === null || retainedVerification.mediaType !== "application/json" || preparationMarker === null || preparationMarker.reference !== "preparation-commit.json" || preparationMarker.mediaType !== "application/json" || preparationBundle === null || preparationBundle.reference !== "preparation.json" || preparationBundle.mediaType !== "application/json" || record.result.deterministicReplayMatched !== true) return false;
	const expectedDirectory = nativeReportDirectory(preparationBundle.sha256);
	const retained = record.retainedReport;
	const mappedVerifiedRun = mappedIdentity("verified-run.json", retainedVerifiedRun);
	const mappedReport = mappedIdentity("report.md", retainedReport);
	const mappedMarker = mappedIdentity("report-verification.json", retainedVerification);
	const expectedContainsResults = record.result.outcome.kind !== "unavailable";
	return record.containsResults === expectedContainsResults && (record.result.outcome.kind !== "unavailable" || record.result.outcome.evidenceState === "verified-unbounded-within-tolerance" && record.result.outcome.reason === "no-finite-bound") && retained.preparationBundleSha256 === preparationBundle.sha256 && retained.preparationMarkerSha256 === preparationMarker.sha256 && retained.directory === expectedDirectory && retainedVerifiedRun.reference === `${expectedDirectory}/verified-run.json` && retainedReport.reference === `${expectedDirectory}/report.md` && retainedVerification.reference === `${expectedDirectory}/report-verification.json` && sameArtifactIdentity(receiptMarker, mappedMarker) && sameReceiptArtifact(receipt, "verified-run.json", mappedVerifiedRun) && sameReceiptArtifact(receipt, "report.md", mappedReport) && record.publication.confirmation === "host-callback-bracket" && record.publication.executionStartBoundary === "confirmed-operation-callback-entry" && record.publication.pointOfNoReturn === "exclusive-report-commit-marker" && record.publication.distributedExactlyOnceClaim === false && record.publication.resourceUri === resourceUri(mappedReport, mappedMarker, preparationBundle.sha256, preparationMarker.sha256);
}
function rememberReportBinding(bindings, uri, binding) {
	bindings.delete(uri);
	while (bindings.size >= HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumActivationLocalReportBindings) {
		const oldest = bindings.keys().next().value;
		if (typeof oldest !== "string") break;
		bindings.delete(oldest);
	}
	bindings.set(uri, binding);
}
function mintHiddenConfirmation(handle) {
	const invocation = Object.freeze(Object.create(null));
	confirmedHiddenFlowInvocations.add(invocation);
	confirmedHiddenFlowBindings.set(invocation, handle);
	return invocation;
}
function revokeHiddenConfirmation(invocation) {
	confirmedHiddenFlowInvocations.delete(invocation);
	confirmedHiddenFlowBindings.delete(invocation);
}
function isRuntimeHiddenFlowV1ConfirmedInvocation(value) {
	return value !== null && typeof value === "object" && confirmedHiddenFlowInvocations.has(value) && confirmedHiddenFlowBindings.has(value);
}
function preparationMarker(problem, nativeBundle, v2Bundle) {
	const document = deepFreeze({
		$schema: HIDDEN_FLOW_V1_OUTER_PREPARATION_MARKER_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-v2-hidden-flow-preparation-marker-v1",
		status: "committed",
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		reviewedCommits: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.reviewedCommits,
		problemSnapshot: problem,
		preparation: {
			nativeBundle,
			v2Bundle
		},
		publication: {
			marker: "preparation-commit.json",
			pointOfNoReturn: "exclusive-preparation-commit-marker",
			distributedExactlyOnceClaim: false
		}
	});
	const bytes = canonicalJsonBytes(document);
	return {
		document,
		artifact: Object.freeze({
			identity: Object.freeze({
				reference: "preparation-commit.json",
				byteLength: bytes.byteLength,
				sha256: flowBlindV2Sha256(bytes),
				mediaType: "application/json"
			}),
			bytes
		})
	};
}
function validCommitResult(value, marker, bundle) {
	return value.status === "committed" && sameArtifactIdentity(value.marker, marker) && sameArtifactIdentity(value.preparationBundle, bundle) && value.selectionHandle.trim().length > 0 && value.immutableVersionId.trim().length > 0;
}
async function prepareHiddenFlow(runtime, committer, scientist, problem, signal) {
	const problemMember = problem.members[0];
	const native = await runtime.prepare(runtime.nativePackageAuthority, {
		action: "prepare-study",
		input: scientist.input,
		selectedProblemSnapshot: problemMember.bytes,
		...signal === void 0 ? {} : { signal }
	});
	runtime.assertPreparation(runtime.nativePackageAuthority, native.response, native.bundle);
	if (native.response.status === "refused") {
		const response = projectRefusal(native.response);
		if (response === null) throw new HiddenFlowV1BridgeContractError("preparation-contract-invalid", "The verified hidden-flow runtime returned an invalid typed refusal.");
		return refusalOutcome(response);
	}
	const response = native.response;
	const bundle = native.bundle;
	if (response.schemaVersion !== 1 || response.capabilityVersion !== "1.1.0" || response.containsResults !== false || !nativeHumanContextMatches(response.humanContext, scientist.input) || bundle === null || !identityMatchesBytes(bundle.identity, bundle.bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes) || bundle.identity.mediaType !== "application/json" || !canonicalJsonSnapshot(bundle.bytes) || !sameArtifactIdentity(response.preparationBundle, bundle.identity)) throw new HiddenFlowV1BridgeContractError("preparation-contract-invalid", "The verified hidden-flow runtime returned an invalid result-free preparation bundle.");
	const v2Bundle = mappedIdentity("preparation.json", bundle.identity);
	const marker = preparationMarker(problemMember.identity, bundle.identity, v2Bundle);
	const committed = await committer.commit({
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		problemSnapshot: { identity: problemMember.identity },
		nativePreparationBundle: bundle.identity,
		preparationBundle: Object.freeze({
			identity: v2Bundle,
			bytes: Uint8Array.from(bundle.bytes)
		}),
		marker: marker.artifact
	}, signal);
	if (!validCommitResult(committed, marker.artifact.identity, v2Bundle)) throw new HiddenFlowV1BridgeContractError("preparation-contract-invalid", "The host did not commit the exact preparation bundle and outer marker.");
	const problemBinding = resourceIdentity(problem);
	const bundleBinding = Object.freeze({
		role: PREPARATION_BUNDLE_ROLE.role,
		selectionHandle: committed.selectionHandle,
		immutableVersionId: committed.immutableVersionId,
		members: Object.freeze([Object.freeze({
			role: "preparation-bundle",
			identity: v2Bundle
		})])
	});
	const preparedStudy = Object.freeze({
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		preparationSchema: HIDDEN_FLOW_V1_PREPARATION_SCHEMA,
		humanContext: scientist.scientist.intent,
		preparationMarker: marker.artifact.identity,
		preparationArtifact: v2Bundle,
		resources: Object.freeze([problemBinding, bundleBinding])
	});
	const receipt = Object.freeze({
		status: "committed",
		phase: "prepare",
		marker: marker.artifact.identity,
		artifacts: Object.freeze([v2Bundle]),
		pointOfNoReturn: "exclusive-preparation-commit-marker",
		distributedExactlyOnceClaim: false
	});
	return deepFreeze({
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		preparationSchema: HIDDEN_FLOW_V1_PREPARATION_SCHEMA,
		preparedStudy,
		preparation: {
			nativeResponse: response,
			problemSnapshot: problemMember.identity,
			reviewedCandidate: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE
		},
		adapterPublication: committedPublication(receipt),
		publication: {
			confirmation: "none",
			pointOfNoReturn: "exclusive-preparation-commit-marker",
			distributedExactlyOnceClaim: false
		}
	});
}
async function runHiddenFlow(runtime, scientist, prepared, bundle, confirmedExecution, signal, reconciliationKey, reconciliationByPreparation, reportBindingsByUri) {
	const nativeConfirmation = mintHiddenConfirmation(confirmedExecution);
	try {
		const invocation = {
			action: "run-and-verify-study",
			input: scientist.input,
			preparationBundleSnapshot: bundle.members[0].bytes,
			outerPreparationMarker: prepared.preparationMarker,
			confirmedInvocation: nativeConfirmation,
			outputLimits: HIDDEN_FLOW_V1_RESOURCE_LIMITS,
			...signal === void 0 ? {} : { signal }
		};
		const native = await runtime.run(runtime.nativePackageAuthority, invocation);
		if (native.kind === "refused") {
			runtime.assertActionResponse(runtime.nativePackageAuthority, native.response);
			const response = projectRefusal(native.response);
			if (response === null) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "The verified hidden-flow runtime returned an invalid typed refusal.");
			return refusalOutcome(response);
		}
		if (native.kind === "unavailable") {
			runtime.assertActionResponse(runtime.nativePackageAuthority, native.response);
			const response = projectUnavailable(native.response);
			if (response === null) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "The verified hidden-flow runtime returned an invalid typed execution-unavailable response.");
			return unavailableOutcome(response);
		}
		const reportSet = native.reportSet;
		if (ownDataValue(reportSet, "markerInstalledLast") !== true) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "The retained package returned a report set without a marker-last publication point of no return.");
		let validation = null;
		const memoize = (receipt, violations, detail) => {
			const outcome = reconciliationOutcome(reconciliationKey, receipt, violations, detail);
			reconciliationByPreparation.set(reconciliationKey, outcome);
			return outcome;
		};
		if (native.kind === "marker-verified-reconciliation-required") {
			try {
				validation = validateReportSet(reportSet, prepared, scientist.input);
			} catch {
				return memoize(null, ["native-report-artifact-invalid"], native.detail);
			}
			return memoize(validation.usableReceipt, validation.violations.length === 0 ? ["native-reconciliation-required"] : validation.violations, native.detail);
		}
		try {
			validation = validateReportSet(reportSet, prepared, scientist.input);
		} catch (error) {
			return memoize(null, ["native-report-artifact-invalid"], error instanceof Error ? error.message : "The marker-last report set could not be projected safely.");
		}
		if (validation.usableReceipt === null || validation.binding === null) return memoize(null, validation.violations, "The retained package exposed a marker-last set without usable artifact identities.");
		if (validation.violations.length > 0) return memoize(validation.usableReceipt, validation.violations, "The marker exists, but the native report set does not satisfy the v2 bridge binding.");
		try {
			runtime.assertReportSet(runtime.nativePackageAuthority, reportSet);
		} catch (error) {
			const detail = error instanceof Error ? error.message : "Native semantic verification failed.";
			return memoize(validation.usableReceipt, ["post-ponr-native-semantic-verification-failed"], detail);
		}
		try {
			const record = resultRecord(reportSet, prepared, runtime, validation.usableReceipt, validation.binding);
			rememberReportBinding(reportBindingsByUri, record.publication.resourceUri, validation.binding);
			return record;
		} catch (error) {
			const detail = error instanceof Error ? error.message : "The v2 result mapping failed after the native marker was committed.";
			return memoize(validation.usableReceipt, ["post-ponr-v2-result-mapping-failed"], detail);
		}
	} finally {
		revokeHiddenConfirmation(nativeConfirmation);
	}
}
function preparationMismatch(prepared, scientist) {
	const reasons = [];
	if (!sameContext(prepared.binding.humanContext, scientist.scientist.intent)) reasons.push("prepared-study-human-context-mismatch");
	if (!sameArtifactIdentity(prepared.bundle.members[0].identity, prepared.binding.preparationArtifact)) reasons.push("prepared-study-bundle-mismatch");
	return reasons;
}
function sameBoundResourceIdentity(left, right) {
	return left.role === right.role && left.selectionHandle === right.selectionHandle && left.immutableVersionId === right.immutableVersionId && left.members.length === right.members.length && left.members.every((member, index) => {
		const candidate = right.members[index];
		return candidate !== void 0 && member.role === candidate.role && sameArtifactIdentity(member.identity, candidate.identity);
	});
}
function samePreparedBinding(left, right) {
	return sameCapabilityIdentity(left.capability, right.capability) && samePackageBinding(left.package, right.package) && sameSchemaBinding(left.preparationSchema, right.preparationSchema) && sameContext(left.humanContext, right.humanContext) && sameArtifactIdentity(left.preparationMarker, right.preparationMarker) && sameArtifactIdentity(left.preparationArtifact, right.preparationArtifact) && left.resources.length === right.resources.length && left.resources.every((resource, index) => {
		const candidate = right.resources[index];
		return candidate !== void 0 && sameBoundResourceIdentity(resource, candidate);
	});
}
function runBundleMatches(prepared, bundle) {
	const expected = prepared.bundle;
	return bundle.role === expected.role && bundle.selectionHandle === expected.selectionHandle && bundle.immutableVersionId === expected.immutableVersionId && bundle.members.length === 1 && bundle.members[0].role === expected.members[0].role && sameArtifactIdentity(bundle.members[0].identity, expected.members[0].identity);
}
function sameAttachmentHandle(left, right) {
	return left.role === right.role && left.selectionHandle === right.selectionHandle && left.immutableVersionId === right.immutableVersionId && left.members.length === right.members.length && left.members.every((member, index) => {
		const candidate = right.members[index];
		return candidate !== void 0 && member.role === candidate.role && sameArtifactIdentity(member.identity, candidate.identity) && member.bytes.byteLength === candidate.bytes.byteLength && flowBlindV2Sha256(member.bytes) === flowBlindV2Sha256(candidate.bytes);
	});
}
function confirmationRequest(prepared) {
	const problem = prepared.resources.find((resource) => resource.role === PROBLEM_ROLE.role);
	const bundle = prepared.resources.find((resource) => resource.role === PREPARATION_BUNDLE_ROLE.role);
	return Object.freeze({
		recordType: "flowblind-catalog-v2-run-confirmation-request-v1",
		route: Object.freeze({
			methodId: HIDDEN_FLOW_V1_CAPABILITY.methodId,
			methodVersion: HIDDEN_FLOW_V1_CAPABILITY.methodVersion,
			action: "run-and-verify-study"
		}),
		routerPackageVersion: FLOWBLIND_V2_ROUTER_PACKAGE_VERSION,
		familyPackageCompatibilityKey: HIDDEN_FLOW_V1_PACKAGE.compatibilityKey,
		preparationSchemaId: HIDDEN_FLOW_V1_PREPARATION_SCHEMA.schemaId,
		preparationMarkerSha256: prepared.preparationMarker.sha256,
		preparationArtifactSha256: prepared.preparationArtifact.sha256,
		candidateResourceSha256s: Object.freeze(problem?.members.map((member) => member.identity.sha256) ?? []),
		preparedArtifactSetSha256s: Object.freeze(bundle?.members.map((member) => member.identity.sha256) ?? []),
		executionStartBoundary: "confirmed-operation-callback-entry",
		distributedExactlyOnceClaim: false
	});
}
async function settle(host, request, terminal, executionFailure) {
	let settlementFailure;
	try {
		await host.settleConfirmedExecution(request, terminal);
	} catch (error) {
		settlementFailure = error;
	}
	if (executionFailure !== void 0 && settlementFailure !== void 0) throw new AggregateError([executionFailure, settlementFailure], "Hidden-flow execution and host settlement both failed.");
	if (executionFailure !== void 0) throw executionFailure;
	if (settlementFailure !== void 0) throw settlementFailure;
}
function confirmationOutcome(confirmed) {
	if (confirmed.status === "cancelled") return resultFree$1({
		status: "confirmation-required",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		reasonCodes: ["run-confirmation-cancelled"],
		guidance: "A later retry must obtain a new host callback-bracket confirmation."
	});
	if (confirmed.status === "busy") return resultFree$1({
		status: "execution-busy",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		scope: confirmed.scope,
		reasonCodes: [`confirmed-execution-busy-${confirmed.scope}`],
		guidance: "Do not invoke the retained package while the exact execution or package capacity is busy."
	});
	if (confirmed.status === "prior-outcome-unknown") return resultFree$1({
		status: "prior-outcome-unknown",
		containsResults: false,
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		reasonCodes: ["confirmed-execution-prior-outcome-unknown"],
		guidance: "Reconcile the prior marker before any new package invocation.",
		reconciliation: {
			state: "execution-outcome-reconciliation-required",
			phase: "run"
		}
	});
	return null;
}
function directCapabilityCast(value) {
	return value;
}
async function activateHiddenFlowV1Bridge(input) {
	if (HIDDEN_FLOW_V1_DESCRIPTOR.lifecycle !== null || HIDDEN_FLOW_V1_DESCRIPTOR.release.status !== "default-off") throw new HiddenFlowV1BridgeContractError("activation-contract-invalid", "The immutable default hidden-flow descriptor is not default-off.");
	if (typeof input.loader?.loadExact !== "function" || !isRuntimeHiddenFlowV1PackageVerifier(input.verifier) || typeof input.preparationCommitter?.commit !== "function") return {
		status: "authority-unavailable",
		containsResults: false,
		reason: "package-verification-failed"
	};
	let loaded;
	try {
		loaded = await input.loader.loadExact(Object.freeze({
			route: HIDDEN_FLOW_V1_CAPABILITY,
			package: HIDDEN_FLOW_V1_PACKAGE,
			reviewedCandidate: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE
		}), input.signal);
	} catch {
		return {
			status: "authority-unavailable",
			containsResults: false,
			reason: "retained-package-unavailable"
		};
	}
	if (loaded.status === "not-installed") return {
		status: "authority-unavailable",
		containsResults: false,
		reason: "package-not-installed"
	};
	if (loaded.status === "retained-package-unavailable") return {
		status: "authority-unavailable",
		containsResults: false,
		reason: "retained-package-unavailable"
	};
	let verified;
	try {
		verified = await input.verifier.verifyAndMint(loaded.candidate, input.signal);
	} catch {
		return {
			status: "authority-unavailable",
			containsResults: false,
			reason: "package-verification-failed"
		};
	}
	const runtime = resolveVerifiedHiddenFlowV1Package(verified);
	if (verified === null || runtime === null) return {
		status: "authority-unavailable",
		containsResults: false,
		reason: "package-verification-failed"
	};
	let preview;
	try {
		preview = await runtime.declarationPreview(runtime.nativePackageAuthority, input.signal);
	} catch {
		return {
			status: "authority-unavailable",
			containsResults: false,
			reason: "package-verification-failed"
		};
	}
	if (!declarationMatches(preview)) return {
		status: "authority-unavailable",
		containsResults: false,
		reason: "package-verification-failed"
	};
	const reconciliationByPreparation = /* @__PURE__ */ new Map();
	const reportBindingsByUri = /* @__PURE__ */ new Map();
	const runtimeCapability = {
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		authorityRequirementId: HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.requirementId,
		package: HIDDEN_FLOW_V1_PACKAGE,
		preparationSchema: HIDDEN_FLOW_V1_PREPARATION_SCHEMA,
		resultSchema: HIDDEN_FLOW_V1_RESULT_SCHEMA,
		renderer: HIDDEN_FLOW_V1_RENDERER,
		async prepare(invocation) {
			const authorization = authorizedPrepareInvocations.get(invocation);
			authorizedPrepareInvocations.delete(invocation);
			if (authorization === void 0 || invocation.scientist !== authorization.scientist.scientist || invocation.attachments.length !== 1 || invocation.attachments[0] !== authorization.handle) throw new HiddenFlowV1BridgeContractError("preparation-contract-invalid", "Hidden-flow preparation must originate from the explicit bridge route.");
			const problem = resolveRuntimeResourceSnapshot(authorization.snapshot, authorization.request);
			const normalizedProblem = problem === null ? null : normalizeSingleAttachment(problem, {
				role: PROBLEM_ROLE.role,
				memberRole: "problem",
				reference: "problem.json",
				mediaType: "application/json",
				maximumBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes,
				canonicalJson: true
			});
			if (normalizedProblem === null || !sameAttachmentHandle(normalizedProblem, authorization.handle)) throw new HiddenFlowV1BridgeContractError("preparation-contract-invalid", "Hidden-flow preparation requires the exact request-bound canonical problem snapshot.");
			return await prepareHiddenFlow(runtime, input.preparationCommitter, authorization.scientist, normalizedProblem, invocation.signal);
		},
		async run(invocation) {
			const authorization = authorizedRunInvocations.get(invocation);
			authorizedRunInvocations.delete(invocation);
			if (authorization === void 0 || invocation.scientist !== authorization.scientist.scientist || invocation.attachments.length !== 1 || invocation.attachments[0] !== authorization.handle || !isRuntimeConfirmedExecutionHandle(invocation.confirmedExecution, authorization.confirmationRequest)) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "Hidden-flow execution must originate from the exact branded bridge confirmation callback.");
			const prepared = projectPreparedStudy(invocation.preparedStudy);
			const bundle = resolveRuntimeResourceSnapshot(authorization.snapshot, authorization.request);
			if (prepared === null || !samePreparedBinding(prepared.binding, authorization.prepared.binding) || preparationMismatch(prepared, authorization.scientist).length > 0 || bundle === null || !validSingleAttachment(bundle, {
				role: PREPARATION_BUNDLE_ROLE.role,
				memberRole: "preparation-bundle",
				reference: "preparation.json",
				mediaType: "application/json",
				maximumBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes,
				canonicalJson: true
			}) || !sameAttachmentHandle(bundle, authorization.handle) || !runBundleMatches(prepared, bundle) || bundle.members[0].identity.sha256 !== authorization.reconciliationKey) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "Hidden-flow execution requires the exact projected preparation and request-bound retained bundle.");
			return directCapabilityCast(await runHiddenFlow(runtime, authorization.scientist, prepared.binding, bundle, invocation.confirmedExecution, invocation.signal, authorization.reconciliationKey, reconciliationByPreparation, reportBindingsByUri));
		},
		async render(record) {
			const hiddenRecord = record;
			if (!validResultRecord(hiddenRecord, runtime)) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "Cannot render an invalid hidden-flow result record.");
			const bytes = await runtime.readCommittedArtifact(runtime.nativePackageAuthority, hiddenRecord.retainedReport, "report");
			if (!identityMatchesBytes(hiddenRecord.retainedReport.report, bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes)) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "The retained Markdown report bytes do not match the committed receipt.");
			return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		},
		async readResource(uri) {
			const binding = reportBindingsByUri.get(uri);
			if (binding === void 0) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "The resource URI is not bound to a validated result from this activation.");
			const bytes = await runtime.readCommittedArtifact(runtime.nativePackageAuthority, binding, "report");
			if (!identityMatchesBytes(binding.report, bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes)) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "The retained report bytes do not match the receipt.");
			return bytes;
		}
	};
	const integration = {
		integrationId: HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.integrationId,
		integrationVersion: HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.integrationVersion,
		grants: HIDDEN_FLOW_V1_AUTHORITY_REQUIREMENT.requiredGrants,
		capabilities: [runtimeCapability]
	};
	const authorityEvidence = createRuntimeAuthorityIssuer((candidate) => candidate === verified ? integration : null).issue(verified);
	if (authorityEvidence === null) throw new HiddenFlowV1BridgeContractError("activation-contract-invalid", "The exact verified hidden-flow package did not mint v2 authority.");
	const route = async (request) => {
		if (request.action !== "prepare-study" && request.action !== "run-and-verify-study") return resultFree$1({
			status: "unsupported-action",
			containsResults: false,
			reasonCodes: ["unsupported-public-lifecycle-action"],
			guidance: "Use exactly prepare-study or run-and-verify-study."
		});
		const normalized = parseScientist(request.scientist);
		if (!("scientist" in normalized)) return normalized;
		const selection = routeSelection(normalized);
		if (selection !== null) return selection;
		if (!authorityMatches(request.host.authorityEvidence, authorityEvidence)) return authorityUnavailable("package-verification-failed");
		const authority = resolveRuntimeAuthority(request.host.authorityEvidence, HIDDEN_FLOW_V1_CAPABILITY);
		if (authority === null) return authorityUnavailable("package-verification-failed");
		if (request.action === "prepare-study") {
			const attachmentRequest = Object.freeze({
				action: "prepare-study",
				capability: HIDDEN_FLOW_V1_CAPABILITY,
				roles: Object.freeze([PROBLEM_ROLE])
			});
			const problem = await loadSingleAttachment(attachmentRequest, request.host, {
				role: PROBLEM_ROLE.role,
				memberRole: "problem",
				reference: "problem.json",
				mediaType: "application/json",
				maximumBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes,
				canonicalJson: true,
				normalizeIdentity: true
			});
			if (problem === null) return resultFree$1({
				status: "attachment-contract-invalid",
				containsResults: false,
				capability: HIDDEN_FLOW_V1_CAPABILITY,
				reasonCodes: ["hidden-flow-problem-snapshot-invalid"],
				guidance: "Select exactly one immutable canonical stable-JSON problem snapshot."
			});
			const runtimeInvocation = {
				scientist: normalized.scientist,
				attachments: [problem.handle],
				...request.host.signal === void 0 ? {} : { signal: request.host.signal }
			};
			authorizedPrepareInvocations.set(runtimeInvocation, Object.freeze({
				request: attachmentRequest,
				snapshot: problem.raw,
				handle: problem.handle,
				scientist: normalized
			}));
			try {
				return await authority.capability.prepare(runtimeInvocation);
			} finally {
				authorizedPrepareInvocations.delete(runtimeInvocation);
			}
		}
		const prepared = projectPreparedStudy(request.host.preparedStudy);
		if (prepared === null) return resultFree$1({
			status: "preparation-incompatible",
			containsResults: false,
			capability: HIDDEN_FLOW_V1_CAPABILITY,
			reasonCodes: ["prepared-study-binding-invalid"],
			guidance: "Run only the exact retained hidden-flow preparation, marker, version, and package binding."
		});
		const mismatch = preparationMismatch(prepared, normalized);
		if (mismatch.length > 0) return resultFree$1({
			status: "preparation-incompatible",
			containsResults: false,
			capability: HIDDEN_FLOW_V1_CAPABILITY,
			reasonCodes: mismatch,
			guidance: "Run must preserve the exact prepared scientist context and retained bundle."
		});
		const attachmentRequest = Object.freeze({
			action: "run-and-verify-study",
			capability: HIDDEN_FLOW_V1_CAPABILITY,
			roles: Object.freeze([PREPARATION_BUNDLE_ROLE])
		});
		const bundle = await loadSingleAttachment(attachmentRequest, request.host, {
			role: PREPARATION_BUNDLE_ROLE.role,
			memberRole: "preparation-bundle",
			reference: "preparation.json",
			mediaType: "application/json",
			maximumBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes,
			canonicalJson: true
		});
		if (bundle === null || !runBundleMatches(prepared, bundle.handle)) return resultFree$1({
			status: "preparation-incompatible",
			containsResults: false,
			capability: HIDDEN_FLOW_V1_CAPABILITY,
			reasonCodes: ["retained-preparation-bundle-mismatch"],
			guidance: "Load the exact immutable preparation bundle retained with this outer marker."
		});
		const reconciliationKey = bundle.handle.members[0].identity.sha256;
		const existingReconciliation = reconciliationByPreparation.get(reconciliationKey);
		if (existingReconciliation !== void 0) return existingReconciliation;
		if (!isRuntimeConfirmedExecutionAuthority(request.host.confirmedExecution) || typeof request.host.settleConfirmedExecution !== "function") return authorityUnavailable("host-confirmation-authority-unavailable");
		const confirmRequest = confirmationRequest(prepared.binding);
		let callbackRecord;
		let confirmed;
		let executionFailure;
		let terminal = { status: "failed" };
		try {
			confirmed = await request.host.confirmedExecution.withConfirmedExecution(confirmRequest, async (confirmedExecution) => {
				if (!isRuntimeConfirmedExecutionHandle(confirmedExecution, confirmRequest)) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "The confirmation callback supplied an untrusted execution handle.");
				const runtimeInvocation = {
					scientist: normalized.scientist,
					preparedStudy: prepared.binding,
					attachments: [bundle.handle],
					confirmedExecution,
					...request.host.signal === void 0 ? {} : { signal: request.host.signal }
				};
				authorizedRunInvocations.set(runtimeInvocation, Object.freeze({
					request: attachmentRequest,
					snapshot: bundle.raw,
					handle: bundle.handle,
					scientist: normalized,
					prepared,
					confirmationRequest: confirmRequest,
					reconciliationKey
				}));
				try {
					const record = await authority.capability.run(runtimeInvocation);
					callbackRecord = record;
					return record;
				} finally {
					authorizedRunInvocations.delete(runtimeInvocation);
				}
			}, request.host.signal);
			terminal = confirmed.status === "completed" ? { status: "completed" } : confirmed.status === "cancelled" ? { status: "cancelled" } : confirmed.status === "busy" ? {
				status: "busy",
				scope: confirmed.scope
			} : { status: "prior-outcome-unknown" };
		} catch (error) {
			executionFailure = error;
		}
		await settle(request.host, confirmRequest, terminal, executionFailure);
		if (confirmed === void 0) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "Confirmed hidden-flow execution produced no terminal outcome.");
		const terminalResult = confirmationOutcome(confirmed);
		if (terminalResult !== null) return terminalResult;
		if (confirmed.status !== "completed" || callbackRecord === void 0 || confirmed.result !== callbackRecord) throw new HiddenFlowV1BridgeContractError("result-contract-invalid", "The completed result was not the exact object returned by the branded callback.");
		return confirmed.result;
	};
	const readResource = async (evidence, record, signal) => {
		if (!authorityMatches(evidence, authorityEvidence) || !validResultRecord(record, runtime)) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "Resource reads require the exact activation authority and a fully receipt-bound hidden-flow result.");
		const bytes = await runtime.readCommittedArtifact(runtime.nativePackageAuthority, record.retainedReport, "report", signal);
		if (!identityMatchesBytes(record.retainedReport.report, bytes, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes)) throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", "The retained report bytes do not match the committed report identity.");
		return Uint8Array.from(bytes);
	};
	return {
		status: "active",
		activation: Object.freeze({
			descriptor: HIDDEN_FLOW_V1_PRIVATE_DESCRIPTOR,
			authorityEvidence,
			route,
			async render(evidence, record, signal) {
				const bytes = await readResource(evidence, record, signal);
				try {
					return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
				} catch (error) {
					throw new HiddenFlowV1BridgeContractError("resource-contract-invalid", error instanceof Error ? `The committed report is not valid UTF-8: ${error.message}` : "The committed report is not valid UTF-8.");
				}
			},
			readResource
		})
	};
}
//#endregion
//#region tools/catalogResearchV2/package/retainedHiddenV1.ts
function record(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function value(source, key) {
	const candidate = record(source);
	if (candidate === null) return void 0;
	const descriptor = Object.getOwnPropertyDescriptor(candidate, key);
	return descriptor !== void 0 && "value" in descriptor ? descriptor.value : void 0;
}
function identity(source, maximumByteLength = FLOWBLIND_V2_MAX_ARTIFACT_BYTES) {
	const candidate = record(source);
	const byteLength = value(candidate, "byteLength");
	if (candidate === null || typeof byteLength !== "number" || !Number.isSafeInteger(byteLength) || byteLength <= 0 || byteLength > maximumByteLength || !isFlowBlindV2ArtifactIdentity({
		...candidate,
		byteLength: Math.min(byteLength, 16777216)
	})) throw new Error("The retained hidden-flow runtime returned an invalid artifact identity.");
	return Object.freeze({
		reference: candidate.reference,
		byteLength,
		sha256: candidate.sha256,
		mediaType: candidate.mediaType
	});
}
function exactKeys(source, expected) {
	return source !== null && JSON.stringify(Object.keys(source).sort()) === JSON.stringify([...expected].sort());
}
function sameArtifactContent(left, right) {
	return left.byteLength === right.byteLength && left.sha256 === right.sha256 && left.mediaType === right.mediaType;
}
function artifact(reference, mediaType, bytes, signal) {
	throwIfAborted(signal);
	return Object.freeze({
		identity: artifactIdentity$1(reference, mediaType, bytes, signal),
		bytes: Uint8Array.from(bytes)
	});
}
function hiddenInputContext(bundle, signal) {
	throwIfAborted(signal);
	const human = record(bundle.humanContext);
	const goal = value(human, "goal");
	const details = value(human, "details");
	if (typeof goal !== "string" || !(details === null || typeof details === "string")) throw new Error("The retained hidden-flow preparation has invalid human context.");
	let decisionQuestion = null;
	let nextEvidenceIntent = null;
	if (typeof details === "string") {
		let parsed;
		try {
			throwIfAborted(signal);
			parsed = JSON.parse(details);
		} catch (error) {
			throwIfAborted(signal);
			throw new Error("The retained hidden-flow details projection is invalid.", { cause: error });
		}
		const projected = record(parsed);
		const decision = value(projected, "decisionQuestion");
		const next = value(projected, "nextEvidenceIntent");
		if (projected === null || Object.keys(projected).length !== 2 || !(decision === null || typeof decision === "string") || !(next === null || typeof next === "string") || stableCompactJson(parsed) !== details) throw new Error("The retained hidden-flow details projection is not canonical.");
		decisionQuestion = decision;
		nextEvidenceIntent = next;
	}
	return Object.freeze({
		researchGoal: goal,
		decisionQuestion,
		nextEvidenceIntent
	});
}
function problemHandle(bytes, signal) {
	const problemIdentity = artifactIdentity$1("problem.json", "application/json", bytes, signal);
	return Object.freeze({
		role: "problem-snapshot",
		selectionHandle: `sha256:${problemIdentity.sha256}`,
		immutableVersionId: `sha256:${problemIdentity.sha256}`,
		members: Object.freeze([Object.freeze({
			role: "problem",
			identity: problemIdentity,
			bytes: Uint8Array.from(bytes)
		})])
	});
}
function preparationHandle(bytes, signal) {
	const preparationIdentity = artifactIdentity$1("preparation.json", "application/json", bytes, signal);
	return Object.freeze({
		role: "preparation-bundle",
		selectionHandle: `sha256:${preparationIdentity.sha256}`,
		immutableVersionId: `sha256:${preparationIdentity.sha256}`,
		members: Object.freeze([Object.freeze({
			role: "preparation-bundle",
			identity: preparationIdentity,
			bytes: Uint8Array.from(bytes)
		})])
	});
}
function resourceBinding(handle) {
	return Object.freeze({
		role: handle.role,
		selectionHandle: handle.selectionHandle,
		immutableVersionId: handle.immutableVersionId,
		members: Object.freeze(handle.members.map((member) => Object.freeze({
			role: member.role,
			identity: Object.freeze({ ...member.identity })
		})))
	});
}
async function loadHiddenV1AttachmentSelection(action, inputRoot, signal) {
	throwIfAborted(signal);
	const files = await listOrdinaryFiles(inputRoot, {
		maximumFiles: action === "prepare-study" ? 1 : 2,
		maximumDepth: 4,
		maximumBytesEach: action === "prepare-study" ? HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes : HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes
	}, signal);
	throwIfAborted(signal);
	if (action === "prepare-study") {
		if (files.length !== 1 || files[0].reference !== "problem.json") throw new Error("Hidden-flow preparation requires the mounted problem at the exact relative reference problem.json.");
		parseCanonicalJson(files[0].bytes, "Hidden-flow problem", "stable", signal);
		return Object.freeze({ attachment: problemHandle(files[0].bytes, signal) });
	}
	const bundleFiles = files.filter((file) => basename(file.reference) === "preparation.json");
	const markerFiles = files.filter((file) => basename(file.reference) === "preparation-commit.json");
	if (files.length !== 2 || bundleFiles.length !== 1 || markerFiles.length !== 1 || dirname(bundleFiles[0].reference) !== dirname(markerFiles[0].reference)) throw new Error("Hidden-flow run requires one exact preparation.json and preparation-commit.json asset.");
	const bundleFile = bundleFiles[0];
	const markerFile = markerFiles[0];
	const expectedDirectory = `flowblind-hidden-flow-preparation-${bundleFile.sha256}`;
	if (bundleFile.reference !== `${expectedDirectory}/preparation.json` || markerFile.reference !== `${expectedDirectory}/preparation-commit.json`) throw new Error("The hidden-flow preparation asset must preserve its exact content-addressed directory with preparation.json and preparation-commit.json.");
	const bundle = parseCanonicalJson(bundleFile.bytes, "Hidden-flow preparation bundle", "stable", signal);
	const marker = parseCanonicalJson(markerFile.bytes, "Hidden-flow preparation marker", "compact", signal);
	const markerCapability = record(marker.capability);
	const markerPackage = record(marker.package);
	const markerProblem = identity(marker.problemSnapshot, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes);
	const reviewedCommits = record(marker.reviewedCommits);
	const markerPreparation = record(marker.preparation);
	const markerNativeBundle = identity(value(markerPreparation, "nativeBundle"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes);
	const markerV2Bundle = identity(value(markerPreparation, "v2Bundle"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes);
	const publication = record(marker.publication);
	const bundleProblem = record(bundle.problem);
	const bundleProblemIdentity = identity(value(bundleProblem, "identity"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes);
	const bundleIdentity = artifactIdentity$1("preparation.json", "application/json", bundleFile.bytes, signal);
	const markerIdentity = artifactIdentity$1("preparation-commit.json", "application/json", markerFile.bytes, signal);
	if (!exactKeys(marker, [
		"$schema",
		"schemaVersion",
		"recordType",
		"status",
		"capability",
		"package",
		"reviewedCommits",
		"problemSnapshot",
		"preparation",
		"publication"
	]) || marker.$schema !== "https://flowblind.local/schemas/flowblind-v2-hidden-flow-preparation-marker-v1.schema.json" || marker.schemaVersion !== 1 || marker.recordType !== "flowblind-v2-hidden-flow-preparation-marker-v1" || marker.status !== "committed" || !exactKeys(markerCapability, [
		"familyId",
		"methodId",
		"methodVersion"
	]) || !sameCapabilityIdentity(markerCapability, HIDDEN_FLOW_V1_CAPABILITY) || !exactKeys(markerPackage, [
		"packageId",
		"packageVersion",
		"compatibilityKey"
	]) || !samePackageBinding(markerPackage, HIDDEN_FLOW_V1_PACKAGE) || !exactKeys(reviewedCommits, ["authorityRuntimeBase", "independentHardening"]) || reviewedCommits?.authorityRuntimeBase !== HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.reviewedCommits.authorityRuntimeBase || reviewedCommits?.independentHardening !== HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.reviewedCommits.independentHardening || !exactKeys(markerPreparation, ["nativeBundle", "v2Bundle"]) || !exactKeys(publication, [
		"marker",
		"pointOfNoReturn",
		"distributedExactlyOnceClaim"
	]) || publication?.marker !== "preparation-commit.json" || publication?.pointOfNoReturn !== "exclusive-preparation-commit-marker" || publication?.distributedExactlyOnceClaim !== false || markerProblem.reference !== "problem.json" || markerProblem.mediaType !== "application/json" || bundleProblem === null || bundleProblem.canonicalization !== "stable-json-v1" || !sameArtifactContent(markerProblem, bundleProblemIdentity) || bundleProblemIdentity.reference !== `flowblind-catalog-hidden-flow-problem-${bundleProblemIdentity.sha256}.json` || markerNativeBundle.reference !== `flowblind-catalog-hidden-flow-preparation-${markerNativeBundle.sha256}.json` || !sameArtifactContent(markerNativeBundle, bundleIdentity) || markerV2Bundle.reference !== "preparation.json" || !sameArtifactIdentity(markerV2Bundle, bundleIdentity)) throw new Error("The hidden-flow preparation marker does not bind the selected retained bundle.");
	const problem = Object.freeze({
		role: "problem-snapshot",
		selectionHandle: `sha256:${markerProblem.sha256}`,
		immutableVersionId: `sha256:${markerProblem.sha256}`,
		members: Object.freeze([Object.freeze({
			role: "problem",
			identity: markerProblem,
			bytes: /* @__PURE__ */ new Uint8Array()
		})])
	});
	const preparation = preparationHandle(bundleFile.bytes, signal);
	const preparedStudy = Object.freeze({
		capability: HIDDEN_FLOW_V1_CAPABILITY,
		package: HIDDEN_FLOW_V1_PACKAGE,
		preparationSchema: HIDDEN_FLOW_V1_PREPARATION_SCHEMA,
		humanContext: hiddenInputContext(bundle, signal),
		preparationMarker: markerIdentity,
		preparationArtifact: bundleIdentity,
		resources: Object.freeze([resourceBinding(problem), resourceBinding(preparation)])
	});
	return Object.freeze({
		attachment: preparation,
		preparedStudy
	});
}
async function loadRetainedRuntime(packageEvidence, verifierPort, signal) {
	throwIfAborted(signal);
	const retained = await verifierPort.verifyRetainedPackage(packageEvidence, "hidden-flow-v1", signal);
	throwIfAborted(signal);
	if (retained === null) throw new Error("The retained hidden-flow closure did not pass its exact tree manifest.");
	throwIfAborted(signal);
	const verifier = await import(pathToFileURL(resolve(retained.rootPath, "flowblind-hidden-flow-capability-verification-v1.mjs")).href);
	throwIfAborted(signal);
	const verified = await verifier.verifyFlowBlindHiddenFlowPackage(signal);
	throwIfAborted(signal);
	const authority = verifier.flowBlindHiddenFlowPackageRuntimeAuthority(verified.runtimeAuthority);
	throwIfAborted(signal);
	if (authority === null) throw new Error("The retained hidden-flow verifier did not mint same-module runtime authority.");
	throwIfAborted(signal);
	const runtime = await import(`${pathToFileURL(verified.runtimePath).href}?sha256=${verified.lock.publicRuntime.sha256}`);
	throwIfAborted(signal);
	if (runtime.catalogHiddenFlowRuntimeVersion !== "1.1.0" || typeof runtime.callCatalogHiddenFlowAction !== "function" || typeof runtime.catalogHiddenFlowDeclarationPreview !== "function" || typeof runtime.assertCatalogHiddenFlowActionResponseSemanticContract !== "function") throw new Error("The retained hidden-flow runtime does not expose its reviewed bridge entry points.");
	throwIfAborted(signal);
	return Object.freeze({
		module: runtime,
		authority
	});
}
function unavailableForOutputLimit(artifact = "verified-run.json") {
	return Object.freeze({
		schemaVersion: 1,
		capabilityVersion: "1.1.0",
		status: "unavailable",
		containsResults: false,
		deterministicReplayMatched: false,
		outcome: Object.freeze({
			kind: "unavailable",
			evidenceState: "failed",
			reason: "output-resource-limit",
			detail: `The individual ${artifact} file exceeds its v2 prepublication ceiling.`
		})
	});
}
function hiddenReportReferences(preparationSha256) {
	const directory = `flowblind-hidden-flow-study-${preparationSha256}`;
	return Object.freeze({
		directory,
		json: `${directory}/verified-run.json`,
		markdown: `${directory}/report.md`,
		verification: `${directory}/report-verification.json`
	});
}
async function publishHiddenReportSet(input) {
	throwIfAborted(input.signal);
	if (input.rawJson.bytes.byteLength > HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes) throw new Error("The retained hidden-flow verified run exceeds the v2 prepublication ceiling.");
	input.module.assertCatalogHiddenFlowActionResponseSemanticContract(input.rawResponse, { verifiedRun: input.raw });
	const verifiedRunRecord = parseCanonicalJson(input.rawJson.bytes, "Retained hidden-flow verified run", "stable", input.signal);
	if (input.rawJson.bytes.byteLength > HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes) throw new Error("The retained hidden-flow verified run exceeds the v2 prepublication ceiling.");
	const markdownBytes = Uint8Array.from(input.rawMarkdown.bytes);
	if (markdownBytes.byteLength > HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes) throw new Error("The retained hidden-flow Markdown exceeds its reviewed byte limit.");
	const references = hiddenReportReferences(input.preparation.sha256);
	const verifiedRun = artifact(references.json, "application/json", input.rawJson.bytes, input.signal);
	if (verifiedRun.identity.byteLength !== input.rawJson.identity.byteLength || verifiedRun.identity.sha256 !== input.rawJson.identity.sha256) throw new Error("The v2 hidden-flow mapping changed retained verified-run bytes.");
	const report = artifact(references.markdown, "text/markdown", markdownBytes, input.signal);
	if (report.identity.byteLength !== input.rawMarkdown.identity.byteLength || report.identity.sha256 !== input.rawMarkdown.identity.sha256) throw new Error("The v2 hidden-flow report mapping changed retained Markdown bytes.");
	const verificationRecord = Object.freeze({
		$schema: "https://flowblind.local/schemas/flowblind-catalog-v2-hidden-flow-report-verification-v1.schema.json",
		schemaVersion: 1,
		recordType: "flowblind-catalog-v2-hidden-flow-report-verification-v1",
		status: "verified-report-complete",
		capability: Object.freeze({
			capabilityId: "finite-basis-hidden-flow-v1",
			capabilityVersion: "1.1.0",
			methodFamily: "finite-basis-observation-compatible-hidden-flow-v1",
			packageVersion: "1.0.0"
		}),
		preparation: Object.freeze({
			id: value(record(verifiedRunRecord.preparation), "id"),
			associationSha256: value(record(verifiedRunRecord.preparation), "associationSha256"),
			bundle: value(record(verifiedRunRecord.preparation), "artifact")
		}),
		problem: Object.freeze({
			id: value(record(verifiedRunRecord.problem), "id"),
			identity: value(record(verifiedRunRecord.problem), "identity")
		}),
		software: verifiedRunRecord.software,
		deterministicReplay: verifiedRunRecord.deterministicReplay,
		artifacts: Object.freeze({
			json: verifiedRun.identity,
			markdown: report.identity
		}),
		bridge: Object.freeze({
			outerPreparationMarker: input.outerPreparationMarker,
			maximumVerifiedRunBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes,
			markerInstalledLast: true
		}),
		publication: Object.freeze({
			directory: references.directory,
			commitMarker: "report-verification.json",
			pointOfNoReturn: "exclusive-report-verification-commit-marker",
			policy: "deterministic-exclusive-create-or-verify-content-then-commit-marker",
			distributedExactlyOnceClaim: false
		})
	});
	const verification = artifact(references.verification, "application/json", canonicalCompactJsonBytes(verificationRecord), input.signal);
	const response = Object.freeze({
		...input.rawResponse,
		artifacts: Object.freeze({
			json: verifiedRun.identity,
			markdown: report.identity,
			verification: verification.identity
		}),
		publication: Object.freeze({
			state: "marker-verified",
			promotable: true,
			directory: references.directory,
			pointOfNoReturn: "exclusive-report-verification-commit-marker",
			policy: "deterministic-exclusive-create-or-verify-content-then-commit-marker",
			distributedExactlyOnceClaim: false
		})
	});
	throwIfAborted(input.signal, "The hidden-flow run was cancelled before publication.");
	await installDeterministicFile(input.outputRoot, references.json, verifiedRun.bytes, "application/json", input.signal);
	throwIfAborted(input.signal);
	await installDeterministicFile(input.outputRoot, references.markdown, report.bytes, "text/markdown", input.signal);
	throwIfAborted(input.signal);
	throwIfAborted(input.signal, "The hidden-flow run was cancelled before the commit marker.");
	await installDeterministicFile(input.outputRoot, references.verification, verification.bytes, "application/json", void 0);
	await verifyHiddenReportBinding(input.outputRoot, Object.freeze({
		preparationBundleSha256: input.preparation.sha256,
		preparationMarkerSha256: input.outerPreparationMarker.sha256,
		directory: references.directory,
		verifiedRun: verifiedRun.identity,
		report: report.identity,
		verification: verification.identity
	}), void 0);
	return Object.freeze({
		response,
		verifiedRun,
		report,
		verification,
		verifiedRunRecord,
		verificationRecord,
		markerInstalledLast: true
	});
}
function stableJsonRecordMatchesBytes(value, bytes) {
	const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
	return stableCompactJson(value) === text || stableJson$1(value) === text;
}
function assertHiddenReportSet(reportSet, signal) {
	throwIfAborted(signal);
	const identities = [
		reportSet.verifiedRun,
		reportSet.report,
		reportSet.verification
	];
	if (reportSet.markerInstalledLast !== true || reportSet.verifiedRun.bytes.byteLength > HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes || identities.some((entry) => sha256Bytes(entry.bytes, signal) !== entry.identity.sha256 || entry.bytes.byteLength !== entry.identity.byteLength) || !stableJsonRecordMatchesBytes(reportSet.verifiedRunRecord, reportSet.verifiedRun.bytes) || stableCompactJson(reportSet.verificationRecord) !== new TextDecoder("utf-8", { fatal: true }).decode(reportSet.verification.bytes) || !sameArtifactIdentity(reportSet.response.artifacts.json, reportSet.verifiedRun.identity) || !sameArtifactIdentity(reportSet.response.artifacts.markdown, reportSet.report.identity) || !sameArtifactIdentity(reportSet.response.artifacts.verification, reportSet.verification.identity)) throw new Error("The adapted hidden-flow report set failed its marker-last semantic contract.");
}
async function verifyHiddenReportBinding(outputRoot, binding, signal) {
	throwIfAborted(signal);
	const references = hiddenReportReferences(binding.preparationBundleSha256);
	if (binding.directory !== references.directory || binding.verifiedRun.reference !== references.json || binding.report.reference !== references.markdown || binding.verification.reference !== references.verification) throw new Error("The hidden-flow resource binding is not preparation-derived.");
	const verifiedRun = await readStableFile(outputRoot, references.json, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes, binding.verifiedRun, signal);
	throwIfAborted(signal);
	const report = await readStableFile(outputRoot, references.markdown, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes, binding.report, signal);
	throwIfAborted(signal);
	const marker = await readStableFile(outputRoot, references.verification, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes, binding.verification, signal);
	throwIfAborted(signal);
	const verifiedRunRecord = parseCanonicalJson(verifiedRun.bytes, "Hidden-flow verified run", "stable", signal);
	const markerRecord = parseCanonicalJson(marker.bytes, "Hidden-flow report marker", "compact", signal);
	const markerArtifacts = record(markerRecord.artifacts);
	const markerCapability = record(markerRecord.capability);
	const bridge = record(markerRecord.bridge);
	const outerPreparationMarker = identity(value(bridge, "outerPreparationMarker"));
	const markerPreparation = record(markerRecord.preparation);
	const markerProblem = record(markerRecord.problem);
	const markerPublication = record(markerRecord.publication);
	const verifiedPreparation = record(verifiedRunRecord.preparation);
	const verifiedProblem = record(verifiedRunRecord.problem);
	const markerBundle = identity(value(markerPreparation, "bundle"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes);
	const markerJson = identity(value(markerArtifacts, "json"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes);
	const markerMarkdown = identity(value(markerArtifacts, "markdown"));
	const markerProblemIdentity = identity(value(markerProblem, "identity"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes);
	if (!exactKeys(markerRecord, [
		"$schema",
		"schemaVersion",
		"recordType",
		"status",
		"capability",
		"preparation",
		"problem",
		"software",
		"deterministicReplay",
		"artifacts",
		"bridge",
		"publication"
	]) || markerRecord.$schema !== "https://flowblind.local/schemas/flowblind-catalog-v2-hidden-flow-report-verification-v1.schema.json" || markerRecord.schemaVersion !== 1 || markerRecord.status !== "verified-report-complete" || markerRecord.recordType !== "flowblind-catalog-v2-hidden-flow-report-verification-v1" || !exactKeys(markerCapability, [
		"capabilityId",
		"capabilityVersion",
		"methodFamily",
		"packageVersion"
	]) || markerCapability?.capabilityId !== "finite-basis-hidden-flow-v1" || markerCapability?.capabilityVersion !== "1.1.0" || markerCapability?.methodFamily !== "finite-basis-observation-compatible-hidden-flow-v1" || markerCapability?.packageVersion !== "1.0.0" || !exactKeys(markerArtifacts, ["json", "markdown"]) || !sameArtifactIdentity(markerJson, binding.verifiedRun) || !sameArtifactIdentity(markerMarkdown, binding.report) || !exactKeys(markerPreparation, [
		"id",
		"associationSha256",
		"bundle"
	]) || markerBundle.sha256 !== binding.preparationBundleSha256 || markerBundle.reference !== `flowblind-catalog-hidden-flow-preparation-${markerBundle.sha256}.json` || value(verifiedPreparation, "id") !== value(markerPreparation, "id") || value(verifiedPreparation, "associationSha256") !== value(markerPreparation, "associationSha256") || !sameArtifactIdentity(identity(value(verifiedPreparation, "artifact"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes), markerBundle) || !exactKeys(markerProblem, ["id", "identity"]) || value(verifiedProblem, "id") !== value(markerProblem, "id") || !sameArtifactIdentity(identity(value(verifiedProblem, "identity"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumProblemSnapshotBytes), markerProblemIdentity) || stableCompactJson(markerRecord.software) !== stableCompactJson(verifiedRunRecord.software) || stableCompactJson(markerRecord.deterministicReplay) !== stableCompactJson(verifiedRunRecord.deterministicReplay) || !/^[a-f0-9]{64}$/u.test(binding.preparationMarkerSha256) || !exactKeys(bridge, [
		"outerPreparationMarker",
		"maximumVerifiedRunBytes",
		"markerInstalledLast"
	]) || outerPreparationMarker.reference !== "preparation-commit.json" || outerPreparationMarker.sha256 !== binding.preparationMarkerSha256 || value(bridge, "maximumVerifiedRunBytes") !== HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes || value(bridge, "markerInstalledLast") !== true || !exactKeys(markerPublication, [
		"directory",
		"commitMarker",
		"pointOfNoReturn",
		"policy",
		"distributedExactlyOnceClaim"
	]) || markerPublication?.directory !== references.directory || markerPublication?.commitMarker !== "report-verification.json" || markerPublication?.pointOfNoReturn !== "exclusive-report-verification-commit-marker" || markerPublication?.policy !== "deterministic-exclusive-create-or-verify-content-then-commit-marker" || markerPublication?.distributedExactlyOnceClaim !== false) throw new Error("The hidden-flow report marker does not bind the exact cold resource.");
	throwIfAborted(signal);
	return Object.freeze({
		verifiedRun: Object.freeze({
			identity: binding.verifiedRun,
			bytes: verifiedRun.bytes
		}),
		report: Object.freeze({
			identity: binding.report,
			bytes: report.bytes
		}),
		verification: Object.freeze({
			identity: binding.verification,
			bytes: marker.bytes
		}),
		verifiedRunRecord,
		verificationRecord: markerRecord
	});
}
function hiddenResponseFromCommitted(input) {
	const problem = record(input.verified.verifiedRunRecord.problem);
	const review = record(input.verified.verifiedRunRecord.review);
	const outcome = record(input.verified.verifiedRunRecord.outcome);
	if (problem === null || review === null || outcome === null) throw new Error("The committed hidden-flow verified run cannot reconstruct its response.");
	return Object.freeze({
		schemaVersion: 1,
		capabilityVersion: "1.1.0",
		status: "report-complete",
		containsResults: outcome.kind !== "unavailable",
		humanContext: input.verified.verifiedRunRecord.humanContext,
		problem: Object.freeze({
			id: problem.id,
			title: problem.title,
			targetId: problem.targetId,
			targetType: problem.targetType
		}),
		review: Object.freeze({
			authorityVersion: review.authorityVersion,
			reviewScope: review.reviewScope,
			claimBoundary: review.claimBoundary
		}),
		deterministicReplayMatched: true,
		outcome,
		artifacts: Object.freeze({
			json: input.verified.verifiedRun.identity,
			markdown: input.verified.report.identity,
			verification: input.verified.verification.identity
		}),
		publication: Object.freeze({
			state: "marker-verified",
			promotable: true,
			directory: input.directory,
			pointOfNoReturn: "exclusive-report-verification-commit-marker",
			policy: "deterministic-exclusive-create-or-verify-content-then-commit-marker",
			distributedExactlyOnceClaim: false
		})
	});
}
function recoveredHiddenReportSet(input) {
	throwIfAborted(input.signal);
	const response = hiddenResponseFromCommitted({
		verified: input.verified,
		directory: input.directory
	});
	const nativeResponse = Object.freeze({
		...response,
		artifacts: Object.freeze({
			json: Object.freeze({
				...input.verified.verifiedRun.identity,
				reference: `flowblind-catalog-hidden-flow-run-${input.verified.verifiedRun.identity.sha256}.json`
			}),
			markdown: Object.freeze({
				...input.verified.report.identity,
				reference: `flowblind-catalog-hidden-flow-report-${input.verified.report.identity.sha256}.md`
			})
		}),
		publication: Object.freeze({
			state: "uncommitted-core-bytes",
			promotable: false
		})
	});
	input.module.assertCatalogHiddenFlowActionResponseSemanticContract(nativeResponse, { verifiedRun: input.verified.verifiedRunRecord });
	const reportSet = Object.freeze({
		response,
		verifiedRun: input.verified.verifiedRun,
		report: input.verified.report,
		verification: input.verified.verification,
		verifiedRunRecord: input.verified.verifiedRunRecord,
		verificationRecord: input.verified.verificationRecord,
		markerInstalledLast: true
	});
	assertHiddenReportSet(reportSet, input.signal);
	return reportSet;
}
function hiddenPriorOutcome(detail) {
	const unavailableArtifact = Object.freeze({
		identity: null,
		bytes: /* @__PURE__ */ new Uint8Array()
	});
	return Object.freeze({
		kind: "marker-verified-reconciliation-required",
		detail,
		reportSet: Object.freeze({
			response: Object.freeze({}),
			verifiedRun: unavailableArtifact,
			report: unavailableArtifact,
			verification: unavailableArtifact,
			verifiedRunRecord: Object.freeze({}),
			verificationRecord: Object.freeze({}),
			markerInstalledLast: true
		})
	});
}
async function inspectHiddenCommittedRun(input) {
	throwIfAborted(input.signal);
	const references = hiddenReportReferences(input.preparation.sha256);
	let directoryState;
	try {
		directoryState = await inspectOrdinaryDirectory(input.outputRoot, references.directory, input.signal);
		throwIfAborted(input.signal);
	} catch {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: "The deterministic hidden-flow report path could not be resolved safely."
		});
	}
	if (directoryState === "absent") return Object.freeze({ kind: "absent" });
	try {
		if (await readOrReconcileDeterministicFile(input.outputRoot, references.verification, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes, "application/json", input.signal) === null) return Object.freeze({ kind: "absent" });
	} catch {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: "The deterministic hidden-flow report marker could not be resolved safely."
		});
	}
	let files;
	try {
		files = await listOrdinaryFiles(resolve(input.outputRoot, references.directory), {
			maximumFiles: 3,
			maximumDepth: 1,
			maximumBytesEach: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes
		}, input.signal);
		throwIfAborted(input.signal);
	} catch {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: "The deterministic hidden-flow report directory could not be inspected safely."
		});
	}
	const byReference = new Map(files.map((file) => [file.reference, file]));
	const expected = [
		"verified-run.json",
		"report.md",
		"report-verification.json"
	];
	if (files.length !== expected.length || expected.some((reference) => !byReference.has(reference))) return Object.freeze({
		kind: "prior-outcome-unknown",
		detail: "A marker-committed hidden-flow report set is incomplete or non-canonical."
	});
	try {
		const markerFile = byReference.get("report-verification.json");
		const markerArtifacts = record(parseCanonicalJson(markerFile.bytes, "Committed hidden-flow report marker", "compact", input.signal).artifacts);
		const verifiedRun = identity(value(markerArtifacts, "json"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes);
		const report = identity(value(markerArtifacts, "markdown"));
		const verification = artifactIdentity$1(references.verification, "application/json", markerFile.bytes, input.signal);
		const verified = await verifyHiddenReportBinding(input.outputRoot, Object.freeze({
			preparationBundleSha256: input.preparation.sha256,
			preparationMarkerSha256: input.outerPreparationMarker.sha256,
			directory: references.directory,
			verifiedRun,
			report,
			verification
		}), input.signal);
		throwIfAborted(input.signal);
		const reportSet = recoveredHiddenReportSet({
			module: input.module,
			verified,
			directory: references.directory,
			...input.signal === void 0 ? {} : { signal: input.signal }
		});
		return Object.freeze({
			kind: "recovered",
			value: Object.freeze({
				kind: "report-set",
				reportSet
			})
		});
	} catch (error) {
		throwIfAborted(input.signal);
		return Object.freeze({
			kind: "prior-outcome-unknown",
			detail: error instanceof Error ? error.message : "The committed hidden-flow report could not be revalidated safely."
		});
	}
}
async function executeHiddenRetainedRun(input) {
	throwIfAborted(input.signal);
	const raw = await input.retained.module.callCatalogHiddenFlowAction("run-and-verify-study", input.invocation.input, {
		preparationBundleBytes: input.invocation.preparationBundleSnapshot,
		...input.signal === void 0 ? {} : { signal: input.signal }
	}, input.retained.authority);
	throwIfAborted(input.signal);
	const rawCall = record(raw);
	const response = record(value(rawCall, "response"));
	const artifacts = record(value(rawCall, "artifacts"));
	if (response === null) throw new Error("The retained hidden-flow run returned no response.");
	if (response.status === "refused") {
		input.retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(response);
		return Object.freeze({
			kind: "refused",
			response
		});
	}
	if (response.status === "unavailable") {
		input.retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(response);
		return Object.freeze({
			kind: "unavailable",
			response
		});
	}
	if (artifacts === null) throw new Error("The retained hidden-flow report omitted its in-memory artifacts.");
	const jsonArtifact = record(artifacts.json);
	const markdownArtifact = record(artifacts.markdown);
	const jsonBytes = value(jsonArtifact, "bytes");
	const markdownBytes = value(markdownArtifact, "bytes");
	if (!(jsonBytes instanceof Uint8Array) || !(markdownBytes instanceof Uint8Array)) throw new Error("The retained hidden-flow report artifacts are invalid.");
	if (jsonBytes.byteLength > input.invocation.outputLimits.maximumV2VerifiedRunBytes) {
		const unavailable = unavailableForOutputLimit();
		input.retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(unavailable);
		return Object.freeze({
			kind: "unavailable",
			response: unavailable
		});
	}
	if (markdownBytes.byteLength > HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkdownBytes) {
		const unavailable = unavailableForOutputLimit("report.md");
		input.retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(unavailable);
		return Object.freeze({
			kind: "unavailable",
			response: unavailable
		});
	}
	const rawVerifiedRun = parseCanonicalJson(jsonBytes, "Retained hidden-flow verified run", "stable", input.signal);
	const reportSet = await publishHiddenReportSet({
		outputRoot: input.outputRoot,
		raw: rawVerifiedRun,
		rawResponse: response,
		rawJson: Object.freeze({
			identity: identity(jsonArtifact, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes),
			bytes: jsonBytes
		}),
		rawMarkdown: Object.freeze({
			identity: identity(markdownArtifact),
			bytes: markdownBytes
		}),
		preparation: input.preparation,
		outerPreparationMarker: input.invocation.outerPreparationMarker,
		...input.signal === void 0 ? {} : { signal: input.signal },
		module: input.retained.module
	});
	return Object.freeze({
		kind: "report-set",
		reportSet
	});
}
async function hiddenRuntimeCandidate(retained, outputRoot, signal) {
	throwIfAborted(signal);
	const runtime = {
		evidence: Object.freeze({
			reviewedCommits: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.reviewedCommits,
			packageLock: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.packageLock,
			runtime: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.runtime,
			review: HIDDEN_FLOW_V1_REVIEWED_CANDIDATE.review,
			outputPolicy: Object.freeze({
				nativeMaximumVerifiedRunBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumNativeVerifiedRunBytes,
				bridgeMaximumVerifiedRunBytes: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes,
				enforcement: "prepublication-v2-ceiling-required"
			})
		}),
		nativePackageAuthority: retained.authority,
		async declarationPreview(authority) {
			throwIfAborted(signal);
			if (authority !== retained.authority) throw new Error("The retained hidden-flow authority is not live in this verifier module.");
			throwIfAborted(signal);
			const preview = await retained.module.catalogHiddenFlowDeclarationPreview(retained.authority);
			throwIfAborted(signal);
			const declaration = record(value(preview, "declaration"));
			const capability = record(value(declaration, "capability"));
			const reviewPolicy = record(value(declaration, "reviewPolicy"));
			if (declaration === null || capability === null || reviewPolicy === null) throw new Error("The retained hidden-flow declaration is unavailable.");
			return Object.freeze({
				capabilityId: capability.capabilityId,
				capabilityVersion: capability.capabilityVersion,
				methodFamily: capability.methodFamily,
				packageVersion: declaration.packageVersion,
				reviewAuthority: reviewPolicy.authorityVersion,
				reviewPolicy: `${String(reviewPolicy.id)}@${String(reviewPolicy.policyVersion)}`,
				reviewScope: reviewPolicy.reviewScope
			});
		},
		async prepare(authority, invocation) {
			const operationSignal = invocation.signal ?? signal;
			throwIfAborted(operationSignal);
			if (authority !== retained.authority) throw new Error("The retained hidden-flow authority is invalid.");
			throwIfAborted(operationSignal);
			const raw = await retained.module.callCatalogHiddenFlowAction("prepare-study", invocation.input, {
				selectedProblemBytes: invocation.selectedProblemSnapshot,
				...operationSignal === void 0 ? {} : { signal: operationSignal }
			}, retained.authority);
			throwIfAborted(operationSignal);
			const rawRecord = record(raw);
			const response = value(rawRecord, "response");
			const bundle = value(rawRecord, "bundle");
			retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(response);
			const responseRecord = record(response);
			if (responseRecord?.status !== "prepared-awaiting-confirmation" || !(bundle instanceof Object && record(bundle) !== null)) return Object.freeze({
				response,
				bundle: null
			});
			const rawBytes = value(bundle, "bytes");
			if (!(rawBytes instanceof Uint8Array)) throw new Error("The retained hidden-flow preparation omitted its exact bundle bytes.");
			parseCanonicalJson(rawBytes, "Retained hidden-flow preparation bundle", "stable", operationSignal);
			retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(responseRecord);
			return Object.freeze({
				response: responseRecord,
				bundle: artifact(identity(bundle, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes).reference, "application/json", rawBytes, operationSignal)
			});
		},
		async run(authority, invocation) {
			const operationSignal = invocation.signal ?? signal;
			throwIfAborted(operationSignal);
			if (authority !== retained.authority || !isRuntimeHiddenFlowV1ConfirmedInvocation(invocation.confirmedInvocation)) throw new Error("The retained hidden-flow run lacks exact package and confirmation authority.");
			const preparation = artifactIdentity$1("preparation.json", "application/json", invocation.preparationBundleSnapshot, operationSignal);
			throwIfAborted(operationSignal);
			return runRetainedWithRestartGuard({
				inspect: () => inspectHiddenCommittedRun({
					outputRoot,
					preparation,
					outerPreparationMarker: invocation.outerPreparationMarker,
					module: retained.module,
					...operationSignal === void 0 ? {} : { signal: operationSignal }
				}),
				execute: () => executeHiddenRetainedRun({
					retained,
					outputRoot,
					invocation,
					preparation,
					...operationSignal === void 0 ? {} : { signal: operationSignal }
				}),
				priorOutcome: hiddenPriorOutcome,
				...operationSignal === void 0 ? {} : { signal: operationSignal }
			});
		},
		assertPreparation(authority, response, bundle) {
			throwIfAborted(signal);
			if (authority !== retained.authority || response.status === "prepared-awaiting-confirmation" && (bundle === null || !sameArtifactIdentity(response.preparationBundle, bundle.identity) || sha256Bytes(bundle.bytes, signal) !== bundle.identity.sha256 || !stableJsonRecordMatchesBytes(parseCanonicalJson(bundle.bytes, "Retained hidden-flow preparation bundle", "stable", signal), bundle.bytes))) throw new Error("The adapted hidden-flow preparation failed verification.");
			retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(response);
			throwIfAborted(signal);
		},
		assertActionResponse(authority, response) {
			throwIfAborted(signal);
			if (authority !== retained.authority) throw new Error("The retained hidden-flow action authority is invalid.");
			retained.module.assertCatalogHiddenFlowActionResponseSemanticContract(response);
			throwIfAborted(signal);
		},
		assertReportSet(authority, reportSet) {
			throwIfAborted(signal);
			if (authority !== retained.authority) throw new Error("The retained hidden-flow report authority is invalid.");
			assertHiddenReportSet(reportSet, signal);
		},
		async readCommittedArtifact(authority, binding, role) {
			if (authority !== retained.authority || role !== "report") throw new Error("Only the exact retained authority may read a committed hidden-flow report.");
			throwIfAborted(signal);
			const verified = await verifyHiddenReportBinding(outputRoot, binding, signal);
			throwIfAborted(signal);
			return verified.report.bytes;
		}
	};
	return Object.freeze(runtime);
}
async function preparationCommitter(outputRoot, request, signal) {
	throwIfAborted(signal);
	const directory = `flowblind-hidden-flow-preparation-${request.preparationBundle.identity.sha256}`;
	const preparationReference = `${directory}/preparation.json`;
	const markerReference = `${directory}/preparation-commit.json`;
	await installDeterministicFile(outputRoot, preparationReference, request.preparationBundle.bytes, "application/json", signal);
	throwIfAborted(signal);
	await installDeterministicFile(outputRoot, markerReference, request.marker.bytes, "application/json", void 0);
	const files = await listOrdinaryFiles(resolve(outputRoot, directory), {
		maximumFiles: 2,
		maximumDepth: 1,
		maximumBytesEach: HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumPreparationBundleBytes
	}, void 0);
	if (files.length !== 2 || !files.some((file) => file.reference === "preparation.json") || !files.some((file) => file.reference === "preparation-commit.json")) throw new Error("The hidden-flow preparation publication contains unexpected files.");
	return Object.freeze({
		status: "committed",
		marker: request.marker.identity,
		preparationBundle: request.preparationBundle.identity,
		selectionHandle: `sha256:${request.preparationBundle.identity.sha256}`,
		immutableVersionId: `sha256:${request.preparationBundle.identity.sha256}`
	});
}
async function activateRetainedHiddenV1(input) {
	throwIfAborted(input.signal);
	const candidate = Object.freeze(Object.create(null));
	const verifier = createHiddenFlowV1PackageVerifier(async (selected, _expected, signal) => {
		throwIfAborted(signal);
		if (selected !== candidate) return null;
		const retained = await loadRetainedRuntime(input.packageEvidence, input.verifierPort, signal);
		throwIfAborted(signal);
		return hiddenRuntimeCandidate(retained, input.outputRoot, signal);
	});
	throwIfAborted(input.signal);
	const activated = await activateHiddenFlowV1Bridge({
		loader: { async loadExact(_request, signal) {
			throwIfAborted(signal);
			return Object.freeze({
				status: "loaded",
				candidate
			});
		} },
		verifier,
		preparationCommitter: { commit: (request, signal) => preparationCommitter(input.outputRoot, request, signal) },
		...input.signal === void 0 ? {} : { signal: input.signal }
	});
	throwIfAborted(input.signal);
	return activated;
}
function hiddenResourceParts(uri) {
	const match = /^flowblind-hidden-flow-report:\/\/sha256\/([a-f0-9]{64})\?verification=([a-f0-9]{64})&preparation=([a-f0-9]{64})&preparationMarker=([a-f0-9]{64})$/u.exec(uri);
	return match === null ? null : Object.freeze({
		reportSha256: match[1],
		verificationSha256: match[2],
		preparationSha256: match[3],
		preparationMarkerSha256: match[4]
	});
}
async function readHiddenV1ResourceCold(uri, outputRoot, signal) {
	throwIfAborted(signal);
	const parts = hiddenResourceParts(uri);
	if (parts === null) throw new Error("The hidden-flow resource URI is not canonical.");
	const references = hiddenReportReferences(parts.preparationSha256);
	const marker = await readOrReconcileDeterministicFile(outputRoot, references.verification, HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumMarkerBytes, "application/json", signal);
	if (marker === null) throw new Error("The hidden-flow report marker is absent.");
	throwIfAborted(signal);
	if (marker.sha256 !== parts.verificationSha256) throw new Error("The hidden-flow report URI does not match the committed marker.");
	const artifacts = record(parseCanonicalJson(marker.bytes, "Hidden-flow report marker", "compact", signal).artifacts);
	const verifiedRun = identity(value(artifacts, "json"), HIDDEN_FLOW_V1_RESOURCE_LIMITS.maximumV2VerifiedRunBytes);
	const report = identity(value(artifacts, "markdown"));
	const verification = artifactIdentity$1(references.verification, "application/json", marker.bytes, signal);
	if (report.sha256 !== parts.reportSha256) throw new Error("The hidden-flow report URI does not match its marker.");
	const verified = await verifyHiddenReportBinding(outputRoot, Object.freeze({
		preparationBundleSha256: parts.preparationSha256,
		preparationMarkerSha256: parts.preparationMarkerSha256,
		directory: references.directory,
		verifiedRun,
		report,
		verification
	}), signal);
	throwIfAborted(signal);
	return Object.freeze({
		directory: references.directory,
		verified
	});
}
async function readVerifiedHiddenV1ResourceCold(input) {
	throwIfAborted(input.signal);
	const retained = await loadRetainedRuntime(input.packageEvidence, input.verifierPort, input.signal);
	throwIfAborted(input.signal);
	const cold = await readHiddenV1ResourceCold(input.uri, input.outputRoot, input.signal);
	throwIfAborted(input.signal);
	recoveredHiddenReportSet({
		module: retained.module,
		verified: cold.verified,
		directory: cold.directory,
		...input.signal === void 0 ? {} : { signal: input.signal }
	});
	throwIfAborted(input.signal);
	return cold.verified.report.bytes;
}
function hiddenPreparedStudyFromSelection(selection) {
	return selection.preparedStudy;
}
//#endregion
//#region tools/catalogResearchV2/package/runtime.ts
var PublicAttachmentSelectionError = class extends Error {
	constructor(message) {
		super(message);
		this.name = "PublicAttachmentSelectionError";
	}
};
var verificationModuleReference = ["..", "flowblind-research-teammate-verification-v2.mjs"].join("/");
function asRecord(value) {
	return value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function ownDescriptorValue(descriptors, key) {
	const descriptor = Reflect.get(descriptors, key);
	if (descriptor === void 0) return void 0;
	if (!("value" in descriptor)) throw new TypeError(`FlowBlind v2 invocation field ${key} must be an own data property.`);
	return descriptor.value;
}
function invocationDescriptors(value, label) {
	if (value === null || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${label} must be an object with own data properties.`);
	try {
		return Object.getOwnPropertyDescriptors(value);
	} catch (error) {
		throw new TypeError(`${label} properties could not be snapshotted safely.`, { cause: error });
	}
}
function snapshotPrivateActivation(value) {
	if (value === void 0 || value === null) return;
	const descriptors = invocationDescriptors(value, "FlowBlind v2 private activation");
	const digest = ownDescriptorValue(descriptors, "digest");
	const manifestBytes = ownDescriptorValue(descriptors, "manifestBytes");
	if (typeof digest !== "string" || !(manifestBytes instanceof Uint8Array)) return;
	return Object.freeze({
		digest,
		manifestBytes: Uint8Array.from(manifestBytes)
	});
}
function snapshotActionContext(context) {
	const descriptors = invocationDescriptors(context, "FlowBlind v2 invocation context");
	const inputRoot = ownDescriptorValue(descriptors, "inputRoot");
	const outputRoot = ownDescriptorValue(descriptors, "outputRoot");
	if (typeof inputRoot !== "string" || typeof outputRoot !== "string") throw new TypeError("FlowBlind v2 inputRoot and outputRoot must be own string data properties.");
	const runConfirmationEvidence = ownDescriptorValue(descriptors, "runConfirmationEvidence");
	const privateActivation = snapshotPrivateActivation(ownDescriptorValue(descriptors, "privateActivation"));
	const signal = ownDescriptorValue(descriptors, "signal");
	return Object.freeze({
		inputRoot,
		outputRoot,
		...runConfirmationEvidence === void 0 ? {} : { runConfirmationEvidence },
		...privateActivation === void 0 ? {} : { privateActivation },
		...signal === void 0 ? {} : { signal }
	});
}
function snapshotPreviewContext(context) {
	const descriptors = invocationDescriptors(context, "FlowBlind v2 private preview context");
	const outputRoot = ownDescriptorValue(descriptors, "outputRoot");
	if (typeof outputRoot !== "string") throw new TypeError("FlowBlind v2 outputRoot must be an own string data property.");
	const privateActivation = snapshotPrivateActivation(ownDescriptorValue(descriptors, "privateActivation"));
	const signal = ownDescriptorValue(descriptors, "signal");
	return Object.freeze({
		outputRoot,
		...privateActivation === void 0 ? {} : { privateActivation },
		...signal === void 0 ? {} : { signal }
	});
}
var vectorStringMetadataFields = Object.freeze([
	"vectorSourceKind",
	"coordinateUnit",
	"valueUnit",
	"timeUnit",
	"samplingKind"
]);
function hasInvalidVectorStringMetadata(scientist) {
	const candidate = asRecord(scientist);
	if (candidate === null) return false;
	let metadataValue;
	try {
		const descriptor = Object.getOwnPropertyDescriptor(candidate, "metadata");
		metadataValue = descriptor !== void 0 && "value" in descriptor ? descriptor.value : void 0;
	} catch {
		return false;
	}
	const metadata = asRecord(metadataValue);
	if (metadata === null) return false;
	for (const key of vectorStringMetadataFields) {
		let descriptor;
		try {
			descriptor = Object.getOwnPropertyDescriptor(metadata, key);
		} catch {
			return false;
		}
		if (descriptor !== void 0 && "value" in descriptor && descriptor.value !== void 0 && descriptor.value !== null && typeof descriptor.value !== "string") return true;
	}
	return false;
}
async function packageAuthority(candidate, signal) {
	throwIfAborted(signal);
	if (candidate === null || candidate === void 0) return null;
	try {
		throwIfAborted(signal);
		const verifier = await import(new URL(verificationModuleReference, import.meta.url).href);
		throwIfAborted(signal);
		const evidence = verifier.flowBlindCatalogResearchV2PackageVerificationEvidence(candidate);
		return evidence === null ? null : Object.freeze({
			evidence,
			verifier
		});
	} catch {
		throwIfAborted(signal);
		return null;
	}
}
function resultFree(input) {
	return Object.freeze({
		schemaVersion: 2,
		routerVersion: FLOWBLIND_V2_ROUTER_PACKAGE_VERSION,
		status: input.status,
		containsResults: false,
		...input.capability === void 0 ? {} : { capability: input.capability },
		...input.familyOutcome === void 0 ? {} : { familyOutcome: input.familyOutcome },
		reasonCodes: Object.freeze([...input.reasonCodes]),
		guidance: input.guidance
	});
}
function packageRefusal() {
	return resultFree({
		status: "authority-unavailable",
		reasonCodes: ["package-attestation-failed"],
		guidance: "The portable FlowBlind v2 package could not verify its outer runtime, policy, schemas, and exact package inventory."
	});
}
function familyOutcome(error, capability) {
	const retained = asRecord(error.outcome);
	const retainedError = asRecord(retained?.error);
	const code = typeof retainedError?.code === "string" ? retainedError.code : typeof retained?.status === "string" ? retained.status : "unavailable";
	const detail = typeof retainedError?.detail === "string" ? retainedError.detail : typeof retained?.guidance === "string" ? retained.guidance : "The retained public method returned a result-free outcome.";
	return resultFree({
		status: "retained-family-outcome",
		capability,
		familyOutcome: error.outcome,
		reasonCodes: [`retained-catalog-v1-${code}`],
		guidance: detail
	});
}
function packageUnavailable(capability, reason, action) {
	return Object.freeze({
		...resultFree({
			status: "authority-unavailable",
			capability,
			reasonCodes: [reason],
			guidance: "Restore the exact retained package closure and rerun package verification. No alternate version or unverified runtime may execute."
		}),
		route: Object.freeze({
			methodId: capability.methodId,
			methodVersion: capability.methodVersion,
			action
		}),
		releaseState: sameCapabilityIdentity(capability, HIDDEN_FLOW_V1_DESCRIPTOR.identity) ? "trusted-private" : "candidate-active",
		authorityRequirementId: sameCapabilityIdentity(capability, HIDDEN_FLOW_V1_DESCRIPTOR.identity) ? HIDDEN_FLOW_V1_DESCRIPTOR.authority.requirement.requirementId : REGIONAL_AGREEMENT_V1_ADAPTER.authority.requirement.requirementId,
		requiredGrants: sameCapabilityIdentity(capability, HIDDEN_FLOW_V1_DESCRIPTOR.identity) ? HIDDEN_FLOW_V1_DESCRIPTOR.authority.requirement.requiredGrants : REGIONAL_AGREEMENT_V1_ADAPTER.authority.requirement.requiredGrants,
		authority: Object.freeze({
			state: "unavailable",
			reason
		})
	});
}
function unadvertisedCapabilityOutcome() {
	return resultFree({
		status: "unsupported",
		reasonCodes: ["no-advertised-capability-matched"],
		guidance: "Restate one scientific goal for regional agreement or vector/time readiness without capability IDs or data-shape hints."
	});
}
function priorOutcomeUnknown(capability, error) {
	return Object.freeze({
		...resultFree({
			status: "prior-outcome-unknown",
			capability,
			reasonCodes: error.reasonCodes,
			guidance: error.message
		}),
		reconciliation: Object.freeze({
			state: "execution-outcome-reconciliation-required",
			phase: "run"
		})
	});
}
function matchedCapability(outcome) {
	const capability = asRecord(asRecord(outcome)?.capability);
	if (capability === null || typeof capability.familyId !== "string" || typeof capability.methodId !== "string" || typeof capability.methodVersion !== "string") return null;
	return Object.freeze({
		familyId: capability.familyId,
		methodId: capability.methodId,
		methodVersion: capability.methodVersion
	});
}
function namesUnadvertisedCapability(outcome) {
	const reasonCodes = asRecord(outcome)?.reasonCodes;
	return Array.isArray(reasonCodes) && reasonCodes.some((reason) => reason === "home-qc-not-registered");
}
function isPublicCapability(capability) {
	return sameCapabilityIdentity(capability, REGIONAL_AGREEMENT_V1_ADAPTER.identity) || sameCapabilityIdentity(capability, VECTOR_TIME_READINESS_V1_ADAPTER.identity);
}
function mintSnapshots(request, handles, signal) {
	throwIfAborted(signal);
	return Object.freeze(handles.map((handle) => {
		throwIfAborted(signal);
		const token = Object.freeze(Object.create(null));
		const snapshot = createRuntimeResourceSnapshotVerifier((candidate) => candidate === token ? handle : null).verifyAndMint(token, request);
		if (snapshot === null) throw new Error("The trusted attachment verifier did not mint a resource snapshot.");
		throwIfAborted(signal);
		return snapshot;
	}));
}
function confirmationAuthority(authority, evidence, signal, onConfirmed) {
	throwIfAborted(signal);
	if (authority.verifier.flowBlindCatalogResearchV2RunConfirmationEvidence(evidence) === null) return;
	return createRuntimeConfirmedExecutionAuthority(async () => {
		throwIfAborted(signal);
		const consumed = authority.verifier.consumeFlowBlindCatalogResearchV2RunConfirmationEvidence(evidence);
		throwIfAborted(signal);
		if (consumed === null) return "prior-outcome-unknown";
		onConfirmed?.();
		return "confirmed";
	});
}
async function probeRoute(action, scientist, signal) {
	throwIfAborted(signal);
	const record = asRecord(scientist);
	let probeScientist = scientist;
	if (action === "prepare-study" && record !== null) try {
		const keys = Reflect.ownKeys(record);
		if (Object.getOwnPropertyDescriptor(record, "metadata") === void 0) {
			const projected = Object.create(null);
			let safe = true;
			for (const key of keys) {
				if (typeof key !== "string") {
					safe = false;
					break;
				}
				const descriptor = Object.getOwnPropertyDescriptor(record, key);
				if (descriptor === void 0 || !("value" in descriptor)) {
					safe = false;
					break;
				}
				if (descriptor.enumerable) projected[key] = descriptor.value;
			}
			if (safe) {
				projected.metadata = Object.freeze({});
				probeScientist = Object.freeze(projected);
			}
		}
	} catch {
		probeScientist = scientist;
	}
	const outcome = await routeFlowBlindCapability(FLOWBLIND_V2_CAPABILITY_REGISTRY, {
		action,
		scientist: probeScientist,
		host: {
			authorityEvidence: null,
			...signal === void 0 ? {} : { signal },
			async loadAttachments() {
				throw new Error("The route probe must finish before attachment access.");
			}
		}
	});
	throwIfAborted(signal);
	return outcome;
}
async function routePublic(input) {
	throwIfAborted(input.context.signal);
	let authority;
	try {
		authority = await issuePublicV1Authority({
			packageEvidence: input.packageAuthority.evidence,
			verifierPort: input.packageAuthority.verifier,
			outputRoot: input.context.outputRoot,
			...input.context.signal === void 0 ? {} : { signal: input.context.signal }
		});
		throwIfAborted(input.context.signal);
	} catch {
		throwIfAborted(input.context.signal);
		return packageUnavailable(input.capability, "retained-package-unavailable", input.action);
	}
	let selection;
	if (input.action === "run-and-verify-study") {
		try {
			selection = await loadPublicV1AttachmentSelection(input.action, input.context.inputRoot, input.context.signal);
		} catch (error) {
			throwIfAborted(input.context.signal);
			return resultFree({
				status: "attachment-contract-invalid",
				capability: input.capability,
				reasonCodes: ["host-attachment-selection-invalid"],
				guidance: error instanceof Error ? error.message : "The public attachment selection is invalid."
			});
		}
		throwIfAborted(input.context.signal);
		if (selection.preparedStudy === void 0 || !sameCapabilityIdentity(selection.preparedStudy.capability, input.capability)) return resultFree({
			status: "preparation-incompatible",
			capability: input.capability,
			reasonCodes: ["selected-preparation-method-mismatch"],
			guidance: "Select the exact preparation asset created for the matched public method."
		});
	}
	let confirmedExecutionStarted = false;
	const confirmed = input.action === "run-and-verify-study" ? confirmationAuthority(input.packageAuthority, input.context.runConfirmationEvidence, input.context.signal, () => {
		confirmedExecutionStarted = true;
	}) : void 0;
	try {
		throwIfAborted(input.context.signal);
		return await routeFlowBlindCapability(FLOWBLIND_V2_CAPABILITY_REGISTRY, {
			action: input.action,
			scientist: input.scientist,
			host: {
				authorityEvidence: authority.evidence,
				...selection?.preparedStudy === void 0 ? {} : { preparedStudy: selection.preparedStudy },
				...confirmed === void 0 ? {} : {
					confirmedExecution: confirmed,
					async settleConfirmedExecution() {}
				},
				async loadAttachments(request) {
					if (selection === void 0) try {
						selection = await loadPublicV1AttachmentSelection("prepare-study", input.context.inputRoot, input.context.signal);
						throwIfAborted(input.context.signal);
					} catch (error) {
						throwIfAborted(input.context.signal);
						throw new PublicAttachmentSelectionError(error instanceof Error ? error.message : "The public attachment selection is invalid.");
					}
					return mintSnapshots(request, selection.attachments, input.context.signal);
				},
				...input.context.signal === void 0 ? {} : { signal: input.context.signal }
			}
		});
	} catch (error) {
		if (error instanceof RetainedRunPriorOutcomeUnknownError) return priorOutcomeUnknown(input.capability, error);
		if (input.action === "run-and-verify-study" && confirmedExecutionStarted && input.context.signal?.aborted === true) return priorOutcomeUnknown(input.capability, new RetainedRunPriorOutcomeUnknownError("Confirmed execution was interrupted after the package consumed the run authority; reconcile the output before retrying.", ["confirmed-execution-prior-outcome-unknown"]));
		throwIfAborted(input.context.signal);
		if (error instanceof PublicAttachmentSelectionError) return resultFree({
			status: "attachment-contract-invalid",
			capability: input.capability,
			reasonCodes: ["host-attachment-selection-invalid"],
			guidance: error.message
		});
		if (error instanceof RetainedCatalogV1OutcomeError) return familyOutcome(error, input.capability);
		throw error;
	}
}
async function privateActivationEvidence(authority, candidate, signal) {
	throwIfAborted(signal);
	if (candidate === void 0) return null;
	const verified = authority.verifier.verifyPrivateHiddenFlowActivation(authority.evidence, candidate, signal);
	throwIfAborted(signal);
	return verified !== null && authority.verifier.flowBlindPrivateHiddenFlowActivationEvidence(verified) !== null ? verified : null;
}
async function routeHidden(input) {
	throwIfAborted(input.context.signal);
	const activationEvidence = await privateActivationEvidence(input.packageAuthority, input.context.privateActivation, input.context.signal);
	throwIfAborted(input.context.signal);
	if (activationEvidence === null) return unadvertisedCapabilityOutcome();
	let activated;
	try {
		activated = await activateRetainedHiddenV1({
			packageEvidence: input.packageAuthority.evidence,
			verifierPort: input.packageAuthority.verifier,
			outputRoot: input.context.outputRoot,
			...input.context.signal === void 0 ? {} : { signal: input.context.signal }
		});
		throwIfAborted(input.context.signal);
	} catch {
		throwIfAborted(input.context.signal);
		return packageUnavailable(input.capability, "retained-package-unavailable", input.action);
	}
	if (activated.status !== "active") return packageUnavailable(input.capability, activated.reason, input.action);
	let selection;
	try {
		selection = await loadHiddenV1AttachmentSelection(input.action, input.context.inputRoot, input.context.signal);
	} catch (error) {
		throwIfAborted(input.context.signal);
		return resultFree({
			status: "attachment-contract-invalid",
			capability: input.capability,
			reasonCodes: ["hidden-flow-attachment-selection-invalid"],
			guidance: error instanceof Error ? error.message : "The hidden-flow attachment selection is invalid."
		});
	}
	throwIfAborted(input.context.signal);
	const preparedStudy = hiddenPreparedStudyFromSelection(selection);
	throwIfAborted(input.context.signal);
	let confirmedExecutionStarted = false;
	try {
		return await activated.activation.route({
			action: input.action,
			scientist: input.scientist,
			host: {
				authorityEvidence: activated.activation.authorityEvidence,
				...preparedStudy === void 0 ? {} : { preparedStudy },
				...input.action === "run-and-verify-study" ? {
					confirmedExecution: confirmationAuthority(input.packageAuthority, input.context.runConfirmationEvidence, input.context.signal, () => {
						confirmedExecutionStarted = true;
					}),
					async settleConfirmedExecution() {}
				} : {},
				async loadAttachments(request) {
					return mintSnapshots(request, [selection.attachment], input.context.signal);
				},
				...input.context.signal === void 0 ? {} : { signal: input.context.signal }
			}
		});
	} catch (error) {
		if (error instanceof RetainedRunPriorOutcomeUnknownError) return priorOutcomeUnknown(input.capability, error);
		if (input.action === "run-and-verify-study" && confirmedExecutionStarted && input.context.signal?.aborted === true) return priorOutcomeUnknown(input.capability, new RetainedRunPriorOutcomeUnknownError("Confirmed private execution was interrupted after the package consumed the run authority; reconcile the output before retrying.", ["confirmed-execution-prior-outcome-unknown"]));
		throw error;
	}
}
var catalogResearchV2RuntimeVersion = FLOWBLIND_V2_PACKAGE_VERSION;
var catalogResearchV2SupportedActions = Object.freeze([...FLOWBLIND_V2_PUBLIC_ACTIONS]);
var catalogResearchV2AdvertisedCapabilities = Object.freeze(FLOWBLIND_V2_CAPABILITY_REGISTRY.advertised.map((advertisement) => Object.freeze({
	identity: Object.freeze({ ...advertisement.identity }),
	releaseStatus: advertisement.releaseStatus,
	actions: Object.freeze([...advertisement.actions])
})));
var catalogResearchV2ToolDefinitions = Object.freeze([Object.freeze({
	name: "flowblind-prepare-study-v2",
	action: "prepare-study",
	confirmation: "Disabled"
}), Object.freeze({
	name: "flowblind-run-and-verify-study-v2",
	action: "run-and-verify-study",
	confirmation: "Enabled"
})]);
function serializeCatalogResearchV2Value(value) {
	return stableJson$1(value);
}
async function callCatalogResearchV2Action(action, scientist, context, packageVerification) {
	const scientistSnapshot = snapshotFlowBlindScientistInput(scientist);
	const contextSnapshot = snapshotActionContext(context);
	const packageVerificationSnapshot = packageVerification;
	throwIfAborted(contextSnapshot.signal);
	const authority = await packageAuthority(packageVerificationSnapshot, contextSnapshot.signal);
	throwIfAborted(contextSnapshot.signal);
	if (authority === null) return packageRefusal();
	if (hasInvalidVectorStringMetadata(scientistSnapshot)) return resultFree({
		status: "scientist-metadata-invalid",
		reasonCodes: ["vector-metadata-must-be-text"],
		guidance: "Vector source, coordinate, value, time, and sampling metadata must be ordinary text when supplied."
	});
	const probe = await probeRoute(action, scientistSnapshot, contextSnapshot.signal);
	throwIfAborted(contextSnapshot.signal);
	if (namesUnadvertisedCapability(probe)) return unadvertisedCapabilityOutcome();
	const capability = matchedCapability(probe);
	if (capability === null) return probe;
	if (!FLOWBLIND_V2_PUBLIC_ACTIONS.includes(action)) return probe;
	if (isPublicCapability(capability)) return await routePublic({
		action,
		scientist: scientistSnapshot,
		context: contextSnapshot,
		packageAuthority: authority,
		capability
	});
	if (sameCapabilityIdentity(capability, HIDDEN_FLOW_V1_DESCRIPTOR.identity)) return await routeHidden({
		action,
		scientist: scientistSnapshot,
		context: contextSnapshot,
		packageAuthority: authority,
		capability
	});
	return unadvertisedCapabilityOutcome();
}
async function readCatalogResearchV2Resource(uri, outputRoot, packageVerification, privateActivation, signal) {
	const privateActivationSnapshot = snapshotPrivateActivation(privateActivation);
	throwIfAborted(signal);
	const authority = await packageAuthority(packageVerification, signal);
	throwIfAborted(signal);
	if (authority === null) throw new Error("Resource reads require exact outer package authority.");
	if (uri.startsWith("flowblind-report://")) {
		const runtime = await loadPublicV1RuntimeForResource(authority.evidence, authority.verifier, signal);
		throwIfAborted(signal);
		const bytes = await readPublicV1Resource(uri, outputRoot, runtime, signal);
		throwIfAborted(signal);
		return bytes;
	}
	if (uri.startsWith("flowblind-hidden-flow-report://")) {
		const activation = await privateActivationEvidence(authority, privateActivationSnapshot, signal);
		throwIfAborted(signal);
		if (activation === null) throw new Error("Hidden-flow resources require the exact host-owned private activation manifest.");
		const bytes = await readVerifiedHiddenV1ResourceCold({
			uri,
			outputRoot,
			packageEvidence: authority.evidence,
			verifierPort: authority.verifier,
			...signal === void 0 ? {} : { signal }
		});
		throwIfAborted(signal);
		return bytes;
	}
	throw new Error("The resource URI scheme is not registered by FlowBlind v2.");
}
async function previewCatalogResearchV2PrivateCapability(context, packageVerification) {
	const contextSnapshot = snapshotPreviewContext(context);
	const packageVerificationSnapshot = packageVerification;
	throwIfAborted(contextSnapshot.signal);
	const authority = await packageAuthority(packageVerificationSnapshot, contextSnapshot.signal);
	throwIfAborted(contextSnapshot.signal);
	if (authority === null) return packageRefusal();
	const activationEvidence = await privateActivationEvidence(authority, contextSnapshot.privateActivation, contextSnapshot.signal);
	throwIfAborted(contextSnapshot.signal);
	if (activationEvidence === null) return probeRoute("prepare-study", Object.freeze({ researchGoal: "Bound an unobserved hidden flow perturbation." }), contextSnapshot.signal);
	const activated = await activateRetainedHiddenV1({
		packageEvidence: authority.evidence,
		verifierPort: authority.verifier,
		outputRoot: contextSnapshot.outputRoot,
		...contextSnapshot.signal === void 0 ? {} : { signal: contextSnapshot.signal }
	});
	throwIfAborted(contextSnapshot.signal);
	if (activated.status !== "active") return packageUnavailable(HIDDEN_FLOW_V1_DESCRIPTOR.identity, activated.reason, "prepare-study");
	return Object.freeze({
		schemaVersion: 2,
		routerVersion: FLOWBLIND_V2_ROUTER_PACKAGE_VERSION,
		status: "private-capability-available",
		containsResults: false,
		advertiseToScientist: false,
		descriptor: activated.activation.descriptor
	});
}
var catalogResearchV2PackageIdentity = Object.freeze({
	packageId: FLOWBLIND_V2_PACKAGE_ID,
	packageVersion: FLOWBLIND_V2_PACKAGE_VERSION
});
//#endregion
export { callCatalogResearchV2Action, catalogResearchV2AdvertisedCapabilities, catalogResearchV2PackageIdentity, catalogResearchV2RuntimeVersion, catalogResearchV2SupportedActions, catalogResearchV2ToolDefinitions, previewCatalogResearchV2PrivateCapability, readCatalogResearchV2Resource, serializeCatalogResearchV2Value };

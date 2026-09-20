import { constants } from "node:fs";
import { link, lstat, mkdir, open, opendir, realpath, unlink } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { setImmediate, setTimeout } from "node:timers/promises";
//#region tools/catalogResearch/catalogResearchProfile.ts
function stableValue$1(value) {
	if (Array.isArray(value)) return value.map(stableValue$1);
	if (typeof value === "object" && value !== null) return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableValue$1(value[key])]));
	if (value === null || typeof value === "string" || typeof value === "boolean") return value;
	if (typeof value === "number" && Number.isFinite(value)) return value;
	throw new Error("Catalog research records may contain only finite JSON values.");
}
function stableJson$1(value) {
	return `${JSON.stringify(stableValue$1(value), null, 2)}\n`;
}
var FLOWBLIND_CATALOG_RESEARCH_VERSION = "1.0.0";
var FLOWBLIND_PREPARE_STUDY_ACTION = "prepare-study";
var FLOWBLIND_RUN_AND_VERIFY_STUDY_ACTION = "run-and-verify-study";
var FLOWBLIND_CATALOG_PROTOCOL_PRESET_ID = "paired-planar-regional-agreement-3x3-minimum-30-v1";
var FLOWBLIND_CATALOG_VECTOR_PROTOCOL_PRESET_ID = "structured-planar-vector-time-readiness-standard-v1";
var FLOWBLIND_CATALOG_VECTOR_PREPARATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-vector-preparation-bundle-v1.schema.json";
var FLOWBLIND_CATALOG_VECTOR_SIDECAR_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-vector-source-sidecar-v1.schema.json";
var FLOWBLIND_CATALOG_VECTOR_VERIFIED_STUDY_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-vector-verified-study-v1.schema.json";
var FLOWBLIND_CATALOG_RESEARCH_ACTIONS = [FLOWBLIND_PREPARE_STUDY_ACTION, FLOWBLIND_RUN_AND_VERIFY_STUDY_ACTION];
var FLOWBLIND_CATALOG_PREPARATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-preparation-bundle-v1.schema.json";
var FLOWBLIND_CATALOG_VERIFIED_STUDY_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-verified-study-v1.schema.json";
var FLOWBLIND_CATALOG_REPORT_VERIFICATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-report-verification-v1";
var FLOWBLIND_CATALOG_RESOURCE_LIMITS = Object.freeze({
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
var FLOWBLIND_CATALOG_PREPARE_INPUT_SCHEMA = Object.freeze({
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
var CatalogResearchError = class extends Error {
	code;
	classification;
	publicDetail;
	constructor(code, classification, publicDetail, options) {
		super(publicDetail, options);
		this.name = "CatalogResearchError";
		this.code = code;
		this.classification = classification;
		this.publicDetail = publicDetail;
	}
};
function catalogRefusal(error) {
	const detail = [...error.publicDetail.normalize("NFC")].slice(0, 512).join("");
	return {
		schemaVersion: 1,
		teammateVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
		status: "refused",
		error: {
			code: error.code,
			classification: error.classification,
			detail
		},
		containsResults: false
	};
}
function sha256Bytes(value) {
	return createHash("sha256").update(value).digest("hex");
}
function utf8Bytes(value) {
	return Buffer.from(value, "utf8");
}
function artifactIdentity(reference, value, mediaType) {
	return {
		reference,
		byteLength: value.byteLength,
		sha256: sha256Bytes(value),
		...mediaType === void 0 ? {} : { mediaType }
	};
}
function associationIdentity(value) {
	return sha256Bytes(utf8Bytes(stableJson$1(value)));
}
function throwIfCatalogAborted(signal) {
	if (signal?.aborted === true) throw new CatalogResearchError("operation-cancelled", "cancellation", "The catalog research operation was cancelled before publication.");
}
//#endregion
//#region tools/catalogResearch/catalogAttachments.ts
var READ_CHUNK_BYTES = 65536;
var ALLOCATION_BLOCK_BYTES = 512n;
function numericMetadata(value) {
	return typeof value === "bigint" ? Number(value) : value ?? 0;
}
function samePath$1(left, right) {
	const normalizedLeft = resolve(left);
	const normalizedRight = resolve(right);
	return process.platform === "win32" ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase() : normalizedLeft === normalizedRight;
}
function isWithin(root, candidate) {
	const relativePath = relative(root, candidate);
	return relativePath.length > 0 && relativePath !== ".." && !relativePath.startsWith(`..${sep}`) && !isAbsolute(relativePath);
}
function normalizedReference(root, absolutePath) {
	const reference = relative(root, absolutePath).replaceAll("\\", "/");
	if (reference.length === 0 || reference === ".." || reference.startsWith("../") || isAbsolute(reference) || reference.includes("\0") || reference.split("/").some((segment) => segment.length === 0 || segment === "." || segment === "..")) throw new CatalogResearchError("attachment-path-unsafe", "input-validation", "An attachment reference escapes the selected attachment root.");
	return reference;
}
function pathError(detail, cause) {
	return new CatalogResearchError("attachment-path-unsafe", "input-validation", detail, cause === void 0 ? void 0 : { cause });
}
async function metadata(path, detail) {
	try {
		return await lstat(path, { bigint: true });
	} catch (error) {
		throw pathError(detail, error);
	}
}
async function canonicalPath(path, detail) {
	try {
		return await realpath(path);
	} catch (error) {
		throw pathError(detail, error);
	}
}
function hasUnsafeFileAttributes(metadataValue) {
	const attributes = numericMetadata(metadataValue.fileAttributes);
	const reparseTag = numericMetadata(metadataValue.reparsePointTag);
	return (attributes & 4461568) !== 0 || reparseTag !== 0;
}
function isFullyHydratedCatalogMetadata(metadataValue) {
	return !hasUnsafeFileAttributes(metadataValue) && (metadataValue.size === 0n || metadataValue.blocks * ALLOCATION_BLOCK_BYTES >= metadataValue.size);
}
function assertFullyHydrated(metadataValue) {
	if (!isFullyHydratedCatalogMetadata(metadataValue)) throw new CatalogResearchError("source-not-fully-hydrated", "input-validation", "Every selected attachment must be a fully hydrated ordinary local file.");
}
function sameNodeIdentity(left, right) {
	return left.dev === right.dev && left.ino === right.ino && left.mode === right.mode && numericMetadata(left.fileAttributes) === numericMetadata(right.fileAttributes) && numericMetadata(left.reparsePointTag) === numericMetadata(right.reparsePointTag);
}
function sameFileIdentity(left, right) {
	return sameNodeIdentity(left, right) && left.nlink === right.nlink && left.size === right.size && left.blocks === right.blocks && left.mtimeNs === right.mtimeNs;
}
async function ordinaryDirectoryEntry(root, path) {
	const value = await metadata(path, "The selected attachment directory is unavailable.");
	const canonical = await canonicalPath(path, "The selected attachment directory cannot be resolved safely.");
	if (value.isSymbolicLink() || !value.isDirectory() || hasUnsafeFileAttributes(value) || !samePath$1(path, canonical) || path !== root && !isWithin(root, canonical)) throw pathError("Attachment directories must be ordinary, confined directories without links or reparse indirection.");
	return {
		absolutePath: path,
		reference: path === root ? "." : normalizedReference(root, path),
		kind: "directory",
		metadata: value
	};
}
async function ordinaryFileEntry(root, path) {
	const value = await metadata(path, "A selected attachment is unavailable.");
	const canonical = await canonicalPath(path, "A selected attachment cannot be resolved safely.");
	if (value.isSymbolicLink() || !value.isFile() || value.nlink !== 1n || hasUnsafeFileAttributes(value) || !samePath$1(path, canonical) || !isWithin(root, canonical)) throw pathError("Attachments must be confined regular files without links or reparse indirection.");
	assertFullyHydrated(value);
	if (value.size > BigInt(FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumAttachmentBytesEach)) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "A selected attachment exceeds the reviewed byte limit.");
	return {
		absolutePath: path,
		reference: normalizedReference(root, path),
		kind: "file",
		metadata: value
	};
}
async function scanTree(rootInput) {
	const requestedRoot = resolve(rootInput);
	const requestedMetadata = await metadata(requestedRoot, "The selected attachment directory is unavailable.");
	if (requestedMetadata.isSymbolicLink() || !requestedMetadata.isDirectory() || hasUnsafeFileAttributes(requestedMetadata)) throw pathError("The selected attachment root must be an ordinary directory without links or reparse indirection.");
	const root = await canonicalPath(requestedRoot, "The selected attachment directory cannot be resolved safely.");
	const rootEntry = await ordinaryDirectoryEntry(root, root);
	const entries = [];
	const visit = async (directory) => {
		const children = [];
		try {
			const handle = await opendir(directory);
			for await (const child of handle) {
				children.push(child);
				if (entries.length + children.length > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumAttachmentFiles * 4) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "The selected attachment tree contains too many entries.");
			}
		} catch (error) {
			if (error instanceof CatalogResearchError) throw error;
			throw pathError("The selected attachment directory cannot be enumerated safely.", error);
		}
		children.sort((left, right) => left.name.localeCompare(right.name, "en"));
		for (const child of children) {
			const path = resolve(directory, child.name);
			if (child.isSymbolicLink()) throw pathError("Attachment paths must not contain symbolic links.");
			if (child.isDirectory()) {
				const entry = await ordinaryDirectoryEntry(root, path);
				entries.push(entry);
				await visit(path);
			} else entries.push(await ordinaryFileEntry(root, path));
		}
	};
	await visit(root);
	return {
		root: rootEntry,
		entries
	};
}
function compareTrees(before, after) {
	if (!samePath$1(before.root.absolutePath, after.root.absolutePath) || !sameNodeIdentity(before.root.metadata, after.root.metadata) || before.entries.length !== after.entries.length) throw new CatalogResearchError("attachment-changed-during-read", "input-validation", "The selected attachment tree changed while it was being verified.");
	for (const [index, left] of before.entries.entries()) {
		const right = after.entries[index];
		if (right === void 0 || left.reference !== right.reference || left.kind !== right.kind || !samePath$1(left.absolutePath, right.absolutePath) || (left.kind === "file" ? !sameFileIdentity(left.metadata, right.metadata) : !sameNodeIdentity(left.metadata, right.metadata))) throw new CatalogResearchError("attachment-changed-during-read", "input-validation", "The selected attachment tree changed while it was being verified.");
	}
}
function readFlags() {
	return constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0) | (typeof constants.O_NONBLOCK === "number" ? constants.O_NONBLOCK : 0);
}
async function readEntry(root, entry, request) {
	await request.checkpoint?.("before-file-open", entry.reference);
	throwIfCatalogAborted(request.signal);
	let handle;
	try {
		handle = await open(entry.absolutePath, readFlags());
	} catch (error) {
		throw pathError("A selected attachment could not be opened with no-follow read-only access.", error);
	}
	try {
		const opened = await handle.stat({ bigint: true });
		if (!opened.isFile() || !sameFileIdentity(entry.metadata, opened)) throw new CatalogResearchError("attachment-changed-during-read", "input-validation", "A selected attachment changed before it could be read.");
		assertFullyHydrated(opened);
		await request.checkpoint?.("after-file-open", entry.reference);
		throwIfCatalogAborted(request.signal);
		const chunks = [];
		let totalBytes = 0;
		while (true) {
			throwIfCatalogAborted(request.signal);
			const buffer = Buffer.allocUnsafe(READ_CHUNK_BYTES);
			const { bytesRead } = await handle.read(buffer, 0, buffer.byteLength, null);
			if (bytesRead === 0) break;
			totalBytes += bytesRead;
			if (totalBytes > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumAttachmentBytesEach) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "A selected attachment exceeds the reviewed byte limit.");
			chunks.push(buffer.subarray(0, bytesRead));
		}
		const bytes = Buffer.concat(chunks, totalBytes);
		await request.checkpoint?.("after-file-read", entry.reference);
		throwIfCatalogAborted(request.signal);
		const afterHandle = await handle.stat({ bigint: true });
		const afterPath = await metadata(entry.absolutePath, "A selected attachment became unavailable after reading.");
		const afterCanonical = await canonicalPath(entry.absolutePath, "A selected attachment could not be re-resolved after reading.");
		if (!sameFileIdentity(entry.metadata, afterHandle) || !sameFileIdentity(entry.metadata, afterPath) || !samePath$1(entry.absolutePath, afterCanonical) || !isWithin(root, afterCanonical) || BigInt(totalBytes) !== entry.metadata.size) throw new CatalogResearchError("attachment-changed-during-read", "input-validation", "A selected attachment changed while it was being read.");
		assertFullyHydrated(afterHandle);
		await request.checkpoint?.("after-file-revalidation", entry.reference);
		throwIfCatalogAborted(request.signal);
		return {
			reference: entry.reference,
			byteLength: totalBytes,
			sha256: sha256Bytes(bytes),
			bytes
		};
	} finally {
		await handle.close();
	}
}
async function loadCatalogAttachments(request) {
	throwIfCatalogAborted(request.signal);
	const before = await scanTree(request.root);
	await request.checkpoint?.("after-initial-scan");
	throwIfCatalogAborted(request.signal);
	const files = before.entries.filter((entry) => entry.kind === "file");
	if (files.length !== request.expectedFileCount) throw new CatalogResearchError("attachment-set-invalid", "input-validation", `This action requires exactly ${request.expectedFileCount} selected attachment files.`);
	if (files.reduce((sum, entry) => sum + Number(entry.metadata.size), 0) > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumAttachmentBytesTotal) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "The selected attachment set exceeds the reviewed aggregate byte limit.");
	const loaded = [];
	for (const file of files) loaded.push(await readEntry(before.root.absolutePath, file, request));
	await request.checkpoint?.("before-final-scan");
	throwIfCatalogAborted(request.signal);
	compareTrees(before, await scanTree(request.root));
	await request.checkpoint?.("after-final-scan");
	throwIfCatalogAborted(request.signal);
	return Object.freeze(loaded.sort((left, right) => left.reference.localeCompare(right.reference, "en")));
}
//#endregion
//#region tools/discovery/flowblindDisplayText.ts
var FLOWBLIND_MAX_DISPLAY_TEXT_CODE_POINTS = 4096;
var FlowBlindDisplayTextError = class extends Error {
	code;
	constructor(code, message) {
		super(message);
		this.name = "FlowBlindDisplayTextError";
		this.code = code;
	}
};
function unsafeDisplayCodePoint(code) {
	return code <= 31 || code >= 127 && code <= 159 || code === 173 || code === 1564 || code >= 8203 && code <= 8207 || code === 8232 || code === 8233 || code >= 8234 && code <= 8238 || code >= 8288 && code <= 8303 || code === 65279 || code >= 65529 && code <= 65531;
}
function validateFlowBlindDisplayText(value, label, maximumCodePoints = FLOWBLIND_MAX_DISPLAY_TEXT_CODE_POINTS) {
	if (typeof value !== "string" || value.length === 0) throw new FlowBlindDisplayTextError("display-text-empty", `${label} must be nonempty text.`);
	if (value !== value.trim() || value !== value.normalize("NFC")) throw new FlowBlindDisplayTextError("display-text-not-normalized", `${label} must be trimmed NFC text.`);
	const codePoints = [...value];
	if (codePoints.length > maximumCodePoints) throw new FlowBlindDisplayTextError("display-text-too-long", `${label} must not exceed ${maximumCodePoints} Unicode code points.`);
	for (const character of codePoints) {
		const code = character.codePointAt(0);
		if (code !== void 0 && unsafeDisplayCodePoint(code)) throw new FlowBlindDisplayTextError("display-text-unsafe-character", `${label} contains an unsafe display-control character.`);
	}
	return value;
}
//#endregion
//#region tools/discovery/safeIntakeFile.ts
var FLOWBLIND_MAX_INTAKE_FILE_BYTES = 16777216;
var SafeIntakeError = class extends Error {
	code;
	constructor(code, message, options) {
		super(message, options);
		this.name = "SafeIntakeError";
		this.code = code;
	}
};
//#endregion
//#region tools/discovery/strictUtf8.ts
var UTF8_BOM$2 = [
	239,
	187,
	191
];
function canStillBeBom(prefix) {
	return prefix.every((byte, index) => byte === UTF8_BOM$2[index]);
}
var StrictUtf8StreamDecoder = class {
	decoder = new TextDecoder("utf-8", {
		fatal: true,
		ignoreBOM: true
	});
	prefix = [];
	prefixResolved = false;
	write(chunk) {
		try {
			if (this.prefixResolved) return this.decoder.decode(chunk, { stream: true });
			let offset = 0;
			while (offset < chunk.byteLength && this.prefix.length < UTF8_BOM$2.length) {
				this.prefix.push(chunk[offset] ?? 0);
				offset += 1;
				if (!canStillBeBom(this.prefix)) return this.resolvePrefix(chunk.subarray(offset));
			}
			if (this.prefix.length === UTF8_BOM$2.length) {
				if (canStillBeBom(this.prefix)) throw new SafeIntakeError("file-read-failed", "FlowBlind intake text must be UTF-8 without a byte-order mark.");
				return this.resolvePrefix(chunk.subarray(offset));
			}
			return "";
		} catch (error) {
			if (error instanceof SafeIntakeError) throw error;
			throw new SafeIntakeError("file-read-failed", "FlowBlind intake text must contain strict UTF-8.", { cause: error });
		}
	}
	finish() {
		try {
			return (this.prefixResolved ? "" : this.resolvePrefix(/* @__PURE__ */ new Uint8Array())) + this.decoder.decode();
		} catch (error) {
			if (error instanceof SafeIntakeError) throw error;
			throw new SafeIntakeError("file-read-failed", "FlowBlind intake text must contain complete strict UTF-8.", { cause: error });
		}
	}
	resolvePrefix(remainder) {
		this.prefixResolved = true;
		const prefix = Uint8Array.from(this.prefix);
		this.prefix.length = 0;
		return this.decoder.decode(prefix, { stream: true }) + this.decoder.decode(remainder, { stream: true });
	}
};
//#endregion
//#region tools/discovery/pairedPlanarCsvIntake.ts
var PAIRED_PLANAR_CSV_HEADER = [
	"x",
	"y",
	"reference_value",
	"candidate_value"
];
var PAIRED_PLANAR_CSV_HEADER_TEXT = "x,y,reference_value,candidate_value";
var PAIRED_PLANAR_CSV_LIMITS = Object.freeze({
	maximumBytes: FLOWBLIND_MAX_INTAKE_FILE_BYTES,
	maximumDataRows: 25e4,
	exactColumns: 4,
	maximumCharactersPerField: 4096,
	maximumDataFields: 1e6
});
var PAIRED_PLANAR_CSV_VALIDATOR_VERSION = "flowblind-paired-planar-csv-v1";
var DECIMAL_PATTERN$1 = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/u;
function formatDecimalKey(coefficient, exponent10) {
	return `${coefficient.toString()}e${exponent10}`;
}
function normalizeDecimal(coefficientInput, exponentInput, value) {
	let coefficient = coefficientInput;
	let exponent10 = exponentInput;
	if (coefficient === 0n) return {
		coefficient: 0n,
		exponent10: 0,
		key: "0e0",
		value: 0
	};
	while (coefficient % 10n === 0n) {
		coefficient /= 10n;
		exponent10 += 1;
	}
	return {
		coefficient,
		exponent10,
		key: formatDecimalKey(coefficient, exponent10),
		value
	};
}
function invalidNumber$1(row, column) {
	throw new SafeIntakeError("file-read-failed", `CSV data row ${row} column ${column} must contain a finite decimal number.`);
}
function parseFiniteDecimal$1(field, row, column) {
	if (!DECIMAL_PATTERN$1.test(field)) invalidNumber$1(row, column);
	const value = Number(field);
	if (!Number.isFinite(value)) invalidNumber$1(row, column);
	return Object.is(value, -0) ? 0 : value;
}
function parseCoordinate$1(field, row, column) {
	const match = DECIMAL_PATTERN$1.exec(field);
	if (match === null) invalidNumber$1(row, column);
	const value = Number(field);
	if (!Number.isFinite(value)) invalidNumber$1(row, column);
	const integerPart = match[2] ?? "0";
	const fractionalPart = match[2] === void 0 ? match[4] ?? "" : match[3] ?? "";
	const digits = `${integerPart}${fractionalPart}`;
	let coefficient = BigInt(digits);
	if (match[1] === "-") coefficient = -coefficient;
	if (coefficient === 0n) return normalizeDecimal(0n, 0, 0);
	if (value === 0) throw new SafeIntakeError("file-read-failed", `CSV data row ${row} column ${column} is outside the supported finite coordinate range.`);
	const declaredExponent = Number(match[5] ?? "0");
	if (!Number.isSafeInteger(declaredExponent)) invalidNumber$1(row, column);
	const exponent10 = declaredExponent - fractionalPart.length;
	if (!Number.isSafeInteger(exponent10)) invalidNumber$1(row, column);
	return normalizeDecimal(coefficient, exponent10, Object.is(value, -0) ? 0 : value);
}
function decimalDifference(right, left) {
	const exponent10 = Math.min(right.exponent10, left.exponent10);
	const rightScale = right.exponent10 - exponent10;
	const leftScale = left.exponent10 - exponent10;
	return normalizeDecimal(right.coefficient * 10n ** BigInt(rightScale) - left.coefficient * 10n ** BigInt(leftScale), exponent10, right.value - left.value);
}
function hasUniformSpacing(axis) {
	if (axis.length <= 2) return true;
	const firstDifference = decimalDifference(axis[1], axis[0]);
	for (let index = 2; index < axis.length; index += 1) if (decimalDifference(axis[index], axis[index - 1]).key !== firstDifference.key) return false;
	return true;
}
function exactUniformSpacing(axis) {
	if (axis.length === 1) return 1;
	if (!hasUniformSpacing(axis)) return null;
	const difference = decimalDifference(axis[1], axis[0]);
	const value = Number(`${difference.coefficient.toString()}e${difference.exponent10}`);
	if (!Number.isFinite(value) || value <= 0) throw new SafeIntakeError("file-read-failed", "CSV coordinate spacing must be finite and positive.");
	return value;
}
function coordinatePairKey$1(x, y) {
	return `${x.key}|${y.key}`;
}
var PairedPlanarCsvParser = class {
	state = "unquoted";
	field = "";
	fieldCharacters = 0;
	fields = [];
	recordTouched = false;
	pendingCarriageReturn = false;
	headerRead = false;
	rawHeader = "";
	dataRows = 0;
	dataFields = 0;
	xCoordinates = /* @__PURE__ */ new Map();
	yCoordinates = /* @__PURE__ */ new Map();
	xNumberIdentities = /* @__PURE__ */ new Map();
	yNumberIdentities = /* @__PURE__ */ new Map();
	rows = /* @__PURE__ */ new Map();
	write(text) {
		for (const character of text) this.writeCharacter(character);
	}
	finish() {
		if (this.pendingCarriageReturn) this.malformed("CSV records must use LF or CRLF line endings.");
		if (this.state === "quoted") this.malformed("CSV contains an unterminated quoted field.");
		if (this.recordTouched || this.fields.length > 0 || this.fieldCharacters > 0) {
			this.finishField();
			this.finishRecord();
		}
		if (!this.headerRead) throw new SafeIntakeError("file-read-failed", `CSV header must be exactly ${PAIRED_PLANAR_CSV_HEADER_TEXT}.`);
		if (this.dataRows === 0) throw new SafeIntakeError("file-read-failed", "CSV must contain at least one paired data row.");
		const xAxis = [...this.xCoordinates.values()].sort((left, right) => left.value - right.value);
		const yAxis = [...this.yCoordinates.values()].sort((left, right) => left.value - right.value);
		if (xAxis.length * yAxis.length !== this.dataRows) throw new SafeIntakeError("file-read-failed", "CSV coordinate rows must form one complete Cartesian grid.");
		const referenceValues = [];
		const candidateValues = [];
		for (const y of yAxis) for (const x of xAxis) {
			const values = this.rows.get(coordinatePairKey$1(x, y));
			if (values === void 0) throw new SafeIntakeError("file-read-failed", "CSV coordinate rows must form one complete Cartesian grid.");
			referenceValues.push(values[0]);
			candidateValues.push(values[1]);
		}
		const xSpacing = exactUniformSpacing(xAxis);
		const ySpacing = exactUniformSpacing(yAxis);
		return {
			structure: {
				columnCount: 4,
				coordinateDimensions: 2,
				singleFrame: true,
				pairedValues: true,
				finitePairedRowCount: this.dataRows,
				dataFieldCount: this.dataFields,
				gridShape: {
					xCount: xAxis.length,
					yCount: yAxis.length
				},
				duplicateCoordinates: false,
				completeCartesianGrid: true,
				uniformSpacing: {
					x: xSpacing !== null,
					y: ySpacing !== null
				}
			},
			axes: {
				x: Object.freeze(xAxis.map((coordinate) => coordinate.value)),
				y: Object.freeze(yAxis.map((coordinate) => coordinate.value)),
				spacing: {
					x: xSpacing,
					y: ySpacing
				}
			},
			values: {
				order: "y-major-x-minor",
				reference: Object.freeze(referenceValues),
				candidate: Object.freeze(candidateValues)
			}
		};
	}
	writeCharacter(character) {
		if (this.pendingCarriageReturn) {
			if (character !== "\n") this.malformed("CSV records must use LF or CRLF line endings.");
			this.pendingCarriageReturn = false;
			this.finishRecord();
			return;
		}
		if (!this.headerRead && (this.state === "quoted" || character !== "\r" && character !== "\n")) this.rawHeader += character;
		if (this.state === "quoted") {
			if (character === "\"") this.state = "after-quote";
			else this.appendCharacter(character);
			return;
		}
		if (this.state === "after-quote") {
			if (character === "\"") {
				this.appendCharacter("\"");
				this.state = "quoted";
			} else if (character === ",") this.finishDelimitedField();
			else if (character === "\n") {
				this.finishField();
				this.finishRecord();
			} else if (character === "\r") {
				this.finishField();
				this.pendingCarriageReturn = true;
			} else this.malformed("CSV quoted fields must end at a delimiter or record boundary.");
			return;
		}
		if (character === "\"") {
			if (this.fieldCharacters !== 0) this.malformed("CSV quotes are only allowed at the start of a field.");
			this.recordTouched = true;
			this.state = "quoted";
		} else if (character === ",") this.finishDelimitedField();
		else if (character === "\n") {
			this.finishField();
			this.finishRecord();
		} else if (character === "\r") {
			this.finishField();
			this.pendingCarriageReturn = true;
		} else this.appendCharacter(character);
	}
	appendCharacter(character) {
		if (character === "\0") this.malformed("CSV fields must not contain NUL.");
		if (this.fieldCharacters + 1 > PAIRED_PLANAR_CSV_LIMITS.maximumCharactersPerField) throw new SafeIntakeError("file-read-failed", `CSV fields must not exceed ${PAIRED_PLANAR_CSV_LIMITS.maximumCharactersPerField} characters.`);
		this.fieldCharacters += 1;
		this.field += character;
		this.recordTouched = true;
	}
	finishDelimitedField() {
		if (this.fields.length >= PAIRED_PLANAR_CSV_LIMITS.exactColumns - 1) throw new SafeIntakeError("file-read-failed", `CSV records must contain exactly ${PAIRED_PLANAR_CSV_LIMITS.exactColumns} columns.`);
		this.finishField();
		this.state = "unquoted";
		this.recordTouched = true;
	}
	finishField() {
		if (this.fields.length >= PAIRED_PLANAR_CSV_LIMITS.exactColumns) throw new SafeIntakeError("file-read-failed", `CSV records must contain exactly ${PAIRED_PLANAR_CSV_LIMITS.exactColumns} columns.`);
		this.fields.push(this.field);
		this.field = "";
		this.fieldCharacters = 0;
		this.state = "unquoted";
	}
	finishRecord() {
		const record = this.fields;
		if (!this.headerRead) {
			if (this.rawHeader !== "x,y,reference_value,candidate_value" || record.length !== PAIRED_PLANAR_CSV_LIMITS.exactColumns || record.some((field, index) => field !== PAIRED_PLANAR_CSV_HEADER[index])) throw new SafeIntakeError("file-read-failed", `CSV header must be exactly ${PAIRED_PLANAR_CSV_HEADER_TEXT}.`);
			this.headerRead = true;
		} else this.finishDataRecord(record);
		this.fields = [];
		this.recordTouched = false;
		this.rawHeader = "";
		this.state = "unquoted";
	}
	finishDataRecord(record) {
		if (record.length !== PAIRED_PLANAR_CSV_LIMITS.exactColumns) throw new SafeIntakeError("file-read-failed", `CSV records must contain exactly ${PAIRED_PLANAR_CSV_LIMITS.exactColumns} columns.`);
		const nextRowCount = this.dataRows + 1;
		const nextFieldCount = this.dataFields + record.length;
		const rowOverflow = nextRowCount > PAIRED_PLANAR_CSV_LIMITS.maximumDataRows;
		const fieldOverflow = nextFieldCount > PAIRED_PLANAR_CSV_LIMITS.maximumDataFields;
		if (rowOverflow || fieldOverflow) throw new SafeIntakeError("file-read-failed", `CSV exceeds the ${[rowOverflow ? `${PAIRED_PLANAR_CSV_LIMITS.maximumDataRows} data rows` : "", fieldOverflow ? `${PAIRED_PLANAR_CSV_LIMITS.maximumDataFields} data fields` : ""].filter((resource) => resource.length > 0).join(" and ")} limit.`);
		const x = parseCoordinate$1(record[0], nextRowCount, "x");
		const y = parseCoordinate$1(record[1], nextRowCount, "y");
		const referenceValue = parseFiniteDecimal$1(record[2], nextRowCount, "reference_value");
		const candidateValue = parseFiniteDecimal$1(record[3], nextRowCount, "candidate_value");
		this.assertCoordinatePrecision(this.xNumberIdentities, x, nextRowCount, "x");
		this.assertCoordinatePrecision(this.yNumberIdentities, y, nextRowCount, "y");
		const pairKey = coordinatePairKey$1(x, y);
		if (this.rows.has(pairKey)) throw new SafeIntakeError("file-read-failed", `CSV data row ${nextRowCount} repeats an existing coordinate pair.`);
		this.xCoordinates.set(x.key, x);
		this.yCoordinates.set(y.key, y);
		this.rows.set(pairKey, [referenceValue, candidateValue]);
		this.dataRows = nextRowCount;
		this.dataFields = nextFieldCount;
	}
	assertCoordinatePrecision(numericIdentities, coordinate, row, column) {
		const existing = numericIdentities.get(coordinate.value);
		if (existing !== void 0 && existing !== coordinate.key) throw new SafeIntakeError("file-read-failed", `CSV data row ${row} column ${column} cannot be represented as a distinct finite coordinate.`);
		numericIdentities.set(coordinate.value, coordinate.key);
	}
	malformed(message) {
		throw new SafeIntakeError("file-read-failed", message);
	}
};
function validatePairedPlanarCsvBytes(request) {
	if (request.bytes.byteLength > PAIRED_PLANAR_CSV_LIMITS.maximumBytes || request.source.byteLength !== request.bytes.byteLength || request.source.sha256 !== createHash("sha256").update(request.bytes).digest("hex")) throw new SafeIntakeError("identity-mismatch", "Registered paired-planar CSV bytes do not match their immutable identity.");
	const decoder = new StrictUtf8StreamDecoder();
	const parser = new PairedPlanarCsvParser();
	parser.write(decoder.write(request.bytes));
	parser.write(decoder.finish());
	const parsed = parser.finish();
	return {
		source: request.source,
		parser: {
			version: PAIRED_PLANAR_CSV_VALIDATOR_VERSION,
			encoding: "utf-8",
			header: PAIRED_PLANAR_CSV_HEADER
		},
		structure: parsed.structure,
		axes: parsed.axes,
		values: parsed.values
	};
}
//#endregion
//#region src/domain/vectorDatasetModel.ts
function resolveFrameAverageSampling(sampling) {
	return {
		...sampling,
		exposureOperator: sampling.exposureOperator ?? "unspecified",
		timestampAnchor: sampling.timestampAnchor ?? "unspecified"
	};
}
//#endregion
//#region src/application/evidenceReport.ts
function isRecord$1(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}
function stableValue(value) {
	if (Array.isArray(value)) return value.map(stableValue);
	if (isRecord$1(value)) {
		const result = {};
		for (const key of Object.keys(value).sort()) result[key] = stableValue(value[key]);
		return result;
	}
	if (value === null || typeof value === "string" || typeof value === "boolean") return value;
	if (typeof value === "number" && Number.isFinite(value)) return value;
	throw new Error("Evidence reports may contain only finite JSON values.");
}
function stableJson(value) {
	return `${JSON.stringify(stableValue(value), null, 2)}\n`;
}
function escapeMarkdown$1(value) {
	return value.replace(/[\u202a-\u202e\u2066-\u2069]/gu, (character) => `bidi-control-U${character.codePointAt(0)?.toString(16).toUpperCase()}`).replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;").replace(/[\r\n]+/gu, " ").replace(/([\\*_[\]{}()#+!|])/gu, "\\$1").replace(/:/gu, "&#58;").replace(/`/gu, "&#96;");
}
function formatted(value) {
	return typeof value === "number" ? Number.isFinite(value) ? value.toPrecision(8).replace(/(?:\.0+|(\.\d+?)0+)(e|$)/u, "$1$2") : "not finite" : escapeMarkdown$1(value);
}
function temporalSamplingDescription(report) {
	const temporal = report.dataset.temporal;
	if (temporal.sampling.kind !== "frame-average") return `${temporal.kind}; ${temporal.sampling.kind}; ${temporal.timestampUnit}`;
	const sampling = resolveFrameAverageSampling(temporal.sampling);
	return `${temporal.kind}; ${sampling.kind}; ${temporal.timestampUnit}; operator ${sampling.exposureOperator}; exposure ${formatted(sampling.exposureDuration)} ${temporal.timestampUnit}; timestamp anchor ${sampling.timestampAnchor}`;
}
function metricStatus$1(name, metric) {
	if (metric.status === "available") return [`| ${escapeMarkdown$1(name)} | available | ${formatted(metric.coverage.fraction)} | — |`];
	const coverage = metric.status === "insufficient-evidence" ? formatted(metric.coverage.fraction) : "—";
	return [`| ${escapeMarkdown$1(name)} | ${escapeMarkdown$1(metric.status)} | ${coverage} | ${escapeMarkdown$1(metric.reason)}: ${escapeMarkdown$1(metric.detail)} |`];
}
function gateRows(label, metric) {
	return metric.gates.map((gate) => `| ${escapeMarkdown$1(label)} | ${escapeMarkdown$1(gate.id)} | ${gate.passed ? "pass" : "refuse"} | ${formatted(gate.observed)} | ${formatted(gate.criterion)} | ${escapeMarkdown$1(gate.detail)} |`);
}
function singleReportMarkdown(report, headingLevel) {
	const heading = "#".repeat(headingLevel);
	const subheading = "#".repeat(headingLevel + 1);
	const lines = [
		`${heading} ${escapeMarkdown$1(report.scenario.title)}`,
		"",
		`**Report ID:** \`${escapeMarkdown$1(report.reportId)}\`  `,
		`**Dataset:** ${escapeMarkdown$1(report.dataset.title)} (\`${escapeMarkdown$1(report.dataset.id)}\`)  `,
		`**Software:** ${escapeMarkdown$1(report.software.name)} ${escapeMarkdown$1(report.software.version)}  `,
		`**Dataset document/source SHA-256:** \`${escapeMarkdown$1(report.dataset.documentSource.sha256)}\``,
		"",
		`${subheading} Inputs and provenance`,
		"",
		"| Property | Value |",
		"| --- | --- |",
		`| Dataset kind | ${escapeMarkdown$1(report.dataset.kind)} |`,
		`| Dataset description | ${escapeMarkdown$1(report.dataset.description)} |`,
		`| Coordinate frame | ${escapeMarkdown$1(report.dataset.coordinateFrame.id)}; ${report.dataset.coordinateFrame.dimension}D ${escapeMarkdown$1(report.dataset.coordinateFrame.type)}; ${escapeMarkdown$1(report.dataset.coordinateFrame.handedness)} |`,
		`| Length unit | ${escapeMarkdown$1(report.dataset.coordinateFrame.lengthUnit)} |`,
		`| Components | ${report.dataset.components.map((component) => `${escapeMarkdown$1(component.name)} → ${component.axis} [${escapeMarkdown$1(component.unit)}]`).join("; ")} |`,
		`| Frames / points | ${report.dataset.frameCount} / ${report.dataset.pointCount} |`,
		`| Time semantics | ${escapeMarkdown$1(temporalSamplingDescription(report))} |`,
		`| Requested / resolved time | ${formatted(report.metrics.instantaneous.requestedTime)} / ${report.metrics.instantaneous.resolvedTime === null ? "unresolved" : formatted(report.metrics.instantaneous.resolvedTime)} ${escapeMarkdown$1(report.dataset.temporal.timestampUnit)} |`,
		`| Dataset source | ${escapeMarkdown$1(report.dataset.documentSource.reference)}; ${report.dataset.documentSource.byteLength} bytes |`,
		`| Wall evidence | ${report.dataset.wall === null ? "not supplied" : `${escapeMarkdown$1(report.dataset.wall.method.kind)}; viscosity ${formatted(report.dataset.wall.dynamicViscosity.value)} ${escapeMarkdown$1(report.dataset.wall.dynamicViscosity.unit)}; ${report.dataset.wall.method.wallPointIndices.length} pairs`} |`,
		`| Source kind | ${escapeMarkdown$1(report.dataset.provenance.sourceKind)} |`,
		`| Citation | ${escapeMarkdown$1(report.dataset.provenance.citation)} |`,
		`| License | ${escapeMarkdown$1(report.dataset.provenance.license)} |`,
		"",
		`${subheading} Gate outcomes`,
		"",
		"| Metric | Status | Coverage | Reason |",
		"| --- | --- | ---: | --- |",
		...metricStatus$1("Instantaneous speed", report.metrics.instantaneous.speed),
		...metricStatus$1("Instantaneous derivatives", report.metrics.instantaneous.derivatives),
		...metricStatus$1("Wall shear stress", report.metrics.instantaneous.wallShear),
		...metricStatus$1("Unweighted frame mean", report.metrics.frameMean),
		...metricStatus$1("Complete-cycle mean", report.metrics.completeCycle),
		"",
		"| Scope | Gate | Decision | Observed | Criterion | Detail |",
		"| --- | --- | --- | ---: | ---: | --- |",
		...gateRows("instantaneous speed", report.metrics.instantaneous.speed),
		...gateRows("instantaneous derivatives", report.metrics.instantaneous.derivatives),
		...gateRows("wall shear stress", report.metrics.instantaneous.wallShear),
		...gateRows("frame mean", report.metrics.frameMean),
		...gateRows("complete cycle", report.metrics.completeCycle),
		"",
		`${subheading} Available metrics`,
		""
	];
	const speed = report.metrics.instantaneous.speed;
	if (speed.status === "available") lines.push(`- Instantaneous ${escapeMarkdown$1(speed.value.quantity)}: mean ${formatted(speed.value.mean)} ${escapeMarkdown$1(speed.value.unit)}, RMS ${formatted(speed.value.rms)} ${escapeMarkdown$1(speed.value.unit)}, maximum ${formatted(speed.value.maximum)} ${escapeMarkdown$1(speed.value.unit)}.`);
	const derivatives = report.metrics.instantaneous.derivatives;
	if (derivatives.status === "available") lines.push(`- Postprocessed discrete divergence: RMS ${formatted(derivatives.value.divergence.rms)} 1/s, p95 absolute ${formatted(derivatives.value.divergence.p95Absolute)} 1/s, maximum absolute ${formatted(derivatives.value.divergence.maximumAbsolute)} 1/s.`, `- Vorticity/curl (${escapeMarkdown$1(derivatives.value.vorticity.representation)}): mean magnitude ${formatted(derivatives.value.vorticity.meanMagnitude)} 1/s, maximum magnitude ${formatted(derivatives.value.vorticity.maximumMagnitude)} 1/s.`, `- Strain-rate magnitude (${escapeMarkdown$1(derivatives.value.strainRate.convention)}): mean ${formatted(derivatives.value.strainRate.mean)} 1/s, maximum ${formatted(derivatives.value.strainRate.maximum)} 1/s.`);
	const wallShear = report.metrics.instantaneous.wallShear;
	if (wallShear.status === "available") lines.push(`- Wall shear stress (${escapeMarkdown$1(wallShear.value.method)}): mean magnitude ${formatted(wallShear.value.meanMagnitude)} Pa, maximum magnitude ${formatted(wallShear.value.maximumMagnitude)} Pa.`);
	const frameMean = report.metrics.frameMean;
	if (frameMean.status === "available") lines.push(`- Unweighted frame mean of spatial mean speed: ${formatted(frameMean.value.spatialMeanSpeed)} ${escapeMarkdown$1(frameMean.value.unit)} across ${frameMean.value.contributingFrames}/${frameMean.value.totalFrames} frames.`);
	const cycle = report.metrics.completeCycle;
	if (cycle.status === "available") lines.push(cycle.value.duration === null ? `- Complete-cycle time mean of spatial mean speed: ${formatted(cycle.value.spatialMeanSpeed)} ${escapeMarkdown$1(cycle.value.unit)}; duration unavailable.` : `- Complete-cycle time mean of spatial mean speed: ${formatted(cycle.value.spatialMeanSpeed)} ${escapeMarkdown$1(cycle.value.unit)} over ${formatted(cycle.value.duration)} ${escapeMarkdown$1(report.dataset.temporal.timestampUnit)}.`);
	if (speed.status !== "available" && derivatives.status !== "available" && wallShear.status !== "available" && frameMean.status !== "available" && cycle.status !== "available") lines.push("- No requested metric passed its declared evidence gate.");
	lines.push("", `${subheading} Source records`, "");
	for (const source of report.dataset.provenance.sources) lines.push(`- ${escapeMarkdown$1(source.path)} (${escapeMarkdown$1(source.format)}, ${source.byteLength} bytes): \`${escapeMarkdown$1(source.sha256)}\`; expected digest ${source.expectedSha256 === null ? "explicitly unpinned" : `\`${escapeMarkdown$1(source.expectedSha256)}\``}.`);
	lines.push("", `${subheading} Transformations`, "");
	if (report.dataset.provenance.transformations.length === 0) lines.push("- No source transformation was declared.");
	else for (const transformation of report.dataset.provenance.transformations) lines.push(`- ${escapeMarkdown$1(transformation)}`);
	lines.push("", `${subheading} Provenance software`, "", "| Name | Version | Source digest |", "| --- | --- | --- |");
	for (const software of report.dataset.provenance.software) lines.push(`| ${escapeMarkdown$1(software.name)} | ${escapeMarkdown$1(software.version)} | ${software.sha256 === null ? "not declared" : `\`${escapeMarkdown$1(software.sha256)}\``} |`);
	lines.push("", `${subheading} Limitations`, "");
	for (const limitation of report.limitations) lines.push(`- ${escapeMarkdown$1(limitation)}`);
	return lines;
}
function renderVectorEvidenceReportMarkdown(report) {
	return `${singleReportMarkdown(report, 1).join("\n")}\n`;
}
//#endregion
//#region src/application/sha256.ts
async function sha256Text(value) {
	const payload = new TextEncoder().encode(value);
	const digest = await globalThis.crypto.subtle.digest("SHA-256", payload);
	return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
//#endregion
//#region src/domain/evidence.ts
function countCoverage(valid, eligible) {
	return {
		valid,
		eligible,
		fraction: eligible === 0 ? 0 : valid / eligible
	};
}
//#endregion
//#region src/domain/numericalSafety.ts
function finite$1(value) {
	return Number.isFinite(value) ? value : null;
}
function maximumAbsolute(values) {
	let maximum = 0;
	for (const value of values) {
		if (!Number.isFinite(value)) return null;
		maximum = Math.max(maximum, Math.abs(value));
	}
	return maximum;
}
function numericExtrema(values) {
	let minimum = Number.POSITIVE_INFINITY;
	let maximum = Number.NEGATIVE_INFINITY;
	for (const value of values) {
		minimum = Math.min(minimum, value);
		maximum = Math.max(maximum, value);
	}
	return {
		minimum,
		maximum
	};
}
function compensatedNormalizedSum(values, scale) {
	let sum = 0;
	let correction = 0;
	for (const value of values) {
		const adjusted = value / scale - correction;
		const next = sum + adjusted;
		correction = next - sum - adjusted;
		sum = next;
	}
	return sum;
}
function safeNorm(values) {
	let scale = 0;
	let scaledSquares = 0;
	for (const value of values) {
		if (!Number.isFinite(value)) return null;
		const magnitude = Math.abs(value);
		if (magnitude === 0) continue;
		if (scale < magnitude) {
			const ratio = scale / magnitude;
			scaledSquares = 1 + scaledSquares * ratio * ratio;
			scale = magnitude;
		} else {
			const ratio = magnitude / scale;
			scaledSquares += ratio * ratio;
		}
	}
	if (scale === 0) return 0;
	return finite$1(scale * Math.sqrt(scaledSquares));
}
function safeRms(values) {
	if (values.length === 0) return null;
	let scale = 0;
	let scaledSquares = 0;
	for (const value of values) {
		if (!Number.isFinite(value)) return null;
		const magnitude = Math.abs(value);
		if (magnitude === 0) continue;
		if (scale < magnitude) {
			const ratio = scale / magnitude;
			scaledSquares = 1 + scaledSquares * ratio * ratio;
			scale = magnitude;
		} else {
			const ratio = magnitude / scale;
			scaledSquares += ratio * ratio;
		}
	}
	if (scale === 0) return 0;
	return finite$1(scale * Math.sqrt(scaledSquares / values.length));
}
function safeMean(values) {
	if (values.length === 0) return null;
	let directTotal = 0;
	for (const value of values) directTotal += value;
	const directMean = directTotal / values.length;
	if (Number.isFinite(directMean)) return directMean;
	const scale = maximumAbsolute(values);
	if (scale === null) return null;
	if (scale === 0) return 0;
	return finite$1(scale * Math.max(-1, Math.min(1, compensatedNormalizedSum(values, scale) / values.length)));
}
function safeSum(values) {
	let direct = 0;
	for (const value of values) direct += value;
	if (Number.isFinite(direct)) return direct;
	const scale = maximumAbsolute(values);
	if (scale === null) return null;
	if (scale === 0) return 0;
	return finite$1(scale * compensatedNormalizedSum(values, scale));
}
function safeDifference(a, b) {
	if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
	const direct = a - b;
	if (Number.isFinite(direct)) return direct;
	const scale = Math.max(Math.abs(a), Math.abs(b));
	if (scale === 0) return 0;
	return finite$1(scale * (a / scale - b / scale));
}
function safeDifferenceQuotient(a, b, denominator) {
	if (!Number.isFinite(denominator) || denominator === 0) return null;
	if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
	const direct = (a - b) / denominator;
	if (Number.isFinite(direct)) return direct;
	const scale = Math.max(Math.abs(a), Math.abs(b));
	if (scale === 0) return 0;
	const normalizedDifference = a / scale - b / scale;
	if (normalizedDifference === 0) return 0;
	const scaleOverDenominator = scale / denominator;
	if (Number.isFinite(scaleOverDenominator)) return finite$1(normalizedDifference * scaleOverDenominator);
	const denominatorOverScale = denominator / scale;
	if (denominatorOverScale === 0) return null;
	return finite$1(normalizedDifference / denominatorOverScale);
}
function safeLinearInterpolate(lower, upper, fraction) {
	const direct = lower + fraction * (upper - lower);
	if (Number.isFinite(direct)) return direct;
	return safeWeightedMean([lower, upper], [1 - fraction, fraction]);
}
function safeWeightedMean(values, weights) {
	if (values.length === 0 || values.length !== weights.length) return null;
	let directWeightedTotal = 0;
	let directWeightTotal = 0;
	for (let index = 0; index < values.length; index += 1) {
		directWeightedTotal += values[index] * weights[index];
		directWeightTotal += weights[index];
	}
	const direct = directWeightedTotal / directWeightTotal;
	if (Number.isFinite(direct) && directWeightTotal > 0) return direct;
	const valueScale = maximumAbsolute(values);
	const weightScale = maximumAbsolute(weights);
	if (valueScale === null || weightScale === null || weightScale === 0) return null;
	if (weights.some((weight) => weight < 0)) return null;
	if (valueScale === 0) return 0;
	const normalizedWeights = weights.map((weight) => weight / weightScale);
	const weightTotal = safeSum(normalizedWeights);
	if (weightTotal === null || weightTotal <= 0) return null;
	const weightedTotal = safeSum(values.map((value, index) => value / valueScale * normalizedWeights[index]));
	if (weightedTotal === null) return null;
	return finite$1(valueScale * Math.max(-1, Math.min(1, weightedTotal / weightTotal)));
}
function safeProduct(first, second) {
	if (!Number.isFinite(first) || !Number.isFinite(second)) return null;
	return finite$1(first * second);
}
function safeProductQuotient(first, second, denominator) {
	if (!Number.isFinite(first) || !Number.isFinite(second) || !Number.isFinite(denominator) || denominator === 0) return null;
	for (const candidate of [
		first * second / denominator,
		first / denominator * second,
		second / denominator * first
	]) if (Number.isFinite(candidate)) return candidate;
	return null;
}
function safeDot(first, second) {
	if (first.length !== second.length) return null;
	const products = [];
	for (let index = 0; index < first.length; index += 1) {
		const product = safeProduct(first[index], second[index]);
		if (product === null) return null;
		products.push(product);
	}
	return safeSum(products);
}
//#endregion
//#region src/domain/statistics.ts
function nearestRankPercentile(values, probability) {
	validateSample(values, probability);
	const sorted = [...values].sort((a, b) => a - b);
	const index = Math.ceil(probability * sorted.length) - 1;
	return sorted[Math.max(0, Math.min(index, sorted.length - 1))];
}
function linearQuantile(values, probability) {
	validateSample(values, probability);
	const sorted = [...values].sort((a, b) => a - b);
	if (sorted.length === 1) return sorted[0];
	const position = (sorted.length - 1) * probability;
	const lowerIndex = Math.floor(position);
	const upperIndex = Math.ceil(position);
	const fraction = position - lowerIndex;
	return sorted[lowerIndex] * (1 - fraction) + sorted[upperIndex] * fraction;
}
function validateSample(values, probability) {
	if (values.length === 0) throw new Error("Cannot calculate a quantile of an empty sample.");
	if (!values.every(Number.isFinite)) throw new Error("Quantile samples must contain only finite values.");
	if (!Number.isFinite(probability) || probability < 0 || probability > 1) throw new Error("Quantile probability must lie between zero and one.");
}
//#endregion
//#region src/domain/agreementMetrics.ts
function metric(value, definition, coverage) {
	return {
		status: "available",
		value: {
			value,
			definition
		},
		coverage,
		gates: []
	};
}
function insufficient(reason, detail, coverage) {
	return {
		status: "insufficient-evidence",
		reason,
		detail,
		coverage,
		gates: []
	};
}
function unavailable(reason, detail) {
	return {
		status: "unavailable",
		reason,
		detail,
		gates: []
	};
}
function validateInputs(reference, estimate, eligibleMask, selectedMask, grid) {
	const pointCount = grid.width * grid.height;
	if (reference.length !== pointCount || estimate.length !== pointCount || eligibleMask.length !== pointCount || selectedMask.length !== pointCount) throw new Error("Agreement arrays and masks must match the comparison grid.");
	if (!reference.every(Number.isFinite) || !estimate.every(Number.isFinite)) throw new Error("Agreement fields must contain only finite values.");
}
function selectedIndices(eligibleMask, selectedMask) {
	const indices = [];
	for (let index = 0; index < eligibleMask.length; index += 1) if (eligibleMask[index] && selectedMask[index]) indices.push(index);
	return indices;
}
function centeredCorrelation(first, second) {
	const firstMean = safeMean(first);
	const secondMean = safeMean(second);
	if (firstMean === null || secondMean === null) return null;
	let covariance = 0;
	let firstSquares = 0;
	let secondSquares = 0;
	for (let index = 0; index < first.length; index += 1) {
		const firstCentered = first[index] - firstMean;
		const secondCentered = second[index] - secondMean;
		covariance += firstCentered * secondCentered;
		firstSquares += firstCentered * firstCentered;
		secondSquares += secondCentered * secondCentered;
	}
	if (firstSquares === 0 || secondSquares === 0) return NaN;
	const value = covariance / Math.sqrt(firstSquares * secondSquares);
	return Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : null;
}
function averageRanks(values) {
	const order = values.map((value, index) => ({
		value,
		index
	}));
	order.sort((left, right) => left.value - right.value || left.index - right.index);
	const ranks = Array(values.length);
	let start = 0;
	while (start < order.length) {
		let end = start + 1;
		while (end < order.length && order[end].value === order[start].value) end += 1;
		const rank = (start + 1 + end) / 2;
		for (let index = start; index < end; index += 1) ranks[order[index].index] = rank;
		start = end;
	}
	return ranks;
}
function indexCoordinates(grid, index) {
	const x = index % grid.width;
	const y = Math.floor(index / grid.width);
	return [grid.originX + x * grid.spacingX, grid.originY + y * grid.spacingY];
}
function peakEvidence(reference, estimate, indices, coverage, grid) {
	if (indices.length === 0) return unavailable("comparison-domain-empty", "No paired point is available for peak comparison.");
	let pivIndex = indices[0];
	let cfdIndex = indices[0];
	for (const index of indices.slice(1)) {
		if (reference[index] > reference[pivIndex]) pivIndex = index;
		if (estimate[index] > estimate[cfdIndex]) cfdIndex = index;
	}
	const pivLocation = indexCoordinates(grid, pivIndex);
	const cfdLocation = indexCoordinates(grid, cfdIndex);
	const signedMagnitudeDifference = estimate[cfdIndex] - reference[pivIndex];
	return {
		status: "available",
		value: {
			pivMagnitude: reference[pivIndex],
			cfdMagnitude: estimate[cfdIndex],
			signedMagnitudeDifference,
			absoluteMagnitudeDifference: Math.abs(signedMagnitudeDifference),
			locationDisplacement: Math.hypot(cfdLocation[0] - pivLocation[0], cfdLocation[1] - pivLocation[1]),
			pivIndex,
			cfdIndex,
			definition: "Independent maxima over the selected paired points; location displacement uses the registered physical grid."
		},
		coverage,
		gates: []
	};
}
function emptyMetricSet(reason, detail, coverage) {
	const result = () => insufficient(reason, detail, coverage);
	return {
		coverage: {
			pairedPoints: coverage.valid,
			eligiblePoints: coverage.eligible,
			pairedFraction: coverage.fraction
		},
		signedBias: result(),
		meanAbsoluteError: result(),
		rangeNormalizedRmse: result(),
		pearsonCorrelation: result(),
		spearmanCorrelation: result(),
		peak: result(),
		hotspotRecall: result(),
		hotspotJaccard: result()
	};
}
function createAgreementReferenceContext(reference, eligibleMask, hotspotPercentile) {
	if (!Number.isFinite(hotspotPercentile) || hotspotPercentile <= 0 || hotspotPercentile >= 1) throw new Error("Hotspot percentile must lie strictly between zero and one.");
	if (reference.length !== eligibleMask.length) throw new Error("Reference values and eligibility mask must have equal length.");
	const values = reference.filter((_, index) => eligibleMask[index]);
	if (values.length === 0) return unavailable("comparison-domain-empty", "The registered common domain contains no paired points.");
	const { minimum, maximum } = numericExtrema(values);
	return {
		status: "available",
		value: {
			minimum,
			maximum,
			range: maximum - minimum,
			hotspotPercentile,
			hotspotThreshold: nearestRankPercentile(values, hotspotPercentile),
			eligiblePoints: values.length
		},
		coverage: countCoverage(values.length, values.length),
		gates: []
	};
}
function evaluateAgreement(reference, estimate, eligibleMask, selectedMask, grid, context, method) {
	validateInputs(reference, estimate, eligibleMask, selectedMask, grid);
	const indices = selectedIndices(eligibleMask, selectedMask);
	const coverage = countCoverage(indices.length, context.eligiblePoints);
	const signedResidual = Array(reference.length).fill(null);
	const absoluteResidual = Array(reference.length).fill(null);
	for (const index of indices) {
		const residual = estimate[index] - reference[index];
		signedResidual[index] = residual;
		absoluteResidual[index] = Math.abs(residual);
	}
	if (indices.length === 0) return {
		method,
		metrics: emptyMetricSet("comparison-domain-empty", "The selected observation phase contains no paired points.", coverage),
		maps: {
			selectedMask: [...selectedMask],
			signedResidual,
			absoluteResidual
		}
	};
	const pivValues = indices.map((index) => reference[index]);
	const cfdValues = indices.map((index) => estimate[index]);
	const residuals = cfdValues.map((value, index) => value - pivValues[index]);
	const absoluteResiduals = residuals.map(Math.abs);
	const bias = safeMean(residuals);
	const mae = safeMean(absoluteResiduals);
	const rmse = safeRms(residuals);
	const numericalFailure = (definition) => insufficient("numerical-range-exceeded", `Finite inputs exceeded the representable range while calculating ${definition}.`, coverage);
	const signedBias = bias === null ? numericalFailure("signed bias") : metric(bias, "Arithmetic mean of CFD minus PIV over selected paired points.", coverage);
	const meanAbsoluteError = mae === null ? numericalFailure("mean absolute error") : metric(mae, "Arithmetic mean absolute CFD-minus-PIV residual over selected paired points.", coverage);
	const rangeNormalizedRmse = context.range === 0 ? insufficient("reference-range-zero", "PIV range on the fixed full common domain is zero.", coverage) : rmse === null || !Number.isFinite(rmse / context.range) ? numericalFailure("range-normalized RMSE") : metric(rmse / context.range, "RMSE over selected paired points divided by the PIV range on the fixed full common domain.", coverage);
	let pearsonCorrelation;
	let spearmanCorrelation;
	if (indices.length < 3) {
		pearsonCorrelation = insufficient("comparison-pairs-too-few", "Pearson correlation requires at least three paired points.", coverage);
		spearmanCorrelation = insufficient("comparison-pairs-too-few", "Spearman correlation requires at least three paired points.", coverage);
	} else {
		const pearson = centeredCorrelation(pivValues, cfdValues);
		pearsonCorrelation = Number.isNaN(pearson) ? insufficient("variance-zero", "Pearson correlation is undefined when either selected field has zero variance.", coverage) : pearson === null ? numericalFailure("Pearson correlation") : metric(pearson, "Ordinary Pearson product-moment correlation over selected paired points.", coverage);
		const spearman = centeredCorrelation(averageRanks(pivValues), averageRanks(cfdValues));
		spearmanCorrelation = Number.isNaN(spearman) ? insufficient("variance-zero", "Spearman correlation is undefined when either selected rank field has zero variance.", coverage) : spearman === null ? numericalFailure("Spearman correlation") : metric(spearman, "Spearman rank correlation using deterministic average ranks for ties.", coverage);
	}
	let referenceHotspots = 0;
	let intersection = 0;
	let union = 0;
	for (const index of indices) {
		const referenceHot = reference[index] >= context.hotspotThreshold;
		const estimateHot = estimate[index] >= context.hotspotThreshold;
		if (referenceHot) referenceHotspots += 1;
		if (referenceHot && estimateHot) intersection += 1;
		if (referenceHot || estimateHot) union += 1;
	}
	const hotspotRecall = referenceHotspots === 0 ? insufficient("hotspot-reference-empty", "The selected sparse phase contains no PIV point above the fixed full-domain top-decile threshold.", coverage) : metric(intersection / referenceHotspots, "Fraction of selected PIV top-decile points also classified as hot by CFD using the fixed full-domain PIV threshold.", coverage);
	const hotspotJaccard = union === 0 ? insufficient("hotspot-union-empty", "Neither selected field contains a point above the fixed full-domain PIV hotspot threshold.", coverage) : metric(intersection / union, "Intersection over union of selected PIV and CFD hotspots using the fixed full-domain PIV threshold.", coverage);
	return {
		method,
		metrics: {
			coverage: {
				pairedPoints: indices.length,
				eligiblePoints: context.eligiblePoints,
				pairedFraction: coverage.fraction
			},
			signedBias,
			meanAbsoluteError,
			rangeNormalizedRmse,
			pearsonCorrelation,
			spearmanCorrelation,
			peak: peakEvidence(reference, estimate, indices, coverage, grid),
			hotspotRecall,
			hotspotJaccard
		},
		maps: {
			selectedMask: [...selectedMask],
			signedResidual,
			absoluteResidual
		}
	};
}
//#endregion
//#region src/domain/regionalAgreementStudy.ts
var REGIONAL_AGREEMENT_STUDY_FAMILY = "regional-agreement-selection-sensitivity-v1";
var REGIONAL_AGREEMENT_METHOD_VERSION = "1.0.0";
var REGIONAL_AGREEMENT_PARTITION_KIND = "equal-grid-index-bins-v1";
var REGIONAL_AGREEMENT_REFERENCE_CONTEXT_POLICY = "full-nominal-valid-mask";
var REGIONAL_AGREEMENT_MAXIMUM_GRID_POINTS = 1e6;
var REGIONAL_AGREEMENT_MAXIMUM_POINT_WINDOW_EVALUATIONS = 5e7;
var REGIONAL_AGREEMENT_ENDPOINTS = [
	"pearsonCorrelation",
	"rangeNormalizedRmse",
	"meanAbsoluteError",
	"hotspotRecall",
	"hotspotJaccard"
];
var validatedManifestInstances = /* @__PURE__ */ new WeakSet();
var SHA256$3 = /^[a-f0-9]{64}$/u;
function fail$2(path, detail) {
	throw new Error(`${path}: ${detail}`);
}
function record$2(value, path) {
	if (typeof value !== "object" || value === null || Array.isArray(value)) fail$2(path, "must be an object.");
	return value;
}
function assertKeys(value, allowed, path) {
	const allowedKeys = new Set(allowed);
	const unexpected = Object.keys(value).filter((key) => !allowedKeys.has(key));
	if (unexpected.length > 0) fail$2(path, `contains unsupported properties: ${unexpected.join(", ")}.`);
	for (const key of allowed) if (!Object.prototype.hasOwnProperty.call(value, key)) fail$2(path, `is missing required property ${JSON.stringify(key)}.`);
}
function text$3(value, path) {
	if (typeof value !== "string" || value.length === 0 || value.length > 4096) fail$2(path, "must be nonempty text no longer than 4,096 characters.");
	return value;
}
function integer$1(value, path, minimum, maximum) {
	if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || value > maximum) fail$2(path, `must be an integer from ${minimum} through ${maximum}.`);
	return value;
}
function finiteFraction(value, path) {
	if (typeof value !== "number" || !Number.isFinite(value) || value <= 0 || value >= 1) fail$2(path, "must lie strictly between zero and one.");
	return value;
}
function endpointArray(value, path) {
	if (!Array.isArray(value)) fail$2(path, "must be an array.");
	return value.map((item, index) => {
		if (typeof item !== "string" || !REGIONAL_AGREEMENT_ENDPOINTS.includes(item)) fail$2(`${path}[${index}]`, "is not a supported agreement endpoint.");
		return item;
	});
}
function textArray$1(value, path) {
	if (!Array.isArray(value)) fail$2(path, "must be an array.");
	return value.map((item, index) => text$3(item, `${path}[${index}]`));
}
function deepFreeze$1(value) {
	if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
	for (const child of Object.values(value)) deepFreeze$1(child);
	return Object.freeze(value);
}
function validateRegionalAgreementStudyManifest(value) {
	const item = record$2(value, "$");
	assertKeys(item, [
		"schemaVersion",
		"id",
		"actionId",
		"studyFamily",
		"methodVersion",
		"title",
		"classification",
		"source",
		"comparison",
		"partition",
		"sufficiency",
		"resourceBounds",
		"endpoints",
		"interpretationBoundary"
	], "$");
	if (item.schemaVersion !== 1) fail$2("$.schemaVersion", "must be 1.");
	if (item.studyFamily !== "regional-agreement-selection-sensitivity-v1") fail$2("$.studyFamily", `must be ${REGIONAL_AGREEMENT_STUDY_FAMILY}.`);
	if (item.methodVersion !== "1.0.0") fail$2("$.methodVersion", `must be ${REGIONAL_AGREEMENT_METHOD_VERSION}.`);
	if (item.classification !== "descriptive-spatial-selection-sensitivity") fail$2("$.classification", "must be descriptive-spatial-selection-sensitivity.");
	const id = text$3(item.id, "$.id");
	const actionId = text$3(item.actionId, "$.actionId");
	if (id !== actionId) fail$2("$.actionId", "must equal the study id.");
	const sourceValue = record$2(item.source, "$.source");
	assertKeys(sourceValue, [
		"adapterId",
		"registeredPairId",
		"artifact"
	], "$.source");
	const artifactValue = record$2(sourceValue.artifact, "$.source.artifact");
	assertKeys(artifactValue, [
		"reference",
		"byteLength",
		"sha256"
	], "$.source.artifact");
	const artifactSha256 = text$3(artifactValue.sha256, "$.source.artifact.sha256");
	if (!SHA256$3.test(artifactSha256)) fail$2("$.source.artifact.sha256", "must be a lowercase SHA-256 digest.");
	const comparisonValue = record$2(item.comparison, "$.comparison");
	assertKeys(comparisonValue, [
		"quantityMethod",
		"expectedGrid",
		"expectedNominalPairedPoints",
		"referenceContextPolicy",
		"hotspotPercentile"
	], "$.comparison");
	if (comparisonValue.quantityMethod !== "interpolated-supplied-vxy") fail$2("$.comparison.quantityMethod", "must be interpolated-supplied-vxy.");
	if (comparisonValue.referenceContextPolicy !== "full-nominal-valid-mask") fail$2("$.comparison.referenceContextPolicy", `must be ${REGIONAL_AGREEMENT_REFERENCE_CONTEXT_POLICY}.`);
	const expectedGridValue = record$2(comparisonValue.expectedGrid, "$.comparison.expectedGrid");
	assertKeys(expectedGridValue, ["width", "height"], "$.comparison.expectedGrid");
	const width = integer$1(expectedGridValue.width, "$.comparison.expectedGrid.width", 1, 4096);
	const height = integer$1(expectedGridValue.height, "$.comparison.expectedGrid.height", 1, 4096);
	const expectedNominalPairedPoints = integer$1(comparisonValue.expectedNominalPairedPoints, "$.comparison.expectedNominalPairedPoints", 1, width * height);
	const gridPoints = width * height;
	if (gridPoints > 1e6) fail$2("$.comparison.expectedGrid", `contains more than ${REGIONAL_AGREEMENT_MAXIMUM_GRID_POINTS} grid points.`);
	const partitionValue = record$2(item.partition, "$.partition");
	assertKeys(partitionValue, [
		"kind",
		"rows",
		"columns",
		"order",
		"idFormat"
	], "$.partition");
	if (partitionValue.kind !== "equal-grid-index-bins-v1") fail$2("$.partition.kind", `must be ${REGIONAL_AGREEMENT_PARTITION_KIND}.`);
	if (partitionValue.order !== "row-major") fail$2("$.partition.order", "must be row-major.");
	if (partitionValue.idFormat !== "row-{row}-column-{column}") fail$2("$.partition.idFormat", "must be row-{row}-column-{column}.");
	const rows = integer$1(partitionValue.rows, "$.partition.rows", 1, 16);
	const columns = integer$1(partitionValue.columns, "$.partition.columns", 1, 16);
	if (rows > height || columns > width || rows * columns > 256) fail$2("$.partition", `must fit the declared grid and contain at most 256 windows.`);
	const sufficiencyValue = record$2(item.sufficiency, "$.sufficiency");
	assertKeys(sufficiencyValue, [
		"minimumPairedPoints",
		"belowMinimumStatus",
		"belowMinimumReason"
	], "$.sufficiency");
	if (sufficiencyValue.belowMinimumStatus !== "insufficient-evidence") fail$2("$.sufficiency.belowMinimumStatus", "must be insufficient-evidence.");
	if (sufficiencyValue.belowMinimumReason !== "paired-points-below-preregistered-minimum") fail$2("$.sufficiency.belowMinimumReason", "must be paired-points-below-preregistered-minimum.");
	const minimumPairedPoints = integer$1(sufficiencyValue.minimumPairedPoints, "$.sufficiency.minimumPairedPoints", 1, expectedNominalPairedPoints);
	const resourceValue = record$2(item.resourceBounds, "$.resourceBounds");
	assertKeys(resourceValue, [
		"maximumGridPoints",
		"maximumWindows",
		"maximumPointWindowEvaluations"
	], "$.resourceBounds");
	const maximumGridPoints = integer$1(resourceValue.maximumGridPoints, "$.resourceBounds.maximumGridPoints", gridPoints, REGIONAL_AGREEMENT_MAXIMUM_GRID_POINTS);
	const windowCount = rows * columns;
	const maximumWindows = integer$1(resourceValue.maximumWindows, "$.resourceBounds.maximumWindows", windowCount, 256);
	const pointWindowEvaluations = gridPoints * windowCount;
	const maximumPointWindowEvaluations = integer$1(resourceValue.maximumPointWindowEvaluations, "$.resourceBounds.maximumPointWindowEvaluations", pointWindowEvaluations, REGIONAL_AGREEMENT_MAXIMUM_POINT_WINDOW_EVALUATIONS);
	const endpointsValue = record$2(item.endpoints, "$.endpoints");
	assertKeys(endpointsValue, ["primary", "secondary"], "$.endpoints");
	const primary = endpointArray(endpointsValue.primary, "$.endpoints.primary");
	const secondary = endpointArray(endpointsValue.secondary, "$.endpoints.secondary");
	if (primary.length === 0) fail$2("$.endpoints.primary", "must declare at least one primary endpoint.");
	const endpoints = [...primary, ...secondary];
	if (new Set(endpoints).size !== endpoints.length) fail$2("$.endpoints", "must not repeat an endpoint.");
	const interpretationBoundary = textArray$1(item.interpretationBoundary, "$.interpretationBoundary");
	if (interpretationBoundary.length === 0) fail$2("$.interpretationBoundary", "must not be empty.");
	const validated = deepFreeze$1({
		schemaVersion: 1,
		id,
		actionId,
		studyFamily: REGIONAL_AGREEMENT_STUDY_FAMILY,
		methodVersion: REGIONAL_AGREEMENT_METHOD_VERSION,
		title: text$3(item.title, "$.title"),
		classification: "descriptive-spatial-selection-sensitivity",
		source: {
			adapterId: text$3(sourceValue.adapterId, "$.source.adapterId"),
			registeredPairId: text$3(sourceValue.registeredPairId, "$.source.registeredPairId"),
			artifact: {
				reference: text$3(artifactValue.reference, "$.source.artifact.reference"),
				byteLength: integer$1(artifactValue.byteLength, "$.source.artifact.byteLength", 1, 1073741824),
				sha256: artifactSha256
			}
		},
		comparison: {
			quantityMethod: "interpolated-supplied-vxy",
			expectedGrid: {
				width,
				height
			},
			expectedNominalPairedPoints,
			referenceContextPolicy: REGIONAL_AGREEMENT_REFERENCE_CONTEXT_POLICY,
			hotspotPercentile: finiteFraction(comparisonValue.hotspotPercentile, "$.comparison.hotspotPercentile")
		},
		partition: {
			kind: REGIONAL_AGREEMENT_PARTITION_KIND,
			rows,
			columns,
			order: "row-major",
			idFormat: "row-{row}-column-{column}"
		},
		sufficiency: {
			minimumPairedPoints,
			belowMinimumStatus: "insufficient-evidence",
			belowMinimumReason: "paired-points-below-preregistered-minimum"
		},
		resourceBounds: {
			maximumGridPoints,
			maximumWindows,
			maximumPointWindowEvaluations
		},
		endpoints: {
			primary,
			secondary
		},
		interpretationBoundary
	});
	validatedManifestInstances.add(validated);
	return validated;
}
function assertValidatedRegionalAgreementStudyManifest(manifest) {
	if (!validatedManifestInstances.has(manifest) || !Object.isFrozen(manifest)) throw new Error("Regional agreement study execution requires a manifest returned by the validator.");
}
function regionalPartitionIndex(index, size, partitions) {
	if (!Number.isInteger(index) || !Number.isInteger(size) || !Number.isInteger(partitions) || size <= 0 || partitions <= 0 || partitions > size || index < 0 || index >= size) throw new Error("Regional partition indices must lie inside a positive, bounded grid axis.");
	return Math.min(partitions - 1, Math.floor(partitions * index / size));
}
function regionalWindowId(row, column) {
	if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0) throw new Error("Regional window row and column must be nonnegative.");
	return `row-${row}-column-${column}`;
}
function regionalWindowForGridIndex(grid, partition, x, y) {
	return regionalWindowId(regionalPartitionIndex(y, grid.height, partition.rows), regionalPartitionIndex(x, grid.width, partition.columns));
}
function regionalWindowSelectionMask(grid, partition, id) {
	const mask = Array(grid.width * grid.height);
	for (let y = 0; y < grid.height; y += 1) for (let x = 0; x < grid.width; x += 1) mask[y * grid.width + x] = regionalWindowForGridIndex(grid, partition, x, y) === id;
	return mask;
}
function axisBounds(size, partitions, partition) {
	let minimum = -1;
	let maximum = -1;
	for (let index = 0; index < size; index += 1) {
		if (regionalPartitionIndex(index, size, partitions) !== partition) continue;
		if (minimum === -1) minimum = index;
		maximum = index;
	}
	if (minimum === -1 || maximum === -1) throw new Error("Every regional partition must contain a grid index.");
	return [minimum, maximum];
}
function buildRegionalWindowDefinitions(grid, manifest, coordinateAxes) {
	if (coordinateAxes !== void 0 && (coordinateAxes.x.length !== grid.width || coordinateAxes.y.length !== grid.height)) throw new Error("Regional agreement coordinate axes do not match the grid shape.");
	const definitions = [];
	for (let row = 0; row < manifest.partition.rows; row += 1) for (let column = 0; column < manifest.partition.columns; column += 1) {
		const [xMinimum, xMaximum] = axisBounds(grid.width, manifest.partition.columns, column);
		const [yMinimum, yMaximum] = axisBounds(grid.height, manifest.partition.rows, row);
		definitions.push({
			id: regionalWindowId(row, column),
			row,
			column,
			gridIndexBounds: {
				xMinimum,
				xMaximum,
				yMinimum,
				yMaximum
			},
			physicalCoordinateBounds: {
				xMinimum: coordinateAxes?.x[xMinimum] ?? grid.originX + xMinimum * grid.spacingX,
				xMaximum: coordinateAxes?.x[xMaximum] ?? grid.originX + xMaximum * grid.spacingX,
				yMinimum: coordinateAxes?.y[yMinimum] ?? grid.originY + yMinimum * grid.spacingY,
				yMaximum: coordinateAxes?.y[yMaximum] ?? grid.originY + yMaximum * grid.spacingY,
				unit: grid.coordinateUnit
			},
			cropPoints: (xMaximum - xMinimum + 1) * (yMaximum - yMinimum + 1)
		});
	}
	return definitions;
}
function endpointEvidence(metrics, endpoint) {
	if (endpoint === "pearsonCorrelation") return metrics.pearsonCorrelation;
	if (endpoint === "rangeNormalizedRmse") return metrics.rangeNormalizedRmse;
	if (endpoint === "meanAbsoluteError") return metrics.meanAbsoluteError;
	if (endpoint === "hotspotRecall") return metrics.hotspotRecall;
	return metrics.hotspotJaccard;
}
function baselineMetric$1(evidence) {
	if (evidence.status === "available") return {
		status: "available",
		value: evidence.value.value,
		definition: evidence.value.definition
	};
	return {
		status: evidence.status,
		reason: evidence.reason,
		detail: evidence.detail
	};
}
function windowMetric$1(evidence, baseline) {
	if (evidence.status === "available") return {
		status: "available",
		value: evidence.value.value,
		absoluteDeltaFromFull: baseline.status === "available" ? Math.abs(evidence.value.value - baseline.value) : null,
		definition: evidence.value.definition
	};
	return {
		status: evidence.status,
		reason: evidence.reason,
		detail: evidence.detail
	};
}
function pairedPoints(eligibleMask, selectedMask) {
	let count = 0;
	for (let index = 0; index < eligibleMask.length; index += 1) if (eligibleMask[index] && selectedMask[index]) count += 1;
	return count;
}
function endpointSummary(endpoint, baseline, windows) {
	const values = windows.flatMap((window) => {
		if (window.status !== "available") return [];
		const metric = window.metrics[endpoint];
		return metric?.status === "available" ? [{
			windowId: window.window.id,
			value: metric.value,
			absoluteDeltaFromFull: metric.absoluteDeltaFromFull
		}] : [];
	});
	if (values.length === 0) return {
		endpoint,
		fullBaseline: baseline.status === "available" ? baseline.value : null,
		validWindows: 0,
		insufficientWindows: windows.length,
		minimum: null,
		maximum: null,
		range: null,
		maximumAbsoluteDeltaFromFull: null
	};
	const minimum = values.reduce((best, item) => item.value < best.value ? item : best);
	const maximum = values.reduce((best, item) => item.value > best.value ? item : best);
	const valuesWithDelta = values.filter((item) => item.absoluteDeltaFromFull !== null);
	const maximumAbsoluteDeltaFromFull = valuesWithDelta.length === 0 ? null : valuesWithDelta.reduce((best, item) => item.absoluteDeltaFromFull > best.absoluteDeltaFromFull ? item : best);
	return {
		endpoint,
		fullBaseline: baseline.status === "available" ? baseline.value : null,
		validWindows: values.length,
		insufficientWindows: windows.length - values.length,
		minimum,
		maximum,
		range: maximum.value - minimum.value,
		maximumAbsoluteDeltaFromFull
	};
}
function allSelected(length) {
	return Array(length).fill(true);
}
function declaredEndpoints(manifest) {
	return [...manifest.endpoints.primary, ...manifest.endpoints.secondary];
}
function runRegionalAgreementStudy(pair, manifest) {
	assertValidatedRegionalAgreementStudyManifest(manifest);
	const grid = pair.piv.field;
	const eligibleMask = pair.cfd.vectorField.frames[0].validMask;
	const nominalPairedPoints = eligibleMask.filter(Boolean).length;
	if (pair.id !== manifest.source.registeredPairId || grid.width !== manifest.comparison.expectedGrid.width || grid.height !== manifest.comparison.expectedGrid.height || nominalPairedPoints !== manifest.comparison.expectedNominalPairedPoints || pair.maskSummary.nominalCfdValid !== nominalPairedPoints) throw new Error("The parsed registered pair does not match the frozen regional-study manifest.");
	if (manifest.partition.rows > grid.height || manifest.partition.columns > grid.width) throw new Error("The regional partition does not fit the parsed grid.");
	const context = createAgreementReferenceContext(grid.values, eligibleMask, manifest.comparison.hotspotPercentile);
	if (context.status !== "available") throw new Error(`Full nominal reference context is unavailable: ${context.reason}: ${context.detail}`);
	const fullComparison = evaluateAgreement(grid.values, pair.cfd.nominalSuppliedVxy, eligibleMask, allSelected(grid.values.length), grid, context.value, manifest.comparison.quantityMethod);
	const endpoints = declaredEndpoints(manifest);
	const baselineMetrics = Object.fromEntries(endpoints.map((endpoint) => [endpoint, baselineMetric$1(endpointEvidence(fullComparison.metrics, endpoint))]));
	const windows = buildRegionalWindowDefinitions(grid, manifest, pair.coordinateAxes).map((window) => {
		const selectionMask = regionalWindowSelectionMask(grid, manifest.partition, window.id);
		const count = pairedPoints(eligibleMask, selectionMask);
		if (count < manifest.sufficiency.minimumPairedPoints) return {
			status: "insufficient-evidence",
			reason: manifest.sufficiency.belowMinimumReason,
			detail: `${window.id} contains ${count} paired points; the preregistered minimum is ${manifest.sufficiency.minimumPairedPoints}.`,
			window,
			pairedPoints: count,
			minimumPairedPoints: manifest.sufficiency.minimumPairedPoints,
			metrics: null
		};
		const comparison = evaluateAgreement(grid.values, pair.cfd.nominalSuppliedVxy, eligibleMask, selectionMask, grid, context.value, manifest.comparison.quantityMethod);
		return {
			status: "available",
			window,
			pairedPoints: count,
			metrics: Object.fromEntries(endpoints.map((endpoint) => {
				const baseline = baselineMetrics[endpoint];
				if (baseline === void 0) throw new Error(`Missing baseline metric for ${endpoint}.`);
				return [endpoint, windowMetric$1(endpointEvidence(comparison.metrics, endpoint), baseline)];
			}))
		};
	});
	return {
		schemaVersion: 1,
		action: manifest.actionId,
		study: {
			id: manifest.id,
			title: manifest.title,
			family: manifest.studyFamily,
			classification: manifest.classification
		},
		source: {
			adapterId: manifest.source.adapterId,
			registeredPairId: pair.id,
			artifact: manifest.source.artifact,
			piv: {
				title: pair.piv.provenance.title,
				doi: pair.piv.provenance.doi,
				fileName: pair.piv.provenance.sourceFile,
				sha256: pair.piv.provenance.sourceSha256
			},
			cfd: {
				title: pair.cfd.record.title,
				doi: pair.cfd.record.doi,
				participant: pair.cfd.record.participant,
				caseName: pair.cfd.record.caseName,
				fileName: pair.cfd.source.fileName,
				sha256: pair.cfd.source.sha256,
				decompressedSha256: pair.cfd.source.decompressedSha256
			}
		},
		protocol: {
			quantityMethod: manifest.comparison.quantityMethod,
			expectedGrid: manifest.comparison.expectedGrid,
			partition: manifest.partition,
			windowOrder: windows.map(({ window }) => window.id),
			minimumPairedPoints: manifest.sufficiency.minimumPairedPoints,
			referenceContextPolicy: manifest.comparison.referenceContextPolicy,
			hotspotPercentile: manifest.comparison.hotspotPercentile,
			endpoints: manifest.endpoints
		},
		referenceContext: context.value,
		baseline: {
			domain: "full nominal supplied-Vxy comparison domain",
			pairedPoints: fullComparison.metrics.coverage.pairedPoints,
			metrics: baselineMetrics
		},
		windows,
		endpointSummaries: endpoints.map((endpoint) => {
			const baseline = baselineMetrics[endpoint];
			if (baseline === void 0) throw new Error(`Missing baseline metric for ${endpoint}.`);
			return endpointSummary(endpoint, baseline, windows);
		}),
		claimBoundary: manifest.interpretationBoundary
	};
}
//#endregion
//#region src/application/regionalAgreementStudyLifecycle.ts
function deepFreeze(value) {
	if (typeof value !== "object" || value === null || Object.isFrozen(value)) return value;
	for (const child of Object.values(value)) deepFreeze(child);
	return Object.freeze(value);
}
function validateRegionalAgreementStudyDraft(draft) {
	return validateRegionalAgreementStudyManifest(draft);
}
async function freezeRegionalAgreementStudyManifest(manifest) {
	assertValidatedRegionalAgreementStudyManifest(manifest);
	const canonicalManifest = stableJson(manifest);
	const byteLength = new TextEncoder().encode(canonicalManifest).byteLength;
	const digest = await sha256Text(canonicalManifest);
	return deepFreeze({
		manifest,
		canonicalManifest,
		receipt: {
			schemaVersion: 1,
			id: `${manifest.id}--manifest-freeze-v1`,
			studyId: manifest.id,
			studyFamily: manifest.studyFamily,
			methodVersion: manifest.methodVersion,
			manifest: {
				canonicalization: "stable-json-v1",
				byteLength,
				sha256: digest
			},
			sourceArtifact: manifest.source.artifact,
			sourceAdapterId: manifest.source.adapterId,
			protocol: {
				rows: manifest.partition.rows,
				columns: manifest.partition.columns,
				minimumPairedPoints: manifest.sufficiency.minimumPairedPoints,
				primaryEndpoints: manifest.endpoints.primary,
				secondaryEndpoints: manifest.endpoints.secondary
			},
			resourceBounds: manifest.resourceBounds
		}
	});
}
async function verifyFrozenRegionalAgreementStudyFreeze(frozen) {
	if (!Object.isFrozen(frozen) || !Object.isFrozen(frozen.manifest) || !Object.isFrozen(frozen.receipt)) throw new Error("Regional-study execution requires an immutable freeze package.");
	const canonicalManifest = stableJson(frozen.manifest);
	const byteLength = new TextEncoder().encode(canonicalManifest).byteLength;
	const digest = await sha256Text(canonicalManifest);
	if (frozen.canonicalManifest !== canonicalManifest || frozen.receipt.studyId !== frozen.manifest.id || frozen.receipt.schemaVersion !== 1 || frozen.receipt.id !== `${frozen.manifest.id}--manifest-freeze-v1` || frozen.receipt.studyFamily !== frozen.manifest.studyFamily || frozen.receipt.methodVersion !== frozen.manifest.methodVersion || frozen.receipt.sourceAdapterId !== frozen.manifest.source.adapterId || frozen.receipt.manifest.canonicalization !== "stable-json-v1" || frozen.receipt.manifest.byteLength !== byteLength || frozen.receipt.manifest.sha256 !== digest || stableJson(frozen.receipt.sourceArtifact) !== stableJson(frozen.manifest.source.artifact) || stableJson(frozen.receipt.protocol) !== stableJson({
		rows: frozen.manifest.partition.rows,
		columns: frozen.manifest.partition.columns,
		minimumPairedPoints: frozen.manifest.sufficiency.minimumPairedPoints,
		primaryEndpoints: frozen.manifest.endpoints.primary,
		secondaryEndpoints: frozen.manifest.endpoints.secondary
	}) || stableJson(frozen.receipt.resourceBounds) !== stableJson(frozen.manifest.resourceBounds)) throw new Error("The regional-study manifest no longer matches its freeze receipt.");
}
async function runFrozenRegionalAgreementStudy(pair, frozen) {
	await verifyFrozenRegionalAgreementStudyFreeze(frozen);
	return {
		freezeReceipt: frozen.receipt,
		study: runRegionalAgreementStudy(pair, frozen.manifest)
	};
}
//#endregion
//#region tools/catalogResearch/catalogTrustedSidecar.ts
var FLOWBLIND_CATALOG_TRUSTED_SIDECAR_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-trusted-source-sidecar-v2.schema.json";
var SHARED_KEYS = [
	"schemaVersion",
	"quantity",
	"sourceMeaning",
	"referenceRole",
	"referenceMeaning",
	"candidateRole",
	"candidateMeaning",
	"coordinateUnit",
	"valueUnit",
	"provenance",
	"license",
	"coordinateDimensionality",
	"singleFrame"
];
var BINDING_KEYS = [
	"candidateReference",
	"candidateByteLength",
	"candidateSha256"
];
var JSON_WHITESPACE = /* @__PURE__ */ new Set([
	" ",
	"	",
	"\r",
	"\n"
]);
var HEX_PATTERN = /^[0-9a-fA-F]{4}$/u;
var SHA256_PATTERN = /^[a-f0-9]{64}$/u;
var UTF8_BOM$1 = Buffer.from([
	239,
	187,
	191
]);
function invalidSidecar(detail, cause) {
	throw new CatalogResearchError("sidecar-invalid", "input-validation", detail, cause === void 0 ? void 0 : { cause });
}
function strictUtf8$3(bytes) {
	if (bytes.byteLength >= UTF8_BOM$1.byteLength && Buffer.from(bytes.subarray(0, UTF8_BOM$1.byteLength)).equals(UTF8_BOM$1)) invalidSidecar("Trusted sidecars must use UTF-8 without a byte-order mark.");
	try {
		return new TextDecoder("utf-8", {
			fatal: true,
			ignoreBOM: true
		}).decode(bytes);
	} catch (error) {
		invalidSidecar("Trusted sidecars must contain complete strict UTF-8.", error);
	}
}
function containsUnpairedSurrogate(value) {
	for (let index = 0; index < value.length; index += 1) {
		const code = value.charCodeAt(index);
		if (code >= 55296 && code <= 56319) {
			const next = value.charCodeAt(index + 1);
			if (next < 56320 || next > 57343) return true;
			index += 1;
		} else if (code >= 56320 && code <= 57343) return true;
	}
	return false;
}
function parseStrictFlatJsonObject(text) {
	let index = 0;
	const document = Object.create(null);
	const seen = /* @__PURE__ */ new Set();
	const skipWhitespace = () => {
		while (index < text.length && JSON_WHITESPACE.has(text[index])) index += 1;
	};
	const parseString = () => {
		if (text[index] !== "\"") invalidSidecar("Trusted sidecars must contain one strict JSON object.");
		const start = index;
		index += 1;
		while (index < text.length) {
			const character = text[index];
			if (text.charCodeAt(index) < 32) invalidSidecar("Trusted sidecar strings contain an invalid control character.");
			if (character === "\"") {
				index += 1;
				try {
					const value = JSON.parse(text.slice(start, index));
					if (typeof value !== "string") invalidSidecar("Trusted sidecar JSON keys must be strings.");
					return value;
				} catch (error) {
					invalidSidecar("Trusted sidecar contains an invalid JSON string.", error);
				}
			}
			if (character === "\\") {
				index += 1;
				if (index >= text.length) invalidSidecar("Trusted sidecar contains an incomplete JSON escape.");
				const escape = text[index];
				if (escape === "u") {
					const hexadecimal = text.slice(index + 1, index + 5);
					if (!HEX_PATTERN.test(hexadecimal)) invalidSidecar("Trusted sidecar contains an invalid Unicode escape.");
					index += 5;
					continue;
				}
				if (!"\"\\/bfnrt".includes(escape)) invalidSidecar("Trusted sidecar contains an invalid JSON escape.");
			}
			index += 1;
		}
		invalidSidecar("Trusted sidecar contains an unterminated JSON string.");
	};
	const parseScalar = () => {
		skipWhitespace();
		if (text[index] === "\"") return parseString();
		if (text[index] === "{" || text[index] === "[") invalidSidecar("Trusted sidecar fields must be scalar declarations.");
		const start = index;
		while (index < text.length && text[index] !== "," && text[index] !== "}") index += 1;
		const token = text.slice(start, index).trim();
		if (token.length === 0) invalidSidecar("Trusted sidecar contains a missing JSON value.");
		try {
			return JSON.parse(token);
		} catch (error) {
			invalidSidecar("Trusted sidecar contains an invalid JSON value.", error);
		}
	};
	skipWhitespace();
	if (text[index] !== "{") invalidSidecar("Trusted sidecars must contain one strict JSON object.");
	index += 1;
	skipWhitespace();
	if (text[index] === "}") index += 1;
	else while (index < text.length) {
		skipWhitespace();
		const key = parseString();
		if (containsUnpairedSurrogate(key)) invalidSidecar("Trusted sidecar contains an invalid JSON key.");
		if (seen.has(key)) invalidSidecar("Trusted sidecar contains a duplicate JSON key.");
		seen.add(key);
		skipWhitespace();
		if (text[index] !== ":") invalidSidecar("Trusted sidecar JSON keys must be followed by a colon.");
		index += 1;
		document[key] = parseScalar();
		skipWhitespace();
		if (text[index] === ",") {
			index += 1;
			continue;
		}
		if (text[index] === "}") {
			index += 1;
			break;
		}
		invalidSidecar("Trusted sidecar contains malformed JSON object syntax.");
	}
	skipWhitespace();
	if (index !== text.length) invalidSidecar("Trusted sidecar must not contain trailing JSON content.");
	return document;
}
function declaration(value, field) {
	try {
		const text = validateFlowBlindDisplayText(value, `Trusted sidecar field ${field}`);
		if (containsUnpairedSurrogate(text)) invalidSidecar(`Trusted sidecar field ${field} contains an invalid Unicode surrogate.`);
		return text;
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		invalidSidecar(`Trusted sidecar field ${field} must be trimmed NFC text without display controls and no longer than 4,096 Unicode code points.`, error);
	}
}
function validateCatalogTrustedSidecar(sidecar, candidate) {
	const document = parseStrictFlatJsonObject(strictUtf8$3(sidecar.bytes));
	if (document.schemaVersion === 1) throw new CatalogResearchError("legacy-sidecar-not-trusted", "input-validation", "Automatic preparation requires a candidate-bound trusted sidecar v2.");
	const expectedKeys = [...SHARED_KEYS, ...BINDING_KEYS];
	const actualKeys = Object.keys(document);
	if (document.schemaVersion !== 2 || expectedKeys.some((key) => !Object.hasOwn(document, key)) || actualKeys.some((key) => !expectedKeys.includes(key)) || actualKeys.length !== expectedKeys.length) invalidSidecar("Trusted sidecar fields do not match the reviewed candidate-bound v2 schema.");
	const candidateReference = declaration(document.candidateReference, "candidateReference");
	if (!Number.isSafeInteger(document.candidateByteLength) || document.candidateByteLength <= 0 || typeof document.candidateSha256 !== "string" || !SHA256_PATTERN.test(document.candidateSha256)) throw new CatalogResearchError("candidate-sidecar-mismatch", "input-validation", "Trusted sidecar candidate binding is invalid.");
	if (candidateReference !== basename(candidate.reference) || document.candidateByteLength !== candidate.byteLength || document.candidateSha256 !== candidate.sha256) throw new CatalogResearchError("candidate-sidecar-mismatch", "input-validation", "Trusted sidecar is bound to a different candidate attachment.");
	if (document.referenceRole !== "reference" || document.candidateRole !== "candidate" || document.coordinateDimensionality !== 2 || document.singleFrame !== true) invalidSidecar("Trusted sidecar structural declarations do not describe one paired planar frame.");
	return {
		identity: {
			reference: basename(sidecar.reference),
			byteLength: sidecar.byteLength,
			sha256: sidecar.sha256
		},
		schemaId: FLOWBLIND_CATALOG_TRUSTED_SIDECAR_SCHEMA_ID,
		candidateBinding: {
			reference: candidateReference,
			byteLength: document.candidateByteLength,
			sha256: document.candidateSha256
		},
		declarations: {
			quantity: declaration(document.quantity, "quantity"),
			sourceMeaning: declaration(document.sourceMeaning, "sourceMeaning"),
			referenceRole: "reference",
			referenceMeaning: declaration(document.referenceMeaning, "referenceMeaning"),
			candidateRole: "candidate",
			candidateMeaning: declaration(document.candidateMeaning, "candidateMeaning"),
			coordinateUnit: declaration(document.coordinateUnit, "coordinateUnit"),
			valueUnit: declaration(document.valueUnit, "valueUnit"),
			provenance: declaration(document.provenance, "provenance"),
			license: declaration(document.license, "license"),
			coordinateDimensionality: 2,
			singleFrame: true
		},
		containsResults: false,
		bytes: sidecar.bytes
	};
}
function createCatalogTrustedSidecar(candidate, metadata) {
	const reference = "trusted-sidecar.json";
	const bytes = utf8Bytes(stableJson$1({
		schemaVersion: 2,
		candidateReference: basename(candidate.reference),
		candidateByteLength: candidate.byteLength,
		candidateSha256: candidate.sha256,
		quantity: metadata.quantity,
		sourceMeaning: "One researcher-selected paired planar field with aligned reference and candidate values.",
		referenceRole: "reference",
		referenceMeaning: metadata.referenceMeaning,
		candidateRole: "candidate",
		candidateMeaning: metadata.candidateMeaning,
		coordinateUnit: metadata.coordinateUnit,
		valueUnit: metadata.valueUnit,
		provenance: metadata.provenance,
		license: metadata.license,
		coordinateDimensionality: 2,
		singleFrame: true
	}));
	const identity = artifactIdentity(reference, bytes);
	return validateCatalogTrustedSidecar({
		reference,
		byteLength: identity.byteLength,
		sha256: identity.sha256,
		bytes
	}, candidate);
}
//#endregion
//#region tools/catalogResearch/catalogPreparation.ts
var ROWS = 3;
var COLUMNS = 3;
var MINIMUM_PAIRED_POINTS = 30;
var HOTSPOT_PERCENTILE = .9;
var PRIMARY_ENDPOINTS = ["pearsonCorrelation", "rangeNormalizedRmse"];
var SECONDARY_ENDPOINTS = [
	"meanAbsoluteError",
	"hotspotRecall",
	"hotspotJaccard"
];
var INTERPRETATION_BOUNDARY = [
	"This is a deterministic descriptive regional selection-sensitivity study for one paired planar field and quantity.",
	"The declared reference is not ground truth and the declared candidate is not a scientific or operational verdict.",
	"The rectangular index grid and row-column window identifiers do not encode physical equal area or scientific importance.",
	"Window differences are not uncertainty intervals, probabilities, solver verification, operational validation, acceptance verdicts, or a globally best-region ranking."
];
function supportCounts(width, height) {
	const counts = Array(9).fill(0);
	for (let y = 0; y < height; y += 1) {
		const row = Math.min(2, Math.floor(ROWS * y / height));
		for (let x = 0; x < width; x += 1) {
			const column = Math.min(2, Math.floor(COLUMNS * x / width));
			counts[row * COLUMNS + column] += 1;
		}
	}
	return counts;
}
function validateCandidate(candidate) {
	try {
		return validatePairedPlanarCsvBytes({
			source: {
				reference: basename(candidate.reference),
				byteLength: candidate.byteLength,
				sha256: candidate.sha256
			},
			bytes: candidate.bytes
		});
	} catch (error) {
		throw new CatalogResearchError("source-structure-invalid", "input-validation", "The candidate does not satisfy the reviewed paired planar CSV contract.", { cause: error });
	}
}
function canonicalSource$1(validated, declarations) {
	const width = validated.structure.gridShape.xCount;
	const height = validated.structure.gridShape.yCount;
	const rows = validated.structure.finitePairedRowCount;
	const pointWindowEvaluations = rows * ROWS * COLUMNS;
	if (rows !== width * height || rows > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumDataRows || rows > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumGridPoints || rows * PAIRED_PLANAR_CSV_HEADER.length > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumDataFields || 9 > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumWindows || pointWindowEvaluations > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumPointWindowEvaluations || !validated.structure.uniformSpacing.x || !validated.structure.uniformSpacing.y) throw new CatalogResearchError("source-structure-invalid", "input-validation", "The candidate exceeds the reviewed topology or resource contract.");
	const windowSupport = supportCounts(width, height);
	if (width < COLUMNS || height < ROWS || windowSupport.some((count) => count < MINIMUM_PAIRED_POINTS)) throw new CatalogResearchError("source-structure-invalid", "input-validation", "The candidate does not provide the reviewed minimum support in every 3 x 3 region.");
	return {
		contractId: "paired-planar-csv-v1",
		parser: {
			version: PAIRED_PLANAR_CSV_VALIDATOR_VERSION,
			encoding: "utf-8",
			header: PAIRED_PLANAR_CSV_HEADER
		},
		structure: {
			rows,
			width,
			height,
			coordinateDimensions: 2,
			singleFrame: true,
			pairedValues: true,
			duplicateCoordinates: false,
			completeCartesianGrid: true,
			uniformSpacing: {
				x: true,
				y: true
			}
		},
		geometry: {
			topology: "complete-uniform-cartesian-index-grid",
			coordinateDimensions: 2,
			coordinateUnit: declarations.coordinateUnit,
			areaSemantics: "index-grid-non-equal-area"
		},
		temporalSampling: {
			frameCount: 1,
			sampling: "single-frame",
			exposure: "unspecified"
		},
		windowSupport
	};
}
function protocolManifest(source, sidecar, canonical) {
	const sourceIdentity = associationIdentity({
		source,
		sidecar,
		structure: canonical.structure
	});
	const registeredPairId = `attached-pair-${sourceIdentity.slice(0, 32)}`;
	const studyId = `${registeredPairId}--regional-agreement-3x3-v1`;
	const pointCount = canonical.structure.rows;
	const windowCount = 9;
	return validateRegionalAgreementStudyDraft({
		schemaVersion: 1,
		id: studyId,
		actionId: studyId,
		studyFamily: "regional-agreement-selection-sensitivity-v1",
		methodVersion: "1.0.0",
		title: "3 x 3 regional agreement study",
		classification: "descriptive-spatial-selection-sensitivity",
		source: {
			adapterId: `attached-paired-planar-v1-${sourceIdentity.slice(0, 16)}`,
			registeredPairId,
			artifact: {
				reference: source.reference,
				byteLength: source.byteLength,
				sha256: source.sha256
			}
		},
		comparison: {
			quantityMethod: "interpolated-supplied-vxy",
			expectedGrid: {
				width: canonical.structure.width,
				height: canonical.structure.height
			},
			expectedNominalPairedPoints: pointCount,
			referenceContextPolicy: "full-nominal-valid-mask",
			hotspotPercentile: HOTSPOT_PERCENTILE
		},
		partition: {
			kind: "equal-grid-index-bins-v1",
			rows: ROWS,
			columns: COLUMNS,
			order: "row-major",
			idFormat: "row-{row}-column-{column}"
		},
		sufficiency: {
			minimumPairedPoints: MINIMUM_PAIRED_POINTS,
			belowMinimumStatus: "insufficient-evidence",
			belowMinimumReason: "paired-points-below-preregistered-minimum"
		},
		resourceBounds: {
			maximumGridPoints: pointCount,
			maximumWindows: windowCount,
			maximumPointWindowEvaluations: pointCount * windowCount
		},
		endpoints: {
			primary: PRIMARY_ENDPOINTS,
			secondary: SECONDARY_ENDPOINTS
		},
		interpretationBoundary: INTERPRETATION_BOUNDARY
	});
}
async function prepareCatalogStudy(humanContext, intent, candidate, trustedSidecar, software) {
	if (intent.capability.capabilityId !== "regional-agreement-v1") throw new CatalogResearchError("source-structure-invalid", "input-validation", "The selected capability does not use the regional agreement preparation contract.");
	if (basename(candidate.reference) !== trustedSidecar.candidateBinding.reference) throw new CatalogResearchError("candidate-sidecar-mismatch", "input-validation", "The trusted sidecar does not bind the selected candidate.");
	const validatedCandidate = validateCandidate(candidate);
	const sourceProjection = canonicalSource$1(validatedCandidate, trustedSidecar.declarations);
	const candidateIdentity = artifactIdentity(basename(candidate.reference), candidate.bytes);
	const sidecarIdentity = trustedSidecar.identity;
	const manifest = protocolManifest(candidateIdentity, sidecarIdentity, sourceProjection);
	const frozen = await freezeRegionalAgreementStudyManifest(validateRegionalAgreementStudyDraft(manifest));
	const protocolBytes = utf8Bytes(frozen.canonicalManifest);
	const protocol = {
		canonicalization: "stable-json-v1",
		manifest,
		byteLength: protocolBytes.byteLength,
		sha256: artifactIdentity("protocol.json", protocolBytes).sha256,
		freezeReceipt: frozen.receipt
	};
	const associationBindings = {
		humanContext,
		source: {
			candidate: candidateIdentity,
			trustedSidecar: {
				...sidecarIdentity,
				schemaId: trustedSidecar.schemaId
			},
			candidateBinding: {
				reference: trustedSidecar.candidateBinding.reference,
				byteLength: trustedSidecar.candidateBinding.byteLength,
				sha256: trustedSidecar.candidateBinding.sha256
			}
		},
		declarations: trustedSidecar.declarations,
		canonicalSource: sourceProjection,
		capability: intent.capability,
		protocol,
		resourceLimits: FLOWBLIND_CATALOG_RESOURCE_LIMITS,
		dataHandling: {
			inputs: "exact-host-mounted-candidate-plus-scientist-metadata",
			processing: "local-confined-read-only-no-network-no-arbitrary-code",
			retention: "no-source-copy-no-saved-dataset-no-process-local-association",
			output: "portable-result-free-content-addressed-preparation-bundle"
		},
		software
	};
	const associationSha256 = associationIdentity(associationBindings);
	const bundle = {
		$schema: FLOWBLIND_CATALOG_PREPARATION_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-preparation-v1",
		id: `flowblind-preparation-${associationSha256.slice(0, 32)}`,
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		association: {
			canonicalization: "stable-json-v1",
			sha256: associationSha256
		},
		...associationBindings
	};
	const bundleBytes = utf8Bytes(stableJson$1(bundle));
	return {
		bundle,
		bundleBytes,
		bundleIdentity: artifactIdentity(`flowblind-preparation-${artifactIdentity("bundle", bundleBytes).sha256}.json`, bundleBytes, "application/json"),
		sidecarBytes: trustedSidecar.bytes,
		sidecarIdentity: {
			...sidecarIdentity,
			schemaId: trustedSidecar.schemaId
		},
		validatedCandidate
	};
}
function preparationResponse(prepared, published) {
	return {
		schemaVersion: 1,
		teammateVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		humanContext: prepared.bundle.humanContext,
		sourceIdentity: prepared.bundle.source.candidate,
		sidecarIdentity: {
			...published.sidecar,
			mediaType: "application/json",
			schemaId: prepared.bundle.source.trustedSidecar.schemaId
		},
		declarationPreview: {
			reviewStatus: "requires-scientist-review-before-run",
			unverifiedScientistAssertions: {
				quantity: prepared.bundle.declarations.quantity,
				referenceMeaning: prepared.bundle.declarations.referenceMeaning,
				candidateMeaning: prepared.bundle.declarations.candidateMeaning,
				coordinateUnit: prepared.bundle.declarations.coordinateUnit,
				valueUnit: prepared.bundle.declarations.valueUnit,
				provenance: prepared.bundle.declarations.provenance,
				license: prepared.bundle.declarations.license
			},
			validatedV1Projection: {
				sourceMeaning: prepared.bundle.declarations.sourceMeaning,
				referenceRole: "reference",
				candidateRole: "candidate",
				coordinateDimensions: 2,
				singleFrame: true,
				pairedValues: true,
				rows: prepared.bundle.canonicalSource.structure.rows,
				width: prepared.bundle.canonicalSource.structure.width,
				height: prepared.bundle.canonicalSource.structure.height,
				header: [
					"x",
					"y",
					"reference_value",
					"candidate_value"
				],
				temporalSampling: prepared.bundle.canonicalSource.temporalSampling
			}
		},
		structure: {
			rows: prepared.bundle.canonicalSource.structure.rows,
			width: prepared.bundle.canonicalSource.structure.width,
			height: prepared.bundle.canonicalSource.structure.height
		},
		windowSupport: prepared.bundle.canonicalSource.windowSupport,
		matchedCapability: prepared.bundle.capability,
		preparationAsset: {
			reference: published.directory,
			bundleSha256: published.bundle.sha256,
			fileCount: 2
		},
		preparationBundle: {
			...published.bundle,
			mediaType: "application/json"
		}
	};
}
//#endregion
//#region tools/catalogResearch/catalogBundle.ts
function referenceParts(reference) {
	const parts = reference.split("/");
	return {
		parent: parts.slice(0, -1).join("/"),
		name: parts.at(-1) ?? ""
	};
}
function validatePreparationEnvelopeShape(bundle, sidecar) {
	const bundleReference = referenceParts(bundle.reference);
	const sidecarReference = referenceParts(sidecar.reference);
	if (bundleReference.name !== "preparation.json" || sidecarReference.name !== "trusted-sidecar.json" || bundleReference.parent !== sidecarReference.parent) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The selected preparation asset does not match the reviewed content-addressed directory envelope.");
	return bundleReference.parent;
}
function validatePreparationEnvelopeIdentity(parent, bundle) {
	if ((parent.split("/").at(-1) ?? "") !== `flowblind-preparation-${bundle.sha256}`) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The selected preparation asset directory is not bound to its preparation bundle identity.");
}
var UTF8_BOM = Buffer.from([
	239,
	187,
	191
]);
var MAXIMUM_JSON_DEPTH = 64;
var MAXIMUM_JSON_SEPARATORS = 1e5;
function boundedJsonStructure(text) {
	let depth = 0;
	let separators = 0;
	let inString = false;
	let escaped = false;
	for (const character of text) {
		if (inString) {
			if (escaped) escaped = false;
			else if (character === "\\") escaped = true;
			else if (character === "\"") inString = false;
			continue;
		}
		if (character === "\"") inString = true;
		else if (character === "{" || character === "[") {
			depth += 1;
			if (depth > MAXIMUM_JSON_DEPTH) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "Preparation bundle nesting exceeds the reviewed limit.");
		} else if (character === "}" || character === "]") depth -= 1;
		else if (character === "," || character === ":") {
			separators += 1;
			if (separators > MAXIMUM_JSON_SEPARATORS) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "Preparation bundle structure exceeds the reviewed limit.");
		}
	}
}
function strictUtf8$2(bytes, label) {
	if (bytes.byteLength >= UTF8_BOM.byteLength && Buffer.from(bytes.subarray(0, UTF8_BOM.byteLength)).equals(UTF8_BOM)) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", `${label} must use UTF-8 without a byte-order mark.`);
	try {
		return new TextDecoder("utf-8", {
			fatal: true,
			ignoreBOM: true
		}).decode(bytes);
	} catch (error) {
		throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", `${label} must contain complete strict UTF-8.`, { cause: error });
	}
}
function canonicalJsonObject(attachment) {
	let value;
	let text;
	try {
		text = strictUtf8$2(attachment.bytes, "Preparation bundle");
		boundedJsonStructure(text);
	} catch {
		return null;
	}
	try {
		value = JSON.parse(text);
	} catch {
		return null;
	}
	if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
	return stableJson$1(value) === text ? value : null;
}
function catalogCandidateAttachment(attachments) {
	const values = attachments.filter((attachment) => attachment.reference.toLowerCase().endsWith(".csv"));
	if (values.length !== 1) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "Execution requires exactly one candidate CSV attachment.");
	return values[0];
}
function catalogJsonAttachments(attachments) {
	const values = attachments.filter((attachment) => attachment.reference.toLowerCase().endsWith(".json"));
	if (values.length !== 2) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "Execution requires exactly one trusted sidecar and one preparation bundle JSON attachment.");
	return values;
}
function catalogBundleAttachment(attachments, recordType = "flowblind-catalog-preparation-v1") {
	const parsed = attachments.flatMap((attachment) => {
		const value = canonicalJsonObject(attachment);
		return value === null ? [] : [{
			attachment,
			value
		}];
	});
	const candidates = parsed.filter(({ value }) => value.recordType === recordType);
	if (candidates.length !== 1) {
		if (candidates.length === 0 && parsed.some(({ value }) => ["flowblind-catalog-preparation-v1", "flowblind-catalog-vector-preparation-v1"].includes(String(value.recordType)))) throw new CatalogResearchError("capability-preparation-mismatch", "input-validation", "The selected preparation asset belongs to a different reviewed method than the current research goal.");
		throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "Execution requires one canonical FlowBlind preparation bundle.");
	}
	return candidates[0];
}
function catalogSidecarAttachment(attachments, bundle) {
	const values = attachments.filter((attachment) => attachment !== bundle);
	if (values.length !== 1) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "Execution requires one trusted sidecar attachment.");
	return values[0];
}
function objectField(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}
function classifyBundleMismatch(value, humanContext, candidate, software) {
	const bundledCandidate = objectField(objectField(value.source)?.candidate);
	const bundledHumanContext = objectField(value.humanContext);
	const bundledLock = objectField(objectField(value.software)?.bundleLock);
	if (bundledCandidate !== null && (bundledCandidate.sha256 !== candidate.sha256 || bundledCandidate.byteLength !== candidate.byteLength)) return new CatalogResearchError("preparation-bundle-source-mismatch", "input-validation", "The preparation bundle is bound to different candidate bytes.");
	if (bundledHumanContext !== null && stableJson$1(bundledHumanContext) !== stableJson$1(humanContext)) return new CatalogResearchError("human-context-mismatch", "input-validation", "The run human context does not match the preparation bundle.");
	if (bundledLock !== null && bundledLock.sha256 !== software.bundleLock.sha256) return new CatalogResearchError("preparation-build-mismatch", "verification", "The preparation belongs to a different attested FlowBlind build and must be prepared again with the deployed tool pair.");
	return new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The preparation bundle is stale, tampered, or belongs to a different package identity.");
}
async function validateRunAttachments(humanContext, intent, attachments, software) {
	if (attachments.length !== 3) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "Execution requires exactly three selected attachments.");
	const candidate = catalogCandidateAttachment(attachments);
	const json = catalogJsonAttachments(attachments);
	const selectedBundle = catalogBundleAttachment(json);
	const sidecar = catalogSidecarAttachment(json, selectedBundle.attachment);
	const preparationParent = validatePreparationEnvelopeShape(selectedBundle.attachment, sidecar);
	const trustedSidecar = validateCatalogTrustedSidecar(sidecar, candidate);
	const regeneratedSidecar = createCatalogTrustedSidecar(candidate, {
		quantity: trustedSidecar.declarations.quantity,
		referenceMeaning: trustedSidecar.declarations.referenceMeaning,
		candidateMeaning: trustedSidecar.declarations.candidateMeaning,
		coordinateUnit: trustedSidecar.declarations.coordinateUnit,
		valueUnit: trustedSidecar.declarations.valueUnit,
		provenance: trustedSidecar.declarations.provenance,
		license: trustedSidecar.declarations.license
	});
	const expected = await prepareCatalogStudy(humanContext, intent, candidate, regeneratedSidecar, software);
	if (!selectedBundle.attachment.bytes.equals(expected.bundleBytes) || !sidecar.bytes.equals(regeneratedSidecar.bytes)) throw classifyBundleMismatch(selectedBundle.value, humanContext, candidate, software);
	validatePreparationEnvelopeIdentity(preparationParent, selectedBundle.attachment);
	let validatedCandidate;
	try {
		validatedCandidate = validatePairedPlanarCsvBytes({
			source: {
				reference: expected.bundle.source.candidate.reference,
				byteLength: candidate.byteLength,
				sha256: candidate.sha256
			},
			bytes: candidate.bytes
		});
	} catch (error) {
		throw new CatalogResearchError("source-identity-mismatch", "verification", "The candidate could not be revalidated for execution.", { cause: error });
	}
	return {
		preparation: expected,
		preparationAttachment: selectedBundle.attachment,
		candidate,
		sidecar,
		validatedCandidate
	};
}
//#endregion
//#region tools/catalogResearch/catalogExecution.ts
function reviewedSpacing(value, label) {
	if (value === null || !Number.isFinite(value) || value <= 0) throw new CatalogResearchError("source-structure-invalid", "input-validation", `${label} is not uniformly spaced for the reviewed operation.`);
	return value;
}
function compatiblePair(bundle, candidate) {
	const structure = bundle.canonicalSource.structure;
	const pointCount = structure.width * structure.height;
	if (candidate.axes.x.length !== structure.width || candidate.axes.y.length !== structure.height || candidate.values.reference.length !== pointCount || candidate.values.candidate.length !== pointCount || candidate.values.reference.some((value) => !Number.isFinite(value)) || candidate.values.candidate.some((value) => !Number.isFinite(value))) throw new CatalogResearchError("source-identity-mismatch", "verification", "The reloaded candidate structure does not match the preparation bundle.");
	const spacingX = reviewedSpacing(candidate.axes.spacing.x, "Candidate x axis");
	const spacingY = reviewedSpacing(candidate.axes.spacing.y, "Candidate y axis");
	const declarations = bundle.declarations;
	const sourceFilename = basename(bundle.source.candidate.reference);
	const sourceSha256 = bundle.source.candidate.sha256;
	const sourceReference = bundle.source.candidate.reference;
	return {
		id: bundle.protocol.manifest.source.registeredPairId,
		piv: {
			field: {
				width: structure.width,
				height: structure.height,
				originX: candidate.axes.x[0],
				originY: candidate.axes.y[0],
				spacingX,
				spacingY,
				coordinateUnit: declarations.coordinateUnit,
				valueUnit: declarations.valueUnit,
				values: candidate.values.reference
			},
			provenance: {
				title: declarations.referenceMeaning,
				citation: declarations.provenance,
				doi: "not-declared",
				recordUrl: "not-declared",
				sourceUrl: sourceReference,
				sourceFile: sourceFilename,
				sourceMd5: "not-collected",
				sourceSha256,
				license: declarations.license,
				licenseUrl: "not-declared",
				pipelineVersion: bundle.canonicalSource.parser.version,
				pipelineSha256: sourceSha256,
				transform: "Canonical paired-planar CSV; no value transformation."
			},
			measurement: {
				caseName: bundle.id,
				plane: "xy",
				zMillimeters: 0,
				quantity: declarations.quantity,
				timeRepresentation: "single-frame",
				vectorComponentsAvailable: false,
				qualityReason: "All rows passed the reviewed paired-planar structural contract.",
				maskingPolicy: "Every reviewed row is paired and eligible.",
				referenceMeaning: declarations.referenceMeaning
			}
		},
		cfd: {
			record: {
				title: declarations.candidateMeaning,
				doi: "not-declared",
				recordUrl: sourceReference,
				license: declarations.license,
				licenseUrl: "not-declared",
				participant: declarations.sourceMeaning,
				institution: "not-declared",
				caseName: bundle.id,
				treatment: "not-declared",
				solutionRepresentation: "steady-state",
				solver: "not-declared",
				coordinateUnit: declarations.coordinateUnit
			},
			source: {
				fileId: 0,
				fileName: sourceFilename,
				sourceUrl: sourceReference,
				byteLength: bundle.source.candidate.byteLength,
				md5: "not-collected",
				sha256: sourceSha256,
				decompressedByteLength: bundle.source.candidate.byteLength,
				decompressedSha256: sourceSha256
			},
			nominalSuppliedVxy: candidate.values.candidate,
			vectorField: { frames: [{
				timestamp: 0,
				values: [],
				validMask: Array(pointCount).fill(true)
			}] }
		},
		maskSummary: { nominalCfdValid: pointCount },
		coordinateAxes: {
			x: candidate.axes.x,
			y: candidate.axes.y
		}
	};
}
function projectStudy(bundle, result) {
	const definitions = {
		pearsonCorrelation: "Ordinary Pearson product-moment correlation over selected paired reference and candidate values.",
		rangeNormalizedRmse: "RMSE over selected paired candidate-minus-reference residuals divided by the reference range on the fixed full domain.",
		meanAbsoluteError: "Arithmetic mean absolute candidate-minus-reference residual over selected paired values.",
		hotspotRecall: "Fraction of selected reference top-decile values also classified as hot by the candidate using the fixed full-domain reference threshold.",
		hotspotJaccard: "Intersection over union of selected reference and candidate hotspots using the fixed full-domain reference threshold."
	};
	const neutralDetail = (value) => value.replaceAll("PIV", "reference").replaceAll("CFD", "candidate").replaceAll("sparse phase", "regional window");
	const projectMetric = (endpoint, metric) => metric.status === "available" ? {
		...metric,
		definition: definitions[endpoint]
	} : {
		...metric,
		detail: neutralDetail(metric.detail)
	};
	const baselineMetrics = Object.fromEntries(Object.entries(result.baseline.metrics).map(([endpoint, metric]) => [endpoint, projectMetric(endpoint, metric)]));
	const windows = result.windows.map((window) => {
		if (window.status !== "available") return {
			...window,
			detail: neutralDetail(window.detail)
		};
		return {
			...window,
			metrics: Object.fromEntries(Object.entries(window.metrics).map(([endpoint, metric]) => [endpoint, projectMetric(endpoint, metric)]))
		};
	});
	return {
		study: result.study,
		source: {
			candidate: bundle.source.candidate,
			trustedSidecar: bundle.source.trustedSidecar,
			quantity: bundle.declarations.quantity,
			reference: {
				role: "reference",
				meaning: bundle.declarations.referenceMeaning
			},
			candidateRole: {
				role: "candidate",
				meaning: bundle.declarations.candidateMeaning
			},
			units: {
				coordinate: bundle.declarations.coordinateUnit,
				value: bundle.declarations.valueUnit
			},
			provenance: bundle.declarations.provenance,
			license: bundle.declarations.license,
			geometry: bundle.canonicalSource.geometry,
			temporalSampling: bundle.canonicalSource.temporalSampling
		},
		protocol: {
			...result.protocol,
			quantityMethod: "paired-planar-reference-candidate-values-v1"
		},
		referenceContext: result.referenceContext,
		baseline: {
			domain: "full reviewed paired comparison domain",
			pairedPoints: result.baseline.pairedPoints,
			metrics: baselineMetrics
		},
		windows,
		endpointSummaries: result.endpointSummaries,
		claimBoundary: result.claimBoundary
	};
}
async function executeCatalogStudy(bundle, preparationBundleIdentity, candidate, options = {}) {
	await options.checkpoint?.("before-freeze-verification");
	throwIfCatalogAborted(options.signal);
	let frozen;
	try {
		frozen = await freezeRegionalAgreementStudyManifest(validateRegionalAgreementStudyDraft(bundle.protocol.manifest));
	} catch (error) {
		throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The preparation bundle contains an invalid frozen protocol.", { cause: error });
	}
	if (frozen.canonicalManifest.length === 0 || Buffer.byteLength(frozen.canonicalManifest, "utf8") !== bundle.protocol.byteLength || stableJson$1(frozen.receipt) !== stableJson$1(bundle.protocol.freezeReceipt)) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The preparation bundle protocol no longer matches its freeze evidence.");
	await options.checkpoint?.("after-freeze-verification");
	throwIfCatalogAborted(options.signal);
	const pair = compatiblePair(bundle, candidate);
	const runStudy = options.runStudy ?? runFrozenRegionalAgreementStudy;
	let primary;
	try {
		await options.checkpoint?.("before-primary-compute");
		throwIfCatalogAborted(options.signal);
		primary = (await runStudy(pair, frozen)).study;
		await options.checkpoint?.("after-primary-compute");
		throwIfCatalogAborted(options.signal);
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		throw new CatalogResearchError("run-failed", "execution", "The reviewed numerical operation did not complete.", { cause: error });
	}
	let replay;
	try {
		await options.checkpoint?.("before-replay-compute");
		throwIfCatalogAborted(options.signal);
		replay = (await runStudy(pair, frozen)).study;
		await options.checkpoint?.("after-replay-compute");
		throwIfCatalogAborted(options.signal);
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		throw new CatalogResearchError("verification-failed", "verification", "The deterministic verification replay did not complete.", { cause: error });
	}
	await options.checkpoint?.("before-result-projection");
	throwIfCatalogAborted(options.signal);
	const projectedPrimary = projectStudy(bundle, primary);
	const projectedReplay = projectStudy(bundle, replay);
	if (stableJson$1(projectedPrimary) !== stableJson$1(projectedReplay)) throw new CatalogResearchError("verification-failed", "verification", "The deterministic verification replay did not match the first result.");
	const record = {
		$schema: FLOWBLIND_CATALOG_VERIFIED_STUDY_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-verified-study-v1",
		status: "verified",
		containsResults: true,
		humanContext: bundle.humanContext,
		capability: bundle.capability,
		preparation: {
			id: bundle.id,
			associationSha256: bundle.association.sha256,
			bundle: preparationBundleIdentity
		},
		source: {
			candidate: bundle.source.candidate,
			trustedSidecar: bundle.source.trustedSidecar
		},
		protocol: {
			sha256: bundle.protocol.sha256,
			freezeReceipt: bundle.protocol.freezeReceipt
		},
		verification: {
			artifactVerificationStatus: "verified",
			deterministicReplayMatched: true,
			sourceIdentityMatched: true,
			softwareIdentityMatched: true
		},
		study: projectedPrimary
	};
	await options.checkpoint?.("after-result-projection");
	throwIfCatalogAborted(options.signal);
	return record;
}
//#endregion
//#region tools/catalogResearch/catalogPublication.ts
function samePath(left, right) {
	const normalizedLeft = resolve(left);
	const normalizedRight = resolve(right);
	return process.platform === "win32" ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase() : normalizedLeft === normalizedRight;
}
function confined(root, reference) {
	const path = resolve(root, reference);
	const relativePath = relative(root, path);
	if (relativePath.length === 0 || relativePath === ".." || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) throw new CatalogResearchError("attachment-path-unsafe", "publication", "A catalog output reference escaped the reviewed output root.");
	return path;
}
async function ordinaryDirectory(path, allowCreate = false, allowAlias = false) {
	if (allowCreate) try {
		await mkdir(path);
	} catch (error) {
		if (typeof error !== "object" || error === null || error.code !== "EEXIST") throw new CatalogResearchError("concurrent-publication-conflict", "publication", "A deterministic output directory could not be created.", { cause: error });
	}
	let metadata;
	let canonical;
	try {
		metadata = await lstat(path);
		canonical = await realpath(path);
	} catch (error) {
		throw new CatalogResearchError("attachment-path-unsafe", "publication", "The catalog output directory is unavailable.", { cause: error });
	}
	if (metadata.isSymbolicLink() || !metadata.isDirectory() || !allowAlias && !samePath(path, canonical)) throw new CatalogResearchError("attachment-path-unsafe", "publication", "Catalog output directories must be ordinary directories without links.");
}
async function ensureOutputRoot(rootInput) {
	const requested = resolve(rootInput);
	await ordinaryDirectory(requested, false, true);
	return realpath(requested);
}
async function cleanupStagingFiles(directory, publishedBasenames) {
	const allowed = new Set(publishedBasenames.map((name) => `.${name}.stage-`));
	for (let attempt = 0; attempt < 100; attempt += 1) {
		const staging = [];
		const handle = await opendir(directory);
		let entryCount = 0;
		for await (const entry of handle) {
			entryCount += 1;
			if (entryCount > 1024) throw new CatalogResearchError("output-publication-partial", "publication", "The deterministic output directory contains too many entries.");
			if (entry.isFile() && [...allowed].some((prefix) => entry.name.startsWith(prefix))) staging.push(entry.name);
		}
		if (staging.length === 0) return;
		await Promise.all(staging.map((name) => unlink(resolve(directory, name)).catch(() => void 0)));
		await setTimeout(10);
	}
	throw new CatalogResearchError("output-publication-partial", "publication", "Uncommitted staging files could not be reconciled after publication.");
}
async function verifyExactDirectoryEntries(directory, expectedNames) {
	const expected = [...expectedNames].sort();
	const actual = [];
	const handle = await opendir(directory);
	for await (const entry of handle) {
		if (!entry.isFile()) throw new CatalogResearchError("concurrent-publication-conflict", "publication", "The deterministic preparation directory contains an unsupported entry.");
		actual.push(entry.name);
	}
	actual.sort();
	if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new CatalogResearchError("concurrent-publication-conflict", "publication", "The deterministic preparation directory contains unexpected or missing files.");
}
async function readHandleBounded(handle, maximumBytes) {
	const chunks = [];
	let totalBytes = 0;
	while (true) {
		const buffer = Buffer.allocUnsafe(65536);
		const { bytesRead } = await handle.read(buffer, 0, buffer.byteLength, null);
		if (bytesRead === 0) break;
		totalBytes += bytesRead;
		if (totalBytes > maximumBytes) throw new CatalogResearchError("output-artifact-tampered", "publication", "A published artifact exceeds its reviewed byte limit.");
		chunks.push(buffer.subarray(0, bytesRead));
	}
	return Buffer.concat(chunks, totalBytes);
}
async function verifiedFile(path, expected, missingCode) {
	let before;
	try {
		before = await lstat(path, { bigint: true });
	} catch (error) {
		throw new CatalogResearchError(missingCode, "publication", missingCode === "output-publication-partial" ? "A committed report is missing one or more required artifacts." : "A published artifact is unavailable.", { cause: error });
	}
	if (before.isSymbolicLink() || !before.isFile()) throw new CatalogResearchError("output-artifact-tampered", "publication", "A published artifact is not an ordinary file.");
	if (before.size !== BigInt(expected.byteLength) || before.size > BigInt(FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumOutputArtifactBytes)) throw new CatalogResearchError("output-artifact-tampered", "publication", "A published artifact has an unexpected or excessive byte length.");
	let handle;
	try {
		handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	} catch (error) {
		throw new CatalogResearchError("output-artifact-tampered", "publication", "A published artifact could not be opened safely.", { cause: error });
	}
	try {
		const opened = await handle.stat({ bigint: true });
		if (!opened.isFile() || opened.size !== before.size || opened.size !== BigInt(expected.byteLength)) throw new CatalogResearchError("output-artifact-tampered", "publication", "A published artifact changed before it could be read.");
		const bytes = await readHandleBounded(handle, expected.byteLength);
		const after = await handle.stat({ bigint: true });
		const final = await lstat(path, { bigint: true });
		const canonical = await realpath(path);
		if (before.dev !== opened.dev || before.ino !== opened.ino || opened.dev !== after.dev || opened.ino !== after.ino || opened.size !== after.size || opened.mtimeNs !== after.mtimeNs || after.dev !== final.dev || after.ino !== final.ino || final.isSymbolicLink() || !samePath(path, canonical) || bytes.byteLength !== expected.byteLength || sha256Bytes(bytes) !== expected.sha256) throw new CatalogResearchError("output-artifact-tampered", "publication", "A published artifact changed or no longer matches its verified identity.");
		return bytes;
	} finally {
		await handle.close();
	}
}
async function readOrdinaryFile(path, maximumBytes) {
	let before;
	try {
		before = await lstat(path, { bigint: true });
	} catch (error) {
		throw new CatalogResearchError("output-publication-partial", "publication", "A required published artifact is unavailable.", { cause: error });
	}
	if (before.isSymbolicLink() || !before.isFile()) throw new CatalogResearchError("output-artifact-tampered", "publication", "A required published artifact is not an ordinary file.");
	if (before.size < 0n || before.size > BigInt(maximumBytes)) throw new CatalogResearchError("output-artifact-tampered", "publication", "A required published artifact exceeds its reviewed byte limit.");
	let handle;
	try {
		handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	} catch (error) {
		throw new CatalogResearchError("output-artifact-tampered", "publication", "A required published artifact could not be opened safely.", { cause: error });
	}
	try {
		const opened = await handle.stat({ bigint: true });
		if (!opened.isFile() || opened.size !== before.size) throw new CatalogResearchError("output-artifact-tampered", "publication", "A required published artifact changed before it could be read.");
		const bytes = await readHandleBounded(handle, maximumBytes);
		const after = await handle.stat({ bigint: true });
		const final = await lstat(path, { bigint: true });
		const canonical = await realpath(path);
		if (before.dev !== opened.dev || before.ino !== opened.ino || opened.dev !== after.dev || opened.ino !== after.ino || opened.size !== after.size || opened.mtimeNs !== after.mtimeNs || after.dev !== final.dev || after.ino !== final.ino || final.isSymbolicLink() || !samePath(path, canonical) || BigInt(bytes.byteLength) !== before.size) throw new CatalogResearchError("output-artifact-tampered", "publication", "A required published artifact changed while being read.");
		return bytes;
	} finally {
		await handle.close();
	}
}
async function fileExists(path) {
	try {
		await lstat(path);
		return true;
	} catch (error) {
		if (typeof error === "object" && error !== null && error.code === "ENOENT") return false;
		throw error;
	}
}
async function syncDirectory(path) {
	if (process.platform === "win32") return;
	const handle = await open(path, constants.O_RDONLY);
	try {
		await handle.sync();
	} finally {
		await handle.close();
	}
}
async function installCompleteFile(path, bytes) {
	const expected = artifactIdentity(path, bytes);
	if (await fileExists(path)) try {
		await verifiedFile(path, expected, "output-artifact-tampered");
		return;
	} catch (error) {
		throw new CatalogResearchError("concurrent-publication-conflict", "publication", "A deterministic output target already contains different or incomplete bytes.", { cause: error });
	}
	const parent = dirname(path);
	await ordinaryDirectory(parent);
	const temporary = resolve(parent, `.${basename(path)}.stage-${randomUUID()}`);
	let handle;
	let temporaryCreated = false;
	try {
		handle = await open(temporary, "wx", 384);
		temporaryCreated = true;
		try {
			await handle.writeFile(bytes);
			await handle.sync();
		} finally {
			await handle.close();
			handle = void 0;
		}
		try {
			await verifiedFile(temporary, {
				...expected,
				reference: basename(temporary)
			}, "output-artifact-tampered");
		} catch (error) {
			if (await fileExists(path)) {
				await verifiedFile(path, expected, "output-artifact-tampered");
				return;
			}
			throw error;
		}
		await ordinaryDirectory(parent);
		try {
			await link(temporary, path);
			await syncDirectory(parent);
		} catch (error) {
			const code = typeof error === "object" && error !== null ? error.code : void 0;
			if ([
				"ENOENT",
				"EPERM",
				"EACCES"
			].includes(code ?? "") && await fileExists(path)) {
				await verifiedFile(path, expected, "output-artifact-tampered");
				return;
			}
			if (code !== "EEXIST") throw new CatalogResearchError("concurrent-publication-conflict", "publication", "A complete deterministic artifact could not be installed atomically.", { cause: error });
			try {
				await verifiedFile(path, expected, "output-artifact-tampered");
			} catch (verificationError) {
				throw new CatalogResearchError("concurrent-publication-conflict", "publication", "A concurrent publication installed different immutable bytes.", { cause: verificationError });
			}
		}
	} finally {
		await handle?.close().catch(() => void 0);
		if (temporaryCreated) await unlink(temporary).catch(() => void 0);
	}
}
function assertOutputBudgets(artifacts) {
	const values = Object.values(artifacts);
	if (values.some((value) => value.byteLength > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumOutputArtifactBytes) || values.reduce((sum, value) => sum + value.byteLength, 0) > FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumPublishedBytes) throw new CatalogResearchError("run-failed", "execution", "The verified output exceeds the reviewed publication budget.");
}
async function publishPreparationAssets(outputRootInput, bundleIdentity, bundleBytes, sidecarIdentity, sidecarBytes, options = {}) {
	const root = await ensureOutputRoot(outputRootInput);
	const directory = `flowblind-preparation-${bundleIdentity.sha256}`;
	const directoryPath = confined(root, directory);
	await ordinaryDirectory(directoryPath, true);
	const publishedSidecar = artifactIdentity(`${directory}/trusted-sidecar.json`, sidecarBytes, "application/json");
	const publishedBundle = artifactIdentity(`${directory}/preparation.json`, bundleBytes, "application/json");
	if (publishedSidecar.byteLength !== sidecarIdentity.byteLength || publishedSidecar.sha256 !== sidecarIdentity.sha256 || publishedBundle.byteLength !== bundleIdentity.byteLength || publishedBundle.sha256 !== bundleIdentity.sha256) throw new CatalogResearchError("preparation-bundle-invalid", "verification", "Generated preparation assets do not match their reviewed identities.");
	await options.checkpoint?.("before-prepare-publication");
	throwIfCatalogAborted(options.signal);
	const sidecarPath = confined(root, publishedSidecar.reference);
	const bundlePath = confined(root, publishedBundle.reference);
	await installCompleteFile(sidecarPath, sidecarBytes);
	await options.checkpoint?.("after-prepare-sidecar-publication");
	throwIfCatalogAborted(options.signal);
	await installCompleteFile(bundlePath, bundleBytes);
	await verifiedFile(sidecarPath, publishedSidecar, "output-artifact-tampered");
	await verifiedFile(bundlePath, publishedBundle, "output-artifact-tampered");
	await cleanupStagingFiles(directoryPath, ["trusted-sidecar.json", "preparation.json"]);
	await verifyExactDirectoryEntries(directoryPath, ["trusted-sidecar.json", "preparation.json"]);
	try {
		await options.checkpoint?.("after-prepare-publication");
	} catch {}
	return {
		directory,
		sidecar: publishedSidecar,
		bundle: publishedBundle
	};
}
function artifactReferences(preparationSha256) {
	const directory = `flowblind-study-${preparationSha256}`;
	return {
		directory,
		preparation: `${directory}/preparation.json`,
		json: `${directory}/verified-study.json`,
		markdown: `${directory}/report.md`,
		html: `${directory}/report.html`,
		verification: `${directory}/report-verification.json`
	};
}
function resourceUri(html, verification, preparation) {
	return `flowblind-report://sha256/${html.sha256}?verification=${verification.sha256}&preparation=${preparation.sha256}`;
}
function parseVerification(bytes) {
	let value;
	try {
		value = JSON.parse(bytes.toString("utf8"));
	} catch (error) {
		throw new CatalogResearchError("output-artifact-tampered", "publication", "The report-verification commit marker is invalid JSON.", { cause: error });
	}
	if (typeof value !== "object" || value === null || Array.isArray(value) || value.recordType !== "flowblind-catalog-report-verification-v1" || stableJson$1(value) !== bytes.toString("utf8")) throw new CatalogResearchError("output-artifact-tampered", "publication", "The report-verification commit marker is invalid.");
	return value;
}
function parseCanonicalJson(bytes, label) {
	let value;
	try {
		value = JSON.parse(bytes.toString("utf8"));
	} catch (error) {
		throw new CatalogResearchError("output-artifact-tampered", "publication", `${label} is invalid JSON.`, { cause: error });
	}
	if (typeof value !== "object" || value === null || Array.isArray(value) || stableJson$1(value) !== bytes.toString("utf8")) throw new CatalogResearchError("output-artifact-tampered", "publication", `${label} is not canonical JSON.`);
	return value;
}
async function verifyPublishedSet(root, verificationIdentity) {
	const directory = verificationIdentity.reference.split("/")[0] ?? "";
	if (!/^flowblind-study-[a-f0-9]{64}$/u.test(directory) || verificationIdentity.reference !== `${directory}/report-verification.json`) throw new CatalogResearchError("output-artifact-tampered", "publication", "The report-verification reference is not content-addressed.");
	const references = artifactReferences(directory.replace("flowblind-study-", ""));
	const record = parseVerification(await verifiedFile(confined(root, verificationIdentity.reference), verificationIdentity, "output-publication-partial"));
	if (record.status !== "verified-report-complete" || record.publication.directory !== references.directory || record.artifacts.preparation.reference !== references.preparation || record.artifacts.json.reference !== references.json || record.artifacts.markdown.reference !== references.markdown || record.artifacts.html.reference !== references.html) throw new CatalogResearchError("output-artifact-tampered", "publication", "The report-verification marker does not bind the deterministic output directory.");
	const preparationBytes = await verifiedFile(confined(root, record.artifacts.preparation.reference), record.artifacts.preparation, "output-publication-partial");
	const resultBytes = await verifiedFile(confined(root, record.artifacts.json.reference), record.artifacts.json, "output-publication-partial");
	const markdown = await verifiedFile(confined(root, record.artifacts.markdown.reference), record.artifacts.markdown, "output-publication-partial");
	const html = await verifiedFile(confined(root, record.artifacts.html.reference), record.artifacts.html, "output-publication-partial");
	const preparation = parseCanonicalJson(preparationBytes, "Published preparation bundle");
	const result = parseCanonicalJson(resultBytes, "Published verified study");
	const preparationSource = preparation.source;
	const preparationProtocol = preparation.protocol;
	const resultPreparation = result.preparation;
	const resultVerification = result.verification;
	const resultCapability = result.capability;
	const vectorCapability = record.capability.capabilityId === "vector-time-readiness-audit-v1";
	const expectedPreparationRecordType = vectorCapability ? "flowblind-catalog-vector-preparation-v1" : "flowblind-catalog-preparation-v1";
	const expectedResultRecordType = vectorCapability ? "flowblind-catalog-vector-verified-study-v1" : "flowblind-catalog-verified-study-v1";
	if (preparation.recordType !== expectedPreparationRecordType || preparation.id !== record.preparation.id || stableJson$1(preparation.capability) !== stableJson$1(record.capability) || preparation.association?.sha256 !== record.preparation.associationSha256 || stableJson$1(preparationSource?.candidate) !== stableJson$1(record.source.candidate) || stableJson$1(preparationSource?.trustedSidecar) !== stableJson$1(record.source.trustedSidecar) || preparationProtocol?.sha256 !== record.protocol.sha256 || stableJson$1(preparation.software) !== stableJson$1(record.software) || result.recordType !== expectedResultRecordType || result.status !== "verified" || result.containsResults !== true || stableJson$1(resultCapability) !== stableJson$1(record.capability) || resultPreparation?.id !== record.preparation.id || (resultPreparation?.bundle)?.sha256 !== record.preparation.bundle.sha256 || stableJson$1(result.source) !== stableJson$1(record.source) || result.protocol?.sha256 !== record.protocol.sha256 || resultVerification?.artifactVerificationStatus !== "verified" || resultVerification.deterministicReplayMatched !== true || resultVerification.sourceIdentityMatched !== true || resultVerification.softwareIdentityMatched !== true || markdown.byteLength === 0 || html.byteLength === 0) throw new CatalogResearchError("output-artifact-tampered", "publication", "The committed report artifacts do not preserve the complete preparation, source, protocol, software, and verification chain.");
	return {
		record,
		html
	};
}
async function publishCatalogStudy(outputRootInput, record, preparationBytes, markdown, html, software, options = {}) {
	const root = await ensureOutputRoot(outputRootInput);
	const references = artifactReferences(record.preparation.bundle.sha256);
	const artifacts = {
		preparation: preparationBytes,
		json: utf8Bytes(stableJson$1(record)),
		markdown: utf8Bytes(markdown),
		html: utf8Bytes(html)
	};
	assertOutputBudgets(artifacts);
	const identities = {
		preparation: artifactIdentity(references.preparation, artifacts.preparation, "application/json"),
		json: artifactIdentity(references.json, artifacts.json, "application/json"),
		markdown: artifactIdentity(references.markdown, artifacts.markdown, "text/markdown"),
		html: artifactIdentity(references.html, artifacts.html, "text/html")
	};
	if (identities.preparation.sha256 !== record.preparation.bundle.sha256 || identities.preparation.byteLength !== record.preparation.bundle.byteLength) throw new CatalogResearchError("preparation-bundle-invalid", "verification", "The published preparation evidence does not match the verified study.");
	const verificationBytes = utf8Bytes(stableJson$1({
		$schema: FLOWBLIND_CATALOG_REPORT_VERIFICATION_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-report-verification-v1",
		status: "verified-report-complete",
		teammateVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
		capability: record.capability,
		preparation: {
			id: record.preparation.id,
			associationSha256: record.preparation.associationSha256,
			bundle: record.preparation.bundle
		},
		source: record.source,
		protocol: { sha256: record.protocol.sha256 },
		software,
		artifacts: identities,
		publication: {
			directory: references.directory,
			commitMarker: "report-verification.json",
			pointOfNoReturn: "exclusive-report-verification-commit-marker",
			policy: "deterministic-exclusive-create-or-verify-content-then-commit-marker",
			distributedExactlyOnceClaim: false
		}
	}));
	const verificationIdentity = artifactIdentity(references.verification, verificationBytes, "application/json");
	if (await fileExists(confined(root, references.verification))) {
		const existing = await verifyPublishedSet(root, verificationIdentity);
		await cleanupStagingFiles(confined(root, references.directory), [
			"preparation.json",
			"verified-study.json",
			"report.md",
			"report.html",
			"report-verification.json"
		]);
		return {
			directory: references.directory,
			artifacts: {
				...identities,
				verification: verificationIdentity
			},
			openVisualReport: {
				label: "Open visual report",
				uri: resourceUri(identities.html, verificationIdentity, record.preparation.bundle),
				mediaType: "text/html",
				byteLength: existing.html.byteLength,
				sha256: identities.html.sha256
			},
			verificationRecord: existing.record
		};
	}
	const finalDirectory = confined(root, references.directory);
	await ordinaryDirectory(finalDirectory, true);
	const final = {
		preparation: confined(finalDirectory, "preparation.json"),
		json: confined(finalDirectory, "verified-study.json"),
		markdown: confined(finalDirectory, "report.md"),
		html: confined(finalDirectory, "report.html"),
		verification: confined(finalDirectory, "report-verification.json")
	};
	await options.checkpoint?.("before-write-preparation");
	throwIfCatalogAborted(options.signal);
	await installCompleteFile(final.preparation, artifacts.preparation);
	await options.checkpoint?.("before-write-result");
	throwIfCatalogAborted(options.signal);
	await installCompleteFile(final.json, artifacts.json);
	await options.checkpoint?.("before-write-markdown");
	throwIfCatalogAborted(options.signal);
	await installCompleteFile(final.markdown, artifacts.markdown);
	await options.checkpoint?.("before-write-html");
	throwIfCatalogAborted(options.signal);
	await installCompleteFile(final.html, artifacts.html);
	await cleanupStagingFiles(finalDirectory, [
		"preparation.json",
		"verified-study.json",
		"report.md",
		"report.html"
	]);
	await options.checkpoint?.("before-commit-marker");
	throwIfCatalogAborted(options.signal);
	await installCompleteFile(final.verification, verificationBytes);
	try {
		await options.checkpoint?.("after-commit-marker");
	} catch {}
	const verified = await verifyPublishedSet(root, verificationIdentity);
	await cleanupStagingFiles(finalDirectory, [
		"preparation.json",
		"verified-study.json",
		"report.md",
		"report.html",
		"report-verification.json"
	]);
	return {
		directory: references.directory,
		artifacts: {
			...identities,
			verification: verificationIdentity
		},
		openVisualReport: {
			label: "Open visual report",
			uri: resourceUri(identities.html, verificationIdentity, record.preparation.bundle),
			mediaType: "text/html",
			byteLength: verified.html.byteLength,
			sha256: identities.html.sha256
		},
		verificationRecord: verified.record
	};
}
function resourceQuery(uri) {
	let parsed;
	try {
		parsed = new URL(uri);
	} catch (error) {
		throw new CatalogResearchError("output-artifact-tampered", "publication", "The visual report resource authority is invalid.", { cause: error });
	}
	const htmlSha256 = parsed.pathname.startsWith("/") ? parsed.pathname.slice(1) : "";
	const verificationSha256 = parsed.searchParams.get("verification") ?? "";
	const preparationSha256 = parsed.searchParams.get("preparation") ?? "";
	if (parsed.protocol !== "flowblind-report:" || parsed.hostname !== "sha256" || parsed.username !== "" || parsed.password !== "" || parsed.port !== "" || parsed.hash !== "" || parsed.pathname !== `/${htmlSha256}` || !/^[a-f0-9]{64}$/u.test(htmlSha256) || !/^[a-f0-9]{64}$/u.test(verificationSha256) || !/^[a-f0-9]{64}$/u.test(preparationSha256) || [...parsed.searchParams.keys()].sort().join(",") !== "preparation,verification" || uri !== `flowblind-report://sha256/${htmlSha256}?verification=${verificationSha256}&preparation=${preparationSha256}`) throw new CatalogResearchError("output-artifact-tampered", "publication", "The visual report resource authority is invalid.");
	return {
		htmlSha256,
		verificationSha256,
		preparationSha256
	};
}
async function readCatalogVisualResource(outputRootInput, uri, expectedSoftware, options = {}) {
	await options.checkpoint?.("before-resource-read");
	throwIfCatalogAborted(options.signal);
	const root = await ensureOutputRoot(outputRootInput);
	const query = resourceQuery(uri);
	const references = artifactReferences(query.preparationSha256);
	const markerBytes = await readOrdinaryFile(confined(root, references.verification), FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumOutputArtifactBytes);
	const markerIdentity = artifactIdentity(references.verification, markerBytes, "application/json");
	if (markerIdentity.sha256 !== query.verificationSha256) throw new CatalogResearchError("output-artifact-tampered", "publication", "The visual report commit marker does not match its content-addressed authority.");
	const verified = await verifyPublishedSet(root, markerIdentity);
	if (verified.record.preparation.bundle.sha256 !== query.preparationSha256 || verified.record.artifacts.preparation.sha256 !== query.preparationSha256 || verified.record.artifacts.html.sha256 !== query.htmlSha256 || stableJson$1(verified.record.software) !== stableJson$1(expectedSoftware)) throw new CatalogResearchError("output-artifact-tampered", "publication", "The visual report no longer matches its preparation or attested software authority.");
	await options.checkpoint?.("after-resource-read");
	throwIfCatalogAborted(options.signal);
	return verified.html;
}
//#endregion
//#region tools/catalogResearch/catalogResearchInput.ts
function normalizedGoal(goal) {
	return validateFlowBlindDisplayText(goal, "Research goal").toLowerCase();
}
function extractCatalogRequestSignals(researchGoal) {
	const goal = researchGoal.toLowerCase();
	return {
		prohibitedRequestElements: {
			externalPath: /(?:^|\s)(?:[a-z]:[\\/]|\\\\|file:\/\/|\.\.[\\/]|\/(?:etc|home|mnt|opt|tmp|users|var)(?:\/|\b))/u.test(goal),
			urlFetch: /\b(?:fetch|download|open|read|retrieve)\b[^.!?\n]{0,80}\bhttps?:\/\//u.test(goal) || /\bhttps?:\/\//u.test(goal),
			arbitraryCode: /\b(?:execute|run|write)\b[^.!?\n]{0,40}\b(?:arbitrary\s+)?(?:code|command|script|shell)\b/u.test(goal),
			unconfinedExecution: /\b(?:terminal|command prompt|powershell|bash)\b/u.test(goal),
			sourceMutationOutsideRegistration: /\b(?:overwrite|replace|edit|modify|transform)\b[^.!?\n]{0,60}\b(?:source|dataset|file)\b/u.test(goal),
			approvalBypass: /\b(?:skip|bypass|combine|fake)\b[^.!?\n]{0,50}\bapproval(?:s)?\b/u.test(goal) || /\bwithout\b[^.!?\n]{0,35}\b(?:approval|confirmation|asking)\b/u.test(goal) || /\bpre[- ]?authori[sz]e\b/u.test(goal) || /\bapprove (?:everything|all steps|all approvals)\b/u.test(goal),
			unreviewedClinicalVerdict: /\b(?:clinical|diagnos(?:is|e|tic)|patient|treatment|medical)\b[^.!?\n]{0,80}\b(?:decision|verdict|recommendation|claim|relevance|outcome)\b/u.test(goal)
		},
		scientificMethodRequests: {
			newMetric: /\b(?:new|custom|invent(?:ed)?|novel)\b[^.!?\n]{0,35}\bmetric(?:s)?\b/u.test(goal),
			modelAuthoredThreshold: /\b(?:invent|choose|create|set|make up)\b[^.!?\n]{0,35}\bthreshold\b/u.test(goal),
			newScientificMethod: /\b(?:invent|design|create)\b[^.!?\n]{0,45}\b(?:scientific )?(?:method|study design|analysis method)\b/u.test(goal),
			scientificVerdict: /\b(?:pass[/-]fail|accepted|rejected|acceptance|scientific verdict|model verdict)\b/u.test(goal)
		},
		explicitSourceCompatibility: {
			dimensionality: /\b(?:3d|three[- ]dimensional)\b/u.test(goal) ? "three-dimensional" : "unknown",
			temporalMeaning: /\b(?:time[- ]varying|time series|multiple frames|over time)\b/u.test(goal) ? "time-varying" : "unknown",
			pairing: /\b(?:unpaired|separate reference and candidate files|one[- ]sided)\b/u.test(goal) ? "unpaired" : "unknown",
			topology: /\b(?:sparse|scattered (?:points|samples)|unstructured grid)\b/u.test(goal) ? "sparse" : "unknown",
			semantics: /\b(?:semantically incompatible|different physical quantities|unrelated quantities)\b/u.test(goal) ? "incompatible" : "unknown"
		}
	};
}
function matchesReviewedCapability(researchGoal) {
	const goal = normalizedGoal(researchGoal);
	const any = (patterns) => patterns.some((pattern) => pattern.test(goal));
	return any([
		/\bagree(?:ment|s|d)?\b/u,
		/\bconcordance\b/u,
		/\bmatch(?:es|ed|ing)?\b/u,
		/\bconsisten(?:cy|t)\b/u,
		/\bpearson(?: correlation)?\b/u,
		/\brange[- ]normalized rmse\b/u,
		/\bmean absolute error\b/u,
		/\bhotspot (?:recall|jaccard)\b/u
	]) && any([
		/\breference(?:s)?\b/u,
		/\bobserv(?:ation|ations|ed|ational)\b/u,
		/\bmeasurement(?:s)?\b/u,
		/\bexperiment(?:al)?\b/u,
		/\bpiv\b/u,
		/\bera5\b/u
	]) && any([
		/\bcandidate(?:s)?\b/u,
		/\bmodel(?:led|ed|s)?\b/u,
		/\bsimulation(?:s)?\b/u,
		/\bforecast(?:s)?\b/u,
		/\bprediction(?:s)?\b/u,
		/\bestimate(?:s|d)?\b/u,
		/\bcfd\b/u,
		/\bhres\b/u
	]) && any([
		/\bregion(?:al|s)?\b/u,
		/\bspatial\b/u,
		/\blocation(?:s)?\b/u,
		/\bwindow(?:s)?\b/u,
		/\bfield[- ]of[- ]view\b/u,
		/\bpart(?:s)? of (?:the )?(?:field|domain)\b/u,
		/\bacross (?:the )?(?:field|domain)\b/u
	]);
}
function matchesVectorTimeReadiness(researchGoal) {
	const goal = normalizedGoal(researchGoal);
	const any = (patterns) => patterns.some((pattern) => pattern.test(goal));
	return any([
		/\bvector(?: field)?\b/u,
		/\bvelocity(?: field)?\b/u,
		/\bflow field\b/u,
		/\btime series\b/u,
		/\btemporal\b/u
	]) && any([
		/\baudit\b/u,
		/\breadiness\b/u,
		/\bquality\b/u,
		/\bcoverage\b/u,
		/\bderivative(?:s)?\b/u,
		/\bdivergence\b/u,
		/\bvorticity\b/u,
		/\bstrain(?: rate)?\b/u,
		/\bwall shear\b/u,
		/\bframe mean\b/u,
		/\bcycle mean\b/u
	]);
}
function inputObject(value, allowedFields) {
	if (typeof value !== "object" || value === null || Array.isArray(value)) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Catalog research input must be one object.");
	const item = value;
	const allowed = new Set(allowedFields);
	if (Object.keys(item).filter((key) => !allowed.has(key)).length > 0) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Catalog research input contains unsupported properties.");
	return item;
}
function validateCatalogHumanContext(value) {
	return humanContext(inputObject(value, [
		"researchGoal",
		"decisionQuestion",
		"nextEvidenceIntent"
	]));
}
function humanContext(item) {
	let researchGoal;
	let decisionQuestion;
	let nextEvidenceIntent;
	try {
		researchGoal = validateFlowBlindDisplayText(item.researchGoal, "Research goal");
		decisionQuestion = Object.hasOwn(item, "decisionQuestion") ? validateFlowBlindDisplayText(item.decisionQuestion, "Decision question") : null;
		nextEvidenceIntent = Object.hasOwn(item, "nextEvidenceIntent") ? validateFlowBlindDisplayText(item.nextEvidenceIntent, "Next evidence intent") : null;
	} catch (error) {
		throw new CatalogResearchError("source-structure-invalid", "input-validation", "Human context must be trimmed NFC text without display controls and no longer than 4,096 Unicode code points.", { cause: error });
	}
	return {
		researchGoal,
		decisionQuestion,
		nextEvidenceIntent
	};
}
function validateCatalogPreparationInput(value, capabilityId = "regional-agreement-v1") {
	const commonFields = [
		"researchGoal",
		"decisionQuestion",
		"nextEvidenceIntent",
		"quantity",
		"coordinateUnit",
		"valueUnit",
		"provenance",
		"license"
	];
	const regionalFields = ["referenceMeaning", "candidateMeaning"];
	const vectorFields = [
		"vectorMeaning",
		"vectorSourceKind",
		"timeUnit",
		"samplingKind",
		"selectedTime",
		"exposureDuration",
		"exposureOperator",
		"timestampAnchor",
		"cycleStartTime",
		"cycleEndTime",
		"cyclePeriod",
		"cyclePhaseOrigin"
	];
	const item = inputObject(value, [
		...commonFields,
		...regionalFields,
		...vectorFields
	]);
	const requiredFields = capabilityId === "regional-agreement-v1" ? regionalFields : vectorFields.slice(0, 4);
	const oppositeFields = capabilityId === "regional-agreement-v1" ? vectorFields : regionalFields;
	const missing = requiredFields.filter((field) => !Object.hasOwn(item, field));
	const opposite = oppositeFields.filter((field) => Object.hasOwn(item, field));
	if (missing.length > 0 || opposite.length > 0) throw new CatalogResearchError("capability-metadata-mismatch", "input-validation", capabilityId === "regional-agreement-v1" ? "The matched regional agreement method requires reference and candidate meaning and does not accept vector/time-only details." : "The matched vector/time readiness method requires vector meaning, source kind, time unit, and sampling kind and does not accept reference/candidate-only details.");
	try {
		const common = {
			quantity: validateFlowBlindDisplayText(item.quantity, "Scientific quantity"),
			coordinateUnit: validateFlowBlindDisplayText(item.coordinateUnit, "Coordinate unit"),
			valueUnit: validateFlowBlindDisplayText(item.valueUnit, "Value unit"),
			provenance: validateFlowBlindDisplayText(item.provenance, "Provenance"),
			license: validateFlowBlindDisplayText(item.license, "Licence")
		};
		if (capabilityId === "regional-agreement-v1") return {
			capabilityId,
			humanContext: humanContext(item),
			metadata: {
				...common,
				referenceMeaning: validateFlowBlindDisplayText(item.referenceMeaning, "Reference meaning"),
				candidateMeaning: validateFlowBlindDisplayText(item.candidateMeaning, "Candidate meaning")
			}
		};
		return {
			capabilityId,
			humanContext: humanContext(item),
			metadata: vectorPreparationMetadata(item, common)
		};
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		throw new CatalogResearchError("source-structure-invalid", "input-validation", "Scientific metadata must be trimmed NFC text without display controls and no longer than 4,096 Unicode code points.", { cause: error });
	}
}
function validateCatalogPreparationHumanContext(value) {
	return humanContext(inputObject(value, [
		"researchGoal",
		"decisionQuestion",
		"nextEvidenceIntent",
		"quantity",
		"coordinateUnit",
		"valueUnit",
		"provenance",
		"license",
		"referenceMeaning",
		"candidateMeaning",
		"vectorMeaning",
		"vectorSourceKind",
		"timeUnit",
		"samplingKind",
		"selectedTime",
		"exposureDuration",
		"exposureOperator",
		"timestampAnchor",
		"cycleStartTime",
		"cycleEndTime",
		"cyclePeriod",
		"cyclePhaseOrigin"
	]));
}
function optionalFiniteNumber(value, label) {
	if (value === void 0) return null;
	if (typeof value !== "number" || !Number.isFinite(value)) throw new CatalogResearchError("source-structure-invalid", "input-validation", `${label} must be a finite number when supplied.`);
	return Object.is(value, -0) ? 0 : value;
}
function requiredEnum(value, allowed, label) {
	if (typeof value !== "string" || !allowed.includes(value)) throw new CatalogResearchError("capability-metadata-mismatch", "input-validation", `${label} must use one reviewed value: ${allowed.join(", ")}.`);
	return value;
}
function optionalEnum(value, allowed, label) {
	return value === void 0 ? null : requiredEnum(value, allowed, label);
}
function vectorPreparationMetadata(item, common) {
	const coordinateUnit = requiredEnum(common.coordinateUnit, [
		"m",
		"cm",
		"mm"
	], "Coordinate unit");
	const valueUnit = requiredEnum(common.valueUnit, [
		"m/s",
		"cm/s",
		"mm/s"
	], "Velocity unit");
	const samplingKind = requiredEnum(item.samplingKind, [
		"instantaneous",
		"steady-state",
		"frame-average"
	], "Sampling kind");
	const exposureDuration = optionalFiniteNumber(item.exposureDuration, "Exposure duration");
	if (samplingKind === "frame-average" && (exposureDuration === null || exposureDuration <= 0)) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Frame-average sampling requires a positive exposure duration.");
	if (samplingKind !== "frame-average" && (exposureDuration !== null || item.exposureOperator !== void 0 || item.timestampAnchor !== void 0)) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Exposure declarations are supported only for frame-average sampling.");
	const hasExposureOperator = item.exposureOperator !== void 0;
	const hasTimestampAnchor = item.timestampAnchor !== void 0;
	if (samplingKind === "frame-average" && hasExposureOperator !== hasTimestampAnchor) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Frame-average exposure operator and timestamp anchor must be supplied together or both omitted.");
	const cycleValues = [
		item.cycleStartTime,
		item.cycleEndTime,
		item.cyclePeriod,
		item.cyclePhaseOrigin
	];
	const hasCycle = cycleValues.some((entry) => entry !== void 0);
	if (hasCycle && cycleValues.some((entry) => entry === void 0)) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Cycle start, end, period, and phase origin must be supplied together.");
	const cycle = hasCycle ? {
		startTime: optionalFiniteNumber(item.cycleStartTime, "Cycle start time"),
		endTime: optionalFiniteNumber(item.cycleEndTime, "Cycle end time"),
		period: optionalFiniteNumber(item.cyclePeriod, "Cycle period"),
		phaseOrigin: optionalFiniteNumber(item.cyclePhaseOrigin, "Cycle phase origin")
	} : null;
	if (cycle !== null && (cycle.endTime <= cycle.startTime || cycle.period <= 0)) throw new CatalogResearchError("source-structure-invalid", "input-validation", "Cycle end must follow its start and cycle period must be positive.");
	return {
		...common,
		vectorMeaning: validateFlowBlindDisplayText(item.vectorMeaning, "Vector field meaning"),
		vectorSourceKind: requiredEnum(item.vectorSourceKind, [
			"generated",
			"measured",
			"simulation"
		], "Vector source kind"),
		coordinateUnit,
		valueUnit,
		timeUnit: requiredEnum(item.timeUnit, ["s", "ms"], "Time unit"),
		samplingKind,
		selectedTime: optionalFiniteNumber(item.selectedTime, "Selected audit time"),
		exposureDuration,
		exposureOperator: optionalEnum(item.exposureOperator, ["uniform-window-average", "unspecified"], "Exposure operator"),
		timestampAnchor: optionalEnum(item.timestampAnchor, [
			"start",
			"midpoint",
			"end",
			"unspecified"
		], "Timestamp anchor"),
		cycle
	};
}
function unsafeReasonCodes(signals) {
	const reasons = [];
	if (signals.prohibitedRequestElements.externalPath) reasons.push("external-path-requested");
	if (signals.prohibitedRequestElements.urlFetch) reasons.push("url-fetch-requested");
	if (signals.prohibitedRequestElements.arbitraryCode) reasons.push("arbitrary-code-requested");
	if (signals.prohibitedRequestElements.unconfinedExecution) reasons.push("unconfined-execution-requested");
	if (signals.prohibitedRequestElements.sourceMutationOutsideRegistration) reasons.push("source-mutation-outside-registration-requested");
	if (signals.prohibitedRequestElements.approvalBypass) reasons.push("approval-bypass-requested");
	if (signals.prohibitedRequestElements.unreviewedClinicalVerdict) reasons.push("unreviewed-clinical-verdict-requested");
	return reasons;
}
function scientificReasonCodes(goal, signals) {
	const reasons = [];
	if (signals.explicitSourceCompatibility.dimensionality === "three-dimensional") reasons.push("three-dimensional-source-declared");
	if (signals.explicitSourceCompatibility.temporalMeaning === "time-varying") reasons.push("time-varying-source-declared");
	if (signals.explicitSourceCompatibility.pairing === "unpaired") reasons.push("unpaired-source-declared");
	if (signals.explicitSourceCompatibility.topology === "sparse") reasons.push("sparse-source-declared");
	if (signals.explicitSourceCompatibility.semantics === "incompatible") reasons.push("incompatible-source-semantics-declared");
	if (signals.scientificMethodRequests.newMetric) reasons.push("new-metric-requested");
	if (signals.scientificMethodRequests.modelAuthoredThreshold) reasons.push("model-authored-threshold-requested");
	if (signals.scientificMethodRequests.newScientificMethod) reasons.push("new-scientific-method-requested");
	if (signals.scientificMethodRequests.scientificVerdict) reasons.push("scientific-verdict-requested");
	const withoutReviewedMae = goal.toLowerCase().replaceAll("mean absolute error", "");
	if (/\b(?:averag(?:e|ed|es|ing)|means?|medians?|trends?|integrat(?:e|ed|es|ing|ion|ions|ive)|aggregat(?:e|ed|es|ing|ion|ions)|variance|standard deviation|std\.? dev\.?|rms|root[- ]mean[- ]square|percentile|quantile|autocorrelation|spectrum|spectral|fft|power spectral density|psd)\b/u.test(withoutReviewedMae)) reasons.push("unreviewed-summary-operation-requested");
	if (/\bpressure[- ]only\b/u.test(goal.toLowerCase())) reasons.push("pressure-only-source-declared");
	if (/\bone[- ]sided (?:error|difference|map)\b/u.test(goal.toLowerCase())) reasons.push("unpaired-source-declared");
	return [...new Set(reasons)];
}
function requestsUnsupportedVectorSummary(value) {
	let remaining = value.toLowerCase();
	for (const supported of [
		/\bframe[- ]average(?:d)?(?: sampling| frames?| data| dataset| measurements?)?\b/gu,
		/\b(?:unweighted )?frame[- ]means?(?: of (?:the )?spatial[- ]mean speeds?)?\b/gu,
		/\b(?:complete[- ]cycle|cycle)(?: time)? means?(?: of (?:the )?spatial[- ]mean speeds?)?\b/gu,
		/\bspatial[- ]mean speeds?\b/gu,
		/\bmean speeds?\b/gu,
		/\baverage speeds?\b/gu
	]) remaining = remaining.replace(supported, "");
	return /\b(?:averag(?:e|ed|es|ing)|means?|medians?|trends?|integrat(?:e|ed|es|ing|ion|ions|ive)|aggregat(?:e|ed|es|ing|ion|ions)|variance|standard deviation|std\.? dev\.?|rms|root[- ]mean[- ]square|percentile|quantile|autocorrelation|spectrum|spectral|fft|power spectral density|psd)\b/u.test(remaining);
}
function requestsUnsupportedVectorTemporalOperation(value) {
	const goal = value.toLowerCase();
	const temporalMetric = String.raw`(?:divergence|vorticity|strain(?: rate)?|wall shear)`;
	const temporalOperator = String.raw`(?:averag(?:e|ed|es|ing)|means?|integrat(?:e|ed|es|ing|ion|ions)|aggregat(?:e|ed|es|ing|ion|ions)|rms|root[- ]mean[- ]square|variance|standard deviation|std\.? dev\.?)`;
	const temporalBinding = String.raw`(?:over time|across frames|temporally|per cycle|through(?:out)? the cycle)`;
	return /\b(?:temporal|time)[ -]?(?:derivative(?:s)?|gradient|differential)\b/u.test(goal) || /\b(?:material|local|convective)[ -]?derivative(?:s)?\b/u.test(goal) || /\b(?:acceleration|time rate of change|temporal rate of change)\b/u.test(goal) || /\bd\s*[a-z0-9_]*\s*\/\s*d\s*t\b/u.test(goal) || /∂[^.!?\n]{0,40}\/\s*∂\s*t/u.test(goal) || /\bderivative(?:s)?\b[^.!?\n]{0,80}\b(?:over time|across frames|temporally)\b/u.test(goal) || new RegExp(String.raw`\b(?:time|temporal(?:ly)?|cycle)[ -]?${temporalOperator}\b(?:\s+of)?[^.!?\n]{0,30}\b${temporalMetric}\b`, "u").test(goal) || new RegExp(String.raw`\b${temporalOperator}\b(?:\s+of)?[^.!?\n]{0,30}\b${temporalMetric}\b[^.!?\n]{0,40}\b${temporalBinding}\b`, "u").test(goal) || new RegExp(String.raw`\b${temporalMetric}\b[^.!?\n]{0,30}\b${temporalOperator}\b[^.!?\n]{0,40}\b${temporalBinding}\b`, "u").test(goal) || new RegExp(String.raw`\b${temporalMetric}\b[^.!?\n]{0,40}\b${temporalBinding}\b`, "u").test(goal);
}
function assessCatalogResearchIntent(humanContext) {
	const contextValues = [
		humanContext.researchGoal,
		humanContext.decisionQuestion,
		humanContext.nextEvidenceIntent
	].filter((value) => value !== null);
	const policyContext = contextValues.join("\n");
	const signals = extractCatalogRequestSignals(policyContext);
	const unsafe = unsafeReasonCodes(signals);
	if (unsafe.length > 0) return {
		status: "unsafe-unsupported",
		reasonCodes: unsafe,
		containsResults: false
	};
	const regionalMatch = matchesReviewedCapability(humanContext.researchGoal);
	const vectorMatch = matchesVectorTimeReadiness(humanContext.researchGoal);
	const scientific = scientificReasonCodes(policyContext, signals);
	if (contextValues.some((value) => requestsUnsupportedVectorTemporalOperation(value))) scientific.push("unreviewed-vector-temporal-operation-requested");
	const universalScientific = scientific.filter((reason) => [
		"three-dimensional-source-declared",
		"sparse-source-declared",
		"incompatible-source-semantics-declared",
		"new-metric-requested",
		"model-authored-threshold-requested",
		"new-scientific-method-requested",
		"scientific-verdict-requested",
		"pressure-only-source-declared",
		"unreviewed-vector-temporal-operation-requested"
	].includes(reason));
	if (universalScientific.length > 0) return {
		status: "needs-scientific-method",
		reasonCodes: vectorMatch ? universalScientific : scientific,
		containsResults: false
	};
	if (regionalMatch && vectorMatch) return {
		status: "ambiguous",
		reasonCodes: ["multiple-reviewed-capabilities-match"],
		containsResults: false
	};
	const capabilitySpecificScientific = vectorMatch ? scientific.filter((reason) => reason !== "time-varying-source-declared" && reason !== "unpaired-source-declared" && reason !== "unreviewed-summary-operation-requested") : scientific;
	if (vectorMatch && requestsUnsupportedVectorSummary(policyContext)) capabilitySpecificScientific.push("unreviewed-summary-operation-requested");
	if (capabilitySpecificScientific.length > 0) return {
		status: "needs-scientific-method",
		reasonCodes: [...new Set(capabilitySpecificScientific)],
		containsResults: false
	};
	if (!regionalMatch && !vectorMatch) return {
		status: "unsupported",
		reasonCodes: ["no-reviewed-capability-match"],
		containsResults: false
	};
	if (regionalMatch) return {
		status: "matched",
		capability: catalogCapabilityIdentity("regional-agreement-v1")
	};
	return {
		status: "matched",
		capability: catalogCapabilityIdentity("vector-time-readiness-audit-v1")
	};
}
//#endregion
//#region tools/catalogResearch/catalogReport.ts
var ENDPOINTS = [
	"pearsonCorrelation",
	"rangeNormalizedRmse",
	"meanAbsoluteError",
	"hotspotRecall",
	"hotspotJaccard"
];
var ENDPOINT_LABELS = {
	pearsonCorrelation: "Pearson correlation",
	rangeNormalizedRmse: "Range-normalized RMSE",
	meanAbsoluteError: "Mean absolute error",
	hotspotRecall: "Hotspot recall",
	hotspotJaccard: "Hotspot Jaccard"
};
function escapeHtml$1(value) {
	return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\"", "&quot;").replaceAll("'", "&#39;");
}
function escapeMarkdown(value) {
	return value.replace(/([\\`*_[\]{}<>|])/gu, "\\$1");
}
function numberText(value) {
	if (!Number.isFinite(value)) throw new Error("Verified reports may render only finite numbers.");
	return Object.is(value, -0) ? "0" : String(value);
}
function baselineMetric(record, endpoint) {
	const metric = record.study.baseline.metrics[endpoint];
	if (metric === void 0) throw new Error(`Verified result is missing baseline ${endpoint}.`);
	return metric;
}
function windowMetric(window, endpoint) {
	if (window.status !== "available") return {
		status: "insufficient-evidence",
		reason: window.reason,
		detail: window.detail
	};
	const metric = window.metrics[endpoint];
	if (metric === void 0) throw new Error(`Verified result is missing ${endpoint} for ${window.window.id}.`);
	return metric;
}
function metricText(metric) {
	return metric.status === "available" ? numberText(metric.value) : `${metric.status}: ${metric.reason}`;
}
function signedDelta(record, window, endpoint) {
	const baseline = baselineMetric(record, endpoint);
	const metric = windowMetric(window, endpoint);
	return baseline.status === "available" && metric.status === "available" ? metric.value - baseline.value : null;
}
function deltaText(value) {
	if (value === null) return "not available";
	return `${value > 0 ? "+" : ""}${numberText(value)}`;
}
function directionText(value) {
	if (value === null) return "unavailable";
	if (value > 0) return "higher";
	if (value < 0) return "lower";
	return "equal";
}
function worstNormalizedError(record) {
	const summary = record.study.endpointSummaries.find((item) => item.endpoint === "rangeNormalizedRmse");
	if (summary === void 0) throw new Error("Verified result is missing normalized-error summary.");
	return summary.maximum === null ? "Not enough evidence" : numberText(summary.maximum.value);
}
function markdownWindowRow(window) {
	if (window.status !== "available") return [
		`| ${escapeMarkdown(window.window.id)}`,
		window.pairedPoints,
		"insufficient-evidence",
		"-",
		"-",
		"-",
		"-",
		"- |"
	].join(" | ");
	return [
		`| ${escapeMarkdown(window.window.id)}`,
		window.pairedPoints,
		metricText(windowMetric(window, "pearsonCorrelation")),
		metricText(windowMetric(window, "rangeNormalizedRmse")),
		metricText(windowMetric(window, "meanAbsoluteError")),
		metricText(windowMetric(window, "hotspotRecall")),
		`${metricText(windowMetric(window, "hotspotJaccard"))} |`
	].join(" | ");
}
function renderCatalogStudyMarkdown(record) {
	const context = record.humanContext;
	const study = record.study;
	const deviations = study.windows.flatMap((window) => ENDPOINTS.map((endpoint) => {
		const metric = windowMetric(window, endpoint);
		return [
			`| ${escapeMarkdown(window.window.id)}`,
			escapeMarkdown(ENDPOINT_LABELS[endpoint]),
			metric.status,
			metric.status === "available" ? numberText(metric.value) : "-",
			deltaText(signedDelta(record, window, endpoint)),
			`${directionText(signedDelta(record, window, endpoint))} |`
		].join(" | ");
	}));
	return [
		`# ${escapeMarkdown(study.study.title)}`,
		"",
		`**Research goal:** ${escapeMarkdown(context.researchGoal)}`,
		"",
		`**Decision question:** ${context.decisionQuestion === null ? "Not supplied" : escapeMarkdown(context.decisionQuestion)}`,
		"",
		`**Next evidence intent:** ${context.nextEvidenceIntent === null ? "Not supplied" : escapeMarkdown(context.nextEvidenceIntent)}`,
		"",
		"## Neutral verified summary",
		"",
		`FlowBlind compared the full-field result across ${study.windows.length} fixed index-grid regions. The values below are descriptive and do not provide a generic robustness verdict.`,
		"",
		`- Baseline Pearson correlation: ${metricText(baselineMetric(record, "pearsonCorrelation"))}`,
		`- Baseline range-normalized RMSE: ${metricText(baselineMetric(record, "rangeNormalizedRmse"))}`,
		`- Worst tested range-normalized RMSE: ${worstNormalizedError(record)}`,
		"",
		"> Geometry warning: this is an index-grid, non-equal-area projection. Row and column positions do not encode physical equal area or scientific importance.",
		"",
		"## Fixed regional windows",
		"",
		"| Window | Paired points | Pearson | Range-normalized RMSE | MAE | Hotspot recall | Hotspot Jaccard |",
		"| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
		...study.windows.map((window) => markdownWindowRow(window)),
		"",
		"## Exact signed deviations from the full baseline",
		"",
		"| Window | Endpoint | Status | Exact value | Signed deviation | Direction |",
		"| --- | --- | --- | ---: | ---: | --- |",
		...deviations,
		"",
		"## Evidence boundary",
		"",
		"- Typed insufficient or unavailable values remain uncertainty; they are not converted to failure, zero, or success.",
		"- No endpoint is combined into a score and no region is designated globally best.",
		...study.claimBoundary.map((item) => `- ${escapeMarkdown(item)}`),
		"",
		"## Identities",
		"",
		`- Preparation bundle SHA-256: \`${record.preparation.bundle.sha256}\``,
		`- Candidate SHA-256: \`${record.source.candidate.sha256}\``,
		`- Trusted sidecar SHA-256: \`${record.source.trustedSidecar.sha256}\``,
		`- Protocol SHA-256: \`${record.protocol.sha256}\``,
		""
	].join("\n");
}
function heatCell(record, window, endpoint) {
	const metric = windowMetric(window, endpoint);
	const delta = signedDelta(record, window, endpoint);
	const label = metric.status === "available" ? `${ENDPOINT_LABELS[endpoint]} ${numberText(metric.value)}, ${directionText(delta)} than baseline by ${deltaText(delta)}` : `${ENDPOINT_LABELS[endpoint]} not enough evidence: ${metric.reason}`;
	return `<div class="heat-cell status-${metric.status}" role="listitem" tabindex="0" aria-label="${escapeHtml$1(`${window.window.id}: ${label}`)}">
  <strong>${escapeHtml$1(window.window.id)}</strong>
  <span class="metric-value">${metric.status === "available" ? numberText(metric.value) : "Not enough evidence"}</span>
  <span>${metric.status === "available" ? `${deltaText(delta)} (${directionText(delta)})` : escapeHtml$1(metric.reason)}</span>
  <span>${window.pairedPoints} paired points</span>
</div>`;
}
function heatmap(record, endpoint) {
	return `<figure class="card heatmap">
  <figcaption>
    <p class="eyebrow">${escapeHtml$1(ENDPOINT_LABELS[endpoint])}</p>
    <h3>Verified regional values</h3>
    <p>Each cell states its exact value, signed deviation, and typed evidence status. Shading does not mean pass/fail.</p>
  </figcaption>
  <div class="heat-grid" role="list" style="--columns:${record.study.protocol.partition.columns}">
    ${record.study.windows.map((window) => heatCell(record, window, endpoint)).join("\n    ")}
  </div>
</figure>`;
}
function exactRows(record) {
	return record.study.windows.flatMap((window) => ENDPOINTS.map((endpoint) => {
		const metric = windowMetric(window, endpoint);
		const delta = signedDelta(record, window, endpoint);
		return `<tr>
  <th scope="row">${escapeHtml$1(window.window.id)}</th>
  <td>${escapeHtml$1(ENDPOINT_LABELS[endpoint])}</td>
  <td>${metric.status}</td>
  <td>${metric.status === "available" ? numberText(metric.value) : "not available"}</td>
  <td>${deltaText(delta)}</td>
  <td>${directionText(delta)}</td>
  <td>${window.pairedPoints}</td>
</tr>`;
	})).join("\n");
}
function renderCatalogStudyHtml(record) {
	const context = record.humanContext;
	const coreMaps = ["pearsonCorrelation", "rangeNormalizedRmse"].map((endpoint) => heatmap(record, endpoint)).join("\n");
	const secondaryMaps = [
		"meanAbsoluteError",
		"hotspotRecall",
		"hotspotJaccard"
	].map((endpoint) => heatmap(record, endpoint)).join("\n");
	const baselineCorrelation = metricText(baselineMetric(record, "pearsonCorrelation"));
	const baselineNormalizedError = metricText(baselineMetric(record, "rangeNormalizedRmse"));
	return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml$1(record.study.study.title)} - verified visual report</title>
<style>
:root {
  color-scheme: light dark;
  --cp-bg: #f7f4ef;
  --cp-surface: #ffffff;
  --cp-surface-soft: #f2f0ec;
  --cp-text: #242424;
  --cp-muted: #5c5c5c;
  --cp-border: #c8c6c2;
  --cp-accent: #b11f4b;
  --cp-accent-soft: #f8e8ee;
}
@media (prefers-color-scheme: dark) {
  :root {
    --cp-bg: #292929;
    --cp-surface: #343231;
    --cp-surface-soft: #3d3b3a;
    --cp-text: #f5f5f5;
    --cp-muted: #c8c6c2;
    --cp-border: #5c5c5c;
    --cp-accent: #f06a94;
    --cp-accent-soft: #4b2935;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--cp-bg);
  color: var(--cp-text);
  font-family: "Segoe UI", Aptos, Calibri, sans-serif;
  line-height: 1.5;
}
.page {
  width: min(1180px, calc(100% - 2rem));
  margin: 0 auto;
  padding: 2rem 0 4rem;
}
.skip-link {
  position: absolute;
  left: 1rem;
  top: 1rem;
  padding: .6rem .8rem;
  background: var(--cp-accent);
  color: white;
  transform: translateY(-180%);
}
.skip-link:focus { transform: translateY(0); }
.hero, .card, details {
  border: 1px solid var(--cp-border);
  border-radius: 16px;
  background: var(--cp-surface);
}
.hero { padding: 1.5rem; }
.eyebrow {
  color: var(--cp-muted);
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .08em;
  text-transform: uppercase;
}
h1 { font-size: clamp(2rem, 5vw, 3.4rem); line-height: 1.05; }
h2 { margin-top: 2rem; }
.neutral {
  max-width: 850px;
  border-left: 4px solid var(--cp-accent);
  padding: .8rem 1rem;
  background: var(--cp-accent-soft);
}
.headline-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
  margin-top: 1.25rem;
}
.headline {
  min-height: 150px;
  padding: 1rem;
  border: 1px solid var(--cp-border);
  border-radius: 16px;
  background: var(--cp-surface-soft);
}
.headline strong {
  display: block;
  margin: .5rem 0;
  font-family: Consolas, monospace;
  font-size: clamp(1.8rem, 4vw, 3rem);
  overflow-wrap: anywhere;
}
.warning {
  margin-top: 1rem;
  padding: 1rem;
  border: 2px solid var(--cp-accent);
  background: var(--cp-accent-soft);
}
.heatmap { padding: 1rem; margin: 1rem 0; }
.heat-grid {
  display: grid;
  grid-template-columns: repeat(var(--columns), minmax(0, 1fr));
  gap: .5rem;
}
.heat-cell {
  display: flex;
  min-height: 120px;
  flex-direction: column;
  gap: .25rem;
  padding: .75rem;
  border: 1px solid var(--cp-border);
  border-radius: 10px;
  background: var(--cp-surface-soft);
}
.heat-cell:focus-visible, summary:focus-visible {
  outline: 3px solid var(--cp-accent);
  outline-offset: 2px;
}
.metric-value { font-family: Consolas, monospace; font-weight: 700; }
.status-insufficient-evidence, .status-unavailable {
  background: repeating-linear-gradient(135deg, var(--cp-surface-soft), var(--cp-surface-soft) 10px, var(--cp-surface) 10px, var(--cp-surface) 20px);
}
details { margin-top: 1rem; padding: 1rem; }
summary { cursor: pointer; font-weight: 700; color: var(--cp-accent); }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td {
  padding: .65rem;
  border: 1px solid var(--cp-border);
  text-align: left;
  vertical-align: top;
}
th { background: var(--cp-surface-soft); }
code { overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .headline-grid, .heat-grid { grid-template-columns: 1fr; }
  .page { width: min(100% - 1rem, 1180px); }
}
@media print {
  body { background: white; color: black; }
  .page { width: 100%; padding: 0; }
  .hero, .card, details { break-inside: avoid; box-shadow: none; }
  details > :not(summary) { display: block; }
  .heat-grid { grid-template-columns: repeat(var(--columns), minmax(0, 1fr)); }
  .skip-link { display: none; }
}
</style>
</head>
<body>
<a class="skip-link" href="#main-content">Skip to report content</a>
<div class="page">
  <header class="hero">
    <p class="eyebrow">Verified descriptive regional study</p>
    <p><strong>Research goal:</strong> ${escapeHtml$1(context.researchGoal)}</p>
    <h1>${escapeHtml$1(record.study.study.title)}</h1>
    <p class="neutral">FlowBlind compared the full-field result across ${record.study.windows.length} fixed regions. This report presents verified values and typed evidence states without a generic robustness or acceptance verdict.</p>
    <div class="headline-grid" aria-label="Three headline verified values">
      <article class="headline">
        <span>Baseline correlation</span>
        <strong data-headline-number="1">${escapeHtml$1(baselineCorrelation)}</strong>
        <span>Higher indicates closer pattern agreement.</span>
      </article>
      <article class="headline">
        <span>Baseline normalized error</span>
        <strong data-headline-number="2">${escapeHtml$1(baselineNormalizedError)}</strong>
        <span>Lower indicates less error relative to the reference range.</span>
      </article>
      <article class="headline">
        <span>Worst tested normalized error</span>
        <strong data-headline-number="3">${escapeHtml$1(worstNormalizedError(record))}</strong>
        <span>The exact region and signed deviation are below.</span>
      </article>
    </div>
    <p class="warning"><strong>Index-grid warning:</strong> this is a non-equal-area projection. Upper, lower, left, and right describe source-array positions, not physical equal area or scientific importance.</p>
  </header>
  <main id="main-content">
    <section aria-labelledby="core-heading">
      <h2 id="core-heading">Core verified regional maps</h2>
      ${coreMaps}
    </section>
    <details>
      <summary>More verified metrics</summary>
      ${secondaryMaps}
    </details>
    <details>
      <summary>Technical appendix: exact values, signed deviations, provenance, and identities</summary>
      <p><strong>Decision question:</strong> ${context.decisionQuestion === null ? "Not supplied" : escapeHtml$1(context.decisionQuestion)}</p>
      <p><strong>Next evidence intent:</strong> ${context.nextEvidenceIntent === null ? "Not supplied" : escapeHtml$1(context.nextEvidenceIntent)}</p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Window</th>
              <th scope="col">Endpoint</th>
              <th scope="col">Typed status</th>
              <th scope="col">Exact value</th>
              <th scope="col">Signed deviation</th>
              <th scope="col">Direction</th>
              <th scope="col">Paired points</th>
            </tr>
          </thead>
          <tbody>${exactRows(record)}</tbody>
        </table>
      </div>
      <h3>Source declarations</h3>
      <p><strong>Quantity:</strong> ${escapeHtml$1(record.study.source.quantity)}</p>
      <p><strong>Reference:</strong> ${escapeHtml$1(record.study.source.reference.meaning)}</p>
      <p><strong>Candidate:</strong> ${escapeHtml$1(record.study.source.candidateRole.meaning)}</p>
      <p><strong>Coordinate unit:</strong> ${escapeHtml$1(record.study.source.units.coordinate)}</p>
      <p><strong>Value unit:</strong> ${escapeHtml$1(record.study.source.units.value)}</p>
      <p><strong>Temporal sampling:</strong> one declared frame; exposure unspecified.</p>
      <p><strong>Provenance:</strong> ${escapeHtml$1(record.study.source.provenance)}</p>
      <p><strong>Licence:</strong> ${escapeHtml$1(record.study.source.license)}</p>
      <h3>Hash-bound evidence</h3>
      <p>Preparation <code>${record.preparation.bundle.sha256}</code></p>
      <p>Candidate <code>${record.source.candidate.sha256}</code></p>
      <p>Sidecar <code>${record.source.trustedSidecar.sha256}</code></p>
      <p>Protocol <code>${record.protocol.sha256}</code></p>
    </details>
    <section aria-labelledby="boundary-heading">
      <h2 id="boundary-heading">Evidence boundary</h2>
      <ul>
        <li>Typed insufficient or unavailable values are uncertainty, not failure or zero.</li>
        <li>No endpoint is combined into a score and no region is designated globally best.</li>
        ${record.study.claimBoundary.map((item) => `<li>${escapeHtml$1(item)}</li>`).join("\n        ")}
      </ul>
    </section>
  </main>
  <footer>
    <p>Deterministic self-contained FlowBlind catalog report. The verified JSON and report-verification identity remain authoritative.</p>
  </footer>
</div>
</body>
</html>
`;
}
//#endregion
//#region tools/catalogResearch/catalogVectorSidecar.ts
var EXPECTED_KEYS = [
	"schemaVersion",
	"recordType",
	"candidateReference",
	"candidateByteLength",
	"candidateSha256",
	"quantity",
	"sourceMeaning",
	"sourceKind",
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
	"coordinateDimensionality",
	"topology",
	"componentX",
	"componentY",
	"provenance",
	"license"
];
var SHA256$2 = /^[a-f0-9]{64}$/u;
function invalid(detail, cause) {
	throw new CatalogResearchError("sidecar-invalid", "input-validation", detail, { cause });
}
function strictUtf8$1(bytes) {
	if (bytes.byteLength >= 3 && bytes[0] === 239 && bytes[1] === 187 && bytes[2] === 191) invalid("Generated vector source sidecar must use UTF-8 without a byte-order mark.");
	try {
		return new TextDecoder("utf-8", {
			fatal: true,
			ignoreBOM: true
		}).decode(bytes);
	} catch (error) {
		invalid("Generated vector source sidecar must contain complete strict UTF-8.", error);
	}
}
function text$2(value, field) {
	try {
		return validateFlowBlindDisplayText(value, `Vector source sidecar field ${field}`);
	} catch (error) {
		invalid(`Vector source sidecar field ${field} is invalid.`, error);
	}
}
function finiteOrNull(value, field) {
	if (value === null) return null;
	if (typeof value !== "number" || !Number.isFinite(value)) invalid(`Vector source sidecar field ${field} must be a finite number or null.`);
	return Object.is(value, -0) ? 0 : value;
}
function enumValue$1(value, allowed, field) {
	if (typeof value !== "string" || !allowed.includes(value)) invalid(`Vector source sidecar field ${field} is unsupported.`);
	return value;
}
function validateCatalogVectorSidecar(sidecar, candidate) {
	const document = parseStrictFlatJsonObject(strictUtf8$1(sidecar.bytes));
	const actualKeys = Object.keys(document);
	if (actualKeys.length !== EXPECTED_KEYS.length || EXPECTED_KEYS.some((key) => !Object.hasOwn(document, key)) || actualKeys.some((key) => !EXPECTED_KEYS.includes(key)) || document.schemaVersion !== 1 || document.recordType !== "flowblind-catalog-vector-source-v1") invalid("Generated vector source sidecar fields do not match the reviewed v1 schema.");
	if (document.candidateReference !== basename(candidate.reference) || document.candidateByteLength !== candidate.byteLength || document.candidateSha256 !== candidate.sha256 || typeof document.candidateSha256 !== "string" || !SHA256$2.test(document.candidateSha256)) throw new CatalogResearchError("candidate-sidecar-mismatch", "input-validation", "Generated vector source sidecar is bound to different candidate bytes.");
	if (document.coordinateDimensionality !== 2 || document.topology !== "complete-rectilinear-grid" || document.componentX !== "u" || document.componentY !== "v") invalid("Generated vector source sidecar structural declarations are unsupported.");
	const selectedTime = finiteOrNull(document.selectedTime, "selectedTime");
	const exposureDuration = finiteOrNull(document.exposureDuration, "exposureDuration");
	const cycleValues = [
		finiteOrNull(document.cycleStartTime, "cycleStartTime"),
		finiteOrNull(document.cycleEndTime, "cycleEndTime"),
		finiteOrNull(document.cyclePeriod, "cyclePeriod"),
		finiteOrNull(document.cyclePhaseOrigin, "cyclePhaseOrigin")
	];
	const cycle = cycleValues.every((value) => value === null) ? null : cycleValues.every((value) => value !== null) ? {
		startTime: cycleValues[0],
		endTime: cycleValues[1],
		period: cycleValues[2],
		phaseOrigin: cycleValues[3]
	} : invalid("Generated vector source sidecar cycle fields must be all null or all finite.");
	const declarations = {
		quantity: text$2(document.quantity, "quantity"),
		sourceMeaning: text$2(document.sourceMeaning, "sourceMeaning"),
		vectorMeaning: text$2(document.sourceMeaning, "sourceMeaning"),
		vectorSourceKind: enumValue$1(document.sourceKind, [
			"generated",
			"measured",
			"simulation"
		], "sourceKind"),
		coordinateUnit: enumValue$1(document.coordinateUnit, [
			"m",
			"cm",
			"mm"
		], "coordinateUnit"),
		valueUnit: enumValue$1(document.valueUnit, [
			"m/s",
			"cm/s",
			"mm/s"
		], "valueUnit"),
		timeUnit: enumValue$1(document.timeUnit, ["s", "ms"], "timeUnit"),
		samplingKind: enumValue$1(document.samplingKind, [
			"instantaneous",
			"steady-state",
			"frame-average"
		], "samplingKind"),
		selectedTime,
		exposureDuration,
		exposureOperator: document.exposureOperator === null ? null : enumValue$1(document.exposureOperator, ["uniform-window-average", "unspecified"], "exposureOperator"),
		timestampAnchor: document.timestampAnchor === null ? null : enumValue$1(document.timestampAnchor, [
			"start",
			"midpoint",
			"end",
			"unspecified"
		], "timestampAnchor"),
		cycle,
		provenance: text$2(document.provenance, "provenance"),
		license: text$2(document.license, "license"),
		coordinateDimensionality: 2,
		topology: "complete-rectilinear-grid",
		componentX: "u",
		componentY: "v"
	};
	if (declarations.samplingKind === "frame-average" && (declarations.exposureDuration === null || declarations.exposureDuration <= 0)) invalid("Frame-average vector source sidecar requires a positive exposure duration.");
	const hasExposureOperator = declarations.exposureOperator !== null;
	const hasTimestampAnchor = declarations.timestampAnchor !== null;
	if (declarations.samplingKind === "frame-average" && hasExposureOperator !== hasTimestampAnchor) invalid("Frame-average vector source sidecar exposure operator and timestamp anchor must be supplied together or both omitted.");
	if (declarations.samplingKind !== "frame-average" && (declarations.exposureDuration !== null || declarations.exposureOperator !== null || declarations.timestampAnchor !== null)) invalid("Only frame-average vector source sidecars may declare exposure metadata.");
	if (declarations.cycle !== null && (declarations.cycle.endTime <= declarations.cycle.startTime || declarations.cycle.period <= 0)) invalid("Generated vector source sidecar cycle declaration is invalid.");
	return {
		bytes: sidecar.bytes,
		identity: {
			reference: "trusted-sidecar.json",
			byteLength: sidecar.byteLength,
			sha256: sidecar.sha256
		},
		schemaId: FLOWBLIND_CATALOG_VECTOR_SIDECAR_SCHEMA_ID,
		candidateBinding: {
			reference: document.candidateReference,
			byteLength: document.candidateByteLength,
			sha256: document.candidateSha256
		},
		declarations
	};
}
function createCatalogVectorSidecar(candidate, metadata) {
	const bytes = utf8Bytes(stableJson$1({
		schemaVersion: 1,
		recordType: "flowblind-catalog-vector-source-v1",
		candidateReference: basename(candidate.reference),
		candidateByteLength: candidate.byteLength,
		candidateSha256: candidate.sha256,
		quantity: metadata.quantity,
		sourceMeaning: metadata.vectorMeaning,
		sourceKind: metadata.vectorSourceKind,
		coordinateUnit: metadata.coordinateUnit,
		valueUnit: metadata.valueUnit,
		timeUnit: metadata.timeUnit,
		samplingKind: metadata.samplingKind,
		selectedTime: metadata.selectedTime,
		exposureDuration: metadata.exposureDuration,
		exposureOperator: metadata.exposureOperator,
		timestampAnchor: metadata.timestampAnchor,
		cycleStartTime: metadata.cycle?.startTime ?? null,
		cycleEndTime: metadata.cycle?.endTime ?? null,
		cyclePeriod: metadata.cycle?.period ?? null,
		cyclePhaseOrigin: metadata.cycle?.phaseOrigin ?? null,
		coordinateDimensionality: 2,
		topology: "complete-rectilinear-grid",
		componentX: "u",
		componentY: "v",
		provenance: metadata.provenance,
		license: metadata.license
	}));
	const identity = artifactIdentity("trusted-sidecar.json", bytes);
	return validateCatalogVectorSidecar({
		reference: identity.reference,
		byteLength: identity.byteLength,
		sha256: identity.sha256,
		bytes
	}, candidate);
}
//#endregion
//#region src/domain/vectorTopology.ts
function topologyPointCount(topology) {
	if (topology.kind === "unstructured") return topology.points.length / topology.dimension;
	if (topology.dimension === 2) return topology.coordinates.x.length * topology.coordinates.y.length;
	return topology.coordinates.x.length * topology.coordinates.y.length * topology.coordinates.z.length;
}
function structuredPointIndex(topology, x, y, z = 0) {
	return x + topology.coordinates.x.length * (y + topology.coordinates.y.length * z);
}
function topologyPointCoordinates(topology, index) {
	if (topology.kind === "unstructured") {
		const offset = index * topology.dimension;
		return topology.points.slice(offset, offset + topology.dimension);
	}
	const xCount = topology.coordinates.x.length;
	const yCount = topology.coordinates.y.length;
	const x = index % xCount;
	const y = Math.floor(index / xCount) % yCount;
	if (topology.dimension === 2) return [topology.coordinates.x[x], topology.coordinates.y[y]];
	const z = Math.floor(index / (xCount * yCount));
	return [
		topology.coordinates.x[x],
		topology.coordinates.y[y],
		topology.coordinates.z[z]
	];
}
//#endregion
//#region src/domain/units.ts
var LENGTH_TO_METERS = {
	m: 1,
	cm: .01,
	mm: .001
};
var VELOCITY_TO_METERS_PER_SECOND = {
	"m/s": 1,
	"cm/s": .01,
	"mm/s": .001
};
var VISCOSITY_TO_PASCAL_SECONDS = {
	"Pa*s": 1,
	"mPa*s": .001
};
function lengthToMeters(value, unit) {
	return value * LENGTH_TO_METERS[unit];
}
function velocityToMetersPerSecond(value, unit) {
	return value * VELOCITY_TO_METERS_PER_SECOND[unit];
}
function viscosityToPascalSeconds(value, unit) {
	return value * VISCOSITY_TO_PASCAL_SECONDS[unit];
}
//#endregion
//#region src/domain/vectorMetrics.ts
function validateCoverageGate$2(minimumCoverage) {
	if (!Number.isFinite(minimumCoverage) || minimumCoverage < 0 || minimumCoverage > 1) throw new Error("A metric coverage gate must lie between zero and one.");
}
function coverageGate(id, observed, criterion, detail) {
	return {
		id,
		passed: observed >= criterion,
		observed,
		criterion,
		detail
	};
}
function numericalRangeGate$1(id, invalidCount, detail) {
	return {
		id,
		passed: invalidCount === 0,
		observed: invalidCount,
		criterion: 0,
		detail
	};
}
function extrema(values) {
	let minimum = Number.POSITIVE_INFINITY;
	let maximum = Number.NEGATIVE_INFINITY;
	for (const value of values) {
		minimum = Math.min(minimum, value);
		maximum = Math.max(maximum, value);
	}
	return {
		minimum,
		maximum
	};
}
function componentValue(frame, pointIndex, componentIndex, componentCount) {
	return frame.values[pointIndex * componentCount + componentIndex];
}
function evaluateSpeed(dataset, frame, minimumCoverage) {
	validateCoverageGate$2(minimumCoverage);
	const pointCount = topologyPointCount(dataset.topology);
	const componentCount = dataset.components.length;
	const speeds = [];
	let numericalRangePoints = 0;
	for (let pointIndex = 0; pointIndex < pointCount; pointIndex += 1) {
		if (!frame.validMask[pointIndex]) continue;
		const components = [];
		for (let componentIndex = 0; componentIndex < componentCount; componentIndex += 1) components.push(componentValue(frame, pointIndex, componentIndex, componentCount));
		const pointSpeed = safeNorm(components);
		if (pointSpeed === null) numericalRangePoints += 1;
		else speeds.push(pointSpeed);
	}
	const coverage = countCoverage(speeds.length, pointCount);
	const coverageDecision = coverageGate("minimum-speed-point-coverage", coverage.fraction, minimumCoverage, "Valid points must contain every declared vector component.");
	const numericalDecision = numericalRangeGate$1("finite-derived-speed", numericalRangePoints, "Every valid component vector must have a finite representable Euclidean norm.");
	const gates = [coverageDecision, numericalDecision];
	if (!numericalDecision.passed) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "At least one valid finite component vector has a speed outside the supported numerical range.",
		coverage,
		gates
	};
	if (speeds.length === 0) return {
		status: "insufficient-evidence",
		reason: "no-valid-points",
		detail: "No point is valid for a speed summary.",
		coverage,
		gates
	};
	if (!coverageDecision.passed) return {
		status: "insufficient-evidence",
		reason: "coverage-below-gate",
		detail: "Valid point coverage is below the declared speed gate.",
		coverage,
		gates
	};
	const mean = safeMean(speeds);
	const rms = safeRms(speeds);
	if (mean === null || rms === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Speed summary aggregation exceeded the supported numerical range.",
		coverage,
		gates
	};
	const speedExtrema = extrema(speeds);
	return {
		status: "available",
		value: {
			quantity: dataset.coordinateFrame.dimension === 2 ? "in-plane-speed" : "speed",
			unit: dataset.components[0].unit,
			minimum: speedExtrema.minimum,
			mean,
			rms,
			maximum: speedExtrema.maximum
		},
		coverage,
		gates
	};
}
function coordinatesForAxis(topology, axis) {
	if (axis === 0) return topology.coordinates.x;
	if (axis === 1) return topology.coordinates.y;
	if (topology.dimension === 3 && axis === 2) return topology.coordinates.z;
	throw new Error("Derivative axis exceeds the structured topology dimension.");
}
function coordinateIndex(point, axis) {
	if (axis === 0) return point[0];
	if (axis === 1) return point[1];
	return point[2];
}
function withAxisOffset(point, axis, offset) {
	const result = [
		point[0],
		point[1],
		point[2]
	];
	result[axis] += offset;
	return result;
}
function firstDerivative(coordinates, index, minusValue, centerValue, plusValue) {
	const hMinus = coordinates[index] - coordinates[index - 1];
	const hPlus = coordinates[index + 1] - coordinates[index];
	const direct = (hMinus * hMinus * plusValue + (hPlus * hPlus - hMinus * hMinus) * centerValue - hPlus * hPlus * minusValue) / (hMinus * hPlus * (hMinus + hPlus));
	const leftSlope = safeDifferenceQuotient(centerValue, minusValue, hMinus);
	const rightSlope = safeDifferenceQuotient(plusValue, centerValue, hPlus);
	if (leftSlope === null || rightSlope === null) return null;
	const fallback = safeWeightedMean([leftSlope, rightSlope], [Math.abs(hPlus), Math.abs(hMinus)]);
	if (fallback === null) return Number.isFinite(direct) ? direct : null;
	if (!Number.isFinite(direct)) return fallback;
	const comparisonScale = Math.max(1, Math.abs(direct), Math.abs(fallback));
	return Math.abs(direct - fallback) <= 64 * Number.EPSILON * comparisonScale ? direct : fallback;
}
function pointIsStencilValid(topology, frame, point) {
	const center = structuredPointIndex(topology, point[0], point[1], point[2]);
	if (!frame.validMask[center]) return false;
	for (let axis = 0; axis < topology.dimension; axis += 1) {
		const minus = withAxisOffset(point, axis, -1);
		const plus = withAxisOffset(point, axis, 1);
		if (!frame.validMask[structuredPointIndex(topology, minus[0], minus[1], minus[2])] || !frame.validMask[structuredPointIndex(topology, plus[0], plus[1], plus[2])]) return false;
	}
	return true;
}
function gradientAt(dataset, topology, frame, point, coordinatesMeters) {
	const componentCount = dataset.components.length;
	const gradient = [];
	for (let componentIndex = 0; componentIndex < componentCount; componentIndex += 1) {
		const row = [];
		for (let axis = 0; axis < topology.dimension; axis += 1) {
			const axisIndex = coordinateIndex(point, axis);
			const minus = withAxisOffset(point, axis, -1);
			const plus = withAxisOffset(point, axis, 1);
			const minusPoint = structuredPointIndex(topology, minus[0], minus[1], minus[2]);
			const centerPoint = structuredPointIndex(topology, point[0], point[1], point[2]);
			const plusPoint = structuredPointIndex(topology, plus[0], plus[1], plus[2]);
			const unit = dataset.components[componentIndex].unit;
			const minusValue = velocityToMetersPerSecond(componentValue(frame, minusPoint, componentIndex, componentCount), unit);
			const centerValue = velocityToMetersPerSecond(componentValue(frame, centerPoint, componentIndex, componentCount), unit);
			const plusValue = velocityToMetersPerSecond(componentValue(frame, plusPoint, componentIndex, componentCount), unit);
			const derivative = firstDerivative(coordinatesMeters[axis], axisIndex, minusValue, centerValue, plusValue);
			if (derivative === null) return null;
			row.push(derivative);
		}
		gradient.push(row);
	}
	return gradient;
}
function curlMagnitude(gradient) {
	if (gradient.length === 2) {
		const outOfPlane = safeDifference(gradient[1][0], gradient[0][1]);
		if (outOfPlane === null) return null;
		return {
			signedOutOfPlane: outOfPlane,
			magnitude: Math.abs(outOfPlane)
		};
	}
	const x = safeDifference(gradient[2][1], gradient[1][2]);
	const y = safeDifference(gradient[0][2], gradient[2][0]);
	const z = safeDifference(gradient[1][0], gradient[0][1]);
	if (x === null || y === null || z === null) return null;
	const magnitude = safeNorm([
		x,
		y,
		z
	]);
	return magnitude === null ? null : {
		signedOutOfPlane: null,
		magnitude
	};
}
function strainRateMagnitude(gradient) {
	let directTensorSquare = 0;
	for (let row = 0; row < gradient.length; row += 1) for (let column = 0; column < gradient.length; column += 1) {
		const symmetric = .5 * (gradient[row][column] + gradient[column][row]);
		directTensorSquare += symmetric * symmetric;
	}
	const direct = Math.sqrt(2 * directTensorSquare);
	if (Number.isFinite(direct)) return direct;
	const symmetricComponents = [];
	for (let row = 0; row < gradient.length; row += 1) for (let column = 0; column < gradient.length; column += 1) {
		const symmetric = safeMean([gradient[row][column], gradient[column][row]]);
		if (symmetric === null) return null;
		symmetricComponents.push(symmetric);
	}
	const tensorMagnitude = safeNorm(symmetricComponents);
	if (tensorMagnitude === null) return null;
	const strainRate = tensorMagnitude * Math.SQRT2;
	return Number.isFinite(strainRate) ? strainRate : null;
}
function evaluateStructuredDerivatives(dataset, frame, minimumCoverage) {
	validateCoverageGate$2(minimumCoverage);
	if (dataset.topology.kind !== "rectilinear") return {
		status: "unavailable",
		reason: "unsupported-topology",
		detail: "Unstructured derivative operators are intentionally deferred until a reviewed method is supplied.",
		gates: []
	};
	const topology = dataset.topology;
	const xCount = topology.coordinates.x.length;
	const yCount = topology.coordinates.y.length;
	const zCount = topology.dimension === 3 ? topology.coordinates.z.length : 1;
	if (xCount < 3 || yCount < 3 || topology.dimension === 3 && zCount < 3) return {
		status: "unavailable",
		reason: "derivative-axis-too-short",
		detail: "Every structured axis requires at least three coordinates for a central stencil.",
		gates: []
	};
	const divergenceValues = [];
	const vorticityMagnitudes = [];
	const signedOutOfPlaneValues = [];
	const strainValues = [];
	const interiorCenters = (xCount - 2) * (yCount - 2) * (topology.dimension === 3 ? zCount - 2 : 1);
	let maskExcludedStencils = 0;
	let numericalRangeStencils = 0;
	const coordinatesMeters = Array.from({ length: topology.dimension }, (_, axis) => coordinatesForAxis(topology, axis).map((coordinate) => lengthToMeters(coordinate, dataset.coordinateFrame.lengthUnit)));
	if (coordinatesMeters.some((coordinates) => coordinates.some((coordinate) => !Number.isFinite(coordinate)) || coordinates.some((coordinate, index) => index > 0 && coordinate === coordinates[index - 1]))) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Coordinate conversion collapses or exceeds the supported numerical range for derivative stencils.",
		coverage: countCoverage(0, interiorCenters),
		gates: [numericalRangeGate$1("finite-derivative-coordinate-range", 1, "Converted derivative coordinates must remain finite and distinct.")]
	};
	const firstZ = topology.dimension === 3 ? 1 : 0;
	const lastZ = topology.dimension === 3 ? zCount - 2 : 0;
	for (let z = firstZ; z <= lastZ; z += 1) for (let y = 1; y < yCount - 1; y += 1) for (let x = 1; x < xCount - 1; x += 1) {
		const point = [
			x,
			y,
			z
		];
		if (!pointIsStencilValid(topology, frame, point)) {
			maskExcludedStencils += 1;
			continue;
		}
		const gradient = gradientAt(dataset, topology, frame, point, coordinatesMeters);
		if (gradient === null) {
			numericalRangeStencils += 1;
			continue;
		}
		const divergence = safeSum(gradient.map((row, index) => row[index]));
		const curl = curlMagnitude(gradient);
		const strain = strainRateMagnitude(gradient);
		if (divergence === null || curl === null || strain === null) {
			numericalRangeStencils += 1;
			continue;
		}
		divergenceValues.push(divergence);
		vorticityMagnitudes.push(curl.magnitude);
		if (curl.signedOutOfPlane !== null) signedOutOfPlaneValues.push(curl.signedOutOfPlane);
		strainValues.push(strain);
	}
	const coverage = countCoverage(divergenceValues.length, interiorCenters);
	const coverageDecision = coverageGate("minimum-derivative-stencil-coverage", coverage.fraction, minimumCoverage, "Only complete central stencils with valid vector points are eligible.");
	const numericalDecision = numericalRangeGate$1("finite-derived-spatial-metrics", numericalRangeStencils, "Every complete stencil must produce finite representable gradients and derived metrics.");
	const gates = [coverageDecision, numericalDecision];
	if (!numericalDecision.passed) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "At least one complete valid stencil exceeds the supported numerical range.",
		coverage,
		gates
	};
	if (divergenceValues.length === 0) return {
		status: "insufficient-evidence",
		reason: "no-valid-stencils",
		detail: "No complete valid local spatial stencil is available.",
		coverage,
		gates
	};
	if (!coverageDecision.passed) return {
		status: "insufficient-evidence",
		reason: "coverage-below-gate",
		detail: "Complete stencil coverage is below the declared derivative gate.",
		coverage,
		gates
	};
	const divergenceAbsolute = divergenceValues.map(Math.abs);
	const divergenceExtrema = extrema(divergenceAbsolute);
	const vorticityExtrema = extrema(vorticityMagnitudes);
	const strainExtrema = extrema(strainValues);
	const divergenceMean = safeMean(divergenceValues);
	const divergenceRms = safeRms(divergenceValues);
	const vorticityMean = safeMean(vorticityMagnitudes);
	const strainMean = safeMean(strainValues);
	const signedVorticityMean = topology.dimension === 2 ? safeMean(signedOutOfPlaneValues) : null;
	const divergenceP95 = linearQuantile(divergenceAbsolute, .95);
	if (divergenceMean === null || divergenceRms === null || vorticityMean === null || strainMean === null || topology.dimension === 2 && signedVorticityMean === null || !Number.isFinite(divergenceP95)) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Spatial metric aggregation exceeds the supported numerical range.",
		coverage,
		gates
	};
	const totalPoints = topologyPointCount(topology);
	return {
		status: "available",
		value: {
			coverageDetail: {
				totalPoints,
				boundaryExcluded: totalPoints - interiorCenters,
				interiorCenters,
				maskExcludedStencils,
				completeStencils: divergenceValues.length
			},
			divergence: {
				unit: "1/s",
				signedMean: divergenceMean,
				rms: divergenceRms,
				p95Absolute: divergenceP95,
				maximumAbsolute: divergenceExtrema.maximum
			},
			vorticity: {
				unit: "1/s",
				representation: topology.dimension === 2 ? "signed-out-of-plane" : "curl-vector-magnitude",
				signedMeanOutOfPlane: topology.dimension === 2 ? signedVorticityMean : null,
				meanMagnitude: vorticityMean,
				maximumMagnitude: vorticityExtrema.maximum
			},
			strainRate: {
				unit: "1/s",
				convention: "sqrt(2 D:D)",
				mean: strainMean,
				maximum: strainExtrema.maximum
			}
		},
		coverage,
		gates
	};
}
//#endregion
//#region src/domain/temporalMetrics.ts
function frameAverageTemporalRefusal(dataset, operation) {
	if (dataset.temporal.sampling.kind !== "frame-average") return null;
	const sampling = resolveFrameAverageSampling(dataset.temporal.sampling);
	if (sampling.exposureOperator === "unspecified" || sampling.timestampAnchor === "unspecified") return {
		status: "unavailable",
		reason: "frame-average-exposure-metadata-insufficient",
		detail: `${operation} requires a concrete exposure operator and timestamp anchor. This frame-average dataset leaves at least one unspecified, so FlowBlind will not treat its timestamps as instantaneous samples.`,
		gates: []
	};
	return {
		status: "unavailable",
		reason: "frame-average-temporal-operation-unsupported",
		detail: `${operation} is not implemented for ${sampling.exposureOperator} frames anchored at the exposure ${sampling.timestampAnchor}. FlowBlind will not substitute point-sample interpolation, temporal integration, or deconvolution.`,
		gates: []
	};
}
function validateCoverageGate$1(value, label) {
	if (!Number.isFinite(value) || value < 0 || value > 1) throw new Error(`${label} must lie between zero and one.`);
}
function validateMaximumGap(value) {
	if (!Number.isFinite(value) || value <= 0) throw new Error("The maximum interpolation gap must be greater than zero.");
}
function validateCyclePolicy(policy) {
	if (!Number.isInteger(policy.minimumIntervals) || policy.minimumIntervals < 1) throw new Error("A cycle gate requires at least one integer interval.");
	if (!Number.isFinite(policy.maximumGapFractionOfPeriod) || policy.maximumGapFractionOfPeriod <= 0 || policy.maximumGapFractionOfPeriod > 1) throw new Error("The maximum cycle gap fraction must lie above zero and at most one.");
	if (!Number.isFinite(policy.maximumCadenceDeviationFraction) || policy.maximumCadenceDeviationFraction < 0) throw new Error("The cadence deviation fraction must be nonnegative.");
	validateCoverageGate$1(policy.endpointToleranceFraction, "Cycle endpoint tolerance");
}
function interpolationGapGate(observed, criterion) {
	return {
		id: "maximum-interpolation-gap",
		passed: observed <= criterion,
		observed,
		criterion,
		detail: "Linear interpolation is allowed only across a declared maximum timestamp gap."
	};
}
function interpolateVectorFrame(dataset, targetTime, maximumGap) {
	if (!Number.isFinite(targetTime)) throw new Error("The requested interpolation time must be finite.");
	validateMaximumGap(maximumGap);
	const frameAverageRefusal = frameAverageTemporalRefusal(dataset, "Point-time frame resolution");
	if (frameAverageRefusal !== null) return frameAverageRefusal;
	const exact = dataset.frames.find((frame) => frame.timestamp === targetTime);
	if (exact !== void 0) {
		const valid = exact.validMask.filter(Boolean).length;
		return {
			status: "available",
			value: {
				frame: exact,
				interpolated: false
			},
			coverage: countCoverage(valid, topologyPointCount(dataset.topology)),
			gates: [interpolationGapGate(0, maximumGap)]
		};
	}
	const firstTime = dataset.frames[0].timestamp;
	const lastTime = dataset.frames[dataset.frames.length - 1].timestamp;
	if (dataset.temporal.kind !== "time-series" || targetTime < firstTime || targetTime > lastTime) return {
		status: "unavailable",
		reason: "time-out-of-range",
		detail: "The requested time is not an available frame and cannot be resolved without extrapolation.",
		gates: []
	};
	let upperIndex = 1;
	while (upperIndex < dataset.frames.length && dataset.frames[upperIndex].timestamp < targetTime) upperIndex += 1;
	const lower = dataset.frames[upperIndex - 1];
	const upper = dataset.frames[upperIndex];
	const gap = safeDifference(upper.timestamp, lower.timestamp);
	if (gap === null || gap <= 0) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "The bracketing timestamp difference exceeds the supported numerical range.",
		coverage: countCoverage(0, topologyPointCount(dataset.topology)),
		gates: []
	};
	const gate = interpolationGapGate(gap, maximumGap);
	const pointCount = topologyPointCount(dataset.topology);
	const validMask = lower.validMask.map((valid, pointIndex) => valid && upper.validMask[pointIndex]);
	const coverage = countCoverage(validMask.filter(Boolean).length, pointCount);
	if (!gate.passed) return {
		status: "insufficient-evidence",
		reason: "interpolation-gap-too-large",
		detail: "The bracketing frames exceed the declared interpolation gap.",
		coverage,
		gates: [gate]
	};
	const targetOffset = safeDifference(targetTime, lower.timestamp);
	if (targetOffset === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "The requested interpolation offset exceeds the supported numerical range.",
		coverage,
		gates: [gate]
	};
	const fraction = targetOffset / gap;
	if (!Number.isFinite(fraction)) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "The interpolation fraction exceeds the supported numerical range.",
		coverage,
		gates: [gate]
	};
	const values = [];
	for (let index = 0; index < lower.values.length; index += 1) {
		const interpolated = safeLinearInterpolate(lower.values[index], upper.values[index], fraction);
		if (interpolated === null) return {
			status: "insufficient-evidence",
			reason: "numerical-range-exceeded",
			detail: "Component-wise interpolation exceeds the supported numerical range.",
			coverage,
			gates: [gate]
		};
		values.push(interpolated);
	}
	return {
		status: "available",
		value: {
			interpolated: true,
			frame: {
				timestamp: targetTime,
				values,
				validMask
			}
		},
		coverage,
		gates: [gate]
	};
}
function availableFrameSpeeds(dataset, minimumPointCoverage) {
	const available = [];
	let numericalRangeFailures = 0;
	for (const frame of dataset.frames) {
		const result = evaluateSpeed(dataset, frame, minimumPointCoverage);
		if (result.status === "available") available.push({
			timestamp: frame.timestamp,
			summary: result.value
		});
		else if (result.status === "insufficient-evidence" && result.reason === "numerical-range-exceeded") numericalRangeFailures += 1;
	}
	return {
		values: available,
		numericalRangeFailures
	};
}
function maximum$1(values) {
	let result = Number.NEGATIVE_INFINITY;
	for (const value of values) result = Math.max(result, value);
	return result;
}
function frameCoverageGate(observed, criterion) {
	return {
		id: "minimum-frame-summary-coverage",
		passed: observed >= criterion,
		observed,
		criterion,
		detail: "An unweighted frame summary uses only frames whose speed metric passes its spatial gate."
	};
}
function summarizeFrameMeanSpeed(dataset, minimumPointCoverage, minimumFrameCoverage) {
	validateCoverageGate$1(minimumPointCoverage, "Speed point coverage");
	validateCoverageGate$1(minimumFrameCoverage, "Frame summary coverage");
	if (dataset.temporal.kind !== "time-series") return {
		status: "unavailable",
		reason: "not-a-time-series",
		detail: "A single vector field does not have a frame-mean summary.",
		gates: []
	};
	const frameAverageRefusal = frameAverageTemporalRefusal(dataset, "The unweighted temporal speed summary");
	if (frameAverageRefusal !== null) return frameAverageRefusal;
	const evaluated = availableFrameSpeeds(dataset, minimumPointCoverage);
	const available = evaluated.values;
	const coverage = countCoverage(available.length, dataset.frames.length);
	const gate = frameCoverageGate(coverage.fraction, minimumFrameCoverage);
	if (evaluated.numericalRangeFailures > 0) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "At least one frame speed summary exceeds the supported numerical range.",
		coverage,
		gates: [gate]
	};
	if (available.length === 0) return {
		status: "insufficient-evidence",
		reason: "no-valid-points",
		detail: "No frame passes the declared spatial speed gate.",
		coverage,
		gates: [gate]
	};
	if (!gate.passed) return {
		status: "insufficient-evidence",
		reason: "coverage-below-gate",
		detail: "Frame coverage is below the declared summary gate.",
		coverage,
		gates: [gate]
	};
	const spatialMeanSpeed = safeMean(available.map((item) => item.summary.mean));
	const instantaneousMaximumSpeedMean = safeMean(available.map((item) => item.summary.maximum));
	if (spatialMeanSpeed === null || instantaneousMaximumSpeedMean === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Frame-mean aggregation exceeds the supported numerical range.",
		coverage,
		gates: [gate]
	};
	return {
		status: "available",
		value: {
			scope: "unweighted-frame-mean",
			unit: available[0].summary.unit,
			spatialMeanSpeed,
			instantaneousMaximumSpeedMean,
			maximumObservedSpeed: maximum$1(available.map((item) => item.summary.maximum)),
			contributingFrames: available.length,
			totalFrames: dataset.frames.length,
			duration: null
		},
		coverage,
		gates: [gate]
	};
}
function cycleGate(id, passed, observed, criterion, detail) {
	return {
		id,
		passed,
		observed,
		criterion,
		detail
	};
}
function trapezoidalMean(samples, select) {
	let directIntegral = 0;
	for (let index = 0; index < samples.length - 1; index += 1) {
		const current = samples[index];
		const next = samples[index + 1];
		directIntegral += .5 * (select(current.summary) + select(next.summary)) * (next.timestamp - current.timestamp);
	}
	const directSpan = safeDifference(samples[samples.length - 1].timestamp, samples[0].timestamp);
	if (directSpan !== null && directSpan > 0) {
		const direct = directIntegral / directSpan;
		if (Number.isFinite(direct)) return direct;
	}
	const intervalMeans = [];
	const durations = [];
	for (let index = 0; index < samples.length - 1; index += 1) {
		const current = samples[index];
		const next = samples[index + 1];
		const intervalMean = safeMean([select(current.summary), select(next.summary)]);
		const duration = safeDifference(next.timestamp, current.timestamp);
		if (intervalMean === null || duration === null || duration <= 0) return null;
		intervalMeans.push(intervalMean);
		durations.push(duration);
	}
	return safeWeightedMean(intervalMeans, durations);
}
function selectCanonicalCycleFrames(frames, cycle) {
	return frames.filter((frame) => frame.timestamp >= cycle.startTime && frame.timestamp <= cycle.endTime);
}
function summarizeCompleteCycleSpeed(dataset, minimumPointCoverage, policy) {
	validateCoverageGate$1(minimumPointCoverage, "Speed point coverage");
	if (dataset.temporal.kind !== "time-series") return {
		status: "unavailable",
		reason: "not-a-time-series",
		detail: "A single vector field cannot support a complete-cycle summary.",
		gates: []
	};
	if (policy === null) return {
		status: "unavailable",
		reason: "cycle-gate-not-declared",
		detail: "No complete-cycle gate policy was declared by the audit scenario.",
		gates: []
	};
	validateCyclePolicy(policy);
	const temporal = dataset.temporal;
	const cycle = temporal.cycle;
	if (cycle === null) return {
		status: "unavailable",
		reason: "cycle-metadata-missing",
		detail: "The dataset does not declare cycle period, endpoints, and phase origin.",
		gates: []
	};
	const frameAverageRefusal = frameAverageTemporalRefusal(dataset, "The complete-cycle temporal speed summary");
	if (frameAverageRefusal !== null) return frameAverageRefusal;
	const tolerance = policy.endpointToleranceFraction * cycle.period;
	const cycleFrames = selectCanonicalCycleFrames(dataset.frames, cycle);
	const first = cycleFrames[0];
	const last = cycleFrames[cycleFrames.length - 1];
	const startDifference = first === void 0 ? null : safeDifference(first.timestamp, cycle.startTime);
	const endDifference = last === void 0 ? null : safeDifference(last.timestamp, cycle.endTime);
	if (first !== void 0 && startDifference === null || last !== void 0 && endDifference === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Cycle endpoint comparison exceeds the supported numerical range.",
		coverage: countCoverage(0, cycleFrames.length),
		gates: []
	};
	const endpointPassed = first !== void 0 && last !== void 0 && startDifference !== null && endDifference !== null && Math.abs(startDifference) <= tolerance && Math.abs(endDifference) <= tolerance;
	const durationResult = first === void 0 || last === void 0 ? 0 : safeDifference(last.timestamp, first.timestamp);
	if (durationResult === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Cycle duration exceeds the supported numerical range.",
		coverage: countCoverage(0, cycleFrames.length),
		gates: []
	};
	const actualDuration = durationResult;
	const periodDifference = safeDifference(actualDuration, cycle.period);
	if (periodDifference === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Cycle period comparison exceeds the supported numerical range.",
		coverage: countCoverage(0, cycleFrames.length),
		gates: []
	};
	const periodRelativeError = Math.abs(periodDifference) / cycle.period;
	if (!Number.isFinite(periodRelativeError)) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Cycle period normalization exceeds the supported numerical range.",
		coverage: countCoverage(0, cycleFrames.length),
		gates: []
	};
	const intervals = Math.max(0, cycleFrames.length - 1);
	const gaps = [];
	for (let index = 1; index < cycleFrames.length; index += 1) {
		const gap = safeDifference(cycleFrames[index].timestamp, cycleFrames[index - 1].timestamp);
		if (gap === null || gap <= 0) return {
			status: "insufficient-evidence",
			reason: "numerical-range-exceeded",
			detail: "A cycle timestamp interval exceeds the supported numerical range.",
			coverage: countCoverage(0, cycleFrames.length),
			gates: []
		};
		gaps.push(gap);
	}
	const maximumGapFraction = gaps.length === 0 ? null : maximum$1(gaps) / cycle.period;
	if (maximumGapFraction !== null && !Number.isFinite(maximumGapFraction)) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Cycle gap normalization exceeds the supported numerical range.",
		coverage: countCoverage(0, cycleFrames.length),
		gates: []
	};
	const cadenceDeviations = [];
	for (const gap of gaps) {
		const difference = safeDifference(gap, temporal.nominalCadence);
		if (difference === null) return {
			status: "insufficient-evidence",
			reason: "numerical-range-exceeded",
			detail: "Cycle cadence comparison exceeds the supported numerical range.",
			coverage: countCoverage(0, cycleFrames.length),
			gates: []
		};
		const deviation = Math.abs(difference) / temporal.nominalCadence;
		if (!Number.isFinite(deviation)) return {
			status: "insufficient-evidence",
			reason: "numerical-range-exceeded",
			detail: "Cycle cadence normalization exceeds the supported numerical range.",
			coverage: countCoverage(0, cycleFrames.length),
			gates: []
		};
		cadenceDeviations.push(deviation);
	}
	const maximumCadenceDeviation = cadenceDeviations.length === 0 ? null : maximum$1(cadenceDeviations);
	const endpointGate = cycleGate("complete-cycle-endpoints", endpointPassed, endpointPassed ? "covered" : "incomplete", `within ${policy.endpointToleranceFraction} of period`, "The first and last frames selected from the closed canonical cycle window must represent the declared endpoints within tolerance.");
	const periodGate = cycleGate("complete-cycle-period-match", periodRelativeError <= policy.endpointToleranceFraction, periodRelativeError, policy.endpointToleranceFraction, "The selected closed-window timestamp span must match the declared period within the endpoint acceptance tolerance.");
	const intervalGate = cycleGate("minimum-cycle-intervals", intervals >= policy.minimumIntervals, intervals, policy.minimumIntervals, "The cycle must contain the declared minimum number of intervals.");
	const gapGate = cycleGate("maximum-cycle-gap", maximumGapFraction !== null && maximumGapFraction <= policy.maximumGapFractionOfPeriod, maximumGapFraction ?? "no intervals", policy.maximumGapFractionOfPeriod, "No temporal gap may exceed the declared fraction of the cycle period.");
	const cadenceGate = cycleGate("maximum-cycle-cadence-deviation", maximumCadenceDeviation !== null && maximumCadenceDeviation <= policy.maximumCadenceDeviationFraction, maximumCadenceDeviation ?? "no intervals", policy.maximumCadenceDeviationFraction, "Every interval must remain within the declared nominal-cadence tolerance.");
	const timedSpeeds = [];
	let numericalRangeFailures = 0;
	for (const frame of cycleFrames) {
		const speed = evaluateSpeed(dataset, frame, minimumPointCoverage);
		if (speed.status === "available") timedSpeeds.push({
			timestamp: frame.timestamp,
			summary: speed.value
		});
		else if (speed.status === "insufficient-evidence" && speed.reason === "numerical-range-exceeded") numericalRangeFailures += 1;
	}
	const metricCoverage = countCoverage(timedSpeeds.length, cycleFrames.length);
	const gates = [
		endpointGate,
		periodGate,
		intervalGate,
		gapGate,
		cadenceGate,
		cycleGate("complete-cycle-metric-frame-coverage", metricCoverage.fraction === 1, metricCoverage.fraction, 1, "Every cycle frame must pass the spatial speed gate.")
	];
	if (numericalRangeFailures > 0) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "At least one cycle frame speed summary exceeds the supported numerical range.",
		coverage: metricCoverage,
		gates
	};
	const failed = gates.find((gate) => !gate.passed);
	if (failed !== void 0) return {
		status: "insufficient-evidence",
		reason: !endpointGate.passed ? "cycle-endpoints-incomplete" : !periodGate.passed ? "cycle-period-mismatch" : !intervalGate.passed ? "cycle-too-few-intervals" : !gapGate.passed ? "cycle-gap-too-large" : !cadenceGate.passed ? "cycle-cadence-mismatch" : "coverage-below-gate",
		detail: failed.detail,
		coverage: metricCoverage,
		gates
	};
	const spatialMeanSpeed = trapezoidalMean(timedSpeeds, (summary) => summary.mean);
	const instantaneousMaximumSpeedMean = trapezoidalMean(timedSpeeds, (summary) => summary.maximum);
	if (spatialMeanSpeed === null || instantaneousMaximumSpeedMean === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Complete-cycle time integration exceeds the supported numerical range.",
		coverage: metricCoverage,
		gates
	};
	return {
		status: "available",
		value: {
			scope: "complete-cycle-time-mean",
			unit: timedSpeeds[0].summary.unit,
			spatialMeanSpeed,
			instantaneousMaximumSpeedMean,
			maximumObservedSpeed: maximum$1(timedSpeeds.map((item) => item.summary.maximum)),
			contributingFrames: timedSpeeds.length,
			totalFrames: cycleFrames.length,
			duration: actualDuration
		},
		coverage: metricCoverage,
		gates
	};
}
//#endregion
//#region src/domain/vectorAuditValidation.ts
var IDENTIFIER$1 = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
function fail$1(path, message) {
	throw new Error(`${path}: ${message}`);
}
function isRecord(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record$1(value, path) {
	if (!isRecord(value)) return fail$1(path, "must be an object.");
	return value;
}
function exactKeys$1(value, required, path) {
	const allowed = new Set(required);
	for (const key of required) if (!Object.prototype.hasOwnProperty.call(value, key)) fail$1(path, `is missing required property ${JSON.stringify(key)}.`);
	for (const key of Object.keys(value)) if (!allowed.has(key)) fail$1(path, `contains unsupported property ${JSON.stringify(key)}.`);
}
function property$1(value, key) {
	return value[key];
}
function finite(value, path) {
	if (typeof value !== "number" || !Number.isFinite(value)) return fail$1(path, "must be a finite number.");
	return value;
}
function positive(value, path) {
	const parsed = finite(value, path);
	if (parsed <= 0) fail$1(path, "must be greater than zero.");
	return parsed;
}
function fraction(value, path) {
	const parsed = finite(value, path);
	if (parsed < 0 || parsed > 1) fail$1(path, "must lie between zero and one.");
	return parsed;
}
function nonnegative(value, path) {
	const parsed = finite(value, path);
	if (parsed < 0) fail$1(path, "must be nonnegative.");
	return parsed;
}
function identifier$1(value, path) {
	if (typeof value !== "string" || !IDENTIFIER$1.test(value)) return fail$1(path, "must be a portable identifier.");
	return value;
}
function hasControlCharacter(value) {
	for (const character of value) {
		const code = character.codePointAt(0);
		if (code !== void 0 && (code < 32 || code === 127 || code >= 8234 && code <= 8238 || code >= 8294 && code <= 8297)) return true;
	}
	return false;
}
function text$1(value, path) {
	if (typeof value !== "string" || value.length === 0 || value.length > 256 || hasControlCharacter(value)) return fail$1(path, "must be nonempty bounded text without control characters.");
	return value;
}
function parseCyclePolicy(value, path) {
	if (value === null) return null;
	const item = record$1(value, path);
	exactKeys$1(item, [
		"minimumIntervals",
		"maximumGapFractionOfPeriod",
		"maximumCadenceDeviationFraction",
		"endpointToleranceFraction"
	], path);
	const minimumIntervals = finite(property$1(item, "minimumIntervals"), `${path}.minimumIntervals`);
	if (!Number.isInteger(minimumIntervals) || minimumIntervals < 1) fail$1(`${path}.minimumIntervals`, "must be a positive integer.");
	const maximumGapFractionOfPeriod = positive(property$1(item, "maximumGapFractionOfPeriod"), `${path}.maximumGapFractionOfPeriod`);
	if (maximumGapFractionOfPeriod > 1) fail$1(`${path}.maximumGapFractionOfPeriod`, "must not exceed one.");
	return {
		minimumIntervals,
		maximumGapFractionOfPeriod,
		maximumCadenceDeviationFraction: nonnegative(property$1(item, "maximumCadenceDeviationFraction"), `${path}.maximumCadenceDeviationFraction`),
		endpointToleranceFraction: fraction(property$1(item, "endpointToleranceFraction"), `${path}.endpointToleranceFraction`)
	};
}
function parseGates(value, path) {
	const item = record$1(value, path);
	exactKeys$1(item, [
		"minimumSpeedPointCoverage",
		"minimumDerivativeStencilCoverage",
		"maximumInterpolationGap",
		"minimumFrameSummaryCoverage",
		"minimumWallPairCoverage",
		"cycle"
	], path);
	return {
		minimumSpeedPointCoverage: fraction(property$1(item, "minimumSpeedPointCoverage"), `${path}.minimumSpeedPointCoverage`),
		minimumDerivativeStencilCoverage: fraction(property$1(item, "minimumDerivativeStencilCoverage"), `${path}.minimumDerivativeStencilCoverage`),
		maximumInterpolationGap: positive(property$1(item, "maximumInterpolationGap"), `${path}.maximumInterpolationGap`),
		minimumFrameSummaryCoverage: fraction(property$1(item, "minimumFrameSummaryCoverage"), `${path}.minimumFrameSummaryCoverage`),
		minimumWallPairCoverage: fraction(property$1(item, "minimumWallPairCoverage"), `${path}.minimumWallPairCoverage`),
		cycle: parseCyclePolicy(property$1(item, "cycle"), `${path}.cycle`)
	};
}
function parseVectorAuditScenario(value) {
	const path = "scenario";
	const item = record$1(value, path);
	exactKeys$1(item, [
		"schemaVersion",
		"id",
		"title",
		"selectedTime",
		"gates"
	], path);
	if (property$1(item, "schemaVersion") !== 1) fail$1(`${path}.schemaVersion`, "must equal 1.");
	return {
		schemaVersion: 1,
		id: identifier$1(property$1(item, "id"), `${path}.id`),
		title: text$1(property$1(item, "title"), `${path}.title`),
		selectedTime: finite(property$1(item, "selectedTime"), `${path}.selectedTime`),
		gates: parseGates(property$1(item, "gates"), `${path}.gates`)
	};
}
//#endregion
//#region src/domain/wallShear.ts
function validateCoverageGate(minimumCoverage) {
	if (!Number.isFinite(minimumCoverage) || minimumCoverage < 0 || minimumCoverage > 1) throw new Error("A wall coverage gate must lie between zero and one.");
}
function maximum(values) {
	let result = Number.NEGATIVE_INFINITY;
	for (const value of values) result = Math.max(result, value);
	return result;
}
function numericalRangeGate(invalidCount) {
	return {
		id: "finite-wall-shear-derivation",
		passed: invalidCount === 0,
		observed: invalidCount,
		criterion: 0,
		detail: "Every accepted wall pair must produce finite representable geometry and shear values."
	};
}
function wallCoverageGate(observed, criterion) {
	return {
		id: "minimum-wall-pair-coverage",
		passed: observed >= criterion,
		observed,
		criterion,
		detail: "Wall shear requires valid no-slip wall and near-wall vectors for every accepted pair."
	};
}
function evaluateWallShear(dataset, frame, minimumCoverage) {
	validateCoverageGate(minimumCoverage);
	if (dataset.wall === null) return {
		status: "unavailable",
		reason: "wall-evidence-missing",
		detail: "Wall shear requires wall locations, normals, dynamic viscosity, and an explicit near-wall gradient method.",
		gates: []
	};
	const { dynamicViscosity, method } = dataset.wall;
	const dimension = dataset.coordinateFrame.dimension;
	const componentCount = dataset.components.length;
	const velocityUnit = dataset.components[0].unit;
	const viscosity = viscosityToPascalSeconds(dynamicViscosity.value, dynamicViscosity.unit);
	const maximumWallSpeed = velocityToMetersPerSecond(method.maximumWallSpeed, method.wallSpeedUnit);
	const magnitudes = [];
	let maskExcludedPairs = 0;
	let noSlipExcludedPairs = 0;
	let geometryExcludedPairs = 0;
	let numericalRangePairs = 0;
	for (let pair = 0; pair < method.wallPointIndices.length; pair += 1) {
		const wallIndex = method.wallPointIndices[pair];
		const nearWallIndex = method.nearWallPointIndices[pair];
		if (!frame.validMask[wallIndex] || !frame.validMask[nearWallIndex]) {
			maskExcludedPairs += 1;
			continue;
		}
		const wallVelocity = Array.from({ length: componentCount }, (_, component) => velocityToMetersPerSecond(frame.values[wallIndex * componentCount + component], velocityUnit));
		const wallSpeed = safeNorm(wallVelocity);
		if (wallSpeed === null) {
			numericalRangePairs += 1;
			continue;
		}
		if (wallSpeed > maximumWallSpeed) {
			noSlipExcludedPairs += 1;
			continue;
		}
		const nearWallVelocity = Array.from({ length: componentCount }, (_, component) => velocityToMetersPerSecond(frame.values[nearWallIndex * componentCount + component], velocityUnit));
		const wallPoint = topologyPointCoordinates(dataset.topology, wallIndex).map((coordinate) => lengthToMeters(coordinate, dataset.coordinateFrame.lengthUnit));
		const nearWallPoint = topologyPointCoordinates(dataset.topology, nearWallIndex).map((coordinate) => lengthToMeters(coordinate, dataset.coordinateFrame.lengthUnit));
		const normal = method.normals.slice(pair * dimension, (pair + 1) * dimension);
		const spatialDelta = [];
		for (let axis = 0; axis < dimension; axis += 1) {
			const difference = safeDifference(nearWallPoint[axis], wallPoint[axis]);
			if (difference === null) {
				numericalRangePairs += 1;
				break;
			}
			spatialDelta.push(difference);
		}
		if (spatialDelta.length !== dimension) continue;
		const normalDistance = safeDot(spatialDelta, normal);
		if (normalDistance === null) {
			numericalRangePairs += 1;
			continue;
		}
		if (normalDistance <= 0) {
			geometryExcludedPairs += 1;
			continue;
		}
		const tangentialOffset = [];
		for (let axis = 0; axis < dimension; axis += 1) {
			const normalComponent = safeProduct(normalDistance, normal[axis]);
			const component = normalComponent === null ? null : safeDifference(spatialDelta[axis], normalComponent);
			if (component === null) {
				numericalRangePairs += 1;
				break;
			}
			tangentialOffset.push(component);
		}
		if (tangentialOffset.length !== dimension) continue;
		const tangentialOffsetMagnitude = safeNorm(tangentialOffset);
		if (tangentialOffsetMagnitude === null) {
			numericalRangePairs += 1;
			continue;
		}
		const tangentialOffsetFraction = tangentialOffsetMagnitude / normalDistance;
		if (!Number.isFinite(tangentialOffsetFraction)) {
			numericalRangePairs += 1;
			continue;
		}
		if (tangentialOffsetFraction > method.maximumTangentialOffsetFraction) {
			geometryExcludedPairs += 1;
			continue;
		}
		const velocityDelta = [];
		for (let axis = 0; axis < dimension; axis += 1) {
			const difference = safeDifference(nearWallVelocity[axis], wallVelocity[axis]);
			if (difference === null) {
				numericalRangePairs += 1;
				break;
			}
			velocityDelta.push(difference);
		}
		if (velocityDelta.length !== dimension) continue;
		const normalVelocityDelta = safeDot(velocityDelta, normal);
		if (normalVelocityDelta === null) {
			numericalRangePairs += 1;
			continue;
		}
		const tangentialVelocityDelta = [];
		for (let axis = 0; axis < dimension; axis += 1) {
			const normalComponent = safeProduct(normalVelocityDelta, normal[axis]);
			const component = normalComponent === null ? null : safeDifference(velocityDelta[axis], normalComponent);
			if (component === null) {
				numericalRangePairs += 1;
				break;
			}
			tangentialVelocityDelta.push(component);
		}
		if (tangentialVelocityDelta.length !== dimension) continue;
		const shearVector = [];
		for (const component of tangentialVelocityDelta) {
			const shear = safeProductQuotient(viscosity, component, normalDistance);
			if (shear === null) {
				numericalRangePairs += 1;
				break;
			}
			shearVector.push(shear);
		}
		if (shearVector.length !== dimension) continue;
		const shearMagnitude = safeNorm(shearVector);
		if (shearMagnitude === null) {
			numericalRangePairs += 1;
			continue;
		}
		magnitudes.push(shearMagnitude);
	}
	const coverage = countCoverage(magnitudes.length, method.wallPointIndices.length);
	const coverageDecision = wallCoverageGate(coverage.fraction, minimumCoverage);
	const numericalDecision = numericalRangeGate(numericalRangePairs);
	const gates = [coverageDecision, numericalDecision];
	if (!numericalDecision.passed) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "At least one valid wall pair exceeds the supported numerical range.",
		coverage,
		gates
	};
	if (magnitudes.length === 0) return {
		status: "insufficient-evidence",
		reason: noSlipExcludedPairs > 0 ? "wall-no-slip-failed" : geometryExcludedPairs > 0 ? "wall-gradient-invalid" : "coverage-below-gate",
		detail: "No wall pair satisfies the declared mask, no-slip, geometry, and gradient evidence.",
		coverage,
		gates
	};
	if (!coverageDecision.passed) return {
		status: "insufficient-evidence",
		reason: "coverage-below-gate",
		detail: "Valid wall-pair coverage is below the declared WSS gate.",
		coverage,
		gates
	};
	const meanMagnitude = safeMean(magnitudes);
	if (meanMagnitude === null) return {
		status: "insufficient-evidence",
		reason: "numerical-range-exceeded",
		detail: "Wall shear aggregation exceeds the supported numerical range.",
		coverage,
		gates
	};
	return {
		status: "available",
		value: {
			unit: "Pa",
			method: "point-pair-first-order",
			meanMagnitude,
			maximumMagnitude: maximum(magnitudes),
			pairCount: method.wallPointIndices.length,
			maskExcludedPairs,
			noSlipExcludedPairs,
			geometryExcludedPairs
		},
		coverage,
		gates
	};
}
//#endregion
//#region src/version.ts
var FLOWBLIND_VERSION = "0.11.0";
//#endregion
//#region src/application/runVectorTimeAudit.ts
function propagateFailure(result) {
	if (result.status === "unavailable") return {
		status: "unavailable",
		reason: result.reason,
		detail: result.detail,
		gates: result.gates
	};
	return {
		status: "insufficient-evidence",
		reason: result.reason,
		detail: result.detail,
		coverage: result.coverage,
		gates: result.gates
	};
}
function limitationsFor(dataset) {
	const limitations = ["This readiness report does not establish multimodal, solver, physiological, acquisition, clinical, or diagnostic validation."];
	if (dataset.coordinateFrame.dimension === 2) limitations.push("Two-dimensional components support only in-plane speed, in-plane divergence, out-of-plane vorticity, and in-plane strain; omitted through-plane terms remain unknown.");
	if (dataset.topology.kind === "unstructured") limitations.push("Unstructured derivative metrics are unavailable in Layer 2 because no reviewed unstructured gradient operator is implemented.");
	if (dataset.wall === null) limitations.push("Wall shear stress is unavailable without wall locations, normals, dynamic viscosity, and an explicit valid near-wall gradient method.");
	if (dataset.provenance.sourceKind === "generated") limitations.push("The dataset is generated evidence for software readiness, not patient data or an independent physical measurement.");
	if (dataset.temporal.sampling.kind === "frame-average") {
		const sampling = resolveFrameAverageSampling(dataset.temporal.sampling);
		if (sampling.exposureOperator === "unspecified" || sampling.timestampAnchor === "unspecified") limitations.push("Frame-average exposure metadata does not concretely declare both the exposure operator and timestamp anchor. Point-time interpolation and temporal derived metrics are unavailable rather than evaluated with timestamp-sample assumptions.");
		else limitations.push(`Frame-average sampling declares ${sampling.exposureOperator} over ${sampling.exposureDuration} ${dataset.temporal.timestampUnit}, anchored at the exposure ${sampling.timestampAnchor}. FlowBlind does not yet implement exposure-aware point-time interpolation, temporal integration, or deconvolution, so those derived metrics are unavailable.`);
	}
	return limitations;
}
function temporalForReport(temporal) {
	if (temporal.sampling.kind !== "frame-average") return temporal;
	return {
		...temporal,
		sampling: resolveFrameAverageSampling(temporal.sampling)
	};
}
function runVectorTimeAudit(dataset, source, scenario) {
	const declaredScenario = parseVectorAuditScenario(scenario);
	const resolved = interpolateVectorFrame(dataset, declaredScenario.selectedTime, declaredScenario.gates.maximumInterpolationGap);
	let instantaneous;
	if (resolved.status === "available") {
		const frame = resolved.value.frame;
		instantaneous = {
			requestedTime: declaredScenario.selectedTime,
			resolvedTime: frame.timestamp,
			interpolated: resolved.value.interpolated,
			speed: evaluateSpeed(dataset, frame, declaredScenario.gates.minimumSpeedPointCoverage),
			derivatives: evaluateStructuredDerivatives(dataset, frame, declaredScenario.gates.minimumDerivativeStencilCoverage),
			wallShear: evaluateWallShear(dataset, frame, declaredScenario.gates.minimumWallPairCoverage)
		};
	} else instantaneous = {
		requestedTime: declaredScenario.selectedTime,
		resolvedTime: null,
		interpolated: false,
		speed: propagateFailure(resolved),
		derivatives: propagateFailure(resolved),
		wallShear: propagateFailure(resolved)
	};
	return {
		schemaVersion: 1,
		reportId: `${dataset.id}--${declaredScenario.id}`,
		software: {
			name: "FlowBlind",
			version: FLOWBLIND_VERSION
		},
		dataset: {
			id: dataset.id,
			title: dataset.title,
			description: dataset.description,
			kind: dataset.kind,
			pointCount: topologyPointCount(dataset.topology),
			frameCount: dataset.frames.length,
			coordinateFrame: dataset.coordinateFrame,
			components: dataset.components,
			temporal: temporalForReport(dataset.temporal),
			wall: dataset.wall,
			provenance: dataset.provenance,
			documentSource: source
		},
		scenario: declaredScenario,
		metrics: {
			instantaneous,
			frameMean: summarizeFrameMeanSpeed(dataset, declaredScenario.gates.minimumSpeedPointCoverage, declaredScenario.gates.minimumFrameSummaryCoverage),
			completeCycle: summarizeCompleteCycleSpeed(dataset, declaredScenario.gates.minimumSpeedPointCoverage, declaredScenario.gates.cycle)
		},
		limitations: limitationsFor(dataset)
	};
}
//#endregion
//#region src/domain/vectorDatasetValidation.ts
var IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
var SHA256$1 = /^[a-f0-9]{64}$/;
var UNIT_NORMAL_TOLERANCE = 1e-6;
var CELL_ARITY = {
	vertex: 1,
	line: 2,
	triangle: 3,
	quad: 4,
	tetrahedron: 4,
	hexahedron: 8,
	wedge: 6,
	pyramid: 5
};
function fail(path, message) {
	throw new Error(`${path}: ${message}`);
}
function isUnknownRecord(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record(value, path) {
	if (!isUnknownRecord(value)) return fail(path, "must be an object.");
	return value;
}
function array(value, path) {
	if (!Array.isArray(value)) return fail(path, "must be an array.");
	return value;
}
function exactKeys(value, required, optional, path) {
	const allowed = /* @__PURE__ */ new Set([...required, ...optional]);
	for (const key of required) if (!Object.prototype.hasOwnProperty.call(value, key)) fail(path, `is missing required property ${JSON.stringify(key)}.`);
	for (const key of Object.keys(value)) if (!allowed.has(key)) fail(path, `contains unsupported property ${JSON.stringify(key)}.`);
}
function property(value, key) {
	return value[key];
}
function finiteNumber(value, path) {
	if (typeof value !== "number" || !Number.isFinite(value)) return fail(path, "must be a finite number.");
	return value;
}
function positiveNumber(value, path) {
	const parsed = finiteNumber(value, path);
	if (parsed <= 0) fail(path, "must be greater than zero.");
	return parsed;
}
function nonnegativeNumber(value, path) {
	const parsed = finiteNumber(value, path);
	if (parsed < 0) fail(path, "must be nonnegative.");
	return parsed;
}
function integer(value, path) {
	const parsed = finiteNumber(value, path);
	if (!Number.isInteger(parsed)) fail(path, "must be an integer.");
	return parsed;
}
function nonnegativeInteger(value, path) {
	const parsed = integer(value, path);
	if (parsed < 0) fail(path, "must be nonnegative.");
	return parsed;
}
function hasUnsupportedControl(value) {
	for (const character of value) {
		const code = character.codePointAt(0);
		if (code === 127 || code !== void 0 && code >= 8234 && code <= 8238 || code !== void 0 && code >= 8294 && code <= 8297 || code !== void 0 && code < 32 && code !== 9 && code !== 10 && code !== 13) return true;
	}
	return false;
}
function boundedFraction(value, path) {
	const parsed = finiteNumber(value, path);
	if (parsed < 0 || parsed > 1) fail(path, "must lie between zero and one.");
	return parsed;
}
function text(value, path, maximumLength = 2048) {
	if (typeof value !== "string" || value.length === 0 || value.length > maximumLength || hasUnsupportedControl(value)) return fail(path, `must be nonempty text no longer than ${maximumLength} characters without control characters.`);
	return value;
}
function identifier(value, path) {
	const parsed = text(value, path, 64);
	if (!IDENTIFIER.test(parsed)) fail(path, "must be a portable identifier.");
	return parsed;
}
function sha256(value, path) {
	if (typeof value !== "string" || !SHA256$1.test(value)) return fail(path, "must be a lowercase hexadecimal SHA-256 digest.");
	return value;
}
function parseLengthUnit(value, path) {
	if (value === "m" || value === "cm" || value === "mm") return value;
	return fail(path, "must be one of m, cm, or mm.");
}
function parseTimeUnit(value, path) {
	if (value === "s" || value === "ms") return value;
	return fail(path, "must be s or ms.");
}
function parseVelocityUnit(value, path) {
	if (value === "m/s" || value === "cm/s" || value === "mm/s") return value;
	return fail(path, "must be one of m/s, cm/s, or mm/s.");
}
function parseDynamicViscosityUnit(value, path) {
	if (value === "Pa*s" || value === "mPa*s") return value;
	return fail(path, "must be Pa*s or mPa*s.");
}
function parseAxis(value, path) {
	if (value === "x" || value === "y" || value === "z") return value;
	return fail(path, "must be x, y, or z.");
}
function parseKind(value, path) {
	if (value === "structured-vector-field" || value === "structured-vector-time-series" || value === "unstructured-vector-field" || value === "unstructured-vector-time-series") return value;
	return fail(path, "is not a supported vector dataset kind.");
}
function numberArray(value, path) {
	return array(value, path).map((item, index) => finiteNumber(item, `${path}[${index}]`));
}
function booleanArray(value, path) {
	return array(value, path).map((item, index) => {
		if (typeof item !== "boolean") fail(`${path}[${index}]`, "must be a boolean.");
		return item;
	});
}
function integerArray(value, path) {
	return array(value, path).map((item, index) => nonnegativeInteger(item, `${path}[${index}]`));
}
function textArray(value, path) {
	return array(value, path).map((item, index) => text(item, `${path}[${index}]`));
}
function validateStrictMonotonic(values, path) {
	if (values.length === 0) fail(path, "must contain at least one coordinate.");
	if (values.length === 1) return;
	const direction = Math.sign(values[1] - values[0]);
	if (direction === 0) fail(path, "must be strictly monotonic.");
	for (let index = 1; index < values.length; index += 1) if (Math.sign(values[index] - values[index - 1]) !== direction) fail(path, "must be strictly monotonic.");
}
function parseCoordinateFrame(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"id",
		"type",
		"dimension",
		"handedness",
		"axisNames",
		"lengthUnit"
	], [], path);
	if (property(item, "type") !== "cartesian") fail(`${path}.type`, "must be cartesian.");
	const dimensionValue = integer(property(item, "dimension"), `${path}.dimension`);
	if (dimensionValue !== 2 && dimensionValue !== 3) fail(`${path}.dimension`, "must be 2 or 3.");
	const axisNames = textArray(property(item, "axisNames"), `${path}.axisNames`);
	if (axisNames.length !== dimensionValue || new Set(axisNames).size !== axisNames.length) fail(`${path}.axisNames`, "must contain one unique display name per coordinate axis.");
	const handedness = property(item, "handedness");
	if (handedness !== "right-handed" && handedness !== "unspecified") fail(`${path}.handedness`, "must be right-handed or explicitly unspecified.");
	return {
		id: identifier(property(item, "id"), `${path}.id`),
		type: "cartesian",
		dimension: dimensionValue,
		handedness,
		axisNames,
		lengthUnit: parseLengthUnit(property(item, "lengthUnit"), `${path}.lengthUnit`)
	};
}
function parseComponents(value, frame, path) {
	const expectedAxes = frame.dimension === 2 ? ["x", "y"] : [
		"x",
		"y",
		"z"
	];
	const componentValues = array(value, path);
	if (componentValues.length !== frame.dimension) fail(path, "must contain exactly one component per coordinate axis.");
	const components = componentValues.map((entry, index) => {
		const itemPath = `${path}[${index}]`;
		const item = record(entry, itemPath);
		exactKeys(item, [
			"name",
			"axis",
			"frameId",
			"unit"
		], [], itemPath);
		return {
			name: text(property(item, "name"), `${itemPath}.name`, 128),
			axis: parseAxis(property(item, "axis"), `${itemPath}.axis`),
			frameId: identifier(property(item, "frameId"), `${itemPath}.frameId`),
			unit: parseVelocityUnit(property(item, "unit"), `${itemPath}.unit`)
		};
	});
	if (new Set(components.map((component) => component.name)).size !== components.length) fail(path, "must use unique component names.");
	const firstUnit = components[0]?.unit;
	for (let index = 0; index < components.length; index += 1) {
		const component = components[index];
		if (component.axis !== expectedAxes[index]) fail(`${path}[${index}].axis`, `must be ${expectedAxes[index]} in canonical component order.`);
		if (component.frameId !== frame.id) fail(`${path}[${index}].frameId`, "must match the declared coordinate frame.");
		if (component.unit !== firstUnit) fail(path, "must use one compatible velocity unit for every component.");
	}
	return components;
}
function parseStructuredTopology(value, dimension, path) {
	const item = record(value, path);
	exactKeys(item, [
		"kind",
		"dimension",
		"pointOrdering",
		"coordinates"
	], [], path);
	if (property(item, "kind") !== "rectilinear") fail(`${path}.kind`, "must be rectilinear.");
	if (property(item, "pointOrdering") !== "x-fastest") fail(`${path}.pointOrdering`, "must be x-fastest.");
	if (integer(property(item, "dimension"), `${path}.dimension`) !== dimension) fail(`${path}.dimension`, "must match the coordinate frame dimension.");
	const coordinatePath = `${path}.coordinates`;
	const coordinates = record(property(item, "coordinates"), coordinatePath);
	if (dimension === 2) {
		exactKeys(coordinates, ["x", "y"], [], coordinatePath);
		const x = numberArray(property(coordinates, "x"), `${coordinatePath}.x`);
		const y = numberArray(property(coordinates, "y"), `${coordinatePath}.y`);
		validateStrictMonotonic(x, `${coordinatePath}.x`);
		validateStrictMonotonic(y, `${coordinatePath}.y`);
		return {
			kind: "rectilinear",
			dimension: 2,
			pointOrdering: "x-fastest",
			coordinates: {
				x,
				y
			}
		};
	}
	exactKeys(coordinates, [
		"x",
		"y",
		"z"
	], [], coordinatePath);
	const x = numberArray(property(coordinates, "x"), `${coordinatePath}.x`);
	const y = numberArray(property(coordinates, "y"), `${coordinatePath}.y`);
	const z = numberArray(property(coordinates, "z"), `${coordinatePath}.z`);
	validateStrictMonotonic(x, `${coordinatePath}.x`);
	validateStrictMonotonic(y, `${coordinatePath}.y`);
	validateStrictMonotonic(z, `${coordinatePath}.z`);
	return {
		kind: "rectilinear",
		dimension: 3,
		pointOrdering: "x-fastest",
		coordinates: {
			x,
			y,
			z
		}
	};
}
function parseCellType(value, path) {
	if (value === "vertex" || value === "line" || value === "triangle" || value === "quad" || value === "tetrahedron" || value === "hexahedron" || value === "wedge" || value === "pyramid") return value;
	return fail(path, "is not a supported unstructured cell type.");
}
function parseUnstructuredTopology(value, dimension, path) {
	const item = record(value, path);
	exactKeys(item, [
		"kind",
		"dimension",
		"points",
		"cells"
	], [], path);
	if (property(item, "kind") !== "unstructured") fail(`${path}.kind`, "must be unstructured.");
	if (integer(property(item, "dimension"), `${path}.dimension`) !== dimension) fail(`${path}.dimension`, "must match the coordinate frame dimension.");
	const points = numberArray(property(item, "points"), `${path}.points`);
	if (points.length === 0 || points.length % dimension !== 0) fail(`${path}.points`, "must contain complete flattened coordinates for every point.");
	const pointCount = points.length / dimension;
	const cells = array(property(item, "cells"), `${path}.cells`).map((entry, index) => {
		const itemPath = `${path}.cells[${index}]`;
		const cell = record(entry, itemPath);
		exactKeys(cell, ["type", "pointIndices"], [], itemPath);
		const type = parseCellType(property(cell, "type"), `${itemPath}.type`);
		if (dimension === 2 && type !== "vertex" && type !== "line" && type !== "triangle" && type !== "quad") fail(`${itemPath}.type`, "is not compatible with a two-dimensional topology.");
		const pointIndices = integerArray(property(cell, "pointIndices"), `${itemPath}.pointIndices`);
		if (pointIndices.length !== CELL_ARITY[type]) fail(`${itemPath}.pointIndices`, `must contain ${CELL_ARITY[type]} indices for ${type}.`);
		if (new Set(pointIndices).size !== pointIndices.length) fail(`${itemPath}.pointIndices`, "must not repeat a point index.");
		if (pointIndices.some((pointIndex) => pointIndex >= pointCount)) fail(`${itemPath}.pointIndices`, "contains an out-of-range point index.");
		return {
			type,
			pointIndices
		};
	});
	if (cells.length === 0) fail(`${path}.cells`, "must contain at least one cell.");
	return dimension === 2 ? {
		kind: "unstructured",
		dimension: 2,
		points,
		cells
	} : {
		kind: "unstructured",
		dimension: 3,
		points,
		cells
	};
}
function parseSampling(value, path) {
	const item = record(value, path);
	const kind = property(item, "kind");
	if (kind === "instantaneous") {
		exactKeys(item, ["kind"], [], path);
		return { kind: "instantaneous" };
	}
	if (kind === "steady-state") {
		exactKeys(item, ["kind"], [], path);
		return { kind: "steady-state" };
	}
	if (kind === "frame-average") {
		exactKeys(item, ["kind", "exposureDuration"], ["exposureOperator", "timestampAnchor"], path);
		const hasExposureOperator = Object.prototype.hasOwnProperty.call(item, "exposureOperator");
		const hasTimestampAnchor = Object.prototype.hasOwnProperty.call(item, "timestampAnchor");
		if (hasExposureOperator !== hasTimestampAnchor) fail(path, "must declare exposureOperator and timestampAnchor together or omit both only for a legacy frame-average document.");
		const sampling = {
			kind: "frame-average",
			exposureDuration: positiveNumber(property(item, "exposureDuration"), `${path}.exposureDuration`)
		};
		if (hasExposureOperator && hasTimestampAnchor) {
			const exposureOperator = property(item, "exposureOperator");
			if (exposureOperator !== "uniform-window-average" && exposureOperator !== "unspecified") fail(`${path}.exposureOperator`, "must be uniform-window-average or unspecified.");
			const timestampAnchor = property(item, "timestampAnchor");
			if (timestampAnchor !== "start" && timestampAnchor !== "midpoint" && timestampAnchor !== "end" && timestampAnchor !== "unspecified") fail(`${path}.timestampAnchor`, "must be start, midpoint, end, or unspecified.");
			sampling.exposureOperator = exposureOperator;
			sampling.timestampAnchor = timestampAnchor;
		}
		return sampling;
	}
	return fail(`${path}.kind`, "must be instantaneous, steady-state, or frame-average.");
}
function parseCycle(value, path) {
	if (value === null) return null;
	const item = record(value, path);
	exactKeys(item, [
		"startTime",
		"endTime",
		"period",
		"phaseOrigin"
	], [], path);
	const startTime = finiteNumber(property(item, "startTime"), `${path}.startTime`);
	const endTime = finiteNumber(property(item, "endTime"), `${path}.endTime`);
	const period = positiveNumber(property(item, "period"), `${path}.period`);
	const phaseOrigin = finiteNumber(property(item, "phaseOrigin"), `${path}.phaseOrigin`);
	if (endTime <= startTime) fail(path, "must have an end time greater than its start time.");
	return {
		startTime,
		endTime,
		period,
		phaseOrigin
	};
}
function parseTemporal(value, kind, path) {
	const item = record(value, path);
	const temporalKind = property(item, "kind");
	if (kind === "structured-vector-field" || kind === "unstructured-vector-field") {
		exactKeys(item, [
			"kind",
			"timestampUnit",
			"sampling"
		], [], path);
		if (temporalKind !== "single-frame") fail(`${path}.kind`, "must be single-frame for a vector field.");
		return {
			kind: "single-frame",
			timestampUnit: parseTimeUnit(property(item, "timestampUnit"), `${path}.timestampUnit`),
			sampling: parseSampling(property(item, "sampling"), `${path}.sampling`)
		};
	}
	exactKeys(item, [
		"kind",
		"timestampUnit",
		"sampling",
		"nominalCadence",
		"cycle"
	], [], path);
	if (temporalKind !== "time-series") fail(`${path}.kind`, "must be time-series for a vector time series.");
	const sampling = parseSampling(property(item, "sampling"), `${path}.sampling`);
	if (sampling.kind === "steady-state") fail(`${path}.sampling.kind`, "steady-state sampling is valid only for a single-frame vector field.");
	return {
		kind: "time-series",
		timestampUnit: parseTimeUnit(property(item, "timestampUnit"), `${path}.timestampUnit`),
		sampling,
		nominalCadence: positiveNumber(property(item, "nominalCadence"), `${path}.nominalCadence`),
		cycle: parseCycle(property(item, "cycle"), `${path}.cycle`)
	};
}
function parseFrames(value, pointCount, componentCount, path) {
	return array(value, path).map((entry, index) => {
		const itemPath = `${path}[${index}]`;
		const item = record(entry, itemPath);
		exactKeys(item, [
			"timestamp",
			"values",
			"validMask"
		], [], itemPath);
		const values = numberArray(property(item, "values"), `${itemPath}.values`);
		const validMask = booleanArray(property(item, "validMask"), `${itemPath}.validMask`);
		if (values.length !== pointCount * componentCount) fail(`${itemPath}.values`, "length must equal point count times component count.");
		if (validMask.length !== pointCount) fail(`${itemPath}.validMask`, "length must equal point count.");
		return {
			timestamp: finiteNumber(property(item, "timestamp"), `${itemPath}.timestamp`),
			values,
			validMask
		};
	});
}
function parseSourceFormat(value, path) {
	if (value === "csv" || value === "mat" || value === "zip" || value === "video" || value === "vti" || value === "vtu" || value === "generated") return value;
	return fail(path, "must be csv, mat, zip, video, vti, vtu, or generated.");
}
function relativeSourcePath(value, path) {
	const parsed = text(value, path, 512);
	const segments = parsed.split("/");
	if (parsed.startsWith("/") || parsed.includes("\\") || /^[A-Za-z]:/u.test(parsed) || /^[A-Za-z][A-Za-z0-9+.-]*:/u.test(parsed) || segments.some((segment) => segment === "." || segment === ".." || segment.length === 0)) fail(path, "must be a normalized relative forward-slash path.");
	return parsed;
}
function parseProvenanceSource(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"path",
		"format",
		"byteLength",
		"sha256",
		"expectedSha256"
	], [], path);
	const actual = sha256(property(item, "sha256"), `${path}.sha256`);
	const expectedValue = property(item, "expectedSha256");
	const expected = expectedValue === null ? null : sha256(expectedValue, `${path}.expectedSha256`);
	if (expected !== null && expected !== actual) fail(`${path}.expectedSha256`, "does not match the actual source digest.");
	return {
		path: relativeSourcePath(property(item, "path"), `${path}.path`),
		format: parseSourceFormat(property(item, "format"), `${path}.format`),
		byteLength: nonnegativeInteger(property(item, "byteLength"), `${path}.byteLength`),
		sha256: actual,
		expectedSha256: expected
	};
}
function parseSoftware(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"name",
		"version",
		"sha256"
	], [], path);
	const digestValue = property(item, "sha256");
	return {
		name: text(property(item, "name"), `${path}.name`, 128),
		version: text(property(item, "version"), `${path}.version`, 128),
		sha256: digestValue === null ? null : sha256(digestValue, `${path}.sha256`)
	};
}
function parseProvenance(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"sourceKind",
		"citation",
		"license",
		"sources",
		"transformations",
		"software"
	], [], path);
	const sourceKind = property(item, "sourceKind");
	if (sourceKind !== "generated" && sourceKind !== "measured" && sourceKind !== "simulation") fail(`${path}.sourceKind`, "must be generated, measured, or simulation.");
	const sources = array(property(item, "sources"), `${path}.sources`).map((entry, index) => parseProvenanceSource(entry, `${path}.sources[${index}]`));
	if (sources.length === 0) fail(`${path}.sources`, "must contain at least one source record.");
	const software = array(property(item, "software"), `${path}.software`).map((entry, index) => parseSoftware(entry, `${path}.software[${index}]`));
	if (software.length === 0) fail(`${path}.software`, "must identify at least one software component.");
	return {
		sourceKind,
		citation: text(property(item, "citation"), `${path}.citation`),
		license: text(property(item, "license"), `${path}.license`, 256),
		sources,
		transformations: textArray(property(item, "transformations"), `${path}.transformations`),
		software
	};
}
function parseWall(value, pointCount, dimension, path) {
	if (value === null) return null;
	const item = record(value, path);
	exactKeys(item, ["dynamicViscosity", "method"], [], path);
	const viscosityPath = `${path}.dynamicViscosity`;
	const viscosity = record(property(item, "dynamicViscosity"), viscosityPath);
	exactKeys(viscosity, ["value", "unit"], [], viscosityPath);
	const methodPath = `${path}.method`;
	const method = record(property(item, "method"), methodPath);
	exactKeys(method, [
		"kind",
		"wallPointIndices",
		"nearWallPointIndices",
		"normals",
		"normalDirection",
		"boundaryCondition",
		"maximumTangentialOffsetFraction",
		"maximumWallSpeed",
		"wallSpeedUnit"
	], [], methodPath);
	if (property(method, "kind") !== "point-pair-first-order") fail(`${methodPath}.kind`, "must be point-pair-first-order.");
	if (property(method, "normalDirection") !== "into-fluid") fail(`${methodPath}.normalDirection`, "must be into-fluid.");
	if (property(method, "boundaryCondition") !== "stationary-no-slip") fail(`${methodPath}.boundaryCondition`, "must be stationary-no-slip for the reviewed method.");
	const wallPointIndices = integerArray(property(method, "wallPointIndices"), `${methodPath}.wallPointIndices`);
	const nearWallPointIndices = integerArray(property(method, "nearWallPointIndices"), `${methodPath}.nearWallPointIndices`);
	const normals = numberArray(property(method, "normals"), `${methodPath}.normals`);
	if (wallPointIndices.length === 0 || nearWallPointIndices.length !== wallPointIndices.length || normals.length !== wallPointIndices.length * dimension) fail(methodPath, "wall points, near-wall points, and normals must describe the same nonempty set of pairs.");
	if (new Set(wallPointIndices).size !== wallPointIndices.length || new Set(nearWallPointIndices).size !== nearWallPointIndices.length) fail(methodPath, "wall and near-wall point indices must each be unique.");
	for (let index = 0; index < wallPointIndices.length; index += 1) {
		if (wallPointIndices[index] >= pointCount || nearWallPointIndices[index] >= pointCount) fail(methodPath, "contains an out-of-range point index.");
		if (wallPointIndices[index] === nearWallPointIndices[index]) fail(methodPath, "wall and near-wall indices must differ.");
		let normalSquare = 0;
		for (let axis = 0; axis < dimension; axis += 1) {
			const component = normals[index * dimension + axis];
			normalSquare += component * component;
		}
		if (Math.abs(Math.sqrt(normalSquare) - 1) > UNIT_NORMAL_TOLERANCE) fail(`${methodPath}.normals`, "must contain unit normals in coordinate-frame component order.");
	}
	return {
		dynamicViscosity: {
			value: positiveNumber(property(viscosity, "value"), `${viscosityPath}.value`),
			unit: parseDynamicViscosityUnit(property(viscosity, "unit"), `${viscosityPath}.unit`)
		},
		method: {
			kind: "point-pair-first-order",
			wallPointIndices,
			nearWallPointIndices,
			normals,
			normalDirection: "into-fluid",
			boundaryCondition: "stationary-no-slip",
			maximumTangentialOffsetFraction: boundedFraction(property(method, "maximumTangentialOffsetFraction"), `${methodPath}.maximumTangentialOffsetFraction`),
			maximumWallSpeed: nonnegativeNumber(property(method, "maximumWallSpeed"), `${methodPath}.maximumWallSpeed`),
			wallSpeedUnit: parseVelocityUnit(property(method, "wallSpeedUnit"), `${methodPath}.wallSpeedUnit`)
		}
	};
}
function validateWallGeometry(dataset, path) {
	if (dataset.wall === null) return;
	const { method } = dataset.wall;
	for (let pair = 0; pair < method.wallPointIndices.length; pair += 1) {
		const wallPoint = topologyPointCoordinates(dataset.topology, method.wallPointIndices[pair]);
		const nearWallPoint = topologyPointCoordinates(dataset.topology, method.nearWallPointIndices[pair]);
		const normal = method.normals.slice(pair * dataset.coordinateFrame.dimension, (pair + 1) * dataset.coordinateFrame.dimension);
		const delta = nearWallPoint.map((coordinate, axis) => coordinate - wallPoint[axis]);
		const normalDistance = delta.reduce((total, component, axis) => total + component * normal[axis], 0);
		if (normalDistance <= 0) fail(path, "near-wall points must lie along the declared into-fluid normal.");
		const tangentialSquare = delta.reduce((total, component, axis) => {
			const tangential = component - normalDistance * normal[axis];
			return total + tangential * tangential;
		}, 0);
		if (Math.sqrt(tangentialSquare) / Math.abs(normalDistance) > method.maximumTangentialOffsetFraction) fail(path, "a wall-to-near-wall pair exceeds its declared tangential-offset limit.");
	}
}
function validateFrameTimes(frames, temporal, path) {
	if (temporal.kind === "single-frame") {
		if (frames.length !== 1) fail(path, "a vector field must contain exactly one frame.");
		return;
	}
	if (frames.length < 2) fail(path, "a vector time series must contain at least two frames.");
	for (let index = 1; index < frames.length; index += 1) if (frames[index].timestamp <= frames[index - 1].timestamp) fail(path, "timestamps must be strictly increasing.");
}
function parseCanonicalVectorDataset(value) {
	const path = "dataset";
	const item = record(value, path);
	exactKeys(item, [
		"schemaVersion",
		"kind",
		"id",
		"title",
		"description",
		"coordinateFrame",
		"topology",
		"components",
		"temporal",
		"frames",
		"provenance",
		"wall"
	], [], path);
	if (property(item, "schemaVersion") !== 1) fail(`${path}.schemaVersion`, `must equal 1.`);
	const kind = parseKind(property(item, "kind"), `${path}.kind`);
	const coordinateFrame = parseCoordinateFrame(property(item, "coordinateFrame"), `${path}.coordinateFrame`);
	const topology = kind === "structured-vector-field" || kind === "structured-vector-time-series" ? parseStructuredTopology(property(item, "topology"), coordinateFrame.dimension, `${path}.topology`) : parseUnstructuredTopology(property(item, "topology"), coordinateFrame.dimension, `${path}.topology`);
	const components = parseComponents(property(item, "components"), coordinateFrame, `${path}.components`);
	const temporal = parseTemporal(property(item, "temporal"), kind, `${path}.temporal`);
	const frames = parseFrames(property(item, "frames"), topologyPointCount(topology), components.length, `${path}.frames`);
	validateFrameTimes(frames, temporal, `${path}.frames`);
	const base = {
		schemaVersion: 1,
		id: identifier(property(item, "id"), `${path}.id`),
		title: text(property(item, "title"), `${path}.title`, 256),
		description: text(property(item, "description"), `${path}.description`),
		coordinateFrame,
		components,
		provenance: parseProvenance(property(item, "provenance"), `${path}.provenance`),
		wall: parseWall(property(item, "wall"), topologyPointCount(topology), coordinateFrame.dimension, `${path}.wall`)
	};
	let dataset;
	if (kind === "structured-vector-field" && topology.kind === "rectilinear" && temporal.kind === "single-frame") dataset = {
		...base,
		kind,
		topology,
		temporal,
		frames: [frames[0]]
	};
	else if (kind === "structured-vector-time-series" && topology.kind === "rectilinear" && temporal.kind === "time-series") dataset = {
		...base,
		kind,
		topology,
		temporal,
		frames
	};
	else if (kind === "unstructured-vector-field" && topology.kind === "unstructured" && temporal.kind === "single-frame") dataset = {
		...base,
		kind,
		topology,
		temporal,
		frames: [frames[0]]
	};
	else if (kind === "unstructured-vector-time-series" && topology.kind === "unstructured" && temporal.kind === "time-series") dataset = {
		...base,
		kind,
		topology,
		temporal,
		frames
	};
	else return fail(path, "kind, topology, and temporal metadata do not describe the same dataset contract.");
	validateWallGeometry(dataset, `${path}.wall.method`);
	return dataset;
}
//#endregion
//#region tools/catalogResearch/catalogVectorCsv.ts
var XYUV_HEADER = Object.freeze([
	"x",
	"y",
	"u",
	"v"
]);
var XYUV_VALID_HEADER = Object.freeze([
	"x",
	"y",
	"u",
	"v",
	"valid"
]);
var TIME_XYUV_HEADER = Object.freeze([
	"time",
	"x",
	"y",
	"u",
	"v"
]);
var TIME_XYUV_VALID_HEADER = Object.freeze([
	"time",
	"x",
	"y",
	"u",
	"v",
	"valid"
]);
var MAXIMUM_COORDINATE_SIGNIFICANT_DIGITS = 64;
var MINIMUM_COORDINATE_EXPONENT = -400;
var MAXIMUM_COORDINATE_EXPONENT = 400;
Object.freeze([
	XYUV_HEADER,
	XYUV_VALID_HEADER,
	TIME_XYUV_HEADER,
	TIME_XYUV_VALID_HEADER
]);
var CATALOG_VECTOR_CSV_VALIDATOR_VERSION = "flowblind-catalog-vector-csv-v1";
var CATALOG_VECTOR_CSV_LIMITS = Object.freeze({
	maximumBytes: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumAttachmentBytesEach,
	maximumDataRows: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumDataRows,
	maximumDataFields: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumDataFields,
	maximumVectorFrames: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumVectorFrames,
	maximumVectorPointSamples: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumVectorPointSamples,
	maximumCharactersPerField: 4096,
	maximumCoordinateSignificantDigits: MAXIMUM_COORDINATE_SIGNIFICANT_DIGITS
});
var XYUV_LAYOUT = Object.freeze({
	header: XYUV_HEADER,
	columnCount: 4,
	hasTime: false,
	hasValidity: false,
	timeIndex: null,
	xIndex: 0,
	yIndex: 1,
	uIndex: 2,
	vIndex: 3,
	validIndex: null
});
var XYUV_VALID_LAYOUT = Object.freeze({
	header: XYUV_VALID_HEADER,
	columnCount: 5,
	hasTime: false,
	hasValidity: true,
	timeIndex: null,
	xIndex: 0,
	yIndex: 1,
	uIndex: 2,
	vIndex: 3,
	validIndex: 4
});
var TIME_XYUV_LAYOUT = Object.freeze({
	header: TIME_XYUV_HEADER,
	columnCount: 5,
	hasTime: true,
	hasValidity: false,
	timeIndex: 0,
	xIndex: 1,
	yIndex: 2,
	uIndex: 3,
	vIndex: 4,
	validIndex: null
});
var TIME_XYUV_VALID_LAYOUT = Object.freeze({
	header: TIME_XYUV_VALID_HEADER,
	columnCount: 6,
	hasTime: true,
	hasValidity: true,
	timeIndex: 0,
	xIndex: 1,
	yIndex: 2,
	uIndex: 3,
	vIndex: 4,
	validIndex: 5
});
var DECIMAL_PATTERN = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/u;
var SHA256 = /^[a-f0-9]{64}$/u;
function structureInvalid(detail, cause) {
	throw new CatalogResearchError("source-structure-invalid", "input-validation", detail, cause === void 0 ? void 0 : { cause });
}
function identityInvalid(cause) {
	throw new CatalogResearchError("source-identity-mismatch", "verification", "The vector CSV bytes do not match their immutable source identity.", cause === void 0 ? void 0 : { cause });
}
function checkedAdd(left, right) {
	if (!Number.isSafeInteger(left) || !Number.isSafeInteger(right) || left < 0 || right < 0 || left > Number.MAX_SAFE_INTEGER - right) structureInvalid("Vector CSV resource counts exceed safe integer arithmetic.");
	return left + right;
}
function checkedMultiply(left, right) {
	if (!Number.isSafeInteger(left) || !Number.isSafeInteger(right) || left < 0 || right < 0 || left !== 0 && right > Math.floor(Number.MAX_SAFE_INTEGER / left)) structureInvalid("Vector CSV resource counts exceed safe integer arithmetic.");
	return left * right;
}
function safeSourceReference(reference) {
	if (typeof reference !== "string" || reference.length === 0 || reference.length > 512 || reference.startsWith("/") || reference.includes("\\") || /^[A-Za-z]:/u.test(reference) || /^[A-Za-z][A-Za-z0-9+.-]*:/u.test(reference)) return false;
	if (reference.split("/").some((segment) => segment.length === 0 || segment === "." || segment === "..")) return false;
	for (const character of reference) {
		const code = character.codePointAt(0);
		if (code === 127 || code !== void 0 && code < 32) return false;
	}
	return true;
}
function validateSourceIdentity(source, bytes) {
	if (!safeSourceReference(source.reference) || !Number.isSafeInteger(source.byteLength) || source.byteLength < 0 || typeof source.sha256 !== "string" || !SHA256.test(source.sha256) || source.byteLength !== bytes.byteLength) identityInvalid();
	let digest;
	try {
		digest = createHash("sha256").update(bytes).digest("hex");
	} catch (error) {
		identityInvalid(error);
	}
	if (digest !== source.sha256) identityInvalid();
	return Object.freeze({
		reference: source.reference,
		byteLength: source.byteLength,
		sha256: source.sha256
	});
}
function strictUtf8(bytes) {
	if (bytes.byteLength >= 3 && bytes[0] === 239 && bytes[1] === 187 && bytes[2] === 191) structureInvalid("Vector CSV must use UTF-8 without a byte-order mark.");
	try {
		return new TextDecoder("utf-8", {
			fatal: true,
			ignoreBOM: true
		}).decode(bytes);
	} catch (error) {
		structureInvalid("Vector CSV must contain complete strict UTF-8.", error);
	}
}
function normalizedDecimal(coefficientInput, exponentInput, value) {
	let coefficient = coefficientInput;
	let exponent = exponentInput;
	if (coefficient === 0n) return {
		key: "0e0",
		value: 0
	};
	while (coefficient % 10n === 0n) {
		coefficient /= 10n;
		exponent += 1;
	}
	return {
		key: `${coefficient.toString()}e${exponent}`,
		value
	};
}
function invalidNumber(row, column) {
	structureInvalid(`Vector CSV data row ${row} column ${column} must contain a finite decimal number.`);
}
function parseFiniteDecimal(field, row, column) {
	if (!DECIMAL_PATTERN.test(field)) invalidNumber(row, column);
	const value = Number(field);
	if (!Number.isFinite(value)) invalidNumber(row, column);
	return Object.is(value, -0) ? 0 : value;
}
function parseCoordinate(field, row, column) {
	const match = DECIMAL_PATTERN.exec(field);
	if (match === null) invalidNumber(row, column);
	const value = Number(field);
	if (!Number.isFinite(value)) invalidNumber(row, column);
	const integerPart = match[2] ?? "0";
	const fractionalPart = match[2] === void 0 ? match[4] ?? "" : match[3] ?? "";
	const withoutLeadingZeroes = `${integerPart}${fractionalPart}`.replace(/^0+/u, "");
	if (withoutLeadingZeroes.length === 0) return normalizedDecimal(0n, 0, 0);
	const withoutTrailingZeroes = withoutLeadingZeroes.replace(/0+$/u, "");
	const trailingZeroes = withoutLeadingZeroes.length - withoutTrailingZeroes.length;
	if (withoutTrailingZeroes.length > MAXIMUM_COORDINATE_SIGNIFICANT_DIGITS) structureInvalid(`Vector CSV data row ${row} column ${column} exceeds the reviewed coordinate precision limit.`);
	let coefficient = BigInt(withoutTrailingZeroes);
	if (match[1] === "-") coefficient = -coefficient;
	if (value === 0) structureInvalid(`Vector CSV data row ${row} column ${column} is outside the supported finite coordinate range.`);
	const declaredExponent = Number(match[5] ?? "0");
	if (!Number.isSafeInteger(declaredExponent)) invalidNumber(row, column);
	const exponent = declaredExponent - fractionalPart.length + trailingZeroes;
	if (!Number.isSafeInteger(exponent) || exponent < MINIMUM_COORDINATE_EXPONENT || exponent > MAXIMUM_COORDINATE_EXPONENT) invalidNumber(row, column);
	return normalizedDecimal(coefficient, exponent, Object.is(value, -0) ? 0 : value);
}
function parseValidFlag(field, row) {
	if (field === "1") return true;
	if (field === "0") return false;
	structureInvalid(`Vector CSV data row ${row} column valid must be exactly 0 or 1.`);
}
function coordinatePairKey(x, y) {
	return `${x.key}|${y.key}`;
}
function headerLayout(record) {
	const text = record.join(",");
	if (text === "x,y,u,v") return XYUV_LAYOUT;
	if (text === "x,y,u,v,valid") return XYUV_VALID_LAYOUT;
	if (text === "time,x,y,u,v") return TIME_XYUV_LAYOUT;
	if (text === "time,x,y,u,v,valid") return TIME_XYUV_VALID_LAYOUT;
	structureInvalid("Vector CSV header must be exactly x,y,u,v; x,y,u,v,valid; time,x,y,u,v; or time,x,y,u,v,valid.");
}
function sameCoordinateGrid(left, right) {
	return left.length === right.length && left.every((coordinate, index) => coordinate.key === right[index]?.key);
}
var CatalogVectorCsvParser = class {
	field = "";
	fieldCharacters = 0;
	fields = [];
	recordTouched = false;
	pendingCarriageReturn = false;
	layout = null;
	dataRows = 0;
	dataFields = 0;
	startedFrames = 0;
	validPointSamples = 0;
	currentFrame = null;
	canonicalX = null;
	canonicalY = null;
	xNumberIdentities = /* @__PURE__ */ new Map();
	yNumberIdentities = /* @__PURE__ */ new Map();
	timeNumberIdentities = /* @__PURE__ */ new Map();
	timestamps = [];
	values = [];
	masks = [];
	write(text) {
		for (let index = 0; index < text.length; index += 1) this.writeCharacter(text[index]);
	}
	finish() {
		if (this.pendingCarriageReturn) structureInvalid("Vector CSV records must use LF or CRLF line endings.");
		if (this.recordTouched || this.fields.length > 0 || this.fieldCharacters > 0) {
			this.finishField();
			this.finishRecord();
		}
		if (this.layout === null) structureInvalid("Vector CSV must contain one reviewed exact header.");
		if (this.dataRows === 0) structureInvalid("Vector CSV must contain at least one data row.");
		this.finishCurrentFrame();
		const frameCount = this.timestamps.length;
		if (this.layout.hasTime && frameCount < 2) structureInvalid("Vector time-series CSV must contain at least two frames.");
		if (!this.layout.hasTime && frameCount !== 1) structureInvalid("Vector field CSV must contain exactly one frame.");
		const x = this.canonicalX;
		const y = this.canonicalY;
		if (x === null || y === null) structureInvalid("Vector CSV must contain one complete Cartesian grid.");
		const pointCount = checkedMultiply(x.length, y.length);
		if (checkedMultiply(pointCount, frameCount) !== this.dataRows || this.startedFrames !== frameCount) structureInvalid("Vector CSV frames must share one complete Cartesian grid.");
		return {
			header: this.layout.header,
			structure: {
				dataRows: this.dataRows,
				pointCount,
				frameCount,
				width: x.length,
				height: y.length,
				validPointSamples: this.validPointSamples,
				hasValidityColumn: this.layout.hasValidity,
				completeCartesianGrid: true,
				sharedCoordinatesAcrossFrames: true
			},
			axes: {
				x: Object.freeze(x.map((coordinate) => coordinate.value)),
				y: Object.freeze(y.map((coordinate) => coordinate.value))
			},
			timestamps: Object.freeze([...this.timestamps]),
			values: Object.freeze([...this.values]),
			masks: Object.freeze([...this.masks]),
			isTimeSeries: this.layout.hasTime
		};
	}
	writeCharacter(character) {
		if (this.pendingCarriageReturn) {
			if (character !== "\n") structureInvalid("Vector CSV records must use LF or CRLF line endings.");
			this.pendingCarriageReturn = false;
			this.finishRecord();
			return;
		}
		if (character === "\"") structureInvalid("Vector CSV quoted fields are not supported by the reviewed canonical parser.");
		if (character === ",") this.finishDelimitedField();
		else if (character === "\n") {
			this.finishField();
			this.finishRecord();
		} else if (character === "\r") {
			this.finishField();
			this.pendingCarriageReturn = true;
		} else this.appendCharacter(character);
	}
	appendCharacter(character) {
		if (character === "\0") structureInvalid("Vector CSV fields must not contain NUL.");
		if (this.fieldCharacters + 1 > CATALOG_VECTOR_CSV_LIMITS.maximumCharactersPerField) structureInvalid(`Vector CSV fields must not exceed ${CATALOG_VECTOR_CSV_LIMITS.maximumCharactersPerField} characters.`);
		this.fieldCharacters += 1;
		this.field += character;
		this.recordTouched = true;
	}
	finishDelimitedField() {
		const maximumColumns = this.layout?.columnCount ?? 6;
		if (this.fields.length >= maximumColumns - 1) structureInvalid(`Vector CSV records must contain exactly ${maximumColumns} columns.`);
		this.finishField();
		this.recordTouched = true;
	}
	finishField() {
		const maximumColumns = this.layout?.columnCount ?? 6;
		if (this.fields.length >= maximumColumns) structureInvalid(`Vector CSV records must contain exactly ${maximumColumns} columns.`);
		this.fields.push(this.field);
		this.field = "";
		this.fieldCharacters = 0;
	}
	finishRecord() {
		const record = this.fields;
		if (this.layout === null) this.layout = headerLayout(record);
		else {
			if (record.length === 1 && record[0] === "") structureInvalid("Vector CSV must not contain blank rows.");
			this.finishDataRecord(record, this.layout);
		}
		this.fields = [];
		this.recordTouched = false;
	}
	finishDataRecord(record, layout) {
		if (record.length !== layout.columnCount) structureInvalid(`Vector CSV records must contain exactly ${layout.columnCount} columns.`);
		const nextRowCount = checkedAdd(this.dataRows, 1);
		const nextFieldCount = checkedAdd(this.dataFields, record.length);
		const rowOverflow = nextRowCount > CATALOG_VECTOR_CSV_LIMITS.maximumDataRows;
		const pointOverflow = nextRowCount > CATALOG_VECTOR_CSV_LIMITS.maximumVectorPointSamples;
		const fieldOverflow = nextFieldCount > CATALOG_VECTOR_CSV_LIMITS.maximumDataFields;
		if (rowOverflow || pointOverflow || fieldOverflow) structureInvalid(`Vector CSV exceeds the ${[
			rowOverflow ? `${CATALOG_VECTOR_CSV_LIMITS.maximumDataRows} data rows` : "",
			pointOverflow ? `${CATALOG_VECTOR_CSV_LIMITS.maximumVectorPointSamples} point samples` : "",
			fieldOverflow ? `${CATALOG_VECTOR_CSV_LIMITS.maximumDataFields} data fields` : ""
		].filter((resource) => resource.length > 0).join(" and ")} limit.`);
		const timestamp = layout.timeIndex === null ? {
			key: "0e0",
			value: 0
		} : parseCoordinate(record[layout.timeIndex], nextRowCount, "time");
		const x = parseCoordinate(record[layout.xIndex], nextRowCount, "x");
		const y = parseCoordinate(record[layout.yIndex], nextRowCount, "y");
		const u = parseFiniteDecimal(record[layout.uIndex], nextRowCount, "u");
		const v = parseFiniteDecimal(record[layout.vIndex], nextRowCount, "v");
		const valid = layout.validIndex === null ? true : parseValidFlag(record[layout.validIndex], nextRowCount);
		if (layout.hasTime) this.assertNumericIdentity(this.timeNumberIdentities, timestamp, nextRowCount, "time");
		this.selectFrame(timestamp);
		this.assertNumericIdentity(this.xNumberIdentities, x, nextRowCount, "x");
		this.assertNumericIdentity(this.yNumberIdentities, y, nextRowCount, "y");
		const frame = this.currentFrame;
		if (frame === null) structureInvalid("Vector CSV frame construction failed.");
		const pairKey = coordinatePairKey(x, y);
		if (frame.rows.has(pairKey)) structureInvalid(`Vector CSV data row ${nextRowCount} repeats a coordinate row within one frame.`);
		frame.xCoordinates.set(x.key, x);
		frame.yCoordinates.set(y.key, y);
		frame.rows.set(pairKey, {
			u,
			v,
			valid
		});
		this.dataRows = nextRowCount;
		this.dataFields = nextFieldCount;
		if (valid) this.validPointSamples = checkedAdd(this.validPointSamples, 1);
	}
	selectFrame(timestamp) {
		if (this.currentFrame === null) {
			this.startFrame(timestamp);
			return;
		}
		if (timestamp.key === this.currentFrame.timestamp.key) return;
		if (timestamp.value <= this.currentFrame.timestamp.value) structureInvalid("Vector CSV frame timestamps must be strictly increasing without duplicates.");
		this.finishCurrentFrame();
		this.startFrame(timestamp);
	}
	startFrame(timestamp) {
		const nextFrameCount = checkedAdd(this.startedFrames, 1);
		if (nextFrameCount > CATALOG_VECTOR_CSV_LIMITS.maximumVectorFrames) structureInvalid(`Vector CSV exceeds the ${CATALOG_VECTOR_CSV_LIMITS.maximumVectorFrames} frame limit.`);
		this.startedFrames = nextFrameCount;
		this.currentFrame = {
			timestamp,
			xCoordinates: /* @__PURE__ */ new Map(),
			yCoordinates: /* @__PURE__ */ new Map(),
			rows: /* @__PURE__ */ new Map()
		};
	}
	finishCurrentFrame() {
		const frame = this.currentFrame;
		if (frame === null) return;
		const x = [...frame.xCoordinates.values()].sort((left, right) => left.value - right.value);
		const y = [...frame.yCoordinates.values()].sort((left, right) => left.value - right.value);
		const expectedRows = checkedMultiply(x.length, y.length);
		if (expectedRows === 0 || frame.rows.size !== expectedRows) structureInvalid("Every vector CSV frame must contain one complete Cartesian product of x and y coordinates.");
		if (this.canonicalX === null || this.canonicalY === null) {
			this.canonicalX = Object.freeze(x);
			this.canonicalY = Object.freeze(y);
		} else if (!sameCoordinateGrid(this.canonicalX, x) || !sameCoordinateGrid(this.canonicalY, y)) structureInvalid("Vector CSV coordinate grids must be identical across all frames.");
		for (const yCoordinate of y) for (const xCoordinate of x) {
			const point = frame.rows.get(coordinatePairKey(xCoordinate, yCoordinate));
			if (point === void 0) structureInvalid("Every vector CSV frame must contain one complete Cartesian product of x and y coordinates.");
			this.values.push(point.u, point.v);
			this.masks.push(point.valid);
		}
		this.timestamps.push(frame.timestamp.value);
		this.currentFrame = null;
	}
	assertNumericIdentity(identities, coordinate, row, column) {
		const existing = identities.get(coordinate.value);
		if (existing !== void 0 && existing !== coordinate.key) structureInvalid(`Vector CSV data row ${row} column ${column} cannot be represented as a distinct finite coordinate.`);
		identities.set(coordinate.value, coordinate.key);
	}
};
function validateResourceBytes(bytes) {
	if (bytes.byteLength > CATALOG_VECTOR_CSV_LIMITS.maximumBytes) structureInvalid(`Vector CSV must not exceed ${CATALOG_VECTOR_CSV_LIMITS.maximumBytes} bytes.`);
}
async function validateCatalogVectorCsvBytesCancellable(request) {
	throwIfCatalogAborted(request.signal);
	validateResourceBytes(request.bytes);
	const source = validateSourceIdentity(request.source, request.bytes);
	throwIfCatalogAborted(request.signal);
	const text = strictUtf8(request.bytes);
	const parser = new CatalogVectorCsvParser();
	const chunkCharacters = 65536;
	for (let offset = 0; offset < text.length; offset += chunkCharacters) {
		parser.write(text.slice(offset, offset + chunkCharacters));
		await setImmediate();
		throwIfCatalogAborted(request.signal);
	}
	const parsed = parser.finish();
	throwIfCatalogAborted(request.signal);
	return validatedCatalogVectorCsv(source, parsed);
}
function validatedCatalogVectorCsv(source, parsed) {
	return Object.freeze({
		source,
		parser: Object.freeze({
			version: CATALOG_VECTOR_CSV_VALIDATOR_VERSION,
			encoding: "utf-8",
			header: parsed.header
		}),
		structure: Object.freeze(parsed.structure),
		axes: Object.freeze(parsed.axes),
		timestamps: parsed.timestamps,
		valueOrder: "frame-major-y-major-x-minor-interleaved-uv",
		values: parsed.values,
		maskOrder: "frame-major-y-major-x-minor",
		masks: parsed.masks,
		isTimeSeries: parsed.isTimeSeries
	});
}
function enumValue(value, allowed, label) {
	for (const candidate of allowed) if (value === candidate) return candidate;
	structureInvalid(`${label} must use one reviewed value.`);
}
function optionalFinite(value, label) {
	if (value === void 0 || value === null) return null;
	if (typeof value !== "number" || !Number.isFinite(value)) structureInvalid(`${label} must be a finite number.`);
	return Object.is(value, -0) ? 0 : value;
}
function normalizeCycle(value) {
	if (value === void 0 || value === null) return null;
	if (typeof value !== "object" || Array.isArray(value)) structureInvalid("Complete-cycle metadata must be one complete object.");
	const cycle = value;
	const startTime = optionalFinite(cycle.startTime, "Complete-cycle start time");
	const endTime = optionalFinite(cycle.endTime, "Complete-cycle end time");
	const period = optionalFinite(cycle.period, "Complete-cycle period");
	const phaseOrigin = optionalFinite(cycle.phaseOrigin, "Complete-cycle phase origin");
	if (startTime === null || endTime === null || period === null || phaseOrigin === null || endTime <= startTime || period <= 0) structureInvalid("Complete-cycle metadata requires finite start, end, period, and phase origin values with end after start and positive period.");
	return {
		startTime,
		endTime,
		period,
		phaseOrigin
	};
}
function normalizeMetadata(metadata) {
	const direct = "sourceKind" in metadata;
	return {
		title: direct ? metadata.title : metadata.quantity,
		meaning: direct ? metadata.meaning : metadata.vectorMeaning,
		sourceKind: enumValue(direct ? metadata.sourceKind : metadata.vectorSourceKind, [
			"generated",
			"measured",
			"simulation"
		], "Vector source kind"),
		coordinateUnit: enumValue(metadata.coordinateUnit, [
			"m",
			"cm",
			"mm"
		], "Coordinate unit"),
		velocityUnit: enumValue(direct ? metadata.velocityUnit : metadata.valueUnit, [
			"m/s",
			"cm/s",
			"mm/s"
		], "Velocity unit"),
		timeUnit: enumValue(metadata.timeUnit, ["s", "ms"], "Time unit"),
		samplingKind: enumValue(metadata.samplingKind, [
			"instantaneous",
			"steady-state",
			"frame-average"
		], "Sampling kind"),
		exposureDuration: optionalFinite(metadata.exposureDuration, "Exposure duration"),
		exposureOperator: metadata.exposureOperator ?? null,
		timestampAnchor: metadata.timestampAnchor ?? null,
		provenance: metadata.provenance,
		licence: direct ? metadata.licence : metadata.license,
		selectedTime: optionalFinite(metadata.selectedTime, "Selected time"),
		completeCycle: normalizeCycle(direct ? metadata.completeCycle : metadata.cycle)
	};
}
function validatedSampling(metadata) {
	const hasOperator = metadata.exposureOperator !== null;
	const hasAnchor = metadata.timestampAnchor !== null;
	if (hasOperator !== hasAnchor) structureInvalid("Frame-average exposure operator and timestamp anchor must be supplied together or both omitted.");
	if (metadata.samplingKind === "frame-average") {
		if (metadata.exposureDuration === null || metadata.exposureDuration <= 0) structureInvalid("Frame-average sampling requires a positive exposure duration.");
		if (metadata.exposureOperator !== null && metadata.timestampAnchor !== null) return {
			kind: "frame-average",
			exposureDuration: metadata.exposureDuration,
			exposureOperator: metadata.exposureOperator,
			timestampAnchor: metadata.timestampAnchor
		};
		return {
			kind: "frame-average",
			exposureDuration: metadata.exposureDuration
		};
	}
	if (metadata.exposureDuration !== null || hasOperator || hasAnchor) structureInvalid("Exposure metadata is supported only for frame-average sampling.");
	return { kind: metadata.samplingKind };
}
function assertFiniteIncreasing(values, label) {
	for (let index = 0; index < values.length; index += 1) {
		const value = values[index];
		if (value === void 0 || !Number.isFinite(value) || index > 0 && value <= values[index - 1]) structureInvalid(`${label} must contain finite strictly increasing values.`);
	}
}
function assertValidatedCsv(validated) {
	if ("bytes" in validated.source || !safeSourceReference(validated.source.reference) || !Number.isSafeInteger(validated.source.byteLength) || validated.source.byteLength <= 0 || validated.source.byteLength > CATALOG_VECTOR_CSV_LIMITS.maximumBytes || !SHA256.test(validated.source.sha256)) identityInvalid();
	const layout = headerLayout(validated.parser.header);
	if (validated.parser.version !== "flowblind-catalog-vector-csv-v1" || validated.parser.encoding !== "utf-8" || validated.isTimeSeries !== layout.hasTime || validated.structure.hasValidityColumn !== layout.hasValidity || validated.structure.completeCartesianGrid !== true || validated.structure.sharedCoordinatesAcrossFrames !== true) structureInvalid("Validated vector CSV parser metadata is inconsistent.");
	if ([
		validated.structure.dataRows,
		validated.structure.pointCount,
		validated.structure.frameCount,
		validated.structure.width,
		validated.structure.height,
		validated.structure.validPointSamples
	].some((value) => !Number.isSafeInteger(value) || value < 0) || validated.structure.dataRows < 1 || validated.structure.pointCount < 1 || validated.structure.frameCount < 1 || validated.structure.width < 1 || validated.structure.height < 1 || validated.structure.dataRows > CATALOG_VECTOR_CSV_LIMITS.maximumDataRows || validated.structure.dataRows > CATALOG_VECTOR_CSV_LIMITS.maximumVectorPointSamples || validated.structure.frameCount > CATALOG_VECTOR_CSV_LIMITS.maximumVectorFrames) structureInvalid("Validated vector CSV resource counts are invalid.");
	const pointCount = checkedMultiply(validated.structure.width, validated.structure.height);
	const dataRows = checkedMultiply(pointCount, validated.structure.frameCount);
	const dataFields = checkedMultiply(dataRows, layout.columnCount);
	const valueCount = checkedMultiply(dataRows, 2);
	if (pointCount !== validated.structure.pointCount || dataRows !== validated.structure.dataRows || dataFields > CATALOG_VECTOR_CSV_LIMITS.maximumDataFields || validated.axes.x.length !== validated.structure.width || validated.axes.y.length !== validated.structure.height || validated.timestamps.length !== validated.structure.frameCount || validated.values.length !== valueCount || validated.masks.length !== dataRows) structureInvalid("Validated vector CSV arrays do not match their declared structure.");
	assertFiniteIncreasing(validated.axes.x, "Validated vector CSV x coordinates");
	assertFiniteIncreasing(validated.axes.y, "Validated vector CSV y coordinates");
	if (layout.hasTime) {
		if (validated.timestamps.length < 2) structureInvalid("Validated vector time series must contain at least two frames.");
		assertFiniteIncreasing(validated.timestamps, "Validated vector CSV timestamps");
	} else if (validated.timestamps.length !== 1 || validated.timestamps[0] !== 0) structureInvalid("Validated single-frame vector CSV timestamp must be zero.");
	if (validated.values.some((value) => !Number.isFinite(value)) || validated.masks.some((value) => typeof value !== "boolean")) structureInvalid("Validated vector CSV values and masks are invalid.");
	const validPointSamples = validated.masks.reduce((count, valid) => count + (valid ? 1 : 0), 0);
	if (validPointSamples !== validated.structure.validPointSamples || !layout.hasValidity && validPointSamples !== dataRows) structureInvalid("Validated vector CSV validity masks are inconsistent.");
	return layout;
}
function catalogVectorDataset(validated, metadataInput) {
	const layout = assertValidatedCsv(validated);
	const metadata = normalizeMetadata(metadataInput);
	const sampling = validatedSampling(metadata);
	if (layout.hasTime && sampling.kind === "steady-state") structureInvalid("Steady-state sampling is valid only for a single-frame vector field.");
	if (!layout.hasTime && metadata.selectedTime !== null && metadata.selectedTime !== 0) structureInvalid("A single-frame vector field may select only timestamp 0.");
	if (!layout.hasTime && metadata.completeCycle !== null) structureInvalid("Complete-cycle metadata is supported only for a vector time series.");
	const frames = validated.timestamps.map((timestamp, frameIndex) => {
		const pointOffset = checkedMultiply(frameIndex, validated.structure.pointCount);
		const valueOffset = checkedMultiply(pointOffset, 2);
		return {
			timestamp,
			values: validated.values.slice(valueOffset, valueOffset + checkedMultiply(validated.structure.pointCount, 2)),
			validMask: validated.masks.slice(pointOffset, pointOffset + validated.structure.pointCount)
		};
	});
	const datasetId = `attached-vector-${validated.source.sha256.slice(0, 32)}`;
	const frameId = `attached-vector-frame-${validated.source.sha256.slice(0, 24)}`;
	const temporal = layout.hasTime ? {
		kind: "time-series",
		timestampUnit: metadata.timeUnit,
		sampling,
		nominalCadence: validated.timestamps[1] - validated.timestamps[0],
		cycle: metadata.completeCycle
	} : {
		kind: "single-frame",
		timestampUnit: metadata.timeUnit,
		sampling
	};
	if (temporal.kind === "time-series" && (!Number.isFinite(temporal.nominalCadence) || temporal.nominalCadence <= 0)) structureInvalid("The first positive timestamp interval must define a finite nominal cadence.");
	try {
		return parseCanonicalVectorDataset({
			schemaVersion: 1,
			kind: layout.hasTime ? "structured-vector-time-series" : "structured-vector-field",
			id: datasetId,
			title: metadata.title,
			description: metadata.meaning,
			coordinateFrame: {
				id: frameId,
				type: "cartesian",
				dimension: 2,
				handedness: "unspecified",
				axisNames: ["x", "y"],
				lengthUnit: metadata.coordinateUnit
			},
			topology: {
				kind: "rectilinear",
				dimension: 2,
				pointOrdering: "x-fastest",
				coordinates: validated.axes
			},
			components: [{
				name: "u",
				axis: "x",
				frameId,
				unit: metadata.velocityUnit
			}, {
				name: "v",
				axis: "y",
				frameId,
				unit: metadata.velocityUnit
			}],
			temporal,
			frames,
			provenance: {
				sourceKind: metadata.sourceKind,
				citation: metadata.provenance,
				license: metadata.licence,
				sources: [{
					path: validated.source.reference,
					format: "csv",
					byteLength: validated.source.byteLength,
					sha256: validated.source.sha256,
					expectedSha256: validated.source.sha256
				}],
				transformations: ["Strictly parsed the reviewed CSV columns and reordered each complete rectilinear frame into x-fastest order without interpolation."],
				software: [{
					name: "FlowBlind catalog vector CSV intake",
					version: CATALOG_VECTOR_CSV_VALIDATOR_VERSION,
					sha256: null
				}]
			},
			wall: null
		});
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		structureInvalid("Vector CSV scientist metadata cannot be projected into the canonical vector dataset contract.", error);
	}
}
//#endregion
//#region tools/catalogResearch/catalogVectorStudy.ts
function vectorScenario(candidate, dataset, metadata) {
	const firstTime = dataset.frames[0].timestamp;
	const nominalCadence = dataset.temporal.kind === "time-series" ? dataset.temporal.nominalCadence : null;
	return parseVectorAuditScenario({
		schemaVersion: 1,
		id: `vector-readiness-${candidate.sha256.slice(0, 32)}`,
		title: "Structured planar vector/time readiness audit",
		selectedTime: metadata.selectedTime ?? firstTime,
		gates: {
			minimumSpeedPointCoverage: .6,
			minimumDerivativeStencilCoverage: .5,
			maximumInterpolationGap: nominalCadence === null ? 1 : nominalCadence * 1.000002,
			minimumFrameSummaryCoverage: 1,
			minimumWallPairCoverage: 1,
			cycle: dataset.temporal.kind === "time-series" && dataset.temporal.cycle !== null ? {
				minimumIntervals: 20,
				maximumGapFractionOfPeriod: .0500001,
				maximumCadenceDeviationFraction: 1e-9,
				endpointToleranceFraction: 1e-9
			} : null
		}
	});
}
function canonicalSource(validated, dataset, scenario, metadata) {
	return {
		datasetId: dataset.id,
		parser: validated.parser,
		structure: validated.structure,
		geometry: {
			topology: "complete-rectilinear-grid",
			coordinateDimensions: 2,
			coordinateUnit: metadata.coordinateUnit,
			areaSemantics: "planar-cartesian-no-wall-evidence"
		},
		temporalSampling: {
			kind: dataset.temporal.kind,
			timeUnit: metadata.timeUnit,
			samplingKind: metadata.samplingKind,
			selectedTime: scenario.selectedTime,
			nominalCadence: dataset.temporal.kind === "time-series" ? dataset.temporal.nominalCadence : null,
			exposureDuration: metadata.exposureDuration,
			exposureOperator: metadata.exposureOperator,
			timestampAnchor: metadata.timestampAnchor,
			cycle: metadata.cycle
		}
	};
}
async function prepareCatalogVectorStudy(humanContext, intent, candidate, trustedSidecar, software, signal) {
	if (intent.capability.capabilityId !== "vector-time-readiness-audit-v1") throw new CatalogResearchError("source-structure-invalid", "input-validation", "The selected capability does not use the vector/time readiness preparation contract.");
	const canonicalCandidate = {
		...candidate,
		reference: basename(candidate.reference)
	};
	const validatedCandidate = await validateCatalogVectorCsvBytesCancellable({
		source: canonicalCandidate,
		bytes: canonicalCandidate.bytes,
		signal
	});
	const dataset = catalogVectorDataset(validatedCandidate, trustedSidecar.declarations);
	const scenario = vectorScenario(canonicalCandidate, dataset, trustedSidecar.declarations);
	const sourceProjection = canonicalSource(validatedCandidate, dataset, scenario, trustedSidecar.declarations);
	const candidateIdentity = artifactIdentity(canonicalCandidate.reference, canonicalCandidate.bytes);
	const sidecarIdentity = {
		...trustedSidecar.identity,
		schemaId: trustedSidecar.schemaId
	};
	const protocolBytes = utf8Bytes(stableJson$1(scenario));
	const protocolIdentity = artifactIdentity("vector-readiness-protocol.json", protocolBytes);
	const freezeBindings = {
		schemaVersion: 1,
		capabilityId: "vector-time-readiness-audit-v1",
		protocolPresetId: FLOWBLIND_CATALOG_VECTOR_PROTOCOL_PRESET_ID,
		sourceArtifact: candidateIdentity,
		sidecarArtifact: trustedSidecar.identity,
		protocol: {
			canonicalization: "stable-json-v1",
			sha256: protocolIdentity.sha256
		},
		resourceBounds: {
			maximumDataRows: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumDataRows,
			maximumVectorFrames: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumVectorFrames,
			maximumVectorPointSamples: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumVectorPointSamples,
			maximumVectorValues: FLOWBLIND_CATALOG_RESOURCE_LIMITS.maximumVectorValues
		}
	};
	const freezeSha256 = associationIdentity(freezeBindings);
	const freezeReceipt = {
		...freezeBindings,
		id: `vector-readiness-freeze-${freezeSha256.slice(0, 32)}`
	};
	const source = {
		candidate: candidateIdentity,
		trustedSidecar: {
			...sidecarIdentity,
			schemaId: trustedSidecar.schemaId
		},
		candidateBinding: { ...trustedSidecar.candidateBinding }
	};
	const protocol = {
		canonicalization: "stable-json-v1",
		scenario,
		byteLength: protocolBytes.byteLength,
		sha256: protocolIdentity.sha256,
		freezeReceipt
	};
	const associationBindings = {
		humanContext,
		source,
		declarations: trustedSidecar.declarations,
		canonicalSource: sourceProjection,
		capability: intent.capability,
		protocol,
		resourceLimits: FLOWBLIND_CATALOG_RESOURCE_LIMITS,
		dataHandling: {
			inputs: "exact-host-mounted-candidate-plus-scientist-metadata",
			processing: "local-confined-read-only-no-network-no-arbitrary-code",
			retention: "no-source-copy-no-saved-dataset-no-process-local-association",
			output: "portable-result-free-content-addressed-preparation-bundle"
		},
		software
	};
	const associationSha256 = associationIdentity(associationBindings);
	const bundle = {
		$schema: FLOWBLIND_CATALOG_VECTOR_PREPARATION_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-vector-preparation-v1",
		id: `flowblind-preparation-${associationSha256.slice(0, 32)}`,
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		association: {
			canonicalization: "stable-json-v1",
			sha256: associationSha256
		},
		...associationBindings
	};
	const bundleBytes = utf8Bytes(stableJson$1(bundle));
	return {
		bundle,
		bundleBytes,
		bundleIdentity: {
			...artifactIdentity("preparation.json", bundleBytes, "application/json"),
			mediaType: "application/json"
		},
		sidecarBytes: trustedSidecar.bytes,
		sidecarIdentity,
		validatedCandidate,
		dataset
	};
}
function vectorPreparationResponse(prepared, published) {
	return {
		schemaVersion: 1,
		teammateVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		humanContext: prepared.bundle.humanContext,
		sourceIdentity: prepared.bundle.source.candidate,
		sidecarIdentity: {
			...published.sidecar,
			mediaType: "application/json",
			schemaId: prepared.bundle.source.trustedSidecar.schemaId
		},
		declarationPreview: {
			reviewStatus: "requires-scientist-review-before-run",
			unverifiedScientistAssertions: {
				quantity: prepared.bundle.declarations.quantity,
				vectorMeaning: prepared.bundle.declarations.vectorMeaning,
				sourceKind: prepared.bundle.declarations.vectorSourceKind,
				coordinateUnit: prepared.bundle.declarations.coordinateUnit,
				velocityUnit: prepared.bundle.declarations.valueUnit,
				timeUnit: prepared.bundle.declarations.timeUnit,
				samplingKind: prepared.bundle.declarations.samplingKind,
				selectedTime: prepared.bundle.declarations.selectedTime,
				exposureDuration: prepared.bundle.declarations.exposureDuration,
				exposureOperator: prepared.bundle.declarations.exposureOperator,
				timestampAnchor: prepared.bundle.declarations.timestampAnchor,
				cycle: prepared.bundle.declarations.cycle,
				provenance: prepared.bundle.declarations.provenance,
				license: prepared.bundle.declarations.license
			},
			validatedV1Projection: {
				coordinateDimensions: 2,
				topology: "complete-rectilinear-grid",
				componentOrder: ["u", "v"],
				pointCount: prepared.bundle.canonicalSource.structure.pointCount,
				frameCount: prepared.bundle.canonicalSource.structure.frameCount,
				width: prepared.bundle.canonicalSource.structure.width,
				height: prepared.bundle.canonicalSource.structure.height,
				validPointSamples: prepared.bundle.canonicalSource.structure.validPointSamples,
				sharedCoordinatesAcrossFrames: true,
				wallEvidence: "not-supplied"
			}
		},
		vectorStructure: prepared.bundle.canonicalSource.structure,
		matchedCapability: prepared.bundle.capability,
		auditScenario: prepared.bundle.protocol.scenario,
		preparationAsset: {
			reference: published.directory,
			bundleSha256: published.bundle.sha256,
			fileCount: 2
		},
		preparationBundle: {
			...published.bundle,
			mediaType: "application/json"
		}
	};
}
async function validateVectorRunAttachments(humanContext, intent, attachments, software, signal) {
	if (attachments.length !== 3) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "Vector/time execution requires one CSV and one two-file preparation asset.");
	const candidate = catalogCandidateAttachment(attachments);
	const json = catalogJsonAttachments(attachments);
	const selectedBundle = catalogBundleAttachment(json, "flowblind-catalog-vector-preparation-v1");
	const sidecar = catalogSidecarAttachment(json, selectedBundle.attachment);
	const preparationParent = validatePreparationEnvelopeShape(selectedBundle.attachment, sidecar);
	const regeneratedSidecar = createCatalogVectorSidecar(candidate, validateCatalogVectorSidecar(sidecar, candidate).declarations);
	const expected = await prepareCatalogVectorStudy(humanContext, intent, candidate, regeneratedSidecar, software, signal);
	if (!selectedBundle.attachment.bytes.equals(expected.bundleBytes) || !sidecar.bytes.equals(regeneratedSidecar.bytes)) throw classifyBundleMismatch(selectedBundle.value, humanContext, candidate, software);
	validatePreparationEnvelopeIdentity(preparationParent, selectedBundle.attachment);
	return {
		preparation: expected,
		preparationAttachment: selectedBundle.attachment,
		candidate,
		sidecar
	};
}
async function executeCatalogVectorStudy(prepared, preparationBundleIdentity, options = {}) {
	await options.checkpoint?.("before-freeze-verification");
	throwIfCatalogAborted(options.signal);
	let scenario;
	try {
		scenario = parseVectorAuditScenario(prepared.bundle.protocol.scenario);
	} catch (error) {
		throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The vector/time preparation bundle contains an invalid frozen protocol.", { cause: error });
	}
	const protocolBytes = utf8Bytes(stableJson$1(scenario));
	if (protocolBytes.byteLength !== prepared.bundle.protocol.byteLength || artifactIdentity("protocol.json", protocolBytes).sha256 !== prepared.bundle.protocol.sha256) throw new CatalogResearchError("preparation-bundle-invalid", "input-validation", "The vector/time frozen protocol no longer matches its recorded identity.");
	await options.checkpoint?.("after-freeze-verification");
	throwIfCatalogAborted(options.signal);
	const runStudy = options.runStudy ?? runVectorTimeAudit;
	let primary;
	try {
		await options.checkpoint?.("before-primary-compute");
		throwIfCatalogAborted(options.signal);
		primary = runStudy(prepared.dataset, prepared.bundle.source.candidate, scenario);
		await options.checkpoint?.("after-primary-compute");
		throwIfCatalogAborted(options.signal);
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		throw new CatalogResearchError("run-failed", "execution", "The reviewed vector/time readiness operation did not complete.", { cause: error });
	}
	let replay;
	try {
		await options.checkpoint?.("before-replay-compute");
		throwIfCatalogAborted(options.signal);
		replay = runStudy(prepared.dataset, prepared.bundle.source.candidate, scenario);
		await options.checkpoint?.("after-replay-compute");
		throwIfCatalogAborted(options.signal);
	} catch (error) {
		if (error instanceof CatalogResearchError) throw error;
		throw new CatalogResearchError("verification-failed", "verification", "The vector/time readiness verification replay did not complete.", { cause: error });
	}
	if (stableJson$1(primary) !== stableJson$1(replay)) throw new CatalogResearchError("verification-failed", "verification", "The vector/time readiness verification replay did not match the first result.");
	await options.checkpoint?.("before-result-projection");
	throwIfCatalogAborted(options.signal);
	const record = {
		$schema: FLOWBLIND_CATALOG_VECTOR_VERIFIED_STUDY_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-vector-verified-study-v1",
		status: "verified",
		containsResults: true,
		humanContext: prepared.bundle.humanContext,
		capability: prepared.bundle.capability,
		preparation: {
			id: prepared.bundle.id,
			associationSha256: prepared.bundle.association.sha256,
			bundle: preparationBundleIdentity
		},
		source: {
			candidate: prepared.bundle.source.candidate,
			trustedSidecar: prepared.bundle.source.trustedSidecar
		},
		protocol: {
			sha256: prepared.bundle.protocol.sha256,
			freezeReceipt: prepared.bundle.protocol.freezeReceipt
		},
		verification: {
			artifactVerificationStatus: "verified",
			deterministicReplayMatched: true,
			sourceIdentityMatched: true,
			softwareIdentityMatched: true
		},
		study: {
			capabilityId: "vector-time-readiness-audit-v1",
			report: primary,
			claimBoundary: [
				"This is a descriptive software and evidence-readiness audit.",
				"Unavailable and insufficient-evidence outcomes are preserved and are not pass/fail verdicts.",
				"The report does not establish solver, acquisition, physiological, clinical, or diagnostic validation."
			]
		}
	};
	await options.checkpoint?.("after-result-projection");
	throwIfCatalogAborted(options.signal);
	return record;
}
function renderCatalogVectorMarkdown(record) {
	return [
		"# FlowBlind vector/time readiness",
		"",
		`**Research goal:** ${escapeMarkdown$1(record.humanContext.researchGoal)}`,
		`**Decision question:** ${record.humanContext.decisionQuestion === null ? "not supplied" : escapeMarkdown$1(record.humanContext.decisionQuestion)}`,
		`**Next evidence intent:** ${record.humanContext.nextEvidenceIntent === null ? "not supplied" : escapeMarkdown$1(record.humanContext.nextEvidenceIntent)}`,
		"",
		renderVectorEvidenceReportMarkdown(record.study.report).trimEnd(),
		"",
		"## Claim boundary",
		"",
		...record.study.claimBoundary.map((item) => `- ${item}`),
		""
	].join("\n");
}
function escapeHtml(value) {
	return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll("\"", "&quot;").replaceAll("'", "&#39;");
}
function metricStatus(metric) {
	return metric.status === "available" ? "available" : `${metric.status}: ${metric.reason ?? "not specified"}`;
}
function renderCatalogVectorHtml(record) {
	const report = record.study.report;
	const statuses = [
		["Instantaneous speed", report.metrics.instantaneous.speed],
		["Instantaneous derivatives", report.metrics.instantaneous.derivatives],
		["Wall shear stress", report.metrics.instantaneous.wallShear],
		["Frame mean", report.metrics.frameMean],
		["Complete cycle", report.metrics.completeCycle]
	];
	return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>FlowBlind vector/time readiness</title>
<style>
:root{color-scheme:light dark;font-family:ui-sans-serif,system-ui,sans-serif}
body{margin:0;background:#0b1020;color:#eef2ff}
main{max-width:980px;margin:auto;padding:32px}
.card{background:#151c32;border:1px solid #35405f;border-radius:14px;padding:18px;margin:16px 0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #35405f}
code{overflow-wrap:anywhere}small{color:#b8c0d9}
@media print{body{background:white;color:black}.card{border:1px solid #777;background:white}}
</style>
</head>
<body><main>
<h1>Vector/time readiness audit</h1>
<p>${escapeHtml(report.dataset.title)}</p>
<section class="card"><h2>Dataset</h2>
<p>${escapeHtml(report.dataset.description)}</p>
<p><strong>Shape:</strong> ${report.dataset.frameCount} frame(s), ${report.dataset.pointCount} points, ${report.dataset.coordinateFrame.dimension}D ${escapeHtml(report.dataset.kind)}</p>
<p><strong>Sampling:</strong> ${escapeHtml(report.dataset.temporal.sampling.kind)}; <strong>requested time:</strong> ${report.metrics.instantaneous.requestedTime}</p>
</section>
<section class="card"><h2>Evidence states</h2><table><thead><tr><th>Metric</th><th>Status</th></tr></thead><tbody>
${statuses.map(([label, metric]) => `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(metricStatus(metric))}</td></tr>`).join("")}
</tbody></table></section>
<section class="card"><h2>Claim boundary</h2><ul>${record.study.claimBoundary.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>
<section class="card"><h2>Verification</h2><p>Deterministic replay matched. Source and software identities were revalidated.</p><small>Preparation SHA-256: <code>${record.preparation.bundle.sha256}</code></small></section>
</main></body></html>
`;
}
//#endregion
//#region tools/catalogResearch/catalogCoordinator.ts
function intentResponse(assessment) {
	const scientificGuidance = assessment.reasonCodes.includes("unreviewed-vector-temporal-operation-requested") ? "This teammate can report selected-frame speed and spatial derivatives, plus the frame or complete-cycle mean of spatial mean speed. Restate the question using only those operations, or use a separately reviewed method." : assessment.reasonCodes.includes("unreviewed-summary-operation-requested") ? "Use the fixed regional agreement endpoints or the vector frame or complete-cycle mean of spatial mean speed. Other summaries require a separately reviewed method." : "Use a separately reviewed method contract; this teammate will not invent or broaden a scientific method.";
	return {
		schemaVersion: 1,
		teammateVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
		status: assessment.status,
		reasonCodes: assessment.reasonCodes,
		guidance: assessment.status === "ambiguous" ? "Restate whether the goal is a regional reference/candidate agreement study or a readiness audit of one vector field or time series." : assessment.status === "unsupported" ? "Describe either a regional reference/candidate agreement question or a vector/time evidence-readiness audit." : assessment.status === "needs-scientific-method" ? scientificGuidance : "Remove external-access, approval-bypass, arbitrary-execution, or unreviewed clinical requests before preparing a study.",
		containsResults: false
	};
}
function preparationAttachments(attachments) {
	const candidate = attachments.filter((attachment) => attachment.reference.toLowerCase().endsWith(".csv"));
	if (candidate.length !== 1) throw new CatalogResearchError("attachment-set-invalid", "input-validation", "Preparation requires exactly one candidate CSV attachment.");
	return { candidate: candidate[0] };
}
function assertCatalogPolicy(action, software) {
	if (software.catalogPolicy.humanInTheLoop !== "Enabled" || software.catalogPolicy.disableDataHandlingTools !== false) throw new CatalogResearchError("package-attestation-failed", "package-attestation", "The attested catalog policy does not preserve the reviewed human and attachment boundaries.");
	if (action === "prepare-study" && software.catalogPolicy.prepareConfirmation !== "Disabled") throw new CatalogResearchError("package-attestation-failed", "package-attestation", "Preparation must remain result-free without a source-registration confirmation.");
	if (action === "run-and-verify-study" && software.catalogPolicy.runConfirmation !== "Enabled") throw new CatalogResearchError("confirmation-required", "confirmation", "The run tool requires an enabled host confirmation policy.");
}
function mapUnexpectedFailure(action, error) {
	return action === "run-and-verify-study" ? new CatalogResearchError("run-failed", "execution", "The catalog run failed without publishing a verified result.", { cause: error }) : new CatalogResearchError("source-structure-invalid", "input-validation", "Preparation could not validate the selected scientific inputs.", { cause: error });
}
async function callAttestedCatalogResearchAction(action, input, context, software) {
	try {
		if (action !== "prepare-study" && action !== "run-and-verify-study") throw new CatalogResearchError("unsupported-action", "input-validation", "Only the two reviewed catalog research actions are supported.");
		assertCatalogPolicy(action, software);
		const humanContext = action === "prepare-study" ? validateCatalogPreparationHumanContext(input) : validateCatalogHumanContext(input);
		const assessment = assessCatalogResearchIntent(humanContext);
		if (assessment.status !== "matched") return intentResponse(assessment);
		if (action === "prepare-study") {
			const preparationInput = validateCatalogPreparationInput(input, assessment.capability.capabilityId);
			const selected = preparationAttachments(await loadCatalogAttachments({
				root: context.inputRoot,
				expectedFileCount: 1,
				signal: context.signal,
				checkpoint: context.hooks?.attachment
			}));
			if (preparationInput.capabilityId === "vector-time-readiness-audit-v1") {
				if (assessment.capability.capabilityId !== "vector-time-readiness-audit-v1") throw new CatalogResearchError("capability-metadata-mismatch", "input-validation", "The matched capability and validated vector metadata disagree.");
				const trustedSidecar = createCatalogVectorSidecar(selected.candidate, preparationInput.metadata);
				await context.hooks?.execution?.("before-preparation-build");
				throwIfCatalogAborted(context.signal);
				const prepared = await prepareCatalogVectorStudy(humanContext, assessment, selected.candidate, trustedSidecar, software, context.signal);
				await context.hooks?.execution?.("after-preparation-build");
				throwIfCatalogAborted(context.signal);
				return vectorPreparationResponse(prepared, await publishPreparationAssets(context.outputRoot, prepared.bundleIdentity, prepared.bundleBytes, prepared.sidecarIdentity, prepared.sidecarBytes, {
					signal: context.signal,
					checkpoint: context.hooks?.publication
				}));
			}
			const trustedSidecar = createCatalogTrustedSidecar(selected.candidate, preparationInput.metadata);
			await context.hooks?.execution?.("before-preparation-build");
			throwIfCatalogAborted(context.signal);
			const prepared = await prepareCatalogStudy(humanContext, assessment, selected.candidate, trustedSidecar, software);
			await context.hooks?.execution?.("after-preparation-build");
			throwIfCatalogAborted(context.signal);
			return preparationResponse(prepared, await publishPreparationAssets(context.outputRoot, prepared.bundleIdentity, prepared.bundleBytes, prepared.sidecarIdentity, prepared.sidecarBytes, {
				signal: context.signal,
				checkpoint: context.hooks?.publication
			}));
		}
		const firstAttachments = await loadCatalogAttachments({
			root: context.inputRoot,
			expectedFileCount: 3,
			signal: context.signal,
			checkpoint: context.hooks?.attachment
		});
		await context.hooks?.execution?.("before-run-bundle-validation");
		throwIfCatalogAborted(context.signal);
		if (assessment.capability.capabilityId === "vector-time-readiness-audit-v1") {
			const vectorAssessment = {
				...assessment,
				capability: assessment.capability
			};
			const first = await validateVectorRunAttachments(humanContext, vectorAssessment, firstAttachments, software, context.signal);
			await context.hooks?.execution?.("after-run-bundle-validation");
			throwIfCatalogAborted(context.signal);
			const executionAttachments = await loadCatalogAttachments({
				root: context.inputRoot,
				expectedFileCount: 3,
				signal: context.signal,
				checkpoint: context.hooks?.attachment
			});
			await context.hooks?.execution?.("before-run-bundle-validation");
			throwIfCatalogAborted(context.signal);
			const execution = await validateVectorRunAttachments(humanContext, vectorAssessment, executionAttachments, software, context.signal);
			await context.hooks?.execution?.("after-run-bundle-validation");
			throwIfCatalogAborted(context.signal);
			if (stableJson$1(first.preparation.bundle) !== stableJson$1(execution.preparation.bundle) || first.candidate.sha256 !== execution.candidate.sha256 || first.sidecar.sha256 !== execution.sidecar.sha256 || first.preparationAttachment.sha256 !== execution.preparationAttachment.sha256) throw new CatalogResearchError("source-identity-mismatch", "verification", "The selected attachments changed before execution.");
			const verifiedRecord = await executeCatalogVectorStudy(execution.preparation, artifactIdentity("preparation.json", execution.preparationAttachment.bytes, "application/json"), {
				signal: context.signal,
				checkpoint: context.hooks?.execution,
				runStudy: context.hooks?.runVectorStudy
			});
			await context.hooks?.execution?.("before-markdown-render");
			throwIfCatalogAborted(context.signal);
			const markdown = renderCatalogVectorMarkdown(verifiedRecord);
			await context.hooks?.execution?.("after-markdown-render");
			throwIfCatalogAborted(context.signal);
			await context.hooks?.execution?.("before-html-render");
			throwIfCatalogAborted(context.signal);
			const html = renderCatalogVectorHtml(verifiedRecord);
			await context.hooks?.execution?.("after-html-render");
			throwIfCatalogAborted(context.signal);
			return catalogRunResponse(humanContext, verifiedRecord, await publishCatalogStudy(context.outputRoot, verifiedRecord, execution.preparation.bundleBytes, markdown, html, software, {
				signal: context.signal,
				checkpoint: context.hooks?.publication
			}), software);
		}
		const first = await validateRunAttachments(humanContext, assessment, firstAttachments, software);
		await context.hooks?.execution?.("after-run-bundle-validation");
		throwIfCatalogAborted(context.signal);
		const executionAttachments = await loadCatalogAttachments({
			root: context.inputRoot,
			expectedFileCount: 3,
			signal: context.signal,
			checkpoint: context.hooks?.attachment
		});
		await context.hooks?.execution?.("before-run-bundle-validation");
		throwIfCatalogAborted(context.signal);
		const execution = await validateRunAttachments(humanContext, assessment, executionAttachments, software);
		await context.hooks?.execution?.("after-run-bundle-validation");
		throwIfCatalogAborted(context.signal);
		if (stableJson$1(first.preparation.bundle) !== stableJson$1(execution.preparation.bundle) || first.candidate.sha256 !== execution.candidate.sha256 || first.sidecar.sha256 !== execution.sidecar.sha256 || first.preparationAttachment.sha256 !== execution.preparationAttachment.sha256) throw new CatalogResearchError("source-identity-mismatch", "verification", "The selected attachments changed before execution.");
		const verifiedRecord = await executeCatalogStudy(execution.preparation.bundle, artifactIdentity("preparation.json", execution.preparationAttachment.bytes, "application/json"), execution.validatedCandidate, {
			signal: context.signal,
			checkpoint: context.hooks?.execution,
			runStudy: context.hooks?.runStudy
		});
		await context.hooks?.execution?.("before-markdown-render");
		throwIfCatalogAborted(context.signal);
		const markdown = renderCatalogStudyMarkdown(verifiedRecord);
		await context.hooks?.execution?.("after-markdown-render");
		throwIfCatalogAborted(context.signal);
		await context.hooks?.execution?.("before-html-render");
		throwIfCatalogAborted(context.signal);
		const html = renderCatalogStudyHtml(verifiedRecord);
		await context.hooks?.execution?.("after-html-render");
		throwIfCatalogAborted(context.signal);
		return catalogRunResponse(humanContext, verifiedRecord, await publishCatalogStudy(context.outputRoot, verifiedRecord, execution.preparation.bundleBytes, markdown, html, software, {
			signal: context.signal,
			checkpoint: context.hooks?.publication
		}), software);
	} catch (error) {
		context.hooks?.unexpectedError?.(error);
		return catalogRefusal(error instanceof CatalogResearchError ? error : mapUnexpectedFailure(action === "prepare-study" ? FLOWBLIND_PREPARE_STUDY_ACTION : FLOWBLIND_RUN_AND_VERIFY_STUDY_ACTION, error));
	}
}
function catalogRunResponse(humanContext, verifiedRecord, published, software) {
	return {
		schemaVersion: 1,
		teammateVersion: FLOWBLIND_CATALOG_RESEARCH_VERSION,
		status: "report-complete",
		containsResults: true,
		humanContext,
		matchedCapability: verifiedRecord.capability,
		verifiedStudy: {
			status: "verified",
			artifactVerificationStatus: "verified",
			deterministicReplayMatched: true,
			sourceIdentityMatched: true,
			result: verifiedRecord.study,
			artifacts: {
				json: published.artifacts.json,
				markdown: published.artifacts.markdown,
				html: published.artifacts.html,
				verification: published.artifacts.verification
			},
			openVisualReport: published.openVisualReport
		},
		preparationEvidence: {
			kind: "portable-preparation-bundle-v1",
			preparation: {
				id: verifiedRecord.preparation.id,
				associationSha256: verifiedRecord.preparation.associationSha256,
				bundle: verifiedRecord.preparation.bundle
			},
			source: verifiedRecord.source,
			protocol: { sha256: verifiedRecord.protocol.sha256 },
			software
		}
	};
}
async function readAttestedCatalogVisualResource(uri, outputRoot, software, context = {}) {
	assertCatalogPolicy(FLOWBLIND_RUN_AND_VERIFY_STUDY_ACTION, software);
	return readCatalogVisualResource(outputRoot, uri, software, {
		signal: context.signal,
		checkpoint: context.hooks?.publication
	});
}
//#endregion
//#region tools/catalogResearch/catalogResearchRuntime.ts
var verificationModuleReference = ["..", "flowblind-research-teammate-verification-v1.mjs"].join("/");
async function packageEvidence(value) {
	if (value === null || value === void 0) return null;
	try {
		const authority = await import(new URL(verificationModuleReference, import.meta.url).href);
		return typeof authority.flowBlindCatalogPackageVerificationEvidence === "function" ? authority.flowBlindCatalogPackageVerificationEvidence(value) : null;
	} catch {
		return null;
	}
}
function attestationRefusal() {
	return catalogRefusal(new CatalogResearchError("package-attestation-failed", "package-attestation", "Direct or unverified catalog runtime invocation is not permitted."));
}
var catalogResearchRuntimeVersion = FLOWBLIND_CATALOG_RESEARCH_VERSION;
var catalogResearchCapabilities = FLOWBLIND_CATALOG_CAPABILITIES;
var catalogResearchToolDefinitions = [{
	name: FLOWBLIND_PREPARE_STUDY_ACTION,
	title: "Prepare a reviewed FlowBlind study",
	description: "Read one exact host attachment and produce a deterministic result-free preparation asset containing its generated sidecar and frozen bundle without running science.",
	inputSchema: FLOWBLIND_CATALOG_PREPARE_INPUT_SCHEMA,
	annotations: {
		readOnlyHint: false,
		destructiveHint: false,
		idempotentHint: true,
		openWorldHint: false
	}
}, {
	name: FLOWBLIND_RUN_AND_VERIFY_STUDY_ACTION,
	title: "Run and verify a prepared FlowBlind study",
	description: "After host confirmation, revalidate exact attachments, execute only the frozen reviewed operation, verify deterministic replay, and publish verified reports.",
	inputSchema: FLOWBLIND_CATALOG_PUBLIC_INPUT_SCHEMA,
	annotations: {
		readOnlyHint: false,
		destructiveHint: false,
		idempotentHint: true,
		openWorldHint: false
	}
}];
var catalogResearchSupportedActions = FLOWBLIND_CATALOG_RESEARCH_ACTIONS;
function serializeCatalogResearchValue(value) {
	return stableJson$1(value);
}
async function callCatalogResearchAction(action, input, context, packageVerification) {
	const software = await packageEvidence(packageVerification);
	if (software === null) return attestationRefusal();
	return callAttestedCatalogResearchAction(action, input, context, software);
}
async function readCatalogResearchVisualResource(uri, outputRoot, packageVerification) {
	const software = await packageEvidence(packageVerification);
	if (software === null) throw new CatalogResearchError("package-attestation-failed", "package-attestation", "Direct or unverified visual-resource reads are not permitted.");
	return readAttestedCatalogVisualResource(uri, outputRoot, software);
}
//#endregion
export { callCatalogResearchAction, catalogResearchCapabilities, catalogResearchRuntimeVersion, catalogResearchSupportedActions, catalogResearchToolDefinitions, readCatalogResearchVisualResource, serializeCatalogResearchValue };

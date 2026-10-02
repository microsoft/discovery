import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { link, lstat, mkdir, mkdtemp, open, opendir, realpath, rm, unlink, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { execFile } from "node:child_process";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
//#region src/domain/hiddenFlowModel.ts
var HIDDEN_FLOW_LIMITS = {
	maximumDocumentBytes: 16777216,
	maximumSolverResultBytes: 16777216,
	maximumSolverBatchRequests: 64,
	maximumSolverBatchInputBytes: 33554432,
	maximumSolverBatchResultBytes: 67108864,
	maximumBasisFunctions: 96,
	maximumObservationRows: 256,
	maximumObservationMatrixEntries: 24576,
	maximumTargetGridPoints: 256,
	maximumDirections: 64,
	maximumScenarios: 24,
	maximumTextLength: 2048,
	maximumIdentifierLength: 64,
	maximumMatrixEntries: 9216,
	maximumCanonicalMatrixEntries: 7e4,
	maximumNumericMagnitude: 1e100
};
//#endregion
//#region src/domain/hiddenFlowValidation.ts
var IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
var HiddenFlowInputError = class extends Error {
	code;
	constructor(code, path, message) {
		super(`${path}: ${message}`);
		this.name = "HiddenFlowInputError";
		this.code = code;
	}
};
function fail$1(path, message, code = "invalid-input") {
	throw new HiddenFlowInputError(code, path, message);
}
function isRecord$1(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}
function record$1(value, path) {
	if (!isRecord$1(value)) return fail$1(path, "must be an object.");
	return value;
}
function array(value, path) {
	if (!Array.isArray(value)) return fail$1(path, "must be an array.");
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
function finite$1(value, path) {
	if (typeof value !== "number" || !Number.isFinite(value)) return fail$1(path, "must be a finite number.");
	if (Math.abs(value) > HIDDEN_FLOW_LIMITS.maximumNumericMagnitude) fail$1(path, "exceeds the supported numerical magnitude.");
	return value;
}
function positive(value, path) {
	const parsed = finite$1(value, path);
	if (parsed <= 0) fail$1(path, "must be greater than zero.");
	return parsed;
}
function nonnegative(value, path) {
	const parsed = finite$1(value, path);
	if (parsed < 0) fail$1(path, "must be nonnegative.");
	return parsed;
}
function integer$1(value, path, minimum, maximum) {
	const parsed = finite$1(value, path);
	if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) return fail$1(path, `must be an integer between ${minimum} and ${maximum}.`);
	return parsed;
}
function identifier(value, path) {
	if (typeof value !== "string" || !IDENTIFIER.test(value)) return fail$1(path, "must be a portable identifier.");
	return value;
}
function hasRejectedCharacter(value) {
	for (const character of value) {
		const code = character.codePointAt(0);
		if (code !== void 0 && (code < 32 || code === 127 || code >= 8234 && code <= 8238 || code >= 8294 && code <= 8297)) return true;
	}
	return false;
}
function text$1(value, path, maximumLength = HIDDEN_FLOW_LIMITS.maximumTextLength) {
	if (typeof value !== "string" || value.length === 0 || value.length > maximumLength || hasRejectedCharacter(value)) return fail$1(path, `must be nonempty text no longer than ${maximumLength} characters without control or bidirectional formatting characters.`);
	return value;
}
function enumValue(value, allowed, path) {
	if (typeof value !== "string" || !allowed.includes(value)) return fail$1(path, `must be one of ${allowed.join(", ")}.`);
	return value;
}
function finiteArray$1(value, path, minimumLength, maximumLength) {
	const items = array(value, path);
	if (items.length < minimumLength || items.length > maximumLength) fail$1(path, `must contain between ${minimumLength} and ${maximumLength} values.`, "resource-limit-exceeded");
	return items.map((item, index) => finite$1(item, `${path}[${index}]`));
}
function booleanArray(value, path, expectedLength) {
	const items = array(value, path);
	if (items.length !== expectedLength) fail$1(path, `must contain exactly ${expectedLength} values.`);
	return items.map((item, index) => {
		if (typeof item !== "boolean") return fail$1(`${path}[${index}]`, "must be a boolean.");
		return item;
	});
}
function increasing(values, path) {
	for (let index = 1; index < values.length; index += 1) if (values[index] <= values[index - 1]) fail$1(path, "must be strictly increasing.");
}
function point(value, path) {
	const item = record$1(value, path);
	exactKeys$1(item, ["x", "y"], path);
	return {
		x: finite$1(property$1(item, "x"), `${path}.x`),
		y: finite$1(property$1(item, "y"), `${path}.y`)
	};
}
function direction(value, path) {
	const values = finiteArray$1(value, path, 2, 2);
	const norm = Math.hypot(values[0], values[1]);
	if (norm <= 1e-12) fail$1(path, "must have nonzero length.");
	return [values[0] / norm, values[1] / norm];
}
var DEFAULT_HIDDEN_FLOW_PROBLEM_RESOURCE_LIMITS = {
	maximumDomainCells: HIDDEN_FLOW_LIMITS.maximumTargetGridPoints * 4,
	maximumBasisFunctions: HIDDEN_FLOW_LIMITS.maximumBasisFunctions
};
function parseDomain(value, path, limits) {
	const item = record$1(value, path);
	exactKeys$1(item, [
		"id",
		"coordinateFrameId",
		"lengthUnit",
		"xEdges",
		"yEdges",
		"validCellMask"
	], path);
	const xEdges = finiteArray$1(property$1(item, "xEdges"), `${path}.xEdges`, 3, 65);
	const yEdges = finiteArray$1(property$1(item, "yEdges"), `${path}.yEdges`, 3, 65);
	increasing(xEdges, `${path}.xEdges`);
	increasing(yEdges, `${path}.yEdges`);
	const cellCount = (xEdges.length - 1) * (yEdges.length - 1);
	if (cellCount > limits.maximumDomainCells) fail$1(path, `declares ${cellCount} cells, exceeding the bounded domain limit.`, "resource-limit-exceeded");
	const validCellMask = booleanArray(property$1(item, "validCellMask"), `${path}.validCellMask`, cellCount);
	if (!validCellMask.some(Boolean)) fail$1(`${path}.validCellMask`, "must retain at least one valid cell.");
	return {
		id: identifier(property$1(item, "id"), `${path}.id`),
		coordinateFrameId: identifier(property$1(item, "coordinateFrameId"), `${path}.coordinateFrameId`),
		lengthUnit: enumValue(property$1(item, "lengthUnit"), ["mm"], `${path}.lengthUnit`),
		xEdges,
		yEdges,
		validCellMask
	};
}
function parseBasisCenter(value, path) {
	const item = record$1(value, path);
	exactKeys$1(item, ["id", "point"], path);
	return {
		id: identifier(property$1(item, "id"), `${path}.id`),
		point: point(property$1(item, "point"), `${path}.point`)
	};
}
function parseBasis(value, path, limits) {
	const item = record$1(value, path);
	exactKeys$1(item, [
		"family",
		"degree",
		"spacingX",
		"spacingY",
		"streamfunctionLengthScale",
		"interiorMarginCells",
		"quadratureOrder",
		"coefficientUnit",
		"boundaryPolicy",
		"centers"
	], path);
	if (property$1(item, "degree") !== 3) fail$1(`${path}.degree`, "must equal 3.");
	if (property$1(item, "quadratureOrder") !== 4) fail$1(`${path}.quadratureOrder`, "must equal 4.");
	const centerValues = array(property$1(item, "centers"), `${path}.centers`);
	if (centerValues.length === 0 || centerValues.length > limits.maximumBasisFunctions) fail$1(`${path}.centers`, `must contain between 1 and ${limits.maximumBasisFunctions} centers.`, "resource-limit-exceeded");
	const centers = centerValues.map((entry, index) => parseBasisCenter(entry, `${path}.centers[${index}]`));
	if (new Set(centers.map((center) => center.id)).size !== centers.length) fail$1(`${path}.centers`, "must use unique center IDs.");
	return {
		family: enumValue(property$1(item, "family"), ["tensor-cardinal-cubic-streamfunction-v1"], `${path}.family`),
		degree: 3,
		spacingX: positive(property$1(item, "spacingX"), `${path}.spacingX`),
		spacingY: positive(property$1(item, "spacingY"), `${path}.spacingY`),
		streamfunctionLengthScale: positive(property$1(item, "streamfunctionLengthScale"), `${path}.streamfunctionLengthScale`),
		interiorMarginCells: integer$1(property$1(item, "interiorMarginCells"), `${path}.interiorMarginCells`, 1, 8),
		quadratureOrder: 4,
		coefficientUnit: enumValue(property$1(item, "coefficientUnit"), ["mm/s"], `${path}.coefficientUnit`),
		boundaryPolicy: enumValue(property$1(item, "boundaryPolicy"), ["compact-support-inside-valid-cell-union"], `${path}.boundaryPolicy`),
		centers
	};
}
function parseHiddenFlowObservation(value, path) {
	const item = record$1(value, path);
	const observationType = property$1(item, "type");
	if (observationType !== "point-component" && observationType !== "point-direction") fail$1(`${path}.type`, `observation type ${JSON.stringify(observationType)} is not supported in schema version 1.`, "unsupported-observation-type");
	exactKeys$1(item, [
		"type",
		"id",
		"sensorId",
		"point",
		"coordinateFrameId",
		"unit",
		"baselineValue",
		"observedValue",
		"tolerance",
		"provenance",
		observationType === "point-component" ? "component" : "direction"
	], path);
	const base = {
		id: identifier(property$1(item, "id"), `${path}.id`),
		sensorId: identifier(property$1(item, "sensorId"), `${path}.sensorId`),
		point: point(property$1(item, "point"), `${path}.point`),
		coordinateFrameId: identifier(property$1(item, "coordinateFrameId"), `${path}.coordinateFrameId`),
		unit: enumValue(property$1(item, "unit"), ["mm/s"], `${path}.unit`),
		baselineValue: finite$1(property$1(item, "baselineValue"), `${path}.baselineValue`),
		observedValue: finite$1(property$1(item, "observedValue"), `${path}.observedValue`),
		tolerance: nonnegative(property$1(item, "tolerance"), `${path}.tolerance`),
		provenance: text$1(property$1(item, "provenance"), `${path}.provenance`)
	};
	if (observationType === "point-component") return {
		...base,
		type: observationType,
		component: enumValue(property$1(item, "component"), ["x", "y"], `${path}.component`)
	};
	return {
		...base,
		type: observationType,
		direction: direction(property$1(item, "direction"), `${path}.direction`)
	};
}
function parseTarget(value, path) {
	const item = record$1(value, path);
	const targetType = property$1(item, "type");
	const common = {
		id: identifier(property$1(item, "id"), `${path}.id`),
		title: text$1(property$1(item, "title"), `${path}.title`, 256)
	};
	if (targetType === "point-component") {
		exactKeys$1(item, [
			"type",
			"id",
			"title",
			"point",
			"component",
			"unit"
		], path);
		return {
			...common,
			type: targetType,
			point: point(property$1(item, "point"), `${path}.point`),
			component: enumValue(property$1(item, "component"), ["x", "y"], `${path}.component`),
			unit: enumValue(property$1(item, "unit"), ["mm/s"], `${path}.unit`)
		};
	}
	if (targetType === "point-direction") {
		exactKeys$1(item, [
			"type",
			"id",
			"title",
			"point",
			"direction",
			"unit"
		], path);
		return {
			...common,
			type: targetType,
			point: point(property$1(item, "point"), `${path}.point`),
			direction: direction(property$1(item, "direction"), `${path}.direction`),
			unit: enumValue(property$1(item, "unit"), ["mm/s"], `${path}.unit`)
		};
	}
	if (targetType === "point-speed-envelope") {
		exactKeys$1(item, [
			"type",
			"id",
			"title",
			"point",
			"unit",
			"directionCount"
		], path);
		return {
			...common,
			type: targetType,
			point: point(property$1(item, "point"), `${path}.point`),
			unit: enumValue(property$1(item, "unit"), ["mm/s"], `${path}.unit`),
			directionCount: integer$1(property$1(item, "directionCount"), `${path}.directionCount`, 3, HIDDEN_FLOW_LIMITS.maximumDirections)
		};
	}
	if (targetType === "region-component") {
		exactKeys$1(item, [
			"type",
			"id",
			"title",
			"cellIndices",
			"component",
			"unit"
		], path);
		const cellIndexValues = array(property$1(item, "cellIndices"), `${path}.cellIndices`);
		const maximumCellIndices = HIDDEN_FLOW_LIMITS.maximumTargetGridPoints * 4;
		if (cellIndexValues.length === 0 || cellIndexValues.length > maximumCellIndices) fail$1(`${path}.cellIndices`, `must contain between 1 and ${maximumCellIndices} cell indices.`, "resource-limit-exceeded");
		const cellIndices = cellIndexValues.map((entry, index) => integer$1(entry, `${path}.cellIndices[${index}]`, 0, maximumCellIndices));
		if (new Set(cellIndices).size !== cellIndices.length) fail$1(`${path}.cellIndices`, "must not contain duplicate indices.");
		return {
			...common,
			type: targetType,
			cellIndices,
			component: enumValue(property$1(item, "component"), ["x", "y"], `${path}.component`),
			unit: enumValue(property$1(item, "unit"), ["mm/s"], `${path}.unit`)
		};
	}
	if (targetType === "point-strain-component") {
		exactKeys$1(item, [
			"type",
			"id",
			"title",
			"point",
			"component",
			"unit"
		], path);
		return {
			...common,
			type: targetType,
			point: point(property$1(item, "point"), `${path}.point`),
			component: enumValue(property$1(item, "component"), [
				"xx",
				"yy",
				"xy"
			], `${path}.component`),
			unit: enumValue(property$1(item, "unit"), ["1/s"], `${path}.unit`)
		};
	}
	return fail$1(`${path}.type`, `target type ${JSON.stringify(targetType)} is not supported in schema version 1.`, "unsupported-target-type");
}
function parseBudgets(value, path) {
	const item = record$1(value, path);
	exactKeys$1(item, ["velocityRms", "velocityGradientRms"], path);
	const velocity = property$1(item, "velocityRms");
	const gradient = property$1(item, "velocityGradientRms");
	const parseBudget = (candidate, candidatePath, unit) => {
		if (candidate === null) return null;
		const budget = record$1(candidate, candidatePath);
		exactKeys$1(budget, ["value", "unit"], candidatePath);
		return {
			value: nonnegative(property$1(budget, "value"), `${candidatePath}.value`),
			unit: enumValue(property$1(budget, "unit"), [unit], `${candidatePath}.unit`)
		};
	};
	return {
		velocityRms: parseBudget(velocity, `${path}.velocityRms`, "mm/s"),
		velocityGradientRms: parseBudget(gradient, `${path}.velocityGradientRms`, "1/s")
	};
}
function parseNumerics(value, path) {
	const item = record$1(value, path);
	exactKeys$1(item, [
		"rankRelativeTolerance",
		"basisConditionLimit",
		"verificationAbsoluteTolerance",
		"verificationRelativeTolerance",
		"maximumSolverIterations"
	], path);
	return {
		rankRelativeTolerance: positive(property$1(item, "rankRelativeTolerance"), `${path}.rankRelativeTolerance`),
		basisConditionLimit: positive(property$1(item, "basisConditionLimit"), `${path}.basisConditionLimit`),
		verificationAbsoluteTolerance: positive(property$1(item, "verificationAbsoluteTolerance"), `${path}.verificationAbsoluteTolerance`),
		verificationRelativeTolerance: positive(property$1(item, "verificationRelativeTolerance"), `${path}.verificationRelativeTolerance`),
		maximumSolverIterations: integer$1(property$1(item, "maximumSolverIterations"), `${path}.maximumSolverIterations`, 1, 1e5)
	};
}
function stringArray$1(value, path, maximum) {
	const items = array(value, path);
	if (items.length > maximum) fail$1(path, `must not contain more than ${maximum} entries.`, "resource-limit-exceeded");
	return items.map((entry, index) => text$1(entry, `${path}[${index}]`));
}
function parseHiddenFlowProblem(value, resourceLimits = DEFAULT_HIDDEN_FLOW_PROBLEM_RESOURCE_LIMITS) {
	const path = "hiddenFlowProblem";
	const item = record$1(value, path);
	exactKeys$1(item, [
		"schemaVersion",
		"id",
		"title",
		"description",
		"domain",
		"basis",
		"observations",
		"budgets",
		"target",
		"numerics",
		"provenance",
		"limitations"
	], path);
	if (property$1(item, "schemaVersion") !== 1) fail$1(`${path}.schemaVersion`, "must equal 1.");
	const domain = parseDomain(property$1(item, "domain"), `${path}.domain`, resourceLimits);
	const basis = parseBasis(property$1(item, "basis"), `${path}.basis`, resourceLimits);
	const observationValues = array(property$1(item, "observations"), `${path}.observations`);
	if (observationValues.length > HIDDEN_FLOW_LIMITS.maximumObservationRows) fail$1(`${path}.observations`, `must not exceed ${HIDDEN_FLOW_LIMITS.maximumObservationRows} scalar rows.`, "resource-limit-exceeded");
	const observations = observationValues.map((entry, index) => parseHiddenFlowObservation(entry, `${path}.observations[${index}]`));
	if (new Set(observations.map((entry) => entry.id)).size !== observations.length) fail$1(`${path}.observations`, "must use unique observation IDs.");
	if (observations.length * basis.centers.length > HIDDEN_FLOW_LIMITS.maximumObservationMatrixEntries) fail$1(`${path}.observations`, `would exceed the ${HIDDEN_FLOW_LIMITS.maximumObservationMatrixEntries}-entry observation-matrix limit.`, "resource-limit-exceeded");
	for (const observation of observations) if (observation.coordinateFrameId !== domain.coordinateFrameId) fail$1(`${path}.observations`, `observation ${JSON.stringify(observation.id)} uses a different coordinate frame.`);
	const provenance = record$1(property$1(item, "provenance"), `${path}.provenance`);
	exactKeys$1(provenance, [
		"sourceKind",
		"citation",
		"license",
		"transformations"
	], `${path}.provenance`);
	return {
		schemaVersion: 1,
		id: identifier(property$1(item, "id"), `${path}.id`),
		title: text$1(property$1(item, "title"), `${path}.title`, 256),
		description: text$1(property$1(item, "description"), `${path}.description`),
		domain,
		basis,
		observations,
		budgets: parseBudgets(property$1(item, "budgets"), `${path}.budgets`),
		target: parseTarget(property$1(item, "target"), `${path}.target`),
		numerics: parseNumerics(property$1(item, "numerics"), `${path}.numerics`),
		provenance: {
			sourceKind: enumValue(property$1(provenance, "sourceKind"), ["generated", "declared"], `${path}.provenance.sourceKind`),
			citation: text$1(property$1(provenance, "citation"), `${path}.provenance.citation`),
			license: text$1(property$1(provenance, "license"), `${path}.provenance.license`, 256),
			transformations: stringArray$1(property$1(provenance, "transformations"), `${path}.provenance.transformations`, 32)
		},
		limitations: stringArray$1(property$1(item, "limitations"), `${path}.limitations`, 32)
	};
}
function validateDenseMatrix(matrix, path, expectedRows, expectedColumns, maximumEntries = HIDDEN_FLOW_LIMITS.maximumMatrixEntries) {
	if (!Number.isInteger(matrix.rows) || !Number.isInteger(matrix.columns) || matrix.rows < 0 || matrix.columns < 0) fail$1(path, "must declare nonnegative integer dimensions.");
	if (expectedRows !== void 0 && matrix.rows !== expectedRows) fail$1(path, `must have ${expectedRows} rows.`);
	if (expectedColumns !== void 0 && matrix.columns !== expectedColumns) fail$1(path, `must have ${expectedColumns} columns.`);
	const entries = matrix.rows * matrix.columns;
	if (entries > maximumEntries || matrix.values.length !== entries) fail$1(path, `must contain exactly ${entries} entries within the matrix resource limit.`, "resource-limit-exceeded");
	for (let index = 0; index < matrix.values.length; index += 1) if (!Number.isFinite(matrix.values[index])) fail$1(`${path}.values[${index}]`, "must be finite.");
}
//#endregion
//#region src/domain/hiddenFlowBasis.ts
var GAUSS_NODES = [
	-.8611363115940526,
	-.3399810435848563,
	.3399810435848563,
	.8611363115940526
];
var GAUSS_WEIGHTS = [
	.34785484513745385,
	.6521451548625461,
	.6521451548625461,
	.34785484513745385
];
function matrixIndex$1(columns, row, column) {
	return row * columns + column;
}
function cellIndex(xCellCount, xIndex, yIndex) {
	return xIndex + xCellCount * yIndex;
}
function evaluateCardinalCubic(value) {
	const absolute = Math.abs(value);
	if (absolute >= 2) return {
		value: 0,
		first: 0,
		second: 0
	};
	if (absolute < 1) return {
		value: 2 / 3 - absolute * absolute + absolute ** 3 / 2,
		first: -2 * value + 1.5 * value * absolute,
		second: -2 + 3 * absolute
	};
	const remaining = 2 - absolute;
	return {
		value: remaining ** 3 / 6,
		first: -.5 * Math.sign(value) * remaining * remaining,
		second: remaining
	};
}
function rawBasisEvaluation(center, spacingX, spacingY, streamfunctionLengthScale, point) {
	const x = evaluateCardinalCubic((point.x - center.x) / spacingX);
	const y = evaluateCardinalCubic((point.y - center.y) / spacingY);
	const common = streamfunctionLengthScale;
	const mixed = common / (spacingX * spacingY);
	return {
		u: common / spacingY * x.value * y.first,
		v: -(common / spacingX) * x.first * y.value,
		duDx: mixed * x.first * y.first,
		duDy: common / (spacingY * spacingY) * x.value * y.second,
		dvDx: -(common / (spacingX * spacingX)) * x.second * y.value,
		dvDy: -mixed * x.first * y.first
	};
}
function normalizedBasisEvaluation(basis, point) {
	const raw = rawBasisEvaluation(basis.center, basis.spacingX, basis.spacingY, basis.streamfunctionLengthScale, point);
	const scale = basis.velocityNormalization;
	return {
		u: raw.u / scale,
		v: raw.v / scale,
		duDx: raw.duDx / scale,
		duDy: raw.duDy / scale,
		dvDx: raw.dvDx / scale,
		dvDy: raw.dvDy / scale
	};
}
function erodedMask(domain, margin) {
	const xCellCount = domain.xEdges.length - 1;
	const yCellCount = domain.yEdges.length - 1;
	return domain.validCellMask.map((valid, index) => {
		if (!valid) return false;
		const xIndex = index % xCellCount;
		const yIndex = Math.floor(index / xCellCount);
		for (let yOffset = -margin; yOffset <= margin; yOffset += 1) for (let xOffset = -margin; xOffset <= margin; xOffset += 1) {
			const candidateX = xIndex + xOffset;
			const candidateY = yIndex + yOffset;
			if (candidateX < 0 || candidateX >= xCellCount || candidateY < 0 || candidateY >= yCellCount || !domain.validCellMask[cellIndex(xCellCount, candidateX, candidateY)]) return false;
		}
		return true;
	});
}
function supportInsideDomain(support, domain, admissibleMask) {
	const xMinimum = domain.xEdges[0];
	const xMaximum = domain.xEdges[domain.xEdges.length - 1];
	const yMinimum = domain.yEdges[0];
	const yMaximum = domain.yEdges[domain.yEdges.length - 1];
	const scale = Math.max(Math.abs(xMinimum), Math.abs(xMaximum), Math.abs(yMinimum), Math.abs(yMaximum), 1);
	const epsilon = 128 * Number.EPSILON * scale;
	if (support.xMinimum <= xMinimum + epsilon || support.xMaximum >= xMaximum - epsilon || support.yMinimum <= yMinimum + epsilon || support.yMaximum >= yMaximum - epsilon) return false;
	const xCellCount = domain.xEdges.length - 1;
	const yCellCount = domain.yEdges.length - 1;
	let intersected = false;
	for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) {
		const cellYMinimum = domain.yEdges[yIndex];
		if (domain.yEdges[yIndex + 1] <= support.yMinimum + epsilon || cellYMinimum >= support.yMaximum - epsilon) continue;
		for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
			const cellXMinimum = domain.xEdges[xIndex];
			if (domain.xEdges[xIndex + 1] <= support.xMinimum + epsilon || cellXMinimum >= support.xMaximum - epsilon) continue;
			intersected = true;
			if (!admissibleMask[cellIndex(xCellCount, xIndex, yIndex)]) return false;
		}
	}
	return intersected;
}
function validCells(domain) {
	const xCellCount = domain.xEdges.length - 1;
	const yCellCount = domain.yEdges.length - 1;
	const cells = [];
	for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
		if (!domain.validCellMask[cellIndex(xCellCount, xIndex, yIndex)]) continue;
		const xMinimum = domain.xEdges[xIndex];
		const xMaximum = domain.xEdges[xIndex + 1];
		const yMinimum = domain.yEdges[yIndex];
		const yMaximum = domain.yEdges[yIndex + 1];
		cells.push({
			xMinimum,
			xMaximum,
			yMinimum,
			yMaximum,
			area: (xMaximum - xMinimum) * (yMaximum - yMinimum)
		});
	}
	return cells;
}
function quadraturePoints(cell) {
	const halfWidth = (cell.xMaximum - cell.xMinimum) / 2;
	const halfHeight = (cell.yMaximum - cell.yMinimum) / 2;
	const centerX = (cell.xMinimum + cell.xMaximum) / 2;
	const centerY = (cell.yMinimum + cell.yMaximum) / 2;
	const jacobian = halfWidth * halfHeight;
	const points = [];
	for (let yIndex = 0; yIndex < GAUSS_NODES.length; yIndex += 1) for (let xIndex = 0; xIndex < GAUSS_NODES.length; xIndex += 1) points.push({
		point: {
			x: centerX + halfWidth * GAUSS_NODES[xIndex],
			y: centerY + halfHeight * GAUSS_NODES[yIndex]
		},
		weight: jacobian * GAUSS_WEIGHTS[xIndex] * GAUSS_WEIGHTS[yIndex]
	});
	return points;
}
function hiddenFlowSymmetricEigenvalues(matrix, dimension) {
	if (dimension === 0) return [];
	const values = [...matrix];
	const norm = Math.max(1, ...Array.from({ length: dimension }, (_, row) => Math.abs(values[matrixIndex$1(dimension, row, row)])));
	const tolerance = 64 * Number.EPSILON * norm;
	const maximumSweeps = 64;
	for (let sweep = 0; sweep < maximumSweeps; sweep += 1) {
		let changed = false;
		for (let p = 0; p < dimension - 1; p += 1) for (let q = p + 1; q < dimension; q += 1) {
			const pqIndex = matrixIndex$1(dimension, p, q);
			const apq = values[pqIndex];
			if (Math.abs(apq) <= tolerance) continue;
			changed = true;
			const app = values[matrixIndex$1(dimension, p, p)];
			const aqq = values[matrixIndex$1(dimension, q, q)];
			const angle = .5 * Math.atan2(2 * apq, aqq - app);
			const cosine = Math.cos(angle);
			const sine = Math.sin(angle);
			for (let k = 0; k < dimension; k += 1) {
				if (k === p || k === q) continue;
				const kpIndex = matrixIndex$1(dimension, k, p);
				const kqIndex = matrixIndex$1(dimension, k, q);
				const akp = values[kpIndex];
				const akq = values[kqIndex];
				const rotatedP = cosine * akp - sine * akq;
				const rotatedQ = sine * akp + cosine * akq;
				values[kpIndex] = rotatedP;
				values[matrixIndex$1(dimension, p, k)] = rotatedP;
				values[kqIndex] = rotatedQ;
				values[matrixIndex$1(dimension, q, k)] = rotatedQ;
			}
			values[matrixIndex$1(dimension, p, p)] = cosine * cosine * app - 2 * sine * cosine * apq + sine * sine * aqq;
			values[matrixIndex$1(dimension, q, q)] = sine * sine * app + 2 * sine * cosine * apq + cosine * cosine * aqq;
			values[pqIndex] = 0;
			values[matrixIndex$1(dimension, q, p)] = 0;
		}
		if (!changed) break;
	}
	return Array.from({ length: dimension }, (_, index) => values[matrixIndex$1(dimension, index, index)]).sort((left, right) => left - right);
}
function matrixDiagnostics(matrix, relativeTolerance) {
	const eigenvalues = hiddenFlowSymmetricEigenvalues(matrix.values, matrix.rows);
	const maximumEigenvalue = Math.max(...eigenvalues);
	const threshold = Math.max(relativeTolerance * Math.max(maximumEigenvalue, 1), 128 * Number.EPSILON * Math.max(maximumEigenvalue, 1));
	const positive = eigenvalues.filter((value) => value > threshold);
	return {
		rank: positive.length,
		conditionEstimate: positive.length === 0 ? Number.POSITIVE_INFINITY : maximumEigenvalue / positive[0],
		minimumEigenvalue: eigenvalues[0],
		maximumEigenvalue,
		threshold
	};
}
function integrateBasisMatrices(domain, functions) {
	const dimension = functions.length;
	const mass = Array(dimension * dimension).fill(0);
	const roughness = Array(dimension * dimension).fill(0);
	const cells = validCells(domain);
	const area = cells.reduce((sum, cell) => sum + cell.area, 0);
	let maximumVerificationDivergence = 0;
	for (const cell of cells) for (const quadrature of quadraturePoints(cell)) {
		const active = [];
		for (let index = 0; index < dimension; index += 1) {
			const basis = functions[index];
			if (quadrature.point.x <= basis.support.xMinimum || quadrature.point.x >= basis.support.xMaximum || quadrature.point.y <= basis.support.yMinimum || quadrature.point.y >= basis.support.yMaximum) continue;
			const value = normalizedBasisEvaluation(basis, quadrature.point);
			const divergence = value.duDx + value.dvDy;
			maximumVerificationDivergence = Math.max(maximumVerificationDivergence, Math.abs(divergence));
			if (value.u !== 0 || value.v !== 0 || value.duDx !== 0 || value.duDy !== 0 || value.dvDx !== 0 || value.dvDy !== 0) active.push({
				index,
				value
			});
		}
		for (const left of active) for (const right of active) {
			const index = matrixIndex$1(dimension, left.index, right.index);
			mass[index] += quadrature.weight * (left.value.u * right.value.u + left.value.v * right.value.v);
			roughness[index] += quadrature.weight * (left.value.duDx * right.value.duDx + left.value.duDy * right.value.duDy + left.value.dvDx * right.value.dvDx + left.value.dvDy * right.value.dvDy);
		}
	}
	for (let index = 0; index < mass.length; index += 1) {
		mass[index] /= area;
		roughness[index] /= area;
	}
	return {
		massMatrix: {
			rows: dimension,
			columns: dimension,
			values: mass
		},
		roughnessMatrix: {
			rows: dimension,
			columns: dimension,
			values: roughness
		},
		maximumVerificationDivergence,
		area
	};
}
function rawVelocityRms(domain, center, spec) {
	let integral = 0;
	let area = 0;
	for (const cell of validCells(domain)) {
		area += cell.area;
		for (const quadrature of quadraturePoints(cell)) {
			const value = rawBasisEvaluation(center, spec.spacingX, spec.spacingY, spec.streamfunctionLengthScale, quadrature.point);
			integral += quadrature.weight * (value.u * value.u + value.v * value.v);
		}
	}
	return Math.sqrt(integral / area);
}
function compileHiddenFlowBasis(domain, spec, numerics) {
	const admissibleMask = erodedMask(domain, spec.interiorMarginCells);
	const functions = [];
	let rejectedSupportCount = 0;
	for (const center of spec.centers) {
		const support = {
			xMinimum: center.point.x - 2 * spec.spacingX,
			xMaximum: center.point.x + 2 * spec.spacingX,
			yMinimum: center.point.y - 2 * spec.spacingY,
			yMaximum: center.point.y + 2 * spec.spacingY
		};
		if (!supportInsideDomain(support, domain, admissibleMask)) {
			rejectedSupportCount += 1;
			continue;
		}
		const velocityNormalization = rawVelocityRms(domain, center.point, spec);
		if (!Number.isFinite(velocityNormalization) || velocityNormalization <= numerics.verificationAbsoluteTolerance) throw new Error(`Basis function ${center.id} has zero or non-finite RMS velocity.`);
		functions.push({
			id: center.id,
			center: center.point,
			spacingX: spec.spacingX,
			spacingY: spec.spacingY,
			streamfunctionLengthScale: spec.streamfunctionLengthScale,
			velocityNormalization,
			support
		});
	}
	if (functions.length === 0) throw new Error("The compact-interior boundary policy rejected every basis function.");
	const integrated = integrateBasisMatrices(domain, functions);
	const mass = matrixDiagnostics(integrated.massMatrix, numerics.rankRelativeTolerance);
	const roughness = matrixDiagnostics(integrated.roughnessMatrix, numerics.rankRelativeTolerance);
	const diagnostics = {
		retainedCount: functions.length,
		rejectedSupportCount,
		domainArea: integrated.area,
		maximumVerificationDivergence: integrated.maximumVerificationDivergence,
		mass,
		roughness
	};
	for (const [label, result] of [["mass", mass], ["roughness", roughness]]) if (result.rank !== functions.length || result.minimumEigenvalue < -result.threshold || !Number.isFinite(result.conditionEstimate) || result.conditionEstimate > numerics.basisConditionLimit) throw new Error(`The ${label} matrix is singular, indefinite, or ill-conditioned: rank ${result.rank}/${functions.length}, condition ${result.conditionEstimate}.`);
	return {
		spec,
		functions,
		massMatrix: integrated.massMatrix,
		roughnessMatrix: integrated.roughnessMatrix,
		diagnostics
	};
}
function evaluateHiddenFlowBasisAtPoint(basis, point) {
	const evaluations = basis.functions.map((item) => normalizedBasisEvaluation(item, point));
	return {
		u: evaluations.map((item) => item.u),
		v: evaluations.map((item) => item.v),
		duDx: evaluations.map((item) => item.duDx),
		duDy: evaluations.map((item) => item.duDy),
		dvDx: evaluations.map((item) => item.dvDx),
		dvDy: evaluations.map((item) => item.dvDy),
		divergence: evaluations.map((item) => item.duDx + item.dvDy)
	};
}
function hiddenFlowCellIndexAtPoint(domain, point) {
	const xCellCount = domain.xEdges.length - 1;
	const yCellCount = domain.yEdges.length - 1;
	let xIndex = -1;
	let yIndex = -1;
	for (let index = 0; index < xCellCount; index += 1) {
		const last = index === xCellCount - 1;
		if (point.x >= domain.xEdges[index] && (point.x < domain.xEdges[index + 1] || last && point.x === domain.xEdges[index + 1])) {
			xIndex = index;
			break;
		}
	}
	for (let index = 0; index < yCellCount; index += 1) {
		const last = index === yCellCount - 1;
		if (point.y >= domain.yEdges[index] && (point.y < domain.yEdges[index + 1] || last && point.y === domain.yEdges[index + 1])) {
			yIndex = index;
			break;
		}
	}
	if (xIndex < 0 || yIndex < 0) return null;
	const index = cellIndex(xCellCount, xIndex, yIndex);
	return domain.validCellMask[index] ? index : null;
}
function hiddenFlowRegionComponentRow(domain, basis, cellIndices, component) {
	const selected = new Set(cellIndices);
	const xCellCount = domain.xEdges.length - 1;
	const yCellCount = domain.yEdges.length - 1;
	const row = Array(basis.functions.length).fill(0);
	let selectedArea = 0;
	for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
		const index = cellIndex(xCellCount, xIndex, yIndex);
		if (!selected.has(index) || !domain.validCellMask[index]) continue;
		const cell = {
			xMinimum: domain.xEdges[xIndex],
			xMaximum: domain.xEdges[xIndex + 1],
			yMinimum: domain.yEdges[yIndex],
			yMaximum: domain.yEdges[yIndex + 1],
			area: (domain.xEdges[xIndex + 1] - domain.xEdges[xIndex]) * (domain.yEdges[yIndex + 1] - domain.yEdges[yIndex])
		};
		selectedArea += cell.area;
		for (const quadrature of quadraturePoints(cell)) {
			const values = evaluateHiddenFlowBasisAtPoint(basis, quadrature.point);
			const componentValues = component === "x" ? values.u : values.v;
			for (let basisIndex = 0; basisIndex < row.length; basisIndex += 1) row[basisIndex] += quadrature.weight * componentValues[basisIndex];
		}
	}
	if (selectedArea <= 0) throw new Error("Region target does not contain any valid domain cell.");
	return row.map((value) => value / selectedArea);
}
//#endregion
//#region src/domain/hiddenFlowOperator.ts
function combineRows(first, second, firstScale, secondScale) {
	if (first.length !== second.length) throw new Error("Basis rows must have the same length.");
	return first.map((value, index) => firstScale * value + secondScale * second[index]);
}
function compileHiddenFlowPointVelocityRow(basis, point, component) {
	const evaluation = evaluateHiddenFlowBasisAtPoint(basis, point);
	return component === "x" ? evaluation.u : evaluation.v;
}
function pointDirectionRow(basis, point, direction) {
	const evaluation = evaluateHiddenFlowBasisAtPoint(basis, point);
	return combineRows(evaluation.u, evaluation.v, direction[0], direction[1]);
}
function compileHiddenFlowObservationRow(basis, observation) {
	return observation.type === "point-component" ? compileHiddenFlowPointVelocityRow(basis, observation.point, observation.component) : pointDirectionRow(basis, observation.point, observation.direction);
}
function ensurePointInDomain(problem, point, label) {
	if (hiddenFlowCellIndexAtPoint(problem.domain, point) === null) throw new Error(`${label} lies outside the declared valid-cell domain.`);
}
function compileTarget(problem, basis, target) {
	if (target.type === "point-component") {
		ensurePointInDomain(problem, target.point, `Target ${target.id}`);
		return {
			id: target.id,
			title: target.title,
			type: target.type,
			objective: compileHiddenFlowPointVelocityRow(basis, target.point, target.component),
			unit: target.unit,
			direction: null
		};
	}
	if (target.type === "point-direction") {
		ensurePointInDomain(problem, target.point, `Target ${target.id}`);
		return {
			id: target.id,
			title: target.title,
			type: target.type,
			objective: pointDirectionRow(basis, target.point, target.direction),
			unit: target.unit,
			direction: target.direction
		};
	}
	if (target.type === "region-component") {
		const maximumCellIndex = (problem.domain.xEdges.length - 1) * (problem.domain.yEdges.length - 1) - 1;
		if (target.cellIndices.some((cellIndex) => cellIndex < 0 || cellIndex > maximumCellIndex)) throw new Error(`Target ${target.id} references a cell outside the domain.`);
		return {
			id: target.id,
			title: target.title,
			type: target.type,
			objective: hiddenFlowRegionComponentRow(problem.domain, basis, target.cellIndices, target.component),
			unit: target.unit,
			direction: null
		};
	}
	ensurePointInDomain(problem, target.point, `Target ${target.id}`);
	const evaluation = evaluateHiddenFlowBasisAtPoint(basis, target.point);
	const objective = target.component === "xx" ? evaluation.duDx : target.component === "yy" ? evaluation.dvDy : combineRows(evaluation.duDy, evaluation.dvDx, .5, .5);
	return {
		id: target.id,
		title: target.title,
		type: target.type,
		objective,
		unit: target.unit,
		direction: null
	};
}
function compileHiddenFlowLinearSystem(problem, basis) {
	const rows = [];
	const lowerBounds = [];
	const upperBounds = [];
	for (const observation of problem.observations) {
		ensurePointInDomain(problem, observation.point, `Observation ${observation.id}`);
		for (const value of compileHiddenFlowObservationRow(basis, observation)) rows.push(value);
		const center = observation.observedValue - observation.baselineValue;
		lowerBounds.push(center - observation.tolerance);
		upperBounds.push(center + observation.tolerance);
	}
	return {
		observationMatrix: {
			rows: problem.observations.length,
			columns: basis.functions.length,
			values: rows
		},
		lowerBounds,
		upperBounds
	};
}
function compileHiddenFlowProblem(problem, basis, target) {
	return {
		problem: {
			...problem,
			target
		},
		basis,
		observations: compileHiddenFlowLinearSystem(problem, basis),
		target: compileTarget(problem, basis, target)
	};
}
function hiddenFlowDirections(count) {
	if (!Number.isInteger(count) || count < 3) throw new Error("Direction count must be an integer of at least three.");
	return Array.from({ length: count }, (_, index) => {
		const angle = 2 * Math.PI * index / count;
		return [Math.cos(angle), Math.sin(angle)];
	});
}
function compileHiddenFlowSpeedDirections(problem, basis) {
	if (problem.target.type !== "point-speed-envelope") throw new Error("The problem target is not a point-speed envelope.");
	const target = problem.target;
	return hiddenFlowDirections(target.directionCount).map((direction, index) => compileHiddenFlowProblem(problem, basis, {
		type: "point-direction",
		id: `${target.id}-direction-${index}`,
		title: `${target.title} direction ${index + 1}`,
		point: target.point,
		direction,
		unit: target.unit
	}));
}
var DEFAULT_HIDDEN_FLOW_SOLVER_SETTINGS = {
	maximumIterations: 250,
	absoluteGapTolerance: 1e-9,
	relativeGapTolerance: 1e-9,
	feasibilityTolerance: 1e-9,
	infeasibilityTolerance: 1e-9,
	presolveEnabled: true,
	equilibrationEnabled: true,
	iterativeRefinementEnabled: true,
	maximumThreads: 1
};
function squareMatrixCopy(matrix) {
	return {
		rows: matrix.rows,
		columns: matrix.columns,
		values: [...matrix.values]
	};
}
function createHiddenFlowSupportRequest(compiled, requestId) {
	return {
		schemaVersion: 1,
		requestId,
		problemId: compiled.problem.id,
		coefficientCount: compiled.basis.functions.length,
		observationMatrix: {
			rows: compiled.observations.observationMatrix.rows,
			columns: compiled.observations.observationMatrix.columns,
			values: [...compiled.observations.observationMatrix.values]
		},
		lowerBounds: [...compiled.observations.lowerBounds],
		upperBounds: [...compiled.observations.upperBounds],
		energyMatrix: squareMatrixCopy(compiled.basis.massMatrix),
		energyBudget: compiled.problem.budgets.velocityRms?.value ?? null,
		roughnessMatrix: squareMatrixCopy(compiled.basis.roughnessMatrix),
		roughnessBudget: compiled.problem.budgets.velocityGradientRms?.value ?? null,
		objective: [...compiled.target.objective],
		rankRelativeTolerance: compiled.problem.numerics.rankRelativeTolerance,
		solverSettings: {
			...DEFAULT_HIDDEN_FLOW_SOLVER_SETTINGS,
			maximumIterations: compiled.problem.numerics.maximumSolverIterations
		}
	};
}
//#endregion
//#region src/domain/hiddenFlowVerification.ts
function matrixIndex(columns, row, column) {
	return row * columns + column;
}
function dot(left, right) {
	if (left.length !== right.length) throw new Error("Vector dimensions do not match.");
	let value = 0;
	for (let index = 0; index < left.length; index += 1) value += left[index] * right[index];
	return value;
}
function matrixVector(matrix, vector) {
	if (matrix.columns !== vector.length) throw new Error("Matrix and vector dimensions do not match.");
	return Array.from({ length: matrix.rows }, (_, row) => {
		let value = 0;
		for (let column = 0; column < matrix.columns; column += 1) value += matrix.values[matrixIndex(matrix.columns, row, column)] * vector[column];
		return value;
	});
}
function transposeMatrixVector(matrix, vector) {
	if (matrix.rows !== vector.length) throw new Error("Transposed matrix and vector dimensions do not match.");
	return Array.from({ length: matrix.columns }, (_, column) => {
		let value = 0;
		for (let row = 0; row < matrix.rows; row += 1) value += matrix.values[matrixIndex(matrix.columns, row, column)] * vector[row];
		return value;
	});
}
function quadratic(matrix, vector) {
	return dot(vector, matrixVector(matrix, vector));
}
function maximumAbsolute(values) {
	return values.reduce((maximum, value) => Math.max(maximum, Math.abs(value)), 0);
}
function differenceMaximum(left, right) {
	if (left.length !== right.length) return Number.POSITIVE_INFINITY;
	return left.reduce((maximum, value, index) => Math.max(maximum, Math.abs(value - right[index])), 0);
}
function tolerance(absoluteTolerance, relativeTolerance, ...scales) {
	return absoluteTolerance + relativeTolerance * Math.max(1, ...scales.map((value) => Math.abs(value)));
}
function matrixScale(matrix) {
	return maximumAbsolute(matrix.values);
}
function verifyFactor(factor, original, expectedPresent, absoluteTolerance, relativeTolerance) {
	if (!expectedPresent) return factor === null ? 0 : Number.POSITIVE_INFINITY;
	if (factor === null || factor.rows !== original.rows || factor.columns !== original.columns) return Number.POSITIVE_INFINITY;
	let maximumDifference = 0;
	for (let row = 0; row < original.rows; row += 1) for (let column = 0; column < original.columns; column += 1) {
		let reconstructed = 0;
		for (let factorRow = 0; factorRow < factor.rows; factorRow += 1) reconstructed += factor.values[matrixIndex(factor.columns, factorRow, row)] * factor.values[matrixIndex(factor.columns, factorRow, column)];
		maximumDifference = Math.max(maximumDifference, Math.abs(reconstructed - original.values[matrixIndex(original.columns, row, column)]));
	}
	const allowed = tolerance(absoluteTolerance, relativeTolerance, matrixScale(original));
	return maximumDifference <= allowed ? maximumDifference : Number.POSITIVE_INFINITY;
}
function expectedCanonicalization(request, energyFactor, roughnessFactor) {
	const rows = [];
	const b = [];
	const cones = [];
	const appendObservationRows = (indices, sign, bounds, cone) => {
		if (indices.length === 0) return;
		for (const row of indices) {
			for (let column = 0; column < request.observationMatrix.columns; column += 1) rows.push(sign * request.observationMatrix.values[matrixIndex(request.observationMatrix.columns, row, column)]);
			b.push(sign * bounds[row]);
		}
		cones.push(cone);
	};
	const exact = [];
	const bands = [];
	for (let index = 0; index < request.lowerBounds.length; index += 1) if (request.lowerBounds[index] === request.upperBounds[index]) exact.push(index);
	else bands.push(index);
	if ((exact.length + 2 * bands.length + (energyFactor === null || request.energyBudget === null ? 0 : energyFactor.rows + 1) + (roughnessFactor === null || request.roughnessBudget === null ? 0 : roughnessFactor.rows + 1)) * request.coefficientCount > HIDDEN_FLOW_LIMITS.maximumCanonicalMatrixEntries) throw new HiddenFlowInputError("resource-limit-exceeded", "hiddenFlowCanonicalization.a", `would exceed the ${HIDDEN_FLOW_LIMITS.maximumCanonicalMatrixEntries}-entry limit.`);
	appendObservationRows(exact, 1, request.upperBounds, {
		type: "zero",
		dimension: exact.length,
		label: "observation-exact"
	});
	appendObservationRows(bands, 1, request.upperBounds, {
		type: "nonnegative",
		dimension: bands.length,
		label: "observation-upper"
	});
	appendObservationRows(bands, -1, request.lowerBounds, {
		type: "nonnegative",
		dimension: bands.length,
		label: "observation-lower"
	});
	const appendBudget = (factor, budget, label) => {
		if (factor === null || budget === null) return;
		for (let index = 0; index < request.coefficientCount; index += 1) rows.push(0);
		b.push(budget);
		for (const value of factor.values) rows.push(value);
		for (let index = 0; index < factor.rows; index += 1) b.push(0);
		cones.push({
			type: "second-order",
			dimension: factor.rows + 1,
			label: `${label}-budget`
		});
	};
	appendBudget(energyFactor, request.energyBudget, "energy");
	appendBudget(roughnessFactor, request.roughnessBudget, "roughness");
	return {
		q: request.objective.map((value) => -value),
		a: {
			rows: b.length,
			columns: request.coefficientCount,
			values: rows
		},
		b,
		cones
	};
}
function conesEqual(left, right) {
	return left.length === right.length && left.every((cone, index) => cone.type === right[index].type && cone.dimension === right[index].dimension && cone.label === right[index].label);
}
function coneViolation(values, cones, dual) {
	let offset = 0;
	let maximum = 0;
	for (const cone of cones) {
		const block = values.slice(offset, offset + cone.dimension);
		if (block.length !== cone.dimension) return Number.POSITIVE_INFINITY;
		if (cone.type === "zero") {
			if (!dual) maximum = Math.max(maximum, maximumAbsolute(block));
		} else if (cone.type === "nonnegative") maximum = Math.max(maximum, block.reduce((violation, value) => Math.max(violation, Math.max(0, -value)), 0));
		else {
			const head = block[0];
			const tailNorm = Math.hypot(...block.slice(1));
			maximum = Math.max(maximum, Math.max(0, tailNorm - head));
		}
		offset += cone.dimension;
	}
	return offset === values.length ? maximum : Number.POSITIVE_INFINITY;
}
function independentSingularValues(matrix) {
	const gram = Array(matrix.columns * matrix.columns).fill(0);
	for (let left = 0; left < matrix.columns; left += 1) for (let right = 0; right < matrix.columns; right += 1) {
		let value = 0;
		for (let row = 0; row < matrix.rows; row += 1) value += matrix.values[matrixIndex(matrix.columns, row, left)] * matrix.values[matrixIndex(matrix.columns, row, right)];
		gram[matrixIndex(matrix.columns, left, right)] = value;
	}
	return Array.from(hiddenFlowSymmetricEigenvalues(gram, matrix.columns)).sort((left, right) => right - left).slice(0, Math.min(matrix.rows, matrix.columns)).map((value) => Math.sqrt(Math.max(0, value)));
}
function independentMatrixRank(matrix, threshold) {
	const values = [...matrix.values];
	const rowCount = matrix.rows;
	const columnCount = matrix.columns;
	let rank = 0;
	while (rank < rowCount && rank < columnCount) {
		let pivotRow = -1;
		let pivotColumn = -1;
		let pivotMagnitude = 0;
		for (let row = rank; row < rowCount; row += 1) for (let column = rank; column < columnCount; column += 1) {
			const magnitude = Math.abs(values[matrixIndex(columnCount, row, column)]);
			if (magnitude > pivotMagnitude) {
				pivotMagnitude = magnitude;
				pivotRow = row;
				pivotColumn = column;
			}
		}
		if (pivotMagnitude <= threshold) break;
		if (pivotRow !== rank) for (let column = 0; column < columnCount; column += 1) {
			const left = matrixIndex(columnCount, rank, column);
			const right = matrixIndex(columnCount, pivotRow, column);
			const temporary = values[left];
			values[left] = values[right];
			values[right] = temporary;
		}
		if (pivotColumn !== rank) for (let row = 0; row < rowCount; row += 1) {
			const left = matrixIndex(columnCount, row, rank);
			const right = matrixIndex(columnCount, row, pivotColumn);
			const temporary = values[left];
			values[left] = values[right];
			values[right] = temporary;
		}
		const pivot = values[matrixIndex(columnCount, rank, rank)];
		for (let row = rank + 1; row < rowCount; row += 1) {
			const factor = values[matrixIndex(columnCount, row, rank)] / pivot;
			values[matrixIndex(columnCount, row, rank)] = 0;
			for (let column = rank + 1; column < columnCount; column += 1) values[matrixIndex(columnCount, row, column)] -= factor * values[matrixIndex(columnCount, rank, column)];
		}
		rank += 1;
	}
	return rank;
}
function hiddenFlowIndependentObservationDiagnostics(matrix, relativeTolerance) {
	const singularValues = independentSingularValues(matrix);
	const maximum = singularValues[0] ?? 0;
	const threshold = Math.max(relativeTolerance * maximum, 128 * Number.EPSILON * Math.max(maximum, 1));
	const rank = independentMatrixRank(matrix, threshold);
	return {
		singularValues,
		rank,
		nullity: matrix.columns - rank,
		threshold,
		spectrumFloor: Math.sqrt(Number.EPSILON) * Math.max(maximum, 1) * 4
	};
}
function verifySvd(request, result, absoluteTolerance, relativeTolerance) {
	const diagnostics = hiddenFlowIndependentObservationDiagnostics(request.observationMatrix, request.rankRelativeTolerance);
	const expected = diagnostics.singularValues;
	const maximum = expected[0] ?? 0;
	const { threshold, rank, spectrumFloor } = diagnostics;
	const spectrumViolation = expected.reduce((current, value, index) => {
		const reported = result.svd.singularValues[index];
		return Math.max(value, reported) <= spectrumFloor ? current : Math.max(current, Math.abs(value - reported));
	}, 0);
	const allowed = tolerance(absoluteTolerance, relativeTolerance, maximum, matrixScale(request.observationMatrix));
	if (Math.abs(result.svd.threshold - threshold) > allowed) return "The returned SVD threshold does not match the declared rule.";
	if (result.svd.rank !== rank || result.svd.nullity !== request.coefficientCount - rank) return "The direct SVD and independent complete-pivoting rank estimators disagree at the declared threshold.";
	if (spectrumViolation > allowed) return "The returned singular spectrum disagrees with the independent A-transpose-A check above its square-root-epsilon floor.";
	const expectedCondition = rank === 0 ? null : result.svd.singularValues[0] / result.svd.singularValues[rank - 1];
	if (expectedCondition === null !== (result.svd.conditionEstimate === null) || expectedCondition !== null && result.svd.conditionEstimate !== null && Math.abs(expectedCondition - result.svd.conditionEstimate) > allowed) return "The returned SVD condition estimate is inconsistent with its spectrum.";
	const nullBasis = result.svd.nullSpaceBasis;
	let nullViolation = 0;
	for (let column = 0; column < nullBasis.columns; column += 1) {
		const vector = Array.from({ length: nullBasis.rows }, (_, row) => nullBasis.values[matrixIndex(nullBasis.columns, row, column)]);
		nullViolation = Math.max(nullViolation, maximumAbsolute(matrixVector(request.observationMatrix, vector)));
		for (let otherColumn = 0; otherColumn < nullBasis.columns; otherColumn += 1) {
			const other = Array.from({ length: nullBasis.rows }, (_, row) => nullBasis.values[matrixIndex(nullBasis.columns, row, otherColumn)]);
			nullViolation = Math.max(nullViolation, Math.abs(dot(vector, other) - (column === otherColumn ? 1 : 0)));
		}
	}
	return nullViolation <= allowed ? null : "The returned null-space basis fails residual or orthonormality checks.";
}
function maximumObservationViolation(compiled, coefficients) {
	const values = matrixVector(compiled.observations.observationMatrix, coefficients);
	let maximum = 0;
	const active = [];
	const absoluteTolerance = compiled.problem.numerics.verificationAbsoluteTolerance;
	const relativeTolerance = compiled.problem.numerics.verificationRelativeTolerance;
	for (let index = 0; index < values.length; index += 1) {
		const lower = compiled.observations.lowerBounds[index];
		const upper = compiled.observations.upperBounds[index];
		maximum = Math.max(maximum, Math.max(0, lower - values[index], values[index] - upper));
		const allowed = tolerance(absoluteTolerance, relativeTolerance, lower, upper, values[index]);
		if (Math.abs(values[index] - lower) <= allowed || Math.abs(values[index] - upper) <= allowed) active.push(compiled.problem.observations[index].id);
	}
	return {
		maximum,
		active
	};
}
function hiddenFlowCandidateMaximumDivergence(compiled, coefficients) {
	const domain = compiled.problem.domain;
	const xCellCount = domain.xEdges.length - 1;
	const yCellCount = domain.yEdges.length - 1;
	let maximum = 0;
	for (let yIndex = 0; yIndex < yCellCount; yIndex += 1) for (let xIndex = 0; xIndex < xCellCount; xIndex += 1) {
		const cellIndex = xIndex + xCellCount * yIndex;
		if (!domain.validCellMask[cellIndex]) continue;
		const xMinimum = domain.xEdges[xIndex];
		const xMaximum = domain.xEdges[xIndex + 1];
		const yMinimum = domain.yEdges[yIndex];
		const yMaximum = domain.yEdges[yIndex + 1];
		for (const yFraction of [
			.25,
			.5,
			.75
		]) for (const xFraction of [
			.25,
			.5,
			.75
		]) {
			const evaluation = evaluateHiddenFlowBasisAtPoint(compiled.basis, {
				x: xMinimum + xFraction * (xMaximum - xMinimum),
				y: yMinimum + yFraction * (yMaximum - yMinimum)
			});
			maximum = Math.max(maximum, Math.abs(dot(evaluation.divergence, coefficients)));
		}
	}
	return maximum;
}
function failed(detail) {
	return {
		accepted: false,
		state: "failed",
		detail,
		objectiveValue: null,
		rigorousObjectiveUpperBound: null,
		approximateDualUpperDiagnostic: null,
		upperBoundQualification: "not-applicable",
		observationMaximumViolation: null,
		activeObservationConstraints: [],
		velocityRms: null,
		velocityGradientRms: null,
		maximumVerificationDivergence: null,
		primalResidual: null,
		dualResidual: null,
		absoluteGap: null,
		relativeGap: null,
		coneViolation: null,
		numericalEvidenceQualification: "not-applicable"
	};
}
function stateDetail(state) {
	if (state === "verified-optimal-within-tolerance") return "The feasible candidate and approximate dual diagnostics independently satisfy the declared numerical tolerances for this finite conic problem; no rigorous objective upper bound is established.";
	if (state === "approximate-candidate") return "A primal-feasible candidate was found, but the native solver status or dual evidence does not support a verified optimum.";
	if (state === "verified-infeasible-within-tolerance") return "The returned dual ray independently satisfies the declared numerical infeasibility checks.";
	if (state === "verified-unbounded-within-tolerance") return "The returned primal ray independently satisfies the declared numerical unboundedness checks.";
	if (state === "full-observation-zero-nullity") return "The exact zero-residual observation operator has zero numerical nullity in the declared basis.";
	if (state === "degenerate-objective") return "The declared target row is numerically zero in the retained basis, so no optimizer result is presented.";
	return "The solver result did not support an accepted evidence state.";
}
function settingsEqual(left, right) {
	return left.maximumIterations === right.maximumIterations && left.absoluteGapTolerance === right.absoluteGapTolerance && left.relativeGapTolerance === right.relativeGapTolerance && left.feasibilityTolerance === right.feasibilityTolerance && left.infeasibilityTolerance === right.infeasibilityTolerance && left.presolveEnabled === right.presolveEnabled && left.equilibrationEnabled === right.equilibrationEnabled && left.iterativeRefinementEnabled === right.iterativeRefinementEnabled && left.maximumThreads === right.maximumThreads;
}
function verifyHiddenFlowSupportResult(compiled, request, solverResult, hashes) {
	const absoluteTolerance = compiled.problem.numerics.verificationAbsoluteTolerance;
	const relativeTolerance = compiled.problem.numerics.verificationRelativeTolerance;
	if (!hashes.requestMatches || !hashes.canonicalMatches) return {
		request,
		solverResult,
		verification: failed("Request or canonical solver-data hash mismatch.")
	};
	if (!settingsEqual(request.solverSettings, solverResult.settings) || solverResult.requestId !== request.requestId) return {
		request,
		solverResult,
		verification: failed("Solver settings or request identity changed.")
	};
	const factorViolation = Math.max(verifyFactor(solverResult.canonicalization.energyFactor, request.energyMatrix, request.energyBudget !== null, absoluteTolerance, relativeTolerance), verifyFactor(solverResult.canonicalization.roughnessFactor, request.roughnessMatrix, request.roughnessBudget !== null, absoluteTolerance, relativeTolerance));
	if (!Number.isFinite(factorViolation)) return {
		request,
		solverResult,
		verification: failed("A returned quadratic factor does not reconstruct the declared matrix.")
	};
	const expected = expectedCanonicalization(request, solverResult.canonicalization.energyFactor, solverResult.canonicalization.roughnessFactor);
	const canonicalTolerance = tolerance(absoluteTolerance, relativeTolerance, matrixScale(expected.a), maximumAbsolute(expected.b), maximumAbsolute(expected.q));
	if (!conesEqual(expected.cones, solverResult.canonicalization.cones) || differenceMaximum(expected.q, solverResult.canonicalization.q) > canonicalTolerance || differenceMaximum(expected.b, solverResult.canonicalization.b) > canonicalTolerance || differenceMaximum(expected.a.values, solverResult.canonicalization.a.values) > canonicalTolerance) return {
		request,
		solverResult,
		verification: failed("The returned conic form does not match the declared observations, budgets, and target.")
	};
	const svdFailure = verifySvd(request, solverResult, absoluteTolerance, relativeTolerance);
	if (svdFailure !== null) return {
		request,
		solverResult,
		verification: failed(svdFailure)
	};
	const solution = solverResult.solution;
	const canonical = solverResult.canonicalization;
	const primalTolerance = tolerance(absoluteTolerance, relativeTolerance, matrixScale(canonical.a), maximumAbsolute(canonical.b), maximumAbsolute(solution.coefficients));
	const originalConstraintTolerance = tolerance(absoluteTolerance, relativeTolerance, matrixScale(request.observationMatrix), maximumAbsolute(request.lowerBounds), maximumAbsolute(request.upperBounds), request.energyBudget ?? 0, request.roughnessBudget ?? 0);
	const dualTolerance = tolerance(absoluteTolerance, relativeTolerance, matrixScale(canonical.a), maximumAbsolute(canonical.q), maximumAbsolute(solution.dual));
	const slackMismatch = differenceMaximum(matrixVector(canonical.a, solution.coefficients).map((value, index) => canonical.b[index] - value), solution.slacks);
	const primalResidual = slackMismatch;
	const primalConeViolation = coneViolation(solution.slacks, canonical.cones, false);
	const transposedDual = transposeMatrixVector(canonical.a, solution.dual);
	const dualResidual = maximumAbsolute(transposedDual.map((value, index) => value + canonical.q[index]));
	const infeasibilityDualResidual = maximumAbsolute(transposedDual);
	const dualConeViolation = coneViolation(solution.dual, canonical.cones, true);
	const coneMaximum = Math.max(primalConeViolation, dualConeViolation);
	const primalObjective = dot(canonical.q, solution.coefficients);
	const dualObjective = -dot(canonical.b, solution.dual);
	const absoluteGap = primalObjective - dualObjective;
	const relativeGap = Math.abs(absoluteGap) / Math.max(Math.abs(primalObjective), Math.abs(dualObjective), 1);
	const objectiveValue = dot(request.objective, solution.coefficients);
	const unboundedPrimalResidual = maximumAbsolute(matrixVector(canonical.a, solution.coefficients).map((value, index) => value + solution.slacks[index]));
	const observation = maximumObservationViolation(compiled, solution.coefficients);
	const energyValue = Math.sqrt(Math.max(0, quadratic(request.energyMatrix, solution.coefficients)));
	const roughnessValue = Math.sqrt(Math.max(0, quadratic(request.roughnessMatrix, solution.coefficients)));
	const divergence = hiddenFlowCandidateMaximumDivergence(compiled, solution.coefficients);
	const energyViolation = request.energyBudget === null ? 0 : Math.max(0, energyValue - request.energyBudget);
	const roughnessViolation = request.roughnessBudget === null ? 0 : Math.max(0, roughnessValue - request.roughnessBudget);
	const originalFeasible = observation.maximum <= originalConstraintTolerance && energyViolation <= originalConstraintTolerance && roughnessViolation <= originalConstraintTolerance && divergence <= originalConstraintTolerance;
	const objectiveEvidenceMatches = (solution.primalObjective === null || Math.abs(solution.primalObjective - primalObjective) <= primalTolerance) && (solution.dualObjective === null || Math.abs(solution.dualObjective - dualObjective) <= dualTolerance);
	let state = "failed";
	let accepted = false;
	let qualification = "not-applicable";
	const objectiveScale = maximumAbsolute(request.objective);
	const objectiveZero = objectiveScale <= 128 * Number.EPSILON * Math.max(objectiveScale, 1);
	const exactZeroObservations = request.lowerBounds.every((value, index) => value === 0 && request.upperBounds[index] === 0);
	const coefficientScale = maximumAbsolute(solution.coefficients);
	if (solution.status === "PrimalInfeasible" || solution.status === "AlmostPrimalInfeasible") {
		const rayResidual = infeasibilityDualResidual;
		const rayConeViolation = dualConeViolation;
		const raySeparation = dot(canonical.b, solution.dual);
		if (solution.status === "PrimalInfeasible" && rayResidual <= dualTolerance && rayConeViolation <= dualTolerance && raySeparation < -dualTolerance) {
			state = "verified-infeasible-within-tolerance";
			accepted = true;
			qualification = "verified-to-declared-tolerances";
		}
	} else if (solution.status === "DualInfeasible" || solution.status === "AlmostDualInfeasible") {
		const rayObjective = dot(canonical.q, solution.coefficients);
		if (solution.status === "DualInfeasible" && unboundedPrimalResidual <= primalTolerance && primalConeViolation <= primalTolerance && rayObjective < -primalTolerance) {
			state = "verified-unbounded-within-tolerance";
			accepted = true;
			qualification = "verified-to-declared-tolerances";
		}
	} else if (originalFeasible && slackMismatch <= primalTolerance && objectiveEvidenceMatches) {
		if (solverResult.svd.nullity === 0 && exactZeroObservations && coefficientScale <= primalTolerance) {
			state = "full-observation-zero-nullity";
			accepted = true;
			qualification = "verified-to-declared-tolerances";
		} else if (objectiveZero && solution.status === "Solved" && primalConeViolation <= primalTolerance && solverResult.warnings.some((warning) => warning.startsWith("Degenerate objective:"))) {
			state = "degenerate-objective";
			accepted = true;
			qualification = "verified-to-declared-tolerances";
		} else if (solution.status === "Solved" && primalConeViolation <= primalTolerance && dualResidual <= dualTolerance && dualConeViolation <= dualTolerance && absoluteGap >= -dualTolerance && absoluteGap <= Math.max(solverResult.settings.absoluteGapTolerance, solverResult.settings.relativeGapTolerance * Math.max(Math.abs(primalObjective), Math.abs(dualObjective), 1), primalTolerance, dualTolerance)) {
			state = "verified-optimal-within-tolerance";
			accepted = true;
			qualification = "verified-to-declared-tolerances";
		} else if (solution.status === "AlmostSolved" || solution.status === "MaxIterations" || solution.status === "MaxTime" || solution.status === "InsufficientProgress") {
			state = "approximate-candidate";
			accepted = true;
			qualification = "candidate-only";
		}
	}
	return {
		request,
		solverResult,
		verification: {
			accepted,
			state,
			detail: stateDetail(state),
			objectiveValue: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" || state === "degenerate-objective" ? null : state === "full-observation-zero-nullity" ? 0 : objectiveValue,
			rigorousObjectiveUpperBound: null,
			approximateDualUpperDiagnostic: !accepted || solution.dualObjective === null || state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : -dualObjective,
			upperBoundQualification: state === "verified-optimal-within-tolerance" || state === "approximate-candidate" || state === "full-observation-zero-nullity" || state === "degenerate-objective" ? "unavailable-no-rigorous-dual-certificate" : "not-applicable",
			observationMaximumViolation: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : observation.maximum,
			activeObservationConstraints: observation.active,
			velocityRms: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : energyValue,
			velocityGradientRms: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : roughnessValue,
			maximumVerificationDivergence: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : divergence,
			primalResidual: state === "verified-infeasible-within-tolerance" ? null : state === "verified-unbounded-within-tolerance" ? unboundedPrimalResidual : primalResidual,
			dualResidual: state === "verified-infeasible-within-tolerance" ? infeasibilityDualResidual : state === "verified-unbounded-within-tolerance" ? null : dualResidual,
			absoluteGap: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : absoluteGap,
			relativeGap: state === "verified-infeasible-within-tolerance" || state === "verified-unbounded-within-tolerance" ? null : relativeGap,
			coneViolation: state === "verified-infeasible-within-tolerance" ? dualConeViolation : state === "verified-unbounded-within-tolerance" ? primalConeViolation : coneMaximum,
			numericalEvidenceQualification: qualification
		}
	};
}
//#endregion
//#region src/application/evidenceReport.ts
function isRecord(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}
function stableValue(value) {
	if (Array.isArray(value)) return value.map(stableValue);
	if (isRecord(value)) {
		const result = {};
		for (const key of Object.keys(value).sort()) result[key] = stableValue(value[key]);
		return result;
	}
	if (value === null || typeof value === "string" || typeof value === "boolean") return value;
	if (typeof value === "number" && Number.isFinite(value)) return value;
	throw new Error("Evidence reports may contain only finite JSON values.");
}
function stableJson$1(value) {
	return `${JSON.stringify(stableValue(value), null, 2)}\n`;
}
function escapeMarkdown(value) {
	return value.replace(/[\u202a-\u202e\u2066-\u2069]/gu, (character) => `bidi-control-U${character.codePointAt(0)?.toString(16).toUpperCase()}`).replace(/&/gu, "&amp;").replace(/</gu, "&lt;").replace(/>/gu, "&gt;").replace(/[\r\n]+/gu, " ").replace(/([\\*_[\]{}()#+!|])/gu, "\\$1").replace(/:/gu, "&#58;").replace(/`/gu, "&#96;");
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
function validateFlowBlindOptionalDisplayText(value, label, maximumCodePoints = FLOWBLIND_MAX_DISPLAY_TEXT_CODE_POINTS) {
	return value === null ? null : validateFlowBlindDisplayText(value, label, maximumCodePoints);
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/profile.ts
function deepFreeze(value) {
	if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
		for (const nested of Object.values(value)) deepFreeze(nested);
		Object.freeze(value);
	}
	return value;
}
var FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION = "1.1.0";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION = "1.0.0";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID = "finite-basis-hidden-flow-v1";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY = "finite-basis-observation-compatible-hidden-flow-v1";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION = "prepare-study";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION = "run-and-verify-study";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS = [FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION, FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION];
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_ID = "flowblind-catalog-hidden-flow-generic-review-policy-v1";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION = "1.0.0";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION = "attested-generic-hidden-flow-problem-authority-v1";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE = "generic-problem-contract-parser-and-executable-preflight-only";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY = "finite-basis-declared-model-only-no-physical-truth-source-validity-or-clinical-inference";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES = ["point-component", "point-direction"];
var FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES = [
	"point-component",
	"point-direction",
	"point-speed-envelope",
	"region-component",
	"point-strain-component"
];
var FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-preparation-bundle-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_VERIFIED_RUN_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-verified-run-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_PROBLEM_ACCEPTANCE_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REPORT_VERIFICATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-report-verification-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-review-policy-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_ATTESTATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-review-attestation-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION_SCHEMA_ID = "https://flowblind.local/schemas/flowblind-catalog-hidden-flow-declaration-v1.schema.json";
var FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES = HIDDEN_FLOW_LIMITS.maximumDocumentBytes + 1048576;
var FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES = 134217728;
var FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES = HIDDEN_FLOW_LIMITS.maximumDocumentBytes;
var FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS = deepFreeze({ ...HIDDEN_FLOW_LIMITS });
var FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME = deepFreeze({
	platform: "linux/amd64",
	nodeImage: "node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94",
	pythonImage: "python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79",
	pythonRequirementsSha256: "1ffda1962375e2d2d77b794b7a930d55902869a2923e695ad333a3f8e0d7a4ed",
	pythonPackages: deepFreeze([
		{
			requirement: "clarabel==0.11.1",
			sha256: "c8c41aaa6f3f8c0f3bd9d86c3e568dcaee079562c075bd2ec9fb3a80287380ef"
		},
		{
			requirement: "cffi==2.1.1",
			sha256: "c1453022f490d2459a11819d83ad1d586e9ff65a12ac3e705ffebd46d3685dcf"
		},
		{
			requirement: "numpy==2.2.6",
			sha256: "fd83c01228a688733f1ded5201c678f0c53ecc1006ffbc404db9f7a899ac6249"
		},
		{
			requirement: "pycparser==3.0",
			sha256: "b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992"
		},
		{
			requirement: "scipy==1.15.3",
			sha256: "271e3713e645149ea5ea3e97b57fdab61ce61333f97cfae392c28ba786f9bb49"
		}
	]),
	solverModule: "tools.hidden_flow_solver",
	solverAdapter: "PinnedPythonProcessHiddenFlowSolverAdapter",
	solverIdentity: {
		adapter: "flowblind-hidden-flow-direct-clarabel",
		adapterVersion: "1.0.0",
		pythonVersion: "3.12.14",
		clarabelVersion: "0.11.1",
		scipyVersion: "1.15.3",
		numpyVersion: "2.2.6",
		image: "python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79",
		architecture: "x86_64",
		linearSolverPrefix: "qdldl;direct=true;threads=1;"
	},
	maximumThreads: 1,
	networkRequiredAtRuntime: false,
	confinement: {
		user: "10001:10001",
		rootFilesystem: "read-only",
		temporaryFilesystem: "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777",
		network: "none",
		noNewPrivileges: true,
		childProcessTimeoutMilliseconds: 6e4,
		maximumStdoutStderrBytes: 1048576
	},
	requiredEnvironment: {
		PYTHONDONTWRITEBYTECODE: "1",
		PYTHONUNBUFFERED: "1",
		PYTHONHASHSEED: "0",
		OMP_NUM_THREADS: "1",
		OPENBLAS_NUM_THREADS: "1",
		OPENBLAS_CORETYPE: "NEHALEM",
		MKL_NUM_THREADS: "1",
		NUMEXPR_NUM_THREADS: "1",
		VECLIB_MAXIMUM_THREADS: "1",
		BLIS_NUM_THREADS: "1"
	}
});
var FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY = deepFreeze({
	$schema: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_SCHEMA_ID,
	schemaVersion: 1,
	id: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_ID,
	policyVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
	authorityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
	reviewScope: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
	subject: {
		capabilityId: FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
		capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
		methodFamily: FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
		problemSchemaVersion: 1,
		genericProblemSchema: "https://flowblind.local/schemas/hidden-flow-problem.schema.json",
		genericProblemSchemaRole: "syntactic-prefilter-only",
		problemAcceptanceSchema: FLOWBLIND_CATALOG_HIDDEN_FLOW_PROBLEM_ACCEPTANCE_SCHEMA_ID,
		parser: "parseHiddenFlowProblem",
		canonicalization: "stable-json-v1",
		allowedObservationTypes: FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES,
		allowedTargetTypes: FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES,
		resourceLimits: FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
		executablePreflight: "compile-basis-and-all-solver-requests-without-solving"
	},
	runtime: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
	claimBoundary: FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY,
	assertions: {
		genericProblemContract: "attested",
		canonicalProblemBytes: "attested",
		parserAcceptance: "attested",
		allowedObservationAndTargetTypes: "attested",
		resourceLimits: "attested",
		executablePreflight: "attested",
		solverRuntime: "attested",
		neutralFiniteBasisClaims: "attested",
		physicalTruth: "not-attested",
		sourceAccuracy: "not-attested",
		measurementValidity: "not-attested",
		clinicalUse: "not-attested",
		modelOrUserApproval: "not-accepted-as-authority"
	},
	authorityInput: "host-selected-canonical-problem-bytes-only"
});
var FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA = deepFreeze({
	type: "object",
	properties: {
		goal: {
			type: "string",
			minLength: 1,
			maxLength: 4096,
			title: "Research goal",
			description: "Describe the hidden-flow robustness question in ordinary scientific language."
		},
		details: {
			type: ["string", "null"],
			minLength: 1,
			maxLength: 4096,
			title: "Additional details",
			description: "Optional ordinary-language context for interpreting the already selected canonical problem."
		}
	},
	required: ["goal"],
	additionalProperties: false
});
var catalogHiddenFlowToolDefinitions = deepFreeze([{
	name: FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARE_ACTION,
	title: "Prepare a reviewed finite-basis hidden-flow study",
	description: "Attest one host-selected canonical generic hidden-flow problem and emit a deterministic result-free preparation bundle.",
	inputSchema: FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA,
	annotations: {
		readOnlyHint: true,
		destructiveHint: false,
		idempotentHint: true,
		openWorldHint: false
	}
}, {
	name: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUN_ACTION,
	title: "Run and verify a prepared finite-basis hidden-flow study",
	description: "After host confirmation, re-attest the generic problem, run only the pinned Clarabel closure, independently verify it, and require deterministic replay.",
	inputSchema: FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA,
	annotations: {
		readOnlyHint: false,
		destructiveHint: false,
		idempotentHint: true,
		openWorldHint: false
	}
}]);
var FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION = deepFreeze({
	$schema: FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION_SCHEMA_ID,
	schemaVersion: 1,
	id: "flowblind-catalog-hidden-flow-declaration-v1",
	packageVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION,
	capability: {
		capabilityId: FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
		capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
		methodFamily: FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY
	},
	publicInputSchema: FLOWBLIND_CATALOG_HIDDEN_FLOW_PUBLIC_INPUT_SCHEMA,
	actions: [{
		...catalogHiddenFlowToolDefinitions[0],
		confirmation: "Disabled",
		hostSelection: "exactly-one-canonical-hidden-flow-problem-json",
		resultFree: true
	}, {
		...catalogHiddenFlowToolDefinitions[1],
		confirmation: "Enabled",
		hostSelection: "exactly-one-preparation-bundle-json",
		resultFree: false
	}],
	reviewPolicy: {
		id: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_ID,
		policyVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
		authorityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
		reviewScope: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
		claimBoundary: FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY
	},
	runtime: {
		platform: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.platform,
		nonRootUser: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement.user,
		rootFilesystem: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement.rootFilesystem,
		network: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement.network,
		temporaryFilesystem: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement.temporaryFilesystem
	}
});
var CatalogHiddenFlowError = class extends Error {
	code;
	classification;
	publicDetail;
	constructor(code, classification, publicDetail, options) {
		super(publicDetail, options);
		this.name = "CatalogHiddenFlowError";
		this.code = code;
		this.classification = classification;
		this.publicDetail = publicDetail;
	}
};
function inputObject(value) {
	if (typeof value !== "object" || value === null || Array.isArray(value)) throw new CatalogHiddenFlowError("input-invalid", "input-validation", "Hidden-flow input must be one object containing ordinary-language context.");
	const item = value;
	const allowed = /* @__PURE__ */ new Set(["goal", "details"]);
	if (Object.keys(item).some((key) => !allowed.has(key))) throw new CatalogHiddenFlowError("input-invalid", "input-validation", "Hidden-flow input contains unsupported properties.");
	return item;
}
function validateCatalogHiddenFlowHumanContext(value) {
	const item = inputObject(value);
	try {
		return {
			goal: validateFlowBlindDisplayText(item.goal, "Research goal"),
			details: validateFlowBlindOptionalDisplayText(Object.hasOwn(item, "details") ? item.details : null, "Additional details")
		};
	} catch (error) {
		throw new CatalogHiddenFlowError("input-invalid", "input-validation", "Goal and details must be trimmed NFC text without display controls and no longer than 4,096 Unicode code points.", { cause: error });
	}
}
function stableJson(value) {
	return stableJson$1(value);
}
function sha256Bytes(value) {
	return createHash("sha256").update(value).digest("hex");
}
function utf8Bytes(value) {
	return Buffer.from(value, "utf8");
}
function artifact(reference, bytes, mediaType) {
	const value = Buffer.from(bytes);
	return {
		reference,
		byteLength: value.byteLength,
		sha256: sha256Bytes(value),
		mediaType,
		bytes: value
	};
}
function artifactIdentity(value) {
	return {
		reference: value.reference,
		byteLength: value.byteLength,
		sha256: value.sha256,
		mediaType: value.mediaType
	};
}
function catalogHiddenFlowRefusal(error) {
	return {
		schemaVersion: 1,
		capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
		status: "refused",
		containsResults: false,
		error: {
			code: error.code,
			classification: error.classification,
			detail: [...error.publicDetail.normalize("NFC")].slice(0, 512).join("")
		}
	};
}
function throwIfCatalogHiddenFlowAborted(signal) {
	if (signal?.aborted === true) throw new CatalogHiddenFlowError("operation-cancelled", "cancellation", "The hidden-flow operation was cancelled before publishing an artifact.");
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/engine.ts
function requestId(problem, index) {
	return problem.target.type === "point-speed-envelope" ? `${problem.id}-d-${index}` : `${problem.id}-solve`;
}
function compileCatalogHiddenFlowPlan(problem) {
	const basis = compileHiddenFlowBasis(problem.domain, problem.basis, problem.numerics);
	const compiledProblems = problem.target.type === "point-speed-envelope" ? compileHiddenFlowSpeedDirections(problem, basis) : [compileHiddenFlowProblem(problem, basis, problem.target)];
	const requests = compiledProblems.map((compiled, index) => createHiddenFlowSupportRequest(compiled, requestId(problem, index)));
	return {
		problem,
		basis,
		compiledProblems,
		requests,
		preflight: {
			basisSha256: sha256Bytes(utf8Bytes(stableJson({
				spec: basis.spec,
				functions: basis.functions,
				massMatrix: basis.massMatrix,
				roughnessMatrix: basis.roughnessMatrix
			}))),
			retainedBasisFunctions: basis.functions.length,
			rejectedBasisFunctions: basis.diagnostics.rejectedSupportCount,
			observationRows: problem.observations.length,
			observationRankLimit: Math.min(problem.observations.length, basis.functions.length),
			solverRequestCount: requests.length,
			solverRequestSha256: requests.map((request) => sha256Bytes(utf8Bytes(stableJson(request)))),
			target: {
				id: problem.target.id,
				type: problem.target.type,
				title: problem.target.title,
				unit: problem.target.unit
			}
		}
	};
}
function verifySupport(compiled, request, solverResult) {
	return verifyHiddenFlowSupportResult(compiled, request, solverResult, {
		requestMatches: solverResult.requestSha256 === sha256Bytes(utf8Bytes(stableJson(request))),
		canonicalMatches: solverResult.canonicalSha256 === sha256Bytes(utf8Bytes(stableJson(solverResult.canonicalization)))
	});
}
function aggregateSpeedEnvelope(problem, results) {
	if (problem.target.type !== "point-speed-envelope") throw new Error("Cannot aggregate a non-speed target.");
	const first = results[0];
	if (first === void 0) throw new Error("The hidden-flow speed plan did not produce any directional result.");
	if (results.every((result) => result.verification.state === "verified-infeasible-within-tolerance")) return first;
	if (results.every((result) => result.verification.state === "verified-unbounded-within-tolerance")) return first;
	const incompatible = results.find((result) => result.verification.state === "unsupported" || result.verification.state === "failed");
	if (incompatible !== void 0) return incompatible;
	if (results.some((result) => result.verification.state === "verified-infeasible-within-tolerance" || result.verification.state === "verified-unbounded-within-tolerance" || !result.verification.accepted)) return {
		...first,
		verification: {
			...first.verification,
			accepted: false,
			state: "failed",
			detail: "Directional solves produced inconsistent feasibility or verification states.",
			objectiveValue: null,
			rigorousObjectiveUpperBound: null,
			approximateDualUpperDiagnostic: null,
			upperBoundQualification: "not-applicable",
			numericalEvidenceQualification: "not-applicable"
		}
	};
	const allDegenerate = results.every((result) => result.verification.state === "degenerate-objective");
	const allFullObservationZero = results.every((result) => result.verification.state === "full-observation-zero-nullity");
	const candidates = results.flatMap((result, index) => {
		const objective = result.verification.objectiveValue ?? (result.verification.state === "degenerate-objective" ? 0 : null);
		return objective === null || !result.verification.accepted ? [] : [{
			index,
			objective,
			coefficients: result.solverResult.solution.coefficients
		}];
	});
	if (candidates.length === 0) return first;
	const best = candidates.reduce((current, candidate) => candidate.objective > current.objective ? candidate : current);
	const directionCount = problem.target.directionCount;
	const angle = 2 * Math.PI * best.index / directionCount;
	const allDirectionalCandidatesVerified = results.every((result) => [
		"verified-optimal-within-tolerance",
		"degenerate-objective",
		"full-observation-zero-nullity"
	].includes(result.verification.state));
	return {
		state: allDegenerate ? "degenerate-objective" : allFullObservationZero ? "full-observation-zero-nullity" : allDirectionalCandidatesVerified ? "verified-directional-lower-bound-within-tolerance" : "approximate-candidate",
		directionCount,
		geometricFactor: 1 / Math.cos(Math.PI / directionCount),
		lowerBound: best.objective,
		upperBound: null,
		unit: problem.target.unit,
		bestDirection: [Math.cos(angle), Math.sin(angle)],
		bestCandidate: best.coefficients,
		directionalResults: results
	};
}
async function executeCatalogHiddenFlowPlan(plan, solver) {
	const solverResults = plan.requests.length === 1 ? [await solver.solve(plan.requests[0])] : await solver.solveMany(plan.requests);
	if (solverResults.length !== plan.requests.length) throw new Error("The hidden-flow solver returned a different result count than requested.");
	const supports = plan.compiledProblems.map((compiled, index) => verifySupport(compiled, plan.requests[index], solverResults[index]));
	const first = supports[0];
	if (first === void 0) throw new Error("The hidden-flow plan did not produce a verified support result.");
	return {
		basis: plan.basis,
		observationRank: first.solverResult.svd.rank,
		observationNullity: first.solverResult.svd.nullity,
		observationSingularValues: first.solverResult.svd.singularValues,
		support: plan.problem.target.type === "point-speed-envelope" ? aggregateSpeedEnvelope(plan.problem, supports) : first
	};
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/authority.ts
function decodeSelectedProblem(selectedProblemBytes) {
	if (selectedProblemBytes.byteLength === 0 || selectedProblemBytes.byteLength > HIDDEN_FLOW_LIMITS.maximumDocumentBytes) throw new CatalogHiddenFlowError("problem-bytes-invalid", "input-validation", "The selected hidden-flow problem must be a nonempty bounded UTF-8 JSON document.");
	try {
		const text = new TextDecoder("utf-8", { fatal: true }).decode(selectedProblemBytes);
		return JSON.parse(text);
	} catch (error) {
		throw new CatalogHiddenFlowError("problem-bytes-invalid", "input-validation", "The selected hidden-flow problem must be valid UTF-8 JSON.", { cause: error });
	}
}
function parseSelectedProblem(selectedProblemBytes) {
	let problem;
	try {
		problem = parseHiddenFlowProblem(decodeSelectedProblem(selectedProblemBytes));
	} catch (error) {
		throw new CatalogHiddenFlowError("problem-bytes-invalid", "input-validation", error instanceof HiddenFlowInputError ? `The selected hidden-flow problem was refused with ${error.code}.` : "The selected hidden-flow problem did not satisfy the version 1 generic contract.", { cause: error });
	}
	const bytes = utf8Bytes(stableJson(problem));
	if (!Buffer.from(selectedProblemBytes).equals(bytes)) throw new CatalogHiddenFlowError("problem-not-canonical", "input-validation", "The selected problem must use the canonical stable-JSON serialization of the validated version 1 problem.");
	const sha256 = sha256Bytes(bytes);
	return {
		problem,
		bytes,
		identity: artifactIdentity({
			reference: `flowblind-catalog-hidden-flow-problem-${sha256}.json`,
			byteLength: bytes.byteLength,
			sha256,
			mediaType: "application/json",
			bytes
		})
	};
}
function assertPackageEvidence(software) {
	if (software.policy !== "attested-generic-hidden-flow-contract-parser-runtime-and-neutral-claims" || software.packageVersion !== "1.0.0" || software.runtimeNetworkRequired !== false || software.reviewPolicy.sha256.length !== 64 || software.problemSchema.sha256.length !== 64 || software.problemAcceptanceSchema.sha256.length !== 64 || software.parser.sha256.length !== 64 || software.pythonRequirements.sha256 !== FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.pythonRequirementsSha256) throw new CatalogHiddenFlowError("package-attestation-failed", "package-attestation", "The generic hidden-flow review authority is not bound to the reviewed package closure.");
}
function assertReviewedTypes(problem) {
	const observationTypes = new Set(FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES);
	if (problem.observations.some((observation) => !observationTypes.has(observation.type))) throw new CatalogHiddenFlowError("review-attestation-invalid", "review", "The selected problem contains an observation type outside the generic reviewed policy.");
	if (!new Set(FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES).has(problem.target.type)) throw new CatalogHiddenFlowError("review-attestation-invalid", "review", "The selected problem contains a target type outside the generic reviewed policy.");
}
function createAttestedGenericHiddenFlowReviewAuthority(software) {
	assertPackageEvidence(software);
	return Object.freeze({
		authorityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
		reviewSelectedProblem(selectedProblemBytes, signal) {
			throwIfCatalogHiddenFlowAborted(signal);
			const selected = parseSelectedProblem(selectedProblemBytes);
			assertReviewedTypes(selected.problem);
			let preflight;
			try {
				preflight = compileCatalogHiddenFlowPlan(selected.problem).preflight;
			} catch (error) {
				throw new CatalogHiddenFlowError("problem-not-executable", "input-validation", "The selected problem passed structural validation but could not produce the bounded generic hidden-flow solver plan.", { cause: error });
			}
			throwIfCatalogHiddenFlowAborted(signal);
			return {
				...selected,
				preflight,
				review: {
					$schema: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_ATTESTATION_SCHEMA_ID,
					schemaVersion: 1,
					authorityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_AUTHORITY_VERSION,
					policyVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY_VERSION,
					reviewScope: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_SCOPE,
					policy: software.reviewPolicy,
					problemSchema: software.problemSchema,
					problemAcceptanceSchema: software.problemAcceptanceSchema,
					parser: software.parser,
					reviewedProblemSha256: selected.identity.sha256,
					allowedObservationTypes: FLOWBLIND_CATALOG_HIDDEN_FLOW_OBSERVATION_TYPES,
					allowedTargetTypes: FLOWBLIND_CATALOG_HIDDEN_FLOW_TARGET_TYPES,
					resourceLimits: FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
					runtime: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
					claimBoundary: FLOWBLIND_CATALOG_HIDDEN_FLOW_CLAIM_BOUNDARY,
					assertions: FLOWBLIND_CATALOG_HIDDEN_FLOW_REVIEW_POLICY.assertions
				},
				software
			};
		}
	});
}
//#endregion
//#region src/application/hiddenFlowEvidenceReport.ts
function formatted(value) {
	return Number.isFinite(value) ? value.toPrecision(8).replace(/(?:\.0+|(\.\d+?)0+)(e|$)/u, "$1$2") : "not finite";
}
function searchSupports(search) {
	return "directionalResults" in search.support ? search.support.directionalResults : [search.support];
}
function representativeSearchSupport(search) {
	return searchSupports(search).reduce((best, candidate) => {
		const bestValue = best.verification.objectiveValue ?? Number.NEGATIVE_INFINITY;
		return (candidate.verification.objectiveValue ?? Number.NEGATIVE_INFINITY) > bestValue ? candidate : best;
	});
}
function searchValue(search, unit) {
	if ("directionalResults" in search.support) {
		if (!search.support.directionalResults.every((result) => result.verification.accepted)) return "not available; no feasible value is claimed";
		return `${formatted(search.support.lowerBound)} ${escapeMarkdown(search.support.unit)} candidate feasible within declared tolerance; rigorous upper unavailable`;
	}
	return !search.support.verification.accepted || search.support.verification.objectiveValue === null ? "not available" : `${formatted(search.support.verification.objectiveValue)} ${escapeMarkdown(unit)} candidate feasible within declared tolerance; rigorous upper unavailable`;
}
function evidenceReportLines(report, headingLevel) {
	const heading = "#".repeat(headingLevel);
	const subheading = "#".repeat(headingLevel + 1);
	const supports = searchSupports(report.result);
	const first = representativeSearchSupport(report.result);
	const accepted = supports.filter((support) => support.verification.accepted).length;
	return [
		`${heading} Declared problem: ${escapeMarkdown(report.problem.title)}`,
		"",
		"> **Authority boundary:** This report contains declared finite-basis evidence only. Problem, target, provenance, citation, and limitation text are unreviewed declarations. It does not attest physical truth, source accuracy, measurement validity or calibration, clinical relevance or use, or model/user approval.",
		"",
		`**Report ID:** \`${escapeMarkdown(report.reportId)}\`  `,
		`**Software:** ${escapeMarkdown(report.software.name)} ${escapeMarkdown(report.software.version)}  `,
		`**Problem source:** ${escapeMarkdown(report.problemSource.reference)}; ${report.problemSource.byteLength} bytes; SHA-256 \`${escapeMarkdown(report.problemSource.sha256)}\`  `,
		`**Basis SHA-256:** \`${escapeMarkdown(report.basisSha256)}\``,
		"",
		`${subheading} Declared problem`,
		"",
		`- Declared target: ${escapeMarkdown(report.problem.target.title)} (${escapeMarkdown(report.problem.target.type)}); result ${searchValue(report.result, report.problem.target.unit)}.`,
		`- Observations: ${report.problem.observations.length} scalar rows; numerical rank ${report.result.observationRank}, nullity ${report.result.observationNullity}.`,
		`- Velocity RMS budget: ${report.problem.budgets.velocityRms === null ? "not declared" : `${formatted(report.problem.budgets.velocityRms.value)} ${escapeMarkdown(report.problem.budgets.velocityRms.unit)}`}.`,
		`- Velocity-gradient RMS budget: ${report.problem.budgets.velocityGradientRms === null ? "not declared" : `${formatted(report.problem.budgets.velocityGradientRms.value)} ${escapeMarkdown(report.problem.budgets.velocityGradientRms.unit)}`}.`,
		`- Boundary policy: ${escapeMarkdown(report.problem.basis.boundaryPolicy)}; ${report.problem.basis.interiorMarginCells}-cell collar; no general no-slip claim.`,
		`- Basis: ${report.basis.retainedCount} retained, mass rank ${report.basis.mass.rank}, roughness rank ${report.basis.roughness.rank}, condition estimates ${formatted(report.basis.mass.conditionEstimate)} / ${formatted(report.basis.roughness.conditionEstimate)}.`,
		"",
		`${subheading} Solver and verification`,
		"",
		`- Accepted support solves: ${accepted}/${supports.length}.`,
		..."directionalResults" in report.result.support ? [`- Representative solve: best sampled direction (${report.result.support.bestDirection.map(formatted).join(", ")}) of ${report.result.support.directionCount}; the status, hashes, residuals, gap, and dual diagnostic below refer to this directional subproblem.`] : [],
		`- Solver: ${escapeMarkdown(first.solverResult.solver.adapter)} ${escapeMarkdown(first.solverResult.solver.adapterVersion)}; Clarabel ${escapeMarkdown(first.solverResult.solver.clarabelVersion)}; SciPy ${escapeMarkdown(first.solverResult.solver.scipyVersion)}; NumPy ${escapeMarkdown(first.solverResult.solver.numpyVersion)}.`,
		`- Native status: ${escapeMarkdown(first.solverResult.solution.status)}; FlowBlind state: ${escapeMarkdown(first.verification.state)}.`,
		`- Request SHA-256: \`${escapeMarkdown(first.solverResult.requestSha256)}\`; conic-form SHA-256: \`${escapeMarkdown(first.solverResult.canonicalSha256)}\`.`,
		`- Independent residuals: primal ${first.verification.primalResidual === null ? "not applicable" : formatted(first.verification.primalResidual)}, dual ${first.verification.dualResidual === null ? "not applicable" : formatted(first.verification.dualResidual)}, cone ${first.verification.coneViolation === null ? "not applicable" : formatted(first.verification.coneViolation)}, absolute gap ${first.verification.absoluteGap === null ? "not applicable" : formatted(first.verification.absoluteGap)}.`,
		`- Numerical qualification: ${escapeMarkdown(first.verification.numericalEvidenceQualification)}. Numerical evidence is checked to declared tolerances, not by formal exact arithmetic.`,
		`- Rigorous objective upper bound: unavailable. Approximate dual upper diagnostic: ${first.verification.approximateDualUpperDiagnostic === null ? "not available" : formatted(first.verification.approximateDualUpperDiagnostic)}; this diagnostic is not a bound.`,
		"",
		`${subheading} Limitations`,
		"",
		...report.limitations.length === 0 ? ["- No additional declarer-supplied limitations were provided; the fixed authority boundary above still applies."] : report.limitations.map((limitation) => `- ${escapeMarkdown(limitation)}`)
	];
}
function renderHiddenFlowEvidenceReportMarkdown(report) {
	return `${evidenceReportLines(report, 1).join("\n")}\n`;
}
//#endregion
//#region src/version.ts
var FLOWBLIND_VERSION = "0.11.0";
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/execution.ts
function catalogHiddenFlowOutputLengthsWithinLimits(jsonByteLength, markdownByteLength) {
	return Number.isSafeInteger(jsonByteLength) && jsonByteLength >= 0 && jsonByteLength <= 134217728 && Number.isSafeInteger(markdownByteLength) && markdownByteLength >= 0 && markdownByteLength <= FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES;
}
function supportResults(result) {
	return "directionalResults" in result.support ? result.support.directionalResults : [result.support];
}
function pinnedSolverIdentityMatched(result) {
	const expected = FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.solverIdentity;
	return supportResults(result).every(({ solverResult }) => {
		const actual = solverResult.solver;
		return actual.adapter === expected.adapter && actual.adapterVersion === expected.adapterVersion && actual.pythonVersion === expected.pythonVersion && actual.clarabelVersion === expected.clarabelVersion && actual.scipyVersion === expected.scipyVersion && actual.numpyVersion === expected.numpyVersion && actual.image === expected.image && actual.architecture === expected.architecture && actual.linearSolver !== null && actual.linearSolver.toLowerCase().startsWith(expected.linearSolverPrefix.toLowerCase());
	});
}
function scalarSupport(result) {
	return "directionalResults" in result.support ? null : result.support;
}
function outcomeDetail(state, fallback) {
	if (state === "verified-directional-lower-bound-within-tolerance") return "The reported value is the best verified directional candidate and is a lower bound only; no rigorous speed upper bound is claimed.";
	return fallback;
}
function classifyCatalogHiddenFlowOutcome(problem, result) {
	if ("directionalResults" in result.support) {
		const state = result.support.state;
		if (state === "verified-directional-lower-bound-within-tolerance" || state === "approximate-candidate" || state === "full-observation-zero-nullity" || state === "degenerate-objective") return {
			kind: "numerical",
			evidenceState: state,
			targetId: problem.target.id,
			targetType: problem.target.type,
			targetTitle: problem.target.title,
			value: result.support.lowerBound,
			unit: result.support.unit,
			rigorousUpperBound: result.support.upperBound,
			qualification: state === "approximate-candidate" ? "candidate-only" : "verified-to-declared-tolerances",
			detail: outcomeDetail(state, "The finite-basis target produced a verified numerical result.")
		};
	}
	const support = scalarSupport(result);
	if (support === null) return {
		kind: "unavailable",
		evidenceState: "failed",
		reason: "verification-not-accepted",
		detail: "The directional hidden-flow result did not support a finite verified candidate."
	};
	const verification = support.verification;
	if (verification.state === "verified-infeasible-within-tolerance") return {
		kind: "infeasible",
		evidenceState: verification.state,
		targetId: problem.target.id,
		targetType: problem.target.type,
		targetTitle: problem.target.title,
		qualification: "verified-to-declared-tolerances",
		detail: verification.detail
	};
	if (verification.state === "verified-unbounded-within-tolerance") return {
		kind: "unavailable",
		evidenceState: verification.state,
		reason: "no-finite-bound",
		detail: "The finite problem is verified unbounded, so no finite hidden-flow value is reported."
	};
	if (verification.accepted && (verification.state === "verified-optimal-within-tolerance" || verification.state === "approximate-candidate" || verification.state === "full-observation-zero-nullity" || verification.state === "degenerate-objective")) return {
		kind: "numerical",
		evidenceState: verification.state,
		targetId: problem.target.id,
		targetType: problem.target.type,
		targetTitle: problem.target.title,
		value: verification.objectiveValue ?? 0,
		unit: problem.target.unit,
		rigorousUpperBound: verification.rigorousObjectiveUpperBound,
		qualification: verification.numericalEvidenceQualification === "candidate-only" ? "candidate-only" : "verified-to-declared-tolerances",
		detail: verification.detail
	};
	return {
		kind: "unavailable",
		evidenceState: verification.state === "unsupported" || verification.state === "failed" ? verification.state : "failed",
		reason: "verification-not-accepted",
		detail: "The existing independent verifier did not accept a numerical or infeasibility claim."
	};
}
function report(bundle, result) {
	return {
		schemaVersion: 1,
		reportId: `catalog-hidden-flow-${bundle.association.sha256.slice(0, 32)}`,
		software: {
			name: "FlowBlind",
			version: FLOWBLIND_VERSION
		},
		problemSource: {
			reference: bundle.problem.identity.reference,
			byteLength: bundle.problem.identity.byteLength,
			sha256: bundle.problem.identity.sha256
		},
		problem: bundle.problem.document,
		basisSha256: bundle.preflight.basisSha256,
		basis: result.basis.diagnostics,
		result,
		limitations: bundle.problem.document.limitations
	};
}
function unavailable(reason, detail, evidenceState = null) {
	return {
		schemaVersion: 1,
		capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
		status: "unavailable",
		containsResults: false,
		deterministicReplayMatched: false,
		outcome: {
			kind: "unavailable",
			evidenceState,
			reason,
			detail
		}
	};
}
async function executeCatalogHiddenFlowBundle(humanContext, validated, options = {}) {
	try {
		throwIfCatalogHiddenFlowAborted(options.signal);
		const plan = compileCatalogHiddenFlowPlan(validated.bundle.problem.document);
		if (stableJson(plan.preflight) !== stableJson(validated.bundle.preflight)) return unavailable("verification-not-accepted", "The deterministic solver plan no longer matches the preparation preflight.");
		const solver = options.solver;
		if (solver === void 0) return unavailable("runtime-unavailable", "The attested pinned hidden-flow solver runtime was not supplied.");
		const first = await executeCatalogHiddenFlowPlan(plan, solver);
		if (!pinnedSolverIdentityMatched(first)) return unavailable("runtime-identity-mismatch", "The solver result did not match the attested Python, Clarabel, dependency, image, architecture, and single-thread identity.");
		throwIfCatalogHiddenFlowAborted(options.signal);
		const replay = await executeCatalogHiddenFlowPlan(plan, solver);
		if (!pinnedSolverIdentityMatched(replay)) return unavailable("runtime-identity-mismatch", "The replay solver result did not match the attested pinned runtime identity.");
		throwIfCatalogHiddenFlowAborted(options.signal);
		const firstBytes = utf8Bytes(stableJson(first));
		const replayBytes = utf8Bytes(stableJson(replay));
		const firstSha256 = sha256Bytes(firstBytes);
		const replaySha256 = sha256Bytes(replayBytes);
		if (firstSha256 !== replaySha256 || !firstBytes.equals(replayBytes)) return unavailable("deterministic-replay-mismatch", "Two executions of the same prepared problem did not produce byte-identical verified evidence.");
		const typedOutcome = classifyCatalogHiddenFlowOutcome(validated.bundle.problem.document, first);
		if (typedOutcome.kind === "unavailable" && typedOutcome.reason !== "no-finite-bound") return unavailable(typedOutcome.reason, typedOutcome.detail, typedOutcome.evidenceState);
		const evidence = report(validated.bundle, first);
		const runBindings = {
			capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
			humanContext,
			preparation: {
				id: validated.bundle.id,
				artifact: artifactIdentity(validated.bundleArtifact),
				associationSha256: validated.bundle.association.sha256
			},
			problem: {
				identity: validated.bundle.problem.identity,
				id: validated.bundle.problem.document.id,
				title: validated.bundle.problem.document.title,
				targetId: validated.bundle.problem.document.target.id,
				targetType: validated.bundle.problem.document.target.type
			},
			review: validated.bundle.review,
			software: validated.bundle.software,
			deterministicReplay: {
				canonicalization: "stable-json-v1",
				matched: true,
				firstExecutionSha256: firstSha256,
				replayExecutionSha256: replaySha256
			},
			outcome: typedOutcome,
			evidence
		};
		const jsonBytes = utf8Bytes(stableJson({
			$schema: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERIFIED_RUN_SCHEMA_ID,
			schemaVersion: 1,
			recordType: "flowblind-catalog-hidden-flow-verified-run-v1",
			id: `flowblind-hidden-flow-run-${sha256Bytes(utf8Bytes(stableJson(runBindings))).slice(0, 32)}`,
			...runBindings
		}));
		const markdownBytes = utf8Bytes(renderHiddenFlowEvidenceReportMarkdown(evidence));
		if (!catalogHiddenFlowOutputLengthsWithinLimits(jsonBytes.byteLength, markdownBytes.byteLength)) return unavailable("output-resource-limit", "The deterministic evidence exceeded the bounded catalog artifact limits, so no partial artifact was returned.");
		const json = artifact(`flowblind-catalog-hidden-flow-run-${sha256Bytes(jsonBytes)}.json`, jsonBytes, "application/json");
		const markdown = artifact(`flowblind-catalog-hidden-flow-report-${sha256Bytes(markdownBytes)}.md`, markdownBytes, "text/markdown");
		return {
			response: {
				schemaVersion: 1,
				capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
				status: "report-complete",
				containsResults: typedOutcome.kind !== "unavailable",
				humanContext,
				problem: {
					id: runBindings.problem.id,
					title: runBindings.problem.title,
					targetId: runBindings.problem.targetId,
					targetType: runBindings.problem.targetType
				},
				review: {
					authorityVersion: validated.bundle.review.authorityVersion,
					reviewScope: validated.bundle.review.reviewScope,
					claimBoundary: validated.bundle.review.claimBoundary
				},
				deterministicReplayMatched: true,
				outcome: typedOutcome,
				artifacts: {
					json: artifactIdentity(json),
					markdown: artifactIdentity(markdown)
				},
				publication: {
					state: "uncommitted-core-bytes",
					promotable: false
				}
			},
			artifacts: {
				json,
				markdown
			}
		};
	} catch (error) {
		try {
			options.onUnexpectedError?.(error);
		} catch {}
		if (options.signal?.aborted === true || error instanceof Error && (error.name === "AbortError" || error.name === "CatalogHiddenFlowError" && "code" in error && error.code === "operation-cancelled")) return unavailable("operation-cancelled", "The hidden-flow run was cancelled before verified artifacts were produced.");
		return unavailable("runtime-unavailable", "The pinned hidden-flow runtime did not complete; no numerical or infeasibility claim is made.");
	}
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/preparation.ts
function decodeJsonBytes(bytes, maximumBytes, label, errorCode = "problem-bytes-invalid") {
	if (bytes.byteLength === 0 || bytes.byteLength > maximumBytes) throw new CatalogHiddenFlowError(errorCode, errorCode === "problem-bytes-invalid" ? "input-validation" : "verification", `${label} must be a nonempty bounded UTF-8 JSON document.`);
	try {
		const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		return {
			text,
			value: JSON.parse(text)
		};
	} catch (error) {
		throw new CatalogHiddenFlowError(errorCode, errorCode === "problem-bytes-invalid" ? "input-validation" : "verification", `${label} must be valid UTF-8 JSON.`, { cause: error });
	}
}
function preparationBindings(humanContext, problem) {
	return {
		humanContext,
		capability: {
			capabilityId: FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
			capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
			methodFamily: FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
			problemSchemaVersion: 1
		},
		problem: {
			canonicalization: "stable-json-v1",
			identity: problem.identity,
			document: problem.problem
		},
		review: problem.review,
		preflight: problem.preflight,
		resourceLimits: {
			hiddenFlow: FLOWBLIND_CATALOG_HIDDEN_FLOW_LIMITS,
			maximumPreparationBundleBytes: FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES,
			maximumVerifiedRunArtifactBytes: FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_RUN_BYTES,
			maximumMarkdownArtifactBytes: FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_MARKDOWN_BYTES
		},
		dataHandling: {
			scientistInput: "ordinary-language-goal-and-details-only",
			selection: "one-host-selected-canonical-problem-json",
			preparation: "local-read-only-validation-and-result-free-preflight",
			execution: "host-confirmed-run-without-an-approval-input-field",
			retention: "self-contained-content-addressed-bundle-with-no-hidden-state"
		},
		runtime: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME,
		software: problem.software
	};
}
function prepareOrThrow(humanContext, selectedProblemBytes, reviewAuthority, signal) {
	throwIfCatalogHiddenFlowAborted(signal);
	if (reviewAuthority.authorityVersion !== "attested-generic-hidden-flow-problem-authority-v1") throw new CatalogHiddenFlowError("review-attestation-invalid", "review", "The selected hidden-flow problem review authority is malformed.");
	const selected = reviewAuthority.reviewSelectedProblem(selectedProblemBytes, signal);
	throwIfCatalogHiddenFlowAborted(signal);
	const bindings = preparationBindings(humanContext, selected);
	const associationSha256 = sha256Bytes(utf8Bytes(stableJson(bindings)));
	const bundleBytes = utf8Bytes(stableJson({
		$schema: FLOWBLIND_CATALOG_HIDDEN_FLOW_PREPARATION_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-hidden-flow-preparation-v1",
		id: `flowblind-hidden-flow-preparation-${associationSha256.slice(0, 32)}`,
		status: "prepared-awaiting-confirmation",
		containsResults: false,
		association: {
			canonicalization: "stable-json-v1",
			sha256: associationSha256
		},
		...bindings
	}));
	if (bundleBytes.byteLength > FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES) throw new CatalogHiddenFlowError("problem-bytes-invalid", "input-validation", "The prepared hidden-flow bundle exceeds its bounded portable size.");
	const bundleArtifact = artifact(`flowblind-catalog-hidden-flow-preparation-${sha256Bytes(bundleBytes)}.json`, bundleBytes, "application/json");
	return {
		response: {
			schemaVersion: 1,
			capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
			status: "prepared-awaiting-confirmation",
			containsResults: false,
			humanContext,
			problem: {
				id: selected.problem.id,
				title: selected.problem.title,
				targetType: selected.problem.target.type,
				targetTitle: selected.problem.target.title,
				observationRows: selected.problem.observations.length,
				retainedBasisFunctions: selected.preflight.retainedBasisFunctions,
				solverRequestCount: selected.preflight.solverRequestCount
			},
			review: {
				authorityVersion: selected.review.authorityVersion,
				reviewScope: selected.review.reviewScope,
				claimBoundary: selected.review.claimBoundary
			},
			preparationBundle: artifactIdentity(bundleArtifact)
		},
		bundle: bundleArtifact
	};
}
function prepareCatalogHiddenFlowBundle(humanContext, selectedProblemBytes, reviewAuthority, signal) {
	return prepareOrThrow(humanContext, selectedProblemBytes, reviewAuthority, signal);
}
function object(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}
function validateCatalogHiddenFlowBundle(humanContext, bundleBytes, reviewAuthority, signal) {
	throwIfCatalogHiddenFlowAborted(signal);
	const decoded = decodeJsonBytes(bundleBytes, FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES, "The hidden-flow preparation bundle", "preparation-bundle-invalid");
	const document = object(decoded.value);
	const bundledContext = object(document?.humanContext);
	const bundledProblem = object(document?.problem);
	if (document === null || bundledContext === null || bundledProblem === null || bundledProblem.document === void 0) throw new CatalogHiddenFlowError("preparation-bundle-invalid", "verification", "The selected preparation bundle is malformed or incomplete.");
	let rebuilt;
	try {
		rebuilt = prepareOrThrow(validateCatalogHiddenFlowHumanContext(bundledContext), utf8Bytes(stableJson(bundledProblem.document)), reviewAuthority, signal);
	} catch (error) {
		throw new CatalogHiddenFlowError("preparation-bundle-invalid", "verification", "The selected preparation bundle cannot be reconstructed from its declared content.", { cause: error });
	}
	if (!Buffer.from(bundleBytes).equals(rebuilt.bundle.bytes)) throw new CatalogHiddenFlowError("preparation-bundle-invalid", "verification", "The selected preparation bundle is noncanonical, stale, or tampered.");
	if (stableJson(humanContext) !== stableJson(rebuilt.response.humanContext)) throw new CatalogHiddenFlowError("human-context-mismatch", "verification", "The ordinary-language run context does not match the preparation bundle.");
	throwIfCatalogHiddenFlowAborted(signal);
	return {
		bundle: JSON.parse(decoded.text),
		bundleArtifact: rebuilt.bundle
	};
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/capability.ts
function preparationFailure(error) {
	return catalogHiddenFlowRefusal(error instanceof CatalogHiddenFlowError ? error : new CatalogHiddenFlowError("problem-not-executable", "input-validation", "The selected hidden-flow problem could not be prepared safely.", { cause: error }));
}
function runFailure(error) {
	return catalogHiddenFlowRefusal(error instanceof CatalogHiddenFlowError ? error : new CatalogHiddenFlowError("preparation-bundle-invalid", "verification", "The selected hidden-flow preparation bundle could not be validated.", { cause: error }));
}
function prepareCatalogHiddenFlow(input, context, options = {}) {
	try {
		if (options.reviewAuthority === void 0) throw new CatalogHiddenFlowError("review-authority-unavailable", "review", "The generic hidden-flow reviewed-problem authority is unavailable.");
		return prepareCatalogHiddenFlowBundle(validateCatalogHiddenFlowHumanContext(input), context.selectedProblemBytes, options.reviewAuthority, options.signal);
	} catch (error) {
		return {
			response: preparationFailure(error),
			bundle: null
		};
	}
}
async function runCatalogHiddenFlow(input, context, options = {}) {
	try {
		if (options.reviewAuthority === void 0) throw new CatalogHiddenFlowError("review-authority-unavailable", "review", "The generic hidden-flow reviewed-problem authority is unavailable.");
		const humanContext = validateCatalogHiddenFlowHumanContext(input);
		const executed = await executeCatalogHiddenFlowBundle(humanContext, validateCatalogHiddenFlowBundle(humanContext, context.preparationBundleBytes, options.reviewAuthority, options.signal), options);
		return "response" in executed ? executed : {
			response: executed,
			artifacts: null
		};
	} catch (error) {
		return {
			response: runFailure(error),
			artifacts: null
		};
	}
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/packageIo.ts
var MAXIMUM_ATTACHMENT_TREE_ENTRIES = 64;
var MAXIMUM_ATTACHMENT_TREE_DEPTH = 8;
function confinedPath(root, reference) {
	const path = resolve(root, reference);
	const child = relative(root, path);
	if (child.length === 0 || child === ".." || child.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute(child)) throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The selected attachment escapes the host-provided input root.");
	return path;
}
async function selectedReferences(root, current = root, depth = 0, state = { entries: 0 }, signal) {
	throwIfCatalogHiddenFlowAborted(signal);
	if (depth > MAXIMUM_ATTACHMENT_TREE_DEPTH) throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The selected attachment tree exceeds the reviewed directory-depth limit.");
	const references = [];
	try {
		const directory = await opendir(current);
		for await (const entry of directory) {
			throwIfCatalogHiddenFlowAborted(signal);
			state.entries += 1;
			if (state.entries > MAXIMUM_ATTACHMENT_TREE_ENTRIES) throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The selected attachment tree exceeds the reviewed entry-count limit.");
			const path = resolve(current, entry.name);
			const reference = relative(root, path);
			if (entry.isSymbolicLink()) throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "Selected attachment roots may not contain symbolic links.");
			if (entry.isDirectory()) references.push(...await selectedReferences(root, path, depth + 1, state, signal));
			else if (entry.isFile()) references.push(reference);
			else throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "Selected attachments must be ordinary files.");
			if (references.length > 1) throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The hidden-flow action requires exactly one selected JSON attachment.");
		}
	} catch (error) {
		if (error instanceof CatalogHiddenFlowError) throw error;
		throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The host-selected attachment tree is missing or unreadable.", { cause: error });
	}
	return references;
}
async function stableRead(root, reference, signal) {
	throwIfCatalogHiddenFlowAborted(signal);
	const path = confinedPath(root, reference);
	let metadata;
	try {
		metadata = await lstat(path);
	} catch (error) {
		throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The selected attachment is missing or unreadable.", { cause: error });
	}
	if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.nlink !== 1 || metadata.size <= 0 || metadata.size > FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES) throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The selected attachment must be one bounded, single-link ordinary file.");
	let canonicalRoot;
	let canonicalPath;
	try {
		canonicalRoot = await realpath(root);
		canonicalPath = await realpath(path);
	} catch (error) {
		throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The selected attachment could not be resolved safely.", { cause: error });
	}
	if (relative(canonicalRoot, canonicalPath).startsWith("..")) throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The selected attachment resolves outside the host-provided input root.");
	let handle;
	try {
		handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	} catch (error) {
		throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The selected attachment could not be opened as an ordinary no-follow file.", { cause: error });
	}
	try {
		const before = await handle.stat({ bigint: true });
		if (!before.isFile() || before.nlink !== 1n || before.size <= 0n || before.size > BigInt(FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES)) throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The opened attachment is not one bounded, single-link ordinary file.");
		const chunks = [];
		let total = 0;
		while (true) {
			throwIfCatalogHiddenFlowAborted(signal);
			const chunk = Buffer.allocUnsafe(65536);
			const { bytesRead } = await handle.read(chunk, 0, chunk.byteLength, null);
			if (bytesRead === 0) break;
			total += bytesRead;
			if (total > FLOWBLIND_CATALOG_HIDDEN_FLOW_MAXIMUM_BUNDLE_BYTES) throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The selected attachment exceeds the bounded hidden-flow input limit.");
			chunks.push(chunk.subarray(0, bytesRead));
		}
		const after = await handle.stat({ bigint: true });
		if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs || total !== Number(before.size)) throw new CatalogHiddenFlowError("attachment-changed-during-read", "attachment", "The selected attachment changed while it was being read.");
		return {
			path,
			bytes: Buffer.concat(chunks, total)
		};
	} catch (error) {
		if (error instanceof CatalogHiddenFlowError) throw error;
		throw new CatalogHiddenFlowError("attachment-changed-during-read", "attachment", "The selected attachment could not be read with stable identity.", { cause: error });
	} finally {
		await handle.close();
	}
}
async function loadSingleCatalogHiddenFlowAttachment(root, signal) {
	let metadata;
	try {
		metadata = await lstat(root);
	} catch (error) {
		throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The host-provided input root is missing or unreadable.", { cause: error });
	}
	if (metadata.isSymbolicLink() || !metadata.isDirectory()) throw new CatalogHiddenFlowError("attachment-path-unsafe", "attachment", "The host-provided input root must be an ordinary directory.");
	const references = await selectedReferences(root, root, 0, { entries: 0 }, signal);
	if (references.length !== 1 || !references[0].toLowerCase().endsWith(".json")) throw new CatalogHiddenFlowError("attachment-set-invalid", "attachment", "The hidden-flow action requires exactly one selected JSON attachment.");
	return stableRead(root, references[0], signal);
}
async function verifyExisting(path, expected) {
	const metadata = await lstat(path);
	if (metadata.isSymbolicLink() || !metadata.isFile() || metadata.nlink !== 1 || metadata.size !== expected.byteLength) throw new CatalogHiddenFlowError("output-publication-conflict", "publication", "A content-addressed hidden-flow output already exists with different bytes.");
	const handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	try {
		const before = await handle.stat({ bigint: true });
		const bytes = Buffer.allocUnsafe(expected.byteLength);
		let offset = 0;
		while (offset < bytes.byteLength) {
			const { bytesRead } = await handle.read(bytes, offset, bytes.byteLength - offset, offset);
			if (bytesRead === 0) break;
			offset += bytesRead;
		}
		const after = await handle.stat({ bigint: true });
		if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs || offset !== expected.byteLength || !bytes.equals(Buffer.from(expected))) throw new CatalogHiddenFlowError("output-publication-conflict", "publication", "A content-addressed hidden-flow output already exists with different bytes.");
	} finally {
		await handle.close();
	}
}
async function publishCatalogHiddenFlowArtifact(outputRoot, artifact, signal) {
	const rootMetadata = await lstat(outputRoot);
	if (rootMetadata.isSymbolicLink() || !rootMetadata.isDirectory()) throw new CatalogHiddenFlowError("output-publication-conflict", "publication", "The host-provided output root must be an ordinary directory.");
	const finalPath = confinedPath(outputRoot, artifact.reference);
	const stagePath = confinedPath(outputRoot, `.flowblind-stage-${process.pid}-${randomUUID()}`);
	let staged = false;
	try {
		throwIfCatalogHiddenFlowAborted(signal);
		const handle = await open(stagePath, "wx", 384);
		staged = true;
		try {
			await handle.writeFile(artifact.bytes);
			await handle.sync();
		} finally {
			await handle.close();
		}
		throwIfCatalogHiddenFlowAborted(signal);
		try {
			await link(stagePath, finalPath);
		} catch (error) {
			if (typeof error === "object" && error !== null && "code" in error && error.code === "EEXIST") await verifyExisting(finalPath, artifact.bytes);
			else throw error;
		}
		await unlink(stagePath);
		staged = false;
		await verifyExisting(finalPath, artifact.bytes);
	} finally {
		if (staged) await unlink(stagePath).catch((error) => {
			if (typeof error !== "object" || error === null || !("code" in error) || error.code !== "ENOENT") throw error;
		});
	}
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/packagePublication.ts
function samePath(left, right) {
	const normalizedLeft = resolve(left);
	const normalizedRight = resolve(right);
	return process.platform === "win32" ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase() : normalizedLeft === normalizedRight;
}
function confined(root, reference) {
	const path = resolve(root, reference);
	const child = relative(root, path);
	if (child.length === 0 || child === ".." || child.startsWith(`..${sep}`) || isAbsolute(child)) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow report-set reference escaped the host-provided output root.");
	return path;
}
async function ordinaryDirectory(path, allowCreate = false, allowAlias = false) {
	if (allowCreate) try {
		await mkdir(path);
	} catch (error) {
		if (typeof error !== "object" || error === null || error.code !== "EEXIST") throw new CatalogHiddenFlowError("concurrent-publication-conflict", "publication", "The deterministic hidden-flow report directory could not be created.", { cause: error });
	}
	try {
		const metadata = await lstat(path);
		const canonical = await realpath(path);
		if (metadata.isSymbolicLink() || !metadata.isDirectory() || !allowAlias && !samePath(path, canonical)) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "Hidden-flow report directories must be ordinary directories without aliases or links.");
	} catch (error) {
		if (error instanceof CatalogHiddenFlowError) throw error;
		throw new CatalogHiddenFlowError("output-publication-conflict", "publication", "The host-provided hidden-flow output directory is unavailable.", { cause: error });
	}
}
async function ensureOutputRoot(rootInput) {
	const requested = resolve(rootInput);
	await ordinaryDirectory(requested, false, true);
	return realpath(requested);
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
async function removeStagingFile(path, directory, unlinkFile = unlink) {
	try {
		await unlinkFile(path);
		await syncDirectory(directory);
	} catch (error) {
		throw new CatalogHiddenFlowError("output-publication-partial", "publication", "A hidden-flow staging entry could not be removed and synchronized authoritatively.", { cause: error });
	}
}
async function readHandle(handle, maximumBytes) {
	const chunks = [];
	let total = 0;
	while (true) {
		const chunk = Buffer.allocUnsafe(65536);
		const { bytesRead } = await handle.read(chunk, 0, chunk.byteLength, null);
		if (bytesRead === 0) break;
		total += bytesRead;
		if (total > maximumBytes) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow report artifact exceeds its verified byte length.");
		chunks.push(chunk.subarray(0, bytesRead));
	}
	return Buffer.concat(chunks, total);
}
async function verifiedFile(path, expected, missingCode) {
	let before;
	try {
		before = await lstat(path, { bigint: true });
	} catch (error) {
		throw new CatalogHiddenFlowError(missingCode, "publication", missingCode === "output-publication-partial" ? "A marker-committed hidden-flow report is missing a required artifact." : "A hidden-flow report artifact is unavailable.", { cause: error });
	}
	if (before.isSymbolicLink() || !before.isFile() || before.nlink !== 1n || before.size !== BigInt(expected.byteLength)) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow report artifact is not the expected single-link ordinary file.");
	let handle;
	try {
		handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	} catch (error) {
		throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow report artifact could not be opened safely.", { cause: error });
	}
	try {
		const opened = await handle.stat({ bigint: true });
		if (!opened.isFile() || opened.nlink !== 1n || opened.size !== before.size) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow report artifact changed before it could be read.");
		const bytes = await readHandle(handle, expected.byteLength);
		const after = await handle.stat({ bigint: true });
		const final = await lstat(path, { bigint: true });
		const canonical = await realpath(path);
		if (before.dev !== opened.dev || before.ino !== opened.ino || opened.dev !== after.dev || opened.ino !== after.ino || opened.size !== after.size || opened.mtimeNs !== after.mtimeNs || after.dev !== final.dev || after.ino !== final.ino || final.nlink !== 1n || final.isSymbolicLink() || !samePath(path, canonical) || bytes.byteLength !== expected.byteLength || sha256Bytes(bytes) !== expected.sha256) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow report artifact changed or failed identity verification.");
		return bytes;
	} finally {
		await handle.close();
	}
}
async function verifiedStagingHardLink(path, expected, linked) {
	let handle;
	try {
		handle = await open(path, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
		const opened = await handle.stat({ bigint: true });
		if (!opened.isFile() || opened.dev !== linked.dev || opened.ino !== linked.ino || opened.nlink !== linked.nlink || opened.size !== BigInt(expected.byteLength)) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow staging hard link changed before it could be verified.");
		const bytes = await readHandle(handle, expected.byteLength);
		const after = await handle.stat({ bigint: true });
		const final = await lstat(path, { bigint: true });
		if (after.dev !== opened.dev || after.ino !== opened.ino || after.nlink !== opened.nlink || after.size !== opened.size || after.mtimeNs !== opened.mtimeNs || final.dev !== after.dev || final.ino !== after.ino || final.nlink !== after.nlink || final.isSymbolicLink() || bytes.byteLength !== expected.byteLength || sha256Bytes(bytes) !== expected.sha256) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow staging hard link failed expected-byte verification.");
	} catch (error) {
		if (error instanceof CatalogHiddenFlowError) throw error;
		throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow staging hard link could not be opened safely.", { cause: error });
	} finally {
		await handle?.close().catch(() => void 0);
	}
}
async function installCompleteFile(path, bytes, mediaType) {
	const expected = artifactIdentity(artifact(basename(path), bytes, mediaType));
	if (await fileExists(path)) try {
		await verifiedFile(path, expected, "output-artifact-tampered");
		return;
	} catch (error) {
		throw new CatalogHiddenFlowError("concurrent-publication-conflict", "publication", "A deterministic hidden-flow report target already contains different or incomplete bytes.", { cause: error });
	}
	const parent = dirname(path);
	await ordinaryDirectory(parent);
	const temporary = resolve(parent, `.${basename(path)}.stage-${randomUUID()}`);
	let temporaryCreated = false;
	let handle;
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
		await verifiedFile(temporary, {
			...expected,
			reference: basename(temporary)
		}, "output-artifact-tampered");
		try {
			await link(temporary, path);
			await syncDirectory(parent);
		} catch (error) {
			if ((typeof error === "object" && error !== null ? error.code : void 0) !== "EEXIST") throw new CatalogHiddenFlowError("concurrent-publication-conflict", "publication", "A complete hidden-flow report artifact could not be installed atomically.", { cause: error });
			try {
				await verifiedFile(path, expected, "output-artifact-tampered");
			} catch (verificationError) {
				throw new CatalogHiddenFlowError("concurrent-publication-conflict", "publication", "A concurrent hidden-flow publication installed different immutable bytes.", { cause: verificationError });
			}
		}
	} finally {
		await handle?.close().catch(() => void 0);
		if (temporaryCreated) await removeStagingFile(temporary, parent);
	}
}
function references(preparationSha256) {
	const directory = `flowblind-hidden-flow-study-${preparationSha256}`;
	return {
		directory,
		json: `${directory}/verified-run.json`,
		markdown: `${directory}/report.md`,
		verification: `${directory}/report-verification.json`
	};
}
var SHA256_PATTERN = /^[a-f0-9]{64}$/u;
function semantic(condition, detail) {
	if (!condition) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", detail);
}
function assertContentAddressedReference(identity, prefix, suffix, label) {
	semantic(SHA256_PATTERN.test(identity.sha256) && identity.reference === `${prefix}${identity.sha256}${suffix}`, `${label} does not match its content-addressed SHA-256 reference.`);
}
function assertStableJsonIdentity(identity, value, label) {
	const bytes = utf8Bytes(stableJson(value));
	semantic(identity.mediaType === "application/json" && identity.byteLength === bytes.byteLength && identity.sha256 === sha256Bytes(bytes), `${label} does not bind the canonical JSON bytes.`);
}
function assertCatalogHiddenFlowVerifiedRunSemanticContract(run) {
	semantic(run.deterministicReplay.matched === true && SHA256_PATTERN.test(run.deterministicReplay.firstExecutionSha256) && run.deterministicReplay.firstExecutionSha256 === run.deterministicReplay.replayExecutionSha256, "A matched hidden-flow replay must carry equal first and replay execution hashes.");
	assertContentAddressedReference(run.preparation.artifact, "flowblind-catalog-hidden-flow-preparation-", ".json", "The hidden-flow preparation artifact");
	assertContentAddressedReference(run.problem.identity, "flowblind-catalog-hidden-flow-problem-", ".json", "The hidden-flow problem artifact");
}
function assertResponseMatchesVerifiedRun(response, run) {
	assertCatalogHiddenFlowVerifiedRunSemanticContract(run);
	semantic(response.capabilityVersion === run.capabilityVersion && response.deterministicReplayMatched === true && response.containsResults === (run.outcome.kind !== "unavailable") && sameJson(response.humanContext, run.humanContext) && sameJson(response.outcome, run.outcome) && sameJson(response.problem, {
		id: run.problem.id,
		title: run.problem.title,
		targetId: run.problem.targetId,
		targetType: run.problem.targetType
	}) && sameJson(response.review, {
		authorityVersion: run.review.authorityVersion,
		reviewScope: run.review.reviewScope,
		claimBoundary: run.review.claimBoundary
	}), "The hidden-flow action response does not match its canonical verified-run record.");
	assertStableJsonIdentity(response.artifacts.json, run, "The hidden-flow verified-run identity");
}
function assertCatalogHiddenFlowReportSetSemanticContract(response, verificationRecord, verificationArtifact, verifiedRun) {
	assertResponseMatchesVerifiedRun(response, verifiedRun);
	const preparationSha256 = verificationRecord.preparation.bundle.sha256;
	semantic(SHA256_PATTERN.test(preparationSha256), "The hidden-flow report set has an invalid preparation digest.");
	assertContentAddressedReference(verificationRecord.preparation.bundle, "flowblind-catalog-hidden-flow-preparation-", ".json", "The report-set preparation artifact");
	const expected = references(preparationSha256);
	semantic(verificationRecord.deterministicReplay.matched === true && verificationRecord.deterministicReplay.firstExecutionSha256 === verificationRecord.deterministicReplay.replayExecutionSha256 && sameJson(verificationRecord.deterministicReplay, verifiedRun.deterministicReplay), "The report-verification marker does not bind one matched deterministic replay.");
	semantic(verificationRecord.publication.directory === expected.directory && verificationRecord.artifacts.json.reference === expected.json && verificationRecord.artifacts.markdown.reference === expected.markdown && verificationArtifact.reference === expected.verification, "The report-verification marker does not bind every member to its preparation-derived study directory.");
	semantic(response.publication.directory === expected.directory && response.artifacts.json.reference === expected.json && response.artifacts.markdown.reference === expected.markdown && response.artifacts.verification.reference === expected.verification, "The packaged action response does not identify the same canonical report set as its marker.");
	semantic(sameJson(response.artifacts.json, verificationRecord.artifacts.json) && sameJson(response.artifacts.markdown, verificationRecord.artifacts.markdown) && sameJson(response.artifacts.verification, verificationArtifact), "The packaged action response does not preserve the marker member identities.");
	semantic(verificationRecord.preparation.id === verifiedRun.preparation.id && verificationRecord.preparation.associationSha256 === verifiedRun.preparation.associationSha256 && sameJson(verificationRecord.preparation.bundle, verifiedRun.preparation.artifact) && verificationRecord.problem.id === verifiedRun.problem.id && sameJson(verificationRecord.problem.identity, verifiedRun.problem.identity) && sameJson(verificationRecord.software, verifiedRun.software), "The report-verification marker does not preserve the verified-run authority chain.");
	assertStableJsonIdentity(verificationRecord.artifacts.json, verifiedRun, "The report-set verified-run identity");
	assertStableJsonIdentity(verificationArtifact, verificationRecord, "The report-verification marker identity");
}
function assertCatalogHiddenFlowActionResponseSemanticContract(response, context = {}) {
	if (response.status === "prepared-awaiting-confirmation") {
		semantic(response.preparationBundle.mediaType === "application/json", "The hidden-flow preparation response must identify canonical JSON.");
		assertContentAddressedReference(response.preparationBundle, "flowblind-catalog-hidden-flow-preparation-", ".json", "The hidden-flow preparation response artifact");
		return;
	}
	if (response.status === "unavailable" || response.status === "refused") return;
	semantic(context.verifiedRun !== void 0, "Semantic validation of a report-complete response requires its verified-run record.");
	if (response.publication.state === "uncommitted-core-bytes") {
		assertResponseMatchesVerifiedRun(response, context.verifiedRun);
		assertContentAddressedReference(response.artifacts.json, "flowblind-catalog-hidden-flow-run-", ".json", "The uncommitted hidden-flow JSON artifact");
		assertContentAddressedReference(response.artifacts.markdown, "flowblind-catalog-hidden-flow-report-", ".md", "The uncommitted hidden-flow Markdown artifact");
		return;
	}
	semantic(context.reportVerification !== void 0 && context.verificationArtifact !== void 0, "Semantic validation of a committed response requires its report-verification record and marker identity.");
	assertCatalogHiddenFlowReportSetSemanticContract(response, context.reportVerification, context.verificationArtifact, context.verifiedRun);
}
function parseCanonicalObject(bytes, label) {
	let value;
	try {
		value = JSON.parse(bytes.toString("utf8"));
	} catch (error) {
		throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", `${label} is invalid JSON.`, { cause: error });
	}
	if (typeof value !== "object" || value === null || Array.isArray(value) || stableJson(value) !== bytes.toString("utf8")) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", `${label} is not canonical closed JSON.`);
	return value;
}
function parseVerifiedRun(artifactValue) {
	const value = parseCanonicalObject(artifactValue.bytes, "The hidden-flow verified run");
	if (value.recordType !== "flowblind-catalog-hidden-flow-verified-run-v1" || value.schemaVersion !== 1 || value.capabilityVersion !== "1.1.0") throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "The hidden-flow verified-run artifact has an invalid identity.");
	const run = value;
	assertCatalogHiddenFlowVerifiedRunSemanticContract(run);
	return run;
}
var STAGING_NAME = /^\.(verified-run\.json|report\.md|report-verification\.json)\.stage-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;
function expectedPublicationMembers(record, marker) {
	return {
		"verified-run.json": record.artifacts.json,
		"report.md": record.artifacts.markdown,
		"report-verification.json": marker
	};
}
async function reconcileCatalogHiddenFlowPublicationStaging(directory, expected, unlinkFile = unlink) {
	const handle = await opendir(directory);
	let entries = 0;
	for await (const entry of handle) {
		entries += 1;
		if (entries > 32) throw new CatalogHiddenFlowError("output-publication-partial", "publication", "The deterministic hidden-flow report directory contains too many entries.");
		const match = STAGING_NAME.exec(entry.name);
		if (match === null) continue;
		if (!entry.isFile()) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A recognized hidden-flow staging entry is not an ordinary file.");
		const member = match[1];
		const identity = expected[member];
		const stagingPath = resolve(directory, entry.name);
		const finalPath = resolve(directory, member);
		const staging = await lstat(stagingPath, { bigint: true });
		if (staging.isSymbolicLink() || !staging.isFile() || staging.size !== BigInt(identity.byteLength)) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A recognized hidden-flow staging entry is not the expected ordinary artifact.");
		if (await fileExists(finalPath)) {
			const final = await lstat(finalPath, { bigint: true });
			if (final.isSymbolicLink() || !final.isFile()) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow staging entry targets a non-ordinary final artifact.");
			if (staging.dev === final.dev && staging.ino === final.ino) {
				if (staging.nlink < 2n || staging.nlink !== final.nlink) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow staging hard link has an inconsistent link count.");
				await verifiedStagingHardLink(stagingPath, identity, staging);
			} else await verifiedFile(stagingPath, {
				...identity,
				reference: entry.name
			}, "output-artifact-tampered");
		} else await verifiedFile(stagingPath, {
			...identity,
			reference: entry.name
		}, "output-artifact-tampered");
		const current = await lstat(stagingPath, { bigint: true });
		if (current.dev !== staging.dev || current.ino !== staging.ino || current.size !== staging.size || current.nlink !== staging.nlink || current.mtimeNs !== staging.mtimeNs) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "A hidden-flow staging entry changed before reconciliation.");
		await removeStagingFile(stagingPath, directory, unlinkFile);
	}
}
async function verifyDirectoryEntries(directory) {
	const expected = /* @__PURE__ */ new Set([
		"verified-run.json",
		"report.md",
		"report-verification.json"
	]);
	const seen = /* @__PURE__ */ new Set();
	const seenFolded = /* @__PURE__ */ new Set();
	const handle = await opendir(directory);
	for await (const entry of handle) {
		const folded = entry.name.toLowerCase();
		if (seen.has(entry.name) || seenFolded.has(folded) || !expected.has(entry.name) || !entry.isFile()) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "The marker-committed hidden-flow report directory contains an unexpected, aliased, linked, or unsupported entry.");
		seen.add(entry.name);
		seenFolded.add(folded);
	}
	if (seen.size !== expected.size || [...expected].some((name) => !seen.has(name))) throw new CatalogHiddenFlowError("output-publication-partial", "publication", "The marker-committed hidden-flow report set is incomplete.");
}
function sameJson(left, right) {
	return stableJson(left) === stableJson(right);
}
async function verifyPublishedSet(root, expectedRecord, expectedMarker, expectedResponse, expectedRun) {
	const finalDirectory = confined(root, references(expectedRecord.preparation.bundle.sha256).directory);
	await ordinaryDirectory(finalDirectory);
	await reconcileCatalogHiddenFlowPublicationStaging(finalDirectory, expectedPublicationMembers(expectedRecord, expectedMarker));
	assertCatalogHiddenFlowReportSetSemanticContract(expectedResponse, expectedRecord, expectedMarker, expectedRun);
	const marker = parseCanonicalObject(await verifiedFile(confined(root, expectedMarker.reference), expectedMarker, "output-publication-partial"), "The hidden-flow report-verification marker");
	if (!sameJson(marker, expectedRecord)) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "The hidden-flow report-verification marker does not match the expected closed record.");
	const jsonBytes = await verifiedFile(confined(root, expectedRecord.artifacts.json.reference), expectedRecord.artifacts.json, "output-publication-partial");
	const markdownBytes = await verifiedFile(confined(root, expectedRecord.artifacts.markdown.reference), expectedRecord.artifacts.markdown, "output-publication-partial");
	const run = parseCanonicalObject(jsonBytes, "The committed hidden-flow verified run");
	assertCatalogHiddenFlowVerifiedRunSemanticContract(run);
	if (run.recordType !== "flowblind-catalog-hidden-flow-verified-run-v1" || run.capabilityVersion !== expectedRecord.capability.capabilityVersion || run.preparation.id !== expectedRecord.preparation.id || run.preparation.associationSha256 !== expectedRecord.preparation.associationSha256 || !sameJson(run.preparation.artifact, expectedRecord.preparation.bundle) || run.problem.id !== expectedRecord.problem.id || !sameJson(run.problem.identity, expectedRecord.problem.identity) || !sameJson(run.software, expectedRecord.software) || !sameJson(run.deterministicReplay, expectedRecord.deterministicReplay) || markdownBytes.byteLength === 0) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "The committed hidden-flow artifacts do not preserve the preparation, problem, software, and replay authority chain.");
	assertCatalogHiddenFlowReportSetSemanticContract(expectedResponse, marker, expectedMarker, run);
	await verifyDirectoryEntries(finalDirectory);
}
async function publishCatalogHiddenFlowReportSet(outputRootInput, executed, options = {}) {
	const root = await ensureOutputRoot(outputRootInput);
	const record = parseVerifiedRun(executed.artifacts.json);
	if (!sameJson(executed.response.artifacts.json, artifactIdentity(executed.artifacts.json)) || !sameJson(executed.response.artifacts.markdown, artifactIdentity(executed.artifacts.markdown))) throw new CatalogHiddenFlowError("output-artifact-tampered", "publication", "The in-memory hidden-flow response does not bind its artifact bytes.");
	const outputReferences = references(record.preparation.artifact.sha256);
	const json = artifact(outputReferences.json, executed.artifacts.json.bytes, "application/json");
	const markdown = artifact(outputReferences.markdown, executed.artifacts.markdown.bytes, "text/markdown");
	const verificationRecord = {
		$schema: FLOWBLIND_CATALOG_HIDDEN_FLOW_REPORT_VERIFICATION_SCHEMA_ID,
		schemaVersion: 1,
		recordType: "flowblind-catalog-hidden-flow-report-verification-v1",
		status: "verified-report-complete",
		capability: {
			capabilityId: FLOWBLIND_CATALOG_HIDDEN_FLOW_CAPABILITY_ID,
			capabilityVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION,
			methodFamily: FLOWBLIND_CATALOG_HIDDEN_FLOW_METHOD_FAMILY,
			packageVersion: FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION
		},
		preparation: {
			id: record.preparation.id,
			associationSha256: record.preparation.associationSha256,
			bundle: record.preparation.artifact
		},
		problem: {
			id: record.problem.id,
			identity: record.problem.identity
		},
		software: record.software,
		deterministicReplay: record.deterministicReplay,
		artifacts: {
			json: artifactIdentity(json),
			markdown: artifactIdentity(markdown)
		},
		publication: {
			directory: outputReferences.directory,
			commitMarker: "report-verification.json",
			pointOfNoReturn: "exclusive-report-verification-commit-marker",
			policy: "deterministic-exclusive-create-or-verify-content-then-commit-marker",
			distributedExactlyOnceClaim: false
		}
	};
	const verificationBytes = utf8Bytes(stableJson(verificationRecord));
	const verification = artifact(outputReferences.verification, verificationBytes, "application/json");
	const verificationIdentity = artifactIdentity(verification);
	const response = {
		...executed.response,
		artifacts: {
			json: artifactIdentity(json),
			markdown: artifactIdentity(markdown),
			verification: verificationIdentity
		},
		publication: {
			state: "marker-verified",
			promotable: true,
			directory: outputReferences.directory,
			pointOfNoReturn: "exclusive-report-verification-commit-marker",
			policy: "deterministic-exclusive-create-or-verify-content-then-commit-marker",
			distributedExactlyOnceClaim: false
		}
	};
	assertCatalogHiddenFlowReportSetSemanticContract(response, verificationRecord, verificationIdentity, record);
	const finalDirectory = confined(root, outputReferences.directory);
	if (await fileExists(confined(root, outputReferences.verification))) {
		await verifyPublishedSet(root, verificationRecord, verificationIdentity, response, record);
		return {
			response,
			verificationRecord
		};
	}
	throwIfCatalogHiddenFlowAborted(options.signal);
	await ordinaryDirectory(finalDirectory, true);
	await reconcileCatalogHiddenFlowPublicationStaging(finalDirectory, expectedPublicationMembers(verificationRecord, verificationIdentity));
	await options.checkpoint?.("before-write-json");
	throwIfCatalogHiddenFlowAborted(options.signal);
	await installCompleteFile(confined(finalDirectory, "verified-run.json"), json.bytes, "application/json");
	await options.checkpoint?.("before-write-markdown");
	throwIfCatalogHiddenFlowAborted(options.signal);
	await installCompleteFile(confined(finalDirectory, "report.md"), markdown.bytes, "text/markdown");
	await reconcileCatalogHiddenFlowPublicationStaging(finalDirectory, expectedPublicationMembers(verificationRecord, verificationIdentity));
	await options.checkpoint?.("before-commit-marker");
	throwIfCatalogHiddenFlowAborted(options.signal);
	await installCompleteFile(confined(finalDirectory, "report-verification.json"), verification.bytes, "application/json");
	await options.checkpoint?.("after-commit-marker");
	await verifyPublishedSet(root, verificationRecord, verificationIdentity, response, record);
	return {
		response,
		verificationRecord
	};
}
//#endregion
//#region src/domain/hiddenFlowSolverValidation.ts
var SHA256 = /^[a-f0-9]{64}$/;
var STATUSES = [
	"Unsolved",
	"Solved",
	"PrimalInfeasible",
	"DualInfeasible",
	"AlmostSolved",
	"AlmostPrimalInfeasible",
	"AlmostDualInfeasible",
	"MaxIterations",
	"MaxTime",
	"NumericalError",
	"InsufficientProgress",
	"CallbackTerminated",
	"Unknown"
];
function fail(path, detail) {
	throw new Error(`${path}: ${detail}`);
}
function record(value, path) {
	if (typeof value !== "object" || value === null || Array.isArray(value)) return fail(path, "must be an object.");
	return value;
}
function exactKeys(value, required, path) {
	const allowed = new Set(required);
	for (const key of required) if (!Object.prototype.hasOwnProperty.call(value, key)) fail(path, `is missing required property ${JSON.stringify(key)}.`);
	for (const key of Object.keys(value)) if (!allowed.has(key)) fail(path, `contains unsupported property ${JSON.stringify(key)}.`);
}
function property(value, key) {
	return value[key];
}
function finite(value, path) {
	if (typeof value !== "number" || !Number.isFinite(value)) return fail(path, "must be finite.");
	if (Math.abs(value) > HIDDEN_FLOW_LIMITS.maximumNumericMagnitude) fail(path, "exceeds the supported numerical magnitude.");
	return value;
}
function nullableFinite(value, path) {
	return value === null ? null : finite(value, path);
}
function integer(value, path, minimum, maximum) {
	const parsed = finite(value, path);
	if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) return fail(path, `must be an integer between ${minimum} and ${maximum}.`);
	return parsed;
}
function text(value, path, maximum = 2048) {
	if (typeof value !== "string" || value.length === 0 || value.length > maximum) return fail(path, `must be nonempty text no longer than ${maximum}.`);
	return value;
}
function boolean(value, path) {
	if (typeof value !== "boolean") return fail(path, "must be a boolean.");
	return value;
}
function finiteArray(value, path, expectedLength) {
	if (!Array.isArray(value)) return fail(path, "must be an array.");
	if (expectedLength !== void 0 && value.length !== expectedLength) fail(path, `must contain exactly ${expectedLength} values.`);
	return value.map((item, index) => finite(item, `${path}[${index}]`));
}
function stringArray(value, path) {
	if (!Array.isArray(value) || value.length > 64) return fail(path, "must be an array with at most 64 entries.");
	return value.map((item, index) => text(item, `${path}[${index}]`));
}
function digest(value, path) {
	if (typeof value !== "string" || !SHA256.test(value)) return fail(path, "must be a lowercase SHA-256 digest.");
	return value;
}
function parseMatrix(value, path, expectedRows, expectedColumns, maximumEntries = HIDDEN_FLOW_LIMITS.maximumMatrixEntries) {
	const item = record(value, path);
	exactKeys(item, [
		"rows",
		"columns",
		"values"
	], path);
	const rows = integer(property(item, "rows"), `${path}.rows`, 0, 1024);
	const columns = integer(property(item, "columns"), `${path}.columns`, 0, 96);
	if (expectedRows !== void 0 && rows !== expectedRows) fail(path, `must have ${expectedRows} rows.`);
	if (expectedColumns !== void 0 && columns !== expectedColumns) fail(path, `must have ${expectedColumns} columns.`);
	const entries = rows * columns;
	if (entries > maximumEntries) fail(path, `must contain exactly ${entries} entries within the matrix resource limit.`);
	const rawValues = property(item, "values");
	if (!Array.isArray(rawValues) || rawValues.length !== entries) fail(path, `must contain exactly ${entries} entries.`);
	const matrix = {
		rows,
		columns,
		values: rawValues.map((item, index) => finite(item, `${path}.values[${index}]`))
	};
	validateDenseMatrix(matrix, path, expectedRows, expectedColumns, maximumEntries);
	return matrix;
}
function parseSettings(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"maximumIterations",
		"absoluteGapTolerance",
		"relativeGapTolerance",
		"feasibilityTolerance",
		"infeasibilityTolerance",
		"presolveEnabled",
		"equilibrationEnabled",
		"iterativeRefinementEnabled",
		"maximumThreads"
	], path);
	const positive = (key) => {
		const parsed = finite(property(item, key), `${path}.${key}`);
		if (parsed <= 0 || parsed > 1) fail(`${path}.${key}`, "must lie in (0, 1].");
		return parsed;
	};
	integer(property(item, "maximumThreads"), `${path}.maximumThreads`, 1, 1);
	return {
		maximumIterations: integer(property(item, "maximumIterations"), `${path}.maximumIterations`, 1, 1e5),
		absoluteGapTolerance: positive("absoluteGapTolerance"),
		relativeGapTolerance: positive("relativeGapTolerance"),
		feasibilityTolerance: positive("feasibilityTolerance"),
		infeasibilityTolerance: positive("infeasibilityTolerance"),
		presolveEnabled: boolean(property(item, "presolveEnabled"), `${path}.presolveEnabled`),
		equilibrationEnabled: boolean(property(item, "equilibrationEnabled"), `${path}.equilibrationEnabled`),
		iterativeRefinementEnabled: boolean(property(item, "iterativeRefinementEnabled"), `${path}.iterativeRefinementEnabled`),
		maximumThreads: 1
	};
}
function parseSolver(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"adapter",
		"adapterVersion",
		"pythonVersion",
		"clarabelVersion",
		"scipyVersion",
		"numpyVersion",
		"image",
		"architecture",
		"linearSolver"
	], path);
	const linearSolver = property(item, "linearSolver");
	return {
		adapter: text(property(item, "adapter"), `${path}.adapter`, 256),
		adapterVersion: text(property(item, "adapterVersion"), `${path}.adapterVersion`, 64),
		pythonVersion: text(property(item, "pythonVersion"), `${path}.pythonVersion`, 64),
		clarabelVersion: text(property(item, "clarabelVersion"), `${path}.clarabelVersion`, 64),
		scipyVersion: text(property(item, "scipyVersion"), `${path}.scipyVersion`, 64),
		numpyVersion: text(property(item, "numpyVersion"), `${path}.numpyVersion`, 64),
		image: property(item, "image") === null ? null : text(property(item, "image"), `${path}.image`, 512),
		architecture: text(property(item, "architecture"), `${path}.architecture`, 64),
		linearSolver: linearSolver === null ? null : text(linearSolver, `${path}.linearSolver`, 512)
	};
}
function parseSvd(value, request, path) {
	const item = record(value, path);
	exactKeys(item, [
		"singularValues",
		"rank",
		"nullity",
		"threshold",
		"conditionEstimate",
		"nullSpaceBasis"
	], path);
	const maximumRank = Math.min(request.observationMatrix.rows, request.coefficientCount);
	const rank = integer(property(item, "rank"), `${path}.rank`, 0, maximumRank);
	const nullity = integer(property(item, "nullity"), `${path}.nullity`, 0, request.coefficientCount);
	if (rank + nullity !== request.coefficientCount) fail(path, "rank plus nullity must equal the coefficient count.");
	return {
		singularValues: finiteArray(property(item, "singularValues"), `${path}.singularValues`, maximumRank),
		rank,
		nullity,
		threshold: finite(property(item, "threshold"), `${path}.threshold`),
		conditionEstimate: nullableFinite(property(item, "conditionEstimate"), `${path}.conditionEstimate`),
		nullSpaceBasis: parseMatrix(property(item, "nullSpaceBasis"), `${path}.nullSpaceBasis`, request.coefficientCount, nullity)
	};
}
function parseCone(value, path) {
	const item = record(value, path);
	exactKeys(item, [
		"type",
		"dimension",
		"label"
	], path);
	const type = property(item, "type");
	if (type !== "zero" && type !== "nonnegative" && type !== "second-order") return fail(`${path}.type`, "is unsupported.");
	return {
		type,
		dimension: integer(property(item, "dimension"), `${path}.dimension`, 1, 1024),
		label: text(property(item, "label"), `${path}.label`, 128)
	};
}
function parseCanonicalization(value, request, path) {
	const item = record(value, path);
	exactKeys(item, [
		"q",
		"a",
		"b",
		"cones",
		"energyFactor",
		"roughnessFactor"
	], path);
	const conesValue = property(item, "cones");
	if (!Array.isArray(conesValue) || conesValue.length > 260) fail(`${path}.cones`, "must be a bounded array.");
	const cones = conesValue.map((cone, index) => parseCone(cone, `${path}.cones[${index}]`));
	const rowCount = cones.reduce((sum, cone) => sum + cone.dimension, 0);
	const parseFactor = (factor, factorPath) => factor === null ? null : parseMatrix(factor, factorPath, request.coefficientCount, request.coefficientCount);
	return {
		q: finiteArray(property(item, "q"), `${path}.q`, request.coefficientCount),
		a: parseMatrix(property(item, "a"), `${path}.a`, rowCount, request.coefficientCount, HIDDEN_FLOW_LIMITS.maximumCanonicalMatrixEntries),
		b: finiteArray(property(item, "b"), `${path}.b`, rowCount),
		cones,
		energyFactor: parseFactor(property(item, "energyFactor"), `${path}.energyFactor`),
		roughnessFactor: parseFactor(property(item, "roughnessFactor"), `${path}.roughnessFactor`)
	};
}
function parseSolution(value, request, canonicalization, path) {
	const item = record(value, path);
	exactKeys(item, [
		"status",
		"coefficients",
		"slacks",
		"dual",
		"primalObjective",
		"dualObjective",
		"iterations",
		"reportedPrimalResidual",
		"reportedDualResidual",
		"reportedAbsoluteGap",
		"reportedRelativeGap"
	], path);
	const status = property(item, "status");
	if (typeof status !== "string" || !STATUSES.includes(status)) fail(`${path}.status`, "is not a supported native status.");
	const rowCount = canonicalization.b.length;
	return {
		status,
		coefficients: finiteArray(property(item, "coefficients"), `${path}.coefficients`, request.coefficientCount),
		slacks: finiteArray(property(item, "slacks"), `${path}.slacks`, rowCount),
		dual: finiteArray(property(item, "dual"), `${path}.dual`, rowCount),
		primalObjective: nullableFinite(property(item, "primalObjective"), `${path}.primalObjective`),
		dualObjective: nullableFinite(property(item, "dualObjective"), `${path}.dualObjective`),
		iterations: integer(property(item, "iterations"), `${path}.iterations`, 0, request.solverSettings.maximumIterations),
		reportedPrimalResidual: nullableFinite(property(item, "reportedPrimalResidual"), `${path}.reportedPrimalResidual`),
		reportedDualResidual: nullableFinite(property(item, "reportedDualResidual"), `${path}.reportedDualResidual`),
		reportedAbsoluteGap: nullableFinite(property(item, "reportedAbsoluteGap"), `${path}.reportedAbsoluteGap`),
		reportedRelativeGap: nullableFinite(property(item, "reportedRelativeGap"), `${path}.reportedRelativeGap`)
	};
}
function parseHiddenFlowSolverResult(value, request) {
	const path = "hiddenFlowSolverResult";
	const item = record(value, path);
	exactKeys(item, [
		"schemaVersion",
		"requestId",
		"requestSha256",
		"canonicalSha256",
		"solver",
		"settings",
		"svd",
		"canonicalization",
		"solution",
		"warnings"
	], path);
	if (property(item, "schemaVersion") !== 1) fail(`${path}.schemaVersion`, "must equal 1.");
	const requestId = text(property(item, "requestId"), `${path}.requestId`, 128);
	if (requestId !== request.requestId) fail(`${path}.requestId`, "does not match the request.");
	const settings = parseSettings(property(item, "settings"), `${path}.settings`);
	const canonicalization = parseCanonicalization(property(item, "canonicalization"), request, `${path}.canonicalization`);
	return {
		schemaVersion: 1,
		requestId,
		requestSha256: digest(property(item, "requestSha256"), `${path}.requestSha256`),
		canonicalSha256: digest(property(item, "canonicalSha256"), `${path}.canonicalSha256`),
		solver: parseSolver(property(item, "solver"), `${path}.solver`),
		settings,
		svd: parseSvd(property(item, "svd"), request, `${path}.svd`),
		canonicalization,
		solution: parseSolution(property(item, "solution"), request, canonicalization, `${path}.solution`),
		warnings: stringArray(property(item, "warnings"), `${path}.warnings`)
	};
}
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/pinnedSolver.ts
var executeFile = promisify(execFile);
function aggregateBytes(current, byteLength, limit, resource) {
	const next = current + byteLength;
	if (!Number.isSafeInteger(byteLength) || byteLength < 0 || !Number.isSafeInteger(next) || next > limit) throw new CatalogHiddenFlowError("problem-not-executable", "verification", `The pinned hidden-flow solver ${resource} exceeds ${limit} bytes.`);
	return next;
}
async function readResult(outputPath, request, maximumBytes = HIDDEN_FLOW_LIMITS.maximumSolverResultBytes, signal) {
	const handle = await open(outputPath, constants.O_RDONLY | (typeof constants.O_NOFOLLOW === "number" ? constants.O_NOFOLLOW : 0));
	try {
		const before = await handle.stat({ bigint: true });
		if (!before.isFile() || before.nlink !== 1n || before.size <= 0n || before.size > BigInt(maximumBytes) || before.size > BigInt(Number.MAX_SAFE_INTEGER)) throw new CatalogHiddenFlowError("problem-not-executable", "verification", "The opened hidden-flow solver result is invalid, unsafe, or oversized.");
		throwIfCatalogHiddenFlowAborted(signal);
		const expectedBytes = Number(before.size);
		const bytes = Buffer.allocUnsafe(expectedBytes);
		let offset = 0;
		while (offset < expectedBytes) {
			throwIfCatalogHiddenFlowAborted(signal);
			const { bytesRead } = await handle.read(bytes, offset, expectedBytes - offset, offset);
			if (bytesRead === 0) break;
			offset += bytesRead;
		}
		const after = await handle.stat({ bigint: true });
		if (before.dev !== after.dev || before.ino !== after.ino || before.nlink !== after.nlink || before.size !== after.size || before.mtimeNs !== after.mtimeNs || offset !== expectedBytes) throw new CatalogHiddenFlowError("problem-not-executable", "verification", "The pinned hidden-flow solver result changed while it was being read.");
		const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		return {
			result: parseHiddenFlowSolverResult(JSON.parse(text), request),
			byteLength: expectedBytes
		};
	} finally {
		await handle.close();
	}
}
var PinnedPythonProcessHiddenFlowSolverAdapter = class {
	executable;
	moduleRoot;
	signal;
	constructor(context, signal) {
		if (!isAbsolute(context.pythonExecutable) || !isAbsolute(context.pythonModuleRoot)) throw new CatalogHiddenFlowError("package-attestation-failed", "package-attestation", "The pinned hidden-flow runtime must provide absolute executable and module roots.");
		this.executable = context.pythonExecutable;
		this.moduleRoot = context.pythonModuleRoot;
		this.signal = signal;
	}
	async environment() {
		return {
			PATH: "/usr/local/bin:/usr/bin:/bin",
			HOME: "/tmp",
			TMPDIR: "/tmp",
			LANG: "C.UTF-8",
			LC_ALL: "C.UTF-8",
			PYTHONPATH: await realpath(this.moduleRoot),
			PYTHONDONTWRITEBYTECODE: "1",
			PYTHONUNBUFFERED: "1",
			PYTHONHASHSEED: "0",
			OMP_NUM_THREADS: "1",
			OPENBLAS_NUM_THREADS: "1",
			OPENBLAS_CORETYPE: "NEHALEM",
			MKL_NUM_THREADS: "1",
			NUMEXPR_NUM_THREADS: "1",
			VECLIB_MAXIMUM_THREADS: "1",
			BLIS_NUM_THREADS: "1",
			FLOWBLIND_SOLVER_IMAGE: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.pythonImage
		};
	}
	async execute(arguments_) {
		throwIfCatalogHiddenFlowAborted(this.signal);
		try {
			const moduleRoot = await realpath(this.moduleRoot);
			await executeFile(this.executable, [
				"-I",
				"-c",
				"import runpy,sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module('tools.hidden_flow_solver', run_name='__main__')",
				moduleRoot,
				...arguments_
			], {
				cwd: moduleRoot,
				encoding: "utf8",
				maxBuffer: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement.maximumStdoutStderrBytes,
				timeout: FLOWBLIND_CATALOG_HIDDEN_FLOW_RUNTIME.confinement.childProcessTimeoutMilliseconds,
				windowsHide: true,
				env: await this.environment(),
				signal: this.signal
			});
		} catch (error) {
			if (this.signal?.aborted === true || error instanceof Error && error.name === "AbortError") throw new CatalogHiddenFlowError("operation-cancelled", "cancellation", "The pinned hidden-flow solver was cancelled before returning verified evidence.", { cause: error });
			throw error;
		}
		throwIfCatalogHiddenFlowAborted(this.signal);
	}
	async solve(request) {
		throwIfCatalogHiddenFlowAborted(this.signal);
		const directory = await mkdtemp(resolve(tmpdir(), "flowblind-hidden-flow-"));
		const inputPath = resolve(directory, "request.json");
		const outputPath = resolve(directory, "result.json");
		try {
			const content = stableJson(request);
			if (Buffer.byteLength(content) > HIDDEN_FLOW_LIMITS.maximumDocumentBytes) throw new CatalogHiddenFlowError("problem-not-executable", "verification", "The pinned hidden-flow solver request exceeds its bounded document limit.");
			await writeFile(inputPath, content, {
				encoding: "utf8",
				flag: "wx"
			});
			await this.execute([
				"--input",
				inputPath,
				"--output",
				outputPath
			]);
			return (await readResult(outputPath, request, void 0, this.signal)).result;
		} finally {
			await rm(directory, {
				recursive: true,
				force: true,
				maxRetries: 10,
				retryDelay: 100
			});
		}
	}
	async solveMany(requests) {
		throwIfCatalogHiddenFlowAborted(this.signal);
		if (requests.length === 0) return [];
		if (requests.length === 1) return [await this.solve(requests[0])];
		if (requests.length > HIDDEN_FLOW_LIMITS.maximumSolverBatchRequests) throw new CatalogHiddenFlowError("problem-not-executable", "verification", "The pinned hidden-flow solver batch exceeds its reviewed request-count limit.");
		const contents = [];
		let aggregateInputBytes = 0;
		for (const request of requests) {
			const content = stableJson(request);
			const byteLength = Buffer.byteLength(content);
			if (byteLength > HIDDEN_FLOW_LIMITS.maximumDocumentBytes) throw new CatalogHiddenFlowError("problem-not-executable", "verification", "A pinned hidden-flow solver request exceeds its bounded document limit.");
			aggregateInputBytes = aggregateBytes(aggregateInputBytes, byteLength, HIDDEN_FLOW_LIMITS.maximumSolverBatchInputBytes, "batch input");
			contents.push(content);
		}
		const directory = await mkdtemp(resolve(tmpdir(), "flowblind-hidden-flow-batch-"));
		const requestPath = (index) => resolve(directory, `request-${String(index).padStart(3, "0")}.json`);
		const resultPath = (index) => resolve(directory, `result-${String(index).padStart(3, "0")}.json`);
		try {
			await Promise.all(contents.map((content, index) => writeFile(requestPath(index), content, {
				encoding: "utf8",
				flag: "wx"
			})));
			await this.execute([
				"--batch-directory",
				directory,
				"--batch-count",
				String(requests.length)
			]);
			const results = [];
			let aggregateResultBytes = 0;
			for (let index = 0; index < requests.length; index += 1) {
				const remaining = HIDDEN_FLOW_LIMITS.maximumSolverBatchResultBytes - aggregateResultBytes;
				const read = await readResult(resultPath(index), requests[index], Math.min(HIDDEN_FLOW_LIMITS.maximumSolverResultBytes, remaining), this.signal);
				aggregateResultBytes = aggregateBytes(aggregateResultBytes, read.byteLength, HIDDEN_FLOW_LIMITS.maximumSolverBatchResultBytes, "batch output");
				results.push(read.result);
			}
			return results;
		} finally {
			await rm(directory, {
				recursive: true,
				force: true,
				maxRetries: 10,
				retryDelay: 100
			});
		}
	}
};
//#endregion
//#region tools/catalogCapabilities/hiddenFlow/runtime.ts
var verificationModuleReference = ["..", "flowblind-hidden-flow-capability-verification-v1.mjs"].join("/");
async function packageAuthority(value) {
	if (value === null || value === void 0) return null;
	try {
		const authority = await import(new URL(verificationModuleReference, import.meta.url).href);
		return typeof authority.flowBlindHiddenFlowPackageRuntimeAuthority === "function" ? authority.flowBlindHiddenFlowPackageRuntimeAuthority(value) : null;
	} catch {
		return null;
	}
}
function attestationRefusal() {
	return catalogHiddenFlowRefusal(new CatalogHiddenFlowError("package-attestation-failed", "package-attestation", "Direct or unverified hidden-flow capability invocation is not permitted."));
}
function ioRefusal(error) {
	return catalogHiddenFlowRefusal(error instanceof CatalogHiddenFlowError ? error : new CatalogHiddenFlowError("output-publication-conflict", "publication", "The packaged hidden-flow action failed before publishing complete verified artifacts.", { cause: error }));
}
function verifiedRun(bytes) {
	return JSON.parse(Buffer.from(bytes).toString("utf8"));
}
var catalogHiddenFlowRuntimeVersion = FLOWBLIND_CATALOG_HIDDEN_FLOW_VERSION;
var catalogHiddenFlowPackageVersion = FLOWBLIND_CATALOG_HIDDEN_FLOW_PACKAGE_VERSION;
var catalogHiddenFlowSupportedActions = FLOWBLIND_CATALOG_HIDDEN_FLOW_ACTIONS;
function serializeCatalogHiddenFlowValue(value) {
	return stableJson(value);
}
async function catalogHiddenFlowDeclarationPreview(packageVerification) {
	const authority = await packageAuthority(packageVerification);
	if (authority === null) return attestationRefusal();
	return {
		declaration: FLOWBLIND_CATALOG_HIDDEN_FLOW_DECLARATION,
		package: authority.packageVerification
	};
}
async function callCatalogHiddenFlowAction(action, input, context, packageVerification) {
	const packageRuntime = await packageAuthority(packageVerification);
	if (packageRuntime === null) {
		const response = attestationRefusal();
		assertCatalogHiddenFlowActionResponseSemanticContract(response);
		return {
			response,
			bundle: null
		};
	}
	const reviewAuthority = createAttestedGenericHiddenFlowReviewAuthority(packageRuntime.packageVerification);
	if (action === "prepare-study" && context.selectedProblemBytes !== void 0) {
		const prepared = prepareCatalogHiddenFlow(input, { selectedProblemBytes: context.selectedProblemBytes }, {
			reviewAuthority,
			signal: context.signal
		});
		assertCatalogHiddenFlowActionResponseSemanticContract(prepared.response);
		return prepared;
	}
	if (action === "run-and-verify-study" && context.preparationBundleBytes !== void 0) {
		const run = await runCatalogHiddenFlow(input, { preparationBundleBytes: context.preparationBundleBytes }, {
			reviewAuthority,
			signal: context.signal,
			solver: new PinnedPythonProcessHiddenFlowSolverAdapter(packageRuntime.pinnedRuntime, context.signal)
		});
		assertCatalogHiddenFlowActionResponseSemanticContract(run.response, "artifacts" in run && run.artifacts !== null ? { verifiedRun: verifiedRun(run.artifacts.json.bytes) } : {});
		return run;
	}
	const refusal = catalogHiddenFlowRefusal(new CatalogHiddenFlowError("input-invalid", "input-validation", "Only the reviewed prepare-study and run-and-verify-study actions with matching host-selected attachment contexts are supported."));
	assertCatalogHiddenFlowActionResponseSemanticContract(refusal);
	return {
		response: refusal,
		bundle: null
	};
}
async function callPackagedCatalogHiddenFlowAction(action, input, context, packageVerification) {
	try {
		if (action !== "prepare-study" && action !== "run-and-verify-study") throw new CatalogHiddenFlowError("input-invalid", "input-validation", "Only the reviewed prepare-study and run-and-verify-study actions are supported.");
		const selected = await loadSingleCatalogHiddenFlowAttachment(context.inputRoot, context.signal);
		if (action === "prepare-study") {
			const prepared = await callCatalogHiddenFlowAction(action, input, {
				selectedProblemBytes: selected.bytes,
				signal: context.signal
			}, packageVerification);
			if ("bundle" in prepared && prepared.bundle !== null) await publishCatalogHiddenFlowArtifact(context.outputRoot, prepared.bundle, context.signal);
			return prepared.response;
		}
		const run = await callCatalogHiddenFlowAction(action, input, {
			preparationBundleBytes: selected.bytes,
			signal: context.signal
		}, packageVerification);
		if ("artifacts" in run && run.artifacts !== null) {
			const published = await publishCatalogHiddenFlowReportSet(context.outputRoot, run, { signal: context.signal });
			assertCatalogHiddenFlowReportSetSemanticContract(published.response, published.verificationRecord, published.response.artifacts.verification, verifiedRun(run.artifacts.json.bytes));
			return published.response;
		}
		return run.response;
	} catch (error) {
		const refusal = ioRefusal(error);
		assertCatalogHiddenFlowActionResponseSemanticContract(refusal);
		return refusal;
	}
}
//#endregion
export { assertCatalogHiddenFlowActionResponseSemanticContract, assertCatalogHiddenFlowReportSetSemanticContract, callCatalogHiddenFlowAction, callPackagedCatalogHiddenFlowAction, catalogHiddenFlowDeclarationPreview, catalogHiddenFlowPackageVersion, catalogHiddenFlowRuntimeVersion, catalogHiddenFlowSupportedActions, serializeCatalogHiddenFlowValue };

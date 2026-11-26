(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TokenEstimation = factory();
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const VERSION = '1.2.0';
  const INPUT_VERSIONS = ['1.0.0', '1.1.0', VERSION];
  const UNIT = 'input_plus_output_tokens';

  function fail(path, message) {
    const error = new Error(path + ': ' + message);
    error.code = 'INVALID_INPUT';
    error.path = path;
    throw error;
  }
  function object(value, path, keys) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) fail(path, 'expected an object');
    for (const key of Object.keys(value)) {
      if (!keys.includes(key)) fail(path + '.' + key, 'unsupported field; token inputs are not accepted');
    }
  }
  function text(value, path) {
    if (typeof value !== 'string' || !value.trim()) fail(path, 'expected nonempty text');
  }
  function count(value, path) {
    if (!Number.isSafeInteger(value) || value < 1) fail(path, 'expected a positive safe integer');
    return value;
  }
  function multiply(a, b, path) {
    const result = a * b;
    if (!Number.isSafeInteger(result)) fail(path, 'token range exceeds safe integer arithmetic');
    return result;
  }
  function add(a, b) {
    const result = a + b;
    if (!Number.isSafeInteger(result)) fail('tasks', 'aggregate range exceeds safe integer arithmetic');
    return result;
  }
  function range(lower, upper) { return { lower, upper, unit: UNIT }; }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  // Deliberately narrow recognition rules; a match is still only a provisional analogy.
  const RULES = [
    ['evidence-assessment', /\b(assess(?:ment)?|review)\b.*\b(evidence|outcomes?|existing results)\b|\bevidence\b.*\b(assessment|review)\b/i],
    ['literature-screening-synthesis', /\b(screen(?:ing)?|extract(?:ion)?)\b.*\b(literature|documents?|evidence table)\b|\b(literature|documents?)\b.*\b(screen(?:ing)?|extract(?:ion)?)\b/i],
    ['tool-verification-analysis', /\b(verif(?:y|ication)|check)\b.*\b(tool|numerical result|reference comparison)\b|\btool\b.*\b(verif(?:y|ication)|reference comparisons?)\b/i],
    ['simulation-development-execution', /\b(simulation|solver)\b/i],
    ['prediction-development-validation', /\b(prediction|predictive|training workflow|model fitting|forecast(?:ing)?)\b|\b(real[ -]data|real[ -]world|observed data)\b.*\bmodel\b|\bmodel\b.*\b(real[ -]data|real[ -]world|observed data)\b/i]
  ];
  const OPERATION = /\b(run|execute|launch|start|set[ -]?up|configure|troubleshoot|prepare commands?)\b/i;
  const EXISTING = /\b(existing|working|documented|provided|known|already (?:built|working|available))\b/i;
  const WORKFLOW = /\b(simulation|solver|workflow|tool|pipeline|script)\b/i;
  const DEVELOPMENT = /\b(develop|implement(?:ation)?|build|adapt|port|prototype|integrat(?:e|ion)|sweep|modeling|modelling)\b|\bscientific[ -]model development\b|\b(correct|fix|repair|debug)\b.{0,30}\b(model|solver|simulation|scientific)\b/i;

  function affirmativeWork(description) {
    const item = '(?:raw[ -]data (?:preparation|cleaning)|scientific[ -]model development)';
    const list = item + '(?:(?:\\s+(?:and|or|nor)\\s+|\\s*,\\s*(?:(?:and|or|nor)\\s+)?)' + item + ')*';
    const location = '(?: (?:from|in|for) (?:this|the|the same) (?:focused |bounded )?(?:task|session|scope))?';
    const exclusion = '(?:(?:no(?: new)?|without|excluding|exclude|not including|neither)\\s+' +
      list + location + '|' + list + '\\s+(?:(?:is|are) )?(?:explicitly )?(?:excluded|not included|out of scope)' + location + ')';
    const complete = new RegExp('(?:^|[,(])\\s*(' + exclusion + ')\\s*(?=$|[,)])', 'gi');
    const qualified = /\b(?:if|unless|perhaps|might|may|could|should|would|plan|proposal|propos(?:e|ed)|reject(?:ed)?|not|no|never|without|neither|cannot|false|deny|conditional|don't|doesn't|isn't|aren't|can't|won't|mustn't)\b|["?]/i;
    // Match complete assertions, retaining their surrounding statement as context.
    return description.split(/([.;\n])/).map(statement => {
      if (/\b(?:but|however|yet)\b/i.test(statement)) return statement;
      return statement.replace(complete, (match, assertion, offset) => {
        const preamble = statement.slice(0, offset).replace(/[,(\s]+$/, '');
        const after = statement.slice(offset + match.length);
        const directOperation = /^\s*(?:launch|execute|run|start|read|understand|prepare|configure|troubleshoot)\b/i.test(preamble) &&
          EXISTING.test(preamble) && WORKFLOW.test(preamble) && !qualified.test(preamble);
        if (preamble && !directOperation || qualified.test(after)) return match;
        return match.replace(assertion, '');
      });
    }).join('');
  }

  function createEstimator(data) {
    if (!data || !data.calibration || !data.profiles) throw new Error('Calibration and profiles are required');
    const calibration = clone(data.calibration);
    const profiles = clone(data.profiles);
    if (calibration.schema_version !== '1.0' || profiles.schema_version !== '1.2') {
      throw new Error('Unsupported calibration/profile schema');
    }
    const observations = new Map(calibration.observations.map(o => [o.id, o]));
    const bands = new Map(profiles.bands.map(b => [b.id, b]));
    const byProfile = new Map(profiles.profiles.map(p => [p.id, p]));
    const byPhase = new Map(profiles.phases.map(p => [p.id, p]));
    if (byPhase.size !== profiles.phases.length || byProfile.size !== profiles.profiles.length ||
        bands.size !== profiles.bands.length || observations.size !== calibration.observations.length) {
      throw new Error('Duplicate calibration/profile/phase/band identity');
    }
    const scopeRule = new RegExp(profiles.selection.unsupported_scope_pattern, 'i');
    const operationComparison = profiles.selection.operation_comparison;
    if (!operationComparison || !Number.isSafeInteger(operationComparison.max_retry_limit) ||
        operationComparison.max_retry_limit < 1 || !Number.isSafeInteger(operationComparison.max_monitoring_checks) ||
        operationComparison.max_monitoring_checks < 1 || !operationComparison.interpretation) {
      throw new Error('Missing focused operation comparison policy');
    }
    function affirmativePreparationExclusion(description, match) {
      const before = description.slice(0, match.index).split(/[.;\n]/).pop().trim();
      const after = description.slice(match.index + match[0].length).split(/[.;\n]/)[0].trim();
      // Accept complete local clauses, not an exclusion token embedded in another assertion.
      const preamble = /^(?:develop|correct|integrate|assess|screen|verify)(?:[ -]+(?:a|an|one|the|and|validate|debug|existing|initial|focused|bounded|real|data|predictive|prediction|synthetic|simulation|implementation|package|model|trajectory|distribution|workflow|using|component|models|evidence|outcomes|in|session|literature|extract|concise|table|numerical|tool|with|reference|comparisons|short|report|packing|sweep|included|checks|for|task))+[,:]\s*/i.exec(before);
      const prefix = preamble ? before.slice(preamble[0].length) : before;
      const location = '(?:(?:from|in|for) (?:this|the|the same) (?:focused |bounded )?(?:task|session|scope))?';
      const tail = new RegExp('^' + location + '$', 'i');
      const prefixExclusion = /^(?:(?:explicitly )?(?:exclude|excluding)|(?:this (?:task|session)|we) excludes?|without|no(?: new)?|not including|(?:does|do|will) not include)$/i;
      const suffixExclusion = new RegExp('^(?:(?:is|are) )?(?:explicitly )?(?:excluded|not included|out of scope)(?: ' + location + ')?$', 'i');
      return prefixExclusion.test(prefix) && tail.test(after) ||
        prefix === '' && suffixExclusion.test(after);
    }
    function includedUnsupportedScope(description, computational) {
      for (const match of description.matchAll(new RegExp(scopeRule.source, 'gi'))) {
        if (/\braw[ -]data\b/i.test(match[0])) {
          if (!affirmativePreparationExclusion(description, match)) return true;
        } else if (computational) return true;
      }
      return false;
    }
    const phaseRules = profiles.phases.map(phase => ({
      phase, include: new RegExp(phase.recognition.pattern, 'i'),
      exclude: phase.recognition.exclude ? new RegExp(phase.recognition.exclude, 'i') : null
    }));
    for (const band of bands.values()) {
      if (!Number.isSafeInteger(band.lower) || !Number.isSafeInteger(band.upper) ||
          band.lower < 1 || band.upper < band.lower) {
        throw new Error('Invalid numeric calibration: ' + band.id);
      }
      const anchor = observations.get(band.anchor_id);
      if (!anchor) throw new Error('Missing calibration observation: ' + band.anchor_id);
      if (band.comparison_ids && (!Array.isArray(band.comparison_ids) ||
          new Set(band.comparison_ids).size !== band.comparison_ids.length ||
          !band.comparison_ids.includes(band.anchor_id) ||
          band.comparison_ids.some(id => !observations.has(id)))) {
        throw new Error('Invalid comparison calibration: ' + band.id);
      }
    }
    for (const target of [...byProfile.values(), ...byPhase.values()]) {
      if (target.token_band_id && (!bands.has(target.token_band_id) ||
          bands.get(target.token_band_id).use !== 'bounded_session_analogy')) {
        throw new Error('Invalid numeric profile/phase calibration: ' + target.id);
      }
      for (const id of target.evidence_ids) {
        if (!observations.has(id)) throw new Error('Missing calibration observation: ' + id);
      }
      if (target.profile_id) {
        const profile = byProfile.get(target.profile_id);
        const band = bands.get(target.token_band_id);
        if (!profile || !Array.isArray(profile.phase_ids) || !band ||
            !profile.phase_ids.includes(target.id) || !target.evidence_ids.includes(band.anchor_id)) {
          throw new Error('Invalid phase attribution: ' + target.id);
        }
      } else if (target.phase_ids && target.phase_ids.some(id => !byPhase.has(id))) {
        throw new Error('Missing phase for profile: ' + target.id);
      }
    }

    function evidence(id) {
      const observation = observations.get(id);
      if (!observation) throw new Error('Missing calibration observation: ' + id);
      // Source pointers are inert provenance, never filesystem instructions.
      return clone({
        observationId: id,
        attributionUnit: observation.attribution_unit || null,
        calibrationRef: observation.calibration_ref || calibration.task || 'community-reference',
        summary: observation.summary || 'Provisional reference observation for coarse planning only.',
        limitations: Array.isArray(observation.limitations) ? observation.limitations : []
      });
    }

    function estimate(input) {
      object(input, '$', ['contractVersion', 'tasks', 'concurrency', 'nonOverlap', 'scopeDescription']);
      if (!INPUT_VERSIONS.includes(input.contractVersion)) fail('contractVersion', 'expected 1.0.0 or ' + VERSION);
      if (!Array.isArray(input.tasks) || !input.tasks.length) fail('tasks', 'expected at least one explicit task');
      if (input.nonOverlap !== undefined && typeof input.nonOverlap !== 'boolean') fail('nonOverlap', 'expected boolean');
      if (input.scopeDescription !== undefined) text(input.scopeDescription, 'scopeDescription');
      const concurrency = input.concurrency === undefined ? 1 : count(input.concurrency, 'concurrency');
      const ids = new Set();
      const clarifications = [];
      const results = input.tasks.map((task, index) => {
        const path = 'tasks[' + index + ']';
        object(task, path, ['id', 'profileId', 'phaseId', 'readiness', 'description', 'count', 'bounded', 'depth', 'validation', 'amountDescription', 'retryLimit', 'monitoring', 'monitoringChecks']);
        text(task.id, path + '.id');
        if (ids.has(task.id)) fail(path + '.id', 'duplicate task id');
        ids.add(task.id);
        if (task.profileId !== undefined) text(task.profileId, path + '.profileId');
        if (task.phaseId !== undefined) text(task.phaseId, path + '.phaseId');
        if (task.readiness !== undefined && !['ready', 'not-ready', 'unresolved'].includes(task.readiness)) fail(path + '.readiness', 'expected ready, not-ready or unresolved');
        if (task.description !== undefined) text(task.description, path + '.description');
        if (!task.profileId && !task.description) fail(path, 'provide profileId or a work description');
        if (task.bounded !== undefined && typeof task.bounded !== 'boolean') fail(path + '.bounded', 'expected boolean');
        if (task.amountDescription !== undefined) text(task.amountDescription, path + '.amountDescription');
        if (task.depth !== undefined && !['bounded', 'unresolved'].includes(task.depth)) fail(path + '.depth', 'expected bounded or unresolved');
        if (task.validation !== undefined && !['included', 'separate-tasks', 'unresolved'].includes(task.validation)) fail(path + '.validation', 'expected included, separate-tasks or unresolved');
        if (task.retryLimit !== undefined && (!Number.isSafeInteger(task.retryLimit) || task.retryLimit < 0)) fail(path + '.retryLimit', 'expected a nonnegative safe integer');
        if (task.monitoring !== undefined && !['startup-only', 'bounded', 'ongoing', 'unresolved'].includes(task.monitoring)) fail(path + '.monitoring', 'expected startup-only, bounded, ongoing or unresolved');
        if (task.monitoringChecks !== undefined) count(task.monitoringChecks, path + '.monitoringChecks');
        if (task.monitoringChecks !== undefined && task.monitoring !== 'bounded') fail(path + '.monitoringChecks', 'requires monitoring=bounded');
        const n = task.count === undefined ? 1 : count(task.count, path + '.count');
        const description = task.description || '';
        const affirmative = affirmativeWork(description);
        const operationIntent = OPERATION.test(affirmative) && EXISTING.test(affirmative) &&
          WORKFLOW.test(affirmative) &&
          !/\b(?:repeat|monitoring|supervision)[ -]only\b|\bonly monitor\b/i.test(description);
        const mixedOperation = operationIntent && DEVELOPMENT.test(affirmative);
        const operationDescription = operationIntent && !mixedOperation;
        const described = operationDescription ? ['existing-workflow-operation'] :
          task.description ? RULES.filter(([, rule]) => rule.test(affirmative)).map(([id]) => id) : [];
        const candidates = task.profileId ? (byProfile.has(task.profileId) ? [task.profileId] : []) : described;
        const profile = candidates.length === 1 ? byProfile.get(candidates[0]) : null;
        const phaseCandidates = profile && profile.phase_ids ? phaseRules.filter(rule =>
          rule.phase.profile_id === profile.id && rule.include.test(affirmative) &&
          !(rule.exclude && rule.exclude.test(affirmative))).map(rule => rule.phase.id) : [];
        const requestedPhase = task.phaseId ? byPhase.get(task.phaseId) : null;
        const phase = task.phaseId ? requestedPhase :
          phaseCandidates.length === 1 ? byPhase.get(phaseCandidates[0]) : null;
        const reasons = [];
        const additions = [];
        if (mixedOperation) reasons.push('Existing-workflow launch and scientific development are mixed in one task; neither phase allowance covers both. Separate their deliverables and shared work before estimating the full scope.');
        if (profile && described.some(id => id !== profile.id)) reasons.push('Description conflicts with the selected work class or mixes work classes.');
        if (task.phaseId && (!phase || !profile || phase.profile_id !== profile.id)) reasons.push('Unknown phase or phase does not belong to the selected work class.');
        if (task.phaseId && phaseCandidates.some(id => id !== task.phaseId)) reasons.push('Explicit phase conflicts with the described phase.');
        if (phaseCandidates.length > 1) reasons.push('Multiple development phases are described in one task; separate disjoint deliverables or clarify shared work.');
        const computational = !!(profile && profile.phase_ids);
        const operational = !!(profile && profile.id === 'existing-workflow-operation');
        const uncertainReadiness = operational && (
          /\b(?:unknown|uncertain|unresolved|unconfirmed|unsure)\b.{0,35}\b(?:environment|access|permissions?|inputs?|instructions?|readiness)\b/i.test(description) ||
          /\b(?:environment|access|permissions?|inputs?|instructions?|readiness)\b.{0,35}\b(?:unknown|uncertain|unresolved|unconfirmed)\b/i.test(description) ||
          /\b(?:not sure|do not know|don't know)\b.{0,50}\b(?:environment|access|permissions?|inputs?|instructions?)\b/i.test(description));
        const failedReadiness = operational && /\bfailed setup\b|\b(?:environment|access|permissions?|setup)\b.{0,25}\b(?:not ready|missing|failed|unavailable|denied|blocked)\b|\bmissing (?:instructions|inputs|permissions)\b|\bno (?:access|permission)\b/i.test(description);
        const readiness = task.readiness || (uncertainReadiness ? 'unresolved' : failedReadiness ? 'not-ready' : undefined);
        if (operational && task.readiness === 'ready' && (uncertainReadiness || failedReadiness)) {
          reasons.push('Confirmed-ready selection conflicts with described missing/uncertain environment, inputs or access; resolve readiness or scope failed-setup troubleshooting.');
        }
        if (!operational && [task.retryLimit, task.monitoring, task.monitoringChecks].some(value => value !== undefined)) {
          reasons.push('Retry and monitoring scope belongs to an existing-workflow operation, not development or review.');
        }
        if (computational && profile.id === 'simulation-development-execution' &&
            /\b(implement|build|adapt|port)\b.*\b(and|then|plus)\b.*\b(correct|fix|repair|sweep)\b/i.test(description)) {
          reasons.push('Implementation and a second simulation phase are mixed in one task; clarify their boundary and overlap rather than silently selecting the sweep/correction band.');
        }
        const executionOnly = /\b(run|execute|repeat|monitor|supervise)\b/i.test(description) &&
          !/\b(develop|implement(?:ation)?|build|adapt|correct|fix|repair|debug|prototype|integrat(?:e|ion)|sweep|modeling|modelling)\b/i.test(description);
        // Operational setup is not raw scientific data preparation; retain the same negation gate.
        const operationalScope = operational ? affirmative.replace(/\b(?:only (?:run|execute)|execution[ -]only|external[ -]only)\b/gi, '') : affirmative;
        const unsupportedScope = includedUnsupportedScope(operationalScope, computational) || computational && (!operational && executionOnly ||
          /\b(whole|entire|full|complete)\b.{0,40}\b(project|investigation|campaign|programme)\b/i.test(description));
        const unsupportedMatches = [...operationalScope.matchAll(new RegExp(scopeRule.source, 'gi'))];
        const preparationAddition = unsupportedScope && phase && unsupportedMatches.length > 0 &&
          unsupportedMatches.every(match => /\braw[ -]data\b/i.test(match[0])) &&
          (operational || !executionOnly);
        if (preparationAddition) additions.push('Raw scientific data preparation is outside the selected task analogy. Only the conditional development/operation base is shown; additional preparation and the full combined total remain unknown.');
        else if (unsupportedScope) reasons.push(profiles.selection.unsupported_scope_reason);
        const externalAmbiguity = operational && /\bexternal[ -]only\b/i.test(description) &&
          !/\b(read|understand|instructions?|config(?:uration)?|commands?|startup|confirm|AI)\b/i.test(description);
        const resourceOnly = computational && /\b(?:CPU|GPU|runtime|cost|utilization|resources?)\b/i.test(description) &&
          !DEVELOPMENT.test(affirmative) && !/\b(?:AI|instructions?|commands?|startup)\b/i.test(description);
        const monitoringOnly = operational && (!OPERATION.test(description) && /\bmonitor/i.test(description));
        if (externalAmbiguity) reasons.push('External-only is ambiguous: clarify whether AI instruction/input review, command preparation and startup confirmation are requested, or only solver compute.');
        if (resourceOnly || monitoringOnly) reasons.push('Pure external resources or monitoring-only work is not a bounded AI launch operation.');
        if (operational && (DEVELOPMENT.test(affirmative) || /\b(greenfield|from scratch)\b/i.test(affirmative))) reasons.push('Scientific development is not included in an operational setup allowance.');
        const comparisonExceeded = operational && (
          task.retryLimit > operationComparison.max_retry_limit ||
          task.monitoringChecks > operationComparison.max_monitoring_checks);
        if (comparisonExceeded) additions.push('Requested retry/status-inspection scope exceeds the focused startup comparison policy. Only the conditional startup base is shown; additional work has no calibrated rate.');
        if (operational && (task.monitoring === 'ongoing' || task.monitoring === 'unresolved' ||
            /\b(continuous(?:ly)?|ongoing|indefinite|unlimited|unbounded|open[ -]ended)\b|\buntil (?:the )?(?:job|simulation|solver|workflow) (?:finishes|completes)\b/i.test(description) ||
            /\b(?:monitor|watch)\b.*\buntil (?:completion|complete|finished)\b/i.test(description))) {
          additions.push('Ongoing monitoring or open-ended troubleshooting has no calibrated rate; the conditional startup base excludes that unmeasured work.');
        }
        if (operational && task.monitoring === 'bounded' && task.monitoringChecks === undefined) {
          additions.push('Bounded monitoring needs an explicit maximum number of status inspections; only the startup base is covered, not assumed free monitoring.');
        }
        if (operational && /\b(?:retry|retries|monitor|monitoring)\b/i.test(description) &&
            task.retryLimit === undefined && task.monitoring === undefined) {
          additions.push('Clarify the retry limit and whether monitoring ends at startup/error confirmation or has a bounded inspection limit.');
        }
        if (operational && /\b(?:retry|retries)\b/i.test(description) && task.retryLimit === undefined) {
          additions.push('An explicitly requested retry loop needs a finite retry limit; the conditional startup base does not cover that loop.');
        }
        if (operational && /\b(?:monitor|monitoring|watch)\b/i.test(description) &&
            task.monitoring !== 'bounded' && !/\b(?:startup|start[ -]up|initial|error confirmation)\b/i.test(description)) {
          additions.push('Requested monitoring beyond startup needs a bounded inspection scope; startup-only metadata cannot erase that work.');
        }
        if (operational && (n > 1 && /\b(shared|same setup|repeat|rerun)\b/i.test(description))) {
          reasons.push('Shared setup/repeats belong inside one scoped operation; do not multiply the operation allowance by repeat count.');
        }
        const integrationUnready = phase && phase.id === 'prediction-pipeline-integration' && !task.phaseId &&
          !/\b(existing|reus(?:e|ing|able)|already (?:built|working|available))\b/i.test(task.description || '');
        const boundedTroubleshooting = operational && task.bounded === true && task.retryLimit !== undefined &&
          /\b(troubleshoot|repair|fix|failed setup|setup fail|environment|command)\b/i.test(description);
        if (operational && (readiness === 'unresolved' || readiness === 'not-ready' && !boundedTroubleshooting)) {
          additions.push('Readiness is not established. The base is conditional on usable instructions/inputs and environment/access/permission, or a comparable local blocked-or-ready attempt. Additional preparation/repair remains unknown; no ready launch or success is promised.');
        }
        if (profile && !operational && (task.readiness === 'unresolved' || task.readiness === 'not-ready' || integrationUnready)) {
          additions.push('Component, data or method readiness/comparability is unresolved. The base is conditional on usable data/components and a comparable method/environment; additional preparation is unknown, not zero.');
        }
        if (computational && /\bindependent (review|validation|assessment)\b/i.test(description)) {
          additions.push('Independent checking is a separate deliverable, not an included-check multiplier; describe its nonoverlapping scope explicitly.');
        }
        if (operational && task.validation === 'separate-tasks' && !input.tasks.some(other =>
            other.id !== task.id && (other.profileId === 'evidence-assessment' || /\bindependent\b/i.test(other.description || '')))) {
          additions.push('List the genuinely disjoint independent review as its own task, or include startup/local verification once in this operation.');
        }
        const mapping = {
          basis: task.profileId ? 'explicit_profile' : 'description_rule_v1',
          requestedProfileId: task.profileId || null,
          requestedPhaseId: task.phaseId || null,
          candidates, phaseCandidates,
          phaseBasis: task.phaseId ? 'explicit_phase' : computational ? (phase ? 'description_phase_rules_v1.2' : 'coarse_class_envelope') : null,
          ambiguous: candidates.length > 1 || phaseCandidates.length > 1 || reasons.some(reason => /conflict/i.test(reason)),
          status: profile && !reasons.length ? 'provisional_analogy' : 'unresolved'
        };
        const selected = phase && profile && phase.profile_id === profile.id ? phase : profile;
        const classPhases = computational && !phase ? profile.phase_ids.map(id => byPhase.get(id)) : [];
        const classBands = [...new Set(classPhases.map(item => item.token_band_id))].map(id => bands.get(id));
        const band = selected && selected.token_band_id ? bands.get(selected.token_band_id) :
          classBands.length ? {
            id: 'class-envelope:' + profile.id,
            lower: Math.min(...classBands.map(item => item.lower)),
            upper: Math.max(...classBands.map(item => item.upper))
          } : null;
        const evidenceIds = [...new Set((selected ? selected.evidence_ids : [])
          .concat(classPhases.flatMap(item => item.evidence_ids)))];
        const questions = [];
        if (mixedOperation || operationIntent && unsupportedScope) questions.push('Which launch/setup work and scientific development or raw-data preparation are separate deliverables, and which checks/setup are shared? List only justified disjoint tasks; otherwise the full mixed-scope total remains unknown.');
        if (comparisonExceeded) questions.push('Can this be re-scoped to one focused command/environment attempt with a few startup inspections and a blocked-or-ready handoff? Describe the retry/inspection work and stopping condition; separate broader troubleshooting or monitoring instead of asserting that a finite count fits one session.');
        if (!profile && !unsupportedScope) questions.push('What deliverable is needed? Clarify the work or identify its general work profile; no nearest-band fallback is used.');
        if (reasons.length && !unsupportedScope && !mixedOperation && !comparisonExceeded) questions.push(operational ?
          'Does AI need to read instructions/inputs, prepare commands, launch and confirm startup? Are environment/access/permissions ready; what finite troubleshooting/retry and status-inspection limits apply, and are checks included or genuinely disjoint?' :
          'Which single focused phase and deliverable is intended, what data/components already work, and which work is separate rather than shared?');
        if (band && task.bounded !== true) additions.push('Planning scale assumption: one comparable task/session per listed deliverable, not a confirmed scope fact. Broader or multiple-session work is unknown; the displayed base is not its full total.');
        if (band && (task.depth === 'unresolved' || task.validation === 'unresolved')) {
          additions.push('Deeper work or validation is unresolved. The base includes usual local checks once; additional depth/independent review is unknown, not zero.');
          questions.push('Which deeper work or validation is already included, and which is a separate independent deliverable? List separate tasks explicitly.');
        }
        if (additions.length && !questions.length) questions.push('What additional preparation, depth, review or monitoring is needed beyond the conditional comparison base? Clarify only the unresolved part; a phase is optional.');
        const supported = !!band && !reasons.length;
        const conditional = supported && additions.length > 0;
        for (const question of questions) clarifications.push({ taskId: task.id, question });
        const perUnit = supported ? range(band.lower, band.upper) : null;
        return {
          id: task.id, description: task.description || null, profileId: profile ? profile.id : null,
          phaseId: phase && profile && phase.profile_id === profile.id ? phase.id : null,
          count: n, mapping,
          status: supported ? (conditional ? 'partial' : 'estimated') : 'unknown',
          attributionUnit: selected ? selected.estimation_unit : null,
          unknownReasons: supported ? additions : reasons.concat(questions),
          uncertainty: computational ?
            'Provisional task/session analogy with substantial transfer uncertainty; bundled references are not complete lifetime totals, independent replications, statistical intervals or external jobs.' :
            'Bounded session analogy, not statistical bounds or whole-investigation coverage.',
          perUnitTokens: perUnit,
          listedTaskTokens: supported ? range(multiply(band.lower, n, path + '.count'), multiply(band.upper, n, path + '.count')) : null,
          drivers: { amountDescription: task.amountDescription || null, depth: task.depth || (supported ? 'bounded_assumed' : 'unresolved'), validation: task.validation || (supported ? 'included_assumed' : 'unresolved'), readiness: readiness || (computational && supported ? 'ready_assumed' : 'not_established'), explicitTaskCount: n,
            ...(operational ? { retryLimit: task.retryLimit ?? 1, retryBasis: task.retryLimit === undefined ? 'comparison_assumption' : 'explicit_scope_not_rate', monitoring: task.monitoring || 'startup-only', monitoringChecks: task.monitoringChecks ?? null } : {}) },
          assumptions: selected ? selected.assumptions.map(assumption => band && (!supported || conditional) ?
            'Profile analogy condition (not established for this task): ' + assumption : assumption).concat(classBands.length ? [
            'Optional phase not selected: class envelope takes the minimum lower and maximum upper of existing comparable phase bands (' + classBands.map(item => item.id).join(', ') + '), not their sum or a cheapest-phase selection. These are alternative task scenarios, not a complete sequential workflow.',
            'Readiness is a comparison condition, not a fact: usable data/components/instructions and a comparable environment are assumed only for the base; preparation beyond that condition is unmeasured.'
          ] : []).concat(band ? [
            supported ? 'Each count is a distinct hypothetical work unit comparable to one profile anchor; scope/depth equivalence is an unmeasured modeling assumption.' :
              'A numeric session analogy requires distinct comparable work units; scope/depth equivalence is not established.',
            supported ? 'Checks already inside the session are included once. Additional independent review must be a separate task; no hidden depth, size or repeat multiplier.' :
              'For a session analogy, checks inside the session count once. Additional independent review must be a separate task; no hidden depth, size or repeat multiplier.'
          ] : []).concat(operational ? [
            'Focused comparison assumption: retry and inspection work is limited to local command/environment readiness and a short startup-or-blocked handoff, not repeated scientific analysis or job-lifetime supervision. ' + operationComparison.interpretation,
            'Operational boundary: ' + (task.retryLimit === undefined ? 'at most one retry assumed' : 'at most ' + task.retryLimit + ' retries requested') +
              '; ' + (task.monitoring === 'bounded' ? 'at most ' + (task.monitoringChecks ?? 'unresolved') + ' status inspections' : (task.monitoring || 'startup-only') + ' confirmation') +
              '. Limits are comparison scope, not measured token rates or guaranteed coverage; if repair/inspection becomes substantial, re-scope rather than multiply.',
            boundedTroubleshooting ? 'Failed setup is a bounded local command/environment troubleshooting analogy; success is not promised and unresolved access may end in a blocked handoff.' :
              'No successful cluster-launch endpoint was measured in the selected operational evidence; transfer to launch/confirmation is a provisional assumption.'
          ] : []) : [],
          notCovered: selected ? selected.not_covered.concat(additions) : ['No supported calibration for this work description/profile.'],
          provenance: profile ? {
            method: profiles.range_method.id,
            bandId: supported ? band.id : null,
            ...(classBands.length ? { componentBandIds: classBands.map(item => item.id), envelopeRule: 'minimum_lower_maximum_upper_alternative_phase_bands_not_sum' } : {}),
            evidence: evidenceIds.map(evidence),
            interpretation: profiles.range_method.interpretation
          } : null,
          externalCompute: {
            estimatedElapsedSeconds: null, estimatedCpuCoreSeconds: null, estimatedGpuSeconds: null,
            allocatedResources: null, utilization: null,
            historicalMetricReferences: profile ? clone(profile.external_compute.historical_metric_refs || []) : [],
            note: profile ? profile.external_compute.note : 'Unknown; no external compute analogy selected.'
          }
        };
      });
      const composed = results.length > 1 || results.some(t => t.count > 1);
      const canSum = !composed || input.nonOverlap === true;
      if (!canSum && results.some(task => task.listedTaskTokens)) clarifications.push({ taskId: null, question: 'Are all listed task units distinct and nonoverlapping, including repetitions? Set nonOverlap=true only if so; shared/contained work must not be summed.' });
      let lower = 0, upper = 0, knownUnits = 0, totalUnits = 0;
      for (const task of results) {
        totalUnits = add(totalUnits, task.count);
        if (task.listedTaskTokens) {
          knownUnits = add(knownUnits, task.count);
          if (canSum) {
            lower = add(lower, task.listedTaskTokens.lower);
            upper = add(upper, task.listedTaskTokens.upper);
          }
        }
      }
      const subtotal = canSum && knownUnits ? range(lower, upper) : null;
      const complete = canSum && results.every(task => task.status === 'estimated');
      return {
        contractVersion: VERSION, modelVersion: VERSION,
        status: complete ? 'estimated' : knownUnits ? 'partial' : 'unknown',
        boundary: 'listed_hypothetical_tasks_only',
        scopeDescription: input.scopeDescription || null,
        coverage: { totalUnits, knownUnits, unknownUnits: totalUnits - knownUnits, aggregationAllowed: canSum, completeForListedTasks: complete },
        totalTokens: complete ? subtotal : null,
        knownSubtotalTokens: subtotal,
        wholeInvestigationTokens: null,
        tasks: results,
        scheduling: {
          requestedConcurrency: concurrency, changesConsumption: false,
          elapsedSeconds: null, peakActiveAgents: null, peakTokens: null, tokensPerSecond: null,
          speedup: null, capacityCeiling: null,
          note: 'Concurrency is requested scheduling metadata, not measured demand or a duration prediction. No validated rates, ceilings or linear speedups.'
        },
        externalCompute: { elapsedSeconds: null, cpuCoreSeconds: null, gpuSeconds: null, allocatedResources: null, utilization: null, peakMemoryGiB: null },
        cost: { amount: null, currency: null, reason: 'No supported prices or billable accounting conversion.' },
        assumptions: [
          'Planning envelopes around provisional reference comparisons, not empirical bounds, confidence intervals or guaranteed coverage.',
          'Only listed hypothetical tasks are covered; investigation completeness is not established.',
          composed ? (canSum ? 'Caller asserts all counted work units are disjoint; no parent/child or contained-stage addition.' : 'Nonoverlap is unconfirmed; no aggregate is reported.') : 'One listed hypothetical task; bounded scope is not implied and no whole-investigation inference is made.',
          'Unsupported fields remain null, not zero. Amount changes only through explicit counts; concurrency never scales consumption.'
        ],
        drivers: clone(profiles.drivers),
        accounting: clone(profiles.accounting),
        provenance: { inputContractVersion: input.contractVersion, calibrationTask: calibration.task, calibrationRevisionTask: calibration.calibration_revision ? calibration.calibration_revision.task : null, operationalRevisionTask: calibration.operational_revision ? calibration.operational_revision.task : null, calibrationSchemaVersion: calibration.schema_version, profilesTask: profiles.task, profilesSchemaVersion: profiles.schema_version, rangeMethod: profiles.range_method.id },
        clarifications
      };
    }
    return Object.freeze({ estimate });
  }
  return Object.freeze({ VERSION, createEstimator });
}));

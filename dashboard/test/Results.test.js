import assert from "node:assert/strict";
import test from "node:test";

import {HARNESS_CATALOG} from "../src/data/Harness Catalog.js";
import {TOOLBOX_CATALOG} from "../src/data/Toolbox Catalog.js";
import {
  admitResults,
  aggregateBehavior,
  annoyanceFromTranscript,
  campaignVerdict,
  aggregateHarnesses,
  behaviorFromTrial,
  defaultModel,
  normalizeResults,
  qualityFromGrade,
  renderResults
} from "../src/components/Results.js";

const DIGEST = `sha256:${"a".repeat(64)}`;
const OTHER_DIGEST = `sha256:${"b".repeat(64)}`;
const QUALITY_DIMENSIONS = [
  "plain_language",
  "appropriate_autonomy",
  "self_verification",
  "regression_coverage",
  "requirements_fit",
  "research_depth"
];
const COMMUNICATION_DIMENSIONS = [
  "directness",
  "proportionality",
  "progress_usefulness",
  "autonomy",
  "candor",
  "warmth",
  "restraint",
  "completion_clarity"
];

class FakeElement {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.className = "";
    this.listeners = {};
    this.value = "";
    this._text = "";
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent ?? String(child)).join("");
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}

function descendants(node) {
  return [node, ...node.children.flatMap((child) => child instanceof FakeElement ? descendants(child) : [])];
}

function conditions(overrides = {}) {
  return {
    kickoff: {
      provider: "codex",
      runtime_version: "0.150.1",
      model: "gpt-6-astra",
      effort: "high"
    },
    task_ids: ["react-active-badge-count"],
    task_variant: "comparison",
    executor_inventory: [],
    attempts: 2,
    concurrency: 1,
    timeout_seconds: 1800,
    retry_policy: "none",
    accounting_policy: "agent-tree-v1",
    decision_policy: "benchmark-readiness-v2",
    resources: {cpus: 2, memory_mb: 4096},
    task_digests: {"react-active-badge-count": DIGEST},
    evaluator_digest: DIGEST,
    image_digests: {node: DIGEST},
    authority_digest: DIGEST,
    scripted_user_digest: DIGEST,
    adapter_digest: DIGEST,
    ...overrides
  };
}

function completedGrade(score = 4, overrides = {}) {
  return {
    status: "completed",
    protocol_id: DIGEST,
    rubric_version: "tim-work-quality-v2",
    dimensions: QUALITY_DIMENSIONS.map((name) => ({name, score, rationale: `${name} evidence`})),
    would_work_again: true,
    duration_seconds: 10,
    usage_complete: true,
    model_usage: [],
    cost_usd: 0,
    pricing_digest: DIGEST,
    ...overrides
  };
}

function oldCommunicationGrade(score = 3) {
  return completedGrade(score, {
    rubric_version: "tim-collaboration-v1",
    dimensions: COMMUNICATION_DIMENSIONS.map((name) => ({name, score, rationale: `${name} evidence`}))
  });
}

function trial(harness, task = "react-active-badge-count", attempt = 1, overrides = {}) {
  return {
    trial_id: `trial-${harness.id}-${task}-${attempt}`,
    task_id: task,
    attempt,
    contender_id: harness.identity,
    status: "completed",
    correctness: true,
    protected_state: true,
    duration_seconds: 60,
    usage_complete: true,
    cost_usd: 0.01,
    pricing_digest: DIGEST,
    model_usage: [{
      provider: "openai",
      model: "gpt-6-astra",
      input_tokens: 100,
      cache_read_tokens: 20,
      cache_write_tokens: 5,
      output_tokens: 25
    }],
    session_usage: [],
    interaction_count: 2,
    child_count: 0,
    incomplete_reasons: [],
    ...overrides
  };
}

function report(reportId, trials, overrides = {}) {
  const experimentOverrides = overrides.experiment ?? {};
  const evidenceOverrides = overrides.evidence ?? {};
  const reportOverrides = {...overrides};
  delete reportOverrides.experiment;
  delete reportOverrides.evidence;
  return {
    schema_version: "3",
    report_id: reportId,
    run_id: `run-${reportId}`,
    updated_at: "2026-09-15T12:00:00Z",
    finished_at: "2026-09-15T12:00:00Z",
    status: "completed",
    source: {kind: "current", label: null},
    evidence: {review_state: "unreviewed", limitations: [], ...evidenceOverrides},
    jobs: [{
      name: "legacy-job-must-not-drive-results",
      runtime_seconds: 9999,
      efficiency: {prompt_tokens: 9999, completion_tokens: 9999, api_equivalent_cost_usd: 9999}
    }],
    experiment: {
      label: `Experiment ${reportId}`,
      purpose: "candidate",
      conditions: conditions(),
      baseline_result_ids: [],
      predecessor_result_ids: [],
      trials,
      comparison: {
        status: "no_clear_winner",
        provisional: true,
        policy_id: "benchmark-readiness-v2"
      },
      ...experimentOverrides
    },
    ...reportOverrides
  };
}

test("bound evaluations include only explicitly selected trials without altering source evidence", () => {
  const [harness] = HARNESS_CATALOG;
  const chosen = trial(harness, "react-active-badge-count", 1);
  const superseded = trial(harness, "react-active-badge-count", 2);
  const source = report(DIGEST, [chosen, superseded], {experiment: {
    evaluation_binding: {trial_ids: [chosen.trial_id]}
  }});
  const before = JSON.stringify(source);
  const rows = normalizeResults([source], TOOLBOX_CATALOG, HARNESS_CATALOG);
  assert.deepEqual(rows.map(row => row.trialId), [chosen.trial_id]);
  assert.equal(JSON.stringify(source), before);
  source.experiment.evaluation_binding.trial_ids = [];
  assert.equal(normalizeResults([source], TOOLBOX_CATALOG, HARNESS_CATALOG).length, 0);
  delete source.experiment.evaluation_binding;
  assert.equal(normalizeResults([source], TOOLBOX_CATALOG, HARNESS_CATALOG).length, 2);
});

test("normalizes authoritative trials and complete whole-tree telemetry", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const authoritative = trial(studio, "react-active-badge-count", 1, {
    duration_seconds: 877.011,
    cost_usd: 1.8773864,
    model_usage: [
      {provider: "openai", model: "root", input_tokens: 1000, cache_read_tokens: 2000, cache_write_tokens: 3000, output_tokens: 4000},
      {provider: "openai", model: "child", input_tokens: 10, cache_read_tokens: 20, cache_write_tokens: 30, output_tokens: 40}
    ]
  });
  const missingUsage = trial(nothing, "react-active-badge-count", 1, {
    usage_complete: false,
    cost_usd: 42,
    model_usage: [{provider: "openai", model: "root", input_tokens: 1, cache_read_tokens: 2, cache_write_tokens: 3, output_tokens: 4}]
  });
  const reports = [
    report("authoritative", [authoritative, missingUsage]),
    report("old-schema", [trial(studio)], {schema_version: "2"}),
    report("historical", [trial(studio)], {source: {kind: "identified-historical", label: "old"}}),
    report("unknowns", [
      trial({...studio, identity: OTHER_DIGEST}, "react-active-badge-count", 1),
      trial(studio, "not-in-toolbox", 1)
    ])
  ];

  const observations = normalizeResults(reports, TOOLBOX_CATALOG, HARNESS_CATALOG);
  const studioObservation = observations.find(({harnessId}) => harnessId === studio.id);
  const nothingObservation = observations.find(({harnessId}) => harnessId === nothing.id);

  assert.equal(observations.length, 2);
  assert.equal(studioObservation.runtime, 877.011);
  assert.equal(studioObservation.tokens, 10_100);
  assert.equal(studioObservation.cost, 1.8773864);
  assert.equal(studioObservation.pricingDigest, DIGEST);
  assert.equal(nothingObservation.tokens, null);
  assert.equal(nothingObservation.cost, null);
  assert.equal(defaultModel(observations), "gpt-6-astra\0high");
});

test("decision admission counts genuine failed attempts and rejects diagnostic, quarantined, and old-policy evidence", () => {
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const decision = report("decision", [
    trial(studio, "react-active-badge-count", 1),
    trial(studio, "react-active-badge-count", 2, {status: "agent_failed", correctness: null})
  ]);
  const diagnostic = report("diagnostic", [trial(studio)], {experiment: {purpose: "diagnostic"}});
  const quarantined = report("quarantined", [trial(studio)], {evidence: {review_state: "quarantined"}});
  const oldPolicy = report("old-policy", [trial(studio)], {
    experiment: {conditions: conditions({decision_policy: "development-comparison-v1"})}
  });
  const observations = normalizeResults([decision, diagnostic, quarantined, oldPolicy], TOOLBOX_CATALOG, HARNESS_CATALOG);
  const admitted = admitResults(observations);
  const row = aggregateHarnesses(observations, HARNESS_CATALOG, {cohort: "decision"})
    .find(({id}) => id === studio.id);

  assert.equal(admitted.length, 2);
  assert.deepEqual(admitted.map(({correctness}) => correctness), [1, 0]);
  assert.equal(row.correctness, 0.5);
  assert.equal(row.attempts, 2);
  assert.equal(row.runtime, 60);
  assert.equal(row.tokens, 150);
  assert.equal(row.cost, 0.01);
  assert.deepEqual(
    observations.filter(({decisionEligible}) => !decisionEligible).map(({evidenceState}) => evidenceState).sort(),
    ["diagnostic", "old-policy", "quarantined"]
  );
});

test("explicit report cohorts require matching conditions and use exact baseline and predecessor references", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const predecessor = {
    ...studio,
    id: "studio-moser-v4-test",
    identity: OTHER_DIGEST,
    versionLabel: "v4 test",
    versionOrder: studio.versionOrder - 1,
    predecessorId: null
  };
  const candidate = {...studio, predecessorId: predecessor.id};
  const harnesses = [nothing, predecessor, candidate];
  const baseline = report("baseline", [trial(nothing, "react-active-badge-count", 1, {correctness: false})], {
    experiment: {purpose: "baseline"}
  });
  const predecessorReport = report("predecessor", [trial(predecessor, "react-active-badge-count", 1, {correctness: false})], {
    experiment: {purpose: "baseline"}
  });
  const candidateReport = report("candidate", [trial(candidate)], {
    experiment: {
      baseline_result_ids: ["baseline"],
      predecessor_result_ids: ["predecessor"]
    }
  });
  const sameNamesWrongEvaluator = report("wrong-evaluator", [trial(nothing, "react-active-badge-count", 1)], {
    experiment: {conditions: conditions({evaluator_digest: OTHER_DIGEST})}
  });
  const observations = normalizeResults(
    [baseline, predecessorReport, candidateReport, sameNamesWrongEvaluator],
    TOOLBOX_CATALOG,
    harnesses
  );
  const rows = aggregateHarnesses(observations, harnesses, {cohort: "candidate"});
  const studioRow = rows.find(({id}) => id === candidate.id);

  assert.equal(studioRow.correctness, 1);
  assert.equal(studioRow.deltaFromNothing, 1);
  assert.equal(studioRow.deltaFromPredecessor, 1);
  assert.equal(rows.find(({id}) => id === nothing.id).observations, 1);
  assert.equal(rows.find(({id}) => id === predecessor.id).observations, 1);
  assert.equal(rows.find(({id}) => id === nothing.id).exploratoryObservations, 0);
});

test("grades join by report and trial identity, count once, and require every Quality dimension", () => {
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const first = trial(studio, "react-active-badge-count", 1, {collaboration: {grade: completedGrade(5)}});
  const second = trial(studio, "react-active-badge-count", 2);
  const duplicateReport = report("graded", [first, second]);
  const observations = normalizeResults(
    [duplicateReport, structuredClone(duplicateReport)],
    TOOLBOX_CATALOG,
    HARNESS_CATALOG
  );
  const row = aggregateHarnesses(observations, HARNESS_CATALOG, {cohort: "graded"})
    .find(({id}) => id === studio.id);

  assert.equal(observations.length, 2);
  assert.equal(row.quality, null);
  assert.equal(row.qualityObservations, 1);
  assert.equal(qualityFromGrade(completedGrade(5, {dimensions: completedGrade().dimensions.slice(0, 5)})), null);
  assert.equal(qualityFromGrade(completedGrade(5, {
    dimensions: completedGrade().dimensions.map((dimension, index) => index === 2 ? {...dimension, score: null} : dimension)
  })), null);
});

test("quality trade-offs use shared trial samples and incompatible pricing stays separate", () => {
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const anotherTask = "react-accent-polish";
  const reportConditions = conditions({
    task_ids: ["react-active-badge-count", anotherTask],
    task_digests: {"react-active-badge-count": DIGEST, [anotherTask]: DIGEST}
  });
  const observations = normalizeResults([report("matched", [
    trial(studio, "react-active-badge-count", 1, {
      duration_seconds: 10,
      cost_usd: 1,
      collaboration: {grade: completedGrade(5)}
    }),
    trial(studio, anotherTask, 1, {duration_seconds: 1010, cost_usd: 3}),
    trial(studio, anotherTask, 2, {
      duration_seconds: 20,
      cost_usd: 2,
      pricing_digest: OTHER_DIGEST,
      collaboration: {grade: completedGrade(1)}
    })
  ], {experiment: {conditions: reportConditions}})], TOOLBOX_CATALOG, HARNESS_CATALOG);
  const row = aggregateHarnesses(observations, HARNESS_CATALOG, {cohort: "matched"})
    .find(({id}) => id === studio.id);

  assert.equal(row.runtime, 262.5);
  assert.equal(row.quality, null);
  assert.equal(row.tradeoffs.runtime.value, 15);
  assert.equal(row.tradeoffs.runtime.quality, 0.6);
  assert.equal(row.tradeoffs.runtime.observations, 2);
  assert.equal(row.cost, null);
  assert.equal(row.tradeoffs.cost.value, null);
  assert.equal(row.telemetryCoverage.cost, 0);
});

test("regraded protocols cannot be averaged together and empty usage stays unknown", () => {
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const observations = normalizeResults([report("mixed-grades", [
    trial(studio, "react-active-badge-count", 1, {collaboration: {grade: completedGrade(5)}, model_usage: []}),
    trial(studio, "react-active-badge-count", 2, {collaboration: {grade: completedGrade(1, {protocol_id: OTHER_DIGEST})}})
  ])], TOOLBOX_CATALOG, HARNESS_CATALOG);
  assert.equal(observations[0].tokens, null);
  const row = aggregateHarnesses(observations, HARNESS_CATALOG, {cohort: "mixed-grades"}).find(({id}) => id === studio.id);
  assert.equal(row.qualityCompatible, false);
  assert.equal(row.quality, null);
  assert.equal(row.tradeoffs.runtime.value, null);
});

test("pending infrastructure and review/protected-state gaps stay visible without becoming failed attempts", () => {
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const observations = normalizeResults([report("gaps", [
    trial(studio, "react-active-badge-count", 1, {protected_state: null, code_review: undefined}),
    trial(studio, "react-active-badge-count", 2, {
      status: "infrastructure_failure",
      correctness: null,
      protected_state: null,
      incomplete_reasons: ["provider unavailable"]
    })
  ])], TOOLBOX_CATALOG, HARNESS_CATALOG);
  const row = aggregateHarnesses(observations, HARNESS_CATALOG, {cohort: "gaps"})
    .find(({id}) => id === studio.id);

  assert.equal(row.correctness, 1);
  assert.equal(row.attempts, 1);
  assert.equal(row.cohortComplete, false);
  assert.equal(row.gaps.infrastructure, 1);
  assert.equal(row.gaps.protectedUnknown, 2);
  assert.equal(row.gaps.unreviewed, 2);
});

test("trade-off charts put higher quality and lower resource use toward the top right", () => {
  const harnesses = HARNESS_CATALOG.filter(harness => harness.identity).slice(0, 3);
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag), createElementNS: (_, tag) => new FakeElement(tag)};
  try {
    for (const values of [[0, 50, 100], [0, 0, 0], [100, 105, 110], [100, 100, 100]]) {
      const source = report("axis-direction", harnesses.map((harness, i) => trial(harness, "react-active-badge-count", 1, {
        duration_seconds: values[i], cost_usd: values[i],
        model_usage: [{input_tokens: values[i], output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0}],
        collaboration: {grade: completedGrade(5 - i)}
      })));
      const root = renderResults({tests: TOOLBOX_CATALOG, harnesses, reports: [source]});
      const charts = descendants(root).filter(node => node.tag === "svg");
      assert.match(root.className, /\bcontainer-xl\b/);
      assert.ok(descendants(root).filter(node => node.tag === "table").every(node => node.className.includes("card-table")));
      assert.ok(descendants(root).filter(node => node.attributes["aria-pressed"] === "true").every(node => node.className.includes("nav-link active")));
      assert.ok(descendants(root).filter(node => node.className.includes("results-filter-group")).every(node => node.className.includes("nav nav-pills")));
      assert.equal(charts.length, 3);
      assert.match(root.textContent, /Better is toward the top right/);
      for (const chart of charts) {
        assert.match(chart.attributes["aria-label"], /Higher Quality is up; lower .* is right/);
        const points = harnesses.map(harness => descendants(chart).find(node => node.tag === "circle" && node.attributes.class.endsWith(`results-chart-${harness.family}`)));
        const xs = points.map(point => Number(point.attributes.cx));
        const ys = points.map(point => Number(point.attributes.cy));
        assert.ok(xs.every(Number.isFinite) && ys.every(Number.isFinite));
        assert.ok(ys[0] < ys[1] && ys[1] < ys[2]);
        if (values[0] !== values[2]) assert.ok(xs[0] > xs[1] && xs[1] > xs[2]);
        else assert.ok(xs.every(x => x === xs[0]));
        const ticks = descendants(chart).filter(node => node.tag === "text" && node.attributes["text-anchor"] === "middle");
        assert.equal(ticks.length, 3);
        assert.ok(Number(ticks[0].attributes.x) < Number(ticks[2].attributes.x));
        if (values[0] > 0) {
          assert.doesNotMatch(ticks[2].textContent, /^(0s|0|\$0\.00)$/);
          assert.ok(xs.every(x => x > 48 && x < 496));
          if (values[0] !== values[2]) assert.ok(xs[0] - xs[2] > 448 * 0.8, "clustered values use most of the plot width");
          else assert.ok(xs.every(x => Math.abs(x - 272) < 0.001), "identical values are centered");
        } else assert.match(ticks[2].textContent, /^(0s|0|\$0\.00)$/);
      }
    }
  } finally {globalThis.document = previousDocument;}
});

test("Results page separates an empty decision-grade view from exploratory detail", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const diagnostic = report("diagnostic-ui", [
    trial(nothing, "react-active-badge-count", 1, {
      protected_state: null,
      collaboration: {grade: oldCommunicationGrade(3)}
    }),
    trial(studio, "react-active-badge-count", 1, {status: "agent_failed", correctness: null})
  ], {
    experiment: {
      purpose: "diagnostic",
      conditions: conditions({decision_policy: "development-comparison-v1"})
    }
  });
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createElementNS: (namespace, tag) => new FakeElement(tag)
  };
  try {
    const root = renderResults({tests: TOOLBOX_CATALOG, harnesses: HARNESS_CATALOG, reports: [diagnostic]});
    assert.equal(root.attributes["aria-label"], "Harness results");
    assert.match(root.textContent, /No decision-grade ranking/);
    assert.match(root.textContent, /2 exploratory observations/);
    assert.match(root.textContent, /Diagnostic · Old policy/);
    assert.match(root.textContent, /communication · automated/);
    assert.match(root.textContent, /protected state unknown/);
    assert.match(root.textContent, /not code-reviewed/);
    assert.match(root.textContent, /1 agent failure/);
    assert.match(root.textContent, /Studio Moser v5/);
    assert.match(root.textContent, /React active badge count/);
    assert.doesNotMatch(root.textContent, /All models/i);
    assert.doesNotMatch(root.textContent, /recommend/i);

    const nodes = descendants(root);
    assert.equal(nodes.filter((node) => node.tag === "select").length, 2);
    assert.equal(nodes.filter((node) => node.className === "results-chart-legend").length, 1);
  } finally {
    globalThis.document = previousDocument;
  }
});

function metrics(overrides = {}) {
  return {
    assistant_words: 200,
    final_answer_words: 50,
    assistant_message_count: 3,
    slop_phrase_count: 0,
    repeated_sentence_count: 0,
    prompt_restatement: false,
    unnecessary_question_count: 0,
    unnecessary_approval_request_count: 0,
    useful_progress_update_rate: 0.5,
    formatting_density: 0.05,
    bullet_count: 2,
    heading_count: 0,
    violations: [],
    slop_matches: [],
    ...overrides
  };
}

test("behavior evidence is aggregated per model and harness version from completed trials only", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const astra = report("astra", [
    trial(nothing, "react-active-badge-count", 1, {collaboration: {metrics: metrics(), grade: completedGrade(5)}}),
    trial(nothing, "react-active-badge-count", 2, {collaboration: {metrics: metrics({assistant_words: 100, slop_phrase_count: 2, prompt_restatement: true})}}),
    trial(studio, "react-active-badge-count", 1, {collaboration: {metrics: metrics({assistant_words: 300, violations: [{rule: "x"}]}), grade: completedGrade(3)}}),
    trial(studio, "react-active-badge-count", 2, {status: "timeout", correctness: null, collaboration: {metrics: metrics({assistant_words: 9999})}})
  ]);
  const sol = report("sol", [
    trial(studio, "react-active-badge-count", 1, {collaboration: {metrics: metrics({assistant_words: 120}), grade: oldCommunicationGrade(4)}})
  ], {experiment: {conditions: conditions({kickoff: {provider: "codex", runtime_version: "0.150.1", model: "gpt-5.6-sol", effort: "medium"}})}});
  const observations = normalizeResults([astra, sol], TOOLBOX_CATALOG, HARNESS_CATALOG);
  const columns = aggregateBehavior(observations, HARNESS_CATALOG);

  assert.deepEqual(columns.map(({model, harnessId, trials}) => [model, harnessId, trials]), [
    ["gpt-5.6-sol", studio.id, 1],
    ["gpt-6-astra", nothing.id, 2],
    ["gpt-6-astra", studio.id, 1]
  ]);
  const astraNothing = columns[1].values;
  assert.equal(astraNothing["transcript.assistant_words"].mean, 150);
  assert.equal(astraNothing["transcript.slop_phrase_count"].mean, 1);
  assert.equal(astraNothing["transcript.prompt_restatement"].mean, 0.5);
  assert.deepEqual(astraNothing["quality.plain_language"], {mean: 5, samples: 1});
  assert.equal(astraNothing["communication.warmth"], null);
  const astraStudio = columns[2].values;
  assert.equal(astraStudio["transcript.assistant_words"].mean, 300); // the timed-out trial is excluded
  assert.equal(astraStudio["transcript.violation_count"].mean, 1);
  assert.equal(astraStudio["quality.plain_language"].mean, 3);
  assert.equal(columns[0].values["communication.warmth"].mean, 4);
  assert.deepEqual(behaviorFromTrial({}), {transcript: {}, annoyance: {}, quality: {}, communication: {}});
  assert.deepEqual(aggregateBehavior(observations, HARNESS_CATALOG, {type: "polish"}), []);

  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag), createElementNS: (_, tag) => new FakeElement(tag)};
  try {
    const root = renderResults({tests: TOOLBOX_CATALOG, harnesses: HARNESS_CATALOG, reports: [astra, sol]});
    const text = root.textContent;
    assert.match(text, /Behavior across models and harness versions/);
    assert.match(text, /Transcript metrics/);
    assert.match(text, /gpt-5\.6-sol · medium · 1 trial/);
    assert.match(text, /Slop phrases ↓/);
    assert.match(text, /Communication grader/);
    assert.match(text, /4\.00 \/ 5/);
  } finally {globalThis.document = previousDocument;}
});

test("annoyance counters read the assistant's visible messages only", () => {
  const transcript = [
    {role: "user", content: "Great question! Fix it."},
    {role: "assistant", content: "Great question! I think it\u2019s worth noting this is robust \u2014 let me know if you want more."},
    {role: "assistant", content: "Done."}
  ];
  const counts = annoyanceFromTranscript(transcript);
  assert.equal(counts.sycophancy, 1);
  assert.equal(counts.hedging, 1);
  assert.equal(counts.filler, 1);
  assert.equal(counts.self_praise, 1);
  assert.equal(counts.closing_offers, 1);
  assert.equal(counts.em_dashes, 1);
  assert.equal(counts.exclamations, 1);
  assert.deepEqual(annoyanceFromTranscript(null), {});
  assert.deepEqual(annoyanceFromTranscript([{role: "user", content: "hi!"}]), {});
});

test("campaign verdict card names the recommended harness per lane and renders on the page", () => {
  const nothing = HARNESS_CATALOG.find(({id}) => id === "nothing-v1");
  const studio = HARNESS_CATALOG.find(({id}) => id === "studio-moser-v5");
  const contender = (harness, cost, reviewed = true, unconfirmed = 0) => ({
    id: harness.identity, successes: 19, scheduled: 19, eligible: true, reviewed,
    mean_cost_usd: cost, mean_duration_seconds: 70, code_review: {unconfirmed}
  });
  const campaign = {
    campaign_digest: DIGEST, status: "recommended", winner_id: nothing.identity, reasons: [],
    lanes: {
      comparison: {limitations: ["Some slots were rerun."], comparison: {
        status: "recommended", winner_id: nothing.identity, reasons: ["practical_advantage_supported"],
        unsolved_tasks: [], contenders: [contender(nothing, 0.29, true, 5), contender(studio, 0.56, false)]
      }},
      deepswe: {limitations: [], comparison: {status: "no_clear_winner", winner_id: null, reasons: [], unsolved_tasks: ["pest"], contenders: []}}
    }
  };
  const verdict = campaignVerdict(campaign, HARNESS_CATALOG);
  assert.equal(verdict.winner, "Nothing v1");
  assert.equal(verdict.lanes[0].winner, "Nothing v1");
  assert.equal(verdict.lanes[0].contenders[1].reviewed, false);
  assert.equal(verdict.lanes[1].winner, null);
  assert.equal(campaignVerdict(null, HARNESS_CATALOG), null);
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: tag => new FakeElement(tag), createElementNS: (_, tag) => new FakeElement(tag)};
  try {
    const root = renderResults({tests: TOOLBOX_CATALOG, harnesses: HARNESS_CATALOG, reports: [], campaign});
    const text = root.textContent;
    assert.match(text, /Campaign verdict: Nothing v1 recommended/);
    assert.match(text, /Comparison lane · Nothing v1 recommended/);
    assert.match(text, /5 unconfirmed claims/);
    assert.match(text, /incomplete/);
    assert.match(text, /Unsolved by every harness: pest/);
    const without = renderResults({tests: TOOLBOX_CATALOG, harnesses: HARNESS_CATALOG, reports: []});
    assert.doesNotMatch(without.textContent, /Campaign verdict/);
  } finally {globalThis.document = previousDocument;}
});

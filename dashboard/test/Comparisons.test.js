import assert from "node:assert/strict";
import test from "node:test";
import {comparisonReports, selectComparison, comparisonUrl, versionHistory, sortNumericRows, trialLabel} from "../src/components/Comparisons.js";

function report(id, version, purpose = "candidate") {
  return {schema_version: "3", report_id: id, run_id: `run-${id}`, updated_at: `2026-09-05T12:00:0${id}Z`, experiment: {label: id, purpose, contenders: [{id: version, family: "studio-moser", label: version}], predecessor_result_ids: [], comparison: {status: "insufficient_evidence"}}};
}

test("selects comparison evidence explicitly and never defaults to a later diagnostic", () => {
  const reports = [report("1", "v1"), report("2", "v2", "diagnostic"), {schema_version: "2"}];
  assert.equal(comparisonReports(reports).length, 1);
  assert.equal(selectComparison(reports).report_id, "1");
  assert.equal(selectComparison(reports, "missing"), null);
  assert.equal(selectComparison(reports, "2").report_id, "2");
});

test("URL selections are encoded and preserved across views", () => {
  const url = new URL(comparisonUrl("/Run_Detail", {comparison: "sha256:a", task: "a & b", version: "v1"}), "https://example.invalid");
  assert.equal(url.searchParams.get("task"), "a & b");
  assert.equal(url.searchParams.get("comparison"), "sha256:a");
  assert.equal(url.searchParams.get("version"), "v1");
});

test("version history groups reruns and preserves explicit predecessors", () => {
  const reports = [report("1", "v1"), report("2", "v1"), report("3", "branch")];
  reports[2].experiment.predecessor_result_ids = ["1"];
  const versions = versionHistory(reports);
  assert.equal(versions.find(v => v.id === "v1").runs.length, 2);
  assert.deepEqual(versions.find(v => v.id === "branch").runs[0].experiment.predecessor_result_ids, ["1"]);
});

test("sorts measurements numerically with nulls last in either direction", () => {
  const rows = [{time: 102.8}, {time: 38.5}, {time: null}];
  assert.deepEqual(sortNumericRows(rows, "time").map(row => row.time), [38.5, 102.8, null]);
  assert.deepEqual(sortNumericRows(rows, "time", false).map(row => row.time), [102.8, 38.5, null]);
  assert.equal(rows[0].time, 102.8);
});


test("trial labels distinguish protected failures and incomplete execution", () => {
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:true}), "Passed");
  assert.equal(trialLabel({status:"completed", correctness:true, protected_state:false}), "Protected files changed");
  assert.equal(trialLabel({status:"timeout", correctness:true, protected_state:true}), "timeout");
  assert.equal(trialLabel({status:"completed", correctness:null, protected_state:null}), "Ungraded");
});

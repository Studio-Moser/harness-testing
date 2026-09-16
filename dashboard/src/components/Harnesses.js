import {HARNESS_FAMILIES, familyVersions, primaryHarnesses} from "../data/Harness Catalog.js";

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function list(items, className = "harness-list") {
  const node = element("ul", className);
  for (const item of items) node.append(element("li", "", item));
  return node;
}

function detail(title, ...content) {
  const node = element("details", "toolbox-detail harness-detail");
  node.append(element("summary", "toolbox-detail-summary", title), ...content);
  return node;
}

function renderPurpose(family) {
  const body = element("div", "toolbox-detail-body");
  body.append(element("p", "toolbox-detail-lede", family.purpose), list(family.effects));
  return body;
}

function renderLayers(version) {
  const body = element("div", "toolbox-detail-body");
  if (version.layers.length === 0) {
    body.append(element("p", "toolbox-detail-lede", "No added plugins, skills, rubric, or startup instructions."));
  } else {
    const layers = element("div", "harness-layer-list");
    for (const layer of version.layers) {
      const item = element("section", "harness-layer");
      const heading = element("div", "harness-layer-heading");
      heading.append(element("strong", "", layer.name), element("span", "", `${layer.kind} · ${layer.version}`));
      item.append(heading, element("p", "", layer.description));
      layers.append(item);
    }
    body.append(layers);
  }

  const facts = element("dl", "toolbox-facts harness-facts");
  facts.append(
    element("dt", "", "Routing rubric"),
    element("dd", "", version.rubric.description),
    element("dt", "", "Startup input"),
    element("dd", "", version.startup)
  );
  body.append(facts);
  return body;
}

function renderDelivery(version) {
  const body = element("div", "toolbox-detail-body");
  body.append(list(version.delivery));
  return body;
}

function renderIdentity(version) {
  const body = element("div", "toolbox-detail-body");
  const facts = element("dl", "toolbox-facts harness-facts harness-identity-facts");
  facts.append(
    element("dt", "", "Predecessor"),
    element("dd", "", version.predecessorId ?? "First cataloged version"),
    element("dt", "", "Contender identity"),
    element("dd", "", version.identity ?? "Created when a House Style snapshot is frozen")
  );
  body.append(facts, list(version.identityNotes));

  if (version.sources.length) {
    const pins = element("div", "harness-pins");
    for (const source of version.sources) {
      const row = element("div", "harness-pin");
      const link = element("a", "", `${source.name} ${source.version}`);
      link.setAttribute("href", `${source.url}/commit/${source.commit}`);
      link.setAttribute("target", "_blank");
      link.setAttribute("rel", "noreferrer");
      row.append(link, element("code", "", source.commit));
      pins.append(row);
    }
    body.append(pins);
  } else {
    body.append(element("p", "harness-identity-note", version.identity
      ? "No external source pin. The materialized inputs still have a content-derived identity."
      : "This template becomes a version only after its exact startup guidance is frozen."));
  }
  return body;
}

function renderCard(version, family) {
  const card = element("article", `harness-card harness-card-${family.role} harness-card-family-${version.family} card`);
  card.setAttribute("data-harness-id", version.id);

  const header = element("header", "harness-card-header harness-version-header");
  const labels = element("div", "toolbox-card-labels");
  labels.append(
    element("span", "toolbox-badge harness-version-badge", version.versionLabel),
    element("span", `toolbox-badge harness-state harness-state-${version.state}`, version.state === "ready" ? "Ready" : "Draft")
  );
  if (version.latest && version.family === "studio-moser") labels.append(element("span", "toolbox-badge harness-latest", "Latest"));

  const changes = element("div", "harness-change");
  changes.append(
    element("p", "harness-change-label", "Changes from previous version"),
    element("p", "harness-change-summary", version.changeSummary),
    list(version.changeDetails, "harness-change-list")
  );
  header.append(
    labels,
    element("h3", "toolbox-card-title harness-card-title", `${family.name} ${version.versionLabel}`),
    element("p", "harness-card-subtitle", version.sourceLabel),
    changes
  );

  const details = element("div", "toolbox-details");
  details.append(
    detail("What it does", renderPurpose(family)),
    detail("Included layers", renderLayers(version)),
    detail("How it is delivered", renderDelivery(version)),
    detail("Version identity", renderIdentity(version))
  );
  card.append(header, details);
  return card;
}

function renderFamily(catalog, familyId, {newestFirst = false} = {}) {
  const family = HARNESS_FAMILIES[familyId];
  const versions = familyVersions(catalog, familyId);
  if (newestFirst) versions.reverse();
  const section = element("section", `harness-family harness-family-${familyId}`);
  const heading = element("header", "harness-family-heading");
  const title = element("div", "harness-family-title");
  title.append(
    element("h3", "", family.name),
    element("span", "harness-family-count", `${versions.length} ${versions.length === 1 ? "version" : "versions"}`)
  );
  heading.append(
    title,
    element("p", "harness-family-purpose", family.purpose),
    element("p", "harness-family-question", family.question)
  );
  const grid = element("div", `harness-grid ${versions.length > 1 ? "harness-grid-history" : "harness-grid-single"}`);
  for (const version of versions) grid.append(renderCard(version, family));
  section.append(heading, grid);
  return section;
}

function renderBaselines(catalog) {
  const familyIds = ["nothing", "superpowers", "studio-personality"];
  const versions = familyIds.flatMap((familyId) => familyVersions(catalog, familyId));
  const section = element("section", "harness-family harness-family-baselines");
  const heading = element("header", "harness-family-heading");
  const title = element("div", "harness-family-title");
  title.append(element("h3", "", "Baselines"), element("span", "harness-family-count", `${versions.length} harnesses`));
  heading.append(
    title,
    element("p", "harness-family-purpose", "Reference configurations that remain separate from the Studio Moser version line."),
    element("p", "harness-family-question", "Together they isolate bare-runtime behavior, general workflow guidance, and Studio Moser communication guidance.")
  );
  const grid = element("div", "harness-grid harness-grid-history");
  for (const version of versions) grid.append(renderCard(version, HARNESS_FAMILIES[version.family]));
  section.append(heading, grid);
  return section;
}

function renderGroup(title, description, catalog, familyIds, className) {
  const section = element("section", `harness-group ${className}`);
  const heading = element("div", "harness-group-heading");
  heading.append(element("h2", "", title), element("p", "", description));
  section.append(heading);
  for (const familyId of familyIds) section.append(renderFamily(catalog, familyId));
  return section;
}

export function renderHarnesses(catalog) {
  const primary = primaryHarnesses(catalog);
  const primaryFamilies = Object.entries(HARNESS_FAMILIES)
    .filter(([, family]) => family.role === "primary")
    .sort(([, a], [, b]) => a.stage - b.stage)
    .map(([id]) => id);
  const draftBaselines = catalog.filter(({family, state}) => HARNESS_FAMILIES[family]?.role === "baseline" && state === "draft");
  const root = element("section", "harnesses");
  root.setAttribute("aria-label", "Harness catalog");

  const intro = element("header", "toolbox-intro harnesses-intro");
  intro.append(
    element("h1", "", `${primary.length} Harness Versions`),
    element("p", "toolbox-intro-copy", "Track each harness revision as a distinct test input: what it contains, which version preceded it, and exactly what changed. This catalog contains definitions only—no results or recommendations."),
    element("p", "harness-count", `${primary.length} ready harness versions, plus ${draftBaselines.length} draft baseline.`)
  );

  const primaryGroup = renderGroup(
    "Primary comparison",
    "The baselines anchor a newest-first Studio Moser history; newer does not imply better.",
    catalog,
    [],
    "harness-group-primary"
  );
  primaryGroup.append(renderFamily(catalog, "studio-moser", {newestFirst: true}), renderBaselines(catalog));
  root.append(intro, primaryGroup);
  return root;
}

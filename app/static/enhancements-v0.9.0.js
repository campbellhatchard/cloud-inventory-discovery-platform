"use strict";

(() => {
  // v0.9.0 Quick Entry mappings.
  if (!QUICK_ENTRY_AREAS.some(item => item.value === "MASTER_DATA")) {
    QUICK_ENTRY_AREAS.unshift({value: "MASTER_DATA", label: "Master Data"});
  }

  const priorQuickEntrySection = quickEntrySection;
  quickEntrySection = function v090QuickEntrySection(value) {
    if (!state.report || !value) return null;
    if (value === "MASTER_DATA") {
      return state.report.sections.find(
        section => section.stable_key === "master-data" && section.state !== "REMOVED"
      ) || null;
    }
    if (value === "OTHER") {
      return state.report.sections.find(
        section => section.stable_key === "general-observations" && section.state !== "REMOVED"
      ) || null;
    }
    return priorQuickEntrySection(value);
  };

  // Keep Master Data as a Quick Entry destination without silently changing
  // the controlled product-knowledge module taxonomy.
  const priorKnowledgeModuleOptions = knowledgeModuleOptions;
  knowledgeModuleOptions = function v090KnowledgeModuleOptions(selected = "") {
    const masterIndex = QUICK_ENTRY_AREAS.findIndex(item => item.value === "MASTER_DATA");
    const master = masterIndex >= 0 ? QUICK_ENTRY_AREAS.splice(masterIndex, 1)[0] : null;
    try {
      return priorKnowledgeModuleOptions(selected);
    } finally {
      if (master) QUICK_ENTRY_AREAS.splice(masterIndex, 0, master);
    }
  };

  // Route only Current Operations AI wording through the new latency-isolated
  // endpoint. All existing saved-wording, polling, refinement, and approval UI
  // remains unchanged.
  requestAiEnhancement = async function v090RequestAiEnhancement(
    section,
    parentSuggestionId = null,
    {forceRegenerate = false} = {},
  ) {
    const instruction = document.getElementById("ai-refinement-instruction")?.value?.trim() || null;
    if (parentSuggestionId && !instruction) {
      throw new Error("Enter a refinement request before refining the AI wording.");
    }
    const output = document.getElementById("ai-enhanced-output");
    if (output) {
      output.innerHTML = '<div class="ai-working"><div class="spinner" aria-hidden="true"></div><p>Preparing a fast text-only wording draft…</p><p class="help">The draft is returned first. Source verification runs independently and cannot block the fast-text queue.</p></div>';
    }
    const result = await api(`/api/reports/${state.report.report.id}/ai-fast-wording`, {
      method: "POST",
      body: {
        section_id: section.id,
        instructions: instruction,
        evidence_ids: [],
        parent_suggestion_id: parentSuggestionId,
        force_regenerate: forceRegenerate,
      },
    }, false);
    const token = ++state.aiEnhancementPollToken;
    await pollAiEnhancement(
      result.ai_job_id,
      section,
      token,
      Boolean(result.restored || result.reused),
    );
  };

  function photoStatusLabel(value) {
    return {
      NOT_ANALYZED: "Not Analyzed",
      ANALYZING: "Analyzing",
      ANALYSIS_COMPLETE: "Analysis Complete",
      REVIEW_AVAILABLE: "Review Available",
      REVIEWED: "Reviewed",
    }[value] || String(value || "Not Analyzed").replaceAll("_", " ");
  }

  function photoStatusClass(value) {
    if (value === "REVIEWED") return "badge-success";
    if (value === "REVIEW_AVAILABLE" || value === "ANALYSIS_COMPLETE") return "badge-cyan";
    if (value === "ANALYZING") return "badge-warning";
    return "";
  }

  function photoIntelligenceCard(section) {
    const photoCount = state.report.evidence.filter(item => {
      if (item.section_id !== section.id) return false;
      const file = item.preview_file || item.file;
      return Boolean(file?.mime_type?.startsWith("image/"));
    }).length;
    return `
      <section class="card" id="photo-intelligence">
        <div class="section-head">
          <div>
            <h2>Photo Intelligence</h2>
            <p class="help">Photographs are analyzed independently first. The saved visual analysis is then correlated with the Current Operations Narrative to suggest a separately reviewable revision. Photo analysis never blocks AI Enhanced Wording.</p>
          </div>
          <div class="toolbar">
            <span id="photo-intelligence-status" class="badge">${photoCount ? "Loading" : "Not Analyzed"}</span>
            <button class="btn btn-secondary btn-small" type="button" data-v090-action="analyze-photos" ${photoCount ? "" : "disabled"}>Analyze Photos</button>
            <button id="photo-intelligence-revision-button" class="btn btn-primary btn-small" type="button" data-v090-action="suggest-photo-revision" disabled>Suggest Revision</button>
          </div>
        </div>
        <div id="photo-intelligence-body">
          ${photoCount ? '<div class="ai-working"><div class="spinner spinner-small" aria-hidden="true"></div><p>Loading photo intelligence status…</p></div>' : '<p class="help">Add one or more photographs to this section to use Photo Intelligence.</p>'}
        </div>
      </section>`;
  }

  const priorReportSectionContent = reportSectionContent;
  reportSectionContent = function v090ReportSectionContent(section) {
    const html = priorReportSectionContent(section);
    const anchor = '<section class="card" id="photos">';
    if (!html.includes(anchor)) return `${html}${photoIntelligenceCard(section)}`;
    return html.replace(anchor, `${photoIntelligenceCard(section)}${anchor}`);
  };

  function renderPhotoAnalysis(photo) {
    const analysis = photo.analysis || {};
    const observations = analysis.operational_observations || [];
    const uncertainties = analysis.uncertainties || [];
    const labels = analysis.visible_text_or_labels || [];
    return `
      <article class="finding">
        <div class="section-head">
          <div>
            <strong>${esc(photo.caption || photo.file_name || "Site photograph")}</strong>
            <div class="card-meta">
              <span class="badge ${photo.status === "ANALYZED" ? "badge-success" : "badge-warning"}">${esc(photoStatusLabel(photo.status))}</span>
              ${analysis.confidence ? `<span>Confidence: ${esc(analysis.confidence)}</span>` : ""}
            </div>
          </div>
          ${photo.file_id ? `<button class="btn btn-ghost btn-small" type="button" data-action="open-evidence-preview" data-id="${esc(photo.evidence_id)}">Open file</button>` : ""}
        </div>
        ${analysis.visual_description ? `<p>${esc(analysis.visual_description)}</p>` : ""}
        ${observations.length ? `<div class="ai-trace"><strong>Visual operational observations</strong><ul>${observations.map(item => `<li>${esc(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul></div>` : ""}
        ${labels.length ? `<div class="ai-trace"><strong>Visible text / labels</strong><ul>${labels.slice(0, 8).map(item => `<li>${esc(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul></div>` : ""}
        ${uncertainties.length ? `<div class="ai-trace"><strong>Uncertainty retained</strong><ul>${uncertainties.map(item => `<li>${esc(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul></div>` : ""}
      </article>`;
  }

  function renderPhotoRevision(data) {
    const suggestion = data.latest_revision;
    if (!suggestion) {
      if (data.status === "ANALYZING" && data.revision_job_id) {
        return '<div class="ai-working"><div class="spinner spinner-small" aria-hidden="true"></div><p>Correlating the independent photo analyses with the Current Operations Narrative…</p><p class="help">This runs on the separate Photo Intelligence lane.</p></div>';
      }
      if (data.status === "ANALYSIS_COMPLETE") {
        return '<div class="validation-item INFO"><strong>Independent analysis complete.</strong><p>The photographs have been interpreted and cached without narrative context. Select <strong>Suggest Revision</strong> to compare those visual findings with the written Current Operations Narrative.</p></div>';
      }
      return "";
    }

    if (data.latest_revision_is_stale) {
      return '<div class="validation-item WARNING"><strong>Previous photo revision is stale.</strong><p>The narrative or photograph analysis changed after this revision was generated. Generate a new revision before reviewing it.</p></div>';
    }

    const content = suggestion.content || {};
    const pending = suggestion.review_state === "PENDING";
    const passed = content.verification_status === "PASSED" && content.accept_allowed === true;
    const additions = content.photo_supported_additions || [];
    const questions = content.conflicts_or_questions || [];
    const unsupported = content.unsupported_claims || [];
    const noRevision = content.revision_needed === false;
    return `
      <section class="photo-revision-review">
        <div class="section-head">
          <div>
            <h3>Suggested revision based on photo evidence</h3>
            <div class="card-meta">
              <span class="badge ${suggestion.review_state === "APPROVED" ? "badge-success" : suggestion.review_state === "REJECTED" ? "badge-danger" : "badge-warning"}">${esc(suggestion.review_state)}</span>
              <span class="badge ${passed ? "badge-success" : "badge-warning"}">${esc(content.verification_status || "REVIEW REQUIRED")}</span>
            </div>
          </div>
        </div>
        ${noRevision ? '<div class="validation-item INFO"><strong>No wording change recommended.</strong><p>The photo analysis did not provide sufficiently supported additional information to justify changing the narrative.</p></div>' : `
          <div class="ai-comparison-grid">
            <section class="ai-comparison-panel">
              <div class="ai-panel-title"><h3>Current narrative</h3><span class="badge">Written context</span></div>
              <textarea class="ai-comparison-text" readonly>${esc(content.original_text || "")}</textarea>
            </section>
            <section class="ai-comparison-panel">
              <div class="ai-panel-title"><h3>Photo-supported revision</h3><span class="badge badge-cyan">Suggested</span></div>
              <textarea class="ai-comparison-text" readonly>${esc(content.suggested_text || content.enhanced_text || "")}</textarea>
            </section>
          </div>`}
        ${content.rationale ? `<p class="help"><strong>Why:</strong> ${esc(content.rationale)}</p>` : ""}
        ${additions.length ? `<div class="ai-trace"><strong>Photo-supported additions</strong><ul>${additions.map(item => `<li>${esc(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul></div>` : ""}
        ${questions.length ? `<div class="ai-trace"><strong>Conflicts / questions</strong><ul>${questions.map(item => `<li>${esc(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul></div>` : ""}
        ${unsupported.length ? `<div class="validation-item ERROR"><strong>Unsupported wording detected.</strong><ul>${unsupported.map(item => `<li>${esc(item.text || JSON.stringify(item))}${item.reason ? ` — ${esc(item.reason)}` : ""}</li>`).join("")}</ul></div>` : ""}
        ${pending && !noRevision ? `<div class="card-actions"><button class="btn btn-primary" type="button" data-v090-action="review-photo-revision" data-decision="APPROVED" data-suggestion-id="${esc(suggestion.id)}" ${passed ? "" : "disabled"}>Accept Revision</button><button class="btn btn-danger" type="button" data-v090-action="review-photo-revision" data-decision="REJECTED" data-suggestion-id="${esc(suggestion.id)}">Reject</button></div>` : ""}
      </section>`;
  }

  async function refreshPhotoIntelligence(sectionId) {
    const body = document.getElementById("photo-intelligence-body");
    if (!body) return null;
    const data = await api(`/api/reports/${state.report.report.id}/sections/${sectionId}/photo-intelligence`, {}, false);
    const status = document.getElementById("photo-intelligence-status");
    if (status) {
      status.textContent = photoStatusLabel(data.status);
      status.className = `badge ${photoStatusClass(data.status)}`;
    }
    const revisionButton = document.getElementById("photo-intelligence-revision-button");
    if (revisionButton) revisionButton.disabled = !data.can_request_revision;

    const analyses = data.photos.length
      ? `<div class="photo-intelligence-results"><div class="card-meta"><span>${esc(data.analyzed_count)} of ${esc(data.photo_count)} analyzed</span></div>${data.photos.map(renderPhotoAnalysis).join("")}</div>`
      : '<p class="help">Add one or more photographs to this section to use Photo Intelligence.</p>';

    body.innerHTML = `${analyses}${renderPhotoRevision(data)}`;
    return data;
  }

  async function pollPhotoIntelligence(sectionId) {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      if (!document.getElementById("photo-intelligence") || selectedSection()?.id !== sectionId) return;
      const data = await refreshPhotoIntelligence(sectionId);
      if (!data || data.status !== "ANALYZING") return;
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    const body = document.getElementById("photo-intelligence-body");
    if (body) {
      body.insertAdjacentHTML("afterbegin", '<div class="validation-item INFO">Photo Intelligence is still processing in the background. You can navigate away and return later without losing the analysis.</div>');
    }
  }

  const priorRenderReport = renderReport;
  renderReport = async function v090RenderReport(id, sectionId = null) {
    await priorRenderReport(id, sectionId);
    const section = selectedSection();
    if (section && document.getElementById("photo-intelligence")) {
      refreshPhotoIntelligence(section.id).catch(error => {
        const body = document.getElementById("photo-intelligence-body");
        if (body) body.innerHTML = `<div class="validation-item ERROR">${esc(error.message)}</div>`;
      });
    }
  };

  document.addEventListener("click", async event => {
    const target = event.target.closest("[data-v090-action]");
    if (!target) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const section = selectedSection();
    const reportId = state.report?.report?.id;
    if (!section || !reportId) return;
    try {
      const action = target.dataset.v090Action;
      if (action === "analyze-photos") {
        target.disabled = true;
        await api(`/api/reports/${reportId}/sections/${section.id}/photo-intelligence/analyze`, {
          method: "POST",
          body: {},
        }, false);
        toast("Photo Intelligence analysis queued.", "success");
        await pollPhotoIntelligence(section.id);
        return;
      }
      if (action === "suggest-photo-revision") {
        target.disabled = true;
        await api(`/api/reports/${reportId}/sections/${section.id}/photo-intelligence/revision`, {
          method: "POST",
          body: {},
        }, false);
        toast("Photo-supported narrative revision queued.", "success");
        await pollPhotoIntelligence(section.id);
        return;
      }
      if (action === "review-photo-revision") {
        const decision = target.dataset.decision;
        const suggestionId = target.dataset.suggestionId;
        let note = null;
        if (decision === "REJECTED") {
          note = window.prompt("Optional reason for rejecting this photo-supported revision:", "") || null;
        }
        await api(`/api/reports/${reportId}/sections/${section.id}/photo-intelligence/revisions/${suggestionId}/review`, {
          method: "POST",
          body: {decision, note},
        }, false);
        toast(decision === "APPROVED" ? "Photo-supported narrative revision accepted." : "Photo-supported revision rejected.", "success");
        await renderReport(reportId, section.id);
      }
    } catch (error) {
      toast(error.message, "error");
      target.disabled = false;
      refreshPhotoIntelligence(section.id).catch(() => {});
    }
  }, true);
})();

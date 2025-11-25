(() => {
  const dataEl = document.getElementById("run-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent || "{}");
  const timeline = data.timeline || {};
  const transcript = data.transcript || [];
  const winners = data.winning_agents || [];

  const agentSel = document.getElementById("agentSelect");
  const roundSel = document.getElementById("roundSelect");
  const viewer = document.getElementById("viewerText");
  const viewerMeta = document.getElementById("viewerMeta");
  const wrapBtn = document.getElementById("wrapBtn");
  const copyBtn = document.getElementById("copyBtn");
  const finalText = document.getElementById("finalText");
  const finalCopyBtn = document.getElementById("finalCopyBtn");
  const finalWrapBtn = document.getElementById("finalWrapBtn");

  let currentTab = "solution";

  const findEvent = (aid, roundIdx) => {
    const events = timeline[aid] || [];
    return events.find((e) => e.round === roundIdx) || null;
  };

  const setTab = (tab) => {
    currentTab = tab;
    document.querySelectorAll(".tab-link").forEach((el) => {
      el.classList.remove("border-blue-500", "text-blue-600");
      el.classList.add("text-slate-600");
      if (el.dataset.tab === tab) {
        el.classList.add("border-blue-500", "text-blue-600");
        el.classList.remove("text-slate-600");
      }
    });
    updateView();
  };

  const updateView = () => {
    const aid = agentSel.value;
    const roundIdx = parseInt(roundSel.value, 10);
    const e = findEvent(aid, roundIdx);
    if (!e) {
      viewer.textContent = "(no event for this agent in this round)";
      viewerMeta.textContent = "";
      return;
    }
    let text = "";
    if (currentTab === "solution") text = e.solution || "(empty)";
    if (currentTab === "reasoning") text = e.reasoning || "(empty)";
    if (currentTab === "diff") text = e.diff || "(no diff)";
    viewer.textContent = text;
    viewerMeta.textContent = `Agent ${aid} — Round ${e.round} (${e.type}) — decision: ${e.decision} — changed: ${e.changed} — peers_seen: ${e.peers_seen}`;
  };

  document.querySelectorAll(".tab-link").forEach((el) => {
    el.addEventListener("click", (ev) => {
      ev.preventDefault();
      setTab(el.dataset.tab);
    });
  });
  agentSel?.addEventListener("change", updateView);
  roundSel?.addEventListener("change", updateView);

  wrapBtn?.addEventListener("click", () => {
    const wrap = wrapBtn.getAttribute("data-wrap") === "1";
    if (wrap) {
      viewer.classList.remove("whitespace-pre-wrap");
      viewer.classList.add("whitespace-pre");
      wrapBtn.textContent = "Wrap";
      wrapBtn.setAttribute("data-wrap", "0");
    } else {
      viewer.classList.remove("whitespace-pre");
      viewer.classList.add("whitespace-pre-wrap");
      wrapBtn.textContent = "No-wrap";
      wrapBtn.setAttribute("data-wrap", "1");
    }
  });

  copyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(viewer.textContent || "");
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = "Copy"), 1200);
    } catch {
      /* no-op */
    }
  });

  finalCopyBtn?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(finalText?.textContent || "");
      finalCopyBtn.textContent = "Copied!";
      setTimeout(() => (finalCopyBtn.textContent = "Copy"), 1200);
    } catch {
      /* no-op */
    }
  });

  finalWrapBtn?.addEventListener("click", () => {
    const wrap = finalWrapBtn.getAttribute("data-wrap") === "1";
    if (wrap) {
      finalText?.classList.remove("whitespace-pre-wrap");
      finalText?.classList.add("whitespace-pre");
      finalWrapBtn.textContent = "Wrap";
      finalWrapBtn.setAttribute("data-wrap", "0");
    } else {
      finalText?.classList.remove("whitespace-pre");
      finalText?.classList.add("whitespace-pre-wrap");
      finalWrapBtn.textContent = "No-wrap";
      finalWrapBtn.setAttribute("data-wrap", "1");
    }
  });

  // Default selection
  const init = () => {
    if (winners && winners.length && timeline[winners[0]]) {
      agentSel.value = winners[0];
    }
    if (transcript && transcript.length) {
      roundSel.value = transcript[transcript.length - 1].round;
    }
    updateView();
  };
  init();
})();

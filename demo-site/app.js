const fileInputs = {
  pcb: document.querySelector("#pcb-file"),
  sch: document.querySelector("#sch-file"),
};

const fileViews = {
  pcb: {
    card: document.querySelector("#pcb-card"),
    name: document.querySelector("#pcb-name"),
    extension: ".kicad_pcb",
  },
  sch: {
    card: document.querySelector("#sch-card"),
    name: document.querySelector("#sch-name"),
    extension: ".kicad_sch",
  },
};

const runButton = document.querySelector("#run-button");
const resetButton = document.querySelector("#reset-button");
const reviewPlanButton = document.querySelector("#review-plan-button");
const proceedButton = document.querySelector("#proceed-button");
const reviewReportButton = document.querySelector("#review-report-button");
const inputStatus = document.querySelector("#input-status");
const uploadNote = document.querySelector("#upload-note");
const runId = document.querySelector("#run-id");
const testRunId = document.querySelector("#test-run-id");
const systemState = document.querySelector("#system-state");
const successCard = document.querySelector("#success-card");
const executionPanel = document.querySelector("#execution-panel");
const reportReady = document.querySelector("#report-ready");
const reportPreview = document.querySelector("#report-preview");
const steps = [...document.querySelectorAll("#steps .step")];
const testSteps = [...document.querySelectorAll("[data-test-step]")];

let running = false;
let selectedFiles = { pcb: null, sch: null };

function resetSteps() {
  steps.forEach((step, index) => {
    step.classList.remove("active", "complete");
    step.querySelector(".step-state").textContent = index === 0 ? "Waiting" : "Queued";
  });
  successCard.hidden = true;
  runId.textContent = "IDLE";
}

function resetTestSteps() {
  testSteps.forEach((step, index) => {
    step.classList.remove("active", "complete");
    step.querySelector(".step-state").textContent = index === 0 ? "Waiting" : "Queued";
  });
  executionPanel.hidden = true;
  reportReady.hidden = true;
  reportPreview.hidden = true;
  testRunId.textContent = "STANDBY";
}

function updateFile(key) {
  const file = fileInputs[key].files[0];
  const view = fileViews[key];

  if (!file) {
    selectedFiles[key] = null;
    view.card.classList.remove("loaded");
    view.name.textContent = `Select ${view.extension}`;
    updateReadiness();
    return;
  }

  if (!file.name.toLowerCase().endsWith(view.extension)) {
    selectedFiles[key] = null;
    fileInputs[key].value = "";
    view.card.classList.remove("loaded");
    view.name.textContent = `Select ${view.extension}`;
    uploadNote.textContent = `${file.name} is not a ${view.extension} file.`;
    uploadNote.classList.add("error");
    updateReadiness();
    return;
  }

  selectedFiles[key] = file;
  view.card.classList.add("loaded");
  view.name.textContent = file.name;
  updateReadiness();
}

function updateReadiness() {
  const ready = Boolean(selectedFiles.pcb && selectedFiles.sch);
  runButton.disabled = !ready || running;
  inputStatus.textContent = ready ? "Package ready" : "Awaiting files";
  inputStatus.classList.toggle("ready", ready);

  if (!ready && !uploadNote.classList.contains("error")) {
    uploadNote.textContent = "Both KiCad design files are required to begin.";
  }
  if (ready) {
    uploadNote.textContent = "Design package verified. Generate the inspection plan when ready.";
    uploadNote.classList.remove("error");
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function runInspection() {
  if (running || !selectedFiles.pcb || !selectedFiles.sch) return;

  running = true;
  resetSteps();
  runButton.disabled = true;
  inputStatus.textContent = "Processing";
  inputStatus.classList.remove("ready");
  uploadNote.textContent = "Inspection pipeline is running locally.";
  runId.textContent = "RUNNING";

  for (const [index, step] of steps.entries()) {
    step.classList.add("active");
    step.querySelector(".step-state").textContent = "Working";
    await wait(index === 0 ? 1700 : 1900);
    step.classList.remove("active");
    step.classList.add("complete");
    step.querySelector(".step-state").textContent = "Complete";
  }

  runId.textContent = "COMPLETE";
  inputStatus.textContent = "Plan ready";
  inputStatus.classList.add("ready");
  uploadNote.textContent = "Inspection plan finalized for the uploaded design package.";
  successCard.hidden = false;
  running = false;
  updateReadiness();
}

async function runTests() {
  if (running) return;

  running = true;
  resetTestSteps();
  runButton.disabled = true;
  executionPanel.hidden = false;
  executionPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  systemState.textContent = "Test run active";
  testRunId.textContent = "SEARCHING";

  const delays = [2300, 1900, 5200, 2800];
  for (const [index, step] of testSteps.entries()) {
    step.classList.add("active");
    step.querySelector(".step-state").textContent = index === 0 ? "Searching" : "Working";
    if (index === 1) testRunId.textContent = "DEVICE FOUND";
    if (index === 2) testRunId.textContent = "TESTING";
    if (index === 3) testRunId.textContent = "FINALIZING";
    await wait(delays[index]);
    step.classList.remove("active");
    step.classList.add("complete");
    step.querySelector(".step-state").textContent = "Complete";
  }

  testRunId.textContent = "COMPLETE";
  systemState.textContent = "System ready";
  reportReady.hidden = false;
  running = false;
  updateReadiness();
}

function resetDemo() {
  if (running) return;
  selectedFiles = { pcb: null, sch: null };
  Object.entries(fileInputs).forEach(([key, input]) => {
    input.value = "";
    const view = fileViews[key];
    view.card.classList.remove("loaded");
    view.name.textContent = `Select ${view.extension}`;
  });
  uploadNote.classList.remove("error");
  resetSteps();
  resetTestSteps();
  systemState.textContent = "System ready";
  updateReadiness();
}

fileInputs.pcb.addEventListener("change", () => updateFile("pcb"));
fileInputs.sch.addEventListener("change", () => updateFile("sch"));
runButton.addEventListener("click", runInspection);
resetButton.addEventListener("click", resetDemo);
proceedButton.addEventListener("click", runTests);
reviewPlanButton.addEventListener("click", () => {
  uploadNote.textContent = "Plan summary is available in the full inspector application.";
});
reviewReportButton.addEventListener("click", () => {
  reportPreview.hidden = false;
  reportPreview.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

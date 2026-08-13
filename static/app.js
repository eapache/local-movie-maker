const $ = (selector) => document.querySelector(selector);

const form = $('#movie-form');
const prompt = $('#prompt');
const duration = $('#duration');
const production = $('#production');
const result = $('#result');
const story = $('#story');
const submitButton = form.querySelector('button[type="submit"]');
let pollTimer = null;
let currentProject = null;

const stages = [
  ['planning', 'Writing'],
  ['handoff', 'GPU handoff'],
  ['references', 'References'],
  ['shots', 'Rendering'],
  ['soundtrack', 'Sound + edit'],
];

const stageOrder = {
  queued: -1, planning: 0, handoff: 1, references: 2, shots: 3,
  soundtrack: 4, assembly: 4, complete: 5, failed: -1,
};

function setText(selector, value) {
  $(selector).textContent = value ?? '';
}

function showError(message) {
  const node = $('#form-error');
  node.textContent = message;
  node.hidden = !message;
}

function updateDuration() {
  const seconds = Number(duration.value);
  $('#duration-output').value = seconds < 60 ? `${seconds} sec` : `${seconds / 60} min`;
}

duration.addEventListener('input', updateDuration);
prompt.addEventListener('input', () => setText('#prompt-count', `${prompt.value.length} / 1,000`));

const ideas = [
  'A lonely lighthouse keeper discovers the stars are answering his signals.',
  'A tiny robot tends the last garden on a silent space station.',
  'Every night, a baker leaves one glowing loaf on the windowsill for the moon.',
  'Two strangers share an umbrella while time freezes around them.',
  'A child finds a door in an old tree that opens onto tomorrow.',
];

$('#inspire').addEventListener('click', () => {
  const choices = ideas.filter((idea) => idea !== prompt.value);
  prompt.value = choices[Math.floor(Math.random() * choices.length)];
  prompt.dispatchEvent(new Event('input'));
  prompt.focus();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showError('');
  submitButton.disabled = true;
  const body = {
    prompt: prompt.value.trim(),
    duration: Number(duration.value),
    resolution: new FormData(form).get('resolution'),
    llama_model: $('#llama-model').value || null,
    checkpoint: $('#checkpoint').value || null,
    video_workflow: $('#video-workflow').value || null,
  };
  try {
    const response = await fetch('/api/projects', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not create the project.');
    currentProject = data.id;
    renderProject(data);
    production.scrollIntoView({behavior: 'smooth', block: 'start'});
    pollProject();
  } catch (error) {
    showError(error.message);
    submitButton.disabled = false;
  }
});

async function pollProject() {
  clearTimeout(pollTimer);
  if (!currentProject) return;
  try {
    const response = await fetch(`/api/projects/${currentProject}`, {cache: 'no-store'});
    const project = await response.json();
    if (!response.ok) throw new Error(project.error || 'Could not read project status.');
    renderProject(project);
    if (project.status === 'queued' || project.status === 'running') {
      pollTimer = setTimeout(pollProject, 1200);
    }
  } catch (error) {
    $('#project-error').hidden = false;
    setText('#project-error', error.message);
    pollTimer = setTimeout(pollProject, 3000);
  }
}

function renderProject(project) {
  production.hidden = false;
  const plan = project.plan;
  setText('#project-title', plan?.title || 'Building your film');
  setText('#project-status', project.status === 'running' ? project.stage : project.status);
  setText('#progress-message', project.message);
  setText('#progress-value', `${project.progress}%`);
  $('#progress-bar').style.width = `${project.progress}%`;
  renderStages(project.stage);

  const error = $('#project-error');
  error.hidden = !project.error;
  error.textContent = project.error || '';

  if (plan) renderStory(plan, project.assets || []);
  if (project.status === 'complete') {
    submitButton.disabled = false;
    renderResult(project);
  } else if (project.status === 'failed') {
    submitButton.disabled = false;
  }
}

function renderStages(active) {
  const list = $('#stage-list');
  list.replaceChildren();
  const current = stageOrder[active] ?? -1;
  stages.forEach(([key, label], index) => {
    const node = document.createElement('div');
    node.className = `stage ${index < current ? 'done' : index === current ? 'active' : ''}`;
    node.textContent = label;
    list.append(node);
  });
}

function renderStory(plan, assets) {
  story.hidden = false;
  $('#story-overview').textContent = plan.overview;
  const gallery = $('#asset-gallery');
  gallery.replaceChildren();
  assets.forEach((asset) => {
    const figure = document.createElement('figure');
    figure.className = 'asset';
    const img = document.createElement('img');
    img.src = asset.url;
    img.alt = `${asset.name} reference`;
    img.loading = 'lazy';
    const caption = document.createElement('figcaption');
    const name = document.createElement('span');
    name.textContent = asset.name;
    const kind = document.createElement('span');
    kind.textContent = asset.kind;
    caption.append(name, kind);
    figure.append(img, caption);
    gallery.append(figure);
  });

  const shots = $('#shot-list');
  shots.replaceChildren();
  plan.shots.forEach((shot) => {
    const row = document.createElement('article');
    row.className = 'shot';
    const number = document.createElement('span');
    number.className = 'shot-number';
    number.textContent = String(shot.id).padStart(2, '0');
    const copy = document.createElement('div');
    const title = document.createElement('h4');
    title.textContent = shot.title;
    const action = document.createElement('p');
    action.textContent = `${shot.action} · ${shot.camera}`;
    copy.append(title, action);
    const timing = document.createElement('span');
    timing.className = 'shot-duration';
    timing.textContent = `${shot.duration}s`;
    row.append(number, copy, timing);
    shots.append(row);
  });
}

function renderResult(project) {
  result.hidden = false;
  setText('#result-title', project.plan?.title || 'Your film');
  setText('#result-logline', project.plan?.logline || '');
  const video = $('#final-video');
  if (video.src !== new URL(project.video_url, location.href).href) {
    video.src = project.video_url;
    video.load();
  }
  $('#download').href = project.video_url;
  result.scrollIntoView({behavior: 'smooth', block: 'center'});
}

async function init() {
  updateDuration();
  try {
    const response = await fetch('/api/config');
    const config = await response.json();
    $('#mode-badge').hidden = !config.demo_mode;
    await loadIntegrations();
    const projectsResponse = await fetch('/api/projects');
    const {projects} = await projectsResponse.json();
    const latest = projects?.[0];
    if (latest && ['queued', 'running'].includes(latest.status)) {
      currentProject = latest.id;
      renderProject(latest);
      pollProject();
    }
  } catch (_) {
    // The form can still surface a useful error if initial discovery fails.
  }
}

async function loadIntegrations() {
  const summary = $('#integration-summary');
  summary.textContent = 'Discovering local services…';
  try {
    const response = await fetch('/api/integrations', {cache: 'no-store'});
    const integrations = await response.json();
    if (!response.ok) throw new Error(integrations.error || 'Discovery failed.');
    fillSelect(
      $('#llama-model'),
      integrations.llama.models.map((name) => ({value: name, label: name})),
      integrations.llama.configured,
    );
    fillSelect(
      $('#checkpoint'),
      integrations.comfy.checkpoints.map((name) => ({value: name, label: name})),
      integrations.comfy.configured,
    );

    const workflows = [];
    if (integrations.comfy.workflows.video) {
      workflows.push({value: '', label: `Configured: ${integrations.comfy.workflows.video}`});
    }
    integrations.comfy.saved_workflows
      .filter((workflow) => ['t2v', 'i2v'].includes(workflow.kind))
      .forEach((workflow) => workflows.push({
        value: workflow.id,
        label: `${workflow.name} · ${workflow.kind.toUpperCase()}${workflow.executable ? '' : ' · UI format (export API)'}`,
        disabled: !workflow.executable,
      }));
    fillSelect($('#video-workflow'), workflows, null, !integrations.comfy.workflows.video);

    const llamaOK = integrations.llama.models.length > 0;
    const comfyOK = integrations.comfy.checkpoints.length > 0;
    const videoOK = Boolean(integrations.comfy.workflows.video) || workflows.some((item) => item.value && !item.disabled);
    summary.textContent = `${llamaOK ? integrations.llama.models.length : 0} LLMs · ${comfyOK ? integrations.comfy.checkpoints.length : 0} checkpoints · ${videoOK ? 'video ready' : 'video workflow needed'}`;
    $('#workflow-help').textContent = videoOK
      ? 'The selected API workflow will receive each shot prompt, keyframe, duration, dimensions, FPS, and seed.'
      : 'Saved UI workflows were found, but ComfyUI only executes API-format graphs remotely. In Dev Mode, use Save (API Format), then refresh.';
    if (!llamaOK || !comfyOK || !videoOK) $('#advanced').open = true;
  } catch (error) {
    summary.textContent = 'Local service discovery failed';
    $('#workflow-help').textContent = error.message;
    $('#advanced').open = true;
  }
}

function fillSelect(select, options, selected, requireChoice = false) {
  const first = select.options[0];
  select.replaceChildren(first);
  options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    option.disabled = Boolean(item.disabled);
    select.append(option);
  });
  if (selected && [...select.options].some((option) => option.value === selected)) {
    select.value = selected;
  } else if (!requireChoice && options.length && !options[0].disabled) {
    select.value = options[0].value;
  }
}

$('#refresh-integrations').addEventListener('click', loadIntegrations);

init();

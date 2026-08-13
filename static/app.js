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

const durationChoices = Array.from({length: 24}, (_, index) => (index + 1) * 5);

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
  $('#duration-output').value = formatDuration(selectedDuration());
}

function selectedDuration() {
  return durationChoices[Number(duration.value)];
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes} min ${remainder} sec` : `${minutes} min`;
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
    duration: selectedDuration(),
    resolution: new FormData(form).get('resolution'),
    llama_model: $('#llama-model').value || null,
    image_workflow: $('#image-workflow').value || null,
    video_workflow: $('#video-workflow').value || null,
    background_audio_workflow: $('#background-audio-workflow').value || null,
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
  const aspectRatios = {
    vertical: '9 / 16',
    square: '1 / 1',
  };
  video.closest('.screen').style.aspectRatio = aspectRatios[project.request?.resolution] || '16 / 9';
  if (video.src !== new URL(project.video_url, location.href).href) {
    video.src = project.video_url;
    video.load();
  }
  $('#download').href = project.video_url;
  result.scrollIntoView({behavior: 'smooth', block: 'center'});
}

async function init() {
  duration.max = String(durationChoices.length - 1);
  duration.value = String(durationChoices.indexOf(30));
  updateDuration();

  // Discovery should not depend on the unrelated config request succeeding.
  // In particular, opening the HTML directly or receiving a stale response must
  // produce a visible error instead of leaving the initial status there forever.
  const integrationsPromise = loadIntegrations();
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('Could not load application configuration.');
    const config = await response.json();
    $('#mode-badge').hidden = !config.demo_mode;
  } catch (_) {
    // Integration discovery reports its own actionable connection error.
  }

  await integrationsPromise;
  try {
    const projectsResponse = await fetch('/api/projects');
    if (!projectsResponse.ok) throw new Error('Could not load projects.');
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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch('/api/integrations', {
      cache: 'no-store',
      signal: controller.signal,
    });
    const integrations = await response.json();
    if (!response.ok) throw new Error(integrations.error || 'Discovery failed.');
    fillSelect(
      $('#llama-model'),
      integrations.llama.models.map((name) => ({value: name, label: name})),
      integrations.llama.configured,
    );
    const imageWorkflows = integrations.comfy.saved_workflows
      .filter((workflow) => workflow.kind === 'image')
      .map((workflow) => ({
        value: workflow.id,
        label: `${workflow.name}${workflow.executable ? '' : ' · UI format (Export API)'}`,
        disabled: !workflow.executable,
      }))
      .sort((left, right) => Number(left.disabled) - Number(right.disabled));
    fillSelect($('#image-workflow'), imageWorkflows, null);

    const videoWorkflows = [];
    if (integrations.comfy.workflows.video) {
      videoWorkflows.push({value: '', label: `Configured: ${integrations.comfy.workflows.video}`});
    }
    integrations.comfy.saved_workflows
      .filter((workflow) => workflow.capabilities?.video
        && workflow.capabilities.references
        && !workflow.capabilities.keyframe)
      .forEach((workflow) => videoWorkflows.push({
        value: workflow.id,
        label: `${workflow.name} · REF2V${workflow.executable ? '' : ' · UI format (Export API)'}`,
        disabled: !workflow.executable,
      }));
    videoWorkflows.sort((left, right) => Number(left.disabled) - Number(right.disabled));
    fillSelect(
      $('#video-workflow'),
      videoWorkflows,
      null,
      !integrations.comfy.workflows.video,
    );

    const backgroundAudioWorkflows = [];
    if (integrations.comfy.workflows.background_audio) {
      backgroundAudioWorkflows.push({
        value: '',
        label: `Configured: ${integrations.comfy.workflows.background_audio}`,
      });
    }
    integrations.comfy.saved_workflows
      .filter((workflow) => workflow.kind === 'audio')
      .forEach((workflow) => backgroundAudioWorkflows.push({
        value: workflow.id,
        label: `${workflow.name} · T2A${workflow.executable ? '' : ' · UI format (Export API)'}`,
        disabled: !workflow.executable,
      }));
    backgroundAudioWorkflows.sort((left, right) => Number(left.disabled) - Number(right.disabled));
    fillSelect($('#background-audio-workflow'), backgroundAudioWorkflows, null);

    const llamaOK = integrations.llama.models.length > 0;
    const executableImages = imageWorkflows.filter((item) => !item.disabled);
    const imageOK = Boolean(integrations.comfy.workflows.image) || executableImages.length > 0;
    const videoOK = Boolean(integrations.comfy.workflows.video) || videoWorkflows.some((item) => item.value && !item.disabled);
    const audioOK = Boolean(integrations.comfy.workflows.background_audio)
      || backgroundAudioWorkflows.some((item) => item.value && !item.disabled);
    summary.textContent = `${llamaOK ? integrations.llama.models.length : 0} LLMs · ${executableImages.length} image workflows · ${videoOK ? 'reference video ready' : 'reference video workflow needed'} · ${audioOK ? 'background audio ready' : 'no background audio'}`;
    $('#image-workflow-help').textContent = executableImages.length
      ? 'Executable T2I workflows are preferred; the configured image workflow remains available as a fallback.'
      : imageWorkflows.length
        ? `${imageWorkflows.length} saved image workflow(s) still need an API export.`
        : `No saved T2I API workflows found; using configured ${integrations.comfy.workflows.image}.`;
    $('#workflow-help').textContent = videoOK
      ? 'Begins each shot from its text plus the matching character and setting references.'
      : 'No executable text + reference video workflow was found.';
    if (!llamaOK || !imageOK || !videoOK) $('#advanced').open = true;
  } catch (error) {
    summary.textContent = 'Local service discovery failed';
    $('#workflow-help').textContent = error.name === 'AbortError'
      ? 'Discovery timed out. Check that the local server can reach llama.cpp and ComfyUI, then refresh.'
      : `${error.message} Make sure this page was opened from the Local Movie Maker server, not as a file.`;
    $('#advanced').open = true;
  } finally {
    clearTimeout(timeout);
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

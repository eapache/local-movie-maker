const $ = (selector) => document.querySelector(selector);

const form = $('#movie-form');
const prompt = $('#prompt');
const duration = $('#duration');
const production = $('#production');
const result = $('#result');
const story = $('#story');
const submitButton = form.querySelector('button[type="submit"]');
const projectsToggle = $('#projects-toggle');
const projectsSidebar = $('#project-sidebar');
const sidebarBackdrop = $('#sidebar-backdrop');
let pollTimer = null;
let currentProject = null;
let projectHistory = [];

const durationChoices = [
  ...Array.from({length: 24}, (_, index) => (index + 1) * 5),
  ...Array.from({length: 6}, (_, index) => 150 + index * 30),
  ...Array.from({length: 10}, (_, index) => 360 + index * 60),
  ...Array.from({length: 15}, (_, index) => 1_200 + index * 300),
];

const stages = [
  ['overview', 'Overview'],
  ['bible', 'Story bible'],
  ['screenplay', 'Screenplay'],
  ['shotlist', 'Shot planning'],
  ['references', 'References'],
  ['shots', 'Rendering'],
  ['soundtrack', 'Soundtrack'],
  ['assembly', 'Editing'],
];

const stageOrder = {
  queued: -1, planning: 0, overview: 0, bible: 1, screenplay: 2, shotlist: 3,
  references: 4, shots: 5, soundtrack: 6, assembly: 7,
  complete: 8, failed: -1,
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

function formatProjectDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown date';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(date);
}

function projectLabel(project) {
  return project.plan?.title || project.request?.prompt || 'Untitled project';
}

function projectStatus(project) {
  const value = project.status === 'running' ? project.stage : project.status;
  return String(value || 'unknown').replaceAll('_', ' ');
}

function renderProjectHistory(emptyMessage = '') {
  const history = $('#project-history');
  history.replaceChildren();
  $('#project-count').textContent = String(projectHistory.length);

  if (!projectHistory.length) {
    const empty = document.createElement('p');
    empty.className = 'project-history-empty';
    empty.textContent = emptyMessage || 'No projects yet. Your finished and in-progress films will appear here.';
    history.append(empty);
    return;
  }

  projectHistory.forEach((project) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'project-history-item';
    button.dataset.projectId = project.id;
    button.setAttribute('aria-current', project.id === currentProject ? 'true' : 'false');
    button.setAttribute('aria-label', `Load ${projectLabel(project)}`);

    const heading = document.createElement('span');
    heading.className = 'project-history-title';
    const title = document.createElement('strong');
    title.textContent = projectLabel(project);
    const status = document.createElement('span');
    status.className = `project-history-status status-${project.status}`;
    status.textContent = projectStatus(project);
    heading.append(title, status);

    const meta = document.createElement('span');
    meta.className = 'project-history-meta';
    meta.textContent = [
      formatProjectDate(project.created_at),
      project.request?.duration ? formatDuration(project.request.duration) : null,
      project.request?.resolution,
    ].filter(Boolean).join(' · ');
    button.append(heading, meta);
    button.addEventListener('click', () => reloadProject(project.id));
    history.append(button);
  });
}

function rememberProject(project) {
  projectHistory = [project, ...projectHistory.filter((item) => item.id !== project.id)]
    .sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)))
    .slice(0, 20);
  renderProjectHistory();
  setText('#project-history-status', `${projectHistory.length} recent project${projectHistory.length === 1 ? '' : 's'}`);
}

async function loadProjects() {
  const refresh = $('#projects-refresh');
  refresh.disabled = true;
  setText('#project-history-status', 'Refreshing projects…');
  try {
    const response = await fetch('/api/projects', {cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load projects.');
    projectHistory = Array.isArray(data.projects) ? data.projects : [];
    renderProjectHistory();
    setText('#project-history-status', `${projectHistory.length} recent project${projectHistory.length === 1 ? '' : 's'}`);
  } catch (error) {
    setText('#project-history-status', 'Archive unavailable');
    if (!projectHistory.length) renderProjectHistory(error.message);
  } finally {
    refresh.disabled = false;
  }
  return projectHistory;
}

function setProjectSidebar(open, returnFocus = true) {
  projectsToggle.setAttribute('aria-expanded', String(open));
  projectsSidebar.setAttribute('aria-hidden', String(!open));
  projectsSidebar.inert = !open;
  projectsSidebar.classList.toggle('is-open', open);
  sidebarBackdrop.classList.toggle('is-open', open);
  document.body.classList.toggle('sidebar-open', open);
  if (open) {
    $('#projects-close').focus();
  } else if (returnFocus) {
    projectsToggle.focus();
  }
}

async function reloadProject(projectId) {
  setText('#project-history-status', 'Opening project…');
  try {
    const response = await fetch(`/api/projects/${projectId}`, {cache: 'no-store'});
    const project = await response.json();
    if (!response.ok) throw new Error(project.error || 'Could not load the project.');
    clearTimeout(pollTimer);
    currentProject = project.id;
    renderProject(project);
    setProjectSidebar(false, false);
    if (project.status !== 'complete') {
      production.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    if (project.status === 'queued' || project.status === 'running') pollProject();
  } catch (error) {
    setText('#project-history-status', error.message);
  }
}

projectsToggle.addEventListener('click', () => {
  const open = projectsToggle.getAttribute('aria-expanded') !== 'true';
  setProjectSidebar(open);
  if (open) loadProjects();
});
$('#projects-close').addEventListener('click', () => setProjectSidebar(false));
$('#projects-refresh').addEventListener('click', loadProjects);
sidebarBackdrop.addEventListener('click', () => setProjectSidebar(false));
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && projectsToggle.getAttribute('aria-expanded') === 'true') {
    setProjectSidebar(false);
  }
});

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
  const projectId = currentProject;
  try {
    const response = await fetch(`/api/projects/${projectId}`, {cache: 'no-store'});
    const project = await response.json();
    if (!response.ok) throw new Error(project.error || 'Could not read project status.');
    if (projectId !== currentProject) return;
    renderProject(project);
    if (project.status === 'queued' || project.status === 'running') {
      pollTimer = setTimeout(pollProject, 1200);
    }
  } catch (error) {
    if (projectId !== currentProject) return;
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

  story.hidden = !plan;
  if (plan) renderStory(plan, project.assets || []);
  if (project.status === 'complete') {
    submitButton.disabled = false;
    renderResult(project);
  } else if (project.status === 'failed') {
    submitButton.disabled = false;
    result.hidden = true;
  } else {
    submitButton.disabled = true;
    result.hidden = true;
  }
  rememberProject(project);
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
  const aspectRatios = {square: '1 / 1'};
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
  const projectsPromise = loadProjects();
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('Could not load application configuration.');
    const config = await response.json();
    $('#mode-badge').hidden = !config.demo_mode;
  } catch (_) {
    // Integration discovery reports its own actionable connection error.
  }

  const projects = await projectsPromise;
  const latest = projects[0];
  if (latest && ['queued', 'running'].includes(latest.status)) {
    currentProject = latest.id;
    renderProject(latest);
    pollProject();
  }
  await integrationsPromise;
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
    const configuredImage = integrations.comfy.workflows.image;
    if (configuredImage) {
      $('#image-workflow').options[0].textContent = `Configured: ${configuredImage}`;
    } else {
      $('#image-workflow').options[0].textContent = 'Select an image workflow';
    }
    fillSelect($('#image-workflow'), imageWorkflows, null, Boolean(configuredImage));

    const videoWorkflows = [];
    const configuredVideo = integrations.comfy.workflows.video;
    if (configuredVideo) {
      $('#video-workflow').options[0].textContent = `Configured: ${configuredVideo}`;
    } else {
      $('#video-workflow').options[0].textContent = 'Select a video workflow';
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
      Boolean(configuredVideo),
    );

    const backgroundAudioWorkflows = [];
    const configuredAudio = integrations.comfy.workflows.background_audio;
    if (configuredAudio) {
      $('#background-audio-workflow').options[0].textContent = `Configured: ${configuredAudio}`;
    } else {
      $('#background-audio-workflow').options[0].textContent = 'Select an audio workflow';
    }
    integrations.comfy.saved_workflows
      .filter((workflow) => workflow.kind === 'audio')
      .forEach((workflow) => backgroundAudioWorkflows.push({
        value: workflow.id,
        label: `${workflow.name} · T2A${workflow.executable ? '' : ' · UI format (Export API)'}`,
        disabled: !workflow.executable,
      }));
    backgroundAudioWorkflows.sort((left, right) => Number(left.disabled) - Number(right.disabled));
    fillSelect(
      $('#background-audio-workflow'),
      backgroundAudioWorkflows,
      null,
      Boolean(configuredAudio),
    );

    const llamaOK = integrations.llama.models.length > 0;
    const executableImages = imageWorkflows.filter((item) => !item.disabled);
    const imageOK = Boolean(integrations.comfy.workflows.image) || executableImages.length > 0;
    const videoOK = Boolean(configuredVideo) || videoWorkflows.some((item) => item.value && !item.disabled);
    const audioOK = Boolean(configuredAudio)
      || backgroundAudioWorkflows.some((item) => item.value && !item.disabled);
    summary.textContent = `${llamaOK ? integrations.llama.models.length : 0} LLMs · ${executableImages.length} image workflows · ${videoOK ? 'reference video ready' : 'reference video workflow needed'} · ${audioOK ? 'background audio ready' : 'background audio workflow needed'}`;
    $('#image-workflow-help').textContent = executableImages.length
      ? 'Select an executable T2I workflow for character and setting references.'
      : imageWorkflows.length
        ? `${imageWorkflows.length} saved image workflow(s) still need an API export.`
        : 'No executable T2I workflow was found.';
    $('#workflow-help').textContent = videoOK
      ? 'Begins each shot from its text plus the matching character and setting references.'
      : 'No executable text + reference video workflow was found.';
    if (!llamaOK || !imageOK || !videoOK || !audioOK) $('#advanced').open = true;
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

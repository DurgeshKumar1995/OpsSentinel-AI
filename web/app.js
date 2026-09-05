const $ = (selector) => document.querySelector(selector);
const incidentForm = $('#incident-form');
const messageInput = $('#incident-message');
const progress = $('#progress');
const result = $('#result');
const feedback = $('#feedback');
const approvalCard = $('#approval-card');
const logFileInput = $('#incident-log-file');
const responseEmpty = $('#response-empty');
let threadId = null;
let originalSymptom = '';
let latestAnswer = '';
let approvalToken = '';

const PROMPT_LIBRARY_KEY = 'opssentinel-prompt-library-v1';
const SESSION_STORE_KEY = 'opssentinel-incident-sessions-v1';
const APPROVAL_STORE_KEY = 'opssentinel-pending-approvals-v1';
const OPERATOR_STORE_KEY = 'opssentinel-operator-key-v1';
const SESSION_RETENTION_MS = 30 * 24 * 60 * 60 * 1000;
const DEFAULT_PROMPT_LIBRARY = {
  groups: [{id: 'diagnostics', name: 'Diagnostics'}, {id: 'recovery', name: 'Recovery'}],
  tags: [
    {id: 'payment-logs', groupId: 'diagnostics', label: 'Check payment logs', prompt: 'Check payment-gateway logs for the last 15 minutes.'},
    {id: 'fix-auth', groupId: 'recovery', label: 'Fix auth service', prompt: 'The auth-service is returning 500 errors. Investigate and fix it.'},
  ],
};
let promptLibrary = loadPromptLibrary();
let sessions = loadSessions();

function newId(prefix) { return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

function loadSessions() {
  try {
    const saved = JSON.parse(localStorage.getItem(SESSION_STORE_KEY));
    if (Array.isArray(saved)) return saved.filter((session) => session?.id && Array.isArray(session.turns) && Date.now() - Number(session.updatedAt || 0) <= SESSION_RETENTION_MS).slice(0, 20);
  } catch (_) { /* Invalid session history is ignored. */ }
  return [];
}

function approvalTokens() {
  try { return JSON.parse(sessionStorage.getItem(APPROVAL_STORE_KEY)) || {}; }
  catch (_) { return {}; }
}

function storeApprovalToken(id, token) {
  const tokens = approvalTokens();
  if (token) tokens[id] = token;
  else delete tokens[id];
  sessionStorage.setItem(APPROVAL_STORE_KEY, JSON.stringify(tokens));
}

function responseForStorage(data) {
  const safe = {...data};
  delete safe.approval_token;
  return safe;
}

function saveSessions() {
  sessions.sort((a, b) => b.updatedAt - a.updatedAt);
  sessions = sessions.slice(0, 20);
  localStorage.setItem(SESSION_STORE_KEY, JSON.stringify(sessions));
  renderSessions();
}

function sessionTitle(message) {
  const compact = message.replace(/\s+/g, ' ').trim();
  return compact.length > 48 ? `${compact.slice(0, 48)}…` : compact;
}

function saveSessionTurn(data) {
  let session = sessions.find((item) => item.id === data.thread_id);
  if (!session) {
    session = {id: data.thread_id, title: sessionTitle(originalSymptom), createdAt: Date.now(), updatedAt: Date.now(), turns: []};
    sessions.push(session);
  }
  session.updatedAt = Date.now();
  session.turns.push({request: originalSymptom, response: responseForStorage(data), createdAt: Date.now()});
  session.turns = session.turns.slice(-30);
  storeApprovalToken(session.id, data.approval_token || '');
  saveSessions();
}

function updateSessionResponse(data) {
  const session = sessions.find((item) => item.id === threadId);
  const turn = session?.turns.at(-1);
  if (!turn) return;
  turn.response = responseForStorage(data);
  session.updatedAt = Date.now();
  storeApprovalToken(session.id, data.approval_token || '');
  saveSessions();
}

function renderSessions() {
  const list = $('#session-list');
  const items = sessions.map((session) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `session-item${session.id === threadId ? ' active' : ''}`;
    const title = document.createElement('strong');
    title.textContent = session.title || 'Untitled incident';
    const meta = document.createElement('small');
    const count = session.turns.length;
    meta.textContent = `${count} ${count === 1 ? 'request' : 'requests'} · ${new Date(session.updatedAt).toLocaleDateString()}`;
    button.append(title, meta);
    button.addEventListener('click', () => activateSession(session.id));
    return button;
  });
  list.replaceChildren(...items);
  $('#session-empty').classList.toggle('hidden', items.length > 0);
}

function updateActiveSessionContext(session = null) {
  const context = $('#active-session-context');
  context.textContent = session
    ? `Using session context: ${session.title || 'Untitled incident'}`
    : 'New session · no previous context';
  context.classList.toggle('has-context', Boolean(session));
}

async function activateSession(id) {
  let session = sessions.find((item) => item.id === id);
  if (session?.serverBacked && !session.turns.length) {
    try {
      const detail = await request(`/sessions/${encodeURIComponent(id)}`);
      session.turns = detail.turns.map((turn) => ({
        request: turn.query,
        response: {thread_id: id, message: turn.response, status: turn.status, source: turn.source},
        createdAt: Date.parse(turn.created_at),
      }));
      saveSessions();
    } catch (_) { return; }
  }
  const turn = session?.turns.at(-1);
  if (!turn) return;
  threadId = session.id;
  originalSymptom = turn.request;
  messageInput.value = turn.request;
  messageInput.dispatchEvent(new Event('input'));
  updateActiveSessionContext(session);
  renderSessions();
  renderResult({...turn.response, approval_token: approvalTokens()[id] || ''});
  revealWorkspaceResponse();
}

function startNewSession() {
  threadId = null; approvalToken = ''; originalSymptom = ''; latestAnswer = '';
  messageInput.value = ''; messageInput.dispatchEvent(new Event('input'));
  logFileInput.value = ''; $('#log-file-status').textContent = '';
  $('#feedback-form').reset(); $('#operator-key-field').classList.add('hidden');
  result.classList.add('hidden'); feedback.classList.add('hidden'); approvalCard.classList.add('hidden');
  progress.classList.add('hidden'); responseEmpty.classList.remove('hidden');
  $('#generated-visual').classList.add('hidden'); $('#download-image').classList.add('hidden'); $('#response-action-status').textContent = '';
  updateActiveSessionContext();
  renderSessions(); setStep(1); messageInput.focus();
}

function revealWorkspaceResponse() {
  $('.response-pane').scrollTop = 0;
  window.requestAnimationFrame(() => {
    const top = Math.max(0, document.querySelector('.workspace').offsetTop - 72);
    const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    window.scrollTo({top, behavior});
  });
}

function loadPromptLibrary() {
  try {
    const saved = JSON.parse(localStorage.getItem(PROMPT_LIBRARY_KEY));
    if (Array.isArray(saved?.groups) && Array.isArray(saved?.tags) && saved.groups.length) return saved;
  } catch (_) { /* Invalid browser data is safely replaced with defaults. */ }
  return JSON.parse(JSON.stringify(DEFAULT_PROMPT_LIBRARY));
}

function savePromptLibrary() {
  localStorage.setItem(PROMPT_LIBRARY_KEY, JSON.stringify(promptLibrary));
  renderPromptLibrary();
  renderTagManager();
}

function renderPromptLibrary() {
  const sections = promptLibrary.groups.map((group) => {
    const tags = promptLibrary.tags.filter((tag) => tag.groupId === group.id);
    if (!tags.length) return null;
    const section = document.createElement('section');
    section.className = 'prompt-group';
    const heading = document.createElement('small');
    heading.textContent = group.name;
    const list = document.createElement('div');
    list.className = 'prompt-tags';
    tags.forEach((tag) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'prompt-tag';
      button.textContent = tag.label;
      button.title = tag.prompt;
      button.addEventListener('click', () => {
        document.querySelectorAll('.prompt-tag').forEach((item) => item.classList.remove('selected'));
        button.classList.add('selected');
        messageInput.value = tag.prompt;
        messageInput.dispatchEvent(new Event('input'));
        messageInput.focus();
      });
      list.append(button);
    });
    section.append(heading, list);
    return section;
  }).filter(Boolean);
  $('#prompt-groups').replaceChildren(...sections);
}

function resetTagForm() {
  $('#tag-form').reset();
  $('#tag-id').value = '';
  $('#cancel-tag-edit').classList.add('hidden');
}

function renderTagManager() {
  const select = $('#tag-group');
  const selected = select.value;
  select.replaceChildren(...promptLibrary.groups.map((group) => {
    const option = document.createElement('option');
    option.value = group.id;
    option.textContent = group.name;
    return option;
  }));
  if (promptLibrary.groups.some((group) => group.id === selected)) select.value = selected;
  const groups = promptLibrary.groups.map((group) => {
    const section = document.createElement('section');
    section.className = 'tag-manager-group';
    const header = document.createElement('div');
    const title = document.createElement('h4');
    title.textContent = group.name;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'tag-action danger-text';
    remove.textContent = 'Delete group';
    remove.disabled = promptLibrary.groups.length === 1;
    remove.addEventListener('click', () => deleteGroup(group.id));
    header.append(title, remove);
    section.append(header);
    promptLibrary.tags.filter((tag) => tag.groupId === group.id).forEach((tag) => {
      const row = document.createElement('div');
      row.className = 'tag-manager-row';
      const copy = document.createElement('div');
      const label = document.createElement('b');
      label.textContent = tag.label;
      const prompt = document.createElement('small');
      prompt.textContent = tag.prompt;
      copy.append(label, prompt);
      const actions = document.createElement('div');
      ['Edit', 'Delete'].forEach((action) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `tag-action${action === 'Delete' ? ' danger-text' : ''}`;
        button.textContent = action;
        button.addEventListener('click', () => action === 'Edit' ? editTag(tag.id) : deleteTag(tag.id));
        actions.append(button);
      });
      row.append(copy, actions);
      section.append(row);
    });
    return section;
  });
  $('#tag-manager-list').replaceChildren(...groups);
}

function editTag(id) {
  const tag = promptLibrary.tags.find((item) => item.id === id);
  if (!tag) return;
  $('#tag-id').value = tag.id;
  $('#tag-label').value = tag.label;
  $('#tag-prompt').value = tag.prompt;
  $('#tag-group').value = tag.groupId;
  $('#cancel-tag-edit').classList.remove('hidden');
  $('#tag-label').focus();
}

function deleteTag(id) {
  promptLibrary.tags = promptLibrary.tags.filter((tag) => tag.id !== id);
  savePromptLibrary();
}

function deleteGroup(id) {
  if (promptLibrary.groups.length === 1) return;
  const fallback = promptLibrary.groups.find((group) => group.id !== id);
  promptLibrary.tags.forEach((tag) => { if (tag.groupId === id) tag.groupId = fallback.id; });
  promptLibrary.groups = promptLibrary.groups.filter((group) => group.id !== id);
  resetTagForm();
  savePromptLibrary();
}

function setStep(number) {
  document.querySelectorAll('.step').forEach((step) => {
    step.classList.toggle('active', Number(step.dataset.step) <= number);
  });
}

function showError(message) {
  progress.classList.add('hidden');
  responseEmpty.classList.add('hidden');
  result.classList.remove('hidden');
  $('#result-icon').textContent = '!';
  $('#result-status').textContent = 'Unable to complete investigation';
  $('#result-message').textContent = message;
  approvalCard.classList.add('hidden');
}

function updateMessageCount() {
  const length = messageInput.value.length;
  $('#message-count').textContent = `${length.toLocaleString()} / 2000`;
  $('#message-count').classList.toggle('near-limit', length >= 1800);
  document.querySelectorAll('.prompt-tag.selected').forEach((tag) => {
    if (tag.title !== messageInput.value) tag.classList.remove('selected');
  });
}

messageInput.addEventListener('input', updateMessageCount);
messageInput.addEventListener('keydown', (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
    event.preventDefault();
    incidentForm.requestSubmit();
  }
});

async function request(url, options = {}) {
  const operatorKey = sessionStorage.getItem(OPERATOR_STORE_KEY);
  const response = await fetch(url, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(operatorKey ? {'X-Operator-Key': operatorKey} : {}), ...(options.headers || {})},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'The agent service returned an error.');
  return data;
}

async function syncServerSessions() {
  try {
    const data = await request('/sessions?limit=20');
    data.sessions.forEach((remote) => {
      if (sessions.some((item) => item.id === remote.thread_id)) return;
      sessions.push({
        id: remote.thread_id,
        title: remote.title,
        createdAt: Date.parse(remote.updated_at),
        updatedAt: Date.parse(remote.updated_at),
        turns: [],
        serverBacked: true,
      });
    });
    saveSessions();
  } catch (_) { /* Production sessions load after operator credentials are supplied. */ }
}

function renderResult(data) {
  progress.classList.add('hidden');
  responseEmpty.classList.add('hidden');
  result.classList.remove('hidden');
  $('#result-icon').textContent = data.status === 'approval_required' ? '!' : '✓';
  $('#result-status').textContent = data.status === 'security_blocked'
    ? 'Request blocked for safety'
    : data.status === 'out_of_scope'
    ? 'Outside this agent’s scope'
    : data.status === 'approval_required'
    ? 'Action needs your approval'
    : data.learned ? 'Answered from learned memory' : 'Investigation complete';
  latestAnswer = data.message || (data.status === 'approval_required' ? 'The agent found evidence that may require a service restart.' : 'The agent completed the workflow.');
  approvalToken = data.approval_token || '';
  const sourceNote = data.learned ? '\n\nLearned response · No AI or diagnostic tool call was needed.' : '';
  $('#result-message').textContent = latestAnswer + sourceNote;
  const usage = data.usage || {};
  $('#usage-model').textContent = usage.model || 'No AI call';
  $('#usage-input').textContent = Number(usage.input_tokens || 0).toLocaleString();
  $('#usage-output').textContent = Number(usage.output_tokens || 0).toLocaleString();
  $('#usage-cost').textContent = `$${Number(usage.estimated_cost_usd || 0).toFixed(6)}`;
  renderFlow(data.flow || []);
  if (data.pending_action) {
    const args = data.pending_action.args || {};
    $('#action-details').replaceChildren(
      detail('Service', args.service_name || 'Unknown'),
      detail('Reason', args.reason || 'No reason supplied')
    );
    $('#feedback-service').value = args.service_name || '';
    approvalCard.classList.remove('hidden');
    const canDecide = Boolean(approvalToken);
    $('#approve-button').disabled = !canDecide;
    $('#deny-button').disabled = !canDecide;
    $('.safety-note').textContent = canDecide
      ? 'Nothing will be changed unless you approve this action.'
      : 'This saved approval has expired. Submit the request again to create a new approval.';
    feedback.classList.add('hidden');
    setStep(2);
  } else {
    approvalCard.classList.add('hidden');
    feedback.classList.remove('hidden');
    feedback.open = false;
    $('#feedback-approved').checked = false;
    $('#operator-key-field').classList.add('hidden');
    $('#feedback-operator-key').value = '';
    $('#feedback-resolution').value = data.message || '';
    setStep(3);
  }
}

async function generateVisual(data) {
  const panel = $('#generated-visual');
  panel.classList.add('hidden');
  $('#visual-image').classList.add('hidden');
  $('#download-image').classList.add('hidden');
  $('#visual-error').classList.add('hidden');
  const promptRequestsVisual = /\b(diagram|image|visual|flowchart)\b/i.test(originalSymptom);
  if ((!$('#include-visual').checked && !promptRequestsVisual) || data.status !== 'completed') return;
  panel.classList.remove('hidden');
  $('#visual-loading').classList.remove('hidden');
  try {
    const visual = await request('/visuals', {method: 'POST', body: JSON.stringify({request: originalSymptom, answer: latestAnswer})});
    $('#visual-image').src = visual.image_url;
    $('#visual-image').classList.remove('hidden');
    $('#download-image').classList.remove('hidden');
    $('#visual-model').textContent = visual.model;
  } catch (error) {
    $('#visual-error').textContent = error.message;
    $('#visual-error').classList.remove('hidden');
  } finally {
    $('#visual-loading').classList.add('hidden');
  }
}

function responseDocument() {
  const flow = [...document.querySelectorAll('#flow-steps li')]
    .map((item, index) => `${index + 1}. ${item.textContent}`)
    .join('\n');
  return `OpsSentinel AI response\n\nRequest\n${originalSymptom}\n\nAnswer\n${latestAnswer}\n\nProcessing flow\n${flow}\n`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadText(text, filename) {
  const link = document.createElement('a');
  link.href = `data:text/plain;charset=utf-8,${encodeURIComponent(text)}`;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function showActionSuccess(button, message) {
  const status = $('#response-action-status');
  status.textContent = message;
  button.classList.add('action-success');
  window.setTimeout(() => {
    status.textContent = '';
    button.classList.remove('action-success');
  }, 1800);
}

function fallbackCopy(text) {
  const input = document.createElement('textarea');
  input.value = text;
  input.setAttribute('readonly', '');
  input.style.position = 'fixed';
  input.style.left = '-9999px';
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand('copy');
  input.remove();
  return copied;
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      // Some browsers deny clipboard permission; use the compatible fallback.
    }
  }
  return fallbackCopy(text);
}

$('#copy-response').addEventListener('click', async () => {
  const button = $('#copy-response');
  const status = $('#response-action-status');
  try {
    const copied = await copyText(responseDocument());
    if (!copied) throw new Error('copy failed');
    showActionSuccess(button, 'Copied');
  } catch (_) {
    status.textContent = 'Copy unavailable';
  }
});

$('#download-response').addEventListener('click', () => {
  downloadText(responseDocument(), `opssentinel-ai-response-${threadId || 'result'}.txt`);
  showActionSuccess($('#download-response'), 'Downloaded');
});

$('#download-image').addEventListener('click', async () => {
  const status = $('#response-action-status');
  try {
    const response = await fetch($('#visual-image').src);
    if (!response.ok) throw new Error('download failed');
    downloadBlob(await response.blob(), `opssentinel-ai-architecture-${threadId || 'visual'}.png`);
    status.textContent = 'Image downloaded';
  } catch (_) {
    status.textContent = 'Image download failed';
  }
});

function renderFlow(steps) {
  const list = $('#flow-steps');
  list.replaceChildren(...steps.map((step) => {
    const item = document.createElement('li');
    item.className = step.status || 'waiting';
    item.textContent = step.label;
    return item;
  }));
  $('#processing-details').classList.toggle('hidden', steps.length === 0);
}

function detail(label, value) {
  const wrapper = document.createDocumentFragment();
  const dt = document.createElement('dt');
  const dd = document.createElement('dd');
  dt.textContent = label;
  dd.textContent = value;
  wrapper.append(dt, dd);
  return wrapper;
}

$('#manage-tags').addEventListener('click', () => { resetTagForm(); renderTagManager(); $('#tag-manager').showModal(); });
$('#close-tag-manager').addEventListener('click', () => $('#tag-manager').close());
$('#cancel-tag-edit').addEventListener('click', resetTagForm);
$('#group-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const name = $('#group-name').value.trim();
  if (!name) return;
  promptLibrary.groups.push({id: newId('group'), name});
  event.target.reset();
  savePromptLibrary();
});
$('#tag-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const id = $('#tag-id').value;
  const values = {groupId: $('#tag-group').value, label: $('#tag-label').value.trim(), prompt: $('#tag-prompt').value.trim()};
  if (!values.label || !values.prompt || !values.groupId) return;
  const existing = promptLibrary.tags.find((tag) => tag.id === id);
  if (existing) Object.assign(existing, values);
  else promptLibrary.tags.push({id: newId('tag'), ...values});
  resetTagForm();
  savePromptLibrary();
});
renderPromptLibrary();
renderSessions();

incidentForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  originalSymptom = messageInput.value.trim();
  if (!originalSymptom) return;
  result.classList.add('hidden');
  feedback.classList.add('hidden');
  responseEmpty.classList.add('hidden');
  progress.classList.remove('hidden');
  $('#investigate-button').disabled = true;
  $('#investigate-label').textContent = 'Investigating…';
  setStep(2);
  try {
    const payload = {message: originalSymptom};
    if (threadId) payload.thread_id = threadId;
    const logFile = logFileInput.files[0];
    let endpoint = '/incidents';
    if (logFile) {
      if (logFile.size === 0) throw new Error('The selected log file is empty.');
      if (logFile.size > 100 * 1024) throw new Error('Log file must be 100 KB or smaller.');
      if (!/\.(log|txt|json)$/i.test(logFile.name)) throw new Error('Upload a .log, .txt, or .json file.');
      payload.filename = logFile.name;
      payload.content = await logFile.text();
      endpoint = '/incidents/log-analysis';
    }
    const data = await request(endpoint, {method: 'POST', body: JSON.stringify(payload)});
    threadId = data.thread_id;
    renderResult(data);
    saveSessionTurn(data);
    revealWorkspaceResponse();
    await generateVisual(data);
  } catch (error) {
    showError(error.message);
  } finally {
    $('#investigate-button').disabled = false;
    $('#investigate-label').textContent = 'Start investigation';
  }
});

async function decide(approved) {
  if (!threadId) return;
  $('#approve-button').disabled = true;
  $('#deny-button').disabled = true;
  try {
    const data = await request(`/incidents/${encodeURIComponent(threadId)}/approval`, {method: 'POST', body: JSON.stringify({approved, approval_token: approvalToken})});
    if (data.status === 'denied') {
      const denied = {...data, message: 'The restart was denied. No production change was made.'};
      renderResult(denied); updateSessionResponse(denied);
    } else { renderResult(data); updateSessionResponse(data); await generateVisual(data); }
  } catch (error) { showError(error.message); }
  finally { $('#approve-button').disabled = false; $('#deny-button').disabled = false; }
}

$('#approve-button').addEventListener('click', () => decide(true));
$('#deny-button').addEventListener('click', () => decide(false));
$('#new-incident').addEventListener('click', startNewSession);
$('#new-session').addEventListener('click', startNewSession);
$('#clear-sessions').addEventListener('click', () => {
  if (!window.confirm('Clear all incident history saved in this browser?')) return;
  sessions = [];
  localStorage.removeItem(SESSION_STORE_KEY);
  sessionStorage.removeItem(APPROVAL_STORE_KEY);
  startNewSession();
});
$('#operator-access').addEventListener('click', () => {
  $('#operator-access-key').value = sessionStorage.getItem(OPERATOR_STORE_KEY) || '';
  $('#operator-dialog').showModal();
});
$('#operator-form').addEventListener('submit', (event) => {
  if (event.submitter?.value === 'cancel') return;
  const key = $('#operator-access-key').value.trim();
  if (key) sessionStorage.setItem(OPERATOR_STORE_KEY, key);
  else sessionStorage.removeItem(OPERATOR_STORE_KEY);
  window.setTimeout(syncServerSessions, 0);
});
$('#feedback-approved').addEventListener('change', (event) => {
  $('#operator-key-field').classList.toggle('hidden', !event.target.checked);
  if (!event.target.checked) $('#feedback-operator-key').value = '';
});

logFileInput.addEventListener('change', () => {
  const file = logFileInput.files[0];
  const status = $('#log-file-status');
  status.classList.remove('error');
  if (!file) { status.textContent = ''; return; }
  if (file.size === 0) {
    status.textContent = 'The selected log file is empty.';
    status.classList.add('error');
    return;
  }
  if (file.size > 100 * 1024) {
    status.textContent = 'File is too large. Choose a file up to 100 KB.';
    status.classList.add('error');
    return;
  }
  status.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB selected`;
});

$('#feedback-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const status = $('#feedback-status');
  try {
    const approved = $('#feedback-approved').checked;
    const operatorKey = $('#feedback-operator-key').value;
    const data = await request('/feedback', {method: 'POST', headers: approved ? {'X-Operator-Key': operatorKey} : {}, body: JSON.stringify({
      service_name: $('#feedback-service').value,
      symptom: originalSymptom,
      resolution: $('#feedback-resolution').value,
      rating: Number($('#feedback-rating').value),
      operator_approved: approved,
    })});
    $('#feedback-operator-key').value = '';
    status.textContent = data.learned ? 'Saved. This reviewed lesson can help future investigations.' : 'Saved for review. It will not influence the agent yet.';
  } catch (error) { status.textContent = error.message; }
});

syncServerSessions();

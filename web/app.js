const $ = (selector) => document.querySelector(selector);
const incidentForm = $('#incident-form');
const messageInput = $('#incident-message');
const progress = $('#progress');
const result = $('#result');
const feedback = $('#feedback');
const approvalCard = $('#approval-card');
let threadId = null;
let originalSymptom = '';
let latestAnswer = '';

function setStep(number) {
  document.querySelectorAll('.step').forEach((step) => {
    step.classList.toggle('active', Number(step.dataset.step) <= number);
  });
}

function showError(message) {
  progress.classList.add('hidden');
  result.classList.remove('hidden');
  $('#result-icon').textContent = '!';
  $('#result-status').textContent = 'Unable to complete investigation';
  $('#result-message').textContent = message;
  approvalCard.classList.add('hidden');
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'The agent service returned an error.');
  return data;
}

function renderResult(data) {
  progress.classList.add('hidden');
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
    feedback.classList.add('hidden');
    setStep(2);
  } else {
    approvalCard.classList.add('hidden');
    feedback.classList.remove('hidden');
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
  return `SafeOps response\n\nRequest\n${originalSymptom}\n\nAnswer\n${latestAnswer}\n\nProcessing flow\n${flow}\n`;
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
  downloadText(responseDocument(), `safeops-response-${threadId || 'result'}.txt`);
  showActionSuccess($('#download-response'), 'Downloaded');
});

$('#download-image').addEventListener('click', async () => {
  const status = $('#response-action-status');
  try {
    const response = await fetch($('#visual-image').src);
    if (!response.ok) throw new Error('download failed');
    downloadBlob(await response.blob(), `safeops-architecture-${threadId || 'visual'}.png`);
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
  $('#answer-flow').classList.toggle('hidden', steps.length === 0);
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

document.querySelectorAll('[data-example]').forEach((button) => {
  button.addEventListener('click', () => { messageInput.value = button.dataset.example; messageInput.focus(); });
});

incidentForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  originalSymptom = messageInput.value.trim();
  if (!originalSymptom) return;
  result.classList.add('hidden');
  feedback.classList.add('hidden');
  progress.classList.remove('hidden');
  $('#investigate-button').disabled = true;
  setStep(2);
  try {
    const data = await request('/incidents', {method: 'POST', body: JSON.stringify({message: originalSymptom})});
    threadId = data.thread_id;
    renderResult(data);
    await generateVisual(data);
  } catch (error) {
    showError(`${error.message} Check that OPENAI_API_KEY is valid, then try again.`);
  } finally {
    $('#investigate-button').disabled = false;
  }
});

async function decide(approved) {
  if (!threadId) return;
  $('#approve-button').disabled = true;
  $('#deny-button').disabled = true;
  try {
    const data = await request(`/incidents/${encodeURIComponent(threadId)}/approval`, {method: 'POST', body: JSON.stringify({approved})});
    if (data.status === 'denied') {
      renderResult({...data, message: 'The restart was denied. No production change was made.'});
    } else { renderResult(data); await generateVisual(data); }
  } catch (error) { showError(error.message); }
  finally { $('#approve-button').disabled = false; $('#deny-button').disabled = false; }
}

$('#approve-button').addEventListener('click', () => decide(true));
$('#deny-button').addEventListener('click', () => decide(false));
$('#new-incident').addEventListener('click', () => {
  threadId = null; originalSymptom = ''; messageInput.value = '';
  result.classList.add('hidden'); feedback.classList.add('hidden'); approvalCard.classList.add('hidden'); $('#generated-visual').classList.add('hidden'); $('#download-image').classList.add('hidden'); $('#response-action-status').textContent = '';
  setStep(1); messageInput.focus();
});

$('#feedback-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const status = $('#feedback-status');
  try {
    const data = await request('/feedback', {method: 'POST', body: JSON.stringify({
      service_name: $('#feedback-service').value,
      symptom: originalSymptom,
      resolution: $('#feedback-resolution').value,
      rating: Number($('#feedback-rating').value),
      operator_approved: $('#feedback-approved').checked,
    })});
    status.textContent = data.learned ? 'Saved. This reviewed lesson can help future investigations.' : 'Saved for review. It will not influence the agent yet.';
  } catch (error) { status.textContent = error.message; }
});

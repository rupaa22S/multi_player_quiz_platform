const pageName = document.body.dataset.page;
const AUTH_EMAIL_KEY = 'quizblast_auth_email';
const NAME_STORAGE_KEY = 'quizblast_name';

function getQueryParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

function showToast(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || 'Request failed.');
  }
  return data;
}

async function copyTextToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  textarea.remove();
}

function getWebSocketUrl(roomCode, userId, userName, isAdmin) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const encodedName = encodeURIComponent(userName);
  return `${protocol}://${window.location.host}/ws/${roomCode}?user_id=${userId}&user_name=${encodedName}&is_admin=${isAdmin}`;
}

function makeRoomCode(code) {
  return code ? code.toUpperCase().trim() : '';
}

function getStoredEmail() {
  return localStorage.getItem(AUTH_EMAIL_KEY) || '';
}

function getStoredName() {
  return localStorage.getItem(NAME_STORAGE_KEY) || '';
}

function saveIdentity(name, email) {
  if (name) {
    localStorage.setItem(NAME_STORAGE_KEY, name);
  }
  if (email) {
    const normalized = email.trim().toLowerCase();
    localStorage.setItem(AUTH_EMAIL_KEY, normalized);
  }
}

function prefillIdentityInputs() {
  const savedName = getStoredName();

  const adminName = document.getElementById('admin-name');
  const playerName = document.getElementById('player-name');
  const signinEmail = document.getElementById('signin-email');

  if (adminName && savedName) adminName.value = savedName;
  if (playerName && savedName) playerName.value = savedName;
  if (signinEmail && getStoredEmail()) signinEmail.value = getStoredEmail();
}

function clearIdentity() {
  localStorage.removeItem(AUTH_EMAIL_KEY);
  localStorage.removeItem(NAME_STORAGE_KEY);
}

function updateAuthStatus() {
  const status = document.getElementById('auth-status');
  const signIn = document.getElementById('signin-link');
  const signOut = document.getElementById('signout-btn');
  const email = getStoredEmail();
  if (status) {
    status.textContent = email ? `Signed in: ${email}` : 'Not signed in';
  }
  if (signIn) {
    signIn.classList.toggle('hidden', !!email);
  }
  if (signOut) {
    signOut.classList.toggle('hidden', !email);
  }
}

function redirectToSignin() {
  if (window.location.pathname !== '/signin') {
    window.location.href = '/signin';
  }
}

function requireAuth() {
  if (pageName === 'signin') return true;
  if (!getStoredEmail()) {
    redirectToSignin();
    return false;
  }
  return true;
}

async function connectSocket(roomCode, userId, userName, isAdmin, onMessage) {
  const url = getWebSocketUrl(roomCode, userId, userName, isAdmin);
  const socket = new WebSocket(url);

  socket.addEventListener('open', () => {
    console.log('WS connected', roomCode, userName);
  });

  socket.addEventListener('message', (event) => {
    try {
      const payload = JSON.parse(event.data);
      onMessage(payload);
    } catch (error) {
      console.warn('Invalid WS payload', error);
    }
  });

  socket.addEventListener('close', () => {
    console.log('WS closed', roomCode);
  });

  return socket;
}

function sanitizeText(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function buildUserItem(user, onKick) {
  const li = document.createElement('li');
  li.className = 'user-item';
  li.innerHTML = `
    <div class="name"><span class="avatar">${sanitizeText(user.name[0] || '?')}</span><strong>${sanitizeText(user.name)}</strong></div>
    <div class="flex gap-1"><span class="text-muted">${user.is_admin ? 'Admin' : 'Player'}</span></div>
  `;

  if (!user.is_admin) {
    const button = document.createElement('button');
    button.className = 'btn btn-outline btn-sm';
    button.textContent = 'Kick';
    button.addEventListener('click', () => onKick(user));
    li.querySelector('.flex').appendChild(button);
  }

  return li;
}

function renderLeaderboard(leaderboard, currentUserId, options = {}) {
  const list = document.getElementById('leaderboard-list');
  if (!list) return;
  const adminMode = Boolean(options.adminMode);

  list.innerHTML = leaderboard.map((entry, index) => {
    const isCurrentUser = entry.is_you || entry.user_id === Number(currentUserId);

    if (!adminMode) {
      return `
        <li class="lb-item ${isCurrentUser ? 'is-you' : ''}">
          <div class="lb-rank">${index + 1}</div>
          <div class="lb-name">${sanitizeText(entry.name)}</div>
          <div class="lb-score">${entry.score}</div>
        </li>
      `;
    }

    return `
      <li class="lb-item admin-lb-item ${isCurrentUser ? 'is-you' : ''}" data-user-id="${entry.user_id}">
        <div class="lb-main-row">
          <div class="lb-rank">${index + 1}</div>
          <div class="lb-name">${sanitizeText(entry.name)}</div>
          <div class="lb-score">${entry.score}</div>
          <button type="button" class="submission-toggle leaderboard-toggle" aria-expanded="false" aria-label="Show submitted answers"><span class="accordion-arrow">v</span></button>
        </div>
        <div class="submission-breakdown hidden"></div>
      </li>
    `;
  }).join('');

  if (!adminMode) return;

  list.querySelectorAll('.leaderboard-toggle').forEach((button) => {
    button.addEventListener('click', async () => {
      const item = button.closest('.lb-item');
      const breakdown = item?.querySelector('.submission-breakdown');
      if (!item || !breakdown) return;

      const userId = Number(item.dataset.userId);
      const open = !breakdown.classList.contains('hidden');

      if (open) {
        breakdown.classList.add('hidden');
        button.setAttribute('aria-expanded', 'false');
        return;
      }

      breakdown.classList.remove('hidden');
      button.setAttribute('aria-expanded', 'true');

      if (typeof options.onToggle === 'function') {
        await options.onToggle(userId, breakdown);
      }
    });
  });
}

function setButtonLoading(button, loading, label) {
  if (!button) return;

  if (loading) {
    if (!button.dataset.originalHtml) {
      button.dataset.originalHtml = button.innerHTML;
    }
    button.disabled = true;
    button.classList.add('btn-loading');
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${sanitizeText(label)}</span>`;
    return;
  }

  button.disabled = false;
  button.classList.remove('btn-loading');
  if (button.dataset.originalHtml) {
    button.innerHTML = button.dataset.originalHtml;
    delete button.dataset.originalHtml;
  }
}

async function setupHomePage() {
  const createForm = document.getElementById('create-room-form');
  const createButton = document.getElementById('create-room-btn');
  const joinForm = document.getElementById('join-room-form');
  if (!requireAuth()) return;
  prefillIdentityInputs();
  updateAuthStatus();

  createForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const adminName = document.getElementById('admin-name').value.trim();
    const authEmail = getStoredEmail();
    const quizTopic = document.getElementById('quiz-topic').value.trim();
    const difficulty = document.getElementById('difficulty').value;
    const questionType = document.getElementById('question-type').value;
    const numQuestions = Number(document.getElementById('num-questions').value);

    if (!adminName || !authEmail) {
      showToast('Please sign in first.', 'error');
      return;
    }

    setButtonLoading(createButton, true, 'Generating questions...');

    try {
      const response = await fetchJson('/create-room', {
        method: 'POST',
        body: JSON.stringify({
          admin_name: adminName,
          auth_email: authEmail,
          quiz_topic: quizTopic,
          difficulty,
          num_questions: numQuestions,
          question_type: questionType,
        }),
      });
      saveIdentity(adminName, authEmail);
      const query = new URLSearchParams({ room_code: response.room_code, user_id: response.admin_id, user_name: response.admin_name });
      window.location.href = `/admin?${query.toString()}`;
    } catch (error) {
      showToast(error.message, 'error');
      setButtonLoading(createButton, false);
    }
  });

  joinForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = document.getElementById('player-name').value.trim();
    const authEmail = getStoredEmail();
    const roomCode = makeRoomCode(document.getElementById('join-room-code').value);

    if (!name || !authEmail || !roomCode) {
      showToast('Please sign in and enter your name plus room code.', 'error');
      return;
    }

    try {
      const response = await fetchJson('/join-room', {
        method: 'POST',
        body: JSON.stringify({ name, auth_email: authEmail, room_code: roomCode }),
      });
      saveIdentity(name, authEmail);
      const query = new URLSearchParams({ room_code: response.room_code, user_id: response.user_id, user_name: response.user_name });
      window.location.href = `/quiz?${query.toString()}`;
    } catch (error) {
      showToast(error.message, 'error');
    }
  });
}

async function setupAdminPage() {
  const roomCode = makeRoomCode(getQueryParam('room_code'));
  const adminId = getQueryParam('user_id');
  const adminName = getQueryParam('user_name');

  if (!requireAuth() || !roomCode || !adminId || !adminName) {
    showToast('Missing admin session. Please create a room again.', 'error');
    setTimeout(() => window.location.href = '/', 1400);
    return;
  }

  const statusBadge = document.getElementById('room-status-badge');
  const adminCode = document.getElementById('admin-room-code');
  const userList = document.getElementById('users-list');
  const startButton = document.getElementById('start-quiz-btn');
  const endButton = document.getElementById('end-quiz-btn');
  const questionsSection = document.getElementById('questions-section');
  const adminQuestionsList = document.getElementById('admin-questions-list');
  const leaderboardSection = document.getElementById('leaderboard-section');
  const leaderboardNote = document.getElementById('leaderboard-note');
  const expandedSubmissionUsers = new Set();
  const submissionCache = new Map();

  adminCode.textContent = roomCode;
  adminCode.title = 'Click to copy room code';
  adminCode.addEventListener('click', async () => {
    try {
      await copyTextToClipboard(roomCode);
      showToast('Room code copied!', 'success');
    } catch (error) {
      showToast('Could not copy room code.', 'error');
    }
  });

  async function loadSubmissionBreakdown(userId, container) {
    if (!container) return;

    if (submissionCache.has(userId)) {
      renderAnswerBreakdown(submissionCache.get(userId), container);
      return;
    }

    container.innerHTML = '<div class="text-muted">Loading submitted answers...</div>';

    try {
      const data = await fetchJson(`/admin/user-results/${roomCode}/${userId}?admin_id=${encodeURIComponent(adminId)}`);
      const results = data.question_results || [];
      submissionCache.set(userId, results);
      renderAnswerBreakdown(results, container);
    } catch (error) {
      container.innerHTML = `<div class="text-red">Could not load submitted answers: ${sanitizeText(error.message)}</div>`;
    }
  }

  async function loadLeaderboard() {
    try {
      const data = await fetchJson(`/leaderboard/${roomCode}`);
      renderLeaderboard(data.leaderboard || [], adminId, {
        adminMode: true,
        onToggle: loadSubmissionBreakdown,
      });
      leaderboardSection.classList.remove('hidden');
      leaderboardNote.textContent = 'Final leaderboard after quiz end.';
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  function buildUserRow(user, statusLabel, statusClass) {
    const submitted = user.submission_status === 'submitted';
    const row = document.createElement('li');
    row.className = 'user-item admin-user-item';
    row.dataset.userId = user.id;

    row.innerHTML = `
      <div class="user-row-main">
        <div class="name">
          <span class="avatar">${sanitizeText(user.name[0] || '?')}</span>
          <strong>${sanitizeText(user.name)}</strong>
        </div>
        <div class="user-meta">
          <span class="text-muted">${user.is_admin ? 'Admin' : 'Player'}</span>
          ${user.email ? `<span class="user-email">${sanitizeText(user.email)}</span>` : ''}
          ${!user.is_admin ? `<span class="badge ${statusClass}">${statusLabel}</span>` : ''}
        </div>
      </div>
      ${!user.is_admin ? `
        <div class="user-row-actions">
          ${submitted ? `
            <button type="button" class="submission-toggle" aria-expanded="false" aria-label="Show submitted answers"><span class="accordion-arrow">v</span></button>
          ` : ''}
          <button type="button" class="btn btn-outline btn-sm kick-btn">Kick</button>
        </div>
      ` : ''}
      ${submitted ? `<div class="submission-breakdown hidden"></div>` : ''}
    `;

    if (!user.is_admin) {
      const kickButton = row.querySelector('.kick-btn');
      if (kickButton) {
        kickButton.addEventListener('click', () => removePlayer(user.id));
      }

      const toggleButton = row.querySelector('.submission-toggle');
      const breakdown = row.querySelector('.submission-breakdown');
      if (toggleButton && breakdown) {
        const isOpen = expandedSubmissionUsers.has(user.id);
        if (isOpen) {
          breakdown.classList.remove('hidden');
          toggleButton.setAttribute('aria-expanded', 'true');
          loadSubmissionBreakdown(user.id, breakdown);
        }

        toggleButton.addEventListener('click', async () => {
          const open = !breakdown.classList.contains('hidden');
          if (open) {
            breakdown.classList.add('hidden');
            toggleButton.setAttribute('aria-expanded', 'false');
            expandedSubmissionUsers.delete(user.id);
            return;
          }

          breakdown.classList.remove('hidden');
          toggleButton.setAttribute('aria-expanded', 'true');
          expandedSubmissionUsers.add(user.id);
          await loadSubmissionBreakdown(user.id, breakdown);
        });
      }
    }

    return row;
  }

  async function refreshRoomInfo() {
    try {
      const data = await fetchJson(`/room-info/${roomCode}`);
      statusBadge.textContent = data.status.toUpperCase();
      statusBadge.className = `badge badge-${data.status === 'started' ? 'green' : data.status === 'closed' ? 'red' : 'pink'}`;
      document.getElementById('player-count').textContent = data.users.filter((item) => !item.is_admin).length;
      document.getElementById('quiz-status').textContent = data.status === 'started' ? 'Live' : data.status === 'closed' ? 'Closed' : 'Waiting';
      startButton.disabled = data.status !== 'waiting';
      endButton.disabled = data.status === 'closed';
      userList.innerHTML = '';

      data.users.forEach((user) => {
        const statusLabel = user.submission_status === 'submitted' ? 'Submitted' : 'Taking';
        const statusClass = user.submission_status === 'submitted' ? 'badge-green' : 'badge-muted';
        userList.appendChild(buildUserRow(user, statusLabel, statusClass));
      });

      if (data.status === 'closed') {
        await loadLeaderboard();
      } else {
        leaderboardSection.classList.add('hidden');
      }
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  async function loadAdminQuestions() {
    if (!questionsSection || !adminQuestionsList) return;

    try {
      const data = await fetchJson(`/admin/questions/${roomCode}?admin_id=${encodeURIComponent(adminId)}`);
      questionsSection.classList.remove('hidden');
      adminQuestionsList.innerHTML = data.questions.map((question, index) => renderAdminQuestionItem(question, index)).join('');
    } catch (error) {
      questionsSection.classList.add('hidden');
      adminQuestionsList.innerHTML = '';
      showToast(error.message, 'error');
    }
  }

  async function removePlayer(userId) {
    try {
      await fetchJson(`/remove-user/${userId}?admin_id=${encodeURIComponent(adminId)}`, { method: 'DELETE' });
      showToast('Player removed.', 'success');
      await refreshRoomInfo();
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  async function startQuiz() {
    try {
      await fetchJson('/start-quiz', {
        method: 'POST',
        body: JSON.stringify({ room_code: roomCode, admin_id: Number(adminId) }),
      });
      showToast('Quiz started!', 'success');
      await refreshRoomInfo();
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  async function endQuiz() {
    try {
      const response = await fetchJson('/end-quiz', {
        method: 'POST',
        body: JSON.stringify({ room_code: roomCode, admin_id: Number(adminId) }),
      });
      showToast('Quiz ended.', 'success');
      await loadLeaderboard();
      await refreshRoomInfo();
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  startButton?.addEventListener('click', startQuiz);
  endButton?.addEventListener('click', endQuiz);

  function handleSocketEvent(payload) {
    if (payload.event === 'user_joined' || payload.event === 'user_left' || payload.event === 'user_submitted') {
      if (payload.event === 'user_submitted') {
        showToast(`${sanitizeText(payload.user_name)} has submitted their answers.`, 'info');
      }
      refreshRoomInfo();
    }
    if (payload.event === 'quiz_ended') {
      loadLeaderboard();
      statusBadge.textContent = 'CLOSED';
      statusBadge.className = 'badge badge-red';
    }
    if (payload.event === 'quiz_started') {
      statusBadge.textContent = 'STARTED';
      statusBadge.className = 'badge badge-green';
      showToast('Quiz started and participants are live.', 'success');
    }
  }

  await refreshRoomInfo();
  await loadAdminQuestions();
  connectSocket(roomCode, Number(adminId), adminName, true, handleSocketEvent).catch(() => {
    showToast('Unable to connect real-time updates.', 'error');
  });
}

async function setupQuizPage() {
  const roomCode = makeRoomCode(getQueryParam('room_code'));
  const userId = getQueryParam('user_id');
  const userName = getQueryParam('user_name');
  const authEmail = getStoredEmail();
  const waitingSection = document.getElementById('waiting-screen');
  const quizSection = document.getElementById('quiz-screen');
  const questionList = document.getElementById('questions-list');
  const submitButton = document.getElementById('submit-answers-btn');
  const roomLabel = document.getElementById('quiz-room-code');
  const statusNote = document.getElementById('quiz-status-note');

  if (!requireAuth() || !roomCode || !userId || !userName || !authEmail) {
    showToast('Missing quiz session. Please join again.', 'error');
    setTimeout(() => window.location.href = '/', 1400);
    return;
  }

  roomLabel.textContent = roomCode;

  let currentQuestions = [];
  let submitted = false;

  function renderQuestions(questions) {
    currentQuestions = questions;
    questionList.innerHTML = '';

    questions.forEach((question, index) => {
      const card = document.createElement('div');
      card.className = 'question-card';
      card.innerHTML = `
        <div class="question-number">Question ${index + 1}</div>
        <div class="question-text">${sanitizeText(question.question_text)}</div>
      `;

      if (question.type === 'mcq') {
        const options = document.createElement('div');
        options.className = 'options';

        question.options.forEach((option, optionIndex) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'option-btn';
          button.dataset.value = option;
          button.innerHTML = `
            <span class="option-letter">${String.fromCharCode(65 + optionIndex)}</span>
            <span>${sanitizeText(option)}</span>
          `;
          button.addEventListener('click', () => {
            card.querySelectorAll('.option-btn').forEach((btn) => btn.classList.remove('selected'));
            button.classList.add('selected');
          });
          options.appendChild(button);
        });

        card.appendChild(options);
      } else {
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'blank-input';
        input.placeholder = 'Type your answer here';
        input.dataset.questionId = question.id;
        card.appendChild(input);
      }

      questionList.appendChild(card);
    });

    waitingSection.classList.add('hidden');
    quizSection.classList.remove('hidden');
  }

  async function loadQuestions() {
    try {
      const data = await fetchJson(`/questions/${roomCode}`);
      renderQuestions(data.questions);
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  async function submitAnswers() {
    if (submitted) return;
    const answers = [];
    currentQuestions.forEach((question, index) => {
      const card = questionList.children[index];
      if (!card) return;
      if (question.type === 'mcq') {
        const selected = card.querySelector('.option-btn.selected');
        answers.push({ question_id: question.id, answer: selected ? selected.dataset.value.trim() : '' });
      } else {
        const field = card.querySelector('.blank-input');
        answers.push({ question_id: question.id, answer: field ? field.value.trim() : '' });
      }
    });

    try {
      const result = await fetchJson('/submit-answer', {
        method: 'POST',
        body: JSON.stringify({ room_code: roomCode, user_id: Number(userId), answers }),
      });
      showToast(result.message || 'Submitted! Waiting for the quiz to end.', 'success');
      submitted = true;
      submitButton.disabled = true;
      document.getElementById('quiz-screen').classList.add('hidden');
      document.getElementById('submitted-screen').classList.remove('hidden');
      statusNote.textContent = 'Answers submitted. The admin will reveal results when the quiz ends.';
    } catch (error) {
      showToast(error.message, 'error');
    }
  }

  function handleSocketEvent(payload) {
    if (payload.event === 'quiz_started') {
      renderQuestions(payload.questions);
      statusNote.textContent = 'Quiz is live! Answer all questions and submit when done.';
    }
    if (payload.event === 'kicked') {
      showToast(payload.message || 'You have been removed from the room.', 'error');
      setTimeout(() => window.location.href = '/', 1400);
    }
    if (payload.event === 'quiz_ended') {
      showToast('Quiz ended. Viewing results...', 'info');
      const query = new URLSearchParams({ room_code: roomCode, user_id: userId, user_name: userName });
      setTimeout(() => window.location.href = `/result?${query.toString()}`, 1200);
    }
  }

  submitButton?.addEventListener('click', submitAnswers);

  await connectSocket(roomCode, Number(userId), userName, false, handleSocketEvent).catch(() => {
    showToast('Unable to connect to real-time server.', 'error');
  });

  try {
    const roomInfo = await fetchJson(`/room-info/${roomCode}`);
    if (roomInfo.status === 'started') {
      await loadQuestions();
    } else {
      statusNote.textContent = 'Waiting for the admin to start the quiz...';
    }
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function setupResultPage() {
  const roomCode = makeRoomCode(getQueryParam('room_code'));
  const userId = getQueryParam('user_id');
  const userName = getQueryParam('user_name') || getStoredName();
  const userEmail = getStoredEmail();

  if (!requireAuth() || !roomCode || !userId) {
    showToast('Missing result session. Please join again.', 'error');
    setTimeout(() => window.location.href = '/', 1400);
    return;
  }

  const scoreCard = document.getElementById('user-score');
  const userNameLabel = document.getElementById('result-user-name');
  const roomLabel = document.getElementById('result-room-code');

  try {
    const data = await fetchJson(`/results/${roomCode}/${Number(userId)}`);
    if (userNameLabel) {
      userNameLabel.textContent = sanitizeText(data.user_name);
    }
    scoreCard.textContent = `${data.score}`;
    roomLabel.textContent = roomCode;
    renderLeaderboard(data.leaderboard, userId);
    renderAnswerBreakdown(data.question_results || []);
    loadHistory(userEmail || data.user_email);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function renderAnswerBreakdown(questionResults, containerOrId = 'answer-breakdown') {
  const container = typeof containerOrId === 'string'
    ? document.getElementById(containerOrId)
    : containerOrId;
  if (!container) return;

  if (!questionResults.length) {
    container.innerHTML = '<div class="text-muted">No answers to display.</div>';
    return;
  }

  container.innerHTML = questionResults.map((result, index) => {
    const questionNumber = result.question_number || (index + 1);
    const normalizedUserAnswer = String(result.user_answer || '').trim().toLowerCase();
    const normalizedCorrectAnswer = String(result.correct_answer || '').trim().toLowerCase();
    const statusLabel = result.is_correct ? 'Correct' : 'Wrong';
    const optionHtml = result.type === 'mcq'
      ? `<div class="answer-options">
          ${(result.options || []).map((option, optionIndex) => {
            const normalizedOption = String(option || '').trim().toLowerCase();
            const isCorrect = normalizedOption === normalizedCorrectAnswer;
            const isPicked = normalizedOption === normalizedUserAnswer;
            const classes = ['answer-option'];
            if (isCorrect) classes.push('correct');
            if (isPicked && !isCorrect) classes.push('picked-wrong');
            return `
              <div class="${classes.join(' ')}">
                <span class="option-letter">${String.fromCharCode(65 + optionIndex)}</span>
                <span class="option-text">${sanitizeText(option)}</span>
                ${isCorrect ? '<span class="option-tag">Correct</span>' : ''}
                ${isPicked && !isCorrect ? '<span class="option-tag wrong">Your answer</span>' : ''}
              </div>
            `;
          }).join('')}
        </div>`
      : `<div class="blank-answer">
          <div><span class="text-muted">Your answer:</span> <strong>${sanitizeText(result.user_answer || '—')}</strong></div>
          <div><span class="text-muted">Correct answer:</span> <strong class="text-green">${sanitizeText(result.correct_answer)}</strong></div>
        </div>`;

    return `
      <div class="answer-row ${result.is_correct ? 'correct-row' : 'wrong-row'}">
        <div>
          <p class="answer-meta">Q${questionNumber} · ${result.type === 'mcq' ? 'MCQ' : 'Fill-in-the-blank'}</p>
          <p class="answer-question">${sanitizeText(result.question_text)}</p>
          ${optionHtml}
          <p class="answer-summary">
            <span class="text-muted">Status:</span>
            <strong class="${result.is_correct ? 'text-green' : 'text-red'}">${statusLabel}</strong>
          </p>
          <p class="answer-summary">
            <span class="text-muted">Your answer:</span>
            <strong class="${result.is_correct ? 'text-green' : 'text-red'}">${sanitizeText(result.user_answer || '—')}</strong>
          </p>
          <p class="answer-summary">
            <span class="text-muted">Correct answer:</span>
            <strong class="text-green">${sanitizeText(result.correct_answer)}</strong>
          </p>
        </div>
        <span class="answer-icon">${result.is_correct ? '✅' : '❌'}</span>
      </div>
    `;
  }).join('');
}

function renderAdminQuestionItem(question, index) {
  const optionsHtml = question.type === 'mcq'
    ? `<div class="admin-option-list">
        ${(question.options || []).map((option, optionIndex) => `
          <div class="admin-option">
            <span class="option-letter">${String.fromCharCode(65 + optionIndex)}</span>
            <span class="option-text">${sanitizeText(option)}</span>
          </div>
        `).join('')}
      </div>`
    : `<div class="admin-option">
        <span class="option-letter">A</span>
        <span class="option-text">${sanitizeText(question.correct_answer)}</span>
      </div>`;

  return `
    <details class="accordion-item">
      <summary class="accordion-summary">
        <div>
          <div class="accordion-title">Q${index + 1} · ${question.type === 'mcq' ? 'MCQ' : 'Fill-in-the-blank'}</div>
          <div class="accordion-question">${sanitizeText(question.question_text)}</div>
        </div>
        <span class="accordion-arrow">v</span>
      </summary>
      <div class="accordion-body">
        ${optionsHtml}
        <div class="admin-answer">
          <span class="text-muted">Correct answer:</span>
          <strong class="text-green">${sanitizeText(question.correct_answer)}</strong>
        </div>
      </div>
    </details>
  `;
}

async function loadHistory(email) {
  const historyList = document.getElementById('history-list');
  const historyNote = document.getElementById('history-note');
  if (!historyList || !email) return;

  try {
    const data = await fetchJson(`/history?email=${encodeURIComponent(email)}`);
    if (historyNote) {
      historyNote.textContent = `History for ${data.email}`;
    }

    if (!data.history.length) {
      historyList.innerHTML = '<li class="history-item">No previous quiz history found for this email.</li>';
      return;
    }

    historyList.innerHTML = data.history.map((entry) => `
      <li class="history-item">
        <div>
          <div class="history-title">${sanitizeText(entry.quiz_topic)}</div>
          <div class="history-meta">
            ${sanitizeText(entry.room_code)} · ${sanitizeText(entry.difficulty)} · ${sanitizeText(entry.status)}
          </div>
        </div>
        <div class="history-score">${entry.score}/${entry.total_questions}</div>
      </li>
    `).join('');
  } catch (error) {
    if (historyNote) historyNote.textContent = error.message;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  if (pageName !== 'signin' && !getStoredEmail()) {
    redirectToSignin();
    return;
  }

  prefillIdentityInputs();
  updateAuthStatus();

  const signOutButton = document.getElementById('signout-btn');
  if (signOutButton) {
    signOutButton.addEventListener('click', () => {
      clearIdentity();
      window.location.href = '/signin';
    });
  }

  if (pageName === 'signin') setupSigninPage();
  if (pageName === 'home') setupHomePage();
  if (pageName === 'admin') setupAdminPage();
  if (pageName === 'quiz') setupQuizPage();
  if (pageName === 'result') setupResultPage();
});

async function setupSigninPage() {
  const form = document.getElementById('signin-form');
  const emailInput = document.getElementById('signin-email');
  const passwordInput = document.getElementById('signin-password');

  if (getStoredEmail()) {
    window.location.href = '/';
    return;
  }

  if (emailInput && !emailInput.value) {
    emailInput.focus();
  } else if (passwordInput) {
    passwordInput.focus();
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = emailInput.value.trim().toLowerCase();
    const password = passwordInput.value;

    if (!email || !password) {
      showToast('Please enter email and password.', 'error');
      return;
    }

    try {
      const data = await fetchJson('/auth/signin', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      saveIdentity('', data.email);
      updateAuthStatus();
      showToast(data.created ? 'Account created and signed in.' : 'Signed in successfully.', 'success');
      setTimeout(() => {
        window.location.href = '/';
      }, 100);
    } catch (error) {
      showToast(error.message, 'error');
    }
  });
}

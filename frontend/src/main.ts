import { confetti, replayClass, setSoundEnabled, sound, soundEnabled, toast, unlockAudio } from './fx';

type Stats = { best: number; correct: number; total: number; completedRuns: number; average: number | null };
type Profile = { authenticated: boolean; userId: number | null; login: string | null; displayName: string; avatar: string; stats: Stats };
type Card = { roundId: number; options: [string, string]; deadline: string; serverNow: string; streak: number };
type Answer = { correct: boolean; timedOut: boolean; correctSide: 'A' | 'B'; explanation: string; streak: number; gameOver: boolean; stats: Stats };
type Rank = { userId: number; name: string; avatar: string; best: number; average: number | null };

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const basePath = import.meta.env.BASE_URL.replace(/\/$/, '');
const defaultStats: Stats = { best: 0, correct: 0, total: 0, completedRuns: 0, average: null };
let profile: Profile = { authenticated: false, userId: null, login: null, displayName: 'Гость', avatar: 'preset:cat', stats: defaultStats };
let card: Card | null = null;
let resolved = false;
let gameOver = false;
let timerId: number | null = null;
let activePage = 'play';
let metric = 'streak';
let period = 'today';
let authMode: 'register' | 'login' = 'register';
let questionCount = 0;
// Best streak before the current run; `recordBroken` flips once the run passes it.
let recordToBeat: number | null = null;
let recordBroken = false;
let lastTickSecond = 0;
// Server clock minus device clock: the deadline is server time, so a skewed device clock must not shift the timer.
let clockOffset = 0;
const roundSeconds = 15;
const defaultHint = 'Выбери карточку за 15 секунд · или нажми 1 / 2';
const presetIcons: Record<string, string> = {
  cat: '🐈', fox: '🦊', owl: '🦉', frog: '🐸', bear: '🐻', star: '⭐', panda: '🐼', koala: '🐨', tiger: '🐯',
  penguin: '🐧', rabbit: '🐰', hedgehog: '🦔', octopus: '🐙', unicorn: '🦄', dragon: '🐉', robot: '🤖', alien: '👽', rocket: '🚀',
};
const presetNames: Record<string, string> = {
  cat: 'кот', fox: 'лиса', owl: 'сова', frog: 'лягушка', bear: 'медведь', star: 'звезда', panda: 'панда', koala: 'коала', tiger: 'тигр',
  penguin: 'пингвин', rabbit: 'кролик', hedgehog: 'ёжик', octopus: 'осьминог', unicorn: 'единорог', dragon: 'дракон', robot: 'робот', alien: 'пришелец', rocket: 'ракета',
};
const guestCacheKey = 'factish_guest_stats_v1';

async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const method = init.method || 'GET';
  const headers = new Headers(init.headers);
  if (method !== 'GET') headers.set('X-Factish-Request', '1');
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${basePath}/api${path}`, { ...init, headers, credentials: 'same-origin' });
  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    try { await api('/auth/refresh', { method: 'POST' }, false); return api(path, init, false); } catch { /* Guest or expired login. */ }
  }
  if (!response.ok) {
    let message = 'Не удалось выполнить запрос';
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : message; } catch { /* Empty response. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function saveGuestStats() {
  if (!profile.authenticated) {
    try { localStorage.setItem(guestCacheKey, JSON.stringify(profile.stats)); } catch { /* Storage unavailable. */ }
  } else {
    try { localStorage.removeItem(guestCacheKey); } catch { /* Storage unavailable. */ }
  }
}

function avatar(target: HTMLElement, value: string) {
  target.replaceChildren();
  if (value.startsWith('/avatars/')) {
    const img = document.createElement('img');
    img.src = `${basePath}${value}`;
    img.alt = '';
    target.append(img);
  } else target.textContent = presetIcons[value.replace('preset:', '')] || presetIcons.cat;
}

function renderProfile() {
  $('profileDisplayName').textContent = profile.displayName;
  avatar($('profileAvatar'), profile.avatar);
  avatar($('headerAvatar'), profile.avatar);
  $('statBest').textContent = String(profile.stats.best);
  $('statCorrect').textContent = String(profile.stats.correct);
  $('statAccuracy').textContent = profile.stats.total ? `${Math.round(profile.stats.correct / profile.stats.total * 100)}%` : '—';
  $<HTMLInputElement>('nicknameInput').value = profile.displayName;
  $<HTMLInputElement>('nicknameInput').disabled = !profile.authenticated;
  $<HTMLButtonElement>('saveName').disabled = !profile.authenticated;
  $('authPanel').hidden = profile.authenticated;
  $('avatarSettings').hidden = !profile.authenticated;
  $('logoutButton').hidden = !profile.authenticated;
  $('profileSaved').textContent = profile.authenticated ? `Аккаунт: ${profile.login}` : 'Гостевой результат сохраняется в этом браузере. Зарегистрируйся, чтобы попасть в рейтинг.';
  document.querySelectorAll<HTMLButtonElement>('#avatarPresets button').forEach(button => button.classList.toggle('selected', profile.avatar === `preset:${button.dataset.preset}`));
  saveGuestStats();
}

function setTheme(value: string) {
  document.documentElement.dataset.theme = value;
  $('themeToggle').setAttribute('aria-label', value === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему');
  $('themeIcon').innerHTML = value === 'dark'
    ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
    : '<path d="M20.2 15.6A8.7 8.7 0 0 1 8.4 3.8 8.8 8.8 0 1 0 20.2 15.6Z"/>';
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')!.content = value === 'dark' ? '#11151e' : '#fafaf7';
  try { localStorage.setItem('factish_theme_v1', value); } catch { /* Storage unavailable. */ }
}

function renderSoundToggle() {
  const on = soundEnabled();
  $('soundToggle').setAttribute('aria-pressed', String(on));
  $('soundToggle').setAttribute('aria-label', on ? 'Выключить звук и вибрацию' : 'Включить звук и вибрацию');
  $('soundIcon').innerHTML = on
    ? '<path d="M4 9h4l5-4v14l-5-4H4Z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/>'
    : '<path d="M4 9h4l5-4v14l-5-4H4Z"/><path d="m17 9 5 6m0-6-5 6"/>';
}

function setTier(streak: number) {
  document.body.dataset.tier = streak >= 20 ? '3' : streak >= 10 ? '2' : streak >= 5 ? '1' : '0';
}

function setHint(text: string, hot = false) {
  $('playHint').textContent = text;
  $('playHint').classList.toggle('hot', hot);
}

function streakHint(streak: number) {
  if (recordBroken) return setHint('🏆 Ты на новом рекорде — каждый ответ поднимает его выше', true);
  const need = (recordToBeat ?? 0) + 1 - streak;
  if (recordToBeat && need === 1) return setHint('🔥 Ещё один верный — и новый рекорд!', true);
  if (recordToBeat && need === 2) return setHint('Ещё 2 верных — и новый рекорд', true);
  setHint(defaultHint);
}

function milestoneText(streak: number) {
  if (streak === 5) return '🔥 Огненная серия!';
  if (streak === 10) return '⚡ Десятка без промаха!';
  if (streak === 20) return '👑 Легендарная серия!';
  return `👑 ${streak} подряд!`;
}

function celebrate(streak: number) {
  const winner = document.querySelector<HTMLElement>('.fact-card.correct')!;
  replayClass($('streakValue'), 'bump');
  setTier(streak);
  const milestone = streak === 5 || streak === 10 || streak === 20 || (streak > 20 && streak % 10 === 0);
  if (!recordBroken && recordToBeat && streak > recordToBeat) {
    recordBroken = true;
    toast('🏆 Новый рекорд!');
    sound.fanfare(true);
    confetti(winner, 70);
  } else if (milestone) {
    toast(milestoneText(streak));
    sound.fanfare(streak >= 10);
    confetti(winner, 45);
  } else confetti(winner, 14);
}

function showGameOver(finalStreak: number) {
  const best = recordToBeat ?? 0;
  const lastDigit = finalStreak % 10, lastTwo = finalStreak % 100;
  $('goScore').textContent = String(finalStreak);
  $('goLabel').textContent = lastDigit === 1 && lastTwo !== 11 ? 'верный подряд' : 'верных подряд';
  const record = $('goRecord');
  record.classList.toggle('record', finalStreak > best);
  if (finalStreak > best) record.textContent = best ? `🏆 Новый рекорд! Было ${best}` : '🏆 Первый рекорд!';
  else if (finalStreak === best && best) record.textContent = `Повторил рекорд ${best}`;
  else record.textContent = best ? `Рекорд ${best} · не хватило ${best + 1 - finalStreak}` : 'Первая серия впереди';
  const place = $('goPlace');
  place.hidden = true;
  $('gameOverSummary').hidden = false;
  if (!profile.authenticated || !finalStreak) return;
  void api<{ rows: Rank[] }>('/leaderboard?period=today&metric=streak').then(data => {
    const index = data.rows.findIndex(row => row.userId === profile.userId);
    if (index < 0) return;
    place.textContent = `${['🥇', '🥈', '🥉'][index] || '📊'} #${index + 1} в рейтинге дня`;
    place.hidden = false;
  }).catch(() => { /* The summary works without a rank. */ });
}

function navigate(page: string) {
  activePage = page;
  for (const name of ['play', 'leaderboard', 'profile']) $(`${name}Page`).hidden = page !== name;
  document.querySelectorAll<HTMLButtonElement>('.nav-btn').forEach(button => {
    const selected = button.dataset.page === page;
    button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  if (page === 'leaderboard') void renderLeaderboard();
  if (page === 'profile') renderProfile();
}

function timerTick() {
  if (!card || resolved) return;
  const remaining = Math.min(roundSeconds, Math.max(0, (Date.parse(card.deadline) - Date.now() - clockOffset) / 1000));
  $('seconds').textContent = String(Math.ceil(remaining));
  $('timer').classList.toggle('low', remaining <= 5);
  $('upperSand').style.transform = `scaleY(${Math.max(0.04, remaining / roundSeconds)})`;
  const low = remaining > 0 && remaining <= 5 && activePage === 'play';
  document.body.classList.toggle('tension', low);
  const second = Math.ceil(remaining);
  if (low && second !== lastTickSecond && document.visibilityState === 'visible') { lastTickSecond = second; sound.tick(second <= 2); }
  if (remaining <= 0) void submitAnswer(null);
}

function clearTimer() { if (timerId !== null) window.clearInterval(timerId); timerId = null; }

function renderCard(next: Card) {
  card = next;
  clockOffset = Date.parse(next.serverNow) - Date.now();
  resolved = false;
  gameOver = false;
  $('streakValue').textContent = String(next.streak);
  $('feedback').hidden = true;
  $('gameOverSummary').hidden = true;
  $('guestPrompt').hidden = true;
  lastTickSecond = 0;
  if (next.streak === 0 || recordToBeat === null) {
    // Stats include the open run, so after a mid-run reload best === streak means this run already holds the record.
    recordToBeat = profile.stats.best;
    recordBroken = next.streak > 0 && profile.stats.best <= next.streak;
  }
  setTier(next.streak);
  streakHint(next.streak);
  $('cards').classList.remove('resolved');
  document.querySelectorAll<HTMLButtonElement>('.fact-card').forEach((button, index) => {
    button.disabled = false;
    button.classList.remove('revealed', 'correct', 'wrong', 'chosen');
    button.querySelector<HTMLElement>('.card-text')!.textContent = next.options[index];
    button.setAttribute('aria-label', `Вариант ${index === 0 ? 'А' : 'Б'}: ${next.options[index]}`);
  });
  clearTimer();
  timerTick();
  if (!resolved) timerId = window.setInterval(timerTick, 100);
}

async function loadNext() {
  if (!questionCount) {
    setHint('Вопросы пока не загружены. Игра станет доступна после добавления набора фактов.');
    document.querySelectorAll<HTMLButtonElement>('.fact-card').forEach(button => { button.disabled = true; button.querySelector<HTMLElement>('.card-text')!.textContent = 'Скоро здесь появится вопрос'; });
    return;
  }
  try { renderCard(await api<Card>('/game/next', { method: 'POST' })); }
  catch (error) { setHint((error as Error).message); }
}

async function submitAnswer(choice: 'A' | 'B' | null) {
  if (!card || resolved) return;
  resolved = true;
  clearTimer();
  document.body.classList.remove('tension');
  // Keep the picked card lifted while the answer is checked; disabling it drops :hover.
  document.querySelectorAll<HTMLButtonElement>('.fact-card').forEach(button => { button.disabled = true; button.classList.toggle('chosen', button.dataset.side === choice); });
  try {
    const result = await api<Answer>('/game/answer', { method: 'POST', body: JSON.stringify({ roundId: card.roundId, choice }) });
    profile.stats = result.stats;
    saveGuestStats();
    gameOver = result.gameOver;
    $('streakValue').textContent = String(result.gameOver ? 0 : result.streak);
    $('cards').classList.add('resolved');
    document.querySelectorAll<HTMLButtonElement>('.fact-card').forEach(button => {
      button.classList.add('revealed');
      if (button.dataset.side === result.correctSide) button.classList.add('correct');
      else if (button.dataset.side === choice) button.classList.add('wrong');
    });
    if (result.timedOut) sound.timeout(); else if (result.correct) sound.correct(result.streak); else sound.wrong();
    if (result.correct) celebrate(result.streak);
    else { replayClass($('cards'), 'shake'); setTier(0); showGameOver(result.streak); }
    $('feedbackTitle').textContent = result.timedOut ? '⌛ Время вышло!' : result.correct ? `✨ Верно! Серия: ${result.streak}` : '💥 Не угадал!';
    $('feedbackText').textContent = result.explanation;
    $('nextButton').textContent = result.gameOver ? 'Начать новую серию ↻' : 'Следующий вопрос →';
    $('feedback').hidden = false;
    $('guestPrompt').hidden = !(result.gameOver && !profile.authenticated);
    setHint(result.correct ? 'Успеешь распознать следующий факт?' : `Лучшая серия: ${profile.stats.best}`);
  } catch (error) {
    setHint((error as Error).message);
    // A stale or duplicate round must be replaced with server state.
    await loadNext();
  }
}

async function renderLeaderboard() {
  $('leaderStatus').textContent = 'Загружаем рейтинг…';
  try {
    const data = await api<{ rows: Rank[] }>(`/leaderboard?period=${period}&metric=${metric}`);
    const host = $('leaderRows'); host.replaceChildren();
    const isStreak = metric === 'streak';
    $('leaderSubtitle').textContent = isStreak ? 'Кто смог отличить больше всего фактов подряд?' : 'У кого больше всего верных ответов в среднем за игру?';
    $('rankScoreHeading').textContent = isStreak ? 'Рекорд 🔥' : 'Фактов / игру';
    $('leaderExplainer').textContent = isStreak ? 'Самая длинная серия верных ответов подряд за выбранный период.' : 'Среднее число верных ответов за завершённую игру, включая игры с нулевым результатом.';
    $('leaderRows').setAttribute('aria-label', isStreak ? 'Рейтинг по рекорду серии' : 'Рейтинг по среднему числу ответов за игру');
    $('leaderboardResults').setAttribute('aria-labelledby', isStreak ? 'streakTab' : 'averageTab');
    $('leaderStatus').textContent = data.rows.length ? '' : 'Пока никто не занял место в рейтинге.';
    data.rows.forEach((item, index) => {
      const row = document.createElement('div');
      row.className = `rank-row${profile.userId === item.userId ? ' me' : ''}${index < 3 ? ` podium rank-${index + 1}` : ''}`;
      const rank = document.createElement('span'); rank.className = 'rank'; rank.textContent = ['🥇', '🥈', '🥉'][index] || `#${index + 1}`;
      const name = document.createElement('span'); name.className = 'rank-name';
      const icon = document.createElement('span'); icon.className = 'rank-avatar'; avatar(icon, item.avatar);
      name.append(icon, document.createTextNode(item.name));
      const score = document.createElement('span'); score.className = 'rank-score';
      score.textContent = isStreak ? `${item.best} 🔥` : item.average?.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) ?? '—';
      row.append(rank, name, score); host.append(row);
    });
  } catch (error) { $('leaderStatus').textContent = (error as Error).message; }
}

function setAuthMode(mode: 'register' | 'login') {
  authMode = mode;
  $('registerTab').classList.toggle('selected', mode === 'register');
  $('loginTab').classList.toggle('selected', mode === 'login');
  $('authSubmit').textContent = mode === 'register' ? 'Зарегистрироваться' : 'Войти';
  $<HTMLInputElement>('passwordInput').autocomplete = mode === 'register' ? 'new-password' : 'current-password';
  $('authError').textContent = '';
}

async function init() {
  try { await api('/auth/refresh', { method: 'POST' }, false); } catch { /* No saved account. */ }
  try {
    const data = await api<{ profile: Profile; questionCount: number; presets: string[] }>('/bootstrap');
    profile = data.profile;
    questionCount = data.questionCount;
    for (const name of data.presets) {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.preset = name;
      button.textContent = presetIcons[name] || '✦'; button.setAttribute('aria-label', `Аватар: ${presetNames[name] || name}`);
      button.addEventListener('click', async () => {
        try { profile = (await api<{ profile: Profile }>('/profile/avatar', { method: 'PATCH', body: JSON.stringify({ preset: name }) })).profile; renderProfile(); }
        catch (error) { $('profileSaved').textContent = (error as Error).message; }
      });
      $('avatarPresets').append(button);
    }
    renderProfile();
    await loadNext();
  } catch (error) {
    try { profile.stats = JSON.parse(localStorage.getItem(guestCacheKey) || 'null') || defaultStats; } catch { profile.stats = defaultStats; }
    renderProfile();
    setHint(`Не удалось подключиться к игре: ${(error as Error).message}`);
    document.querySelectorAll<HTMLButtonElement>('.fact-card').forEach(button => { button.disabled = true; });
  }
}

let savedTheme: string | null = null;
try { savedTheme = localStorage.getItem('factish_theme_v1'); } catch { /* Storage unavailable. */ }
setTheme(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
renderSoundToggle();
$('soundToggle').addEventListener('click', () => { setSoundEnabled(!soundEnabled()); renderSoundToggle(); });
document.addEventListener('pointerdown', unlockAudio, true);
document.addEventListener('keydown', unlockAudio, true);
$('themeToggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
$('accountButton').addEventListener('click', () => navigate('profile'));
$('homeLogo').addEventListener('click', () => navigate('play'));
document.querySelectorAll<HTMLButtonElement>('.nav-btn').forEach(button => button.addEventListener('click', () => navigate(button.dataset.page!)));
document.querySelectorAll<HTMLButtonElement>('.fact-card').forEach(button => button.addEventListener('click', () => void submitAnswer(button.dataset.side as 'A' | 'B')));
$('nextButton').addEventListener('click', () => void loadNext());
$('promptRegister').addEventListener('click', () => { setAuthMode('register'); navigate('profile'); $<HTMLInputElement>('loginInput').focus(); });
document.addEventListener('visibilitychange', timerTick);
document.addEventListener('keydown', event => {
  if (activePage !== 'play' || resolved || !card || ['INPUT', 'TEXTAREA', 'SELECT'].includes((document.activeElement?.tagName || '')) || event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
  if (event.key === '1') void submitAnswer('A'); if (event.key === '2') void submitAnswer('B');
});
document.querySelectorAll<HTMLButtonElement>('[data-metric]').forEach(button => button.addEventListener('click', () => {
  metric = button.dataset.metric!;
  document.querySelectorAll<HTMLButtonElement>('[data-metric]').forEach(tab => { const selected = tab === button; tab.classList.toggle('selected', selected); tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1; });
  void renderLeaderboard();
}));
document.querySelectorAll<HTMLButtonElement>('[data-period]').forEach(button => button.addEventListener('click', () => {
  period = button.dataset.period!;
  document.querySelectorAll<HTMLButtonElement>('[data-period]').forEach(tab => { const selected = tab === button; tab.classList.toggle('selected', selected); tab.setAttribute('aria-pressed', String(selected)); });
  void renderLeaderboard();
}));
$('registerTab').addEventListener('click', () => setAuthMode('register'));
$('loginTab').addEventListener('click', () => setAuthMode('login'));
$<HTMLFormElement>('authForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('authError').textContent = '';
  try {
    const data = await api<{ profile: Profile }>(`/auth/${authMode}`, { method: 'POST', body: JSON.stringify({ login: $<HTMLInputElement>('loginInput').value, password: $<HTMLInputElement>('passwordInput').value }) }, false);
    profile = data.profile; renderProfile(); $<HTMLInputElement>('passwordInput').value = '';
    $('guestPrompt').hidden = true;
  } catch (error) { $('authError').textContent = (error as Error).message; }
});
$('saveName').addEventListener('click', async () => {
  try { profile = (await api<{ profile: Profile }>('/profile/name', { method: 'PATCH', body: JSON.stringify({ displayName: $<HTMLInputElement>('nicknameInput').value }) })).profile; renderProfile(); }
  catch (error) { $('profileSaved').textContent = (error as Error).message; }
});
$<HTMLInputElement>('avatarUpload').addEventListener('change', async event => {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
  const body = new FormData(); body.append('image', file);
  try { profile = (await api<{ profile: Profile }>('/profile/avatar/upload', { method: 'POST', body })).profile; renderProfile(); }
  catch (error) { $('profileSaved').textContent = (error as Error).message; }
});
$('logoutButton').addEventListener('click', async () => {
  try { await api('/auth/logout', { method: 'POST' }, false); location.reload(); }
  catch (error) { $('profileSaved').textContent = (error as Error).message; }
});
void init();

// Game feedback effects: synthesized sound, vibration, confetti, shake and toasts.
const soundKey = 'factish_sound_v1';
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let context: AudioContext | null = null;
let enabled = true;
try { enabled = localStorage.getItem(soundKey) !== 'off'; } catch { /* Storage unavailable. */ }

export const soundEnabled = () => enabled;

export function setSoundEnabled(value: boolean) {
  enabled = value;
  try { localStorage.setItem(soundKey, value ? 'on' : 'off'); } catch { /* Storage unavailable. */ }
  if (value) unlockAudio();
}

// Browsers only start audio after a user gesture, so the context is resumed on the first one.
export function unlockAudio() {
  if (!enabled) return;
  try {
    context ??= new AudioContext();
    if (context.state === 'suspended') void context.resume();
  } catch { /* Web Audio unavailable. */ }
}

function tone(freq: number, start: number, duration: number, type: OscillatorType = 'triangle', volume = 0.12, slideTo?: number) {
  if (!enabled || !context || context.state !== 'running') return;
  const at = context.currentTime + start;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(freq, at);
  if (slideTo) oscillator.frequency.exponentialRampToValueAtTime(slideTo, at + duration);
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(volume, at + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + duration);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(at);
  oscillator.stop(at + duration + 0.02);
}

function vibrate(pattern: number | number[]) {
  if (!enabled) return;
  try { navigator.vibrate?.(pattern); } catch { /* Vibration unavailable. */ }
}

const semitone = (base: number, steps: number) => base * 2 ** (steps / 12);

export const sound = {
  tick(last: boolean) { tone(last ? 1320 : 990, 0, 0.05, 'square', 0.035); },
  // Each streak step raises the chime by a semitone, capped at one octave.
  correct(streak: number) {
    const base = semitone(523, Math.min(streak, 12));
    tone(base, 0, 0.16); tone(semitone(base, 4), 0.07, 0.16); tone(semitone(base, 7), 0.14, 0.26);
    vibrate(30);
  },
  wrong() { tone(233, 0, 0.42, 'sawtooth', 0.07, 98); tone(175, 0.05, 0.4, 'square', 0.03, 82); vibrate([70, 50, 90]); },
  timeout() { tone(392, 0, 0.14, 'square', 0.05); tone(262, 0.18, 0.34, 'square', 0.05, 196); vibrate([120, 60, 120]); },
  fanfare(big: boolean) {
    const notes = big ? [0, 4, 7, 12, 16, 19, 24] : [0, 4, 7, 12];
    notes.forEach((step, index) => tone(semitone(523, step), 0.22 + index * 0.08, 0.3, 'triangle', 0.1));
    vibrate(big ? [40, 40, 40, 40, 120] : [40, 40, 80]);
  },
};

const confettiColors = ['#54ea83', '#bfa5ff', '#ff9f3b', '#ffd35c', '#6fd3ff', '#ff7a9a'];

export function confetti(origin: HTMLElement, amount: number) {
  if (reducedMotion.matches) return;
  const layer = document.getElementById('fxLayer');
  if (!layer) return;
  const rect = origin.getBoundingClientRect();
  for (let i = 0; i < amount; i++) {
    const piece = document.createElement('span');
    piece.className = 'confetti';
    const angle = Math.random() * Math.PI * 2;
    const distance = 90 + Math.random() * (140 + amount * 3);
    piece.style.left = `${rect.left + rect.width * (0.2 + Math.random() * 0.6)}px`;
    piece.style.top = `${rect.top + rect.height * 0.35}px`;
    piece.style.setProperty('--dx', `${Math.cos(angle) * distance}px`);
    piece.style.setProperty('--dy', `${Math.sin(angle) * distance * 0.6 - 60}px`);
    piece.style.setProperty('--spin', `${(Math.random() - 0.5) * 900}deg`);
    piece.style.background = confettiColors[i % confettiColors.length];
    piece.style.animationDelay = `${Math.random() * 90}ms`;
    piece.addEventListener('animationend', () => piece.remove(), { once: true });
    layer.append(piece);
  }
}

// Restarts a one-shot CSS animation class even if it is already applied.
export function replayClass(element: HTMLElement, name: string) {
  element.classList.remove(name);
  void element.offsetWidth;
  element.classList.add(name);
  element.addEventListener('animationend', () => element.classList.remove(name), { once: true });
}

let toastTimer: number | null = null;

export function toast(text: string) {
  const element = document.getElementById('streakToast');
  if (!element) return;
  element.textContent = text;
  element.hidden = false;
  replayClass(element, 'show');
  if (toastTimer !== null) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { element.hidden = true; }, 2200);
}

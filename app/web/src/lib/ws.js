// Shared WebSocket client. The server is the single source of truth:
// every view renders from the latest `state` snapshot and `tick`.
import { writable } from 'svelte/store';

export const state = writable({ state: 'idle', advance_mode: 'both' });
export const tick = writable(null);
export const connected = writable(false);
// rolling event log for the control panel (markers, rejections, endings)
export const events = writable([]);

let ws = null;

function log(entry) {
  const t = new Date().toLocaleTimeString();
  events.update((l) => [...l.slice(-199), { t, ...entry }]);
}

export function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => connected.set(true);
  ws.onclose = () => {
    connected.set(false);
    setTimeout(connect, 1000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    switch (msg.type) {
      case 'state':
        state.set(msg);
        if (msg.state !== 'rest_pre' && msg.state !== 'rest_post') tick.set(null);
        break;
      case 'tick':
        tick.set(msg);
        break;
      case 'marker':
        log({ kind: 'marker', text: `marker ${msg.code} ${msg.name}` });
        break;
      case 'command_rejected':
        log({ kind: 'rejected', text: `${msg.command} rejected: ${msg.reason}` });
        break;
      case 'rejected':
        log({ kind: 'rejected', text: `${msg.cmd} rejected: ${msg.reason}` });
        break;
      case 'dnf_flagged':
        log({ kind: 'dnf', text: `trial ${msg.trial} flagged DNF` });
        break;
      case 'session_ended':
        log({
          kind: 'ended',
          text: msg.error
            ? `session ended with error: ${msg.error}`
            : msg.completed
              ? 'session completed'
              : 'session aborted',
        });
        break;
      case 'error':
        log({ kind: 'error', text: msg.reason });
        break;
    }
  };
}

export function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

export function advance(fromState, source = 'experimenter') {
  send({ cmd: 'advance', from_state: fromState, source });
}
